"""Step 14a.2 UI: Edit > Insert, menu deletion, the Document menu and the clipboard keys (Tk)."""

# mypy: disable-error-code="unreachable"
from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from pyguibud.core.commands import InsertNode
from pyguibud.core.model import (
    Action,
    GridCell,
    Menu,
    Menubar,
    MenuSeparator,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.editing import M_EXTERNAL_INCLUDES, new_node
from tests.conftest import reset_geometry

pytestmark = pytest.mark.gui
# The tests assert a state, undo, and assert the opposite: mypy would call that unreachable.


@pytest.fixture
def shown(designer_root: Any) -> Iterator[Any]:
    """The root mapped and focused: key events only reach a focused window."""
    designer_root.geometry("1400x800")
    designer_root.deiconify()
    designer_root.update()
    designer_root.focus_force()
    yield designer_root
    reset_geometry(designer_root)


def _document(app: DesignerApp) -> Any:
    assert app.session.document is not None
    return app.session.document


def _window(app: DesignerApp) -> Any:
    window = _document(app).children[0]
    assert isinstance(window, Window)
    return window


def _sel(app: DesignerApp) -> Any:
    """The primary selected node (untyped: the tests compare it by identity)."""
    return app.session.selection.node


def _tree(app: DesignerApp) -> Any:
    tree = app.shell.tree.tree
    assert tree is not None
    return tree


def _vtree(app: DesignerApp) -> Any:
    tree = app.shell.variables.tree
    assert tree is not None
    return tree


def _dialog(app: DesignerApp) -> Any:
    (dialog,) = app._live_dialogs()
    return dialog


def _label_in_window(app: DesignerApp, root: Any) -> Widget:
    """A form with one Label in the main window of the template."""
    app.session.new_from_template("main_window")
    assert app.session.stack is not None
    label = new_node(app.session.registry.require("Label"), _document(app))
    assert isinstance(label, Widget)
    label.placement = GridCell(row=0, column=0)
    assert app.session.stack.execute(InsertNode(_window(app), label)).accepted
    root.update()
    return label


def _invoke(app: DesignerApp, action_id: str) -> None:
    app.shell.clear_message()
    assert app.shell._invoke(action_id), action_id


def _enabled(app: DesignerApp, action_id: str) -> bool:
    action = app.registry.get(action_id)
    assert action is not None
    return app.registry.is_enabled(action)


# ---------------------------------------------------------------- Edit > Insert
def test_insert_builds_a_menu_bar_menus_actions_separators_and_a_submenu(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_component")
    component = _document(shell).children[-1]
    shell.session.select(component, origin="tree")
    # a component has no chrome (validate.component_chrome): both items are greyed out
    assert not _enabled(shell, "edit.insert.menubar")
    assert not _enabled(shell, "edit.insert.statusbar")
    assert not shell.shell._invoke("edit.insert.menubar") and component.menubar is None
    _invoke(shell, "document.add_dialog")
    window = _document(shell).children[-1]
    shell.session.select(window, origin="tree")
    assert [_enabled(shell, f"edit.insert.{k}") for k in ("menubar", "menu", "action")] == [
        True,
        False,
        False,
    ]
    _invoke(shell, "edit.insert.menubar")
    assert isinstance(window.menubar, Menubar) and _sel(shell) is window.menubar
    assert not _enabled(shell, "edit.insert.menubar")  # one menu bar per window
    _invoke(shell, "edit.insert.menu")
    menu = _sel(shell)
    assert isinstance(menu, Menu) and window.menubar.children[0] is menu
    _invoke(shell, "edit.insert.menu")  # a menu in a menu is a submenu
    submenu = _sel(shell)
    assert isinstance(submenu, Menu) and menu.children[0] is submenu
    shell.session.select(menu, origin="tree")
    _invoke(shell, "edit.insert.action")
    action = _sel(shell)
    assert isinstance(action, Action) and menu.children[-1] is action
    _invoke(shell, "edit.insert.separator")  # after the selected action
    kids: Any = menu.children
    assert isinstance(kids[-1], MenuSeparator) and kids[-2] is action
    assert isinstance(_sel(shell), MenuSeparator)
    shell.session.select(window, origin="tree")
    _invoke(shell, "edit.insert.statusbar")
    assert isinstance(window.statusbar, Statusbar)
    assert _sel(shell) is window.statusbar
    assert not _enabled(shell, "edit.insert.statusbar")
    for _ in range(7):  # every insert was one undo step
        shell.registry.invoke("edit.undo")
    assert window.menubar is None and window.statusbar is None


def test_insert_is_disabled_for_a_widget_and_without_a_document(
    shell: DesignerApp, designer_root: Any
) -> None:
    assert not any(_enabled(shell, f"edit.insert.{k}") for k in ("menubar", "menu", "action"))
    label = _label_in_window(shell, designer_root)
    shell.session.select(label, origin="tree")
    assert not any(
        _enabled(shell, f"edit.insert.{k}")
        for k in ("menubar", "menu", "action", "separator", "statusbar")
    )


# ---------------------------------------------------------------- delete of menu nodes
def test_delete_removes_menu_nodes_and_a_menu_with_items_asks_first(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    assert window.menubar is not None and window.statusbar is not None
    menu: Any = window.menubar.children[0]
    item = menu.children[0]
    shell.session.select(item, origin="tree")
    assert _enabled(shell, "edit.delete")
    _invoke(shell, "edit.delete")
    assert item not in menu.children and _sel(shell) is menu
    shell.registry.invoke("edit.undo")
    assert item in menu.children
    shell.session.select(menu, origin="tree")  # a menu with items asks first
    _invoke(shell, "edit.delete")
    dialog = _dialog(shell)
    assert menu.parent is not None
    dialog.confirm()
    assert menu.parent is None
    shell.registry.invoke("edit.undo")
    assert menu.parent is not None
    shell.session.select(window.statusbar, origin="tree")  # a bar is a field of its window
    _invoke(shell, "edit.delete")
    assert window.statusbar is None and _sel(shell) is window
    shell.registry.invoke("edit.undo")
    assert window.statusbar is not None
    shell.session.select(window.menubar, origin="tree")
    _invoke(shell, "edit.delete")
    dialog = _dialog(shell)
    dialog.confirm()
    assert window.menubar is None


def test_delete_still_refuses_a_window_and_says_where_to_delete_it(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    shell.session.select(_window(shell), origin="tree")
    assert not _enabled(shell, "edit.delete")
    _tree(shell).focus_force()
    _tree(shell).event_generate("<Delete>")
    assert shell.shell._message == "Windows are deleted with Document > Delete window."
    assert _document(shell).children


# ---------------------------------------------------------------- the Document menu
def _window_by_kind(app: DesignerApp, kind: str) -> Any:
    return next(w for w in _document(app).children if w.kind == kind)


def test_add_windows_selects_them_and_a_second_main_window_is_refused(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_dialog")
    dialog = _document(shell).children[-1]
    assert dialog.kind == "dialog" and _sel(shell) is dialog
    _invoke(shell, "document.add_component")
    assert [w.kind for w in _document(shell).children] == ["main", "dialog", "component"]
    count = len(_document(shell).children)
    _invoke(shell, "document.add_main")
    assert len(_document(shell).children) == count
    assert shell.shell._message  # the guard's reason: one main window per file


def test_rename_window_judges_the_id_inside_the_dialog(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_component")
    component = _window_by_kind(shell, "component")
    main = _window(shell)
    shell.session.select(component, origin="tree")
    old = component.id
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set(main.id)
    dialog.accept()
    assert not dialog.closed and component.id == old  # kept open, nothing changed
    assert dialog.reason.cget("text")
    dialog.value.set("panel")
    dialog.accept()
    assert dialog.closed and component.id == "panel"
    assert shell.shell._message == M_EXTERNAL_INCLUDES
    shell.registry.invoke("edit.undo")
    assert component.id == old
    shell.session.select(main, origin="tree")  # a dialog or main window warns about nothing
    _invoke(shell, "document.rename")
    dialog = _dialog(shell)
    dialog.value.set("shell")
    dialog.accept()
    assert main.id == "shell" and shell.shell._message == ""


def test_f2_renames_a_window_on_the_canvas_only(shell: DesignerApp, shown: Any) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    shell.session.select(window, origin="tree")
    proxy = shell.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate("<F2>")
    assert len(shell._live_dialogs()) == 1
    shell._live_dialogs()[0].close()
    shell.session.select(window, origin="tree")
    _vtree(shell).focus_force()  # F2 there is the variable rename
    _vtree(shell).event_generate("<F2>")
    assert shell._live_dialogs() == []


def test_delete_window_confirms_and_the_last_window_is_refused(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_dialog")
    extra = _document(shell).children[-1]
    _invoke(shell, "document.delete")
    dialog = _dialog(shell)
    dialog.close()
    assert extra.parent is not None
    _invoke(shell, "document.delete")
    dialog = _dialog(shell)
    dialog.confirm()
    assert extra.parent is None and _sel(shell) is _window(shell)
    _invoke(shell, "document.delete")  # now the last one
    assert shell._live_dialogs() == []
    assert shell.shell._message == "A document needs at least one window."
    shell.registry.invoke("edit.undo")
    assert extra.parent is not None


def test_ctrl_pagedown_and_pageup_switch_the_window_tab(shell: DesignerApp, shown: Any) -> None:
    shell.session.new_from_template("main_window")
    _invoke(shell, "document.add_dialog")
    first, second = _document(shell).children
    assert _sel(shell) is second
    assert _enabled(shell, "document.next")
    shell.shell.canvas.focus_widget.focus_force()
    shown.focus_get().event_generate("<Control-Next>")
    assert _sel(shell) is first  # wraps around
    shown.focus_get().event_generate("<Control-Prior>")
    assert _sel(shell) is second
    _tree(shell).focus_force()  # global: also from the tree
    _tree(shell).event_generate("<Control-Next>")
    assert _sel(shell) is first


# ---------------------------------------------------------------- copy, cut, paste, duplicate
def test_copy_then_paste_round_trips_through_the_tk_clipboard(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    window = _window(shell)
    shell.session.select(label, origin="canvas")
    proxy = shell.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate("<Control-c>")
    assert "clip:mode" in shown.clipboard_get()  # the .ui text, readable by any program
    shell.session.select(window, origin="canvas")
    proxy.event_generate("<Control-v>")
    labels = [w for w in window.children if isinstance(w, Widget)]
    assert len(labels) == 2 and _sel(shell) is labels[1]
    assert labels[1].id != label.id  # the id was remapped
    assert shell.shell._message == "Pasted 1 element."
    shell.registry.invoke("edit.undo")
    assert len([w for w in window.children if isinstance(w, Widget)]) == 1


def test_cut_removes_and_puts_the_text_on_the_clipboard(shell: DesignerApp, shown: Any) -> None:
    label = _label_in_window(shell, shown)
    shown.clipboard_clear()
    shell.session.select(label, origin="tree")
    tree = _tree(shell)
    tree.focus_force()
    tree.event_generate("<Control-x>")
    assert label.parent is None and "clip:mode" in shown.clipboard_get()
    assert _sel(shell) is _window(shell)
    tree.event_generate("<Control-v>")  # the window is selected: into its body
    assert any(isinstance(w, Widget) for w in _window(shell).children)


def test_duplicate_inserts_after_the_original_without_the_clipboard(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    shown.clipboard_clear()
    shown.clipboard_append("keep me")
    shell.session.select(label, origin="canvas")
    proxy = shell.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate("<Control-d>")
    labels = [w for w in _window(shell).children if isinstance(w, Widget)]
    assert len(labels) == 2 and labels[0] is label
    assert shown.clipboard_get() == "keep me"


def test_paste_of_foreign_text_and_an_empty_clipboard_say_so(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    shell.session.select(label, origin="canvas")
    proxy = shell.shell.canvas.focus_widget
    proxy.focus_force()
    stack = shell.session.stack
    assert stack is not None
    depth = stack.index
    for text in ("just some words", ""):
        shown.clipboard_clear()
        if text:
            shown.clipboard_append(text)
        shell.shell.clear_message()
        proxy.event_generate("<Control-v>")
        proxy.event_generate("<KeyRelease-v>")  # a new physical press next time
        assert shell.shell._message == "The clipboard holds no PyGUIbud elements."
        assert stack.index == depth


def test_ctrl_c_and_ctrl_v_in_an_entry_keep_their_text_meaning(
    shell: DesignerApp, shown: Any
) -> None:
    label = _label_in_window(shell, shown)
    shell.session.select(label, origin="canvas")
    shown.clipboard_clear()
    shown.clipboard_append("sentinel")
    entry = shell.shell.variables.id_entry
    entry.focus_force()
    stack = shell.session.stack
    assert stack is not None
    depth = stack.index
    entry.event_generate("<Control-c>")
    entry.event_generate("<Control-v>")
    entry.event_generate("<Control-d>")
    assert shown.clipboard_get() == "sentinel"  # no widgets were copied
    assert stack.index == depth  # and nothing was pasted or duplicated


def test_a_held_ctrl_v_pastes_once_per_physical_press(shell: DesignerApp, shown: Any) -> None:
    label = _label_in_window(shell, shown)
    shell.session.select(label, origin="canvas")
    proxy = shell.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate("<Control-c>")
    window = _window(shell)

    def count() -> int:
        return len([w for w in window.children if isinstance(w, Widget)])

    for _ in range(3):  # auto-repeat: presses without a release
        proxy.event_generate("<Control-v>")
    assert count() == 2
    proxy.event_generate("<KeyRelease-v>")
    proxy.event_generate("<Control-v>")
    assert count() == 3
    proxy.event_generate("<KeyRelease-v>")
    shell.session.select(label, origin="canvas")
    for _ in range(3):  # a held Ctrl+D duplicates once as well
        proxy.event_generate("<Control-d>")
    assert count() == 4


def test_copy_of_a_menu_explains_and_the_tree_menu_offers_insert(
    shell: DesignerApp, shown: Any
) -> None:
    shell.session.new_from_template("main_window")
    window = _window(shell)
    assert window.menubar is not None
    shell.session.select(window.menubar.children[0], origin="tree")
    shell.shell.clear_message()
    _invoke(shell, "edit.copy")
    assert shell.shell._message == "Menus and actions cannot be copied yet."
    menu = shell.shell.tree_menu
    labels = [
        menu.entrycget(i, "label")
        for i in range((menu.index("end") or 0) + 1)
        if menu.type(i) != "separator"
    ]
    assert labels[:5] == ["Menu bar", "Menu", "Action", "Separator", "Status bar"]
    assert "Paste" in labels and "Delete" in labels
