"""Step 17b (testing pass): more of the ``tb:`` factories and the Tk plugin guard.

Spec ``docs/specs/plugins.md`` 4, 5, 10 and 11 ("Backends (Tk)"). Complements
``test_tb_factories.py`` (not repeated here): every property of the five widgets takes effect,
variables in both directions, events on the inner widget, retranslation of the extra slots,
and guard cases the developer's tests do not reach.
"""

from __future__ import annotations

import datetime
import logging
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud.core.widgets import core_widgets
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import write_ui
from tests.runtime.test_tb_factories import _label_text, _raising, _registry

pytestmark = pytest.mark.gui


class Calls(Counter[str]):
    """Handlers that count their calls; any name is a handler."""

    def __getitem__(self, name: str) -> int:
        return super().get(name, 0)

    def handlers(self, *names: str) -> dict[str, Callable[[], None]]:
        return {name: (lambda name=name: self.update([name])) for name in names}  # type: ignore[misc]


class Translator:
    """A gettext-like translator from a mapping (unknown texts are returned unchanged)."""

    def __init__(self, table: dict[str, str]) -> None:
        self.table = table

    def gettext(self, text: str) -> str:
        return self.table.get(text, text)

    def pgettext(self, _context: str, text: str) -> str:
        return self.table.get(text, text)


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


def _load(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    body: str,
    handlers: object = None,
    variables: str = "",
) -> LoadedUi:
    window = f'<window id="w"><layout type="grid"/>{body}</window>'
    path = write_ui(tmp_path / "t.ui", window, variables=variables)
    ui = load_ui(path, handlers, strict=handlers is not None, master=tk_root)
    loaded.append(ui)
    return ui


def _outer(widget: Any, cls: str) -> Any:
    """The ttkbootstrap widget of class ``cls`` that holds ``widget`` (``ui.<id>`` is inner)."""
    while type(widget).__name__ != cls:
        widget = widget.master
    return widget


def _no_factory_failures() -> None:
    failures = [
        d
        for d in registry_module.default_registry().diagnostics()
        if d.code == "registry.factory_failed"
    ]
    assert failures == []


def _focus_and_return(ui: LoadedUi, widget: Any, calls: Calls) -> None:
    """focus_in, activate (<Return>) and focus_out reach the handlers wired on ``widget``."""
    ui.w.deiconify()
    widget.focus_force()
    widget.update()
    widget.event_generate("<FocusIn>", when="now")
    widget.event_generate("<Return>", when="now")
    widget.update()
    assert calls["h_act"] == 1 and calls["h_in"] >= 1
    before = calls["h_out"]
    widget.event_generate("<FocusOut>", when="now")
    assert calls["h_out"] == before + 1
    ui.w.withdraw()


# ------------------------------------------------------------------ Meter
def test_meter_properties_take_effect(tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]) -> None:
    body = """
    <widget class="tb:Meter" id="mtr" fallback="Progressbar">
      <prop name="amount_format">{:.1f} kg</prop><prop name="interactive">true</prop>
      <prop name="maximum">50</prop><prop name="meter_size">150</prop>
      <prop name="meter_thickness">5</prop><prop name="meter_type">semi</prop>
      <prop name="show_text">false</prop><prop name="subtext" translatable="true">Load</prop>
      <prop name="value">33.5</prop><cell row="0" column="0"/></widget>
    """
    ui = _load(tmp_path, tk_root, loaded, body)
    m = ui.mtr
    assert type(m).__name__ == "Meter"
    got = {
        k: m.cget(k)
        for k in (
            "amount_used",
            "amount_total",
            "meter_type",
            "meter_size",
            "meter_thickness",
            "amount_format",
            "subtext",
            "show_text",
            "interactive",
        )
    }
    assert got == {
        "amount_used": 33.5,
        "amount_total": 50.0,
        "meter_type": "semi",
        "meter_size": 150,
        "meter_thickness": 5,
        "amount_format": "{:.1f} kg",
        "subtext": "Load",
        "show_text": False,
        "interactive": True,
    }
    _no_factory_failures()


def test_meter_defaults_follow_the_spec(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="tb:Meter" id="mtr" fallback="Progressbar">'
        '<cell row="0" column="0"/></widget>'
    )
    m = _load(tmp_path, tk_root, loaded, body).mtr
    assert (m.cget("meter_type"), m.cget("meter_size"), m.cget("meter_thickness")) == (
        "full",
        200,
        10,
    )
    assert (m.cget("amount_used"), m.cget("amount_total")) == (0.0, 100.0)
    assert m.cget("show_text") is True and m.cget("interactive") is False


@pytest.mark.parametrize(
    ("kind", "default", "written"), [("double", "12.5", 44.7), ("int", "12", 44)]
)
def test_meter_amount_follows_the_bound_variable_both_ways(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    kind: str,
    default: str,
    written: float,
) -> None:
    body = (
        '<widget class="tb:Meter" id="mtr" bind="lv" fallback="Progressbar">'
        '<prop name="value">90</prop><cell row="0" column="0"/></widget>'
    )
    ui = _load(
        tmp_path,
        tk_root,
        loaded,
        body,
        variables=f'<var id="lv" type="{kind}" default="{default}"/>',
    )
    own = ui.mtr.amount_used_var
    assert own.get() == float(default)  # the bound value wins over the "value" property
    ui.vars.lv.set(written)
    assert own.get() == written
    own.set(7)
    assert ui.vars.lv.get() == 7


def test_meter_subtext_is_retranslated(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="tb:Meter" id="mtr" fallback="Progressbar">'
        '<prop name="subtext" translatable="true">Load</prop><cell row="0" column="0"/></widget>'
    )
    ui = _load(tmp_path, tk_root, loaded, body)
    ui.retranslate(translator=Translator({"Load": "Carga"}))
    assert ui.mtr.cget("subtext") == "Carga"


# ------------------------------------------------------------------ Floodgauge
def test_floodgauge_properties_take_effect_and_retranslate(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:Floodgauge" id="flg" fallback="Progressbar" tb:bootstyle="danger">
      <prop name="length">120</prop><prop name="mask">{}%</prop><prop name="maximum">60</prop>
      <prop name="mode">determinate</prop><prop name="orient">vertical</prop>
      <prop name="text" translatable="true">Flood</prop><prop name="value">30</prop>
      <cell row="0" column="0"/></widget>
    """
    ui = _load(tmp_path, tk_root, loaded, body)
    f = ui.flg
    assert type(f).__name__ == "Floodgauge"
    got = {k: f.cget(k) for k in ("value", "maximum", "mode", "orient", "length", "mask")}
    assert got == {
        "value": 30.0,
        "maximum": 60,
        "mode": "determinate",
        "orient": "vertical",
        "length": 120,
        "mask": "{}%",
    }
    assert f.cget("text") == "Flood"
    ui.retranslate(translator=Translator({"Flood": "Crue"}))
    assert f.cget("text") == "Crue"
    _no_factory_failures()


@pytest.mark.parametrize("kind", ["double", "int"])
def test_floodgauge_uses_the_bound_variable(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], kind: str
) -> None:
    body = (
        '<widget class="tb:Floodgauge" id="flg" bind="lv" fallback="Progressbar">'
        '<cell row="0" column="0"/></widget>'
    )
    ui = _load(
        tmp_path, tk_root, loaded, body, variables=f'<var id="lv" type="{kind}" default="25"/>'
    )
    assert ui.flg.variable is ui.vars.lv
    assert float(ui.flg.cget("value")) == 25
    ui.vars.lv.set(40)
    assert float(ui.flg.cget("value")) == 40


# ------------------------------------------------------------------ DateEntry
def test_date_entry_properties_take_effect(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:DateEntry" id="day" fallback="Entry">
      <prop name="date_format">%d/%m/%Y</prop><prop name="first_weekday">6</prop>
      <prop name="state">disabled</prop><prop name="value">2026-10-14</prop>
      <prop name="width">25</prop><cell row="0" column="0"/></widget>
    """
    ui = _load(tmp_path, tk_root, loaded, body)
    entry = ui.day
    outer = _outer(entry, "DateEntry")
    assert type(entry).__name__ == "Entry" and entry is outer.entry
    assert entry.get() == "14/10/2026"  # the ISO value shown in date_format
    assert outer.get_date().date() == datetime.date(2026, 10, 14)
    assert int(entry.cget("width")) == 25
    assert outer._firstweekday == 6
    assert str(entry.cget("state")) == "disabled"
    assert str(outer.button.cget("state")) == "disabled"  # the popup button follows the state
    _no_factory_failures()


def test_date_entry_without_value_shows_a_date(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="tb:DateEntry" id="day" fallback="Entry"><cell row="0" column="0"/></widget>'
    )
    ui = _load(tmp_path, tk_root, loaded, body)
    assert datetime.date.fromisoformat(ui.day.get())  # ttkbootstrap's default: today, ISO


def test_date_entry_text_variable_sits_on_the_inner_entry_both_ways(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="tb:DateEntry" id="day" bind="d" fallback="Entry">'
        '<cell row="0" column="0"/></widget>'
    )
    ui = _load(
        tmp_path,
        tk_root,
        loaded,
        body,
        variables='<var id="d" type="string" default="2026-10-14"/>',
    )
    assert str(ui.day.cget("textvariable")) == str(ui.vars.d)
    ui.vars.d.set("2027-01-02")
    assert ui.day.get() == "2027-01-02"
    ui.day.delete(0, "end")
    ui.day.insert(0, "2028-03-04")
    assert ui.vars.d.get() == "2028-03-04"


def test_date_entry_events_are_wired_on_the_inner_entry(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:DateEntry" id="day" fallback="Entry">
      <event name="change" handler="h_change"/><event name="activate" handler="h_act"/>
      <event name="focus_in" handler="h_in"/><event name="focus_out" handler="h_out"/>
      <cell row="0" column="0"/></widget>
    """
    calls = Calls()
    ui = _load(
        tmp_path, tk_root, loaded, body, calls.handlers("h_change", "h_act", "h_in", "h_out")
    )
    assert not calls  # building fires nothing
    entry = ui.day
    entry.insert("end", "x")  # change: a private StringVar traced on the inner entry
    assert calls["h_change"] == 1
    _focus_and_return(ui, entry, calls)


def test_date_entry_popup_title_is_translated(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="tb:DateEntry" id="day" fallback="Entry"><cell row="0" column="0"/></widget>'
    )
    outer = _outer(_load(tmp_path, tk_root, loaded, body).day, "DateEntry")
    titles = [value for key, value in vars(outer).items() if "title" in key.lower()]
    assert "Select a date" in titles


# ------------------------------------------------------------------ Tableview
def test_tableview_properties_take_effect(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:Tableview" id="tbl" fallback="Treeview">
      <prop name="columns" translatable="true">Name;Age;Town</prop><prop name="height">7</prop>
      <prop name="pagesize">3</prop><prop name="paginated">true</prop>
      <prop name="searchable">true</prop><prop name="selectmode">extended</prop>
      <cell row="0" column="0"/></widget>
    """
    ui = _load(tmp_path, tk_root, loaded, body)
    view = ui.tbl
    table = _outer(view, "Tableview")
    assert type(view).__name__ == "Treeview" and view is table.view
    assert [c.headertext for c in table.tablecolumns] == ["Name", "Age", "Town"]
    assert table.pagesize == 3 and int(view.cget("height")) == 7
    assert str(view.cget("selectmode")) == "extended"
    assert table._paginated is True and table._searchable is True  # no public getter
    assert table.tablerows == []  # rows come from handler code
    _no_factory_failures()


@pytest.mark.parametrize(
    ("translated", "expected", "logged"),
    [
        ("Nom;Âge;Ville", ["Nom", "Âge", "Ville"], None),
        ("Nom", ["Nom", "", ""], "1 column headings for 3 columns"),
        ("A;B;C;D;E", ["A", "B", "C"], "5 column headings for 3 columns"),
    ],
)
def test_tableview_headings_are_retranslated_padded_or_truncated(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    translated: str,
    expected: list[str],
    logged: str | None,
) -> None:
    body = (
        '<widget class="tb:Tableview" id="tbl" fallback="Treeview">'
        '<prop name="columns" translatable="true">Name;Age;Town</prop>'
        '<cell row="0" column="0"/></widget>'
    )
    ui = _load(tmp_path, tk_root, loaded, body)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        ui.retranslate(translator=Translator({"Name;Age;Town": translated}))
    assert [ui.tbl.heading(c)["text"] for c in ui.tbl["columns"]] == expected
    if logged is None:
        assert "column headings" not in caplog.text
    else:
        assert logged in caplog.text


def test_tableview_select_and_activate_are_wired_on_the_inner_view(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:Tableview" id="tbl" fallback="Treeview">
      <prop name="columns">A;B</prop>
      <event name="select" handler="h_sel"/><event name="activate" handler="h_act"/>
      <event name="focus_in" handler="h_in"/><event name="focus_out" handler="h_out"/>
      <cell row="0" column="0"/></widget>
    """
    calls = Calls()
    ui = _load(tmp_path, tk_root, loaded, body, calls.handlers("h_sel", "h_act", "h_in", "h_out"))
    table = _outer(ui.tbl, "Tableview")
    row = table.insert_row("end", ("a", 1))
    table.load_table_data()
    ui.w.deiconify()
    ui.w.update()
    ui.tbl.selection_set(row.iid)  # Tk itself sends <<TreeviewSelect>>
    ui.tbl.update()
    assert calls["h_sel"] == 1
    _focus_and_return(ui, ui.tbl, calls)


# ------------------------------------------------------------------ ToggleButton
@pytest.mark.parametrize(
    ("bootstyle", "shape", "style"),
    [
        (None, None, "Round.Toggle"),  # no colour, the default shape
        (None, "square", "Square.Toggle"),
        ("success", "round", "success.Round.Toggle"),
        ("outline-warning", "square", "warning.Square.Toggle"),  # the colour token, wherever
        ("danger info", None, "danger.Round.Toggle"),  # the first colour wins
        ("outline", "square", "Square.Toggle"),  # a type token alone: no colour
    ],
)
def test_toggle_button_style_from_shape_and_colour(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    bootstyle: str | None,
    shape: str | None,
    style: str,
) -> None:
    attr = f' tb:bootstyle="{bootstyle}"' if bootstyle else ""
    prop = f'<prop name="shape">{shape}</prop>' if shape else ""
    body = (
        f'<widget class="tb:ToggleButton" id="tgl" fallback="Checkbutton"{attr}>{prop}'
        '<cell row="0" column="0"/></widget>'
    )
    ui = _load(tmp_path, tk_root, loaded, body)
    assert type(ui.tgl).__name__ == "Checkbutton"
    assert ui.tgl.cget("style") == style
    _no_factory_failures()


@pytest.mark.parametrize(
    ("kind", "default", "on", "off"), [("bool", "true", True, False), ("int", "1", 1, 0)]
)
def test_toggle_button_bound_variable_both_ways(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    kind: str,
    default: str,
    on: object,
    off: object,
) -> None:
    body = (
        '<widget class="tb:ToggleButton" id="tgl" bind="v" fallback="Checkbutton">'
        '<cell row="0" column="0"/></widget>'
    )
    ui = _load(
        tmp_path,
        tk_root,
        loaded,
        body,
        variables=f'<var id="v" type="{kind}" default="{default}"/>',
    )
    assert ui.tgl.instate(["selected"])
    ui.tgl.invoke()
    assert ui.vars.v.get() == off and not ui.tgl.instate(["selected"])
    ui.vars.v.set(on)
    assert ui.tgl.instate(["selected"])


def test_toggle_button_events_text_state_and_retranslation(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = """
    <widget class="tb:ToggleButton" id="tgl" fallback="Checkbutton">
      <prop name="state">disabled</prop><prop name="text" translatable="true">_Wifi</prop>
      <event name="command" handler="h_cmd"/><event name="change" handler="h_change"/>
      <event name="focus_in" handler="h_in"/><event name="focus_out" handler="h_out"/>
      <cell row="0" column="0"/></widget>
    <widget class="tb:ToggleButton" id="tg2" fallback="Checkbutton">
      <event name="command" handler="h_cmd2"/><event name="change" handler="h_change2"/>
      <cell row="1" column="0"/></widget>
    """
    calls = Calls()
    names = ("h_cmd", "h_change", "h_in", "h_out", "h_cmd2", "h_change2")
    ui = _load(tmp_path, tk_root, loaded, body, calls.handlers(*names))
    assert ui.tgl.cget("text") == "Wifi" and int(ui.tgl.cget("underline")) == 0
    assert str(ui.tgl.cget("state")) == "disabled"
    ui.tg2.invoke()
    assert (calls["h_cmd2"], calls["h_change2"]) == (1, 1)
    ui.tgl.event_generate("<FocusIn>", when="now")
    ui.tgl.event_generate("<FocusOut>", when="now")
    assert (calls["h_in"], calls["h_out"]) == (1, 1)
    ui.retranslate(translator=Translator({"_Wifi": "_Rede"}))
    assert ui.tgl.cget("text") == "Rede" and int(ui.tgl.cget("underline")) == 0


# ------------------------------------------------------------------ the guard
def _spec(factory: Any, name: str = "zz:Gauge", **kw: Any) -> WidgetSpec:
    fields: dict[str, Any] = {
        "display_name": "Gauge",
        "category": "Zz",
        "api_version": WIDGET_API_VERSION,
        "fallback": "Label",
        "properties": (_label_text(),),
    }
    fields.update(kw)
    return WidgetSpec(name=name, factories={"ttkbootstrap": factory}, **fields)


def _gauges(count: int, cls: str = "zz:Gauge", fallback: str = "Label") -> str:
    return "".join(
        f'<widget class="{cls}" id="g{i}" fallback="{fallback}">'
        f'<prop name="text">G{i}</prop><cell row="{i}" column="0"/></widget>'
        for i in range(count)
    )


def test_many_failing_widgets_give_one_log_one_diagnostic_and_one_revision_bump(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reg = _registry(_spec(_raising))
    monkeypatch.setattr(registry_module, "_default", reg)
    assert reg.diagnostics() == ()  # loads the registry
    revision = reg.revision
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, tk_root, loaded, _gauges(100))
    assert all(type(getattr(ui, f"g{i}")).__name__ == "Label" for i in range(100))
    assert ui.g99.cget("text") == "G99"
    body = ui.g0.master
    assert len(body.winfo_children()) == 100  # no stray widget from any of the 100 calls
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [(d.params["name"], d.params["backend"], d.params["stage"]) for d in failures] == [
        ("zz:Gauge", "ttkbootstrap", "create")
    ]
    assert reg.revision == revision + 1


def test_two_failing_classes_are_reported_separately(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def none(*_args: object) -> None:
        return None

    reg = _registry(_spec(_raising), _spec(none, "zz:Dial"))
    monkeypatch.setattr(registry_module, "_default", reg)
    assert reg.diagnostics() == ()
    revision = reg.revision
    body = _gauges(3) + "".join(
        f'<widget class="zz:Dial" id="d{i}" fallback="Label"><cell row="{i}" column="1"/></widget>'
        for i in range(3)
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        _load(tmp_path, tk_root, loaded, body)
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    assert caplog.text.count("'zz:Dial' failed to build") == 1
    stages = sorted(
        (d.params["name"], d.params["stage"])
        for d in reg.diagnostics()
        if d.code == "registry.factory_failed"
    )
    assert stages == [("zz:Dial", "check"), ("zz:Gauge", "create")]
    assert reg.revision == revision + 2


def test_a_failing_text_slot_inside_the_guard_falls_back(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A widget without a ``text`` option fails while its text is set: still the guard."""

    def canvas(parent: Any, *_args: object) -> Any:
        import tkinter

        return tkinter.Canvas(parent)

    reg = _registry(_spec(canvas))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, tk_root, loaded, _gauges(2))
    assert type(ui.g0).__name__ == "Label" and ui.g1.cget("text") == "G1"
    assert len(ui.g0.master.winfo_children()) == 2
    stages = [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert stages == ["check"]


def test_an_inner_widget_outside_outer_is_rejected_and_destroyed(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    def elsewhere(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        outer = ttkbootstrap.Frame(parent)
        inner = ttkbootstrap.Label(parent.winfo_toplevel())  # not a descendant of outer
        return outer, inner

    reg = _registry(_spec(elsewhere))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _load(tmp_path, tk_root, loaded, _gauges(1))
    assert type(ui.g0).__name__ == "Label"
    stages = [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert stages == ["check"]
    top = ui.g0.winfo_toplevel()
    assert [type(c).__name__ for c in top.winfo_children()] == ["Frame"]  # the body only


@pytest.mark.parametrize("pick", ["parent", "toplevel", "root"])
def test_an_inner_widget_that_is_an_ancestor_is_rejected_but_kept(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    monkeypatch: pytest.MonkeyPatch,
    pick: str,
) -> None:
    """The sweep never destroys the parent, the window or the root a bad factory names."""

    def ancestor(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        chosen = {"parent": parent, "toplevel": parent.winfo_toplevel(), "root": tk_root}[pick]
        return ttkbootstrap.Frame(parent), chosen

    reg = _registry(_spec(ancestor))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _load(tmp_path, tk_root, loaded, _gauges(2))
    assert type(ui.g0).__name__ == "Label" and ui.g1.cget("text") == "G1"
    assert ui.g0.winfo_exists() and tk_root.winfo_exists()
    assert [type(c).__name__ for c in ui.g0.master.winfo_children()] == ["Label", "Label"]


def test_a_factory_that_destroys_its_parent_is_caught_at_check(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 11 (QA): "a factory that destroys its parent (caught at check)"."""

    def vandal(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        widget = ttkbootstrap.Label(parent)
        parent.destroy()
        return widget

    reg = _registry(_spec(vandal))
    monkeypatch.setattr(registry_module, "_default", reg)
    with pytest.raises(UiError) as caught:  # no fallback fits a destroyed parent: a clean refusal
        _load(tmp_path, tk_root, loaded, _gauges(1))
    assert caught.value.code == "runtime.build_failed"
    stages = [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert stages == ["check"]


def test_a_factory_rejecting_the_bootstyle_is_retried_without_it(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[object] = []

    def picky(parent: Any, _props: object, _var: object, bootstyle: object) -> Any:
        import ttkbootstrap

        seen.append(bootstyle)
        if bootstyle is not None:
            raise TypeError("no bootstyle here")
        return ttkbootstrap.Label(parent)

    reg = _registry(_spec(picky))
    monkeypatch.setattr(registry_module, "_default", reg)
    body = (
        '<widget class="zz:Gauge" id="g" fallback="Label" tb:bootstyle="info">'
        '<prop name="text">Hi</prop><cell row="0" column="0"/></widget>'
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, tk_root, loaded, body)
    assert seen == ["info", None]
    assert ui.g.cget("text") == "Hi" and "failed to build" not in caplog.text
    assert "'info'" in caplog.text  # the ignored-style note
    assert [d for d in reg.diagnostics() if d.code == "registry.factory_failed"] == []


def test_the_factory_gets_converted_props_variable_and_bootstyle(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spec 4.1: fresh converted props, translated texts, the bound variable, the bootstyle."""
    got: list[tuple[dict[str, Any], Any, Any]] = []

    def spy(parent: Any, props: dict[str, Any], var: Any, bootstyle: Any) -> Any:
        import ttkbootstrap

        got.append((dict(props), var, bootstyle))
        props.clear()  # the factory may consume it
        return ttkbootstrap.Label(parent)

    progress = next(s for s in core_widgets() if s.name == "Progressbar")
    spec = _spec(
        spy,
        fallback="Progressbar",
        properties=(*progress.properties, _label_text()),
        bind_types=("double",),
    )
    monkeypatch.setattr(registry_module, "_default", _registry(spec))
    body = (
        '<widget class="zz:Gauge" id="g" bind="lv" fallback="Progressbar" tb:bootstyle="success">'
        '<prop name="maximum">50</prop><prop name="text" translatable="true">Hi</prop>'
        '<cell row="0" column="0"/></widget>'
    )
    ui = load_ui(
        write_ui(
            tmp_path / "t.ui",
            f'<window id="w"><layout type="grid"/>{body}</window>',
            variables='<var id="lv" type="double" default="5"/>',
        ),
        None,
        strict=False,
        master=tk_root,
        translator=Translator({"Hi": "Olá"}),
    )
    loaded.append(ui)
    (props, var, bootstyle), *_rest = got
    assert props["maximum"] == 50.0 and isinstance(props["maximum"], float)
    assert props["text"] == "Olá"
    assert var is ui.vars.lv and bootstyle == "success"


def test_keyboard_interrupt_in_a_factory_propagates(tmp_path: Path) -> None:
    """D7: KeyboardInterrupt is not isolated (run in a child, so pytest is not interrupted)."""
    window = (
        '<window id="w" kind="main"><layout type="grid"/>'
        '<widget class="zz:Gauge" id="g" fallback="Label"><cell row="0" column="0"/></widget>'
        "</window>"
    )
    path = write_ui(tmp_path / "k.ui", window)
    code = f"""
import sys
sys.path.insert(0, {str(Path(__file__).resolve().parents[2])!r})
from pyguibud.core import registry as rm
from tests.runtime.test_tb_factories_extra import _spec
from tests.runtime.test_tb_factories import _registry
from pyguibud_runtime import load_ui
def interrupt(*_args):
    raise KeyboardInterrupt
reg = _registry(_spec(interrupt))
rm._default = reg
try:
    load_ui({str(path)!r}, None, strict=False)
except KeyboardInterrupt:
    print("propagated", [d.code for d in reg.diagnostics()])
"""
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "propagated []"


# ------------------------------------------------------------------ design build (Embed)
def _embedded(
    tmp_path: Path, tk_root: Any, body: str
) -> tuple[Any, Any, list[tuple[str, str]], list[tuple[Any, Any, Any]]]:
    from tkinter import ttk

    from pyguibud.backends._tk import Embed
    from pyguibud.backends.ttkbootstrap import TtkbootstrapBackend
    from pyguibud_runtime._load import _prepare

    path = write_ui(tmp_path / "e.ui", f'<window id="w"><layout type="grid"/>{body}</window>')
    host = ttk.Frame(tk_root)
    nodes: list[tuple[Any, Any, Any]] = []
    cards: list[tuple[str, str]] = []

    def failed(node: Any, parent: Any, reason: str) -> Any:
        cards.append((node.id, reason))
        return ttk.Label(parent, text="card")

    embed = Embed(
        host=host,
        on_node=lambda node, outer, inner: nodes.append((node, outer, inner)),
        on_title=lambda _window, _text: None,
        placeholder=lambda _node, parent: ttk.Frame(parent),
        failed=failed,
    )
    _ui, plan = _prepare(path, None, strict=False, master=tk_root)
    session = TtkbootstrapBackend().build_embedded(plan, embed)
    return session, host, cards, nodes


_BOX = (
    '<widget class="zz:Box" id="box" fallback="Frame"><layout type="grid"/>'
    '<widget class="Label" id="kid"><prop name="text">kid</prop><cell row="0" column="0"/>'
    '</widget><cell row="0" column="0"/></widget>'
)


def _box_spec(factory: Any) -> WidgetSpec:
    frame = next(s for s in core_widgets() if s.name == "Frame")
    return WidgetSpec(
        name="zz:Box",
        display_name="Box",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Frame",
        children="layout",
        properties=frame.properties,
        factories={"ttkbootstrap": factory},
    )


def _check_container_fallback(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch, factory: Any
) -> None:
    monkeypatch.setattr(registry_module, "_default", _registry(_box_spec(factory)))
    session, host, cards, nodes = _embedded(tmp_path, tk_root, _BOX)
    try:
        assert cards == []  # a container shows its fallback (D6), never the card
        reported = {getattr(n, "id", None): (outer, inner) for n, outer, inner in nodes}
        assert "kid" in reported  # its children stay editable
        box = reported["box"][1]
        assert type(box).__name__ == "Frame"
        assert reported["kid"][0].master is box
    finally:
        session.destroy()
        host.destroy()


def test_a_design_build_shows_the_fallback_for_a_container_failing_at_create(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _check_container_fallback(tmp_path, tk_root, monkeypatch, _raising)


def test_a_design_build_shows_the_fallback_for_a_container_failing_at_import(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _check_container_fallback(tmp_path, tk_root, monkeypatch, "zz_missing_module:factory")


def test_a_design_build_with_a_factory_destroying_its_parent_fails_cleanly(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """17b risk 4: reported first, then the build's own error path (the canvas shows its card)."""
    import tkinter

    def vandal(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        widget = ttkbootstrap.Label(parent)
        parent.destroy()
        return widget

    reg = _registry(_spec(vandal))
    monkeypatch.setattr(registry_module, "_default", reg)
    before = set(tk_root.winfo_children())
    with pytest.raises(tkinter.TclError, match="bad window path"):  # the card's dead parent
        _embedded(tmp_path, tk_root, _gauges(1))
    stages = [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert stages == ["check"]
    hosts = [c for c in tk_root.winfo_children() if c not in before]
    assert [h.winfo_children() for h in hosts] == [[]]  # build_embedded removed the window
    hosts[0].destroy()


def test_a_design_build_reports_the_card_once_per_failing_node(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(registry_module, "_default", _registry(_spec("zz_missing_module:f")))
    session, host, cards, nodes = _embedded(tmp_path, tk_root, _gauges(3))
    try:
        assert [card[0] for card in cards] == ["g0", "g1", "g2"]
        assert all(reason == "import" for _id, reason in cards)
        for node_id in ("g0", "g1", "g2"):
            (outer, inner), *more = [(o, i) for n, o, i in nodes if getattr(n, "id", "") == node_id]
            assert more == [] and outer is inner and outer.cget("text") == "card"
            assert outer.winfo_manager() == "grid"
    finally:
        session.destroy()
        host.destroy()


def test_a_design_build_of_the_tb_widgets_reports_outer_and_inner(
    tmp_path: Path, tk_root: Any
) -> None:
    body = (
        '<widget class="tb:DateEntry" id="day" fallback="Entry"><cell row="0" column="0"/></widget>'
        '<widget class="tb:Tableview" id="tbl" fallback="Treeview"><prop name="columns">A</prop>'
        '<cell row="1" column="0"/></widget>'
    )
    session, host, cards, nodes = _embedded(tmp_path, tk_root, body)
    try:
        assert cards == []
        got = {
            n.id: (type(o).__name__, type(i).__name__)
            for n, o, i in nodes
            if hasattr(n, "class_name")
        }
        assert got == {"day": ("DateEntry", "Entry"), "tbl": ("Tableview", "Treeview")}
    finally:
        session.destroy()
        host.destroy()


# ------------------------------------------------------------------ Tableview rows (open issue)
# Characterisation, not a contract: ``ui.tbl`` is the inner ttk.Treeview (D4 "behaves as its
# fallback"), so handler code that calls ``ui.tbl.insert(...)`` writes rows the Tableview does
# not know about (``tablerows`` stays empty). ttkbootstrap's sort, search and pagination work on
# ``tablerows`` only, so those rows are never sorted, filtered or paged, and never removed.
_TABLE = """
<widget class="tb:Tableview" id="tbl" fallback="Treeview">
  <prop name="columns">Name;Age</prop><prop name="pagesize">2</prop>
  <prop name="paginated">true</prop><prop name="searchable">true</prop>
  <cell row="0" column="0"/></widget>
"""
_ROWS = [("c", 3), ("a", 1), ("b", 2), ("d", 4), ("e", 5)]


def _table(tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]) -> tuple[LoadedUi, Any]:
    ui = _load(tmp_path, tk_root, loaded, _TABLE)
    ui.w.deiconify()
    ui.w.update()
    return ui, _outer(ui.tbl, "Tableview")


def _shown(view: Any) -> list[str]:
    return [str(view.item(iid)["values"][0]) for iid in view.get_children()]


@pytest.mark.parametrize("operation", ["sort", "header_click", "search", "next_page", "reset"])
def test_rows_inserted_on_the_inner_treeview_bypass_the_tableview(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], operation: str
) -> None:
    ui, table = _table(tmp_path, tk_root, loaded)
    for row in _ROWS:
        ui.tbl.insert("", "end", values=row)  # what handler code can reach through ui.tbl
    assert _shown(ui.tbl) == ["c", "a", "b", "d", "e"]  # displayed, as on a Treeview
    assert table.tablerows == []  # unknown to the Tableview
    if operation == "sort":
        table.sort_column_data(cid="0")
    elif operation == "header_click":
        ui.tbl.update()
        x = ui.tbl.bbox(ui.tbl.get_children()[0], "#1")[0] + 5  # inside the first column
        ui.tbl.event_generate("<Button-1>", x=x, y=5, when="now")  # on the heading row
        ui.tbl.update()
    elif operation == "search":
        table.search_table_data("a")
    elif operation == "next_page":
        table.goto_next_page()
    else:
        table.reset_table()
    # neither sorted, nor filtered, nor paged (pagesize 2), nor removed
    assert _shown(ui.tbl) == ["c", "a", "b", "d", "e"]
    ui.w.withdraw()


def test_rows_inserted_through_the_tableview_api_are_sorted_and_paged(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    """The working alternative for handler code: the outer Tableview's own row API."""
    ui, table = _table(tmp_path, tk_root, loaded)
    for row in _ROWS:
        table.insert_row("end", row)
    table.load_table_data()
    assert len(table.tablerows) == 5 and len(_shown(ui.tbl)) == 2  # one page of 2
    table.sort_column_data(cid="0", sort=0)  # ascending
    assert _shown(ui.tbl) == ["a", "b"]
    table.goto_next_page()
    assert _shown(ui.tbl) == ["c", "d"]
    table.search_table_data("e")
    assert _shown(ui.tbl) == ["e"]
    ui.w.withdraw()


# ------------------------------------------------------------------ the tkinter backend
def test_the_tkinter_backend_notes_each_tb_class_once_and_reports_no_failure(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    from tests.runtime.test_tb_factories import TB_BODY, TB_VARS

    twice = TB_BODY + TB_BODY.replace('id="', 'id="x_').replace('row="', 'row="1')
    window = f'<window id="w"><layout type="grid"/>{twice}</window>'
    path = write_ui(tmp_path / "tk.ui", window, variables=TB_VARS)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = load_ui(path, None, strict=False, backend="tkinter", master=tk_root)
    loaded.append(ui)
    assert type(ui.flg).__name__ == type(ui.x_flg).__name__ == "Progressbar"
    assert type(ui.ent_day).__name__ == "Entry" and type(ui.x_tbl).__name__ == "Treeview"
    for name in ("tb:Meter", "tb:Floodgauge", "tb:DateEntry", "tb:Tableview", "tb:ToggleButton"):
        assert caplog.text.count(f"'{name}' is shown as its fallback") == 1, name
    assert "failed to build" not in caplog.text
    _no_factory_failures()


def test_a_working_container_factory_holds_the_children(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    def box(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        outer = ttkbootstrap.Labelframe(parent, text="box")
        inner: Any = ttkbootstrap.Frame(outer)
        inner.pack()
        return outer, inner

    monkeypatch.setattr(registry_module, "_default", _registry(_box_spec(box)))
    ui = _load(tmp_path, tk_root, loaded, _BOX)
    assert type(ui.box).__name__ == "Frame" and type(ui.box.master).__name__ == "Labelframe"
    assert ui.kid.master is ui.box and ui.kid.winfo_manager() == "grid"


def test_a_type_error_without_a_bootstyle_is_not_retried(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []

    def strict(_parent: Any, _props: object, _var: object, bootstyle: object) -> Any:
        seen.append(bootstyle)
        raise TypeError("unexpected keyword")

    reg = _registry(_spec(strict))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _load(tmp_path, tk_root, loaded, _gauges(1))
    assert seen == [None] and type(ui.g0).__name__ == "Label"
    stages = [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert stages == ["create"]
