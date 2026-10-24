"""Step 19g regressions: bidi-escaped values in dialog questions, 10,000-character values in
the Variables panel and the Rename dialog, and a read-only editor that stays disabled."""

from __future__ import annotations

import datetime
import os
import shutil
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.commands import CommandStack
from pyguibud.core.model import Widget
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.dialogs.rename import RenameDialog
from pyguibud.designer.dialogs.save_changes import save_changes_dialog
from pyguibud.designer.recovery import RecoveryEntry
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT
from tests.designer.test_qa18_abuse import HELLO, _settle
from tests.designer.test_qa19f_abuse import (
    _BIDI_UI,
    RLO,
    _raw,
    _shown_texts,
)
from tests.designer.test_qa19f_abuse import (
    app as _app,
)
from tests.designer.test_qa19f_abuse import (
    bidi as _bidi,
)
from tests.designer.test_qa19f_abuse import (
    errors as _errors,
)

pytestmark = pytest.mark.gui

app, bidi, errors = _app, _bidi, _errors  # the shared fixtures of the 19f abuse pass
ESCAPED = "\\u202e"


def _dialog_texts(app: Any) -> list[str]:
    dialog = app._live_dialogs()[-1]
    texts = _shown_texts(dialog.window)
    dialog.close()
    return texts


def _check(texts: list[str]) -> None:
    assert _raw(texts) == []
    assert any(ESCAPED in text for text in texts), texts


def test_save_changes_question_escapes_the_name(app: Any, errors: list[str]) -> None:
    dialog = save_changes_dialog(
        app.root, lambda: f"a{RLO}b.ui", save=lambda: None, discard=lambda: None
    )
    dialog.open()
    _settle(app.root)
    texts = _shown_texts(dialog.window)
    dialog.close()
    _check(texts)
    assert errors == []


def test_missing_file_message_escapes_the_path(
    app: Any,
    tmp_path: Path,
    errors: list[str],
) -> None:
    app.open_recent(str(tmp_path / f"gone{RLO}.ui"))
    _settle(app.root)
    _check(_dialog_texts(app))
    assert errors == []


def test_conflict_question_escapes_the_name(
    app: Any,
    tmp_path: Path,
    errors: list[str],
) -> None:
    bidi = app
    path = tmp_path / f"evil{RLO}.ui"  # a clean document, so no error question comes first
    shutil.copy(HELLO, path)
    assert app.open_path(path)
    _settle(app.root)
    stat = os.stat(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    os.utime(path, (stat.st_atime, stat.st_mtime + 60))  # "changed by another program"
    bidi.registry.invoke("file.save")
    _settle(bidi.root)
    _check(_dialog_texts(bidi))
    assert errors == []


def test_export_unsaved_question_escapes_the_name(bidi: Any, errors: list[str]) -> None:
    widget = next(n for n in bidi.session.document.walk() if isinstance(n, Widget))
    bidi.session.select(widget, origin="tree")
    _settle(bidi.root)
    inspector = bidi.shell.inspector
    editor = inspector._editors["field:id"]
    assert inspector.commit(editor, "other")
    assert bidi.session.dirty
    bidi.exporter.start()
    _settle(bidi.root)
    _check(_dialog_texts(bidi))
    assert errors == []


def test_recovery_location_and_discard_question_escape_the_path(
    app: Any,
    tmp_path: Path,
    errors: list[str],
) -> None:
    path = str(tmp_path / f"evil{RLO}.ui")
    saved = datetime.datetime.now(datetime.timezone.utc)
    entry = RecoveryEntry(tmp_path, path, f"n{RLO}.ui", saved)
    asked: list[str] = []
    dialog = RecoveryDialog(
        app.root, [entry], restore=lambda *_a: None, confirm=lambda q, _then: asked.append(q)
    )
    try:
        _settle(app.root)
        assert ESCAPED in str(dialog.where.cget("text"))
        dialog.discard()
        assert asked and ESCAPED in asked[0] and RLO not in asked[0]
    finally:
        dialog.close()
    assert errors == []


def test_variable_delete_question_escapes_the_id(
    app: Any,
    tmp_path: Path,
    errors: list[str],
) -> None:
    path = tmp_path / "v.ui"
    body = _BIDI_UI.format(rlo=RLO).replace(f'id="btn_{RLO}gnp"', f'id="btn" bind="v_{RLO}txt"')
    path.write_text(body, encoding="utf-8")
    assert app.open_path(path)
    _settle(app.root)
    panel = app.shell.variables
    asked: list[str] = []
    panel.confirm = lambda question, _then: asked.append(question)
    panel.tree.selection_set(f"v_{RLO}txt")
    panel.delete()
    assert asked and ESCAPED in asked[0] and RLO not in asked[0]
    assert errors == []


# ------------------------------------------------------------------ 10,000-character values
def _long_variable_panel(app: Any, tmp_path: Path, value: str) -> Any:
    path = tmp_path / "long.ui"
    path.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<meta generator="pyguibud" source_locale="en_GB"/>'
        f'<variables><var id="{value}" type="string" default="{value}"/></variables>'
        '<window id="w" kind="main"><layout type="grid"/></window></pyguibud-ui>',
        encoding="utf-8",
    )
    assert app.open_path(path)
    _settle(app.root)
    return app.shell.variables


@pytest.mark.parametrize("length", [10_000, 40_000])
def test_a_long_variable_id_and_default_are_read_only_clips_that_never_commit(
    app: Any,
    tmp_path: Path,
    errors: list[str],
    length: int,
) -> None:
    value = "ü" * length
    panel = _long_variable_panel(app, tmp_path, value)
    started = time.perf_counter()
    panel.tree.selection_set(value)
    _settle(app.root)
    panel._load_row()
    assert time.perf_counter() - started < 1.0
    assert len(panel.id_var.get()) < length and len(panel.default_var.get()) < length
    assert panel.id_entry.instate(["readonly"]) and panel.default_entry.instate(["readonly"])
    depth = app.session.stack.can_undo
    panel._commit_id()
    panel._commit_default()
    assert panel.flush()
    variable = app.session.document.variables[value]
    assert variable.id == value and variable.default == value
    assert app.session.stack.can_undo == depth
    assert errors == []


def test_a_long_window_id_prefills_the_rename_dialog_with_a_clip(
    app: Any,
    errors: list[str],
) -> None:
    done: list[str] = []
    started = time.perf_counter()
    dialog = RenameDialog(app.root, "ü" * 10_000, lambda _t: None, done.append)
    dialog.open()
    _settle(app.root)
    assert time.perf_counter() - started < 1.0
    assert len(dialog.value.get()) <= CANVAS_TEXT_LIMIT + 1
    assert dialog.entry.instate(["readonly"])
    dialog.accept()  # never hands the clip back
    assert done == []
    assert errors == []


# ------------------------------------------------------------------ read-only stays disabled
def test_a_read_only_editor_stays_disabled_when_a_long_value_becomes_short(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    errors: list[str],
) -> None:
    widget = next(n for n in app.session.document.walk() if isinstance(n, Widget))
    monkeypatch.setattr(CommandStack, "read_only", property(lambda _s: True))
    try:
        app.session.select(widget, origin="tree")
        _settle(app.root)
        editor = app.shell.inspector._editors["field:id"]
        assert editor.widget.instate(["readonly"])
        editor.load(replace(editor.field, value="x" * 5_000))
        assert editor.long and editor.widget.instate(["readonly"])
        editor.load(replace(editor.field, value="short"))
        assert not editor.long
        assert editor.widget.instate(["readonly"])
    finally:
        monkeypatch.undo()
    assert errors == []


# ------------------------------------------------------------------ QA-19c-09: no silent trim
@pytest.mark.parametrize("typed", ["user_name2\n", "a\nb"])
def test_qa19c_09_the_variables_tab_refuses_an_id_with_a_newline(
    app: Any, errors: list[str], typed: str
) -> None:
    panel = app.shell.variables
    panel.tree.selection_set("user_name")
    _settle(app.root)
    depth = app.session.stack.can_undo
    panel.id_var.set(typed)
    app.shell.clear_message()
    panel._commit_id()
    _settle(app.root)
    assert set(app.session.document.variables) == {"user_name"}  # never trimmed to an id
    assert app.session.stack.can_undo == depth
    assert "is not a valid id" in app.shell._message  # the inspector's reason
    assert errors == []


def test_qa19c_09_the_rename_dialog_refuses_an_id_with_a_newline(
    app: Any, errors: list[str]
) -> None:
    window = app.session.document.children[0]
    app.session.select(window, origin="tree")
    _settle(app.root)
    app.registry.invoke("document.rename")
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    try:
        dialog.value.set(f"{window.id}2\n")
        dialog.accept()
        _settle(app.root)
        assert not dialog.closed and window.id == "main"
        reason = str(dialog.reason.cget("text"))
        assert "is not a valid id" in reason and dialog.reason.winfo_manager()
        assert RLO not in reason and "\n" not in reason.rstrip()
    finally:
        dialog.close()
    assert errors == []


# ------------------------------------------------------------------ X11 middle-click paste
def test_paste_selection_is_guarded_like_ctrl_v(app: Any, errors: list[str]) -> None:
    import tkinter
    from tkinter import ttk

    top = tkinter.Toplevel(app.root)
    try:
        source, target = ttk.Entry(top), ttk.Entry(top)
        source.pack()
        target.pack()
        _settle(app.root)
        for text, lands in (("9" * (CANVAS_TEXT_LIMIT + 1), False), ("abc", True)):
            source.delete(0, "end")
            source.insert(0, text)
            source.selection_range(0, "end")  # owns PRIMARY (exportselection)
            target.delete(0, "end")
            app.shell.clear_message()
            target.event_generate("<ButtonPress-2>", x=1, y=1)  # ttk's ScanMark
            target.event_generate("<<PasteSelection>>", x=1, y=1)
            _settle(app.root)
            assert (target.get() == text) is lands, target.get()[:20]
            assert (f"at most {CANVAS_TEXT_LIMIT}" in app.shell._message) is not lands
    finally:
        top.destroy()
    assert errors == []


def test_the_status_bar_never_lays_out_a_60000_character_message(
    app: Any, errors: list[str]
) -> None:
    app.shell.show_message("evil " + RLO * 10_000)  # escaped: 60,005 characters
    _settle(app.root)
    assert RLO not in app.shell._message
    assert len(str(app.shell._status.cget("text"))) <= CANVAS_TEXT_LIMIT
    assert errors == []
