"""Smoke tests of the Step 09 UAT demo ``examples/validator_demo.py``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

DEMO = Path(__file__).resolve().parents[1] / "examples" / "validator_demo.py"
HEADERS = ("1. ", "2. ", "3. ", "4. ", "5. ", "6. ")


def _run(*args: str, encoding: str) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, "PYTHONIOENCODING": encoding}
    env.pop("PYTHONUTF8", None)
    return subprocess.run(
        [sys.executable, str(DEMO), *args], capture_output=True, env=env, check=False, timeout=120
    )


@pytest.mark.parametrize("encoding", ["cp1252", "utf-8"])
def test_demo_runs_and_exits_zero(encoding: str) -> None:
    result = _run(encoding=encoding)
    assert result.returncode == 0, result.stderr.decode(encoding, "replace")
    out = result.stdout.decode(encoding)
    lines = out.splitlines()
    for header in HEADERS:
        assert any(line.startswith(header) for line in lines), header
    assert out.count("BLOCKED: ") == 17  # 15 guarded edits + 2 read-only edits
    assert "Document unchanged after the blocked edits: yes" in out
    assert "Document is valid: no" in out
    assert "Traceback" not in result.stderr.decode(encoding, "replace")


def test_demo_pseudo_locale_on_cp1252_console() -> None:
    plain = _run(encoding="cp1252")
    pseudo = _run("--lang", "en_XA", encoding="cp1252")
    assert pseudo.returncode == 0, pseudo.stderr.decode("cp1252", "replace")
    assert pseudo.stdout != plain.stdout
    lines = pseudo.stdout.decode("cp1252").splitlines()
    for header in HEADERS:
        assert any(line.startswith(header) for line in lines), header


def test_demo_main_is_importable(capsys: pytest.CaptureFixture[str]) -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location("validator_demo_main", DEMO)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main([]) == 0
    assert "6. " in capsys.readouterr().out
