"""Shared fixtures of the runtime tests: i18n reset, display gate, the shared Tk root is ``tk_root``
in ``tests/conftest.py``."""

from __future__ import annotations

import gettext
from collections.abc import Iterator
from pathlib import Path

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry
from tests.conftest import display_problem

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


_display = display_problem


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
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))  # host locale
    reset_default_registry()
    yield
    reset_default_registry()
