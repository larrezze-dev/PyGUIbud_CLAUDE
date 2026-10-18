"""Step 19d, H50: backend abuse cases B1-B16 (spec backends §6) that no earlier test pinned.

The audit table is ``docs/specs/backends-audit-19d.md``. The cases an earlier step already pins
are mapped there; this module adds the Tk-side B12 and B13, B15 through ``load_ui``, B9's
"warned once" reading in a fresh interpreter, B14's hand-edited ``settings.json`` on disk and a
non-``slow`` B16 smoke. Qt tests run offscreen on the session ``QApplication``; B9 runs in a
subprocess (Tk and Qt in one process are order dependent).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.registry import Registry
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import clean_i18n, write_ui  # noqa: F401 - autouse: i18n, registry

ROOT = Path(__file__).resolve().parents[2]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}


def _messages(caplog: pytest.LogCaptureFixture) -> str:
    return "\n".join(record.getMessage() for record in caplog.records)


@pytest.fixture
def qapp() -> Any:
    """The session ``QApplication`` (offscreen), or a skip without PySide6."""
    pytest.importorskip("PySide6")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtWidgets

    return QtWidgets.QApplication.instance() or QtWidgets.QApplication(["pyguibud-tests"])


@pytest.fixture
def loaded() -> Iterator[list[LoadedUi]]:
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()


# ---------------------------------------------------------------- B13, Tk side
RANGES = (
    '<window id="main"><layout type="pack"/>'
    '<widget class="Scale" id="sc_inv"><prop name="minimum">10</prop>'
    '<prop name="maximum">0</prop><pack/></widget>'
    '<widget class="Spinbox" id="spn_inv"><prop name="minimum">5</prop>'
    '<prop name="maximum">1</prop><pack/></widget></window>'
)


@pytest.mark.gui
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_b13_inverted_ranges_build_on_tk_without_a_crash(
    backend: str, tk_root: Any, tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(tmp_path / "range.ui", RANGES)
    ui = load_ui(path, None, strict=False, backend=backend, master=tk_root)
    loaded.append(ui)
    tk_root.update_idletasks()
    assert ui.sc_inv.winfo_exists() and ui.spn_inv.winfo_exists()
    # Tk draws an inverted scale / counts down natively: the options reach the widget as written
    # (the "inverted slider / sorted range" wording of the spec is the Qt mapping, pinned in
    # tests/qt/test_qt_session_abuse.py::test_b13_inverted_ranges_do_not_crash).
    assert (float(ui.sc_inv.cget("from")), float(ui.sc_inv.cget("to"))) == (10.0, 0.0)
    assert (float(ui.spn_inv.cget("from")), float(ui.spn_inv.cget("to"))) == (5.0, 1.0)


# ---------------------------------------------------------------- B12, Tk side
@pytest.mark.gui
@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_b12_an_int_entry_receiving_text_raises_nothing_and_keeps_the_variable(
    backend: str, tk_root: Any, tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(
        tmp_path / "b12.ui",
        '<window id="main"><layout type="pack"/>'
        '<widget class="Entry" id="ent_n" bind="n"><pack/></widget></window>',
        variables='<var id="n" type="int" default="3"/>',
    )
    ui = load_ui(path, None, strict=False, backend=backend, master=tk_root)
    loaded.append(ui)
    ui.ent_n.delete(0, "end")
    ui.ent_n.insert(0, "abc")  # no exception
    tk_root.update_idletasks()
    value: object
    try:
        value = ui.vars.n.get()
    except Exception as exc:  # Tk's own IntVar refuses "abc": it must be the documented kind
        value = type(exc).__name__
    assert value in (3, "ValueError", "TclError")
    ui.ent_n.delete(0, "end")
    ui.ent_n.insert(0, "12")
    assert ui.vars.n.get() == 12  # a later valid text works again


# ---------------------------------------------------------------- B15, a third-party backend
@dataclass
class _EP:
    name: str
    value: str
    group: str
    dist: object
    obj: object

    def load(self) -> object:
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


class _NoHost:
    """A fork backend without the optional ``preview_host`` capability."""


def _with_backends(monkeypatch: pytest.MonkeyPatch, *eps: _EP) -> None:
    import pyguibud.core.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "_metadata_entry_points",
        lambda group: [ep for ep in eps if ep.group == group],
    )


def test_b15_a_backend_that_crashes_on_load_is_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _with_backends(
        monkeypatch,
        _EP("crashy", "acme.nothing:B", "pyguibud.backends", None, RuntimeError("no toolkit")),
    )
    path = write_ui(tmp_path / "x.ui", '<window id="main"><layout type="pack"/></window>')
    with pytest.raises(UiError) as caught:
        load_ui(path, None, strict=False, backend="crashy")
    assert caught.value.code == "runtime.backend_unavailable"
    assert "no toolkit" in str(caught.value) or "crashy" in str(caught.value)


def test_b15_the_crash_is_diagnosed_and_the_registry_stays_usable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _with_backends(
        monkeypatch,
        _EP("crashy", "acme.nothing:B", "pyguibud.backends", None, RuntimeError("no toolkit")),
    )
    registry = Registry()
    with pytest.raises(Exception) as caught:
        registry.load_backend("crashy")
    assert getattr(caught.value, "code", "") == "registry.backend_failed"
    assert any(d.code == "registry.backend_failed" for d in registry.diagnostics())
    assert registry.require("Button").name == "Button"  # the core widgets are unaffected
    assert [b.name for b in registry.backends()] == ["crashy"]


def test_b15_a_backend_without_a_host_is_backend_unavailable_for_the_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.preview import _host

    _with_backends(monkeypatch, _EP("nohost", "acme:H", "pyguibud.backends", None, _NoHost))
    with pytest.raises(UiError) as caught:
        _host.host_for("nohost")
    assert caught.value.code == "runtime.backend_unavailable"


# ---------------------------------------------------------------- B14, a hand-edited file
@pytest.mark.parametrize(
    "value", ["pyside6; rm -rf", "", "x" * 10_240, "../../etc", "pyside6\x00"], ids=str
)
def test_b14_a_hand_edited_settings_file_on_disk_falls_back(value: str, tmp_path: Path) -> None:
    from pyguibud.designer.settings import load_settings, save_settings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"preview_backend": value}), encoding="utf-8")
    settings = load_settings(path=path)[0]
    assert settings.preview_backend == "ttkbootstrap"
    assert save_settings(settings, path=path)
    assert "preview_backend" not in json.loads(path.read_text("utf-8"))


# ---------------------------------------------------------------- B9, once, in a subprocess
B9_SCRIPT = textwrap.dedent(
    """
    import logging, sys, tempfile, pathlib
    records = []
    class H(logging.Handler):
        def emit(self, record): records.append(record.getMessage())
    logging.getLogger().addHandler(H()); logging.getLogger().setLevel(logging.INFO)
    from pyguibud_runtime import load_ui
    from tests.runtime.conftest import write_ui
    tmp = pathlib.Path(tempfile.mkdtemp())
    ui_path = write_ui(tmp / "a.ui", '<window id="main"><layout type="pack"/></window>')
    tk = load_ui(ui_path, None, strict=False, backend="tkinter")
    qt1 = load_ui(ui_path, None, strict=False, backend="pyside6")
    qt2 = load_ui(ui_path, None, strict=False, backend="pyside6")
    print(sum("Tk and Qt windows" in m for m in records))
    for ui in (qt2, qt1, tk):
        ui.destroy()
    """
)


@pytest.mark.gui
@pytest.mark.qt
def test_b9_the_mixed_toolkit_warning_is_logged_once_for_two_qt_builds() -> None:
    pytest.importorskip("PySide6")
    done = subprocess.run(
        [sys.executable, "-c", B9_SCRIPT],
        cwd=ROOT,
        env={**ENV, "PYTHONPATH": str(ROOT)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stderr[-800:]
    assert done.stdout.strip().splitlines()[-1] == "1", done.stdout


# ---------------------------------------------------------------- B16, the default-run smoke
@pytest.mark.qt
def test_b16_a_thousand_widgets_build_quickly_with_pyside6(
    tmp_path: Path, loaded: list[LoadedUi], qapp: Any
) -> None:
    """The 10,000-widget budget is ``tests/qt/test_qt_session_abuse.py`` (marked ``slow``)."""
    frames = "".join(
        f'<widget class="Frame" id="f{f}"><layout type="pack" orient="horizontal"/><pack/>'
        + "".join(
            f'<widget class="Label" id="l{f}_{i}"><prop name="text">L{i}</prop><pack/></widget>'
            for i in range(99)
        )
        + "</widget>"
        for f in range(10)
    )  # 10 frames + 990 labels
    path = write_ui(tmp_path / "k.ui", f'<window id="main"><layout type="pack"/>{frames}</window>')
    started = time.perf_counter()
    ui = load_ui(path, None, strict=False, backend="pyside6")
    loaded.append(ui)
    assert time.perf_counter() - started <= 5.0
    assert ui.l9_98.text() == "L98" and ui.l9_98.parentWidget() is ui.f9
