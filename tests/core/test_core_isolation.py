"""The core must stay free of GUI toolkits."""

from __future__ import annotations

import subprocess
import sys

import pytest

_TOOLKITS = ("tkinter", "ttkbootstrap", "PySide6", "PyQt5", "PyQt6")


def _run(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


def test_import_core_leaves_toolkits_out() -> None:
    code = (
        "import sys, pyguibud.core, pyguibud.core.widgets, pyguibud.core.registry;"
        "import pyguibud.core.diagnostics, pyguibud.core.validate, pyguibud.core.commands;"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {_TOOLKITS!r});"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_loading_registry_leaves_toolkits_out() -> None:
    code = (
        "import sys; from pyguibud.core import default_registry;"
        "r = default_registry(); assert len(r.specs()) == 24 and not r.diagnostics();"
        "r.backends();"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {_TOOLKITS!r});"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_import_does_not_load_plugins() -> None:
    code = (
        "import sys, importlib.metadata as md;"
        "calls = []; orig = md.entry_points;"
        "md.entry_points = lambda **k: (calls.append(k), orig(**k))[1];"
        "import pyguibud.core; assert not calls, calls"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", ["errors", "model", "widgets", "registry"])
def test_each_module_imports_alone(module: str) -> None:
    result = _run(f"import pyguibud.core.{module}")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "module", ["schema", "xmltree", "migrations", "xml_io", "diagnostics", "validate", "commands"]
)
def test_xml_io_modules_import_alone(module: str) -> None:
    result = _run(f"import pyguibud.core.{module}")
    assert result.returncode == 0, result.stderr


def test_importing_xml_io_leaves_toolkits_out() -> None:
    code = (
        "import sys, pyguibud.core.xml_io, pyguibud.core.xmltree, pyguibud.core.migrations,"
        " pyguibud.core.schema, pyguibud.uic;"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {_TOOLKITS!r});"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_reading_and_writing_leaves_toolkits_out() -> None:
    code = (
        "import sys; from pyguibud.core import read_ui_bytes, dump_ui;"
        'b = b\'<?xml version="1.0"?><pyguibud-ui schema_version="1.0" '
        'xmlns="urn:pyguibud:ui:1"/>\';'
        "dump_ui(read_ui_bytes(b).document);"
        f"bad = sorted(m for m in sys.modules if m.split('.')[0] in {_TOOLKITS!r});"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = _run(code)
    assert result.returncode == 0, result.stdout + result.stderr


def test_xmltree_avoids_the_unhardened_elementtree_entry_points() -> None:
    from pathlib import Path

    import pyguibud.core.xmltree as xmltree

    source = Path(xmltree.__file__).read_text("utf-8")
    for forbidden in (
        "ET.parse(",
        "fromstring",
        "XMLParser",
        "tostring",
        "ET.indent",
        "register_namespace",
    ):
        assert forbidden not in source, forbidden
    assert "tkinter" not in source and "registry" not in source
