"""``tools/verify_install.py --from-index`` takes TestPyPI and PyPI (Step 21c, the v0.1.0 check)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from tests._paths import ROOT


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_install", ROOT / "tools" / "verify_install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


@pytest.mark.parametrize(
    ("index", "url"),
    [("testpypi", "https://test.pypi.org/simple/"), ("pypi", "https://pypi.org/simple/")],
)
def test_from_index_accepts_both_indexes(script: ModuleType, index: str, url: str) -> None:
    args = script.parse(["--from-index", index, "--version", "0.1.0"])
    assert args.from_index == index
    assert script.INDEXES[index][0] == url


def test_from_index_rejects_an_unknown_index(script: ModuleType) -> None:
    with pytest.raises(SystemExit):
        script.parse(["--from-index", "example.org", "--version", "0.1.0"])


def test_pip_download_uses_the_chosen_index(
    script: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    verifier = script.Verifier(tmp_path, sys.executable, "0.1.0")
    commands: list[list[object]] = []
    labels: list[str] = []

    def run(command: list[object]) -> tuple[int, str]:
        commands.append(command)
        return 1, "no network in this test"  # a failed download ends pip_path

    def record(path: str, check: str, ok: bool, detail: str = "") -> bool:
        labels.append(check)
        return ok

    monkeypatch.setattr(verifier, "make_venv", lambda _path, _venv: Path(sys.executable))
    monkeypatch.setattr(verifier, "run", run)
    monkeypatch.setattr(verifier, "record", record)
    verifier.pip_path(Path(), "pypi")
    assert commands, "pip download was not run"
    assert "https://pypi.org/simple/" in commands[0]
    assert "pyguibud==0.1.0" in commands[0]
    assert labels[0] == "download from PyPI"
