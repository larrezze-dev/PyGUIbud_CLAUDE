"""Invariant: a document the command stack accepts can always be written and re-read.

``CommandStack.execute`` validates after every edit, so any state it accepts must be serialisable by
``dump_ui`` (and readable again). These tests push invalid values through every field that
``SetField`` whitelists, plus the other value-carrying commands.
"""

from __future__ import annotations

import importlib
from collections.abc import Callable
from dataclasses import dataclass

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
    Meta,
    PackPlacement,
    PagePlacement,
    Prop,
    Statusbar,
    Variable,
    Widget,
    Window,
    default_registry,
    dump_ui,
    read_ui,
    read_ui_bytes,
    xml_io,
)
from pyguibud.core.commands import (
    EDITABLE_FIELDS,
    Command,
    InsertNode,
    SetEvents,
    SetField,
    SetProp,
    SetResource,
    SetVariable,
)
from tests.core.xml_helpers import HELLO

Pick = Callable[[Document], object]


def _find(node_id: str) -> Pick:
    return lambda document: document.find(node_id)


def _window(document: Document) -> object:
    return document.children[0]


def _meta(document: Document) -> object:
    return document.meta


def _statusbar(document: Document) -> object:
    return document.children[0].statusbar


@dataclass(frozen=True)
class Case:
    owner: type
    pick: Pick
    field: str
    values: tuple[object, ...]


BAD_LAYOUTS: tuple[object, ...] = (
    Layout(type="bogus"),  # type: ignore[arg-type]
    Layout(type="pack", orient="diagonal"),  # type: ignore[arg-type]
    Layout(type="grid", padding=-1),
    Layout(type="grid", gap=10_001),
    Layout(type="grid"),
    Layout(type="pack"),
    None,
)
BAD_PLACEMENTS: tuple[object, ...] = (
    GridCell(row=-1, column=0),
    GridCell(row=0, column=0, sticky="zz"),
    GridCell(row=0, column=5, sticky="n"),
    GridCell(row=0, column=1),  # collides with the entry
    PackPlacement(fill="bogus"),  # type: ignore[arg-type]
    PackPlacement(expand=1),  # type: ignore[arg-type]
    PackPlacement(fill="both", expand=True),
    PackPlacement(padx=-3),
    PagePlacement(text=Prop(name="other", value="x")),
    PagePlacement(text="plain"),  # type: ignore[arg-type]
    PagePlacement(image="missing"),
    PagePlacement(weight=-1),
    PagePlacement(text=Prop(name="text", value="Tab", translatable=True)),
    None,
)
IDS: tuple[object, ...] = ("", "1bad", "with space", "class", "x" * 70, "nbk_main", "fresh_id")
TEXTS: tuple[object, ...] = ("bad\x01char", "fine", "", None)

CASES: tuple[Case, ...] = (
    Case(Window, _window, "id", IDS),
    Case(Window, _window, "kind", ("bogus", "", "MAIN", "dialog", "component", "main")),
    Case(Window, _window, "layout", BAD_LAYOUTS),
    Case(Window, _window, "menubar", (None, Menubar())),
    Case(Window, _window, "statusbar", (None, Statusbar(id="sts_two"), Statusbar(id="bad id"))),
    Case(Window, _window, "min_width", (-1, 10_001, 0, 480, None)),
    Case(Window, _window, "min_height", (-1, 10_001, 0, 320, None)),
    Case(Window, _window, "modal", (True, False)),
    Case(Window, _window, "buttons", TEXTS),
    Case(Widget, _find("btn_greet"), "id", IDS),
    Case(
        Widget,
        _find("btn_greet"),
        "class_name",
        ("Bogus", "", "tb:meter", "a:b:c", "tb:Meter", ":Meter", "Entry", "Frame", "Menu", "Label"),
    ),
    Case(Widget, _find("ent_name"), "bind", ("nope", "1x", "class", "user_name", "x\x01", None)),
    Case(Widget, _find("btn_greet"), "fallback", ("Bogus", "tb:Meter", "Label", "x\x01", None)),
    Case(Widget, _find("btn_greet"), "plugin", TEXTS),
    Case(Widget, _find("btn_greet"), "placement", BAD_PLACEMENTS),
    Case(Widget, _find("lbl_about"), "placement", BAD_PLACEMENTS),
    Case(Widget, _find("frm_about"), "placement", BAD_PLACEMENTS),
    Case(Widget, _find("frm_greeting"), "layout", BAD_LAYOUTS),
    Case(Widget, _find("lbl_name"), "layout", BAD_LAYOUTS),
    Case(Widget, _find("nbk_main"), "layout", BAD_LAYOUTS),
    Case(Include, _find("inc_one"), "id", IDS),
    Case(Include, _find("inc_one"), "src", ("", "a\x01.ui", "/abs.ui", "../x.ui", "ok.ui")),
    Case(Include, _find("inc_one"), "component", ("", "1x", "class", "x\x01", "other")),
    Case(Include, _find("inc_one"), "placement", BAD_PLACEMENTS),
    Case(Menu, _find("mnu_file"), "id", IDS),
    Case(Action, _find("act_quit"), "id", IDS),
    Case(Action, _find("act_quit"), "handler", ("", "1x", "class", "x\x01", "on_other", None)),
    Case(Action, _find("act_quit"), "shortcut", ("badchar", "fine", "", "Q", "Ctrl+Z", None)),
    Case(Statusbar, _statusbar, "id", IDS),
    Case(Meta, _meta, "generator", TEXTS[:3]),
    Case(Meta, _meta, "source_locale", TEXTS[:3]),
    Case(Meta, _meta, "i18n_domain", TEXTS[:3]),
    Case(Meta, _meta, "theme", TEXTS[:3]),
)


def _stack() -> CommandStack:
    document = read_ui(HELLO).document
    window = document.children[0]
    # An include is part of the SetField whitelist; HELLO has none, so add a valid one.
    include = Include(
        id="inc_one",
        src="part.ui",
        component="part",
        placement=GridCell(row=3, column=0),
    )
    stack = CommandStack(document, default_registry(), source="hello.ui")
    assert stack.execute(InsertNode(window, include)).accepted
    return stack


def assert_serialisable(document: Document) -> None:
    """The invariant: the writer accepts the document and the reader accepts what it wrote."""
    data = dump_ui(document)
    again = read_ui_bytes(data).document
    assert dump_ui(again) == data


def _ids(case: Case) -> str:
    return f"{case.owner.__name__}.{case.field}"


def test_every_whitelisted_field_is_covered() -> None:
    covered = {(case.owner, case.field) for case in CASES}
    whitelisted = {(owner, name) for owner, fields in EDITABLE_FIELDS.items() for name in fields}
    assert covered == whitelisted


@pytest.mark.parametrize("case", CASES, ids=_ids)
def test_accepted_set_field_is_always_serialisable(case: Case) -> None:
    for value in case.values:
        stack = _stack()
        target = case.pick(stack.document)
        assert isinstance(target, case.owner)
        outcome = stack.execute(SetField(target, case.field, value))
        if not outcome.accepted:
            assert outcome.findings, (case.field, value)
        assert_serialisable(stack.document)


# ---------------------------------------------------------------- Step 10 guards (R69 to R72)
@pytest.mark.parametrize("value", ["fine", "", "Q", "Ctrl+Ctrl+Z", "badchar"])
def test_bad_shortcut_is_rejected_by_the_guard(value: str) -> None:
    stack = _stack()
    action = stack.document.find("act_quit")
    assert isinstance(action, Action)
    before = dump_ui(stack.document)
    outcome = stack.execute(SetField(action, "shortcut", value))
    assert not outcome.accepted and outcome.findings
    assert action.shortcut == "Ctrl+Q" and dump_ui(stack.document) == before


@pytest.mark.parametrize("value", ["Ctrl+Z", "ctrl+shift+f5", "F1", None])
def test_good_shortcut_is_accepted_by_the_guard(value: str | None) -> None:
    stack = _stack()
    action = stack.document.find("act_quit")
    assert isinstance(action, Action)
    assert stack.execute(SetField(action, "shortcut", value)).accepted
    assert_serialisable(stack.document)


@pytest.mark.parametrize("name", ["run", "show", "vars", "destroy", "setup_ui"])
def test_reserved_id_is_rejected_by_the_guard(name: str) -> None:
    stack = _stack()
    label = stack.document.find("lbl_name")
    assert isinstance(label, Widget)
    outcome = stack.execute(SetField(label, "id", name))
    assert not outcome.accepted
    assert [f.code for f in outcome.findings] == ["validate.reserved_id"]
    assert label.id == "lbl_name"


def test_bad_key_sequence_is_rejected_by_the_guard() -> None:
    stack = _stack()
    entry = stack.document.find("ent_name")
    assert isinstance(entry, Widget)
    outcome = stack.execute(SetEvents(entry, [Event(name="key:<Button-1>", handler="h")]))
    assert not outcome.accepted
    assert [f.code for f in outcome.findings] == ["validate.bad_key_sequence"]


# ---------------------------------------------------------------- the reported bug
@pytest.mark.parametrize("kind", ["bogus", "", "MAIN", "dialogs"])
def test_bogus_window_kind_is_rejected(kind: str) -> None:
    stack = _stack()
    window = stack.document.children[0]
    before = dump_ui(stack.document)
    outcome = stack.execute(SetField(window, "kind", kind))
    assert not outcome.accepted
    assert [f.code for f in outcome.findings] == ["validate.bad_window_kind"]
    assert window.kind == "main"
    assert dump_ui(stack.document) == before


def test_valid_window_kind_change_is_accepted() -> None:
    stack = _stack()
    window = stack.document.children[0]
    assert stack.execute(SetField(window, "kind", "dialog")).accepted
    # A window with a menu bar cannot become a component.
    assert not stack.execute(SetField(window, "kind", "component")).accepted
    assert_serialisable(stack.document)


# ---------------------------------------------------------------- the other value commands
def _other_commands(stack: CommandStack) -> list[Command]:
    document = stack.document
    window = document.children[0]
    label = document.find("lbl_name")
    assert isinstance(label, Widget)
    return [
        SetVariable(document, Variable(id="v1", type="bogus")),  # type: ignore[arg-type]
        SetVariable(document, Variable(id="v1", type="int", default="x")),
        SetVariable(document, Variable(id="v1", type="string", default=3)),  # type: ignore[arg-type]
        SetVariable(document, Variable(id="v1", type="string", default="d\x01")),
        SetVariable(document, Variable(id="1bad", type="string")),
        SetVariable(document, Variable(id="ok_var", type="bool", default="true")),
        SetResource(document, ImageResource(id="img", src="")),
        SetResource(document, ImageResource(id="img", src="a\x01.png")),
        SetResource(document, ImageResource(id="img", src="icons/a.png")),
        SetProp(label, Prop(name="text", value=3)),  # type: ignore[arg-type]
        SetProp(label, Prop(name="text", value="x", translatable=1)),  # type: ignore[arg-type]
        SetProp(label, Prop(name="text", value="x", ref="missing")),
        SetProp(label, Prop(name="text", value="x", context="c\x01")),
        SetProp(label, Prop(name="odd\x01name", value="x")),
        SetProp(label, Prop(name="", value="x")),
        SetProp(window, Prop(name="title", value="T", comment=5)),  # type: ignore[arg-type]
        SetEvents(label, [Event(name="bogus", handler="h")]),
        SetEvents(label, [Event(name="change", handler=5)]),  # type: ignore[arg-type]
        SetEvents(label, [Event(name="change", handler="on_change")]),
    ]


@pytest.mark.parametrize("index", range(19))
def test_other_commands_never_leave_an_unwritable_document(index: int) -> None:
    stack = _stack()
    command = _other_commands(stack)[index]
    stack.execute(command)
    assert_serialisable(stack.document)


# ---------------------------------------------------------------- the writer's closed sets
def test_validator_closed_sets_match_the_writer() -> None:
    validate_module = importlib.import_module("pyguibud.core.validate")
    assert validate_module._WINDOW_KINDS == xml_io._KINDS
    assert validate_module._VARIABLE_TYPES == xml_io._VAR_TYPES
    assert validate_module._LAYOUT_TYPES == xml_io._LAYOUT_TYPES
    assert validate_module._ORIENTS == xml_io._ORIENTS
    assert validate_module._FILLS == xml_io._FILLS
