"""Shared fixtures of the runtime tests: i18n reset, display gate, one session-wide Tk root."""

from __future__ import annotations

import functools
import gettext
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"'
    ' xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">\n'
)


def ui_text(windows: str, *, meta: str = "", resources: str = "", variables: str = "") -> str:
    """A complete .ui document from its parts."""
    parts = [HEADER, f'<meta source_locale="en_GB" {meta}/>']
    if resources:
        parts.append(f"<resources>{resources}</resources>")
    if variables:
        parts.append(f"<variables>{variables}</variables>")
    parts += [windows, "</pyguibud-ui>\n"]
    return "".join(parts)


def write_ui(path: Path, windows: str, **parts: str) -> Path:
    path.write_text(ui_text(windows, **parts), encoding="utf-8")
    return path


@functools.cache
def _display() -> str | None:
    """None when Tk can open a window, else the reason (probed once, in a subprocess)."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "the Tk probe timed out"
    return None if result.returncode == 0 else result.stderr.strip()[-200:] or "no display"


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("gui") is not None:
        reason = _display()
        if reason is not None:
            pytest.skip(f"needs a Tk display: {reason}")


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run in untranslated en_GB, with a fresh registry, and restore the global state."""
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture(scope="session")
def tk_root() -> Iterator[Any]:
    """The one ttkbootstrap root of the test process (ttkbootstrap allows a single root)."""
    if _display() is not None:
        pytest.skip("needs a Tk display")
    import ttkbootstrap

    root = ttkbootstrap.App(title="tests")
    root.withdraw()
    yield root
    root.destroy()
