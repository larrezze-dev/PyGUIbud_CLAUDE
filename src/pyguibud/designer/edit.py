"""Edit actions (pure; spec dnd-selection 11): undo, redo and delete on the session's stack.

Every change goes through the command stack. Delete asks for confirmation (through the
``confirm`` callback, which opens a dialog and returns at once) when the node has children.
"""

from __future__ import annotations

from collections.abc import Callable

from pyguibud.core.model import (
    Action,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.designer.editing import delete_command
from pyguibud.designer.session import DesignerSession
from pyguibud.i18n import N_, _, ngettext

__all__ = ["EditActions", "count_descendants"]

_M_NOT_DELETABLE = N_("Windows, menu bars and status bars cannot be deleted here.")
_M_MENU_EDITOR = N_("Menus and actions are edited in the menu editor.")

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


class EditActions:
    """What the Edit menu calls; ``message`` shows a refusal in the status bar."""

    def __init__(
        self, session: DesignerSession, confirm: Confirm, message: Callable[[str], None]
    ) -> None:
        self.session, self._confirm, self._message = session, confirm, message

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
        if self.session.stack is not None:
            self.session.stack.undo()

    def redo(self) -> None:
        if self.session.stack is not None:
            self.session.stack.redo()

    # ------------------------------------------------------------ delete
    def can_delete(self) -> bool:
        """Only widgets and includes: windows and bars belong to the Step 14 editors."""
        node = self.session.selection.node
        return self.session.stack is not None and isinstance(node, Widget | Include)

    def delete_refusal(self) -> str | None:
        """Why Delete does nothing on the selection, for the status bar (QA-13a-07), or None."""
        node = self.session.selection.node
        if self.session.stack is None:
            return None
        if isinstance(node, Window | Menubar | Statusbar):
            return _(_M_NOT_DELETABLE)
        if isinstance(node, Menu | Action | MenuSeparator):
            return _(_M_MENU_EDITOR)
        return None

    def delete(self) -> None:
        """Delete the selected node; a node with children asks first."""
        node = self.session.selection.node
        if not self.can_delete() or node is None:
            return
        count = count_descendants(node)
        if count == 0:
            self._remove(node)
            return
        question = ngettext(
            "Delete '{id}' and its {count} element?",
            "Delete '{id}' and its {count} elements?",
            count,
        ).format(id=getattr(node, "id", ""), count=count)
        self._confirm(question, lambda: self._remove(node))

    def _remove(self, node: object) -> None:
        stack, parent = self.session.stack, getattr(node, "parent", None)
        if stack is None or parent is None:  # the document changed while the dialog was open
            return
        stack.break_merge()  # one gesture = one undo step
        outcome = stack.execute(delete_command(node))
        if not outcome.accepted:
            self._message(outcome.message)
            return
        self.session.select(parent, origin="session")
