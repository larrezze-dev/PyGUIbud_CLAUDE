"""The PySide6 preview host (spec backends 5): Qt timers, a hidden master and one shown window.

Imported only by ``_host.host_for("pyside6")``, so importing the preview loads no toolkit
(ADR-013). The child's stdin thread only fills a queue; ``schedule`` runs the polling on the Qt
main thread, so ``lang`` commands retranslate live as in the Tk hosts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6 import QtCore, QtWidgets

from pyguibud.backends.base import NoDisplayError
from pyguibud.backends.pyside6 import application
from pyguibud.preview._host import _M_DISPLAY
from pyguibud_runtime import UiError

__all__ = ["QtHost"]


class _OnClose(QtCore.QObject):
    """Calls ``on_close`` after the shown window's Close event (never deleting inside it)."""

    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_close = on_close

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() == QtCore.QEvent.Type.Close:
            QtCore.QTimer.singleShot(0, self._on_close)
        return False


class QtHost:
    """The ``pyside6`` host: no themes (D18), the platform's default style."""

    def __init__(self) -> None:
        self._app: Any = None
        self._master: Any = None
        self._ui: Any = None
        self._shown: Any = None
        self._watch: _OnClose | None = None
        self._closed = False

    def prepare(self, has_main: bool, theme: str) -> object | None:
        """The ``QApplication`` (D8 guard first); without a main window a hidden master."""
        try:
            self._app = application()
        except NoDisplayError as exc:
            raise UiError("runtime.no_display", _M_DISPLAY, reason=str(exc)) from exc
        if has_main:
            return None
        self._master = QtWidgets.QWidget()  # parentless and never shown
        master: object = self._master
        return master

    def attach(
        self,
        ui: Any,  # noqa: ANN401 - a LoadedUi
        main: str | None,
        window: str | None,
        on_close: Callable[[], None],
    ) -> None:
        self._ui, tops = ui, ui.windows
        show = window or main or next(iter(tops))
        self._shown = tops[show]
        if show != main:
            if main is not None:
                tops[main].hide()
            ui.show(show)
        self._watch = _OnClose(on_close)
        self._shown.installEventFilter(self._watch)

    def themes(self) -> list[str]:
        return []

    def current_theme(self) -> str:
        return ""

    def set_theme(self, name: str) -> bool:
        return False

    def schedule(self, ms: int, fn: Callable[[], None]) -> None:
        QtCore.QTimer.singleShot(ms, fn)

    def lift(self) -> None:
        if self._shown.isMinimized():
            self._shown.showNormal()
        self._shown.show()
        self._shown.raise_()
        self._shown.activateWindow()

    def update(self) -> None:
        self._app.processEvents()

    def run(self) -> None:
        if not self._closed:
            self._app.exec()

    def close(self) -> None:
        """Delete the interface and the master, then end the event loop (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if self._ui is not None:
            self._ui.destroy()
        if self._master is not None:
            self._master.deleteLater()
        if self._app is not None:
            self._app.quit()
