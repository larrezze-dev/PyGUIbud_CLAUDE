"""The object tree: the document's windows, menus and widgets; selecting a row selects the node.

Rows can be dragged (spec direct-manipulation 5): ``tree_dnd`` turns the row and zone under the
pointer into a canvas ``Target``; hover runs ``check()`` after a 60 ms rest (cached per drag) and
the drop runs the canvas's own move. Esc or a release outside the tree cancels.
"""

from __future__ import annotations

import contextlib
import tkinter
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from pyguibud.core import ValidationReport
from pyguibud.core.commands import Command
from pyguibud.designer import tree_dnd
from pyguibud.designer.editing import move_command
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present import fit_text, severity_label
from pyguibud.designer.present.icons import node_icon
from pyguibud.designer.present.tree import tree_rows
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.targets import Target
from pyguibud.designer.theme import ThemeSpec, tag_colours
from pyguibud.designer.theme_tk import scaled
from pyguibud.i18n import N_, _

__all__ = ["TreePanel"]

#: Queued behind the <<TreeviewSelect>> events of a programmatic selection (as in the palette).
_SHOWN = "<<TreeShown>>"
_THRESHOLD, _REST_MS = 4, 60  # px at 96 dpi before a press is a drag; ms of rest to check
_M_RELEASE_CANCEL = N_("Release to cancel.")
_M_CANCELLED = N_("Drag cancelled.")


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
        #: The shell's canvas move (one undo step, keeps the nodes selected) and status bar.
        self.mover: Callable[[Target, tuple[object, ...]], bool] | None = None
        self.status: Callable[[str], None] = lambda _text: None
        # A drag: (x, y, payload, row, keep the multi-selection), dragging, (row, zone), mark.
        self._press: tuple[int, int, tuple[object, ...], str, bool] | None = None
        self._dragging, self._marked = False, ""
        self._over: tuple[str, tree_dnd.Zone] = ("", "into")
        self._checked: dict[tuple[str, str], tuple[bool, str]] = {}
        self._job: str | None = None  # the pending hover check
        for sequence, handler in (
            ("<ButtonPress-1>", self._drag_press),
            ("<B1-Motion>", self._drag_motion),
            ("<ButtonRelease-1>", self._drag_release),
            ("<Escape>", self._drag_cancel),
        ):
            tree.bind(sequence, handler, add="+")
        self._connect(session.document_changed, self._on_document)
        self._connect(session.selection_changed, self._on_selection)
        self._connect(session.report_changed, self._on_report)
        self._render()

    # ------------------------------------------------------------ drag-and-drop (spec 5)
    def _drag_press(self, event: Any) -> str | None:  # noqa: ANN401 - a Tk event
        tree, state = self.tree, event.state if isinstance(event.state, int) else 0
        assert tree is not None
        self._end_drag()
        row = tree.identify_row(event.y)
        # Ctrl/Shift extend the selection and the expander opens the row: neither starts a drag.
        if not row or state & 0x5 or "indicator" in tree.identify_element(event.x, event.y):
            return None
        picked = tree.selection()
        nodes = tuple(self.session.selection.nodes) if row in picked else (self._nodes[row],)
        keep = row in picked and len(picked) > 1
        self._press = (event.x, event.y, nodes, row, keep)
        if not keep:
            return None
        tree.focus_set()  # what the skipped class binding does: Esc mid-drag must reach us
        return "break"  # the class binding would drop the multi-selection

    def _drag_motion(self, event: Any) -> str | None:  # noqa: ANN401 - a Tk event
        press, tree = self._press, self.tree
        if press is None or tree is None:
            return None
        if not self._dragging:
            if max(abs(event.x - press[0]), abs(event.y - press[1])) < scaled(tree, _THRESHOLD):
                return None
            self._dragging = True
        self._drag_hover(event.x, event.y)
        return "break"

    def _drag_hover(self, x: int, y: int) -> None:
        tree, press = self.tree, self._press
        assert tree is not None and press is not None
        row = tree.identify_row(y)
        box, node = (tree.bbox(row) if row else ""), self._nodes.get(row)
        if not box or node is None or not 0 <= x < tree.winfo_width():
            self._over = ("", "into")
            self._cancel_job()  # a check still pending would claim a release here moves
            self._unmark()
            self.status(_(_M_RELEASE_CANCEL))
            return
        zone = tree_dnd.zone_of(y - box[1], box[3])
        if (row, zone) == self._over:
            return
        self._over = (row, zone)
        self._cancel_job()
        found = tree_dnd.target(node, zone, press[2], self.session.registry)
        built = move_command(press[2], found) if isinstance(found, Target) else found
        if isinstance(built, str) or not isinstance(found, Target):
            self._mark(row, False, str(built))
        elif (row, zone) in self._checked:
            self._mark(row, *self._checked[row, zone])
        else:
            text = tree_dnd.release_text(press[2], found)
            self._job = tree.after(_REST_MS, lambda: self._drag_check(built, text))

    def _drag_check(self, built: Command, text: str) -> None:
        self._job = None  # it ran: Tcl already deleted its command
        if (stack := self.session.stack) is None:
            return
        outcome = stack.check(built)
        accepted = outcome.accepted
        self._checked[self._over] = (accepted, text if accepted else outcome.message)
        self._mark(self._over[0], *self._checked[self._over])

    def _mark(self, row: str, accepted: bool, message: str) -> None:
        """Tag ``row`` as the drop target (theme colours) or as denied; say why in the status."""
        self._unmark()
        if self.tree is not None and self.tree.exists(row):
            tags = (*self.tree.item(row, "tags"), "drop-target" if accepted else "drop-denied")
            self.tree.item(row, tags=tags)
            self._marked = row
        self.status(message)

    def _unmark(self) -> None:
        tree, row = self.tree, self._marked
        if tree is not None and row and tree.exists(row):
            tree.item(row, tags=[t for t in tree.item(row, "tags") if not t.startswith("drop-")])
        self._marked = ""

    def _drag_release(self, event: Any) -> str | None:  # noqa: ANN401 - a Tk event
        press, dragging, (row, zone) = self._press, self._dragging, self._over
        self._end_drag()  # the drop re-renders the tree: every row key changes
        tree = self.tree
        if press is None or tree is None:
            return None
        if not dragging:
            if press[4]:  # a click on a row of a multi-selection selects just that row
                tree.selection_set(press[3])
                tree.focus(press[3])
            return None
        inside = 0 <= event.x < tree.winfo_width() and 0 <= event.y < tree.winfo_height()
        node = self._nodes.get(row) if inside else None
        found = tree_dnd.target(node, zone, press[2], self.session.registry) if node else None
        if not isinstance(found, Target) or self.mover is None:
            self.status(found if isinstance(found, str) else _(_M_CANCELLED))
        else:
            self.mover(found, press[2])
        return "break"

    def _drag_cancel(self, _event: object) -> str | None:
        """Esc mid-drag cancels it (and nothing else); otherwise Esc is left to the tree."""
        if not self._dragging:
            return None
        self._end_drag()
        self.status(_(_M_CANCELLED))
        return "break"

    def _cancel_job(self) -> None:
        # The widget that scheduled the job cancels it: another one would delete the Tcl
        # command but leave its name in the tree's list, and tree.destroy() would then fail.
        if self._job is not None and self.tree is not None:
            with contextlib.suppress(tkinter.TclError):  # the tree is already destroyed
                self.tree.after_cancel(self._job)
        self._job = None

    def _end_drag(self) -> None:
        self._cancel_job()
        self._unmark()
        self._press, self._dragging, self._over = None, False, ("", "into")
        self._checked.clear()

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
        press, dragging = self._press, self._dragging
        pressed = self._nodes.get(press[3]) if press is not None else None
        self._end_drag()  # an edit or undo mid-drag: the payload and the row keys are stale
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
                image=self._icon(node_icon(row.node, self.session.registry)),
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
        # The inspector commits on the FocusOut of the press that starts a drag: the drag goes
        # on while every node it carries is still shown (QA-14b2-11); its row key may change.
        again = self._keys.get(id(pressed))
        if press is not None and again is not None and all(id(n) in self._keys for n in press[2]):
            self._press, self._dragging = (*press[:3], again, press[4]), dragging

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
        self._end_drag()
        if self._fit_job is not None and self.tree is not None:
            with contextlib.suppress(tkinter.TclError):  # the tree is already destroyed
                self.tree.after_cancel(self._fit_job)
        self._fit_job = None
        super().dispose()

    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        if self.tree is not None:
            self.tree.tag_configure("error", foreground=tag_colours(spec)["error"])
            colours = spec.colors
            self.tree.tag_configure(
                "drop-target", background=colours["selectbg"], foreground=colours["selectfg"]
            )
            self.tree.tag_configure("drop-denied", foreground=tag_colours(spec)["error"])

    # ------------------------------------------------------------ test helpers
    def key_of(self, node: object) -> str | None:
        """The tree key of ``node`` (None when it is not shown)."""
        return self._keys.get(id(node))
