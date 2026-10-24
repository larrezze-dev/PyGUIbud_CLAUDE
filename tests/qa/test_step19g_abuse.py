"""QA abuse pass of Step 19g (final sweep and gate).

Careless and hostile use of what 19g changed, and of the places next to it: bidi/control
characters in every dialog question (not only the six 19f deferred), long values combined with
bidi characters, the Variables panel switching between long and short variables, the Events tab
with a 10,000-character handler, a real newer-MINOR (read-only) file, and the preview rows of
`docs/specs/preview-export.md` §8 that had no test (P8, P10, P11, P12) plus the B15 status text.

Every "no crash" check is real: the Tk callback errors and the ERROR log records are collected
and must stay empty. Open defects are strict ``xfail`` marks named ``QA-19g-NN``; the debugger
removes the mark with the fix.
"""

from __future__ import annotations

import contextlib
import logging
import shutil
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.model import Widget
from pyguibud.core.text import printable
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT
from tests.conftest import BUDGET_FACTOR, reset_root
from tests.designer.fakes import FakeProcess
from tests.designer.test_qa18_abuse import HELLO, _designer, _settle
from tests.designer.test_qa19f_abuse import RLO, _raw, _shown_texts
from tests.designer.test_sweep_19f import _descendants

pytestmark = pytest.mark.gui

ESCAPED = "\\u202e"
_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1">'
    '<meta generator="pyguibud" source_locale="en_GB"/>'
)


def _ui(body: str, variables: str = "", version: str = "1.0") -> str:
    return (
        _HEAD.format(version=version)
        + (f"<variables>{variables}</variables>" if variables else "")
        + body
        + "</pyguibud-ui>"
    )


def _main(inner: str, wid: str = "w") -> str:
    return (
        f'<window id="{wid}" kind="main"><layout type="grid" padding="12" gap="6"/>{inner}</window>'
    )


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings and recovery data go to temporary folders, never the real profile."""
    base = tmp_path_factory.mktemp("profile19g")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))


@pytest.fixture
def root(tk_root: Any) -> Iterator[Any]:
    reset_root(tk_root)
    yield tk_root
    reset_root(tk_root)


@pytest.fixture
def errors(root: Any, caplog: pytest.LogCaptureFixture) -> Iterator[list[str]]:
    """Tk callback errors and ERROR log records seen during the test (must stay empty)."""
    found: list[str] = []
    original = root.report_callback_exception

    def collect(kind: type[BaseException], value: BaseException, _tb: object) -> None:
        found.append(f"{kind.__name__}: {value}")

    root.report_callback_exception = collect
    caplog.set_level(logging.ERROR)
    try:
        yield found
    finally:
        root.report_callback_exception = original
    found += [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.fixture
def app(root: Any, tmp_path: Path) -> Iterator[Any]:
    """The designer, mapped at its minimum size, on a copy of hello.ui."""
    shutil.copy(HELLO, tmp_path / "hello.ui")
    with _designer(root, tmp_path / "hello.ui") as designer:
        yield designer


def _open(app: Any, path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    app.open_path(path)
    _settle(app.root)


def _last_dialog_texts(app: Any) -> list[str]:
    dialogs = app._live_dialogs()
    assert dialogs, "no dialog was shown"
    texts = _shown_texts(dialogs[-1].window)
    for dialog in dialogs:
        dialog.close()
    _settle(app.root)
    return texts


def _select(app: Any, wid: str) -> Any:
    node = next(n for n in app.session.document.walk() if getattr(n, "id", None) == wid)
    app.session.select(node, origin="tree")
    _settle(app.root)
    return node


def _buttons_on_screen(dialog: Any) -> list[str]:
    """Buttons of ``dialog`` whose box is outside the screen (empty when all are visible)."""
    top = dialog.window
    top.update_idletasks()
    width, height = top.winfo_screenwidth(), top.winfo_screenheight()
    lost = []
    for child in _descendants(top):
        if child.winfo_class() == "TButton" and child.winfo_ismapped():
            x, y = child.winfo_rootx(), child.winfo_rooty()
            if not (0 <= x < width and 0 <= y + child.winfo_height() <= height):
                lost.append(str(child.cget("text")))
    return lost


# ================================================================== 1. escaping in questions
_CONTAINER = _main(
    f'<widget class="Frame" id="frm_{RLO}gnp"><cell row="0" column="0"/>'
    '<layout type="pack"/><widget class="Label" id="lbl"><pack/></widget></widget>'
)


def test_qa19g_01_the_delete_container_question_escapes_a_bidi_id(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    _open(app, tmp_path / "c.ui", _ui(_CONTAINER))
    _select(app, f"frm_{RLO}gnp")
    app.registry.invoke("edit.delete")
    _settle(app.root)
    texts = _last_dialog_texts(app)
    assert _raw(texts) == [], texts
    assert errors == []


def test_qa19g_02_the_open_failure_message_escapes_the_file_name(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    path = tmp_path / f"broken{RLO}lmx.ui"
    path.write_text('<?xml version="1.0"?><pyguibud-ui', encoding="utf-8")
    assert not app.open_path(path)
    _settle(app.root)
    texts = _last_dialog_texts(app)
    assert _raw(texts) == [], texts
    assert errors == []


def test_qa19g_03_the_not_a_ui_file_refusal_escapes_the_target_name(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    target = tmp_path / f"notes{RLO}txt.ui"
    target.write_text("hand-written notes, not a .ui file", encoding="utf-8")
    app._save_to(target, None)
    _settle(app.root)
    texts = _last_dialog_texts(app)
    assert target.read_text(encoding="utf-8").startswith("hand-written")  # never replaced
    assert _raw(texts) == [], texts
    assert errors == []


def test_qa19g_04_the_write_failure_message_escapes_the_path(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    target = tmp_path / f"gone{RLO}lmx" / "out.ui"  # a folder that does not exist: a real failure
    app._save_to(target, None)
    _settle(app.root)
    texts = _last_dialog_texts(app)
    assert not target.exists()
    assert _raw(texts) == [], texts
    assert errors == []


# ================================================================== 2. long + bidi questions
_LONG_RLO_ID = "v" + RLO * 10_000


@pytest.mark.parametrize(
    "kind",
    [
        "variable",
        "window",
        "container",
    ],
)
def test_qa19g_09_a_10000_bidi_character_id_in_a_question_opens_fast_and_keeps_the_buttons(
    app: Any, tmp_path: Path, errors: list[str], kind: str
) -> None:
    long_id = _LONG_RLO_ID
    if kind == "variable":
        body = _main(
            f'<widget class="Entry" id="ent" bind="{long_id}"><cell row="0" column="0"/></widget>'
        )
        _open(app, tmp_path / "v.ui", _ui(body, f'<var id="{long_id}" type="string"/>'))
        panel = app.shell.variables
        panel.tree.selection_set(long_id)
        _settle(app.root)
        started = time.perf_counter()
        panel.delete()
    elif kind == "window":
        body = (
            _main("", wid=long_id) + '<window id="d" kind="dialog"><layout type="pack"/></window>'
        )
        _open(app, tmp_path / "w.ui", _ui(body))
        app.session.select(app.session.document.children[0], origin="tree")
        _settle(app.root)
        started = time.perf_counter()
        app.registry.invoke("document.delete")
    else:
        body = _main(
            f'<widget class="Frame" id="{long_id}"><cell row="0" column="0"/>'
            '<layout type="pack"/><widget class="Label" id="lbl"><pack/></widget></widget>'
        )
        _open(app, tmp_path / "c.ui", _ui(body))
        _select(app, long_id)
        started = time.perf_counter()
        app.registry.invoke("edit.delete")
    _settle(app.root)
    elapsed = time.perf_counter() - started
    dialogs = app._live_dialogs()
    assert dialogs, "no question was asked"
    lost = _buttons_on_screen(dialogs[-1])
    texts = _last_dialog_texts(app)
    assert max(map(len, texts)) <= CANVAS_TEXT_LIMIT + 500, max(map(len, texts))  # clipped
    assert elapsed < 10.0 * BUDGET_FACTOR, elapsed  # loose: the length above is the real check
    assert lost == []
    assert _raw(texts) == []
    assert errors == []


# ================================================================== 3. the 19g Variables fix
def _two_variables(app: Any, tmp_path: Path, long: str) -> Any:
    variables = f'<var id="{long}" type="string" default="{long}"/><var id="short" type="string"/>'
    _open(app, tmp_path / "vars.ui", _ui(_main(""), variables))
    return app.shell.variables


def test_qa19g_05_a_short_variable_after_a_long_one_is_editable_again(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    long = "ü" * 10_000
    panel = _two_variables(app, tmp_path, long)
    panel.tree.selection_set(long)
    _settle(app.root)
    assert panel.id_entry.instate(["readonly"])
    panel.tree.selection_set("short")
    _settle(app.root)
    assert panel.id_var.get() == "short"
    assert not panel.id_entry.instate(["readonly"]), "the short variable's id cannot be typed"
    assert not panel.default_entry.instate(["readonly"])
    assert errors == []


def test_qa19g_05_the_stuck_lock_survives_opening_another_document(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    long = "ü" * 10_000
    panel = _two_variables(app, tmp_path, long)
    panel.tree.selection_set(long)
    _settle(app.root)
    _open(app, tmp_path / "other.ui", _ui(_main(""), '<var id="name" type="string"/>'))
    panel = app.shell.variables
    panel.tree.selection_set("name")
    _settle(app.root)
    assert panel.id_var.get() == "name"
    stuck = panel.id_entry.instate(["readonly"])
    xfail_note = "another document's variable cannot be typed either"
    assert not stuck, xfail_note
    assert errors == []


def test_history_keys_and_escape_in_a_long_variable_entry_never_load_the_full_text(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    long = "ü" * 10_000
    panel = _two_variables(app, tmp_path, long)
    panel.tree.selection_set(long)
    _settle(app.root)
    depth = app.session.stack.can_undo
    for entry in (panel.id_entry, panel.default_entry):
        entry.focus_set()
        for sequence in ("<Control-z>", "<Control-y>", "<Escape>", "<Return>", "<FocusOut>"):
            entry.event_generate(sequence)
            _settle(app.root)
            assert len(panel.id_var.get()) <= CANVAS_TEXT_LIMIT
            assert len(panel.default_var.get()) <= CANVAS_TEXT_LIMIT
    assert app.session.stack.can_undo == depth
    variable = app.session.document.variables[long]
    assert variable.id == long and variable.default == long
    assert errors == []


def test_a_long_id_with_a_short_default_still_edits_the_default(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    long = "ü" * 10_000
    _open(app, tmp_path / "v.ui", _ui(_main(""), f'<var id="{long}" type="string" default="a"/>'))
    panel = app.shell.variables
    panel.tree.selection_set(long)
    _settle(app.root)
    assert panel.id_entry.instate(["readonly"]) and not panel.default_entry.instate(["readonly"])
    panel.default_var.set("b")
    panel._commit_default()
    assert app.session.document.variables[long].default == "b"
    app.registry.invoke("edit.undo")
    _settle(app.root)
    assert app.session.document.variables[long].default == "a"
    assert errors == []


def test_qa19g_06_the_rename_dialog_says_why_a_long_id_cannot_be_changed(
    app: Any, errors: list[str]
) -> None:
    from pyguibud.designer.dialogs.rename import RenameDialog

    done: list[str] = []
    dialog = RenameDialog(app.root, "ü" * 10_000, lambda _t: None, done.append)
    dialog.open()
    _settle(app.root)
    try:
        chrome = {"OK", "Cancel", "Id", ""}
        reasons = [t for t in _shown_texts(dialog.window) if t not in chrome]
        dialog.accept()
        _settle(app.root)
        assert done == []  # the clip is never handed back (19g)
        assert reasons, "a read-only clipped id with no word on why it cannot be typed"
    finally:
        if not dialog.closed:
            dialog.close()
    assert errors == []


# ================================================================== 4. Events tab, long handler
def test_qa19g_07_a_10000_character_handler_never_freezes_the_events_tab(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    handler = "ü" * 10_000  # a valid Python identifier
    body = _main(
        '<widget class="Button" id="btn"><cell row="0" column="0"/>'
        f'<event name="command" handler="{handler}"/></widget>'
    )
    _open(app, tmp_path / "h.ui", _ui(body))
    started = time.perf_counter()
    _select(app, "btn")
    inspector = app.shell.inspector
    inspector.notebook.select(inspector.events.frame)
    _settle(app.root)
    elapsed = time.perf_counter() - started
    boxes = inspector.events.editors()
    assert boxes
    assert elapsed < 1.0 * BUDGET_FACTOR, elapsed
    assert all(len(box.var.get()) <= CANVAS_TEXT_LIMIT for box in boxes), "full text in the box"
    assert all(len(v) <= CANVAS_TEXT_LIMIT for b in boxes for v in b.widget.cget("values"))
    assert errors == []


# ================================================================== 5. real read-only file
def test_a_real_newer_minor_file_keeps_every_editor_read_only(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    long = "x" * 5_000
    body = _main(
        f'<widget class="Label" id="lbl_long"><cell row="0" column="0"/><prop name="text">{long}'
        '</prop></widget><widget class="Button" id="btn"><cell row="1" column="0"/>'
        '<prop name="text">short</prop><event name="command" handler="on_go"/></widget>'
    )
    _open(app, tmp_path / "ro.ui", _ui(body, version="1.9"))
    assert app.session.stack.read_only
    for wid in ("lbl_long", "btn", "lbl_long", "btn"):
        _select(app, wid)
        inspector = app.shell.inspector
        for key, editor in inspector._editors.items():
            widget = editor.widget
            if widget is None:
                continue
            assert widget.instate(["readonly"]) or widget.instate(["disabled"]), (wid, key)
        for box in inspector.events.editors():
            assert box.widget.instate(["readonly"]) or box.widget.instate(["disabled"])
    depth = app.session.stack.can_undo
    assert app.shell.inspector.flush()
    assert app.session.stack.can_undo == depth
    assert errors == []


# ================================================================== 6. preview rows P8-P12, B15
@pytest.fixture
def children(app: Any) -> Iterator[list[FakeProcess]]:
    started: list[FakeProcess] = []

    def popen(argv: list[str], *, cwd: Path, **_options: Any) -> FakeProcess:
        started.append(FakeProcess(argv, Path(cwd)))
        return started[-1]

    app.preview.runner.popen = popen
    yield started
    app.preview.dispose()


def _folders_now() -> set[Path]:
    import tempfile

    return set(Path(tempfile.gettempdir()).glob("pyguibud-preview-*"))


def test_p12_no_python_interpreter_is_refused_with_its_reason(
    app: Any, children: list[FakeProcess], monkeypatch: pytest.MonkeyPatch, errors: list[str]
) -> None:
    before = _folders_now()
    monkeypatch.setattr(sys, "executable", "")
    app.preview.run()
    assert children == []
    assert app.shell._message == "The preview cannot start: no Python interpreter was found."
    assert _folders_now() <= before
    assert errors == []


def test_p11_a_denied_temporary_folder_is_refused_with_the_os_reason(
    app: Any, children: list[FakeProcess], monkeypatch: pytest.MonkeyPatch, errors: list[str]
) -> None:
    from pyguibud.designer import preview_tk

    def denied(_prefix: str) -> Path:
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(preview_tk, "make_temp_dir", denied)
    app.preview.run()
    assert children == []
    assert app.shell._message == "The preview needs a temporary folder: Access is denied."
    assert app.preview.state.phase == "idle"
    assert errors == []


def test_qa19g_08_a_vanished_interpreter_is_not_called_a_temporary_folder_problem(
    app: Any, children: list[FakeProcess], monkeypatch: pytest.MonkeyPatch, errors: list[str]
) -> None:
    """sys.executable set, but the file is gone (a deleted venv): Popen raises FileNotFoundError."""

    def missing(argv: list[str], **_options: Any) -> FakeProcess:
        raise FileNotFoundError(2, "The system cannot find the file specified")

    app.preview.runner.popen = missing
    before = _folders_now()
    app.preview.run()
    assert app.preview.state.phase == "idle" and _folders_now() <= before
    assert "temporary folder" not in app.shell._message, app.shell._message
    assert errors == []


def test_p8_a_clean_newer_minor_file_previews_from_its_file(
    app: Any, children: list[FakeProcess], tmp_path: Path, errors: list[str]
) -> None:
    path = tmp_path / "ro.ui"
    path.write_bytes(HELLO.read_bytes().replace(b'schema_version="1.0"', b'schema_version="1.9"'))
    assert app.open_path(path)
    assert app.session.stack.read_only
    app.preview.run()
    assert len(children) == 1 and str(path) in children[0].argv
    assert errors == []


def test_p8_a_newer_minor_file_changed_on_disk_is_refused_with_the_reason(
    app: Any, children: list[FakeProcess], tmp_path: Path, errors: list[str]
) -> None:
    import os

    path = tmp_path / "ro.ui"
    path.write_bytes(HELLO.read_bytes().replace(b'schema_version="1.0"', b'schema_version="1.9"'))
    assert app.open_path(path)
    stat = os.stat(path)
    path.write_bytes(path.read_bytes() + b"\n")
    os.utime(path, (stat.st_atime, stat.st_mtime + 60))
    before = _folders_now()
    app.preview.run()
    assert children == []
    assert app.shell._message  # the reason dump_ui gives for a newer MINOR
    assert "1.9" in app.shell._message or "newer" in app.shell._message.lower()
    assert _folders_now() <= before
    assert errors == []


@pytest.mark.slow
def test_p10_ten_thousand_widgets_start_a_preview_quickly(
    app: Any, children: list[FakeProcess], tmp_path: Path, errors: list[str]
) -> None:
    rows = "".join(
        f'<widget class="Label" id="l{i}"><cell row="{i // 4}" column="{i % 4}"/>'
        f'<prop name="text">{i}</prop></widget>'
        for i in range(10_000)
    )
    path = tmp_path / "big.ui"
    path.write_text(_ui(_main(rows)), encoding="utf-8")
    assert app.open_path(path)
    _settle(app.root)
    _select(app, "l5")
    app.shell.inspector.commit(app.shell.inspector._editors["prop:text"], "dirty")  # a snapshot
    started = time.perf_counter()
    app.preview.run()
    elapsed = time.perf_counter() - started
    assert len(children) == 1
    assert elapsed < 5.0 * BUDGET_FACTOR, elapsed
    assert errors == []


def test_b15_a_backend_failure_reaches_the_status_bar_with_its_reason(
    app: Any, children: list[FakeProcess], errors: list[str]
) -> None:
    app.preview.run()
    message = "The backend 'acme' failed to load: boom."
    children[0].end(1, {"code": "runtime.backend_failed", "message": message})
    app.preview.runner._poll()
    _settle(app.root)
    shown = [app.shell._message, *(" ".join(_shown_texts(d.window)) for d in app._live_dialogs())]
    for dialog in app._live_dialogs():
        dialog.close()
    assert any(message in text for text in shown), shown
    assert errors == []


def test_b15_a_bidi_backend_message_is_escaped_in_the_status_bar(
    app: Any, children: list[FakeProcess], errors: list[str]
) -> None:
    app.preview.run()
    children[0].end(1, {"code": "runtime.backend_failed", "message": f"evil {RLO}gnp.exe"})
    app.preview.runner._poll()
    _settle(app.root)
    for dialog in app._live_dialogs():
        dialog.close()
    status = str(app.shell._status.cget("text"))
    assert status == printable(status)
    assert errors == []


# ================================================================== 7. storms on the 19g dialogs
def test_rapid_returns_on_the_escaped_save_changes_question_run_one_answer(
    app: Any, errors: list[str]
) -> None:
    from pyguibud.designer.dialogs.save_changes import save_changes_dialog

    saved: list[int] = []
    dialog = save_changes_dialog(app.root, lambda: f"a{RLO}b.ui", save=lambda: saved.append(1),
                                 discard=lambda: None)  # fmt: skip
    dialog.open()
    _settle(app.root)
    for _ in range(20):
        with contextlib.suppress(Exception):
            dialog.window.event_generate("<Return>")
    _settle(app.root)
    assert saved == [1] and dialog.closed
    assert errors == []


def test_language_storm_with_the_escaped_recovery_dialog_open(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    import datetime

    from pyguibud import i18n
    from pyguibud.designer.dialogs.recovery import RecoveryDialog
    from pyguibud.designer.recovery import RecoveryEntry

    saved = datetime.datetime.now(datetime.timezone.utc)
    entry = RecoveryEntry(tmp_path, str(tmp_path / f"e{RLO}.ui"), f"n{RLO}.ui", saved)
    dialog = RecoveryDialog(app.root, [entry], restore=lambda *_a: None,
                            confirm=lambda _q, _t: None)  # fmt: skip
    try:
        for code in (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE, "en_GB"):
            app.set_language(code)
            _settle(app.root)
            where = str(dialog.where.cget("text"))
            assert RLO not in where and ESCAPED in where, (code, where)
    finally:
        dialog.close()
        app.set_language("en_GB")
    assert errors == []


def test_widget_inspector_untouched_by_a_bidi_text_prop(app: Any, errors: list[str]) -> None:
    """Guard: the 19g lock flag never leaks to a writable document's next selection."""
    widget = next(n for n in app.session.document.walk() if isinstance(n, Widget))
    app.session.select(widget, origin="tree")
    _settle(app.root)
    editor = app.shell.inspector._editors["field:id"]
    assert not editor.locked and not editor.widget.instate(["readonly"])
    assert errors == []


def test_p9_exporting_a_components_only_document_says_there_is_nothing_to_generate(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    root_dir = Path(__file__).resolve().parents[2]
    path = tmp_path / f"part{RLO}x.ui"
    path.write_bytes((root_dir / "tests/codegen/data/part.ui").read_bytes())
    assert app.open_path(path)
    _settle(app.root)
    app.exporter.start()
    _settle(app.root)
    dialogs = app._live_dialogs()
    shown = [app.shell._message]
    if dialogs:
        dialog = dialogs[-1]
        if hasattr(dialog, "accept"):
            dialog.accept()
            _settle(app.root)
        shown += [t for d in app._live_dialogs() for t in _shown_texts(d.window)]
        for d in app._live_dialogs():
            d.close()
    assert not list(tmp_path.glob("*.py"))
    assert any("no main window or dialog" in t for t in shown), shown
    assert _raw(shown) == [], shown
    assert errors == []


def test_qa19g_10_a_long_but_valid_variable_default_can_still_be_changed(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    """R80 allows 10,000 characters; the Variables panel offers the inspector's Reset (ruling)."""
    default = "d" * 5_000
    _open(
        app, tmp_path / "d.ui", _ui(_main(""), f'<var id="v" type="string" default="{default}"/>')
    )
    assert not app.session.report().errors  # a valid file
    panel = app.shell.variables
    panel.tree.selection_set("v")
    _settle(app.root)
    assert panel.default_entry.instate(["readonly"]) and panel.reset.winfo_manager()
    assert "Reset" in str(panel.note.cget("text"))  # the reason and the way out
    panel.reset.invoke()
    _settle(app.root)
    assert app.session.document.variables["v"].default == ""
    assert not panel.default_entry.instate(["readonly"]), "a shorter default can be typed now"
    assert not panel.reset.winfo_manager() and not panel.note.winfo_manager()
    app.registry.invoke("edit.undo")
    _settle(app.root)
    assert app.session.document.variables["v"].default == default
    assert panel.default_entry.instate(["readonly"]) and panel.reset.winfo_manager()
    assert errors == []


def test_qa19g_10_a_read_only_document_refuses_the_default_reset(
    app: Any, tmp_path: Path, errors: list[str]
) -> None:
    default = "d" * 5_000
    variables = f'<var id="v" type="string" default="{default}"/>'
    _open(app, tmp_path / "ro.ui", _ui(_main(""), variables, version="1.9"))
    assert app.session.stack.read_only
    panel = app.shell.variables
    panel.tree.selection_set("v")
    _settle(app.root)
    assert panel.reset.winfo_manager() and panel.reset.instate(["disabled"])
    panel.reset_default()  # the key path too: refused with the read-only reason
    _settle(app.root)
    assert app.session.document.variables["v"].default == default
    assert app.shell._message
    assert errors == []
