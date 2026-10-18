"""Tk tests of the editable inspector, the Events tab and the Variables tab (spec 14a 3-5, 17)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import dump_ui
from pyguibud.core.commands import CommandStack, InsertNode, Macro
from pyguibud.core.model import GridCell, Prop, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.dialogs.text import TextDialog
from pyguibud.designer.editing import new_node
from pyguibud.designer.panels.editors import ADD, NEW
from pyguibud.designer.panels.inspector import InspectorPanel
from pyguibud.designer.properties import commit_commands
from tests.conftest import BUDGET_FACTOR
from tests.designer.conftest import best_of
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _settle,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui


def _open(app: DesignerApp, root: Any, node_id: str | None = None) -> Any:  # noqa: F811
    app.new_from_template("login_form")
    document = app.session.document
    assert document is not None
    node = next((n for n in document.walk() if node_id and getattr(n, "id", "") == node_id), None)
    if node is not None:
        app.session.select(node, origin="tree")
    _settle(root)
    return node


def _editor(inspector: InspectorPanel, key: str) -> Any:
    editor = inspector._editors.get(key)
    assert editor is not None, key
    return editor


def test_typed_text_commits_on_enter_and_undoes(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    label = _open(app, designer_root, "lbl_username")
    stack = app.session.stack
    assert stack is not None and app.session.document is not None
    before = dump_ui(app.session.document)
    editor = _editor(app.shell.inspector, "prop:text")
    editor.var.set("Login:")
    assert editor.pending()
    editor._enter()
    assert label.props["text"].value == "Login:" and label.props["text"].translatable
    assert not editor.pending() and app.shell._message == ""
    _settle(designer_root)
    app.shell._invoke("edit.undo")
    _settle(designer_root)
    assert dump_ui(app.session.document) == before
    assert app.shell.inspector.value_of("prop:text") == "User name:"  # reloaded
    assert tk_errors == []


def test_an_untouched_editor_never_commits(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root, "lbl_username")
    stack = app.session.stack
    assert stack is not None
    inspector = app.shell.inspector
    for editor in inspector._editors.values():
        assert not editor.pending()
        editor.commit_pending()
    assert inspector.flush() and not stack.can_undo


def test_bad_number_is_refused_marked_and_escape_reverts(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "lbl_username")
    stack = app.session.stack
    assert stack is not None
    editor = _editor(app.shell.inspector, "prop:width")
    editor.var.set("999999999999")
    assert not editor.commit_pending()
    assert "width" not in label.props and not stack.can_undo
    assert str(editor.widget.cget("style")) == "Designer.Invalid.TSpinbox"
    assert app.shell._message.startswith("Must be between")  # QA-14a1-13: a number, too big
    assert not app.shell.inspector.flush()  # A15: the pending text blocks Save/Quit
    app.shell._invoke("edit.undo")  # R2: undo flushes first; the refusal stops it
    assert editor.text() == "999999999999"
    editor._escape()
    assert editor.text() == "" and str(editor.widget.cget("style")) == "Designer.TSpinbox"
    assert app.shell.inspector.flush()


def test_a_refusal_then_a_good_commit_clears_the_status(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    entry = _open(app, designer_root, "ent_password")
    editor = _editor(app.shell.inspector, "field:id")
    editor.var.set("lbl_username")  # a duplicate id: the guard refuses
    assert not editor.commit_pending() and entry.id == "ent_password"
    assert app.shell._message
    editor.var.set("ent_secret")
    assert editor.commit_pending() and entry.id == "ent_secret"
    assert app.shell._message == ""  # rule C2


def test_spinbox_arrows_merge_into_one_step_and_reset(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "lbl_username")
    stack = app.session.stack
    assert stack is not None
    inspector = app.shell.inspector
    editor = _editor(inspector, "prop:width")
    inspector.focus_in(editor)
    for value in ("1", "2", "3"):
        editor.var.set(value)
        editor._arrow()
    assert label.props["width"].value == "3" and stack.index == 1
    _settle(designer_root)
    inspector.reset("prop:width")
    assert "width" not in label.props and stack.index == 2


def test_ctrl_z_reverts_typed_text_first_then_undoes(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "lbl_username")
    stack = app.session.stack
    assert stack is not None
    inspector = app.shell.inspector
    editor = _editor(inspector, "prop:text")
    editor.var.set("A")
    editor._enter()
    _settle(designer_root)
    editor = _editor(inspector, "prop:text")
    editor.var.set("typed")
    assert inspector.history_key(editor, redo=False) == "break"
    assert editor.text() == "A" and label.props["text"].value == "A"  # a local revert
    inspector.history_key(editor, redo=False)
    _settle(designer_root)
    assert label.props["text"].value == "User name:"
    inspector.history_key(_editor(inspector, "prop:text"), redo=True)
    assert label.props["text"].value == "A"


def test_multi_edit_shows_mixed_and_commits_one_macro(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root)
    document = app.session.document
    assert document is not None and app.session.stack is not None
    labels = [n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label"]
    app.session.select_many(labels, origin="canvas")
    _settle(designer_root)
    inspector = app.shell.inspector
    assert "field:id" not in inspector._editors
    editor = _editor(inspector, "prop:text")
    assert editor.text() == "" and inspector._rows["prop:text"][2].winfo_manager() == "grid"
    assert not editor.pending()  # (mixed) is never typed text
    editor.var.set("Same")
    editor._enter()
    assert {w.props["text"].value for w in labels} == {"Same"}
    assert app.session.stack.undo_text == "Set 'Text' on 2 elements"
    assert inspector.header.cget("text") == "2 elements selected; editing shared properties."


def test_selection_change_commits_pending_text_to_the_old_node(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "lbl_username")
    editor = _editor(app.shell.inspector, "prop:text")
    editor.var.set("Moved on")
    other = next(n for n in label.parent.children if n.id == "lbl_password")
    app.session.select(other, origin="tree")
    _settle(designer_root)
    assert label.props["text"].value == "Moved on"
    assert other.props["text"].value == "Password:"


def test_text_dialog_keeps_translation_data(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    app.new_from_template("login_form")
    assert app.session.document is not None
    window = app.session.document.children[0]
    app.session.select(window, origin="tree")
    _settle(designer_root)
    inspector = app.shell.inspector
    opened: list[ModalDialog] = []
    inspector.open_dialog = opened.append
    inspector.special(_editor(inspector, "prop:title"), "text")
    (dialog,) = opened
    assert isinstance(dialog, TextDialog)
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", "Two\nlines")
    dialog.comment.set("for translators")
    dialog.accept()
    title = window.props["title"]
    assert title == Prop(
        name="title",
        value="Two\nlines",
        translatable=True,
        context="window title",
        comment="for translators",
    )


def test_new_variable_entry_binds_in_one_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    entry = _open(app, designer_root, "ent_username")
    document = app.session.document
    assert document is not None
    inspector = app.shell.inspector
    inspector.special(_editor(inspector, "field:bind"), NEW)
    assert entry.bind == "var1" and document.variables["var1"].type == "string"
    _settle(designer_root)
    assert inspector.value_of("field:bind") == "var1"


def test_read_only_disables_every_editor(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open(app, designer_root, "lbl_username")
    monkeypatch.setattr(CommandStack, "read_only", property(lambda _s: True))
    app.session.read_only_reason = "the file is write-protected"
    inspector = app.shell.inspector
    inspector._render()
    editor = _editor(inspector, "prop:text")
    assert "readonly" in editor.widget.state()  # D9: selectable, not disabled
    assert inspector.header.cget("text") == (
        "This document is read-only: the file is write-protected"
    )
    editor.var.set("x")
    assert not inspector.commit(editor, "x")


# ---------------------------------------------------------------- events
def test_events_tab_binds_unbinds_and_adds_keys(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    button = _open(app, designer_root, "btn_login")
    stack = app.session.stack
    assert stack is not None
    tab = app.shell.inspector.events
    boxes = {box.field.key: box for box in tab.boxes}
    command = boxes["event:command"]
    assert command.text() == "on_login" and "on_login" in command.field.choices
    command.var.set("on_ok")
    assert command.commit_pending()
    assert [(e.name, e.handler) for e in button.events] == [("command", "on_ok")]
    _settle(designer_root)
    tab.key_entry.insert(0, "Ctrl+K")
    tab.add_key()
    assert button.events[-1].name == "key:Ctrl+K"
    _settle(designer_root)
    assert "event:key:Ctrl+K" in {b.field.key for b in tab.boxes}
    tab.key_entry.insert(0, "Ctrl+K")
    index = stack.index
    tab.add_key()  # a duplicate: the guard refuses with its reason
    assert stack.index == index and app.shell._message
    tab.change("key:Ctrl+K", "")
    assert [e.name for e in button.events] == ["command"]
    app.session.select(button.parent, origin="tree")
    _settle(designer_root)
    assert tab.boxes == []
    assert tk_errors == []


# ---------------------------------------------------------------- variables
def test_variables_add_rename_bind_and_delete(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    entry = _open(app, designer_root, "ent_username")
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    panel = app.shell.variables
    tree = panel.tree
    assert tree is not None and tree.get_children() == ("username", "password")
    assert "ent_username" in tree.set("username", "used")
    panel.add()
    _settle(designer_root)
    assert panel.current() == "var1"
    tree.selection_set("username")
    _settle(designer_root)
    panel.id_var.set("user_name")
    panel._commit_id()
    _settle(designer_root)
    assert entry.bind == "user_name" and panel.current() == "user_name"
    panel.id_var.set("password")
    panel._commit_id()  # A12: refused with the reason, nothing changes
    assert "user_name" in document.variables and app.shell._message
    asked: list[str] = []
    panel.confirm = lambda question, then: (asked.append(question), then())  # type: ignore[assignment, func-returns-value]
    panel.delete()
    assert asked == ["'user_name' is bound to 1 widget. Unbind it and delete it?"]
    assert entry.bind is None and "user_name" not in document.variables
    _settle(designer_root)
    tree.selection_set("var1")
    _settle(designer_root)
    panel.bind_selection()
    assert str(entry.bind) == "var1"
    panel.type_var.set("bool")
    panel._commit_type()  # an Entry cannot hold a bool: refused, the row reloads
    assert document.variables["var1"].type == "string" and panel.type_var.get() == "string"
    assert tk_errors == []


def test_side_tabs_switch_with_ctrl_tab_and_retranslate(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    shell = app.shell
    tree = shell.tree.tree
    assert tree is not None
    assert shell._switch_tab(SimpleNamespace(widget=tree), 1) == "break"
    assert shell.panels[2].name == "variables"
    assert shell._switch_tab(SimpleNamespace(widget=shell.inspector.notebook), 1) == "break"
    assert shell.inspector.notebook.select() == str(shell.inspector.events.frame)
    assert shell._switch_tab(SimpleNamespace(widget=shell.toolbar), 1) is None
    shell._switch_tab(SimpleNamespace(widget=shell.variables.frame), 1)
    assert shell.panels[2].name == "tree"
    i18n.set_language("en_XA")
    designer_root.update()
    assert str(shell.side.tab(shell.variables.frame, "text")).startswith("[")
    assert str(shell.variables.heading.cget("text")).startswith("[")
    assert str(shell.inspector.notebook.tab(shell.inspector.form_tab, "text")).startswith("[")


# ---------------------------------------------------------------- every editor kind (spec 17)
def test_bool_enum_sticky_and_buttons_editors(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    entry = _open(app, designer_root, "ent_password")
    inspector = app.shell.inspector
    sticky = _editor(inspector, "place:grid:sticky")
    sticky.flags[1][1].set(False)  # untick E of "ew"
    sticky._toggle()
    assert entry.placement.sticky == "w"
    _settle(designer_root)
    sticky = _editor(inspector, "place:grid:sticky")
    sticky.flags[0][1].set(True)  # tick N: appended, the order kept
    sticky._toggle()
    assert entry.placement.sticky == "wn"
    window = entry.parent
    app.session.select(window, origin="tree")
    _settle(designer_root)
    modal = _editor(inspector, "field:modal")
    modal.widget.invoke()
    assert window.modal is True
    _settle(designer_root)
    inspector.reset("field:modal")
    assert not bool(window.modal)
    orient = _editor(inspector, "layout:orient")
    orient.widget.current(1)
    orient._picked()
    assert window.layout.orient == "horizontal"
    app.new_from_template("dialog")
    assert app.session.document is not None
    dialog = app.session.document.children[0]
    app.session.select(dialog, origin="tree")
    _settle(designer_root)
    buttons = _editor(inspector, "field:buttons")
    buttons.flags[4][1].set(True)  # close
    buttons._toggle()
    assert dialog.buttons == "ok,cancel,close"
    _settle(designer_root)
    buttons = _editor(inspector, "field:buttons")
    buttons.flags[0][1].set(False)  # ok
    buttons._toggle()
    assert dialog.buttons == "cancel,close"


def test_image_and_colour_editors_use_the_file_seam(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "lbl_username")
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    inspector = app.shell.inspector
    logo = Path(__file__).resolve().parents[2] / "assets/brand/logo/pyguibud.png"
    inspector.ask_image = lambda _root: str(logo)  # type: ignore[assignment]
    inspector.special(_editor(inspector, "prop:image"), ADD)
    assert document.resources["image1"].src == logo.as_posix()
    assert label.props["image"].ref == "image1"
    stack.undo()  # one step: the resource and the reference
    assert dump_ui(document) == before
    canvas = new_node(app.session.registry.require("Canvas"), document)
    assert isinstance(canvas, Widget)
    canvas.placement = GridCell(row=3, column=0)
    assert stack.execute(InsertNode(label.parent, canvas)).accepted
    app.session.select(canvas, origin="tree")
    _settle(designer_root)
    inspector.ask_colour = lambda _root, _initial: "#1C3FF0"  # type: ignore[assignment]
    inspector.special(_editor(inspector, "prop:background"), "colour")
    assert canvas.props["background"].value == "#1C3FF0"
    colour = _editor(inspector, "prop:background")
    colour.var.set("#12")
    assert not colour.commit_pending()
    assert app.shell._message == "Not a colour such as #1C3FF0."


@pytest.mark.budget
def test_rebuild_and_multi_edit_budgets(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    label = _open(app, designer_root, "ent_password")
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    inspector = app.shell.inspector
    # spec 17: form rebuild <= 60 ms; best of 7 with a 1.5x factor, as it ran at 48-50 ms (H10)
    assert best_of(inspector._render) <= 0.060 * BUDGET_FACTOR
    labels = []
    for row in range(50):
        node = new_node(app.session.registry.require("Label"), document)
        assert isinstance(node, Widget)
        node.id = f"many{row}"
        node.placement = GridCell(row=10 + row, column=0)
        labels.append(node)
    assert stack.execute(Macro("x", [InsertNode(label.parent, n) for n in labels])).accepted
    app.session.select_many(labels, origin="canvas")
    _settle(designer_root)
    field = _editor(inspector, "prop:text").field
    values = iter(str(k) for k in range(100))
    took = best_of(
        lambda: stack.execute(commit_commands(tuple(labels), field, next(values))), repeat=3
    )
    assert took <= 0.150  # spec 17: one guard run for 50 widgets


def test_a_late_focus_in_for_a_destroyed_row_is_ignored(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    """UAT 19d: a FocusIn queued for a row that a rebuild destroyed raised a TclError."""
    _open(app, designer_root, "lbl_username")
    inspector = app.shell.inspector
    editor = _editor(inspector, "prop:width")
    editor.frame.destroy()
    inspector.focus_in(editor)  # used to raise "bad window path name"
