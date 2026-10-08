"""Regression tests for the QA pass 2 fixes of Step 14a.1 (QA-14a1-18 to 22, beyond the repros)."""

# ruff: noqa: F811 - the imported fixtures are parameters of the tests below

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core import read_ui
from pyguibud.core.model import Prop, Widget
from pyguibud.designer import files
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.message import ChoiceDialog, message_dialog
from pyguibud.i18n import _
from tests.designer.test_edit import shown  # noqa: F401 - key events need a focused root
from tests.designer.test_qa14a1_abuse import (  # noqa: F401 - fixtures
    HELLO,
    _crash,
    _labels,
    _restore,
    _settle,
    hello,
    qa_app,
)


def _mixed_file(tmp_path: Path) -> Path:
    """hello.ui with two Canvases (width, background) and two Buttons (state) that differ."""
    text = HELLO.read_text(encoding="utf-8")
    start = text.index('<widget class="Label" id="lbl_name">')
    end = text.index("</widget>", start) + len("</widget>")

    def canvas(name: str, colour: str, width: int, row: int) -> str:
        return (
            f'<widget class="Canvas" id="{name}">\n'
            f'          <prop name="background">{colour}</prop>\n'
            f'          <prop name="width">{width}</prop>\n'
            f'          <cell row="{row}" column="0"/>\n        </widget>'
        )

    both = canvas("cnv_a", "red", 10, 0) + "\n        " + canvas("cnv_b", "blue", 20, 2)
    text = text[:start] + both + text[end:]
    button = text.index('<widget class="Button" id="btn_greet"')
    close = text.index("</widget>", button)
    second = (
        '</widget>\n        <widget class="Button" id="btn_two">\n'
        '          <prop name="text">Two</prop>\n'
        '          <cell row="3" column="1" sticky="e"/>\n        '
    )
    disabled = text[button:close].replace(
        '<prop name="text"', '<prop name="state">disabled</prop>\n          <prop name="text"'
    )
    target = tmp_path / "mixed.ui"
    target.write_text(text[:button] + disabled + second + text[close:], encoding="utf-8")
    return target


def _nodes(app: DesignerApp, class_name: str) -> list[Widget]:
    document = app.session.document
    assert document is not None
    return [n for n in document.walk() if isinstance(n, Widget) and n.class_name == class_name]


# ---------------------------------------------------------------- 18: untouched "(mixed)"
@pytest.mark.gui
@pytest.mark.parametrize(
    ("class_name", "key"),
    [("Canvas", "prop:background"), ("Canvas", "prop:width"), ("Button", "prop:state"),
     ("Button", "prop:text")],
)  # fmt: skip
def test_enter_on_any_untouched_mixed_editor_commits_nothing(
    qa_app: DesignerApp, tmp_path: Path, class_name: str, key: str
) -> None:
    """Colour entry, spinbox, combobox and entry: the model and the history stay as they were."""
    assert qa_app.open_path(_mixed_file(tmp_path))
    nodes = _nodes(qa_app, class_name)
    assert len(nodes) == 2
    qa_app.session.select_many(nodes, origin="tree")
    _settle(qa_app.root)
    stack = qa_app.session.stack
    assert stack is not None
    editor = qa_app.shell.inspector._editors[key]
    assert editor.field.value is None  # "(mixed)"
    before, index = [dict(n.props) for n in nodes], stack.index
    enter = getattr(editor, "_enter", None)
    if enter is not None:
        enter()
    editor.commit_pending()  # what focus-out runs
    assert [dict(n.props) for n in nodes] == before and stack.index == index
    assert not qa_app.session.dirty


@pytest.mark.gui
def test_enter_still_commits_text_the_user_typed_in_a_mixed_editor(
    qa_app: DesignerApp, tmp_path: Path
) -> None:
    assert qa_app.open_path(_mixed_file(tmp_path))
    nodes = _nodes(qa_app, "Canvas")
    qa_app.session.select_many(nodes, origin="tree")
    _settle(qa_app.root)
    editor = qa_app.shell.inspector._editors["prop:width"]
    editor.var.set("33")
    editor._enter()  # type: ignore[attr-defined]
    assert [n.props["width"].value for n in nodes] == ["33", "33"]
    assert qa_app.session.dirty


@pytest.mark.gui
def test_enter_on_an_untouched_single_field_does_not_touch_the_history(
    qa_app: DesignerApp, hello: Path
) -> None:
    assert qa_app.open_path(hello)
    qa_app.session.select(_labels(qa_app)[0], origin="tree")
    _settle(qa_app.root)
    stack = qa_app.session.stack
    assert stack is not None
    qa_app.shell.inspector._editors["prop:width"]._enter()  # type: ignore[attr-defined]
    assert stack.index == 0 and not qa_app.session.dirty


# ---------------------------------------------------------------- 19: a deleted original
@pytest.mark.gui
def test_a_restored_snapshot_of_a_deleted_file_asks_for_a_new_name(
    qa_app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason says so, the title is not read-only, editing works and Save is Save As."""
    assert qa_app.recovery is not None
    _crash(qa_app.recovery.root, hello)
    hello.unlink()
    _restore(qa_app, hello)
    session = qa_app.session
    assert session.dirty and session.read_only_reason == files.M_GONE
    assert _(files.M_GONE) == "the file no longer exists"
    assert "read-only" not in session.title and "read-only" not in qa_app.root.title()
    assert session.stack is not None and not session.stack.read_only
    asked: list[str] = []
    target = hello.parent / "again.ui"

    def ask_save(_root: object, name: str, _folder: object) -> str:
        asked.append(name)
        return str(target)

    monkeypatch.setattr(file_dialogs, "ask_save", ask_save)
    qa_app.save()
    _settle(qa_app.root)
    assert asked == ["hello.ui"] and target.exists() and not hello.exists()
    assert session.stack is not None and not session.stack.is_dirty
    assert session.path == target and session.read_only_reason is None


def test_only_a_vanished_file_is_called_gone(tmp_path: Path) -> None:
    result = read_ui(HELLO)
    assert files.read_only_reason(result, tmp_path / "nothing.ui") == files.M_GONE
    assert files.read_only_reason(result, None) is None
    assert files.read_only_reason(result, HELLO) in (None, files.M_WRITE_PROTECTED)
    assert files.M_GONE in files.SAVE_AS_REASONS and files.M_NEWER not in files.SAVE_AS_REASONS


# ---------------------------------------------------------------- 20: the "..." dialog
@pytest.mark.gui
def test_text_dialog_stays_open_with_the_reason_when_the_guard_refuses(
    qa_app: DesignerApp, hello: Path
) -> None:
    """The typed text and the model are kept; fixing the text then applies it."""
    assert qa_app.open_path(hello)
    label = _labels(qa_app)[0]
    qa_app.session.select(label, origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    stack = qa_app.session.stack
    assert stack is not None
    original, index = dict(label.props), stack.index
    inspector.special(inspector._editors["prop:text"], "text")
    _settle(qa_app.root)
    dialog: Any = qa_app._live_dialogs()[-1]
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", "Line one\x0bLine two")
    dialog.accept()
    _settle(qa_app.root)
    assert not dialog.closed and dialog in qa_app._live_dialogs()
    assert dialog.reason.winfo_manager() and "U+000B" in str(dialog.reason.cget("text"))
    assert dialog.text.get("1.0", "end-1c") == "Line one\x0bLine two"
    assert dict(label.props) == original and stack.index == index  # the dry run left no trace
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", "Line one\nLine two")
    dialog.accept()
    _settle(qa_app.root)
    assert dialog.closed and label.props["text"].value == "Line one\nLine two"


@pytest.mark.gui
def test_text_dialog_refuses_a_too_long_text_and_cancel_still_closes(
    qa_app: DesignerApp, hello: Path
) -> None:
    from pyguibud.core.validate import MAX_TEXT_LENGTH

    assert qa_app.open_path(hello)
    qa_app.session.select(_labels(qa_app)[0], origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    inspector.special(inspector._editors["prop:text"], "text")
    dialog: Any = qa_app._live_dialogs()[-1]
    dialog.text.insert("1.0", "x" * (MAX_TEXT_LENGTH + 1))
    dialog.accept()
    assert not dialog.closed and str(MAX_TEXT_LENGTH) in str(dialog.reason.cget("text"))
    dialog.text.event_generate("<Key>", keysym="a")  # typing clears the stale reason
    assert not dialog.reason.winfo_manager()
    dialog.close()
    assert dialog.closed and not qa_app.session.dirty


# ---------------------------------------------------------------- 21: variable rename history
@pytest.mark.gui
def test_undo_and_redo_of_a_variable_rename_keep_the_variable_selected(
    qa_app: DesignerApp, hello: Path
) -> None:
    assert qa_app.open_path(hello)
    panel = qa_app.shell.variables
    panel._render()
    assert panel.tree is not None
    panel.tree.selection_set("user_name")
    _settle(qa_app.root)
    panel.id_var.set("person")
    assert panel.flush()
    _settle(qa_app.root)
    assert panel.current() == "person"
    panel.invoke("edit.undo")
    _settle(qa_app.root)
    assert panel.current() == "user_name" and panel.id_var.get() == "user_name"
    panel.invoke("edit.redo")
    _settle(qa_app.root)
    assert panel.current() == "person" and panel.id_var.get() == "person"


@pytest.mark.gui
def test_undoing_the_deletion_of_a_variable_does_not_invent_a_selection(
    qa_app: DesignerApp, hello: Path
) -> None:
    assert qa_app.open_path(hello)
    panel = qa_app.shell.variables
    panel._render()
    assert panel.tree is not None
    panel.tree.selection_set("user_name")
    panel.delete()  # it is bound to the Entry: a confirmation first
    confirm: Any = qa_app._live_dialogs()[-1]
    confirm.confirm()
    _settle(qa_app.root)
    assert panel.current() is None
    panel.invoke("edit.undo")
    _settle(qa_app.root)
    assert panel.current() is None


# ---------------------------------------------------------------- 22: access keys
@pytest.mark.gui
@pytest.mark.parametrize("language", ["en_GB", "en_XA", "de_DE"])
def test_the_buttons_of_every_dialog_have_unique_access_keys(
    qa_app: DesignerApp, language: str
) -> None:
    """The four dialogs of the finding, plus the file-conflict and write-failure questions."""
    from pyguibud import i18n
    from pyguibud.designer import app as app_module
    from pyguibud.designer.dialogs.new_file import NewFileDialog
    from pyguibud.designer.dialogs.save_changes import save_changes_dialog
    from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
    from pyguibud.designer.dialogs.text import TextDialog

    root = qa_app.root
    i18n.set_language(language)
    conflict = [(app_module._M_OVERWRITE, None), (app_module._M_SAVE_AS, None),
                (app_module._M_CANCEL, None)]  # fmt: skip
    failure = [(app_module._M_OK, None), (app_module._M_SAVE_AS, None)]
    dialogs: list[Any] = [
        NewFileDialog(root, lambda _t: True),
        ShortcutsDialog(root, qa_app.registry),
        TextDialog(root, Prop(name="text", value="x"), lambda _p: None, translatable=True),
        save_changes_dialog(root, lambda: "x.ui", save=lambda: None, discard=lambda: None),
        message_dialog(root, lambda: "?"),
        ChoiceDialog(root, lambda: "?", conflict),
        ChoiceDialog(root, lambda: "?", failure),
    ]
    try:
        for dialog in dialogs:
            dialog.retranslate()
            letters = []
            for button, _msgid in dialog.access_keys:
                underline = int(button.cget("underline"))
                assert underline >= 0, (type(dialog).__name__, button.cget("text"))
                letters.append(str(button.cget("text"))[underline].lower())
            assert len(letters) == len(set(letters)), (type(dialog).__name__, letters)
        text_dialog = dialogs[2]
        text_dialog._on_alt(SimpleNamespace(char="c"))  # Alt+C is Cancel
        assert text_dialog.closed
    finally:
        i18n.set_language("en_GB")
        for dialog in dialogs:
            dialog.close()


# ---------------------------------------------------------------- the extra: settings
@pytest.mark.gui
def test_a_refused_settings_save_is_said_once_per_run(
    qa_app: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer import app as app_module

    posted: list[str] = []
    qa_app.message.connect(posted.append)
    monkeypatch.setattr(app_module, "save_settings", lambda *_a, **_k: False)
    qa_app._save_settings()
    qa_app._save_settings()
    qa_app.set_language("de_DE")
    qa_app.set_language("en_GB")
    said = [m for m in posted if m == "Your settings could not be saved."]
    assert len(said) == 1
    monkeypatch.setattr(app_module, "save_settings", lambda *_a, **_k: True)
    qa_app._save_settings()
    assert posted.count("Your settings could not be saved.") == 1
