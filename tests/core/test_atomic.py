"""``core.atomic.create_temporary``: the bounded replacement of ``tempfile.mkstemp`` (QA-15b-01)."""

from __future__ import annotations

import errno
import os
import secrets
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.atomic import (
    MAX_TEMPORARY_ATTEMPTS,
    backup_path,
    create_temporary,
    make_temp_dir,
)


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


def test_the_default_name_does_not_grow_with_the_target(tmp_path: Path) -> None:
    """H23 (QA-15b-12): ``~pgb<8 hex>.tmp`` whatever the target is called."""
    descriptor, path = create_temporary(tmp_path)
    os.close(descriptor)
    assert Path(path).parent == tmp_path
    name = Path(path).name
    assert name.startswith("~pgb") and name.endswith(".tmp") and len(name) == 16
    int(name[4:12], 16)


def test_make_temp_dir_creates_a_private_folder_in_the_temporary_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    names = iter(["a" * 8, "b" * 8, "c" * 8])
    monkeypatch.setattr(secrets, "token_hex", lambda _n: next(names))
    (tmp_path / f"run-{'a' * 8}").write_bytes(b"taken")
    (tmp_path / f"run-{'b' * 8}").mkdir()
    folder = make_temp_dir("run-")
    assert folder == tmp_path / f"run-{'c' * 8}" and folder.is_dir()
    assert list(folder.iterdir()) == []


def test_make_temp_dir_fails_at_once_when_the_temporary_folder_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H24 (QA-15b-13): ``tempfile.mkdtemp`` retried a denied %TEMP% up to 2**31 times."""
    calls: list[str] = []

    def refuse(path: Any, *_args: Any, **_kwargs: Any) -> None:
        calls.append(os.fspath(path))
        raise PermissionError(errno.EACCES, "Permission denied", path)

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(os, "mkdir", refuse)
    with pytest.raises(PermissionError):
        make_temp_dir("run-")
    assert len(calls) == 1


def test_make_temp_dir_running_out_of_names_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def taken(path: Any, *_args: Any, **_kwargs: Any) -> None:
        calls.append(os.fspath(path))
        raise FileExistsError(errno.EEXIST, "File exists", path)

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(os, "mkdir", taken)
    with pytest.raises(FileExistsError):
        make_temp_dir("run-")
    assert len(calls) == MAX_TEMPORARY_ATTEMPTS


@pytest.mark.parametrize("letter", ["a", "\U0001f600"], ids=["ascii", "emoji"])
def test_backup_path_shortens_only_a_name_too_long_for_its_bak(tmp_path: Path, letter: str) -> None:
    # QA-19b-01: the longest valid name (255 UTF-16 units on Windows, 255 bytes on POSIX).
    assert backup_path(tmp_path / "hello.ui") == tmp_path / "hello.ui.bak"
    unit = len(letter.encode("utf-16-le")) // 2 if os.name == "nt" else len(letter.encode())
    name = letter * ((255 - 3) // unit) + ".ui"
    (tmp_path / name).write_bytes(b"ui")  # the file system takes the name
    bak = backup_path(tmp_path / name)
    assert bak.parent == tmp_path and bak.name.endswith(".bak") and bak.name != name + ".bak"
    assert name.startswith(bak.name.removesuffix(".bak"))
    bak.write_bytes(b"bak")  # ... and the backup's name too
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([name, bak.name])
    long_bak = tmp_path / ("b" * 251 + ".BAK")  # shortening must never give the file itself
    assert backup_path(long_bak).name == "b" * 250 + ".bak"
