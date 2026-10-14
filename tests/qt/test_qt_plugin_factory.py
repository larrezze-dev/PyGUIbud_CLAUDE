"""Step 17b: the plugin factory path and guard of the Qt builder (spec plugins 4.1-4.2, 11)."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtWidgets

from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui
from tests.runtime.test_tb_factories import TB_BODY, TB_VARS, _label_text, _registry

pytestmark = pytest.mark.qt


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()


def _spec(factory: Any) -> WidgetSpec:
    return WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(_label_text(),),
        factories={"pyside6": factory},
    )


def _wrong_inner(parent: Any, props: dict[str, Any]) -> Any:
    return QtWidgets.QPushButton(parent)  # not a QLabel, the fallback's Qt class


def _strays(parent: Any, props: dict[str, Any]) -> Any:
    QtWidgets.QWidget(parent)
    return QtWidgets.QLabel(parent)


def _raising(parent: Any, props: dict[str, Any]) -> Any:
    QtWidgets.QLabel(parent)
    raise RuntimeError("boom")


def _good(parent: Any, props: dict[str, Any]) -> Any:
    outer = QtWidgets.QFrame(parent)
    inner = QtWidgets.QLabel(outer)
    return outer, inner


def _build(tmp_path: Path, uis: list[LoadedUi], body: str, **parts: str) -> LoadedUi:
    path = write_ui(
        tmp_path / "q.ui", f'<window id="w"><layout type="grid"/>{body}</window>', **parts
    )
    ui = load_ui(path, None, strict=False, backend="pyside6")
    uis.append(ui)
    return ui


GAUGES = "".join(
    f'<widget class="zz:Gauge" id="g{i}" fallback="Label">'
    f'<prop name="text" translatable="true">G{i}</prop><cell row="{i}" column="0"/></widget>'
    for i in range(2)
)


@pytest.mark.parametrize(
    ("factory", "stage"), [(_wrong_inner, "check"), (_strays, "check"), (_raising, "create")]
)
def test_a_failing_qt_factory_falls_back(
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
        ui = _build(tmp_path, loaded, GAUGES)
    assert type(ui.g0) is QtWidgets.QLabel and ui.g1.text() == "G1"
    parent: Any = ui.g0.parentWidget()
    kids = [c for c in parent.children() if c.isWidgetType()]
    assert set(map(id, kids)) == {id(ui.g0), id(ui.g1)}
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [d.params["stage"] for d in failures] == [stage]


def test_a_working_qt_factory_is_wired_as_its_fallback(
    tmp_path: Path, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "_default", _registry(_spec(_good)))
    ui = _build(tmp_path, loaded, GAUGES)
    assert type(ui.g0) is QtWidgets.QLabel and ui.g0.text() == "G0"
    assert type(ui.g0.parentWidget()) is QtWidgets.QFrame


def test_tb_widgets_show_their_fallbacks_under_pyside6(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded, TB_BODY, variables=TB_VARS)
    assert type(ui.mtr) is QtWidgets.QProgressBar and type(ui.ent_day) is QtWidgets.QLineEdit
    assert type(ui.tbl) is QtWidgets.QTreeWidget and type(ui.tgl) is QtWidgets.QCheckBox
    assert "failed to build" not in caplog.text
    assert caplog.text.count("'tb:Meter' is shown as its fallback") == 1
