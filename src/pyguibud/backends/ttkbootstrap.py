"""The ttkbootstrap backend (2.2.x): class table, theme and ``bootstyle`` on top of ``_tk``.

``tkinter`` and ``ttkbootstrap`` are imported only inside :meth:`prepare` and :meth:`build`.
"""

from __future__ import annotations

import warnings
from typing import Any, ClassVar, cast

from pyguibud.backends._tk import Tk, TkSession
from pyguibud.backends.base import BuildPlan, NoDisplayError, RootExistsError
from pyguibud.i18n import N_

__all__ = ["TtkbootstrapBackend"]

# Core class -> ttkbootstrap attribute (spec 8.4); the rest use the same name.
_RENAMED = {"LabelFrame": "Labelframe", "PanedWindow": "Panedwindow"}
_CLASSES = (
    *("Frame", "LabelFrame", "Notebook", "PanedWindow", "ScrolledFrame", "Label", "Button"),
    *("Entry", "Text", "Checkbutton", "Radiobutton", "Combobox", "Spinbox", "Scale"),
    *("Progressbar", "Separator", "Listbox", "Treeview", "Scrollbar", "Canvas", "Menu"),
    "Toplevel",
)
# Translators: the .ui file asks for a ttkbootstrap theme that is not installed.
_M_UNKNOWN_THEME = N_("The theme '{theme}' is not available; the default theme is used.")
# Translators: the application already has a window, so the .ui file's theme is not applied.
_M_THEME_IGNORED = N_("The theme '{theme}' is ignored because the application owns the theme.")


class TtkbootstrapBackend:
    """Builds ``.ui`` documents with ttkbootstrap widgets."""

    name: ClassVar[str] = "ttkbootstrap"

    def prepare(self, master: object | None) -> None:
        """Import the toolkit and check ``master``; never creates a window.

        Raises:
            ImportError: ttkbootstrap is missing.
            TypeError: ``master`` is not a live Tk widget.
            RootExistsError: ``master`` is None but a live root exists.
        """
        import tkinter

        import ttkbootstrap

        if master is not None:
            if not isinstance(master, tkinter.Misc) or not _exists(master):
                raise TypeError("master must be a live Tk widget")
            return
        style: Any = cast(Any, ttkbootstrap.Style).get_instance()
        roots = (getattr(tkinter, "_default_root", None), getattr(style, "master", None))
        if any(root is not None and _exists(root) for root in roots):
            raise RootExistsError("a Tk root window already exists")

    def build(self, plan: BuildPlan, master: object | None) -> TkSession:
        """Build the plan (the main window is shown when this returns)."""
        import tkinter

        import ttkbootstrap

        style_class: Any = ttkbootstrap.Style
        classes = {name: getattr(ttkbootstrap, _RENAMED.get(name, name)) for name in _CLASSES}

        def make_root() -> Tk:
            try:
                return ttkbootstrap.App(title="")
            except tkinter.TclError as exc:
                raise NoDisplayError(str(exc)) from exc

        def apply_theme(root: Tk, owns_root: bool) -> None:
            name = plan.theme
            style: Any = style_class.get_instance() or style_class()
            if not name or name == style.theme_use():
                return
            if not owns_root:
                plan.log(_M_THEME_IGNORED, theme=name)
                return
            if name not in style.theme_names():
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", DeprecationWarning)
                    ttkbootstrap.install_legacy_themes(style)
            if name not in style.theme_names():
                plan.log(_M_UNKNOWN_THEME, theme=name)
                return
            style.theme_use(name)

        session = TkSession(
            plan,
            master,
            tk=tkinter,
            classes=classes,
            make_root=make_root,
            apply_theme=apply_theme,
            backend=self.name,
            bootstyle=True,
        )
        return session.build()


def _exists(widget: Tk) -> bool:
    try:
        return bool(widget.winfo_exists())
    except Exception:  # a destroyed application raises TclError
        return False
