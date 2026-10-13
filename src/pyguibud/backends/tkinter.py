"""The plain ``tkinter`` backend: ``tkinter.ttk`` widgets with no ttkbootstrap (spec backends D2).

It reuses :class:`~pyguibud.backends._tk.TkSession`, so layouts, events, variables, menus,
images and includes behave exactly as with ttkbootstrap; only the class table, the root and the
theme differ. This module must keep importing the standard library's ``tkinter`` (absolute
imports only) and never imports ``ttkbootstrap``. The toolkit is imported only inside
:meth:`prepare` and :meth:`build`.
"""

from __future__ import annotations

from typing import ClassVar

from pyguibud.backends._tk import Tk, TkSession
from pyguibud.backends._tkmap import _CLASSES, _RENAMED
from pyguibud.backends.base import BuildPlan, NoDisplayError, RootExistsError
from pyguibud.backends.ttkbootstrap import _exists

__all__ = ["TkinterBackend"]

# These classes come from ``tkinter`` itself; every other one is a ``tkinter.ttk`` widget.
_CLASSIC = frozenset({"Text", "Listbox", "Canvas", "Menu", "Toplevel"})


class TkinterBackend:
    """Builds ``.ui`` documents with the standard library's ``tkinter`` and ``tkinter.ttk``."""

    name: ClassVar[str] = "tkinter"

    def prepare(self, master: object | None) -> None:
        """Import the toolkit and check ``master``; never creates a window.

        Raises:
            TypeError: ``master`` is not a live Tk widget.
            RootExistsError: ``master`` is None but a live root exists.
        """
        import tkinter

        if master is not None:
            if not isinstance(master, tkinter.Misc) or not _exists(master):
                raise TypeError("master must be a live Tk widget")
            return
        root = getattr(tkinter, "_default_root", None)
        if root is not None and _exists(root):
            raise RootExistsError("a Tk root window already exists")

    def build(self, plan: BuildPlan, master: object | None) -> TkSession:
        """Build the plan (the main window is shown when this returns)."""
        import tkinter
        from tkinter import ttk

        from pyguibud.backends._tkscrolled import ScrolledFrame

        classes = {
            name: ScrolledFrame
            if name == "ScrolledFrame"
            else getattr(tkinter if name in _CLASSIC else ttk, _RENAMED.get(name, name))
            for name in _CLASSES
        }

        def make_root() -> Tk:
            try:
                root = tkinter.Tk()
                root.title("")  # as ttkbootstrap's App(title=""): a window without a title has none
                return root
            except tkinter.TclError as exc:
                raise NoDisplayError(str(exc)) from exc

        def apply_theme(root: Tk, owns_root: bool) -> None:
            # Theme names belong to ttkbootstrap: one that this Tk does not know is ignored (D4).
            style = ttk.Style(root)
            if owns_root and plan.theme in style.theme_names():
                style.theme_use(plan.theme)

        session = TkSession(
            plan,
            master,
            tk=tkinter,
            classes=classes,
            make_root=make_root,
            apply_theme=apply_theme,
            backend=self.name,
            bootstyle=False,
        )
        return session.build()
