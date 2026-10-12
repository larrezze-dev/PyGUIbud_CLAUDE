"""``FocusFrame``: the outer frame of a panel; its border shows which panel has the focus."""

from __future__ import annotations

import tkinter
from typing import Any

__all__ = ["FocusFrame"]


class FocusFrame(tkinter.Frame):
    """A plain ``tk.Frame`` whose highlight ring is coloured by the shell (focus-within ring)."""

    def __init__(self, parent: Any, *, thickness: int = 2) -> None:  # noqa: ANN401 - Tk parent
        super().__init__(parent, highlightthickness=thickness, borderwidth=0, takefocus=False)
        self._ring = ""
        self._plain = ""
        self._fill = ""
        self._active = False

    def set_colours(self, *, ring: str, plain: str, fill: str = "") -> None:
        """Set the focused and unfocused border colours (from the current theme) and the
        ``fill`` between the border and the body (the border colour when omitted)."""
        self._ring, self._plain, self._fill = ring, plain, fill
        self.mark(self._active)

    def mark(self, active: bool) -> None:
        """Show (or hide) the focus ring."""
        self._active = active
        colour = self._ring if active else self._plain
        if colour:
            self.configure(highlightbackground=colour, highlightcolor=colour)
        if self._plain:
            self.configure(background=self._fill or self._plain)  # not themed by ttk
