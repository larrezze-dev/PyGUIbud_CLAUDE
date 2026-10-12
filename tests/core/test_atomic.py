"""``core.atomic.create_temporary``: the bounded replacement of ``tempfile.mkstemp`` (QA-15b-01)."""

from __future__ import annotations

import errno
import os
import secrets
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.atomic import MAX_TEMPORARY_ATTEMPTS, create_temporary


def test_creates_a_private_new_file_with_the_given_name_shape(tmp_path: Path) -> None:
    descriptor, path = create_temporary(tmp_path, prefix=".hello.ui.", suffix=".tmp")
    try:
        os.write(descriptor, b"data")
    finally:
        os.close(descriptor)
    name = Path(path).name
    assert Path(path).parent == tmp_path and os.path.isabs(path)
    assert name.startswith(".hello.ui.") and name.endswith(".tmp") and len(name) > 14
    assert Path(path).read_bytes() == b"data"
    if os.name == "posix":  # pragma: no cover - POSIX CI only
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600


def test_a_relative_folder_gives_an_absolute_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    descriptor, path = create_temporary(".", prefix="x", suffix=".tmp")
    os.close(descriptor)
    assert os.path.isabs(path) and Path(path).parent == tmp_path


def test_taken_names_and_same_named_folders_are_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    names = iter(["a" * 12, "b" * 12, "c" * 12])
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(names))
    (tmp_path / f"p{'a' * 12}s").write_bytes(b"taken")
    (tmp_path / f"p{'b' * 12}s").mkdir()
    descriptor, path = create_temporary(tmp_path, prefix="p", suffix="s")
    os.close(descriptor)
    assert Path(path).name == f"p{'c' * 12}s"
    assert (tmp_path / f"p{'a' * 12}s").read_bytes() == b"taken"


def test_a_refused_folder_fails_at_once_even_if_access_says_writable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def refuse(path: Any, *_args: Any, **_kwargs: Any) -> int:
        calls.append(os.fspath(path))
        raise PermissionError(errno.EACCES, "Permission denied", path)

    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(os, "access", lambda *_a, **_k: True)
    with pytest.raises(PermissionError):
        create_temporary(tmp_path, prefix=".x.", suffix=".tmp")
    assert len(calls) == 1


def test_running_out_of_names_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def taken(path: Any, *_args: Any, **_kwargs: Any) -> int:
        calls.append(os.fspath(path))
        raise FileExistsError(errno.EEXIST, "File exists", path)

    monkeypatch.setattr(os, "open", taken)
    with pytest.raises(FileExistsError) as info:
        create_temporary(tmp_path, prefix=".x.", suffix=".tmp")
    assert len(calls) == MAX_TEMPORARY_ATTEMPTS and info.value.strerror


def test_a_missing_folder_is_an_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_temporary(tmp_path / "missing", prefix=".x.", suffix=".tmp")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs (os.access ignores them)")
def test_a_real_folder_denying_new_files_fails_at_once(tmp_path: Path) -> None:
    import subprocess
    import time

    folder = tmp_path / "denied"
    folder.mkdir()
    everyone = "*S-1-1-0"
    try:
        denied = subprocess.run(
            ["icacls", str(folder), "/deny", f"{everyone}:(WD,AD)"],
            capture_output=True,
            check=False,
            timeout=30,
        )
    except OSError:  # pragma: no cover - icacls missing
        pytest.skip("icacls is not available")
    if denied.returncode != 0:  # pragma: no cover - a locked-down machine
        pytest.skip("the folder ACL cannot be changed")
    try:
        assert os.access(folder, os.W_OK)  # what made tempfile.mkstemp loop
        start = time.monotonic()
        with pytest.raises(PermissionError):
            create_temporary(folder, prefix=".pyguibud-", suffix=".tmp")
        assert time.monotonic() - start < 1.0
    finally:
        subprocess.run(
            ["icacls", str(folder), "/remove:d", everyone],
            capture_output=True,
            check=False,
            timeout=30,
        )
    assert list(folder.iterdir()) == []
