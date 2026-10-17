"""Output guards shared by ``pyguibud-uic`` and the designer's Export dialog (ADR-013).

Whatever writes a generated module or a translation template goes through these functions, so
that the command line and the designer refuse and write exactly the same way. Nothing here
imports the CLI, the designer or a toolkit.
"""

from __future__ import annotations

import contextlib
import os
import re
import stat

from pyguibud.codegen import GENERATED_MARKER
from pyguibud.codegen._errors import (
    M_ALREADY_WRITTEN,
    M_NOT_REGULAR,
    M_SAME_FILE,
    M_STREAM_NAME,
)
from pyguibud.core.atomic import create_temporary
from pyguibud.core.errors import XmlIoError
from pyguibud.core.files import MAX_INCLUDE_FILES, DiskFiles, is_device_name
from pyguibud.core.model import Include
from pyguibud.core.xml_io import ReadResult

__all__ = [
    "check_output",
    "holds_translations",
    "protected_ui_files",
    "replaceable",
    "same_file",
    "write_atomic",
]

_MARKER = GENERATED_MARKER.encode("utf-8")
# The header line every template written by --extract carries (codegen/_pot.py).
_POT_MARKER = b'\n"Generated-By: pyguibud-uic '
_POT_HEAD_BYTES = 4096
_POT_LIMIT = 16 * 1024 * 1024  # a larger existing file is never replaced without --force
_PO_FIELD_RE = re.compile(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[[0-9]+\])?)\s+"(.*)"')
_PO_MORE_RE = re.compile(r'"(.*)"')


def _plain(path: str) -> str:
    r"""``path`` without a Win32 namespace prefix (``\\?\``, ``//?/``, ``\\.\``, ``\??\``).

    ``realpath`` keeps such a prefix, so ``\\?\C:\a.ui`` and ``C:\a.ui`` would look like two
    files (QA-11-13). ``\\?\UNC\host\share`` becomes ``\\host\share``.
    """
    if os.name != "nt":
        return path
    text = path.replace("/", "\\")
    for prefix in (r"\\?" + "\\", r"\\." + "\\", r"\??" + "\\"):
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            return r"\\" + rest[4:] if rest[:4].upper() == "UNC\\" else rest
    return path


def _identity(path: str) -> str:
    """The identity of a path: real path without a namespace prefix, case-folded on Windows."""
    return os.path.normcase(os.path.realpath(_plain(path)))


def same_file(first: str, second: str) -> bool:
    """True if both paths name one file: the same inode when both exist (hard links, aliases)."""
    try:
        if os.path.samefile(first, second):
            return True
    except (OSError, ValueError):  # one does not exist yet, or cannot be a path
        pass
    return _identity(first) == _identity(second)


def protected_ui_files(path: str, result: ReadResult) -> list[str]:
    """``path`` and every ``.ui`` file it includes, directly or not (bounded, best effort).

    Only used to protect these files from being overwritten, so an unreadable include still
    counts and nothing is validated.
    """
    files = DiskFiles(path, result)
    keys = [files.root]
    index = 0
    while index < len(keys) and len(keys) <= MAX_INCLUDE_FILES:
        key = keys[index]
        index += 1
        try:
            document = files.read(key).document
        except (OSError, XmlIoError):
            continue
        for node in document.walk():
            if isinstance(node, Include) and isinstance(node.src, str):
                try:
                    target = files.resolve(key, node.src)
                except OSError:
                    continue
                if target not in keys:
                    keys.append(target)
    return [files.path_of(key) for key in keys]


def _stream_name(output: str) -> bool:
    """True if ``output`` names an NTFS alternate data stream (``a.py:evil``, QA-15b-08)."""
    if os.name != "nt":
        return False
    return ":" in os.path.splitdrive(_plain(output))[1]


def _regular_or_absent(output: str) -> bool:
    """True if ``output`` does not exist or is a regular file; it is never opened (QA-11-05)."""
    if os.name == "nt" and is_device_name(os.path.basename(output)):  # CON, nul.txt, COM1 .py
        return False
    try:
        mode = os.stat(output).st_mode
    except (FileNotFoundError, NotADirectoryError):  # writing reports a bad folder itself
        return True
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(mode)


def replaceable(output: str, *, extracting: bool) -> bool:
    """True if ``output`` (absent or a regular file) may be replaced without ``--force``.

    Only what pyguibud-uic itself wrote is: a module starting with its marker, or a template
    with its ``Generated-By`` header line (see also :func:`holds_translations`).
    """
    size = _POT_HEAD_BYTES if extracting else len(_MARKER)
    try:
        with open(output, "rb") as stream:
            head = stream.read(size)
    except (FileNotFoundError, NotADirectoryError):  # writing reports a bad folder itself
        return True
    except OSError:
        return False
    return _POT_MARKER in head if extracting else head.startswith(_MARKER)


def holds_translations(output: str) -> bool:
    """True if ``output`` is a ``.po`` file or an existing file holding translations.

    A ``.po`` file copied from the template keeps its ``Generated-By`` line, so the marker alone
    cannot protect the translations in it (QA-11-14).
    """
    if os.path.splitext(output)[1].lower() == ".po":
        return True
    try:
        with open(output, "rb") as stream:
            data = stream.read(_POT_LIMIT + 1)
    except OSError:  # absent (the marker check has already refused anything unreadable)
        return False
    if len(data) > _POT_LIMIT:
        return True
    return _has_translations(data.decode("utf-8", errors="replace"))


def _has_translations(text: str) -> bool:
    """True if a PO text has a non-empty ``msgstr`` outside its header (obsolete ``#~`` too)."""
    entry: dict[str, str] = {}
    field: str | None = None

    def translated() -> bool:
        header = entry.get("msgid") == "" and "msgctxt" not in entry
        return not header and any(v for k, v in entry.items() if k.startswith("msgstr"))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#~"):
            line = line[2:].strip()
        found = _PO_FIELD_RE.fullmatch(line)
        if found is not None:
            name, value = found.groups()
            if name == "msgctxt" or (name == "msgid" and "msgid" in entry):
                if translated():
                    return True
                entry = {}
            entry[name] = value
            field = name
        elif field is not None and (more := _PO_MORE_RE.fullmatch(line)) is not None:
            entry[field] += more.group(1)
        else:
            field = None
    return translated()


def check_output(output: str, protected: list[str], written: list[str]) -> str | None:
    """The msgid that refuses ``output`` whatever ``--force`` says, or None."""
    if any(same_file(output, path) for path in protected):
        return M_SAME_FILE
    if any(same_file(output, path) for path in written):
        return M_ALREADY_WRITTEN
    if _stream_name(output):
        return M_STREAM_NAME
    if not _regular_or_absent(output):
        return M_NOT_REGULAR
    return None


def write_atomic(output: str, text: str) -> None:
    """Write ``text`` (UTF-8, LF) through a temporary file in the target folder.

    Raises:
        OSError: the file cannot be written; no temporary file is left behind.
    """
    folder = os.path.dirname(os.path.abspath(output))
    descriptor, temporary = create_temporary(folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        # The temporary file is private (0600); the result is an ordinary, non-executable one.
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o644)
        os.replace(temporary, output)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise
