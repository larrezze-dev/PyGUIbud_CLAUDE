"""ADR-007/013: importing the runtime, a backend or the preview child loads no toolkit and none
of the designer side."""

from __future__ import annotations

import subprocess
import sys

import pytest

_FORBIDDEN = repr(
    (
        *("tkinter", "ttkbootstrap", "PySide6", "pyguibud.cli", "pyguibud.uic"),
        *("pyguibud.designer", "pyguibud.codegen"),
        *("pyguibud.preview._host_qt", "pyguibud.preview._describe_qt"),  # lazy (spec backends 5)
    )
)


@pytest.mark.parametrize(
    "imports",
    [
        "pyguibud_runtime, pyguibud.backends.ttkbootstrap, pyguibud.backends._tk",
        "pyguibud.backends.tkinter",
        "pyguibud.backends.pyside6, pyguibud.backends._qtmap, pyguibud.backends._vars",
        "pyguibud.core",
        # ADR-013: the preview child loads its toolkit only inside run()
        "pyguibud.preview, pyguibud.preview._host, pyguibud.preview._describe",
    ],
)
def test_import_boundary(imports: str) -> None:
    code = (
        f"import sys, {imports};"
        f"bad = sorted(m for m in sys.modules if m.startswith({_FORBIDDEN}));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
