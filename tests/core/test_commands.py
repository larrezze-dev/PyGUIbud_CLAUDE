"""Tests for the command stack and its guards (spec ``docs/specs/validate-commands.md`` §6)."""

# The tests re-read state that mypy narrowed before a mutating call.
# mypy: disable-error-code="unreachable"

from __future__ import annotations

import importlib.util
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

from pyguibud.core import (
    Action,
    CommandStack,
    Document,
    Event,
    GridCell,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    Outcome,
    PackPlacement,
    PagePlacement,
    Placement,
    Prop,
    StackEvent,
    Statusbar,
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
    RemoveResource,
    RemoveVariable,
    SetEvents,
    SetField,
    SetProp,
    SetResource,
    SetVariable,
    change_layout,
    reparent,
)
from pyguibud.i18n import set_language
from tests.core.xml_helpers import HELLO, structure

DEMO = Path(__file__).parents[2] / "examples" / "validator_demo.py"


# ---------------------------------------------------------------- helpers
@pytest.fixture
def doc() -> Document:
    return read_ui(HELLO).document


@pytest.fixture
def stack(doc: Document) -> CommandStack:
    return CommandStack(doc, default_registry(), source="hello.ui")


def w(document: Document, node_id: str) -> Widget:
    node = document.find(node_id)
    assert isinstance(node, Widget)
    return node


def text(value: str) -> Prop:
    return Prop(name="text", value=value, translatable=True)


class Snapshot:
    """Everything a rejected command must leave untouched."""

    def __init__(self, stack: CommandStack) -> None:
        self.stack = stack
        self.data = self._take()

    def _take(self) -> tuple[object, ...]:
        s = self.stack
        return (
            dump_ui(s.document),
            structure(s.document),
            s.index,
            s.is_dirty,
            s.can_redo,
            s._saved_index,
            s._merge_open,
            s.report(),  # never cached (QA Step 09): equal findings, not the same object
            len(s._history),
        )

    def unchanged(self) -> bool:
        return self._take() == self.data


def roundtrip(stack: CommandStack, command: Command) -> None:
    """Execute, undo and redo ``command`` checking the document at every stage."""
    original = dump_ui(stack.document)
    original_structure = structure(stack.document)
    outcome = stack.execute(command)
    assert outcome.accepted and outcome.changed, outcome.message
    changed = dump_ui(stack.document)
    assert changed != original or structure(stack.document) != original_structure
    assert stack.undo()
    assert dump_ui(stack.document) == original
    assert structure(stack.document) == original_structure
    assert stack.redo()
    assert dump_ui(stack.document) == changed


def parents_ok(document: Document) -> bool:
    todo: list[object] = [document]
    while todo:
        node = todo.pop()
        children = getattr(node, "children", ())
        for child in children:
            if child.parent is not node:
                return False
            todo.append(child)
        if isinstance(node, Window) and node.menubar is not None:
            todo.append(node.menubar)
    return True


# ---------------------------------------------------------------- each command
def test_insert_node_append_and_index(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    roundtrip(stack, InsertNode(greeting, Widget(class_name="Label", id="lbl_new",
                                                 placement=GridCell(row=2, column=0))))  # fmt: skip
    assert greeting.children[-1].id == "lbl_new"
    first = Widget(class_name="Label", id="lbl_first", placement=GridCell(row=3, column=0))
    roundtrip(stack, InsertNode(greeting, first, 0))
    assert greeting.children[0].id == "lbl_first"


def test_insert_window_and_menu_items(stack: CommandStack, doc: Document) -> None:
    roundtrip(stack, InsertNode(doc, Window(id="dlg", kind="dialog", layout=DEFAULT_LAYOUT)))
    menu = doc.find("mnu_file")
    assert isinstance(menu, Menu)
    roundtrip(stack, InsertNode(menu, MenuSeparator()))
    roundtrip(stack, InsertNode(menu, Action(id="act_open", handler="on_open"), 0))
    window = doc.children[0]
    assert window.menubar is not None
    roundtrip(stack, InsertNode(window.menubar, Menu(id="mnu_help")))


def test_insert_never_noop_and_rejects_bad_types(doc: Document) -> None:
    assert not InsertNode(doc, Window(id="x", layout=DEFAULT_LAYOUT)).is_noop()
    with pytest.raises(TypeError):
        InsertNode(Prop(name="x"), Window(id="x"))
    with pytest.raises(TypeError):
        InsertNode(doc, Prop(name="x"))


def test_remove_node_keeps_index(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    entry = w(doc, "ent_name")
    roundtrip(stack, RemoveNode(w(doc, "btn_greet")))
    stack.undo()
    roundtrip(stack, RemoveNode(entry))
    stack.undo()
    assert greeting.children[1] is entry and entry.parent is greeting
    with pytest.raises(TypeError):
        RemoveNode(Menubar())


def test_remove_window_and_menu(stack: CommandStack, doc: Document) -> None:
    stack.execute(InsertNode(doc, Window(id="dlg", kind="dialog", layout=DEFAULT_LAYOUT)))
    roundtrip(stack, RemoveNode(doc.children[1]))
    action = doc.find("act_quit")
    roundtrip(stack, RemoveNode(action))


def test_move_node_same_parent(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    label = w(doc, "lbl_name")
    roundtrip(stack, MoveNode(label, greeting, 2))
    assert greeting.children[2] is label
    stack.undo()
    assert greeting.children[0] is label


@pytest.mark.parametrize(("index", "noop"), [(0, True), (-3, True), (-99, True), (1, False),
                                             (2, False), (99, False), (-1, False)])  # fmt: skip
def test_move_node_noop(doc: Document, index: int, noop: bool) -> None:
    greeting = w(doc, "frm_greeting")
    assert MoveNode(w(doc, "lbl_name"), greeting, index).is_noop() is noop


def test_move_node_noop_last(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    command = MoveNode(w(doc, "btn_greet"), greeting, 99)
    assert command.is_noop()
    outcome = stack.execute(command)
    assert outcome.accepted and not outcome.changed and stack.index == 0


def test_move_node_across_parents_needs_reparent(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    about = w(doc, "frm_about")
    snap = Snapshot(stack)
    outcome = stack.execute(MoveNode(label, about, 0))
    assert not outcome.accepted
    assert outcome.findings[0].code == "validate.placement_mismatch"
    assert snap.unchanged()
    roundtrip(stack, reparent(label, about, 0, PackPlacement(fill="x")))
    assert label.parent is about and isinstance(label.placement, PackPlacement)
    stack.undo()
    assert label.parent is w(doc, "frm_greeting") and isinstance(label.placement, GridCell)


def test_move_into_own_descendant_is_a_cycle(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    snap = Snapshot(stack)
    outcome = stack.execute(MoveNode(w(doc, "nbk_main"), greeting, 0))
    assert not outcome.accepted and outcome.findings[0].code == "model.cycle"
    assert outcome.findings[0].is_error and outcome.message
    assert snap.unchanged() and parents_ok(doc)


def test_model_errors_become_rejections(stack: CommandStack, doc: Document) -> None:
    window = doc.children[0]
    snap = Snapshot(stack)
    bad_child = stack.execute(InsertNode(window, Menu(id="mnu_x")))
    assert bad_child.findings[0].code == "model.bad_child"
    parented = stack.execute(InsertNode(window, w(doc, "lbl_name")))
    assert parented.findings[0].code == "model.already_parented"
    label = w(doc, "lbl_about")
    twice = stack.execute(Macro("x", [RemoveNode(label), RemoveNode(label)]))
    assert twice.findings[0].code == "model.not_a_child"
    assert snap.unchanged() and parents_ok(doc)


def test_set_prop_add_replace_noop(stack: CommandStack, doc: Document) -> None:
    button = w(doc, "btn_greet")
    roundtrip(stack, SetProp(button, text("Go")))
    roundtrip(stack, SetProp(button, Prop(name="width", value="10")))
    stack.undo()
    assert "width" not in button.props
    assert SetProp(button, text("Go")).is_noop()
    for owner in (doc.children[0], doc.find("mnu_file"), doc.find("act_quit"),
                  doc.children[0].statusbar):  # fmt: skip
        roundtrip(stack, SetProp(owner, text("T")))
    with pytest.raises(TypeError):
        SetProp(doc, text("x"))
    with pytest.raises(TypeError):
        SetProp(button, "text")  # type: ignore[arg-type]


def test_remove_prop_restores_order(stack: CommandStack, doc: Document) -> None:
    button = w(doc, "btn_greet")
    stack.execute(SetProp(button, Prop(name="width", value="10")))
    stack.execute(SetProp(button, Prop(name="state", value="normal")))
    order = list(button.props)
    roundtrip(stack, RemoveProp(button, "width"))
    stack.undo()
    assert list(button.props) == order
    roundtrip(stack, RemoveProp(button, "state"))
    stack.undo()
    assert list(button.props) == order
    assert RemoveProp(button, "nope").is_noop()
    with pytest.raises(TypeError):
        RemoveProp(doc, "x")


def test_set_field(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    roundtrip(stack, SetField(label, "id", "lbl_user"))
    roundtrip(stack, SetField(doc.meta, "theme", "darkly"))
    roundtrip(stack, SetField(doc.children[0], "min_width", 600))
    roundtrip(stack, SetField(doc.children[0], "statusbar", None))
    roundtrip(stack, SetField(doc.children[0], "statusbar", Statusbar(id="sts_new")))
    roundtrip(stack, SetField(doc.find("act_quit"), "handler", "on_exit"))
    assert SetField(label, "id", "lbl_user").is_noop()
    assert SetField(label, "placement", GridCell(row=0, column=0, sticky="w")).is_noop()


@pytest.mark.parametrize(
    ("target", "name", "value"),
    [
        ("widget", "parent", None),
        ("widget", "props", {}),
        ("widget", "events", []),
        ("widget", "id", 3),
        ("widget", "placement", "cell"),
        ("window", "min_width", True),
        ("window", "modal", 1),
        ("document", "schema_version", "1.0"),
        ("layout", "type", "grid"),
    ],
)
def test_set_field_whitelist(doc: Document, target: str, name: str, value: object) -> None:
    objects = {"widget": w(doc, "lbl_name"), "window": doc.children[0], "document": doc,
               "layout": DEFAULT_LAYOUT}  # fmt: skip
    with pytest.raises(TypeError):
        SetField(objects[target], name, value)


def test_set_events(stack: CommandStack, doc: Document) -> None:
    button = w(doc, "btn_greet")
    old = button.events
    roundtrip(stack, SetEvents(button, [Event(name="focus_in", handler="on_focus")]))
    stack.undo()
    assert button.events is old
    assert SetEvents(button, list(old)).is_noop()
    with pytest.raises(TypeError):
        SetEvents(doc, [])  # type: ignore[arg-type]


def test_variables_keep_order(stack: CommandStack, doc: Document) -> None:
    roundtrip(stack, SetVariable(doc, Variable(id="count", type="int")))
    order = list(doc.variables)
    roundtrip(stack, SetVariable(doc, Variable(id="user_name", type="string", default="Ann")))
    assert list(doc.variables) == order
    stack.undo()
    assert SetVariable(doc, Variable(id="count", type="int")).is_noop()
    roundtrip(stack, RemoveVariable(doc, "count"))
    stack.undo()
    assert list(doc.variables) == order
    assert RemoveVariable(doc, "nope").is_noop()
    with pytest.raises(TypeError):
        SetVariable(doc, ImageResource(id="x", src="x.png"))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        RemoveVariable(w(doc, "lbl_name"), "x")  # type: ignore[arg-type]


def test_resources(stack: CommandStack, doc: Document) -> None:
    roundtrip(stack, SetResource(doc, ImageResource(id="img_a", src="a.png")))
    roundtrip(stack, SetResource(doc, ImageResource(id="img_b", src="b.png")))
    assert SetResource(doc, ImageResource(id="img_b", src="b.png")).is_noop()
    roundtrip(stack, RemoveResource(doc, "img_a"))
    stack.undo()
    assert list(doc.resources) == ["img_a", "img_b"]
    assert RemoveResource(doc, "nope").is_noop()
    with pytest.raises(TypeError):
        SetResource(doc, Variable(id="x", type="int"))  # type: ignore[arg-type]


@pytest.mark.parametrize("src", ["//host/share/a.png", "\\\\host\\share\\a.png", "icons/con.png"])
def test_a_network_or_device_image_path_is_blocked(
    stack: CommandStack, doc: Document, src: str
) -> None:
    # QA-11-03 (R82): the designer's guard refuses it like --check, load_ui and codegen do.
    outcome = stack.execute(SetResource(doc, ImageResource(id="img_a", src=src)))
    assert not outcome and outcome.findings[0].code == "validate.network_path"
    assert "img_a" not in doc.resources


def test_referenced_resource_cannot_be_removed(stack: CommandStack, doc: Document) -> None:
    stack.execute(SetResource(doc, ImageResource(id="img_a", src="a.png")))
    stack.execute(SetProp(w(doc, "btn_greet"), Prop(name="image", ref="img_a")))
    outcome = stack.execute(RemoveResource(doc, "img_a"))
    assert not outcome and outcome.findings[0].code == "command.resource_in_use"
    assert (
        outcome.message
        == "The image resource 'img_a' is still used by 'btn_greet'; remove that use first."
    )
    assert outcome.findings[0].anchor is w(doc, "btn_greet")


def test_apply_twice_and_revert_unapplied_raise(doc: Document) -> None:
    command = SetField(w(doc, "lbl_name"), "id", "lbl_x")
    with pytest.raises(RuntimeError):
        command.revert()
    command.apply()
    with pytest.raises(RuntimeError):
        command.apply()
    command.revert()
    assert w(doc, "lbl_name").id == "lbl_name"


# ---------------------------------------------------------------- macros and helpers
def test_macro_noop_and_text(doc: Document) -> None:
    label = w(doc, "lbl_name")
    macro = Macro("Nothing", [SetField(label, "id", "lbl_name"), RemoveProp(label, "x")])
    assert macro.is_noop() and macro.text() == "Nothing"
    assert Macro("Empty", []).is_noop()
    with pytest.raises(TypeError):
        Macro("x", ["nope"])  # type: ignore[list-item]


def test_macro_atomic_on_model_error(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    snap = Snapshot(stack)
    macro = Macro("Three", [SetField(label, "id", "lbl_a"), SetProp(label, text("A")),
                            InsertNode(doc.children[0], Menu(id="mnu_bad"))])  # fmt: skip
    outcome = stack.execute(macro)
    assert outcome.findings[0].code == "model.bad_child"
    assert snap.unchanged()
    assert not macro.commands[0]._applied and not macro.commands[1]._applied


class _Boom(Command):
    def apply(self) -> None:
        raise ValueError("bug")

    def revert(self) -> None:  # pragma: no cover - never applied
        pass


class _BadRevert(SetField):
    def revert(self) -> None:
        raise KeyError("also broken")


def test_macro_bug_reverts_and_reraises(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    before = dump_ui(doc)
    with pytest.raises(ValueError, match="bug"):
        stack.execute(Macro("Bug", [SetField(label, "id", "lbl_a"), _Boom()]))
    assert dump_ui(doc) == before and stack.index == 0
    with pytest.raises(ValueError, match="bug"):
        stack.execute(Macro("Bug", [_BadRevert(label, "id", "lbl_b"), _Boom()]))


def test_macro_never_merges(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    stack.execute(Macro("A", [SetProp(label, text("1"))]))
    outcome = stack.execute(Macro("A", [SetProp(label, text("2"))]))
    assert not outcome.merged and stack.index == 2


def test_change_layout(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    placements: dict[Widget | Include, Placement] = {
        child: PackPlacement() for child in greeting.children
    }
    roundtrip(stack, change_layout(greeting, Layout(type="pack"), placements))
    window = doc.children[0]
    roundtrip(stack, change_layout(window, Layout(type="pack"),
                                   {w(doc, "nbk_main"): PackPlacement(fill="both")}))  # fmt: skip
    with pytest.raises(ValueError, match="no placement"):
        change_layout(greeting, Layout(type="pack"), {})
    with pytest.raises(ValueError, match="not a child"):
        change_layout(greeting, Layout(type="pack"),
                      {**placements, w(doc, "lbl_about"): PackPlacement()})  # fmt: skip
    with pytest.raises(TypeError):
        change_layout(greeting, None, placements)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        change_layout(doc, Layout(type="pack"), {})  # type: ignore[arg-type]


def test_d6_layout_rules(stack: CommandStack, doc: Document) -> None:
    greeting = w(doc, "frm_greeting")
    bare = Widget(class_name="Frame", id="frm_x", placement=GridCell(row=2, column=0))
    assert stack.execute(InsertNode(greeting, bare)).findings[0].code == "validate.layout_missing"
    framed = Widget(class_name="Frame", id="frm_x", placement=GridCell(row=2, column=0),
                    layout=DEFAULT_LAYOUT)  # fmt: skip
    assert stack.execute(InsertNode(greeting, framed)).accepted
    window = doc.children[0]
    outcome = stack.execute(SetField(window, "layout", None))
    assert outcome.findings[0].code == "validate.layout_missing"
    assert not stack.execute(InsertNode(doc, Window(id="w2", kind="dialog"))).accepted
    page = Widget(class_name="Frame", id="frm_page", layout=DEFAULT_LAYOUT,
                  placement=PagePlacement())  # fmt: skip
    notebook = w(doc, "nbk_main")
    assert stack.execute(InsertNode(notebook, page)).accepted  # a page that is a layout frame
    stack.undo()
    pages = Widget(class_name="Notebook", id="nbk_x", placement=GridCell(row=4, column=0),
                   layout=DEFAULT_LAYOUT)  # fmt: skip
    outcome = stack.execute(InsertNode(greeting, pages))
    assert outcome.findings[0].code == "validate.layout_on_pages"


# ---------------------------------------------------------------- guards
def _load_demo() -> ModuleType:
    spec = importlib.util.spec_from_file_location("validator_demo", DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["validator_demo"] = module
    spec.loader.exec_module(module)
    return module


DEMO_CODES = [
    "validate.keyword_id",
    "validate.duplicate_id",
    "validate.bad_id",
    "validate.not_a_container",
    "validate.placement_mismatch",
    "validate.grid_collision",
    "validate.out_of_range",
    "validate.bad_prop_value",
    "validate.bad_event",
    "validate.bad_handler",
    "validate.bind_type_mismatch",
    "validate.layout_on_pages",
    "validate.multiple_main",
    "validate.layout_missing",
    "command.variable_in_use",
]


def test_demo_scenarios_are_rejected_without_trace(stack: CommandStack, doc: Document) -> None:
    demo = _load_demo()
    stack.execute(SetField(w(doc, "lbl_name"), "id", "lbl_user"))
    events: list[StackEvent] = []
    stack.subscribe(events.append)
    scenarios = demo.blocked_scenarios(doc)
    assert len(scenarios) == len(DEMO_CODES)
    for (description, command), code in zip(scenarios, DEMO_CODES, strict=True):
        snap = Snapshot(stack)
        checked = stack.check(command)
        outcome = stack.execute(command)
        assert not checked and not outcome, description
        assert checked.findings == outcome.findings
        assert outcome.findings[0].code == code, description
        assert snap.unchanged(), description
        assert parents_ok(doc)
    assert events == []


def test_second_main_window_has_only_r05(stack: CommandStack, doc: Document) -> None:
    outcome = stack.execute(InsertNode(doc, Window(id="w2", kind="main", layout=DEFAULT_LAYOUT)))
    assert [f.code for f in outcome.findings] == ["validate.multiple_main"]


def test_check_never_changes_anything(stack: CommandStack, doc: Document) -> None:
    stack.execute(SetProp(w(doc, "lbl_name"), text("a")))
    snap = Snapshot(stack)
    outcome = stack.check(SetProp(w(doc, "lbl_name"), text("b")))
    assert outcome.accepted and outcome.changed
    assert snap.unchanged()
    assert stack.check(SetProp(w(doc, "lbl_name"), text("b"))).accepted
    noop = stack.check(SetProp(w(doc, "lbl_name"), text("a")))
    assert noop.accepted and not noop.changed


def test_accepted_command_returns_new_warnings(stack: CommandStack, doc: Document) -> None:
    outcome = stack.execute(SetProp(w(doc, "lbl_name"), Prop(name="colour", value="red")))
    assert outcome and [f.code for f in outcome.findings] == ["validate.unknown_prop"]
    assert outcome.message
    again = stack.execute(SetProp(w(doc, "lbl_name"), Prop(name="colour", value="blue")))
    assert again.findings == ()


BROKEN = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Label" id="dup"><cell row="0" column="0"/></widget>
    <widget class="Label" id="dup"><cell row="1" column="0"/></widget>
    <widget class="Label" id="lbl_c"><cell row="2" column="0"/></widget>
    <widget class="Label" id="lbl_d"><cell row="2" column="0"/></widget>
  </window>
</pyguibud-ui>
"""


def test_preexisting_errors_stay_editable(doc: Document) -> None:
    document = read_ui_string(BROKEN).document
    stack = CommandStack(document, default_registry())
    assert not stack.report().ok
    window = document.children[0]
    first, second, third, fourth = window.children
    assert stack.execute(MoveNode(second, window, 0)).accepted  # duplicate pair reordered
    assert stack.execute(MoveNode(fourth, window, 2)).accepted  # collision pair reordered
    assert stack.execute(SetField(third, "id", "lbl_e")).accepted
    assert stack.execute(SetField(first, "id", "lbl_a")).accepted  # fixes the duplicate
    assert not stack.execute(SetField(first, "id", "lbl_e")).accepted


def test_capped_report_still_guards() -> None:
    body = "".join(
        f'<widget class="Label" id="class"><cell row="{i}" column="0"/></widget>'
        for i in range(600)
    )
    document = read_ui_string(
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        f'<window id="main"><layout type="grid"/>{body}</window></pyguibud-ui>'
    ).document
    stack = CommandStack(document, default_registry())
    report = stack.report()
    assert report.truncated and len(report.findings) == 1000 and not report.ok
    assert stack.report() == report  # recomputed on every call, never stale
    label = document.children[0].children[0]
    outcome = stack.execute(SetProp(label, Prop(name="width", value="-1")))
    assert not outcome and outcome.findings[0].code == "validate.out_of_range"


def test_foreign_nodes(stack: CommandStack, doc: Document) -> None:
    other = read_ui(HELLO).document
    snap = Snapshot(stack)
    for command in (
        SetField(w(other, "lbl_name"), "id", "x"),
        SetField(other.meta, "theme", "x"),
        SetProp(other.children[0].statusbar, text("x")),
        InsertNode(other.find("mnu_file"), MenuSeparator()),
        RemoveVariable(other, "user_name"),
        SetProp(Widget(class_name="Label", id="detached"), text("x")),
        InsertNode(Menubar(), Menu(id="m")),
    ):
        outcome = stack.execute(command)
        assert outcome.findings[0].code == "command.foreign_node"
        assert outcome.message == "This element does not belong to the open document."
    assert snap.unchanged()
    with pytest.raises(TypeError):
        stack.execute("nope")  # type: ignore[arg-type]


def test_include_fields(stack: CommandStack, doc: Document) -> None:
    include = Include(id="inc_a", src="part.ui", component="cmp_a",
                      placement=GridCell(row=5, column=0))  # fmt: skip
    roundtrip(stack, InsertNode(w(doc, "frm_greeting"), include))
    roundtrip(stack, SetField(include, "src", "other.ui"))


# ---------------------------------------------------------------- merge
def test_merge_consecutive_set_prop(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    original = dump_ui(doc)
    outcomes = [stack.execute(SetProp(label, text(t))) for t in ("a", "ab", "abc")]
    assert [o.merged for o in outcomes] == [False, True, True]
    assert stack.index == 1 and label.props["text"].value == "abc"
    stack.undo()
    assert dump_ui(doc) == original
    stack.redo()
    assert label.props["text"].value == "abc"


def test_merge_set_field_and_back_to_original(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    stack.execute(SetField(label, "id", "lbl_a"))
    assert stack.execute(SetField(label, "id", "lbl_name")).merged
    assert stack.index == 1 and stack.is_dirty  # documented: a no-op step stays
    stack.undo()
    assert label.id == "lbl_name" and not stack.is_dirty


def test_no_merge_across_owners_names_or_types(stack: CommandStack, doc: Document) -> None:
    label, button = w(doc, "lbl_name"), w(doc, "btn_greet")
    stack.execute(SetProp(label, text("a")))
    assert not stack.execute(SetProp(button, text("a"))).merged
    assert not stack.execute(SetProp(button, Prop(name="width", value="3"))).merged
    assert not stack.execute(SetField(button, "id", "btn_b")).merged
    assert not stack.execute(SetField(label, "id", "lbl_b")).merged
    assert stack.execute(SetField(label, "id", "lbl_c")).merged
    assert stack.index == 5


@pytest.mark.parametrize("breaker", ["other", "undo_redo", "mark_saved", "clear", "break_merge"])
def test_merge_breakers(stack: CommandStack, doc: Document, breaker: str) -> None:
    label = w(doc, "lbl_name")
    stack.execute(SetProp(label, text("a")))
    if breaker == "other":
        stack.execute(SetField(w(doc, "btn_greet"), "id", "btn_b"))
    elif breaker == "undo_redo":
        stack.undo()
        stack.redo()
    elif breaker == "mark_saved":
        stack.mark_saved()
    elif breaker == "clear":
        stack.clear()
    else:
        stack.break_merge()
    before = stack.index
    outcome = stack.execute(SetProp(label, text("b")))
    assert not outcome.merged and stack.index == before + 1


def test_redo_tail_blocks_merge(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    stack.execute(SetProp(label, text("a")))
    stack.break_merge()
    stack.execute(SetProp(label, text("b")))
    stack.undo()
    stack._merge_open = True  # force the flag: the redo tail alone must prevent the merge
    assert not stack.execute(SetProp(label, text("c"))).merged
    stack._merge_open = True
    stack.mark_saved()
    stack._merge_open = True  # the saved mark at the top alone must prevent the merge
    assert not stack.execute(SetProp(label, text("d"))).merged


def test_merge_non_breakers(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    stack.execute(SetProp(label, text("a")))
    assert not stack.execute(SetProp(label, Prop(name="width", value="-1"))).accepted
    assert not stack.execute(SetProp(label, text("a"))).changed  # no-op
    assert stack.check(SetField(label, "id", "lbl_b")).accepted
    assert stack.execute(SetProp(label, text("b"))).merged
    assert stack.index == 1


# ---------------------------------------------------------------- dirty and limit
def test_dirty_transitions(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    assert not stack.is_dirty and not stack.can_undo and not stack.can_redo
    assert not stack.undo() and not stack.redo()
    stack.execute(SetProp(label, text("a")))
    assert stack.is_dirty
    stack.undo()
    assert not stack.is_dirty
    stack.redo()
    stack.mark_saved()
    assert not stack.is_dirty
    stack.execute(SetField(label, "id", "lbl_b"))
    assert stack.is_dirty
    stack.undo()
    assert not stack.is_dirty
    stack.undo()  # past the save point
    assert stack.is_dirty
    stack.execute(SetField(label, "id", "lbl_c"))  # truncates the tail with the save point
    assert stack._saved_index is None and stack.is_dirty
    stack.undo()
    assert stack.is_dirty
    stack.redo()
    stack.mark_saved()
    assert not stack.is_dirty


def test_clear(stack: CommandStack, doc: Document) -> None:
    label = w(doc, "lbl_name")
    stack.execute(SetProp(label, text("a")))
    stack.mark_saved()
    stack.clear()
    assert not stack.is_dirty and stack.index == 0 and not stack.can_undo
    stack.execute(SetProp(label, text("b")))
    stack.clear()
    assert stack.is_dirty and stack._saved_index is None
    assert label.props["text"].value == "b"


def test_limit(doc: Document) -> None:
    with pytest.raises(ValueError):
        CommandStack(doc, default_registry(), limit=0)
    stack = CommandStack(doc, default_registry(), limit=2)
    assert stack.limit == 2 and stack.document is doc
    label = w(doc, "lbl_name")
    for value in ("lbl_a", "lbl_b", "lbl_c"):
        stack.break_merge()
        stack.execute(SetField(label, "id", value))
    assert stack.index == 2
    stack.undo()
    stack.undo()
    assert not stack.undo() and label.id == "lbl_a"
    stack.redo()
    stack.mark_saved()  # saved at index 1
    stack.break_merge()
    stack.execute(SetField(label, "id", "lbl_d"))
    assert stack._saved_index == 1
    stack.break_merge()
    stack.execute(SetField(label, "id", "lbl_e"))  # trims one: saved 1 -> 0
    assert stack._saved_index == 0
    stack.break_merge()
    stack.execute(SetField(label, "id", "lbl_f"))  # saved falls below 0 -> None
    assert stack._saved_index is None and stack.is_dirty
    while stack.undo():
        pass
    assert stack.is_dirty


# ---------------------------------------------------------------- read-only
def test_read_only_blocks_every_edit() -> None:
    text_ui = HELLO.read_text(encoding="utf-8").replace('schema_version="1.0"',
                                                       'schema_version="1.1"')  # fmt: skip
    document = read_ui_string(text_ui).document
    stack = CommandStack(document, default_registry())
    assert stack.read_only
    label = w(document, "lbl_name")
    before = structure(document)
    for command in (SetField(label, "id", "lbl_x"), SetProp(label, text("x")),
                    RemoveNode(label), SetField(label, "id", "lbl_name")):  # fmt: skip
        for outcome in (stack.check(command), stack.execute(command)):
            assert not outcome and outcome.findings[0].code == "command.read_only"
            assert "1.1" in outcome.message
    assert structure(document) == before and stack.index == 0


def test_not_read_only_for_current_or_bad_versions(doc: Document) -> None:
    assert not CommandStack(doc, default_registry()).read_only
    doc.schema_version = "garbage"
    assert not CommandStack(doc, default_registry()).read_only
    with pytest.raises(TypeError):
        CommandStack("doc", default_registry())  # type: ignore[arg-type]


# ---------------------------------------------------------------- events, i18n
def test_subscribe_events(stack: CommandStack, doc: Document) -> None:
    events: list[StackEvent] = []
    order: list[str] = []
    unsubscribe = stack.subscribe(events.append)
    stack.subscribe(lambda e: order.append("second"))
    stack.subscribe(lambda e: order.append("third"))
    label = w(doc, "lbl_name")
    first = SetProp(label, text("a"))
    stack.execute(first)
    stack.execute(SetProp(label, text("b")))
    stack.execute(SetProp(label, text("b")))  # no-op: no event
    stack.execute(SetProp(label, Prop(name="width", value="-1")))  # rejected: no event
    stack.undo()
    stack.redo()
    stack.mark_saved()
    stack.clear()
    assert [(e.kind, e.dirty) for e in events] == [
        ("execute", True),
        ("merge", True),
        ("undo", False),
        ("redo", True),
        ("saved", False),
        ("clear", False),
    ]
    assert events[0].command is first and events[-1].command is None
    assert order[:2] == ["second", "third"]
    unsubscribe()
    unsubscribe()  # idempotent
    stack.execute(SetProp(label, text("c")))
    assert len(events) == 6


def test_listener_exception_is_logged(
    stack: CommandStack, doc: Document, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(event: StackEvent) -> None:
        raise ValueError("listener bug")

    seen: list[str] = []
    stack.subscribe(broken)
    stack.subscribe(lambda e: seen.append(e.kind))
    with caplog.at_level(logging.ERROR, logger="pyguibud.core.commands"):
        assert stack.execute(SetProp(w(doc, "lbl_name"), text("a"))).accepted
    assert seen == ["execute"] and "listener" in caplog.text


def test_reentrancy_raises(stack: CommandStack, doc: Document) -> None:
    errors: list[Exception] = []
    label = w(doc, "lbl_name")

    def reenter(event: StackEvent) -> None:
        for action in (stack.undo, stack.redo, stack.clear,
                       lambda: stack.execute(SetProp(label, text("z"))),
                       lambda: stack.check(SetProp(label, text("z")))):  # fmt: skip
            try:
                action()
            except RuntimeError as exc:
                errors.append(exc)

    stack.subscribe(reenter)
    stack.execute(SetProp(label, text("a")))
    assert len(errors) == 5
    assert stack.index == 1 and stack.undo()  # the guard is released afterwards


def test_texts_follow_language(stack: CommandStack, doc: Document) -> None:
    assert stack.undo_text is None and stack.redo_text is None
    stack.execute(SetProp(w(doc, "lbl_name"), text("a")))
    assert stack.undo_text == "Set property"
    set_language("en_XA")
    assert stack.undo_text not in (None, "Set property")
    stack.undo()
    assert stack.redo_text not in (None, "Set property")


def test_outcome_and_event_values() -> None:
    assert not Outcome(accepted=False, changed=False)
    assert Outcome(accepted=True, changed=False).message == ""
    assert StackEvent(kind="clear", command=None, dirty=False).kind == "clear"


def test_bogus_window_kind_is_rejected_and_dump_still_works(
    stack: CommandStack, doc: Document
) -> None:
    window = doc.children[0]
    snapshot = Snapshot(stack)
    outcome = stack.execute(SetField(window, "kind", "bogus"))
    assert not outcome.accepted
    assert [f.code for f in outcome.findings] == ["validate.bad_window_kind"]
    assert window.kind == "main"
    assert snapshot.unchanged()
    dump_ui(doc)  # the invariant: whatever the stack accepts, the writer can write


def test_parents_ok_detects_bad_pointer(doc: Document) -> None:
    assert parents_ok(doc)
    label = w(doc, "lbl_name")
    label.parent = None
    assert not parents_ok(doc)


@pytest.fixture(autouse=True)
def _drop_demo_module() -> Iterator[None]:
    yield
    sys.modules.pop("validator_demo", None)
