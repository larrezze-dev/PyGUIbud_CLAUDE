"""QA-16a-13: ``show_ui.py`` themes the hidden ttkbootstrap root of a dialog-only document."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.gui

_LOCALE = ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")

_PROBE = """
import json, logging, runpy
records = []
logging.getLogger("pyguibud_runtime").addHandler(logging.Handler())
handler = logging.getLogger("pyguibud_runtime").handlers[-1]
handler.emit = lambda record: records.append(record.getMessage())
show_ui = runpy.run_path({script!r})
ui = show_ui["load"]({path!r}, "ttkbootstrap", None)
import ttkbootstrap
theme = ttkbootstrap.Style.get_instance().theme_use()
ui.destroy()
print(json.dumps({{"theme": theme, "logs": records}}))
"""


def test_the_hidden_ttkbootstrap_root_uses_the_document_theme(tmp_path: Path) -> None:
    path = write_ui(
        tmp_path / "dialogs.ui",
        '<window id="dlg" kind="dialog"><layout type="pack"/></window>',
        meta='theme="darkly"',
    )
    code = _PROBE.format(script=str(EXAMPLES / "show_ui.py"), path=str(path))
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    loaded = json.loads(result.stdout.strip().splitlines()[-1])
    assert loaded["theme"] == "darkly"
    assert not any("theme" in message for message in loaded["logs"]), loaded["logs"]


def test_qa16b_04_an_unknown_theme_gets_the_note_of_a_main_window_document(
    tmp_path: Path,
) -> None:
    path = write_ui(
        tmp_path / "dialogs.ui",
        '<window id="dlg" kind="dialog"><layout type="pack"/></window>',
        meta='theme="bogus"',
    )
    code = _PROBE.format(script=str(EXAMPLES / "show_ui.py"), path=str(path))
    env = {k: v for k, v in os.environ.items() if k not in _LOCALE} | {"PYGUIBUD_LANG": "en_GB"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    logs = json.loads(result.stdout.strip().splitlines()[-1])["logs"]
    notes = [message for message in logs if "theme" in message]
    assert notes == ["The theme 'bogus' is not available; the default theme is used."], logs
