"""QA abuse tests of Step 16c (PySide6 "Qt behaviour": variables, events, menus, QtHost).

Passing tests pin behaviour QA checked and found correct (spec backends §4.4, §5, §6 B1, B4,
B12, B13, QA-16a-12 warnings, the designer flows of the 16c UAT). The findings QA-16c-01..05
are fixed; their regression tests keep the QA-16c-NN id in their names. Marks are per test:
``qt`` only where PySide6 is imported in this process, ``gui`` where the Tk designer is built.
The cases that need a fresh interpreter (PySide6 blocked, the preview child) run in a
subprocess with a hard timeout.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.backends.pyside6 import display_problem
from pyguibud.designer import preview as pv
from pyguibud.preview import NoHandlers
from pyguibud_runtime import LoadedUi, load_ui
from tests.preview.test_child import DIALOGS_ONLY, MAIN_AND_DIALOG
from tests.runtime.conftest import write_ui

ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)
#: The platform plugins of a Windows PySide6 6.11 wheel (as ``_platform_plugins`` lists them).
WINDOWS_PLUGINS = ["qdirect2d.dll", "qminimal.dll", "qoffscreen.dll", "qwindows.dll"]
MARKUP = '<img src="file:///C:/Windows/win.ini"><a href="http://127.0.0.1:9/x">L</a><b>B</b> & [*]'
HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None
_BLOCKER = """
import sys
class _Blocker:
    @staticmethod
    def find_spec(name, path=None, target=None):
        if name.split(".")[0] in ("PySide6", "shiboken6"):
            raise ModuleNotFoundError(f"No module named {name!r}", name=name)
        return None
sys.meta_path.insert(0, _Blocker)
"""


# ------------------------------------------------------------------ fixtures and helpers
@pytest.fixture(scope="module")
def qapp() -> Any:
    """The test process's ``QApplication`` (offscreen when this module creates it)."""
    pytest.importorskip("PySide6")
    from PySide6 import QtWidgets

    made = QtWidgets.QApplication.instance()
    if made is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        made = QtWidgets.QApplication(["pyguibud-qa16c"])
    return made


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test and destroys them afterwards."""
    from PySide6 import QtCore

    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _load(path: Path, uis: list[LoadedUi], handlers: object = None) -> LoadedUi:
    ui = load_ui(path, handlers, strict=handlers is not None, backend="pyside6")
    uis.append(ui)
    return ui


def _main(body: str) -> str:
    return f'<window id="main" kind="main"><layout type="pack"/>{body}</window>'


# ------------------------------------------------------------------ QA-16c-01: D8 guard
@pytest.mark.parametrize(
    "value", ["win", "window", "off", "d", "direct", "off;dir", "direct2", "windowsd"]
)
def test_qa16c_01_a_prefix_of_an_installed_plugin_is_refused(value: str) -> None:
    reason = display_problem("win32", {"QT_QPA_PLATFORM": value}, WINDOWS_PLUGINS)
    assert reason is not None and value in reason


@pytest.mark.parametrize(
    ("platform", "environ", "plugins"),
    [
        ("win32", {"QT_QPA_PLATFORM": "windows"}, WINDOWS_PLUGINS),
        ("win32", {"QT_QPA_PLATFORM": "OFFSCREEN"}, WINDOWS_PLUGINS),  # Qt matches keys caselessly
        ("win32", {"QT_QPA_PLATFORM": "windows:darkmode=2"}, WINDOWS_PLUGINS),
        ("win32", {"QT_QPA_PLATFORM": "bogus;offscreen"}, WINDOWS_PLUGINS),  # Qt tries in turn
        ("win32", {"QT_QPA_PLATFORM": "off;windows"}, WINDOWS_PLUGINS),
        ("win32", {"QT_QPA_PLATFORM": "minimal"}, WINDOWS_PLUGINS),
        ("win32", {"QT_QPA_PLATFORM": "windows"}, ["qwindowsd.dll"]),  # a debug build
        ("linux", {"QT_QPA_PLATFORM": "xcb", "DISPLAY": ":0"}, ["libqxcb.so"]),
        ("linux", {"QT_QPA_PLATFORM": "wayland", "WAYLAND_DISPLAY": "w"}, ["libqwayland.so"]),
        ("linux", {"QT_QPA_PLATFORM": "wayland", "WAYLAND_DISPLAY": "w"}, ["libqwayland-egl.so"]),
        ("win32", {"QT_QPA_PLATFORM": "direct2d"}, ["qdirect2dd.dll", "qminimald.dll"]),
        ("win32", {"QT_QPA_PLATFORM": "windows"}, ["qwindows.dll", "qwindowsd.dll"]),  # an SDK
        ("darwin", {"QT_QPA_PLATFORM": "cocoa"}, ["libqcocoa.dylib"]),
        ("win32", {"QT_QPA_PLATFORM": "bogus"}, []),  # an unreadable folder never refuses
    ],
)
def test_installed_platform_plugins_stay_accepted(
    platform: str, environ: dict[str, str], plugins: list[str]
) -> None:
    """The fix of QA-16c-01 must keep these (Linux ``lib`` prefix, ``.so``/``.dll``, options)."""
    assert display_problem(platform, environ, plugins) is None


def test_a_bogus_or_huge_platform_value_is_refused_with_a_short_reason() -> None:
    reason = display_problem("win32", {"QT_QPA_PLATFORM": "bogus"}, WINDOWS_PLUGINS)
    assert reason == "The Qt platform plugin 'bogus' (QT_QPA_PLATFORM) is not installed."
    huge = display_problem("win32", {"QT_QPA_PLATFORM": "z" * 10_000}, WINDOWS_PLUGINS)
    assert huge is not None and len(huge) < 200


# ------------------------------------------------------------------ ready.json warnings
@pytest.mark.parametrize(
    "items",
    [
        [{"message": "\ud800 lone surrogate"}],
        [{"message": "a\nb\r\n\tc"}],
        [{"message": "nul\x00here"}],
        [{"message": "x" * 60_000}],
        [{"message": ["nested"]}, {"message": {"a": 1}}, {"message": None}, None, 7, "text"],
        [{"message": f"W{i}."} for i in range(500)],
    ],
    ids=["surrogate", "newlines", "nul", "60k", "wrong-types", "500"],
)
def test_malformed_warnings_are_read_as_at_most_twenty_strings(
    tmp_path: Path, items: list[object]
) -> None:
    path = tmp_path / "ready.json"
    path.write_text(json.dumps({"themes": [], "warnings": items}), "utf-8")
    found = pv.read_warnings(path)
    assert len(found) <= 20 and all(isinstance(m, str) and m for m in found)
    note = pv.warning_note(found)
    assert isinstance(note, str)


def test_a_ready_json_over_the_size_limit_or_not_utf8_gives_no_warnings(tmp_path: Path) -> None:
    path = tmp_path / "ready.json"
    path.write_bytes(b'{"themes": [], "warnings": [{"message": "' + b"x" * 70_000 + b'"}]}')
    assert pv.read_warnings(path) == []
    path.write_bytes(b'{"themes": [], "warnings": [{"message": "\xff\xfe"}]}')
    assert pv.read_warnings(path) == []


def test_qa16c_04_the_largest_ready_json_the_child_writes_is_readable(tmp_path: Path) -> None:
    import logging

    from pyguibud.preview import READY, _Collect, _write

    collect = _Collect()
    logger = logging.getLogger("tests.qa16c.collect")
    logger.addHandler(collect)
    logger.propagate = False
    try:
        for _ in range(25):  # e.g. long non-ASCII image paths or ids in an en_XA/CJK message
            logger.warning("é" * 3000)
    finally:
        logger.removeHandler(collect)
    warnings = [{"code": "runtime", "message": m} for m in collect.messages]
    _write(tmp_path / READY, {"themes": [], "theme": "", "warnings": warnings, "pid": 1})
    assert pv.read_ready(tmp_path / READY) == []
    assert (tmp_path / READY).stat().st_size < pv._MAX_RESULT


def test_the_child_warning_budget_leaves_room_under_the_designer_limit() -> None:
    from pyguibud.preview import _MAX_MESSAGE, _MAX_WARNING_BYTES

    assert 12 * _MAX_MESSAGE + 2 <= _MAX_WARNING_BYTES <= pv._MAX_RESULT - 16 * 1024


def test_new_status_texts_keep_their_placeholders_in_every_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Restore the language afterwards: later tests match English texts (en_XA leaked before).
    monkeypatch.setattr(i18n, "_translation", i18n._translation)
    monkeypatch.setattr(i18n, "_language", i18n._language)
    for lang in ("en_GB", "es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR", "en_XA"):
        i18n.set_language(lang)
        note = pv.warning_note(["W1.", "W2.", "W3."])
        assert "W1." in note and "2" in note, (lang, note)
        reason = display_problem("win32", {"QT_QPA_PLATFORM": "bogus"}, WINDOWS_PLUGINS)
        assert reason is not None and "'bogus'" in reason, (lang, reason)


# ------------------------------------------------------------------ B1: the child without PySide6
def test_b1_the_preview_child_without_pyside6_reports_backend_unavailable(
    tmp_path: Path,
) -> None:
    code = _BLOCKER + textwrap.dedent(
        f"""
        import runpy
        sys.argv = ["pyguibud.preview", "--ui-lang", "de_DE", "--backend", "pyside6", "--",
                    {str(HELLO)!r}]
        runpy.run_module("pyguibud.preview", run_name="__main__")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=tmp_path,
        env=ENV,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    data = json.loads((tmp_path / "result.json").read_text("utf-8"))
    assert data["code"] == "runtime.backend_unavailable"
    assert 'pip install "pyguibud[pyside]"' in data["message"]
    assert "Traceback" not in result.stderr and not (tmp_path / "ready.json").exists()


# ------------------------------------------------------------------ the Qt child (subprocess)
@pytest.mark.qt
@pytest.mark.skipif(not HAS_PYSIDE6, reason="needs PySide6")
def test_a_storm_of_language_and_garbage_commands_keeps_the_qt_child_alive(tmp_path: Path) -> None:
    commands = [
        "lang de_DE", "lang en_XA", "lang -", "lang ../../x", "lang " + "a" * 300, "raise",
        "bogus", "lang de_DE extra", "\x00\x7f", "lang fr_FR",
    ] * 30 + ["quit"]  # fmt: skip
    result = subprocess.run(
        [sys.executable, "-m", "pyguibud.preview", "--backend", "pyside6",
         "--localedir", str(HELLO.parent / "locale"), "--", str(HELLO)],
        input="\n".join(commands) + "\n",
        capture_output=True, text=True, encoding="utf-8", timeout=60, cwd=tmp_path, env=ENV,
        check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr
    assert json.loads((tmp_path / "result.json").read_text("utf-8"))["code"] == "ok"
    assert "Traceback" not in result.stderr


# ------------------------------------------------------------------ QA-16c-02: Esc in a dialog
@pytest.mark.qt
@pytest.mark.parametrize(
    ("windows", "has_main", "main", "window"),
    [(DIALOGS_ONLY, False, None, None), (MAIN_AND_DIALOG, True, "main", "dlg")],
    ids=["dialogs-only", "main-and-dialog-window-dlg"],
)
def test_qa16c_02_esc_in_a_previewed_dialog_is_ignored(
    qapp: Any, tmp_path: Path, windows: str, has_main: bool, main: str | None, window: str | None
) -> None:
    from PySide6 import QtCore
    from PySide6.QtTest import QTest

    from pyguibud.preview._host_qt import QtHost

    host, closed = QtHost(), []
    try:
        master = host.prepare(has_main, "")
        ui = load_ui(
            write_ui(tmp_path / "d.ui", windows), NoHandlers(), strict=False,
            backend="pyside6", master=master,
        )  # fmt: skip
        host.attach(ui, main, window, lambda: closed.append(True))
        host.update()
        shown = [key for key in ui.windows if getattr(ui, key).isVisible()]
        assert len(shown) == 1
        QTest.keyClick(getattr(ui, shown[0]), QtCore.Qt.Key.Key_Escape)
        for _ in range(3):
            QtCore.QCoreApplication.processEvents()
        assert closed == [] and getattr(ui, shown[0]).isVisible()  # ruling: Tk parity
        getattr(ui, shown[0]).close()  # the title-bar X still closes it and ends the preview
        for _ in range(3):
            QtCore.QCoreApplication.processEvents()
        assert closed == [True] and not getattr(ui, shown[0]).isVisible()
    finally:
        host.close()


@pytest.mark.qt
def test_qa16c_02_a_key_escape_handler_inside_a_dialog_still_fires(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    seen: list[str] = []
    windows = (
        _main("")
        + '<window id="dlg" kind="dialog"><layout type="pack"/><widget class="Entry" id="ent">'
        '<event name="key:&lt;Escape&gt;" handler="esc"/><pack/></widget></window>'
    )
    ui = _load(write_ui(tmp_path / "esc.ui", windows), loaded, {"esc": lambda: seen.append("e")})
    ui.dlg.show()
    QTest.keyClick(ui.ent, Qt.Key.Key_Escape)
    assert seen == ["e"] and ui.dlg.isVisible()
    QTest.keyClick(ui.ent, Qt.Key.Key_A)  # other keys still reach the dialog's widgets
    assert ui.ent.text() == "a"


@pytest.mark.qt
# QA-16c-06 (fixed): Enter in a Qt dialog clicked the first auto-default QPushButton.
@pytest.mark.parametrize("activate", [False, True], ids=["plain-entry", "entry-with-activate"])
def test_qa16c_06_enter_in_a_dialog_fires_no_button(
    tmp_path: Path, loaded: list[LoadedUi], activate: bool
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    seen: list[str] = []
    event = '<event name="activate" handler="act"/>' if activate else ""
    windows = _main("") + (
        f'<window id="dlg" kind="dialog"><layout type="pack"/>'
        f'<widget class="Entry" id="ent">{event}<pack/></widget>'
        '<widget class="Button" id="bdel"><prop name="text">Delete all</prop>'
        '<event name="command" handler="delete"/><pack/></widget>'
        '<widget class="Checkbutton" id="chk"><prop name="text">C</prop><pack/></widget></window>'
    )
    handlers = {name: (lambda n=name: seen.append(n)) for name in ("act", "delete")}
    ui = _load(write_ui(tmp_path / "enter.ui", windows), loaded, handlers)
    ui.show("dlg")
    QTest.keyClick(ui.ent, Qt.Key.Key_Return)
    QTest.keyClick(ui.chk, Qt.Key.Key_Return)
    assert "delete" not in seen and seen == (["act"] if activate else [])


# ------------------------------------------------------------------ variables (B4, B12, B13)
_VARIABLES = (
    '<var id="s" type="string"/><var id="n" type="int" default="5"/>'
    '<var id="d" type="double" default="5"/>'
)


@pytest.mark.qt
def test_b4_a_bound_label_entry_and_combobox_show_markup_literally(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    from PySide6.QtCore import Qt

    body = (
        '<widget class="Label" id="lbl" bind="s"><pack/></widget>'
        '<widget class="Entry" id="ent" bind="s"><pack/></widget>'
        '<widget class="Combobox" id="cmb" bind="s"><pack/></widget>'
    )
    ui = _load(write_ui(tmp_path / "b4.ui", _main(body), variables=_VARIABLES), loaded)
    ui.vars.s.set(MARKUP)
    assert ui.lbl.textFormat() == Qt.TextFormat.PlainText
    assert ui.lbl.text() == ui.ent.text() == ui.cmb.currentText() == MARKUP


@pytest.mark.qt
@pytest.mark.parametrize(
    ("typed", "n", "d"),
    [
        ("abc", 5, 5.0),
        ("", 5, 5.0),
        ("inf", 5, float("inf")),
        ("-inf", 5, float("-inf")),
        ("1e400", 5, float("inf")),
        ("  12 ", 12, 12.0),
        ("3.7", 3, 3.7),
    ],
    ids=["abc", "empty", "inf", "-inf", "1e400", "spaces", "3.7"],
)
def test_b12_typing_extreme_values_into_int_and_double_entries(
    tmp_path: Path, loaded: list[LoadedUi], typed: str, n: int, d: object
) -> None:
    body = (
        '<widget class="Entry" id="en" bind="n"><pack/></widget>'
        '<widget class="Entry" id="ed" bind="d"><pack/></widget>'
        '<widget class="Scale" id="sc" bind="d"><prop name="maximum">10</prop><pack/></widget>'
        '<widget class="Spinbox" id="sp" bind="n"><prop name="maximum">10</prop><pack/></widget>'
        '<widget class="Progressbar" id="pb" bind="d"><prop name="maximum">10</prop>'
        "<pack/></widget>"
    )
    ui = _load(write_ui(tmp_path / "b12.ui", _main(body), variables=_VARIABLES), loaded)
    ui.en.setText(typed)
    ui.ed.setText(typed)
    assert ui.vars.n.get() == n
    value = ui.vars.d.get()
    assert value == d
    assert 0 <= ui.sc.value() <= 10 and 0 <= ui.pb.value() <= 10  # the widgets stay in range


@pytest.mark.parametrize(
    ("cls", "text", "tk"),
    [
        ("IntVar", "0x10", 16),
        ("DoubleVar", "0x10", 16.0),
        ("IntVar", "1_000", None),
        ("DoubleVar", "nan", None),
        ("IntVar", "9" * 400, int("9" * 400)),
    ],
    ids=["int-hex", "double-hex", "int-underscore", "double-nan", "int-400-nines"],
)
def test_qa16c_05_text_converts_as_tkinter_get_does(cls: str, text: str, tk: object) -> None:
    from pyguibud.backends import _vars

    var = getattr(_vars, cls)(5)
    try:
        var.set(text)
    except (ValueError, TypeError, OverflowError):
        got: object = None  # Tk: get() raises, so the binding keeps the last value (B12)
    else:
        got = var.get()
    assert got == tk


@pytest.mark.qt
@pytest.mark.parametrize(
    ("low", "high"), [("100", "0"), ("5", "5"), ("0", "100")], ids=["inverted", "zero", "plain"]
)
def test_b13_bound_ranges_survive_extreme_variable_values(
    tmp_path: Path, loaded: list[LoadedUi], low: str, high: str
) -> None:
    def ranged(cls: str, wid: str, var: str) -> str:
        return (
            f'<widget class="{cls}" id="{wid}" bind="{var}"><prop name="minimum">{low}</prop>'
            f'<prop name="maximum">{high}</prop><pack/></widget>'
        )

    body = ranged("Scale", "sc", "d") + ranged("Spinbox", "sp", "n") + ranged("Spinbox", "ss", "s")
    ui = _load(write_ui(tmp_path / "b13.ui", _main(body), variables=_VARIABLES), loaded)
    for value in (50, 1e9, -1e9, float("nan"), float("inf"), 2**40, "abc"):
        for var in (ui.vars.d, ui.vars.n, ui.vars.s):
            with contextlib.suppress(ValueError, TypeError, OverflowError):
                var.set(value)  # documented: a value that does not convert changes nothing
    for widget in (ui.sc, ui.sp, ui.ss):
        assert widget.minimum() <= widget.value() <= widget.maximum()


@pytest.mark.qt
@pytest.mark.parametrize("cls", ["Entry", "Combobox"])
def test_qa16c_03_editing_a_long_bound_entry_keeps_the_variable_text(
    tmp_path: Path, loaded: list[LoadedUi], cls: str
) -> None:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    body = f'<widget class="{cls}" id="ent" bind="s"><pack/></widget>'
    ui = _load(write_ui(tmp_path / "long.ui", _main(body), variables=_VARIABLES), loaded)
    ui.vars.s.set("y" * 40_000)
    line = ui.ent if cls == "Entry" else ui.ent.lineEdit()
    line.end(False)
    QTest.keyClick(line, Qt.Key.Key_Backspace)
    assert len(ui.vars.s.get()) == 39_999


# ------------------------------------------------------------------ handler exceptions (D15)
@pytest.mark.qt
def test_a_raising_key_handler_keeps_the_loop_and_the_other_filters(
    tmp_path: Path, loaded: list[LoadedUi], qapp: Any, capfd: pytest.CaptureFixture[str]
) -> None:
    from PySide6 import QtCore, QtGui, QtWidgets
    from PySide6.QtCore import Qt

    seen: list[str] = []

    def kraise() -> None:
        seen.append("kraise")
        raise ValueError("boom")

    body = (
        '<widget class="Entry" id="en"><event name="key:&lt;Return&gt;" handler="kraise"/>'
        '<event name="key:&lt;Escape&gt;" handler="kok"/>'
        '<event name="focus_out" handler="fout"/><pack/></widget>'
        '<widget class="Button" id="bt"><prop name="text">B</prop>'
        '<event name="command" handler="click"/><pack/></widget>'
    )
    handlers = {
        "kraise": kraise,
        "kok": lambda: seen.append("kok"),
        "fout": lambda: seen.append("fout"),
        "click": lambda: seen.append("click"),
    }
    ui = _load(write_ui(tmp_path / "keys.ui", _main(body)), loaded, handlers)
    key_types = (QtCore.QEvent.Type.KeyPress, QtCore.QEvent.Type.KeyRelease)

    def key(code: Any) -> None:
        for kind in key_types:
            QtWidgets.QApplication.postEvent(
                ui.en, QtGui.QKeyEvent(kind, code, Qt.KeyboardModifier.NoModifier)
            )

    later = QtCore.QTimer.singleShot
    later(0, lambda: key(Qt.Key.Key_Return))
    later(10, lambda: key(Qt.Key.Key_Escape))
    later(20, lambda: key(Qt.Key.Key_Return))
    focus_out = QtGui.QFocusEvent(QtCore.QEvent.Type.FocusOut)
    later(30, lambda: QtWidgets.QApplication.postEvent(ui.en, focus_out))
    later(40, ui.bt.click)
    later(120, qapp.quit)
    ui.run()
    assert seen.count("kraise") == 2 and seen.count("kok") == 1  # every key event still filtered
    assert "fout" in seen and seen.count("click") == 1
    assert capfd.readouterr().err.count("boom") >= 2
