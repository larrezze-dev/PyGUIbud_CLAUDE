"""ADR-007/013: importing the runtime, a backend or the preview child loads no toolkit and none
of the designer side."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
        "pyguibud.backends._tbwidgets",  # Step 17b: ttkbootstrap only inside the factories
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


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_the_registry_resolves_tb_factories_without_a_toolkit() -> None:
    """Spec plugins 10: loading the registry and the tb: factory references loads no toolkit."""
    code = (
        "import sys; from pyguibud.core.registry import Registry;"
        "r = Registry(); r.load(); spec = r.require('tb:Meter');"
        "assert r.load_factory(spec, 'tkinter') is None;"
        "assert r.load_factory(spec, 'pyside6') is None;"
        "assert callable(r.load_factory(spec, 'ttkbootstrap'));"
        "assert 'pyguibud.backends._tbwidgets' in sys.modules;"
        "kits = ('tkinter', 'ttkbootstrap', 'PySide6');"
        "bad = sorted(m for m in sys.modules if m.startswith(kits));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_tkinter_and_qt_backends_never_import_tbwidgets() -> None:
    code = (
        "import sys, pyguibud.backends.tkinter, pyguibud.backends.pyside6, pyguibud.backends._tk;"
        "sys.exit('pyguibud.backends._tbwidgets' in sys.modules)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr
    backends = Path(__file__).resolve().parents[2] / "src" / "pyguibud" / "backends"
    for name in ("tkinter.py", "pyside6.py", "_tk.py", "_qt.py", "_qtmap.py"):
        assert "_tbwidgets" not in (backends / name).read_text(encoding="utf-8"), name
