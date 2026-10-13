"""The toolkit side of the preview child: one ``PreviewHost`` per backend (ADR-013, spec 7).

Step 15 ships the ttkbootstrap host and Step 16 the ``tkinter`` one (``pyside6`` joins
:data:`HOSTS` in part 16b). The toolkit is imported only by the host's methods; :func:`host_for`
also finds the optional ``preview_host`` capability of a third-party backend (spec backends D16).
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, Protocol

from pyguibud.i18n import N_, _
from pyguibud_runtime import UiError

__all__ = ["HOSTS", "PreviewHost", "TkinterHost", "TtkbootstrapHost", "host_for"]

_M_DISPLAY = N_("No display is available, so no window can be opened: {reason}")
_M_BACKEND = N_("The backend '{name}' is not available: {reason}")
_M_UNKNOWN = N_("Unknown backend '{name}'.")  # the registry's own msgid
_M_NO_HOST = N_("It cannot be previewed: it provides no preview host.")


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


class _TkHost:
    """What the Tk hosts share: a hidden root, one shown window and the Tk event loop."""

    def __init__(self) -> None:
        self._root: Any = None
        self._shown: Any = None

    def _new_root(self) -> Any:  # noqa: ANN401 - a Tk root
        raise NotImplementedError

    def prepare(self, has_main: bool, theme: str) -> object | None:
        if has_main:
            return None
        import tkinter

        try:
            self._root = self._new_root()
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
        return []

    def current_theme(self) -> str:
        return ""

    def set_theme(self, name: str) -> bool:
        return False

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


class TkinterHost(_TkHost):
    """The plain ``tkinter`` host: no themes (the child reports ``themes: []``)."""

    def _new_root(self) -> Any:  # noqa: ANN401 - a Tk root
        import tkinter

        root = tkinter.Tk()
        root.title("")
        return root

    def prepare(self, has_main: bool, theme: str) -> object | None:
        """As the backend does for a root it owns: a ttk theme name is applied (D4, QA-16a-09)."""
        root = super().prepare(has_main, theme)
        if root is not None:
            from tkinter import ttk

            style = ttk.Style(self._root)
            if theme in style.theme_names():
                style.theme_use(theme)
        return root


class TtkbootstrapHost(_TkHost):
    """The ttkbootstrap host: one ``App`` root, the ``Style`` singleton for themes."""

    def _new_root(self) -> Any:  # noqa: ANN401 - a ttkbootstrap App
        import ttkbootstrap

        return ttkbootstrap.App(title="")

    @staticmethod
    def _style() -> Any:  # noqa: ANN401 - ttkbootstrap is untyped
        import ttkbootstrap

        style: Any = ttkbootstrap.Style
        return style.get_instance() or style()

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


#: ``--backend NAME`` -> host class for the built-in toolkits (``pyside6`` joins in Step 16b).
HOSTS: dict[str, Callable[[], PreviewHost]] = {
    "ttkbootstrap": TtkbootstrapHost,
    "tkinter": TkinterHost,
}


def host_for(name: str) -> PreviewHost:
    """The preview host of backend ``name``: a built-in one, else the backend's optional
    ``preview_host`` capability (D16).

    Raises:
        UiError: ``runtime.backend_unavailable``; the name is malformed or unknown, the backend
            failed to load, has no preview host, or its ``preview_host()`` raised (B15).
    """
    factory = HOSTS.get(name)
    if factory is not None:
        return factory()
    from pyguibud.backends import BACKEND_NAME, load_backend
    from pyguibud.core import default_registry

    try:
        if not BACKEND_NAME.fullmatch(name):  # checked by name: never looked up (D16)
            raise LookupError(_(_M_UNKNOWN).format(name=name))
        capability: Callable[[], PreviewHost] | None = getattr(
            load_backend(name, default_registry()), "preview_host", None
        )
        if not callable(capability):
            raise UiError(
                "runtime.backend_unavailable", _M_BACKEND, name=name, reason=_(_M_NO_HOST)
            )
        return capability()
    except UiError:
        raise
    except Exception as exc:  # unknown, a plugin that crashes on load or in its host (B15)
        reason = str(exc) or type(exc).__name__
        raise UiError("runtime.backend_unavailable", _M_BACKEND, name=name, reason=reason) from exc
