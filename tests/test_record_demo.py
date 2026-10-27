"""``tools/record_demo.py`` isolates the designer's profile before importing it (Step 21b).

The demo itself is never recorded here: the module is only imported and read.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import tempfile
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "record_demo.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("record_demo_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _imports_pyguibud(node: ast.AST) -> bool:
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0].startswith("pyguibud") for alias in node.names)
    if isinstance(node, ast.ImportFrom):
        return (node.module or "").split(".")[0].startswith("pyguibud")
    return False


def test_no_pyguibud_import_at_module_level() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    assert not [n for n in tree.body if _imports_pyguibud(n)]


def test_main_isolates_settings_before_any_designer_import() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    calls = [
        n.lineno
        for n in ast.walk(main)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "isolate_settings"
    ]
    designer = [
        n.lineno
        for n in ast.walk(main)
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("pyguibud.designer")
    ]
    assert calls and designer
    assert min(calls) < min(designer)


def test_isolate_settings_points_both_folders_at_a_fresh_temp_folder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load()
    for var in (*module.PROFILE_VARS, "PYGUIBUD_LANG"):
        monkeypatch.setenv(var, "unset")  # recorded: the teardown restores the real value
        monkeypatch.delenv(var)
    base = module.isolate_settings()
    try:
        assert isinstance(base, Path) and base.is_dir()
        assert base.resolve().is_relative_to(Path(tempfile.gettempdir()).resolve())
        assert set(module.PROFILE_VARS) == {"PYGUIBUD_CONFIG_DIR", "PYGUIBUD_STATE_DIR"}
        for var in module.PROFILE_VARS:
            assert Path(os.environ[var]).resolve().is_relative_to(base.resolve())
    finally:
        shutil.rmtree(base, ignore_errors=True)
