"""Step 20c: the clean-venv install check (``tools/verify_install.py``), as a thin wrapper.

Slow and online (it builds both distributions and installs ttkbootstrap from PyPI), so it is
excluded from the normal run. The uv path is off unless ``PYGUIBUD_INSTALL_UV=1``.
Run it with ``pytest -m install``.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

from tests._paths import ROOT

pytestmark = pytest.mark.install


def test_both_distributions_install_into_clean_environments() -> None:
    command = [sys.executable, str(ROOT / "tools" / "verify_install.py")]
    if os.environ.get("PYGUIBUD_INSTALL_UV") != "1":
        command.append("--skip-uv")
    done = subprocess.run(
        command,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    assert "\nOK: " in "\n" + done.stdout
