"""The canvas overlay (spec dnd-selection 3, ADR-010): ``place()``-d strips above the window.

The strips are plain ``tk.Frame`` children of the stage, raised with ``lift()``; a sibling with a
higher stacking order covers the whole subtree of the window frame. Hit-testing never looks at
them (it uses the geometry snapshot). Step 13a draws the single-selection outline and the
insertion indicator; handles, the rubber band and the cell grid arrive in 13b.
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable
from typing import Any, Literal

from pyguibud.designer.geometry import Rect
from pyguibud.designer.theme import ThemeSpec

__all__ = ["Overlay", "TargetState"]

#: How an insertion target is drawn: accepted, denied (dashed) or still being checked.
TargetState = Literal["allowed", "denied", "pending"]
_DASH = 6  # px at 96 dpi: the segment length of a denied target


def _ring(rect: Rect, width: int) -> list[Rect]:
    """Four strips of ``width`` just outside ``rect``."""
    x, y, w = rect.x - width, rect.y - width, rect.w + 2 * width
    return [
        Rect(x, y, w, width),
        Rect(x, rect.y + rect.h, w, width),
        Rect(x, rect.y, width, rect.h),
        Rect(rect.x + rect.w, rect.y, width, rect.h),
    ]


def _dashed(strip: Rect, dash: int) -> list[Rect]:
    """Every other ``dash``-long piece of ``strip`` (along its long side)."""
    along_x = strip.w >= strip.h
    length = strip.w if along_x else strip.h
    pieces: list[Rect] = []
    for start in range(0, length, 2 * dash):
        size = min(dash, length - start)
        if along_x:
            pieces.append(Rect(strip.x + start, strip.y, size, strip.h))
        else:
            pieces.append(Rect(strip.x, strip.y + start, strip.w, size))
    return pieces


class _Layer:
    """A pool of coloured strips; :meth:`draw` places as many as needed and hides the rest."""

    def __init__(self, stage: Any) -> None:  # noqa: ANN401 - a Tk widget
        self._stage = stage
        self._strips: list[tkinter.Frame] = []

    def draw(self, pieces: list[tuple[Rect, str]], cursor: str = "") -> None:
        while len(self._strips) < len(pieces):
            self._strips.append(tkinter.Frame(self._stage, borderwidth=0, takefocus=0))
        for strip, (rect, colour) in zip(self._strips, pieces, strict=False):
            strip.configure(background=colour, cursor=cursor)
            # "outside": a ttk frame reports its padding as an internal border, and the
            # coordinates are measured from the stage's outer edge (like winfo_rootx).
            strip.place(
                x=rect.x,
                y=rect.y,
                width=max(1, rect.w),
                height=max(1, rect.h),
                bordermode="outside",
            )
            strip.lift()
        for strip in self._strips[len(pieces) :]:
            strip.place_forget()

    def shown(self) -> list[tkinter.Frame]:
        return [s for s in self._strips if s.winfo_manager() == "place"]


class Overlay:
    """Selection outline and insertion indicator of one stage."""

    def __init__(self, stage: Any, *, scale: Callable[[int], int] = lambda px: px) -> None:  # noqa: ANN401
        self._scale = scale
        self.selection = _Layer(stage)
        self.target = _Layer(stage)
        self._colours = {"focus": "", "bg": "", "primary": "", "danger": "", "border": ""}
        self._selected: Rect | None = None
        self._target: tuple[Rect, TargetState, bool] | None = None

    def restyle(self, spec: ThemeSpec) -> None:
        """Re-read the colours from the theme and redraw."""
        colours = spec.colors
        self._colours = {
            "focus": spec.focus,
            "bg": colours["bg"],
            "primary": colours["primary"],
            "danger": colours["danger"],
            "border": colours["border"],
        }
        self.show_selection(self._selected)
        if self._target is not None:
            self.show_target(self._target[0], self._target[1], bar=self._target[2])

    def show_selection(self, rect: Rect | None) -> None:
        """Outline ``rect`` (two-tone: visible on any widget colour); None hides it."""
        self._selected = rect
        if rect is None or not self._colours["focus"]:
            self.selection.draw([])
            return
        outer, inner = self._scale(2), 1
        pieces = [(r, self._colours["bg"]) for r in _ring(rect, inner)]
        grown = Rect(rect.x - inner, rect.y - inner, rect.w + 2 * inner, rect.h + 2 * inner)
        pieces += [(r, self._colours["focus"]) for r in _ring(grown, outer)]
        self.selection.draw(pieces)

    def show_target(self, rect: Rect | None, state: TargetState, *, bar: bool = False) -> None:
        """Draw an insertion target: a cell or container outline, or a filled slot ``bar``.

        A denied target is dashed and shows the ``X_cursor``: colour is never the only cue.
        """
        self._target = None if rect is None else (rect, state, bar)
        if rect is None or not self._colours["primary"]:
            self.target.draw([])
            return
        colour = {"allowed": "primary", "denied": "danger", "pending": "border"}[state]
        strips = [rect] if bar else _ring(rect, self._scale(2))
        if state == "denied":
            strips = [piece for strip in strips for piece in _dashed(strip, self._scale(_DASH))]
        cursor = "X_cursor" if state == "denied" else ""
        self.target.draw([(r, self._colours[colour]) for r in strips], cursor)

    def lift(self) -> None:
        """Raise every shown strip again (after a rebuild created new widgets)."""
        for strip in (*self.selection.shown(), *self.target.shown()):
            strip.lift()
