"""Step 19d (codegen and the Tk factory path): H65 and H49 (spec docs/specs/hardening.md).

The H65 test is pure (it only generates text). The H49 setter test builds widgets with Tk.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from pyguibud.codegen import generate_python
from pyguibud.core import registry as registry_module
from pyguibud.core.registry import WIDGETS_GROUP, Registry, _metadata_entry_points
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import write_ui
from tests.core.test_plugins_17a import _EP, _builtins, _Dist

ACME_SRC = Path(__file__).resolve().parents[2] / "examples" / "acme_plugin" / "src"


def test_h65_a_calendar_invalid_date_is_reported_at_export(tmp_path: Path) -> None:
    path = write_ui(
        tmp_path / "dates.ui",
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="tb:DateEntry" id="bad" fallback="Entry">'
        '<prop name="value">2023-02-30</prop><cell row="0" column="0"/></widget></window>',
    )
    generated = generate_python(read_ui(str(path)), str(path), output=str(tmp_path / "x_ui.py"))
    (finding,) = [w for w in generated.warnings if w.code == "codegen.bad_date"]
    assert finding.params == {"value": "2023-02-30"} and finding.anchor is not None
    assert "2023" not in generated.text.partition("class ")[2]  # still left out of the module
    assert finding.message  # a translated msgid, rendered without error


@pytest.mark.gui
def test_h49_a_raising_text_setter_is_isolated(
    tk_root: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from pyguibud_runtime import load_ui

    monkeypatch.setenv("ACME_PYGUIBUD_BREAK", "setter")
    monkeypatch.syspath_prepend(str(ACME_SRC))
    monkeypatch.delitem(sys.modules, "acme_pyguibud", raising=False)
    acme = importlib.import_module("acme_pyguibud")
    widgets = [
        *_builtins(),
        _EP("acme", "acme_pyguibud:widgets", _Dist("acme-pyguibud"), acme.widgets),
    ]

    def source(group: str) -> Iterable[Any]:
        return widgets if group == WIDGETS_GROUP else _metadata_entry_points(group)

    reg = Registry(entry_points=source)
    monkeypatch.setattr(registry_module, "_default", reg)
    path = write_ui(
        tmp_path / "swatch.ui",
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="acme:ColourSwatch" id="swt" fallback="Label" plugin="acme-pyguibud">'
        '<prop name="text" translatable="true">Swatch</prop><cell row="0" column="0"/>'
        "</widget></window>",
    )
    caplog.set_level(logging.WARNING)
    try:
        for backend in ("ttkbootstrap", "tkinter"):
            ui = load_ui(path, None, strict=False, backend=backend, master=tk_root)
            assert ui.swt.winfo_class() in ("TLabel", "Label")
            assert str(ui.swt.cget("text")) == "Swatch"  # the fallback shows the text
            ui.retranslate()  # the broken slot was never kept, so this cannot raise
            ui.destroy()
    finally:
        sys.modules.pop("acme_pyguibud", None)
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert {d.params["stage"] for d in failures} == {"check"}
    assert "acme-pyguibud was told to break (setter)" in failures[0].params["error"]
