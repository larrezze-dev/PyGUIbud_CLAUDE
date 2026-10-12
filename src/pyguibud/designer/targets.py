"""Insertion targets (pure; spec dnd-selection 5.2, ADR-005): grid cells, pack and page slots.

``hit_test`` maps a pointer position on a geometry :class:`Snapshot` to a :class:`Target`;
``keyboard_target`` picks one from the selection alone (palette Enter / double-click).
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from pyguibud.core.model import GridCell, Include, Widget, WidgetSpec, Window
from pyguibud.core.registry import Registry
from pyguibud.core.validate import MAX_GRID_INDEX
from pyguibud.designer.geometry import ContainerBox, Rect, Snapshot

__all__ = ["MAX_INDEX", "Moving", "NewWidget", "Payload", "Target", "hit_test", "keyboard_target"]

MAX_INDEX = MAX_GRID_INDEX  # Tk's grid limit (one source: the validator)
Role = Literal["widget", "statusbar", "menubar", "menu"]


@dataclass(frozen=True, slots=True)
class NewWidget:
    """A palette item being inserted; ``role`` says where it may go."""

    spec_name: str
    role: Role = "widget"

    @classmethod
    def of(cls, spec: WidgetSpec) -> NewWidget:
        if spec.name in ("Statusbar", "Menubar"):
            return cls(spec.name, "statusbar" if spec.name == "Statusbar" else "menubar")
        menu = spec.children == "menu" or spec.name == "Action"
        return cls(spec.name, "menu" if menu else "widget")


@dataclass(frozen=True, slots=True)
class Moving:
    """Nodes being moved (Step 13b): they and their descendants are never drop containers."""

    nodes: tuple[object, ...]


Payload = NewWidget | Moving


@dataclass(frozen=True, slots=True)
class Target:
    """Where a drop would go. ``index`` is the gap in the container's children (None appends);
    on a grid it marks a tree drop before or after a sibling, which makes room (QA-14b2-12).

    ``rect``/``bar`` only describe the indicator and are not part of the identity.
    """

    container: object
    kind: Literal["grid", "slot", "page", "bar"]
    index: int | None = None
    row: int = 0
    column: int = 0
    rect: Rect = field(default=Rect(0, 0, 0, 0), compare=False)
    bar: bool = field(default=False, compare=False)

    @property
    def key(self) -> tuple[int, str, int, int, int]:
        """A hashable identity (the hover-check cache key)."""
        index = -1 if self.index is None else self.index
        return (id(self.container), self.kind, self.row, self.column, index)


def _shrunk(rect: Rect, by: int) -> Rect:
    return Rect(rect.x + by, rect.y + by, rect.w - 2 * by, rect.h - 2 * by)


def _excluded(node: object, moving: Iterable[object]) -> bool:
    """True when ``node`` is a moving node or lies below one."""
    ids = {id(n) for n in moving}
    current: object | None = node
    while current is not None:
        if id(current) in ids:
            return True
        current = getattr(current, "parent", None)
    return False


def _pick(snapshot: Snapshot, x: int, y: int, band: int, payload: Payload) -> ContainerBox | None:
    """The deepest container under the point; its edge band belongs to the parent."""
    moving = payload.nodes if isinstance(payload, Moving) else ()
    best: ContainerBox | None = None
    for box in snapshot.containers:
        if best is not None and box.depth <= best.depth:
            continue
        if not box.inner.contains(x, y):
            continue
        if box.depth > 0 and not _shrunk(box.rect, band).contains(x, y):
            continue
        if moving and _excluded(box.node, moving):
            continue
        best = box
    return best


def _doc_index(box: ContainerBox, gap: int) -> int:
    """The model index of the ``gap``-th visible child (hidden children keep their place)."""
    kids = list(getattr(box.node, "children", ()))
    if gap < len(box.children):
        node = box.children[gap].node
        return next((k for k, child in enumerate(kids) if child is node), len(kids))
    return len(kids)


def _cell(box: ContainerBox, x: int, y: int) -> Target:
    def line(bounds: tuple[int, ...], start: int, size: int, p: int) -> tuple[int, int, int]:
        if len(bounds) < 2 or bounds[-1] <= bounds[0]:
            bounds = (start, start + size)  # an empty grid: one virtual cell over ``inner``
        i = min(max(bisect_right(bounds, p) - 1, 0), len(bounds) - 1, MAX_INDEX)
        lo = bounds[i]
        hi = bounds[i + 1] if i + 1 < len(bounds) else max(start + size, lo + 16)
        return i, lo, hi - lo

    inner = box.inner
    column, cx, cw = line(box.columns, inner.x, inner.w, x)
    row, cy, ch = line(box.rows, inner.y, inner.h, y)
    return Target(box.node, "grid", None, row, column, Rect(cx, cy, cw, ch))


def _slot(box: ContainerBox, x: int, y: int, kind: Literal["slot", "page"], bar: int) -> Target:
    horizontal = box.orient == "horizontal"
    point = x if horizontal else y
    mids = [
        c.rect.x + c.rect.w // 2 if horizontal else c.rect.y + c.rect.h // 2 for c in box.children
    ]
    gap = sum(1 for mid in mids if mid < point)
    inner = box.inner
    if gap < len(box.children):
        edge = box.children[gap].rect
        at = edge.x if horizontal else edge.y
    elif box.children:
        last = box.children[-1].rect
        at = last.x + last.w if horizontal else last.y + last.h
    else:
        at = inner.x if horizontal else inner.y
    at -= bar // 2
    rect = Rect(at, inner.y, bar, inner.h) if horizontal else Rect(inner.x, at, inner.w, bar)
    return Target(box.node, kind, _doc_index(box, gap), rect=rect, bar=True)


def _tab(box: ContainerBox, x: int, y: int) -> Target:
    """A Notebook: over the tab strip, the tab gap under the pointer; elsewhere, append.

    Only the shown page is in ``box.children``, so the append index never comes from it.
    """
    gap: int | None = None
    if box.tabs and y < max(t.y + t.h for t in box.tabs):
        kids = len(list(getattr(box.node, "children", ())))
        gap = min(sum(1 for t in box.tabs if t.x + t.w // 2 < x), kids)
    return Target(box.node, "page", gap, rect=box.rect)


def hit_test(
    snapshot: Snapshot, x: int, y: int, payload: Payload, *, band: int = 6, bar: int = 3
) -> Target | None:
    """The insertion target under (x, y) in stage coordinates, or None (no target)."""
    if snapshot.visible is not None and not snapshot.visible.contains(x, y):
        return None
    if isinstance(payload, NewWidget) and payload.role == "menu":
        return None  # menus and actions belong to the menu editor
    if isinstance(payload, NewWidget) and payload.role in ("statusbar", "menubar"):
        window = next(
            (b for b in snapshot.containers if b.depth == 0 and b.rect.contains(x, y)), None
        )
        return None if window is None else Target(window.node, "bar", rect=window.rect)
    box = _pick(snapshot, x, y, band, payload)
    if box is None:
        return None
    if box.kind == "pages":
        return _tab(box, x, y) if box.orient == "" else _slot(box, x, y, "page", bar)
    if box.kind == "pack":
        return _slot(box, x, y, "slot", bar)
    return _cell(box, x, y)


def _is_pages(node: object, registry: Registry) -> bool:
    if not isinstance(node, Widget):
        return False
    spec = registry.get(node.class_name) or registry.get(node.fallback or "")
    return spec is not None and spec.children == "pages"


def _free_cell(container: Window | Widget, anchor: object | None) -> tuple[int, int]:
    """The first free grid cell in row-major order (after ``anchor``), else a new row."""
    taken: set[tuple[int, int]] = set()
    rows = columns = 0
    start = (0, 0)
    for child in container.children:
        cell = child.placement
        if not isinstance(cell, GridCell):
            continue
        for r in range(cell.row, cell.row + max(cell.rowspan, 1)):
            for c in range(cell.column, cell.column + max(cell.columnspan, 1)):
                taken.add((r, c))
        rows = max(rows, cell.row + cell.rowspan)
        columns = max(columns, cell.column + cell.columnspan)
        if child is anchor:
            start = (cell.row, cell.column)
    for r in range(start[0], rows):
        for c in range(columns):
            if (r, c) not in taken and (anchor is None or (r, c) > start):
                return r, c
    return min(rows, MAX_INDEX), 0


def keyboard_target(
    window: Window | None, selected: object | None, payload: NewWidget, registry: Registry
) -> Target | None:
    """Where Enter in the palette inserts: into the selected container, after a selected leaf,
    or into ``window`` (the current tab) when nothing in it is selected.
    """
    if payload.role == "menu":
        return None
    if payload.role in ("statusbar", "menubar"):
        owner = selected if isinstance(selected, Window) else window
        return None if owner is None else Target(owner, "bar")
    anchor: object | None = None
    container: object | None = window
    if isinstance(selected, Window) or (
        isinstance(selected, Widget)
        and (selected.layout is not None or _is_pages(selected, registry))
    ):
        container = selected
    elif isinstance(selected, Widget | Include) and selected.parent is not None:
        container, anchor = selected.parent, selected
    if not isinstance(container, Window | Widget):
        return None
    kids = list(container.children)
    after = next((k + 1 for k, child in enumerate(kids) if child is anchor), None)
    if _is_pages(container, registry):
        return Target(container, "page", after)
    layout = container.layout
    if layout is not None and layout.type == "pack":
        return Target(container, "slot", after)
    row, column = _free_cell(container, anchor)
    return Target(container, "grid", None, row, column)
