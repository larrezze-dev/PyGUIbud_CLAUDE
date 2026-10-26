"""Step 14a.2 gap tests (Tk): rename dialog, F2 scopes, window stepping, tree menu, undo, budget.

Only ``event_generate`` is used; no OS-level key is ever sent. Complements
``test_structure_ui.py`` (the happy paths) without repeating it.
"""

# mypy: disable-error-code="unreachable"
from __future__ import annotations

import logging
import time
import tkinter
from collections.abc import Iterator
from typing import Any

import pytest

from pyguibud.core.commands import InsertNode, SetProp
from pyguibud.core.model import Action, GridCell, Menu, Prop, Widget
from pyguibud.core.xml_io import dump_ui, read_ui_string
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.overlay import SELECTION_CAP
from pyguibud.designer.editing import new_node, new_variable
from pyguibud.designer.shell import _flush_first, unique_mnemonics
from pyguibud.designer.theme_tk import underline_of
from tests.conftest import reset_geometry
from tests.designer.test_structure_ui import (
    _dialog,
    _document,
    _enabled,
    _invoke,
    _label_in_window,
    _sel,
    _tree,
    _vtree,
    _window,
)

pytestmark = pytest.mark.gui


@pytest.fixture
def shown(designer_root: Any) -> Iterator[Any]:
    """The root mapped and focused: key events only reach a focused window."""
    designer_root.geometry("1400x800")
    designer_root.deiconify()
    designer_root.update()
    designer_root.focus_force()
    yield designer_root
    reset_geometry(designer_root)


def _stack(app: DesignerApp) -> Any:
    assert app.session.stack is not None
    return app.session.stack


# ---------------------------------------------------------------- rename dialog
def test_rename_dialog_stays_open_with_the_reason_for_every_bad_id(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_dialog")
    target = _document(shell).children[-1]
    old, depth = target.id, _stack(shell).index
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    for bad in ("class", "vars", "9x", "", "a b", "x" * 65, _window(shell).id):
        dialog.value.set(bad)
        dialog.accept()
        assert not dialog.closed, bad
        assert dialog.reason.cget("text") and dialog.reason.winfo_manager(), bad
        assert target.id == old and _stack(shell).index == depth
        assert dialog.value.get() == bad  # the typed text is kept
    dialog.entry.event_generate("<Key>", keysym="a")  # typing again clears the old reason
    assert not dialog.reason.winfo_manager()
    dialog.close()


def test_rename_dialog_escape_cancels_and_an_unchanged_or_padded_id_records_nothing(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    shell.session.select(window, origin="tree")
    depth = _stack(shell).index
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set("elsewhere")
    dialog.window.event_generate("<Escape>")
    assert dialog.closed and window.id != "elsewhere" and _stack(shell).index == depth
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set(f"  {window.id}  ")  # padded, same id: accepted, but no step
    dialog.accept()
    assert dialog.closed and _stack(shell).index == depth
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set("  padded  ")
    dialog.accept()
    assert window.id == "padded" and _stack(shell).index == depth + 1


# ---------------------------------------------------------------- F2 scopes
def test_f2_in_the_variables_panel_renames_the_variable_and_never_a_window(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    command = new_variable(_document(shell))
    assert _stack(shell).execute(command).accepted
    panel = shell.shell.variables
    panel.frame.master.select(panel.frame)  # type: ignore[attr-defined]  # the Variables tab beside the object tree
    shown.update()
    tree = _vtree(shell)
    (row,) = tree.get_children()
    shell.session.select(_window(shell), origin="tree")  # a window is selected, too
    tree.selection_set(row)
    tree.focus(row)
    tree.focus_force()
    shown.update()
    assert shown.focus_get() is tree
    tree.event_generate("<F2>")
    shown.update()
    assert shell._live_dialogs() == []  # not the window rename ...
    assert shown.focus_get() is panel.id_entry  # ... but the keyboard moved to the id field
    panel.id_entry.event_generate("<F2>")  # and in a text field or the object tree: no rename
    _tree(shell).focus_force()
    _tree(shell).event_generate("<F2>")
    assert shell._live_dialogs() == []  # F2 is scoped to the canvas and the variables


# ---------------------------------------------------------------- window stepping
def test_window_stepping_is_disabled_with_one_window_and_noop_by_key(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    assert not _enabled(shell, "document.next") and not _enabled(shell, "document.previous")
    shell.session.select(_window(shell), origin="tree")
    shell.shell.canvas.focus_widget.focus_force()
    shown.focus_get().event_generate("<Control-Next>")
    shown.focus_get().event_generate("<Control-Prior>")
    assert _sel(shell) is _window(shell)


def test_window_stepping_from_a_widget_a_text_field_and_no_selection(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    _invoke(shell, "document.add_dialog")
    first, second = _document(shell).children
    shell.session.select(label, origin="tree")  # a widget of the first window
    _invoke(shell, "document.next")
    assert _sel(shell) is second
    _invoke(shell, "document.next")
    assert _sel(shell) is first  # wraps
    _invoke(shell, "document.previous")
    assert _sel(shell) is second  # wraps backwards
    entry = shell.shell.variables.id_entry
    entry.focus_force()
    entry.event_generate("<Control-Next>")  # a global chord: also from a text field
    assert _sel(shell) is first
    shell.session.select(None, origin="tree")
    _invoke(shell, "document.next")
    assert _sel(shell) is first  # nothing selected: starts at the first window


# ---------------------------------------------------------------- tree context menu states
def _menu_states(app: DesignerApp) -> dict[str, str]:
    app.shell.refresh_states()
    menu = app.shell.tree_menu
    return {
        menu.entrycget(i, "label"): menu.entrycget(i, "state")
        for i in range((menu.index("end") or 0) + 1)
        if menu.type(i) != "separator"
    }


def test_tree_menu_states_follow_the_selection(shell: DesignerApp, shown: Any) -> None:
    assert set(_menu_states(shell).values()) == {"disabled"}  # nothing open: nothing enabled
    label = _label_in_window(shell, shown)
    shell.session.select(label, origin="tree")
    states = _menu_states(shell)
    for item in ("Menu bar", "Menu", "Action", "Separator", "Status bar"):
        assert states[item] == "disabled", item  # a widget takes no menu nodes
    for item in ("Cut", "Copy", "Paste", "Duplicate", "Delete"):
        assert states[item] == "normal", item
    shell.session.new_from_template("main_window")
    window = _window(shell)
    assert window.menubar is not None
    shell.session.select(None, origin="tree")
    states = _menu_states(shell)
    assert states["Copy"] == "disabled" and states["Cut"] == "disabled"
    assert states["Delete"] == "disabled" and states["Duplicate"] == "disabled"
    shell.session.select(window, origin="tree")
    states = _menu_states(shell)
    assert states["Menu"] == "disabled" and states["Action"] == "disabled"
    assert states["Menu bar"] == "disabled"  # the template window already has one
    assert states["Delete"] == "disabled"  # a window goes through Document ▸ Delete window
    assert states["Copy"] == "normal" and states["Paste"] == "normal"
    shell.session.select(window.menubar, origin="tree")
    states = _menu_states(shell)
    assert states["Menu"] == "normal" and states["Action"] == "disabled"
    assert states["Separator"] == "disabled" and states["Delete"] == "normal"
    menu: Any = window.menubar.children[0]
    shell.session.select(menu, origin="tree")
    states = _menu_states(shell)
    assert states["Menu"] == states["Action"] == states["Separator"] == "normal"
    assert states["Menu bar"] == states["Status bar"] == "disabled"
    shell.session.select(menu.children[0], origin="tree")
    states = _menu_states(shell)
    assert states["Action"] == states["Separator"] == "normal" and states["Menu"] == "disabled"


def test_right_click_selects_the_row_under_the_pointer_before_the_menu_opens(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    tree = _tree(shell)
    shown.update()
    row = next(k for k in tree.get_children(tree.get_children()[0]) if k)
    popped: list[tuple[int, int]] = []
    shell.shell.tree.popup = lambda x, y: popped.append((x, y))
    x, y, _w, h = tree.bbox(row)
    tree.event_generate("<Button-3>", x=x + 4, y=y + h // 2)
    assert popped and shell.session.selection.node is not None
    assert label.parent is not None


# ---------------------------------------------------------------- delete on menus
def test_delete_of_a_menu_with_items_can_be_cancelled_and_an_empty_one_goes_at_once(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    assert window.menubar is not None
    menu: Any = window.menubar.children[0]
    assert menu.children
    shell.session.select(menu, origin="tree")
    before, depth = dump_ui(_document(shell)), _stack(shell).index
    _invoke(shell, "edit.delete")
    dialog = _dialog(shell)
    dialog.close()  # Cancel
    assert menu.parent is not None and dump_ui(_document(shell)) == before
    assert _stack(shell).index == depth
    _invoke(shell, "edit.delete")
    _dialog(shell).confirm()
    assert menu.parent is None and _stack(shell).index == depth + 1
    shell.registry.invoke("edit.undo")
    assert dump_ui(_document(shell)) == before
    for child in list(menu.children):  # now empty: no question
        shell.session.select(child, origin="tree")
        _invoke(shell, "edit.delete")
    shell.session.select(menu, origin="tree")
    _invoke(shell, "edit.delete")
    assert shell._live_dialogs() == [] and menu.parent is None


# ---------------------------------------------------------------- one undo step per action
def test_every_new_action_is_exactly_one_undo_step_and_redoes_identically(
    shell: DesignerApp, designer_root: Any
) -> None:
    shown = designer_root
    label = _label_in_window(shell, shown)
    app, stack = shell, _stack(shell)
    window = _window(app)

    def step(label_: str, act: Any) -> None:
        before, depth = dump_ui(_document(app)), stack.index
        act()
        shown.update()
        assert stack.index == depth + 1, label_
        after = dump_ui(_document(app))
        assert after != before, label_
        app.registry.invoke("edit.undo")
        assert stack.index == depth and dump_ui(_document(app)) == before, label_
        app.registry.invoke("edit.redo")
        assert stack.index == depth + 1 and dump_ui(_document(app)) == after, label_

    step("add dialog", lambda: _invoke(app, "document.add_dialog"))
    step("add component", lambda: _invoke(app, "document.add_component"))

    def select(node: object) -> None:
        app.session.select(node, origin="tree")

    select(_document(app).children[-1])

    def rename() -> None:
        _invoke(app, "document.rename")
        _rename(app, "renamed")

    def delete_window() -> None:
        _invoke(app, "document.delete")
        _dialog(app).confirm()

    step("rename", rename)
    select(_document(app).children[-1])
    step("delete window", delete_window)
    select(label)
    step("duplicate", lambda: _invoke(app, "edit.duplicate"))
    select(label)
    _invoke(app, "edit.copy")
    select(window)
    step("paste", lambda: _invoke(app, "edit.paste"))
    select(label)
    step("cut", lambda: _invoke(app, "edit.cut"))
    select(_document(app).children[-1])
    shown.update()
    step("insert menubar", lambda: _invoke(app, "edit.insert.menubar"))
    window2 = _document(app).children[-1]
    select(window2)
    step("insert statusbar", lambda: _invoke(app, "edit.insert.statusbar"))
    select(window2.menubar)
    step("insert menu", lambda: _invoke(app, "edit.insert.menu"))
    menu = window2.menubar.children[-1]
    assert isinstance(menu, Menu)
    select(menu)
    step("insert action", lambda: _invoke(app, "edit.insert.action"))
    action = menu.children[-1]
    assert isinstance(action, Action)
    select(action)
    step("insert separator", lambda: _invoke(app, "edit.insert.separator"))
    select(action)
    step("delete action", lambda: _invoke(app, "edit.delete"))


def _rename(app: DesignerApp, name: str) -> None:
    dialog = _dialog(app)
    dialog.value.set(name)
    dialog.accept()


# ---------------------------------------------------------------- held keys
def test_a_held_ctrl_x_cuts_once_and_does_not_climb_the_tree(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    _invoke(shell, "document.add_dialog")  # a second window: the first is not the last one
    first = _document(shell).children[0]
    shell.shell.canvas.show_window(first)  # a canvas click needs the label's tab on show
    shell.session.select(label, origin="canvas")
    depth = _stack(shell).index
    try:
        for _ in range(4):  # auto-repeat of one physical press: the same key, no release
            proxy = shell.shell.canvas.focus_widget  # the canvas may be rebuilt in between
            proxy.focus_force()
            proxy.event_generate("<Control-x>")
    except tkinter.TclError:
        pass  # the repeat removed the window, and its canvas tab with it
    assert _stack(shell).index == depth + 1, "a held Ctrl+X must act once per physical press"
    assert first.parent is not None and label.parent is None


# ---------------------------------------------------------------- budget
def test_pasting_widgets_through_the_ui_stays_inside_the_500_widget_budget(
    shell: DesignerApp, shown: Any
) -> None:
    """Spec 17: 500 widgets in 1.5 s. 100 used to take 2.8 s (and 500 about 45 s): every
    outline strip was lifted on every redraw, and every selected widget was outlined."""
    shell.session.new_from_template("main_window")
    window = _window(shell)
    count = 100
    widgets = "".join(f'<widget class="Label" id="w{k}"><pack/></widget>' for k in range(count))
    text = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" '
        'xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="widgets">'
        f'<window id="c" kind="component"><layout type="pack"/>{widgets}</window></pyguibud-ui>'
    )
    shown.clipboard_clear()
    shown.clipboard_append(text)
    shell.session.select(window, origin="tree")
    started = time.perf_counter()
    _invoke(shell, "edit.paste")
    shown.update()
    elapsed = time.perf_counter() - started
    assert len([w for w in window.children if isinstance(w, Widget)]) == count
    assert elapsed <= 1.5, f"paste of {count} widgets took {elapsed:.2f}s (budget 1.5s for 500)"


def test_a_large_selection_outlines_the_primary_and_a_capped_number_and_says_so(
    shell: DesignerApp, shown: Any
) -> None:
    """Each outline is 8 native windows: past SELECTION_CAP others, the canvas outlines only
    the primary and the first SELECTION_CAP, and the status bar gives the real count."""
    shell.session.new_from_template("main_window")
    window = _window(shell)
    registry, document = shell.session.registry, _document(shell)
    count = SELECTION_CAP + 5
    for row in range(count):
        node = new_node(registry.require("Label"), document)
        assert isinstance(node, Widget)
        node.placement = GridCell(row=row, column=0)
        assert _stack(shell).execute(InsertNode(window, node)).accepted
    shown.update()
    labels = [w for w in window.children if isinstance(w, Widget)]
    shell.session.select(labels[0], origin="canvas")
    shell.shell.clear_message()
    _invoke(shell, "edit.select_all")
    shown.update()
    assert len(shell.session.selection.nodes) == count
    stage = shell.shell.canvas.stage_of(window)
    assert stage is not None
    overlay = stage.overlay
    assert len(overlay.selection.shown()) == 8 * (SELECTION_CAP + 1)
    assert overlay.primary is not None  # the primary is always outlined (here: the first)
    message = shell.shell._message
    assert str(count) in message and str(SELECTION_CAP + 1) in message
    shell.session.select_many(labels[:3], origin="canvas")  # under the cap: all, no message
    shell.shell.clear_message()
    shell.session.select_many(labels[:4], origin="canvas")
    shown.update()
    assert len(overlay.selection.shown()) == 8 * 4 and shell.shell._message == ""
    shell.session.select(window, origin="canvas")
    shown.update()
    assert len(overlay.selection.shown()) == 8


# ---------------------------------------------------------------- overlay stacking
def test_overlay_strips_stay_above_a_rebuilt_window_and_in_layer_order(
    shell: DesignerApp, shown: Any
) -> None:
    """The strips are stacked once, when created (a lift per strip per draw was quadratic):
    a rebuilt window frame goes beneath them, and new strips go under the layers above."""
    label = _label_in_window(shell, shown)
    window, registry, document = _window(shell), shell.session.registry, _document(shell)
    for row, class_name in ((1, "Frame"), (2, "Label")):  # an empty container, another label
        node = new_node(registry.require(class_name), document)
        assert isinstance(node, Widget)
        node.placement = GridCell(row=row, column=0)
        assert _stack(shell).execute(InsertNode(window, node)).accepted
    other = window.children[-1]
    shell.session.select(label, origin="tree")  # a grid child: outline and handles
    shown.update()
    # An edit rebuilds the window: its new frame is created above every existing strip.
    assert _stack(shell).execute(SetProp(label, Prop(name="text", value="Moved"))).accepted
    shown.update()
    shell.session.select_many([other, label], origin="tree")  # the selection pool grows
    shown.update()
    stage = shell.shell.canvas.stage_of(window)
    assert stage is not None and stage.view is not None
    order = [str(w) for w in stage.stage.winfo_children()]  # lowest first

    def places(widgets: list[Any]) -> list[int]:
        return [order.index(str(w)) for w in widgets]

    overlay = stage.overlay
    empty, selection = places(overlay.empty.shown()), places(overlay.selection.shown())
    handles = places(overlay.handles.shown())
    assert empty and len(selection) == 16 and handles
    frame = order.index(str(stage.view.frame))
    assert frame < min(empty) and max(empty) < min(selection) and max(selection) < min(handles)


@pytest.fixture
def failures(designer_root: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every Tk callback exception: a failed ``<<NotebookTabChanged>>`` handler only reaches
    stderr, never the log (``_no_failures`` adds the logged ERRORs, a failed signal slot)."""
    caught: list[str] = []
    monkeypatch.setattr(
        designer_root,
        "report_callback_exception",
        lambda _kind, value, _tb: caught.append(f"Tk callback: {value!r}"),
    )
    yield caught


def _no_failures(failures: list[str], caplog: pytest.LogCaptureFixture) -> None:
    found = failures + [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not found, found


def test_deleting_a_window_raises_no_slot_error(
    shell: DesignerApp,
    designer_root: Any,
    failures: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The delete selects a kept window while the canvas re-render is still scheduled: the
    stage built for it must not be destroyed by that re-render (re-entrancy, 14a.2)."""
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_dialog")
    designer_root.update()
    shell.session.select(_document(shell).children[-1], origin="tree")
    designer_root.update()
    _invoke(shell, "document.delete")
    _dialog(shell).confirm()
    designer_root.update()
    _no_failures(failures, caplog)
    (window,) = _document(shell).children
    assert [s.window for s in shell.shell.canvas.stages] == [window]
    stage = shell.shell.canvas.stage_of(window)
    assert stage is not None and stage.view is not None and not stage.stale


def test_cutting_a_widget_or_a_window_raises_no_slot_error(
    shell: DesignerApp,
    designer_root: Any,
    failures: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A cut selects the parent window (or the first kept window) while the canvas rebuild is
    still scheduled: neither the build nor the outline may meet a destroyed stage."""
    label = _label_in_window(shell, designer_root)
    _invoke(shell, "document.add_dialog")
    designer_root.update()
    first, second = _document(shell).children
    shell.session.select(label, origin="tree")  # shows the label's tab
    designer_root.update()
    _invoke(shell, "edit.cut")  # the selection moves to the parent window
    assert _sel(shell) is first and label.parent is None
    designer_root.update()
    shell.session.select(second, origin="tree")
    designer_root.update()
    assert not shell.shell._invoke("edit.cut")  # a window is not cut (H43, Step 19c) ...
    assert second.parent is not None and _sel(shell) is second  # ... and nothing changes
    designer_root.update()
    _no_failures(failures, caplog)
    assert [s.window for s in shell.shell.canvas.stages] == [first, second]
    stage = shell.shell.canvas.stage_of(first)
    assert stage is not None and stage.view is not None and not stage.stale


# ---------------------------------------------------------------- QA 14a.2 (debugger)
def _labelled(app: DesignerApp, root: Any) -> tuple[Widget, Any]:
    label = _label_in_window(app, root)
    app.session.select(label, origin="tree")
    root.update()
    return label, app.shell.inspector._editors["prop:width"]


def test_qa02_every_editing_action_commits_the_pending_text_first() -> None:
    for action in (
        "edit.paste",
        "edit.delete",
        "edit.insert.menubar",
        "edit.insert.action",
        "document.add_main",
        "document.add_dialog",
        "document.add_component",
        "document.rename",
        "document.delete",
    ):
        assert _flush_first(action), action
    assert not _flush_first("document.next") and not _flush_first("view.next_panel")


def test_qa02_a_valid_pending_value_is_its_own_step_before_the_delete(
    shell: DesignerApp, designer_root: Any
) -> None:
    label, editor = _labelled(shell, designer_root)
    depth = _stack(shell).index
    editor.var.set("17")  # typed, not yet committed
    _invoke(shell, "edit.delete")
    designer_root.update()
    assert label.parent is None and _stack(shell).index == depth + 2
    shell.registry.invoke("edit.undo")  # the delete first ...
    assert label.parent is not None and label.props["width"].value == "17"
    shell.registry.invoke("edit.undo")  # ... then the typed value
    assert "width" not in label.props


def test_qa02_a_refused_pending_value_stops_the_action_with_its_reason(
    shell: DesignerApp, designer_root: Any
) -> None:
    label, editor = _labelled(shell, designer_root)
    for action in ("edit.paste", "edit.delete", "edit.duplicate", "document.add_dialog"):
        depth, windows = _stack(shell).index, len(_document(shell).children)
        editor.var.set("999999999999")
        shell.shell.clear_message()
        assert shell.shell._invoke(action), action
        designer_root.update()
        assert _stack(shell).index == depth and len(_document(shell).children) == windows
        assert label.parent is not None and shell.shell._message, action
        assert shell._live_dialogs() == []


def test_qa03_unique_mnemonics_keep_free_keys_and_move_clashes() -> None:
    entries = [("Separator", 0), ("Paste", 2), ("Status bar", 7), ("Cut", 2), ("--", -1)]
    assert unique_mnemonics(entries) == [0, 0, 7, 2, -1]
    assert unique_mnemonics([("Menu", 0), ("Eliminar", 0)]) == [0, 0]  # no clash: unchanged
    assert unique_mnemonics([("Menu", 1), ("Eliminar", 0)]) == [1, 1]  # es_ES: the E moves


def test_qa03_the_tree_menu_has_one_access_key_per_entry_in_every_locale(
    shell: DesignerApp, designer_root: Any
) -> None:
    menu = shell.shell.tree_menu
    try:
        for code in ("en_GB", "es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR"):
            shell.set_language(code)
            designer_root.update()
            keys: list[str] = []
            for index in range((menu.index("end") or 0) + 1):
                if menu.type(index) == "separator":
                    continue
                label, underline = (
                    menu.entrycget(index, "label"),
                    underline_of(menu.entrycget(index, "underline")),
                )
                if 0 <= underline < len(label):
                    keys.append(label[underline].lower())
            assert len(keys) == len(set(keys)), (code, keys)
            assert len(keys) >= 9, code  # every entry keeps an access key
    finally:
        shell.set_language("en_GB")


def test_qa04_deleting_a_menu_bar_names_it(shell: DesignerApp, designer_root: Any) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    assert window.menubar is not None and window.menubar.children
    edit = shell.registry.get("edit.delete").handler.__self__  # type: ignore[union-attr]
    asked: list[str] = []
    edit._confirm = lambda question, _then: asked.append(question)
    shell.session.select(window.menubar, origin="tree")
    _invoke(shell, "edit.delete")
    assert len(asked) == 1 and asked[0].startswith("Delete 'Menu bar' and its "), asked


_NEWER = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.7" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main">
    <menubar><menu id="file_menu"><action id="act_quit"/></menu></menubar>
    <layout type="pack"/>
    <widget class="Frame" id="frm"><pack/><layout type="pack"/>
      <widget class="Label" id="lbl"><pack/></widget></widget>
  </window>
  <window id="comp" kind="component"><layout type="pack"/></window>
</pyguibud-ui>
"""


def test_qa05_a_read_only_document_copies_and_refuses_edits_before_any_question(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.open_result(read_ui_string(_NEWER, source="newer"), name="newer")
    designer_root.update()
    stack = _stack(shell)
    assert stack.read_only
    ids = [getattr(n, "id", None) for n in _document(shell).walk()]
    asked: list[str] = []
    for owner in ("edit.delete", "document.delete"):
        handler: Any = shell.registry.get(owner).handler  # type: ignore[union-attr]
        handler.__self__._confirm = lambda question, _then: asked.append(question)
    designer_root.clipboard_clear()
    designer_root.clipboard_append("nothing")
    for selected, action in (
        ("lbl", "edit.copy"),
        ("lbl", "edit.cut"),
        ("frm", "edit.delete"),
        ("lbl", "edit.duplicate"),
        ("frm", "edit.paste"),
        ("file_menu", "edit.insert.action"),
        ("main", "edit.insert.statusbar"),
        ("main", "document.add_dialog"),
        ("comp", "document.rename"),
        ("comp", "document.delete"),
    ):
        shell.session.select(_document(shell).find(selected), origin="tree")
        designer_root.update()
        shell.shell.clear_message()
        ran = shell.shell._invoke(action)
        designer_root.update()
        assert asked == [] and shell._live_dialogs() == [], action
        if action == "edit.copy":
            assert ran and designer_root.clipboard_get().startswith("<?xml")
            assert shell.shell._message == ""
        else:  # greyed out (N3); a shortcut says why
            refusal = shell.registry.get(action).refusal  # type: ignore[union-attr]
            assert not ran and not _enabled(shell, action), action
            assert refusal is not None and str(refusal()).startswith("This document is read-only")
    assert [getattr(n, "id", None) for n in _document(shell).walk()] == ids
    assert stack.index == 0


# ---------------------------------------------------------------- QA-14a2-10, N1 (debugger)
_INCLUDED_UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main"><layout type="pack"/>
    <include id="inc" src="#" component="comp"><pack/></include>
    <include id="dangling" src="#" component="ghost"><pack/></include>
  </window>
  <window id="comp" kind="component"><layout type="pack"/>
    <widget class="Label" id="lbl"><pack/></widget>
  </window>
</pyguibud-ui>
"""


def test_qa10_the_inspector_id_renames_a_component_and_its_includes(
    shell: DesignerApp, designer_root: Any, tmp_path: Any
) -> None:
    from pyguibud.uic import main as uic_main

    good = _INCLUDED_UI.replace(
        '\n    <include id="dangling" src="#" component="ghost"><pack/></include>', ""
    )
    shell.session.open_result(read_ui_string(good, source="inc"), name="inc")
    designer_root.update()
    document, stack = _document(shell), _stack(shell)
    comp, include = document.find("comp"), document.find("inc")
    before, depth = dump_ui(document), stack.index
    shell.session.select(comp, origin="tree")
    designer_root.update()
    editor: Any = shell.shell.inspector._editors["field:id"]
    editor.var.set("card")
    editor._enter()
    designer_root.update()
    assert comp.id == "card" and include.component == "card"  # the include follows
    assert stack.index == depth + 1  # one undo step
    assert (
        shell.shell._message == "Files that include this component from outside were not updated."
    )
    path = tmp_path / "renamed.ui"
    path.write_bytes(dump_ui(document))
    assert uic_main(["--check", str(path)]) == 0
    shell.registry.invoke("edit.undo")
    assert dump_ui(document) == before


def test_qa10_the_inspector_refuses_a_kind_or_component_that_breaks_an_include(
    shell: DesignerApp, designer_root: Any
) -> None:
    good = _INCLUDED_UI.replace(
        '\n    <include id="dangling" src="#" component="ghost"><pack/></include>', ""
    )
    shell.session.open_result(read_ui_string(good, source="inc"), name="inc")
    designer_root.update()
    document, stack = _document(shell), _stack(shell)
    before = dump_ui(document)
    shell.session.select(document.find("inc"), origin="tree")
    designer_root.update()
    for value in ("main", "ghost"):
        editor: Any = shell.shell.inspector._editors["field:component"]
        editor.var.set(value)
        editor._enter()
        designer_root.update()
        assert dump_ui(document) == before and stack.index == 0, value
        assert "component" in shell.shell._message, shell.shell._message
        editor.var.set("comp")  # back to the stored value: nothing pending
        editor._enter()


def test_n1_renaming_a_window_into_a_dangling_include_cycle_is_refused(
    shell: DesignerApp, designer_root: Any
) -> None:
    text = _INCLUDED_UI.replace(
        '<widget class="Label" id="lbl"><pack/></widget>',
        '<widget class="Label" id="lbl"><pack/></widget>'
        '<include id="inner" src="#" component="ghost"><pack/></include>',
    )
    shell.session.open_result(read_ui_string(text, source="dangling"), name="dangling")
    designer_root.update()
    document, stack = _document(shell), _stack(shell)
    before = dump_ui(document)
    shell.session.select(document.find("comp"), origin="tree")
    designer_root.update()
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set("ghost")  # comp would include itself through 'inner'
    dialog.accept()
    assert not dialog.closed and "creates a cycle" in dialog.reason.cget("text")
    dialog.close()
    assert dump_ui(document) == before and stack.index == 0


def test_n5_a_refused_kind_pick_shows_the_model_value_again(
    shell: DesignerApp, designer_root: Any
) -> None:
    dangling = '<include id="dangling" src="#" component="ghost"><pack/></include>'
    good = _INCLUDED_UI.replace(dangling, "")
    shell.session.open_result(read_ui_string(good, source="inc"), name="inc")
    designer_root.update()
    comp = _document(shell).find("comp")
    shell.session.select(comp, origin="tree")
    designer_root.update()
    editor: Any = shell.shell.inspector._editors["field:kind"]
    assert editor.var.get() == "component"
    editor.widget.set("dialog")  # the pick the guard refuses: main still includes it
    editor._picked()
    designer_root.update()
    assert comp.kind == "component" and _stack(shell).index == 0
    assert editor.var.get() == "component"  # not the refused "dialog"
    assert "not a component" in shell.shell._message  # the reason stays in the status bar
