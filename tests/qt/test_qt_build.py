"""Smoke tests of the PySide6 build (Step 16b): every class, layouts, texts, session life."""

from __future__ import annotations

import logging
import shutil
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from pyguibud.backends._qt import QtSession
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.qt

DATA = Path(__file__).resolve().parents[1] / "codegen" / "data"
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
PPM = b"P6\n1 1\n255\n\x00\x00\x00"


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test and destroys them afterwards."""
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _load(path: Path, uis: list[LoadedUi], **options: Any) -> LoadedUi:
    ui = load_ui(path, None, strict=False, backend="pyside6", **options)
    uis.append(ui)
    return ui


def test_hello_builds(loaded: list[LoadedUi]) -> None:
    ui = _load(EXAMPLES / "hello.ui", loaded)
    assert isinstance(ui.main, QtWidgets.QMainWindow) and ui.main.isVisible()
    assert ui.main.windowTitle() == "Hello PyGUIbud"
    assert ui.main.minimumSize() == QtCore.QSize(480, 320)
    assert ui.mnu_file.title() == "&File" and ui.act_quit.text() == "&Quit"
    assert ui.main.menuBar().actions()[0].menu() is ui.mnu_file
    assert ui.sts_main.text() == "Ready" and ui.sts_main.textFormat() == Qt.TextFormat.PlainText
    assert ui.main.statusBar() is ui.sts_main.parentWidget()
    assert isinstance(ui.nbk_main, QtWidgets.QTabWidget) and ui.nbk_main.count() == 2
    assert [ui.nbk_main.tabText(i) for i in range(2)] == ["Greeting", "About"]
    assert isinstance(ui.ent_name, QtWidgets.QLineEdit) and ui.ent_name.text() == ""
    assert ui.btn_greet.text() == "Say hello"
    ui.retranslate("de_DE")  # the example's own catalogue
    assert ui.btn_greet.text() == "Hallo sagen"


def test_closing_the_main_window_ends_the_session(loaded: list[LoadedUi], qapp: Any) -> None:
    ui = _load(EXAMPLES / "hello.ui", loaded)
    main = ui.main
    main.close()
    qapp.processEvents()
    with pytest.raises(UiError) as caught:
        ui.show("main")
    assert caught.value.code == "runtime.destroyed"
    ui.destroy()
    ui.destroy()  # idempotent


def test_every_class_of_the_rich_fixture_builds(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    shutil.copy(DATA / "rich.ui", tmp_path / "rich.ui")
    (tmp_path / "pic.gif").write_bytes(GIF)
    (tmp_path / "pic.ppm").write_bytes(PPM)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path / "rich.ui", loaded)
    messages = "\n".join(r.getMessage() for r in caplog.records)
    expected = {
        "nbk": QtWidgets.QTabWidget,
        "frm": QtWidgets.QFrame,
        "lbl": QtWidgets.QLabel,
        "btn": QtWidgets.QPushButton,
        "ent": QtWidgets.QLineEdit,
        "chk": QtWidgets.QCheckBox,
        "rad": QtWidgets.QRadioButton,
        "cmb": QtWidgets.QComboBox,
        "spn": QtWidgets.QDoubleSpinBox,
        "scl": QtWidgets.QSlider,
        "prg": QtWidgets.QProgressBar,
        "mtr": QtWidgets.QProgressBar,  # tb:Meter shown as its fallback
        "txt": QtWidgets.QPlainTextEdit,
        "lst": QtWidgets.QListWidget,
        "tree": QtWidgets.QTreeWidget,
        "sbr": QtWidgets.QScrollBar,
        "cnv": QtWidgets.QGraphicsView,
        "sep": QtWidgets.QFrame,
        "lfr": QtWidgets.QGroupBox,
        "pnd": QtWidgets.QSplitter,
        "mnu": QtWidgets.QMenu,
        "act_a": QtGui.QAction,
        "dlg": QtWidgets.QDialog,
        "main": QtWidgets.QMainWindow,
    }
    for name, cls in expected.items():
        assert isinstance(getattr(ui, name), cls), name
    assert isinstance(ui.scf.parentWidget().parentWidget(), QtWidgets.QScrollArea)
    assert "tb:Meter" in messages and "4 ttkbootstrap styles" in messages
    assert "image and a text" in messages  # trim T5: lbl shows its image only
    assert ui.lbl.pixmap() is not None and not ui.lbl.pixmap().isNull()
    assert ui.btn.text() == "&Go" and not ui.btn.isEnabled()
    assert ui.nbk.tabText(0) == "&Alpha" and not ui.nbk.tabIcon(0).isNull()
    assert not ui.act_a.isEnabled() and not ui.act_a.icon().isNull()
    assert ui.mnu_sub.title() == "&More"
    assert ui.spn.maximum() == 5.0 and ui.spn.decimals() == 0
    assert ui.tree.rootIsDecorated() is False and not ui.tree.isHeaderHidden()
    assert ui.sts.text() == "Status" and ui.lbl_bound.text() == "Bo"  # its variable (16c)
    assert ui.dlg.windowTitle() == "Dialog" and not ui.dlg.isVisible()
    assert ui.dl.pixmap() is not None and not ui.dl.pixmap().isNull()  # PPM decoded
    assert ui.pnd.count() == 2 and ui.inc.part.parentWidget() is ui.scf
    assert ui.main.minimumWidth() == 200
    assert ui.vars.name.get() == "Bo" and ui.vars.choice.get() == 2  # Step 16c
    assert ui.show("dlg") is None and ui.dlg.isVisible() and ui.dlg.isWindow()
    ui.dlg.close()
    assert not ui.dlg.isVisible() and ui.main.isVisible()  # closing a dialog only hides it


def test_dialogs_only_build_on_a_hidden_master(loaded: list[LoadedUi]) -> None:
    master = QtWidgets.QWidget()
    try:
        ui = _load(DATA / "dialogs.ui", loaded, master=master)
        assert set(ui.windows) == {"dlg_about", "dlg_ask"}
        assert ui.dlg_about.windowTitle() == "About" and ui.dlg_about.parentWidget() is master
        assert ui.lbl_about.text() == "Dialogs only."
        ui.show("dlg_ask")
        assert ui.dlg_ask.isVisible() and not master.isVisible()
    finally:
        loaded.pop().destroy()
        master.deleteLater()


def test_texts_are_never_markup_and_ampersands_stay_literal(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(
        tmp_path / "texts.ui",
        '<window id="main"><prop name="title">Doc [*] &amp; co</prop><layout type="pack"/>'
        '<widget class="Label" id="lbl"><prop name="text">&lt;img src="file:///x"&gt;'
        "&lt;b&gt;bold&lt;/b&gt; &amp; _x</prop><pack/></widget>"
        '<widget class="Button" id="btn"><prop name="text">Save &amp; _quit</prop>'
        '<pack padx="4"/></widget>'
        '<widget class="LabelFrame" id="grp"><prop name="text">A &amp; _B</prop>'
        '<layout type="grid"/><pack/></widget></window>',
    )
    ui = _load(path, loaded)
    assert ui.lbl.text() == '<img src="file:///x"><b>bold</b> & _x'
    assert ui.lbl.textFormat() == Qt.TextFormat.PlainText
    assert ui.btn.text() == "Save && &quit"
    assert ui.grp.title() == "A && _B"  # escaped, no mnemonic split (as Tk)
    assert ui.main.windowTitle() == "Doc [*][*] & co"


def test_degradations_are_logged(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_ui(
        tmp_path / "degrade.ui",
        '<window id="main"><layout type="grid"/>'
        '<widget class="Canvas" id="cnv"><prop name="background">SeaGreen3</prop>'
        '<cell row="0" column="0" padx="3"/></widget>'
        '<widget class="Spinbox" id="spn"><prop name="maximum">-5</prop>'
        '<cell row="1" column="0"/></widget>'
        '<widget class="Scale" id="scl"><prop name="minimum">10</prop>'
        '<prop name="maximum">0</prop><cell row="2" column="0"/></widget></window>',
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(path, loaded)
    messages = "\n".join(r.getMessage() for r in caplog.records)
    assert "SeaGreen3" in messages and "padding" in messages and "'spn'" in messages
    assert (ui.spn.minimum(), ui.spn.maximum()) == (-5.0, 0.0)
    assert (ui.scl.minimum(), ui.scl.maximum(), ui.scl.value()) == (0, 10, 10)


def test_prepare_refuses_a_dead_master_and_a_worker_thread(qapp: Any) -> None:
    from pyguibud.backends.pyside6 import PySide6Backend

    backend = PySide6Backend()
    with pytest.raises(TypeError):
        backend.prepare(object())
    errors: list[BaseException] = []

    def worker() -> None:
        try:
            backend.prepare(None)
        except RuntimeError as exc:
            errors.append(exc)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert errors and "main thread" in str(errors[0])


def test_a_failed_build_deletes_what_it_created(
    loaded: list[LoadedUi], monkeypatch: pytest.MonkeyPatch, qapp: Any
) -> None:
    def boom(*_args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(QtSession, "_make_button", boom)
    before = len(qapp.topLevelWidgets())
    with pytest.raises(UiError) as caught:
        _load(EXAMPLES / "hello.ui", loaded)
    assert caught.value.code == "runtime.build_failed"
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert len(qapp.topLevelWidgets()) == before
