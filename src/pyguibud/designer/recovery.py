"""Autosave and crash recovery, without Tk (spec ``properties-save-load.md`` section 11).

Each process owns ``state_dir()/recovery/<uuid>/`` and holds an exclusive OS lock on its
``owner.lock`` for its whole life. A folder whose lock can be taken and that holds a
``document.ui`` belongs to a dead process: an orphan, offered for recovery at start-up. Any lock
error counts as "alive", so a folder is never deleted on doubt (risk R5).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import sys
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pyguibud.core import Document, PyGUIbudError, ReadResult, dump_ui, read_ui
from pyguibud.core.errors import format_message
from pyguibud.core.files import is_network_or_device_path
from pyguibud.designer.files import FileStamp, write_atomic
from pyguibud.designer.settings import state_dir
from pyguibud.i18n import N_, _

if sys.platform == "win32":
    import msvcrt
else:  # pragma: no cover - exercised on POSIX CI only
    import fcntl

if TYPE_CHECKING:
    from pyguibud.designer.session import DesignerSession

__all__ = ["MAX_AGE_DAYS", "MAX_ORPHANS", "RecoveryEntry", "RecoverySession"]

_log = logging.getLogger(__name__)

MAX_ORPHANS = 20
MAX_AGE_DAYS = 30
# Translators: {reason} is an error description, often from the operating system.
_M_AUTOSAVE_FAILED = N_("Autosave failed: {reason}")
_M_AUTOSAVE_RECOVERED = N_("Autosave works again.")
_LOCK, _SNAPSHOT, _INFO = "owner.lock", "document.ui", "info.json"
_FOLDER = re.compile(r"[0-9a-f]{32}")
#: A folder without a lock file may be a peer between its ``mkdir`` and its lock.
_GRACE_SECONDS = 120
_MAX_SCAN = 500
_MAX_INFO_BYTES = 64 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}")


def _lock(handle: int) -> bool:
    """Take the exclusive lock without waiting; False when someone else holds it."""
    try:
        if sys.platform == "win32":
            os.lseek(handle, 0, os.SEEK_SET)  # both sides must lock the same byte
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)
        else:  # pragma: no cover - POSIX only; flock (not lockf) also excludes this process
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release(handle: int) -> None:
    with contextlib.suppress(OSError):
        if sys.platform == "win32":
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)
        else:  # pragma: no cover - POSIX only
            fcntl.flock(handle, fcntl.LOCK_UN)
    with contextlib.suppress(OSError):
        os.close(handle)


def _claim(folder: Path) -> int | None:
    """The locked handle of a dead folder, or None when it is (or may be) alive."""
    lock = folder / _LOCK
    if not lock.exists() and _young(folder):
        return None
    try:
        handle = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError:
        return None
    if _lock(handle):
        return handle
    with contextlib.suppress(OSError):
        os.close(handle)
    return None


def _young(folder: Path) -> bool:
    try:
        return time.time() - folder.stat().st_mtime < _GRACE_SECONDS
    except OSError:
        return True


def _remove(folder: Path, handle: int) -> None:
    """Delete a claimed folder: data files first, then release the lock, then the folder."""
    for name in (_SNAPSHOT, _INFO):
        with contextlib.suppress(OSError):
            (folder / name).unlink()
    _release(handle)
    shutil.rmtree(folder, ignore_errors=True)


def _read_info(folder: Path) -> dict[str, object]:
    try:
        with (folder / _INFO).open("rb") as stream:
            data = json.loads(stream.read(_MAX_INFO_BYTES + 1)[:_MAX_INFO_BYTES])
    except (OSError, ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _stamp_info(stamp: FileStamp | None) -> dict[str, object] | None:
    if stamp is None:
        return None
    return {"size": stamp.size, "mtime_ns": stamp.mtime_ns, "sha256": stamp.sha256}


def _stamp_of(info: Mapping[str, object]) -> FileStamp | None:
    """The stamp the file had when it was opened or last saved; None when not recorded."""
    data = info.get("stamp")
    if not isinstance(data, dict):
        return None
    size, mtime, digest = data.get("size"), data.get("mtime_ns"), data.get("sha256")
    if type(size) is not int or type(mtime) is not int or min(size, mtime) < 0:
        return None
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        return None
    return FileStamp(size, mtime, digest)


@dataclass(frozen=True, slots=True)
class RecoveryEntry:
    """An orphan snapshot: the unsaved work of a process that ended without saving."""

    folder: Path
    path: str | None  # the original file, or None for an untitled document
    name: str
    saved_at: datetime
    #: The stamp of ``path`` before the crash (at open or at the last save); None when the
    #: snapshot did not record it (older snapshots): a restore then asks before overwriting.
    stamp: FileStamp | None = None

    @classmethod
    def _of(cls, folder: Path, mtime: float) -> RecoveryEntry:
        info = _read_info(folder)
        path = info.get("path")
        if not (isinstance(path, str) and os.path.isabs(path)) or is_network_or_device_path(path):
            path = None
        name = info.get("name")
        if not isinstance(name, str) or not name or len(name) > 255:
            name = Path(path).name if path else "Untitled"
        when = datetime.fromtimestamp(mtime, tz=timezone.utc)
        return cls(folder, path, name, when, _stamp_of(info) if path else None)

    @property
    def display_name(self) -> str:
        """The name in the current language (only the untitled name is translated)."""
        return _(self.name) if self.name == "Untitled" else self.name

    def read(self) -> ReadResult:
        """Read the snapshot with the hardened reader.

        Raises:
            XmlIoError: the snapshot is damaged (A7): offer only Discard.
        """
        return read_ui(self.folder / _SNAPSHOT)

    def discard(self) -> bool:
        """Delete the orphan; False when its process turned out to be alive."""
        handle = _claim(self.folder)
        if handle is None:
            return False
        _remove(self.folder, handle)
        return True


class RecoverySession:
    """This process's recovery folder, its lock and its snapshots."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else state_dir() / "recovery"
        self.folder: Path | None = None
        self._handle: int | None = None
        self._revision: int | None = None
        self._failing = False
        self._error: str | None = None

    # ------------------------------------------------------------ life cycle
    def start(self) -> bool:
        """Create and lock this process's folder; False (and autosave reports it) on failure."""
        if self._handle is not None:
            return True
        folder = self.root / uuid.uuid4().hex
        try:
            folder.mkdir(parents=True)
            handle = os.open(folder / _LOCK, os.O_RDWR | os.O_CREAT, 0o600)
        except OSError as exc:
            self._error = exc.strerror or str(exc)
            _log.warning("Recovery folder %s unavailable: %s", folder, exc)
            return False
        if not _lock(handle):
            os.close(handle)
            self._error = "lock"
            return False
        self.folder, self._handle, self._error = folder, handle, None
        return True

    def close(self, *, keep_snapshot: bool = False) -> None:
        """Release the lock and remove the folder (a normal Quit).

        ``keep_snapshot=True`` is Ctrl+C with a dirty document (A16): the snapshot stays, and the
        next start offers it.
        """
        if self._handle is None or self.folder is None:
            return
        handle, self._handle = self._handle, None
        if keep_snapshot and (self.folder / _SNAPSHOT).exists():
            _release(handle)
        else:
            _remove(self.folder, handle)

    def __enter__(self) -> RecoverySession:
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------ snapshots
    def snapshot(
        self,
        document: Document,
        *,
        path: Path | None,
        name: str,
        stamp: FileStamp | None = None,
    ) -> str | None:
        """Write ``document`` now; returns ``"Autosave failed: …"`` once per failure streak.

        ``stamp`` is the session's stamp of ``path`` (taken at open or at the last save): a
        restore keeps it, so Save still sees what another program changed after the crash.

        Without a folder (the state dir was unavailable at start-up) every call retries it.
        """
        if self.folder is None:
            self.start()
        reason = self._error if self.folder is None else None
        if self.folder is not None:
            try:
                data = dump_ui(document)
                write_atomic(self.folder / _SNAPSHOT, data)
                info = {
                    "version": 1,
                    "path": None if path is None else os.fspath(path),
                    "name": name,
                    "stamp": _stamp_info(stamp),
                    "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "pid": os.getpid(),
                }
                write_atomic(self.folder / _INFO, json.dumps(info).encode("utf-8"))
            except PyGUIbudError as exc:
                reason = exc.message
            except OSError as exc:
                reason = exc.strerror or str(exc)
        if reason is None:
            was_failing, self._failing = self._failing, False
            # Replaces the "Autosave failed" line in the status bar (QA-15b-16).
            return _(_M_AUTOSAVE_RECOVERED) if was_failing else None
        _log.warning("Autosave failed: %s", reason)
        first, self._failing = not self._failing, True
        return format_message(_M_AUTOSAVE_FAILED, {"reason": reason}) if first else None

    def autosave(self, session: DesignerSession, *, force: bool = False) -> str | None:
        """The timer tick and the Ctrl+C hook: snapshot a dirty, editable, changed document."""
        stack, document = session.stack, session.document
        if stack is None or document is None or stack.read_only or not session.dirty:
            return None
        if not force and session.revision == self._revision:
            return None
        message = self.snapshot(document, path=session.path, name=session.name, stamp=session.stamp)
        if not self._failing:
            self._revision = session.revision
        return message

    def discard(self) -> None:
        """Drop the snapshot (saved, replaced or closed); the folder and its lock stay."""
        self._revision = None
        if self.folder is not None:
            for name in (_SNAPSHOT, _INFO):
                with contextlib.suppress(OSError):
                    (self.folder / name).unlink()

    def adopt(self, entry: RecoveryEntry, session: DesignerSession) -> str | None:
        """After a restore: snapshot into this folder first, then delete the orphan."""
        message = self.autosave(session, force=True)
        if not self._failing:
            entry.discard()
        return message

    # ------------------------------------------------------------ orphans
    def scan_orphans(self) -> list[RecoveryEntry]:
        """The newest :data:`MAX_ORPHANS` orphans; older than 30 days or empty ones go."""
        found: list[RecoveryEntry] = []
        try:
            with os.scandir(self.root) as items:
                folders = [e for e in items if _FOLDER.fullmatch(e.name) and e.is_dir()]
        except OSError:
            return found
        limit = time.time() - MAX_AGE_DAYS * 86_400
        for item in folders[:_MAX_SCAN]:
            folder = Path(item.path)
            if self.folder is not None and folder == self.folder:
                continue
            if not (folder / _SNAPSHOT).exists() and _young(folder):
                continue  # possibly a peer that is still starting: never touch it
            handle = _claim(folder)
            if handle is None:
                continue
            try:
                mtime = (folder / _SNAPSHOT).stat().st_mtime
            except OSError:
                mtime = None
            if mtime is None or mtime < limit:
                _remove(folder, handle)
                continue
            found.append(RecoveryEntry._of(folder, mtime))
            _release(handle)
        found.sort(key=lambda entry: entry.saved_at, reverse=True)
        return found[:MAX_ORPHANS]
