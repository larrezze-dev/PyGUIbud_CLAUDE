"""QA Step 20c: abuse of ``tools/verify_install.py`` itself (no builds, no venvs, no network).

Every bad invocation must end with a clear message and a non-zero exit, never a traceback, and
must never leave its temporary folder behind or touch anything outside it. The script is loaded
from its file, as ``tests/test_verify_install_literals.py`` does; ``tempfile.tempdir`` points
into ``tmp_path`` so that every temporary folder the script makes can be counted.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import time
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

from tests._paths import ROOT

VERSION = "0.1.0rc1"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_install_qa", ROOT / "tools" / "verify_install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The folder the script's ``tempfile.mkdtemp`` uses."""
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(root))
    return root


@pytest.fixture
def version(script: ModuleType, monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin the version the script expects, so the tests do not follow ``__about__``."""
    monkeypatch.setattr(script, "read_version", lambda: VERSION)
    return VERSION


def _leftovers(temp_root: Path) -> list[str]:
    return sorted(p.name for p in temp_root.glob("pyguibud-verify-*"))


def _fake_wheels(folder: Path, version: str) -> Path:
    """Minimal real zip files with the right wheel names."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in (
        f"pyguibud-{version}-py3-none-any.whl",
        f"pyguibud_runtime-{version}-py3-none-any.whl",
    ):
        with zipfile.ZipFile(folder / name, "w") as wheel:
            wheel.writestr("marker.txt", "x")
    return folder


# ---------------------------------------------------------------------------- argument errors
@pytest.mark.parametrize(
    "argv",
    [
        ["--version", "9.9.9"],  # --version without --from-index
        ["--dist", "dist", "--from-index", "testpypi"],
        ["--from-index", "example.org"],  # only testpypi and pypi are offered
        ["--bogus"],
    ],
)
def test_bad_arguments_exit_2_with_usage(
    script: ModuleType, argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc:
        script.parse(argv)
    assert exc.value.code == 2
    assert "usage:" in capsys.readouterr().err


# ---------------------------------------------------------------------------- bad --dist folders
@pytest.mark.parametrize("case", ["empty", "missing", "only_designer", "wrong_version", "a_file"])
def test_bad_dist_fails_cleanly_and_cleans_up(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    case: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = tmp_path / "dist"
    if case == "empty":
        dist.mkdir()
    elif case == "only_designer":
        dist.mkdir()
        _fake_wheels(dist, version)
        (dist / f"pyguibud_runtime-{version}-py3-none-any.whl").unlink()
    elif case == "wrong_version":
        _fake_wheels(dist, "0.2.0")
    elif case == "a_file":
        dist.write_text("not a folder", encoding="utf-8")
    code = script.main(["--dist", str(dist), "--skip-uv"])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL build both wheels present" in out
    assert "FAILED: 1 check(s)" in out
    assert "Traceback" not in out
    assert _leftovers(temp_root) == []
    expected = {
        "missing": "does not exist",
        "a_file": "is not a folder",
        "wrong_version": "versions found: 0.2.0",
        "only_designer": "no wheel of pyguibud_runtime",
        "empty": "versions found: none",
    }[case]
    assert expected in out


def test_zero_byte_and_non_zip_wheels_are_rejected(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = _fake_wheels(tmp_path / "dist", version)
    (dist / f"pyguibud-{version}-py3-none-any.whl").write_bytes(b"")
    (dist / f"pyguibud_runtime-{version}-py3-none-any.whl").write_text("junk", encoding="utf-8")
    code = script.main(["--dist", str(dist), "--skip-uv"])
    out = capsys.readouterr().out
    assert code == 1
    assert out.count("is not a valid wheel") == 2
    assert _leftovers(temp_root) == []


def test_non_python_interpreter_fails_cleanly(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """--python pointing at a missing file: both venvs fail, nothing is installed."""
    dist = _fake_wheels(tmp_path / "dist", version)
    bogus = tmp_path / "no-such-python.exe"
    code = script.main(["--dist", str(dist), "--skip-uv", "--python", str(bogus)])
    out = capsys.readouterr().out
    assert code == 1
    assert "FAIL python interpreter is Python 3.10+" in out
    assert "cannot run" in out
    assert "pip install" not in out  # nothing was attempted after the interpreter check
    assert _leftovers(temp_root) == []


def test_old_python_is_refused_up_front(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dist = _fake_wheels(tmp_path / "dist", version)
    monkeypatch.setattr(script.Verifier, "run", lambda self, command, **kw: (0, "3.9"))
    code = script.main(["--dist", str(dist), "--skip-uv"])
    out = capsys.readouterr().out
    assert code == 1
    assert "Python 3.9; PyGUIbud needs 3.10 or newer" in out
    assert "create venv" not in out
    assert _leftovers(temp_root) == []


# ---------------------------------------------------------------------------- temp folder rules
def test_temp_folder_inside_the_checkout_is_refused(
    script: ModuleType,
    version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A TMP inside the checkout (simulated with a fake ROOT, never the real repository)."""
    fake_root = tmp_path / "checkout"
    inner_tmp = fake_root / "tmp"
    inner_tmp.mkdir(parents=True)
    monkeypatch.setattr(script, "ROOT", fake_root)
    monkeypatch.setattr("tempfile.tempdir", str(inner_tmp))
    code = script.main(["--dist", str(tmp_path), "--skip-uv"])
    out = capsys.readouterr().out
    assert code == 1
    assert "lies inside the checkout" in out
    assert list(inner_tmp.iterdir()) == []  # the folder made by mkdtemp is removed again


def test_ctrl_c_prints_interrupted_exits_130_and_cleans_up(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Ctrl+C mid-run: no traceback, exit 130, temporary folder removed."""

    def interrupted(work: Path) -> None:
        (work / "half-done").write_text("x", encoding="utf-8")
        raise KeyboardInterrupt

    monkeypatch.setattr(script, "copy_example", interrupted)
    monkeypatch.setattr(script.Verifier, "run", lambda self, command, **kw: (0, "3.12"))
    assert script.main(["--dist", str(tmp_path), "--skip-uv"]) == 130
    out = capsys.readouterr().out
    assert "interrupted" in out
    assert "Traceback" not in out
    assert _leftovers(temp_root) == []


def test_keep_and_failed_removal_print_the_path(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(script.Verifier, "run", lambda self, command, **kw: (0, "3.12"))
    dist = tmp_path / "missing"
    script.main(["--dist", str(dist), "--skip-uv", "--keep"])
    assert "kept " in capsys.readouterr().out
    assert len(_leftovers(temp_root)) == 1
    monkeypatch.setattr(script.shutil, "rmtree", lambda *a, **k: None)
    script.main(["--dist", str(dist), "--skip-uv"])
    assert "could not remove the temporary folder" in capsys.readouterr().out


def test_sweep_removes_only_old_prefixed_folders(script: ModuleType, temp_root: Path) -> None:
    old = temp_root / "pyguibud-verify-old"
    new = temp_root / "pyguibud-verify-new"
    other = temp_root / "someone-elses-folder"
    for folder in (old, new, other):
        folder.mkdir()
    long_ago = time.time() - 48 * 3600
    for folder in (old, other):
        os.utime(folder, (long_ago, long_ago))
    script.sweep_stale()
    assert not old.exists()
    assert new.exists()
    assert other.exists()


def test_clean_environment_never_points_at_real_profile(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", "C:/real/config")
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", "C:/real/state")
    monkeypatch.setenv("PYGUIBUD_LANG", "de_DE")
    monkeypatch.setenv("VIRTUAL_ENV", "C:/some/venv")
    monkeypatch.setenv("PYTHONPATH", "C:/somewhere")
    env = script.clean_environment(tmp_path)
    assert Path(env["PYGUIBUD_CONFIG_DIR"]).is_relative_to(tmp_path)
    assert Path(env["PYGUIBUD_STATE_DIR"]).is_relative_to(tmp_path)
    assert "PYGUIBUD_LANG" not in env
    assert "VIRTUAL_ENV" not in env
    assert "PYTHONPATH" not in env


# ---------------------------------------------------------------------------- output encoding
def test_non_cp1252_output_does_not_crash(
    script: ModuleType,
    temp_root: Path,
    version: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dist = tmp_path / "dist_\u0142\u00f3d\u017a"  # "dist_lodz" with Polish letters
    dist.mkdir()
    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))
    code = script.main(["--dist", str(dist), "--skip-uv"])
    assert code == 1
    assert b"FAIL build both wheels present" in raw.getvalue()
    assert _leftovers(temp_root) == []
