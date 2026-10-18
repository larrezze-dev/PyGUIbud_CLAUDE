"""Turning insertion targets into commands (pure; spec dnd-selection 5.3).

The canvas and the palette build commands here and hand them to the ``CommandStack``; nothing
in this module mutates a document. A move, nudge or resize builder returns a command, or the
translated reason it is denied (a no-op is denied too: it would not be recorded).
"""

from __future__ import annotations

import keyword
import re
from collections.abc import Iterable, Sequence
from dataclasses import replace
from typing import Literal

from pyguibud.core.commands import (
    DEFAULT_LAYOUT,
    Command,
    InsertNode,
    Macro,
    MoveNode,
    RemoveNode,
    RemoveVariable,
    SetField,
    SetVariable,
    change_layout,
)
from pyguibud.core.model import (
    Action,
    Document,
    GridCell,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    Placement,
    Prop,
    Statusbar,
    Variable,
    Widget,
    WidgetSpec,
    Window,
)
from pyguibud.core.validate import RESERVED_IDS
from pyguibud.designer.geometry import Rect
from pyguibud.designer.targets import MAX_INDEX, Target
from pyguibud.i18n import N_, _

__all__ = [
    "M_EXTERNAL_INCLUDES",
    "M_LAST_WINDOW",
    "Built",
    "Edge",
    "MenuItem",
    "delete_command",
    "delete_window_command",
    "insert_command",
    "menu_insert_command",
    "menu_insert_enabled",
    "move_command",
    "move_index",
    "new_node",
    "new_variable",
    "new_window",
    "nudge_command",
    "past_the_grid",
    "refusal",
    "relayout_command",
    "remove_and_unbind",
    "rename_variable",
    "rename_window",
    "reorder_command",
    "resize_cell",
    "resize_command",
    "same_file_includes",
    "span_rect",
    "unique_id",
    "variable_users",
    "window_delete_refusal",
]

_M_STATUSBAR_EXISTS = N_("This window already has a status bar.")
_M_MENUBAR_EXISTS = N_("This window already has a menu bar.")
_M_INTO_ITSELF = N_("A widget cannot be dropped into itself.")
# Translators: a move or resize that would change nothing; {id} is the id of the element.
_M_ALREADY_THERE = N_("'{id}' is already there.")
_M_OFF_GRID = N_("That would put an element outside the grid.")
_M_MIN_SPAN = N_("An element must span at least one row and one column.")
_M_ONE_CONTAINER = N_("Only elements of the same container can be moved together.")
_M_NOT_MOVABLE = N_("Only widgets and included components can be moved.")
_M_NOT_GRID = N_("Only elements of a grid can be resized.")
_M_SIDE_BY_SIDE = N_("This container arranges its children side by side; use Left and Right.")
_M_TOP_TO_BOTTOM = N_("This container arranges its children top to bottom; use Up and Down.")
_M_MOVE_ONE = N_("Move element")
_M_MOVE_MANY = N_("Move elements")
_M_RESIZE = N_("Resize element")
_M_DELETE_MANY = N_("Delete elements")
_STEM_MAX = 58  # leaves room for a 6-digit counter within the 64-character id limit
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: A node the palette can create: a widget, or one of the two window bars.
NewNode = Widget | Statusbar | Menubar


def _stem(class_name: str) -> str:
    """``ScrolledFrame`` -> ``scrolled_frame``; ``tb:Meter`` -> ``meter``; always id-safe."""
    local = class_name.rpartition(":")[2]
    stem = re.sub(r"[^A-Za-z0-9_]", "", _CAMEL.sub("_", local)).lower()
    if not stem or not stem[0].isalpha():
        stem = "widget" + stem
    return stem[:_STEM_MAX]


def unique_id(document: Document | None, stem: str, taken: Iterable[str] = ()) -> str:
    """``f"{stem}{n}"`` for the smallest n >= 1 that is free in the one id namespace.

    ``taken`` adds ids that are not in ``document`` yet (a paste being prepared).
    """
    stem = _stem(stem)
    used: set[str] = set(taken)
    if document is not None:
        used.update(document.variables, document.resources)
        used.update(i for n in document.walk() if isinstance(i := getattr(n, "id", None), str))
    n = 1
    while (
        (candidate := f"{stem}{n}") in used
        or candidate in RESERVED_IDS
        or keyword.iskeyword(candidate)
    ):
        n += 1
    return candidate


def new_node(spec: WidgetSpec, document: Document | None) -> NewNode:
    """A detached node for ``spec`` with a free id and its default text (user content, en-GB)."""
    if spec.name == "Menubar":
        return Menubar()
    if spec.name == "Statusbar":
        return Statusbar(id=unique_id(document, spec.name))
    text = spec.property("text")
    props = {}
    if text is not None and text.translatable:
        props["text"] = Prop(name="text", value=spec.display_name, translatable=True)
    return Widget(
        class_name=spec.name,
        id=unique_id(document, spec.name),
        props=props,
        fallback=spec.fallback,
        plugin=spec.plugin,
        layout=DEFAULT_LAYOUT if spec.children == "layout" else None,
    )


def _bar_name(node: NewNode) -> str:
    return "statusbar" if isinstance(node, Statusbar) else "menubar"


def refusal(target: Target, node: NewNode) -> str | None:
    """Why ``node`` cannot go to ``target`` before any check (a window already has that bar)."""
    if isinstance(node, Widget) or getattr(target.container, _bar_name(node), None) is None:
        return None
    return _(_M_STATUSBAR_EXISTS if isinstance(node, Statusbar) else _M_MENUBAR_EXISTS)


def insert_command(target: Target, node: NewNode) -> Command:
    """The command that puts ``node`` at ``target``; presets the placement of a widget.

    A drag reuses one node for every hover check, so the placement is set again each time.
    """
    if not isinstance(node, Widget):
        return SetField(target.container, _bar_name(node), node)
    node.placement = _default_placement(target, node.id)
    return InsertNode(target.container, node, target.index)


def _is_notebook(node: object) -> bool:
    return isinstance(node, Widget) and "Notebook" in (node.class_name, node.fallback)


def _default_placement(target: Target, node_id: str) -> Placement:
    """The placement a node gets at ``target`` when it brings none that fits."""
    if target.kind == "grid":
        return GridCell(row=target.row, column=target.column)
    if target.kind == "slot":
        return PackPlacement()
    if _is_notebook(target.container):
        return PagePlacement(text=Prop(name="text", value=node_id, translatable=True))
    return PagePlacement()


def delete_command(*nodes: object) -> Command:
    """Remove widgets or includes; several are one ``Delete elements`` step (spec 11)."""
    if len(nodes) == 1:
        return RemoveNode(nodes[0])
    return Macro(_M_DELETE_MANY, [RemoveNode(node) for node in nodes])


# ---------------------------------------------------------------- move, nudge, resize
#: A command, or the translated reason why there is none.
Built = Command | str
_Movable = Widget | Include


def move_index(old: int, gap: int) -> int:
    """The ``MoveNode`` index that puts the child at ``old`` into ``gap`` (same parent)."""
    return gap if gap <= old else gap - 1


def _block(nodes: Sequence[object]) -> tuple[list[_Movable], Window | Widget, _Movable] | str:
    """(the nodes in sibling order, their one parent, the anchor = the last node) or a reason."""
    moving = [n for n in nodes if isinstance(n, _Movable)]
    if not moving or len(moving) != len(nodes):
        return _(_M_NOT_MOVABLE)
    anchor = moving[-1]
    parent = anchor.parent
    if parent is None or any(n.parent is not parent for n in moving):
        return _(_M_ONE_CONTAINER)
    order = {id(child): k for k, child in enumerate(parent.children)}
    return sorted(moving, key=lambda n: order[id(n)]), parent, anchor


def _is_grid(container: Window | Widget) -> bool:
    return container.layout is not None and container.layout.type == "grid"


def _orient(container: Window | Widget) -> str:
    if container.layout is not None:
        return container.layout.orient
    if _is_notebook(container):
        return "horizontal"
    orient = container.props.get("orient") if isinstance(container, Widget) else None
    return str(orient.value) if orient is not None else "vertical"


def _cell(node: _Movable) -> GridCell:
    placement = node.placement
    return placement if isinstance(placement, GridCell) else GridCell(row=0, column=0)


def _area(cell: GridCell) -> set[tuple[int, int]]:
    rows = range(cell.row, cell.row + max(cell.rowspan, 1))
    return {(r, c) for r in rows for c in range(cell.column, cell.column + max(cell.columnspan, 1))}


def _grid_cells(block: list[_Movable], anchor: _Movable, target: Target) -> list[GridCell] | str:
    """The new cells: each node keeps its offset from the anchor, which lands on the target.

    From a grid, the offsets come from the cells, and sticky, padding and spans are kept; a
    reparented span that would cover a taken cell is clipped to 1 (spec 5.3). From pack or
    pages the nodes are laid out in one row, in sibling order. Collisions are left to the
    validator, whose reason the stack's ``check()`` reports.
    """
    container = target.container
    taken: set[tuple[int, int]] = set()
    if container is not anchor.parent and target.index is None:  # an insert makes room instead
        for child in getattr(container, "children", ()):
            if isinstance(child.placement, GridCell):
                taken |= _area(child.placement)
    from_grid, first, rank = (
        isinstance(anchor.placement, GridCell),
        _cell(anchor),
        block.index(anchor),
    )
    cells: list[GridCell] = []
    for k, node in enumerate(block):
        old = _cell(node)
        dr, dc = (old.row - first.row, old.column - first.column) if from_grid else (0, k - rank)
        row, column = target.row + dr, target.column + dc
        if min(row, column) < 0 or max(row, column) > MAX_INDEX:
            return _(_M_OFF_GRID)
        if not isinstance(node.placement, GridCell):
            cells.append(GridCell(row=row, column=column))
            continue
        new = replace(old, row=row, column=column)
        cells.append(replace(new, rowspan=1, columnspan=1) if _area(new) & taken else new)
    return cells


def _make_room(
    container: Window | Widget, block: list[_Movable], cells: list[GridCell], after: bool
) -> list[Command] | str:
    """Push the other children down, nearest first, off the cells a tree drop before or after
    a grid sibling takes; each push stops at the first free row, a moved node's old cell
    included (ruling QA-14b2-12, spec direct-manipulation 5). A block dropped after a taller
    sibling moves below it instead: ``cells`` is then rewritten in place (D10 a); a block
    dropped before one keeps its cells (QA-19c-04)."""
    claimed = set[tuple[int, int]]().union(*map(_area, cells))
    moving = {id(n) for n in block}
    others = [c for c in container.children if id(c) not in moving and c.placement is not None]
    top = min(c.row for c in cells)
    above = [_cell(c) for c in others if after and _cell(c).row < top and _area(_cell(c)) & claimed]
    if above:  # a taller sibling is never pushed below the block: the block goes under it (D10)
        shift = max(c.row + max(c.rowspan, 1) for c in above) - top
        cells[:] = [replace(c, row=c.row + shift) for c in cells]
        if any(c.row + max(c.rowspan, 1) - 1 > MAX_INDEX for c in cells):
            return _(_M_OFF_GRID)
        claimed = set[tuple[int, int]]().union(*map(_area, cells))
    commands: list[Command] = []
    for child in sorted(others, key=lambda c: (_cell(c).row, _cell(c).column)):
        cell = new = _cell(child)
        while _area(new) & claimed and new.row <= MAX_INDEX:
            new = replace(new, row=new.row + 1)
        if new.row + max(new.rowspan, 1) - 1 > MAX_INDEX:
            return _(_M_OFF_GRID)
        claimed |= _area(new)
        if new != cell:
            commands.append(SetField(child, "placement", new))
    return commands


def _reorder(children: list[_Movable], block: list[_Movable], gap: int) -> list[_Movable]:
    """``children`` with ``block`` taken out and put back, contiguous, at the ``gap``."""
    moving = {id(n) for n in block}
    rest = [c for c in children if id(c) not in moving]
    at = gap - sum(1 for c in children[:gap] if id(c) in moving)
    return rest[:at] + block + rest[at:]


def _realise(parent: object, current: list[_Movable], final: list[_Movable]) -> list[Command]:
    """``MoveNode`` commands that turn ``current`` into ``final`` when applied in order."""
    sim, commands = list(current), list[Command]()
    for index, node in enumerate(final):
        if sim[index] is not node:
            sim.pop(next(k for k, child in enumerate(sim) if child is node))
            sim.insert(index, node)
            commands.append(MoveNode(node, parent, index))
    return commands


def move_command(nodes: Sequence[object], target: Target) -> Built:
    """Move ``nodes`` (one parent; the last one is the anchor) to ``target`` as one command.

    Same grid: new cells, spans kept. Same pack/pages: the nodes become one contiguous block
    at the gap, in sibling order. Another container: a reparent with placement conversion.
    All or nothing (spec 8, multi-move).
    """
    checked = _block(nodes)
    if isinstance(checked, str):
        return checked
    block, parent, anchor = checked
    ancestor: object | None = target.container
    while ancestor is not None:
        if any(ancestor is n for n in block):
            return _(_M_INTO_ITSELF)
        ancestor = getattr(ancestor, "parent", None)
    container = target.container
    if target.kind == "bar" or not isinstance(container, Window | Widget):
        return _(_M_NOT_MOVABLE)
    same, commands = container is parent, list[Command]()
    if target.kind == "grid":
        cells = _grid_cells(block, anchor, target)
        if isinstance(cells, str):
            return cells
        room = [] if target.index is None else _make_room(container, block, cells, target.after)
        if isinstance(room, str):
            return room
        gap = len(container.children) if target.index is None else target.index
        if same and target.index is not None:  # the tree order follows, as with Alt+Up/Down
            kids = list(parent.children)
            commands = _realise(parent, kids, _reorder(kids, block, gap))
        unmoved = all(c == n.placement for n, c in zip(block, cells, strict=True))
        if same and not commands and unmoved:
            return _(_M_ALREADY_THERE).format(id=anchor.id)
        for k, (node, cell) in enumerate(zip(block, cells, strict=True)):
            if not same:
                commands.append(MoveNode(node, container, gap + k))
            commands.append(SetField(node, "placement", cell))
        commands += room
    elif same:
        children = list(parent.children)
        gap = len(children) if target.index is None else target.index
        commands = _realise(parent, children, _reorder(children, block, gap))
        if not commands:
            return _(_M_ALREADY_THERE).format(id=anchor.id)
    else:
        gap = len(container.children) if target.index is None else target.index
        for k, node in enumerate(block):
            # A page keeps its tab text between containers of one kind only (ruling 13b-i).
            keep = isinstance(
                node.placement, PackPlacement if target.kind == "slot" else PagePlacement
            ) and (target.kind == "slot" or _is_notebook(parent) == _is_notebook(container))
            placement = node.placement if keep else _default_placement(target, node.id)
            commands.append(MoveNode(node, container, gap + k))
            commands.append(SetField(node, "placement", placement))
    return Macro(_M_MOVE_ONE if len(block) == 1 else _M_MOVE_MANY, commands)


def past_the_grid(block: Sequence[_Movable], rows: int, columns: int) -> str | None:
    """Why a keyboard step (move or span +1) may not take the far edge of ``block`` beyond the
    append cell, one row/column past the last one the other children use (spec 7.3), or None."""

    def far(node: _Movable) -> tuple[int, int]:
        cell = _cell(node)
        return cell.row + max(cell.rowspan, 1), cell.column + max(cell.columnspan, 1)

    moving = {id(n) for n in block}
    kids = [far(c) for c in getattr(block[0].parent, "children", ()) if id(c) not in moving]
    mine = [far(n) for n in block]
    beyond = any(
        step > 0 and max(m[k] for m in mine) + step > max((o[k] for o in kids), default=0) + 1
        for k, step in enumerate((rows, columns))
    )
    return _(_M_OFF_GRID) if beyond else None


def nudge_command(nodes: Sequence[object], rows: int, columns: int) -> Built:
    """Arrow keys: the grid cell +-1, or the index +-1 along a pack/pages orient (spec 7.3)."""
    checked = _block(nodes)
    if isinstance(checked, str):
        return checked
    block, parent, anchor = checked
    if _is_grid(parent):
        if reason := past_the_grid(block, rows, columns):
            return reason
        cell = _cell(anchor)
        moved = Target(parent, "grid", None, cell.row + rows, cell.column + columns)
        return move_command(nodes, moved)
    horizontal = _orient(parent) == "horizontal"
    step = columns if horizontal else rows
    if step == 0:
        return _(_M_SIDE_BY_SIDE if horizontal else _M_TOP_TO_BOTTOM)
    return reorder_command(nodes, step)


def reorder_command(nodes: Sequence[object], step: int) -> Built:
    """The nodes one sibling earlier (``step`` < 0) or later, as one block (Alt+Up/Down, D8)."""
    checked = _block(nodes)
    if isinstance(checked, str):
        return checked
    block, parent, anchor = checked
    kids = parent.children
    places = [k for k, child in enumerate(kids) if any(child is n for n in block)]
    gap = places[0] - 1 if step < 0 else places[-1] + 2
    if not 0 <= gap <= len(kids):
        return _(_M_ALREADY_THERE).format(id=anchor.id)
    return move_command(nodes, Target(parent, "page" if parent.layout is None else "slot", gap))


def resize_command(node: object, row: int, column: int, rowspan: int, columnspan: int) -> Built:
    """A grid child's new cell and spans (resize handles, Shift+Arrow; spec 8)."""
    if not isinstance(node, _Movable) or not isinstance(node.placement, GridCell):
        return _(_M_NOT_GRID)
    if rowspan < 1 or columnspan < 1:
        return _(_M_MIN_SPAN)
    if min(row, column) < 0 or max(row + rowspan, column + columnspan) > MAX_INDEX + 1:
        return _(_M_OFF_GRID)
    cell = node.placement
    new = replace(cell, row=row, column=column, rowspan=rowspan, columnspan=columnspan)
    if new == cell:
        return _(_M_ALREADY_THERE).format(id=node.id)
    return Macro(_M_RESIZE, [SetField(node, "placement", new)])


#: A resize handle: the edges it moves (n/s change the rows, w/e the columns).
Edge = Literal["n", "s", "w", "e", "nw", "ne", "sw", "se"]


def _snap(lines: Sequence[int], p: int, current: int) -> int:
    """The index of the line nearest to ``p``; a tie (empty, zero-width cells) stays nearest
    to ``current``, so a pointer that has not left the edge changes nothing."""
    return min(range(len(lines)), key=lambda k: (abs(lines[k] - p), abs(k - current)))


def _drag_edge(
    lines: Sequence[int], start: int, span: int, p: int, *, far: bool, pitch: int
) -> tuple[int, int]:
    """(start, span) with the near (``far=False``) or far edge snapped to ``p``.

    The other edge stays put and the span never drops below 1. The far edge may also land on
    one append line, ``pitch`` px past the last boundary (like the move's append row/column).
    """
    end = start + span
    if len(lines) < 2:
        return start, span
    if far:
        extended = (*lines, lines[-1] + max(pitch, 1))
        return start, max(_snap(extended, p, end), start + 1) - start
    first = max(min(_snap(lines, p, start), end - 1), 0)
    return first, end - first


def resize_cell(
    cell: GridCell,
    edge: Edge,
    columns: Sequence[int],
    rows: Sequence[int],
    x: int,
    y: int,
    *,
    pitch: int = 16,
) -> tuple[int, int, int, int]:
    """``(row, column, rowspan, columnspan)`` after dragging ``edge`` to (x, y) (spec 8).

    ``columns``/``rows`` are the parent's cell boundaries (``grid_bbox``, stage coordinates).
    Right/bottom edges change the span; left/top edges move the cell and keep the far edge.
    """
    row, rowspan = cell.row, max(cell.rowspan, 1)
    column, columnspan = cell.column, max(cell.columnspan, 1)
    if "w" in edge or "e" in edge:
        column, columnspan = _drag_edge(
            columns, column, columnspan, x, far="e" in edge, pitch=pitch
        )
    if "n" in edge or "s" in edge:
        row, rowspan = _drag_edge(rows, row, rowspan, y, far="s" in edge, pitch=pitch)
    return row, column, rowspan, columnspan


def span_rect(
    columns: Sequence[int], rows: Sequence[int], area: tuple[int, int, int, int], *, pitch: int = 16
) -> Rect:
    """The stage rectangle of ``area`` = (row, column, rowspan, columnspan); a line past the
    last boundary lies ``pitch`` px further on per index (the resize indicator)."""

    def line(bounds: Sequence[int], k: int) -> int:
        if not bounds:
            return 0
        return bounds[k] if k < len(bounds) else bounds[-1] + (k - len(bounds) + 1) * pitch

    row, column, rowspan, columnspan = area
    x, y = line(columns, column), line(rows, row)
    return Rect(x, y, line(columns, column + columnspan) - x, line(rows, row + rowspan) - y)


# ---------------------------------------------------------------- layout and variables (14a)
_M_CHANGE_LAYOUT = N_("Change layout")
_M_RENAME_VARIABLE = N_("Rename variable")
_M_REMOVE_AND_UNBIND = N_("Remove and unbind variable")
# Translators: a rename would merge two variables; {id} is the name that is taken.
_M_VARIABLE_EXISTS = N_("A variable called '{id}' already exists.")


def relayout_command(container: Window | Widget, kind: str) -> Command:
    """Switch ``container`` to a grid or pack layout, placing the children in reading order.

    Grid -> pack orders the children row by row; pack -> grid puts them along the orientation.
    """
    old = container.layout or DEFAULT_LAYOUT
    if old.type == kind:
        return SetField(container, "layout", container.layout)  # unchanged: a no-op
    children: list[_Movable] = list(container.children)
    layout = replace(old, type="pack" if kind == "pack" else "grid", columns=(), rows=())
    placements: dict[Widget | Include, Placement] = {}
    final = children
    if layout.type == "pack":
        final = sorted(children, key=lambda c: (_cell(c).row, _cell(c).column))
        for child in final:
            cell = _cell(child)
            placements[child] = PackPlacement(padx=cell.padx, pady=cell.pady)
    else:
        across = old.orient == "horizontal"
        for k, child in enumerate(children):
            pack = child.placement if isinstance(child.placement, PackPlacement) else None
            pad = (pack.padx, pack.pady) if pack else (0, 0)
            row, column = (0, k) if across else (k, 0)
            placements[child] = GridCell(row=row, column=column, padx=pad[0], pady=pad[1])
    moves = _realise(container, children, final)
    return Macro(_M_CHANGE_LAYOUT, [*moves, change_layout(container, layout, placements)])


def variable_users(document: Document, var_id: str) -> list[Widget]:
    """The widgets bound to the variable ``var_id``, in document order."""
    return [n for n in document.walk() if isinstance(n, Widget) and n.bind == var_id]


def new_variable(document: Document, var_type: str = "string") -> SetVariable:
    """Declare a fresh ``varN`` variable of ``var_type``."""
    return SetVariable(document, Variable(id=unique_id(document, "var"), type=var_type))  # type: ignore[arg-type]


def rename_variable(document: Document, old: str, new: str) -> Built:
    """Rename a variable and rebind every user, as one step (the guard judges the new id)."""
    if new != old and new in document.variables:
        return _(_M_VARIABLE_EXISTS).format(id=new)
    variable = document.variables[old]
    commands: list[Command] = [RemoveVariable(document, old)]
    commands.append(SetVariable(document, replace(variable, id=new)))
    commands += [SetField(w, "bind", new) for w in variable_users(document, old)]
    return Macro(_M_RENAME_VARIABLE, commands)


def remove_and_unbind(document: Document, var_id: str) -> Command:
    """Delete a variable; a used one is unbound from its widgets first, in the same step."""
    users = variable_users(document, var_id)
    if not users:
        return RemoveVariable(document, var_id)
    unbind: list[Command] = [SetField(w, "bind", None) for w in users]
    return Macro(_M_REMOVE_AND_UNBIND, [*unbind, RemoveVariable(document, var_id)])


# ---------------------------------------------------------------- menus (14a.2, spec 6)
#: What Edit > Insert adds.
MenuItem = Literal["menubar", "menu", "action", "separator", "statusbar"]
# The default texts are user content in the source language, like a new widget's text.
_MENU_TEXT = N_("Menu")
_ACTION_TEXT = N_("Action")


def menu_insert_enabled(selected: object, kind: MenuItem) -> bool:
    """True when Insert > ``kind`` applies to ``selected`` (spec 6 table; greys menu items)."""
    if kind in ("menubar", "statusbar"):
        # Mirrors validate.component_chrome: a component window has no menu bar or status bar.
        return (
            isinstance(selected, Window)
            and selected.kind != "component"
            and getattr(selected, kind) is None
        )
    if kind == "menu":
        return isinstance(selected, Menubar | Menu)
    return isinstance(selected, Menu) or (
        isinstance(selected, Action | MenuSeparator) and selected.parent is not None
    )


def menu_insert_command(document: Document, selected: object, kind: MenuItem) -> Command | None:
    """The Insert > ``kind`` command for ``selected``, or None when it does not apply.

    An action or separator goes after a selected item, or at the end of a selected menu. The
    stack attaches a copy of a new bar: select ``window.menubar``/``statusbar`` afterwards.
    """
    if not menu_insert_enabled(selected, kind):
        return None
    if isinstance(selected, Window):
        if kind == "menubar":
            return SetField(selected, "menubar", Menubar())
        return SetField(selected, "statusbar", Statusbar(id=unique_id(document, "statusbar")))
    node: Menu | Action | MenuSeparator
    if kind == "menu":
        node = Menu(id=unique_id(document, "menu"), props={"text": _text(_MENU_TEXT)})
    elif kind == "action":
        node = Action(id=unique_id(document, "act"), props={"text": _text(_ACTION_TEXT)})
    else:
        node = MenuSeparator()
    if isinstance(selected, Action | MenuSeparator) and selected.parent is not None:
        menu = selected.parent
        return InsertNode(menu, node, menu.index_of(selected) + 1)
    return InsertNode(selected, node)


def _text(value: str) -> Prop:
    return Prop(name="text", value=value, translatable=True)


# ---------------------------------------------------------------- windows (14a.2, spec 7)
_M_RENAME_WINDOW = N_("Rename window")
M_LAST_WINDOW = N_("A document needs at least one window.")
# Translators: deleting a component that another window still shows; {id} is the component,
# {user} the window that includes it.
_M_STILL_INCLUDED = N_("'{id}' is still included by '{user}'.")
#: Shown after renaming a component: other files may include it by its old id.
M_EXTERNAL_INCLUDES = N_("Files that include this component from outside were not updated.")


def new_window(document: Document, kind: Literal["main", "dialog", "component"]) -> Command:
    """Add an empty window of ``kind`` (a second main window is refused by the guard)."""
    window = Window(id=unique_id(document, kind), kind=kind, layout=DEFAULT_LAYOUT)
    return InsertNode(document, window)


def same_file_includes(document: Document, component: str) -> list[Include]:
    """The includes (``src="#"``) of this document that show ``component``."""
    return [
        n
        for n in document.walk()
        if isinstance(n, Include) and n.src == "#" and n.component == component
    ]


def rename_window(document: Document, window: Window, new: str) -> Command:
    """Rename ``window`` and the same-file includes of it, as one step (the guard judges ``new``).

    Files that include it from outside are not updated; the UI shows ``M_EXTERNAL_INCLUDES``
    after renaming a component.
    """
    commands: list[Command] = [SetField(window, "id", new)]
    commands += [SetField(i, "component", new) for i in same_file_includes(document, window.id)]
    return Macro(_M_RENAME_WINDOW, commands)


def _window_of(node: object) -> Window | None:
    return next((a for a in getattr(node, "ancestors", tuple)() if isinstance(a, Window)), None)


def window_delete_refusal(
    document: Document, window: Window, *, also: Sequence[Window] = ()
) -> str | None:
    """Why ``window`` cannot be deleted (the last one; a component still included), or None.

    ``also`` are windows removed in the same step (a cut): their includes do not count.
    """
    if len(document.children) <= 1:
        return _(M_LAST_WINDOW)
    for include in same_file_includes(document, window.id):
        user = _window_of(include)
        if user is not window and not any(user is w for w in also):
            name = include.id if user is None else user.id
            return _(_M_STILL_INCLUDED).format(id=window.id, user=name)
    return None


def delete_window_command(document: Document, window: Window) -> Built:
    """``RemoveNode(window)``, or the reason it is refused."""
    return window_delete_refusal(document, window) or RemoveNode(window)
