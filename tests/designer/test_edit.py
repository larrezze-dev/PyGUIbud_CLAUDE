"""Edit actions (undo, redo, delete), scoped shortcuts, palette keyboard insertion (13a)."""

from __future__ import annotations

from collections.abc import Iterator
from tkinter import ttk
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core import default_registry
from pyguibud.core.commands import InsertNode
from pyguibud.core.model import GridCell, Widget, Window
from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef, label_of
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.edit import EditActions, count_descendants
from pyguibud.designer.editing import new_node
from pyguibud.designer.session import DesignerSession

from .test_drag import _drag

_HINT = "Drag 'Button' onto the canvas, or press Enter to insert it into the selected container."
_MENU_EDITOR = "Menus and actions are edited in the menu editor."


def _noop() -> None:
    return None


def _classes(node: Widget) -> list[str]:
    return [getattr(child, "class_name", "") for child in node.children]


def _parent(node: object) -> object:
    return getattr(node, "parent", None)


# ---------------------------------------------------------------- the registry (pure)
@pytest.fixture
def registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.add_menu(MenuDef("edit", "_Edit"))
    return reg


def test_scoped_chords_collide_only_within_a_scope_or_with_a_global(
    registry: ActionRegistry,
) -> None:
    registry.add(ActionDef("a", "edit", "A", _noop, shortcut="Delete", scope=("canvas",)))
    registry.add(ActionDef("b", "edit", "B", _noop, shortcut="Delete", scope=("tree",)))
    both = ("canvas", "tree")
    with pytest.raises(ValueError, match="used by"):
        registry.add(ActionDef("c", "edit", "C", _noop, shortcut="Delete", scope=both))
    with pytest.raises(ValueError, match="used by"):
        registry.add(ActionDef("d", "edit", "D", _noop, shortcut="Delete"))
    registry.add(ActionDef("e", "edit", "E", _noop, shortcut="Ctrl+E"))
    with pytest.raises(ValueError, match="used by"):
        registry.add(ActionDef("f", "edit", "F", _noop, shortcut="Ctrl+E", scope=("tree",)))


def test_alt_shortcuts_are_registered_and_listed(registry: ActionRegistry) -> None:
    redo = ActionDef(
        "r", "edit", "_Redo", _noop, shortcut="Ctrl+Y", alt_shortcuts=("Ctrl+Shift+Z",)
    )
    registry.add(redo)
    with pytest.raises(ValueError, match="used by"):
        registry.add(ActionDef("x", "edit", "X", _noop, shortcut="Ctrl+Shift+Z"))
    (row,) = registry.cheat_sheet()
    assert row.accelerator == "Ctrl+Y, Ctrl+Shift+Z"


def test_cheat_sheet_names_the_scope_and_ignores_the_live_label(registry: ActionRegistry) -> None:
    live = ActionDef(
        "u",
        "edit",
        "_Undo",
        _noop,
        shortcut="Ctrl+Z",
        dynamic_label=lambda: ("_Undo {action}", {"action": "Add element"}),
    )
    registry.add(live)
    delete = ActionDef("d", "edit", "_Delete", _noop, shortcut="Delete", scope=("canvas", "tree"))
    registry.add(delete)
    assert label_of(live) == "_Undo Add element"
    assert [r.label for r in registry.cheat_sheet()] == ["Undo", "Delete (canvas, object tree)"]


def test_an_underscore_in_a_live_parameter_is_not_a_mnemonic() -> None:
    action = ActionDef(
        "u", "edit", "_Undo", _noop, dynamic_label=lambda: ("_Undo {action}", {"action": "a_b"})
    )
    assert label_of(action) == "_Undo a__b"


# ---------------------------------------------------------------- EditActions (pure)
def _session_with_frame() -> tuple[DesignerSession, Widget, Widget]:
    session = DesignerSession(default_registry())
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    assert session.stack.execute(InsertNode(window, frame)).accepted
    label = new_node(session.registry.require("Label"), session.document)
    assert isinstance(label, Widget)
    label.placement = GridCell(row=0, column=0)
    assert session.stack.execute(InsertNode(frame, label)).accepted
    return session, frame, label


def test_delete_of_a_leaf_is_one_undoable_step_and_selects_the_parent() -> None:
    session, frame, label = _session_with_frame()
    asked: list[str] = []
    edit = EditActions(session, lambda q, _then: asked.append(q), asked.append)
    session.select(label, origin="tree")
    assert edit.can_delete()
    edit.delete()
    assert asked == [] and list(frame.children) == []
    assert session.selection.node is frame
    assert edit.undo_text is not None
    edit.undo()
    assert list(frame.children) == [label] and edit.can_redo()


def test_delete_of_a_container_asks_first_and_counts_descendants() -> None:
    session, frame, _label = _session_with_frame()
    asked: list[tuple[str, Any]] = []
    edit = EditActions(session, lambda q, then: asked.append((q, then)), lambda _m: None)
    session.select(frame, origin="tree")
    edit.delete()
    assert asked[0][0] == f"Delete '{frame.id}' and its 1 element?"
    assert session.document is not None and len(session.document.children[0].children) == 1
    asked[0][1]()  # the user confirms
    assert list(session.document.children[0].children) == []
    assert count_descendants(session.document) >= 1


def test_windows_cannot_be_deleted_and_a_stale_confirmation_is_ignored() -> None:
    session, frame, _label = _session_with_frame()
    assert session.document is not None
    edit = EditActions(session, lambda _q, then: then(), lambda _m: None)
    session.select(session.document.children[0], origin="tree")
    assert not edit.can_delete()
    edit.delete()  # nothing happens
    assert list(session.document.children[0].children) == [frame]
    edit._remove(object())  # a node that never was in the document: no parent, no crash


def test_delete_explains_why_a_window_or_bar_stays() -> None:
    """QA-13a-07: Delete on a window, bar, menu or action gives a reason; a widget gives none."""
    session, frame, _label = _session_with_frame()
    assert session.document is not None
    window = session.document.children[0]
    assert isinstance(window, Window) and window.menubar is not None
    assert window.statusbar is not None
    edit = EditActions(session, lambda *_a: None, lambda _m: None)
    bars = "Windows, menu bars and status bars cannot be deleted here."
    menus = "Menus and actions are edited in the menu editor."
    menu = window.menubar.children[0]
    cases: list[tuple[object, str | None]] = [(window, bars), (window.menubar, bars)]
    cases += [(window.statusbar, bars), (menu, menus)]
    cases += [(menu.children[0], menus), (frame, None)]
    for node, reason in cases:
        session.select(node, origin="tree")
        assert edit.delete_refusal() == reason, node
    assert EditActions(DesignerSession(default_registry()), *_NOOPS).delete_refusal() is None


_NOOPS = (lambda *_a: None, lambda _m: None)


def test_nothing_to_undo_without_a_document() -> None:
    edit = EditActions(DesignerSession(default_registry()), lambda *_a: None, lambda _m: None)
    assert not edit.can_undo() and not edit.can_redo() and not edit.can_delete()
    edit.undo()
    edit.redo()
    edit.delete()


# ---------------------------------------------------------------- the shell (Tk)
def _frame_in_window(shell: DesignerApp, root: Any) -> Widget:
    shell.session.new_from_template("main_window")
    session = shell.session
    assert session.document is not None and session.stack is not None
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    assert session.stack.execute(InsertNode(session.document.children[0], frame)).accepted
    root.update()
    return frame


@pytest.fixture
def shown(designer_root: Any) -> Iterator[Any]:
    """The root mapped and focused: key events only reach a focused window."""
    designer_root.geometry("1400x800")  # wide enough that the whole stage is in view
    designer_root.deiconify()
    designer_root.update()
    designer_root.focus_force()
    yield designer_root
    designer_root.withdraw()
    designer_root.geometry("")


def _entry_of(app: DesignerApp, action_id: str) -> tuple[Any, int]:
    action = app.registry.get(action_id)
    for menu, index, item in app.shell._entries:
        if item is action:
            return menu, index
    raise AssertionError(action_id)


@pytest.mark.gui
def test_edit_menu_labels_and_states_follow_the_stack(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.new_from_template("main_window")
    menu, index = _entry_of(shell, "edit.undo")
    shell.shell.refresh_states()
    assert (menu.entrycget(index, "label"), menu.entrycget(index, "state")) == ("Undo", "disabled")
    _frame_in_window(shell, designer_root)
    assert menu.entrycget(index, "label") == "Undo Add element"
    assert menu.entrycget(index, "state") == "normal"
    shell.registry.invoke("edit.undo")
    redo, redo_index = _entry_of(shell, "edit.redo")
    assert redo.entrycget(redo_index, "label") == "Redo Add element"


@pytest.mark.gui
def test_ctrl_z_still_undoes_after_a_click_on_a_canvas_widget(
    shell: DesignerApp, shown: Any
) -> None:
    """ADR-010 Addendum 1: design-mode bindtags exclude "all", so the focus must stay global."""
    frame = _frame_in_window(shell, shown)
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    widget = stage.view.inner[id(frame)]
    assert "all" not in widget.bindtags()
    widget.event_generate("<ButtonPress-1>", x=2, y=2)
    shown.update()
    assert shell.session.selection.node is frame
    focused = shown.focus_get()
    assert focused is shell.shell.canvas.notebook
    stack = shell.session.stack
    assert stack is not None
    depth = stack.index
    focused.event_generate("<Control-z>")
    assert stack.index == depth - 1
    focused.event_generate("<Control-y>")
    assert stack.index == depth
    focused.event_generate("<Control-z>")
    focused.event_generate("<Control-Shift-Z>")  # Ctrl+Shift+Z redoes: it never undoes
    assert stack.index == depth


@pytest.mark.gui
def test_typed_ctrl_z_in_an_entry_is_left_to_the_entry(
    shell: DesignerApp, designer_root: Any
) -> None:
    _frame_in_window(shell, designer_root)
    entry = ttk.Entry(designer_root)
    handler = shell.shell._key_handler("edit.undo")
    stack = shell.session.stack
    assert stack is not None
    depth = stack.index
    assert handler(SimpleNamespace(widget=entry)) is None and stack.index == depth
    assert handler(SimpleNamespace(widget=shell.shell.tree.tree)) == "break"
    assert stack.index == depth - 1
    entry.destroy()


@pytest.mark.gui
def test_delete_key_on_the_canvas_and_the_tree_but_not_elsewhere(
    shell: DesignerApp, shown: Any
) -> None:
    frame = _frame_in_window(shell, shown)
    session = shell.session
    assert session.document is not None
    window = session.document.children[0]
    session.select(frame, origin="tree")
    tree = shell.shell.tree.tree
    assert tree is not None
    tree.focus_force()
    tree.event_generate("<Delete>")
    shown.update()
    assert frame not in window.children and session.selection.node is window
    shell.registry.invoke("edit.undo")
    session.select(frame, origin="canvas")
    notebook = shell.shell.canvas.notebook
    notebook.focus_force()
    notebook.event_generate("<Delete>")
    assert frame not in window.children
    shell.registry.invoke("edit.undo")
    session.select(frame, origin="tree")
    palette = shell.shell.palette.tree
    assert palette is not None
    palette.focus_force()
    palette.event_generate("<Delete>")  # the key is scoped: the palette does not delete
    assert frame in window.children


@pytest.mark.gui
def test_deleting_a_container_opens_a_confirmation(shell: DesignerApp, designer_root: Any) -> None:
    frame = _frame_in_window(shell, designer_root)
    session = shell.session
    assert session.stack is not None and session.document is not None
    label = new_node(session.registry.require("Label"), session.document)
    assert isinstance(label, Widget)
    label.placement = GridCell(row=0, column=0)
    assert session.stack.execute(InsertNode(frame, label)).accepted
    session.select(frame, origin="tree")
    shell.registry.invoke("edit.delete")
    (dialog,) = shell._live_dialogs()
    assert _parent(frame) is not None  # nothing happened yet
    dialog.close()  # Esc: cancel
    assert _parent(frame) is not None
    shell.registry.invoke("edit.delete")
    (dialog,) = shell._live_dialogs()
    dialog.confirm()  # type: ignore[attr-defined]
    assert _parent(frame) is None
    assert session.selection.node is session.document.children[0]


# ---------------------------------------------------------------- palette (Tk)
def _row(shell: DesignerApp, name: str) -> str:
    tree = shell.shell.palette.tree
    assert tree is not None
    tree.see(f"w:{name}")
    tree.update_idletasks()
    return f"w:{name}"


@pytest.mark.gui
def test_a_click_on_a_palette_item_shows_the_hint(shell: DesignerApp, designer_root: Any) -> None:
    shell.session.new_from_template("main_window")
    tree = shell.shell.palette.tree
    assert tree is not None
    designer_root.update()
    tree.selection_set(_row(shell, "Button"))
    designer_root.update()
    assert shell.shell._message == _HINT
    tree.selection_set(_row(shell, "Action"))
    designer_root.update()
    assert shell.shell._message == _MENU_EDITOR


@pytest.mark.gui
def test_a_language_switch_does_not_repeat_the_hint(shell: DesignerApp, designer_root: Any) -> None:
    tree = shell.shell.palette.tree
    assert tree is not None
    tree.selection_set(_row(shell, "Button"))
    designer_root.update()
    shell.shell.show_message("other")
    shell.shell.palette.retranslate()
    designer_root.update()
    assert shell.shell._message == "other"


@pytest.mark.gui
def test_a_full_language_switch_does_not_repeat_the_hint(
    shell: DesignerApp, designer_root: Any
) -> None:
    """QA-13a-09: the canvas re-render ran the palette's idle job before the queued events."""
    shell.session.new_from_template("main_window")
    # No object-tree row is selected: its full-text offer of a clipped row (en_XA) is a
    # different status-bar message.
    shell.session.select(None, origin="session")
    tree = shell.shell.palette.tree
    assert tree is not None
    tree.selection_set(_row(shell, "Button"))
    designer_root.update()
    assert shell.shell._message == _HINT
    for lang in ("de_DE", "en_XA", "en_GB"):
        shell.shell.show_message("other")
        shell.set_language(lang)
        designer_root.update()
        assert shell.shell._message == "", lang  # cleared (QA-13a-13), and no hint re-posted
    tree.selection_set(_row(shell, "Label"))  # a real pick still shows the hint
    designer_root.update()
    assert shell.shell._message.startswith("Drag 'Label'")


@pytest.mark.gui
def test_enter_and_double_click_insert_and_the_focus_stays_on_the_palette(
    shell: DesignerApp, shown: Any
) -> None:
    frame = _frame_in_window(shell, shown)
    shell.session.select(frame, origin="tree")
    tree = shell.shell.palette.tree
    assert tree is not None
    tree.focus_force()
    tree.focus(_row(shell, "Button"))
    tree.event_generate("<Return>")
    assert _classes(frame) == ["Button"]
    assert shell.session.selection.node is frame.children[0]
    assert shown.focus_get() is tree
    assert shell.shell._message == f"Inserted '{frame.children[0].id}'."
    tree.focus(_row(shell, "Label"))
    tree.event_generate("<Return>")
    assert _classes(frame) == ["Button", "Label"]
    assert "<Double-Button-1>" in tree.bind()  # event_generate cannot synthesise a double click
    shell.shell.palette._activate(_row(shell, "Entry"))
    assert _classes(frame)[-1] == "Entry"
    stack = shell.session.stack
    assert stack is not None
    for _ in range(3):
        stack.undo()
    assert list(frame.children) == []


@pytest.mark.gui
def test_a_menu_item_on_enter_or_a_drag_explains_instead_of_cancelling(
    shell: DesignerApp, designer_root: Any
) -> None:
    _frame_in_window(shell, designer_root)
    shell.shell.drag.insert_widget("Action")
    assert shell.shell._message == _MENU_EDITOR
    shell.shell.show_message("")
    shell.shell.drag.press("Action", 0, 0)
    shell.shell.drag.motion(40, 40)
    shell.shell.drag.release(40, 40)
    assert shell.shell._message == _MENU_EDITOR  # not "Drag cancelled."


@pytest.mark.gui
def test_an_inserted_empty_container_can_take_the_next_drop(shell: DesignerApp, shown: Any) -> None:
    """UAT 13a, build a small form: a Frame first, then a Button dropped into the empty Frame."""
    shell.session.new_from_template("main_window")
    assert shell.session.document is not None
    shell.session.select(shell.session.document.children[0], origin="tree")
    shell.shell.drag.insert_widget("Frame")
    shown.update()
    frame = shell.session.selection.node
    assert isinstance(frame, Widget) and frame.class_name == "Frame"
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    inner = stage.view.inner[id(frame)]
    assert inner.winfo_width() > 30 and inner.winfo_height() > 30  # not a 1 px sliver
    point = (
        inner.winfo_rootx() + inner.winfo_width() // 2,
        inner.winfo_rooty() + inner.winfo_height() // 2,
    )
    _drag(shell, shown, "Button", point)
    shown.update()
    assert _classes(frame) == ["Button"]


@pytest.mark.gui
def test_the_designer_lists_use_their_own_selection_style(shell: DesignerApp) -> None:
    for panel in (shell.shell.palette, shell.shell.tree, shell.shell.inspector):
        assert panel.tree is not None and str(panel.tree.cget("style")) == "Designer.Treeview"
    style = ttk.Style()
    assert style.map("Designer.Treeview", "background")  # the solid selected row
