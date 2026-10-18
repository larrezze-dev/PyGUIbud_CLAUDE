"""Step 19d (hardening): the Qt builder (H54, H55, H56, H59, H61, H62) and the eventFilter
line PySide6 printed when a ``key:`` handler raised (carry-over).

Spec ``docs/specs/hardening.md`` §3 "19d"; background ``docs/specs/backends.md`` §14 (16c
"Known gaps") and ``docs/specs/plugins.md`` §14b.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from pyguibud.core import registry as registry_module
from pyguibud_runtime import LoadedUi, UiError
from tests.qt.test_qt_plugin_factory import GAUGES, _build, _spec, loaded  # noqa: F401
from tests.runtime.conftest import write_ui
from tests.runtime.test_tb_factories import _registry

pytestmark = pytest.mark.qt

_ROOT = Path(__file__).resolve().parents[2]
_SIBLING = '<widget class="Label" id="keep"><prop name="text">Keep me</prop>'
_SIBLING += '<cell row="9" column="0"/></widget>'


def _failures(reg: Any) -> list[str]:
    return [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]


# ------------------------------------------------------------------ H59, H61, H62
def test_an_inner_widget_outside_outer_is_rejected_and_deleted(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H59: a parentless ``inner`` passed the old check (``new == [outer]``)."""
    made: list[Any] = []

    def elsewhere(parent: Any, props: dict[str, Any]) -> Any:
        made.append(QtWidgets.QLabel())  # not inside outer
        return QtWidgets.QFrame(parent), made[-1]

    reg = _registry(_spec(elsewhere))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _build(tmp_path, loaded, GAUGES)
    assert _failures(reg) == ["check"]
    assert type(ui.g0).__name__ == "QLabel" and ui.g0 is not made[0] and ui.g0.text() == "G0"
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert not shiboken6.isValid(made[0])  # what the factory made is swept


def test_a_scrolled_inner_widget_inside_outer_passes_the_check(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H59: a descendant through a viewport is inside ``outer``."""

    def scrolled(parent: Any, props: dict[str, Any]) -> Any:
        area = QtWidgets.QScrollArea(parent)
        inner = QtWidgets.QLabel()
        area.setWidget(inner)
        return area, inner

    reg = _registry(_spec(scrolled))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _build(tmp_path, loaded, GAUGES)
    assert _failures(reg) == [] and ui.g0.text() == "G0"


@pytest.mark.parametrize("shape", ["outer", "inner"])
def test_an_existing_widget_returned_by_a_factory_is_never_deleted(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    """H61 (data loss): only what the factory made is deleted."""

    def thief(parent: Any, props: dict[str, Any]) -> Any:
        victim = next(c for c in parent.children() if isinstance(c, QtWidgets.QLabel))
        return victim if shape == "outer" else (QtWidgets.QFrame(parent), victim)

    reg = _registry(_spec(thief))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _build(tmp_path, loaded, _SIBLING + GAUGES)
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
    assert _failures(reg) == ["check"]
    assert shiboken6.isValid(ui.keep) and ui.keep.text() == "Keep me"
    assert ui.keep.parent() is not None  # still in its window
    frames = [c for c in ui.keep.parent().children() if type(c) is QtWidgets.QFrame]
    assert frames == []  # the new frame was swept


def test_a_deleted_parent_logs_no_fallback_warning(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H62: the build aborts, so "its fallback is shown" would be false."""

    def vandal(parent: Any, props: dict[str, Any]) -> Any:
        label = QtWidgets.QLabel(parent)
        shiboken6.delete(parent)
        return label

    reg = _registry(_spec(vandal))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"), pytest.raises(UiError):
        _build(tmp_path, loaded, GAUGES)
    assert "failed to build" not in caplog.text


# ------------------------------------------------------------------ H55, H56
_COMBOS = (
    '<widget class="Combobox" id="ro" bind="pick"><prop name="state">readonly</prop>'
    '<cell row="0" column="0"/></widget>'
    '<widget class="Combobox" id="ed" bind="pick"><cell row="1" column="0"/></widget>'
)


@pytest.mark.parametrize(("default", "index"), [("beta", 1), ("zeta", -1)])
def test_items_added_after_the_build_keep_the_bound_value(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    default: str,
    index: int,
) -> None:
    """H55: Qt selects the first item added to an empty list; Tk keeps the variable."""
    variables = f'<var id="pick" type="string" default="{default}"/>'
    ui = _build(tmp_path, loaded, _COMBOS, variables=variables)
    ui.ro.addItems(["alpha", "beta"])
    ui.ed.addItems(["alpha", "beta"])
    assert ui.vars.pick.get() == default
    assert ui.ro.currentIndex() == index and ui.ed.currentText() == default
    ui.ro.setCurrentIndex(0)  # a user pick still writes
    assert ui.vars.pick.get() == "alpha" and ui.ed.currentText() == "alpha"


def test_a_destroyed_session_removes_its_traces(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
) -> None:
    """H56: neither the binding nor a change handler stays on the variable."""
    calls: list[str] = []
    body = (
        '<widget class="Entry" id="en" bind="s"><event name="change" handler="h"/>'
        '<cell row="0" column="0"/></widget>'
    )
    path = write_ui(
        tmp_path / "q.ui",
        f'<window id="w"><layout type="grid"/>{body}</window>',
        variables='<var id="s" type="string"/>',
    )
    from pyguibud_runtime import load_ui

    ui = load_ui(path, {"h": lambda: calls.append("h")}, backend="pyside6")
    loaded.append(ui)
    variable = ui.vars.s
    variable.set("a")
    assert calls == ["h"] and len(variable._traces) == 2
    ui.destroy()
    assert variable._traces == {}
    variable.set("b")
    assert calls == ["h"]


# ------------------------------------------------------------------ H54
_KEYS = (
    '<widget class="Entry" id="en">'
    '<event name="key:&lt;Control-s&gt;" handler="save"/>'
    '<event name="key:&lt;Control-Alt-x&gt;" handler="alt_x"/>'
    '<event name="key:&lt;Control-x&gt;" handler="ctrl_x"/>'
    '<event name="key:&lt;Control-plus&gt;" handler="zoom"/>'
    '<cell row="0" column="0"/></widget>'
)
_MODS = {
    "C": Qt.KeyboardModifier.ControlModifier,
    "A": Qt.KeyboardModifier.AltModifier,
    "S": Qt.KeyboardModifier.ShiftModifier,
}


@pytest.mark.parametrize(
    ("key", "mods", "fired"),
    [
        (Qt.Key.Key_S, "C", ["save"]),
        (Qt.Key.Key_S, "CA", ["save"]),  # extra modifiers are allowed, as Tk
        (Qt.Key.Key_S, "CS", []),  # Ctrl+Shift+S is <Control-S> in Tk
        (Qt.Key.Key_S, "", []),
        (Qt.Key.Key_Plus, "CS", ["zoom"]),  # Ctrl+Shift+= on a US layout
        (Qt.Key.Key_Plus, "C", ["zoom"]),  # the keypad plus
        (Qt.Key.Key_X, "CA", ["alt_x"]),  # only the most specific binding, as Tk
        (Qt.Key.Key_X, "C", ["ctrl_x"]),
    ],
)
def test_key_events_match_modifiers_like_tk(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    key: Any,
    mods: str,
    fired: list[str],
) -> None:
    from pyguibud_runtime import load_ui

    calls: list[str] = []
    names = ("save", "alt_x", "ctrl_x", "zoom")
    handlers = {name: (lambda name=name: calls.append(name)) for name in names}
    path = write_ui(tmp_path / "k.ui", f'<window id="w"><layout type="grid"/>{_KEYS}</window>')
    ui = load_ui(path, handlers, backend="pyside6")
    loaded.append(ui)
    modifiers = Qt.KeyboardModifier.NoModifier
    for letter in mods:
        modifiers |= _MODS[letter]
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, modifiers)
    QtWidgets.QApplication.sendEvent(ui.en, event)
    assert calls == fired


# ------------------------------------------------------------------ carry-over
_RAISING = """
import sys
sys.path.insert(0, {root!r})
from PySide6 import QtCore, QtGui, QtWidgets
from pyguibud_runtime import load_ui

def boom():
    raise ValueError("boom")

seen = []
ui = load_ui({path!r}, {{"boom": boom, "ok": lambda: seen.append("ok")}}, backend="pyside6")
for key in (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Escape, QtCore.Qt.Key.Key_Return):
    event = QtGui.QKeyEvent(QtCore.QEvent.Type.KeyPress, key, QtCore.Qt.KeyboardModifier.NoModifier)
    QtWidgets.QApplication.sendEvent(ui.en, event)
QtWidgets.QApplication.processEvents()
print("seen", seen)
"""


def test_a_raising_key_handler_leaves_stderr_clean_at_exit(tmp_path: Path) -> None:
    """Carry-over: the handler's traceback is reported (as Tk), the filter goes on, and
    PySide6's "Error calling Python override" line (written on fd 2) never appears."""
    body = (
        '<widget class="Entry" id="en"><event name="key:&lt;Return&gt;" handler="boom"/>'
        '<event name="key:&lt;Escape&gt;" handler="ok"/>'
        '<cell row="0" column="0"/></widget>'
    )
    window = f'<window id="w" kind="main"><layout type="grid"/>{body}</window>'
    path = write_ui(tmp_path / "r.ui", window)
    code = _RAISING.format(root=str(_ROOT), path=str(path))
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "seen ['ok']"
    assert result.stderr.count("ValueError: boom") == 2
    assert "Error calling Python override" not in result.stderr


# ------------------------------------------------------------------ H49
class _Fragile(QtWidgets.QLabel):
    """A label whose second and later ``setText`` raise."""

    def __init__(self, parent: Any) -> None:
        super().__init__(parent)
        self.sets = 0

    def setText(self, text: str) -> None:  # noqa: N802
        self.sets += 1
        if self.sets >= 2:
            raise RuntimeError("second text set")
        super().setText(text)


def test_a_text_setter_raising_after_the_build_is_isolated(
    tmp_path: Path,
    loaded: list[LoadedUi],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H49: logged once, reported at the ``wire`` stage, the other slots still apply."""
    reg = _registry(_spec(lambda parent, props: _Fragile(parent)))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _build(tmp_path, loaded, GAUGES + _SIBLING)
        ui.retranslate()
    assert ui.keep.text() == "Keep me"
    assert ui.g0.text() == "G0" and ui.g1.text() == "G1"
    assert caplog.text.count("could not show the new text") == 1
    assert _failures(reg) == ["wire"]
