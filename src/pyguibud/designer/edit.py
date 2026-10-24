"""Edit actions (pure; spec dnd-selection 7.3, 11): undo, redo, delete and the canvas keys.

Every change goes through the command stack. Delete asks for confirmation (through the
``confirm`` callback, which opens a dialog and returns at once) when a node has children. One
key press is one command; while ``busy()`` (a canvas rebuild is pending) repeats of the arrow
keys are dropped, so a held key moves at rebuild speed and never queues edits.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from pyguibud.core.commands import Command, InsertNode, SetField
from pyguibud.core.model import (
    Action,
    GridCell,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.designer.actions import window_delete_hint
from pyguibud.designer.editing import (
    MenuItem,
    delete_command,
    menu_insert_command,
    menu_insert_enabled,
    nudge_command,
    past_the_grid,
    reorder_command,
    resize_command,
)
from pyguibud.designer.present import inserted
from pyguibud.designer.present.tree import node_label
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.sizing import Measured, step_command
from pyguibud.i18n import ngettext

__all__ = ["EditActions", "count_descendants", "tab_order"]

#: What Edit > Delete (and the Delete key) removes: elements and the menu nodes.
_DELETABLE = (Widget, Include, Menu, Action, MenuSeparator, Menubar, Statusbar)

#: ``(question, then)``: show ``question``; call ``then`` when the user agrees.
Confirm = Callable[[str, Callable[[], None]], None]


def count_descendants(node: object) -> int:
    """How many nodes are below ``node`` (iterative: no recursion limit)."""
    pending, total = [node], 0
    while pending:
        kids = getattr(pending.pop(), "children", ())
        total += len(kids)
        pending.extend(kids)
    return total


def _preorder(node: object) -> Iterator[object]:
    pending = list(reversed(getattr(node, "children", ())))
    while pending:
        current = pending.pop()
        yield current
        pending.extend(reversed(getattr(current, "children", ())))


def tab_order(window: object) -> list[object]:
    """The widgets and includes of ``window`` in document pre-order (the canvas Tab order)."""
    return [n for n in _preorder(window) if isinstance(n, Widget | Include)]


def _ancestors(node: object) -> Iterator[object]:
    parent = getattr(node, "parent", None)
    while parent is not None:
        yield parent
        parent = getattr(parent, "parent", None)


def _roots(nodes: tuple[object, ...]) -> list[object]:
    """The selected widgets and includes whose ancestors are not selected too."""
    chosen = {id(n) for n in nodes}
    return [
        n
        for n in nodes
        if isinstance(n, _DELETABLE) and not any(id(a) in chosen for a in _ancestors(n))
    ]


def _window(node: object) -> object | None:
    return next((a for a in (node, *_ancestors(node)) if isinstance(a, Window)), None)


class EditActions:
    """What the Edit menu calls; ``message`` shows a refusal in the status bar."""

    def __init__(
        self,
        session: DesignerSession,
        confirm: Confirm,
        message: Callable[[str], None],
        busy: Callable[[], bool] = lambda: False,
        measure: Callable[[object], Measured | None] = lambda _node: None,
    ) -> None:
        self.session, self._confirm, self._message, self._busy = session, confirm, message, busy
        self._measure = measure  # the canvas: shown size and unit pitch of a node (size keys)
        self._stepped: object = None  # the selection of the last size key step

    # ------------------------------------------------------------ undo and redo
    @property
    def undo_text(self) -> str | None:
        stack = self.session.stack
        return stack.undo_text if stack is not None else None

    @property
    def redo_text(self) -> str | None:
        stack = self.session.stack
        return stack.redo_text if stack is not None else None

    def can_undo(self) -> bool:
        return self.session.stack is not None and self.session.stack.can_undo

    def can_redo(self) -> bool:
        return self.session.stack is not None and self.session.stack.can_redo

    def undo(self) -> None:
        stack = self.session.stack
        if stack is not None and stack.can_undo and stack.undo() is False:
            self._tell_failure()

    def redo(self) -> None:
        stack = self.session.stack
        if stack is not None and stack.can_redo and stack.redo() is False:
            self._tell_failure()

    def _tell_failure(self) -> None:
        """A step that could not be reverted or re-applied (H37): the stack restored it."""
        stack = self.session.stack
        if stack is not None and (failure := stack.failure) is not None:
            self._message(failure.message)

    # ------------------------------------------------------------ delete
    def can_delete(self) -> bool:
        """Elements and menu nodes; a window is deleted from the Document menu."""
        node = self.session.selection.node
        return self.editable() and isinstance(node, _DELETABLE)

    def editable(self) -> bool:
        """A document is open and may be edited (not read-only: QA-14a2 N3)."""
        return self.session.stack is not None and self.session.read_only_refusal() is None

    def read_only_refusal(self) -> str | None:
        """Why the editing actions are greyed (shown when their shortcut is pressed)."""
        return self.session.read_only_refusal()

    def delete_refusal(self) -> str | None:
        """Why Delete does nothing on the selection, for the status bar (QA-13a-07), or None."""
        node = self.session.selection.node
        if self.session.stack is None:
            return None
        if reason := self.session.read_only_refusal():
            return reason
        return window_delete_hint() if isinstance(node, Window) else None

    def delete(self) -> None:
        """Delete the selected nodes as one step; any of them with children asks first."""
        nodes = _roots(self.session.selection.nodes)
        if not self.can_delete() or not nodes or self._refused():
            return
        count = sum(count_descendants(node) for node in nodes)
        if count == 0:
            self._remove(nodes)
            return
        if len(nodes) == 1:
            # Translators: {id} is the identifier of the selected element and {count} the number
            # of elements inside it.
            question = ngettext(
                "Delete '{id}' and its {count} element?",
                "Delete '{id}' and its {count} elements?",
                count,
            ).format(id=inserted(getattr(nodes[0], "id", "") or node_label(nodes[0])), count=count)
        else:
            # Translators: several selected elements are deleted with what they contain.
            question = ngettext(
                "Delete {count} element and the elements inside it?",
                "Delete {count} elements and the elements inside them?",
                len(nodes),
            ).format(count=len(nodes))
        self._confirm(question, lambda: self._remove(nodes))

    def _holder(self, node: object) -> object | None:
        """The node that holds ``node``: its parent, or the window of a bar (bars have none)."""
        if isinstance(node, Menubar | Statusbar):
            document = self.session.document
            windows = [] if document is None else document.children
            return next((w for w in windows if node in (w.menubar, w.statusbar)), None)
        return getattr(node, "parent", None)

    def _remove(self, nodes: list[object]) -> None:
        parent = self._holder(nodes[-1])
        if any(self._holder(n) is None for n in nodes):
            return  # the document changed while the dialog was open
        bar = nodes[0]
        if isinstance(bar, Menubar | Statusbar):  # a bar is a field of its window (spec 6)
            built: Command = SetField(
                parent, "menubar" if isinstance(bar, Menubar) else "statusbar", None
            )
        else:
            built = delete_command(*nodes)
        if self._run(built):
            self.session.select(parent, origin="session")

    # ------------------------------------------------------------ insert (spec 6)
    def can_insert(self, kind: MenuItem) -> bool:
        """Edit > Insert > ``kind`` applies to the selection (greys the menu entries)."""
        return self.editable() and menu_insert_enabled(self.session.selection.node, kind)

    def insert(self, kind: MenuItem) -> None:
        """Insert a menu bar, menu, action, separator or status bar and select it."""
        selected, document = self.session.selection.node, self.session.document
        if self._refused():
            return
        command = None if document is None else menu_insert_command(document, selected, kind)
        if command is None or not self._run(command):
            return
        # The stack attaches a copy of a bar: read it back from the window (spec 6).
        added = command.node if isinstance(command, InsertNode) else getattr(selected, kind, None)
        self.session.select(added, origin="session")

    def _refused(self) -> bool:
        """True (and the reason is shown) when the document is read-only (before any question)."""
        reason = self.session.read_only_refusal()
        if reason:
            self._message(reason)
        return reason is not None

    def _run(self, built: Command | str) -> bool:
        """Execute ``built`` as one undo step; a refusal goes to the status bar."""
        stack = self.session.stack
        if stack is None or isinstance(built, str):
            self._message(built if isinstance(built, str) else "")
            return False
        stack.break_merge()  # one key press or gesture = one undo step
        outcome = stack.execute(built)
        if not outcome.accepted:
            self._message(outcome.message)
        return outcome.accepted

    # ------------------------------------------------------------ canvas keys (spec 7.3)
    def has_selection(self) -> bool:
        return self.session.stack is not None and self.session.selection.node is not None

    def select_step(self, delta: int) -> None:
        """Tab / Shift+Tab: the next or previous widget of the window, wrapping."""
        primary = self.session.selection.node
        order = tab_order(_window(primary))
        if order:
            at = next((k for k, n in enumerate(order) if n is primary), -1 if delta > 0 else 0)
            self.session.select(order[(at + delta) % len(order)], origin="canvas")

    def select_child(self) -> None:
        """Enter: the first child of the selected container."""
        kids = getattr(self.session.selection.node, "children", ())
        if kids:
            self.session.select(kids[0], origin="canvas")

    def select_parent(self) -> None:
        """Esc: the parent of the primary node; a window stays selected."""
        node = self.session.selection.node
        if node is not None and not isinstance(node, Window):
            self.session.select(getattr(node, "parent", None), origin="canvas")

    def select_all(self) -> None:
        """Ctrl+A: every child of the primary node's container (of a window: its children)."""
        primary = self.session.selection.node
        container = primary if isinstance(primary, Window) else getattr(primary, "parent", None)
        kids = [n for n in getattr(container, "children", ()) if isinstance(n, Widget | Include)]
        if kids:  # the primary stays the primary (the last occurrence decides)
            last = primary if any(primary is k for k in kids) else kids[-1]
            self.session.select_many([*kids, last], origin="canvas")

    def nudge(self, rows: int, columns: int) -> None:
        """Arrows: the selection one cell, or one place along a pack/pages orient."""
        if not self._busy():
            self._moved(nudge_command(self.session.selection.nodes, rows, columns))

    def reorder(self, step: int) -> None:
        """Alt+Up/Down in the tree: the selection one sibling earlier or later."""
        if not self._busy():
            self._moved(reorder_command(self.session.selection.nodes, step))

    def span(self, rows: int, columns: int) -> None:
        """Shift+Arrows: the primary grid child's rowspan/columnspan +-1 (minimum 1)."""
        node = self.session.selection.node
        if self._busy() or not isinstance(node, Widget | Include):
            return
        if not isinstance(cell := node.placement, GridCell):
            self._run(resize_command(node, 0, 0, 1, 1))  # says: only a grid child
            return
        rowspan, columnspan = max(cell.rowspan, 1) + rows, max(cell.columnspan, 1) + columns
        stop = past_the_grid([node], rows, columns)  # QA-13b-02: never past the append cell
        self._run(stop or resize_command(node, cell.row, cell.column, rowspan, columnspan))

    def size_step(self, k: int, step: int) -> None:
        """Ctrl+Shift+Arrows: the primary's width (k 0) or height (k 1) +-1 unit, or a window's
        minimum +-8 px. Steps on one property merge into one undo step until the selection
        changes (a new ``Selection`` object; spec direct-manipulation 4)."""
        node, stack = self.session.selection.node, self.session.stack
        if self._busy() or node is None or stack is None or self._refused():
            return
        spec = self.session.registry.get(getattr(node, "class_name", ""))
        built = step_command(node, spec, k, step, self._measure(node))
        if isinstance(built, str):
            self._message(built)
            return
        if self.session.selection is not self._stepped:
            stack.break_merge()
            self._stepped = self.session.selection
        outcome = stack.execute(built)
        if not outcome.accepted:
            self._message(outcome.message)

    def _moved(self, built: Command | str) -> None:
        nodes = self.session.selection.nodes
        if self._run(built):
            self.session.select_many(nodes, origin="canvas")
