"""Canvas geometry (pure; spec dnd-selection 5.1): rectangles in stage coordinates.

The snapshot types are filled by ``CanvasEngine`` from live widgets; hit-testing works on them
only, never on ``winfo_containing`` (which would return the overlay strips).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["ChildBox", "ContainerBox", "Rect", "Snapshot"]


@dataclass(frozen=True, slots=True)
class Rect:
    """An axis-aligned rectangle; ``w``/``h`` of 0 or less is empty."""

    x: int
    y: int
    w: int
    h: int

    @property
    def empty(self) -> bool:
        return self.w <= 0 or self.h <= 0

    def contains(self, x: int, y: int) -> bool:
        """True when the point lies inside (left/top edges included, right/bottom excluded)."""
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h

    def covers(self, other: Rect) -> bool:
        """True when ``other`` lies fully inside (the rubber band's rule, D5)."""
        return (
            not other.empty
            and self.x <= other.x
            and self.y <= other.y
            and other.x + other.w <= self.x + self.w
            and other.y + other.h <= self.y + self.h
        )

    def intersects(self, other: Rect) -> bool:
        return not self.intersection(other).empty

    def intersection(self, other: Rect) -> Rect:
        """The overlap of both rectangles (empty when they do not overlap)."""
        x, y = max(self.x, other.x), max(self.y, other.y)
        right = min(self.x + self.w, other.x + other.w)
        bottom = min(self.y + self.h, other.y + other.h)
        return Rect(x, y, max(0, right - x), max(0, bottom - y))


@dataclass(frozen=True, slots=True)
class ChildBox:
    """A placed node: its outer rectangle and its placement (``GridCell``, ...)."""

    node: object
    rect: Rect
    placement: object


@dataclass(frozen=True, slots=True)
class ContainerBox:
    """A node that takes children, with the data the drop targets need."""

    node: object
    rect: Rect
    inner: Rect
    kind: Literal["grid", "pack", "pages", "window"]
    orient: str
    children: tuple[ChildBox, ...]
    depth: int
    columns: tuple[int, ...] = ()  # grid boundary x (from grid_bbox), len = n + 1
    rows: tuple[int, ...] = ()  # grid boundary y
    tabs: tuple[Rect, ...] = ()  # Notebook tab label rectangles


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Every viewable container and leaf of one rendered window."""

    containers: tuple[ContainerBox, ...]
    leaves: tuple[ChildBox, ...]
    visible: Rect | None = None  # the scroll host's visible area; outside it there is no target
