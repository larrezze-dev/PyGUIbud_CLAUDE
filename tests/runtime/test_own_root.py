"""``load_ui`` creating its own root: each case runs in a fresh subprocess (one root each)."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from typing import Any

import pytest

from tests.runtime.conftest import EXAMPLES

pytestmark = pytest.mark.gui

PRELUDE = f"""
import json, sys, tkinter, ttkbootstrap
sys.path.insert(0, {str(EXAMPLES)!r})
from pyguibud_runtime import UiError, load_ui
HELLO = {str(EXAMPLES / "hello.ui")!r}
HANDLERS = {{"on_greet": lambda: None, "on_quit": lambda: None}}
def alive():
    style = ttkbootstrap.Style.get_instance()
    return {{"style": style is not None, "root": tkinter._default_root is not None}}
"""


def _run(code: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", PRELUDE + textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return data


def test_own_root_theme_and_destroy() -> None:
    data = _run(
        """
        ui = load_ui(HELLO, HANDLERS)
        out = {"theme": ttkbootstrap.Style.get_instance().theme_use(), "title": ui.main.title(),
               "is_root": ui.main is tkinter._default_root, "before": alive()}
        try:
            load_ui(HELLO, HANDLERS)
        except UiError as exc:
            out["second"] = exc.code
        ui.main.after(50, ui.destroy)
        ui.run()
        ui.destroy()
        out["after"] = alive()
        print(json.dumps(out))
        """
    )
    assert data["theme"] == "flatly" and data["title"] == "Hello PyGUIbud" and data["is_root"]
    assert data["before"] == {"style": True, "root": True}
    assert data["second"] == "runtime.root_exists"
    assert data["after"] == {"style": False, "root": False}


def test_failures_leave_no_root() -> None:
    data = _run(
        """
        from pyguibud.backends import _tk
        out = {}
        try:
            load_ui(HELLO, {})
        except UiError as exc:
            out["missing"] = [exc.code, list(exc.names)]
        out["clean_missing"] = alive()
        def boom(*args, **kwargs):
            raise RuntimeError("boom")
        _tk.TkSession._container = boom
        try:
            load_ui(HELLO, HANDLERS)
        except UiError as exc:
            out["build"] = exc.code
        out["clean_build"] = alive()
        def no_display(*args, **kwargs):
            raise tkinter.TclError("no display name")
        ttkbootstrap.App = no_display
        try:
            load_ui(HELLO, HANDLERS)
        except UiError as exc:
            out["display"] = exc.code
        out["clean_display"] = alive()
        print(json.dumps(out))
        """
    )
    clean = {"style": False, "root": False}
    assert data["missing"] == ["runtime.missing_handlers", ["on_greet", "on_quit"]]
    assert data["build"] == "runtime.build_failed"
    assert data["display"] == "runtime.no_display"
    assert data["clean_missing"] == data["clean_build"] == data["clean_display"] == clean


def test_unknown_theme_is_logged(tmp_path: Any) -> None:
    path = tmp_path / "t.ui"
    path.write_text(
        EXAMPLES.joinpath("hello.ui").read_text(encoding="utf-8").replace("flatly", "nosuch"),
        encoding="utf-8",
    )
    data = _run(
        f"""
        import logging
        records = []
        class Keep(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())
        logging.getLogger("pyguibud_runtime").addHandler(Keep())
        ui = load_ui({str(path)!r}, HANDLERS)
        ui.destroy()
        print(json.dumps({{"records": records}}))
        """
    )
    assert any("'nosuch' is not available" in record for record in data["records"])


def test_run_hello_example() -> None:
    data = _run(
        """
        import run_hello
        app, ui = run_hello.build("de_DE")
        out = {"title": ui.main.title(), "tab": ui.nbk_main.tab(0, "text")}
        ui.vars.user_name.set("Ana")
        ui.btn_greet.invoke()
        out["greet"] = ui.sts_main.cget("text")
        ui.vars.user_name.set("")
        app.on_greet()
        out["empty"] = ui.sts_main.cget("text")
        app.toggle_language()
        out["switched"] = [ui.main.title(), ui.sts_main.cget("text")]
        ui.main.after(50, app.on_quit)
        ui.run()
        del run_hello.HelloApp.on_greet
        out["exit"] = run_hello.main(["--lang", "de_DE"])
        print(json.dumps(out))
        """
    )
    assert data["title"] == "Hallo PyGUIbud" and data["tab"] == "Begrüßung"
    assert data["greet"] == "Hallo, Ana!"
    assert data["empty"] == "Bitte geben Sie Ihren Namen ein."
    assert data["switched"] == ["Hello PyGUIbud", "Ready"]
    assert data["exit"] == 1
