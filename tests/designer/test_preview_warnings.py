"""QA-16a-12: the preview child's ready.json warnings reach the status bar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pyguibud.designer.app import DesignerApp
from pyguibud.designer.preview import read_warnings, warning_note
from tests.designer.test_preview_gui import (  # noqa: F401 - fixtures
    FakeProcess,
    _poll,
    app,
    children,
)


def test_read_warnings_is_backward_compatible_and_tolerant(tmp_path: Path) -> None:
    path = tmp_path / "ready.json"
    assert read_warnings(path) == []
    path.write_text(json.dumps({"themes": []}), "utf-8")
    assert read_warnings(path) == []  # an older child: no key
    items = [{"code": "runtime", "message": " a "}, {"code": "x"}, 5, {"message": 3}]
    path.write_text(json.dumps({"themes": [], "warnings": items}), "utf-8")
    assert read_warnings(path) == ["a"]
    path.write_text(json.dumps({"warnings": "nope"}), "utf-8")
    assert read_warnings(path) == []


def test_warning_note_shows_the_first_and_counts_the_rest() -> None:
    assert warning_note([]) == ""
    assert warning_note(["Only one."]) == "Warning: Only one."
    assert warning_note(["First.", "Second.", "Third."]) == "Warning: First. (+2 more)"


@pytest.mark.gui
def test_ready_with_warnings_posts_them(app: DesignerApp, children: list[FakeProcess]) -> None:  # noqa: F811
    app.preview.run()
    child = children[0]
    (child.cwd / "ready.json").write_text(
        json.dumps(
            {
                "themes": ["flatly"],
                "warnings": [
                    {"code": "runtime", "message": "W1."},
                    {"code": "runtime", "message": "W2."},
                ],
            }
        ),
        "utf-8",
    )
    _poll(app.preview)
    message = app.shell._message
    assert message.startswith("Preview of 'main' open. Warning: W1. (+1 more)")
    assert message.index("Warning") < message.index("handlers")


@pytest.mark.gui
def test_ready_without_warnings_is_unchanged(app: DesignerApp, children: list[FakeProcess]) -> None:  # noqa: F811
    app.preview.run()
    children[0].ready()
    _poll(app.preview)
    assert "Warning" not in app.shell._message
