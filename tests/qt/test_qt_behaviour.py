"""Qt behaviour (Step 16c): variables both ways, B12, radio groups, the event matrix, menu
shortcuts and handler exceptions (spec backends §4.3, §4.4, §7, D13, D15)."""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from pyguibud.backends import _vars
from pyguibud.core.widgets import core_widgets
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui

pytestmark = pytest.mark.qt

_SKIP = {"Menubar", "Menu", "Action", "Statusbar"}


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


class Calls(Counter[str]):
    """Handlers by name; each call counts once."""

    def handlers(self, names: list[str]) -> dict[str, Callable[[], None]]:
        def handler(name: str) -> Callable[[], None]:
            return lambda: self.update([name])

        return {name: handler(name) for name in names}


def _load(path: Path, uis: list[LoadedUi], handlers: object = None) -> LoadedUi:
    ui = load_ui(path, handlers, backend="pyside6")
    uis.append(ui)
    return ui


def _main(body: str, layout: str = '<layout type="pack"/>', extra: str = "") -> str:
    return f'<window id="main" kind="main">{layout}{body}</window>{extra}'


# ---------------------------------------------------------------- variables (§4.4, D13)
_VARIABLES = (
    '<var id="name" type="string" default="Bo"/><var id="n" type="int" default="3"/>'
    '<var id="lvl" type="double" default="40"/><var id="flag" type="bool" default="true"/>'
    '<var id="choice" type="int" default="2"/>'
)
_P = "<pack/>"


def _radio(rid: str, value: str) -> str:
    return (
        f'<widget class="Radiobutton" id="{rid}" bind="choice">'
        f'<prop name="value">{value}</prop>{_P}</widget>'
    )


_BOUND = _main(
    f'<widget class="Entry" id="ent" bind="name">{_P}</widget>'
    f'<widget class="Entry" id="ent2" bind="name">{_P}</widget>'
    f'<widget class="Label" id="lbl" bind="name"><prop name="text">ignored</prop>{_P}</widget>'
    f'<widget class="Combobox" id="cmb" bind="name">{_P}</widget>'
    f'<widget class="Entry" id="ent_n" bind="n"><event name="change" handler="on_n"/>{_P}</widget>'
    f'<widget class="Spinbox" id="spn" bind="n">{_P}</widget>'
    f'<widget class="Scale" id="scl" bind="lvl">{_P}</widget>'
    f'<widget class="Progressbar" id="prg" bind="lvl">{_P}</widget>'
    f'<widget class="Checkbutton" id="chk" bind="flag"><event name="change" handler="on_flag"/>'
    f"{_P}</widget>"
    f'<widget class="Frame" id="fa"><layout type="pack"/>{_radio("rad1", "1")}{_P}</widget>'
    f'<widget class="Frame" id="fb"><layout type="pack"/>{_radio("rad2", "2")}'
    f"{_radio('rad3', '3')}{_P}</widget>"
)


@pytest.fixture
def bound(tmp_path: Path, loaded: list[LoadedUi]) -> tuple[LoadedUi, Calls]:
    calls = Calls()
    path = write_ui(tmp_path / "b.ui", _BOUND, variables=_VARIABLES)
    ui = _load(path, loaded, calls.handlers(["on_n", "on_flag"]))
    assert not calls  # building fires nothing
    return ui, calls


def test_widgets_show_the_variables(bound: tuple[LoadedUi, Calls]) -> None:
    ui, _calls = bound
    assert isinstance(ui.vars.name, _vars.StringVar) and str(ui.vars.name) == "name"
    assert ui.ent.text() == ui.ent2.text() == ui.lbl.text() == ui.cmb.currentText() == "Bo"
    assert ui.ent_n.text() == "3" and ui.spn.value() == 3.0
    assert ui.scl.value() == 40 and ui.prg.value() == 40 and ui.chk.isChecked()
    assert [r.isChecked() for r in (ui.rad1, ui.rad2, ui.rad3)] == [False, True, False]
    ui.retranslate("de_DE")
    assert ui.lbl.text() == "Bo"  # a bound label has no text slot


def test_variable_to_widgets(bound: tuple[LoadedUi, Calls]) -> None:
    ui, calls = bound
    ui.vars.name.set("Al")
    assert ui.ent.text() == ui.ent2.text() == ui.lbl.text() == ui.cmb.currentText() == "Al"
    ui.vars.lvl.set(75.0)
    assert ui.scl.value() == 75 and ui.prg.value() == 75
    ui.vars.n.set(8)
    assert ui.spn.value() == 8.0 and ui.ent_n.text() == "8" and calls["on_n"] == 1
    ui.vars.flag.set(False)
    assert not ui.chk.isChecked() and calls["on_flag"] == 1


def test_widget_to_variable_without_echo(bound: tuple[LoadedUi, Calls]) -> None:
    ui, _calls = bound
    ui.ent.setText("Zed")
    assert ui.vars.name.get() == "Zed" and ui.ent2.text() == "Zed" and ui.lbl.text() == "Zed"
    ui.ent.setCursorPosition(1)
    ui.ent.setText("Zeds")
    assert ui.ent.text() == "Zeds"
    ui.vars.lvl.set(10)
    ui.scl.setValue(55)
    assert ui.vars.lvl.get() == 55.0 and ui.prg.value() == 55
    ui.spn.setValue(4)
    assert ui.vars.n.get() == 4 and ui.ent_n.text() == "4"


def test_b12_an_int_entry_showing_text_keeps_the_last_value(
    bound: tuple[LoadedUi, Calls],
) -> None:
    ui, calls = bound
    ui.ent_n.setText("abc")
    assert ui.vars.n.get() == 3 and calls["on_n"] == 0 and ui.ent_n.text() == "abc"
    ui.ent_n.setText("12")
    assert ui.vars.n.get() == 12 and calls["on_n"] == 1


def test_bound_change_fires_once_per_user_change(bound: tuple[LoadedUi, Calls]) -> None:
    ui, calls = bound
    ui.chk.click()
    assert ui.vars.flag.get() is False and calls["on_flag"] == 1


def test_radio_group_is_one_per_variable_across_parents(bound: tuple[LoadedUi, Calls]) -> None:
    ui, _calls = bound
    assert ui.rad1.parentWidget() is not ui.rad3.parentWidget()
    ui.rad1.click()
    assert ui.vars.choice.get() == 1
    assert [r.isChecked() for r in (ui.rad1, ui.rad2, ui.rad3)] == [True, False, False]
    ui.vars.choice.set(3)
    assert [r.isChecked() for r in (ui.rad1, ui.rad2, ui.rad3)] == [False, False, True]
    ui.vars.choice.set(9)  # no radio has this value: none is checked, as in Tk
    assert not any(r.isChecked() for r in (ui.rad1, ui.rad2, ui.rad3))
    ui.rad2.click()
    assert ui.vars.choice.get() == 2 and ui.rad1.group() is ui.rad3.group()


def test_includes_share_the_host_variables(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    component = (
        '<window id="part" kind="component"><layout type="pack"/>'
        f'<widget class="Entry" id="inner" bind="name">{_P}</widget></window>'
    )
    windows = _main(f'<include id="inc" src="#" component="part">{_P}</include>', extra=component)
    path = write_ui(tmp_path / "i.ui", windows, variables='<var id="name" type="string"/>')
    ui = _load(path, loaded)
    ui.inc.inner.setText("shared")
    assert ui.vars.name.get() == "shared" and ui.inc.vars.name is ui.vars.name


# ---------------------------------------------------------------- the event matrix (§7)
def _matrix_ui() -> tuple[str, list[tuple[str, str]]]:
    pairs: list[tuple[str, str]] = []
    body: list[str] = []
    for spec in core_widgets():
        if spec.name in _SKIP or not spec.events:
            continue
        events = [*spec.events, *(("key:Ctrl+K",) if "focus_in" in spec.events else ())]
        wid = spec.name.lower()
        tags = "".join(f'<event name="{e}" handler="h_{wid}_{i}"/>' for i, e in enumerate(events))
        pairs += [(spec.name, e) for e in events]
        inner = ""
        if spec.name == "Notebook":
            inner = "".join(
                f'<widget class="Frame" id="pg{i}"><layout type="pack"/>'
                f'<page><prop name="text">P{i}</prop></page></widget>'
                for i in range(2)
            )
        if spec.name in ("Frame", "LabelFrame", "ScrolledFrame"):
            inner = '<layout type="pack"/>'
        body.append(f'<widget class="{spec.name}" id="{wid}">{tags}{inner}{_P}</widget>')
    return _main("".join(body)), pairs


def _trigger(ui: LoadedUi, name: str, event: str) -> None:
    w = getattr(ui, name.lower())
    send = QtWidgets.QApplication.sendEvent
    if event in ("focus_in", "focus_out"):
        kind = QtCore.QEvent.Type.FocusIn if event == "focus_in" else QtCore.QEvent.Type.FocusOut
        send(w, QtGui.QFocusEvent(kind))
    elif event.startswith("key:"):
        QTest.keyClick(w, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    elif (name, event) == ("Radiobutton", "change"):  # a lone checked radio cannot toggle
        w.setAutoExclusive(False)
        w.setChecked(False)
        w.setAutoExclusive(True)
        w.click()
    elif event == "command" or (name, event) in (
        ("Checkbutton", "change"),
        ("Radiobutton", "change"),
    ):
        w.click()
    elif (name, event) == ("Scrollbar", "change"):
        w.triggerAction(QtWidgets.QAbstractSlider.SliderAction.SliderSingleStepAdd)
    elif event == "change":
        {
            "Entry": lambda: w.setText("x"),
            "Text": lambda: w.setPlainText("x"),
            "Combobox": lambda: w.setEditText("x"),
            "Spinbox": lambda: w.setValue(5),
            "Scale": lambda: w.setValue(5),
        }[name]()
    elif event == "select" and name == "Notebook":
        w.setCurrentIndex(1)
    elif event == "select" and name == "Combobox":
        w.addItem("a")
        w.activated.emit(0)
    elif event == "select":
        item = _item(w, name)
        w.setCurrentItem(item)
    elif (name, event) == ("Entry", "activate"):
        QTest.keyClick(w, Qt.Key.Key_Return)
    else:  # activate of Listbox / Treeview
        w.itemActivated.emit(*((_item(w, name),) if name == "Listbox" else (_item(w, name), 0)))


def _item(w: Any, name: str) -> Any:
    if name == "Listbox":
        w.addItem("row")
        return w.item(w.count() - 1)
    return QtWidgets.QTreeWidgetItem(w, ["row"])


def test_event_matrix_each_pair_calls_its_handler_once(
    tmp_path: Path, loaded: list[LoadedUi], qapp: Any
) -> None:
    windows, pairs = _matrix_ui()
    names = [f"h_{c.lower()}_{i}" for c in dict.fromkeys(c for c, _ in pairs) for i in range(30)]
    calls = Calls()
    ui = _load(write_ui(tmp_path / "m.ui", windows), loaded, calls.handlers(names))
    assert not calls  # building fires nothing (signals connected afterwards)
    qapp.processEvents()
    index: Counter[str] = Counter()
    for name, event in pairs:
        handler = f"h_{name.lower()}_{index[name]}"
        index[name] += 1
        calls.clear()
        _trigger(ui, name, event)
        assert calls[handler] == 1, (name, event, dict(calls))
    assert len(pairs) > 30


def test_key_events_do_not_consume_the_key(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    event = '<event name="key:&lt;Shift-A&gt;" handler="k"/>'
    body = f'<widget class="Entry" id="ent">{event}{_P}</widget>'
    calls = Calls()
    ui = _load(write_ui(tmp_path / "k.ui", _main(body)), loaded, calls.handlers(["k"]))
    QTest.keyClicks(ui.ent, "A", Qt.KeyboardModifier.ShiftModifier)
    assert calls["k"] == 1 and ui.ent.text() == "A"


# ---------------------------------------------------------------- menus and shortcuts
_MENU = (
    '<menubar><menu id="mnu"><prop name="text">_File</prop>'
    '<action id="act_q" handler="quit" shortcut="Ctrl+Q"><prop name="text">_Quit</prop></action>'
    '<action id="act_dup" handler="dup" shortcut="ctrl+q"><prop name="text">Dup</prop></action>'
    "</menu></menubar>"
)
_DIALOG = (
    '<window id="dlg" kind="dialog"><menubar><menu id="dmn"><prop name="text">_Edit</prop>'
    '<action id="act_d" handler="dlg_act" shortcut="Ctrl+E"><prop name="text">Do</prop>'
    "</action></menu></menubar>"
    f'<layout type="pack"/><widget class="Entry" id="dent">{_P}</widget></window>'
)


def _activate(window: Any) -> None:
    window.show()
    window.raise_()
    window.activateWindow()
    # qWaitForWindowActive may already be true for a transient dialog of the active window.
    for _ in range(100):
        if QtWidgets.QApplication.activeWindow() is window:
            return
        QTest.qWait(20)
    pytest.fail("the window never became active")


def test_menu_shortcuts_fire_in_main_and_dialog_windows(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    windows = (
        f'<window id="main" kind="main">{_MENU}<layout type="pack"/>'
        f'<widget class="Entry" id="ent">{_P}</widget></window>{_DIALOG}'
    )
    calls = Calls()
    path = write_ui(tmp_path / "s.ui", windows)
    ui = load_ui(path, calls.handlers(["quit", "dup", "dlg_act"]), strict=False, backend="pyside6")
    loaded.append(ui)
    assert "The shortcut 'Ctrl+Q' of 'act_dup' is already used in this window." in caplog.text
    assert ui.act_q.shortcut() == QtGui.QKeySequence("Ctrl+Q") and ui.act_dup.shortcut().isEmpty()
    _activate(ui.main)
    QTest.keyClick(ui.ent, Qt.Key.Key_Q, Qt.KeyboardModifier.ControlModifier)
    assert calls == {"quit": 1}
    ui.act_dup.trigger()
    assert calls["dup"] == 1
    ui.show("dlg")
    _activate(ui.dlg)
    QTest.keyClick(ui.dent, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    assert calls["dlg_act"] == 1 and calls["quit"] == 1


def test_a_raising_handler_keeps_the_loop_running(
    tmp_path: Path, loaded: list[LoadedUi], capsys: pytest.CaptureFixture[str], qapp: Any
) -> None:
    seen: list[str] = []

    def boom() -> None:
        seen.append("boom")
        raise RuntimeError("handler failed")

    body = (
        f'<widget class="Button" id="btn"><event name="command" handler="boom"/>{_P}</widget>'
        '<widget class="Entry" id="ent" bind="name"><event name="change" handler="boom"/>'
        f'<event name="focus_in" handler="boom"/>{_P}</widget>'
        f'<widget class="Label" id="lbl" bind="name">{_P}</widget>'
    )
    path = write_ui(tmp_path / "x.ui", _main(body), variables='<var id="name" type="string"/>')
    ui = _load(path, loaded, {"boom": boom})
    focus = QtGui.QFocusEvent(QtCore.QEvent.Type.FocusIn)
    QtCore.QTimer.singleShot(0, ui.btn.click)  # a signal slot
    QtCore.QTimer.singleShot(0, lambda: ui.ent.setText("typed"))  # a variable trace
    QtCore.QTimer.singleShot(0, lambda: QtWidgets.QApplication.sendEvent(ui.ent, focus))
    QtCore.QTimer.singleShot(20, lambda: seen.append("after"))
    QtCore.QTimer.singleShot(40, qapp.quit)
    ui.run()
    assert seen == ["boom"] * 3 + ["after"] and ui.lbl.text() == "typed"
    assert capsys.readouterr().err.count("Traceback (most recent call last)") == 3


def test_a_variable_set_after_destroy_is_silent(
    tmp_path: Path, loaded: list[LoadedUi], capsys: pytest.CaptureFixture[str]
) -> None:
    body = f'<widget class="Entry" id="ent" bind="name">{_P}</widget>'
    path = write_ui(tmp_path / "d.ui", _main(body), variables='<var id="name" type="string"/>')
    ui = _load(path, loaded)
    name = ui.vars.name
    ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    name.set("late")
    assert name.get() == "late" and capsys.readouterr().err == ""
