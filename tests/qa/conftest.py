"""Shared fixtures of the QA tests: every test starts in untranslated en_GB."""

from __future__ import annotations

import gettext
from collections.abc import Iterator

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Reset the language (filled catalogues make a leaked language visible) and the widget
    registry, and restore them."""
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))  # host locale
    reset_default_registry()  # H04: a plugin registry left by one test never reaches the next
    yield
    reset_default_registry()
