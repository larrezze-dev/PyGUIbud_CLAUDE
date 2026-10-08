"""A yes/no question before a destructive action (Tk). The caller's callback runs on confirm."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk
from typing import Any

from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.i18n import N_

__all__ = ["ConfirmDialog"]

_M_TITLE = N_("Confirm")
# Translators: _ marks the access key (Alt+letter); keep it unique within the dialog.
_M_DELETE = N_("_Delete")
_M_CANCEL = N_("_Cancel")


class ConfirmDialog(ModalDialog):
    """Shows ``question``; Enter or the Delete button confirms, Esc or Cancel keeps everything."""

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        question: str,
        on_confirm: Callable[[], None],
        *,
        confirm_label: str = _M_DELETE,
    ) -> None:
        super().__init__(root)
        self._on_confirm = on_confirm
        ttk.Label(self.body, text=question, wraplength=self.root.winfo_fpixels("3.5i")).pack(
            anchor="w"
        )
        row = ttk.Frame(self.body)
        row.pack(side="bottom", anchor="e", pady=(12, 0))
        self.cancel_button = ttk.Button(row, command=self.close)
        self.confirm_button = ttk.Button(row, command=self.confirm, default="active")
        self.cancel_button.pack(side="right", padx=(6, 0))
        self.confirm_button.pack(side="right")
        self.access_keys = [(self.confirm_button, confirm_label), (self.cancel_button, _M_CANCEL)]
        self.window.bind("<Return>", lambda _e: self.confirm())

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The Delete button (the default; Tab reaches Cancel)."""
        return self.confirm_button

    def retranslate(self) -> None:
        self.label_buttons()
        super().retranslate()

    def confirm(self) -> None:
        """Close, then run the callback."""
        self.close()
        self._on_confirm()
