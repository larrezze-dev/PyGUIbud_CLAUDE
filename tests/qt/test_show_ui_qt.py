"""``examples/show_ui.py --backend pyside6`` (16b UAT viewer), run offscreen in a subprocess."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.qt

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "examples" / "show_ui.py"
_PROBE = """
import json, runpy, sys, time
from PySide6 import QtCore, QtWidgets
sys.argv = ["show_ui.py", {path!r}, "--backend", "pyside6"]
show_ui = runpy.run_path({script!r})
ui = show_ui["load"]({path!r}, "pyside6", None)
tops = dict(ui.windows)
shown = {{key: top.isVisible() for key, top in tops.items()}}
titles = {{key: top.windowTitle() for key, top in tops.items()}}
def close_all():
    for top in tops.values():
        top.close()
QtCore.QTimer.singleShot(50, close_all)
QtCore.QTimer.singleShot(5000, QtWidgets.QApplication.instance().quit)  # fallback: never hang
started = time.perf_counter()
ui.run()  # runs the loop until close_all ends it, as main() does
ran = time.perf_counter() - started
print(json.dumps({{"shown": shown, "titles": titles, "ran": ran}}))
"""


def _probe(path: Path) -> dict[str, Any]:
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    code = _PROBE.format(path=str(path), script=str(SCRIPT))
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    loaded: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return loaded


def test_show_ui_shows_hello_with_pyside6() -> None:
    result = _probe(ROOT / "examples" / "hello.ui")
    assert result["shown"] == {"main": True}
    assert result["titles"] == {"main": "Hello PyGUIbud"}
    assert 0.04 <= result["ran"] < 4.0  # run() blocked until the window closed, not the fallback


def test_show_ui_shows_the_dialogs_of_a_dialog_only_document_with_pyside6() -> None:
    result = _probe(ROOT / "tests" / "codegen" / "data" / "dialogs.ui")
    assert result["shown"] == {"dlg_about": True, "dlg_ask": True}
    assert result["titles"] == {"dlg_about": "About", "dlg_ask": "Question"}
    assert 0.04 <= result["ran"] < 4.0  # the loop ended when the last dialog closed
