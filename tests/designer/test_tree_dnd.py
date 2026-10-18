"""Object-tree drop targets (pure; spec direct-manipulation 5 and 10, base spec 13.1)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core import CommandStack, default_registry, dump_ui, read_ui_string
from pyguibud.core.model import Document, Widget, Window
from pyguibud.designer.editing import move_command
from pyguibud.designer.targets import NewWidget, Target, keyboard_target
from pyguibud.designer.tree_dnd import is_container, release_text, target, zone_of

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)
DOC = HEADER + (
    '<window id="main" kind="main">'
    '<menubar><menu id="mnu"><prop name="text">File</prop><action id="act"/></menu></menubar>'
    '<statusbar id="sts"/><layout type="grid"/>'
    '<widget class="Button" id="btn"><cell row="0" column="0"/></widget>'
    '<widget class="Frame" id="frm"><cell row="1" column="0"/><layout type="grid"/>'
    '<widget class="Label" id="lbl"><cell row="0" column="0"/></widget>'
    '<widget class="Label" id="far"><cell row="0" column="2"/></widget></widget>'
    '<widget class="Frame" id="pck"><cell row="2" column="0"/><layout type="pack"/>'
    '<widget class="Button" id="b1"><pack/></widget><widget class="Button" id="b2"><pack/></widget>'
    '<widget class="Button" id="b3"><pack/></widget></widget>'
    '<widget class="Notebook" id="nbk"><cell row="3" column="0"/>'
    '<widget class="Frame" id="pg1"><page><prop name="text">One</prop></page>'
    '<layout type="grid"/></widget>'
    '<widget class="Frame" id="pg2"><page><prop name="text">Two</prop></page>'
    '<layout type="grid"/></widget></widget>'
    '<include id="inc" src="#" component="part"><cell row="4" column="0"/></include>'
    "</window>"
    '<window id="dlg" kind="dialog"><layout type="grid"/>'
    '<widget class="Label" id="other"><cell row="0" column="0"/></widget></window>'
    '<window id="part" kind="component"><layout type="grid"/></window></pyguibud-ui>'
)
REGISTRY = default_registry()
ACROSS = "Elements cannot be dragged to another window. Use Cut and Paste."
NOWHERE = "Drop elements onto a window, onto a container or next to an element."
LEAF = "'{id}' cannot hold elements: drop them before or after it."


def _doc_of(text: str) -> tuple[Document, dict[str, object]]:
    document = read_ui_string(text).document
    nodes: dict[str, object] = {}
    for window in document.children:
        for node in window.walk():
            if isinstance(node_id := getattr(node, "id", None), str):
                nodes[node_id] = node
    return document, nodes


def _doc() -> tuple[Document, dict[str, object]]:
    return _doc_of(DOC)


@pytest.mark.parametrize(
    ("y", "zone"),
    [(0, "before"), (4, "before"), (5, "into"), (14, "into"), (15, "after"), (19, "after")],
)  # fmt: skip
def test_zones_are_25_50_25(y: int, zone: str) -> None:
    assert zone_of(y, 20) == zone


@given(st.integers(0, 199), st.integers(1, 200))
def test_zones_are_monotonic_down_the_row(y: int, height: int) -> None:
    order = ["before", "into", "after"]
    y = min(y, height - 1)
    assert order.index(zone_of(y, height)) <= order.index(zone_of(height - 1, height))


def test_containers_are_windows_layout_and_page_widgets() -> None:
    _document, n = _doc()
    assert [is_container(n[k], REGISTRY) for k in ("main", "frm", "nbk", "btn", "inc", "mnu")] == [
        True, True, True, False, False, False
    ]  # fmt: skip


def test_reorder_in_pack_is_one_undo_step() -> None:
    document, n = _doc()
    stack = CommandStack(document, REGISTRY)
    found = target(n["b1"], "before", [n["b3"]], REGISTRY)
    assert found == Target(n["pck"], "slot", 0)
    assert target(n["b1"], "after", [n["b3"]], REGISTRY) == Target(n["pck"], "slot", 1)
    before = dump_ui(document)
    built = move_command([n["b3"]], found)
    assert not isinstance(built, str) and stack.execute(built).accepted
    assert [c.id for c in n["pck"].children] == ["b3", "b1", "b2"]  # type: ignore[attr-defined]
    stack.undo()
    assert dump_ui(document) == before


def test_into_is_the_canvas_keyboard_target_and_reparents() -> None:
    document, n = _doc()
    found = target(n["frm"], "into", [n["btn"]], REGISTRY)
    assert found == keyboard_target(None, n["frm"], NewWidget("Frame"), REGISTRY)
    assert isinstance(found, Target) and (found.row, found.column) == (0, 1)  # first free cell
    assert target(n["main"], "before", [n["b1"]], REGISTRY) == keyboard_target(
        None, n["main"], NewWidget("Frame"), REGISTRY
    )  # a window row always means into
    built = move_command([n["btn"]], found)
    assert not isinstance(built, str)
    assert CommandStack(document, REGISTRY).execute(built).accepted
    assert n["btn"].parent is n["frm"]  # type: ignore[attr-defined]


def test_before_takes_the_siblings_cell_and_after_the_next_one_in_reading_order() -> None:
    document, n = _doc()
    after = Target(n["frm"], "grid", 1, 0, 1, after=True)  # QA-19c-04: only "after" shifts
    assert target(n["lbl"], "after", [n["btn"]], REGISTRY) == after
    found = target(n["far"], "before", [n["btn"]], REGISTRY)
    assert found == Target(n["frm"], "grid", 1, 0, 2)
    # Ruling QA-14b2-12: what is in the way moves down its column (no new-row fallback).
    built = move_command([n["btn"]], found)
    assert not isinstance(built, str) and CommandStack(document, REGISTRY).execute(built).accepted
    assert [c.id for c in n["frm"].children] == ["lbl", "btn", "far"]  # type: ignore[attr-defined]
    cells = [(c.placement.row, c.placement.column) for c in n["frm"].children]  # type: ignore[attr-defined]
    assert cells == [(0, 0), (0, 2), (1, 2)]


COLUMN = HEADER + (
    '<window id="main" kind="main"><layout type="grid"/>'
    + "".join(
        f'<widget class="Label" id="{k}"><cell row="{r}" column="0"{s}/></widget>'
        for k, r, s in [*((k, r, "") for r, k in enumerate("abcd")), ("e", 5, ' rowspan="2"')]
    )
    + "</window></pyguibud-ui>"
)  # fmt: skip


@pytest.mark.parametrize(
    ("moved", "zone", "onto", "order", "rows"),
    [
        ("c", "before", "b", "acbde", (0, 2, 1, 3, 5)),  # b moves into the cell c left
        ("b", "before", "a", "bacde", (1, 0, 2, 3, 5)),
        ("a", "after", "d", "bcdae", (4, 1, 2, 3, 5)),
        ("a", "before", "e", "bcdae", (5, 1, 2, 3, 6)),  # a span moves down whole
        ("e", "before", "b", "aebcd", (0, 3, 4, 5, 1)),  # two rows of room for a span
    ],
)  # fmt: skip
def test_a_grid_drop_next_to_a_sibling_makes_room_in_one_step(
    moved: str, zone: str, onto: str, order: str, rows: tuple[int, ...]
) -> None:
    document, n = _doc_of(COLUMN)
    stack = CommandStack(document, REGISTRY)
    before = dump_ui(document)
    found = target(n[onto], zone, [n[moved]], REGISTRY)  # type: ignore[arg-type]
    built = move_command([n[moved]], found) if isinstance(found, Target) else found
    assert not isinstance(built, str) and stack.execute(built).accepted, built
    assert "".join(c.id for c in n["main"].children) == order  # type: ignore[attr-defined]
    assert tuple(n[k].placement.row for k in "abcde") == rows  # type: ignore[attr-defined]
    stack.undo()
    assert dump_ui(document) == before


def test_a_grid_drop_next_to_a_sibling_says_why_it_cannot() -> None:
    _document, n = _doc_of(COLUMN)
    found = target(n["c"], "before", [n["b"]], REGISTRY)  # b is just before c
    assert isinstance(found, Target)
    assert move_command([n["b"]], found) == "'b' is already there."
    last = HEADER + (
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="Label" id="a"><cell row="0" column="1"/></widget>'
        '<widget class="Label" id="b"><cell row="9998" column="0"/></widget>'
        '<widget class="Label" id="c"><cell row="9997" column="0"/></widget>'
        "</window></pyguibud-ui>"
    )
    _document, n = _doc_of(last)
    found = target(n["c"], "before", [n["a"]], REGISTRY)
    assert isinstance(found, Target)
    assert move_command([n["a"]], found) == "That would put an element outside the grid."


def test_pages_reorder_by_index() -> None:
    _document, n = _doc()
    assert target(n["pg1"], "before", [n["pg2"]], REGISTRY) == Target(n["nbk"], "page", 0)


@pytest.mark.parametrize(
    ("row", "zone", "payload", "reason"),
    [
        ("btn", "into", ("lbl",), LEAF.format(id="btn")),
        ("inc", "into", ("btn",), LEAF.format(id="inc")),
        ("lbl", "into", ("frm",), "A widget cannot be dropped into itself."),
        ("lbl", "after", ("frm",), "A widget cannot be dropped into itself."),
        ("frm", "into", ("frm",), "A widget cannot be dropped into itself."),
        ("other", "after", ("btn",), ACROSS),
        ("dlg", "into", ("btn",), ACROSS),
        ("btn", "after", ("dlg",), "Only widgets and included components can be moved."),
        ("btn", "after", ("mnu",), "Only widgets and included components can be moved."),
        ("act", "after", ("btn",), NOWHERE),
        ("mnu", "into", ("btn",), NOWHERE),
        ("sts", "before", ("btn",), NOWHERE),
        ("btn", "before", ("btn",), "'btn' is already there."),
    ],
)  # fmt: skip
def test_refused_drops_say_why(row: str, zone: str, payload: tuple[str, ...], reason: str) -> None:
    _document, n = _doc()
    assert target(n[row], zone, [n[k] for k in payload], REGISTRY) == reason  # type: ignore[arg-type]


def test_a_multi_node_drop_is_one_macro_in_sibling_order() -> None:
    document, n = _doc()
    found = target(n["b3"], "after", [n["b1"], n["b2"]], REGISTRY)
    assert found == Target(n["pck"], "slot", 3)
    built = move_command([n["b1"], n["b2"]], found)
    assert not isinstance(built, str)
    assert CommandStack(document, REGISTRY).execute(built).accepted
    assert [c.id for c in n["pck"].children] == ["b3", "b1", "b2"]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("payload", "cells"),
    [(("lbl", "far"), [(0, 0), (0, 2)]), (("b1", "b2", "b3"), [(0, 0), (0, 1), (0, 2)])],
)
def test_a_multi_drop_into_a_grid_puts_the_block_corner_on_the_free_cell(
    payload: tuple[str, ...], cells: list[tuple[int, int]]
) -> None:
    """QA-14b2-05: a row names no cell, so the anchor (last) keeps its offset from the block's
    top-left cell, which lands on the first free cell: no node on a negative cell."""
    document, n = _doc()
    nodes = [n[k] for k in payload]
    found = target(n["pg1"], "into", nodes, REGISTRY)
    assert isinstance(found, Target) and found.kind == "grid"
    built = move_command(nodes, found)
    assert not isinstance(built, str), built
    assert CommandStack(document, REGISTRY).execute(built).accepted
    assert [(c.placement.row, c.placement.column) for c in nodes] == cells  # type: ignore[attr-defined]


def test_release_texts_are_the_canvas_texts() -> None:
    _document, n = _doc()
    assert release_text([n["btn"]], Target(n["frm"], "grid")) == "Release to move 'btn' into 'frm'."
    assert (
        release_text([n["b1"], n["b2"]], Target(n["pck"], "slot")) == "Release to move 2 elements."
    )


MOVED = ["btn", "frm", "lbl", "far", "pck", "b1", "b2", "b3", "nbk", "pg1", "inc"]
ROWS = ["main", "btn", "frm", "lbl", "far", "pck", "b1", "b3", "nbk", "pg2", "inc"]


@given(st.sampled_from(MOVED), st.sampled_from(ROWS), st.sampled_from(["before", "into", "after"]))
def test_any_drop_is_applied_whole_or_refused_with_a_reason(
    moved: str, row: str, zone: str
) -> None:
    """Hypothesis: never a corrupt model; a refusal changes nothing (I1)."""
    document, n = _doc()
    stack = CommandStack(document, REGISTRY)
    before = dump_ui(document)
    found = target(n[row], zone, [n[moved]], REGISTRY)  # type: ignore[arg-type]
    built = move_command([n[moved]], found) if isinstance(found, Target) else found
    if isinstance(built, str):
        assert built and dump_ui(document) == before
        return
    outcome = stack.execute(built)
    if not outcome.accepted:
        assert outcome.message and dump_ui(document) == before
        return
    assert isinstance(n[moved].parent, Window | Widget)  # type: ignore[attr-defined]
    stack.undo()
    assert dump_ui(document) == before
