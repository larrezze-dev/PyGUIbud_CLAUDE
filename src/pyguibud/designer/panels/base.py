"""Shared plumbing of the panels: a heading, a scrolled ``Treeview`` and signal bookkeeping."""

from __future__ import annotations

import contextlib
import tkinter
from collections.abc import Callable
from tkinter import ttk
from typing import Any, TypeVar

from pyguibud.designer.panels.focus import FocusFrame
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.signals import Signal
from pyguibud.designer.theme import ThemeSpec
from pyguibud.designer.theme_tk import TREE_STYLE
from pyguibud.i18n import _

__all__ = ["PanelBase"]

T = TypeVar("T")


class PanelBase:
    """A panel: ``frame`` (a FocusFrame) holding a translated heading and the body.

    Subclasses set ``name`` and ``HEADING`` (a msgid), implement :meth:`_render` and keep only
    msgids, never translated text, so :meth:`retranslate` can rebuild everything.
    """

    name = ""
    HEADING = ""

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        self.session = session
        self.frame = FocusFrame(parent, thickness=ring_px)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.heading = ttk.Label(self.frame, text=_(self.HEADING), anchor="w")
        self.heading.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(4, 2))
        self.tree: ttk.Treeview | None = None
        self._disconnects: list[Callable[[], None]] = []

    # ------------------------------------------------------------ building blocks
    def _new_tree(self, columns: tuple[str, ...] = (), *, row: int = 1) -> ttk.Treeview:
        """A browse-mode ``Treeview`` with a vertical scrollbar, in the body ``row``."""
        tree = ttk.Treeview(
            self.frame,
            columns=columns,
            show="tree",
            selectmode="browse",
            takefocus=True,
            style=TREE_STYLE,
        )
        tree.column("#0", stretch=True, minwidth=60, width=160)
        for column in columns:
            tree.column(column, stretch=True, minwidth=40, width=100)
        scroll = ttk.Scrollbar(self.frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=row, column=0, sticky="nsew")
        scroll.grid(row=row, column=1, sticky="ns")
        self.tree = tree
        return tree

    def _connect(self, signal: Signal[T], slot: Callable[[T], None]) -> None:
        self._disconnects.append(signal.connect(slot))

    # ------------------------------------------------------------ Panel protocol
    def _render(self) -> None:
        """Rebuild the view from the model in the current language (subclass hook)."""

    def retranslate(self) -> None:
        """Re-render from msgids; selection, open state and scroll are kept by ``_render``."""
        self.heading.configure(text=_(self.HEADING))
        self._render()

    def restyle(self, spec: ThemeSpec) -> None:
        """Re-apply theme-dependent colours (tags, ring); ``spec`` is the new theme."""
        self.frame.set_colours(ring=spec.focus, plain=spec.colors["bg"])

    def focus_first(self) -> None:
        """Focus the main widget (and its selected or first item for a tree)."""
        tree = self.tree
        if tree is None:
            return
        target = tree.selection() or tree.get_children()[:1]
        if target:
            tree.focus(target[0])
        tree.focus_set()

    def dispose(self) -> None:
        """Disconnect from the session signals (the widgets are destroyed by the shell)."""
        for disconnect in self._disconnects:
            disconnect()
        self._disconnects.clear()

    # ------------------------------------------------------------ helpers
    def _scroll_state(self) -> float:
        return self.tree.yview()[0] if self.tree is not None else 0.0

    def _restore_scroll(self, fraction: float) -> None:
        if self.tree is not None:
            with contextlib.suppress(tkinter.TclError):  # the widget is being destroyed
                self.tree.yview_moveto(fraction)
