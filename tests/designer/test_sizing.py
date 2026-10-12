"""Sizes by direct manipulation: the pure rules (spec direct-manipulation 2-4, 10).

No Tk: the canvas's measurements are given as numbers; every command runs on a real stack.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

from pyguibud.core import CommandStack, default_registry, read_ui_string
from pyguibud.core.commands import Macro, RemoveProp, SetField, SetProp
from pyguibud.core.model import GridCell, PackPlacement, Prop, Widget, WidgetSpec, Window
from pyguibud.designer import sizing
from pyguibud.designer.edit import EditActions
from pyguibud.designer.properties import field_rows
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.sizing import Measured, Start

REGISTRY = default_registry()
FORM = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
<window id="w" min_width="200"><layout type="grid"/>
  <widget class="Button" id="b"><prop name="text">B</prop><cell row="0" column="0"/></widget>
  <widget class="Frame" id="f"><cell row="1" column="0"/><layout type="grid"/></widget>
  <widget class="Frame" id="g"><cell row="2" column="0"/><layout type="pack"/>
    <widget class="Label" id="g0"><prop name="text">0</prop><pack fill="x"/></widget>
    <widget class="Checkbutton" id="g1"><prop name="text">1</prop><pack/></widget>
    <widget class="Entry" id="g2"><prop name="width">12</prop><pack/></widget>
  </widget>
  <widget class="Notebook" id="n"><cell row="3" column="0"/>
    <widget class="Frame" id="n0"><page><prop name="text">0</prop></page>
      <layout type="pack"/></widget>
  </widget>
  <widget class="Scale" id="s"><prop name="orient">vertical</prop><cell row="4" column="0"/>
  </widget>
</window>
<window id="c" kind="component"><layout type="grid"/></window>
</pyguibud-ui>"""


def _form() -> tuple[CommandStack, dict[str, object]]:
    document = read_ui_string(FORM).document
    nodes: dict[str, object] = {getattr(n, "id", ""): n for n in document.walk()}
    return CommandStack(document, REGISTRY), nodes


def _spec(node: object) -> WidgetSpec | None:
    return REGISTRY.get(getattr(node, "class_name", ""))


def _widget(class_name: str, **props: str) -> Widget:
    node = Widget(class_name=class_name, id="x")
    for name, value in props.items():
        node.set_prop(Prop(name=name, value=value))
    return node


# ---------------------------------------------------------------- drag_size (spec 2.3)
@given(
    st.integers(1, 10_000), st.integers(-30_000, 30_000), st.integers(-30_000, 30_000),
    st.floats(1.0, 40.0),
)  # fmt: skip
def test_drag_size_is_monotonic_and_clamped(start: int, a: int, b: int, pitch: float) -> None:
    low, high = sorted((a, b))
    for snap in (0, 1, 4):
        small = sizing.drag_size(start, low, pitch, snap=snap)
        large = sizing.drag_size(start, high, pitch, snap=snap)
        assert 1 <= small <= large <= sizing.MAX_SIZE


def test_drag_size_rounds_units_half_away_and_snaps_pixels() -> None:
    assert sizing.drag_size(10, 7.4, 5) == 11  # 1.48 units
    assert sizing.drag_size(10, 7.5, 5) == 12  # 1.5 rounds away from the press
    assert sizing.drag_size(10, -7.5, 5) == 8
    assert sizing.drag_size(100, 5, 1, snap=4) == 104
    assert sizing.drag_size(100, 5, 1, snap=1) == 105
    assert sizing.drag_size(3, -500, 1, snap=4) == 1  # never 0
    assert sizing.drag_size(10, 1e9, 5) == sizing.MAX_SIZE


def test_an_unset_size_dragged_back_keeps_its_natural_size() -> None:
    natural = Start(14, False)
    assert sizing.drag_value(natural, 0, 7.0, "chars", fine=False) is None
    assert sizing.drag_value(natural, -40, 7.0, "chars", fine=False) is None
    assert sizing.drag_value(natural, 21, 7.0, "chars", fine=False) == 17
    assert sizing.drag_value(Start(14, True), -14, 7.0, "chars", fine=False) == 12
    # Back at the press: the start, never a snapped value (a click records nothing).
    assert sizing.drag_value(Start(150, True), 0, 1.0, "px", fine=False) == 150
    assert sizing.drag_value(Start(150, True), 1, 1.0, "px", fine=False) == 150
    assert sizing.drag_value(Start(150, True), 2, 1.0, "px", fine=False) == 152


def test_start_value_reads_the_property_or_estimates() -> None:
    assert sizing.start_value(_widget("Button", width="9"), "width", 300, 7.0) == Start(9, True)
    assert sizing.start_value(_widget("Button"), "width", 70, 7.0) == Start(10, False)
    assert sizing.start_value(_widget("Button", width="x"), "width", 0, 7.0) == Start(1, False)


# ---------------------------------------------------------------- size_axes (spec 2.1)
EXPECTED = {
    "Frame": (("width", "px"), ("height", "px")),
    "LabelFrame": (("width", "px"), ("height", "px")),
    "Notebook": (("width", "px"), ("height", "px")),
    "Canvas": (("width", "px"), ("height", "px")),
    "ScrolledFrame": (None, ("height", "px")),
    "Label": (("width", "chars"), None),
    "Button": (("width", "chars"), None),
    "Entry": (("width", "chars"), None),
    "Combobox": (("width", "chars"), None),
    "Spinbox": (("width", "chars"), None),
    "Text": (("width", "chars"), ("height", "lines")),
    "Listbox": (None, ("height", "rows")),
    "Treeview": (None, ("height", "rows")),
    "Scale": (("length", "px"), None),
    "Progressbar": (("length", "px"), None),
}


@pytest.mark.parametrize("spec", REGISTRY.specs(), ids=lambda s: s.name)
def test_size_axes_follow_the_table_and_the_registry(spec: WidgetSpec) -> None:
    axes = sizing.size_axes(_widget(spec.name), spec)
    assert axes == EXPECTED.get(spec.name, (None, None))
    for axis in axes:
        assert axis is None or spec.property(axis[0]) is not None


def test_oriented_classes_and_extensions() -> None:
    scale, bar = REGISTRY.require("Scale"), REGISTRY.require("Progressbar")
    assert sizing.size_axes(_widget("Scale", orient="vertical"), scale) == (None, ("length", "px"))
    assert sizing.size_axes(_widget("Progressbar", orient="vertical"), bar)[1] == ("length", "px")
    plugin = replace(REGISTRY.require("Frame"), name="tb:Meter")
    assert sizing.size_axes(_widget("tb:Meter"), plugin) == (None, None)
    assert sizing.size_axes(_widget("Frame"), None) == (None, None)


# ---------------------------------------------------------------- hidden axes (2.4-2.5)
@pytest.mark.parametrize("sticky", ["", "n", "e", "w", "ew", "ns", "nsew", "new", "sw"])
def test_grid_sticky_on_both_sides_turns_the_axis_into_a_span(sticky: str) -> None:
    _stack, n = _form()
    text = REGISTRY.require("Text")
    node = Widget(class_name="Text", id="t")
    node.placement = GridCell(row=9, column=0, sticky=sticky)
    n["w"].insert_child(len(n["w"].children), node)  # type: ignore[attr-defined]
    (h, h_why), (v, _v_why) = sizing.sized_axes(node, text)
    assert (h is None) == ("e" in sticky and "w" in sticky)
    assert (v is None) == ("n" in sticky and "s" in sticky)
    assert ("Sticky" in h_why) == (h is None)
    kinds = sizing.handle_kinds(node, text)
    assert len(kinds) == 8  # a grid child always keeps its span handles
    assert (kinds["e"] == "span") == (h is None) and (kinds["s"] == "span") == (v is None)


@pytest.mark.parametrize("fill", ["none", "x", "y", "both"])
def test_pack_fill_hides_the_size_handle_of_its_axis(fill: str) -> None:
    _stack, n = _form()
    node = n["g2"]
    assert isinstance(node, Widget)
    node.placement = PackPlacement(fill=fill)  # type: ignore[arg-type]
    (h, why), _v = sizing.sized_axes(node, _spec(node))
    hidden = fill in ("x", "both")
    assert (h is None) == hidden and ("Fill" in why) == hidden
    assert sizing.handle_kinds(node, _spec(node)) == ({} if hidden else {"e": "size", "w": "size"})


def test_handles_per_node() -> None:
    _stack, n = _form()
    kinds = sizing.handle_kinds(n["b"], _spec(n["b"]))
    assert {e for e, k in kinds.items() if k == "size"} == {"e", "w"}  # D1: filled left/right
    assert {e for e, k in kinds.items() if k == "span"} == {"n", "s", "nw", "ne", "sw", "se"}
    assert set(sizing.handle_kinds(n["f"], _spec(n["f"])).values()) == {"size"}  # empty Frame
    full = sizing.handle_kinds(n["g"], _spec(n["g"]))  # a Frame with children: spans only (D2)
    assert set(full.values()) == {"span"}
    assert "frame with contents" in sizing.hover_text(n["g"], _spec(n["g"]), "e", "span")
    assert sizing.handle_kinds(n["g1"], _spec(n["g1"])) == {}  # Checkbutton in pack
    assert sizing.handle_kinds(n["n0"], _spec(n["n0"])) == {}  # page child (D6)
    assert sizing.handle_kinds(n["s"], _spec(n["s"]))["s"] == "size"  # vertical Scale
    assert "Hold Ctrl" in sizing.hover_text(n["b"], _spec(n["b"]), "e", "size")
    assert sizing.hover_text(n["b"], _spec(n["b"]), "n", "span").startswith("Drag to change the c")
    assert sizing.hover_text(n["g2"], _spec(n["g2"]), "w", "size") == "Drag to change the width."


# ---------------------------------------------------------------- commands (2.7, 3)
def test_a_drag_is_one_resize_step_and_a_no_change_records_nothing() -> None:
    stack, n = _form()
    built = sizing.size_command(n["b"], [("width", 14)])
    assert isinstance(built, Macro) and stack.execute(built).accepted
    assert n["b"].props["width"].value == "14"  # type: ignore[attr-defined]
    assert stack.undo_text == "Resize"
    assert sizing.size_command(n["b"], [("width", 14)]) is None
    assert sizing.size_command(n["w"], [("width", 14)]) is None
    stack.undo()
    assert "width" not in n["b"].props  # type: ignore[attr-defined]


def test_a_guard_rejection_changes_nothing() -> None:
    stack, n = _form()
    built = sizing.size_command(n["b"], [("width", 20_000)])  # past the registry maximum
    assert built is not None
    assert not stack.execute(built).accepted and "width" not in n["b"].props  # type: ignore[attr-defined]


def test_reset_removes_the_axis_property() -> None:
    stack, n = _form()
    built = sizing.reset_size_command(n["g2"], _spec(n["g2"]), "e")
    assert isinstance(built, Macro) and isinstance(built.commands[0], RemoveProp)
    assert stack.execute(built).accepted and stack.undo_text == "Reset width"
    assert sizing.reset_size_command(n["g2"], _spec(n["g2"]), "e") is None
    assert sizing.reset_size_command(n["w"], None, "e") is None


@given(st.integers(-100, 60_000), st.integers(0, 2_000), st.booleans())
@example(extent=1, natural=0, fine=False)  # snapped to 0: the next step (4), not 1
@example(extent=10, natural=9, fine=False)  # snapped to 8: below the contents
@example(extent=60_000, natural=0, fine=False)
def test_window_value_clears_below_the_contents_and_clamps(
    extent: int, natural: int, fine: bool
) -> None:
    value = sizing.window_value(extent, natural, fine=fine)
    if extent <= natural:
        assert value is None
    else:
        assert value is not None and natural < value <= sizing.MAX_SIZE
        assert fine or value % sizing.PIXEL_SNAP == 0
        assert abs(value - extent) <= sizing.PIXEL_SNAP or value == sizing.MAX_SIZE


def test_window_size_command_writes_only_the_changed_fields() -> None:
    stack, n = _form()
    window = n["w"]
    built = sizing.window_size_command(window, {"min_width": 200, "min_height": 300})
    assert isinstance(built, Macro) and len(built.commands) == 1
    assert stack.execute(built).accepted and stack.undo_text == "Resize window"
    assert (window.min_width, window.min_height) == (200, 300)  # type: ignore[attr-defined]
    cleared = sizing.window_size_command(window, {"min_width": None})
    assert cleared is not None and stack.execute(cleared).accepted
    assert window.min_width is None  # type: ignore[attr-defined]
    assert sizing.window_size_command(window, {"min_width": None}) is None
    assert sizing.window_size_command(n["b"], {"min_width": 1}) is None


def test_status_texts() -> None:
    assert sizing.release_text("b", [("chars", 14), None]) == (
        "Release to set the width of 'b' to 14 characters."
    )
    assert sizing.release_text("t", [("chars", 1), ("lines", 3)]) == (
        "Release to set the size of 't' to 1 character × 3 lines."  # noqa: RUF001
    )
    assert sizing.release_text("b", [None, None]) == "'b' keeps its natural size."
    assert sizing.unit_text(2, "rows") == "2 rows" and sizing.unit_text(1, "px") == "1 pixel"
    assert "minimum width was cleared" in sizing.window_release_text("w", (None, 9), (True, False))
    assert "minimum size was cleared" in sizing.window_release_text("w", (None, None), (True, True))
    assert sizing.window_release_text("w", (480, 320), (True, True)) == (
        "Release to set the minimum size of 'w' to 480 × 320 px."  # noqa: RUF001
    )


# ---------------------------------------------------------------- key steps (spec 4)
def test_step_commands() -> None:
    _stack, n = _form()
    measured = Measured((70, 30), (7.0, 15.0), natural=(150, 100))
    step = sizing.step_command(n["b"], _spec(n["b"]), 0, 1, measured)
    assert isinstance(step, SetProp) and step.prop.value == "11"  # 70 px / 7 = 10 (estimate)
    assert (
        sizing.step_command(n["b"], _spec(n["b"]), 1, 1, measured)
        == "'b' has no height that can be changed."
    )
    narrow = sizing.step_command(
        _widget("Button", width="1"), REGISTRY.require("Button"), 0, -1, measured
    )
    assert narrow == "'x' cannot be narrower."
    assert "Fill" in str(sizing.step_command(n["g0"], _spec(n["g0"]), 0, 1, measured))
    frame = sizing.step_command(n["f"], _spec(n["f"]), 1, 1, Measured((120, 64)))
    assert isinstance(frame, SetProp) and frame.prop.value == "68"  # 4 px per pixel step
    grow = sizing.step_command(n["w"], None, 0, 1, measured)
    assert isinstance(grow, SetField) and grow.value == 208  # from the set 200
    shrink = sizing.step_command(n["w"], None, 0, -10, measured)  # 120 <= natural 150: cleared
    assert isinstance(shrink, SetField) and shrink.value is None
    assert sizing.step_command(n["w"], None, 1, -1, measured) == "'w' cannot be shorter."
    tall = sizing.step_command(n["w"], None, 1, 1, Measured((300, 200), natural=(100, 100)))
    assert isinstance(tall, SetField) and tall.value == 208  # from the shown 200 px


def _session() -> tuple[DesignerSession, EditActions, dict[str, object], list[str]]:
    session = DesignerSession(REGISTRY)
    session.open_result(read_ui_string(FORM), name="form.ui")
    messages: list[str] = []
    measured = Measured((70, 30), (7.0, 15.0), natural=(150, 100))
    edit = EditActions(session, lambda *_a: None, messages.append, measure=lambda _n: measured)
    assert session.document is not None
    nodes: dict[str, object] = {getattr(n, "id", ""): n for n in session.document.walk()}
    return session, edit, nodes, messages


def test_three_key_steps_merge_into_one_undo_step_until_the_selection_changes() -> None:
    session, edit, n, _messages = _session()
    stack = session.stack
    assert stack is not None
    session.select(n["b"], origin="canvas")
    for _ in range(3):
        edit.size_step(0, 1)
    assert n["b"].props["width"].value == "13" and stack.index == 1  # type: ignore[attr-defined]
    session.select(n["f"], origin="canvas")
    session.select(n["b"], origin="canvas")
    edit.size_step(0, 1)
    assert stack.index == 2  # a new selection: a new undo step
    stack.undo()
    stack.undo()
    assert "width" not in n["b"].props  # type: ignore[attr-defined]


def test_window_key_steps_merge_per_field() -> None:
    session, edit, n, messages = _session()
    stack, window = session.stack, n["w"]
    assert stack is not None and isinstance(window, Window)
    session.select(window, origin="canvas")
    edit.size_step(0, 1)
    edit.size_step(0, 1)
    edit.size_step(1, 1)  # another field: its own undo step (SetField merges per field)
    assert (window.min_width, window.min_height, stack.index) == (216, 108, 2)
    session.select(n["g1"], origin="canvas")
    edit.size_step(0, 1)
    assert messages[-1] == "'g1' has no width that can be changed." and stack.index == 2


def test_component_windows_label_their_minimum_as_a_preview() -> None:
    stack, n = _form()

    def labels(node: object) -> dict[str, str]:
        rows = field_rows([node], REGISTRY, stack.document)
        return {f.key: f.label for f in rows}

    assert labels(n["c"])["field:min_width"] == "Preview width"  # D4
    assert labels(n["w"])["field:min_height"] == "Minimum height"
