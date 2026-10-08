"""DesignerSession file state: path, stamp, read-only reason, dirty, close (spec section 2)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pyguibud import i18n
from pyguibud.core import Widget, default_registry, read_ui_string
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop
from pyguibud.designer import files
from pyguibud.designer.files import FileStamp, open_document
from pyguibud.designer.session import UNTITLED, DesignerSession

UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Label" id="lbl_a"><cell row="0" column="0"/></widget>
  </window>
</pyguibud-ui>
"""


@pytest.fixture
def ui_file(tmp_path: Path) -> Path:
    path = tmp_path / "main.ui"
    path.write_text(UI.format(version="1.0"), encoding="utf-8")
    return path


def dirty(session: DesignerSession) -> bool:
    """Through a call, so mypy does not narrow the property across mutations."""
    return session.dirty


def edit(session: DesignerSession) -> None:
    assert session.stack is not None and session.document is not None
    label = next(n for n in session.document.walk() if isinstance(n, Widget))
    assert session.stack.execute(SetProp(label, Prop(name="text", value="x"))).accepted


def test_open_document_sets_the_file_state(ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    events: list[str] = []
    session.file_changed.connect(lambda s: events.append(s.title))
    session.document_changed.connect(lambda s: events.append(f"doc {s.name}"))
    opened = open_document(ui_file)
    session.open_document(opened.result, path=opened.path, stamp=opened.stamp)
    assert session.path == opened.path and session.name == "main.ui"
    assert session.stamp == opened.stamp and session.read_only_reason is None
    assert not session.dirty and session.title == "main.ui — PyGUIbud"
    assert events == ["doc main.ui", "main.ui — PyGUIbud"]
    revision = session.revision
    edit(session)
    assert dirty(session) and session.revision > revision
    assert events[-1] == "main.ui* — PyGUIbud"  # the dirty flip is announced
    count = len(events)
    edit(session)
    assert len(events) == count  # still dirty: no new announcement


@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores modes")
def test_open_document_computes_stamp_and_reason(ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    session.open_document(read_ui_string(UI.format(version="1.0")), path=ui_file)
    assert session.stamp == FileStamp.of(ui_file)
    os.chmod(ui_file, stat.S_IREAD)
    try:
        session.open_document(read_ui_string(UI.format(version="1.0")), path=ui_file)
        assert session.read_only_reason == files.M_WRITE_PROTECTED
        assert session.title.endswith("(read-only)")
    finally:
        os.chmod(ui_file, stat.S_IREAD | stat.S_IWRITE)
    session.open_document(read_ui_string(UI.format(version="1.9")), path=None)
    assert session.read_only_reason == files.M_NEWER
    assert session.stack is not None and session.stack.read_only


def test_restored_document_opens_dirty(ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    session.open_document(read_ui_string(UI.format(version="1.0")), path=ui_file, dirty=True)
    assert session.dirty and session.title.startswith("main.ui*")


def test_templates_forget_the_previous_file(ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    opened = open_document(ui_file)
    session.open_document(opened.result, path=opened.path)
    session.new_from_template("main_window")
    assert session.path is None and session.stamp is None and session.read_only_reason is None
    assert session.name == UNTITLED and not session.dirty


def test_close_document(ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    opened = open_document(ui_file)
    session.open_document(opened.result, path=opened.path)
    edit(session)
    seen: list[object] = []
    session.document_changed.connect(lambda s: seen.append(s.document))
    session.close_document()
    assert seen == [None]
    assert session.document is None and session.stack is None and session.path is None
    assert not session.dirty and session.selection.nodes == ()
    assert session.report().findings == ()
    i18n.set_language("en_GB")
    assert session.title == "Untitled — PyGUIbud"


def test_mark_saved(tmp_path: Path, ui_file: Path) -> None:
    session = DesignerSession(default_registry())
    session.mark_saved(ui_file)  # no document: ignored
    session.open_result(read_ui_string(UI.format(version="1.0")), name=UNTITLED)
    edit(session)
    target = tmp_path / "saved.ui"
    target.write_text("written", encoding="utf-8")
    session.mark_saved(target)
    assert not session.dirty and session.path == target and session.name == "saved.ui"
    assert session.stamp == FileStamp.of(target) and session.read_only_reason is None
