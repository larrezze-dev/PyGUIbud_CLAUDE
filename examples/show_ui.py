"""Show any ``.ui`` file with a chosen toolkit backend, handlers doing nothing.

Usage: ``python examples/show_ui.py FILE [--backend NAME] [--lang CODE]``

A document with dialogs only is shown on a hidden root: every dialog opens, and closing the last
one ends the program.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from pyguibud_runtime import UiError, load_ui


class _NoOps(Mapping[str, Callable[[], None]]):
    """Every handler name resolves to a function that does nothing."""

    def __getitem__(self, name: str) -> Callable[[], None]:
        return lambda: None

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def _hidden_root(backend: str) -> Any:  # noqa: ANN401 - a toolkit root
    """The ``master`` of a document without a main window (Tk-based backends: a withdrawn Tk).

    Step 16b: ``pyside6`` gets a hidden parentless ``QWidget`` here, as its preview host does.
    """
    import tkinter

    try:
        root = tkinter.Tk()
    except tkinter.TclError as exc:  # no display
        raise RuntimeError(str(exc)) from exc
    root.withdraw()
    return root


def _show_dialogs(ui: Any, root: Any) -> None:  # noqa: ANN401 - a LoadedUi and a Tk root
    """Show every dialog; closing the last one ends the main loop (Tk; Qt joins in 16b)."""
    left = set(ui.windows)

    def closed(window_id: str) -> None:
        ui.windows[window_id].withdraw()
        left.discard(window_id)
        if not left:
            root.destroy()

    for window_id, top in ui.windows.items():
        top.transient("")  # a transient of the withdrawn root would stay hidden
        top.protocol("WM_DELETE_WINDOW", lambda w=window_id: closed(w))
        ui.show(window_id)


def load(file: str, backend: str, lang: str | None) -> Any:  # noqa: ANN401 - a LoadedUi
    """Load ``file``; a document with dialogs only gets a hidden root and shows them all.

    Raises:
        UiError, ValueError, RuntimeError: the file, the backend or ``lang`` cannot be used.
    """
    options: dict[str, Any] = {"strict": False, "backend": backend, "lang": lang}
    try:
        return load_ui(file, _NoOps(), **options)
    except UiError as exc:
        if exc.code != "runtime.no_main_window":
            raise
    root = _hidden_root(backend)
    try:
        ui = load_ui(file, _NoOps(), master=root, **options)
    except BaseException:
        root.destroy()
        raise
    _show_dialogs(ui, root)
    return ui


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file")
    parser.add_argument("--backend", default="ttkbootstrap")
    parser.add_argument("--lang")
    args = parser.parse_args()
    try:
        ui = load(args.file, args.backend, args.lang)
    except (UiError, ValueError, RuntimeError) as exc:  # one line, no traceback
        print(exc, file=sys.stderr)
        return 1
    ui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
