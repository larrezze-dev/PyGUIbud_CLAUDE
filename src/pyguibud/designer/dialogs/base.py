"""``ModalDialog``: a themed, keyboard-closable, content-sized dialog that retranslates (Tk)."""

from __future__ import annotations

import logging
import tkinter
from tkinter import ttk
from typing import Any

from pyguibud.i18n import _

__all__ = ["ModalDialog"]

_log = logging.getLogger(__name__)


class ModalDialog:
    """Subclasses build their widgets into :attr:`body` and implement :meth:`retranslate`.

    The dialog never blocks the caller (``open`` returns at once): it takes the keyboard and
    pointer grab, which is what makes it modal, and Esc or :meth:`close` releases it.
    """

    TITLE = ""  # a msgid

    def __init__(self, root: Any) -> None:  # noqa: ANN401 - the app root
        self.root = root
        self.closed = False
        self._return_focus: Any = None  # the widget that had the focus before the dialog
        self.window = tkinter.Toplevel(root)
        self.window.withdraw()
        self.window.title("")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self._on_escape)
        self.body = ttk.Frame(self.window, padding=12)
        self.body.pack(fill="both", expand=True)
        self.restyle()

    # ------------------------------------------------------------ hooks
    def retranslate(self) -> None:
        """Re-apply translated texts (subclass hook; call super to refresh the title)."""
        self.window.title(_(self.TITLE))
        self.fit()

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The widget that takes the keyboard focus when the dialog opens (subclass hook)."""
        return self.window

    def restyle(self) -> None:
        """Take the window background from the live ttk theme."""
        try:
            colour = ttk.Style(self.root).lookup("TFrame", "background")
            if colour:
                self.window.configure(background=colour)
        except tkinter.TclError:
            _log.debug("Could not recolour a dialog", exc_info=True)

    # ------------------------------------------------------------ lifecycle
    def open(self) -> None:
        """Show the dialog centred over the main window and make it modal."""
        try:
            self._return_focus = self.root.focus_get()
        except (KeyError, tkinter.TclError):  # the focus is in a widget tkinter does not know
            self._return_focus = None
        self.retranslate()
        self.window.deiconify()
        if self.root.winfo_viewable():
            self.window.transient(self.root)
        self.window.update_idletasks()
        self._centre()
        try:
            self.window.grab_set()
        except tkinter.TclError:  # not viewable yet (headless or minimised root)
            _log.debug("Could not grab the pointer for a dialog", exc_info=True)
        # The keys must reach the dialog's main widget at once, not the bare window (QA-12-02).
        self.initial_focus().focus_force()

    def fit(self) -> None:
        """Size the window to its content (never a fixed size, so +40 % text still fits)."""
        self.window.update_idletasks()
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        self.window.minsize(width, height)
        self.window.geometry(f"{max(width, self.window.winfo_width())}x{height}")

    def close(self) -> None:
        """Release the grab and destroy the window (idempotent)."""
        if self.closed:
            return
        self.closed = True
        try:
            self.window.grab_release()
            self.window.destroy()
        except tkinter.TclError:
            _log.debug("The dialog was already destroyed", exc_info=True)
        if self.root.winfo_exists():
            self._restore_focus()

    def _restore_focus(self) -> None:
        """Give the focus back to the widget that had it before the dialog, else to the root."""
        target = self._return_focus
        try:
            if target is not None and target.winfo_exists():
                target.focus_set()
                return
        except tkinter.TclError:
            _log.debug("The widget that had the focus is gone", exc_info=True)
        self.root.focus_set()

    def _on_escape(self, _event: object) -> str:
        self.close()
        return "break"

    def _centre(self) -> None:
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        left = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        top = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 3
        self.window.geometry(f"+{max(0, left)}+{max(0, top)}")
