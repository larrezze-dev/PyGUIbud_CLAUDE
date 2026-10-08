"""Canvas keys, band containment and multi-delete without Tk (spec dnd-selection 7.2, 7.3, 11)."""

from __future__ import annotations

from collections.abc import Callable

from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core.model import GridCell
from pyguibud.designer.edit import EditActions, tab_order
from pyguibud.designer.geometry import Rect
from pyguibud.designer.session import DesignerSession
from tests.designer.test_move import _session


def _edit(
    session: DesignerSession, busy: Callable[[], bool] = lambda: False
) -> tuple[EditActions, list[str], list[str]]:
    said: list[str] = []
    asked: list[str] = []

    def confirm(question: str, then: Callable[[], None]) -> None:
        asked.append(question)
        then()

    return EditActions(session, confirm, said.append, busy=busy), said, asked


def _ids(nodes: tuple[object, ...]) -> list[str]:
    return [getattr(n, "id", "") for n in nodes]


# ---------------------------------------------------------------- rubber band (D5)
def test_a_band_takes_only_rects_that_lie_fully_inside() -> None:
    band = Rect(10, 10, 100, 50)
    assert band.covers(Rect(10, 10, 100, 50)) and band.covers(Rect(20, 20, 5, 5))
    assert not band.covers(Rect(9, 20, 5, 5)) and not band.covers(Rect(100, 20, 11, 5))
    assert not band.covers(Rect(20, 20, 0, 5))  # an unmapped (empty) widget is never picked


@given(st.integers(-50, 50), st.integers(-50, 50), st.integers(0, 60), st.integers(0, 60))
def test_covers_agrees_with_the_intersection(x: int, y: int, w: int, h: int) -> None:
    band, rect = Rect(0, 0, 40, 30), Rect(x, y, w, h)
    assert band.covers(rect) == (not rect.empty and band.intersection(rect) == rect)


# ---------------------------------------------------------------- Tab, Enter, Esc, Ctrl+A
def test_tab_walks_the_window_in_pre_order_and_wraps() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    order = ["a", "b", "c", "g", "g1", "p", "p0", "p1", "p2", "p3", "h", "h0", "n", "n0"]
    assert _ids(tuple(tab_order(n["w"]))) == order
    session.select(n["w"], origin="tree")
    edit.select_step(1)
    assert session.selection.node is n["a"]
    edit.select_step(-1)
    assert session.selection.node is n["n0"]  # wraps backwards
    edit.select_step(1)
    assert session.selection.node is n["a"]  # and forwards
    session.select(n["w"], origin="tree")
    edit.select_step(-1)
    assert session.selection.node is n["n0"]


def test_enter_esc_and_ctrl_a_walk_the_tree_of_containers() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    session.select(n["g"], origin="tree")
    edit.select_child()
    assert session.selection.node is n["g1"]
    edit.select_parent()
    edit.select_parent()
    assert session.selection.node is n["w"]
    edit.select_parent()
    assert session.selection.node is n["w"]  # a window stays selected
    session.select(n["p1"], origin="tree")
    edit.select_all()
    assert _ids(session.selection.nodes) == ["p0", "p2", "p3", "p1"]  # p1 stays the primary
    session.select(n["w"], origin="tree")
    edit.select_all()
    assert len(session.selection.nodes) == 7 and session.selection.node is n["n"]


# ---------------------------------------------------------------- arrows and Shift+arrows
def test_each_arrow_press_is_one_command_and_a_refusal_says_why() -> None:
    session, n = _session()
    edit, said, _asked = _edit(session)
    stack = session.stack
    assert stack is not None
    session.select(n["c"], origin="tree")
    edit.nudge(0, 1)
    edit.nudge(0, 1)
    assert n["c"].placement == GridCell(row=1, column=2)  # type: ignore[attr-defined]
    assert stack.index == 2 and session.selection.node is n["c"]
    session.select(n["a"], origin="tree")
    edit.nudge(-1, 0)
    assert said[-1] == "That would put an element outside the grid." and stack.index == 2
    session.select(n["p0"], origin="tree")
    edit.nudge(0, 1)
    assert said[-1] == "This container arranges its children top to bottom; use Up and Down."
    edit.nudge(1, 0)
    assert _ids(tuple(n["p"].children)) == ["p1", "p0", "p2", "p3"]  # type: ignore[attr-defined]


def test_shift_arrows_change_the_span_with_a_minimum_of_one() -> None:
    session, n = _session()
    edit, said, _asked = _edit(session)
    assert session.stack is not None
    session.select(n["a"], origin="tree")
    edit.span(0, 1)  # 'b' takes the next cell: the validator's reason, nothing recorded
    assert said and session.stack.index == 0
    session.select(n["n"], origin="tree")
    edit.span(0, 1)
    edit.span(1, 0)  # 'n' is in the last row: row 6 is past the append row (QA-13b-02)
    assert said[-1] == "That would put an element outside the grid."
    cell = n["n"].placement  # type: ignore[attr-defined]
    assert (cell.row, cell.column, cell.rowspan, cell.columnspan) == (5, 0, 1, 2)
    edit.span(-1, 0)
    edit.span(-1, 0)
    assert said[-1] == "An element must span at least one row and one column."
    session.select(n["p0"], origin="tree")
    edit.span(0, 1)
    assert said[-1] == "Only elements of a grid can be resized."


def test_key_repeats_are_dropped_while_a_rebuild_is_pending() -> None:
    session, n = _session()
    pending = [True]
    edit, said, _asked = _edit(session, busy=lambda: pending[0])
    assert session.stack is not None
    session.select(n["c"], origin="tree")
    edit.nudge(0, 1)
    edit.span(0, 1)
    edit.reorder(1)
    assert session.stack.index == 0 and said == []
    pending[0] = False
    edit.nudge(0, 1)
    assert session.stack.index == 1


def test_alt_up_and_down_reorder_siblings_without_moving_cells() -> None:
    session, n = _session()
    edit, said, _asked = _edit(session)
    session.select(n["p2"], origin="tree")
    edit.reorder(-1)
    assert _ids(tuple(n["p"].children)) == ["p0", "p2", "p1", "p3"]  # type: ignore[attr-defined]
    session.select(n["a"], origin="tree")
    edit.reorder(1)
    assert _ids(tuple(n["w"].children))[:2] == ["b", "a"]  # type: ignore[attr-defined]
    assert n["a"].placement == GridCell(row=0, column=0, sticky="w")  # type: ignore[attr-defined]
    session.select(n["p3"], origin="tree")
    edit.reorder(1)
    assert said[-1] == "'p3' is already there."


# ---------------------------------------------------------------- multi-delete
def test_a_multi_delete_is_one_undo_step() -> None:
    session, n = _session()
    edit, _said, asked = _edit(session)
    stack = session.stack
    assert stack is not None
    session.select_many([n["a"], n["c"]], origin="canvas")
    edit.delete()
    assert asked == [] and n["a"].parent is None and n["c"].parent is None  # type: ignore[attr-defined]
    assert stack.undo_text == "Delete elements" and session.selection.node is n["w"]
    stack.undo()
    assert n["a"].parent is n["w"] and n["c"].parent is n["w"]  # type: ignore[attr-defined]


def test_a_multi_delete_with_children_asks_first_and_skips_nested_members() -> None:
    session, n = _session()
    edit, _said, asked = _edit(session)
    assert session.stack is not None
    session.select_many([n["g"], n["g1"]], origin="tree")  # g1 goes with g
    edit.delete()
    assert asked == ["Delete 'g' and its 1 element?"] and n["g"].parent is None  # type: ignore[attr-defined]
    session.stack.undo()
    session.select_many([n["g"], n["p"]], origin="tree")
    edit.delete()
    assert asked[-1] == "Delete 2 elements and the elements inside them?"
    assert n["g"].parent is None and n["p"].parent is None  # type: ignore[attr-defined]
    assert session.stack.undo_text == "Delete elements"
