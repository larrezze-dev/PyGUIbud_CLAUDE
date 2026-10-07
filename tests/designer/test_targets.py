"""Insertion targets, command builders and selection pruning (pure; spec dnd-selection 5, 7.1)."""

from __future__ import annotations

import keyword
import re
from itertools import accumulate

from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core import CommandStack, default_registry, read_ui_bytes, read_ui_string
from pyguibud.core.model import (
    Document,
    GridCell,
    Layout,
    PackPlacement,
    PagePlacement,
    Statusbar,
    Widget,
    WidgetSpec,
    Window,
)
from pyguibud.core.validate import RESERVED_IDS
from pyguibud.designer.editing import delete_command, insert_command, new_node, refusal, unique_id
from pyguibud.designer.geometry import ChildBox, ContainerBox, Rect, Snapshot
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.targets import Moving, NewWidget, Target, hit_test, keyboard_target
from pyguibud.designer.templates import template_bytes, template_info

ID = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)


def _template(name: str) -> Document:
    info = template_info(name)
    assert info is not None
    return read_ui_bytes(template_bytes(info), source=name).document


# ---------------------------------------------------------------- unique_id / new_node
def test_unique_id_skips_every_used_id_and_converts_the_class_name() -> None:
    document = _template("login_form")
    assert unique_id(document, "ScrolledFrame") == "scrolled_frame1"
    assert unique_id(document, "tb:Meter") == "meter1"
    document.children[0].children[0].id = "label1"
    assert unique_id(document, "Label") == "label2"
    assert unique_id(None, "LabelFrame") == "label_frame1"


@given(st.text(max_size=120))
def test_unique_id_is_always_a_valid_free_id(stem: str) -> None:
    result = unique_id(None, stem or "x")
    assert ID.match(result) and result not in RESERVED_IDS and not keyword.iskeyword(result)


def test_new_node_validates_for_every_core_widget_spec() -> None:
    registry = default_registry()
    document = _template("main_window")
    stack = CommandStack(document, registry)
    window = document.children[0]
    for spec in registry.specs():
        payload = NewWidget.of(spec)
        node = new_node(spec, document)
        if payload.role == "menu":
            assert keyboard_target(window, None, payload, registry) is None
            continue
        target = keyboard_target(window, None, payload, registry)
        assert target is not None
        if payload.role != "widget":  # the template already has both bars
            assert refusal(target, node)
            continue
        assert isinstance(node, Widget) and ID.match(node.id)
        assert stack.check(insert_command(target, node)).accepted, spec.name


def test_new_node_of_an_extension_keeps_fallback_and_plugin() -> None:
    spec = WidgetSpec(
        name="tb:Meter",
        display_name="Meter",
        category="Display",
        api_version=1,
        fallback="Progressbar",
        plugin="tbx",
    )
    node = new_node(spec, None)
    assert isinstance(node, Widget)
    assert (node.id, node.fallback, node.plugin, node.layout) == (
        "meter1",
        "Progressbar",
        "tbx",
        None,
    )
    frame = new_node(default_registry().require("Frame"), None)
    assert isinstance(frame, Widget) and frame.layout == Layout(type="grid")
    assert frame.props == {}


def test_a_bar_goes_through_set_field_and_the_window_owns_a_copy() -> None:
    registry = default_registry()
    document = read_ui_string(
        HEADER + '<window id="w"><layout type="grid"/></window></pyguibud-ui>'
    )
    stack = CommandStack(document.document, registry)
    window = document.document.children[0]
    bar = new_node(registry.require("Statusbar"), document.document)
    assert isinstance(bar, Statusbar)
    target = keyboard_target(window, None, NewWidget.of(registry.require("Statusbar")), registry)
    assert target is not None and refusal(target, bar) is None
    assert stack.execute(insert_command(target, bar)).accepted
    assert window.statusbar is not None and window.statusbar is not bar
    assert refusal(target, bar) == "This window already has a status bar."


def test_delete_command_removes_and_undo_restores() -> None:
    document = _template("login_form")
    stack = CommandStack(document, default_registry())
    window = document.children[0]
    button = window.children[-1]
    assert stack.execute(delete_command(button)).accepted and button not in window.children
    stack.undo()
    assert window.children[-1] is button


# ---------------------------------------------------------------- keyboard_target
def test_keyboard_target_grid_first_free_cell_and_leaf_anchor() -> None:
    registry = default_registry()
    document = _template("login_form")  # cells (0,0) (0,1) (1,0) (1,1) (2,1)
    window = document.children[0]
    payload = NewWidget("Label")
    target = keyboard_target(window, None, payload, registry)
    assert target is not None and (target.row, target.column) == (2, 0)
    entry = window.children[1]  # (0, 1): the next free cell after it is (2, 0)
    target = keyboard_target(window, entry, payload, registry)
    assert (
        target is not None and target.container is window and (target.row, target.column) == (2, 0)
    )
    last = window.children[-1]  # (2, 1): nothing after it, so a new row
    target = keyboard_target(window, last, payload, registry)
    assert target is not None and (target.row, target.column) == (3, 0)


def test_keyboard_target_empty_window_pack_and_pages() -> None:
    registry = default_registry()
    empty = _template("main_window").children[0]
    target = keyboard_target(empty, None, NewWidget("Button"), registry)
    assert target == Target(empty, "grid", None, 0, 0)
    settings = _template("settings").children[0]
    notebook = settings.children[0]
    assert isinstance(notebook, Widget)
    general = notebook.children[0]
    assert isinstance(general, Widget)
    target = keyboard_target(settings, notebook, NewWidget("Frame"), registry)
    assert target == Target(notebook, "page", None)
    target = keyboard_target(settings, general, NewWidget("Frame"), registry)
    assert target == Target(general, "slot", None)  # a pack container: append
    check = general.children[0]
    target = keyboard_target(settings, check, NewWidget("Button"), registry)
    assert target == Target(general, "slot", 1)  # after the selected leaf
    node = new_node(registry.require("Frame"), None)
    insert_command(Target(notebook, "page", None), node)
    assert isinstance(node, Widget) and isinstance(node.placement, PagePlacement)
    assert node.placement.text is not None and node.placement.text.value == node.id


# ---------------------------------------------------------------- hit_test
def _grid_box(node: object, widths: list[int], heights: list[int], depth: int = 0) -> ContainerBox:
    xs = tuple(accumulate(widths, initial=10))
    ys = tuple(accumulate(heights, initial=10))
    rect = Rect(0, 0, xs[-1] + 40, ys[-1] + 40)
    return ContainerBox(node, rect, rect, "grid", "vertical", (), depth, xs, ys)


@given(
    st.lists(st.integers(4, 60), min_size=1, max_size=20),
    st.lists(st.integers(4, 60), min_size=1, max_size=20),
    st.data(),
)
def test_grid_hits_stay_in_bounds_and_are_monotonic(
    widths: list[int], heights: list[int], data: st.DataObject
) -> None:
    window = Window(id="w")
    box = _grid_box(window, widths, heights)
    snapshot = Snapshot((box,), ())
    y = data.draw(st.integers(0, box.rect.h - 1))
    xs = sorted(data.draw(st.lists(st.integers(0, box.rect.w - 1), min_size=2, max_size=6)))
    columns = []
    for x in xs:
        target = hit_test(snapshot, x, y, NewWidget("Label"))
        assert target is not None and target.kind == "grid"
        assert 0 <= target.column <= len(widths) and 0 <= target.row <= len(heights)
        assert target.rect.contains(x, y) or x < box.columns[0] or y < box.rows[0]
        columns.append(target.column)
    assert columns == sorted(columns)


def test_an_empty_grid_is_one_virtual_cell() -> None:
    window = Window(id="w")
    rect = Rect(0, 0, 100, 50)
    box = ContainerBox(window, rect, rect, "grid", "vertical", (), 0, (0, 0), (0, 0))
    target = hit_test(Snapshot((box,), ()), 70, 40, NewWidget("Label"))
    assert target is not None and (target.row, target.column) == (0, 0) and target.rect == rect


@given(st.lists(st.integers(5, 40), min_size=0, max_size=50), st.data())
def test_pack_index_counts_the_midpoints_before_the_pointer(
    heights: list[int], data: st.DataObject
) -> None:
    window = Window(id="w")
    window.layout = Layout(type="pack")
    tops = list(accumulate(heights, initial=0))
    kids = []
    for index, height in enumerate(heights):
        child = Widget(class_name="Label", id=f"l{index}", placement=PackPlacement())
        window.insert_child(index, child)
        kids.append(ChildBox(child, Rect(0, tops[index], 50, height), child.placement))
    rect = Rect(0, 0, 50, tops[-1] + 20)
    box = ContainerBox(window, rect, rect, "pack", "vertical", tuple(kids), 0)
    y = data.draw(st.integers(0, rect.h - 1))
    target = hit_test(Snapshot((box,), ()), 10, y, NewWidget("Label"))
    expected = sum(1 for k in kids if k.rect.y + k.rect.h // 2 < y)
    assert target is not None and target.kind == "slot" and target.index == expected
    assert target.bar


def test_edge_band_picks_the_parent_and_moving_nodes_are_never_containers() -> None:
    window = Window(id="w")
    frame = Widget(class_name="Frame", id="f", layout=Layout(type="grid"))
    window.insert_child(0, frame)
    outer = _grid_box(window, [200], [200])
    inner_rect = Rect(50, 50, 100, 100)
    inner = ContainerBox(
        frame, inner_rect, inner_rect, "grid", "vertical", (), 1, (50, 150), (50, 150)
    )
    snapshot = Snapshot((outer, inner), ())
    assert hit_test(snapshot, 100, 100, NewWidget("Label")).container is frame  # type: ignore[union-attr]
    assert hit_test(snapshot, 52, 100, NewWidget("Label")).container is window  # type: ignore[union-attr]
    moving = hit_test(snapshot, 100, 100, Moving((frame,)))
    assert moving is not None and moving.container is window


def test_nothing_outside_the_visible_area_and_no_target_for_menus() -> None:
    window = Window(id="w")
    box = _grid_box(window, [50], [50])
    snapshot = Snapshot((box,), (), visible=Rect(0, 0, 30, 30))
    assert hit_test(snapshot, 40, 10, NewWidget("Label")) is None
    assert hit_test(snapshot, 10, 10, NewWidget("Menu", "menu")) is None
    bar = hit_test(snapshot, 10, 10, NewWidget("Statusbar", "statusbar"))
    assert bar is not None and bar.kind == "bar" and bar.container is window


# ---------------------------------------------------------------- selection
def test_selection_is_pruned_after_undoing_an_insert() -> None:
    session = DesignerSession(default_registry())
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    node = new_node(session.registry.require("Button"), session.document)
    assert session.stack.execute(insert_command(Target(window, "grid"), node)).accepted
    seen: list[Selection] = []
    session.selection_changed.connect(seen.append)
    session.select(node, origin="canvas")
    assert session.selection.primary is node
    session.stack.undo()
    selection: Selection = session.selection  # re-read: mypy keeps the narrowed tuple type
    assert not selection.nodes and seen[-1].origin == "session"
    assert isinstance(node, Widget) and node.placement == GridCell(row=0, column=0)


def test_a_notebook_drop_appends_although_only_the_shown_page_is_visible() -> None:
    notebook = Widget(class_name="Notebook", id="nb")
    pages = [Widget(class_name="Frame", id=f"p{i}", placement=PagePlacement()) for i in range(3)]
    for index, page in enumerate(pages):
        notebook.insert_child(index, page)
    rect = Rect(0, 0, 100, 100)
    shown = ChildBox(pages[0], Rect(0, 20, 100, 80), pages[0].placement)
    box = ContainerBox(notebook, rect, rect, "pages", "", (shown,), 0)
    target = hit_test(Snapshot((box,), ()), 50, 50, NewWidget("Frame"))
    assert target == Target(notebook, "page", None)  # None appends after the last page
