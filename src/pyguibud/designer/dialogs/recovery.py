"""The start-up recovery list: Restore / Discard / Later (Tk; spec 14a section 11.3, D6)."""

from __future__ import annotations

import contextlib
import tkinter
from collections.abc import Callable, Sequence
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from pyguibud.core import ReadResult, XmlIoError
from pyguibud.core.text import printable
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.present import elide_middle
from pyguibud.designer.recovery import RecoveryEntry
from pyguibud.designer.theme_tk import LIST_STYLE, STYLE_MUTED, space
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
_M_NAME = N_("Name")
_M_LOCATION = N_("Location")
_M_SAVED = N_("Saved")
# Translators: shown instead of a location for work that was never saved to a file.
_M_NOT_SAVED = N_("(not saved)")
# Translators: {path} is the full path of the file the selected recovered copy belongs to.
_M_WHERE = N_("Location: {path}")


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
        self.tree = ttk.Treeview(self.body, columns=("path", "time"), show="tree headings",
                                 selectmode="browse", height=rows, style=LIST_STYLE)  # fmt: skip
        self.tree.column("#0", width=int(root.winfo_fpixels("1.6i")), stretch=False)
        self.tree.column("path", width=int(root.winfo_fpixels("2.6i")), stretch=True)
        self.tree.column("time", width=int(root.winfo_fpixels("1.3i")), stretch=False)
        self.tree.tag_configure("muted", foreground=ttk.Style().lookup(STYLE_MUTED, "foreground"))
        self.tree.pack(fill="both", expand=True)
        for iid, entry in self._entries.items():
            when = entry.saved_at.astimezone().strftime("%Y-%m-%d %H:%M")
            self.tree.insert("", "end", iid=iid, text=entry.display_name, values=("", when))
        # The whole path of the selected entry: the column only shows it elided.
        self.where = ttk.Label(self.body, style=STYLE_MUTED, justify="left",
                               wraplength=int(root.winfo_fpixels("4.5i")))  # fmt: skip
        self.where.pack(fill="x", pady=(space(root, "s"), 0))
        self._headings()
        self._locations()
        self._fit_job: str | None = None
        self.tree.bind("<Configure>", self._schedule_locations, add="+")
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
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_where(), add="+")
        self.tree.bind("<Return>", lambda _e: self.restore())
        self.tree.bind("<Delete>", lambda _e: self.discard())
        first = next(iter(self._entries), None)
        if first is not None:
            self.tree.selection_set(first)
            self.tree.focus(first)
        self._show_where()

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The list (Enter restores, Delete discards, Tab reaches the buttons)."""
        return self.tree

    def _headings(self) -> None:
        for column, msgid in (("#0", _M_NAME), ("path", _M_LOCATION), ("time", _M_SAVED)):
            self.tree.heading(column, text=_(msgid))

    def _schedule_locations(self, _event: object = None) -> None:
        """Re-elide once Tk is idle: at the tree's ``<Configure>`` the Treeview has not yet
        resized its stretchable column, so its width is still the old one (QA-14p-05)."""
        if self._fit_job is not None or self.closed:
            return
        with contextlib.suppress(tkinter.TclError):
            self._fit_job = self.tree.after_idle(self._refit)

    def _refit(self) -> None:
        self._fit_job = None
        if not self.closed:
            self._locations()

    def _locations(self) -> None:
        """Show each path cut in the middle to the column width (the file name stays).

        Always from the full path, and measured in pixels with the tree's font, so wide glyphs
        (CJK, "W") fit as well (QA-14p-06).
        """
        name = str(ttk.Style(self.tree).lookup("Treeview", "font") or "TkDefaultFont")
        try:
            font = tkfont.nametofont(name)
        except tkinter.TclError:
            font = tkfont.nametofont("TkDefaultFont")
        padding = 2 * font.measure("m")  # the cell margin Tk keeps around the text
        pixels = max(1, int(self.tree.column("path", "width")) - padding)
        for iid, entry in self._entries.items():
            path = entry.path
            shown = elide_middle(path, pixels, font.measure) if path else _(_M_NOT_SAVED)
            self.tree.set(iid, "path", shown)
            self.tree.item(iid, tags=() if path else ("muted",))

    def _show_where(self) -> None:
        current = self._current()
        path = self._entries[current].path if current in self._entries else None
        self.where.configure(
            text=_(_M_WHERE).format(path=printable(path) if path else _(_M_NOT_SAVED))
        )

    def retranslate(self) -> None:
        self.label_buttons()
        self._headings()
        self._locations()
        self._show_where()
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

        self._confirm(_(_M_DISCARD_QUESTION).format(name=printable(entry.display_name)), drop)

    def close(self) -> None:
        job, self._fit_job = self._fit_job, None
        if job is not None:
            with contextlib.suppress(tkinter.TclError):
                self.tree.after_cancel(job)
        later, self._later = self._later, None
        was_open = not self.closed
        super().close()
        if was_open and later is not None:
            later()
