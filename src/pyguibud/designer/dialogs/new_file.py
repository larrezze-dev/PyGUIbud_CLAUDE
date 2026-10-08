"""The "New from template" wizard (Ctrl+N): pick one of the templates with the keyboard."""

from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk
from typing import Any

from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.present.new_file import TemplateRow, template_rows
from pyguibud.i18n import N_, _

__all__ = ["NewFileDialog"]

_M_TITLE = N_("New from template")
_M_PROMPT = N_("Choose a template for the new document.")
# Translators: the buttons of the template wizard; _ marks the access key (Alt+letter) and must
# differ between the two.
_M_CREATE = N_("C_reate")
_M_CANCEL = N_("_Cancel")


class NewFileDialog(ModalDialog):
    """Arrow keys choose, Enter or double-click creates, Esc cancels.

    ``on_choose`` receives the template id after the dialog has closed.
    """

    TITLE = _M_TITLE

    def __init__(self, root: Any, on_choose: Callable[[str], object]) -> None:  # noqa: ANN401
        super().__init__(root)
        self._on_choose = on_choose
        self._rows: list[TemplateRow] = []
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(1, weight=1)
        self.prompt = ttk.Label(self.body, anchor="w", wraplength=360)
        self.prompt.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.list = ttk.Treeview(
            self.body, show="tree", selectmode="browse", height=5, takefocus=True
        )
        self.list.column("#0", stretch=True, minwidth=120, width=240)
        self.list.grid(row=1, column=0, sticky="nsew")
        self.description = ttk.Label(self.body, anchor="nw", wraplength=360, justify="left")
        self.description.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.body.bind("<Configure>", self._wrap)
        buttons = ttk.Frame(self.body)
        buttons.grid(row=3, column=0, sticky="e", pady=(12, 0))
        self.create_button = ttk.Button(buttons, command=self.choose, default="active")
        self.cancel_button = ttk.Button(buttons, command=self.close)
        self.create_button.pack(side="left", padx=(0, 6))
        self.cancel_button.pack(side="left")
        self.access_keys = [(self.create_button, _M_CREATE), (self.cancel_button, _M_CANCEL)]
        self.list.bind("<<TreeviewSelect>>", self._on_select)
        self.list.bind("<Double-1>", lambda _e: self.choose())
        self.window.bind("<Return>", self._on_return)

    # ------------------------------------------------------------ view
    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The template list, so the arrow keys choose at once."""
        return self.list

    def retranslate(self) -> None:
        """Re-read titles and descriptions; the selected template stays selected."""
        selected = self.selected_id()
        self._rows = template_rows()
        self.window.title(_(self.TITLE))
        self.prompt.configure(text=_(_M_PROMPT))
        self.label_buttons()
        self.list.delete(*self.list.get_children())
        for row in self._rows:
            self.list.insert("", "end", iid=row.id, text=row.title)
        if self._rows:
            self.select(selected if selected in {r.id for r in self._rows} else self._rows[0].id)
        super().retranslate()

    def _wrap(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        width = max(120, int(event.width) - 24)
        self.prompt.configure(wraplength=width)
        self.description.configure(wraplength=width)

    def _on_select(self, _event: object) -> None:
        chosen = self.selected_id()
        row = next((r for r in self._rows if r.id == chosen), None)
        self.description.configure(text=row.description if row else "")

    # ------------------------------------------------------------ behaviour
    def selected_id(self) -> str | None:
        """The id of the highlighted template, or None."""
        picked = self.list.selection()
        return str(picked[0]) if picked else None

    def select(self, template_id: str) -> None:
        """Highlight a template and give the list the focus."""
        self.list.selection_set(template_id)
        self.list.focus(template_id)
        self.list.see(template_id)
        self._on_select(None)

    def choose(self) -> None:
        """Close the dialog and hand the highlighted template to the caller."""
        template_id = self.selected_id()
        if template_id is None:
            return
        self.close()
        self._on_choose(template_id)

    def _on_return(self, _event: object) -> str:
        if self.window.focus_get() is self.cancel_button:  # Enter on Cancel means cancel
            self.close()
            return "break"
        self.choose()
        return "break"
