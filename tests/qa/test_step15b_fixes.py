"""QA regressions of Step 15b: each test names its QA-15b-NN finding (all fixed).

QA-15b-01/02: a folder whose Windows ACL refuses new files made ``tempfile.mkstemp`` retry for
ever (``os.access`` ignores ACLs), so Save, Export, ``pyguibud-uic``, the settings and autosave
hung. The denied folder is simulated portably: ``os.open`` refuses inside it and ``os.access``
says it is writable. The fake stops a retry loop after a few calls, so the unfixed code fails
instead of hanging.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyguibud.codegen._errors import M_WRITE_FAILED
from pyguibud.codegen.output import write_atomic as write_module
from pyguibud.core import XmlIoError, read_ui, write_ui
from pyguibud.designer import export as ex
from pyguibud.designer import preview_tk
from pyguibud.designer.files import FileStamp
from pyguibud.designer.files import write_atomic as write_store
from pyguibud.designer.preview_tk import PreviewRunner
from pyguibud.designer.settings import MAX_EXPORT_PATH, Settings, parse_settings, save_settings
from pyguibud.uic import main as uic_main

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_RETRY_LIMIT = 10
_FAST = 1.0  # seconds: the expected refusal time
_DISPOSE_SECONDS = 1.0 + 1e-9  # the Quit budget of PreviewRunner.dispose


@pytest.fixture
def denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, list[str]]:
    """A folder that refuses new files although ``os.access`` says it is writable."""
    folder = tmp_path / "denied"
    folder.mkdir()
    key = os.path.normcase(str(folder))
    calls: list[str] = []
    real_open: Callable[..., int] = os.open

    def fake_open(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        text = os.path.abspath(os.fspath(path))
        if os.path.normcase(os.path.dirname(text)) == key and flags & os.O_CREAT:
            calls.append(text)
            if len(calls) > _RETRY_LIMIT:
                raise RuntimeError("a refused folder was retried")
            raise PermissionError(errno.EACCES, "Permission denied", text)
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", fake_open)
    monkeypatch.setattr(os, "access", lambda *_args, **_kwargs: True)
    return folder, calls


def _fast(action: Callable[[], object]) -> float:
    start = time.monotonic()
    action()
    return time.monotonic() - start


# ---------------------------------------------------------------- QA-15b-01/02: no endless retry
def test_qa15b_01_save_refuses_a_denied_folder_at_once(denied: tuple[Path, list[str]]) -> None:
    folder, calls = denied
    document = read_ui(EXAMPLES / "hello.ui").document

    def save() -> None:
        with pytest.raises(XmlIoError) as info:
            write_ui(document, folder / "hello.ui")
        assert info.value.code == "xml.write_failed"
        assert "Permission denied" in info.value.message

    assert _fast(save) < _FAST
    assert len(calls) == 1 and list(folder.iterdir()) == []


def test_qa15b_01_the_module_writer_refuses_a_denied_folder_at_once(
    denied: tuple[Path, list[str]],
) -> None:
    folder, calls = denied

    def write() -> None:
        with pytest.raises(PermissionError):
            write_module(str(folder / "form_ui.py"), "x = 1\n")

    assert _fast(write) < _FAST
    assert len(calls) == 1 and list(folder.iterdir()) == []


def test_qa15b_01_settings_and_autosave_refuse_a_denied_folder_at_once(
    denied: tuple[Path, list[str]],
) -> None:
    folder, calls = denied

    def write() -> None:
        with pytest.raises(PermissionError):
            write_store(folder / "snapshot.ui", b"data")
        assert save_settings(Settings(), path=folder / "settings.json") is False

    assert _fast(write) < _FAST
    assert len(calls) == 2 and list(folder.iterdir()) == []


def test_qa15b_02_export_reports_the_os_reason(
    tmp_path: Path, denied: tuple[Path, list[str]]
) -> None:
    folder, calls = denied
    shutil.copy(EXAMPLES / "hello.ui", tmp_path / "hello.ui")
    ui = tmp_path / "hello.ui"
    source = ex.ExportSource(ui, False, FileStamp.of(ui))
    plan = ex.export_plan(source, ex.ExportRequest(str(folder / "hello_ui.py")))
    assert isinstance(plan, ex.ExportPlan), plan.text()  # the folder check is only a hint
    start = time.monotonic()
    outcome = ex.run_export(plan)
    assert time.monotonic() - start < _FAST
    assert outcome.written == () and outcome.failure is not None
    assert outcome.failure.msgid == M_WRITE_FAILED and "Permission denied" in outcome.text()
    assert len(calls) == 1 and list(folder.iterdir()) == []


def test_qa15b_02_uic_reports_the_os_reason(
    tmp_path: Path, denied: tuple[Path, list[str]], capsys: pytest.CaptureFixture[str]
) -> None:
    folder, calls = denied
    shutil.copy(EXAMPLES / "hello.ui", tmp_path / "hello.ui")
    start = time.monotonic()
    assert uic_main([str(tmp_path / "hello.ui"), "-o", str(folder / "hello_ui.py")]) == 1
    assert time.monotonic() - start < 5 * _FAST  # includes generation
    assert "Permission denied" in capsys.readouterr().err
    assert len(calls) == 1 and list(folder.iterdir()) == []


# ---------------------------------------------------------------- QA-15b-03: huge export paths
def test_qa15b_03_over_long_remembered_exports_are_dropped_on_load() -> None:
    huge = "C:\\" + "a" * 200_000
    exports = {
        "k_huge_value": huge,
        "k" * (MAX_EXPORT_PATH + 1): "out.py",
        "k_limit": "b" * MAX_EXPORT_PATH,
        "k_ok": "out.py",
    }
    settings = parse_settings(json.dumps({"exports": exports, "theme": "dark"}).encode())
    assert settings is not None
    assert settings.exports == {"k_limit": "b" * MAX_EXPORT_PATH, "k_ok": "out.py"}
    assert settings.theme == "dark"  # the other keys survive


# ---------------------------------------------------------------- QA-15b-05: run folder leak
class _Root:
    def after(self, _ms: int, _fn: Callable[[], None]) -> str:
        return "after#1"

    def after_cancel(self, _after_id: str) -> None:
        pass


class _Stdin:
    def __init__(self, events: list[object]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("close")


class _HungChild:
    """Ignores the end of stdin; ends only when terminated (unless ``survives``)."""

    def __init__(self, folder: Path, survives: bool = False) -> None:
        self.folder, self.survives = folder, survives
        self.events: list[object] = []
        self.stdin = _Stdin(self.events)
        self.terminated = False

    def poll(self) -> int | None:
        return 1 if self.terminated and not self.survives else None

    def terminate(self) -> None:
        self.events.append("terminate")
        self.terminated = True

    def kill(self) -> None:
        self.events.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        assert timeout is not None and timeout >= 0  # never an unbounded wait
        self.events.append(("wait", timeout, self.folder.exists()))
        code = self.poll()
        if code is None:
            raise subprocess.TimeoutExpired("child", timeout)
        return code


def _runner_with(child_factory: Callable[[Path], _HungChild], folder: Path) -> PreviewRunner:
    runner = PreviewRunner(_Root(), lambda _themes: None, lambda *_args: None)
    runner.popen = lambda *_args, **_kwargs: child_factory(folder)
    runner.start(["child"], folder, wait_ready=False)
    return runner


def test_qa15b_05_a_terminated_child_is_awaited_before_its_folder_goes(tmp_path: Path) -> None:
    folder = tmp_path / "pyguibud-preview-run-x"
    folder.mkdir()
    runner = _runner_with(_HungChild, folder)
    child = runner.process
    assert isinstance(child, _HungChild)
    runner.dispose()
    assert child.events[:3] == ["close", ("wait", preview_tk._QUIT_SECONDS, True), "terminate"]
    last = child.events[3]
    assert isinstance(last, tuple) and last[0] == "wait" and last[2] is True
    waited = sum(e[1] for e in child.events if isinstance(e, tuple))
    assert waited <= _DISPOSE_SECONDS
    assert not folder.exists() and runner.folder is None and runner.process is None


def test_qa15b_05_a_child_surviving_terminate_still_bounds_quit(tmp_path: Path) -> None:
    folder = tmp_path / "pyguibud-preview-run-y"
    folder.mkdir()
    runner = _runner_with(lambda f: _HungChild(f, survives=True), folder)
    child = runner.process
    assert isinstance(child, _HungChild)
    runner.dispose()  # no exception, nothing unbounded
    assert [e for e in child.events if not isinstance(e, tuple)] == ["close", "terminate"]
    assert sum(e[1] for e in child.events if isinstance(e, tuple)) <= _DISPOSE_SECONDS
    assert runner.folder is None


@pytest.mark.skipif(sys.platform != "win32", reason="open files keep a folder only on Windows")
def test_qa15b_05_a_real_hung_child_leaves_no_run_folder(tmp_path: Path) -> None:
    folder = Path(tempfile.mkdtemp(prefix="pyguibud-preview-run-", dir=tmp_path))
    runner = PreviewRunner(_Root(), lambda _themes: None, lambda *_args: None)
    code = "import sys, time; sys.stderr.write('x'); sys.stderr.flush(); time.sleep(60)"
    runner.start([sys.executable, "-c", code], folder, wait_ready=False)
    process = runner.process
    try:
        time.sleep(0.3)  # let it start and hold stderr.txt open
        start = time.monotonic()
        runner.dispose()
        elapsed = time.monotonic() - start
    finally:
        if process.poll() is None:  # pragma: no cover - only if dispose failed
            process.kill()
            process.wait(timeout=10)
    assert not folder.exists()
    assert elapsed <= _DISPOSE_SECONDS + 0.2


def test_qa15b_05_a_briefly_held_folder_is_retried_within_the_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "pyguibud-preview-run-z"
    folder.mkdir()
    runner = _runner_with(_HungChild, folder)
    real_remove = preview_tk._remove
    attempts: list[Path | None] = []

    def held_twice(path: Path | None) -> None:  # a virus scanner holds stderr.txt briefly
        attempts.append(path)
        if len(attempts) > 2:
            real_remove(path)

    monkeypatch.setattr(preview_tk, "_remove", held_twice)
    start = time.monotonic()
    runner.dispose()
    assert time.monotonic() - start < _DISPOSE_SECONDS
    assert len(attempts) == 3 and not folder.exists()


def test_qa15b_05_a_folder_that_stays_held_does_not_block_quit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "pyguibud-preview-run-w"
    folder.mkdir()
    runner = _runner_with(_HungChild, folder)
    monkeypatch.setattr(preview_tk, "_remove", lambda _path: None)
    start = time.monotonic()
    runner.dispose()
    assert time.monotonic() - start <= _DISPOSE_SECONDS + 0.1
    assert folder.exists() and runner.folder is None  # swept after 24 hours (P3)
