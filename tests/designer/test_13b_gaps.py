"""Step 13b independent test pass: undo granularity, byte-identical denials, round trips.

Pure (no Tk). Every gesture goes through a real ``CommandStack`` via the same builders and
``EditActions`` the canvas, tree and keys use (spec dnd-selection 5.3, 7.1, 7.3, 8, 11).
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.core import default_registry, dump_ui, read_ui_string, validate
from pyguibud.core.commands import InsertNode
from pyguibud.core.model import Document, GridCell, Widget
from pyguibud.designer.edit import EditActions
from pyguibud.designer.editing import (
    Edge,
    move_command,
    new_node,
    resize_cell,
    resize_command,
)
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.targets import Target
from tests.designer.test_move import FORM, _session

_NO_FIXTURE = [HealthCheck.function_scoped_fixture, HealthCheck.too_slow]


def _bytes(session: DesignerSession) -> bytes:
    assert session.document is not None
    return dump_ui(session.document)


def _errors(document: Document) -> list[str]:
    report = validate(document, default_registry())
    return [f"{f.code}: {f.message}" for f in report.errors]


def _edit(session: DesignerSession) -> tuple[EditActions, list[str], list[str]]:
    said: list[str] = []
    asked: list[str] = []

    def confirm(question: str, then: Callable[[], None]) -> None:
        asked.append(question)
        then()

    return EditActions(session, confirm, said.append), said, asked


def _ids(container: object) -> list[str]:
    return [c.id for c in container.children]  # type: ignore[attr-defined]


def test_the_fixture_itself_validates_clean() -> None:
    session, _n = _session()
    assert session.document is not None
    assert _errors(session.document) == []


# ---------------------------------------------------------------- denied = byte-identical
@pytest.mark.parametrize(
    ("picked", "target"),
    [
        (("a", "c"), ("w", 1, 1)),  # a -> (0, 1) is covered by b: validator denial
        (("a", "c"), ("w", 0, 5)),  # a would land on row -1: builder denial
        (("a", "b"), ("w", 1, 0)),  # b lands on (1, 1)..(1, 2), a on (1, 0): collides with c
        (("a",), ("w", 1, 0)),  # single occupied cell
        (("a",), ("w", 0, 0)),  # current place
    ],
)
def test_a_denied_grid_move_leaves_the_document_byte_identical(
    picked: tuple[str, ...], target: tuple[str, int, int]
) -> None:
    session, n = _session()
    assert session.stack is not None
    before, index = _bytes(session), session.stack.index
    built = move_command(
        tuple(n[p] for p in picked), Target(n[target[0]], "grid", None, target[1], target[2])
    )
    if isinstance(built, str):
        assert built
    else:
        outcome = session.stack.execute(built)
        assert not outcome.accepted and outcome.message
    assert _bytes(session) == before
    assert session.stack.index == index and session.stack.redo_text is None


def test_a_denied_multi_move_into_a_pack_or_page_target_changes_nothing() -> None:
    session, n = _session()
    assert session.stack is not None
    before = _bytes(session)
    # Mixed parents, a window as a member, and moving a container into its own subtree.
    for built in (
        move_command((n["a"], n["g1"]), Target(n["p"], "slot", 0)),
        move_command((n["w"],), Target(n["p"], "slot", 0)),
        move_command((n["g"], n["a"]), Target(n["g"], "grid", None, 5, 5)),
        move_command((n["p1"],), Target(n["p"], "slot", 1)),
    ):
        assert isinstance(built, str) and built
    assert _bytes(session) == before and session.stack.index == 0


def test_denied_keys_leave_the_document_byte_identical() -> None:
    session, n = _session()
    edit, said, _asked = _edit(session)
    before = _bytes(session)
    session.select(n["a"], origin="tree")
    edit.nudge(-1, 0)  # off the grid
    edit.nudge(0, 1)  # b's cell
    edit.span(0, 1)  # b's cell
    edit.span(-1, 0)  # below the minimum
    session.select_many([n["a"], n["c"]], origin="canvas")
    edit.nudge(-1, 0)  # a would go to row -1 (all or nothing for the block)
    session.select(n["p0"], origin="tree")
    edit.nudge(0, 1)  # wrong axis
    edit.reorder(-1)  # already first
    assert len(said) == 7 and all(said)
    assert _bytes(session) == before and session.stack is not None and session.stack.index == 0


# ---------------------------------------------------------------- one gesture = one undo step
_Gesture = Callable[[EditActions, DesignerSession, dict[str, object]], None]


def _gestures() -> list[tuple[str, _Gesture]]:
    def nudge_one(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select(n["c"], origin="tree")
        e.nudge(0, 1)

    def nudge_many(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select_many([n["c"], n["g"]], origin="canvas")
        e.nudge(0, 1)  # (below the bottom row would pass the append row: QA-13b-02)

    def span(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select(n["c"], origin="tree")
        e.span(0, 1)  # 'n' (the bottom row) may not grow downwards: QA-13b-02

    def reorder(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select(n["p2"], origin="tree")
        e.reorder(-1)

    def pack_nudge(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select_many([n["p1"], n["p2"]], origin="canvas")
        e.nudge(1, 0)

    def delete_many(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        s.select_many([n["c"], n["a"], n["p"]], origin="canvas")
        e.delete()

    def drag_reparent(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        assert s.stack is not None
        built = move_command((n["b"], n["a"]), Target(n["g"], "grid", None, 3, 3))
        assert not isinstance(built, str), built
        assert s.stack.execute(built).accepted

    def drag_into_page(e: EditActions, s: DesignerSession, n: dict[str, object]) -> None:
        assert s.stack is not None
        built = move_command((n["a"], n["c"]), Target(n["n"], "page", None))
        assert not isinstance(built, str), built
        assert s.stack.execute(built).accepted

    return [
        ("nudge_one", nudge_one),
        ("nudge_many", nudge_many),
        ("span", span),
        ("reorder", reorder),
        ("pack_nudge", pack_nudge),
        ("delete_many", delete_many),
        ("drag_reparent", drag_reparent),
        ("drag_into_page", drag_into_page),
    ]


@pytest.mark.parametrize("name", [g[0] for g in _gestures()])
def test_one_gesture_is_one_undo_step_and_redo_restores_it(name: str) -> None:
    gesture = dict(_gestures())[name]
    session, n = _session()
    edit, said, _asked = _edit(session)
    stack = session.stack
    assert stack is not None
    before = _bytes(session)
    gesture(edit, session, n)
    assert not said, said
    after = _bytes(session)
    assert after != before and stack.index == 1, name
    assert _errors(session.document) == []  # type: ignore[arg-type]
    assert stack.undo() and _bytes(session) == before and stack.index == 0
    assert not stack.undo()  # exactly one step: nothing further to undo
    assert stack.redo() and _bytes(session) == after and stack.index == 1
    assert not stack.redo()
    assert stack.undo() and _bytes(session) == before


def test_each_key_press_is_its_own_undo_step_even_when_repeated() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    stack = session.stack
    assert stack is not None
    before = _bytes(session)
    session.select(n["c"], origin="tree")
    for _ in range(4):  # the 4th press would pass the append column 3 (QA-13b-02): not recorded
        edit.nudge(0, 1)
    assert stack.index == 3 and n["c"].placement == GridCell(row=1, column=3)  # type: ignore[attr-defined]
    for expected in (2, 1, 0):
        assert stack.undo() and stack.index == expected
    assert _bytes(session) == before
    for _ in range(3):
        assert stack.redo()
    assert n["c"].placement == GridCell(row=1, column=3)  # type: ignore[attr-defined]


def test_the_selection_survives_move_undo_and_redo() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    assert session.stack is not None
    session.select_many([n["a"], n["c"]], origin="canvas")
    edit.nudge(0, 1)
    nodes = session.selection.nodes
    assert set(map(id, nodes)) == {id(n["a"]), id(n["c"])}
    session.stack.undo()
    assert set(map(id, session.selection.nodes)) == {id(n["a"]), id(n["c"])}
    session.stack.redo()
    assert set(map(id, session.selection.nodes)) == {id(n["a"]), id(n["c"])}


# ---------------------------------------------------------------- selection pruning
def test_pruning_after_undoing_an_insert_drops_only_the_new_node() -> None:
    session, n = _session()
    assert session.stack is not None and session.document is not None
    label = new_node(session.registry.require("Label"), session.document)
    assert isinstance(label, Widget)
    label.placement = GridCell(row=9, column=0)
    assert session.stack.execute(InsertNode(n["w"], label)).accepted
    session.select_many([n["a"], label, n["c"]], origin="canvas")
    assert len(session.selection.nodes) == 3
    assert session.stack.undo()
    assert [id(x) for x in session.selection.nodes] == [id(n["a"]), id(n["c"])]
    assert session.selection.origin == "session"
    session.stack.redo()  # redo does not resurrect the selection of the dropped node
    assert label not in session.selection.nodes


def test_pruning_after_a_multi_delete_leaves_a_valid_selection_and_undo_keeps_it_sane() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    assert session.stack is not None
    session.select_many([n["a"], n["c"]], origin="canvas")
    edit.delete()
    assert session.selection.node is n["w"]  # parent selected (spec 11)
    assert all(node in list(session.document.walk()) for node in session.selection.nodes)  # type: ignore[union-attr]
    session.stack.undo()
    assert all(node in list(session.document.walk()) for node in session.selection.nodes)  # type: ignore[union-attr]


def test_undoing_a_reparent_prunes_nothing_still_in_the_document() -> None:
    session, n = _session()
    assert session.stack is not None
    built = move_command((n["a"],), Target(n["g"], "grid", None, 4, 4))
    assert not isinstance(built, str)
    assert session.stack.execute(built).accepted
    session.select(n["a"], origin="canvas")
    session.stack.undo()
    assert session.selection.node is n["a"] and n["a"].parent is n["w"]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- multi-delete restoration
@pytest.mark.parametrize(
    "picked",
    [
        ["a", "c"],
        ["c", "a"],  # selection order is the reverse of document order
        ["c", "p", "a", "n"],
        ["p0", "p2"],
        ["p3", "p0", "p1"],
        ["p", "g"],
        ["h0", "p3", "n"],
    ],
)
def test_ctrl_z_after_a_multi_delete_restores_order_and_placements(picked: list[str]) -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    stack = session.stack
    assert stack is not None
    before = _bytes(session)
    layout = {k: (getattr(v, "parent", None), getattr(v, "placement", None)) for k, v in n.items()}
    order = {k: _ids(v) for k, v in n.items() if hasattr(v, "children") and not isinstance(v, str)}
    session.select_many([n[p] for p in picked], origin="canvas")
    edit.delete()
    assert stack.index == 1
    assert all(n[p].parent is None for p in picked)  # type: ignore[attr-defined]
    deleted = _bytes(session)
    assert deleted != before and _errors(session.document) == []  # type: ignore[arg-type]
    assert stack.undo()
    assert _bytes(session) == before
    for key, (parent, placement) in layout.items():
        assert getattr(n[key], "parent", None) is parent
        assert getattr(n[key], "placement", None) == placement
    assert {k: _ids(n[k]) for k in order} == order
    assert stack.redo() and _bytes(session) == deleted


def test_a_multi_delete_includes_nested_selected_children_once() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    assert session.stack is not None
    before = _bytes(session)
    session.select_many([n["g1"], n["g"], n["p0"]], origin="canvas")  # g1 is nested in g
    edit.delete()
    assert session.stack.index == 1
    assert session.stack.undo() and _bytes(session) == before


# ---------------------------------------------------------------- the .ui stays valid
def _round_trip_clean(session: DesignerSession) -> None:
    data = _bytes(session)
    result = read_ui_string(data.decode("utf-8"))
    assert [f for f in result.warnings if f.severity == "error"] == []
    assert _errors(result.document) == []
    assert dump_ui(result.document) == data  # canonical: write(read(x)) == x


def test_a_resize_and_move_round_trip_keeps_the_ui_valid_and_canonical() -> None:
    session, n = _session()
    edit, _said, _asked = _edit(session)
    assert session.stack is not None
    session.select(n["n"], origin="tree")
    edit.span(1, 2)
    _round_trip_clean(session)
    built = resize_command(n["c"], 1, 0, 1, 1)  # no change: refused or a no-op, never invalid
    if not isinstance(built, str):
        session.stack.execute(built)
    _round_trip_clean(session)
    built = move_command((n["b"], n["a"]), Target(n["g"], "grid", None, 5, 5))
    assert not isinstance(built, str), built
    assert session.stack.execute(built).accepted
    _round_trip_clean(session)
    built = move_command((n["p1"], n["p3"]), Target(n["n"], "page", None))
    assert not isinstance(built, str), built
    assert session.stack.execute(built).accepted
    _round_trip_clean(session)
    while session.stack.undo():
        _round_trip_clean(session)
    assert _bytes(session) == dump_ui(read_ui_string(FORM).document)


# ---------------------------------------------------------------- property tests
_OPS = st.one_of(
    st.tuples(st.just("nudge"), st.integers(-1, 1), st.integers(-1, 1)),
    st.tuples(st.just("span"), st.integers(-1, 1), st.integers(-1, 1)),
    st.tuples(st.just("reorder"), st.integers(-1, 1), st.just(0)),
    st.tuples(st.just("delete"), st.just(0), st.just(0)),
)
_PICKS = st.lists(
    st.sampled_from(["a", "b", "c", "g", "g1", "p", "p0", "p1", "p2", "p3", "h", "h0", "n", "n0"]),
    min_size=1,
    max_size=4,
)


@settings(max_examples=60, deadline=None, suppress_health_check=_NO_FIXTURE)
@given(st.lists(st.tuples(_PICKS, _OPS), min_size=1, max_size=8))
def test_random_key_sequences_never_corrupt_the_document(
    script: list[tuple[list[str], tuple[str, int, int]]],
) -> None:
    """Every key is applied or denied; the document stays valid; undo/redo are exact."""
    session, n = _session()
    edit, _said, _asked = _edit(session)
    stack = session.stack
    assert stack is not None
    original = _bytes(session)
    states = [original]
    for picks, (op, a, b) in script:
        live = [n[p] for p in picks if getattr(n[p], "parent", None) is not None]
        if not live:
            continue
        session.select_many(live, origin="canvas")
        index = stack.index
        before = _bytes(session)
        if op == "nudge":
            edit.nudge(a, b)
        elif op == "span":
            edit.span(a, b)
        elif op == "reorder":
            edit.reorder(a)
        else:
            edit.delete()
        assert _errors(session.document) == []  # type: ignore[arg-type]
        if stack.index == index:
            assert _bytes(session) == before  # a denial changes nothing
        else:
            assert stack.index == index + 1  # one key = one step
            states.append(_bytes(session))
    while stack.undo():
        states.pop()
        assert _bytes(session) == states[-1]
    assert _bytes(session) == original and len(states) == 1
    while stack.redo():
        pass
    assert _errors(session.document) == []  # type: ignore[arg-type]


_EDGES: list[Edge] = ["n", "s", "w", "e", "nw", "ne", "sw", "se"]


@settings(max_examples=80, deadline=None)
@given(
    st.sampled_from(_EDGES),
    st.integers(0, 600),
    st.integers(0, 400),
)
def test_resize_gestures_either_apply_cleanly_or_are_denied(edge: Edge, x: int, y: int) -> None:
    session, n = _session()
    assert session.stack is not None
    node = n["b"]
    cell = node.placement  # type: ignore[attr-defined]
    columns, rows = [0, 100, 200, 300, 400, 500], [0, 40, 80, 120, 160, 200]
    row, column, rowspan, columnspan = resize_cell(cell, edge, columns, rows, x, y)
    before = _bytes(session)
    assert rowspan >= 1 and columnspan >= 1 and row >= 0 and column >= 0
    built = resize_command(node, row, column, rowspan, columnspan)
    if isinstance(built, str):
        assert built and _bytes(session) == before
        return
    outcome = session.stack.execute(built)
    if outcome.accepted:
        assert _errors(session.document) == []  # type: ignore[arg-type]
        assert session.stack.undo()
    assert _bytes(session) == before
