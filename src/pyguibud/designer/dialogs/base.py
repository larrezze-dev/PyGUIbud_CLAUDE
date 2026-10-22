"""``ModalDialog``: a themed, keyboard-closable, content-sized dialog that retranslates (Tk)."""

from __future__ import annotations

import functools
import logging
import sys
import tkinter
from collections.abc import Sequence
from tkinter import ttk
from typing import Any

from pyguibud.core.keys import split_mnemonic
from pyguibud.designer import screen
from pyguibud.designer.theme_tk import LIST_STYLE, scaled
from pyguibud.i18n import _

__all__ = ["ModalDialog"]

_log = logging.getLogger(__name__)
#: The most of the work area a dialog may take; a taller body scrolls (D6, H85).
_SCREEN_SHARE = 0.85
#: Keys that scroll a scroll area: (units or pages, direction); Home and End jump.
_SCROLL_KEYS = {"<Up>": ("units", -1), "<Down>": ("units", 1), "<Prior>": ("pages", -1),
                "<Next>": ("pages", 1)}  # fmt: skip


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
        #: ``(button, msgid)``: Alt plus the letter marked with ``_`` presses the button (16).
        self.access_keys: Sequence[tuple[Any, str]] = ()
        self.window.bind("<Alt-KeyPress>", self._on_alt)
        self.body = ttk.Frame(self.window, padding=12)
        self.body.pack(fill="both", expand=True)
        self._scroll: tuple[tkinter.Canvas, ttk.Scrollbar, ttk.Frame] | None = None
        self._ringed: list[Any] = []  # plain Tk widgets (Text, Listbox, Canvas)
        self.restyle()

    # ------------------------------------------------------------ hooks
    def retranslate(self) -> None:
        """Re-apply translated texts (subclass hook; call super to refresh the title)."""
        self.window.title(_(self.TITLE))
        self.fit()

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The widget that takes the keyboard focus when the dialog opens (subclass hook)."""
        return self.window

    def ring_on_focus(self, widget: Any) -> None:  # noqa: ANN401 - a plain Tk widget
        """Give a plain Tk widget (no ttk focus look) the 2 px focus ring of the dialog lists."""
        widget.configure(highlightthickness=scaled(self.window, 2))
        self._ringed.append(widget)
        self.restyle()

    def restyle(self) -> None:
        """Take the window background and the focus ring colour from the live ttk theme."""
        try:
            style = ttk.Style(self.root)
            colour = style.lookup("TFrame", "background")
            if colour:
                self.window.configure(background=colour)
                if self._scroll is not None:
                    self._scroll[0].configure(background=colour)
                ring = style.lookup(LIST_STYLE, "bordercolor", ["focus"]) or colour
                for widget in self._ringed:
                    widget.configure(highlightbackground=colour, highlightcolor=ring)
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
        if self.root.winfo_viewable():  # before deiconify: in some Windows foreground states
            self.window.transient(self.root)  # Tk withdraws a window made transient once shown
        self.window.deiconify()
        self.window.update_idletasks()
        self._centre()
        try:
            self.window.grab_set()
        except tkinter.TclError:  # not viewable yet (headless or minimised root)
            _log.debug("Could not grab the pointer for a dialog", exc_info=True)
        # The keys must reach the dialog's main widget at once, not the bare window (QA-12-02).
        self.initial_focus().focus_force()

    def scroll_area(self, parent: Any) -> ttk.Frame:  # noqa: ANN401 - a Tk container
        """A frame in ``parent`` that scrolls vertically (wheel, arrows, Page Up/Down, Home/End)
        once the dialog would be taller than 85 % of the work area (D6). Pack the buttons first,
        so they stay outside it and always visible."""
        canvas = tkinter.Canvas(parent, highlightthickness=0, borderwidth=0, takefocus=False)
        bar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview, takefocus=False)
        canvas.configure(yscrollcommand=bar.set)
        inner = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=inner, anchor="nw")
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width), add="+")
        canvas.pack(side="left", fill="both", expand=True)
        self._scroll = (canvas, bar, inner)
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.window.bind(sequence, self._on_wheel, add="+")
        for sequence, (what, step) in _SCROLL_KEYS.items():
            self.window.bind(sequence, functools.partial(self._on_key, what, step), add="+")
        self.window.bind("<Home>", lambda _e: canvas.yview_moveto(0), add="+")
        self.window.bind("<End>", lambda _e: canvas.yview_moveto(1), add="+")
        self.restyle()
        return inner

    def _on_key(self, what: str, step: int, _event: object) -> None:
        if self._scroll is not None:
            self._scroll[0].yview_scroll(step, what)  # type: ignore[call-overload]

    def _on_wheel(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self._scroll is not None:
            delta = int(getattr(event, "delta", 0) or 0)
            step = -1 if delta > 0 or getattr(event, "num", 0) == 4 else 1
            self._scroll[0].yview_scroll(step, "units")

    def work_area(self) -> tuple[int, int]:
        """The largest size a dialog may take: the work area of the main window's monitor (no
        taskbar) less the title bar, so its whole frame fits (H85, QA-19f-03)."""
        width, height = self.window.wm_maxsize()
        area_width, area_height, _left, _top = screen.work_area(self.root)
        return (min(int(width), area_width),
                min(int(height), area_height) - screen.title_height(self.root))  # fmt: skip

    def fit(self) -> None:
        """Size the window to its content (never a fixed size, so +40 % text still fits), but
        never larger than the work area; a scroll area takes at most 85 % of it (D6)."""
        self.window.update_idletasks()
        area_width, area_height = self.work_area()
        if self._scroll is not None:
            canvas, bar, inner = self._scroll
            content = inner.winfo_reqheight()
            chrome = self.window.winfo_reqheight() - canvas.winfo_reqheight()
            shown = max(1, min(content, int(area_height * _SCREEN_SHARE) - chrome))
            canvas.configure(width=inner.winfo_reqwidth(), height=shown,
                             scrollregion=(0, 0, inner.winfo_reqwidth(), content))  # fmt: skip
            if shown < content:
                bar.pack(side="right", fill="y", before=canvas)
            else:
                bar.pack_forget()
            self.window.update_idletasks()
        width = min(self.window.winfo_reqwidth(), area_width)
        height = min(self.window.winfo_reqheight(), area_height)
        self.window.minsize(width, height)
        self.window.geometry(f"{min(max(width, self.window.winfo_width()), area_width)}x{height}")
        if sys.platform == "win32" and self.window.winfo_viewable():  # a re-fit (language, theme)
            # x, y: the frame's (Windows); kept on the dialog's own monitor, wherever it was moved
            self._place(self.window.winfo_x(), self.window.winfo_y(), self.window)

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
                top = target.winfo_toplevel()
                if str(top) != str(self.root.winfo_toplevel()):
                    top.grab_set()  # back to the dialog under a nested one: still modal
                return
        except tkinter.TclError:
            _log.debug("The widget that had the focus is gone", exc_info=True)
        self.root.focus_set()

    def label_buttons(self) -> None:
        """Show the translated labels of :attr:`access_keys` with their access key underlined."""
        for button, msgid in self.access_keys:
            text, underline = split_mnemonic(_(msgid))
            button.configure(text=text, underline=underline)

    def _on_alt(self, event: Any) -> str | None:  # noqa: ANN401 - a Tk event
        key = str(getattr(event, "char", "") or "").lower()
        for button, msgid in self.access_keys:
            text, underline = split_mnemonic(_(msgid))
            if key and underline >= 0 and text[underline].lower() == key:
                button.invoke()  # a disabled button does nothing
                return "break"
        return None

    def _on_escape(self, _event: object) -> str:
        self.close()
        return "break"

    def _centre(self) -> None:
        """Over the main window, kept on the virtual desktop (a monitor left of or above the
        primary one has negative coordinates, which Tk writes as ``+-1500``)."""
        width, height = self.window.winfo_reqwidth(), self.window.winfo_reqheight()
        left = self.root.winfo_rootx() + (self.root.winfo_width() - width) // 2
        top = self.root.winfo_rooty() + (self.root.winfo_height() - height) // 3
        self._place(left, top)

    def _place(self, left: int, top: int, owner: Any = None) -> None:  # noqa: ANN401 - Tk
        """Move the frame to ``left, top``, kept with its title bar and buttons on the work area
        of the monitor of ``owner`` (default: the main window), above the taskbar (QA-19f-03)."""
        width, height = self.work_area()  # the size fit() gave the dialog, plus its title bar
        width = min(self.window.winfo_reqwidth(), width)
        height = min(self.window.winfo_reqheight(), height) + screen.title_height(self.root)
        area_width, area_height, area_left, area_top = screen.work_area(owner or self.root)
        left = max(area_left, min(left, area_left + area_width - width))
        top = max(area_top, min(top, area_top + area_height - height))
        self.window.geometry(f"+{left}+{top}")
