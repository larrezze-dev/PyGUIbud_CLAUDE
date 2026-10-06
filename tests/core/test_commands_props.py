"""Property tests of the command stack: random edit sequences are exactly undoable (spec §10)."""

from __future__ import annotations

from typing import Literal

from hypothesis import HealthCheck, event, given, settings
from hypothesis import strategies as st

from pyguibud.core import (
    CommandStack,
    Document,
    Event,
    GridCell,
    Include,
    PackPlacement,
    PagePlacement,
    Prop,
    Variable,
    Widget,
    Window,
    default_registry,
    dump_ui,
    read_ui,
    read_ui_string,
)
from pyguibud.core.commands import (
    DEFAULT_LAYOUT,
    Command,
    InsertNode,
    Macro,
    MoveNode,
    RemoveNode,
    RemoveProp,
    RemoveVariable,
    SetEvents,
    SetField,
    SetProp,
    SetVariable,
    reparent,
)
from tests.core.test_commands import parents_ok
from tests.core.xml_helpers import HELLO, structure

SMALL = """<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <variables><var id="flag" type="bool"/></variables>
  <window id="main"><layout type="pack"/>
    <widget class="Frame" id="frm_a"><pack/><layout type="grid"/>
      <widget class="Checkbutton" id="chk_a" bind="flag"><cell row="0" column="0"/></widget>
    </widget>
    <widget class="Label" id="lbl_a"><pack fill="x"/></widget>
  </window>
</pyguibud-ui>"""

IDS = ["lbl_a", "btn_greet", "class", "_x", "main", "w1", "w2", "frm_a", ""]
NAMES = ["text", "width", "state"]
VALUES = ["a", "b", "-5", "maybe", "3", "normal"]
CLASSES = ["Label", "Frame", "Button", "Notebook", "Entry"]


def _nodes(document: Document) -> tuple[list[object], list[object]]:
    """Return (containers, children) of the live tree, iteratively."""
    containers: list[object] = [document]
    children: list[object] = []
    todo: list[object] = [document]
    while todo:
        node = todo.pop()
        for child in getattr(node, "children", ()):
            children.append(child)
            if isinstance(child, (Window, Widget)):
                containers.append(child)
            todo.append(child)
    return containers, children


some_placement = st.one_of(
    st.builds(GridCell, row=st.integers(0, 3), column=st.integers(0, 2)),
    st.builds(PackPlacement),
    st.builds(PagePlacement),
)
placements = st.none() | some_placement


def _command(data: st.DataObject, stack: CommandStack, owner_hint: list[object]) -> Command:
    document = stack.document
    containers, children = _nodes(document)
    widgets = [c for c in children if isinstance(c, Widget)]
    kind = data.draw(
        st.sampled_from(
            ["prop", "prop", "prop", "prop", "remove_prop", "field", "insert", "remove", "move",
             "reparent", "events", "variable", "remove_variable", "macro"]
        )
    )  # fmt: skip
    if (kind in ("prop", "remove_prop", "field", "events") and not widgets) or not children:
        kind = "insert"
    if kind == "prop":
        # Bias towards the same owner and name, so that merges actually happen.
        if owner_hint and owner_hint[0] in widgets and data.draw(st.integers(0, 3)) > 0:
            owner, name = owner_hint
        else:
            owner = data.draw(st.sampled_from(widgets))
            name = data.draw(st.sampled_from(NAMES))
            owner_hint[:] = [owner, name]
        return SetProp(owner, Prop(name=str(name), value=data.draw(st.sampled_from(VALUES))))
    if kind == "remove_prop":
        return RemoveProp(data.draw(st.sampled_from(widgets)), data.draw(st.sampled_from(NAMES)))
    if kind == "field":
        target = data.draw(st.sampled_from(widgets))
        if data.draw(st.booleans()):
            return SetField(target, "id", data.draw(st.sampled_from(IDS)))
        return SetField(target, "placement", data.draw(placements))
    if kind == "events":
        handler = data.draw(st.sampled_from(["on_x", "1abc", "class"]))
        name = data.draw(st.sampled_from(["command", "key:", "focus_in"]))
        return SetEvents(data.draw(st.sampled_from(widgets)), [Event(name=name, handler=handler)])
    if kind == "insert":
        parent = data.draw(st.sampled_from(containers))
        if isinstance(parent, Document):
            return InsertNode(parent, Window(id=data.draw(st.sampled_from(IDS)), kind="dialog",
                                             layout=DEFAULT_LAYOUT))  # fmt: skip
        if data.draw(st.integers(0, 5)) == 0:
            node: object = Include(id=data.draw(st.sampled_from(IDS)), src="x.ui",
                                   component="cmp", placement=data.draw(placements))  # fmt: skip
        else:
            node = Widget(
                class_name=data.draw(st.sampled_from(CLASSES)),
                id=data.draw(st.sampled_from(IDS)),
                placement=data.draw(placements),
                layout=DEFAULT_LAYOUT if data.draw(st.booleans()) else None,
            )
        index = data.draw(st.none() | st.integers(-3, 5))
        return InsertNode(parent, node, index)
    if kind == "remove":
        return RemoveNode(data.draw(st.sampled_from(children)))
    if kind in ("move", "reparent"):
        node = data.draw(st.sampled_from(children))
        parent = data.draw(st.sampled_from(containers))
        index = data.draw(st.integers(-3, 5))
        if kind == "reparent" and isinstance(node, Widget):
            return reparent(node, parent, index, data.draw(some_placement))
        return MoveNode(node, parent, index)
    if kind == "variable":
        var_type: Literal["string", "int", "bool"] = data.draw(
            st.sampled_from(["string", "int", "bool"])
        )
        name = data.draw(st.sampled_from(["user_name", "flag", "v1"]))
        return SetVariable(document, Variable(id=name, type=var_type))
    if kind == "remove_variable":
        return RemoveVariable(document, data.draw(st.sampled_from(["user_name", "flag", "nope"])))
    first = _command(data, stack, owner_hint)
    second = _command(data, stack, owner_hint)
    return Macro("Pair", [first, second])


@settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(data=st.data(), small=st.booleans(), steps=st.integers(1, 40))
def test_random_sequences_are_exactly_undoable(
    data: st.DataObject, small: bool, steps: int
) -> None:
    document = read_ui_string(SMALL).document if small else read_ui(HELLO).document
    stack = CommandStack(document, default_registry())
    original = dump_ui(document)
    original_structure = structure(document)
    saved = original
    assert stack.report().ok
    hint: list[object] = []
    for _step in range(steps):
        action = data.draw(st.sampled_from(["cmd"] * 6 + ["undo", "redo", "save", "break"]))
        if action == "undo":
            stack.undo()
        elif action == "redo":
            stack.redo()
        elif action == "save":
            stack.mark_saved()
            saved = dump_ui(document)
        elif action == "break":
            stack.break_merge()
        else:
            command = _command(data, stack, hint)
            before = (dump_ui(document), structure(document), stack.index, stack.is_dirty)
            outcome = stack.execute(command)
            event("merged" if outcome.merged else "accepted" if outcome else "rejected")
            if not outcome.accepted:
                after = (dump_ui(document), structure(document), stack.index, stack.is_dirty)
                assert after == before, outcome.findings
        assert parents_ok(document)
        assert stack.report().ok, stack.report().errors
        if not stack.is_dirty:
            assert dump_ui(document) == saved
    final = dump_ui(document)
    final_structure = structure(document)
    final_index = stack.index
    while stack.undo():
        pass
    assert dump_ui(document) == original
    assert structure(document) == original_structure
    assert parents_ok(document)
    while stack.index < final_index:
        assert stack.redo()
    assert dump_ui(document) == final
    assert structure(document) == final_structure
    while stack.redo():
        pass
    assert parents_ok(document)
    assert stack.report().ok
