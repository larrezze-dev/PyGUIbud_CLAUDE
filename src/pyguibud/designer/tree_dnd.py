"""Object-tree drag-and-drop targets (pure; spec direct-manipulation 5, properties-save-load 13.1).

A row and a drop zone become the same :class:`~pyguibud.designer.targets.Target` the canvas hit
test produces, so a tree drop runs the canvas's own ``move_command``, ``check()`` and ``execute``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Literal

from pyguibud.core.model import GridCell, Include, Widget, Window
from pyguibud.core.registry import Registry
from pyguibud.designer.targets import NewWidget, Target, keyboard_target
from pyguibud.i18n import N_, _, ngettext

__all__ = ["Zone", "is_container", "release_text", "target", "zone_of"]

Zone = Literal["before", "into", "after"]

_M_ACROSS = N_("Elements cannot be dragged to another window. Use Cut and Paste.")
# Translators: {id} is the row under the pointer: a widget without children or an include.
_M_LEAF = N_("'{id}' cannot hold elements: drop them before or after it.")
_M_NOWHERE = N_("Drop elements onto a window, onto a container or next to an element.")
# The same texts as on the canvas (one msgid, one translation).
_M_NOT_MOVABLE = N_("Only widgets and included components can be moved.")
_M_INTO_ITSELF = N_("A widget cannot be dropped into itself.")
_M_ALREADY_THERE = N_("'{id}' is already there.")
# Translators: {id} is the element being moved, {container} the id of a window or frame.
_M_RELEASE_MOVE = N_("Release to move '{id}' into '{container}'.")


def is_container(node: object, registry: Registry) -> bool:
    """A window, or a widget with a layout or pages (a row that accepts "into")."""
    if isinstance(node, Window):
        return True
    if not isinstance(node, Widget):
        return False
    spec = registry.get(node.class_name) or registry.get(node.fallback or "")
    return node.layout is not None or (spec is not None and spec.children == "pages")


def zone_of(y: int, height: int) -> Zone:
    """The top 25 % is before, the bottom 25 % after, the middle into (a leaf refuses it)."""
    if 4 * y < height:
        return "before"
    return "after" if 4 * y >= 3 * height else "into"


def _window(node: object) -> object | None:
    while node is not None and not isinstance(node, Window):
        node = getattr(node, "parent", None)
    return node


def _below(node: object, moving: Sequence[object]) -> bool:
    """True when ``node`` lies strictly below one of the ``moving`` nodes."""
    current = getattr(node, "parent", None)
    while current is not None:
        if any(current is n for n in moving):
            return True
        current = getattr(current, "parent", None)
    return False


def _past(cell: GridCell, columns: int) -> tuple[int, int]:
    """The first cell after the area of ``cell`` in reading order over ``columns`` columns."""
    rows = range(cell.row, cell.row + max(cell.rowspan, 1))
    spans = range(cell.column, cell.column + max(cell.columnspan, 1))
    row, column = cell.row, cell.column
    while row in rows and column in spans:
        row, column = (row, column + 1) if column + 1 < columns else (row + 1, 0)
    return row, column


def _grid_slot(parent: Window | Widget, sibling: Widget | Include, moving: Sequence[object],
               after: bool) -> Target:  # fmt: skip
    """Before: the sibling's cell; after: the next cell past it in reading order (over the
    columns in use). ``move_command`` pushes what is in the way down (ruling QA-14b2-12) and
    the index keeps the tree order. A block just before the sibling is already there."""
    cells = [c.placement for c in parent.children if isinstance(c.placement, GridCell)]
    columns = max((c.column + max(c.columnspan, 1) for c in cells), default=1)
    cell = (
        sibling.placement if isinstance(sibling.placement, GridCell) else GridCell(row=0, column=0)
    )
    spot = _past(cell, columns) if after else (cell.row, cell.column)
    mine = [c.placement for c in parent.children if any(c is n for n in moving)]
    grid = [c for c in mine if isinstance(c, GridCell)]
    last = max(grid, key=lambda c: (c.row, c.column), default=None)
    if not after and last and len(grid) == len(moving) and _past(last, columns) == spot:
        spot = (min(c.row for c in grid), min(c.column for c in grid))
    index = next(k for k, child in enumerate(parent.children) if child is sibling) + after
    return Target(parent, "grid", index, *spot)


def _aim(found: Target | str, nodes: Sequence[object]) -> Target | str:
    """Put the block's top-left cell, not the anchor, on the grid cell ``found`` names: a row
    names no cell, so no node may land left of or above it on a negative cell (dnd-selection 8:
    grid sources keep their offsets, others form one row in sibling order)."""
    if not isinstance(found, Target) or found.kind != "grid":
        return found
    anchor = nodes[-1]
    assert isinstance(anchor, Widget | Include)  # what makes ``found`` a Target
    cells = [n.placement for n in nodes if isinstance(n, Widget | Include)]
    if isinstance(anchor.placement, GridCell):
        grid = [c for c in cells if isinstance(c, GridCell)]
        rows = anchor.placement.row - min(c.row for c in grid)
        columns = anchor.placement.column - min(c.column for c in grid)
        return replace(found, row=found.row + rows, column=found.column + columns)
    siblings = [c for c in getattr(anchor.parent, "children", ()) if any(c is n for n in nodes)]
    rank = next((k for k, c in enumerate(siblings) if c is anchor), 0)
    return replace(found, column=found.column + rank)


def target(row: object, zone: Zone, nodes: Sequence[object], registry: Registry) -> Target | str:
    """Where dropping ``nodes`` (the tree selection, the anchor last) on ``row`` puts them,
    or why it cannot (spec 5: windows, menus and bars are never a payload; D7)."""
    return _aim(_target(row, zone, nodes, registry), nodes)


def _target(row: object, zone: Zone, nodes: Sequence[object], registry: Registry) -> Target | str:
    if not nodes or not all(isinstance(n, Widget | Include) for n in nodes):
        return _(_M_NOT_MOVABLE)
    if _below(row, nodes) or (zone == "into" and any(row is n for n in nodes)):
        return _(_M_INTO_ITSELF)
    if not isinstance(row, Window | Widget | Include):
        return _(_M_NOWHERE)  # a menu, an action or a bar (menu rows: trim T5)
    if _window(row) is not _window(nodes[-1]):
        return _(_M_ACROSS)
    if isinstance(row, Window) or (zone == "into" and is_container(row, registry)):
        found = keyboard_target(None, row, NewWidget("Frame"), registry)
        return found if found is not None else _(_M_NOWHERE)
    if not isinstance(row.parent, Window | Widget):
        return _(_M_NOWHERE)
    if zone == "into":
        return _(_M_LEAF).format(id=row.id)
    if any(row is n for n in nodes):
        return _(_M_ALREADY_THERE).format(id=row.id)
    parent = row.parent
    if parent.layout is not None and parent.layout.type == "grid":
        return _grid_slot(parent, row, nodes, zone == "after")
    index = next(k for k, child in enumerate(parent.children) if child is row)
    return Target(
        parent, "slot" if parent.layout is not None else "page", index + (zone == "after")
    )


def release_text(nodes: Sequence[object], found: Target) -> str:
    """The status text while a drop on ``found`` would be accepted (the canvas's texts)."""
    if len(nodes) == 1:
        container = getattr(found.container, "id", "")
        return _(_M_RELEASE_MOVE).format(id=getattr(nodes[0], "id", ""), container=container)
    text = ngettext(
        "Release to move {count} element.", "Release to move {count} elements.", len(nodes)
    )
    return text.format(count=len(nodes))
