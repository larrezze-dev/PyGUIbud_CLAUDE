"""Suite-wide fixtures: ONE session Tk root for every Tk package, its reset, and a hang watchdog.

ttkbootstrap allows a single live root per process, so the runtime, designer and codegen tests
share :func:`tk_root` (H01-H03, Step 19a). No test package creates its own in-process root.
"""

from __future__ import annotations

import faulthandler
import functools
import gettext
import os
import re
import subprocess
import sys
from collections.abc import Generator, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n

# Per-test watchdog (pytest-timeout is not a dev dependency): a test that runs longer than this
# dumps every thread's traceback and ends the process instead of hanging the run. ``slow``
# tests (clean virtual environments) get five times as long; 0 disables it.
WATCHDOG_SECONDS = float(os.environ.get("PYGUIBUD_TEST_TIMEOUT", "120"))
ROOT_SIZE = "1280x800"  # the shared root's size between tests (above the designer's minimum)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Iterator[None]:
    if WATCHDOG_SECONDS > 0:
        slow = item.get_closest_marker("slow") is not None
        seconds = WATCHDOG_SECONDS * (5 if slow else 1)
        faulthandler.dump_traceback_later(seconds, exit=True, file=sys.__stderr__ or sys.stderr)
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


# pytest 9.1 binds a conftest's fixtures to the FIRST Directory node of its folder. A file
# argument in ``tests/`` re-collects the ``tests`` package and builds a second ``tests/qa`` node,
# so ``pytest tests/qa/a.py tests/b.py tests/qa/c.py`` silently ran c.py without the qa conftest's
# autouse fixtures (a leaked pseudo-locale, Step 19b). Reuse the first node of each folder.
_DIRECTORIES = pytest.StashKey[dict[tuple[int, Path], pytest.Directory]]()


@pytest.hookimpl(wrapper=True)
def pytest_collect_directory(
    path: Path, parent: pytest.Collector
) -> Generator[None, pytest.Directory | None, pytest.Directory | None]:
    node = yield
    seen = parent.session.stash.setdefault(_DIRECTORIES, {})
    first = seen.get((id(parent), path))
    if first is not None and first.parent is parent and type(first) is type(node):
        return first
    if node is not None:
        seen[(id(parent), path)] = node
    return node


# Timing budgets that run near their limit on a loaded machine get this much slack (H10).
BUDGET_FACTOR = float(os.environ.get("PYGUIBUD_BUDGET_FACTOR", "1.5"))


def under_coverage(config: pytest.Config) -> bool:
    """True when coverage is measuring this run (``--cov``, or any active trace function)."""
    return bool(config.getoption("cov_source", None)) or sys.gettrace() is not None


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    # Every test on the session Tk root is a GUI test, marked or not: CI runs `-m "not gui"`
    # as the blocking cross-platform job (Step 20b.1).
    for item in items:
        if "tk_root" in getattr(item, "fixturenames", ()):
            item.add_marker(pytest.mark.gui)


def pytest_runtest_setup(item: pytest.Item) -> None:
    if {"capfd", "capfdbinary"} & set(getattr(item, "fixturenames", ())):
        # fd-level capture closes the OS handles Tcl wrapped as stdout/stderr when the session
        # root was created; a file Tk opens later may reuse one (QA-10-13, H07; --capture=sys).
        pytest.fail("use capsys, not capfd: fd capture breaks the session Tk root's channels")
    if item.get_closest_marker("budget") is not None and under_coverage(item.config):
        pytest.skip("timing budget: coverage tracing distorts the timing (H06)")


@functools.cache
def display_problem() -> str | None:
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


def reset_i18n() -> None:
    """Untranslated en_GB with no listeners (the module defaults)."""
    i18n._translation = gettext.NullTranslations()
    i18n._language = i18n.SOURCE_LANGUAGE
    i18n._listeners = []


def reset_geometry(root: Any, size: str = ROOT_SIZE) -> None:
    """Give the root a known size: resize while MAPPED, then withdraw.

    A withdrawn Tk root on Windows may ignore ``geometry()``, so ``withdraw()`` followed by
    ``geometry("")`` can leave the last explicit size (e.g. the 800 x 500 minimum) to the next
    test (Step 18 UAT note). ``geometry("")`` is not used either: an empty root that was once
    mapped shrinks to 200 x 200, and a designer built on such a withdrawn root never leaves
    ``update_idletasks`` (its panes keep reconfiguring; H03).
    """
    # Tk caps a window at ``wm maxsize``, by default the screen: a 1024 x 768 CI runner kept the
    # root smaller than ROOT_SIZE, narrowing the canvas the drag tests aim at (Step 20b.1).
    match = re.match(r"(\d+)x(\d+)", size)
    if match is not None:
        width, height = root.wm_maxsize()
        root.wm_maxsize(max(width, int(match[1])), max(height, int(match[2])))
    root.deiconify()
    root.geometry(size)
    root.update_idletasks()
    root.withdraw()
    root.update_idletasks()


def reset_root(root: Any) -> None:
    """Full reset between packages: geometry, stray toplevels, option database, theme, i18n."""
    import tkinter

    for child in root.winfo_children():
        if isinstance(child, tkinter.Toplevel):
            child.destroy()
    root.option_clear()
    theme = getattr(root, "_pyguibud_tests_theme", None)
    if theme is not None:
        from ttkbootstrap import Style

        style: Any = Style  # ttkbootstrap ships no annotations for get_instance
        instance = style.get_instance()
        if instance is not None and instance.theme_use() != theme:
            instance.theme_use(theme)
    root.title("tests")
    reset_geometry(root)
    reset_i18n()


@pytest.fixture(scope="session")
def tk_root() -> Iterator[Any]:
    """The one withdrawn ttkbootstrap root of the test process."""
    if display_problem() is not None:
        pytest.skip("needs a Tk display")
    import ttkbootstrap

    root = ttkbootstrap.App(title="tests")
    root.withdraw()
    root._pyguibud_tests_theme = root.style.theme_use()  # type: ignore[attr-defined, no-untyped-call]
    yield root
    root.destroy()
