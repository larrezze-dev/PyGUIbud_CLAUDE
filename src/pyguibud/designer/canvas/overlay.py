"""The canvas overlay (spec dnd-selection 3, ADR-010): ``place()``-d strips above the window.

The strips are plain ``tk.Frame`` children of the stage, above the window frame in the stacking
order; a sibling with a higher stacking order covers the whole subtree of the window frame.
Hit-testing never looks at them (it uses the geometry snapshot). It outlines every selected node
and draws the insertion indicator, the primary's resize handles and, during a drag, the cell grid.

Stacking is set once per strip, when it is created, never per draw: a Tk ``raise`` walks the
stage's sibling list, so lifting every strip on every redraw was quadratic in the number of
outlined widgets (a paste of 100 widgets took seconds, 14a.2). The canvas puts each new window
frame beneath the strips instead (:meth:`Overlay.sink`).
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable, Sequence
from typing import Any, Literal

from pyguibud.designer.editing import Edge
from pyguibud.designer.geometry import ContainerBox, Rect
from pyguibud.designer.theme import ThemeSpec

__all__ = ["Overlay", "TargetState"]

#: How an insertion target is drawn: accepted, denied (dashed) or still being checked.
TargetState = Literal["allowed", "denied", "pending"]
_DASH = 6  # px at 96 dpi: the segment length of a denied target
_HANDLE = 9  # px at 96 dpi: a 7 px square plus its 1 px border, the whole of it hit-testable
_GRID_CAP = 64  # cell-grid lines drawn per axis at most (the 5 ms overlay budget)
_EMPTY_CAP = 16  # empty-container outlines drawn at most (R-D; the 5 ms overlay budget)
#: Selection outlines drawn at most besides the primary's (always drawn). Each outline is 8
#: native windows at about 1 ms each to map on Windows: an uncapped Select all or paste of 500
#: widgets took seconds (14a.2, ADR-010 amendment). The canvas applies it and says so.
SELECTION_CAP = 16
_PHASES = (
    ("<ButtonPress-1>", "press"),
    ("<B1-Motion>", "motion"),
    ("<ButtonRelease-1>", "release"),
)
#: The handles in pool order, each with its cursor.
HANDLES: tuple[tuple[Edge, str], ...] = (
    ("nw", "sizing"),
    ("n", "sb_v_double_arrow"),
    ("ne", "sizing"),
    ("e", "sb_h_double_arrow"),
    ("se", "sizing"),
    ("s", "sb_v_double_arrow"),
    ("sw", "sizing"),
    ("w", "sb_h_double_arrow"),
)


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


def _relay(
    callback: Callable[[Edge, str, Any], object], edge: Edge, phase: str
) -> Callable[[Any], object]:
    return lambda event: callback(edge, phase, event)


class _Layer:
    """A pool of coloured strips; :meth:`draw` places as many as needed and hides the rest.

    Within the pool, a strip's stacking order is its index (a later piece covers an earlier
    one), and the whole pool sits just below the strips of ``ceiling()`` (the layers above).
    """

    def __init__(
        self,
        stage: Any,  # noqa: ANN401 - a Tk widget
        setup: Callable[[int, tkinter.Frame], None] | None = None,
    ) -> None:
        self._stage = stage
        self._setup = setup  # called once per new strip, with its pool index (handle bindings)
        self._strips: list[tkinter.Frame] = []
        #: What each strip shows now, ``(rect, colour, cursor)``; None = hidden.
        self._shows: list[tuple[Rect, str, str] | None] = []
        #: The lowest strip of the layers above (set by the overlay): a new strip goes under it.
        self.ceiling: Callable[[], tkinter.Frame | None] = lambda: None

    @property
    def lowest(self) -> tkinter.Frame | None:
        """The bottom strip of this pool (None while it has none)."""
        return self._strips[0] if self._strips else None

    def draw(
        self, pieces: list[tuple[Rect, str]], cursor: str = "", *, cursors: Sequence[str] = ()
    ) -> None:
        """Place one strip per (rect, colour); ``cursors`` overrides ``cursor`` per piece.

        Only what changed reaches Tk: an unchanged redraw (a stage ``<Configure>``, a second
        outline of one selection) costs no Tk call.
        """
        while len(self._strips) < len(pieces):
            strip = tkinter.Frame(self._stage, borderwidth=0, takefocus=0)
            ceiling = self.ceiling()
            if ceiling is not None:  # a new widget starts on top: keep the layers in order
                strip.lower(ceiling)
            if self._setup is not None:
                self._setup(len(self._strips), strip)
            self._strips.append(strip)
            self._shows.append(None)
        for k, (strip, (rect, colour)) in enumerate(zip(self._strips, pieces, strict=False)):
            show = (rect, colour, cursors[k] if k < len(cursors) else cursor)
            old = self._shows[k]
            if old == show:
                continue
            if old is None or old[1:] != show[1:]:
                strip.configure(background=colour, cursor=show[2])
            if old is None or old[0] != rect:
                # "outside": a ttk frame reports its padding as an internal border, and the
                # coordinates are measured from the stage's outer edge (like winfo_rootx).
                strip.place(
                    x=rect.x,
                    y=rect.y,
                    width=max(1, rect.w),
                    height=max(1, rect.h),
                    bordermode="outside",
                )
            self._shows[k] = show
        for k in range(len(pieces), len(self._strips)):
            if self._shows[k] is not None:
                self._strips[k].place_forget()
                self._shows[k] = None

    def shown(self) -> list[tkinter.Frame]:
        return [s for s, show in zip(self._strips, self._shows, strict=True) if show is not None]


class Overlay:
    """Selection outline and insertion indicator of one stage."""

    def __init__(
        self,
        stage: Any,  # noqa: ANN401 - a Tk widget
        *,
        scale: Callable[[int], int] = lambda px: px,
        on_handle: Callable[[Edge, str, Any], object] | None = None,
    ) -> None:
        self._scale = scale
        self._on_handle = on_handle
        self.empty = _Layer(stage)  # R-D: the dashed outline of an empty container
        self.grid = _Layer(stage)
        self.selection = _Layer(stage)
        self.band = _Layer(stage)
        self.target = _Layer(stage)
        #: The resize handles, in :data:`HANDLES` order; a press calls ``on_handle``.
        self.handles = _Layer(stage, self._bind_handle)
        # Bottom to top: each layer's new strips go under the lowest strip of the layers above.
        layers = (self.empty, self.grid, self.selection, self.target, self.handles, self.band)
        for index, layer in enumerate(layers):
            layer.ceiling = self._ceiling(layers[index + 1 :])
        self._resizable = False
        self._grid: ContainerBox | None = None
        self._colours = {"focus": "", "bg": "", "primary": "", "danger": "", "border": ""}
        self._selected: tuple[Rect, ...] = ()
        self._empty: tuple[Rect, ...] = ()
        #: The outline of the primary node, where its resize handles go (None: not shown).
        self.primary: Rect | None = None
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
        grid, self._grid = self._grid, None
        self.show_empty(self._empty)
        self.show_grid(grid)
        self.show_selection(self._selected, primary=self.primary, handles=self._resizable)
        if self._target is not None:
            self.show_target(self._target[0], self._target[1], bar=self._target[2])

    def show_selection(
        self, rects: Sequence[Rect], *, primary: Rect | None = None, handles: bool = False
    ) -> None:
        """Outline every rect (two-tone: visible on any widget colour); empty hides them.

        ``handles`` adds the resize handles around ``primary`` (a grid child, spec 8).
        """
        self._selected, self.primary = tuple(rects), primary
        self._resizable = handles and primary is not None
        if not self._colours["focus"]:
            self.selection.draw([])
            self.handles.draw([])
            return
        outer, inner = self._scale(2), 1
        pieces: list[tuple[Rect, str]] = []
        for rect in self._selected:
            pieces += [(r, self._colours["bg"]) for r in _ring(rect, inner)]
            grown = Rect(rect.x - inner, rect.y - inner, rect.w + 2 * inner, rect.h + 2 * inner)
            pieces += [(r, self._colours["focus"]) for r in _ring(grown, outer)]
        self.selection.draw(pieces)
        self._show_handles()

    def show_empty(self, rects: Sequence[Rect]) -> None:
        """R-D: a 1 px dashed outline around each empty, unselected container (design only).

        ``border`` reaches 3:1 against ``bg`` in all three themes (pinned by a test).
        """
        self._empty = tuple(rects)
        dash, colour = self._scale(_DASH), self._colours["border"]
        pieces = [
            (piece, colour)
            for rect in self._empty[:_EMPTY_CAP]
            for strip in _ring(rect, 1)
            for piece in _dashed(strip, dash)
        ]
        self.empty.draw(pieces if colour else [])

    def show_band(self, rect: Rect | None) -> None:
        """The rubber band (D5): a 1 px focus-coloured rectangle; None hides it."""
        colour = self._colours["focus"]
        self.band.draw([(r, colour) for r in _ring(rect, 1)] if rect and colour else [])

    def _show_handles(self) -> None:
        rect = self.primary
        if rect is None or not self._resizable:
            self.handles.draw([])
            return
        size, out = max(self._scale(_HANDLE), 8), 1 + self._scale(2)  # on the outline's ring
        rect = Rect(rect.x - out, rect.y - out, rect.w + 2 * out, rect.h + 2 * out)
        xs = {"w": rect.x, "e": rect.x + rect.w}
        ys = {"n": rect.y, "s": rect.y + rect.h}
        pieces: list[tuple[Rect, str]] = []
        for edge, _cursor in HANDLES:
            x = next((xs[c] for c in edge if c in xs), rect.x + rect.w // 2)
            y = next((ys[c] for c in edge if c in ys), rect.y + rect.h // 2)
            square = Rect(x - size // 2, y - size // 2, size, size)
            pieces.append((square, self._colours["primary"]))
        self.handles.draw(pieces, cursors=[cursor for _edge, cursor in HANDLES])
        for handle in self.handles.shown():  # a 1 px bg border: visible on any widget colour
            handle.configure(highlightthickness=1, highlightbackground=self._colours["bg"])

    def _bind_handle(self, index: int, strip: tkinter.Frame) -> None:
        """A handle holds the pointer grab of its own drag: its events go to ``on_handle``."""
        if index < len(HANDLES) and self._on_handle is not None:
            edge, callback = HANDLES[index][0], self._on_handle
            for sequence, phase in _PHASES:
                strip.bind(sequence, _relay(callback, edge, phase))

    def show_grid(self, box: ContainerBox | None) -> None:
        """The cell lines of a grid container (``grid_bbox``), the snap guide of a drag."""
        if box is self._grid:
            return
        self._grid = box
        columns, rows = (box.columns, box.rows) if box is not None else ((), ())
        if not (columns and rows and self._colours["border"]):
            self.grid.draw([])
            return
        top, left = rows[0], columns[0]
        height, width = rows[-1] - top, columns[-1] - left
        lines = [Rect(x, top, 1, height) for x in columns[:_GRID_CAP]]
        lines += [Rect(left, y, width, 1) for y in rows[:_GRID_CAP]]
        self.grid.draw([(r, self._colours["border"]) for r in lines])

    @staticmethod
    def _ceiling(above: tuple[_Layer, ...]) -> Callable[[], tkinter.Frame | None]:
        """The lowest strip of the layers ``above`` (each layer is contiguous, in order)."""
        return lambda: next((s for s in (layer.lowest for layer in above) if s is not None), None)

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

    @staticmethod
    def sink(widget: Any) -> None:  # noqa: ANN401 - a Tk widget
        """Put ``widget``, a child of the stage created after the strips (a rebuilt window
        frame), beneath every strip: one restack instead of raising each strip again."""
        widget.lower()
