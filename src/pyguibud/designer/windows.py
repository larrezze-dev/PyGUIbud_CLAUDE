"""Document menu actions (pure; spec properties-save-load 7): add, rename, delete, switch windows.

Every change is one command on the stack; a refusal is shown as the validator's reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pyguibud.core.commands import Command
from pyguibud.core.model import Window
from pyguibud.core.text import printable
from pyguibud.designer.editing import (
    M_EXTERNAL_INCLUDES,
    delete_window_command,
    new_window,
    rename_window,
    window_delete_refusal,
)
from pyguibud.designer.present.canvas import window_of
from pyguibud.designer.session import DesignerSession
from pyguibud.i18n import N_, _

__all__ = ["AskName", "WindowActions", "WindowKind"]

WindowKind = Literal["main", "dialog", "component"]

_M_DELETE_WINDOW = N_("Delete the window '{id}' and everything in it?")

#: ``(current id, check, then)``: ask for a name; ``check`` judges a text, ``then`` gets the result.
AskName = Callable[[str, Callable[[str], str | None], Callable[[str], None]], None]


class WindowActions:
    """What the Document menu calls; ``message`` shows a refusal in the status bar."""

    def __init__(
        self,
        session: DesignerSession,
        confirm: Callable[[str, Callable[[], None]], None],
        message: Callable[[str], None],
        ask_name: AskName,
    ) -> None:
        self.session, self._confirm = session, confirm
        self._message, self._ask_name = message, ask_name

    # ------------------------------------------------------------ state
    def can_edit(self) -> bool:
        """A document is open (Add main window, dialog, component)."""
        return self.session.stack is not None

    def selected(self) -> Window | None:
        """The selected node when it is a window (Rename and Delete act on it)."""
        node = self.session.selection.node
        return node if self.can_edit() and isinstance(node, Window) else None

    def has_selected(self) -> bool:
        return self.selected() is not None

    def can_add(self) -> bool:
        """Add a window: a document is open and not read-only (QA-14a2 N3)."""
        return self.can_edit() and self.session.read_only_refusal() is None

    def can_change(self) -> bool:
        """Rename or delete the selected window: as ``has_selected``, not read-only."""
        return self.has_selected() and self.session.read_only_refusal() is None

    def read_only_refusal(self) -> str | None:
        """Why the Document actions are greyed (shown when their shortcut is pressed)."""
        return self.session.read_only_refusal()

    def can_step(self) -> bool:
        document = self.session.document
        return document is not None and len(document.children) > 1

    # ------------------------------------------------------------ add, rename, delete
    def add(self, kind: WindowKind) -> None:
        """A new empty window, selected; a second main window shows the guard's reason."""
        document = self.session.document
        if document is not None and not self._refused() and self._run(new_window(document, kind)):
            self.session.select(document.children[-1], origin="session")

    def rename(self) -> None:
        """Ask for a new id; the dialog judges it with a dry run before it closes."""
        window, document = self.selected(), self.session.document
        if window is None or document is None or self._refused():
            return

        def refusal(new: str) -> str | None:
            stack = self.session.stack
            outcome = stack.check(rename_window(document, window, new)) if stack else None
            return None if outcome is None or outcome.accepted else outcome.message

        def apply(new: str) -> None:
            renamed = new != window.id and self._run(rename_window(document, window, new))
            if renamed and window.kind == "component":  # others may include it by its old id
                self._message(_(M_EXTERNAL_INCLUDES))

        self._ask_name(window.id, refusal, apply)

    def delete(self) -> None:
        """Delete the selected window after a confirmation, unless the guard refuses."""
        window, document = self.selected(), self.session.document
        if window is None or document is None or self._refused():
            return
        if reason := window_delete_refusal(document, window):
            self._message(reason)
            return
        question = _(_M_DELETE_WINDOW).format(id=printable(window.id))
        self._confirm(question, lambda: self._remove(window))

    def _remove(self, window: Window) -> None:
        document = self.session.document
        if document is None or window.parent is not document:
            return  # the document changed while the dialog was open
        at = document.index_of(window)
        built = delete_window_command(document, window)
        if self._run(built):
            kept = document.children
            self.session.select(kept[min(at, len(kept) - 1)] if kept else None, origin="session")

    def step(self, delta: int) -> None:
        """Ctrl+PageDown / Ctrl+PageUp: select the next or previous window, wrapping."""
        document = self.session.document
        if document is None or not self.can_step():
            return
        windows = list(document.children)
        current = window_of(self.session.selection.node, document)
        at = next((k for k, w in enumerate(windows) if w is current), -1 if delta > 0 else 0)
        self.session.select(windows[(at + delta) % len(windows)], origin="session")

    def _refused(self) -> bool:
        """True (and the reason is shown) when the document is read-only (before any dialog)."""
        reason = self.session.read_only_refusal()
        if reason:
            self._message(reason)
        return reason is not None

    def _run(self, built: Command | str) -> bool:
        stack = self.session.stack
        if stack is None or isinstance(built, str):
            self._message(built if isinstance(built, str) else "")
            return False
        stack.break_merge()
        outcome = stack.execute(built)
        if not outcome.accepted:
            self._message(outcome.message)
        return outcome.accepted
