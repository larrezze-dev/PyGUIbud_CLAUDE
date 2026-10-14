"""Step 17b (testing pass): native ``tb:`` emission (spec plugins 7, D13) beyond the golden file.

The generated module runs in a child process without PyGUIbud (``run_generated``) and the same
probe runs against ``load_ui`` in another child, so this module creates no Tk root of its own.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.codegen import generate_python
from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud.core.registry import WIDGETS_GROUP, Registry, _metadata_entry_points
from pyguibud.core.widgets import core_widgets, tb_widgets
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import ROOT, run_generated, write_ui

pytestmark = pytest.mark.gui

BODY = """
<widget class="tb:Meter" id="mtr" bind="level" fallback="Progressbar" tb:bootstyle="success">
  <prop name="amount_format">{:.1f} kg</prop><prop name="interactive">true</prop>
  <prop name="maximum">50</prop><prop name="meter_size">150</prop>
  <prop name="meter_thickness">5</prop><prop name="meter_type">semi</prop>
  <prop name="show_text">false</prop><prop name="subtext" translatable="true">Level</prop>
  <cell row="0" column="0"/></widget>
<widget class="tb:Floodgauge" id="flg" bind="count" fallback="Progressbar">
  <prop name="length">90</prop><prop name="mask">{} items</prop><prop name="maximum">10</prop>
  <prop name="orient">vertical</prop><prop name="text" translatable="true">Items</prop>
  <cell row="0" column="1"/></widget>
<widget class="tb:DateEntry" id="day" bind="when" fallback="Entry">
  <event name="change" handler="on_change"/><cell row="1" column="0"/></widget>
<widget class="tb:DateEntry" id="fixed" fallback="Entry">
  <prop name="date_format">%d/%m/%Y</prop><prop name="first_weekday">6</prop>
  <prop name="state">disabled</prop><prop name="value">2024-02-29</prop>
  <prop name="width">20</prop><cell row="1" column="1"/></widget>
<widget class="tb:DateEntry" id="bad" fallback="Entry">
  <prop name="value">2026-02-30</prop><cell row="2" column="0"/></widget>
<widget class="tb:Tableview" id="tbl" fallback="Treeview">
  <prop name="columns" translatable="true">Name;Colour;Amount</prop><prop name="height">4</prop>
  <prop name="pagesize">3</prop><prop name="paginated">true</prop>
  <prop name="searchable">true</prop><prop name="selectmode">extended</prop>
  <event name="select" handler="on_select"/><cell row="3" column="0" columnspan="2"/></widget>
<widget class="tb:ToggleButton" id="tgl" bind="on" fallback="Checkbutton"
        tb:bootstyle="outline-danger">
  <prop name="shape">square</prop><prop name="text" translatable="true">_Enabled</prop>
  <event name="command" handler="on_cmd"/><cell row="4" column="0"/></widget>
<widget class="tb:ToggleButton" id="tg2" bind="num" fallback="Checkbutton">
  <event name="change" handler="on_change"/><cell row="4" column="1"/></widget>
"""
VARIABLES = (
    '<var id="level" type="double" default="12.5"/><var id="count" type="int" default="3"/>'
    '<var id="when" type="string" default="2026-10-14"/><var id="on" type="bool" default="true"/>'
    '<var id="num" type="int" default="0"/>'
)

# Runs after ``ui`` exists in both children; fills ``out`` with what both builds must share.
PROBE = """
def outer(w, cls):
    while type(w).__name__ != cls:
        w = w.master
    return w
out["types"] = {k: type(getattr(ui, k)).__name__ for k in
                ("mtr", "flg", "day", "fixed", "bad", "tbl", "tgl", "tg2")}
m = ui.mtr
out["meter"] = [m.cget(k) for k in ("amount_used", "amount_total", "meter_type", "meter_size",
                "meter_thickness", "amount_format", "subtext", "show_text", "interactive")]
f = ui.flg
out["flood"] = [str(f.cget(k)) for k in ("value", "maximum", "orient", "length", "mask", "text")]
fixed = outer(ui.fixed, "DateEntry")
out["fixed"] = [ui.fixed.get(), str(ui.fixed.cget("state")), int(ui.fixed.cget("width")),
                fixed._firstweekday, str(fixed.button.cget("state"))]
out["day"] = [ui.day.get(), str(ui.day.cget("textvariable")) == str(ui.vars.when)]
table = outer(ui.tbl, "Tableview")
out["table"] = [[ui.tbl.heading(c)["text"] for c in ui.tbl["columns"]], table.pagesize,
                int(ui.tbl.cget("height")), str(ui.tbl.cget("selectmode")),
                table._paginated, table._searchable]
out["styles"] = [ui.tgl.cget("style"), ui.tg2.cget("style"), ui.tgl.cget("text"),
                 int(ui.tgl.cget("underline"))]
ui.vars.level.set(30.5)
out["link"] = [m.amount_used_var.get()]
m.amount_used_var.set(7)
out["link"].append(ui.vars.level.get())
ui.vars.count.set(6)
out["flood_var"] = float(f.cget("value"))
ui.vars.when.set("2027-01-02")
out["day_var"] = ui.day.get()
ui.tgl.invoke()
ui.tg2.invoke()
out["toggles"] = [ui.vars.on.get(), ui.vars.num.get()]
row = table.insert_row("end", ("a", "red", 1))
table.load_table_data()
ui.main.deiconify()
ui.main.update()
ui.tbl.selection_set(row.iid)  # Tk sends <<TreeviewSelect>> to a mapped view
ui.tbl.update()
class T:
    table = {"Level": "Nivel", "Items": "Objets", "_Enabled": "_Activo",
             "Name;Colour;Amount": "Nom"}
    def gettext(self, text): return self.table.get(text, text)
    def pgettext(self, context, text): return self.gettext(text)
ui.retranslate(translator=T())
out["retranslated"] = [m.cget("subtext"), f.cget("text"), ui.tgl.cget("text"),
                       [ui.tbl.heading(c)["text"] for c in ui.tbl["columns"]]]
out["calls"] = sorted(calls)
ui.destroy()
"""
HANDLERS = """
calls = []
class H:
    def on_change(self): calls.append("change")
    def on_cmd(self): calls.append("cmd")
    def on_select(self): calls.append("select")
"""


def _ui(tmp_path: Path, body: str = BODY, variables: str = VARIABLES) -> Path:
    return write_ui(
        tmp_path / "tbx.ui",
        f'<window id="main" kind="main"><layout type="grid"/>{body}</window>',
        variables=variables,
    )


def _generate(path: Path) -> tuple[Path, Any]:
    module = path.with_name(path.stem + "_ui.py")
    generated = generate_python(read_ui(str(path)), str(path), output=str(module))
    module.write_text(generated.text, encoding="utf-8", newline="\n")
    return module, generated


def _run_load_ui(path: Path, body: str) -> dict[str, Any]:
    code = (
        "import json, logging, sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        "logging.basicConfig(level=logging.WARNING, stream=sys.stderr)\n"
        "from pyguibud_runtime import load_ui\n"
        "out = {}\n"
        + HANDLERS
        + f"ui = load_ui({str(path)!r}, H())\n"
        + body
        + "\nprint(json.dumps(out))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    data["stderr"] = result.stderr
    return data


@pytest.fixture
def both(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], str]:
    path = _ui(tmp_path)
    module, _generated = _generate(path)
    text = module.read_text(encoding="utf-8")
    gen = run_generated(module, HANDLERS + 'ui = g["Ui_Main"]()\nui.setup_ui(None, H())\n' + PROBE)
    return gen, _run_load_ui(path, PROBE), text


def test_the_generated_tb_module_compiles_and_emits_native_widgets(
    both: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    _gen, _loaded, text = both
    compile(text, "tbx_ui.py", "exec")
    tree = ast.parse(text)
    created = {
        ast.unparse(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "_create"
        and node.args
    }
    assert {
        "ttkbootstrap.Meter",
        "ttkbootstrap.Floodgauge",
        "ttkbootstrap.DateEntry",
        "ttkbootstrap.Tableview",
        "ttkbootstrap.Checkbutton",
    } <= created
    assert "datetime.date(2024, 2, 29)" in text
    assert "2026, 2, 30" not in text and "2026-02-30" not in text  # left out, as the factory
    assert "'square-toggle'" not in text  # no colour token -> "round-toggle"/"danger-square-toggle"
    assert "'danger-square-toggle'" in text and "'round-toggle'" in text
    assert "pyguibud" not in "".join(
        line for line in text.splitlines() if line.startswith(("import", "from"))
    )


def test_the_generated_tb_widgets_behave_as_built_by_the_factories(
    both: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    gen, _loaded, _text = both
    assert gen["types"] == {
        "mtr": "Meter",
        "flg": "Floodgauge",
        "day": "Entry",
        "fixed": "Entry",
        "bad": "Entry",
        "tbl": "Treeview",
        "tgl": "Checkbutton",
        "tg2": "Checkbutton",
    }
    assert gen["meter"] == [12.5, 50.0, "semi", 150, 5, "{:.1f} kg", "Level", False, True]
    assert gen["flood"] == ["3", "10.0", "vertical", "90", "{} items", "Items"]
    assert gen["fixed"] == ["29/02/2024", "disabled", 20, 6, "disabled"]
    assert gen["day"] == ["2026-10-14", True]
    assert gen["table"] == [["Name", "Colour", "Amount"], 3, 4, "extended", True, True]
    assert gen["styles"] == ["danger.Square.Toggle", "Round.Toggle", "Enabled", 0]
    assert gen["link"] == [30.5, 7]
    assert gen["flood_var"] == 6.0
    assert gen["day_var"] == "2027-01-02"
    assert gen["toggles"] == [False, 1]
    assert gen["retranslated"] == ["Nivel", "Objets", "Activo", ["Nom", "", ""]]
    assert "1 column headings for 3 columns" in gen["stderr"]
    assert gen["calls"] == ["change", "change", "cmd", "select"]  # day var, tg2, tgl, tbl


def test_the_generated_tb_module_matches_load_ui(
    both: tuple[dict[str, Any], dict[str, Any], str],
) -> None:
    gen, loaded, _text = both
    gen.pop("stderr")
    assert "1 column headings for 3 columns" in loaded.pop("stderr")
    assert gen == loaded


# ------------------------------------------------------------------ third-party plugins
@dataclass
class _Dist:
    name: str


@dataclass
class _EP:
    name: str
    value: str
    dist: _Dist | None
    obj: object
    group: str = WIDGETS_GROUP

    def load(self) -> object:
        return self.obj


def _plugin_registry() -> Registry:
    label = next(s for s in core_widgets() if s.name == "Label")
    spec = WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(label.property("text"),),  # type: ignore[arg-type]
        factories={"ttkbootstrap": "zz_plugin:gauge"},
    )
    widgets = [
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud"), tb_widgets),
        _EP("zz", "zz_plugin:specs", _Dist("zz-plugin"), lambda: (spec,)),
    ]

    def source(group: str) -> Iterable[Any]:
        return widgets if group == WIDGETS_GROUP else _metadata_entry_points(group)

    return Registry(entry_points=source)


def test_a_third_party_plugin_widget_is_generated_as_its_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "_default", _plugin_registry())
    body = (
        "".join(
            f'<widget class="zz:Gauge" id="g{i}" fallback="Label" plugin="zz-plugin">'
            f'<prop name="text" translatable="true">G{i}</prop><cell row="{i}" column="0"/>'
            "</widget>"
            for i in range(2)
        )
        + '<widget class="tb:Meter" id="mtr" fallback="Progressbar"><cell row="2" column="0"/>'
        "</widget>"
    )
    module, generated = _generate(_ui(tmp_path, body, ""))
    codes = [w.code for w in generated.warnings]
    assert codes.count("codegen.extension_fallback") == 1  # once per class, never for tb:
    (warning,) = [w for w in generated.warnings if w.code == "codegen.extension_fallback"]
    assert warning.params == {"name": "zz:Gauge", "fallback": "Label"}
    text = module.read_text(encoding="utf-8")
    assert "zz_plugin" not in text
    out = run_generated(
        module,
        'ui = g["Ui_Main"]()\nui.setup_ui(None, None, strict=False)\n'
        'out["types"] = [type(ui.g0).__name__, type(ui.g1).__name__, type(ui.mtr).__name__]\n'
        'out["text"] = str(ui.g1.cget("text"))\nui.destroy()\n',
    )
    assert out["types"] == ["Label", "Label", "Meter"]
    assert out["text"] == "G1"


_TITLE = """
def outer(w, cls):
    while type(w).__name__ != cls:
        w = w.master
    return w
de = outer(ui.day, "DateEntry")
out["titles"] = sorted(str(v) for k, v in vars(de).items() if "title" in k.lower())
ui.destroy()
"""


def test_the_generated_date_entry_popup_title_matches_load_ui(tmp_path: Path) -> None:
    body = (
        '<widget class="tb:DateEntry" id="day" fallback="Entry"><cell row="0" column="0"/></widget>'
    )
    path = _ui(tmp_path, body, "")
    module, _generated = _generate(path)
    gen = run_generated(
        module, 'ui = g["Ui_Main"]()\nui.setup_ui(None, None, strict=False)\n' + _TITLE
    )
    loaded = _run_load_ui(path, _TITLE)
    assert "Select a date" in loaded["titles"]
    assert gen["titles"] == loaded["titles"]
