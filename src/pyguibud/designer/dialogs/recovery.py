"""The start-up recovery list: Restore / Discard / Later (Tk; spec 14a section 11.3, D6)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from pyguibud.core import ReadResult, XmlIoError
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.recovery import RecoveryEntry
from pyguibud.i18n import N_, _

__all__ = ["RecoveryDialog"]

_M_TITLE = N_("Recover unsaved work")
# Translators: _ marks the access key (Alt+letter); keep it unique within the dialog.
_M_RESTORE = N_("_Restore")
_M_DISCARD = N_("_Discard")
# Translators: keep the recovered copies for the next start (or File > Recover...).
_M_LATER = N_("_Later")
# Translators: a recovered copy that cannot be read any more; only Discard is possible.
_M_DAMAGED = N_("damaged")
# Translators: {name} is a file name such as "main.ui", or "Untitled".
_M_DISCARD_QUESTION = N_("Discard the recovered copy of '{name}'?")


class RecoveryDialog(ModalDialog):
    """Lists orphan snapshots; ``restore(entry, result)`` runs after the dialog has closed.

    ``confirm(question, then)`` asks before a Discard (a nested dialog). ``later`` runs when the
    dialog closes without a restore (Later, Esc, or the last entry discarded).
    """

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        entries: Sequence[RecoveryEntry],
        *,
        restore: Callable[[RecoveryEntry, ReadResult], None],
        confirm: Callable[[str, Callable[[], None]], None],
        later: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(root)
        self._entries = {str(index): entry for index, entry in enumerate(entries)}
        self._damaged: set[str] = set()
        self._restore, self._confirm, self._later = restore, confirm, later
        rows = min(8, max(3, len(entries)))
        self.tree = ttk.Treeview(self.body, columns=("path", "time"), show="tree",
                                 selectmode="browse", height=rows)  # fmt: skip
        self.tree.column("#0", width=int(root.winfo_fpixels("1.6i")))
        self.tree.column("path", width=int(root.winfo_fpixels("2.6i")))
        self.tree.pack(fill="both", expand=True)
        for iid, entry in self._entries.items():
            when = entry.saved_at.astimezone().strftime("%Y-%m-%d %H:%M")
            self.tree.insert("", "end", iid=iid, text=entry.display_name,
                             values=(entry.path or "", when))  # fmt: skip
        row = ttk.Frame(self.body)
        row.pack(side="bottom", anchor="e", pady=(12, 0))
        self.buttons = [
            (ttk.Button(row, command=self.restore, default="active"), _M_RESTORE),
            (ttk.Button(row, command=self.discard), _M_DISCARD),
            (ttk.Button(row, command=self.close), _M_LATER),
        ]
        for button, _msgid in self.buttons:
            button.pack(side="left", padx=(6, 0))
        self.access_keys = self.buttons
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons(), add="+")
        self.tree.bind("<Return>", lambda _e: self.restore())
        self.tree.bind("<Delete>", lambda _e: self.discard())
        first = next(iter(self._entries), None)
        if first is not None:
            self.tree.selection_set(first)
            self.tree.focus(first)

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The list (Enter restores, Delete discards, Tab reaches the buttons)."""
        return self.tree

    def retranslate(self) -> None:
        self.label_buttons()
        for iid in self._damaged:
            self.tree.set(iid, "time", _(_M_DAMAGED))
        super().retranslate()

    def _current(self) -> str | None:
        picked = self.tree.selection()
        return str(picked[0]) if picked else None

    def _update_buttons(self) -> None:
        current = self._current()
        usable = current is not None and current not in self._damaged
        self.buttons[0][0].state(["!disabled"] if usable else ["disabled"])

    def restore(self) -> None:
        """Read the selected snapshot; a damaged one is marked and only Discard stays (A7)."""
        iid = self._current()
        if iid is None or iid in self._damaged:
            return
        entry = self._entries[iid]
        try:
            result = entry.read()
        except (XmlIoError, OSError):
            self._damaged.add(iid)
            self.tree.set(iid, "time", _(_M_DAMAGED))
            self._update_buttons()
            return
        self._later = None
        self.close()
        self._restore(entry, result)

    def discard(self) -> None:
        """Delete the selected snapshot after a confirmation."""
        iid = self._current()
        if iid is None:
            return
        entry = self._entries[iid]

        def drop() -> None:
            if not entry.discard():
                return  # its process is alive after all: never delete it
            self.tree.delete(iid)
            self._entries.pop(iid, None)
            self._damaged.discard(iid)
            remaining = self.tree.get_children()
            if not remaining:
                self.close()
                return
            self.tree.selection_set(remaining[0])
            self.tree.focus(remaining[0])

        self._confirm(_(_M_DISCARD_QUESTION).format(name=entry.display_name), drop)

    def close(self) -> None:
        later, self._later = self._later, None
        was_open = not self.closed
        super().close()
        if was_open and later is not None:
            later()
