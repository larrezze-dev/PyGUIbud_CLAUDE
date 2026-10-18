"""M23 model matrix (Step 19c, H32-H35, H42): the stack refuses abusive edits with a reason."""

from __future__ import annotations

import pytest

from pyguibud.core import (
    CommandStack,
    Document,
    GridCell,
    ImageResource,
    Layout,
    PackPlacement,
    PagePlacement,
    Prop,
    Variable,
    Widget,
    Window,
    default_registry,
    dump_ui,
    read_ui,
)
from pyguibud.core.commands import (
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
    reparent,
)
from pyguibud.core.model import Event
from tests.core.xml_helpers import HELLO
from tests.strategies_m23 import BAD_IDS, BAD_INTS, BAD_NAMES, HUGE_INTS


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


def refused(stack: CommandStack, command: Command) -> None:
    before = dump_ui(stack.document)
    outcome = stack.execute(command)
    assert not outcome.accepted and outcome.message
    assert dump_ui(stack.document) == before
    assert stack.index == 0


@pytest.mark.parametrize("bad", BAD_IDS)
def test_bad_ids_are_refused_everywhere(stack: CommandStack, doc: Document, bad: str) -> None:
    refused(stack, SetField(w(doc, "lbl_name"), "id", bad))
    refused(stack, SetField(doc.children[0], "id", bad))
    new = Widget(class_name="Label", id=bad, placement=PackPlacement())
    refused(stack, InsertNode(w(doc, "frm_about"), new))
    refused(stack, SetVariable(doc, Variable(id=bad, type="string")))
    refused(stack, SetResource(doc, ImageResource(id=bad, src="a.png")))


def test_duplicate_ids_are_refused(stack: CommandStack, doc: Document) -> None:
    refused(stack, SetField(w(doc, "lbl_name"), "id", "btn_greet"))
    refused(stack, SetVariable(doc, Variable(id="btn_greet", type="string")))
    refused(stack, SetResource(doc, ImageResource(id="lbl_name", src="a.png")))


@pytest.mark.parametrize("bad", BAD_NAMES)
def test_non_identifier_handlers_and_variables_are_refused(
    stack: CommandStack, doc: Document, bad: str
) -> None:
    refused(stack, SetEvents(w(doc, "btn_greet"), [Event(name="command", handler=bad)]))
    refused(stack, SetField(w(doc, "ent_name"), "bind", bad))
    refused(stack, SetVariable(doc, Variable(id=bad, type="string")))


def test_an_int_variable_on_a_text_entry_is_accepted_today(
    stack: CommandStack, doc: Document
) -> None:
    """Reported to the orchestrator: the binding table lets Entry bind int/double (Tk allows it).

    A bool is a mismatch (``validate.bind_type_mismatch``). No new rule was invented.
    """
    assert stack.execute(SetVariable(doc, Variable(id="user_name", type="int", default="0")))
    out = stack.execute(SetVariable(doc, Variable(id="user_name", type="bool")))
    assert not out and out.findings[0].code == "validate.bind_type_mismatch"


def test_a_bound_variable_cannot_be_deleted(stack: CommandStack, doc: Document) -> None:
    before = dump_ui(doc)
    outcome = stack.execute(RemoveVariable(doc, "user_name"))
    assert not outcome and outcome.findings[0].code == "command.variable_in_use"
    assert dump_ui(doc) == before


def test_h42_a_used_resource_cannot_be_removed(stack: CommandStack, doc: Document) -> None:
    assert stack.execute(SetResource(doc, ImageResource(id="img_a", src="a.png")))
    assert stack.execute(SetField(w(doc, "frm_about"), "placement", PagePlacement(image="img_a")))
    # Only the page image uses it: still refused.
    out = stack.execute(RemoveResource(doc, "img_a"))
    assert not out and out.findings[0].code == "command.resource_in_use"
    assert "img_a" in doc.resources
    assert stack.execute(SetProp(w(doc, "btn_greet"), Prop(name="image", ref="img_a")))
    out = stack.execute(RemoveResource(doc, "img_a"))
    assert not out and out.findings[0].code == "command.resource_in_use"
    # A ref to a resource that does not exist is refused too (no orphaning on the way in).
    refused_ref = SetProp(w(doc, "lbl_name"), Prop(name="image", ref="img_missing"))
    before = dump_ui(doc)
    assert not stack.execute(refused_ref)
    assert dump_ui(doc) == before


# ---------------------------------------------------------------- cycles and containers
def test_reparent_cycles_and_non_containers(stack: CommandStack, doc: Document) -> None:
    nbk, frm, lbl = w(doc, "nbk_main"), w(doc, "frm_greeting"), w(doc, "lbl_name")
    refused(stack, MoveNode(nbk, frm, 0))
    refused(stack, MoveNode(nbk, nbk, 0))
    refused(stack, MoveNode(frm, lbl, 0))  # a Label is not a container
    new = Widget(class_name="Label", id="zz", placement=GridCell(row=0, column=0))
    refused(stack, InsertNode(lbl, new))
    refused(stack, reparent(nbk, frm, 0, GridCell(row=0, column=0)))


def test_a_window_cannot_nest(stack: CommandStack, doc: Document) -> None:
    win = doc.children[0]
    refused(stack, MoveNode(win, win, 0))
    refused(stack, MoveNode(win, w(doc, "frm_about"), 0))
    refused(stack, InsertNode(w(doc, "frm_about"), win))
    refused(stack, MoveNode(w(doc, "frm_about"), doc, 0))  # a widget cannot be a document child


# ---------------------------------------------------------------- grid values
@pytest.mark.parametrize("bad", BAD_INTS)
def test_absurd_grid_numbers(stack: CommandStack, doc: Document, bad: int) -> None:
    lbl = w(doc, "lbl_name")
    refused(stack, SetField(lbl, "placement", GridCell(row=bad, column=0)))
    refused(stack, SetField(lbl, "placement", GridCell(row=0, column=bad)))
    refused(stack, SetField(lbl, "placement", GridCell(row=0, column=0, rowspan=bad)))
    refused(stack, SetField(lbl, "placement", GridCell(row=0, column=0, columnspan=bad)))
    refused(stack, SetField(lbl, "placement", GridCell(row=0, column=0, padx=bad)))
    refused(stack, SetField(lbl, "placement", GridCell(row=0, column=0, pady=bad)))
    refused(stack, SetField(doc.children[0], "layout", Layout(type="grid", padding=bad)))


@pytest.mark.parametrize("bad", HUGE_INTS)
def test_absurd_pack_numbers(stack: CommandStack, doc: Document, bad: int) -> None:
    lbl = w(doc, "lbl_about")
    refused(stack, SetField(lbl, "placement", PackPlacement(padx=bad)))
    refused(stack, SetField(lbl, "placement", PackPlacement(pady=-1)))


def test_grid_collision_and_mixed_layout(stack: CommandStack, doc: Document) -> None:
    # lbl_about sits in a pack container: a grid cell is the wrong placement kind.
    refused(stack, SetField(w(doc, "lbl_about"), "placement", GridCell(row=0, column=0)))
    # btn_greet onto lbl_name's cell collides.
    refused(stack, SetField(w(doc, "btn_greet"), "placement", GridCell(row=0, column=0)))
    # Layout switched to pack while the children keep their grid cells.
    refused(stack, SetField(w(doc, "frm_greeting"), "layout", Layout(type="pack")))


def test_two_main_windows(stack: CommandStack, doc: Document) -> None:
    refused(stack, InsertNode(doc, Window(id="second", kind="main", layout=Layout(type="pack"))))
    other = Window(id="other", kind="dialog", layout=Layout(type="pack"))
    assert stack.execute(InsertNode(doc, other))
    count = stack.index
    out = stack.execute(SetField(other, "kind", "main"))
    assert not out and out.message and stack.index == count


def test_a_component_that_includes_itself_is_refused(stack: CommandStack, doc: Document) -> None:
    from pyguibud.core import Include

    comp = Window(id="comp", kind="component", layout=Layout(type="pack"))
    assert stack.execute(InsertNode(doc, comp))
    loop = Include(id="inc", src="#", component="comp", placement=PackPlacement())
    refused_count = stack.index
    before = dump_ui(doc)
    out = stack.execute(InsertNode(comp, loop))
    assert not out and out.message and stack.index == refused_count
    assert dump_ui(doc) == before
