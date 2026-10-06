"""Building real ttkbootstrap widgets into the one session root (``master=tk_root``)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.backends import _tk
from pyguibud.backends._tk import event_wiring
from pyguibud.core.keys import tk_key_sequences, tk_shortcut
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.gui

HELLO = EXAMPLES / "hello.ui"
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
PPM = b"P6\n1 1\n255\n\x00\x00\x00"


class Recorder(dict[str, Callable[[], None]]):
    """A handlers mapping that counts the calls of each name."""

    def __init__(self, *names: str) -> None:
        super().__init__()
        self.calls: list[str] = []
        for name in names:
            self[name] = lambda name=name: self.calls.append(name)  # type: ignore[misc]


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test; destroys them and checks nothing is left over."""
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


def _hello(tk_root: Any, loaded: list[LoadedUi], lang: str = "de_DE") -> tuple[LoadedUi, Recorder]:
    handlers = Recorder("on_greet", "on_quit")
    ui = load_ui(HELLO, handlers, master=tk_root, lang=lang)
    loaded.append(ui)
    return ui, handlers


def _aqua(ui: LoadedUi) -> bool:
    return bool(ui.main.tk.call("tk", "windowingsystem") == "aqua")


def _menubar(ui: LoadedUi) -> Any:
    return ui.main.nametowidget(ui.main.cget("menu"))


def test_hello_in_german(tk_root: Any, loaded: list[LoadedUi]) -> None:
    ui, handlers = _hello(tk_root, loaded)
    assert ui.main.title() == "Hallo PyGUIbud"
    assert ui.windows == {"main": ui.main}
    assert (_menubar(ui).entrycget(0, "label"), _menubar(ui).entrycget(0, "underline")) == (
        "Datei",
        0,
    )
    assert ui.act_quit == 0
    assert ui.mnu_file.entrycget(0, "label") == "Beenden"
    assert ui.mnu_file.entrycget(0, "accelerator") == "Ctrl+Q"
    assert [ui.nbk_main.tab(t, "text") for t in ui.nbk_main.tabs()] == ["Begrüßung", "Info"]
    assert ui.lbl_name.cget("text") == "Ihr Name:"
    assert ui.sts_main.cget("text") == "Bereit"
    assert ui.btn_greet.cget("style") == "primary.TButton"
    sequences = tk_shortcut("Ctrl+Q", aqua=_aqua(ui)).sequences
    assert len(sequences) == 2 and all(ui.main.bind(seq) for seq in sequences)
    assert set(ui.widgets) >= {"main", "nbk_main", "ent_name", "act_quit", "sts_main"}
    ui.vars.user_name.set("Ana")
    assert ui.ent_name.get() == "Ana"
    ui.btn_greet.invoke()
    assert handlers.calls == ["on_greet"]
    ui.mnu_file.invoke(ui.act_quit)
    assert handlers.calls == ["on_greet", "on_quit"]


def test_retranslate_switches_language(tk_root: Any, loaded: list[LoadedUi]) -> None:
    ui, _handlers = _hello(tk_root, loaded)
    ui.retranslate("en_GB")
    assert ui.main.title() == "Hello PyGUIbud"
    assert _menubar(ui).entrycget(0, "label") == "File"
    assert ui.nbk_main.tab(0, "text") == "Greeting"
    assert ui.nbk_main.tab(0, "underline") == -1
    ui.retranslate("en_XA")
    assert ui.main.title().startswith("[") and ui.sts_main.cget("text").startswith("[")
    ui.retranslate("de_DE")
    assert ui.sts_main.cget("text") == "Bereit"


def test_build_fires_no_select_and_commands_work_at_once(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    body = (
        '<widget class="Notebook" id="nbk"><event name="select" handler="on_select"/>'
        '<cell row="0" column="0"/>'
        '<widget class="Frame" id="p1"><page/><layout type="pack"/></widget>'
        '<widget class="Frame" id="p2"><page/><layout type="pack"/></widget></widget>'
        '<widget class="Button" id="btn"><event name="command" handler="on_cmd"/>'
        '<cell row="1" column="0"/></widget>'
    )
    path = write_ui(tmp_path / "s.ui", f'<window id="w"><layout type="grid"/>{body}</window>')
    handlers = Recorder("on_select", "on_cmd")
    ui = load_ui(path, handlers, master=tk_root)
    loaded.append(ui)
    ui.btn.invoke()
    assert handlers.calls == ["on_cmd"]
    tk_root.update()
    assert handlers.calls == ["on_cmd"]
    ui.nbk.select(1)
    tk_root.update()
    assert handlers.calls == ["on_cmd", "on_select"]


RICH = """
<window id="main" kind="main" min_width="200">
  <prop name="title">Rich</prop>
  <menubar>
    <menu id="mnu">
      <prop name="text" translatable="true">_Edit</prop>
      <action id="act_a" handler="on_cmd" shortcut="Ctrl+O">
        <prop name="image" ref="pic"/><prop name="state">disabled</prop>
        <prop name="text" translatable="true">_Open</prop>
      </action>
      <separator/>
      <menu id="mnu_sub"><prop name="text">_More</prop>
        <action id="act_b" shortcut="Ctrl+O"><prop name="text">Again</prop></action>
      </menu>
    </menu>
  </menubar>
  <layout type="grid" gap="4"><column index="0" weight="1" minsize="50"/></layout>
  <widget class="Notebook" id="nbk">
    <cell row="0" column="0" sticky="nsew"/>
    <widget class="Frame" id="frm">
      <page image="pic"><prop name="text">_Alpha</prop></page>
      <layout type="grid" padding="3" gap="2"/>
      <widget class="Label" id="lbl"><prop name="image" ref="pic"/><prop name="text">Pic</prop>
        <cell row="0" column="0"/></widget>
      <widget class="Button" id="btn" tb:bootstyle="success">
        <prop name="state">disabled</prop><prop name="text">_Go</prop>
        <event name="command" handler="on_cmd"/><event name="focus_in" handler="on_focus"/>
        <event name="key:Ctrl+K" handler="on_key"/><event name="key:&lt;F5&gt;" handler="on_key"/>
        <cell row="0" column="1"/></widget>
      <widget class="Entry" id="ent" bind="name">
        <event name="change" handler="on_change"/><event name="activate" handler="on_act"/>
        <cell row="1" column="0"/></widget>
      <widget class="Checkbutton" id="chk"><prop name="text">Check</prop>
        <event name="change" handler="on_change"/><cell row="1" column="1"/></widget>
      <widget class="Radiobutton" id="rad" bind="choice"><prop name="value">2</prop>
        <cell row="2" column="0"/></widget>
      <widget class="Radiobutton" id="rad_s"><prop name="value">x</prop>
        <event name="change" handler="on_change"/><cell row="2" column="1"/></widget>
      <widget class="Combobox" id="cmb"><event name="select" handler="on_select"/>
        <cell row="3" column="0"/></widget>
      <widget class="Spinbox" id="spn"><prop name="maximum">5</prop>
        <cell row="3" column="1"/></widget>
      <widget class="Scale" id="scl"><event name="change" handler="on_change"/>
        <cell row="4" column="0"/></widget>
      <widget class="Progressbar" id="prg" bind="level"><cell row="4" column="1"/></widget>
      <widget class="tb:Meter" id="mtr" fallback="Progressbar"><cell row="5" column="0"/></widget>
      <widget class="Text" id="txt" tb:bootstyle="info">
        <event name="change" handler="on_change"/><cell row="5" column="1"/></widget>
      <widget class="Listbox" id="lst"><event name="activate" handler="on_act"/>
        <event name="select" handler="on_select"/><cell row="6" column="0"/></widget>
      <widget class="Treeview" id="tree"><prop name="show">headings</prop>
        <cell row="6" column="1"/></widget>
      <widget class="Scrollbar" id="sbr"><event name="change" handler="on_change"/>
        <cell row="7" column="0"/></widget>
      <widget class="Canvas" id="cnv"><prop name="background">#ffffff</prop>
        <event name="focus_out" handler="on_focus"/><cell row="7" column="1"/></widget>
      <widget class="Label" id="lbl_bound" bind="name"><prop name="text">ignored</prop>
        <cell row="8" column="0"/></widget>
      <widget class="Button" id="btn_bad" tb:bootstyle="Not Valid!">
        <cell row="8" column="1"/></widget>
      <widget class="Button" id="btn_odd" tb:bootstyle="nonsense">
        <cell row="9" column="0"/></widget>
      <widget class="Separator" id="sep"><cell row="9" column="1"/></widget>
      <widget class="LabelFrame" id="lfr"><prop name="text">Group</prop>
        <layout type="pack"/><cell row="10" column="0"/></widget>
    </widget>
    <widget class="ScrolledFrame" id="scf">
      <page><prop name="text">Scroll</prop></page>
      <layout type="pack" orient="horizontal" gap="5"/>
      <widget class="Label" id="l1"><prop name="text">one</prop><pack/></widget>
      <widget class="Label" id="l2"><prop name="text">two</prop>
        <pack fill="y" expand="true"/></widget>
      <include id="inc" src="#" component="part"><pack/></include>
    </widget>
    <widget class="PanedWindow" id="pnd">
      <page><prop name="text">Panes</prop></page>
      <widget class="Frame" id="pa"><page weight="1"/><layout type="pack"/></widget>
      <widget class="Frame" id="pb"><page weight="2"/><layout type="pack"/></widget>
    </widget>
  </widget>
  <statusbar id="sts"><prop name="text">Status</prop></statusbar>
</window>
<window id="dlg" kind="dialog" modal="true" buttons="ok,cancel">
  <prop name="title" translatable="true">Dialog</prop>
  <layout type="pack"/>
  <widget class="Label" id="dl"><prop name="image" ref="ppm"/><pack/></widget>
</window>
<window id="part" kind="component">
  <layout type="grid" padding="2"><row index="0" weight="1"/></layout>
  <widget class="Entry" id="pe" bind="name"><cell row="0" column="0"/></widget>
</window>
"""
HANDLERS = ("on_cmd", "on_focus", "on_key", "on_change", "on_act", "on_select")


@pytest.fixture
def rich(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> tuple[LoadedUi, Recorder, str]:
    (tmp_path / "pic.gif").write_bytes(GIF)
    (tmp_path / "pic.ppm").write_bytes(PPM)
    path = write_ui(
        tmp_path / "rich.ui",
        RICH,
        meta='theme="darkly"',
        resources='<image id="pic" src="pic.gif"/><image id="ppm" src="pic.ppm"/>',
        variables=(
            '<var id="name" type="string" default="Bo"/>'
            '<var id="choice" type="int" default="2"/>'
            '<var id="level" type="double" default="40"/>'
            '<var id="flag" type="bool" default="true"/>'
        ),
    )
    handlers = Recorder(*HANDLERS)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = load_ui(path, handlers, master=tk_root)
    loaded.append(ui)
    return ui, handlers, "\n".join(r.getMessage() for r in caplog.records)


def test_rich_document_builds_every_class(
    rich: tuple[LoadedUi, Recorder, str], tk_root: Any
) -> None:
    ui, handlers, messages = rich
    for expected in ("darkly", "tb:Meter", "Not Valid!", "nonsense", "Ctrl+O", "'info'"):
        assert expected in messages
    assert ui.btn.cget("style") == "success.TButton" and ui.btn.cget("underline") == 0
    assert str(ui.btn.cget("state")) == "disabled"
    assert str(ui.lbl.cget("compound")) == "left"
    assert ui.ent.get() == "Bo" and ui.lbl_bound.cget("text") == "Bo"
    assert ui.vars.choice.get() == 2 and ui.vars.flag.get() is True
    assert ui.vars.level.get() == 40.0
    assert ui.nbk.tab(0, "text") == "Alpha" and str(ui.nbk.tab(0, "compound")) == "left"
    assert ui.mnu.entrycget(ui.act_a, "state") == "disabled"
    assert ui.mnu_sub.entrycget(ui.act_b, "label") == "Again"
    assert ui.spn.cget("to") == 5.0 and ui.cnv.cget("background") == "#ffffff"
    assert "headings" in str(ui.tree.cget("show"))
    assert ui.sts.cget("text") == "Status"
    assert ui.windows.keys() == {"main", "dlg"}
    assert ui.dlg.title() == "Dialog" and ui.dlg.state() == "withdrawn"
    assert ui.main.minsize()[0] == 200
    assert ui.pnd.panes() and ui.inc.part.winfo_exists() and ui.inc.vars.name is ui.vars.name
    assert ui.inc.windows == {} and "pe" in ui.inc.widgets
    assert all(ui.btn.bind(seq) for seq in tk_key_sequences("Ctrl+K", aqua=_aqua(ui)))
    assert ui.btn.bind("<F5>")
    # change events: traces on bound and private variables, Text <<Modified>>
    ui.vars.name.set("Al")
    ui.chk.invoke()
    ui.rad_s.invoke()
    ui.scl.set(5)
    ui.txt.insert("1.0", "x")
    tk_root.update()
    assert handlers.calls.count("on_change") == 5
    ui.sbr.set(0, 1)
    ui.cmb.event_generate("<<ComboboxSelected>>")
    ui.lst.event_generate("<<ListboxSelect>>")
    tk_root.update()
    assert handlers.calls.count("on_select") == 2
    assert ui.show("dlg") is None and ui.dlg.state() == "normal"
    assert ui.show("main") is None
    ui.dlg.protocol("WM_DELETE_WINDOW")


def test_activate_returns_break_and_keys_fire(rich: tuple[LoadedUi, Recorder, str]) -> None:
    ui, handlers, _messages = rich
    ui.main.update()
    for widget, key in ((ui.ent, "<Return>"), (ui.lst, "<Return>"), (ui.btn, "<F5>")):
        widget.focus_force()
        widget.update()
        widget.event_generate(key, when="now")
    assert handlers.calls.count("on_act") == 2
    assert handlers.calls.count("on_key") == 1


def test_event_wiring_table() -> None:
    assert event_wiring("Button", "command") == ("command", ())
    assert event_wiring("Scrollbar", "change") == ("command", ())
    assert event_wiring("Text", "change") == ("modified", ("<<Modified>>",))
    assert event_wiring("Entry", "change") == ("trace", ())
    assert event_wiring("Treeview", "select") == ("virtual", ("<<TreeviewSelect>>",))
    assert event_wiring("Entry", "activate") == ("bind", ("<Return>", "<KP_Enter>"))
    assert event_wiring("Canvas", "focus_out") == ("bind", ("<FocusOut>",))
    assert event_wiring("Button", "key:<Control-s>") == ("key", ("<Control-s>",))


def test_failed_build_leaves_nothing(
    monkeypatch: pytest.MonkeyPatch, tk_root: Any, loaded: list[LoadedUi]
) -> None:
    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(_tk.TkSession, "_container", explode)
    with pytest.raises(UiError) as info:
        load_ui(HELLO, Recorder("on_greet", "on_quit"), master=tk_root)
    assert info.value.code == "runtime.build_failed" and "boom" in str(info.value)


def test_bad_master_and_existing_root(tk_root: Any) -> None:
    with pytest.raises(UiError) as info:
        load_ui(HELLO, Recorder("on_greet", "on_quit"), master="root")
    assert info.value.code == "runtime.backend_unavailable"
    with pytest.raises(UiError) as info:
        load_ui(HELLO, Recorder("on_greet", "on_quit"))
    assert info.value.code == "runtime.root_exists"


def test_handler_exception_keeps_the_app_running(
    tk_root: Any, loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[object] = []
    monkeypatch.setattr(tk_root, "report_callback_exception", lambda *a: errors.append(a))

    def broken() -> None:
        raise ValueError("handler bug")

    ui = load_ui(HELLO, {"on_greet": broken, "on_quit": broken}, master=tk_root)
    loaded.append(ui)
    ui.btn_greet.invoke()
    assert ui.main.winfo_exists()


def test_output_capture_leaves_the_tcl_std_handles_alone(pytestconfig: pytest.Config) -> None:
    # QA-10-13: fd-level capture closes the handles behind Tcl's stdout/stderr channels; Tcl on
    # Windows then fails a later `image create photo -file` with an empty TclError when the
    # file's new handle reuses one of those values. pyproject.toml sets --capture=sys.
    assert pytestconfig.getoption("capture") in ("sys", "no", "tee-sys")
