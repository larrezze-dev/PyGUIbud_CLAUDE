"""The preview child process: ``python -m pyguibud.preview [options] [--] FILE`` (ADR-013).

It shows a ``.ui`` file with ``pyguibud_runtime.load_ui``, the path users ship, with no-op
handlers (D8). It may import the runtime, ``pyguibud.core``, ``pyguibud.i18n`` and
``pyguibud.backends``, never the designer, the CLI, ``uic`` or codegen; the toolkit is imported
only inside :func:`run`. The designer controls it through stdin (``lang CODE|-``, ``raise``,
``quit``; end of input = quit; trim T4: a theme change restarts the child) and reads
``ready.json`` and ``result.json``, which are written atomically into the current folder.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import sys
import threading
import traceback
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

from pyguibud.backends import BACKEND_NAME
from pyguibud.i18n import LANGUAGE_CODE_RE, N_, _, set_language

__all__ = ["BACKEND_RE", "READY", "RESULT", "STDERR", "NoHandlers", "run"]

READY, RESULT, STDERR = "ready.json", "result.json", "stderr.txt"
BACKEND_RE = BACKEND_NAME  # the one backend-name rule; host_for refuses any other name (D16)
_MAX_LINE = 256  # bytes of one stdin command
_POLL_MS = 50
_MAX_WARNINGS = 20
_MAX_MESSAGE = 2000
#: The JSON size of the kept warnings: ready.json (ASCII, so a character may take 12 bytes)
#: stays under the designer's 64 KiB read limit with the themes (QA-16c-04).
_MAX_WARNING_BYTES = 40 * 1024
_CRASH = 3
_M_DESCRIPTION = N_("Show a .ui file in a separate preview window (used by the designer).")


def _noop() -> None:
    """A handler that does nothing (D8)."""


class NoHandlers(Mapping[str, Callable[[], None]]):
    """Every handler name resolves to a no-op, also those of included files (D8).

    The runtime and generated modules bind commands, keys and menus only for resolved handlers,
    so the parity tests pass this same mapping to the generated module.
    """

    def __getitem__(self, name: str) -> Callable[[], None]:
        if not isinstance(name, str):
            raise KeyError(name)
        return _noop

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def _code(value: str) -> str:
    if not LANGUAGE_CODE_RE.fullmatch(value):
        raise argparse.ArgumentTypeError(value)
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pyguibud.preview", description=_(_M_DESCRIPTION))
    parser.add_argument("--ui-lang", type=_code, metavar="CODE")
    parser.add_argument("--lang", type=_code, metavar="CODE")
    parser.add_argument("--theme", metavar="NAME")
    parser.add_argument("--window", metavar="ID")
    parser.add_argument("--localedir", metavar="DIR")
    parser.add_argument("--backend", metavar="NAME", default="ttkbootstrap")  # see host_for
    parser.add_argument("--describe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--portable", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-plugins", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--disable-plugins", metavar="NAME,...", help=argparse.SUPPRESS)
    parser.add_argument("file", metavar="FILE")
    return parser


def _configure_plugins(args: argparse.Namespace) -> None:
    """Apply the designer's plugin filter before anything builds the default registry."""
    from pyguibud.core import configure_default_registry

    if args.no_plugins:
        configure_default_registry("all")
    elif names := tuple(n.strip() for n in (args.disable_plugins or "").split(",") if n.strip()):
        configure_default_registry(names)


def _write(path: Path, data: dict[str, Any]) -> None:
    """Replace ``path`` atomically: the designer never reads half a file."""
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(data), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:  # the designer removed the folder: nobody reads it any more
        logging.getLogger(__name__).warning("%s not written", path, exc_info=True)


class _Collect(logging.Handler):
    """Keeps the runtime's warnings (the handler-free log records) for ``ready.json``."""

    def __init__(self) -> None:
        super().__init__(logging.WARNING)
        self.messages: list[str] = []
        self._room = _MAX_WARNING_BYTES

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()[:_MAX_MESSAGE]
        size = len(json.dumps(message))  # as ready.json stores it (one message always fits)
        if len(self.messages) < _MAX_WARNINGS and size <= self._room:
            self.messages.append(message)
            self._room -= size


def _read_commands(commands: queue.Queue[str]) -> None:
    """The stdin thread: queue each command line; only the Tk thread acts on them.

    Raw ``os.read``: a daemon thread blocked inside a buffered ``readline`` aborts the
    interpreter at exit ("could not acquire lock for <stdin>").
    """
    buffer, skipping = b"", False
    try:
        fd = sys.stdin.fileno() if sys.stdin is not None else -1
        while fd >= 0 and (chunk := os.read(fd, 4096)):
            *lines, buffer = (buffer + chunk).split(b"\n")
            for line in lines:
                if not skipping and len(line) <= _MAX_LINE:
                    commands.put(line.decode("utf-8", "replace").strip())
                skipping = False
            if len(buffer) > _MAX_LINE:  # an over-long line is ignored up to its end
                buffer, skipping = b"", True
    except (OSError, ValueError):
        logging.getLogger(__name__).debug("stdin closed", exc_info=True)
    commands.put("quit")


class _Child:
    def __init__(self, args: argparse.Namespace, folder: Path) -> None:
        from pyguibud.preview._host import host_for

        self.args, self.folder = args, folder
        self.host = host_for(args.backend)
        self.commands: queue.Queue[str] = queue.Queue()
        self.collect = _Collect()
        self.ui: Any = None
        self.source = "en_GB"

    def start(self) -> int:
        from pyguibud.core.errors import XmlIoError
        from pyguibud.core.xml_io import read_ui
        from pyguibud_runtime import load_ui

        args = self.args
        logging.getLogger("pyguibud_runtime").addHandler(self.collect)
        try:  # only to choose the root; load_ui reports a broken file with its own code
            document = read_ui(args.file).document
        except (XmlIoError, OSError):
            document = None
        mains = [w.id for w in document.children if w.kind == "main"] if document else []
        main = mains[0] if mains else None
        if document is not None:
            self.source = document.meta.source_locale or "en_GB"
        theme = document.meta.theme if document is not None else ""
        master = self.host.prepare(main is not None or document is None, theme)
        self.ui = load_ui(
            args.file,
            NoHandlers(),
            strict=False,
            backend=args.backend,
            master=master,
            lang=args.lang,
            localedir=args.localedir,
        )
        if args.theme:
            self.host.set_theme(args.theme)
        window = args.window if args.window in self.ui.windows else None
        self.host.attach(self.ui, main, window, self.quit)
        if args.describe:
            from pyguibud.preview._describe import describe, portable_describe

            self.host.update()
            view = (portable_describe if args.portable else describe)(self.ui, args.backend)
            print(json.dumps(view, sort_keys=True))
            self._ready()
            self.host.close()
            return 0
        self.host.schedule(0, self._ready)
        threading.Thread(target=_read_commands, args=(self.commands,), daemon=True).start()
        self.host.schedule(_POLL_MS, self._poll)
        self.host.run()
        _write(self.folder / RESULT, {"code": "ok", "message": ""})
        return 0

    def _ready(self) -> None:
        data = {
            "themes": self.host.themes(),
            "theme": self.host.current_theme(),
            "warnings": [{"code": "runtime", "message": m} for m in self.collect.messages],
            "pid": os.getpid(),
        }
        _write(self.folder / READY, data)

    def _poll(self) -> None:
        while not self.commands.empty():
            verb, _sep, arg = self.commands.get().partition(" ")
            if verb == "quit":
                self.quit()
                return
            try:
                if verb == "lang" and (arg == "-" or LANGUAGE_CODE_RE.fullmatch(arg)):
                    self.ui.retranslate(self.source if arg == "-" else arg)
                elif verb == "raise":
                    self.host.lift()
            except Exception:  # a failed switch keeps the preview open; the reason is logged
                logging.getLogger(__name__).exception("The command %r failed", verb)
        self.host.schedule(_POLL_MS, self._poll)

    def quit(self) -> None:
        self.host.close()


def run(argv: list[str] | None = None) -> int:
    """Run the child; 0 = closed, 1 = a ``UiError``, 2 = usage, 3 = a crash (spec 4.2)."""
    from pyguibud_runtime import UiError

    args = _parser().parse_args(argv)
    _configure_plugins(args)
    if args.ui_lang:
        try:
            set_language(args.ui_lang)
        except ValueError:
            logging.getLogger(__name__).warning("Unknown interface language %s", args.ui_lang)
    folder = Path.cwd()
    try:
        return _Child(args, folder).start()
    except UiError as exc:
        message = str(exc)
        print(message, file=sys.stderr)
        _write(folder / RESULT, {"code": exc.code, "message": message[:_MAX_MESSAGE]})
        return 1
    except BaseException as exc:  # a plugin's SystemExit, a Tk failure: reported, not raised
        traceback.print_exc()
        _write(folder / RESULT, {"code": "crash", "message": repr(exc)[:_MAX_MESSAGE]})
        return _CRASH
