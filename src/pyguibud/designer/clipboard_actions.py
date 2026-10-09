"""Copy, cut, paste and duplicate for the Edit menu (pure; spec properties-save-load 8).

The system clipboard is two seams (``put`` and ``get``), so this module has no Tk and the
tests can use a plain string. Every model change is one command; a refusal is a status message.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pyguibud.core.commands import Command
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
from pyguibud.designer.clipboard import (
    Pasted,
    copy_text,
    cut_command,
    duplicate_command,
    paste_command,
    pasted_message,
)
from pyguibud.designer.session import DesignerSession

__all__ = ["ClipboardActions"]

#: Selections that copy, cut and duplicate answer: elements, or menu nodes (with their reason).
_COPYABLE = (Window, Widget, Include, Menubar, Menu, Action, MenuSeparator, Statusbar)


class ClipboardActions:
    """What Edit > Cut, Copy, Paste and Duplicate (Ctrl+X/C/V/D) call."""

    def __init__(
        self,
        session: DesignerSession,
        message: Callable[[str], None],
        put: Callable[[str], None],
        get: Callable[[], str],
        current_window: Callable[[], object | None] = lambda: None,
    ) -> None:
        self.session, self._message, self._put, self._get = session, message, put, get
        self._current_window = current_window

    # ------------------------------------------------------------ state
    def can_copy(self) -> bool:
        """Something is selected that can be asked to copy (no ValueError: spec 8 contract)."""
        nodes = self.session.selection.nodes
        return self.session.stack is not None and any(isinstance(n, _COPYABLE) for n in nodes)

    def can_paste(self) -> bool:
        return self._editable() and self._target() is not None

    def can_cut(self) -> bool:
        """Cut and Duplicate: as Copy, but greyed in a read-only document (QA-14a2 N3)."""
        return self.can_copy() and self._editable()

    def read_only_refusal(self) -> str | None:
        """Why Cut, Paste and Duplicate are greyed (shown when their shortcut is pressed)."""
        return self.session.read_only_refusal()

    def _editable(self) -> bool:
        return self.session.stack is not None and self.session.read_only_refusal() is None

    def _target(self) -> object | None:
        node = self.session.selection.node
        return node if node is not None else self._current_window()

    def _origin(self) -> Path | None:
        return self.session.path

    # ------------------------------------------------------------ actions
    def copy(self) -> None:
        document = self.session.document
        if document is None or not self.can_copy():
            return
        copied = copy_text(document, self.session.selection.nodes, self._origin())
        if isinstance(copied, str):
            self._message(copied)
        else:
            self._put(copied.text)

    def _refused(self) -> bool:
        """True (and the reason is shown) when the document is read-only: Copy still works."""
        reason = self.session.read_only_refusal()
        if reason:
            self._message(reason)
        return reason is not None

    def cut(self) -> None:
        document, nodes = self.session.document, self.session.selection.nodes
        if document is None or not self.can_copy() or self._refused():
            return
        built = cut_command(document, nodes, self._origin())
        if isinstance(built, str):
            self._message(built)
            return
        copied, command = built
        parent = getattr(nodes[-1], "parent", None)
        if self._run(command):
            self._put(copied.text)  # the clipboard changes only when the cut happened
            kept = document.children
            self.session.select(parent if isinstance(parent, Window | Widget) else (
                kept[0] if kept else None), origin="session")  # fmt: skip

    def paste(self) -> None:
        document, target = self.session.document, self._target()
        if document is None or target is None or self._refused():
            return
        base = self._origin()
        pasted = paste_command(
            document, target, self._get(), self.session.registry, base.parent if base else None
        )
        self._finish(pasted)

    def duplicate(self) -> None:
        document = self.session.document
        if document is not None and self.can_copy() and not self._refused():
            self._finish(
                duplicate_command(document, self.session.selection.nodes, self.session.registry)
            )

    def _finish(self, pasted: Pasted | str) -> None:
        """Run the paste; select what it added, then say how many (rule C1: after the selection)."""
        if isinstance(pasted, str):
            self._message(pasted)
        elif self._run(pasted.command):
            self.session.select_many(pasted.nodes, origin="session")
            self._message(pasted_message(len(pasted.nodes), pasted.warnings))

    def _run(self, command: Command) -> bool:
        stack = self.session.stack
        if stack is None:
            return False
        stack.break_merge()  # one key press = one undo step
        outcome = stack.execute(command)
        if not outcome.accepted:
            self._message(outcome.message)
        return outcome.accepted
