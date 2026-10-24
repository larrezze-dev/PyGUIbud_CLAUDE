"""A one-line text entry that judges its text before it closes (Tk); renames a window."""

from __future__ import annotations

import tkinter
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from pyguibud.core.text import printable
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.panels.editors import _M_CLIPPED
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT, clip_text
from pyguibud.designer.theme_tk import INVALID_PREFIX, STYLE_ENTRY
from pyguibud.i18n import N_, _

__all__ = ["RenameDialog"]

_M_TITLE = N_("Rename window")
_M_ID = N_("Id")
# Translators: the buttons of the rename dialog; _ marks the access key (Alt+letter).
_M_OK = N_("_OK")
_M_CANCEL = N_("_Cancel")


class RenameDialog(ModalDialog):
    """Asks for a new id. ``check`` judges the text first: a reason keeps the dialog open
    with the typed text (as the text dialog does, QA-14a1-20); ``on_ok`` gets the accepted one."""

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        current: str,
        check: Callable[[str], str | None],
        on_ok: Callable[[str], None],
    ) -> None:
        super().__init__(root)
        self._check, self._on_ok = check, on_ok
        self._length = len(current)  # over the limit: a read-only clip, never committed (19f-08)
        self._long = self._length > CANVAS_TEXT_LIMIT
        self.value = tkinter.StringVar(root, value=clip_text(current))
        self.label = ttk.Label(self.body)
        self.label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.entry = ttk.Entry(self.body, textvariable=self.value, width=32, style=STYLE_ENTRY)
        self.entry.grid(row=0, column=1, sticky="ew")
        if self._long:
            self.entry.state(["readonly"])
        self.body.columnconfigure(1, weight=1)
        style = "TLabel" if self._long else f"{INVALID_PREFIX}.TLabel"  # the long id's note
        self.reason = ttk.Label(self.body, style=style, justify="left",
                                wraplength=self.root.winfo_fpixels("4i"))  # fmt: skip
        self.reason.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        if not self._long:  # a long id says why it cannot be typed (QA-19g-06)
            self.reason.grid_remove()
        self.entry.bind("<Key>", lambda _e: self._clear_reason(), add="+")
        buttons = ttk.Frame(self.body)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.cancel_button = ttk.Button(buttons, command=self.close)
        self.ok_button = ttk.Button(buttons, command=self.accept, default="active")
        self.cancel_button.pack(side="right", padx=(6, 0))
        self.ok_button.pack(side="right")
        self.access_keys = [(self.ok_button, _M_OK), (self.cancel_button, _M_CANCEL)]
        self.window.bind("<Return>", lambda _e: self.accept())

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        return self.entry

    def open(self) -> None:
        super().open()
        self.entry.select_range(0, "end")

    def retranslate(self) -> None:
        self.label.configure(text=_(_M_ID))
        self.label_buttons()
        if self._long:
            self.reason.configure(text=_(_M_CLIPPED).format(
                id=_(_M_ID), length=self._length, limit=CANVAS_TEXT_LIMIT))  # fmt: skip
        elif self.reason.winfo_manager():  # the reason's language
            self.reason.configure(text=printable(self._check(self.value.get().strip(" ")) or ""))
        super().retranslate()

    def _clear_reason(self) -> None:
        if self.reason.winfo_manager() and not self._long:
            self.reason.grid_remove()
            self.fit()

    def accept(self) -> None:
        """Close and hand over the id; a refusal keeps the dialog open and says why."""
        if self._long:
            self.close()
            return
        text = self.value.get().strip(" ")  # spaces only: "x" + a newline is refused (QA-19c-09)
        refusal = self._check(text)
        if refusal:
            self.reason.configure(text=printable(refusal))  # it quotes the typed id (H81)
            self.reason.grid()
            self.fit()
            self.entry.focus_set()
            return
        self.close()
        self._on_ok(text)
