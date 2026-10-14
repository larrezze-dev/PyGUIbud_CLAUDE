"""QA abuse tests of Step 16b (PySide6 "Qt build", ``examples/show_ui.py --backend pyside6``).

Passing tests pin behaviour QA checked and found correct (spec backends §6 B1, B4-B7, B13, CLI
refusals, every locale). Open findings are strict xfails named after their QA-16b-NN id. The
in-process cases run offscreen on the one ``QApplication`` of the test process; the cases that
need a fresh interpreter (PySide6 blocked, the CLI) run in a subprocess.
"""

from __future__ import annotations

import gc
import importlib.util
import json
import logging
import os
import subprocess
import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pyguibud.backends.pyside6 import display_problem
from pyguibud.core.validate import MAX_TEXT_LENGTH
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import clean_i18n, write_ui  # noqa: F401 - autouse: i18n, registry

pytestmark = pytest.mark.qt

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
SHOW_UI = EXAMPLES / "show_ui.py"
DIALOGS = ROOT / "tests" / "codegen" / "data" / "dialogs.ui"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)
LOCALES = ("en_GB", "es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR", "en_XA")
#: Rich text Qt would interpret if any slot were not plain: a local file, a link, bold, ``&``
#: and Qt's window-modified marker.
MARKUP = '<img src="file:///C:/Windows/win.ini"><a href="http://127.0.0.1:9/x">L</a><b>B</b> & [*]'
#: Makes PySide6 and shiboken6 unimportable in a fresh interpreter (spec B1).
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

    app = QtWidgets.QApplication.instance()
    if app is None:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        app = QtWidgets.QApplication(["pyguibud-qa"])
    return app


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test and destroys them afterwards."""
    from PySide6 import QtCore

    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _load(path: Path, uis: list[LoadedUi], **options: Any) -> LoadedUi:
    ui = load_ui(path, None, strict=False, backend="pyside6", **options)
    uis.append(ui)
    return ui


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in caplog.records]


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _every_slot() -> str:
    """A main window with a translatable text in every kind of slot the Qt session owns; the
    texts are the one-letter keys of :data:`_SLOTS`, replaced by the tests."""

    def text(key: str) -> str:
        return f'<prop name="text" translatable="true">{key}</prop>'

    return f"""<window id="main" kind="main"><prop name="title" translatable="true">T</prop>
  <menubar><menu id="mn">{text("M")}<action id="ac">{text("A")}</action>
    <menu id="sub">{text("S")}</menu></menu></menubar>
  <statusbar id="st">{text("B")}</statusbar>
  <layout type="pack"/>
  <widget class="Label" id="lb">{text("L")}<pack/></widget>
  <widget class="Button" id="bt">{text("U")}<pack/></widget>
  <widget class="Checkbutton" id="ck">{text("C")}<pack/></widget>
  <widget class="Radiobutton" id="rb">{text("R")}<pack/></widget>
  <widget class="LabelFrame" id="gp">{text("G")}<layout type="pack"/><pack/></widget>
  <widget class="Notebook" id="nb"><pack/>
    <widget class="Frame" id="pg"><page>{text("P")}</page><layout type="pack"/></widget>
  </widget></window>"""


def _with_texts(texts: dict[str, str]) -> str:
    body = _every_slot()
    for key, value in texts.items():
        body = body.replace(f">{key}<", f">{value}<", 1)
    return body


_SLOTS = ("T", "M", "A", "S", "B", "L", "U", "C", "R", "G", "P")


def _slot_texts(ui: LoadedUi) -> dict[str, str]:
    """What Qt shows in every slot: ``&&`` is a literal ``&`` and ``[*][*]`` a literal ``[*]``."""
    raw = {
        "T": ui.main.windowTitle().replace("[*][*]", "[*]"),
        "M": ui.mn.title(),
        "A": ui.ac.text(),
        "S": ui.sub.title(),
        "B": ui.st.text(),
        "L": ui.lb.text(),
        "U": ui.bt.text(),
        "C": ui.ck.text(),
        "R": ui.rb.text(),
        "G": ui.gp.title(),
        "P": ui.nb.tabText(0),
    }
    plain = {"T", "B", "L"}  # PlainText / verbatim: no mnemonic escaping
    return {k: v if k in plain else v.replace("&&", "&") for k, v in raw.items()}


def _write_mo(folder: Path, domain: str, lang: str, messages: dict[str, str]) -> None:
    from babel.messages.catalog import Catalog
    from babel.messages.mofile import write_mo

    catalog = Catalog(locale=lang, domain=domain)
    for msgid, msgstr in messages.items():
        catalog.add(msgid, msgstr)
    target = folder / "locale" / lang / "LC_MESSAGES"
    target.mkdir(parents=True)
    with (target / f"{domain}.mo").open("wb") as stream:
        write_mo(stream, catalog)


def _show_ui_module() -> ModuleType:
    """A fresh copy of ``examples/show_ui.py`` (its module-level Qt loop list starts empty)."""
    spec = importlib.util.spec_from_file_location("qa16b_show_ui", SHOW_UI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(args: list[str], *, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
        cwd=ROOT, env=ENV,
    )  # fmt: skip


# ------------------------------------------------------------------ B1: PySide6 missing
def test_b1_without_pyside6_every_entry_refuses_with_the_install_hint() -> None:
    code = _BLOCKER + textwrap.dedent(
        f"""
        import json, runpy, contextlib, io
        from pyguibud_runtime import UiError, load_ui
        from pyguibud.designer import preview
        out = {{"installed": preview.toolkit_installed("pyside6"),
               "tkinter": preview.toolkit_installed("tkinter")}}
        try:
            load_ui({str(EXAMPLES / "hello.ui")!r}, None, strict=False, backend="pyside6")
        except UiError as exc:
            out["runtime"] = [exc.code, str(exc)]
        for key, path in (("main", {str(EXAMPLES / "hello.ui")!r}), ("dialogs", {str(DIALOGS)!r})):
            sys.argv = ["show_ui.py", path, "--backend", "pyside6"]
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                try:
                    runpy.run_path({str(SHOW_UI)!r}, run_name="__main__")
                except SystemExit as exc:
                    out[key] = [exc.code, err.getvalue()]
        print(json.dumps(out))
        """
    )
    result = _run([sys.executable, "-c", code])
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    hint = 'pip install "pyguibud[pyside]"'
    assert out["installed"] is False and out["tkinter"] is True
    assert out["runtime"][0] == "runtime.backend_unavailable" and hint in out["runtime"][1]
    for key in ("main", "dialogs"):
        code_, stderr = out[key]
        assert code_ == 1 and hint in stderr and "Traceback" not in stderr
        assert len(stderr.strip().splitlines()) == 1, stderr


# ------------------------------------------------------------------ CLI refusals (one line)
@pytest.mark.parametrize(
    ("case", "extra"),
    [
        ("missing", []),
        ("folder", []),
        ("empty", []),
        ("binary", []),
        ("truncated", []),
        ("damaged-image", []),
        ("hello", ["--lang", ""]),
        ("hello", ["--lang", "../../etc"]),
        ("hello", ["--backend", "PySide6"]),
        ("hello", ["--backend", "pyside6; rm -rf"]),
        ("components-only", []),
    ],
)
def test_show_ui_pyside6_refusals_are_one_line_without_traceback(
    case: str, extra: list[str], tmp_path: Path
) -> None:
    files = {
        "missing": tmp_path / "nowhere.ui",
        "folder": tmp_path / "folder.ui",
        "empty": tmp_path / "empty.ui",
        "binary": tmp_path / "binary.ui",
        "truncated": tmp_path / "truncated.ui",
        "damaged-image": tmp_path / "ünï 😀" / "with_image.ui",
        "hello": EXAMPLES / "hello.ui",
        "components-only": EXAMPLES / "include" / "address_card.ui",
    }
    (tmp_path / "folder.ui").mkdir()
    (tmp_path / "empty.ui").write_bytes(b"")
    (tmp_path / "binary.ui").write_bytes(bytes(range(256)) * 8)
    (tmp_path / "truncated.ui").write_text("<pyguibud-ui", encoding="utf-8")
    damaged = files["damaged-image"].parent
    damaged.mkdir()
    (damaged / "with_image.ui").write_bytes((EXAMPLES / "preview" / "with_image.ui").read_bytes())
    png = (EXAMPLES / "preview" / "logo.png").read_bytes()
    (damaged / "logo.png").write_bytes(png[:40] + b"\0" * 200 + png[-12:])
    args = [sys.executable, str(SHOW_UI), str(files[case]), "--backend", "pyside6"]
    result = _run(args + extra, timeout=30)
    assert result.returncode == 1, result.stdout + result.stderr
    assert "Traceback" not in result.stderr and result.stderr.strip()


# ------------------------------------------------------------------ B4: never markup
@pytest.mark.parametrize("source", ["ui", "translation"])
def test_b4_markup_is_literal_in_every_slot(
    source: str, tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    keys = {k: f"Key {k}" for k in _SLOTS}
    texts = dict.fromkeys(_SLOTS, _escape(MARKUP)) if source == "ui" else keys
    path = write_ui(tmp_path / "markup.ui", _with_texts(texts), meta='i18n_domain="qa"')
    lang = None
    if source == "translation":
        _write_mo(tmp_path, "qa", "de_DE", {keys[k]: MARKUP for k in _SLOTS})
        lang = "de_DE"
    ui = _load(path, loaded, lang=lang)
    from PySide6.QtCore import Qt

    assert ui.lb.textFormat() == Qt.TextFormat.PlainText
    assert ui.st.textFormat() == Qt.TextFormat.PlainText
    assert _slot_texts(ui) == dict.fromkeys(_SLOTS, MARKUP)


# ------------------------------------------------------------------ B5: 200,000 characters
def test_b5_a_huge_translation_is_clipped_with_one_log_per_slot(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    keys = {k: f"Key {k}" for k in _SLOTS}
    path = write_ui(tmp_path / "huge.ui", _with_texts(keys), meta='i18n_domain="qa"')
    _write_mo(tmp_path, "qa", "de_DE", {keys[k]: "y" * 200_000 for k in _SLOTS})
    caplog.set_level(logging.INFO)
    ui = _load(path, loaded, lang="de_DE")
    clipped = [m for m in _messages(caplog) if "200000 characters" in m]
    assert len(clipped) == len(_SLOTS)
    assert {len(v) for v in _slot_texts(ui).values()} == {MAX_TEXT_LENGTH}
    caplog.clear()
    ui.retranslate("en_GB")
    ui.retranslate("de_DE")
    assert not [m for m in _messages(caplog) if "200000 characters" in m]  # logged once


# ------------------------------------------------------------------ B6, B7, B13
def test_b6_five_hundred_bootstyles_give_one_log(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    widgets = "".join(
        f'<widget class="Label" id="l{i}" tb:bootstyle="info"><prop name="text">x</prop>'
        "<pack/></widget>"
        for i in range(500)
    )
    path = write_ui(
        tmp_path / "b6.ui", f'<window id="main" kind="main"><layout type="pack"/>{widgets}</window>'
    )
    caplog.set_level(logging.INFO)
    _load(path, loaded)
    notes = [m for m in _messages(caplog) if "tb:bootstyle" in m]
    assert notes == ["500 ttkbootstrap styles (tb:bootstyle) are ignored by the pyside6 toolkit."]


@pytest.mark.parametrize(
    ("colour", "logged", "shown"),
    [
        ("SeaGreen3", True, None),
        ("gray57", True, None),
        ("#123", False, "#112233"),
        ("red", False, "#ff0000"),
    ],
)
def test_b7_tk_colours_qt_does_not_know_are_logged(
    colour: str, logged: bool, shown: str | None, tmp_path: Path, loaded: list[LoadedUi],
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    path = write_ui(
        tmp_path / "b7.ui",
        '<window id="main" kind="main"><layout type="pack"/><widget class="Canvas" id="cv">'
        f'<prop name="background">{colour}</prop><pack/></widget></window>',
    )
    caplog.set_level(logging.INFO)
    ui = _load(path, loaded)
    assert any(colour in m and "not known to Qt" in m for m in _messages(caplog)) is logged
    if shown is not None:
        assert ui.cv.backgroundBrush().color().name() == shown


@pytest.mark.parametrize(
    ("low", "high", "step"),
    [
        ("5", "1", "1"),
        ("0", "0", "0"),
        ("0.5", "0.5", "-1"),
        ("-999999999999999", "999999999999999", "0.000000000000001"),
        ("0.000000000000001", "0", "1"),
    ],
)
def test_b13_extreme_ranges_build_sorted_ranges(
    low: str, high: str, step: str, tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    def ranged(cls: str, wid: str, extra: str = "") -> str:
        return (
            f'<widget class="{cls}" id="{wid}"><prop name="minimum">{low}</prop>'
            f'<prop name="maximum">{high}</prop>{extra}<pack/></widget>'
        )

    path = write_ui(
        tmp_path / "b13.ui",
        '<window id="main" kind="main"><layout type="pack"/>'
        + ranged("Spinbox", "sp", f'<prop name="increment">{step}</prop>')
        + ranged("Scale", "sc")
        + ranged("Scale", "sv", '<prop name="orient">vertical</prop>')
        + f'<widget class="Progressbar" id="pb"><prop name="maximum">{high}</prop>'
        f'<prop name="value">{low}</prop><pack/></widget></window>',
    )
    ui = _load(path, loaded)
    assert ui.sp.minimum() <= ui.sp.maximum()
    for slider in (ui.sc, ui.sv, ui.pb):
        assert slider.minimum() <= slider.value() <= slider.maximum() or slider.maximum() == 0


# ------------------------------------------------------------------ master misuse
def test_a_wrong_or_deleted_master_is_refused_and_a_later_deletion_destroys(
    tmp_path: Path, loaded: list[LoadedUi], qapp: Any
) -> None:
    import shiboken6
    from PySide6 import QtCore, QtWidgets

    path = write_ui(
        tmp_path / "dlg.ui",
        '<window id="dlg" kind="dialog"><prop name="title">D</prop><layout type="pack"/></window>',
    )
    deleted = QtWidgets.QWidget()
    shiboken6.delete(deleted)
    for master in ("hello", object(), deleted):
        with pytest.raises(UiError) as caught:
            _load(path, loaded, master=master)
        assert caught.value.code == "runtime.backend_unavailable"
    master = QtWidgets.QWidget()
    ui = _load(path, loaded, master=master)
    master.deleteLater()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    with pytest.raises(UiError) as caught:
        ui.show("dlg")
    assert caught.value.code == "runtime.destroyed"


# ------------------------------------------------------------------ every locale via show_ui
@pytest.mark.parametrize("lang", LOCALES)
def test_show_ui_loads_hello_and_dialogs_in_every_locale(lang: str, qapp: Any) -> None:
    from PySide6 import QtCore

    show_ui = _show_ui_module()
    ui = show_ui.load(str(EXAMPLES / "hello.ui"), "pyside6", lang)
    try:
        title, menu, quit_ = ui.main.windowTitle(), ui.mnu_file.title(), ui.act_quit.text()
    finally:
        ui.destroy()
    expected = {"de_DE": ("Hallo PyGUIbud", "&Datei", "&Beenden")}
    if lang == "en_XA":
        assert title.startswith("[") and menu.startswith("[&") and quit_.startswith("[&")
    else:
        assert (title, menu, quit_) == expected.get(lang, ("Hello PyGUIbud", "&File", "&Quit"))
    dialogs = show_ui.load(str(DIALOGS), "pyside6", lang)
    try:
        assert all(window.isVisible() for window in dialogs.windows.values())
        assert len(dialogs.windows) == 2
    finally:
        dialogs.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


# ------------------------------------------------------------------ open findings
# QA-16b-01 (fixed in 16c): Qt aborts instead of raising, so the D8 guard refuses these first.
@pytest.mark.parametrize(
    ("environ"),
    [{"QT_QPA_PLATFORM": "xcb"}, {"QT_QPA_PLATFORM": "wayland"}],
    ids=["xcb-without-DISPLAY", "wayland-without-WAYLAND_DISPLAY"],
)
def test_qa16b_01_a_platform_without_its_display_is_refused(environ: dict[str, str]) -> None:
    assert display_problem("linux", environ) is not None


@pytest.mark.parametrize(
    "environ",
    [{"QT_QPA_PLATFORM": "offscreen"}, {"DISPLAY": ":0"}, {"WAYLAND_DISPLAY": "wayland-0"}],
)
def test_qa16b_01_working_linux_setups_stay_accepted(environ: dict[str, str]) -> None:
    assert display_problem("linux", environ) is None


def test_qa16b_03_windows_outlive_a_dropped_loaded_ui(qapp: Any) -> None:
    from PySide6 import QtWidgets

    def make() -> None:
        load_ui(EXAMPLES / "hello.ui", None, strict=False, backend="pyside6")

    make()
    gc.collect()
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    try:
        assert any(w.windowTitle() == "Hello PyGUIbud" for w in shown)
    finally:
        for widget in shown:
            widget.close()
        qapp.processEvents()  # the deferred destroy() releases the session


def test_qa16b_02_a_backend_without_a_preview_host_reads_as_one_sentence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.preview import _host

    # 16c ships QtHost; without the built-in entry the backend itself has no preview_host.
    monkeypatch.delitem(_host.HOSTS, "pyside6")
    with pytest.raises(UiError) as caught:
        _host.host_for("pyside6")
    assert caught.value.code == "runtime.backend_unavailable"
    assert str(caught.value) == (
        "The backend 'pyside6' is not available: it has no preview host, so it cannot be previewed."
    )
