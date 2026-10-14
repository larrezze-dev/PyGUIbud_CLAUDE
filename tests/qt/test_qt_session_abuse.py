"""PySide6 session life and abuse cases in the test process (spec backends §4.1, §6, §7).

B3 (``load_ui`` from a worker thread), B8, B10 (shared application), B11, B13, B16, and the
20 build/destroy cycles. The cases that need a fresh process are in ``test_qt_process.py``.
"""

from __future__ import annotations

import logging
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import shiboken6
from PySide6 import QtCore, QtTest, QtWidgets

from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.qt

DATA = Path(__file__).resolve().parents[1] / "codegen" / "data"
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
PPM = b"P6\n1 1\n255\n\x00\x00\x00"
#: A GIF whose header and first image descriptor pass the validator's probe (R75/R76), but
#: whose image data is garbage: Qt cannot decode it (B8).
BAD_GIF = b"GIF89a\x01\x00\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\xff\xff\xff\xff"


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test and destroys them afterwards."""
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    _flush()


def _flush() -> None:
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _load(path: Path, uis: list[LoadedUi], **options: Any) -> LoadedUi:
    ui = load_ui(path, None, strict=False, backend="pyside6", **options)
    uis.append(ui)
    return ui


def _messages(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


def _rich(tmp_path: Path) -> Path:
    shutil.copy(DATA / "rich.ui", tmp_path / "rich.ui")
    (tmp_path / "pic.gif").write_bytes(GIF)
    (tmp_path / "pic.ppm").write_bytes(PPM)
    return tmp_path / "rich.ui"


# ---------------------------------------------------------------- B3, B10
def test_b3_load_ui_from_a_worker_thread_is_backend_unavailable(qapp: Any) -> None:
    caught: list[BaseException] = []

    def worker() -> None:
        try:
            load_ui(EXAMPLES / "hello.ui", None, strict=False, backend="pyside6")
        except BaseException as exc:  # handed to the main thread
            caught.append(exc)

    before = len(qapp.topLevelWidgets())
    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(30)
    assert len(caught) == 1 and isinstance(caught[0], UiError)
    assert caught[0].code == "runtime.backend_unavailable"
    assert "main thread" in str(caught[0])
    assert len(qapp.topLevelWidgets()) == before  # nothing was built


def test_b10_two_interfaces_share_the_one_application(loaded: list[LoadedUi], qapp: Any) -> None:
    first = _load(EXAMPLES / "hello.ui", loaded)
    second = _load(EXAMPLES / "hello.ui", loaded)
    assert QtWidgets.QApplication.instance() is qapp
    assert first.main is not second.main and first.main.isVisible() and second.main.isVisible()
    nested: list[float] = []

    def inside() -> None:
        started = time.perf_counter()
        second.run()  # a loop is running: returns at once
        nested.append(time.perf_counter() - started)
        QtCore.QCoreApplication.exit()  # quit() would also close every window (Qt 6)

    fallback = QtCore.QTimer(singleShot=True, interval=5000)  # never hang
    fallback.timeout.connect(QtCore.QCoreApplication.exit)
    fallback.start()
    QtCore.QTimer.singleShot(0, inside)
    started = time.perf_counter()
    first.run()  # no loop is running: exec() on the caller's application too (§4.1)
    fallback.stop()
    assert nested and nested[0] < 0.1 and time.perf_counter() - started < 4.0
    first.destroy()
    _flush()
    assert second.main.isVisible() and QtWidgets.QApplication.instance() is qapp


# ---------------------------------------------------------------- B8
def test_b8_an_image_qt_cannot_decode_is_logged_and_left_out(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "bad.gif").write_bytes(BAD_GIF)
    path = write_ui(
        tmp_path / "bad.ui",
        '<window id="main"><layout type="pack"/>'
        '<widget class="Label" id="lbl"><prop name="image" ref="bad"/>'
        '<prop name="text">Fallback</prop><pack/></widget>'
        '<widget class="Button" id="btn"><prop name="image" ref="bad"/>'
        '<prop name="text">Go</prop><pack/></widget>'
        '<widget class="Entry" id="ent"><pack/></widget></window>',
        resources='<image id="bad" src="bad.gif"/>',
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(path, loaded)
    messages = _messages(caplog)
    assert "'bad'" in messages and "cannot be displayed by Qt" in messages
    assert messages.count("cannot be displayed by Qt") == 1
    assert ui.lbl.pixmap() is None or ui.lbl.pixmap().isNull()
    assert ui.lbl.text() == "Fallback"  # no image: the label shows its text
    assert ui.btn.icon().isNull() and ui.btn.text() == "Go"
    assert isinstance(ui.ent, QtWidgets.QLineEdit) and ui.main.isVisible()


# ---------------------------------------------------------------- B11
_DIALOG = (
    '<window id="main"><layout type="pack"/>'
    '<widget class="Label" id="lbl"><prop name="text">Main</prop><pack/></widget></window>'
    '<window id="dlg" kind="dialog"><prop name="title">Dialog</prop><layout type="pack"/>'
    '<widget class="Button" id="btn"><prop name="text">OK</prop><pack/></widget></window>'
)


def test_b11_closing_the_main_window_with_a_dialog_shown_ends_the_session(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(tmp_path / "dlg.ui", _DIALOG)
    ui = _load(path, loaded)
    ui.show("dlg")
    main, dlg, btn = ui.main, ui.dlg, ui.btn
    assert dlg.isVisible() and main.isVisible()
    main.close()
    QtTest.QTest.qWait(50)  # the session destroys itself in a 0 ms timer
    _flush()
    assert not shiboken6.isValid(dlg) or not dlg.isVisible()
    assert not shiboken6.isValid(main) and not shiboken6.isValid(btn)
    calls: tuple[Callable[[], object], ...] = (lambda: ui.show("dlg"), ui.retranslate, ui.run)
    for call in calls:
        with pytest.raises(UiError) as caught:
            call()
        assert caught.value.code == "runtime.destroyed"


# ---------------------------------------------------------------- B13
def test_b13_inverted_ranges_do_not_crash(
    tmp_path: Path, loaded: list[LoadedUi], caplog: pytest.LogCaptureFixture
) -> None:
    path = write_ui(
        tmp_path / "range.ui",
        '<window id="main"><layout type="pack"/>'
        '<widget class="Scale" id="h_inv"><prop name="minimum">10</prop>'
        '<prop name="maximum">0</prop><pack/></widget>'
        '<widget class="Scale" id="h_ok"><prop name="minimum">0</prop>'
        '<prop name="maximum">10</prop><pack/></widget>'
        '<widget class="Scale" id="v_inv"><prop name="orient">vertical</prop>'
        '<prop name="minimum">10</prop><prop name="maximum">0</prop><pack/></widget>'
        '<widget class="Scale" id="v_ok"><prop name="orient">vertical</prop>'
        '<prop name="minimum">0</prop><prop name="maximum">10</prop><pack/></widget>'
        '<widget class="Spinbox" id="spn_inv"><prop name="minimum">5</prop>'
        '<prop name="maximum">1</prop><pack/></widget></window>',
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(path, loaded)
    # Tk draws ``minimum`` on the left (horizontal) or at the top (vertical): Qt's low end is on
    # the left and at the bottom, so exactly the inverted-horizontal and plain-vertical scales
    # need Qt's inverted appearance.
    assert ui.h_inv.invertedAppearance() and not ui.h_ok.invertedAppearance()
    assert not ui.v_inv.invertedAppearance() and ui.v_ok.invertedAppearance()
    for name in ("h_inv", "v_inv"):
        slider = getattr(ui, name)
        assert slider.minimum() <= slider.maximum() and slider.value() == slider.maximum()
    assert (ui.spn_inv.minimum(), ui.spn_inv.maximum()) == (1.0, 5.0)
    assert "'spn_inv'" in _messages(caplog)


# ---------------------------------------------------------------- cycles, destroy
def test_twenty_build_destroy_cycles_leak_no_top_level(
    tmp_path: Path, loaded: list[LoadedUi], qapp: Any
) -> None:
    path = _rich(tmp_path)
    _flush()
    baseline = len(qapp.topLevelWidgets())
    mains: list[Any] = []
    for _cycle in range(20):
        ui = load_ui(path, None, strict=False, backend="pyside6")
        ui.show("dlg")
        mains.append(ui.main)
        assert len(qapp.topLevelWidgets()) > baseline
        ui.destroy()
        ui.destroy()  # idempotent
        _flush()
        assert len(qapp.topLevelWidgets()) == baseline
    assert not any(shiboken6.isValid(main) for main in mains)
    calls: tuple[Callable[[], object], ...] = (lambda: ui.show("main"), ui.retranslate, ui.run)
    for call in calls:
        with pytest.raises(UiError) as caught:
            call()
        assert caught.value.code == "runtime.destroyed"


# ---------------------------------------------------------------- B16
@pytest.mark.slow
def test_b16_ten_thousand_widgets_build_within_five_seconds(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    frames = "".join(
        f'<widget class="Frame" id="f{f}"><layout type="pack" orient="horizontal"/><pack/>'
        + "".join(
            f'<widget class="Label" id="l{f}_{i}"><prop name="text">L{i}</prop><pack/></widget>'
            for i in range(99)
        )
        + "</widget>"
        for f in range(100)
    )  # 100 frames + 9,900 labels
    path = write_ui(
        tmp_path / "big.ui", f'<window id="main"><layout type="pack"/>{frames}</window>'
    )
    started = time.perf_counter()
    ui = _load(path, loaded)
    elapsed = time.perf_counter() - started
    assert ui.l99_98.text() == "L98" and ui.l99_98.parentWidget() is ui.f99
    assert elapsed <= 5.0, f"10,000 widgets took {elapsed:.2f} s"
