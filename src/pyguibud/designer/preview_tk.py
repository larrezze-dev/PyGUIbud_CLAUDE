"""Preview > Preview (F5): the child process seen from the Tk designer (spec preview-export 4.3).

:class:`PreviewRunner` owns one ``python -m pyguibud.preview`` process: ``Popen`` (argv only, no
shell), ``after()`` polling (never a blocking wait on the main thread), stdin commands, quit ->
terminate -> kill, and the private folder. :class:`PreviewController` is what the menus call.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any, Literal

from pyguibud.core.atomic import make_temp_dir
from pyguibud.core.commands import SetField
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.model import Window
from pyguibud.designer import preview as pv
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.settings import DEFAULT_BACKEND, Settings
from pyguibud.i18n import PSEUDO_LANGUAGE, _, get_language
from pyguibud.preview import READY, RESULT, STDERR

__all__ = ["PreviewController", "PreviewRunner", "private_folder", "python_missing", "sweep_stale"]

_log = logging.getLogger(__name__)
POLL_MS = 200
_TIMEOUT_POLLS = 20_000 // POLL_MS  # "did not start within 20 seconds"
_PREFIX = "pyguibud-preview-"
_STALE_SECONDS = 24 * 3600
#: ``pyguibud-preview-[run-]<pid>-<8 hex>``: the designer that made the folder (QA-15a-06).
_OWNED = re.compile(r"(?:run-)?([0-9]{1,10})-[0-9a-f]{8}")
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
#: Designer Quit waits at most 1 s in all: ``_QUIT_SECONDS`` for the child to quit by itself,
#: then ``_END_SECONDS`` for a terminated child to end and release its open files.
_QUIT_SECONDS = 0.7
_END_SECONDS = 0.3
_REMOVE_RETRY_SECONDS = 0.05


def _remove(folder: Path | None) -> None:
    if folder is not None:
        shutil.rmtree(folder, ignore_errors=True)  # a live child's open files keep it (Windows)


def python_missing(error: OSError, folder: Path) -> bool:
    """A start failed because the interpreter is gone (a deleted venv): a file is missing
    although the private ``folder`` is there (QA-19g-08). Ask before removing ``folder``."""
    return isinstance(error, FileNotFoundError) and folder.is_dir()


def private_folder(kind: str = "") -> Path:
    """A new private folder ``pyguibud-preview-<kind><pid>-<8 hex>`` in the temporary folder.

    Raises:
        OSError: it cannot be created (a denied temporary folder fails at once, QA-15b-13).
    """
    return make_temp_dir(f"{_PREFIX}{kind}{os.getpid()}-")


def _alive(pid: int) -> bool:
    """False only when no process ``pid`` runs; a reused pid merely keeps a folder longer."""
    if not 0 < pid < 2**31 or pid == os.getpid():
        return True  # ours, or no pid a designer wrote (a forged name): keep the folder
    if sys.platform == "win32":
        import ctypes  # Windows only
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such process
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    else:
        try:
            os.kill(pid, 0)  # POSIX only: on Windows this would terminate the process
        except ProcessLookupError:
            return False
        except OSError:  # PermissionError: it runs as another user
            return True
        return True


def sweep_stale(base: Path | None = None) -> None:
    """Remove private folders left by a crashed designer more than 24 hours ago (P3).

    A folder whose name carries the pid of a designer that still runs is kept, however old.
    """
    limit = time.time() - _STALE_SECONDS
    with contextlib.suppress(OSError):
        for folder in Path(base or tempfile.gettempdir()).glob(_PREFIX + "*"):
            with contextlib.suppress(OSError, ValueError):
                if not folder.is_dir() or folder.stat().st_mtime >= limit:
                    continue
                owner = _OWNED.fullmatch(folder.name[len(_PREFIX) :])
                if owner is None or not _alive(int(owner.group(1))):
                    _remove(folder)


class PreviewRunner:
    """One child at a time; ``on_ready(themes)`` and ``on_exit(code, result, tail, timed_out)``."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the designer's Tk root
        on_ready: Callable[[list[str]], None],
        on_exit: Callable[[int, tuple[str, str], str, bool], None],
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.root, self.on_ready, self.on_exit, self.popen = root, on_ready, on_exit, popen
        self.process: Any = None
        self.folder: Path | None = None
        self.after_ids: dict[str, str] = {}
        self._polls, self._ready, self._timed_out = 0, False, False
        self.warnings: list[str] = []  # what the child reported with its ready.json

    def start(
        self, argv: list[str], folder: Path, *, cwd: Path | None = None, wait_ready: bool = True
    ) -> None:
        """Start the child in ``cwd`` (default ``folder``, the private folder deleted at its
        end); OSError when it cannot be started. ``wait_ready`` False: no 20 s start limit (a
        program that writes no ``ready.json``, e.g. an exported module)."""
        with (folder / STDERR).open("wb") as stderr:  # the child keeps its own handle
            self.process = self.popen(
                argv,
                cwd=cwd or folder,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=stderr,
                close_fds=True,
                creationflags=_NO_WINDOW,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"},
            )
        self.folder, self._polls, self._ready, self._timed_out = folder, 0, not wait_ready, False
        self.warnings = []
        self._later("poll", POLL_MS, self._poll)

    def send(self, line: str) -> None:
        """One stdin command; a child that has gone already is not an error."""
        stdin = getattr(self.process, "stdin", None)
        try:
            if stdin is not None:
                stdin.write(f"{line}\n".encode())
                stdin.flush()
        except (OSError, ValueError):
            _log.debug("The preview did not take %r", line, exc_info=True)

    def stop(self) -> None:
        """Ask the child to quit; terminate it after 2 s and kill it after 4 s (P4)."""
        self.send("quit")
        self._later("terminate", 2000, lambda: self._signal("terminate"))
        self._later("kill", 4000, lambda: self._signal("kill"))

    def dispose(self) -> None:
        """Designer Quit: end of stdin (the child quits), at most 1 s of waiting, then delete.

        A child still running is terminated and then awaited too: Windows ends a terminated
        process asynchronously, and until it has ended its open ``stderr.txt`` keeps the private
        folder from being deleted (QA-15b-05).
        """
        start = time.monotonic()
        self._cancel()
        process, self.process = self.process, None
        folder, self.folder = self.folder, None
        if process is not None:
            with contextlib.suppress(OSError, ValueError, AttributeError):
                process.stdin.close()
            try:
                process.wait(timeout=_QUIT_SECONDS)
            except subprocess.TimeoutExpired:
                with contextlib.suppress(OSError):
                    process.terminate()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=_END_SECONDS)
        _remove(folder)
        # A virus scanner may still hold the just-closed stderr.txt: retry within the budget.
        while folder is not None and folder.exists():
            if time.monotonic() - start + _REMOVE_RETRY_SECONDS > _QUIT_SECONDS + _END_SECONDS:
                break
            time.sleep(_REMOVE_RETRY_SECONDS)
            _remove(folder)

    def _later(self, name: str, ms: int, fn: Callable[[], None]) -> None:
        def run() -> None:
            self.after_ids.pop(name, None)
            fn()

        if name in self.after_ids:  # one timer per name: a direct _poll() replaces the next
            self.root.after_cancel(self.after_ids[name])
        self.after_ids[name] = self.root.after(ms, run)

    def _cancel(self) -> None:
        for after_id in self.after_ids.values():
            with contextlib.suppress(Exception):  # the root may be gone at Quit
                self.root.after_cancel(after_id)
        self.after_ids.clear()

    def _signal(self, how: str) -> None:
        if self.process is not None and self.process.poll() is None:
            with contextlib.suppress(OSError):
                getattr(self.process, how)()

    def _poll(self) -> None:
        process, folder = self.process, self.folder
        if process is None or folder is None:
            return
        code = process.poll()
        if code is not None:
            self._cancel()
            with contextlib.suppress(OSError, ValueError, AttributeError):
                process.stdin.close()
            self.process, self.folder = None, None
            result, tail = pv.read_result(folder / RESULT), pv.stderr_tail(folder / STDERR)
            _remove(folder)
            self.on_exit(int(code), result, tail, self._timed_out)
            return
        self._polls += 1
        if not self._ready and (themes := pv.read_ready(folder / READY)) is not None:
            self._ready = True
            self.warnings = pv.read_warnings(folder / READY)
            self.on_ready(themes)
        elif not self._ready and self._polls >= _TIMEOUT_POLLS and not self._timed_out:
            self._timed_out = True
            self._signal("terminate")
        self._later("poll", POLL_MS, self._poll)


_GROUP_LABELS = (pv.M_THEMES_LIGHT, pv.M_THEMES_DARK, pv.M_THEMES_OTHER)


def group_themes(names: Collection[str]) -> dict[str, list[str]]:
    """Split theme names into ``light``, ``dark`` and ``other`` by ttkbootstrap's theme type (or
    the designer's own SAPE modes); the order of ``names`` is kept inside a group (H89)."""
    from ttkbootstrap.themes.standard import STANDARD_THEMES

    from pyguibud.designer.theme import load_theme_specs

    kinds = {spec.name: spec.mode for spec in load_theme_specs()}
    groups: dict[str, list[str]] = {"light": [], "dark": [], "other": []}
    for name in names:
        kind = kinds.get(name) or STANDARD_THEMES.get(name, {}).get("type")
        groups[kind if kind in ("light", "dark") else "other"].append(name)
    return groups


class PreviewController:
    """The Preview menu: F5 (with one pending restart), Shift+F5, Language, Theme (D4-D7)."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the designer's Tk root
        session: DesignerSession,
        settings: Settings,
        *,
        post: Callable[[str], None],
        tell: Callable[[str], None],
        save_settings: Callable[[], None],
        current_window: Callable[[], object | None],
        toolkits: Callable[[], tuple[str, ...]],
        plugins: Collection[str] | Literal["all"] = (),
    ) -> None:
        self.root, self.session, self.settings = root, session, settings
        self.plugins = plugins  # the designer's start-up filter, not the edited settings
        self.toolkits = toolkits  # the listed backend names (Preview > Toolkit)
        self.post, self.tell, self.save_settings = post, tell, save_settings
        self.current_window = current_window
        self.state = pv.PreviewState()
        self.runner = PreviewRunner(root, self._ready, self._exited)
        self.theme: str | None = None  # the preview-only theme override (D7)
        self.themes: list[str] = []  # as the last child reported them
        self.current: pv.PreparedPreview | None = None
        self._next: tuple[pv.PreparedPreview, Path] | None = None
        self._var: Any = None
        self._stopped = False  # the user (or a document change) asked the child to quit
        self._differs = False  # the theme shown differs from the document's (QA-15a-05)
        self._told: str | None = None  # the missing toolkit the status bar already named
        self._disconnects = (
            session.document_changed.connect(lambda _s: self._replaced()),
            session.report_changed.connect(lambda _r: self._theme_changed()),
        )

    @property
    def running(self) -> bool:
        return self.state.phase != "idle"

    def run(self) -> None:
        """F5: prepare now (refusals are immediate), then start or restart the single child."""
        session, document = self.session, self.session.document
        if document is None or session.stack is None:
            return
        if not document.children:
            self.post(_(pv.M_NO_WINDOW))
            return
        if not sys.executable:
            self.post(_(pv.M_NO_PYTHON))
            return
        window = self.current_window()
        window_id = window.id if isinstance(window, Window) else document.children[0].id
        try:
            folder = private_folder()
        except OSError as exc:
            self.post(_(pv.M_TEMP).format(reason=exc.strerror or exc))
            return
        request = pv.PreviewRequest(
            document, session.path, session.dirty, session.stack.read_only, window_id,
            self.settings.preview_lang, self._theme_override(), session.stamp, self.toolkit(),
        )  # fmt: skip
        try:  # QA-15a-02: whatever happens, a refused or failed preview leaves no folder
            findings = pv.preview_findings(document, session.registry, session.path, folder)
            prepared = pv.prepare_preview(request, folder, findings)
            if isinstance(prepared, pv.PreparedPreview) and prepared.snapshot is not None:
                (folder / pv.SNAPSHOT).write_bytes(prepared.snapshot)
        except OSError as exc:
            prepared = pv.Refusal(_(pv.M_TEMP).format(reason=exc.strerror or exc))
        except BaseException:
            _remove(folder)
            raise
        if isinstance(prepared, pv.Refusal):
            _remove(folder)
            self.post(prepared.message)
            return
        self._drop_next()
        self._next = (prepared, folder)
        action = self.state.start()
        if action == "spawn":
            self._spawn()
        elif action == "quit":
            self.runner.stop()

    def _spawn(self) -> None:
        if self._next is None:
            self.state.exited()
            return
        (prepared, folder), self._next = self._next, None
        lang = self.settings.preview_lang
        argv = pv.child_argv(prepared, folder, ui_lang=get_language(), lang=lang,
                             theme=self._theme_override(), backend=self.toolkit(),
                             plugins=self.plugins)  # fmt: skip
        try:
            self.runner.start(argv, folder)
        except OSError as exc:
            gone = python_missing(exc, folder)
            _remove(folder)
            self.state.exited()
            self.post(
                _(pv.M_NO_PYTHON) if gone else _(pv.M_TEMP).format(reason=exc.strerror or exc)
            )
            return
        self.current, self._stopped = prepared, False
        self._differs = self._theme_differs()
        self.post(_(pv.M_STARTING))

    def close(self) -> None:
        """Shift+F5, and whenever the document is replaced or closed."""
        self._drop_next()
        if self.state.stop():
            self._stopped = True
            self.runner.stop()

    def _replaced(self) -> None:
        """Another document (or none): close the preview and forget its theme (QA-15a-04)."""
        self.theme = None
        self.close()

    def _theme_differs(self) -> bool:
        document = self.session.document
        return (
            bool(self._theme_override())
            and document is not None
            and document.meta.theme != self.theme
        )

    def _theme_changed(self) -> None:
        """Re-judge "differs from the export" when the document theme changes (QA-15a-05)."""
        differs = self._theme_differs()
        if differs != self._differs and self.state.phase == "running" and self.current:
            self._status([_(pv.M_OPEN).format(window=self.current.window_id)])
        self._differs = differs

    def _drop_next(self) -> None:
        if self._next is not None:
            _remove(self._next[1])
            self._next = None

    def _ready(self, themes: list[str]) -> None:
        self.state.ready()
        self.themes = themes
        if self.current is not None:
            note = pv.warning_note(self.runner.warnings)  # before the long handlers hint (elision)
            parts = [_(pv.M_OPEN).format(window=self.current.window_id), note, _(pv.M_HANDLERS)]
            self._status([p for p in parts if p])

    def _status(self, parts: list[str]) -> None:
        """Post ``parts`` plus the differences from the export and the missing catalogue (D6)."""
        current, document = self.current, self.session.document
        if current is None or document is None:
            return
        lang = self.settings.preview_lang
        reasons = [r for r in current.differences if r not in (pv.R_THEME, pv.R_PSEUDO)]
        reasons += [pv.R_THEME] if self._theme_differs() else []
        if (saved := self.settings.preview_backend) != self.toolkit() and self._told != saved:
            self._told = saved  # once per missing toolkit (spec backends D17)
            parts.append(pv.not_installed_text(saved))
        reasons += [pv.R_PSEUDO] if lang == PSEUDO_LANGUAGE else []
        parts += [_(pv.M_DIFFERS).format(reason=pv.reason_text(r)) for r in reasons]
        path = self.session.path
        folder = current.localedir or (path.parent / "locale" if path is not None else None)
        if note := pv.catalogue_note(document, folder, lang):
            parts.append(note)
        if parts:
            self.post(" ".join(parts))

    def _exited(self, code: int, result: tuple[str, str], tail: str, timed_out: bool) -> None:
        self.current = None
        if self.state.exited():
            self._spawn()
        elif timed_out:
            qt = self.toolkit() == "pyside6"
            message = pv.M_TIMEOUT_QT if qt else pv.M_TIMEOUT
            self.post(_(message).format(variable="QT_QPA_PLATFORM"))
        elif result[0] == "ok" or self._stopped:  # QA-15a-03: a stop the user asked for
            self.post(_(pv.M_CLOSED))
        elif result[0] != "crash" and code == 1:
            self.post(result[1])  # the runtime's own (translated) reason, e.g. no display
        else:
            self.tell("\n\n".join(t for t in (_(pv.M_CRASHED).format(code=code), tail) if t))

    def set_language(self, code: str | None) -> None:
        """Preview > Language: remembered, and switched live in a running preview (D6)."""
        self.settings.preview_lang = code
        self.save_settings()
        if self.state.phase in ("starting", "running"):  # the child reads stdin from the start
            self.runner.send(f"lang {code or '-'}")
            self._status([])

    def set_theme(self, name: str | None) -> None:
        """Preview > Theme: a preview-only override (D7), None = the document's. Trim T4: no
        live switch, a running preview restarts with ``--theme``."""
        self.theme = name
        if self.running:
            self.run()

    def toolkit(self) -> str:
        """The toolkit the preview uses: the saved one, or ttkbootstrap while it is not listed
        or not installed (the setting itself is kept, spec backends D17)."""
        saved = self.settings.preview_backend
        return saved if self._usable(saved) else DEFAULT_BACKEND

    def _usable(self, name: str) -> bool:
        return name in self.toolkits() and pv.toolkit_installed(name)

    def installed(self, name: str) -> bool:
        return pv.toolkit_installed(name)

    def set_toolkit(self, name: str) -> None:
        """Preview > Toolkit: remembered; a running preview restarts with ``--backend``."""
        if not self._usable(name):  # the listed names all have the backend-name grammar
            return
        self.settings.preview_backend = name
        self.save_settings()
        if self.running:
            self.run()

    def _theme_override(self) -> str | None:
        """The preview-only theme, which only ttkbootstrap has (other hosts list none)."""
        return self.theme if self.toolkit() == DEFAULT_BACKEND else None

    def can_use_theme(self) -> bool:
        stack, document = self.session.stack, self.session.document
        return (
            bool(self._theme_override())
            and stack is not None
            and not stack.read_only
            and (document is not None and document.meta.theme != self.theme)
        )

    def use_theme(self) -> None:
        """Preview > Use this theme in the document: one undoable step (D7)."""
        stack, document = self.session.stack, self.session.document
        if stack is None or document is None or not self.can_use_theme():
            return
        outcome = stack.execute(SetField(document.meta, "theme", self.theme))
        if not outcome.accepted:  # the override stays: Ctrl+Z makes it differ again (QA-15a-05)
            self.post(outcome.message)

    def fill_theme_menu(self, menu: Any) -> None:  # noqa: ANN401 - a tkinter.Menu
        """The postcommand of Preview > Theme: "Document theme" and the reported names."""
        import tkinter

        if self._var is None:
            self._var = tkinter.StringVar(menu)
        self._var.set(self.theme or "")
        ready = self.state.phase == "running" and self.toolkit() == DEFAULT_BACKEND
        state = "normal" if ready else "disabled"
        menu.delete(0, "end")
        for old in menu.winfo_children():  # the group cascades of the last post (QA-19f-04)
            old.destroy()

        def add(target: Any, value: str, label: str) -> None:  # noqa: ANN401 - a tkinter.Menu
            target.add_radiobutton(label=label, value=value, variable=self._var, state=state,
                                   command=lambda: self.set_theme(value or None))  # fmt: skip

        add(menu, "", _(pv.M_DOCUMENT_THEME))
        groups = group_themes(self.themes)
        if any(groups.values()):
            menu.add_separator()
        for key, names in zip(_GROUP_LABELS, groups.values(), strict=True):
            if not names:
                continue
            text, underline = split_mnemonic(_(key))
            sub = tkinter.Menu(menu, tearoff=False)
            menu.add_cascade(label=text, underline=underline, menu=sub, state=state)
            for name in names:
                add(sub, name, name)

    def dispose(self) -> None:
        for disconnect in self._disconnects:
            disconnect()
        self._drop_next()
        self.runner.dispose()
