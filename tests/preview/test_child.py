"""The preview child ``python -m pyguibud.preview`` (spec preview-export 4.2 and 9 "Child")."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyguibud.preview import NoHandlers
from tests.codegen.conftest import EXAMPLES, write_ui
from tests.preview.conftest import CHILD, ENV, describe_child

pytestmark = pytest.mark.gui

DIALOGS_ONLY = (
    '<window id="dlg_a" kind="dialog"><prop name="title">A</prop><layout type="pack"/>'
    '<widget class="Label" id="lbl"><prop name="text">Hi</prop><pack/></widget></window>'
)
MAIN_AND_DIALOG = (
    '<window id="main" kind="main"><prop name="title">Main</prop><layout type="pack"/></window>'
    '<window id="dlg" kind="dialog"><prop name="title">Dialog</prop><layout type="pack"/>'
    '<widget class="Button" id="btn"><prop name="text">Go</prop><pack/>'
    '<event name="command" handler="on_go"/></widget></window>'
)


def wait_for(path: Path, seconds: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
            return data
        except (OSError, ValueError):
            time.sleep(0.05)
    raise AssertionError(f"{path.name} did not appear")


def test_no_handlers_resolves_every_name_to_a_no_op() -> None:
    handlers = NoHandlers()
    found = handlers.get("on_anything")
    assert found is not None and found() is None and handlers["x"] is handlers["y"]
    assert len(handlers) == 0 and list(handlers) == []
    with pytest.raises(KeyError):
        handlers[1]  # type: ignore[index]


def test_describe_prints_the_interface(tmp_path: Path) -> None:
    data = describe_child(EXAMPLES / "hello.ui", cwd=tmp_path)
    assert data["theme"] == "flatly"
    assert data["windows"]["main"]["title"] == "Hello PyGUIbud"
    assert data["widgets"]["btn_greet"]["text"] == "Say hello"
    # D8: the handlers resolve (no-ops), so the key bindings exist as in an application
    assert "<Key-Return>" in data["widgets"]["ent_name"]["bindings"]
    ready = json.loads((tmp_path / "ready.json").read_text(encoding="utf-8"))
    assert "flatly" in ready["themes"] and ready["theme"] == "flatly" and ready["pid"] > 0


def test_quit_on_stdin_ends_with_an_ok_result(tmp_path: Path, spawn: Callable[..., Any]) -> None:
    process = spawn(EXAMPLES / "hello.ui")
    wait_for(tmp_path / "ready.json")
    process.stdin.write(b"theme darkly\nlang de_DE\nraise\nbogus line\n" + b"x" * 400 + b"\nquit\n")
    process.stdin.flush()
    assert process.wait(timeout=15) == 0
    result = wait_for(tmp_path / "result.json")
    assert result == {"code": "ok", "message": ""}


def test_closed_stdin_ends_the_child_within_two_seconds(
    tmp_path: Path, spawn: Callable[..., Any]
) -> None:
    process = spawn(EXAMPLES / "hello.ui")
    wait_for(tmp_path / "ready.json")
    started = time.monotonic()
    process.stdin.close()
    assert process.wait(timeout=10) == 0
    assert time.monotonic() - started < 2.0
    assert wait_for(tmp_path / "result.json")["code"] == "ok"


def test_an_invalid_file_exits_1_with_the_runtime_code(tmp_path: Path) -> None:
    bad = write_ui(
        tmp_path / "bad.ui",
        '<window id="main" kind="main"><layout type="pack"/>'
        '<widget class="Label" id="x"><pack/></widget>'
        '<widget class="Label" id="x"><pack/></widget></window>',
    )
    result = subprocess.run(
        [*CHILD, "--ui-lang", "de_DE", "--", str(bad)],
        capture_output=True,
        timeout=60,
        cwd=tmp_path,
        env=ENV,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads((tmp_path / "result.json").read_text("utf-8"))["code"] == (
        "runtime.invalid_document"
    )


def test_usage_errors_exit_2(tmp_path: Path) -> None:
    result = subprocess.run(
        [*CHILD, "--lang", "../etc", "x.ui"], capture_output=True, timeout=60, cwd=tmp_path
    )
    assert result.returncode == 2


def test_window_shows_only_that_dialog(tmp_path: Path) -> None:
    ui = write_ui(tmp_path / "two.ui", MAIN_AND_DIALOG)
    data = describe_child(ui, "--window", "dlg", cwd=tmp_path)
    assert data["windows"]["main"]["state"] == "withdrawn"
    assert data["windows"]["dlg"]["state"] == "normal"
    assert data["widgets"]["btn"]["bindings"] == []  # a command, not a binding
    default = describe_child(ui, "--window", "nope", cwd=tmp_path)
    assert default["windows"]["main"]["state"] == "normal"
    assert default["windows"]["dlg"]["state"] == "withdrawn"


def test_dialogs_only_file_gets_its_theme_without_a_warning(tmp_path: Path) -> None:
    ui = write_ui(tmp_path / "d.ui", DIALOGS_ONLY, meta='theme="darkly"')
    data = describe_child(ui, cwd=tmp_path)
    assert data["theme"] == "darkly"
    assert data["windows"]["dlg_a"]["state"] == "normal"
    ready = json.loads((tmp_path / "ready.json").read_text(encoding="utf-8"))
    assert ready["warnings"] == []


def test_theme_override_is_applied(tmp_path: Path) -> None:
    data = describe_child(EXAMPLES / "hello.ui", "--theme", "darkly", cwd=tmp_path)
    assert data["theme"] == "darkly"


# The commands are fed to the child's own poll loop inside a fresh process (no stdin thread),
# then the interface is described: this observes what a live switch changes.
_SCRIPT = """
import json, sys
from pathlib import Path
import pyguibud.preview as p
from pyguibud.preview._describe import describe
p._read_commands = lambda queue: None
child = p._Child(p._parser().parse_args(["--", sys.argv[1]]), Path.cwd())
seen = []
def run():
    for line in sys.argv[2:]:
        child.commands.put(line)
        child._poll()
        seen.append(describe(child.ui))
    child.quit()
child.host.run = run
child.start()
print(json.dumps(seen))
"""


def _live(ui: Path, *commands: str, cwd: Path) -> list[dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, "-c", _SCRIPT, str(ui), *commands],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=cwd,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    seen: list[dict[str, Any]] = json.loads(result.stdout.strip().splitlines()[-1])
    return seen


def test_live_language_switches(tmp_path: Path) -> None:
    copy = tmp_path / "examples"
    import shutil

    shutil.copytree(EXAMPLES, copy, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    german, source, ignored = _live(
        copy / "hello.ui", "lang de_DE", "lang -", "theme darkly", cwd=tmp_path
    )
    assert german["widgets"]["btn_greet"]["text"] == "Hallo sagen"
    assert source["widgets"]["btn_greet"]["text"] == "Say hello"
    assert ignored["theme"] == "flatly"  # trim T4: no live theme switch, a restart instead
