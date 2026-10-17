"""The scorer counts only a leading ✅ as done (H06, Step 19a)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCORER = Path(__file__).resolve().parents[1] / "tools" / "scorer.py"


@pytest.fixture(scope="module")
def scorer() -> ModuleType:
    spec = importlib.util.spec_from_file_location("pyguibud_tools_scorer", SCORER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


@pytest.mark.parametrize(
    ("cell", "status"),
    [
        ("✅", "✅"),
        ("🔄 14a.1 ✅ · 14a.2 ⏳", "🔄"),
        ("🔶 13a ✅ · 13b ⏳", "🔄"),
        ("🔶 partial ✅", "🔄"),
        ("⏳", "⏳"),
        ("13a ✅ · 13b ⏳", "⏳"),
        ("done ✅", "✅"),
    ],
)
def test_only_a_leading_tick_is_done(scorer: ModuleType, cell: str, status: str) -> None:
    assert scorer.find_status(cell) == status
