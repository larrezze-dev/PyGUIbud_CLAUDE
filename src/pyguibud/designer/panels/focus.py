"""``FocusFrame``: the outer frame of a panel; its border shows which panel has the focus."""

from __future__ import annotations

import tkinter
from typing import Any

__all__ = ["FocusFrame"]


class FocusFrame(tkinter.Frame):
    """A plain ``tk.Frame`` whose highlight ring is coloured by the shell (focus-within ring)."""

    def __init__(self, parent: Any, *, thickness: int = 2) -> None:  # noqa: ANN401 - Tk parent
        super().__init__(parent, highlightthickness=thickness, borderwidth=0, takefocus=False)
        self._thick = max(1, thickness)
        self._thin = max(1, self._thick // 2)
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
        """Show (or hide) the focus ring: thicker as well as coloured (H90, WCAG 1.4.11).

        The total edge stays ``thickness``: the idle ring is thinner and the remainder is a plain
        border painted with the fill, so the content never shifts when the focus moves."""
        self._active = active
        thin = self._thick if active else self._thin
        self.configure(highlightthickness=thin, borderwidth=self._thick - thin)
        colour = self._ring if active else self._plain
        if colour:
            self.configure(highlightbackground=colour, highlightcolor=colour)
        if self._plain:
            self.configure(background=self._fill or self._plain)  # not themed by ttk
