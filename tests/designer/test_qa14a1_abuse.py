"""QA pass 1 of Step 14a.1 "Files and properties": abuse cases (spec properties-save-load 14).

Strict xfails carry the finding id (QA-14a1-NN) and fail for the stated reason today; the debugger
flips them. The other tests pin behaviour that held up under abuse.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
import tkinter
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core import (
    XmlIoError,
    default_registry,
    dump_ui,
    read_ui,
    read_ui_bytes,
    validate,
)
from pyguibud.core.commands import CommandStack, SetEvents, SetField, SetProp
from pyguibud.core.diagnostics import Finding
from pyguibud.core.model import Event, GridCell, Prop, Widget
from pyguibud.designer import app as app_module
from pyguibud.designer import screen
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.message import ChoiceDialog, message_dialog
from pyguibud.designer.properties import Field, parse_value
from pyguibud.designer.recovery import RecoverySession
from pyguibud.designer.settings import Settings, load_settings
from tests.designer.test_edit import shown  # noqa: F401 - key events need a focused root

HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"
B = chr(92)  # a backslash, built at run time (shell layers eat literal ones)


# ---------------------------------------------------------------- helpers
def _stack(path: Path = HELLO) -> tuple[Any, CommandStack]:
    document = read_ui(path).document
    return document, CommandStack(document, default_registry(), source="qa")


def _widget(document: Any, class_name: str) -> Widget:
    return next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == class_name)


def _with_canvas(tmp_path: Path) -> Path:
    """hello.ui with its About label replaced by a Canvas (the only colour property)."""
    text = HELLO.read_text(encoding="utf-8")
    start = text.index('<widget class="Label" id="lbl_about">')
    end = text.index("</widget>", start) + len("</widget>")
    canvas = (
        '<widget class="Canvas" id="cnv_art">\n          <pack fill="both"/>\n        </widget>'
    )
    target = tmp_path / "canvas.ui"
    target.write_text(text[:start] + canvas + text[end:], encoding="utf-8")
    return target


def _disk_full(*_a: object, **_k: object) -> None:
    """A stand-in for ``write_ui`` on a full disk."""
    raise XmlIoError(
        "xml.write_failed",
        "The file could not be saved: {reason}",
        source="qa",
        reason="There is not enough space on the disk",
    )


def _settle(root: Any, rounds: int = 5) -> None:
    for _ in range(rounds):
        root.update()


def _status(app: DesignerApp) -> str:
    return str(app.shell._status.cget("text"))


def _dialog(app: DesignerApp) -> Any:
    live = app._live_dialogs()
    assert live, "no dialog is open"
    return live[-1]


def _close_dialogs(app: DesignerApp) -> None:
    for dialog in app._live_dialogs():
        dialog.close()


def _edit(app: DesignerApp, text: str = "Edited") -> None:
    session = app.session
    assert session.stack is not None and session.document is not None
    label = _widget(session.document, "Label")
    assert session.stack.execute(SetProp(label, Prop(name="text", value=text))).accepted


def _select(app: DesignerApp, node: object) -> None:
    app.session.select(node, origin="tree")
    _settle(app.root)


@pytest.fixture
def qa_app(designer_root: Any) -> Iterator[DesignerApp]:
    """An app that persists settings and autosaves into the test's private profile."""
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(designer_root, settings=Settings(), recovery=recovery)
    designer.exits = []  # type: ignore[attr-defined]
    designer.on_exit = lambda: designer.exits.append(True)  # type: ignore[attr-defined]
    yield designer
    _close_dialogs(designer)
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()
    designer_root.update()


@pytest.fixture
def hello(tmp_path: Path) -> Iterator[Path]:
    copy = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, copy)
    yield copy
    if copy.exists():
        os.chmod(copy, stat.S_IWRITE | stat.S_IREAD)


# ================================================================ findings (strict xfails)
@pytest.mark.gui
def test_grid_index_that_tk_refuses_is_refused_by_the_guard(designer_root: Any) -> None:
    """Row 9999 (or column 9998 + span 2) passes the guard and the validator, but Tk's grid
    refuses it: the canvas shows an error card instead of the window and the runtime's
    ``load_ui`` raises ``UiError: row out of bounds`` for the saved file."""
    probe = tkinter.Frame(designer_root)
    try:
        with pytest.raises(tkinter.TclError, match="out of bounds"):
            tkinter.Label(probe).grid(row=9999, column=0)  # Tk's own limit (rows 0..9998)
        with pytest.raises(tkinter.TclError, match="out of bounds"):
            tkinter.Label(probe).grid(row=0, column=9998, columnspan=2)
    finally:
        probe.destroy()
    document, stack = _stack()
    label = _widget(document, "Label")
    assert isinstance(label.placement, GridCell)
    cell = GridCell(row=9999, column=label.placement.column, sticky=label.placement.sticky)
    outcome = stack.execute(SetField(label, "placement", cell))
    assert not outcome.accepted, "row 9999 was accepted though Tk cannot grid it"


def test_colour_names_that_tk_does_not_know_are_refused(tmp_path: Path) -> None:
    """Any ``[A-Za-z][A-Za-z0-9 ]{0,39}`` passes as a colour: 'blurple' or 'transparent' make
    the canvas show an error card and the runtime's ``load_ui`` fail ("unknown color name")."""
    document, stack = _stack(_with_canvas(tmp_path))
    canvas = _widget(document, "Canvas")
    field = Field("prop:background", "Properties", "background", "colour", "")
    assert (
        isinstance(parse_value(field, "blurple"), Finding)
        or not stack.execute(SetProp(canvas, Prop(name="background", value="blurple"))).accepted
    )


_DARK_START = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from tkinter import ttk
    from ttkbootstrap import App
    from pyguibud.designer.app import DesignerApp
    root = App(title="qa")
    root.withdraw()
    app = DesignerApp(root, role="dark")
    app.open_path(Path(sys.argv[1]))
    for _ in range(10):
        root.update()
    style = ttk.Style()
    spin = style.lookup("TSpinbox", "fieldbackground")
    print(spin + "|" + style.lookup("TEntry", "fieldbackground"))
    """
)


@pytest.mark.slow
@pytest.mark.gui
def test_starting_in_the_dark_theme_gives_spinboxes_a_dark_field(tmp_path: Path) -> None:
    """Started in the dark theme (settings or ``--theme dark``), the inspector's Spinboxes keep
    a white field with the dark theme's near-white text: Minimum width/height, Width, Padding,
    Row... are unreadable. A live theme switch fixes it, so this needs a fresh process."""
    env = dict(os.environ, PYGUIBUD_CONFIG_DIR=str(tmp_path / "c"),
               PYGUIBUD_STATE_DIR=str(tmp_path / "s"))  # fmt: skip
    result = subprocess.run(
        [sys.executable, "-c", _DARK_START, str(HELLO)],
        capture_output=True, text=True, timeout=120, env=env, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-500:]
    spin, entry = result.stdout.strip().splitlines()[-1].split("|")
    assert spin == entry, f"TSpinbox field {spin!r} differs from TEntry field {entry!r}"


@pytest.mark.gui
def test_ctrl_z_works_in_the_variables_entries(
    qa_app: DesignerApp,
    hello: Path,
    shown: Any,  # noqa: F811
) -> None:
    """Rename a variable with Enter, then Ctrl+Z without leaving the field: nothing happens
    (neither the stack undo nor a local revert). Spec 3.3 / UAT 14a: Ctrl+Z works everywhere."""
    assert qa_app.open_path(hello)
    panel, document = qa_app.shell.variables, qa_app.session.document
    assert document is not None
    qa_app.shell.side.select(1)  # the Variables tab
    _settle(shown)
    panel._render()
    assert panel.tree is not None
    panel.tree.selection_set("user_name")
    _settle(shown)
    panel.id_entry.focus_force()
    panel.id_var.set("person")
    panel.id_entry.event_generate("<Return>")
    _settle(shown)
    assert list(document.variables) == ["person"]
    panel.id_entry.focus_force()
    panel.id_entry.event_generate("<Control-z>")
    _settle(shown)
    assert "user_name" in document.variables, "Ctrl+Z in the variable's id field did nothing"


@pytest.mark.gui
def test_saving_a_restored_document_detects_changes_made_after_the_crash(
    qa_app: DesignerApp, hello: Path
) -> None:
    """Crash with unsaved work, another program then edits the file, restore, Ctrl+S: the file is
    overwritten without the conflict question (the stamp is taken at restore time). A second
    Ctrl+S also replaces the ``.bak``, so the other program's version is gone for good (A3)."""
    assert qa_app.recovery is not None
    crashed = RecoverySession(qa_app.recovery.root)
    assert crashed.start()
    document, stack = _stack(hello)
    stack.execute(SetProp(_widget(document, "Label"), Prop(name="text", value="CRASHED")))
    assert crashed.snapshot(document, path=hello, name=hello.name) is None
    crashed.close(keep_snapshot=True)  # the process dies; its snapshot stays
    hello.write_bytes(hello.read_bytes().replace(b"Say hello", b"OTHER-PROGRAM"))
    entry = next(e for e in qa_app.recovery.scan_orphans() if e.path == str(hello))
    qa_app.restore(entry, entry.read())
    assert qa_app.session.dirty and qa_app.session.path == hello
    qa_app.save()
    conflict = [d for d in qa_app._live_dialogs() if isinstance(d, ChoiceDialog)]
    assert conflict, "the other program's change was overwritten without a question"


@pytest.mark.gui
def test_text_dialog_ok_on_mixed_labels_keeps_their_texts_and_metadata(
    qa_app: DesignerApp, hello: Path
) -> None:
    """Two Labels with different texts: "..." opens an empty dialog showing the FIRST label's
    context; OK without typing sets "" on both, copies that context onto the other label and
    drops its translator comment (one undoable step, but silent and destructive)."""
    assert qa_app.open_path(hello)
    document = qa_app.session.document
    assert document is not None
    labels = [n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label"]
    before = [n.props["text"] for n in labels]
    qa_app.session.select_many(labels, origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    inspector.special(inspector._editors["prop:text"], "text")
    _settle(qa_app.root)
    _dialog(qa_app).accept()
    _settle(qa_app.root)
    assert [n.props["text"] for n in labels] == before


@pytest.mark.gui
def test_dialog_is_centred_over_a_window_left_of_the_primary_monitor(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``ModalDialog._centre`` clamps with ``max(0, ...)``: over a main window on a monitor left
    of (or above) the primary one, the dialog lands at the primary screen's edge instead."""
    # The desktop of that setup: a 1920 px monitor left of the primary one (the test machine
    # may have a single monitor, and the window below is fake).
    monkeypatch.setattr(screen, "desktop_bounds", lambda _root: (3840, 1080, -1920, 0))
    dialog = message_dialog(designer_root, lambda: "QA")
    placed: list[str] = []
    try:
        fake: Any = SimpleNamespace(  # the main window at x = -1800 on a left monitor
            winfo_rootx=lambda: -1800, winfo_rooty=lambda: 100,
            winfo_width=lambda: 1200, winfo_height=lambda: 800,
        )  # fmt: skip
        dialog.root = fake
        dialog.window.geometry = placed.append  # type: ignore[method-assign, assignment]
        dialog._centre()
    finally:
        dialog.root = designer_root
        del dialog.window.geometry
        dialog.close()
    x = int(placed[-1].split("+")[1])
    assert -1800 <= x < -600, f"dialog placed at {placed[-1]}, far from its window"


def test_a_settings_file_locked_for_a_moment_is_not_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-14a1-08 (minor): a sharing violation while another instance replaces the file is
    treated as corruption: settings renamed to ``.corrupt`` and every preference reset."""
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"language": "de_DE", "theme": "dark"}), encoding="utf-8")
    real_open = Path.open

    def locked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path:
            raise PermissionError(13, "being used by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", locked)
    _settings, message = load_settings(path)
    monkeypatch.setattr(Path, "open", real_open)
    assert message is None and path.exists(), "a transient read error reset the settings"


def test_settings_with_a_utf8_bom_are_read(tmp_path: Path) -> None:
    """QA-14a1-09 (minor): a hand-edited settings.json saved with a BOM (PowerShell
    ``Set-Content -Encoding utf8``) counts as corrupt and every preference is reset."""
    path = tmp_path / "settings.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"language": "de_DE"}).encode())
    settings, message = load_settings(path)
    assert message is None and settings.language == "de_DE"


@pytest.mark.gui
def test_handler_box_clears_its_refusal_when_the_original_is_typed_back(
    qa_app: DesignerApp, hello: Path
) -> None:
    """QA-14a1-10 (minor): after a refused handler, typing the model value back and pressing
    Enter commits nothing (not pending), so the red mark and the old refusal stay (rule C2)."""
    assert qa_app.open_path(hello)
    assert qa_app.session.document is not None
    _select(qa_app, _widget(qa_app.session.document, "Button"))
    box = qa_app.shell.inspector.events.boxes[0]
    original = box.text()
    box.var.set("1abc")
    assert not box.commit_pending()
    box.var.set(original)
    box.commit_pending()
    _settle(qa_app.root)
    assert not str(box.widget.cget("style")).startswith("Invalid")


@pytest.mark.gui
def test_variables_buttons_are_disabled_in_a_read_only_document(
    qa_app: DesignerApp, tmp_path: Path
) -> None:
    """QA-14a1-11 (minor): a newer-MINOR document disables every editor (A20), but the Variables
    panel's Add / Rename / Delete / Bind buttons stay enabled and silently do nothing."""
    newer = tmp_path / "newer.ui"
    newer.write_text(HELLO.read_text(encoding="utf-8").replace('schema_version="1.0"',
                     'schema_version="1.9"'), encoding="utf-8")  # fmt: skip
    assert qa_app.open_path(newer)
    _settle(qa_app.root)
    assert all("disabled" in b.state() for b in qa_app.shell.variables.buttons)


@pytest.mark.gui
def test_a_failed_write_offers_save_as(
    qa_app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-14a1-12 (minor): spec 9.3 step 4 offers "Save as..." after a write error; the message
    has only OK."""
    assert qa_app.open_path(hello)
    _edit(qa_app)

    monkeypatch.setattr(app_module, "write_ui", _disk_full)
    qa_app.save()
    assert len(_dialog(qa_app).buttons) > 1


def test_a_too_large_whole_number_says_it_is_out_of_range() -> None:
    """QA-14a1-13 (minor): "999999999999" is a whole number; the reason says it is not one."""
    field = Field("prop:width", "Properties", "width", "int", "", minimum=0, maximum=10_000)
    reason = parse_value(field, "999999999999")
    assert isinstance(reason, Finding) and "between" in reason.message


def test_the_same_chord_in_two_spellings_is_one_event() -> None:
    """QA-14a1-14 (minor): ``key:Ctrl+S`` and ``key:<Control-s>`` are both accepted on one
    widget, so the generated GUI binds the same chord twice."""
    document, stack = _stack()
    button = _widget(document, "Button")
    events = [*button.events, Event(name="key:Ctrl+S", handler="on_a"),
              Event(name="key:<Control-s>", handler="on_b")]  # fmt: skip
    assert not stack.execute(SetEvents(button, events)).accepted


@pytest.mark.gui
def test_recovery_and_confirm_buttons_have_access_keys(qa_app: DesignerApp, hello: Path) -> None:
    """QA-14a1-15 (minor): spec 16 wants Alt mnemonics on dialog buttons; Restore / Discard /
    Later and the confirmation's Delete / Cancel have none."""
    from pyguibud.designer.dialogs.confirm import ConfirmDialog
    from pyguibud.designer.dialogs.recovery import RecoveryDialog
    from pyguibud.designer.recovery import RecoveryEntry

    entry = RecoveryEntry(
        hello.parent, str(hello), hello.name, __import__("datetime").datetime.now()
    )
    recovery = RecoveryDialog(qa_app.root, [entry], restore=lambda *_a: None,
                              confirm=lambda *_a: None)  # fmt: skip
    confirm = ConfirmDialog(qa_app.root, "?", lambda: None)
    try:
        recovery.retranslate()
        confirm.retranslate()
        underlines = [int(b.cget("underline")) for b, _m in recovery.buttons]
        underlines += [int(confirm.confirm_button.cget("underline"))]
        assert all(u >= 0 for u in underlines)
    finally:
        recovery.close()
        confirm.close()


# ================================================================ what held up
@pytest.mark.parametrize(
    "bad_id",
    ["", "class", "None", "lambda", "vars", "_private", "1abc", "a-b", "x" * 10_000, "\u0430bc"],
    ids=["empty", "class", "None", "lambda", "vars", "_private", "1abc", "a-b", "10000-chars",
         "cyrillic-a"],
)  # fmt: skip
def test_absurd_ids_are_refused(bad_id: str) -> None:
    document, stack = _stack()
    label = _widget(document, "Label")
    before = dump_ui(document)
    outcome = stack.execute(SetField(label, "id", bad_id))
    assert not outcome.accepted and outcome.message
    assert dump_ui(document) == before


def test_duplicate_id_is_refused() -> None:
    document, stack = _stack()
    assert not stack.execute(SetField(_widget(document, "Label"), "id", "btn_greet")).accepted


@pytest.mark.parametrize(
    "text",
    ["\x01ab", "a\x00b", "\ud800", "\ufffe", "W" * 100_001],
    ids=["control", "nul", "surrogate", "ufffe", "100001-chars"],
)
def test_unstorable_text_is_refused(text: str) -> None:
    document, stack = _stack()
    outcome = stack.execute(SetProp(_widget(document, "Label"), Prop(name="text", value=text)))
    assert not outcome.accepted and outcome.message


@pytest.mark.parametrize(
    "text",
    ["W" * 100_000, "\U0001f600 \u00fcn\u00ef", "\u202eevil", "a\r\nb\tc  "],
    ids=["100000-chars", "emoji", "rtl-override", "cr-tab-trailing"],
)
def test_odd_but_storable_text_round_trips(text: str) -> None:
    document, stack = _stack()
    label = _widget(document, "Label")
    assert stack.execute(SetProp(label, Prop(name="text", value=text))).accepted
    again = read_ui_bytes(dump_ui(document), source="qa").document
    assert _widget(again, "Label").props["text"].value == text


@pytest.mark.parametrize(
    ("kind", "text"),
    [("int", "abc"), ("int", "1e400"), ("int", "+5"), ("int", "0x10"), ("int", "\uff11\uff12"),
     ("int", "\u0663"), ("int", "-10001"), ("float", "nan"), ("float", "inf"), ("float", "1e400"),
     ("float", "1,5"), ("colour", "#12345"), ("colour", "rgb(0,0,0)"), ("colour", "#gggggg")],
)  # fmt: skip
def test_grammar_refuses_garbage_numbers_and_colours(kind: str, text: str) -> None:
    field = Field("prop:x", "Properties", "x", kind, "")  # type: ignore[arg-type]
    assert isinstance(parse_value(field, text), Finding)


@pytest.mark.gui
@pytest.mark.parametrize(
    ("name", "content"),
    [("empty.ui", b""), ("binary.ui", bytes(range(256)) * 20), ("script.py", b"import os\n"),
     ("bomb.ui", b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "a"><!ENTITY b "&a;&a;">]>'
                 b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">&b;</pyguibud-ui>'),
     ("major.ui", HELLO.read_bytes().replace(b'schema_version="1.0"', b'schema_version="2.0"')),
     ("trunc.ui", HELLO.read_bytes()[:700]),
     ("utf16.ui", HELLO.read_text(encoding="utf-8").encode("utf-16"))],
)  # fmt: skip
def test_bad_files_are_refused_and_the_document_kept(
    qa_app: DesignerApp, hello: Path, tmp_path: Path, name: str, content: bytes
) -> None:
    assert qa_app.open_path(hello)
    kept = qa_app.session.document
    bad = tmp_path / name
    bad.write_bytes(content)
    assert not qa_app.open_path(bad)
    assert qa_app.session.document is kept
    assert str(_dialog(qa_app).label.cget("text"))


@pytest.mark.gui
def test_a_folder_and_a_huge_sparse_file_are_refused(qa_app: DesignerApp, tmp_path: Path) -> None:
    huge = tmp_path / "huge.ui"
    with huge.open("wb") as stream:
        stream.seek(200 * 1024 * 1024)
        stream.write(b"\0")
    for target in (tmp_path, huge):
        assert not qa_app.open_path(target)
        _close_dialogs(qa_app)


@pytest.mark.gui
@pytest.mark.parametrize(
    "parts", [("", "", "qa-no-server", "share", "x.ui"), ("", "", ".", "PhysicalDrive0"),
              ("", "", "?", "C:", "x.ui")],
)  # fmt: skip
def test_network_and_device_paths_are_never_opened_or_saved(
    qa_app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch, parts: tuple[str, ...]
) -> None:
    path = B.join(parts)
    assert qa_app.open_path(hello)
    assert not qa_app.open_path(Path(path))
    assert "Network and device paths" in str(_dialog(qa_app).label.cget("text"))
    _close_dialogs(qa_app)
    _edit(qa_app)
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: path)
    qa_app.save(as_new=True)
    assert "Network and device paths" in str(_dialog(qa_app).label.cget("text"))
    assert qa_app.session.dirty and qa_app.session.path == hello


@pytest.mark.gui
def test_newer_minor_document_is_fully_read_only(
    qa_app: DesignerApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    newer = tmp_path / "newer.ui"
    newer.write_text(HELLO.read_text(encoding="utf-8").replace('schema_version="1.0"',
                     'schema_version="1.9"'), encoding="utf-8")  # fmt: skip
    assert qa_app.open_path(newer)
    document, stack = qa_app.session.document, qa_app.session.stack
    assert document is not None and stack is not None
    assert "(read-only)" in qa_app.root.title()
    _select(qa_app, _widget(document, "Label"))
    assert "disabled" in qa_app.shell.inspector._editors["prop:text"].widget.state()
    assert not stack.execute(
        SetProp(_widget(document, "Label"), Prop(name="text", value="x"))
    ).accepted
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(tmp_path / "copy.ui"))
    for as_new in (False, True):
        qa_app.save(as_new=as_new)
        assert "read-only" in str(_dialog(qa_app).label.cget("text"))
        _close_dialogs(qa_app)
    assert not (tmp_path / "copy.ui").exists()


@pytest.mark.gui
def test_write_protected_file_turns_save_into_save_as(
    qa_app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    os.chmod(hello, stat.S_IREAD)
    assert qa_app.open_path(hello)
    _edit(qa_app)
    asked: list[str] = []
    monkeypatch.setattr(file_dialogs, "ask_save", lambda _r, name, _f: asked.append(name))
    qa_app.save()
    assert asked == ["hello.ui"] and qa_app.session.dirty


@pytest.mark.gui
def test_write_error_in_the_quit_guard_keeps_everything(
    qa_app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A1/A2: Quit -> Save -> disk full: a message, no exit, still dirty, snapshot kept."""
    assert qa_app.open_path(hello)
    _edit(qa_app)
    assert qa_app.recovery is not None and qa_app.recovery.folder is not None
    qa_app.recovery.autosave(qa_app.session)
    snapshot = qa_app.recovery.folder / "document.ui"
    assert snapshot.exists()

    monkeypatch.setattr(app_module, "write_ui", _disk_full)
    original = hello.read_bytes()
    qa_app.quit()
    _dialog(qa_app).press(0)  # Save
    assert "not enough space" in str(_dialog(qa_app).label.cget("text"))
    assert qa_app.exits == []  # type: ignore[attr-defined]
    assert qa_app.session.dirty and snapshot.exists() and hello.read_bytes() == original


@pytest.mark.gui
def test_typed_text_is_never_lost(qa_app: DesignerApp, hello: Path) -> None:
    """Type without leaving the field, then Save / Quit; an invalid pending number aborts Quit."""
    assert qa_app.open_path(hello)
    assert qa_app.session.document is not None
    _select(qa_app, _widget(qa_app.session.document, "Label"))
    inspector = qa_app.shell.inspector
    inspector._editors["prop:text"].var.set("Typed then saved")
    qa_app.save()
    assert b"Typed then saved" in hello.read_bytes() and not qa_app.session.dirty
    inspector._editors["prop:text"].var.set("Typed then quit")
    qa_app.quit()
    assert "Save the changes" in str(_dialog(qa_app).label.cget("text"))
    _dialog(qa_app).press(2)  # Cancel
    width = inspector._editors["prop:width"]
    width.var.set("abc")
    qa_app.quit()
    assert not qa_app._live_dialogs() and qa_app.exits == []  # type: ignore[attr-defined]
    assert _status(qa_app) == "Not a whole number."
    width.revert()


@pytest.mark.gui
def test_absurd_inspector_values_are_marked_and_explained(qa_app: DesignerApp, hello: Path) -> None:
    assert qa_app.open_path(hello)
    assert qa_app.session.document is not None
    label = _widget(qa_app.session.document, "Label")
    before = dump_ui(qa_app.session.document)
    cases = [("prop:width", "999999999999"), ("prop:width", "-5"), ("place:grid:padx", "-1"),
             ("place:grid:rowspan", "0"), ("field:id", ""), ("field:id", "lbl_about")]  # fmt: skip
    for key, text in cases:
        _select(qa_app, label)
        editor = qa_app.shell.inspector._editors[key]
        editor.var.set(text)
        assert not qa_app.shell.inspector.commit(editor, text), (key, text)
        assert str(editor.widget.cget("style")).startswith("Invalid") and _status(qa_app)
        editor.revert()
    assert dump_ui(qa_app.session.document) == before


@pytest.mark.gui
def test_multi_edit_commit_and_reset_are_one_undo_step(qa_app: DesignerApp, hello: Path) -> None:
    assert qa_app.open_path(hello)
    document, stack = qa_app.session.document, qa_app.session.stack
    assert document is not None and stack is not None
    labels = [n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label"]
    qa_app.session.select_many(labels, origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    assert inspector._editors["prop:text"].field.value is None  # (mixed)
    assert inspector.commit(inspector._editors["prop:width"], "12")
    inspector.reset("prop:width")
    assert stack.undo_text == "Set 'Width' on 2 elements"
    assert [n.props.get("width") for n in labels] == [None, None]
    stack.undo()
    assert [n.props["width"].value for n in labels] == ["12", "12"]


@pytest.mark.gui
def test_variable_abuse_is_refused_and_delete_while_bound_unbinds(
    qa_app: DesignerApp, hello: Path
) -> None:
    assert qa_app.open_path(hello)
    document, stack = qa_app.session.document, qa_app.session.stack
    assert document is not None and stack is not None
    panel = qa_app.shell.variables
    asked: list[str] = []

    def confirm(question: str, then: Callable[[], None]) -> None:
        asked.append(question)
        then()

    panel.confirm = confirm
    panel.add()
    _settle(qa_app.root)
    entry = _widget(document, "Entry")
    original = dump_ui(document)
    for new in ["var1", "class", "vars", "", "1x", "a b", "x" * 200]:
        panel._render()
        assert panel.tree is not None
        panel.tree.selection_set("user_name")
        _settle(qa_app.root)
        panel.id_var.set(new)
        assert not panel.flush(), new
        assert entry.bind == "user_name" and dump_ui(document) == original
    panel._load_row()
    assert panel.tree is not None
    panel.tree.selection_set("user_name")
    _settle(qa_app.root)
    panel.delete()
    assert asked and entry.bind is None and "user_name" not in document.variables
    stack.undo()
    assert _widget(document, "Entry").bind == "user_name"
    assert dump_ui(document) == original


@pytest.mark.parametrize(
    "payload",
    [b"\xff\xfe garbage {{{", b"null", b"[1,2]", b'{"x":"' + b"a" * (300 * 1024) + b'"}',
     b"[" * 100_000 + b"]" * 100_000, b'{"autosave_seconds": 1' + b"0" * 5000 + b"}"],
    ids=["garbage", "null", "list", "over-256KiB", "deep-nesting", "5000-digit-int"],
)  # fmt: skip
def test_corrupt_settings_are_renamed_and_reset(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "settings.json"
    path.write_bytes(payload)
    settings, message = load_settings(path)
    assert message is not None and settings == Settings()
    assert (tmp_path / "settings.json.corrupt").exists()


def test_wrong_types_fall_back_per_key_and_keep_fork_keys(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({
        "language": 5, "theme": ["dark"], "window": {"geometry": 123, "zoomed": "yes"},
        "sashes": {"main": ["a", -5]}, "recent_files": "C:/x", "autosave_seconds": True,
        "fork": {"kept": [1, 2]},
    }), encoding="utf-8")  # fmt: skip
    settings, message = load_settings(path)
    assert message is None
    assert (settings.language, settings.theme, settings.geometry) == (None, None, None)
    assert settings.autosave_seconds == 60 and settings.recent_files == ()
    assert settings.extra["fork"] == {"kept": [1, 2]}


_SIGINT_CHILD = textwrap.dedent(
    """
    import signal, sys, threading, os
    from pathlib import Path
    from pyguibud.core import Widget
    from pyguibud.core.commands import SetProp
    from pyguibud.core.model import Prop
    from pyguibud.designer import app as app_module
    watchdog = threading.Timer(60, lambda: os._exit(99))  # never hang the suite
    watchdog.daemon = True
    watchdog.start()
    mode = sys.argv[2]
    original = app_module.DesignerApp.start

    def start(self, path=None, *, notice=None):
        original(self, path, notice=notice)

        def act():
            if mode == "report":
                dialogs = self._live_dialogs()
                tree = getattr(dialogs[-1], "tree", None) if dialogs else None
                rows = [tree.set(i, "path") for i in tree.get_children()] if tree else []
                print("ROWS", rows, flush=True)
            else:
                doc = self.session.document
                label = next(n for n in doc.walk() if isinstance(n, Widget)
                             and n.class_name == "Label")
                self.session.stack.execute(SetProp(label, Prop(name="text", value="UNSAVED-QA")))
                if mode == "dialog":
                    self.quit()  # the save-changes question is open when Ctrl+C arrives
            self.root.after(300, lambda: signal.raise_signal(signal.SIGINT))

        self.root.after(800, act)

    app_module.DesignerApp.start = start
    sys.exit(app_module.run(None, None, path=Path(sys.argv[1])))
    """
)


@pytest.mark.slow
@pytest.mark.gui
@pytest.mark.parametrize("mode", ["plain", "dialog"])
def test_real_sigint_keeps_a_snapshot_and_the_next_start_offers_it(
    tmp_path: Path, hello: Path, mode: str
) -> None:
    """A16 end to end through ``run()``: Ctrl+C (also with the save question open) exits 130,
    leaves the file untouched and a snapshot that the next start lists."""
    env = dict(os.environ, PYGUIBUD_CONFIG_DIR=str(tmp_path / "c"),
               PYGUIBUD_STATE_DIR=str(tmp_path / "s"))  # fmt: skip
    first = subprocess.run([sys.executable, "-c", _SIGINT_CHILD, str(hello), mode], env=env,
                           capture_output=True, text=True, timeout=90, check=False)  # fmt: skip
    assert first.returncode == 130, first.stderr[-500:]
    snapshots = list((tmp_path / "s" / "recovery").rglob("document.ui"))
    assert len(snapshots) == 1 and b"UNSAVED-QA" in snapshots[0].read_bytes()
    assert b"UNSAVED-QA" not in hello.read_bytes()
    second = subprocess.run([sys.executable, "-c", _SIGINT_CHILD, str(hello), "report"], env=env,
                            capture_output=True, text=True, timeout=90, check=False)  # fmt: skip
    assert second.returncode == 130 and str(hello) in second.stdout.replace(B * 2, B)


def test_two_live_sessions_never_see_each_other_as_orphans(tmp_path: Path) -> None:
    """A8: each instance owns a folder and a lock; a third one lists no orphan."""
    root = tmp_path / "recovery"
    first, second = RecoverySession(root), RecoverySession(root)
    assert first.start() and second.start()
    document, _ = _stack()
    for session in (first, second):
        assert session.snapshot(document, path=HELLO, name="hello.ui") is None
    third = RecoverySession(root)
    try:
        assert third.start() and third.scan_orphans() == []
    finally:
        for session in (first, second, third):
            session.close()


def test_validator_still_judges_a_saved_document_clean() -> None:
    """Sanity: hello.ui is valid, so every refusal above comes from the abuse itself."""
    document = read_ui(HELLO).document
    assert validate(document, default_registry()).ok


# ================================================================ QA pass 2 (after the fixes)
def _crash(recovery_root: Path, path: Path, *, stamp: bool = True) -> None:
    """Leave the snapshot of a dead process: ``path`` with an unsaved Label edit."""
    from pyguibud.designer.files import FileStamp

    document, stack = _stack(path)
    stack.execute(SetProp(_widget(document, "Label"), Prop(name="text", value="CRASHED")))
    dead = RecoverySession(recovery_root)
    assert dead.start()
    if stamp:
        message = dead.snapshot(document, path=path, name=path.name, stamp=FileStamp.of(path))
    else:
        message = dead.snapshot(document, path=path, name=path.name)
    assert message is None
    dead.close(keep_snapshot=True)


def _restore(app: DesignerApp, path: Path) -> None:
    assert app.recovery is not None
    entry = next(e for e in app.recovery.scan_orphans() if e.path == str(path))
    app.restore(entry, entry.read())
    _settle(app.root)


def _labels(app: DesignerApp) -> list[Widget]:
    assert app.session.document is not None
    return [
        n for n in app.session.document.walk() if isinstance(n, Widget) and n.class_name == "Label"
    ]


@pytest.mark.gui
def test_enter_on_an_untouched_mixed_field_changes_nothing(
    qa_app: DesignerApp, hello: Path
) -> None:
    """QA-14a1-18 (minor): two Labels with different texts (or widths); Enter in the untouched
    "(mixed)" field sets "" on every label (a width is reset on every label). Tab and focus-out
    are safe; only Enter commits the empty text. One Ctrl+Z restores it."""
    assert qa_app.open_path(hello)
    labels = _labels(qa_app)
    before = [dict(n.props) for n in labels]
    qa_app.session.select_many(labels, origin="tree")
    _settle(qa_app.root)
    editor = qa_app.shell.inspector._editors["prop:text"]
    assert editor.field.value is None  # (mixed)
    editor._enter()  # type: ignore[attr-defined]  # what <Return> runs
    assert [dict(n.props) for n in labels] == before


@pytest.mark.gui
def test_a_restored_file_that_was_deleted_is_not_called_write_protected(
    qa_app: DesignerApp, hello: Path
) -> None:
    """QA-14a1-19 (minor): the original was deleted after the crash; the restored document is
    titled "(read-only)" with the reason "the file is write-protected". Save turns into Save As,
    which is safe, but the reason is wrong."""
    from pyguibud.designer.files import M_WRITE_PROTECTED

    assert qa_app.recovery is not None
    _crash(qa_app.recovery.root, hello)
    hello.unlink()
    _restore(qa_app, hello)
    assert qa_app.session.dirty
    assert qa_app.session.read_only_reason != M_WRITE_PROTECTED


@pytest.mark.gui
def test_text_dialog_keeps_refused_text(qa_app: DesignerApp, hello: Path) -> None:
    """QA-14a1-20 (minor): text pasted from Word holds vertical tabs (soft line breaks), which a
    .ui file cannot store. OK closes the dialog, the guard refuses, and the typed text is gone."""
    assert qa_app.open_path(hello)
    _select(qa_app, _labels(qa_app)[0])
    inspector = qa_app.shell.inspector
    inspector.special(inspector._editors["prop:text"], "text")
    _settle(qa_app.root)
    dialog = _dialog(qa_app)
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", "Line one\x0bLine two")
    dialog.accept()
    _settle(qa_app.root)
    still_open = any(getattr(d, "text", None) is not None for d in qa_app._live_dialogs())
    kept = "Line one" in inspector._editors["prop:text"].text()
    assert still_open or kept, "the refused multi-line text was lost"


@pytest.mark.gui
def test_undoing_a_variable_rename_keeps_the_variable_selected(
    qa_app: DesignerApp, hello: Path
) -> None:
    """QA-14a1-21 (minor): rename a variable, Ctrl+Z in the id field: the rename is undone but
    the Variables list loses its selection, so the edit row is empty and disabled."""
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
    panel._history(False, panel.id_var, "id")
    _settle(qa_app.root)
    document = qa_app.session.document
    assert document is not None and "user_name" in document.variables
    assert panel.current() == "user_name"


@pytest.mark.gui
def test_every_dialog_button_has_an_access_key(qa_app: DesignerApp) -> None:
    """QA-14a1-22 (minor): spec 16 wants Alt access keys on dialog buttons. New from template
    (Create, Cancel), the text dialog (OK, Cancel), the shortcuts sheet (Close) and Cancel of the
    unsaved-changes question have none (Enter, Esc and Tab still reach them)."""
    from pyguibud.designer.dialogs.new_file import NewFileDialog
    from pyguibud.designer.dialogs.save_changes import save_changes_dialog
    from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
    from pyguibud.designer.dialogs.text import TextDialog

    root = qa_app.root
    dialogs: list[Any] = [
        NewFileDialog(root, lambda _t: True),
        ShortcutsDialog(root, qa_app.registry),
        TextDialog(root, Prop(name="text", value="x"), lambda _p: None, translatable=True),
        save_changes_dialog(root, lambda: "x.ui", save=lambda: None, discard=lambda: None),
    ]
    missing: list[str] = []
    try:
        for dialog in dialogs:
            dialog.retranslate()
            stack = list(dialog.window.winfo_children())
            while stack:
                widget = stack.pop()
                stack.extend(widget.winfo_children())
                if widget.winfo_class() == "TButton" and int(widget.cget("underline")) < 0:
                    missing.append(f"{type(dialog).__name__}: {widget.cget('text')}")
    finally:
        for dialog in dialogs:
            dialog.close()
    assert not missing, missing


# ---------------------------------------------------------------- pass 2: what held up
@pytest.mark.parametrize(
    "colour",
    ["alice blue", "AliceBlue", "ALICEBLUE", "grey50", "gray100", "LightGoldenrod4",
     "light goldenrod yellow", "navy blue", "#ABC", "#AABBCCDDEEFF"],
)  # fmt: skip
def test_tk_colour_spellings_are_accepted(tmp_path: Path, colour: str) -> None:
    document, stack = _stack(_with_canvas(tmp_path))
    prop = Prop(name="background", value=colour)
    assert stack.execute(SetProp(_widget(document, "Canvas"), prop)).accepted


@pytest.mark.parametrize(
    "colour",
    ["blurple", "transparent", "Grey 50", "gray101", "SystemButtonFace", "systemHighlight",
     "#fffffffff", "réd", "rebeccapurple"],
)  # fmt: skip
def test_unknown_or_platform_colours_are_refused(tmp_path: Path, colour: str) -> None:
    document, stack = _stack(_with_canvas(tmp_path))
    prop = Prop(name="background", value=colour)
    outcome = stack.execute(SetProp(_widget(document, "Canvas"), prop))
    assert not outcome.accepted and outcome.message


@pytest.mark.parametrize(
    ("row", "column", "rowspan", "columnspan", "accepted"),
    [(9998, 0, 1, 1, True), (0, 9998, 1, 1, True), (9997, 0, 2, 1, True), (0, 9997, 1, 2, True),
     (9999, 0, 1, 1, False), (0, 9998, 1, 2, False), (9998, 0, 2, 1, False)],
)  # fmt: skip
def test_grid_cells_at_the_tk_limit(
    row: int, column: int, rowspan: int, columnspan: int, accepted: bool
) -> None:
    document, stack = _stack()
    label = _widget(document, "Label")
    cell = GridCell(row=row, column=column, rowspan=rowspan, columnspan=columnspan)
    assert stack.execute(SetField(label, "placement", cell)).accepted is accepted


@pytest.mark.gui
def test_grid_line_of_the_last_cell_draws_and_loads(qa_app: DesignerApp, hello: Path) -> None:
    """Row and column 9998 plus a weight on its grid line: no error card, and the file loads."""
    assert qa_app.open_path(hello)
    label = _labels(qa_app)[0]
    inspector = qa_app.shell.inspector
    for key in ("place:grid:row", "place:grid:column", "line:col:9998:weight"):
        _select(qa_app, label)
        assert inspector.commit(inspector._editors[key], "9998" if "place" in key else "3"), key
    _settle(qa_app.root)
    assert [stage.error for stage in qa_app.shell.canvas.stages] == [None]
    qa_app.save()
    assert read_ui(hello).document is not None


@pytest.mark.gui
@pytest.mark.parametrize("change", ["none", "touch"])
def test_restored_document_of_an_unchanged_file_saves_without_a_question(
    qa_app: DesignerApp, hello: Path, change: str
) -> None:
    assert qa_app.recovery is not None
    _crash(qa_app.recovery.root, hello)
    if change == "touch":  # a new mtime, the same bytes: not a change
        info = hello.stat()
        os.utime(hello, ns=(info.st_atime_ns, info.st_mtime_ns + 5_000_000_000))
    _restore(qa_app, hello)
    qa_app.save()
    assert not qa_app._live_dialogs() and b"CRASHED" in hello.read_bytes()


@pytest.mark.gui
def test_restored_snapshot_without_a_stamp_always_asks(qa_app: DesignerApp, hello: Path) -> None:
    """An old snapshot (no stamp recorded): the first save in place asks Overwrite / Save as."""
    assert qa_app.recovery is not None
    _crash(qa_app.recovery.root, hello, stamp=False)
    _restore(qa_app, hello)
    qa_app.save()
    assert "changed by another program" in str(_dialog(qa_app).label.cget("text"))
    assert b"CRASHED" not in hello.read_bytes()


@pytest.mark.gui
@pytest.mark.parametrize("part", ["context", "comment", "translatable"])
def test_text_dialog_on_mixed_labels_changes_only_the_edited_part(
    qa_app: DesignerApp, hello: Path, part: str
) -> None:
    assert qa_app.open_path(hello)
    labels = _labels(qa_app)
    before = [n.props["text"] for n in labels]
    qa_app.session.select_many(labels, origin="tree")
    _settle(qa_app.root)
    inspector = qa_app.shell.inspector
    inspector.special(inspector._editors["prop:text"], "text")
    _settle(qa_app.root)
    dialog = _dialog(qa_app)
    if part == "translatable":
        dialog.translatable.set(not dialog.translatable.get())
    else:
        getattr(dialog, part).set("QA")
    dialog.accept()
    _settle(qa_app.root)
    after = [n.props["text"] for n in labels]
    for old, new in zip(before, after, strict=True):
        assert new.value == old.value  # every label keeps its own text
        for other in ("context", "comment", "translatable"):
            if other != part:
                assert getattr(new, other) == getattr(old, other)
    expected = not before[0].translatable if part == "translatable" else "QA"
    assert all(getattr(n, part) == expected for n in after)


def test_settings_unreadable_for_the_whole_run_are_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Design choice of QA-14a1-08: still locked at save -> nothing written (this run's change is
    lost); readable again -> the file's values plus this run's preferences, fork keys kept."""
    from pyguibud.designer.settings import save_settings

    path = tmp_path / "settings.json"
    stored = {"language": "fr_FR", "theme": "dark", "autosave_seconds": 120, "fork": {"x": 1},
              "recent_files": [str(tmp_path / "one.ui")]}  # fmt: skip
    path.write_text(json.dumps(stored), encoding="utf-8")
    real_open, locked = Path.open, [True]

    def maybe_locked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self == path and locked[0]:
            raise PermissionError(13, "being used by another process")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", maybe_locked)
    settings, message = load_settings(path)
    assert settings.unread and message is None
    settings.theme = "high_contrast"
    assert not save_settings(settings, path=path)
    locked[0] = False
    assert json.loads(path.read_text(encoding="utf-8")) == stored
    assert save_settings(settings, path=path)
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["theme"] == "high_contrast" and merged["language"] == "fr_FR"
    assert merged["autosave_seconds"] == 120 and merged["fork"] == {"x": 1}
    assert str(tmp_path / "one.ui") in merged["recent_files"]
