"""Pure tests of the inspector fields and the variable/layout macros (spec 14a sections 3-5, 17)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.core import default_registry, dump_ui
from pyguibud.core.commands import Macro, RemoveProp, SetField, SetProp
from pyguibud.core.diagnostics import Finding
from pyguibud.core.model import GridCell, PackPlacement, Prop, Widget, Window
from pyguibud.designer.editing import (
    new_variable,
    relayout_command,
    remove_and_unbind,
    rename_variable,
    variable_users,
)
from pyguibud.designer.properties import Field, commit_commands, field_rows, parse_value
from pyguibud.designer.session import DesignerSession


def _session(template: str = "login_form") -> DesignerSession:
    session = DesignerSession(default_registry())
    session.new_from_template(template)
    return session


def _by_id(session: DesignerSession, node_id: str) -> Widget:
    assert session.document is not None
    return next(n for n in session.document.walk() if isinstance(n, Widget) and n.id == node_id)


def _field(session: DesignerSession, nodes: tuple[object, ...], key: str) -> Field:
    assert session.document is not None
    rows = field_rows(nodes, session.registry, session.document)
    return next(f for f in rows if f.key == key)


def _run(session: DesignerSession, nodes: tuple[object, ...], key: str, value: object) -> bool:
    assert session.stack is not None
    command = commit_commands(nodes, _field(session, nodes, key), value)  # type: ignore[arg-type]
    return session.stack.execute(command).accepted


# ---------------------------------------------------------------- field_rows
def test_a_widget_has_general_property_and_placement_fields() -> None:
    session = _session()
    entry = _by_id(session, "ent_password")
    keys = [f.key for f in field_rows((entry,), session.registry, session.document)]  # type: ignore[arg-type]
    assert keys[:3] == ["field:class", "field:id", "field:bind"]
    assert "prop:show" in keys and "place:grid:sticky" in keys
    assert "line:col:1:weight" in keys and "line:row:1:minsize" in keys
    show = _field(session, (entry,), "prop:show")
    assert show.value == "*" and not show.is_default
    bind = _field(session, (entry,), "field:bind")
    assert bind.value == "password" and set(bind.choices) == {"username", "password"}
    weight = _field(session, (entry,), "line:col:1:weight")
    assert weight.value == "1" and not weight.multi


def test_a_window_has_window_fields_and_its_title() -> None:
    session = _session()
    window = session.document.children[0]  # type: ignore[union-attr]
    rows = {f.key: f for f in field_rows((window,), session.registry, session.document)}  # type: ignore[arg-type]
    assert rows["field:min_width"].value == "320"
    assert rows["field:min_height"].is_default and rows["field:min_height"].value == ""
    assert rows["prop:title"].translatable and rows["prop:title"].value == "Sign in"
    assert rows["layout:type"].value == "grid" and "field:buttons" not in rows


def test_multi_edit_shows_shared_fields_and_mixed_values() -> None:
    session = _session()
    first, second = _by_id(session, "lbl_username"), _by_id(session, "lbl_password")
    rows = {f.key: f for f in field_rows((first, second), session.registry, session.document)}  # type: ignore[arg-type]
    assert "field:id" not in rows and "place:grid:row" not in rows
    assert rows["prop:text"].value is None  # different texts: (mixed)
    assert rows["place:grid:sticky"].value == "w"  # equal: shown
    # A Label and an Entry share only fields with the same definition.
    entry = _by_id(session, "ent_username")
    mixed = {f.key for f in field_rows((first, entry), session.registry, session.document)}  # type: ignore[arg-type]
    assert "prop:text" not in mixed and "place:grid:padx" in mixed


@settings(max_examples=30, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(st.lists(st.sampled_from(range(5)), min_size=1, max_size=5, unique=True))
def test_shared_fields_are_the_intersection(picks: list[int]) -> None:
    session = _session()
    window = session.document.children[0]  # type: ignore[union-attr]
    nodes = tuple(window.children[i] for i in picks)
    shared = field_rows(nodes, session.registry, session.document)  # type: ignore[arg-type]
    singles = [
        {f.key for f in field_rows((n,), session.registry, session.document) if f.multi}  # type: ignore[arg-type]
        for n in nodes
    ]
    expected = set.intersection(*singles) if len(nodes) > 1 else {f.key for f in shared}
    assert {f.key for f in shared} <= expected
    if len(nodes) > 1:
        assert all(f.multi for f in shared)


# ---------------------------------------------------------------- parse_value (A14)
@pytest.mark.parametrize(
    ("kind", "text", "ok"),
    [
        ("int", "12", True),
        ("int", " -3 ", True),
        ("int", "999999999999", False),
        ("int", "abc", False),
        ("int", "1.5", False),
        ("float", "1e400", False),
        ("float", "2.5", True),
        ("float", "nan", False),
        ("colour", "#1C3FF0", True),
        ("colour", "red", True),
        ("colour", "#12", False),
        ("string", "anything at all", True),
    ],
)
def test_parse_value_grammar(kind: str, text: str, ok: bool) -> None:
    field = Field("prop:x", "Properties", "x", kind, "", minimum=None, maximum=None)  # type: ignore[arg-type]
    result = parse_value(field, text)
    assert isinstance(result, str) is ok
    if not ok:
        assert isinstance(result, Finding) and result.message


def test_parse_value_checks_the_range_and_empty_resets() -> None:
    field = Field("prop:x", "Properties", "x", "int", "", minimum=0, maximum=10)
    result = parse_value(field, "11")
    assert isinstance(result, Finding) and result.message == "Must be between 0 and 10."
    assert parse_value(field, "  ") == ""


# ---------------------------------------------------------------- commit_commands
def test_a_text_commit_keeps_translatable_context_and_round_trips() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    window = session.document.children[0]
    assert _run(session, (window,), "prop:title", "Log in")
    title = window.props["title"]
    assert title.value == "Log in" and title.translatable and title.context == "window title"
    session.stack.undo()
    assert dump_ui(session.document) == before


def test_reset_removes_the_property_and_a_new_one_takes_translatable() -> None:
    session = _session()
    label = _by_id(session, "lbl_username")
    field = _field(session, (label,), "prop:text")
    assert isinstance(commit_commands((label,), field, None), RemoveProp)
    assert _run(session, (label,), "prop:width", "12")
    assert label.props["width"] == Prop(name="width", value="12")


def test_a_multi_edit_is_one_undo_step_with_a_counted_label() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    first, second = _by_id(session, "lbl_username"), _by_id(session, "lbl_password")
    command = commit_commands(
        (first, second), _field(session, (first, second), "prop:text"), "Same"
    )
    assert isinstance(command, Macro)
    assert session.stack.execute(command).accepted
    assert first.props["text"].value == second.props["text"].value == "Same"
    assert session.stack.undo_text == "Set 'Text' on 2 elements"
    session.stack.undo()
    assert dump_ui(session.document) == before


def test_placement_window_and_grid_line_fields() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    entry = _by_id(session, "ent_password")
    window = session.document.children[0]
    assert _run(session, (entry,), "place:grid:padx", "4")
    assert isinstance(entry.placement, GridCell) and entry.placement.padx == 4
    assert entry.placement.sticky == "ew"
    assert _run(session, (entry,), "line:row:1:minsize", "20")
    assert window.layout is not None and window.layout.rows[0].minsize == 20
    assert _run(session, (entry,), "line:col:1:weight", None)  # reset: the line is dropped
    assert window.layout.columns == ()
    assert _run(session, (window,), "field:min_width", None)
    assert window.min_width is None
    assert _run(session, (window,), "field:modal", "true")
    assert window.modal is True
    while session.stack.can_undo:
        session.stack.undo()
    assert dump_ui(session.document) == before


def test_a_refused_value_changes_nothing() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    entry = _by_id(session, "ent_password")
    assert not _run(session, (entry,), "field:id", "lbl_username")  # a duplicate id
    assert dump_ui(session.document) == before


def test_relayout_grid_to_pack_and_back_in_reading_order() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    window = session.document.children[0]
    assert isinstance(window, Window)
    order = [c.id for c in window.children]
    assert _run(session, (window,), "layout:type", "pack")
    assert window.layout is not None and window.layout.type == "pack"
    assert [c.id for c in window.children] == order  # already row by row
    assert all(isinstance(c.placement, PackPlacement) for c in window.children)
    assert _run(session, (window,), "layout:type", "grid")
    assert [c.placement.row for c in window.children] == list(range(len(order)))  # type: ignore[union-attr]
    session.stack.undo()
    session.stack.undo()
    assert dump_ui(session.document) == before
    assert relayout_command(window, "grid").is_noop()


# ---------------------------------------------------------------- variable macros
def test_rename_variable_rebinds_and_undoes_exactly() -> None:
    session = _session()
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    built = rename_variable(document, "username", "user_name")
    assert not isinstance(built, str) and stack.execute(built).accepted
    assert "user_name" in document.variables and "username" not in document.variables
    assert _by_id(session, "ent_username").bind == "user_name"
    stack.undo()
    assert dump_ui(document) == before


@pytest.mark.parametrize("bad", ["password", "lbl_username", "class", "vars", "1abc", ""])
def test_rename_to_a_bad_id_is_refused_all_or_nothing(bad: str) -> None:
    session = _session()
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    built = rename_variable(document, "username", bad)
    if isinstance(built, str):
        assert built == "A variable called 'password' already exists."
    else:
        outcome = stack.execute(built)
        assert not outcome.accepted and outcome.message
    assert dump_ui(document) == before


def test_remove_and_unbind() -> None:
    session = _session()
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    assert [w.id for w in variable_users(document, "password")] == ["ent_password"]
    assert stack.execute(remove_and_unbind(document, "password")).accepted
    assert "password" not in document.variables
    assert _by_id(session, "ent_password").bind is None
    assert stack.undo_text == "Remove and unbind variable"
    stack.undo()
    assert dump_ui(document) == before
    added = new_variable(document)
    assert stack.execute(added).accepted and added.item.id == "var1"
    assert stack.execute(remove_and_unbind(document, "var1")).accepted


@settings(max_examples=25, suppress_health_check=[HealthCheck.too_slow], deadline=None)
@given(st.text(alphabet="abcxyz_019", min_size=1, max_size=8))
def test_rename_then_undo_is_identical(new: str) -> None:
    session = _session()
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    built = rename_variable(document, "password", new)
    if not isinstance(built, str) and stack.execute(built).changed:
        stack.undo()
    assert dump_ui(document) == before


def test_commands_are_typed_per_field() -> None:
    session = _session()
    window = session.document.children[0]  # type: ignore[union-attr]
    field = _field(session, (window,), "field:min_height")
    command = commit_commands((window,), field, "100")
    assert isinstance(command, SetField) and command.value == 100
    title = replace(_field(session, (window,), "prop:title"))
    prop = Prop(name="title", value="X", translatable=True, comment="c")
    assert isinstance(commit_commands((window,), title, prop), SetProp)
