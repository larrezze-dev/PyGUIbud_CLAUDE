"""Step 17b (testing pass): more of the Qt plugin factory path (spec plugins 4.1-4.2, 5, 11).

Complements ``test_qt_plugin_factory.py`` (not repeated here).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtWidgets

from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud.core.widgets import core_widgets
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import write_ui
from tests.runtime.test_tb_factories import TB_BODY, TB_VARS, _label_text, _registry

pytestmark = pytest.mark.qt

TB_CLASSES = ("tb:Meter", "tb:Floodgauge", "tb:DateEntry", "tb:Tableview", "tb:ToggleButton")


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()


def _spec(factory: Any, fallback: str = "Label", **kw: Any) -> WidgetSpec:
    base = next(s for s in core_widgets() if s.name == fallback)
    return WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback=fallback,
        properties=(_label_text(),),
        events=tuple(e for e in base.events if e == "command"),
        factories={"pyside6": factory},
        **kw,
    )


def _build(
    tmp_path: Path, uis: list[LoadedUi], body: str, handlers: object = None, **parts: str
) -> LoadedUi:
    path = write_ui(
        tmp_path / "q.ui", f'<window id="w"><layout type="grid"/>{body}</window>', **parts
    )
    ui = load_ui(path, handlers, strict=handlers is not None, backend="pyside6")
    uis.append(ui)
    return ui


def _gauges(count: int, fallback: str = "Label", events: str = "") -> str:
    return "".join(
        f'<widget class="zz:Gauge" id="g{i}" fallback="{fallback}">'
        f'<prop name="text" translatable="true">G{i}</prop>{events}'
        f'<cell row="{i}" column="0"/></widget>'
        for i in range(count)
    )


def _none(parent: Any, props: dict[str, Any]) -> Any:
    return None


def _exits(parent: Any, props: dict[str, Any]) -> Any:
    QtWidgets.QLabel(parent)
    raise SystemExit(2)


def _wrong_parent(parent: Any, props: dict[str, Any]) -> Any:
    return QtWidgets.QLabel()  # parentless: outer.parent() is not ``parent``


@pytest.mark.parametrize(
    ("factory", "stage"),
    [(_none, "check"), (_exits, "create"), (_wrong_parent, "check"), ("zz_no_module:f", "import")],
)
def test_more_failing_qt_factories_fall_back(
    tmp_path: Path,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
    stage: str,
) -> None:
    reg = _registry(_spec(factory))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded, _gauges(2))
    assert type(ui.g0) is QtWidgets.QLabel and ui.g1.text() == "G1"
    parent: Any = ui.g0.parentWidget()
    kids = [c for c in parent.children() if c.isWidgetType()]
    assert set(map(id, kids)) == {id(ui.g0), id(ui.g1)}
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [d.params["stage"] for d in failures] == [stage]


def test_a_qt_factory_that_deletes_its_parent_is_reported_then_refused(
    tmp_path: Path, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    """17b: the diagnostic is recorded before the guard touches the deleted parent."""
    import shiboken6

    def vandal(parent: Any, props: dict[str, Any]) -> Any:
        widget = QtWidgets.QLabel(parent)
        shiboken6.delete(parent)  # the C++ object goes now, not at the next event loop turn
        return widget

    reg = _registry(_spec(vandal))
    monkeypatch.setattr(registry_module, "_default", reg)
    with pytest.raises(UiError) as caught:  # no fallback fits a deleted parent: a clean refusal
        _build(tmp_path, loaded, _gauges(1))
    assert caught.value.code == "runtime.build_failed"
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [d.params["stage"] for d in failures] == ["check"]


def test_many_failing_qt_widgets_one_log_one_diagnostic_one_revision_bump(
    tmp_path: Path,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = _registry(_spec(_none))
    monkeypatch.setattr(registry_module, "_default", reg)
    assert reg.diagnostics() == ()  # loads the registry
    revision = reg.revision
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded, _gauges(60))
    assert ui.g59.text() == "G59"
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    assert len([d for d in reg.diagnostics() if d.code == "registry.factory_failed"]) == 1
    assert reg.revision == revision + 1


def test_a_qt_factory_text_slot_is_retranslated_and_events_reach_the_inner_widget(
    tmp_path: Path, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    def button(parent: Any, props: dict[str, Any]) -> Any:
        outer = QtWidgets.QFrame(parent)
        return outer, QtWidgets.QPushButton(outer)

    monkeypatch.setattr(registry_module, "_default", _registry(_spec(button, "Button")))
    calls: list[str] = []
    events = '<event name="command" handler="on_cmd"/>'
    ui = _build(
        tmp_path,
        loaded,
        _gauges(1, "Button", events),
        {"on_cmd": lambda: calls.append("cmd")},
    )
    assert type(ui.g0) is QtWidgets.QPushButton and ui.g0.text() == "G0"

    class Translator:
        def gettext(self, text: str) -> str:
            return {"G0": "_Vai"}.get(text, text)

        def pgettext(self, _context: str, text: str) -> str:
            return self.gettext(text)

    ui.retranslate(translator=Translator())
    assert ui.g0.text() == "&Vai"  # the mnemonic marker of a Qt button
    ui.g0.click()
    assert calls == ["cmd"]


def test_all_tb_widgets_fall_back_under_pyside6_with_one_note_per_class(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    twice = TB_BODY + TB_BODY.replace('id="', 'id="x_').replace('row="', 'row="1')
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded, twice, variables=TB_VARS)
    assert type(ui.flg) is QtWidgets.QProgressBar and type(ui.x_flg) is QtWidgets.QProgressBar
    for name in TB_CLASSES:
        assert caplog.text.count(f"'{name}' is shown as its fallback") == 1, name
    assert not [
        d
        for d in registry_module.default_registry().diagnostics()
        if d.code == "registry.factory_failed"
    ]
    # the fallback behaves as itself: the bound variables still drive it
    ui.vars.level.set(70)
    assert ui.mtr.value() == ui.x_mtr.value() != 0


def test_pyside6_never_imports_tbwidgets(tmp_path: Path) -> None:
    window = f'<window id="w" kind="main"><layout type="grid"/>{TB_BODY}</window>'
    path = write_ui(tmp_path / "tb.ui", window, variables=TB_VARS)
    code = (
        "import os, sys\n"
        "os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n"
        "from pyguibud_runtime import load_ui\n"
        f"ui = load_ui({str(path)!r}, None, strict=False, backend='pyside6')\n"
        "print(sorted({type(w).__name__ for w in ui.widgets.values()}))\n"
        "print('pyguibud.backends._tbwidgets' in sys.modules, 'ttkbootstrap' in sys.modules)\n"
        "ui.destroy()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    classes, imported = result.stdout.strip().splitlines()[-2:]
    assert "QProgressBar" in classes and "QTreeWidget" in classes
    assert imported == "False False"
