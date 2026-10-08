"""A text and a row of buttons (Tk): the one-OK message and every few-answer question.

Enter presses the focused button (else the default one), Esc closes without an answer, and an
Alt+letter presses the button whose label marks that letter with ``_``. The dialog closes
before it runs the answer, so the answer may open the next dialog.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Sequence
from tkinter import ttk
from typing import Any

from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.i18n import N_

__all__ = ["ChoiceDialog", "message_dialog"]

# Translators: the OK button of a message; _ marks the access key (Alt+letter).
_M_OK = N_("_OK")
_TITLE = "PyGUIbud"  # the product name: never translated

Answer = Callable[[], object] | None


class ChoiceDialog(ModalDialog):
    """Shows ``text()`` (re-read on a language switch) and one button per ``(msgid, answer)``."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        text: Callable[[], str],
        buttons: Sequence[tuple[str, Answer]],
        *,
        default: int = 0,
        title: str = _TITLE,
    ) -> None:
        super().__init__(root)
        self.TITLE = title
        self._text = text
        self._default = default
        self.label = ttk.Label(self.body, wraplength=root.winfo_fpixels("3.5i"), justify="left")
        self.label.pack(anchor="w")
        row = ttk.Frame(self.body)
        row.pack(side="bottom", anchor="e", pady=(12, 0))
        self.buttons: list[tuple[ttk.Button, str, Answer]] = []
        for index, (msgid, answer) in enumerate(buttons):
            button = ttk.Button(row, command=functools.partial(self.press, index),
                                default="active" if index == default else "normal")  # fmt: skip
            button.pack(side="left", padx=(6 if index else 0, 0))
            self.buttons.append((button, msgid, answer))
        self.access_keys = [(button, msgid) for button, msgid, _answer in self.buttons]
        self.window.bind("<Return>", self._on_return)

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The default button."""
        return self.buttons[self._default][0]

    def retranslate(self) -> None:
        self.label.configure(text=self._text())
        self.label_buttons()
        super().retranslate()

    def press(self, index: int) -> None:
        """Close, then run the answer of button ``index`` (None answers only close)."""
        answer = self.buttons[index][2]
        self.close()
        if answer is not None:
            answer()

    def _on_return(self, _event: object) -> str:
        focused = self.window.focus_get()
        hits = [i for i, (button, _m, _a) in enumerate(self.buttons) if button is focused]
        self.press(hits[0] if hits else self._default)
        return "break"


def message_dialog(root: Any, text: Callable[[], str]) -> ChoiceDialog:  # noqa: ANN401
    """An error or information message with one OK button (spec 14a section 1)."""
    return ChoiceDialog(root, text, [(_M_OK, None)])
