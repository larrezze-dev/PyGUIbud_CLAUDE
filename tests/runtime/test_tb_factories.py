"""Step 17b: the five ``tb:`` factories and the per-widget plugin guard of the Tk builder.

Spec ``docs/specs/plugins.md`` 4-5 and 11 ("Backends (Tk)"). Plugins are injected with a fake
entry-point source, so an installed plugin never changes these tests.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud.core.registry import WIDGETS_GROUP, Registry, _metadata_entry_points
from pyguibud.core.widgets import core_widgets, tb_widgets
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui

pytestmark = pytest.mark.gui

TB_BODY = """
<widget class="tb:Meter" id="mtr" bind="level" fallback="Progressbar" tb:bootstyle="success">
  <prop name="subtext" translatable="true">Level</prop><cell row="0" column="0"/></widget>
<widget class="tb:Floodgauge" id="flg" bind="level" fallback="Progressbar">
  <prop name="text" translatable="true">Flood</prop><cell row="1" column="0"/></widget>
<widget class="tb:DateEntry" id="ent_day" bind="day" fallback="Entry">
  <prop name="state">readonly</prop><event name="change" handler="on_change"/>
  <cell row="2" column="0"/></widget>
<widget class="tb:DateEntry" id="bad_day" fallback="Entry">
  <prop name="value">2026-02-30</prop><cell row="3" column="0"/></widget>
<widget class="tb:Tableview" id="tbl" fallback="Treeview">
  <prop name="columns" translatable="true">A;B</prop><prop name="selectmode">browse</prop>
  <cell row="4" column="0"/></widget>
<widget class="tb:ToggleButton" id="tgl" bind="on" fallback="Checkbutton" tb:bootstyle="info">
  <prop name="shape">square</prop><prop name="text" translatable="true">_Go</prop>
  <event name="command" handler="on_cmd"/><cell row="5" column="0"/></widget>
"""
TB_VARS = (
    '<var id="level" type="double" default="40"/><var id="day" type="string" default="2026-10-14"/>'
    '<var id="on" type="bool" default="true"/>'
)


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


def _registry(*specs: WidgetSpec) -> Registry:
    """Built-ins plus one fake plugin distribution; backends come from the installed metadata."""
    widgets = [
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud"), tb_widgets),
        _EP("zz", "zz_plugin:specs", _Dist("zz-plugin"), lambda: specs),
    ]

    def source(group: str) -> Iterable[Any]:
        return widgets if group == WIDGETS_GROUP else _metadata_entry_points(group)

    return Registry(entry_points=source)


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


class Calls(dict[str, Callable[[], None]]):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[str] = []
        for name in ("on_change", "on_cmd", "on_text"):
            self[name] = lambda name=name: self.calls.append(name)  # type: ignore[misc]


def test_each_tb_widget_builds_under_ttkbootstrap(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    window = f'<window id="w"><layout type="grid"/>{TB_BODY}</window>'
    path = write_ui(tmp_path / "tb.ui", window, variables=TB_VARS)
    handlers = Calls()
    with caplog.at_level(logging.WARNING):
        ui = load_ui(path, handlers, master=tk_root)
    loaded.append(ui)
    names = {k: type(getattr(ui, k)).__name__ for k in ("mtr", "flg", "ent_day", "tbl", "tgl")}
    assert names == {
        "mtr": "Meter",
        "flg": "Floodgauge",
        "ent_day": "Entry",  # ui.<id> is the inner widget that behaves as the fallback (D4)
        "tbl": "Treeview",
        "tgl": "Checkbutton",
    }
    assert type(ui.ent_day.master).__name__ == "DateEntry"
    assert "2026-02-30" in caplog.text and "failed to build" not in caplog.text
    assert not [
        d
        for d in registry_module.default_registry().diagnostics()
        if d.code.startswith("registry.factory")
    ]
    # variables: the meter follows its bound variable both ways; the date entry shows its own
    ui.vars.level.set(70)
    assert ui.mtr.amount_used_var.get() == 70 and ui.flg.variable is ui.vars.level
    ui.mtr.amount_used_var.set(12)
    assert ui.vars.level.get() == 12
    assert ui.ent_day.get() == "2026-10-14" and str(ui.ent_day.cget("state")) == "readonly"
    ui.vars.day.set("2026-01-01")
    assert handlers.calls == ["on_change"]
    # texts, styles and the Tableview headings
    assert ui.mtr.cget("subtext") == "Level" and ui.flg.cget("text") == "Flood"
    assert ui.tgl.cget("text") == "Go" and int(ui.tgl.cget("underline")) == 0
    assert ui.tgl.cget("style") == "info.Square.Toggle"
    assert [ui.tbl.heading(c)["text"] for c in ui.tbl["columns"]] == ["A", "B"]
    assert str(ui.tbl.cget("selectmode")) == "browse"
    ui.tgl.invoke()
    assert handlers.calls[-1] == "on_cmd" and ui.vars.on.get() is False


def test_a_wrong_heading_count_is_padded_and_logged(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    window = f'<window id="w"><layout type="grid"/>{TB_BODY}</window>'
    path = write_ui(tmp_path / "tb.ui", window, variables=TB_VARS)

    class Pad:
        def gettext(self, text: str) -> str:
            return "X" if text == "A;B" else text

        def pgettext(self, _context: str, text: str) -> str:
            return text

    ui = load_ui(path, Calls(), master=tk_root)
    loaded.append(ui)
    with caplog.at_level(logging.WARNING):
        ui.retranslate(translator=Pad())
    assert [ui.tbl.heading(c)["text"] for c in ui.tbl["columns"]] == ["X", ""]
    assert "1 column headings for 2 columns" in caplog.text


def test_the_tkinter_backend_shows_fallbacks_without_importing_tbwidgets(tmp_path: Path) -> None:
    window = f'<window id="w" kind="main"><layout type="grid"/>{TB_BODY}</window>'
    path = write_ui(tmp_path / "tb.ui", window, variables=TB_VARS)
    code = (
        "import sys, logging\n"
        "from pyguibud_runtime import load_ui\n"
        "class H:\n"
        "    def __getattr__(self, name): return lambda *a: None\n"
        f"ui = load_ui({str(path)!r}, H(), backend='tkinter')\n"
        "print(sorted({type(w).__name__ for w in ui.widgets.values()}))\n"
        "print('pyguibud.backends._tbwidgets' in sys.modules)\n"
        "ui.destroy()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=False
    )
    assert result.returncode == 0, result.stderr
    classes, imported = result.stdout.strip().splitlines()[-2:]
    assert classes == "['Checkbutton', 'Entry', 'Progressbar', 'Tk', 'Treeview']"
    assert imported == "False"
    for name in ("tb:Meter", "tb:DateEntry", "tb:Tableview", "tb:ToggleButton"):
        assert result.stderr.count(f"'{name}' is shown as its fallback") == 1, name


# ------------------------------------------------------------------ the guard (spec 4.2)
def _label_text() -> Any:
    return next(s for s in core_widgets() if s.name == "Label").property("text")


def _raising(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    import ttkbootstrap

    ttkbootstrap.Label(parent)  # a stray child, made before the failure
    raise RuntimeError("boom")


def _none(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    return None


def _wrong_master(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    import ttkbootstrap

    return ttkbootstrap.Label(parent.winfo_toplevel())


def _strays(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    import ttkbootstrap

    ttkbootstrap.Frame(parent)
    return ttkbootstrap.Label(parent)


def _exits(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    raise SystemExit(3)


def _good(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
    import ttkbootstrap

    frame = ttkbootstrap.Frame(parent)
    label: Any = ttkbootstrap.Label(frame)
    label.pack()
    return frame, label


@pytest.mark.parametrize(
    ("factory", "stage"),
    [
        (_raising, "create"),
        (_exits, "create"),
        (_none, "check"),
        (_wrong_master, "check"),
        (_strays, "check"),
        ("zz_plugin_missing_module:factory", "import"),
    ],
)
def test_a_failing_factory_falls_back_without_stray_widgets(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    factory: Any,
    stage: str,
) -> None:
    spec = WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(_label_text(),),
        factories={"ttkbootstrap": factory},
    )
    reg = _registry(spec)
    assert reg.diagnostics() == ()
    monkeypatch.setattr(registry_module, "_default", reg)
    gauges = "".join(
        f'<widget class="zz:Gauge" id="g{i}" fallback="Label">'
        f'<prop name="text" translatable="true">G{i}</prop><cell row="{i}" column="0"/></widget>'
        for i in range(2)
    )
    window = f'<window id="w"><layout type="grid"/>{gauges}</window>'
    path = write_ui(tmp_path / "g.ui", window)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = load_ui(path, object(), master=tk_root)
    loaded.append(ui)
    assert type(ui.g0).__name__ == "Label" and ui.g1.cget("text") == "G1"
    body = ui.g0.master
    assert {str(c) for c in body.winfo_children()} == {str(ui.g0), str(ui.g1)}
    top = ui.g0.winfo_toplevel()  # _wrong_master creates its label here
    assert [type(c).__name__ for c in top.winfo_children() if type(c).__name__ == "Label"] == []
    assert caplog.text.count("'zz:Gauge' failed to build") == 1
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [d.params["stage"] for d in failures] == [stage]


def test_a_working_plugin_factory_is_wired_as_its_fallback(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(_label_text(),),
        factories={"ttkbootstrap": _good},
    )
    monkeypatch.setattr(registry_module, "_default", _registry(spec))
    body = (
        '<widget class="zz:Gauge" id="g" fallback="Label"><prop name="text">Hi</prop>'
        '<cell row="0" column="0"/></widget>'
    )
    ui = load_ui(
        write_ui(tmp_path / "g.ui", f'<window id="w"><layout type="grid"/>{body}</window>'),
        object(),
        master=tk_root,
    )
    loaded.append(ui)
    assert type(ui.g).__name__ == "Label" and ui.g.cget("text") == "Hi"
    assert type(ui.g.master).__name__ == "Frame" and ui.g.master.winfo_manager() == "grid"


def test_a_command_the_plugin_widget_refuses_is_logged_once(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def label(parent: Any, props: dict[str, Any], variable: Any, bootstyle: Any) -> Any:
        import ttkbootstrap

        return ttkbootstrap.Label(parent)  # a Label has no ``command`` option

    button = next(s for s in core_widgets() if s.name == "Button")
    spec = WidgetSpec(
        name="zz:Knob",
        display_name="Knob",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Button",
        properties=(_label_text(),),
        events=("command",),
        factories={"ttkbootstrap": label},
    )
    assert "command" in button.events
    reg = _registry(spec)
    monkeypatch.setattr(registry_module, "_default", reg)
    body = "".join(
        f'<widget class="zz:Knob" id="k{i}" fallback="Button">'
        f'<event name="command" handler="on_cmd"/><cell row="{i}" column="0"/></widget>'
        for i in range(2)
    )
    path = write_ui(tmp_path / "k.ui", f'<window id="w"><layout type="grid"/>{body}</window>')
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = load_ui(path, Calls(), master=tk_root)
    loaded.append(ui)
    assert type(ui.k0).__name__ == "Label" and type(ui.k1).__name__ == "Label"
    assert caplog.text.count("The event 'command' of 'k0' is not supported by 'zz:Knob'.") == 1
    assert "of 'k1'" not in caplog.text  # once per class and event
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [d.params["stage"] for d in failures] == ["wire"]


def test_a_design_build_shows_the_failure_card_for_a_non_container(
    tmp_path: Path, tk_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tkinter import ttk

    from pyguibud.backends._tk import Embed
    from pyguibud.backends.ttkbootstrap import TtkbootstrapBackend
    from pyguibud_runtime._load import _prepare

    spec = WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(_label_text(),),
        factories={"ttkbootstrap": _raising},
    )
    monkeypatch.setattr(registry_module, "_default", _registry(spec))
    body = '<widget class="zz:Gauge" id="g" fallback="Label"><cell row="0" column="0"/></widget>'
    path = write_ui(tmp_path / "g.ui", f'<window id="w"><layout type="grid"/>{body}</window>')
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
    try:
        assert cards == [("g", "RuntimeError('boom')")]
        _node, outer, inner = next(n for n in nodes if getattr(n[0], "id", "") == "g")
        assert outer is inner and outer.cget("text") == "card"
        assert outer.winfo_manager() == "grid"
    finally:
        session.destroy()
        host.destroy()
