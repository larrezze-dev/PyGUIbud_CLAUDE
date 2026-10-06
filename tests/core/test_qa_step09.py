"""Regressions for the Step 09 QA report (B1, B2, M1, M2 and the minors).

Each test mirrors one block of the QA repro script: whatever the command, a rejected or failing
edit leaves the document and the stack byte-identical (I1), whatever the stack accepts can be
saved and read again (I2), and malformed input never leaves a corrupted state behind (I3).
"""

# The tests re-read state that mypy narrowed before a mutating call.
# mypy: disable-error-code="unreachable"

from __future__ import annotations

import pytest

from pyguibud import i18n
from pyguibud.core import (
    CommandStack,
    Document,
    Event,
    Finding,
    GridCell,
    ImageResource,
    Layout,
    Menubar,
    PagePlacement,
    Prop,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    Window,
    commands,
    default_registry,
    dump_ui,
    read_ui,
    read_ui_bytes,
    validate,
)
from pyguibud.core.commands import (
    DEFAULT_LAYOUT,
    Command,
    InsertNode,
    MoveNode,
    RemoveResource,
    RemoveVariable,
    SetEvents,
    SetField,
    SetProp,
    SetResource,
    SetVariable,
)
from pyguibud.core.errors import XmlIoError
from pyguibud.core.model import WidgetSpec
from pyguibud.core.validate import _M_TRUNCATED
from pyguibud.i18n import set_language
from tests.core.xml_helpers import HELLO, structure


@pytest.fixture
def doc() -> Document:
    return read_ui(HELLO).document


@pytest.fixture
def stack(doc: Document) -> CommandStack:
    return CommandStack(doc, default_registry())


def node(document: Document, node_id: str) -> Widget:
    found = document.find(node_id)
    assert isinstance(found, Widget)
    return found


def state(stack: CommandStack) -> tuple[object, ...]:
    """Everything a rejected or failing command must leave untouched (I1)."""
    return (
        dump_ui(stack.document),
        structure(stack.document),
        stack.index,
        stack.is_dirty,
        stack.can_redo,
        stack._saved_index,
        stack._merge_open,
        tuple(stack._history),
    )


def saveable(document: Document) -> None:
    """I2: the state can be written and read back."""
    read_ui_bytes(dump_ui(document))


def harmless_edit_works(stack: CommandStack) -> None:
    """The stack is not bricked: an ordinary edit is accepted and undone."""
    outcome = stack.execute(SetProp(node(stack.document, "lbl_name"), Prop(name="text", value="x")))
    assert outcome.accepted, outcome.message
    assert stack.undo()


# ---------------------------------------------------------------- B1: MoveNode index
@pytest.mark.parametrize(
    ("moved", "index", "final"), [("lbl_name", 10**30, -1), ("btn_greet", -(10**30), 0)]
)
def test_b1_huge_move_index_clamps_instead_of_losing_the_node(
    stack: CommandStack, doc: Document, moved: str, index: int, final: int
) -> None:
    widget, frame = node(doc, moved), node(doc, "frm_greeting")
    original = frame.children
    outcome = stack.execute(MoveNode(widget, frame, index))
    assert outcome.accepted and outcome.changed, outcome.message
    assert widget.parent is frame and doc.find(moved) is widget
    assert frame.children[final] is widget  # list.insert semantics, no OverflowError
    saveable(doc)
    assert stack.undo() and frame.children == original


@pytest.mark.parametrize("index", [1.5, True, "1", None])
def test_b1_bad_move_index_is_refused_before_anything_changes(
    stack: CommandStack, doc: Document, index: object
) -> None:
    before = state(stack)
    with pytest.raises(TypeError, match="index"):
        MoveNode(node(doc, "lbl_name"), node(doc, "frm_greeting"), index)  # type: ignore[arg-type]
    assert state(stack) == before


@pytest.mark.parametrize("index", [1.5, False, "0"])
def test_b1_bad_insert_index_is_refused(doc: Document, index: object) -> None:
    child = Widget(class_name="Label", id="lbl_new", placement=GridCell(row=5, column=0))
    with pytest.raises(TypeError, match="index"):
        InsertNode(node(doc, "frm_greeting"), child, index)  # type: ignore[arg-type]


@pytest.mark.parametrize("index", [1.5, True, 10**30])
def test_b1_model_primitives_check_the_index_before_mutating(doc: Document, index: object) -> None:
    frame = node(doc, "frm_greeting")
    label = node(doc, "lbl_name")
    children = frame.children
    if isinstance(index, int) and not isinstance(index, bool):
        assert frame.move_child(label, index) == 0  # clamped: list.insert semantics
        assert frame.children[-1] is label
        return
    with pytest.raises(TypeError):
        frame.move_child(label, index)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        frame.insert_child(index, Widget(class_name="Label", id="x"))  # type: ignore[arg-type]
    assert frame.children == children and label.parent is frame


# ---------------------------------------------------------------- B2: failures after apply
def test_b2_non_event_items_are_refused_up_front(stack: CommandStack, doc: Document) -> None:
    before = state(stack)
    with pytest.raises(TypeError, match="Event"):
        SetEvents(node(doc, "btn_greet"), [1])  # type: ignore[list-item]
    assert state(stack) == before
    harmless_edit_works(stack)


@pytest.mark.parametrize(
    "layout",
    [
        Layout(type="grid", columns=None),  # type: ignore[arg-type]
        Layout(type="grid", columns=(1,)),  # type: ignore[arg-type]
        Layout(type="grid", rows=("x",)),  # type: ignore[arg-type]
    ],
)
def test_b2_malformed_layout_is_rejected_without_trace(
    stack: CommandStack, doc: Document, layout: Layout
) -> None:
    before = state(stack)
    outcome = stack.execute(SetField(node(doc, "frm_greeting"), "layout", layout))
    assert not outcome.accepted
    assert outcome.findings[0].code == "validate.bad_item"
    assert state(stack) == before
    harmless_edit_works(stack)


class _Exploding:
    """A registry that fails on demand, standing in for a validator or plugin bug."""

    def __init__(self, error: BaseException) -> None:
        self.inner = default_registry()
        self.error = error
        self.armed = False

    def get(self, name: str) -> WidgetSpec | None:
        if self.armed and name == "Label":
            raise self.error
        return self.inner.get(name)


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_b2_a_crash_after_apply_reverts_and_raises(doc: Document, error: BaseException) -> None:
    registry = _Exploding(error)
    stack = CommandStack(doc, registry)
    command = SetProp(node(doc, "btn_greet"), Prop(name="text", value="changed"))
    before = state(stack)

    class _ArmOnApply(Command):
        # Arms the registry from inside apply(), so the crash happens in the post-apply guard.
        def apply(self) -> None:
            command.apply()
            registry.armed = True

        def revert(self) -> None:
            command.revert()

    with pytest.raises(type(error)):
        stack.execute(_ArmOnApply())
    assert state(stack) == before
    registry.armed = False
    harmless_edit_works(stack)


def test_b2_reexecuting_an_applied_command_never_reverts_it(
    stack: CommandStack, doc: Document
) -> None:
    child = Widget(class_name="Label", id="lbl_new", placement=GridCell(row=5, column=0))
    command = InsertNode(node(doc, "frm_greeting"), child)
    assert stack.execute(command).accepted
    before = state(stack)
    with pytest.raises(RuntimeError, match="already applied"):
        stack.execute(command)
    assert state(stack) == before and child.parent is node(doc, "frm_greeting")


# ---------------------------------------------------------------- M1: accepted but unsaveable
def _label_text(**fields: object) -> Prop:
    return Prop(**{"name": "text", "value": "x", **fields})  # type: ignore[arg-type]


UI_RAW = RawXml(xml='<prop xmlns="urn:pyguibud:ui:1"/>')

M1_CASES = [
    ("Prop(name=None)", lambda d: SetProp(node(d, "lbl_name"), Prop(name=None, value="x")),  # type: ignore[arg-type]
     "validate.not_text"),
    ("Prop(value=None)", lambda d: SetProp(node(d, "lbl_name"), _label_text(value=None)),
     "validate.not_text"),
    ("page text value None",
     lambda d: SetField(node(d, "frm_greeting"), "placement",
                        PagePlacement(text=_label_text(value=None))),
     "validate.not_text"),
    ("Prop extra attribute 'a b'",
     lambda d: SetProp(node(d, "lbl_name"), _label_text(extra_attrs={"a b": "1"})),
     "validate.bad_attribute_name"),
    ("Prop extra attribute shadows 'name'",
     lambda d: SetProp(node(d, "lbl_name"), _label_text(extra_attrs={"name": "y"})),
     "validate.bad_attribute_name"),
    ("Prop extra attribute value None",
     lambda d: SetProp(node(d, "lbl_name"), _label_text(extra_attrs={"data": None})),
     "validate.not_text"),
    ("Event extra attribute xmlns",
     lambda d: SetEvents(node(d, "btn_greet"),
                         [Event(name="command", handler="on_greet", extra_attrs={"xmlns": "u"})]),
     "validate.bad_attribute_name"),
    ("Variable extra attribute '1x'",
     lambda d: SetVariable(d, Variable(id="v2", type="string", extra_attrs={"1x": "1"})),
     "validate.bad_attribute_name"),
    ("GridCell extra attribute ''",
     lambda d: SetField(node(d, "lbl_name"), "placement",
                        GridCell(row=0, column=0, sticky="w", extra_attrs={"": "1"})),
     "validate.bad_attribute_name"),
    ("GridCell extra_children str",
     lambda d: SetField(node(d, "lbl_name"), "placement",
                        GridCell(row=0, column=0, extra_children=("x",))),  # type: ignore[arg-type]
     "validate.bad_raw_xml"),
    ("GridCell RawXml broken",
     lambda d: SetField(node(d, "lbl_name"), "placement",
                        GridCell(row=0, column=0, extra_children=(RawXml(xml="<a"),))),
     "validate.bad_raw_xml"),
    ("RawXml that is a .ui element",
     lambda d: SetField(node(d, "lbl_name"), "placement",
                        GridCell(row=0, column=0, extra_children=(UI_RAW,))),
     "validate.bad_raw_xml"),
    ("RawXml with attributes",
     lambda d: SetResource(d, ImageResource(id="img", src="a.png", extra_children=(
         RawXml(xml="<x:a xmlns:x='urn:x'/>", extra_attrs={"k": "v"}),))),
     "validate.bad_raw_xml"),
]  # fmt: skip


@pytest.mark.parametrize(("label", "make", "code"), M1_CASES, ids=[c[0] for c in M1_CASES])
def test_m1_unsaveable_values_are_rejected_by_the_validator(
    stack: CommandStack, doc: Document, label: str, make: object, code: str
) -> None:
    before = state(stack)
    outcome = stack.execute(make(doc))  # type: ignore[operator]
    assert not outcome.accepted, label
    assert code in [f.code for f in outcome.findings], (label, outcome.findings)
    assert outcome.message  # a translated reason, never empty
    assert state(stack) == before
    saveable(doc)


def _deep_raw(levels: int) -> RawXml:
    return RawXml(xml="<x:a xmlns:x='urn:x'>" * levels + "</x:a>" * levels)


def test_m1_safety_net_rejects_what_the_validator_does_not_cover(
    stack: CommandStack, doc: Document
) -> None:
    # RawXml depth is left to the writer (spec section 12): only the safety net sees it.
    before = state(stack)
    # 98 levels parse on their own, but not below <cell> at element depth 6.
    placement = GridCell(row=0, column=0, sticky="w", extra_children=(_deep_raw(98),))
    command = SetField(node(doc, "lbl_name"), "placement", placement)
    checked = stack.check(command)
    outcome = stack.execute(command)
    assert not checked and not outcome
    assert outcome.findings[0].code == "command.unsaveable"
    assert "impossible to save" in outcome.message and "nested" in outcome.message
    assert state(stack) == before


def test_m1_safety_net_catches_a_key_mismatch_of_an_inserted_subtree(
    stack: CommandStack, doc: Document
) -> None:
    child = Widget(
        class_name="Label",
        id="lbl_new",
        placement=GridCell(row=5, column=0),
        props={"text": Prop(name="width", value="3")},
    )
    before = state(stack)
    outcome = stack.execute(InsertNode(node(doc, "frm_greeting"), child))
    assert not outcome and outcome.findings[0].code == "command.unsaveable"
    assert state(stack) == before and child.parent is None


def test_m1_already_unsaveable_documents_stay_editable(doc: Document) -> None:
    # Not a new problem: the guard blocks only what an edit adds (spec section 6.3).
    doc.children[0].extra_children.append(_deep_raw(99))  # parses, too deep below <window>
    with pytest.raises(XmlIoError, match="nested"):
        dump_ui(doc)
    stack = CommandStack(doc, default_registry())
    outcome = stack.execute(SetProp(node(doc, "lbl_name"), Prop(name="text", value="y")))
    assert outcome.accepted and node(doc, "lbl_name").props["text"].value == "y"
    assert stack.undo()
    fix = stack.execute(SetField(doc.children[0], "id", "main"))  # a no-op stays a no-op
    assert fix.accepted and not fix.changed


@pytest.mark.parametrize(
    "build",
    [
        lambda: Widget(class_name="Label", id="w", events=[1]),  # type: ignore[list-item]
        lambda: Widget(class_name="Label", id="w", events=None),  # type: ignore[arg-type]
        lambda: Widget(class_name="Label", id="w", props={"a": 1}),  # type: ignore[dict-item]
        lambda: Widget(class_name="Frame", id="w", layout=Layout(type="grid", columns=None)),  # type: ignore[arg-type]
        lambda: Widget(class_name="Label", id="w", extra_children=None),  # type: ignore[arg-type]
        lambda: Widget(class_name="Label", id="w", extra_attrs={1: "x"}),  # type: ignore[dict-item]
    ],
)
def test_m1_validator_never_raises_on_malformed_collections(build: object) -> None:
    document = Document()
    window = Window(id="main", layout=DEFAULT_LAYOUT)
    widget = build()  # type: ignore[operator]
    widget.placement = GridCell(row=0, column=0)
    window.append_child(widget)
    document.add_window(window)
    document.resources["bad"] = 1  # type: ignore[assignment]
    report = validate(document, default_registry(), limit=None)
    codes = {f.code for f in report.errors}
    assert "validate.bad_item" in codes  # the resource entry at least
    assert codes & {"validate.bad_item", "validate.bad_raw_xml", "validate.bad_attribute_name"}


def test_m1_valid_extras_are_still_accepted(stack: CommandStack, doc: Document) -> None:
    prop = _label_text(extra_attrs={"data-x": "1", "{urn:x}y": "2"})
    outcome = stack.execute(SetProp(node(doc, "lbl_name"), prop))
    assert outcome.accepted, outcome.message
    raw = RawXml(xml="<x:a xmlns:x='urn:x'><x:b/></x:a>")
    cell = GridCell(row=0, column=0, sticky="w", extra_children=(raw,))
    assert stack.execute(SetField(node(doc, "lbl_name"), "placement", cell)).accepted
    saveable(doc)


# ---------------------------------------------------------------- M2: shared bars
def test_m2_a_bar_from_another_document_is_copied_so_nothing_leaks() -> None:
    # The QA repro: doc2's menu bar set on doc1, then edited in doc2.
    doc1, doc2 = read_ui(HELLO).document, read_ui(HELLO).document
    stack1, stack2 = CommandStack(doc1, default_registry()), CommandStack(doc2, default_registry())
    theirs = doc2.children[0].menubar
    assert isinstance(theirs, Menubar)
    assert stack1.execute(SetField(doc1.children[0], "menubar", theirs)).accepted
    ours = doc1.children[0].menubar
    assert isinstance(ours, Menubar) and ours is not theirs
    assert all(a is not b for a, b in zip(ours.children, theirs.children, strict=True))
    file_menu = doc2.find("mnu_file")
    assert file_menu is not None
    assert stack2.execute(SetProp(file_menu, Prop(name="text", value="LEAKED"))).accepted
    assert b"LEAKED" not in dump_ui(doc1) and b"LEAKED" in dump_ui(doc2)
    saveable(doc1)


def test_m2_the_copy_is_kept_for_undo_and_redo(stack: CommandStack, doc: Document) -> None:
    dialog = Window(id="dlg", kind="dialog", layout=DEFAULT_LAYOUT)
    assert stack.execute(InsertNode(doc, dialog)).accepted
    given = Statusbar(id="sts_dlg", props={"text": Prop(name="text", value="Hi")})
    assert stack.execute(SetField(dialog, "statusbar", given)).accepted
    attached = dialog.statusbar
    assert isinstance(attached, Statusbar) and attached is not given
    assert attached.props == given.props and attached.props is not given.props
    assert stack.undo() and dialog.statusbar is None
    assert stack.redo() and dialog.statusbar is attached
    saveable(doc)


def test_m2_a_bar_of_another_window_is_copied_and_guarded(
    stack: CommandStack, doc: Document
) -> None:
    main = doc.children[0]
    dialog = Window(id="dlg", kind="dialog", layout=DEFAULT_LAYOUT)
    assert stack.execute(InsertNode(doc, dialog)).accepted
    before = state(stack)
    for name, bar in (("menubar", main.menubar), ("statusbar", main.statusbar)):
        outcome = stack.execute(SetField(dialog, name, bar))
        # The copy keeps the ids, so the ordinary guard refuses it (R01), not a special rule.
        assert not outcome and outcome.findings[0].code == "validate.duplicate_id", name
        assert state(stack) == before


def test_m2_inserting_a_window_attaches_copies_of_its_bars(
    stack: CommandStack, doc: Document
) -> None:
    main = doc.children[0]
    assert isinstance(main.menubar, Menubar)
    before = state(stack)
    twin = Window(id="dlg", kind="dialog", layout=DEFAULT_LAYOUT, menubar=main.menubar)
    outcome = stack.execute(InsertNode(doc, twin))
    assert not outcome and outcome.findings[0].code == "validate.duplicate_id"
    assert state(stack) == before and twin.menubar is main.menubar  # untouched when rejected
    fresh = Menubar()
    other = Window(id="dlg2", kind="dialog", layout=DEFAULT_LAYOUT, menubar=fresh)
    assert stack.execute(InsertNode(doc, other)).accepted
    attached = other.menubar
    assert isinstance(attached, Menubar) and attached is not fresh
    assert stack.undo() and other.menubar is fresh and other.parent is None
    assert stack.redo() and other.menubar is attached


def test_m2_setting_the_same_bar_again_is_a_noop(stack: CommandStack, doc: Document) -> None:
    main = doc.children[0]
    outcome = stack.execute(SetField(main, "menubar", main.menubar))
    assert outcome.accepted and not outcome.changed


def test_m2_copies_keep_the_whole_menu_tree(stack: CommandStack, doc: Document) -> None:
    main = doc.children[0]
    original = dump_ui(doc)
    theirs = read_ui(HELLO).document.children[0].menubar
    assert stack.execute(SetField(main, "menubar", theirs)).accepted
    assert dump_ui(doc) == original  # same content, other objects, parent pointers rebuilt
    assert isinstance(main.menubar, Menubar) and main.menubar is not theirs
    menu = main.menubar.children[0]
    assert menu.parent is main.menubar and all(c.parent is menu for c in menu.children)


# ---------------------------------------------------------------- minors
def test_edits_behind_the_stacks_back_are_seen(stack: CommandStack, doc: Document) -> None:
    assert stack.report().ok
    node(doc, "lbl_about").id = "class"  # not through the stack
    assert not stack.report().ok  # report() is never stale
    # The external error is pre-existing for the guard, so an unrelated edit is accepted ...
    assert stack.execute(SetProp(node(doc, "lbl_name"), Prop(name="text", value="y"))).accepted
    node(doc, "class").id = "lbl_about"  # ... and an external fix is seen as well:
    outcome = stack.execute(SetField(node(doc, "btn_greet"), "id", "class"))
    assert not outcome and outcome.findings[0].code == "validate.keyword_id"


def test_a_merged_command_can_be_executed_again(stack: CommandStack, doc: Document) -> None:
    label = node(doc, "lbl_name")
    first = SetProp(label, Prop(name="text", value="a"))
    second = SetProp(label, Prop(name="text", value="b"))
    assert stack.execute(first).accepted
    merged = stack.execute(second)
    assert merged.merged and stack.index == 1
    assert stack.execute(SetProp(label, Prop(name="text", value="c"))).merged
    stack.break_merge()
    assert stack.check(second).accepted  # used to raise RuntimeError("already applied")
    outcome = stack.execute(second)
    assert outcome.accepted and outcome.changed and stack.index == 2
    assert label.props["text"].value == "b"
    assert stack.undo() and label.props["text"].value == "c"


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, float("nan"), "3"])
def test_stack_limit_must_be_a_positive_int(doc: Document, limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        CommandStack(doc, default_registry(), limit=limit)  # type: ignore[arg-type]


@pytest.mark.parametrize("version", ["99", "abc", None, "0.9", "1.0.0", 1])
def test_a_hand_set_schema_version_the_writer_refuses_is_an_error(
    doc: Document, version: object
) -> None:
    doc.schema_version = version  # type: ignore[assignment]
    codes = [f.code for f in validate(doc, default_registry()).errors]
    assert codes == ["validate.bad_schema_version"]


@pytest.mark.parametrize("version", ["1.0", "1.1", "2.0"])
def test_current_and_newer_schema_versions_are_not_errors(doc: Document, version: str) -> None:
    doc.schema_version = version  # newer = read-only, which the stack blocks on its own
    assert validate(doc, default_registry()).ok


def test_truncated_message_uses_plural_forms() -> None:
    def message(count: int) -> str:
        return Finding(
            code="validate.truncated", msgid=_M_TRUNCATED, params={"count": count}, source="s"
        ).message

    assert message(1) == "1 more problem was found but not listed."
    assert message(2) == "2 more problems were found but not listed."
    assert i18n.plural_of(_M_TRUNCATED) == "{count} more problems were found but not listed."
    set_language("en_XA")
    assert message(1) != message(2) and "2" in message(2)


def test_removing_a_bound_variable_names_its_user(stack: CommandStack, doc: Document) -> None:
    before = state(stack)
    outcome = stack.execute(RemoveVariable(doc, "user_name"))
    assert not outcome and outcome.findings[0].code == "command.variable_in_use"
    assert (
        outcome.message == "The variable 'user_name' is still used by 'ent_name'; unbind it first."
    )
    assert outcome.findings[0].anchor is node(doc, "ent_name")
    assert state(stack) == before


def test_removing_an_unused_resource_is_accepted(stack: CommandStack, doc: Document) -> None:
    assert stack.execute(SetResource(doc, ImageResource(id="img", src="a.png"))).accepted
    assert stack.execute(RemoveResource(doc, "img")).accepted


def test_a_writer_crash_is_an_unsaveable_rejection(
    stack: CommandStack,
    doc: Document,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A shape the validator misses must still never be accepted (I2): any writer exception counts.
    def broken_dump(document: Document) -> bytes:
        if node(document, "lbl_name").props["text"].value == "y":  # only the edited state
            raise TypeError("unexpected shape")
        return dump_ui(document)

    before = state(stack)
    monkeypatch.setattr(commands, "dump_ui", broken_dump)
    outcome = stack.execute(SetProp(node(doc, "lbl_name"), Prop(name="text", value="y")))
    monkeypatch.undo()
    assert not outcome and outcome.findings[0].code == "command.unsaveable"
    assert "TypeError: unexpected shape" in outcome.message
    assert "writer failed" in caplog.text
    assert state(stack) == before


def test_a_failing_revert_after_a_crash_is_logged_and_the_crash_raised(
    doc: Document, caplog: pytest.LogCaptureFixture
) -> None:
    registry = _Exploding(RuntimeError("boom"))
    stack = CommandStack(doc, registry)

    class _BadRevert(Command):
        def apply(self) -> None:
            registry.armed = True

        def revert(self) -> None:
            raise ValueError("cannot revert")

    with pytest.raises(RuntimeError, match="boom"):
        stack.execute(_BadRevert())
    assert "also failed" in caplog.text
