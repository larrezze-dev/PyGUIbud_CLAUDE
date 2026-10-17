"""Temporary files next to user files, for atomic writes (temporary file, then a rename).

:func:`create_temporary` replaces :func:`tempfile.mkstemp` at every place that writes next to a
user's file (QA-15b-01). ``mkstemp`` retries a ``PermissionError`` for as long as the folder
"is writable" by :func:`os.access`, which ignores Windows ACLs: a folder that denies creating
files (``C:\\Program Files``) made it try up to ``TMP_MAX`` (2**31) names, so Save, Export and
the settings store hung. Here a refusal is final unless the name is taken by a folder, and the
number of names tried is bounded. :func:`make_temp_dir` does the same for private folders in the
system's temporary folder (it replaces :func:`tempfile.mkdtemp`, QA-15b-13). Stdlib only,
toolkit-free.
"""

from __future__ import annotations

import errno
import os
import secrets
import tempfile
from pathlib import Path
from typing import Final

__all__ = [
    "MAX_NAME_LENGTH",
    "MAX_TEMPORARY_ATTEMPTS",
    "TEMPORARY_PREFIX",
    "TEMPORARY_SUFFIX",
    "backup_path",
    "create_temporary",
    "make_temp_dir",
]

#: Random names tried before giving up (8 hex digits, as long as the names mkstemp makes).
MAX_TEMPORARY_ATTEMPTS: Final = 100
#: The name of every temporary file is ``~pgb<8 hex>.tmp`` (16 characters), whatever the target
#: is called: a name derived from the target made a valid 242-255 character name unsaveable
#: (QA-15b-12).
TEMPORARY_PREFIX: Final = "~pgb"
TEMPORARY_SUFFIX: Final = ".tmp"
#: The longest name of one path component: 255 UTF-16 units (NTFS) or bytes (ext4, APFS).
MAX_NAME_LENGTH: Final = 255
# What mkstemp uses: exclusive creation, never through a symbolic link, binary, not inherited.
_FLAGS: Final = (
    os.O_CREAT
    | os.O_EXCL
    | os.O_WRONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_BINARY", 0)
    | getattr(os, "O_NOINHERIT", 0)
)


def create_temporary(
    folder: str | os.PathLike[str],
    *,
    prefix: str = TEMPORARY_PREFIX,
    suffix: str = TEMPORARY_SUFFIX,
) -> tuple[int, str]:
    """Create a new private file (mode 0600) named ``prefix + random + suffix`` in ``folder``.

    Returns the open descriptor (write-only, binary) and the absolute path, like
    :func:`tempfile.mkstemp`.

    Raises:
        PermissionError: the folder refuses new files (at once: never retried).
        FileExistsError: every name tried was taken.
        OSError: any other reason the file cannot be created (missing folder, name too long).
    """
    base = os.fspath(folder)
    for _ in range(MAX_TEMPORARY_ATTEMPTS):
        candidate = os.path.join(base, f"{prefix}{secrets.token_hex(4)}{suffix}")
        try:
            descriptor = os.open(candidate, _FLAGS, 0o600)
        except FileExistsError:
            continue
        except PermissionError:
            # Windows reports a folder of that name as "access denied": only then try again.
            if os.path.isdir(candidate):
                continue
            raise
        return descriptor, os.path.abspath(candidate)
    # The operating system's own wording: it is shown to the user as the reason.
    raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), os.path.abspath(base))


def _name_length(name: str) -> int:
    if os.name == "nt":
        return len(name.encode("utf-16-le", "surrogatepass")) // 2
    return len(os.fsencode(name))


def backup_path(target: Path) -> Path:
    """``<name>.bak`` next to ``target``; when that name is too long for the file system, the
    name is shortened until ``<shortened>.bak`` fits (QA-19b-01). ``target`` keeps its name."""
    name = target.name
    while name and (
        _name_length(name + ".bak") > MAX_NAME_LENGTH
        or (name + ".bak").casefold() == target.name.casefold()  # a long name ending in .bak
    ):
        name = name[:-1]
    return target.with_name(name + ".bak")


def make_temp_dir(prefix: str) -> Path:
    """Create a new private folder (mode 0700) named ``prefix + 8 hex`` in the system's
    temporary folder, with the refusal rules of :func:`create_temporary`.

    Raises:
        PermissionError: the temporary folder refuses new folders (at once: never retried).
        FileExistsError: every name tried was taken.
        OSError: any other reason the folder cannot be created.
    """
    base = tempfile.gettempdir()
    for _ in range(MAX_TEMPORARY_ATTEMPTS):
        candidate = os.path.join(base, f"{prefix}{secrets.token_hex(4)}")
        try:
            os.mkdir(candidate, 0o700)
        except FileExistsError:
            continue
        except PermissionError:
            if os.path.isdir(candidate):  # Windows: a folder of that name is "access denied"
                continue
            raise
        return Path(os.path.abspath(candidate))
    raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), os.path.abspath(base))
