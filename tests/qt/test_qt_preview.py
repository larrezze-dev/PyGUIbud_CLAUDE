"""The PySide6 preview host, the Qt portable reader and QA-16b-01 (spec backends 5, 7, part 16c).

The host methods run in-process on the session ``QApplication``; the child runs in fresh
processes (offscreen), never together with Tk, and every process has a hard timeout.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.preview import READY, RESULT, NoHandlers
from pyguibud.preview._host import HOSTS, host_for
from pyguibud.preview._host_qt import QtHost
from pyguibud_runtime import load_ui
from tests.codegen.conftest import _display, write_ui
from tests.preview.conftest import CHILD, ENV
from tests.preview.test_child import DIALOGS_ONLY, MAIN_AND_DIALOG, wait_for
from tests.runtime.conftest import EXAMPLES

pytestmark = pytest.mark.qt

HELLO = EXAMPLES / "hello.ui"
QT_ENV = {**ENV, "QT_QPA_PLATFORM": "offscreen"}
PADDED = (
    '<window id="main" kind="main"><prop name="title">P</prop><layout type="pack"/>'
    '<widget class="Button" id="btn"><prop name="text">_Go</prop><pack padx="4"/></widget>'
    "</window>"
)


@pytest.fixture
def host(qapp: Any) -> Iterator[QtHost]:
    made = QtHost()
    yield made
    made.close()


# ------------------------------------------------------------------ host (in-process)
def test_pyside6_is_a_built_in_host_imported_lazily() -> None:
    assert "pyside6" in HOSTS
    assert isinstance(host_for("pyside6"), QtHost)


def test_without_a_main_window_the_master_is_a_hidden_parentless_widget(host: QtHost) -> None:
    from PySide6 import QtWidgets

    master: Any = host.prepare(False, "darkly")
    assert isinstance(master, QtWidgets.QWidget)
    assert master.parentWidget() is None and not master.isVisible()
    assert (host.themes(), host.current_theme(), host.set_theme("darkly")) == ([], "", False)


def test_with_a_main_window_there_is_no_master(host: QtHost) -> None:
    assert host.prepare(True, "") is None


def test_attach_shows_only_the_chosen_window_and_closing_it_calls_back(
    host: QtHost, qapp: Any, tmp_path: Path
) -> None:
    from PySide6 import QtCore

    path = write_ui(tmp_path / "two.ui", MAIN_AND_DIALOG)
    closed: list[bool] = []
    ui = load_ui(path, NoHandlers(), strict=False, backend="pyside6", master=host.prepare(True, ""))
    host.attach(ui, "main", "dlg", lambda: closed.append(True))
    host.update()
    assert ui.dlg.isVisible() and not ui.main.isVisible()
    ui.dlg.close()
    QtCore.QCoreApplication.processEvents()  # the callback is deferred out of the Close event
    assert closed == [True]
    host.close()
    host.close()  # idempotent
    assert not ui.dlg.isVisible()


def test_run_returns_once_a_scheduled_close_ran(host: QtHost, qapp: Any) -> None:
    from PySide6 import QtCore

    host.prepare(False, "")
    fallback = QtCore.QTimer()  # a regression must not hang the run; stopped afterwards
    fallback.setSingleShot(True)
    fallback.timeout.connect(qapp.quit)
    fallback.start(10_000)
    try:
        host.schedule(0, host.close)
        host.run()
        host.run()  # closed: never enters the loop again
    finally:
        fallback.stop()


def test_a_dialogs_only_file_shows_its_first_dialog_over_the_hidden_master(
    host: QtHost, tmp_path: Path
) -> None:
    path = write_ui(
        tmp_path / "dialogs.ui",
        DIALOGS_ONLY + DIALOGS_ONLY.replace("dlg_a", "dlg_b").replace("lbl", "lbl_b"),
    )
    master: Any = host.prepare(False, "")
    ui = load_ui(path, NoHandlers(), strict=False, backend="pyside6", master=master)
    host.attach(ui, None, None, lambda: None)
    host.update()
    shown = [key for key in ui.windows if getattr(ui, key).isVisible()]
    assert shown == ["dlg_a"] and not master.isVisible()


# ------------------------------------------------------------------ child (fresh processes)
def _child(
    tmp_path: Path, ui: Path, *args: str, stdin: bytes = b"", env: dict[str, str] = QT_ENV
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*CHILD, "--backend", "pyside6", *args, "--", str(ui)],
        input=stdin.decode(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=tmp_path,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    ("windows", "warnings"),
    [(PADDED, ["The padding (padx, pady) of 'btn' is ignored by Qt."]), (DIALOGS_ONLY, [])],
    ids=["main-with-d6-note", "dialogs-only-hidden-master"],
)
def test_the_child_writes_ready_json_with_the_qt_degradation_warnings(
    tmp_path: Path, windows: str, warnings: list[str]
) -> None:
    """D6: the Qt padding note reaches ready.json, as the Tk D5 note does (QA-16a-12)."""
    ui = write_ui(tmp_path / "padded.ui", windows)
    process = subprocess.Popen(
        [*CHILD, "--backend", "pyside6", "--", str(ui)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=tmp_path,
        env=QT_ENV,
    )
    try:
        ready = wait_for(tmp_path / READY)
        process.communicate(b"raise\nquit\n", timeout=30)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    assert (ready["themes"], ready["theme"]) == ([], "")
    assert [w["message"] for w in ready["warnings"]] == warnings
    assert process.returncode == 0
    assert json.loads((tmp_path / RESULT).read_text(encoding="utf-8"))["code"] == "ok"


_LIVE = """
import json, sys
import pyguibud.preview as p
from pyguibud.preview._describe import portable_describe
seen = []
quit_ = p._Child.quit
def quit(self):
    if not seen:  # the view just before the quit command closes the window
        seen.append(portable_describe(self.ui, "pyside6"))
    quit_(self)
p._Child.quit = quit
code = p.run(["--backend", "pyside6", "--", sys.argv[1]])
print(json.dumps({"code": code, "seen": seen}))
"""


@pytest.mark.parametrize(("commands", "button"), [("lang de_DE", "Hallo sagen"), ("", "Say hello")])
def test_language_switches_live_over_stdin(tmp_path: Path, commands: str, button: str) -> None:
    """The stdin thread fills the queue; the Qt timer drains it on the main thread."""
    result = subprocess.run(
        [sys.executable, "-c", _LIVE, str(HELLO)],
        input=f"{commands}\nquit\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=tmp_path,
        env=QT_ENV,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout.strip().splitlines()[-1])
    assert data["code"] == 0
    assert data["seen"][0]["widgets"]["btn_greet"]["text"] == button


@pytest.mark.parametrize("name", ["hello.ui", "dialogs.ui"])  # with and without a main window
def test_qa16b_01_an_unknown_qt_platform_is_reported_not_a_hang(tmp_path: Path, name: str) -> None:
    ui = HELLO if name == "hello.ui" else Path(__file__).parents[1] / "codegen/data" / name
    result = _child(tmp_path, ui, env={**ENV, "QT_QPA_PLATFORM": "bogus"})
    assert result.returncode == 1, result.stderr
    data = json.loads((tmp_path / RESULT).read_text(encoding="utf-8"))
    assert data["code"] == "runtime.no_display"
    assert "'bogus' (QT_QPA_PLATFORM) is not installed" in data["message"]
    assert not (tmp_path / READY).exists()


def _view(tmp_path: Path, backend: str, *args: str) -> dict[str, Any]:
    env = QT_ENV if backend == "pyside6" else ENV
    result = subprocess.run(
        [*CHILD, "--describe", *args, "--backend", backend, "--", str(HELLO)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=tmp_path,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    view: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return view


@pytest.mark.parametrize("lang", [(), ("--lang", "de_DE")])
def test_portable_view_of_hello_is_the_same_in_qt_and_tk(
    tmp_path: Path, lang: tuple[str, ...]
) -> None:
    if (reason := _display()) is not None:  # the Tk half runs in its own process
        pytest.skip(f"needs a Tk display: {reason}")
    qt = _view(tmp_path, "pyside6", "--portable", *lang)
    assert qt == _view(tmp_path, "tkinter", "--portable", *lang)
    assert qt["windows"]["main"]["status"] and qt["widgets"]["sts_main"] == "<status bar>"
    assert qt["windows"]["main"]["menubar"][0]["items"][0]["shortcut"] == "Ctrl+Q"


def test_describe_of_a_qt_interface_is_its_portable_view(tmp_path: Path) -> None:
    assert _view(tmp_path, "pyside6") == _view(tmp_path, "pyside6", "--portable")
