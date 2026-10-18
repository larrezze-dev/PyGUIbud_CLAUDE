"""The keyboard-shortcut cheat-sheet (F1), generated from the action registry (Tk)."""

from __future__ import annotations

from tkinter import ttk
from typing import Any

from pyguibud.core.errors import format_message
from pyguibud.designer.actions import ActionRegistry
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.panels.canvas import focus_hint
from pyguibud.i18n import N_, _

__all__ = ["ShortcutsDialog"]

_M_TITLE = N_("Keyboard shortcuts")
# Translators: the Close button of the shortcuts sheet; _ marks the access key (Alt+letter).
_M_CLOSE = N_("_Close")
_M_EMPTY = N_("There are no keyboard shortcuts.")
# Translators: a note under the shortcut list (spec preview-export 3). {key} is the key Ctrl+E,
# inserted as it is (key names are not translated).
_M_EXPORT_NOTE = N_(
    "{key} exports from anywhere in the main window, also from a text field (where some "
    "systems also move the cursor to the end of the line)."
)


class ShortcutsDialog(ModalDialog):
    """Every shortcut grouped by menu; rows are re-read from the registry on each retranslate."""

    TITLE = _M_TITLE

    def __init__(self, root: Any, registry: ActionRegistry) -> None:  # noqa: ANN401 - app root
        super().__init__(root)
        self.registry = registry
        self.rows = ttk.Frame(self.body)
        self.rows.pack(fill="both", expand=True)
        self.rows.columnconfigure(1, weight=1)
        self.close_button = ttk.Button(self.body, command=self.close, default="active")
        self.close_button.pack(side="bottom", anchor="e", pady=(12, 0))
        self.access_keys = [(self.close_button, _M_CLOSE)]
        self.window.bind("<Return>", lambda _e: self.close())

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The Close button."""
        return self.close_button

    def retranslate(self) -> None:
        """Rebuild the rows in the current language."""
        for child in self.rows.winfo_children():
            child.destroy()
        self.label_buttons()
        sheet = self.registry.cheat_sheet()
        if not sheet:
            ttk.Label(self.rows, text=_(_M_EMPTY)).grid(row=0, column=0, columnspan=2)
        row = 0
        current = None
        for entry in sheet:
            if entry.menu != current:
                current = entry.menu
                heading = ttk.Label(self.rows, text=entry.menu, anchor="w", font="TkHeadingFont")
                heading.grid(row=row, column=0, columnspan=2, sticky="w", pady=(6 if row else 0, 2))
                row += 1
            ttk.Label(self.rows, text=entry.label, anchor="w").grid(
                row=row, column=0, sticky="w", padx=(12, 24)
            )
            ttk.Label(self.rows, text=entry.accelerator, anchor="e").grid(
                row=row, column=1, sticky="e"
            )
            row += 1
        # The canvas keeps Tab for itself; F6 is the way out (spec 7.4, no keyboard trap).
        ttk.Label(self.rows, text=focus_hint(), anchor="w").grid(
            row=row, column=0, columnspan=2, sticky="w", pady=(12, 0)
        )
        if any(entry.accelerator == "Ctrl+E" for entry in sheet):
            note = ttk.Label(
                self.rows,
                text=format_message(_M_EXPORT_NOTE, {"key": "Ctrl+E"}),
                anchor="w",
                justify="left",
                wraplength=self.root.winfo_fpixels("4i"),
            )
            note.grid(row=row + 1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        super().retranslate()
