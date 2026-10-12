"""The toolkit side of the preview child: one ``PreviewHost`` per backend (ADR-013, spec 7).

Step 15 ships the ttkbootstrap host; Step 16 adds ``tkinter`` and ``pyside6`` hosts to
:data:`HOSTS`. The toolkit is imported only by the host's methods.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, Protocol

from pyguibud.i18n import N_
from pyguibud_runtime import UiError

__all__ = ["HOSTS", "PreviewHost", "TtkbootstrapHost"]

_M_DISPLAY = N_("No display is available, so no window can be opened: {reason}")


class PreviewHost(Protocol):
    """What the child needs from a toolkit: a root, themes, timers and the shown window."""

    def prepare(self, has_main: bool, theme: str) -> object | None:
        """The ``master`` for ``load_ui``: None, or a hidden root with ``theme`` applied."""

    def attach(
        self,
        ui: Any,  # noqa: ANN401 - a LoadedUi
        main: str | None,
        window: str | None,
        on_close: Callable[[], None],
    ) -> None:
        """Show ``window`` alone (or the main window, else the first dialog); closing it calls
        ``on_close``."""

    def themes(self) -> list[str]: ...
    def current_theme(self) -> str: ...
    def set_theme(self, name: str) -> bool: ...
    def schedule(self, ms: int, fn: Callable[[], None]) -> None: ...
    def lift(self) -> None: ...
    def update(self) -> None: ...
    def run(self) -> None: ...
    def close(self) -> None: ...


class TtkbootstrapHost:
    """The ttkbootstrap host: one ``App`` root, the ``Style`` singleton for themes."""

    def __init__(self) -> None:
        self._root: Any = None
        self._shown: Any = None

    @staticmethod
    def _style() -> Any:  # noqa: ANN401 - ttkbootstrap is untyped
        import ttkbootstrap

        style: Any = ttkbootstrap.Style
        return style.get_instance() or style()

    def prepare(self, has_main: bool, theme: str) -> object | None:
        if has_main:
            return None
        import tkinter

        import ttkbootstrap

        try:
            self._root = ttkbootstrap.App(title="")
        except tkinter.TclError as exc:
            raise UiError("runtime.no_display", _M_DISPLAY, reason=str(exc)) from exc
        self._root.withdraw()
        if theme:  # before load_ui, as the generated _preview_dialog does
            self.set_theme(theme)
        root: object = self._root
        return root

    def attach(
        self,
        ui: Any,  # noqa: ANN401 - a LoadedUi
        main: str | None,
        window: str | None,
        on_close: Callable[[], None],
    ) -> None:
        tops = ui.windows
        if self._root is None and main is not None:
            self._root = tops[main]
        show = window or main or next(iter(tops))
        self._shown = tops[show]
        if show != main:
            if main is not None:
                tops[main].withdraw()
            self._shown.transient("")  # a transient of a withdrawn window would stay hidden
            ui.show(show)
        self._shown.protocol("WM_DELETE_WINDOW", on_close)

    def themes(self) -> list[str]:
        import ttkbootstrap

        style = self._style()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            ttkbootstrap.install_legacy_themes(style)
        return sorted(str(name) for name in style.theme_names())

    def current_theme(self) -> str:
        return str(self._style().theme_use())

    def set_theme(self, name: str) -> bool:
        style = self._style()
        if name not in style.theme_names():
            self.themes()
        if name not in style.theme_names():
            return False
        style.theme_use(name)
        return True

    def schedule(self, ms: int, fn: Callable[[], None]) -> None:
        self._root.after(ms, fn)

    def lift(self) -> None:
        self._shown.deiconify()
        self._shown.lift()
        self._shown.focus_force()

    def update(self) -> None:
        self._root.update()

    def run(self) -> None:
        self._root.mainloop()

    def close(self) -> None:
        if self._root is not None:
            self._root.destroy()
            self._root = None


#: ``--backend NAME`` -> host class (Step 16 adds more).
HOSTS: dict[str, Callable[[], PreviewHost]] = {"ttkbootstrap": TtkbootstrapHost}
