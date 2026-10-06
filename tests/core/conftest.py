"""Shared fixtures of the core tests."""

from __future__ import annotations

import gettext
from collections.abc import Iterator

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run every core test in untranslated en_GB and restore the global state afterwards."""
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    reset_default_registry()
    yield
    reset_default_registry()
