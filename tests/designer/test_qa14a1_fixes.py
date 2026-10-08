"""Regression tests for the fixes of QA pass 1 of Step 14a.1 (beyond the QA file's own repros)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop, Widget
from pyguibud.designer import screen
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.confirm import ConfirmDialog
from pyguibud.designer.dialogs.message import ChoiceDialog, message_dialog
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.files import FileStamp
from pyguibud.designer.properties import Field, dialog_commands, dialog_prop
from pyguibud.designer.recovery import RecoveryEntry, RecoverySession
from pyguibud.designer.settings import Settings, load_settings, save_settings
from pyguibud.i18n import _
from tests.designer.test_edit import shown  # noqa: F401 - key events need a focused root
from tests.designer.test_qa14a1_abuse import (  # noqa: F401 - fixtures
    HELLO,
    _settle,
    _widget,
    hello,
    qa_app,
)


def _labels(app: DesignerApp) -> list[Widget]:
    document = app.session.document
    assert document is not None
    return [n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label"]


# ---------------------------------------------------------------- 03: dark start
_DARK_STYLES = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from tkinter import ttk
    from ttkbootstrap import App
    from pyguibud.core.model import GridCell, Widget
    from pyguibud.designer.app import DesignerApp
    root = App(title="qa")
    root.withdraw()
    app = DesignerApp(root, role="dark")
    app.open_path(Path(sys.argv[1]))
    document = app.session.document
    cell = next(n for n in document.walk()
                if isinstance(n, Widget) and isinstance(n.placement, GridCell))
    app.session.select(cell, origin="tree")
    shell = app.shell
    for tab in (1, 0):
        shell.side.select(tab)
        shell.inspector.notebook.select(tab)
        for _ in range(5):
            root.update()
    style = ttk.Style()
    def look():
        found, stack = {}, [root]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            if isinstance(widget, ttk.Widget):
                name = str(widget.cget("style")) or widget.winfo_class()
                found[name] = [str(style.lookup(name, option)) for option in
                               ("fieldbackground", "background", "foreground", "bordercolor")]
        return found
    started = look()
    app.set_theme("light"); app.flush_theme(); root.update()
    app.set_theme("dark"); app.flush_theme(); root.update()
    switched = look()
    print([(n, started[n], switched[n]) for n in started if started[n] != switched.get(n)])
    """
)


@pytest.mark.slow
@pytest.mark.gui
def test_a_dark_start_styles_every_designer_widget_like_a_live_switch(tmp_path: Path) -> None:
    """Every live ttk style of the populated designer looks the same after a dark start as after
    a live switch to dark (the switch rebuilds the styles; the start used to miss some)."""
    env = dict(os.environ, PYGUIBUD_CONFIG_DIR=str(tmp_path / "c"),
               PYGUIBUD_STATE_DIR=str(tmp_path / "s"))  # fmt: skip
    result = subprocess.run(
        [sys.executable, "-c", _DARK_STYLES, str(HELLO)],
        capture_output=True, text=True, timeout=120, env=env, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip().splitlines()[-1] == "[]"


# ---------------------------------------------------------------- 04: history keys
@pytest.mark.gui
def test_ctrl_z_in_the_default_field_reverts_typing_then_undoes(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
    shown: Any,  # noqa: F811
) -> None:
    assert qa_app.open_path(hello)
    panel, document = qa_app.shell.variables, qa_app.session.document
    assert document is not None and panel.tree is not None
    qa_app.shell.side.select(1)
    _settle(shown)
    panel._render()
    panel.tree.selection_set("user_name")
    _settle(shown)
    panel.default_entry.focus_force()
    panel.default_var.set("Ada")
    panel.default_entry.event_generate("<Return>")
    _settle(shown)
    assert document.variables["user_name"].default == "Ada"
    panel.default_var.set("Ada Lovelace")  # typed, not committed
    panel.default_entry.focus_force()
    panel.default_entry.event_generate("<Control-z>")
    _settle(shown)
    assert panel.default_var.get() == "Ada"  # the typing went first
    assert document.variables["user_name"].default == "Ada"
    panel.default_entry.event_generate("<Control-z>")
    _settle(shown)
    assert document.variables["user_name"].default == ""  # then the stack's undo
    panel.default_entry.event_generate("<Control-y>")
    _settle(shown)
    assert document.variables["user_name"].default == "Ada"


@pytest.mark.gui
def test_ctrl_z_in_the_events_key_field_clears_it_then_undoes(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
    shown: Any,  # noqa: F811
) -> None:
    assert qa_app.open_path(hello)
    document = qa_app.session.document
    assert document is not None
    button = _widget(document, "Button")
    qa_app.session.select(button, origin="tree")
    _settle(shown)
    events = qa_app.shell.inspector.events
    before = list(button.events)
    events.key_entry.insert(0, "Ctrl+K")
    events.add_key()
    _settle(shown)
    assert len(button.events) == len(before) + 1
    events = qa_app.shell.inspector.events  # the tab was rebuilt
    events.key_entry.insert(0, "Ctrl+J")
    events.key_entry.focus_force()
    events.key_entry.event_generate("<Control-z>")
    _settle(shown)
    assert events.key_entry.get() == ""
    events.key_entry.event_generate("<Control-z>")
    _settle(shown)
    assert list(button.events) == before


# ---------------------------------------------------------------- 05: recovery stamp
def _crash(app: DesignerApp, path: Path, *, stamp: FileStamp | None) -> RecoveryEntry:
    """A dead process's snapshot of ``path`` with an edit, taken with ``stamp``."""
    assert app.recovery is not None
    crashed = RecoverySession(app.recovery.root)
    assert crashed.start()
    from pyguibud.core import default_registry, read_ui
    from pyguibud.core.commands import CommandStack

    document = read_ui(path).document
    stack = CommandStack(document, default_registry(), source="qa")
    stack.execute(SetProp(_widget(document, "Label"), Prop(name="text", value="CRASHED")))
    assert crashed.snapshot(document, path=path, name=path.name, stamp=stamp) is None
    crashed.close(keep_snapshot=True)
    return next(e for e in app.recovery.scan_orphans() if e.path == str(path))


@pytest.mark.gui
def test_a_restored_snapshot_saves_in_place_when_nobody_changed_the_file(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
) -> None:
    entry = _crash(qa_app, hello, stamp=FileStamp.of(hello))
    assert entry.stamp == FileStamp.of(hello)
    qa_app.restore(entry, entry.read())
    qa_app.save()
    assert not [d for d in qa_app._live_dialogs() if isinstance(d, ChoiceDialog)]
    assert b"CRASHED" in hello.read_bytes() and not qa_app.session.dirty


@pytest.mark.gui
def test_a_restored_snapshot_asks_when_the_file_changed_after_the_crash(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
) -> None:
    entry = _crash(qa_app, hello, stamp=FileStamp.of(hello))
    hello.write_bytes(hello.read_bytes().replace(b"Say hello", b"OTHER-PROGRAM"))
    qa_app.restore(entry, entry.read())
    qa_app.save()
    assert [d for d in qa_app._live_dialogs() if isinstance(d, ChoiceDialog)]
    assert b"OTHER-PROGRAM" in hello.read_bytes()


@pytest.mark.gui
def test_autosave_records_the_stamp_of_the_open_file(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
) -> None:
    assert qa_app.open_path(hello) and qa_app.recovery is not None
    label = _widget(qa_app.session.document, "Label")
    assert qa_app.session.stack is not None
    qa_app.session.stack.execute(SetProp(label, Prop(name="text", value="X")))
    assert qa_app.recovery.autosave(qa_app.session) is None
    assert qa_app.recovery.folder is not None
    info = json.loads((qa_app.recovery.folder / "info.json").read_text(encoding="utf-8"))
    stamp = FileStamp.of(hello)
    assert stamp is not None and info["stamp"]["sha256"] == stamp.sha256


@pytest.mark.parametrize(
    "stamp",
    [None, "x", {"size": 1}, {"size": -1, "mtime_ns": 1, "sha256": "0" * 64},
     {"size": True, "mtime_ns": 1, "sha256": "0" * 64}, {"size": 1, "mtime_ns": 1, "sha256": "z"}],
)  # fmt: skip
def test_a_snapshot_without_a_valid_stamp_reads_as_unknown(tmp_path: Path, stamp: object) -> None:
    folder = tmp_path / ("0" * 32)
    folder.mkdir()
    info = {"version": 1, "path": str(tmp_path / "a.ui"), "name": "a.ui", "stamp": stamp}
    if stamp is None:
        del info["stamp"]  # an older snapshot
    (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
    assert RecoveryEntry._of(folder, 0.0).stamp is None
    assert FileStamp.unknown().changed(HELLO)  # what a restore then uses: Save asks


# ---------------------------------------------------------------- 06: text dialog
@pytest.mark.gui
def test_text_dialog_on_mixed_labels_changes_only_the_text(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
) -> None:
    assert qa_app.open_path(hello)
    labels = _labels(qa_app)
    before = [n.props["text"] for n in labels]
    qa_app.session.select_many(labels, origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    inspector.special(inspector._editors["prop:text"], "text")
    _settle(qa_app.root)
    dialog: Any = qa_app._live_dialogs()[-1]
    assert dialog.context.get() == "" and dialog.comment.get() == ""  # mixed: not the first's
    dialog.text.insert("1.0", "Same")
    dialog.accept()
    _settle(qa_app.root)
    assert [n.props["text"] for n in labels] == [replace(p, value="Same") for p in before]
    assert qa_app.session.stack is not None and qa_app.session.stack.undo()
    assert [n.props["text"] for n in labels] == before  # one undo step


def test_dialog_commands_apply_only_changed_parts() -> None:
    field = Field("prop:text", "Properties", "text", "string", None, translatable=True)
    nodes = [
        Widget(class_name="Label", id="a",
               props={"text": Prop(name="text", value="A", translatable=True, context="x")}),
        Widget(class_name="Label", id="b",
               props={"text": Prop(name="text", value="B", translatable=True, comment="c")}),
    ]  # fmt: skip
    start = dialog_prop(nodes, field)
    assert (start.value, start.context, start.comment) == ("", None, None)
    assert dialog_commands(nodes, field, start, start) is None
    command = dialog_commands(nodes, field, start, replace(start, context="new"))
    assert command is not None
    command.apply()
    texts = [n.props["text"] for n in nodes]
    assert [(t.value, t.context, t.comment) for t in texts] == [("A", "new", None),
                                                                 ("B", "new", "c")]  # fmt: skip


# ---------------------------------------------------------------- 07: dialog placement
@pytest.mark.gui
def test_a_dialog_stays_on_a_single_monitor_desktop(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(screen, "desktop_bounds", lambda _root: (1920, 1080, 0, 0))
    dialog = message_dialog(designer_root, lambda: "QA")
    placed: list[str] = []
    try:
        fake: Any = SimpleNamespace(  # a main window hanging off the right edge
            winfo_rootx=lambda: 1800, winfo_rooty=lambda: -400,
            winfo_width=lambda: 1200, winfo_height=lambda: 300,
        )  # fmt: skip
        dialog.root = fake
        dialog.window.geometry = placed.append  # type: ignore[method-assign, assignment]
        dialog._centre()
        width = dialog.window.winfo_reqwidth()
    finally:
        dialog.root = designer_root
        del dialog.window.geometry
        dialog.close()
    _empty, x, y = placed[-1].split("+")
    assert width > 0 and int(x) == 1920 - width and int(y) == 0  # pushed back onto the desktop


# ---------------------------------------------------------------- 08: settings
def _locked(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    real_open = Path.open

    def locked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise PermissionError(13, "being used by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)


def test_an_unread_settings_file_is_not_rewritten_without_a_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    original = json.dumps({"language": "de_DE", "theme": "dark", "fork": 1}).encode()
    path.write_bytes(original)
    with monkeypatch.context() as patch:
        _locked(patch, path)
        settings, message = load_settings(path)
    assert settings.unread and message is None and settings.language is None
    settings.geometry = "800x600+0+0"  # the window layout at Quit is not a preference
    assert save_settings(settings, path=path)
    assert path.read_bytes() == original


def test_an_unread_settings_file_gets_only_the_changed_preference(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "de_DE", "theme": "dark", "fork": 1}), "utf-8")
    with monkeypatch.context() as patch:
        _locked(patch, path)
        settings, _message = load_settings(path)
        settings.language = "fr_FR"
        assert not save_settings(settings, path=path)  # still locked: never replaced blind
    assert json.loads(path.read_text("utf-8"))["language"] == "de_DE"
    assert save_settings(settings, path=path)
    data = json.loads(path.read_text("utf-8"))
    assert (data["language"], data["theme"], data["fork"]) == ("fr_FR", "dark", 1)
    assert not settings.unread and settings.theme == "dark"


def test_a_corrupt_settings_file_is_still_renamed(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf{not json")
    settings, message = load_settings(path)
    assert message is not None and settings == Settings()
    assert path.with_name("settings.json.corrupt").exists()


# ---------------------------------------------------------------- 11/12: read-only, Save as
@pytest.mark.gui
def test_variables_actions_say_why_in_a_read_only_document(
    qa_app: DesignerApp,  # noqa: F811
    tmp_path: Path,
) -> None:
    newer = tmp_path / "newer.ui"
    newer.write_text(HELLO.read_text(encoding="utf-8").replace('schema_version="1.0"',
                     'schema_version="1.9"'), encoding="utf-8")  # fmt: skip
    assert qa_app.open_path(newer)
    panel = qa_app.shell.variables
    posted: list[str] = []
    panel.status = posted.append
    panel.add()
    assert posted and "read-only" in posted[-1]
    assert all(panel.menu.entrycget(i, "state") == "disabled" for i in range(4))


@pytest.mark.gui
def test_save_as_after_a_failed_write_asks_for_a_file(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.designer import app as app_module
    from tests.designer.test_qa14a1_abuse import _disk_full, _edit

    assert qa_app.open_path(hello)
    _edit(qa_app)
    monkeypatch.setattr(app_module, "write_ui", _disk_full)
    asked: list[str] = []
    monkeypatch.setattr(file_dialogs, "ask_save", lambda _r, name, _f: asked.append(name))
    qa_app.save()
    dialog: Any = qa_app._live_dialogs()[-1]
    assert [_(m) for _b, m, _a in dialog.buttons] == ["_OK", "Save _as…"]
    dialog.press(1)
    assert asked == ["hello.ui"] and qa_app.session.dirty


# ---------------------------------------------------------------- 15: access keys
@pytest.mark.gui
def test_alt_letters_press_the_confirm_and_recovery_buttons(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
) -> None:
    confirmed: list[bool] = []
    confirm = ConfirmDialog(qa_app.root, "?", lambda: confirmed.append(True))
    confirm.retranslate()
    letters = {
        str(b.cget("text"))[int(b.cget("underline"))].lower() for b, _m in confirm.access_keys
    }
    assert len(letters) == 2
    confirm._on_alt(SimpleNamespace(char="d"))
    assert confirmed == [True] and confirm.closed

    later: list[bool] = []
    entry = RecoveryEntry(hello.parent, str(hello), hello.name, datetime.now(tz=timezone.utc))
    recovery = RecoveryDialog(
        qa_app.root, [entry], restore=lambda *_a: None, confirm=lambda *_a: None,
        later=lambda: later.append(True),
    )  # fmt: skip
    recovery.retranslate()
    letters = {str(b.cget("text"))[int(b.cget("underline"))].lower() for b, _m in recovery.buttons}
    assert len(letters) == 3
    recovery._on_alt(SimpleNamespace(char="l"))
    assert later == [True] and recovery.closed


@pytest.mark.gui
def test_ctrl_z_in_an_events_handler_box_undoes_the_committed_handler(
    qa_app: DesignerApp,  # noqa: F811
    hello: Path,  # noqa: F811
    shown: Any,  # noqa: F811
) -> None:
    assert qa_app.open_path(hello)
    document = qa_app.session.document
    assert document is not None
    button = _widget(document, "Button")
    qa_app.session.select(button, origin="tree")
    _settle(shown)
    box = qa_app.shell.inspector.events.boxes[0]
    original = box.text()
    box.var.set("on_other")
    assert box.commit_pending()
    _settle(shown)
    assert button.events[0].handler == "on_other" and not box.pending()
    box = qa_app.shell.inspector.events.boxes[0]
    box.widget.focus_force()
    box.widget.event_generate("<Control-z>")
    _settle(shown)
    box = qa_app.shell.inspector.events.boxes[0]
    assert button.events[0].handler == original and box.text() == original
