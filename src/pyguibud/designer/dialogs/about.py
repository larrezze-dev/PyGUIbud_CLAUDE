"""Help > About PyGUIbud: the name, version, licence and the author credit (Tk)."""

from __future__ import annotations

from tkinter import ttk
from typing import Any

from pyguibud.__about__ import __version__
from pyguibud.core.errors import format_message
from pyguibud.credits import credit
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.i18n import N_

__all__ = ["AboutDialog"]

# Translators: the title of the About dialog.
_M_TITLE = N_("About PyGUIbud")
# Translators: the Close button of the About dialog; _ marks the access key (Alt+letter).
_M_CLOSE = N_("_Close")
# Translators: {version} is a version number such as 0.1.0; {licence} is the licence name (MIT).
_M_DETAILS = N_("Version {version} • Licence: {licence}")


class AboutDialog(ModalDialog):
    """A short, read-only dialog; Esc, Enter and the Close button close it."""

    TITLE = _M_TITLE

    def __init__(self, root: Any) -> None:  # noqa: ANN401 - the app root
        super().__init__(root)
        self.name = ttk.Label(self.body, text="PyGUIbud", font="TkHeadingFont")
        self.name.pack(anchor="w")
        self.details = ttk.Label(self.body)
        self.details.pack(anchor="w", pady=(4, 0))
        self.credit = ttk.Label(self.body, justify="left", wraplength=root.winfo_fpixels("4i"))
        self.credit.pack(anchor="w", pady=(8, 0))
        self.close_button = ttk.Button(self.body, command=self.close, default="active")
        self.close_button.pack(side="bottom", anchor="e", pady=(12, 0))
        self.access_keys = [(self.close_button, _M_CLOSE)]
        self.window.bind("<Return>", lambda _e: self.close())

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The Close button."""
        return self.close_button

    def retranslate(self) -> None:
        """Re-apply the texts in the current language."""
        self.label_buttons()
        details = format_message(_M_DETAILS, {"version": __version__, "licence": "MIT"})
        self.details.configure(text=details)
        self.credit.configure(text=credit())
        super().retranslate()
