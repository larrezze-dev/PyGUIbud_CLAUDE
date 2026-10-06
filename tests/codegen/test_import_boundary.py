"""ADR-007/ADR-008 boundaries between the runtime side and the code generator side.

The runtime half (``pyguibud_runtime``, a backend module) must never load ``pyguibud.codegen*``;
the code generator half (``pyguibud.codegen``, ``pyguibud.uic``, ``pyguibud.backends._tkmap``)
must load no toolkit, even while it generates a module.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.codegen.conftest import EXAMPLES

TOOLKITS = ("tkinter", "_tkinter", "ttkbootstrap", "PySide6")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False, timeout=60
    )


@pytest.mark.parametrize(
    "imports",
    [
        "pyguibud_runtime",
        "pyguibud.backends.ttkbootstrap",
        "pyguibud.backends._tk",
        "pyguibud.backends._tkmap",
        "pyguibud.core, pyguibud.i18n",
    ],
)
def test_the_runtime_side_does_not_load_the_code_generator(imports: str) -> None:
    code = (
        f"import sys, {imports};"
        "bad = sorted(m for m in sys.modules "
        "if m.startswith(('pyguibud.codegen', 'pyguibud.uic')));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "imports", ["pyguibud.codegen", "pyguibud.uic", "pyguibud.backends._tkmap"]
)
def test_the_code_generator_side_loads_no_toolkit_on_import(imports: str) -> None:
    code = (
        f"import sys, {imports};"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {TOOLKITS!r});"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_generating_and_extracting_load_no_toolkit(tmp_path: Path) -> None:
    code = (
        "import sys;"
        "from pyguibud.uic import main;"
        f"a = main([{str(EXAMPLES / 'hello.ui')!r}, '-o', {str(tmp_path / 'h_ui.py')!r}]);"
        f"b = main(['--extract', {str(EXAMPLES / 'hello.ui')!r}, "
        f"'-o', {str(tmp_path / 'h.pot')!r}]);"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {TOOLKITS!r} "
        "or m == 'pyguibud_runtime');"
        "print(a, b, bad); sys.exit(0 if (a, b, bad) == (0, 0, []) else 1)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (tmp_path / "h_ui.py").exists() and (tmp_path / "h.pot").exists()
