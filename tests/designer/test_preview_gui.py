"""Preview menu, runner and controller in the Tk designer, with a fake child (spec 9 "Tk")."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.message import ChoiceDialog
from pyguibud.designer.files import open_document
from pyguibud.designer.preview_tk import PreviewController, sweep_stale
from tests.designer.fakes import FakeProcess

pytestmark = pytest.mark.gui

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def app(shell: DesignerApp, tmp_path: Path) -> Iterator[DesignerApp]:
    shutil.copytree(EXAMPLES, tmp_path / "doc", ignore=shutil.ignore_patterns("__pycache__"))
    opened = open_document(tmp_path / "doc" / "hello.ui")
    shell.session.open_document(opened.result, path=opened.path, stamp=opened.stamp)
    yield shell
    shell.preview.dispose()


@pytest.fixture
def children(app: DesignerApp) -> list[FakeProcess]:
    started: list[FakeProcess] = []

    def popen(argv: list[str], *, cwd: Path, **_options: Any) -> FakeProcess:
        started.append(FakeProcess(argv, Path(cwd)))
        return started[-1]

    app.preview.runner.popen = popen
    return started


def _poll(preview: PreviewController) -> None:
    preview.runner._poll()


def _phase(preview: PreviewController) -> str:
    return preview.state.phase  # read through a call: no narrowing across steps


def test_menus_keys_and_enabled_states(app: DesignerApp, children: list[FakeProcess]) -> None:
    registry = app.registry
    run, close = registry.get("preview.run"), registry.get("preview.close")
    assert run is not None and close is not None
    assert (run.shortcut, close.shortcut, run.icon) == ("F5", "Shift+F5", "preview")
    assert registry.is_enabled(run) and not registry.is_enabled(close)
    rows = {row.label: row.accelerator for row in registry.cheat_sheet()}
    assert rows["Preview"] == "F5" and rows["Close preview"] == "Shift+F5"
    assert app.shell._invoke("preview.run")
    assert registry.is_enabled(close)
    app.session.close_document()  # closing the document closes the preview (4.3)
    assert children[0].stdin.lines == ["quit"]
    assert not registry.is_enabled(run)


def test_f5_starts_the_child_with_the_right_argv_and_reports(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    app.preview.run()
    child = children[0]
    assert child.argv[1:3] == ["-m", "pyguibud.preview"]
    assert child.argv[-2:] == ["--", str(app.session.path)]  # clean: the file itself (D3)
    assert "--window" in child.argv and "--lang" not in child.argv
    assert app.shell._message == "Starting the preview…"
    child.ready()
    _poll(app.preview)
    assert _phase(app.preview) == "running" and app.preview.themes == ["flatly", "darkly"]
    assert app.shell._message.startswith("Preview of 'main' open. Preview: handlers are not")
    child.end(0, {"code": "ok", "message": ""})
    _poll(app.preview)
    assert _phase(app.preview) == "idle" and app.shell._message == "Preview closed."
    assert not child.cwd.exists() and app.preview.runner.after_ids == {}


def test_live_language_and_theme_switches_and_use_theme(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    preview = app.preview
    preview.run()
    children[0].ready()
    _poll(preview)
    assert app.shell._invoke("preview.language.de_DE")
    assert app.settings.preview_lang == "de_DE"
    assert app.shell._invoke("preview.language.document")
    assert app.shell._invoke("preview.language.en_XA")
    assert "pseudo-locale" in app.shell._message
    menu = app.shell.submenus["preview.theme"]
    menu.tk.eval(str(menu.cget("postcommand")))  # what posting the menu runs
    assert menu.index("end") == 2
    menu.invoke(2)  # "Document theme", "flatly", "darkly"
    assert preview.theme == "darkly"
    assert children[0].stdin.lines == ["lang de_DE", "lang -", "lang en_XA", "quit"]
    children[0].end(0, {"code": "ok"})  # trim T4: the theme restarts the preview
    _poll(preview)
    argv = children[1].argv
    assert argv[argv.index("--theme") + 1] == "darkly" and argv[argv.index("--lang") + 1] == "en_XA"
    children[1].ready()
    _poll(preview)
    assert "for the preview only" in app.shell._message
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    assert app.shell._invoke("preview.use_theme")
    assert document.meta.theme == "darkly" and app.session.dirty
    assert "for the preview only" not in app.shell._message  # QA-15a-05: now it matches
    run = app.registry.get("preview.use_theme")
    assert run is not None and not app.registry.is_enabled(run)
    assert app.shell._invoke("edit.undo")
    assert document.meta.theme == "flatly"
    assert "for the preview only" in app.shell._message  # differs again after the undo
    assert app.registry.is_enabled(run)


def test_a_storm_of_f5_gives_one_restart_with_the_latest_document(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    preview = app.preview
    preview.run()
    children[0].ready()
    _poll(preview)
    for _ in range(10):
        preview.run()
    assert len(children) == 1 and children[0].stdin.lines == ["quit"]
    pending = preview._next
    assert pending is not None and pending[1].exists()
    children[0].end(0, {"code": "ok"})
    _poll(preview)
    assert len(children) == 2 and _phase(preview) == "starting"
    assert len(list(pending[1].parent.glob("pyguibud-preview-*"))) >= 1


def test_shift_f5_quits_then_terminates_then_kills(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    preview = app.preview
    preview.run()
    assert app.shell._invoke("preview.close")
    runner = preview.runner
    assert children[0].stdin.lines == ["quit"]
    assert set(runner.after_ids) == {"poll", "terminate", "kill"}
    runner._signal("terminate")
    runner._signal("kill")
    assert children[0].signals == ["terminate", "kill"]
    children[0].end(1, {"code": "runtime.no_display", "message": "No display."})
    _poll(preview)
    assert runner.after_ids == {} and app.shell._message == "Preview closed."  # QA-15a-03


def test_a_crash_shows_the_stderr_tail(app: DesignerApp, children: list[FakeProcess]) -> None:
    app.preview.run()
    children[0].end(3, None, "Traceback\nSystemExit: plugin")
    _poll(app.preview)
    dialog = app._live_dialogs()[-1]
    assert isinstance(dialog, ChoiceDialog)
    dialog.close()


def test_a_child_that_never_gets_ready_is_terminated(
    app: DesignerApp, children: list[FakeProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer import preview_tk

    monkeypatch.setattr(preview_tk, "_TIMEOUT_POLLS", 2)
    app.preview.run()
    _poll(app.preview)
    _poll(app.preview)
    assert children[0].signals == ["terminate"]
    children[0].end(1)
    _poll(app.preview)
    assert app.shell._message == "The preview did not start within 20 seconds."


def test_a_missing_image_refuses_with_the_reason(
    app: DesignerApp, children: list[FakeProcess], tmp_path: Path
) -> None:
    folder = tmp_path / "doc" / "preview"
    (folder / "logo.png").rename(folder / "logo-gone.png")
    assert app.open_path(folder / "with_image.ui")
    app.preview.run()
    assert children == []
    assert app.shell._message.startswith("The document has 1 error. Fix it to preview.")


def test_quit_ends_a_running_child_and_deletes_its_folder(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    app.preview.run()
    children[0].hangs = True
    folder = children[0].cwd
    app.preview.dispose()
    assert children[0].stdin.closed and children[0].signals == ["terminate"]
    assert not folder.exists() and app.preview.runner.after_ids == {}


def test_twenty_start_stop_cycles_leave_nothing_behind(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    preview = app.preview
    for _ in range(20):
        preview.run()
        children[-1].ready()
        _poll(preview)
        preview.close()
        children[-1].end(0, {"code": "ok"})
        _poll(preview)
    assert len(children) == 20 and _phase(preview) == "idle"
    assert preview.runner.after_ids == {} and preview._next is None
    assert not any(child.cwd.exists() for child in children)


def test_stale_private_folders_are_swept(tmp_path: Path) -> None:
    import os
    import time

    old, new = tmp_path / "pyguibud-preview-old", tmp_path / "pyguibud-preview-new"
    for folder in (old, new):
        folder.mkdir()
    os.utime(old, (time.time() - 25 * 3600,) * 2)
    sweep_stale(tmp_path)
    assert not old.exists() and new.exists()


def test_an_old_folder_of_a_running_designer_is_kept(tmp_path: Path) -> None:
    """H27 (QA-15a-06): the pid in the name is checked, not only the age."""
    import os
    import subprocess
    import sys
    import time

    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                           capture_output=True, text=True, check=True)  # fmt: skip
    mine = tmp_path / f"pyguibud-preview-{os.getpid()}-0123abcd"
    gone = tmp_path / f"pyguibud-preview-run-{int(ended.stdout)}-0123abcd"
    for folder in (mine, gone):
        folder.mkdir()
        os.utime(folder, (time.time() - 25 * 3600,) * 2)
    sweep_stale(tmp_path)
    assert mine.exists() and not gone.exists()


def test_a_forged_huge_pid_neither_crashes_nor_removes(tmp_path: Path) -> None:
    import os
    import time

    forged = tmp_path / "pyguibud-preview-9999999999-0123abcd"
    forged.mkdir()
    os.utime(forged, (time.time() - 25 * 3600,) * 2)
    sweep_stale(tmp_path)  # no OverflowError / ctypes.ArgumentError at start-up
    assert forged.exists()


def test_private_folders_carry_the_pid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import tempfile

    from pyguibud.designer.preview_tk import private_folder

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    folder = private_folder("run-")
    assert folder.parent == tmp_path and folder.name.startswith(
        f"pyguibud-preview-run-{os.getpid()}-"
    )


def _pump(root: Any, done: Any, seconds: float = 30.0) -> None:
    import time

    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert done(), "the child did not answer in time"


def test_the_real_child_starts_and_quits(designer_root: Any, tmp_path: Path) -> None:
    """The real ``Popen`` path of F5: options, polling, quit, result and clean-up."""
    from pyguibud.designer.preview import PreparedPreview, child_argv
    from pyguibud.designer.preview_tk import PreviewRunner

    shutil.copytree(EXAMPLES, tmp_path / "doc", ignore=shutil.ignore_patterns("__pycache__"))
    ready: list[list[str]] = []
    exits: list[tuple[Any, ...]] = []
    runner = PreviewRunner(designer_root, ready.append, lambda *args: exits.append(args))
    folder = tmp_path / "private"
    folder.mkdir()
    prepared = PreparedPreview(tmp_path / "doc" / "hello.ui", None, None, "main", None, ())
    runner.start(child_argv(prepared, folder, ui_lang="en_GB", lang="de_DE", theme=None), folder)
    process = runner.process
    try:
        _pump(designer_root, lambda: bool(ready))
        assert "flatly" in ready[0]
        runner.send("lang -")
        runner.stop()
        _pump(designer_root, lambda: bool(exits))
        code, result, tail, timed_out = exits[0]
        assert (code, result, timed_out) == (0, ("ok", ""), False), tail
        assert not folder.exists() and runner.after_ids == {} and runner.process is None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


def test_a_document_without_windows_is_refused(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    from pyguibud.core.xml_io import read_ui_bytes

    empty = b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"><meta/></pyguibud-ui>'
    app.session.open_result(read_ui_bytes(empty), name="empty")
    app.preview.run()
    assert children == [] and app.shell._message == "The document has no window to preview."


# ---------------------------------------------------------------- QA-15a regressions
def test_qa15a_02_an_unknown_window_is_refused_and_leaves_no_folder(
    app: DesignerApp, children: list[FakeProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.core import atomic
    from pyguibud.core.model import Window
    from pyguibud.designer import preview_tk

    made: list[Path] = []
    real = atomic.make_temp_dir

    def make_temp_dir(prefix: str) -> Path:
        made.append(real(prefix))
        return made[-1]

    monkeypatch.setattr(preview_tk, "make_temp_dir", make_temp_dir)
    app.preview.current_window = lambda: Window(id="gone", kind="dialog")
    app.preview.run()
    assert children == [] and app.shell._message == "The document has no window to preview."
    assert made and not any(folder.exists() for folder in made)


def test_qa15a_03_closing_a_hung_child_says_closed(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    app.preview.run()
    assert app.shell._invoke("preview.close")
    app.preview.runner._signal("terminate")
    children[0].end(1, None, "terminated")  # no result.json: killed, not a crash
    _poll(app.preview)
    assert app.shell._message == "Preview closed." and app._live_dialogs() == []


def test_qa15a_04_another_document_forgets_the_theme_override(
    app: DesignerApp, children: list[FakeProcess]
) -> None:
    app.preview.set_theme("darkly")
    assert app.open_path(Path(app.session.path or ""))  # reopen: document_changed
    assert app.preview.theme is None
