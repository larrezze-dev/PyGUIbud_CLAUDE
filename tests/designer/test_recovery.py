"""designer.recovery: locks, snapshots, orphans, caps and autosave (spec section 11)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pyguibud.core import Widget, XmlIoError, default_registry, read_ui_string
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop
from pyguibud.designer import recovery
from pyguibud.designer.recovery import MAX_ORPHANS, RecoverySession
from pyguibud.designer.session import DesignerSession

UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Label" id="lbl_a"><cell row="0" column="0"/></widget>
  </window>
</pyguibud-ui>
"""


@pytest.fixture(autouse=True)
def _state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(tmp_path / "config"))


def document(version: str = "1.0"):  # type: ignore[no-untyped-def]
    return read_ui_string(UI.format(version=version)).document


def edited_session(version: str = "1.0") -> DesignerSession:
    session = DesignerSession(default_registry())
    session.open_document(read_ui_string(UI.format(version=version)), path=None)
    if version == "1.0":
        edit(session, "Hi")
    return session


def edit(session: DesignerSession, text: str) -> None:
    assert session.stack is not None and session.document is not None
    label = next(n for n in session.document.walk() if isinstance(n, Widget))
    assert session.stack.execute(SetProp(label, Prop(name="text", value=text))).accepted


def orphan(root: Path, *, name: str = "main.ui", snapshot: bool = True) -> Path:
    """A dead session folder, as a crashed process (or Ctrl+C while dirty) leaves it."""
    dead = RecoverySession(root)
    assert dead.start() and dead.folder is not None
    if snapshot:
        assert dead.snapshot(document(), path=Path(os.path.abspath(name)), name=name) is None
    dead.close(keep_snapshot=True)
    return dead.folder


def test_default_root_is_under_the_state_dir(tmp_path: Path) -> None:
    assert RecoverySession().root == tmp_path / "state" / "recovery"


def test_start_and_close_without_snapshot_removes_the_folder(tmp_path: Path) -> None:
    live = RecoverySession(tmp_path)
    assert live.start() and live.start()
    assert live.folder is not None and (live.folder / "owner.lock").exists()
    live.close()
    assert not live.folder.exists()
    live.close()  # idempotent


def test_normal_close_removes_the_snapshot_too(tmp_path: Path) -> None:
    live = RecoverySession(tmp_path)
    assert live.start() and live.folder is not None
    assert live.snapshot(document(), path=None, name="x") is None
    live.close()  # Quit after "Don't save": nothing is offered next time
    assert not live.folder.exists()
    kept = RecoverySession(tmp_path)
    assert kept.start() and kept.folder is not None
    kept.close(keep_snapshot=True)  # nothing to keep: removed as well
    assert not kept.folder.exists()


def test_live_sessions_are_never_orphans(tmp_path: Path) -> None:
    with RecoverySession(tmp_path) as first, RecoverySession(tmp_path) as second:
        assert first.snapshot(document(), path=None, name="Untitled") is None
        assert second.snapshot(document(), path=None, name="Untitled") is None
        assert first.scan_orphans() == []
        assert second.scan_orphans() == []
        assert first.folder is not None and first.folder.exists()


def test_closed_session_with_snapshot_is_an_orphan(tmp_path: Path) -> None:
    folder = orphan(tmp_path, name="main.ui")
    assert folder.exists()  # Ctrl+C while dirty: the snapshot survives (A16)
    with RecoverySession(tmp_path) as live:
        entries = live.scan_orphans()
        assert [e.folder for e in entries] == [folder]
        entry = entries[0]
        assert entry.name == "main.ui" and entry.path == os.path.abspath("main.ui")
        assert entry.display_name == "main.ui"
        assert entry.read().document.children[0].id == "main"
        assert entry.discard()
        assert not folder.exists()
        assert live.scan_orphans() == []


def test_corrupt_snapshot_and_info_are_tolerated(tmp_path: Path) -> None:
    folder = orphan(tmp_path)
    (folder / "document.ui").write_bytes(b"<not-xml")
    (folder / "info.json").write_bytes(b"[" * 10_000)
    with RecoverySession(tmp_path) as live:
        (entry,) = live.scan_orphans()
        assert entry.name == "Untitled" and entry.path is None
        with pytest.raises(XmlIoError):
            entry.read()  # A7: damaged, only Discard
        assert entry.discard()


def test_info_path_must_be_absolute_and_local(tmp_path: Path) -> None:
    folder = orphan(tmp_path)
    info = {"path": "//srv/share/x.ui", "name": 7}
    (folder / "info.json").write_text(json.dumps(info), encoding="utf-8")
    with RecoverySession(tmp_path) as live:
        (entry,) = live.scan_orphans()
        assert entry.path is None and entry.name == "Untitled"


def test_empty_and_stale_folders_are_removed(tmp_path: Path) -> None:
    past = time.time() - 31 * 86_400
    empty = orphan(tmp_path, snapshot=False)
    empty.mkdir()  # crash after mkdir and lock, before any snapshot
    (empty / "owner.lock").touch()
    os.utime(empty, (past, past))
    starting = tmp_path / ("c" * 32)
    starting.mkdir()  # a peer between creating its lock file and locking it
    (starting / "owner.lock").touch()
    old = orphan(tmp_path)
    os.utime(old / "document.ui", (past, past))
    young = tmp_path / ("a" * 32)
    young.mkdir()  # a peer between its mkdir and its lock: within the grace period
    aged = tmp_path / ("b" * 32)
    aged.mkdir()
    os.utime(aged, (past, past))
    (tmp_path / "not-a-session").mkdir()
    with RecoverySession(tmp_path) as live:
        assert live.scan_orphans() == []
    assert not empty.exists() and not old.exists() and not aged.exists()
    assert young.exists() and starting.exists() and (tmp_path / "not-a-session").exists()


def test_orphans_are_capped_newest_first(tmp_path: Path) -> None:
    folders = [orphan(tmp_path, name=f"f{index}.ui") for index in range(MAX_ORPHANS + 3)]
    for index, folder in enumerate(folders):
        moment = time.time() - 1000 + index
        os.utime(folder / "document.ui", (moment, moment))
    with RecoverySession(tmp_path) as live:
        entries = live.scan_orphans()
    assert len(entries) == MAX_ORPHANS
    assert entries[0].name == f"f{MAX_ORPHANS + 2}.ui"
    assert all(folder.exists() for folder in folders)  # the extra ones wait for later


def test_snapshot_failures_report_once_per_streak(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    broken = RecoverySession(blocker / "recovery")
    assert not broken.start()
    first = broken.snapshot(document(), path=None, name="Untitled")
    assert first is not None and first.startswith("Autosave failed: ")
    assert broken.snapshot(document(), path=None, name="Untitled") is None
    blocker.unlink()  # the state dir becomes available: the next tick retries and succeeds
    assert broken.snapshot(document(), path=None, name="Untitled") is None
    assert broken.folder is not None and (broken.folder / "document.ui").exists()
    broken.close()
    with RecoverySession(tmp_path / "ok") as live:
        assert live.folder is not None
        (live.folder / "document.ui").mkdir()  # os.replace onto a folder fails
        assert live.snapshot(document(), path=None, name="x") is not None
        (live.folder / "document.ui").rmdir()
        assert live.snapshot(document(), path=None, name="x") is None


def test_autosave_policy(tmp_path: Path) -> None:
    with RecoverySession(tmp_path) as live:
        assert live.folder is not None
        snapshot = live.folder / "document.ui"
        clean = DesignerSession(default_registry())
        assert live.autosave(clean) is None and not snapshot.exists()  # no document
        clean.new_from_template("main_window")
        assert live.autosave(clean) is None and not snapshot.exists()  # not dirty
        session = edited_session()
        session.recovery = live
        assert live.autosave(session) is None and snapshot.exists()
        snapshot.unlink()
        assert live.autosave(session) is None and not snapshot.exists()  # unchanged
        edit(session, "Other")
        assert live.autosave(session) is None and snapshot.exists()
        read_only = edited_session(version="1.9")
        live.discard()
        assert read_only.stack is not None and read_only.stack.read_only
        assert live.autosave(read_only, force=True) is None and not snapshot.exists()


def test_session_replacing_the_document_drops_the_snapshot(tmp_path: Path) -> None:
    with RecoverySession(tmp_path) as live:
        assert live.folder is not None
        session = edited_session()
        session.recovery = live
        live.autosave(session)
        assert (live.folder / "document.ui").exists()
        session.close_document()
        assert not (live.folder / "document.ui").exists()
        assert live.folder.exists()


def test_restore_adopts_the_orphan(tmp_path: Path) -> None:
    folder = orphan(tmp_path, name="main.ui")
    with RecoverySession(tmp_path) as live:
        assert live.folder is not None
        (entry,) = live.scan_orphans()
        session = DesignerSession(default_registry())
        session.recovery = live
        path = Path(entry.path) if entry.path else None
        session.open_document(entry.read(), path=path, dirty=True)
        assert session.dirty and session.title.startswith("main.ui*")
        assert live.adopt(entry, session) is None
        assert (live.folder / "document.ui").exists()  # snapshot first...
        assert not folder.exists()  # ...then the orphan goes


_CHILD = """
import os, sys
from pathlib import Path
from pyguibud.core import read_ui_string
from pyguibud.designer.recovery import RecoverySession
session = RecoverySession(Path(sys.argv[1]))
assert session.start()
doc = read_ui_string(sys.argv[2]).document
assert session.snapshot(doc, path=None, name="child") is None
print("ready", flush=True)
sys.stdin.readline()
os._exit(0)  # a crash: no clean-up, the OS drops the lock
"""


def test_lock_across_processes(tmp_path: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(tmp_path), UI.format(version="1.0")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )
    try:
        assert child.stdout is not None and child.stdin is not None
        assert child.stdout.readline().strip() == "ready"
        with RecoverySession(tmp_path) as live:
            assert live.scan_orphans() == []  # alive: never offered
            child.stdin.write("go\n")
            child.stdin.flush()
            assert child.wait(timeout=30) == 0
            (entry,) = live.scan_orphans()
            assert entry.name == "child"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)


def test_lock_error_counts_as_alive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder = orphan(tmp_path)
    with RecoverySession(tmp_path) as live:
        assert live.folder is not None
        monkeypatch.setattr(recovery, "_lock", lambda _handle: False)
        assert live.scan_orphans() == []
    assert folder.exists()
