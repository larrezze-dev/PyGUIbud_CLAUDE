"""Hypothesis command storm and transactional undo/redo (Step 19c, H37)."""

from __future__ import annotations

import logging
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.core import (
    CommandStack,
    Document,
    GridCell,
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
    Macro,
    MoveNode,
    RemoveNode,
    RemoveProp,
    RemoveVariable,
    SetField,
    SetProp,
    SetVariable,
    reparent,
)
from pyguibud.core.validate import new_errors
from tests.core.xml_helpers import HELLO
from tests.strategies_m23 import BAD_NAMES, any_ids, any_ints, small_ints

_BOXES = ("Frame", "Notebook", "LabelFrame")
CLASSES = ("Label", "Frame", "Button", "Entry", "Notebook", "Bogus")
PROPS = ("text", "width", "state", "image", "bogus")
VALUES = ("x", "", "12", "-3", "true", "99999999999", "#ff0000", "red", "a" * 200)

_action = st.fixed_dictionaries(
    {
        "kind": st.sampled_from(
            [
                "insert",
                "remove",
                "move",
                "setprop",
                "rmprop",
                "id",
                "bind",
                "place",
                "layout",
                "setvar",
                "rmvar",
                "macro",
                "undo",
                "redo",
            ]
        ),
        "a": st.integers(0, 40),
        "b": st.integers(0, 40),
        "idx": st.integers(-2, 6),
        "id": any_ids,
        "cls": st.sampled_from(CLASSES),
        "fresh": st.sampled_from(["alpha", "beta", "gamma", "delta", "w_1", "A9"]),
        "prop": st.sampled_from(PROPS),
        "value": st.sampled_from(VALUES),
        "n": st.lists(
            st.one_of(small_ints, small_ints, small_ints, any_ints), min_size=4, max_size=4
        ),
        "name": st.one_of(st.sampled_from(["user_name", "v1"]), st.sampled_from(BAD_NAMES)),
        "vtype": st.sampled_from(["string", "int", "double", "bool"]),
        "grid": st.booleans(),
        "flip": st.sampled_from([False] * 5 + [True]),
    }
)
_actions = st.lists(_action, min_size=1, max_size=30)


def _code(stack: CommandStack) -> str | None:
    """The failure code (a function, so mypy does not narrow the property across calls)."""
    return stack.failure.code if stack.failure is not None else None


def _nodes(document: Document) -> list[Any]:
    return [n for n in document.walk() if isinstance(n, (Window, Widget))]


def _placement(act: dict[str, Any], parent: Any) -> Any:
    """A placement that fits ``parent``'s layout, unless the action asks for a wrong one."""
    r, c, s, p = act["n"]
    layout = getattr(parent, "layout", None)
    grid = layout is not None and layout.type == "grid"
    if getattr(parent, "class_name", "") in ("Notebook", "PanedWindow"):
        return PagePlacement(text=Prop(name="text", value="t"), weight=max(0, p))
    if grid != act["flip"]:
        return GridCell(row=r, column=c, rowspan=s, columnspan=s, padx=p, pady=p)
    return PackPlacement(padx=p, pady=p)


def _command(document: Document, act: dict[str, Any]) -> Command | None:
    """Build one command from an action; None when the action does not apply."""
    nodes = _nodes(document)
    if not nodes:
        return None  # every window was removed
    node = nodes[act["a"] % len(nodes)]
    other = nodes[act["b"] % len(nodes)]
    if not act["flip"]:  # mostly well-formed targets; the flipped actions are the abuse
        boxes = [n for n in nodes if isinstance(n, Window) or n.class_name in _BOXES] or nodes
        other = boxes[act["b"] % len(boxes)]
        act = {**act, "n": [abs(x) % 4 for x in act["n"]]}
    kind = act["kind"]
    try:
        if kind == "insert":
            child = Widget(
                class_name=act["cls"],
                id=act["id"] if act["flip"] else act["fresh"],
                placement=_placement(act, other),
            )
            return InsertNode(other, child, act["idx"])
        if kind == "remove":
            return RemoveNode(node)
        if kind == "move":
            if act["grid"]:
                return reparent(node, other, act["idx"], _placement(act, other))
            return MoveNode(node, other, act["idx"])
        if kind == "setprop":
            return SetProp(node, Prop(name=act["prop"], value=act["value"]))
        if kind == "rmprop":
            return RemoveProp(node, act["prop"])
        if kind == "id":
            return SetField(node, "id", act["id"])
        if kind == "bind":
            return SetField(node, "bind", act["name"])
        if kind == "place":
            return SetField(node, "placement", _placement(act, node.parent))
        if kind == "layout":
            _, _, s, p = act["n"]
            layout = Layout(type="grid" if act["grid"] else "pack", padding=p, gap=s)
            return SetField(node, "layout", layout)
        if kind == "setvar":
            return SetVariable(document, Variable(id=act["name"], type=act["vtype"]))
        if kind == "rmvar":
            return RemoveVariable(document, act["name"])
        if kind == "macro":
            inner = {**act, "kind": "setprop"}
            first = _command(document, inner)
            second = _command(document, {**act, "kind": "move", "grid": True})
            return Macro("storm", [c for c in (first, second) if c is not None])
    except (TypeError, ValueError):
        return None
    return None


@pytest.fixture
def fresh() -> tuple[Document, CommandStack]:
    document = read_ui(HELLO).document
    return document, CommandStack(document, default_registry(), source="h.ui", limit=10_000)


@settings(
    max_examples=500,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)
@given(actions=_actions)
def test_command_storm(actions: list[dict[str, Any]]) -> None:
    document = read_ui(HELLO).document
    stack = CommandStack(document, default_registry(), source="h.ui", limit=10_000)
    start_dump = dump_ui(document)
    start_findings = stack.report().findings
    for act in actions:
        if act["kind"] == "undo":
            stack.undo()
        elif act["kind"] == "redo":
            stack.redo()
        else:
            command = _command(document, act)
            if command is not None:
                stack.execute(command)
        dump_ui(document)  # must always succeed
        assert not new_errors(start_findings, stack.report().findings)
    while stack.undo():
        pass
    assert dump_ui(document) == start_dump


# ---------------------------------------------------------------- H37 transactional undo/redo
class _Boom(Command):
    """A leaf whose revert (or apply) fails on demand, without touching anything."""

    def __init__(self) -> None:
        super().__init__()
        self.fail_revert = False
        self.fail_apply = False

    def apply(self) -> None:
        self._begin_apply()
        if self.fail_apply:
            raise RuntimeError("apply boom")
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        if self.fail_revert:
            raise RuntimeError("revert boom")
        self._applied = False


def _macro_with_boom(document: Document) -> tuple[Macro, _Boom]:
    boom = _Boom()
    label = document.find("lbl_name")
    assert isinstance(label, Widget)
    frame = document.find("frm_about")
    assert isinstance(frame, Widget)
    # Applied in order: move label, boom, set a property.  Reverted in the reverse order, so
    # the property revert succeeds before the boom fails; the macro must re-apply it.
    macro = Macro(
        "m",
        [
            SetField(frame, "id", "frm_other"),
            boom,
            SetProp(label, Prop(name="text", value="changed")),
        ],
    )
    return macro, boom


def test_a_failed_undo_leaves_the_document_untouched(
    fresh: tuple[Document, CommandStack], caplog: pytest.LogCaptureFixture
) -> None:
    document, stack = fresh
    macro, boom = _macro_with_boom(document)
    assert stack.execute(macro)
    applied = dump_ui(document)
    index = stack.index
    boom.fail_revert = True
    with caplog.at_level(logging.ERROR):
        assert stack.undo() is False
    assert _code(stack) == "command.undo_failed"
    failure = stack.failure
    assert failure is not None and "left as it was" in failure.message
    assert dump_ui(document) == applied
    assert stack.index == index and stack.can_undo and not stack.can_redo
    boom.fail_revert = False
    assert stack.undo() and _code(stack) is None
    assert dump_ui(document) != applied
    assert stack.redo()
    assert dump_ui(document) == applied
    assert stack.undo()


def test_a_failed_redo_leaves_the_document_untouched(
    fresh: tuple[Document, CommandStack],
) -> None:
    document, stack = fresh
    start = dump_ui(document)
    macro, boom = _macro_with_boom(document)
    assert stack.execute(macro)
    assert stack.undo()
    assert dump_ui(document) == start
    boom.fail_apply = True
    assert stack.redo() is False
    assert _code(stack) == "command.undo_failed"
    assert dump_ui(document) == start
    assert stack.index == 0 and stack.can_redo
    boom.fail_apply = False
    assert stack.redo() and _code(stack) is None
    assert stack.undo()
    assert dump_ui(document) == start


def test_failure_resets_on_execute_and_clear(fresh: tuple[Document, CommandStack]) -> None:
    document, stack = fresh
    macro, boom = _macro_with_boom(document)
    stack.execute(macro)
    boom.fail_revert = True
    assert not stack.undo() and _code(stack) is not None
    label = document.find("lbl_name")
    assert isinstance(label, Widget)
    assert stack.execute(SetProp(label, Prop(name="text", value="z")))
    assert _code(stack) is None
    stack.undo()
    boom.fail_revert = True
    stack.undo()  # the macro now fails again
    assert _code(stack) is not None
    stack.clear()
    assert _code(stack) is None


def test_keyboard_interrupt_in_a_revert_is_re_raised(fresh: tuple[Document, CommandStack]) -> None:
    document, stack = fresh
    macro, boom = _macro_with_boom(document)
    stack.execute(macro)
    applied = dump_ui(document)

    def interrupt() -> None:
        raise KeyboardInterrupt

    boom.revert = interrupt  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        stack.undo()
    assert dump_ui(document) == applied
    assert stack.index == 1


def test_a_revert_that_changes_then_raises_clears_the_history_but_stays_dirty(
    fresh: tuple[Document, CommandStack],
) -> None:
    document, stack = fresh
    label = document.find("lbl_name")
    assert isinstance(label, Widget)
    assert stack.execute(SetProp(label, Prop(name="text", value="z")))
    stack.mark_saved()
    assert stack.execute(SetProp(label, Prop(name="text", value="y")))
    stack.break_merge()
    assert stack.execute(SetField(label, "id", "lbl_x"))
    seen: list[str] = []
    stack.subscribe(lambda event: seen.append(event.kind))

    class _Half(SetField):
        def revert(self) -> None:
            super().revert()
            raise RuntimeError("late")

    stack._history[-1] = half = _Half(label, "id", "lbl_x")
    half.apply = lambda: None  # type: ignore[method-assign]
    half._applied = True
    half._old = "lbl_name"
    assert stack.undo() is False
    assert _code(stack) == "command.history_cleared"
    assert stack.index == 0 and not stack.can_undo and not stack.can_redo
    assert stack.is_dirty and seen == ["clear"]
