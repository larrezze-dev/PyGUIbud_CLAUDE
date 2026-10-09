"""The object tree: the document's windows, menus and widgets; selecting a row selects the node."""

from __future__ import annotations

import contextlib
import tkinter
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from pyguibud.core import ValidationReport
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present import fit_text, severity_label
from pyguibud.designer.present.tree import tree_rows
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.theme import ThemeSpec, tag_colours
from pyguibud.i18n import N_

__all__ = ["TreePanel"]

#: Queued behind the <<TreeviewSelect>> events of a programmatic selection (as in the palette).
_SHOWN = "<<TreeShown>>"


class TreePanel(PanelBase):
    """Object tree with a ``key <-> node`` map and a text badge for rows with findings."""

    name = "tree"
    HEADING = N_("Object tree")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
        on_full_text: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        tree = self._new_tree(("detail", "status"))
        tree.configure(selectmode="extended")  # Ctrl/Shift multi-selection (spec 7.2)
        self._on_full_text = on_full_text
        self._full: dict[str, tuple[str, str]] = {}  # key -> untruncated (detail, status)
        self._fit_job: str | None = None
        tree.bind("<Configure>", self._schedule_fit, add="+")
        self._nodes: dict[str, object] = {}
        self._keys: dict[int, str] = {}
        self._open: dict[int, bool] = {}
        self._report: ValidationReport | None = None
        tree.bind("<<TreeviewSelect>>", self._on_pick)
        #: The shell's context menu: ``popup(x_root, y_root)`` (right click, Menu key, Shift+F10).
        self.popup: Callable[[int, int], None] = lambda _x, _y: None
        tree.bind("<Button-3>", self._on_context, add="+")
        for sequence in ("<Menu>", "<Shift-F10>"):
            tree.bind(sequence, self._on_context_key, add="+")
        tree.bind(_SHOWN, lambda _e: self._shown(), add="+")
        self._muted = 0  # programmatic selections whose <<TreeviewSelect>> is still queued
        self._connect(session.document_changed, self._on_document)
        self._connect(session.selection_changed, self._on_selection)
        self._connect(session.report_changed, self._on_report)
        self._render()

    # ------------------------------------------------------------ signals
    def _on_document(self, _session: DesignerSession) -> None:
        self._open.clear()
        self._report = None
        self._render(capture=False)

    def _on_report(self, report: ValidationReport) -> None:
        if report is not self._report:  # not the one this render already used
            self._render()

    def _on_selection(self, selection: Selection) -> None:
        self._show(selection.node)

    def _on_pick(self, _event: object) -> None:
        """Extended selection (Ctrl/Shift): the focused row is the primary (spec 7.2)."""
        tree = self.tree
        picked = tree.selection() if tree is not None else ()
        if tree is None or not picked:
            return
        focus = tree.focus() if tree.focus() in picked else picked[-1]
        user = not self._muted  # only a pick of the user offers the row text (QA-13a-12)
        nodes = [self._nodes[k] for k in (*picked, focus) if k in self._nodes]
        current = self.session.selection
        if {id(n) for n in nodes} == {id(n) for n in current.nodes} and nodes[-1] is current.node:
            if user:
                self._announce_full_text(focus)
            return  # the echo of a re-render: keep the gesture order
        self.session.select_many(nodes, origin="tree")
        self._show(self.session.selection.node)  # rows it dropped emit nothing (QA-13b-03)
        if user:  # after the pick: a selection change clears the status message (QA-13b-11)
            self._announce_full_text(focus)

    def _on_context(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        """Right click: a row outside the selection becomes the selection first."""
        tree = self.tree
        if tree is not None and (row := tree.identify_row(event.y)) and row not in tree.selection():
            tree.selection_set(row)
            self._on_pick(None)  # now: the menu's enabled states read the session as it opens
        self.popup(event.x_root, event.y_root)

    def _on_context_key(self, _event: object) -> str:
        """The keyboard way to the context menu: it opens below the focused row."""
        tree = self.tree
        if tree is not None:
            box = tree.bbox(tree.focus()) or (0, 0, 0, 0)
            self.popup(tree.winfo_rootx() + box[0], tree.winfo_rooty() + box[1] + box[3])
        return "break"

    def _mute(self) -> None:
        """Mark the <<TreeviewSelect>> events just queued as no pick of the user."""
        if self.tree is not None:
            self._muted += 1
            self.tree.event_generate(_SHOWN, when="tail")

    def _shown(self) -> None:
        self._muted = max(0, self._muted - 1)

    def _announce_full_text(self, key: str) -> None:
        """Offer the whole row text (status bar) when a cell was cut short by the column width."""
        tree = self.tree
        if tree is None or self._on_full_text is None or key not in self._full:
            return
        detail, status = self._full[key]
        shown = tree.item(key, "values")
        if tuple(str(v) for v in shown) != (detail, status):
            parts = (str(tree.item(key, "text")), detail, status)
            self._on_full_text(" - ".join(part for part in parts if part))

    # ------------------------------------------------------------ rendering
    def _render(self, *, capture: bool = True) -> None:
        tree = self.tree
        if tree is None:
            return
        if capture:
            for node_id, key in self._keys.items():
                if tree.exists(key):
                    self._open[node_id] = bool(tree.item(key, "open"))
        scroll = self._scroll_state()
        tree.delete(*tree.get_children())
        self._nodes.clear()
        self._keys.clear()
        self._full.clear()
        document = self.session.document
        if document is None:
            return
        report = self._report = self.session.report()
        for row in tree_rows(document, report):
            tree.insert(
                row.parent_key or "",
                "end",
                iid=row.key,
                text=row.text,
                values=(row.detail, severity_label(row.severity)),
                open=self._open.get(id(row.node), True),
                tags=(row.severity,) if row.severity else (),
            )
            self._full[row.key] = (row.detail, severity_label(row.severity))
            self._nodes[row.key] = row.node
            self._keys[id(row.node)] = row.key
        self._show(self.session.selection.node)
        self._mute()  # the delete above and _show queued <<TreeviewSelect>> events
        self._restore_scroll(scroll)
        self._fit_cells()

    # ------------------------------------------------------------ ellipsis fitting
    def _schedule_fit(self, _event: object = None) -> None:
        """Coalesce resize events into one re-fit when Tk is idle."""
        tree = self.tree
        if tree is None or self._fit_job is not None:
            return
        with contextlib.suppress(tkinter.TclError):
            self._fit_job = tree.after_idle(self._fit_cells)

    def _fit_cells(self) -> None:
        """Cut the detail and status cells to their column width, ending with an ellipsis."""
        tree = self.tree
        self._fit_job = None
        if tree is None:
            return
        try:
            font = tkfont.nametofont(
                str(ttk.Style(tree).lookup("Treeview", "font") or "TkDefaultFont")
            )
        except tkinter.TclError:
            font = tkfont.nametofont("TkDefaultFont")
        padding = 2 * font.measure("m")  # the cell margin Tk keeps around the text
        for index, column in enumerate(("detail", "status")):
            width = int(tree.column(column, "width")) - padding
            for key, full in self._full.items():
                if tree.exists(key):
                    tree.set(key, column, fit_text(full[index], width, font.measure))

    def _show(self, node: object | None) -> None:
        """Show the session's selection; ``node`` (the primary) gets the focus and is seen."""
        tree = self.tree
        if tree is None:
            return
        keys = [k for n in self.session.selection.nodes if (k := self._keys.get(id(n)))]
        key = self._keys.get(id(node)) if node is not None else None
        if set(tree.selection()) != set(keys):
            tree.selection_set(keys)
            self._mute()
        if key is not None:
            tree.see(key)
            tree.focus(key)

    def dispose(self) -> None:
        # A queued re-fit would call a Tcl command deleted with the tree ("invalid command name").
        if self._fit_job is not None and self.tree is not None:
            with contextlib.suppress(tkinter.TclError):  # the tree is already destroyed
                self.tree.after_cancel(self._fit_job)
        self._fit_job = None
        super().dispose()

    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        if self.tree is not None:
            self.tree.tag_configure("error", foreground=tag_colours(spec)["error"])

    # ------------------------------------------------------------ test helpers
    def key_of(self, node: object) -> str | None:
        """The tree key of ``node`` (None when it is not shown)."""
        return self._keys.get(id(node))
