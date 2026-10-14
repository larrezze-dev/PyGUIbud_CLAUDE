"""Show any ``.ui`` file with a chosen toolkit backend, handlers doing nothing.

Usage: ``python examples/show_ui.py FILE [--backend NAME] [--lang CODE]``

A document with dialogs only is shown on a hidden root: every dialog opens, and closing the last
one ends the program.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Iterator, Mapping
from typing import Any

from pyguibud_runtime import UiError, load_ui

#: The QApplication of a dialog-only document (pyside6), quit when its last dialog closes.
_QT_LOOP: list[Any] = []


class _NoOps(Mapping[str, Callable[[], None]]):
    """Every handler name resolves to a function that does nothing."""

    def __getitem__(self, name: str) -> Callable[[], None]:
        return lambda: None

    def __iter__(self) -> Iterator[str]:
        return iter(())

    def __len__(self) -> int:
        return 0


def _hidden_root(backend: str, file: str) -> Any:  # noqa: ANN401 - a toolkit root
    """The ``master`` of a document without a main window: a withdrawn Tk root, or a hidden
    parentless ``QWidget`` for ``pyside6``. ttkbootstrap's root gets the document's theme
    (QA-16a-13), because ``load_ui`` never themes a root it was given.
    """
    if backend == "pyside6":
        return _qt_root()
    import tkinter

    try:
        root = tkinter.Tk() if backend != "ttkbootstrap" else _ttkbootstrap_root(file)
    except tkinter.TclError as exc:  # no display
        raise RuntimeError(str(exc)) from exc
    root.withdraw()
    return root


def _ttkbootstrap_root(file: str) -> Any:  # noqa: ANN401 - a ttkbootstrap App
    import warnings

    import ttkbootstrap

    from pyguibud.core.xml_io import read_ui

    root = ttkbootstrap.App(title="")
    theme = read_ui(file).document.meta.theme
    style: Any = ttkbootstrap.Style.get_instance()
    if theme and theme not in style.theme_names():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ttkbootstrap.install_legacy_themes(style)
    if theme in style.theme_names():
        style.theme_use(theme)
    elif theme:  # load_ui would say "ignored": give the note of a main-window doc (QA-16b-04)
        from pyguibud.backends.ttkbootstrap import _M_THEME_IGNORED, _M_UNKNOWN_THEME
        from pyguibud.core.errors import format_message

        def swap(record: logging.LogRecord) -> bool:
            if record.getMessage() == format_message(_M_THEME_IGNORED, {"theme": theme}):
                record.args = (format_message(_M_UNKNOWN_THEME, {"theme": theme}),)
                record.msg = "%s"
            return True

        logging.getLogger("pyguibud_runtime").addFilter(swap)
    return root


def _qt_root() -> Any:  # noqa: ANN401 - a QWidget
    import os

    from pyguibud.backends.pyside6 import _M_INSTALL, display_problem
    from pyguibud.i18n import _

    try:
        from PySide6 import QtWidgets
    except ImportError as exc:
        hint = _(_M_INSTALL).format(extra='pip install "pyguibud[pyside]"')
        raise RuntimeError(hint) from exc
    app = QtWidgets.QApplication.instance()
    if app is None:
        reason = display_problem(sys.platform, os.environ)
        if reason is not None:
            raise RuntimeError(reason)
        app = QtWidgets.QApplication([sys.argv[0]])
    _QT_LOOP.append(app)
    return QtWidgets.QWidget()


def _show_dialogs(ui: Any, root: Any) -> None:  # noqa: ANN401 - a LoadedUi and a root
    """Show every dialog; closing the last one ends the main loop."""
    left = set(ui.windows)

    def closed(window_id: str) -> None:
        if not _QT_LOOP:  # a Qt dialog hides itself when closed
            ui.windows[window_id].withdraw()
        left.discard(window_id)
        if left:
            return
        if _QT_LOOP:
            _QT_LOOP[0].quit()
        else:
            root.destroy()

    for window_id, top in ui.windows.items():
        if _QT_LOOP:
            top.finished.connect(lambda _result, w=window_id: closed(w))
        else:
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
    root = _hidden_root(backend, file)
    try:
        ui = load_ui(file, _NoOps(), master=root, **options)
    except BaseException:
        (root.deleteLater if _QT_LOOP else root.destroy)()
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
    ui.run()  # pyside6: exec() even on the application show_ui created (spec §4.1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
