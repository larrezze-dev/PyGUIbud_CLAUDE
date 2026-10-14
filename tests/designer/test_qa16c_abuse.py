"""QA abuse tests of Step 16c that drive the designer (moved from ``tests/qa`` so the designer's
session root never shares a process scope with ``tests/runtime``; see ``test_step16c_abuse.py``)."""

# ruff: noqa: F811 - the fixtures of test_preview_gui are re-used by import

from __future__ import annotations

import importlib.util
import json
import time
from typing import Any

import pytest

from pyguibud.designer.app import DesignerApp
from tests.designer.test_preview_gui import FakeProcess, _poll, app, children  # noqa: F401

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None


@pytest.mark.gui
@pytest.mark.parametrize(
    "message",
    ["\ud800 lone", "line1\nline2", "nul\x00here", "x" * 15_000, "{first} {count} %s %(x)s"],
    ids=["surrogate", "newline", "nul", "15k", "format-markers"],
)
def test_malformed_warnings_reach_the_status_bar_without_an_error(
    app: DesignerApp, children: list[FakeProcess], message: str
) -> None:
    app.preview.run()
    (children[0].cwd / "ready.json").write_text(
        json.dumps({"themes": [], "warnings": [{"message": message}] * 3}), "utf-8"
    )
    _poll(app.preview)
    app.root.update()
    status = app.shell._message
    assert status.startswith("Preview of 'main' open. Warning: ") and "(+2 more)" in status


# ------------------------------------------------------------------ real designer + real Qt child
@pytest.mark.gui
@pytest.mark.slow
@pytest.mark.skipif(not HAS_PYSIDE6, reason="needs PySide6 for the preview child")
def test_designer_flows_with_a_real_qt_child_leave_no_process(
    app: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    """16c UAT 1 + break-it, unattended: Toolkit PySide6, F5, live Deutsch, a toolkit/F5 storm,
    Shift+F5, then Ctrl+Q (dispose). Offscreen children: nothing pops up on the desktop."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    preview, started = app.preview, []
    real = preview.runner.popen

    def popen(*args: Any, **kwargs: Any) -> Any:
        started.append(real(*args, **kwargs))
        return started[-1]

    preview.runner.popen = popen

    def settle(seconds: float = 40.0) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            app.root.update()
            time.sleep(0.02)
            ready = preview.state.phase == "running" and preview.runner._ready
            if ready and not preview.state.pending:
                return True
        return False

    preview.set_toolkit("pyside6")
    preview.run()
    assert settle(), app.shell._message
    assert "--backend" in started[-1].args and "pyside6" in started[-1].args
    assert app.shell._message.startswith("Preview of 'main' open.")
    preview.set_language("de_DE")
    for _ in range(25):
        app.root.update()
        time.sleep(0.02)
    assert started[-1].poll() is None  # the live switch kept the child
    for index in range(10):
        preview.set_toolkit(("tkinter", "pyside6", "ttkbootstrap")[index % 3])
        preview.run()
        app.root.update()
    preview.set_toolkit("pyside6")
    preview.run()
    assert settle(), app.shell._message
    assert [p for p in started if p.poll() is None] == [started[-1]]  # one preview, the last
    assert "pyside6" in started[-1].args
    preview.close()  # Shift+F5
    deadline = time.monotonic() + 10
    while preview.state.phase != "idle" and time.monotonic() < deadline:
        app.root.update()
        time.sleep(0.02)
    assert preview.state.phase == "idle" and app.shell._message == "Preview closed."
    preview.run()
    assert settle()
    preview.dispose()  # what Ctrl+Q does to the preview
    for process in started:
        process.wait(timeout=5)
    assert all(p.poll() is not None for p in started)
