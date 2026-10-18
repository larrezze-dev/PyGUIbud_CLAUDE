"""Step 19d hardening: the canvas card never shows raw errors (H68); a Qt start-up timeout is
explained (H57)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core import read_ui_string
from pyguibud.core.errors import PyGUIbudError
from pyguibud.designer import preview as pv
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.preview_tk import PreviewController
from tests.designer.test_canvas_engine import TWO_WINDOWS


@pytest.mark.gui
def test_h68_the_card_hides_raw_tcl_text_and_keeps_domain_messages(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = shell.shell.canvas
    real = panel.engine.build
    failures: dict[str, Exception] = {
        "one": RuntimeError('bad window path name ".!frame.!button"'),
        "two": PyGUIbudError("t.domain", "Domain reason {x}", x=7),
    }

    def build(document: Any, window: Any, host: Any) -> Any:
        if window.id in failures:
            raise failures[window.id]
        return real(document, window, host)

    monkeypatch.setattr(panel.engine, "build", build)
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    first, second = panel.stages
    panel.show_window(first.window)
    panel.show_window(second.window)
    raw = first.card.winfo_children()[0].cget("text")
    assert "bad window path" not in raw and "unexpected error" in raw
    assert str(first.error) == "an unexpected error occurred; see the log"
    domain = second.card.winfo_children()[0].cget("text")
    assert domain == "This window cannot be drawn on the canvas: Domain reason 7"


@pytest.mark.parametrize(
    ("toolkit", "message"), [("pyside6", pv.M_TIMEOUT_QT), ("ttkbootstrap", pv.M_TIMEOUT)]
)
def test_h57_a_qt_timeout_names_the_platform_plugin(toolkit: str, message: str) -> None:
    posted: list[str] = []
    controller: Any = object.__new__(PreviewController)
    controller.post = posted.append
    controller.state = SimpleNamespace(exited=lambda: False)
    controller.current = None
    controller.toolkit = lambda: toolkit
    controller._exited(1, ("crash", ""), "", True)
    assert posted == [message.format(variable="QT_QPA_PLATFORM")]
    assert ("QT_QPA_PLATFORM" in posted[0]) == (toolkit == "pyside6")
