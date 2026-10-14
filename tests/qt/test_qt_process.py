"""PySide6 cases that need a fresh process: one ``QCoreApplication`` per process (spec §4.1, §6).

B2 (no display), a non-GUI ``QCoreApplication``, B9 (Tk and Qt together), B10 (``run()`` inside a
running loop) and the life of an application the session owns. Each script prints one JSON line;
every script that enters ``exec()`` arms a fallback quit so that a regression cannot hang the run.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from tests.runtime.conftest import EXAMPLES

pytestmark = pytest.mark.qt

ROOT = Path(__file__).resolve().parents[2]
HELLO = str(EXAMPLES / "hello.ui")
_LOCALE = ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")
_DISPLAY = ("QT_QPA_PLATFORM", "DISPLAY", "WAYLAND_DISPLAY")


def _run(code: str, *, offscreen: bool = True) -> dict[str, Any]:
    """Run ``code`` in a fresh interpreter; ``offscreen=False`` also clears every display variable
    (B2). Otherwise DISPLAY/WAYLAND_DISPLAY are kept: Tk needs them on Linux (pytest-xvfb)."""
    dropped = _LOCALE if offscreen else _LOCALE + _DISPLAY
    env = {k: v for k, v in os.environ.items() if k not in dropped}
    if offscreen:
        env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    loaded: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return loaded


# ---------------------------------------------------------------- B2
def test_b2_no_display_is_refused_before_any_application_exists() -> None:
    # A real Linux without a display cannot be reproduced on Windows, and faking the global
    # ``sys.platform`` would also change the loader, the validator and the PySide6 import.
    # So only the backend module's view of ``sys`` is replaced: ``PySide6Backend.build`` then
    # runs its D8 guard (``display_problem(sys.platform, os.environ)``) exactly as on Linux,
    # with no DISPLAY, WAYLAND_DISPLAY or QT_QPA_PLATFORM in the environment.
    result = _run(
        f"""
        import json, sys, types
        from PySide6 import QtCore, QtWidgets
        import pyguibud.backends.pyside6 as backend
        from pyguibud_runtime import UiError, load_ui
        backend.sys = types.SimpleNamespace(platform="linux", argv=sys.argv)
        try:
            load_ui({HELLO!r}, None, strict=False, backend="pyside6")
            code = None
        except UiError as exc:
            code = exc.code
        print(json.dumps({{
            "code": code,
            "app": QtCore.QCoreApplication.instance() is None,
            "real_platform": sys.platform,
        }}))
        """,
        offscreen=False,
    )
    assert result == {"code": "runtime.no_display", "app": True, "real_platform": sys.platform}


# ---------------------------------------------------------------- QCoreApplication
def test_a_running_core_application_is_backend_unavailable() -> None:
    result = _run(
        f"""
        import json
        from PySide6 import QtCore, QtWidgets
        from pyguibud_runtime import UiError, load_ui
        core = QtCore.QCoreApplication(["core"])
        try:
            load_ui({HELLO!r}, None, strict=False, backend="pyside6")
            code = None
        except UiError as exc:
            code = exc.code
        app = QtCore.QCoreApplication.instance()
        print(json.dumps({{
            "code": code,
            "same": app is core,
            "gui": isinstance(app, QtWidgets.QApplication),
        }}))
        """
    )
    assert result == {"code": "runtime.backend_unavailable", "same": True, "gui": False}


# ---------------------------------------------------------------- B9
_MIXED = """
import json, logging
from pyguibud_runtime import load_ui
records = []
class Collect(logging.Handler):
    def emit(self, record):
        records.append(record.getMessage())
logging.getLogger("pyguibud_runtime").addHandler(Collect())
uis = []
for backend in {order!r}:
    uis.append(load_ui({hello!r}, None, strict=False, backend=backend))
tk_ui = uis[{order!r}.index("tkinter")]
qt_ui = uis[{order!r}.index("pyside6")]
result = {{
    "tk": tk_ui.main.winfo_exists() == 1,
    "qt": qt_ui.main.isVisible(),
    "mixed": sum("Tk and Qt windows" in m for m in records),
}}
qt_ui.destroy()
tk_ui.destroy()
print(json.dumps(result))
"""


@cache
def _tk_display() -> str | None:
    from tests.runtime.conftest import _display

    return _display()


@pytest.mark.parametrize(
    ("order", "warnings"),
    [
        (("tkinter", "pyside6"), 1),
        # Documented: only the Qt build looks for a live Tk root, so Qt first gives no warning.
        (("pyside6", "tkinter"), 0),
    ],
)
def test_b9_tk_and_qt_interfaces_in_one_process(order: tuple[str, str], warnings: int) -> None:
    reason = _tk_display()
    if reason is not None:
        pytest.skip(f"needs a Tk display: {reason}")
    result = _run(_MIXED.format(order=list(order), hello=HELLO))
    assert result == {"tk": True, "qt": True, "mixed": warnings}


# ---------------------------------------------------------------- B10, owned application
_OWNED = f"""
import json, time
from PySide6 import QtCore, QtWidgets
from pyguibud_runtime import UiError, load_ui
out = {{}}
ui = load_ui({HELLO!r}, None, strict=False, backend="pyside6")
app = QtWidgets.QApplication.instance()
out["owns"] = ui._session._owns
def nested():
    started = time.perf_counter()
    ui.run()  # B10: a loop is running, so this returns at once
    out["nested"] = time.perf_counter() - started
QtCore.QTimer.singleShot(50, nested)
QtCore.QTimer.singleShot(200, ui.main.close)
QtCore.QTimer.singleShot(5000, app.quit)  # fallback: never hang
started = time.perf_counter()
ui.run()
out["run1"] = time.perf_counter() - started
try:
    ui.show("main")
    out["after"] = "alive"
except UiError as exc:
    out["after"] = exc.code
out["same_app"] = QtWidgets.QApplication.instance() is app
second = load_ui({HELLO!r}, None, strict=False, backend="pyside6")
out["owns2"] = second._session._owns
QtCore.QTimer.singleShot(300, second.main.close)
QtCore.QTimer.singleShot(5000, app.quit)
started = time.perf_counter()
second.run()
out["run2"] = time.perf_counter() - started
print(json.dumps(out))
"""


@pytest.fixture(scope="module")
def owned() -> dict[str, Any]:
    """One process: an owned application, a nested ``run()``, then a second ``load_ui``."""
    return _run(_OWNED)


def test_the_first_session_owns_the_application_and_runs_until_closed(
    owned: dict[str, Any],
) -> None:
    assert owned["owns"] is True
    assert 0.15 <= owned["run1"] < 4.0  # ended by closing the main window, not the fallback
    assert owned["after"] == "runtime.destroyed"
    assert owned["same_app"] is True


def test_b10_run_inside_a_running_loop_returns_at_once(owned: dict[str, Any]) -> None:
    assert owned["nested"] < 0.1


def test_a_second_interface_after_the_first_ended_runs_its_own_loop(
    owned: dict[str, Any],
) -> None:
    # 16b fix: run() enters exec() whenever no loop runs, and the backend remembers the
    # application it created, so closing the second main window still quits it (Tk parity).
    assert owned["owns2"] is True
    assert 0.25 <= owned["run2"] < 4.0  # ended by closing the main window, not the fallback


# ---------------------------------------------------------------- two live interfaces
_TWO = f"""
import json, time
from PySide6 import QtCore, QtWidgets
from pyguibud_runtime import load_ui
first = load_ui({HELLO!r}, None, strict=False, backend="pyside6")
second = load_ui({HELLO!r}, None, strict=False, backend="pyside6")
app = QtWidgets.QApplication.instance()
out = {{}}
def check():
    out["first"] = [first._session.alive(), first.main.isVisible()]
    out["second"] = second._session.alive()
    first.main.close()
QtCore.QTimer.singleShot(100, second.main.close)
QtCore.QTimer.singleShot(400, check)
QtCore.QTimer.singleShot(5000, app.exit)  # fallback: never hang (exit() closes no window)
started = time.perf_counter()
first.run()
out["run"] = time.perf_counter() - started
print(json.dumps(out))
"""


def test_closing_one_interface_leaves_the_other_alive_and_the_last_ends_the_loop() -> None:
    # Ruling (spec §14): Qt 6 quit() closes every window, so only the last live session quits.
    result = _run(_TWO)
    assert result["first"] == [True, True]
    assert result["second"] is False
    assert 0.35 <= result["run"] < 4.0  # ended by closing the first window, not the fallback
