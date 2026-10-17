"""Fixtures of the designer tests: i18n reset, display gate, ONE package-wide Tk root.

ttkbootstrap allows a single live root per process, so no test creates ``Tk()`` itself: the
designer uses the suite's session root (``tests/conftest.py``), reset on entry and exit.
"""

from __future__ import annotations

import gc
import gettext
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry
from tests.conftest import display_problem, reset_root


def best_of(call: Callable[[], object], repeat: int = 7) -> float:
    """The shortest of ``repeat`` timed calls (seconds), with the garbage collector paused.

    Timing budgets use this instead of one ``perf_counter`` pair: a single gen-2 collection
    over the whole suite's heap can take longer than the budget being checked.
    """
    timings: list[float] = []
    enabled = gc.isenabled()
    gc.disable()
    try:
        for _ in range(repeat):
            started = time.perf_counter()
            call()
            timings.append(time.perf_counter() - started)
    finally:
        if enabled:
            gc.enable()
    return min(timings)


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


@pytest.fixture(scope="package")
def designer_root(tk_root: Any) -> Iterator[Any]:
    """The suite's one withdrawn root (``tests/conftest.py``), reset on entering and leaving."""
    reset_root(tk_root)
    yield tk_root
    reset_root(tk_root)


@pytest.fixture
def shell(designer_root: Any) -> Iterator[Any]:
    """A ``DesignerApp`` on the shared root; its theme is back to light afterwards."""
    from pyguibud.designer.app import DesignerApp

    app = DesignerApp(designer_root)
    yield app
    app.set_theme("light")
    app.flush_theme()
    app.dispose()


@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings and recovery data of every test go to temporary folders, never the real profile."""
    base = tmp_path_factory.mktemp("profile")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))
