"""Menu and window builders of Step 14a.2 (pure; spec properties-save-load 6, 7, A13)."""

from __future__ import annotations

import pytest

from pyguibud.core import (
    CommandStack,
    Document,
    Include,
    Window,
    default_registry,
    dump_ui,
    read_ui_string,
    validate,
)
from pyguibud.core.commands import SetField
from pyguibud.core.model import Action, Menu, Menubar, MenuSeparator, Statusbar
from pyguibud.designer.editing import (
    delete_window_command,
    menu_insert_command,
    menu_insert_enabled,
    new_window,
    rename_window,
    window_delete_refusal,
)

UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main">
    <menubar><menu id="file_menu"><action id="act_open"/><action id="act_quit"/></menu></menubar>
    <layout type="grid"/>
    <include id="inc" src="#" component="comp"><cell row="0" column="0"/></include>
  </window>
  <window id="bare" kind="dialog"><layout type="pack"/></window>
  <window id="comp" kind="component"><layout type="pack"/></window>
</pyguibud-ui>
"""
REG = default_registry()


@pytest.fixture
def doc() -> tuple[Document, CommandStack]:
    document = read_ui_string(UI).document
    assert validate(document, REG).ok
    return document, CommandStack(document, REG)


def find(document: Document, node_id: str) -> object:
    node = document.find(node_id)
    assert node is not None
    return node


def run(stack: CommandStack, command: object) -> None:
    """Execute, then check undo gives identical bytes, then redo."""
    before = dump_ui(stack.document)
    assert command is not None
    outcome = stack.execute(command)  # type: ignore[arg-type]
    assert outcome.accepted, outcome.message
    assert stack.undo() and dump_ui(stack.document) == before
    assert stack.redo()


# ---------------------------------------------------------------- menus
def test_insert_enabled_matrix(doc: tuple[Document, CommandStack]) -> None:
    document, _stack = doc
    main, bare = find(document, "main"), find(document, "bare")
    menu, action = find(document, "file_menu"), find(document, "act_open")
    bar = main.menubar  # type: ignore[attr-defined]
    assert not menu_insert_enabled(main, "menubar") and menu_insert_enabled(bare, "menubar")
    assert menu_insert_enabled(main, "statusbar")
    assert menu_insert_enabled(bar, "menu") and menu_insert_enabled(menu, "menu")
    assert not menu_insert_enabled(main, "menu") and not menu_insert_enabled(action, "menu")
    for kind in ("action", "separator"):
        assert menu_insert_enabled(menu, kind) and menu_insert_enabled(action, kind)
        assert not menu_insert_enabled(bar, kind) and not menu_insert_enabled(main, kind)
    assert menu_insert_command(document, main, "menubar") is None


def test_insert_bars(doc: tuple[Document, CommandStack]) -> None:
    document, stack = doc
    bare = find(document, "bare")
    assert isinstance(bare, Window)
    run(stack, menu_insert_command(document, bare, "menubar"))
    run(stack, menu_insert_command(document, bare, "statusbar"))
    assert isinstance(bare.menubar, Menubar) and isinstance(bare.statusbar, Statusbar)
    assert bare.statusbar.id == "statusbar1"


def test_insert_menu_submenu_action_and_separator(doc: tuple[Document, CommandStack]) -> None:
    document, stack = doc
    main = find(document, "main")
    assert isinstance(main, Window) and main.menubar is not None
    run(stack, menu_insert_command(document, main.menubar, "menu"))
    new_menu = main.menubar.children[-1]
    assert new_menu.id == "menu1" and new_menu.props["text"].value == "Menu"
    run(stack, menu_insert_command(document, new_menu, "menu"))  # a submenu
    assert isinstance(new_menu.children[0], Menu)
    file_menu = find(document, "file_menu")
    assert isinstance(file_menu, Menu)
    run(stack, menu_insert_command(document, find(document, "act_open"), "action"))
    run(stack, menu_insert_command(document, find(document, "act_open"), "separator"))
    run(stack, menu_insert_command(document, file_menu, "action"))
    kinds = [(type(n).__name__, getattr(n, "id", None)) for n in file_menu.children]
    assert kinds == [
        ("Action", "act_open"),
        ("MenuSeparator", None),
        ("Action", "act1"),
        ("Action", "act_quit"),
        ("Action", "act2"),
    ]
    assert isinstance(file_menu.children[1], MenuSeparator)
    assert isinstance(file_menu.children[2], Action)
    assert validate(document, REG).ok


# ---------------------------------------------------------------- windows
def test_new_window_kinds_and_one_main(doc: tuple[Document, CommandStack]) -> None:
    document, stack = doc
    run(stack, new_window(document, "dialog"))
    run(stack, new_window(document, "component"))
    assert [w.id for w in document.children][-2:] == ["dialog1", "component1"]
    before = dump_ui(document)
    outcome = stack.execute(new_window(document, "main"))
    assert not outcome.accepted and outcome.message and dump_ui(document) == before


def test_rename_window_follows_same_file_includes(doc: tuple[Document, CommandStack]) -> None:
    document, stack = doc
    comp = find(document, "comp")
    assert isinstance(comp, Window)
    command = rename_window(document, comp, "panel")
    assert command.text() == "Rename window"
    run(stack, command)
    include = find(document, "inc")
    assert isinstance(include, Include) and include.component == "panel"


@pytest.mark.parametrize("new", ["main", "class", "vars", "", "9x"])
def test_rename_window_refusal_is_all_or_nothing(
    doc: tuple[Document, CommandStack], new: str
) -> None:
    document, stack = doc
    before = dump_ui(document)
    outcome = stack.execute(rename_window(document, find(document, "comp"), new))  # type: ignore[arg-type]
    assert not outcome.accepted and outcome.message and dump_ui(document) == before


def test_window_delete_refusals(doc: tuple[Document, CommandStack]) -> None:
    document, stack = doc
    comp, bare = find(document, "comp"), find(document, "bare")
    assert isinstance(comp, Window) and isinstance(bare, Window)
    assert window_delete_refusal(document, comp) == "'comp' is still included by 'main'."
    assert delete_window_command(document, comp) == "'comp' is still included by 'main'."
    assert window_delete_refusal(document, bare) is None
    run(stack, delete_window_command(document, bare))
    lone = read_ui_string(
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<window id="w" kind="main"><layout type="grid"/></window></pyguibud-ui>'
    ).document
    assert window_delete_refusal(lone, lone.children[0]) == "A document needs at least one window."


@pytest.mark.parametrize("kind", ["menubar", "statusbar"])
def test_component_windows_get_no_bars(doc: tuple[Document, CommandStack], kind: str) -> None:
    document, stack = doc
    comp = find(document, "comp")
    assert isinstance(comp, Window) and comp.kind == "component"
    assert not menu_insert_enabled(comp, kind)  # type: ignore[arg-type]
    assert menu_insert_command(document, comp, kind) is None  # type: ignore[arg-type]
    # the guard agrees (validate.component_chrome): the rule is mirrored, not guessed
    bar = Menubar() if kind == "menubar" else Statusbar(id="sb")
    assert not stack.execute(SetField(comp, kind, bar)).accepted
    assert menu_insert_enabled(find(document, "bare"), kind)  # type: ignore[arg-type]
