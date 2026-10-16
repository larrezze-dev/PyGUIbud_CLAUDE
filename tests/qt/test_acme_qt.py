"""Step 17c: the sample plugin's Qt factory (``acme_pyguibud:qt_swatch``) through the Qt builder.

Spec ``docs/specs/plugins.md`` 4.1-4.2, 9, 11 ("Backends (qt)") and 14b ("the Qt factory path
exists"). This pins that plugin ``pyside6`` factories really run (no ``registry.no_factory``).
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtWidgets

from pyguibud.core.registry import Registry
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui
from tests.runtime.test_acme_plugin import acme  # noqa: F401 - fixture

pytestmark = pytest.mark.qt

SWATCHES = "".join(
    f'<widget class="acme:ColourSwatch" id="swt{i}" fallback="Label" plugin="acme-pyguibud">'
    f'<prop name="text" translatable="true">S{i}</prop>{extra}<cell row="{i}" column="0"/></widget>'
    for i, extra in enumerate(("", '<prop name="colour">#AA0011</prop>'))
)


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()


def _build(tmp_path: Path, uis: list[LoadedUi]) -> LoadedUi:
    path = write_ui(tmp_path / "q.ui", f'<window id="w"><layout type="grid"/>{SWATCHES}</window>')
    ui = load_ui(path, None, strict=False, backend="pyside6")
    uis.append(ui)
    return ui


def test_the_qt_factory_of_the_plugin_runs(
    tmp_path: Path, loaded: list[LoadedUi], acme: Any, monkeypatch: pytest.MonkeyPatch,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    reg: Registry = acme(None)
    calls: list[tuple[str, str, bool]] = []
    original = reg.load_factory

    def spy(spec: Any, backend: str) -> Any:
        factory = original(spec, backend)
        calls.append((spec.name, backend, factory is not None))
        return factory

    monkeypatch.setattr(reg, "load_factory", spy)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded)
    assert ("acme:ColourSwatch", "pyside6", True) in calls
    assert type(ui.swt0) is QtWidgets.QLabel and ui.swt0.text() == "S0"
    assert "#2E86DE" in ui.swt0.styleSheet() and "#AA0011" in ui.swt1.styleSheet()
    assert ui.swt0.parentWidget() is ui.swt1.parentWidget()
    assert "shown as its fallback" not in caplog.text and "failed to build" not in caplog.text
    assert reg.resolve("acme:ColourSwatch", "pyside6").code != "registry.no_factory"
    assert [d for d in reg.diagnostics() if d.distribution == "acme-pyguibud"] == []


def test_a_breaking_qt_factory_falls_back_once(
    tmp_path: Path, loaded: list[LoadedUi], acme: Any,  # noqa: F811
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    reg: Registry = acme("factory")
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded)
    assert type(ui.swt0) is QtWidgets.QLabel and ui.swt1.text() == "S1"
    assert ui.swt0.styleSheet() == ""  # the plain fallback, not the swatch
    parent: Any = ui.swt0.parentWidget()
    kids = [c for c in parent.children() if c.isWidgetType()]
    assert {id(k) for k in kids} == {id(ui.swt0), id(ui.swt1)}
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [(d.distribution, d.params["stage"]) for d in failures] == [("acme-pyguibud", "create")]
    assert caplog.text.count("'acme:ColourSwatch' failed to build") == 1
