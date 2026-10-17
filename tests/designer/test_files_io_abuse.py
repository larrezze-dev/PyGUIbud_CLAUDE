"""Step 19b (frontend half): saving, closing and export abuse (H14, H16-H19, H25, H26).

Disk full and a locked file are simulated by making ``os.replace`` raise for the target; the
dialogs are answered through ``DesignerApp._live_dialogs()`` as in ``test_file_lifecycle``.
"""

from __future__ import annotations

import errno
import os
import shutil
import stat
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.codegen._errors import M_WRITE_FAILED
from pyguibud.core import Widget
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop
from pyguibud.designer import export as ex
from pyguibud.designer import settings as settings_module
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.message import ChoiceDialog
from pyguibud.designer.files import FileStamp
from pyguibud.designer.recovery import RecoverySession
from pyguibud.designer.settings import Settings

HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"


@pytest.fixture
def app(designer_root: Any) -> Iterator[DesignerApp]:
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(designer_root, settings=Settings(), recovery=recovery)
    designer.exits = []  # type: ignore[attr-defined]
    designer.on_exit = lambda: designer.exits.append(True)  # type: ignore[attr-defined]
    yield designer
    designer_root.protocol("WM_DELETE_WINDOW", designer_root.destroy)
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()


@pytest.fixture
def hello(tmp_path: Path) -> Path:
    copy = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, copy)
    return copy


def edit(designer: DesignerApp) -> None:
    session = designer.session
    assert session.stack is not None and session.document is not None
    label = next(
        n for n in session.document.walk() if isinstance(n, Widget) and n.class_name == "Label"
    )
    assert session.stack.execute(SetProp(label, Prop(name="text", value="Edited"))).accepted


def box(designer: DesignerApp) -> ChoiceDialog:
    live = designer._live_dialogs()
    assert live, "no dialog is open"
    assert isinstance(live[-1], ChoiceDialog)
    return live[-1]


def box_text(designer: DesignerApp) -> str:
    return str(box(designer).label.cget("text"))


def fail_replace(monkeypatch: pytest.MonkeyPatch, target: Path, error: OSError) -> None:
    real = os.replace

    def replace(src: Any, dst: Any, *args: Any, **kwargs: Any) -> None:
        if Path(dst) == target:
            raise error
        real(src, dst, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)


# ---------------------------------------------------------------- H14: saving
_LOCKED = PermissionError(errno.EACCES, "The process cannot access the file", None, 32)


@pytest.mark.gui
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (OSError(errno.ENOSPC, "No space left on device"), "No space left on device"),
        (_LOCKED, "The process cannot access the file"),
        (PermissionError(errno.EACCES, "Access is denied"), "Access is denied"),
    ],
    ids=["disk-full", "locked", "denied"],
)
def test_a_failed_write_gives_the_os_reason_and_leaves_everything_intact(
    app: DesignerApp,
    hello: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError,
    reason: str,
) -> None:
    app.open_path(hello)
    original = hello.read_bytes()
    edit(app)
    fail_replace(monkeypatch, hello, error)
    started = time.monotonic()
    app.save()
    assert time.monotonic() - started < 1.5
    assert reason in box_text(app)  # the OS reason, no traceback
    assert hello.read_bytes() == original
    assert (hello.parent / "hello.ui.bak").read_bytes() == original
    assert sorted(p.name for p in hello.parent.iterdir()) == ["hello.ui", "hello.ui.bak"]
    assert app.session.dirty  # the work is still unsaved


@pytest.mark.gui
def test_a_read_only_file_turns_save_into_save_as_and_is_never_touched(
    app: DesignerApp, hello: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = hello.read_bytes()
    hello.chmod(stat.S_IREAD)
    try:
        app.open_path(hello)
        edit(app)
        monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: None)
        app.save()  # asks for another name; the user cancels
        assert hello.read_bytes() == original and app.session.dirty
        target = tmp_path / "copy.ui"
        monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(target))
        app.save()
        assert target.is_file() and app.session.path == target
        assert hello.read_bytes() == original
    finally:
        hello.chmod(stat.S_IWRITE | stat.S_IREAD)


@pytest.mark.gui
def test_save_as_never_replaces_a_file_that_is_not_a_pyguibud_file(
    app: DesignerApp, hello: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("my shopping list", encoding="utf-8")
    app.open_path(hello)
    edit(app)
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(notes))
    app.save(as_new=True)
    assert "'notes.txt' is not a PyGUIbud file" in box_text(app)
    assert notes.read_text(encoding="utf-8") == "my shopping list"
    assert app.session.dirty and app.session.path == hello


@pytest.mark.gui
def test_a_file_changed_by_another_program_asks_and_cancel_keeps_it(
    app: DesignerApp, hello: Path
) -> None:
    app.open_path(hello)
    edit(app)
    hello.write_bytes(hello.read_bytes() + b"\n<!-- other -->\n")
    changed = hello.read_bytes()
    app.save()
    assert "was changed by another program" in box_text(app)
    box(app).press(2)  # Cancel
    assert hello.read_bytes() == changed and app.session.dirty


# ---------------------------------------------------------------- H16: closing
@pytest.mark.gui
def test_every_way_to_close_asks_about_unsaved_changes(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    app.bind_close()
    edit(app)
    root = app.root
    for close in (
        lambda: root.tk.call(root.protocol("WM_DELETE_WINDOW")),  # the X button and Alt+F4
        lambda: app.registry.invoke("file.quit"),  # File > Quit, Ctrl+Q
    ):
        close()
        dialog = box(app)
        assert "hello.ui" in str(dialog.label.cget("text"))
        assert app.exits == []  # type: ignore[attr-defined]
        dialog.close()
    assert app.session.dirty


@pytest.mark.gui
def test_a_settings_failure_at_quit_shows_the_os_reason(
    app: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.start()

    def full(*_a: Any, **_k: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(settings_module, "write_atomic", full)
    app.quit()
    assert "No space left on device" in box_text(app)
    assert app.exits == []  # type: ignore[attr-defined]
    box(app).press(0)  # Quit anyway
    assert app.exits == [True]  # type: ignore[attr-defined]


# ---------------------------------------------------------------- H26: autosave
@pytest.mark.gui
def test_autosave_says_when_it_works_again(
    app: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer import recovery as recovery_module

    app.start()
    assert app.recovery is not None and app.session.document is not None
    real = recovery_module.write_atomic  # type: ignore[attr-defined]

    def full(*_a: Any, **_k: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    def snapshot() -> str | None:
        assert app.recovery is not None and app.session.document is not None
        return app.recovery.snapshot(app.session.document, path=None, name="x")

    monkeypatch.setattr(recovery_module, "write_atomic", full)
    first = snapshot()
    assert first is not None and "Autosave failed: No space left on device" in first
    assert snapshot() is None  # once per streak
    monkeypatch.setattr(recovery_module, "write_atomic", real)
    assert snapshot() == "Autosave works again."
    assert snapshot() is None


# ---------------------------------------------------------------- H17-H19: export wording
@pytest.fixture
def source(tmp_path: Path) -> ex.ExportSource:
    ui = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, ui)
    return ex.ExportSource(ui, False, FileStamp.of(ui))


def refusal(source: ex.ExportSource, output: str, pot: str | None = None) -> ex.Refusal:
    result = ex.export_plan(source, ex.ExportRequest(output, pot))
    assert isinstance(result, ex.Refusal), result
    return result


def test_invalid_characters_and_a_missing_folder_have_their_own_wording(
    source: ex.ExportSource,
) -> None:
    assert source.path is not None
    for name in ("a|b.py", "a?b.py", 'q"x.py', "x.py:evil", "a\x01b.py"):
        if os.name != "nt" and "\x01" not in name:
            continue
        assert refusal(source, name).msgid == ex.M_BAD_CHARS, name
    missing = refusal(source, "nowhere/x.py")
    assert missing.msgid == ex.M_NO_FOLDER
    assert missing.params["folder"] == str(source.path.parent / "nowhere")
    assert "does not exist" in missing.text()


def test_a_locked_generated_file_is_reported_with_the_real_reason(
    source: ex.ExportSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert source.path is not None
    locked = source.path.parent / "hello_ui.py"
    locked.write_text("# Generated by PyGUIbud\n", encoding="utf-8")
    real_open = open

    def deny(file: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
        if Path(file) == locked:
            raise PermissionError(errno.EACCES, "used by another process", None, 32)
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(ex, "open", deny, raising=False)
    result = refusal(source, "hello_ui.py")
    assert result.msgid == M_WRITE_FAILED
    assert "used by another process" in result.text()
    assert "not written by PyGUIbud" not in result.text()


def test_a_template_without_the_pot_suffix_is_a_warning_not_a_refusal(
    source: ex.ExportSource,
) -> None:
    plan = ex.export_plan(source, ex.ExportRequest("hello_ui.py", "locale/hello.txt"))
    assert isinstance(plan, ex.ExportPlan)
    assert [n.msgid for n in plan.notes] == [ex.M_POT_SUFFIX]
    good = ex.export_plan(source, ex.ExportRequest("hello_ui.py", "locale/hello.pot"))
    assert isinstance(good, ex.ExportPlan) and not good.notes
