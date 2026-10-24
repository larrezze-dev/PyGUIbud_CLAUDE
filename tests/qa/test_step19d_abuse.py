"""Step 19d QA: hostile plugins and backends (hardening spec §2/§3 "19d", H49-H69).

What a careless user or a hostile plugin author can do to the plugin guard (Tk and Qt), the
designer canvas, the preview child and ``pyguibud-uic``. The QA-19d-02..09 findings
(QA-19d-01 was fixed during the step) are regression tests now, each tagged with its id.

Plugins come from fake entry points: injected registries in-process, and a fake
``acme_pyguibud`` ``.dist-info`` folder on ``PYTHONPATH`` for subprocesses, so an installed
``acme-pyguibud`` is never needed nor changed.
"""

from __future__ import annotations

import contextlib
import gettext
import importlib
import json
import os
import subprocess
import sys
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import read_ui_string
from pyguibud.core import registry as registry_module
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec, canonical_distribution
from pyguibud.core.registry import WIDGETS_GROUP, Registry
from pyguibud.core.validate import validate
from pyguibud.i18n import LANGUAGES, PSEUDO_LANGUAGE, _
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests._paths import DESIGNER_SRC, RUNTIME_LOCALE, RUNTIME_SRC
from tests.core.test_plugins_17a import _doc, _plugin, _source, _spec, _widget
from tests.runtime.conftest import write_ui
from tests.runtime.test_tb_factories import _label_text, _registry
from tests.runtime.test_tb_factories_extra import _gauges, loaded  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
ACME_SRC = ROOT / "examples" / "acme_plugin" / "src"
DEMO = ROOT / "examples" / "acme_demo.ui"
ACME = "acme-pyguibud"
LOCALES = [*LANGUAGES, PSEUDO_LANGUAGE, "en_GB"]  # ends where it started
THEMES = ["dark", "high_contrast", "light"]  # the designer's three; ends on the default
MODES = ["import", "spec", "factory", "setter", "exit"]  # ACME_PYGUIBUD_BREAK values
_SIBLING = '<widget class="Label" id="keep"><prop name="text">Keep me</prop>'
_SIBLING += '<cell row="9" column="0"/></widget>'


def _failures(reg: Registry) -> list[str]:
    return [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]


def _zz_spec(factory: Any) -> WidgetSpec:
    """``zz:Gauge`` (fallback Label) with ``factory`` for every backend that takes it."""
    return WidgetSpec(
        name="zz:Gauge",
        display_name="Gauge",
        category="Zz",
        api_version=WIDGET_API_VERSION,
        fallback="Label",
        properties=(_label_text(),),
        factories={"ttkbootstrap": factory, "tkinter": factory, "pyside6": factory},
    )


def _window(body: str) -> str:
    return f'<window id="w"><layout type="grid"/>{body}</window>'


@pytest.fixture
def qapp() -> Any:
    """The session ``QApplication`` (offscreen), or a skip without PySide6."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["pyguibud-tests"])


@pytest.fixture
def qt_uis() -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        with contextlib.suppress(Exception):
            ui.destroy()


# ================================================================ Tk: what a factory returns
def _tk_shape(shape: str) -> Callable[..., Any]:
    def factory(parent: Any, *_args: object) -> Any:
        import tkinter

        if shape == "toplevel":
            return tkinter.Toplevel(parent)
        if shape == "menu":
            return tkinter.Menu(parent)
        if shape == "root":
            return parent._root()
        if shape == "window":  # the window that holds the parent
            return parent.winfo_toplevel()
        if shape == "elsewhere":  # made on the window, not in the parent
            return tkinter.Label(parent.winfo_toplevel())
        if shape == "destroyed":
            label = tkinter.Label(parent)
            label.destroy()
            return label
        if shape == "nonwidget":
            return 42
        if shape == "triple":
            label = tkinter.Label(parent)
            return (label, label, label)
        if shape == "none_inner":
            return (tkinter.Label(parent), None)
        if shape == "list":
            label = tkinter.Label(parent)
            return [label, label]
        if shape == "sibling":  # the existing Label of the same window
            return next(c for c in parent.winfo_children() if type(c).__name__ == "Label")
        raise AssertionError(shape)

    return factory


TK_SHAPES = [
    "toplevel", "menu", "root", "window", "elsewhere", "destroyed", "nonwidget", "triple",
    "none_inner", "list", "sibling",
]  # fmt: skip


@pytest.mark.gui
@pytest.mark.parametrize("shape", TK_SHAPES)
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_tk_a_factory_returning_garbage_falls_back_and_destroys_nothing_existing(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811 - the fixture also asserts no stray root children
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
    backend: str,
) -> None:
    reg = _registry(_zz_spec(_tk_shape(shape)))
    monkeypatch.setattr(registry_module, "_default", reg)
    path = write_ui(tmp_path / "t.ui", _window(_SIBLING + _gauges(1)))
    ui = load_ui(path, None, strict=False, backend=backend, master=tk_root)
    loaded.append(ui)
    tk_root.update_idletasks()
    assert _failures(reg) == ["check"]
    assert ui.keep.winfo_exists() and ui.keep.cget("text") == "Keep me"
    assert ui.keep.winfo_manager() == "grid"  # still placed in its window
    assert str(ui.g0.cget("text")) == "G0"  # the fallback
    ui.retranslate()  # nothing of the failed widget is left to raise


@pytest.mark.gui
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_tk_a_factory_littering_another_window_then_raising_is_swept(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
) -> None:
    """H60 in a wider form: strays on the root and a new Toplevel go, the window stays."""
    import tkinter

    litter: list[Any] = []

    def litterbug(parent: Any, *_args: object) -> Any:
        litter.extend((tkinter.Label(tk_root, text="litter"), tkinter.Toplevel(tk_root)))
        raise RuntimeError("after littering")

    reg = _registry(_zz_spec(litterbug))
    monkeypatch.setattr(registry_module, "_default", reg)
    path = write_ui(tmp_path / "t.ui", _window(_SIBLING + _gauges(1)))
    ui = load_ui(path, None, strict=False, backend=backend, master=tk_root)
    loaded.append(ui)
    assert _failures(reg) == ["create"]
    assert [w.winfo_exists() for w in litter] == [0, 0]
    assert ui.keep.winfo_exists()


@pytest.mark.gui
@pytest.mark.parametrize("raises", [False, True])
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_tk_another_interfaces_widget_returned_as_inner_survives(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    backend: str,
    raises: bool,
) -> None:
    """H61 across two interfaces: the other ``ui.keep`` is never destroyed."""
    import tkinter

    other: list[LoadedUi] = []

    def thief(parent: Any, *_args: object) -> Any:
        frame = tkinter.Frame(parent)
        if raises:
            raise RuntimeError("after making a frame")
        return (frame, other[0].keep)

    reg = _registry(_zz_spec(thief))
    monkeypatch.setattr(registry_module, "_default", reg)
    first = write_ui(tmp_path / "o.ui", _window(_SIBLING))
    other.append(load_ui(first, None, strict=False, backend=backend, master=tk_root))
    loaded.append(other[0])
    path = write_ui(tmp_path / "t.ui", _window(_SIBLING + _gauges(1)))
    loaded.append(load_ui(path, None, strict=False, backend=backend, master=tk_root))
    assert _failures(reg) == ["create" if raises else "check"]
    assert other[0].keep.winfo_exists() and other[0].keep.winfo_manager() == "grid"


@pytest.mark.gui
@pytest.mark.parametrize("vandal", ["parent", "sibling"])
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_tk_a_factory_destroying_its_parent_or_a_sibling_gives_a_ui_error(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    vandal: str,
    backend: str,
) -> None:
    """The build cannot go on; ``load_ui`` raises its documented UiError (never a TclError)."""
    import tkinter

    def destroyer(parent: Any, *_args: object) -> Any:
        label = tkinter.Label(parent)
        if vandal == "parent":
            parent.destroy()
        else:
            next(c for c in parent.winfo_children() if c is not label).destroy()
        return label

    monkeypatch.setattr(registry_module, "_default", _registry(_zz_spec(destroyer)))
    path = write_ui(tmp_path / "t.ui", _window(_SIBLING + _gauges(1)))
    with pytest.raises(UiError) as caught:
        loaded.append(load_ui(path, None, strict=False, backend=backend, master=tk_root))
    assert caught.value.code == "runtime.build_failed"


@pytest.mark.gui
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_tk_destroy_twice_and_retranslate_after_destroy_are_safe(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    backend: str,
) -> None:
    calls: list[str] = []
    body = (
        '<widget class="Entry" id="en" bind="s"><event name="change" handler="h"/>'
        '<cell row="0" column="0"/></widget>'
        '<widget class="tb:Meter" id="mt" bind="d" fallback="Progressbar">'
        '<cell row="1" column="0"/></widget>'
    )
    path = write_ui(
        tmp_path / "d.ui",
        _window(body),
        variables='<var id="s" type="string"/><var id="d" type="double"/>',
    )
    ui = load_ui(path, {"h": lambda: calls.append("h")}, backend=backend, master=tk_root)
    ui.destroy()
    ui.destroy()
    with pytest.raises(UiError) as caught:
        ui.retranslate()
    assert caught.value.code == "runtime.destroyed"
    ui.vars.s.set("x")
    ui.vars.d.set(3.0)
    assert calls == [] and ui.vars.s.trace_info() == [] and ui.vars.d.trace_info() == []


# ================================================================ Qt: what a factory returns
def _qt_shape(shape: str) -> Callable[..., Any]:
    def factory(parent: Any, _props: object) -> Any:
        import shiboken6
        from PySide6 import QtCore, QtWidgets

        if shape == "dialog":
            return QtWidgets.QDialog(parent)
        if shape == "mainwindow":
            return QtWidgets.QMainWindow(parent)
        if shape == "deleted":
            label = QtWidgets.QLabel(parent)
            shiboken6.delete(label)
            return label
        if shape == "triple":
            label = QtWidgets.QLabel(parent)
            return (label, label, label)
        if shape == "nonwidget":
            return QtCore.QObject(parent)
        if shape == "parent":
            return parent
        if shape == "window":
            return parent.window()
        if shape == "parentless":
            return QtWidgets.QLabel()
        if shape == "sibling":
            return next(c for c in parent.children() if isinstance(c, QtWidgets.QLabel))
        raise AssertionError(shape)

    return factory


QT_SHAPES = [
    "dialog", "mainwindow", "deleted", "triple", "nonwidget", "parent", "window", "parentless",
    "sibling",
]  # fmt: skip


@pytest.mark.qt
@pytest.mark.parametrize("shape", QT_SHAPES)
def test_qt_a_factory_returning_garbage_falls_back_and_deletes_nothing_existing(
    tmp_path: Path,
    qapp: Any,
    qt_uis: list[LoadedUi],
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    import shiboken6
    from PySide6 import QtCore

    reg = _registry(_zz_spec(_qt_shape(shape)))
    monkeypatch.setattr(registry_module, "_default", reg)
    path = write_ui(tmp_path / "q.ui", _window(_SIBLING + _gauges(1)))
    ui = load_ui(path, None, strict=False, backend="pyside6")
    qt_uis.append(ui)
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert _failures(reg) == ["check"]
    assert shiboken6.isValid(ui.keep) and ui.keep.text() == "Keep me"
    assert type(ui.g0).__name__ == "QLabel" and ui.g0.text() == "G0"
    ui.retranslate()


# ================================================================ Qt: key handlers
def _key_ui(tmp_path: Path, qt_uis: list[LoadedUi], binds: list[str]) -> tuple[Any, list[str]]:
    events = "".join(
        f'<event name="key:{b.replace("<", "&lt;").replace(">", "&gt;")}" handler="h{i}"/>'
        for i, b in enumerate(binds)
    )
    body = f'<widget class="Entry" id="en">{events}<cell row="0" column="0"/></widget>'
    calls: list[str] = []
    handlers = {f"h{i}": (lambda b=b: calls.append(b)) for i, b in enumerate(binds)}
    ui = load_ui(write_ui(tmp_path / "k.ui", _window(body)), handlers, backend="pyside6")
    qt_uis.append(ui)
    return ui, calls


def _press(widget: Any, key: str, mods: str) -> None:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt

    table = {
        "C": Qt.KeyboardModifier.ControlModifier,
        "A": Qt.KeyboardModifier.AltModifier,
        "S": Qt.KeyboardModifier.ShiftModifier,
        "M": Qt.KeyboardModifier.MetaModifier,
    }
    modifiers = Qt.KeyboardModifier.NoModifier
    for letter in mods:
        modifiers |= table[letter]
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, getattr(Qt.Key, key), modifiers)
    QtWidgets.QApplication.sendEvent(widget, event)


@pytest.mark.qt
@pytest.mark.parametrize(
    ("key", "mods", "fired"),
    [
        ("Key_Return", "", ["<Return>"]),
        ("Key_Return", "S", ["<Return>"]),  # extra modifiers allowed, as Tk
        ("Key_Return", "ASM", ["<Return>"]),
        ("Key_Return", "C", ["<Control-Return>"]),  # the most specific only
        ("Key_Return", "CAS", ["<Control-Return>"]),
        ("Key_Escape", "CASM", ["<Escape>"]),
        ("Key_F4", "A", ["<Alt-F4>"]),
        ("Key_F4", "", []),
        ("Key_A", "", ["<a>"]),
        ("Key_A", "S", ["<A>"]),  # Shift is exact on letters
        ("Key_A", "C", ["<a>"]),
        ("Key_Tab", "", ["<Tab>"]),
        ("Key_Backtab", "S", ["<Tab>"]),  # QA-19d-05: Shift+Tab is Tab with Shift (Tk, Windows)
    ],
)
def test_qt_key_handlers_with_modifier_combinations(
    tmp_path: Path,
    qapp: Any,
    qt_uis: list[LoadedUi],
    key: str,
    mods: str,
    fired: list[str],
) -> None:
    binds = ["<Return>", "<Control-Return>", "<Escape>", "<Alt-F4>", "<a>", "<A>", "<Tab>"]
    ui, calls = _key_ui(tmp_path, qt_uis, binds)
    _press(ui.en, key, mods)
    assert calls == fired


# QA-19d-05 (regression)
@pytest.mark.qt
def test_qt_shift_tab_handler_fires_on_backtab(
    tmp_path: Path, qapp: Any, qt_uis: list[LoadedUi]
) -> None:
    ui, calls = _key_ui(tmp_path, qt_uis, ["<Shift-Tab>"])
    _press(ui.en, "Key_Backtab", "S")  # what Qt sends for Shift+Tab
    assert calls == ["<Shift-Tab>"]


_EXIT = """
import os, sys
sys.path.insert(0, {root!r})
from PySide6 import QtCore, QtGui, QtWidgets
from pyguibud_runtime import load_ui

def quit_now():
    sys.exit(5)

ui = load_ui({path!r}, {{"quit_now": quit_now}}, backend="pyside6")
press = QtGui.QKeyEvent(
    QtCore.QEvent.Type.KeyPress, QtCore.Qt.Key.Key_Escape, QtCore.Qt.KeyboardModifier.NoModifier
)
QtCore.QTimer.singleShot(200, lambda: QtWidgets.QApplication.sendEvent(ui.en, press))
QtCore.QTimer.singleShot(5000, QtWidgets.QApplication.quit)
ui.run()
print("still running")
"""


@pytest.mark.qt
def test_qt_a_key_handler_calling_sys_exit_ends_the_program_like_tk(tmp_path: Path) -> None:
    """The eventFilter catches ``Exception`` only: a "quit" handler still quits (Tk parity)."""
    pytest.importorskip("PySide6")
    body = (
        '<widget class="Entry" id="en"><event name="key:&lt;Escape&gt;" handler="quit_now"/>'
        '<cell row="0" column="0"/></widget>'
    )
    window = f'<window id="w" kind="main"><layout type="grid"/>{body}</window>'
    path = write_ui(tmp_path / "x.ui", window)
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, "-c", _EXIT.format(root=str(ROOT), path=str(path))],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
        env=env,
    )
    assert done.returncode == 5, done.stderr
    assert "still running" not in done.stdout
    assert "Error calling Python override" not in done.stderr


# ================================================================ Qt: bound Combobox
def _combos(tmp_path: Path, qt_uis: list[LoadedUi], default: str) -> Any:
    body = (
        '<widget class="Combobox" id="ro" bind="pick"><prop name="state">readonly</prop>'
        '<cell row="0" column="0"/></widget>'
        '<widget class="Combobox" id="ed" bind="pick"><cell row="1" column="0"/></widget>'
    )
    path = write_ui(
        tmp_path / "c.ui",
        _window(body),
        variables=f'<var id="pick" type="string" default="{default}"/>',
    )
    ui = load_ui(path, None, backend="pyside6")
    qt_uis.append(ui)
    return ui


@pytest.mark.qt
def test_qt_combobox_items_added_to_an_empty_list_keep_the_variable(
    tmp_path: Path, qapp: Any, qt_uis: list[LoadedUi]
) -> None:
    ui = _combos(tmp_path, qt_uis, "beta")
    ui.ro.addItems(["gamma"])
    ui.ed.addItems(["x"])
    assert ui.vars.pick.get() == "beta"
    ui.ro.addItems(["beta"])
    assert ui.vars.pick.get() == "beta" and ui.ro.currentText() == "beta"


# QA-19d-06 (regression)
@pytest.mark.qt
@pytest.mark.parametrize(("which", "edit"), [("ro", "clear"), ("ed", "clear"), ("ro", "remove")])
def test_qt_combobox_refreshing_the_list_keeps_the_variable(
    tmp_path: Path, qapp: Any, qt_uis: list[LoadedUi], which: str, edit: str
) -> None:
    ui = _combos(tmp_path, qt_uis, "beta")
    combo = getattr(ui, which)
    combo.addItems(["gamma", "beta"])
    assert ui.vars.pick.get() == "beta" and combo.currentText() == "beta"
    if edit == "clear":
        combo.clear()
        combo.addItems(["gamma", "beta"])
    else:
        combo.removeItem(combo.findText("beta"))
    assert ui.vars.pick.get() == "beta"


# ================================================================ Qt: stolen widgets
def _steal(
    tmp_path: Path, qt_uis: list[LoadedUi], monkeypatch: pytest.MonkeyPatch, mode: str
) -> tuple[Registry, LoadedUi]:
    from PySide6 import QtWidgets

    other: list[LoadedUi] = []

    def thief(parent: Any, _props: object) -> Any:
        victim = other[0].keep
        if mode == "into_parent":  # another window's label moved into the parent
            victim.setParent(parent)
            return victim
        outer = QtWidgets.QFrame(parent)
        victim.setParent(outer)  # ... or into the plugin's own new frame, then a failure
        raise RuntimeError("after the reparent")

    reg = _registry(_zz_spec(thief))
    monkeypatch.setattr(registry_module, "_default", reg)
    other.append(load_ui(write_ui(tmp_path / "o.ui", _window(_SIBLING)), None, backend="pyside6"))
    qt_uis.append(other[0])
    path = write_ui(tmp_path / "t.ui", _window(_SIBLING + _gauges(1)))
    qt_uis.append(load_ui(path, None, strict=False, backend="pyside6"))
    return reg, other[0]


# QA-19d-07 (regression)
@pytest.mark.qt
def test_qt_a_widget_reparented_into_a_failed_outer_is_not_deleted(
    tmp_path: Path, qapp: Any, qt_uis: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    import shiboken6
    from PySide6 import QtCore

    reg, other = _steal(tmp_path, qt_uis, monkeypatch, "into_outer")
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert _failures(reg) == ["create"]
    assert shiboken6.isValid(other.keep)


# QA-19d-08 (regression)
@pytest.mark.qt
def test_qt_a_pre_existing_widget_reparented_into_parent_is_rejected(
    tmp_path: Path, qapp: Any, qt_uis: list[LoadedUi], monkeypatch: pytest.MonkeyPatch
) -> None:
    reg, _other = _steal(tmp_path, qt_uis, monkeypatch, "into_parent")
    assert _failures(reg) == ["check"]


# ================================================================ registry: H66/H67 abuse
JUNK_PLUGINS = [
    "", " ", "x" * 300, "evil; rm -rf /", "acme-pyguibud\n--index-url http://e",
    "acme-pyguibud --index-url=http://e", "../acme",
]  # fmt: skip


@pytest.mark.parametrize("junk", JUNK_PLUGINS)
def test_junk_plugin_names_never_reach_a_pip_hint(junk: str) -> None:
    reg = Registry(entry_points=_source(_plugin([_spec("acme:Other")], ACME)))
    document = _doc(_widget("acme:Gauge", "Label", plugin=junk))
    commands = [str(f.params.get("command", "")) for f in validate(document, reg).findings]
    assert all(c in ("", f"pip install {ACME}") for c in commands), commands


# QA-19d-04 (regression)
@pytest.mark.parametrize("broken", [False, True])
def test_a_correct_plugin_name_is_not_replaced_by_an_unrelated_entry_point(broken: bool) -> None:
    obj: object = RuntimeError("boom") if broken else [_spec("evil:Thing")]
    reg = Registry(entry_points=_source(_plugin(obj, "evil-dist", name="acme")))
    document = _doc(_widget("acme:ColourSwatch", "Label", plugin=ACME))
    (finding,) = validate(document, reg).findings
    assert finding.code == "validate.plugin_missing"
    assert finding.params["plugin"] == ACME
    resolved = reg.resolve("acme:ColourSwatch", "tkinter", "Label", plugin=ACME)
    assert resolved.code == "registry.plugin_missing"


# ================================================================ catalogues
def test_the_new_19d_messages_are_translated_with_their_placeholders() -> None:
    import string

    from pyguibud.backends._tk import _M_TEXT_FAILED
    from pyguibud.backends._tkmap import _M_BAD_DATE
    from pyguibud.designer.panels.canvas import _M_UNEXPECTED
    from pyguibud.designer.preview import M_TIMEOUT_QT
    from pyguibud.i18n import set_language

    def fields(text: str) -> list[str]:
        return sorted(f for _t, f, _s, _c in string.Formatter().parse(text) if f)

    try:
        for lang in [*LANGUAGES, PSEUDO_LANGUAGE]:
            set_language(lang)
            for msgid in (_M_TEXT_FAILED, M_TIMEOUT_QT, _M_UNEXPECTED, _M_BAD_DATE):
                text = _(msgid)
                assert lang == "en_GB" or text != msgid, (lang, msgid)
                assert fields(text) == fields(msgid), (lang, msgid)
    finally:
        set_language("en_GB")


# QA-19d-02 (regression)
def test_no_catalogue_translation_contains_a_control_character() -> None:
    folder = RUNTIME_LOCALE
    bad: list[tuple[str, str]] = []
    for mo in sorted(folder.glob("*/LC_MESSAGES/pyguibud.mo")):
        with mo.open("rb") as handle:
            catalogue: dict[Any, Any] = gettext.GNUTranslations(handle)._catalog  # type: ignore[attr-defined]
        for msgstr in catalogue.values():
            if isinstance(msgstr, str) and any(ord(c) < 32 and c not in "\n\t" for c in msgstr):
                bad.append((mo.parts[-3], msgstr))
    assert bad == []


# QA-19d-03 (regression)
def test_the_canvas_card_messages_keep_their_own_translator_comments() -> None:
    from babel.messages.pofile import read_po

    with (RUNTIME_LOCALE / "pyguibud.pot").open("rb") as handle:
        catalogue = read_po(handle)
    draw = catalogue.get("This window cannot be drawn on the canvas: {reason}")
    unexpected = catalogue.get("an unexpected error occurred; see the log")
    assert draw is not None and unexpected is not None
    assert any("Translators" in c for c in draw.auto_comments)
    assert not any("usually in English" in c for c in unexpected.auto_comments)


# ================================================================ designer
@dataclass
class _Dist:
    name: str


class _AcmeEP:
    """The real acme sample through a fake entry point (an installed acme is filtered out)."""

    name, value, group = "acme", "acme_pyguibud:widgets", WIDGETS_GROUP

    def __init__(self) -> None:
        self.dist = _Dist(ACME)

    def load(self) -> object:
        sys.modules.pop("acme_pyguibud", None)
        return importlib.import_module("acme_pyguibud").widgets


class _ZzEP:
    name, value, group = "zz", "zz_plugin:specs", WIDGETS_GROUP

    def __init__(self, factory: Callable[..., Any]) -> None:
        self.dist = _Dist("zz-plugin")
        self.factory = factory

    def load(self) -> object:
        return lambda: (_zz_spec(self.factory),)


@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path_factory.mktemp("profile19d")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))


@pytest.fixture
def plugin(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """Add a fake plugin to the metadata entry points before the designer starts.

    ``request.param``: an ``ACME_PYGUIBUD_BREAK`` mode (str or None) for the real acme sample,
    or a Tk factory for ``zz:Gauge``.
    """
    real = registry_module._metadata_entry_points
    param = getattr(request, "param", None)
    ep: Any
    if callable(param):
        ep = _ZzEP(param)
    else:
        ep = _AcmeEP()
        monkeypatch.syspath_prepend(str(ACME_SRC))
        if param is None:
            monkeypatch.delenv("ACME_PYGUIBUD_BREAK", raising=False)
        else:
            monkeypatch.setenv("ACME_PYGUIBUD_BREAK", param)

    def source(group: str) -> Iterable[Any]:
        found = [e for e in real(group)
                 if e.dist is None or canonical_distribution(e.dist.name) != ACME]  # fmt: skip
        return [*found, ep] if group == WIDGETS_GROUP else found

    monkeypatch.setattr(registry_module, "_metadata_entry_points", source)
    registry_module.reset_default_registry()
    yield param
    sys.modules.pop("acme_pyguibud", None)


@pytest.fixture
def app(tk_root: Any, plugin: Any) -> Iterator[Any]:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.recovery import RecoverySession
    from pyguibud.designer.settings import Settings
    from tests.conftest import reset_root

    reset_root(tk_root)
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(tk_root, settings=Settings(), recovery=recovery)
    yield designer
    tk_root.protocol("WM_DELETE_WINDOW", tk_root.destroy)
    for dialog in designer._live_dialogs():
        with contextlib.suppress(Exception):
            dialog.close()
    designer.set_language("en_GB")
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()
    reset_root(tk_root)


def _texts(widget: Any) -> list[str]:
    found: list[str] = []
    stack = [widget]
    while stack:
        current = stack.pop()
        with contextlib.suppress(Exception):
            text = str(current.cget("text"))
            if text and not text.startswith("PY_VAR"):  # a Tk variable name, not a text
                found.append(text)
        stack.extend(current.winfo_children())
    return found


def _open(app: Any, tk_root: Any, text: str) -> Any:
    app.session.open_result(read_ui_string(text, source="qa19d"), name="qa19d")
    tk_root.update()
    panel = app.shell.canvas
    for stage in panel.stages:
        panel.show_window(stage.window)
    tk_root.update()
    return panel


def _no_raw(texts: list[str]) -> None:
    for raw in ("invalid command name", "bad window path", "Traceback", "Error(", "TclError"):
        assert not any(raw in t for t in texts), (raw, texts)


@pytest.mark.gui
@pytest.mark.parametrize("plugin", [*MODES, None], indirect=True)
def test_designer_every_acme_break_mode_in_every_locale(
    plugin: str | None, app: Any, tk_root: Any
) -> None:
    from pyguibud.designer.canvas.engine import _M_PLUGIN_FAILED
    from pyguibud.designer.present.plugins import plugin_rows

    panel = _open(app, tk_root, DEMO.read_text(encoding="utf-8"))
    status = {row.key: row.status for row in plugin_rows(app.session.registry)}[ACME]
    assert status == ("loaded" if plugin is None else "failed")
    for lang in LOCALES:
        app.set_language(lang)
        tk_root.update()
        texts = [t for stage in panel.stages for t in _texts(stage.stage)]
        assert all(stage.error is None for stage in panel.stages), lang
        card = _(_M_PLUGIN_FAILED).format(name="acme:ColourSwatch")
        if plugin in ("factory", "setter"):  # it was found and failed to build: the card
            assert card in texts and "Swatch" not in texts, (lang, texts)
        else:  # never found (import/spec/exit), or working: the swatch text is shown
            assert "Swatch" in texts and card not in texts, (lang, texts)
        _no_raw(texts)
    expected = [t for stage in panel.stages for t in _texts(stage.stage)]
    for theme in THEMES:  # a theme switch rebuilds nothing into raw text
        app.set_theme(theme)
        app.flush_theme()
        tk_root.update()
        assert [t for stage in panel.stages for t in _texts(stage.stage)] == expected, theme


def _vandal_parent(parent: Any, *_args: object) -> Any:
    import tkinter

    label = tkinter.Label(parent)
    parent.destroy()
    return label


class _Sets:
    count = 0
    victim: Any = None


def _setter_raising_later(parent: Any, *_args: object) -> Any:
    """Its third text set raises and later ones exit: retranslates and rebuilds survive."""
    import tkinter

    class Fragile(tkinter.Label):
        def configure(self, cnf: Any = None, **kw: Any) -> Any:
            if "text" in kw:
                _Sets.count += 1
                if _Sets.count == 3:
                    raise RuntimeError("third text set")
                if _Sets.count >= 4:
                    sys.exit(9)
            return super().configure(cnf, **kw)

        config = configure

    return Fragile(parent)


def _thief(parent: Any, *_args: object) -> Any:
    """Returns the designer's own top-level window."""
    return parent.winfo_toplevel()


def _designer_thief(parent: Any, *_args: object) -> Any:
    """Returns a widget of the designer shell as ``inner``."""
    import tkinter

    _Sets.victim = parent.winfo_toplevel().winfo_children()[0]
    return (tkinter.Frame(parent), _Sets.victim)


ZZ_DOC = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
    '<window id="w" kind="main"><layout type="grid"/>'
    '<widget class="Label" id="keep"><prop name="text">Keep me</prop>'
    '<cell row="0" column="0"/></widget>'
    '<widget class="zz:Gauge" id="g0" fallback="Label" plugin="zz-plugin">'
    '<prop name="text" translatable="true">G0</prop><cell row="1" column="0"/></widget>'
    "</window></pyguibud-ui>"
)


@pytest.mark.gui
@pytest.mark.parametrize("plugin", [_vandal_parent], indirect=True)
def test_designer_a_factory_destroying_its_parent_shows_a_translated_card(
    plugin: Any, app: Any, tk_root: Any
) -> None:
    """H68 in every locale: the card reason is the translated text, never Tcl's."""
    from pyguibud.designer.panels.canvas import _M_CANNOT_DRAW, _M_UNEXPECTED

    panel = _open(app, tk_root, ZZ_DOC)
    for lang in LOCALES:
        app.set_language(lang)
        tk_root.update()
        (stage,) = panel.stages
        texts = _texts(stage.stage)
        assert _(_M_CANNOT_DRAW).format(reason=_(_M_UNEXPECTED)) in texts, (lang, texts)
        _no_raw(texts)
    for theme in THEMES:
        app.set_theme(theme)
        app.flush_theme()
        tk_root.update()
        (stage,) = panel.stages
        assert _(_M_CANNOT_DRAW).format(reason=_(_M_UNEXPECTED)) in _texts(stage.stage), theme


@pytest.mark.gui
@pytest.mark.parametrize("plugin", [_setter_raising_later], indirect=True)
def test_designer_a_setter_raising_or_exiting_on_later_sets_survives_every_locale(
    plugin: Any, app: Any, tk_root: Any
) -> None:
    from pyguibud.designer.canvas.engine import _M_PLUGIN_FAILED

    _Sets.count = 0
    panel = _open(app, tk_root, ZZ_DOC)
    texts: list[str] = []
    for lang in LOCALES:
        app.set_language(lang)
        tk_root.update()
        texts = [t for stage in panel.stages for t in _texts(stage.stage)]
        assert "Keep me" in texts and all(s.error is None for s in panel.stages), lang
        _no_raw(texts)
    assert _Sets.count >= 4  # both the raise and the exit were met
    assert _(_M_PLUGIN_FAILED).format(name="zz:Gauge") in texts
    assert set(_failures(app.session.registry)) <= {"check", "wire"}


@pytest.mark.gui
@pytest.mark.parametrize("plugin", [_thief, _designer_thief], indirect=True)
def test_designer_a_factory_returning_designer_widgets_never_destroys_them(
    plugin: Any, app: Any, tk_root: Any
) -> None:
    """H61 inside the designer: the designer window and its panels survive."""
    _Sets.victim = None
    before = [str(w) for w in tk_root.winfo_children()]
    _open(app, tk_root, ZZ_DOC)
    assert _failures(app.session.registry) == ["check"]
    assert [str(w) for w in tk_root.winfo_children()] == before
    assert _Sets.victim is None or _Sets.victim.winfo_exists()


# ================================================================ subprocesses: preview, uic
def _fake_acme_path(tmp_path: Path) -> str:
    """A ``PYTHONPATH`` with acme's source and a fake ``acme_pyguibud`` distribution."""
    site = tmp_path / "site"
    info = site / "acme_pyguibud-0.0.1.dist-info"
    info.mkdir(parents=True)
    (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {ACME}\nVersion: 0.0.1\n")
    (info / "entry_points.txt").write_text("[pyguibud.widgets]\nacme = acme_pyguibud:widgets\n")
    return os.pathsep.join([str(site), str(ACME_SRC), str(DESIGNER_SRC), str(RUNTIME_SRC)])


def _preview(work: Path, env: dict[str, str], backend: str, limit: float) -> dict[str, Any]:
    """Run the preview child until ``ready.json`` or ``result.json`` appears, then end it."""
    argv = [sys.executable, "-m", "pyguibud.preview", "--ui-lang", "en_GB", "--backend", backend]
    process = subprocess.Popen(
        [*argv, "--", str(DEMO)],
        cwd=work,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    started, found = time.monotonic(), {}
    try:
        while time.monotonic() - started < limit:
            for name in ("ready.json", "result.json"):
                with contextlib.suppress(OSError, ValueError):
                    found[name] = json.loads((work / name).read_text(encoding="utf-8"))
            if found or process.poll() is not None:
                break
            time.sleep(0.1)
    finally:
        process.kill()
        process.wait(timeout=30)
    return {**found, "seconds": time.monotonic() - started}


@pytest.mark.parametrize(
    "backend",
    [
        pytest.param("ttkbootstrap", marks=pytest.mark.gui),
        pytest.param("tkinter", marks=pytest.mark.gui),
        pytest.param("pyside6", marks=pytest.mark.qt),
    ],
)
@pytest.mark.parametrize("mode", [*MODES, ""])
def test_preview_child_with_every_acme_break_mode_shows_the_window(
    tmp_path: Path, mode: str, backend: str
) -> None:
    if backend == "pyside6":
        pytest.importorskip("PySide6")
    env = {
        **os.environ,
        "PYTHONPATH": _fake_acme_path(tmp_path),
        "ACME_PYGUIBUD_BREAK": mode,
        "QT_QPA_PLATFORM": "offscreen",
        "PYTHONIOENCODING": "utf-8",
    }
    work = tmp_path / "work"
    work.mkdir()
    found = _preview(work, env, backend, 60)
    assert "ready.json" in found, found
    warnings = " ".join(str(w) for w in found["ready.json"].get("warnings", []))
    if mode in ("import", "spec", "exit"):
        assert "failed to load" in warnings
    elif mode in ("factory", "setter"):
        assert "'acme:ColourSwatch' failed to build" in warnings
    else:
        assert "acme" not in warnings


@pytest.mark.parametrize("mode", [*MODES, ""])
def test_uic_export_and_check_with_every_acme_break_mode(tmp_path: Path, mode: str) -> None:
    env = {
        **os.environ,
        "PYTHONPATH": _fake_acme_path(tmp_path),
        "ACME_PYGUIBUD_BREAK": mode,
        "PYTHONIOENCODING": "utf-8",
    }
    out = tmp_path / "demo_ui.py"
    for extra in (["-o", str(out)], ["--check"]):
        done = subprocess.run(
            [sys.executable, "-m", "pyguibud.uic", *extra, str(DEMO)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            check=False,
            env=env,
        )
        assert done.returncode == 0, done.stderr
        assert "Traceback" not in done.stderr
    assert out.is_file() and "acme" in out.read_text(encoding="utf-8")


@pytest.mark.qt
@pytest.mark.parametrize("lang", ["en_GB", "de_DE"])
def test_preview_child_with_a_bogus_qt_platform_is_refused_at_once(
    tmp_path: Path, lang: str
) -> None:
    pytest.importorskip("PySide6")
    from pyguibud.backends.pyside6 import _M_NO_PLUGIN
    from pyguibud.i18n import set_language

    env = {**os.environ, "QT_QPA_PLATFORM": "bogus", "PYTHONIOENCODING": "utf-8"}
    argv = [sys.executable, "-m", "pyguibud.preview", "--ui-lang", lang, "--backend", "pyside6"]
    started = time.monotonic()
    done = subprocess.run(
        [*argv, "--", str(DEMO)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert time.monotonic() - started < 15 and done.returncode == 1
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["code"] == "runtime.no_display"
    try:
        set_language(lang)
        expected = _(_M_NO_PLUGIN).format(name="bogus", variable="QT_QPA_PLATFORM")
    finally:
        set_language("en_GB")
    assert expected in result["message"]


# QA-19d-09 (regression)
@pytest.mark.qt
@pytest.mark.skipif(sys.platform != "win32", reason="Qt's message-box hang is Windows only")
@pytest.mark.parametrize("value", ["   ", ";"])
def test_preview_child_with_a_blank_qt_platform_answers_promptly(
    tmp_path: Path, value: str
) -> None:
    pytest.importorskip("PySide6")
    env = {**os.environ, "QT_QPA_PLATFORM": value, "PYTHONIOENCODING": "utf-8"}
    found = _preview(tmp_path, env, "pyside6", 10)
    assert found.keys() & {"ready.json", "result.json"}, found
