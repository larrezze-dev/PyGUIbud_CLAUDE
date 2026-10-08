"""The file lifecycle of the designer, without Tk (spec ``properties-save-load.md`` section 9).

Open, the save decision, conflict stamps, path rebasing on Save As, recent files and the atomic
write used by the settings and recovery stores. The Tk layer asks the questions (file pickers,
confirmations); everything decided here is testable headless.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import os
import stat
import tempfile
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from pyguibud.core import (
    MAX_UI_BYTES,
    Document,
    ImageResource,
    Include,
    PyGUIbudError,
    ReadResult,
    read_ui,
)
from pyguibud.core.commands import Command, Macro, SetField, SetResource
from pyguibud.core.errors import format_message
from pyguibud.core.files import is_network_or_device_path
from pyguibud.i18n import N_, _

__all__ = [
    "MAX_RECENT",
    "M_GONE",
    "M_NETWORK",
    "M_NEWER",
    "M_READ_ONLY",
    "M_WRITE_PROTECTED",
    "SAVE_AS_REASONS",
    "DocumentFile",
    "FileError",
    "FileStamp",
    "RecentFiles",
    "SavePlan",
    "open_document",
    "path_key",
    "read_only_reason",
    "rebase_paths",
    "save_plan",
    "write_atomic",
    "write_protected",
]

#: The length of the File > Open recent list.
MAX_RECENT = 10
M_NETWORK = N_("Network and device paths cannot be opened.")
M_WRITE_PROTECTED = N_("the file is write-protected")
#: A restored snapshot whose original was deleted since: Save asks for a name, nothing is locked.
M_GONE = N_("the file no longer exists")
M_NEWER = N_("it was written by a newer version of PyGUIbud")
#: The reasons that only turn Save into Save As (the document stays editable).
SAVE_AS_REASONS = (M_WRITE_PROTECTED, M_GONE)
# Translators: {reason} is a short reason such as "the file is write-protected".
M_READ_ONLY = N_("This document is read-only: {reason}")
_M_INCLUDED = N_("A document cannot be saved onto a file that it includes.")
_CHUNK = 1 << 20
_REPLACE_RETRIES = 5
_REPLACE_DELAY = 0.05


class FileError(PyGUIbudError):
    """A file action refused before any file access (a network or device path)."""


def path_key(path: str | os.PathLike[str]) -> str:
    """The identity of a local file (real path, case-folded where the system ignores case).

    Never call it on a network path: resolving one contacts the server (R82).
    """
    return os.path.normcase(os.path.realpath(os.fspath(path)))


def write_atomic(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file and a rename.

    Raises:
        OSError: nothing was replaced (the temporary file is removed).
    """
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(_REPLACE_RETRIES + 1):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:  # Windows indexers and antivirus hold files briefly
                if attempt == _REPLACE_RETRIES:
                    raise
                time.sleep(_REPLACE_DELAY)
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(temporary)
        raise


@dataclass(frozen=True, slots=True)
class FileStamp:
    """What a file looked like at open or save time, for the conflict check (section 9.3)."""

    size: int
    mtime_ns: int
    sha256: str

    @classmethod
    def of(cls, path: Path) -> FileStamp | None:
        """The stamp of ``path`` now, or None when it is missing, unreadable or not openable.

        Only regular files up to the reader's size limit are hashed: a FIFO would block and a
        huge file is refused by the reader anyway (A11).
        """
        if is_network_or_device_path(str(path)):
            return None
        try:
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_UI_BYTES:
                return None
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while chunk := stream.read(_CHUNK):
                    digest.update(chunk)
        except OSError:
            return None
        return cls(info.st_size, info.st_mtime_ns, digest.hexdigest())

    @classmethod
    def unknown(cls) -> FileStamp:
        """A stamp that matches no file: the next save in place asks the conflict question.

        For a restored recovery snapshot that did not record the stamp of its file (A3).
        """
        return cls(-1, -1, "")

    def same_stat(self, path: Path) -> bool:
        """True when size and modification time still match (no read: the focus-in check)."""
        try:
            info = path.stat()
        except OSError:
            return False
        return info.st_size == self.size and info.st_mtime_ns == self.mtime_ns

    def changed(self, path: Path) -> bool:
        """True when the content of ``path`` differs from this stamp (a touch is no change)."""
        if self.same_stat(path):
            return False
        now = FileStamp.of(path)
        return now is None or now.sha256 != self.sha256


def read_only_reason(result: ReadResult, path: Path | None) -> str | None:
    """The msgid of why ``result`` may not be saved in place, or None (D11).

    A newer-MINOR document is fully read-only; a write-protected or vanished file only turns
    Save into Save As.
    """
    if result.read_only:
        return M_NEWER
    if path is None:
        return None
    if _vanished(path):
        return M_GONE
    return M_WRITE_PROTECTED if write_protected(path) else None


def _vanished(path: Path) -> bool:
    """True when ``path`` does not exist (any other stat failure is not "gone")."""
    try:
        path.stat()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return False


def write_protected(path: Path) -> bool:
    """True when ``path`` or its folder is not writable, or it has the Windows read-only flag.

    Windows reports most folders as writable, so a protected folder may only show at save time.
    """
    try:
        protected = not os.access(path, os.W_OK) or not os.access(path.parent, os.W_OK)
        attributes = getattr(path.stat(), "st_file_attributes", 0)
        return protected or bool(attributes & getattr(stat, "FILE_ATTRIBUTE_READONLY", 0))
    except OSError:
        return True


@dataclass(frozen=True, slots=True)
class DocumentFile:
    """A document read from disk, ready for ``DesignerSession.open_document``."""

    path: Path
    result: ReadResult
    stamp: FileStamp | None
    read_only_reason: str | None


def open_document(path: str | os.PathLike[str]) -> DocumentFile:
    """Read ``path`` for editing (section 9.2 steps 1-3).

    The stamp is taken before reading: a change while reading shows as a conflict at save time,
    never as a silent overwrite.

    Raises:
        FileError: a network or device path (nothing was touched).
        XmlIoError: the file cannot be read or is not a valid ``.ui`` file.
    """
    if is_network_or_device_path(os.fspath(path)):
        raise FileError("files.network_path", M_NETWORK)
    target = Path(os.path.abspath(path))
    stamp = FileStamp.of(target)
    result = read_ui(target)
    return DocumentFile(target, result, stamp, read_only_reason(result, target))


@dataclass(frozen=True, slots=True)
class SavePlan:
    """What Save (or Save As onto ``target``) must do next, in this order (section 9.3).

    ``refusal`` (a msgid) stops everything. ``ask_target`` means "show Save As first and plan
    again with the chosen target". Otherwise: confirm ``error_count`` errors when non-zero, ask
    Overwrite / Save as / Cancel when ``conflict``, execute ``rebase`` (undoable) when set, then
    ``write_ui(document, target, backup=True)``.
    """

    target: Path | None
    refusal: str | None = None
    ask_target: bool = False
    error_count: int = 0
    conflict: bool = False
    rebase: Command | None = None
    reason: str | None = None  # msgid filling ``{reason}`` of ``refusal``

    def refusal_text(self) -> str | None:
        """The refusal in the current language, or None."""
        if self.refusal is None:
            return None
        reason = _(self.reason) if self.reason is not None else ""
        return format_message(self.refusal, {"reason": reason})


def save_plan(
    document: Document,
    *,
    path: Path | None,
    stamp: FileStamp | None,
    read_only: bool,
    write_protected: bool,
    error_count: int,
    target: Path | None = None,
) -> SavePlan:
    """Decide the save steps for the open document; pure apart from stat calls.

    ``target`` is None for Save, or the file chosen in Save As.
    """
    if read_only:
        return SavePlan(None, refusal=M_READ_ONLY, reason=M_NEWER)
    if target is None:
        if path is None or write_protected:
            return SavePlan(None, ask_target=True)
        target = path
    elif is_network_or_device_path(str(target)):
        return SavePlan(None, refusal=M_NETWORK)
    else:
        target = Path(os.path.abspath(target))
        if _includes(document, path, target):
            return SavePlan(None, refusal=_M_INCLUDED)
    same = path is not None and _same_file(path, target)
    conflict = same and stamp is not None and stamp.changed(target)
    old_base = path.parent if path is not None else None
    rebase = None if same else rebase_paths(document, old_base, target.parent)
    return SavePlan(target, error_count=error_count, conflict=conflict, rebase=rebase)


def _same_file(first: Path, second: Path) -> bool:
    try:
        return os.path.samefile(first, second)
    except OSError:
        return path_key(first) == path_key(second)


def _includes(document: Document, path: Path | None, target: Path) -> bool:
    """True when ``target`` is a file that ``document`` includes (any alias, A18)."""
    base = path.parent if path is not None else None
    for node in document.walk():
        if not isinstance(node, Include) or node.src in ("", "#"):
            continue
        if is_network_or_device_path(node.src):
            continue
        if not os.path.isabs(node.src) and base is None:
            continue
        resolved = Path(os.path.normpath(os.path.join(base or "", node.src)))
        if resolved.exists() and target.exists() and _same_file(resolved, target):
            return True
        if path_key(resolved) == path_key(target):
            return True
    return False


def _rebased(src: str, old_base: Path | None, new_base: Path) -> str:
    """``src`` re-expressed relative to ``new_base``, or ``src`` when it must stay as it is."""
    if not src or src == "#" or is_network_or_device_path(src):
        return src
    if os.path.isabs(src):
        absolute = os.path.normpath(src)
        try:
            relative = os.path.relpath(absolute, new_base)
        except ValueError:  # another drive
            return src
        return relative.replace(os.sep, "/") if not relative.startswith("..") else src
    if old_base is None:
        return src
    absolute = os.path.normpath(os.path.join(old_base, src))
    try:
        relative = os.path.relpath(absolute, new_base)
    except ValueError:  # another drive: absolute, and the validator warns
        return absolute.replace(os.sep, "/")
    return relative.replace(os.sep, "/")


def rebase_paths(document: Document, old_base: Path | None, new_base: Path) -> Command | None:
    """An undoable macro that keeps image and include paths pointing at the same files.

    ``old_base`` is the folder of the current file (None for an untitled document, whose
    relative paths cannot be resolved and stay). Returns None when nothing changes.
    """
    old = Path(os.path.abspath(old_base)) if old_base is not None else None
    new = Path(os.path.abspath(new_base))
    if old is not None and os.path.normcase(old) == os.path.normcase(new):
        return None  # the same folder: every path still points at the same file
    commands: list[Command] = []
    for image in document.resources.values():
        if isinstance(image, ImageResource):
            src = _rebased(image.src, old, new)
            if src != image.src:
                commands.append(SetResource(document, dataclasses.replace(image, src=src)))
    for node in document.walk():
        if isinstance(node, Include):
            src = _rebased(node.src, old, new)
            if src != node.src:
                commands.append(SetField(node, "src", src))
    return Macro(N_("Update file paths"), commands) if commands else None


class RecentFiles:
    """The most-recently-used list (newest first, at most :data:`MAX_RECENT`, no duplicates).

    ``removed`` remembers what this process dropped, so that saving the settings does not bring
    an entry back from another instance's list (see ``settings.merge_recent``).
    """

    def __init__(self, entries: Iterable[str] = ()) -> None:
        self._entries: list[str] = []
        self.removed: set[str] = set()
        keys: set[str] = set()
        for entry in entries:
            if len(self._entries) < MAX_RECENT and _storable(entry) and path_key(entry) not in keys:
                keys.add(path_key(entry))
                self._entries.append(entry)

    @property
    def entries(self) -> tuple[str, ...]:
        """The paths, newest first."""
        return tuple(self._entries)

    def add(self, path: str | os.PathLike[str]) -> None:
        """Put ``path`` first; network and relative paths are never stored (A19)."""
        text = os.fspath(path)
        if not _storable(text):
            return
        text = os.path.abspath(text)
        key = path_key(text)
        self.removed.discard(key)
        self._entries = [text] + [e for e in self._entries if path_key(e) != key]
        del self._entries[MAX_RECENT:]

    def remove(self, path: str | os.PathLike[str]) -> None:
        """Drop ``path`` (a file that no longer exists)."""
        text = os.fspath(path)
        if is_network_or_device_path(text):
            self._entries = [e for e in self._entries if e != text]
            return
        key = path_key(text)
        self.removed.add(key)
        self._entries = [e for e in self._entries if path_key(e) != key]

    def clear(self) -> None:
        """Empty the list (File > Open recent > Clear list)."""
        self.removed.update(path_key(e) for e in self._entries)
        self._entries.clear()


def _storable(path: str) -> bool:
    return (
        isinstance(path, str)
        and 0 < len(path) <= 4096
        and "\x00" not in path
        and not is_network_or_device_path(path)
        and os.path.isabs(path)
    )
