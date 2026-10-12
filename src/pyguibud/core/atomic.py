"""Temporary files next to user files, for atomic writes (temporary file, then a rename).

:func:`create_temporary` replaces :func:`tempfile.mkstemp` at every place that writes next to a
user's file (QA-15b-01). ``mkstemp`` retries a ``PermissionError`` for as long as the folder
"is writable" by :func:`os.access`, which ignores Windows ACLs: a folder that denies creating
files (``C:\\Program Files``) made it try up to ``TMP_MAX`` (2**31) names, so Save, Export and
the settings store hung. Here a refusal is final unless the name is taken by a folder, and the
number of names tried is bounded. Stdlib only, toolkit-free.
"""

from __future__ import annotations

import errno
import os
import secrets
from typing import Final

__all__ = ["MAX_TEMPORARY_ATTEMPTS", "create_temporary"]

#: Random names tried before giving up (8 hex digits, as long as the names mkstemp makes).
MAX_TEMPORARY_ATTEMPTS: Final = 100
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
    folder: str | os.PathLike[str], *, prefix: str, suffix: str
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
