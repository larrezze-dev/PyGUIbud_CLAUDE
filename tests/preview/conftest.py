"""Fixtures of the preview tests: the display gate and i18n reset of the codegen tests, and a
helper that runs the preview child (``python -m pyguibud.preview``) and always reaps it."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from tests.codegen.conftest import (  # noqa: F401 - pytest hooks and fixtures re-used here
    clean_i18n,
    data_copy,
    pytest_runtest_setup,
)

CHILD = [sys.executable, "-m", "pyguibud.preview"]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)


def describe_child(ui: Path, *args: str, cwd: Path) -> dict[str, Any]:
    """``--describe`` in a fresh process; the JSON it prints."""
    result = subprocess.run(
        [*CHILD, "--describe", *args, "--", str(ui)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        cwd=cwd,
        env=ENV,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return data


@pytest.fixture
def spawn(tmp_path: Path) -> Iterator[Any]:
    """Start live preview children (stdin piped); each is killed and reaped afterwards."""
    started: list[subprocess.Popen[bytes]] = []

    def start(ui: Path, *args: str) -> subprocess.Popen[bytes]:
        process = subprocess.Popen(
            [*CHILD, *args, "--", str(ui)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd=tmp_path,
            env=ENV,
        )
        started.append(process)
        return process

    yield start
    for process in started:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
