"""Shared fixtures of the Qt tests (spec backends D19): offscreen, one session ``QApplication``."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("PySide6")

from tests.runtime.conftest import clean_i18n  # noqa: F401 - autouse: i18n and registry


@pytest.fixture(scope="session")
def qapp() -> Iterator[Any]:
    """The one ``QApplication`` of the test process (offscreen; the sessions reuse it)."""
    from PySide6 import QtWidgets

    app = QtWidgets.QApplication.instance()
    if app is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QtWidgets.QApplication(["pyguibud-tests"])
    yield app
