"""Fixtures of the designer tests: i18n reset, display gate, ONE package-wide Tk root.

ttkbootstrap allows a single live root per process, so no test creates ``Tk()`` itself. The root
is shared by the whole package and reuses an already live root (for example the runtime tests'
session root) instead of creating a second one.
"""

from __future__ import annotations

import functools
import gc
import gettext
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import reset_default_registry


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


@pytest.fixture(scope="package")
def designer_root() -> Iterator[Any]:
    """The one withdrawn ttkbootstrap root of the designer tests (D13)."""
    if _display() is not None:
        pytest.skip("needs a Tk display")
    from ttkbootstrap import App, Style

    style_cls: Any = Style  # ttkbootstrap ships no annotations for get_instance
    existing = style_cls.get_instance()
    master = getattr(existing, "master", None)
    if master is not None and master.winfo_exists():
        yield master  # not ours: never destroy it
        return
    root = App(title="designer-tests")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def shell(designer_root: Any) -> Iterator[Any]:
    """A ``DesignerApp`` on the shared root; its theme is back to light afterwards."""
    from pyguibud.designer.app import DesignerApp

    app = DesignerApp(designer_root)
    yield app
    app.set_theme("light")
    app.flush_theme()
    app.dispose()
