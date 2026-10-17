"""The palette: registered widget classes by category (read-only in Step 12)."""

from __future__ import annotations

import tkinter
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Protocol

from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present.icons import class_icon
from pyguibud.designer.present.palette import palette_groups
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.theme_tk import FONT_HEADER, TREE_STYLE
from pyguibud.i18n import N_, _

__all__ = ["PalettePanel"]

_M_PLUGIN = N_("{label} (plugin)")
#: Queued at the end of a render, behind the render's own <<TreeviewSelect>> events.
_RENDERED = "<<PaletteRendered>>"
_INDENT = 20  # px: Tk's Treeview indent when the theme sets none
_TEXT_PAD = 8  # px: the room Tk keeps around a row's text
_WIDTH = 160  # px: the tree's usual width (``PanelBase._new_tree``); short names keep it


class DragSink(Protocol):
    """Receives the palette's drag gestures (``canvas.drag.DragController``)."""

    def press(self, spec_name: str, x_root: int, y_root: int) -> None: ...
    def motion(self, x_root: int, y_root: int) -> None: ...
    def release(self, x_root: int, y_root: int) -> None: ...
    def cancel(self) -> None: ...
    def insert_widget(self, spec_name: str) -> None: ...
    def hint(self, spec_name: str) -> None: ...
    @property
    def moving(self) -> bool: ...


class PalettePanel(PanelBase):
    """Categories with their widget classes; a widget item is the source of a canvas drag."""

    name = "palette"
    HEADING = N_("Palette")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        tree = self._new_tree()
        tree.tag_configure("category", font=FONT_HEADER)
        self.drag: DragSink | None = None
        tree.bind("<ButtonPress-1>", self._on_press, add="+")
        tree.bind("<B1-Motion>", lambda e: self._forward("motion", e), add="+")
        tree.bind("<ButtonRelease-1>", lambda e: self._forward("release", e), add="+")
        for sequence in ("<Escape>", "<FocusOut>"):
            tree.bind(sequence, lambda _e: self._cancel_insert(), add="+")
        tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select(), add="+")
        for sequence in ("<Return>", "<KP_Enter>"):
            tree.bind(sequence, lambda _e: self._activate(tree.focus()), add="+")
        tree.bind("<Double-Button-1>", lambda e: self._activate(tree.identify_row(e.y)), add="+")
        for sequence in ("<Triple-Button-1>", "<Quadruple-Button-1>"):  # else Tk repeats Double
            tree.bind(sequence, lambda e: self._swallow(tree.identify_row(e.y)), add="+")
        tree.bind(_RENDERED, lambda _e: self._rendered(), add="+")
        self._renders = 0  # renders whose <<TreeviewSelect>> events are still queued
        self._fit = 0  # the tree width that shows every row uncut (QA-18-05)
        self._render()

    def fit_width(self) -> int:
        """The pane width that shows every name uncut in the current language (QA-18-05).

        The shell keeps the palette at least this wide (capped, see ``Shell._minimum``), so long
        translated names are never clipped: it is the tree's need plus the scrollbar and ring.
        """
        tree = self.tree
        if tree is None:
            return 0
        overhead = max(0, self.frame.winfo_reqwidth() - tree.winfo_reqwidth())
        return self._fit + overhead

    def _measure(self, rows: list[tuple[str, Any, bool]]) -> int:
        """The widest row: depth indent, expand indicator, icon and text (category in bold)."""
        tree = self.tree
        if tree is None:
            return 0
        style = ttk.Style(tree)
        try:
            indent = int(tree.winfo_fpixels(style.lookup(TREE_STYLE, "indent") or _INDENT))
            body = tkfont.nametofont(
                str(style.lookup(TREE_STYLE, "font") or style.lookup("Treeview", "font")
                    or "TkDefaultFont")
            )  # fmt: skip
            header = tkfont.nametofont(FONT_HEADER)
        except (tkinter.TclError, ValueError):  # no theme fonts yet (an early render)
            return 0
        widest = 0
        for text, icon, category in rows:
            icon_px = int(tree.tk.call("image", "width", icon)) if icon else 0
            font = header if category else body
            depth = 1 if category else 2  # the indicator column, plus one level for an item
            widest = max(widest, depth * indent + icon_px + font.measure(text) + _TEXT_PAD)
        return widest

    def _on_select(self) -> None:
        picked = self.tree.selection() if self.tree is not None else ()
        if self.drag is not None and not self._renders and picked and picked[0][:2] == "w:":
            self.drag.hint(picked[0][2:])

    def _activate(self, row: str) -> str | None:
        """Enter or double-click on a widget item inserts it; the focus stays here (D7)."""
        if self.drag is None or not row.startswith("w:"):
            return None  # a category keeps the Treeview's own Enter / double-click (expand)
        self.drag.insert_widget(row[2:])
        return "break"

    def _swallow(self, row: str) -> str | None:
        """A 3rd+ rapid click on a widget item inserts nothing more (one per double-click)."""
        return "break" if self.drag is not None and row.startswith("w:") else None

    def _on_press(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        row = self.tree.identify_row(event.y) if self.tree is not None else ""
        if self.drag is not None and row.startswith("w:"):
            self.drag.press(row[2:], event.x_root, event.y_root)

    def _cancel_insert(self) -> None:
        """Esc or the focus leaving cancels only a palette drag, never a canvas gesture.

        A canvas press takes the focus from the palette after arming its move, band or resize;
        cancelling here would undo that press at once (QA-13b-10). The canvas cancels its own.
        """
        if self.drag is not None and not self.drag.moving:
            self.drag.cancel()

    def _forward(self, gesture: str, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self.drag is not None and not self.drag.moving:  # Q12: never a canvas gesture
            getattr(self.drag, gesture)(event.x_root, event.y_root)

    def _render(self) -> None:
        tree = self.tree
        if tree is None:
            return
        # Open state is remembered per category by its first widget class (stable across languages).
        opened: dict[str, bool] = {}
        for category in tree.get_children():
            children = tree.get_children(category)
            if children:
                opened[children[0]] = bool(tree.item(category, "open"))
        selected = tree.selection()
        scroll = self._scroll_state()
        tree.delete(*tree.get_children())
        rows: list[tuple[str, Any, bool]] = []
        for index, group in enumerate(palette_groups(self.session.registry)):
            first = f"w:{group.items[0].name}" if group.items else ""
            category = tree.insert(
                "",
                "end",
                iid=f"c{index}",
                text=group.category_label,
                open=opened.get(first, True),
                tags=("category",),
            )
            rows.append((group.category_label, "", True))
            for item in group.items:
                label = _(_M_PLUGIN).format(label=item.label) if item.plugin else item.label
                icon = self._icon(class_icon(item.name, self.session.registry))
                tree.insert(category, "end", iid=f"w:{item.name}", text=label, image=icon)
                rows.append((label, icon, False))
        self._fit = self._measure(rows)
        if self._fit:  # the requested width: the first layout already shows every name
            tree.column("#0", width=max(_WIDTH, self._fit))
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])
        self._restore_scroll(scroll)
        # The delete and the restore queue <<TreeviewSelect>> events, which are no pick of the
        # user: mute the hint until a marker queued behind them arrives. An idle job is not
        # enough: a later update_idletasks (the canvas re-render of a language switch) runs it
        # before the queued events (QA-13a-09).
        self._renders += 1
        tree.event_generate(_RENDERED, when="tail")

    def _rendered(self) -> None:
        self._renders = max(0, self._renders - 1)
