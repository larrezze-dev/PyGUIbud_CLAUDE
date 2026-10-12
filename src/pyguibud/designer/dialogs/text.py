"""Multi-line text of a property, with its translation data (Tk; spec properties-save-load 3.2)."""

from __future__ import annotations

import tkinter
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import Any

from pyguibud.core.model import Prop
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.theme_tk import INVALID_PREFIX
from pyguibud.i18n import N_, _

__all__ = ["TextDialog"]

_M_TITLE = N_("Edit text")
_M_TRANSLATABLE = N_("Translatable")
# Translators: the gettext context (msgctxt) that tells translators apart equal source texts.
_M_CONTEXT = N_("Context")
# Translators: a note for translators stored with the text.
_M_COMMENT = N_("Comment")
# Translators: the buttons of the text dialog; _ marks the access key (Alt+letter).
_M_OK = N_("_OK")
_M_CANCEL = N_("_Cancel")


class TextDialog(ModalDialog):
    """Edits ``prop``; OK (or Ctrl+Enter) calls ``on_ok`` with the new Prop, Esc cancels.

    ``check`` (optional) judges the edited Prop before the dialog closes: a returned reason is
    shown in the dialog, which stays open with the typed text (QA-14a1-20).
    """

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        prop: Prop,
        on_ok: Callable[[Prop], None],
        *,
        translatable: bool,
        check: Callable[[Prop], str | None] | None = None,
    ) -> None:
        super().__init__(root)
        self.prop, self._on_ok, self._i18n, self._check = prop, on_ok, translatable, check
        self.text = tkinter.Text(self.body, width=48, height=6, wrap="word", undo=True)
        self.text.insert("1.0", prop.value)
        self.text.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.body.columnconfigure(1, weight=1)
        self.body.rowconfigure(0, weight=1)
        self.translatable = tkinter.BooleanVar(root, value=prop.translatable)
        self.context = tkinter.StringVar(root, value=prop.context or "")
        self.comment = tkinter.StringVar(root, value=prop.comment or "")
        self.labels: list[tuple[Any, str]] = []
        if translatable:
            box = ttk.Checkbutton(self.body, variable=self.translatable)
            box.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
            self.labels.append((box, _M_TRANSLATABLE))
            for row, (msgid, var) in enumerate(
                ((_M_CONTEXT, self.context), (_M_COMMENT, self.comment)), start=2
            ):
                label = ttk.Label(self.body)
                label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=(4, 0))
                ttk.Entry(self.body, textvariable=var).grid(row=row, column=1, sticky="ew")
                self.labels.append((label, msgid))
        # The reason a refusal gives; hidden until OK is refused.
        self.reason = ttk.Label(self.body, style=f"{INVALID_PREFIX}.TLabel", justify="left",
                                wraplength=self.root.winfo_fpixels("4i"))  # fmt: skip
        self.reason.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.reason.grid_remove()
        self.text.bind("<Key>", lambda _e: self._clear_reason(), add="+")
        buttons = ttk.Frame(self.body)
        buttons.grid(row=9, column=0, columnspan=2, sticky="e", pady=(12, 0))
        self.cancel_button = ttk.Button(buttons, command=self.close)
        self.ok_button = ttk.Button(buttons, command=self.accept, default="active")
        self.cancel_button.pack(side="right", padx=(6, 0))
        self.ok_button.pack(side="right")
        self.access_keys = [(self.ok_button, _M_OK), (self.cancel_button, _M_CANCEL)]
        # Enter adds a line in the text; Ctrl+Enter is OK anywhere in the dialog.
        self.window.bind("<Control-Return>", lambda _e: self.accept())

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        return self.text

    def retranslate(self) -> None:
        for widget, msgid in self.labels:
            widget.configure(text=_(msgid))
        self.label_buttons()
        if self.reason.winfo_manager() and self._check is not None:  # the reason's language
            self.reason.configure(text=self._check(self.result()) or "")
        super().retranslate()

    def result(self) -> Prop:
        """The edited property (the trailing newline Tk adds is dropped)."""
        value = self.text.get("1.0", "end-1c")
        if not self._i18n:
            return replace(self.prop, value=value)
        return replace(
            self.prop,
            value=value,
            translatable=self.translatable.get(),
            context=self.context.get() or None,
            comment=self.comment.get() or None,
        )

    def _clear_reason(self) -> None:
        if self.reason.winfo_manager():
            self.reason.grid_remove()
            self.fit()

    def accept(self) -> None:
        """Close, then hand the edited property to the caller; a refusal keeps the dialog open."""
        prop = self.result()
        refusal = self._check(prop) if self._check is not None else None
        if refusal:
            self.reason.configure(text=refusal)
            self.reason.grid()
            self.fit()
            self.text.focus_set()
            return
        self.close()
        self._on_ok(prop)
