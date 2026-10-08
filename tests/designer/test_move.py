"""Move, nudge and resize builders and the multi-selection model (spec dnd-selection 5.3, 7.1, 8).

Pure: no Tk. Every command goes through a real ``CommandStack`` so the validator has its say.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core import CommandStack, default_registry, read_ui_string
from pyguibud.core.commands import Command, Macro
from pyguibud.core.model import Document, GridCell, PackPlacement, PagePlacement, Widget, Window
from pyguibud.designer.editing import (
    Edge,
    delete_command,
    move_command,
    move_index,
    nudge_command,
    resize_cell,
    resize_command,
    span_rect,
)
from pyguibud.designer.geometry import Rect
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.targets import Target

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)
FORM = (
    HEADER
    + """
<window id="w"><layout type="grid"/>
  <widget class="Label" id="a"><prop name="text">A</prop>
    <cell row="0" column="0" sticky="w"/></widget>
  <widget class="Label" id="b"><prop name="text">B</prop>
    <cell row="0" column="1" columnspan="2"/></widget>
  <widget class="Label" id="c"><prop name="text">C</prop><cell row="1" column="0"/></widget>
  <widget class="Frame" id="g"><cell row="2" column="0"/><layout type="grid"/>
    <widget class="Label" id="g1"><prop name="text">G</prop><cell row="0" column="0"/></widget>
  </widget>
  <widget class="Frame" id="p"><cell row="3" column="0"/><layout type="pack"/>
    <widget class="Label" id="p0"><prop name="text">0</prop><pack fill="x"/></widget>
    <widget class="Label" id="p1"><prop name="text">1</prop><pack/></widget>
    <widget class="Label" id="p2"><prop name="text">2</prop><pack/></widget>
    <widget class="Label" id="p3"><prop name="text">3</prop><pack/></widget>
  </widget>
  <widget class="Frame" id="h"><cell row="4" column="0"/><layout type="pack" orient="horizontal"/>
    <widget class="Label" id="h0"><prop name="text">0</prop><pack/></widget>
  </widget>
  <widget class="Notebook" id="n"><cell row="5" column="0"/>
    <widget class="Frame" id="n0"><page><prop name="text">0</prop></page>
      <layout type="pack"/></widget>
  </widget>
</window>
<window id="w2" kind="dialog"><layout type="grid"/>
  <widget class="Label" id="x"><prop name="text">X</prop><cell row="0" column="0"/></widget>
</window>
</pyguibud-ui>"""
)


def _form() -> tuple[Document, CommandStack, dict[str, object]]:
    document = read_ui_string(FORM).document
    nodes: dict[str, object] = {getattr(n, "id", ""): n for n in document.walk()}
    return document, CommandStack(document, default_registry()), nodes


def _run(stack: CommandStack, built: Command | str) -> None:
    assert isinstance(built, Command), built
    outcome = stack.execute(built)
    assert outcome.accepted and outcome.changed, outcome.message


def _ids(container: object) -> list[str]:
    return [child.id for child in container.children]  # type: ignore[attr-defined]


def _cell(node: object) -> tuple[int, int, int, int]:
    cell = node.placement  # type: ignore[attr-defined]
    assert isinstance(cell, GridCell)
    return cell.row, cell.column, cell.rowspan, cell.columnspan


# ---------------------------------------------------------------- move_index
@given(
    st.integers(1, 30).flatmap(
        lambda n: st.tuples(st.just(n), st.integers(0, n - 1), st.integers(0, n))
    )
)
def test_move_index_matches_a_list_model(case: tuple[int, int, int]) -> None:
    n, old, gap = case
    items: list[object] = list(range(n))
    expected = [i for i in [*items[:gap], "*", *items[gap:]] if i != old]  # gap marker
    expected[expected.index("*")] = old
    moved = items.copy()
    moved.remove(old)
    moved.insert(move_index(old, gap), old)
    assert moved == expected


# ---------------------------------------------------------------- grid
def test_a_grid_move_keeps_spans_and_sticky_and_is_one_undo_step() -> None:
    _doc, stack, n = _form()
    built = move_command((n["b"],), Target(n["w"], "grid", None, 6, 3))
    assert isinstance(built, Macro) and built.label == "Move element"
    _run(stack, built)
    assert _cell(n["b"]) == (6, 3, 1, 2)
    stack.undo()
    assert _cell(n["b"]) == (0, 1, 1, 2)


def test_moving_to_the_same_cell_is_a_denied_no_op() -> None:
    _doc, stack, n = _form()
    assert move_command((n["a"],), Target(n["w"], "grid", None, 0, 0)) == "'a' is already there."
    assert stack.index == 0


def test_an_occupied_cell_is_denied_by_the_validator() -> None:
    _doc, stack, n = _form()
    built = move_command((n["a"],), Target(n["w"], "grid", None, 1, 0))
    assert isinstance(built, Command)
    outcome = stack.check(built)
    assert not outcome.accepted and "overlaps" in outcome.message


def test_a_multi_move_keeps_the_offsets_from_the_anchor() -> None:
    _doc, stack, n = _form()
    built = move_command((n["c"], n["a"]), Target(n["w"], "grid", None, 7, 4))  # anchor: a
    assert isinstance(built, Macro) and built.label == "Move elements"
    _run(stack, built)
    assert _cell(n["a"])[:2] == (7, 4) and _cell(n["c"])[:2] == (8, 4)
    assert n["a"].placement.sticky == "w"  # type: ignore[attr-defined]
    stack.undo()
    assert _cell(n["a"])[:2] == (0, 0) and _cell(n["c"])[:2] == (1, 0)


def test_a_multi_move_is_all_or_nothing() -> None:
    _doc, stack, n = _form()
    # The anchor c lands on (0, 5); a (one row up) would land on row -1.
    assert move_command((n["a"], n["c"]), Target(n["w"], "grid", None, 0, 5)) == (
        "That would put an element outside the grid."
    )
    # a lands on (6, 0), c on (7, 0): free; b would collide only through c's old place: fine.
    built = move_command((n["a"], n["c"]), Target(n["w"], "grid", None, 1, 1))  # c -> (1,1)
    assert isinstance(built, Command)
    outcome = stack.check(built)  # a -> (0, 1): b covers it -> the whole move is denied
    assert not outcome.accepted and "overlaps" in outcome.message
    assert _cell(n["a"])[:2] == (0, 0) and _cell(n["c"])[:2] == (1, 0)
    # h (the anchor) takes n's old cell: legal because n moves in the same step.
    _run(stack, move_command((n["n"], n["h"]), Target(n["w"], "grid", None, 5, 0)))
    assert _cell(n["h"])[:2] == (5, 0) and _cell(n["n"])[:2] == (6, 0)


# ---------------------------------------------------------------- pack / pages
def test_a_pack_reorder_and_a_block_move() -> None:
    _doc, stack, n = _form()
    p = n["p"]
    _run(stack, move_command((n["p0"],), Target(p, "slot", 3)))
    assert _ids(p) == ["p1", "p2", "p0", "p3"]
    stack.undo()
    _run(stack, move_command((n["p3"], n["p0"]), Target(p, "slot", 2)))  # block, sibling order
    assert _ids(p) == ["p1", "p0", "p3", "p2"]
    stack.undo()
    assert _ids(p) == ["p0", "p1", "p2", "p3"]
    assert move_command((n["p1"],), Target(p, "slot", 2)) == "'p1' is already there."


@given(
    st.integers(2, 12).flatmap(
        lambda size: st.tuples(
            st.just(size),
            st.sets(st.integers(0, size - 1), min_size=1, max_size=size),
            st.integers(0, size),
        )
    )
)
def test_a_block_move_matches_a_list_model(case: tuple[int, set[int], int]) -> None:
    size, picked, gap = case
    labels = "".join(
        f'<widget class="Label" id="l{k}"><prop name="text">x</prop><pack/></widget>'
        for k in range(size)
    )
    document = read_ui_string(
        HEADER + f'<window id="w"><layout type="pack"/>{labels}</window></pyguibud-ui>'
    ).document
    window = document.children[0]
    kids = list(window.children)
    block = [kids[k] for k in sorted(picked)]
    rest = [c for c in kids[:gap] if c not in block]
    expected = rest + block + [c for c in kids[gap:] if c not in block]
    built = move_command(tuple(block), Target(window, "slot", gap))
    if expected == kids:
        assert isinstance(built, str)
        return
    stack = CommandStack(document, default_registry())
    _run(stack, built)
    assert [c.id for c in window.children] == [c.id for c in expected]
    stack.undo()
    assert [c.id for c in window.children] == [c.id for c in kids]


# ---------------------------------------------------------------- reparent
def test_a_reparent_converts_the_placement() -> None:
    _doc, stack, n = _form()
    _run(stack, move_command((n["a"],), Target(n["p"], "slot", 1)))
    assert n["a"].parent is n["p"] and _ids(n["p"])[1] == "a"  # type: ignore[attr-defined]
    assert n["a"].placement == PackPlacement()  # type: ignore[attr-defined]
    _run(stack, move_command((n["p0"],), Target(n["n"], "page", None)))
    page = n["p0"].placement  # type: ignore[attr-defined]
    assert isinstance(page, PagePlacement) and page.text is not None and page.text.value == "p0"
    _run(stack, move_command((n["p1"],), Target(n["h"], "slot", 0)))  # pack -> pack: kept
    stack.undo()
    stack.undo()
    stack.undo()
    assert n["a"].parent is n["w"] and _cell(n["a"]) == (0, 0, 1, 1)  # type: ignore[attr-defined]


def test_a_reparent_into_a_grid_keeps_the_cell_or_clips_a_colliding_span() -> None:
    _doc, stack, n = _form()
    _run(stack, move_command((n["b"],), Target(n["g"], "grid", None, 1, 0)))
    assert n["b"].parent is n["g"] and _cell(n["b"]) == (1, 0, 1, 2)  # type: ignore[attr-defined]
    stack.undo()
    _run(stack, move_command((n["g1"],), Target(n["g"], "grid", None, 0, 2)))  # g1 at (0, 2)
    _run(stack, move_command((n["b"],), Target(n["g"], "grid", None, 0, 1)))
    assert _cell(n["b"]) == (0, 1, 1, 1)  # its 2-wide span would cover (0, 2): clipped


def test_a_pack_block_reparented_into_a_grid_lies_in_one_row() -> None:
    _doc, stack, n = _form()
    _run(stack, move_command((n["p1"], n["p2"]), Target(n["g"], "grid", None, 1, 3)))
    assert _cell(n["p1"])[:2] == (1, 2) and _cell(n["p2"])[:2] == (1, 3)  # anchor p2


def test_a_node_never_moves_into_itself_or_a_descendant() -> None:
    _doc, _stack, n = _form()
    reason = "A widget cannot be dropped into itself."
    assert move_command((n["g"],), Target(n["g"], "grid", None, 1, 1)) == reason
    assert move_command((n["n"],), Target(n["n0"], "slot", None)) == reason


def test_builders_refuse_mixed_parents_and_non_widgets() -> None:
    _doc, _stack, n = _form()
    target = Target(n["w"], "grid", None, 9, 9)
    assert "same container" in str(move_command((n["a"], n["g1"]), target))
    assert "Only widgets" in str(move_command((n["w"],), target))
    assert "Only widgets" in str(move_command((), target))


PAGES = (
    HEADER
    + """
<window id="w"><layout type="grid"/>
  <widget class="Notebook" id="n1"><cell row="0" column="0"/>
    <widget class="Frame" id="t"><page weight="0"><prop name="text">Tab</prop></page>
      <layout type="pack"/></widget>
  </widget>
  <widget class="Notebook" id="n2"><cell row="0" column="1"/></widget>
  <widget class="PanedWindow" id="pw1"><cell row="1" column="0"/>
    <widget class="Frame" id="q"><page weight="3"/><layout type="pack"/></widget>
  </widget>
  <widget class="PanedWindow" id="pw2"><cell row="1" column="1"/></widget>
</window>
</pyguibud-ui>"""
)


def test_a_page_reparented_between_page_containers_keeps_its_placement() -> None:
    """Ruling 13b-i (refined in 13b-c): Notebook -> Notebook keeps the tab text, PanedWindow
    -> PanedWindow the weight; a cross-kind move or a non-page node gets the default."""
    document = read_ui_string(PAGES).document
    stack = CommandStack(document, default_registry())
    n: dict[str, object] = {getattr(node, "id", ""): node for node in document.walk()}
    tab, pane = n["t"].placement, n["q"].placement  # type: ignore[attr-defined]
    _run(stack, move_command((n["t"],), Target(n["n2"], "page", None)))
    _run(stack, move_command((n["q"],), Target(n["pw2"], "page", None)))
    assert n["t"].parent is n["n2"] and n["t"].placement is tab  # type: ignore[attr-defined]
    assert n["q"].parent is n["pw2"] and n["q"].placement is pane  # type: ignore[attr-defined]
    assert isinstance(tab, PagePlacement) and tab.text is not None and tab.text.value == "Tab"
    _run(stack, move_command((n["t"],), Target(n["pw2"], "page", None)))  # Notebook -> Paned
    _run(stack, move_command((n["q"],), Target(n["n2"], "page", None)))  # Paned -> Notebook
    assert n["t"].placement == PagePlacement()  # type: ignore[attr-defined]
    moved = n["q"].placement  # type: ignore[attr-defined]
    assert isinstance(moved, PagePlacement) and moved.text is not None
    assert moved.text.value == "q" and moved.weight != 3  # the default: tab text = node id


# ---------------------------------------------------------------- nudge / resize
def test_nudge_moves_by_one_cell_or_slot_and_explains_the_wrong_axis() -> None:
    _doc, stack, n = _form()
    _run(stack, nudge_command((n["c"],), 0, 1))
    assert _cell(n["c"])[:2] == (1, 1)
    assert nudge_command((n["a"],), -1, 0) == "That would put an element outside the grid."
    _run(stack, nudge_command((n["p1"],), 1, 0))
    assert _ids(n["p"]) == ["p0", "p2", "p1", "p3"]
    _run(stack, nudge_command((n["p1"],), -1, 0))
    assert _ids(n["p"]) == ["p0", "p1", "p2", "p3"]
    assert nudge_command((n["p0"],), -1, 0) == "'p0' is already there."
    assert nudge_command((n["p0"],), 0, 1) == (
        "This container arranges its children top to bottom; use Up and Down."
    )
    assert nudge_command((n["h0"],), 1, 0) == (
        "This container arranges its children side by side; use Left and Right."
    )
    assert nudge_command((n["n0"],), 0, 1) == "'n0' is already there."  # tabs: horizontal


def test_resize_changes_spans_with_a_minimum_of_one() -> None:
    _doc, stack, n = _form()
    built = resize_command(n["c"], 1, 0, 1, 3)
    assert isinstance(built, Macro) and built.label == "Resize element"
    _run(stack, built)
    assert _cell(n["c"]) == (1, 0, 1, 3)
    assert resize_command(n["c"], 1, 0, 0, 3) == (
        "An element must span at least one row and one column."
    )
    assert resize_command(n["c"], 1, 0, 1, 3) == "'c' is already there."
    assert resize_command(n["p0"], 0, 0, 1, 1) == "Only elements of a grid can be resized."
    assert resize_command(n["c"], -1, 0, 1, 1) == "That would put an element outside the grid."


# ---------------------------------------------------------------- resize handles (pure)
COLUMNS = (0, 10, 30, 30, 60)  # 4 columns; column 2 is empty (zero width)
ROWS = (0, 20, 40)  # 2 rows


def _resize(cell: GridCell, edge: Edge, x: int, y: int) -> tuple[int, int, int, int]:
    return resize_cell(cell, edge, COLUMNS, ROWS, x, y, pitch=16)


def test_right_and_bottom_handles_change_the_span_only() -> None:
    cell = GridCell(row=0, column=1)
    assert _resize(cell, "e", 58, 0) == (0, 1, 1, 3)  # snapped to the line at 60
    assert _resize(cell, "e", 74, 0) == (0, 1, 1, 4)  # the one append line (60 + 16)
    assert _resize(cell, "e", 500, 0) == (0, 1, 1, 4)  # never further
    assert _resize(cell, "e", -50, 0) == (0, 1, 1, 1)  # minimum span 1
    assert _resize(cell, "s", 0, 39) == (0, 1, 2, 1)
    assert _resize(cell, "se", 58, 39) == (0, 1, 2, 3)
    assert _resize(cell, "e", 9, 999) == (0, 1, 1, 1)  # the other axis is untouched


def test_left_and_top_handles_keep_the_far_edge() -> None:
    cell = GridCell(row=1, column=3, rowspan=1, columnspan=1)  # right edge at line 4
    assert _resize(cell, "w", 2, 0) == (1, 0, 1, 4)
    assert _resize(cell, "w", 999, 0) == (1, 3, 1, 1)  # minimum span 1, right edge kept
    assert _resize(cell, "w", -99, 0) == (1, 0, 1, 4)  # clamped to column 0
    assert _resize(cell, "n", 0, -5) == (0, 3, 2, 1)  # bottom edge kept
    assert _resize(cell, "nw", 11, 21) == (1, 1, 1, 3)


def test_a_tie_between_coincident_lines_changes_nothing() -> None:
    # Lines 2 and 3 both lie at x=30 (an empty column): the current edge wins the tie.
    assert _resize(GridCell(row=0, column=0, columnspan=3), "e", 30, 0) == (0, 0, 1, 3)
    assert _resize(GridCell(row=0, column=0, columnspan=2), "e", 30, 0) == (0, 0, 1, 2)
    assert _resize(GridCell(row=0, column=3), "w", 31, 0) == (0, 3, 1, 1)


@given(
    st.integers(0, 3),
    st.integers(1, 3),
    st.sampled_from(["n", "s", "w", "e", "nw", "ne", "sw", "se"]),
    st.integers(-100, 200),
    st.integers(-100, 200),
)
def test_resize_cell_never_breaks_the_rules(
    column: int, span: int, edge: Edge, x: int, y: int
) -> None:
    cell = GridCell(row=0, column=column, columnspan=min(span, 4 - column))
    row, col, rowspan, columnspan = _resize(cell, edge, x, y)
    assert min(row, col) >= 0 and min(rowspan, columnspan) >= 1
    end = cell.column + cell.columnspan
    if "w" in edge:
        assert col + columnspan == end  # the right edge is kept
    elif "e" in edge:
        assert col == cell.column and col + columnspan <= len(COLUMNS)
    else:
        assert (col, columnspan) == (cell.column, cell.columnspan)


def test_span_rect_follows_the_lines_and_the_append_line() -> None:
    assert span_rect(COLUMNS, ROWS, (0, 1, 2, 3)) == Rect(10, 0, 50, 40)
    assert span_rect(COLUMNS, ROWS, (1, 3, 1, 2), pitch=16) == Rect(30, 20, 46, 20)


# ---------------------------------------------------------------- selection model
def _session() -> tuple[DesignerSession, dict[str, object]]:
    session = DesignerSession(default_registry())
    session.open_result(read_ui_string(FORM), name="form")
    assert session.document is not None
    return session, {getattr(n, "id", ""): n for n in session.document.walk()}


def _selected(session: DesignerSession) -> tuple[object, ...]:
    return session.selection.nodes  # a call: mypy keeps no narrowing across the edits


def test_select_many_keeps_one_window_and_drops_foreign_and_repeated_nodes() -> None:
    session, n = _session()
    seen: list[Selection] = []
    session.selection_changed.connect(seen.append)
    foreign = Widget(class_name="Label", id="zz")
    session.select_many([n["a"], foreign, n["c"], n["a"], n["g1"]], origin="tree")
    assert session.selection.nodes == (n["c"], n["a"], n["g1"]) and len(seen) == 1
    session.select_many([n["c"], n["a"], n["g1"]], origin="canvas")
    assert len(seen) == 1  # unchanged: no signal
    session.select_many([n["a"], n["x"]], origin="tree")  # another window: replaces
    assert _selected(session) == (n["x"],)
    session.select_many([n["a"], n["w"]], origin="tree")  # a window stands alone
    assert _selected(session) == (n["w"],) and session.selection.node is n["w"]
    session.select_many([], origin="tree")
    assert _selected(session) == ()


def test_a_re_added_node_becomes_the_primary() -> None:
    """Ruling 13b-ii: the LAST occurrence of a repeated node decides its position."""
    session, n = _session()
    session.select_many([n["a"], n["c"], n["a"]], origin="canvas")
    assert session.selection.nodes == (n["c"], n["a"]) and session.selection.node is n["a"]


def test_pruning_drops_deleted_members_and_says_so() -> None:
    session, n = _session()
    assert session.stack is not None
    session.select_many([n["a"], n["c"]], origin="canvas")
    seen: list[Selection] = []
    session.selection_changed.connect(seen.append)
    assert session.stack.execute(delete_command(n["c"])).accepted
    assert session.selection.nodes == (n["a"],) and seen[-1].origin == "session"


def test_selection_rejects_a_bare_node_and_never_uses_truthiness() -> None:
    with pytest.raises(TypeError):
        Selection(Window(id="w"), "tree")  # type: ignore[arg-type]
    assert Selection((), "tree").node is None
