"""A generated module and ``examples/hello_app.py`` run with PyGUIbud made unimportable.

``test_clean_venv_*`` goes further: a new virtual environment holding only ``ttkbootstrap``.
That test is ``slow`` (a network install, unless uv's cache has the wheels) and skips itself
without ``uv`` or without a way to install; the default ``pytest`` run includes it.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.codegen.conftest import EXAMPLES, generate, make_data_copy, run_generated

HELLO_APP_BODY = """
import tkinter
before = sorted(m for m in sys.modules if m.split(".")[0] in ("pyguibud", "pyguibud_runtime")
                and sys.modules[m] is not None)
app = g["HelloApp"]("de_DE")
ui = app.ui
out["button"] = str(ui.btn_greet.cget("text"))
ui.vars.user_name.set("Ada")
app.on_greet()
out["greeting"] = str(ui.sts_main.cget("text"))
ui.vars.user_name.set("")
app.on_greet()
out["asked"] = str(ui.sts_main.cget("text"))
app.toggle_language()
out["toggled"] = [app.lang, str(ui.btn_greet.cget("text"))]
ui.windows["main"].update()
app.on_quit()
out["destroyed"] = tkinter._default_root is None or not ui.windows["main"].winfo_exists()
try:
    ui.show("main")
except g["UiError"] as exc:
    out["code"] = exc.code
out["bad_lang"] = g["main"](["--lang", "not a language"])
out["pyguibud_modules"] = before
"""


@pytest.mark.gui
def test_hello_app_builds_and_closes_without_pyguibud() -> None:
    out = run_generated(EXAMPLES / "hello_app.py", HELLO_APP_BODY)
    assert out["button"] == "Hallo sagen"
    assert out["greeting"] == "Hallo, Ada!"
    assert out["asked"] == "Bitte geben Sie Ihren Namen ein."
    assert out["toggled"] == ["en_GB", "Say hello"]
    assert out["destroyed"] is True and out["code"] == "runtime.destroyed"
    assert out["bad_lang"] == 1
    assert out["pyguibud_modules"] == []
    assert "not a language" in out["stderr"]


@pytest.mark.gui
def test_generated_hello_runs_in_a_process_with_the_modules_poisoned(tmp_path: Path) -> None:
    ui = make_data_copy(tmp_path / "data") / "rich.ui"
    module = ui.with_name("rich_ui.py")
    module.write_text(generate(ui, module), encoding="utf-8", newline="\n")
    out = run_generated(
        module,
        """
ui = g["Ui_Main"]()
ui.setup_ui(None, {}, strict=False)
out["classes"] = sorted({w.winfo_class() for w in ui.widgets.values() if hasattr(w, "winfo_class")})
ui.destroy()
out["leaked"] = sorted(m for m in sys.modules if m.startswith("pyguibud")
                       and sys.modules[m] is not None)
""",
    )
    assert "TNotebook" in out["classes"] and out["leaked"] == []
    assert "Ctrl+O" in out["stderr"]  # the warnings still reach logging


# --------------------------------------------------------------------------- clean virtual env
def _run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "VIRTUAL_ENV"}}
    env["PYTHONNOUSERSITE"] = "1"
    result: subprocess.CompletedProcess[str] = subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        **kwargs,  # type: ignore[call-overload]
    )
    return result


@pytest.mark.slow
@pytest.mark.gui
def test_clean_venv_runs_a_generated_module_with_only_ttkbootstrap(tmp_path: Path) -> None:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    venv = tmp_path / "venv"
    made = _run([uv, "venv", "--python", sys.executable, str(venv)], timeout=120)
    if made.returncode != 0:
        pytest.skip(f"uv venv failed: {made.stderr.strip()[-200:]}")
    python = (
        venv
        / ("Scripts" if os.name == "nt" else "bin")
        / ("python.exe" if os.name == "nt" else "python")
    )
    installed = _run(
        [uv, "pip", "install", "--python", str(python), "ttkbootstrap>=2.2,<3"], timeout=240
    )
    if installed.returncode != 0:
        pytest.skip(f"cannot install ttkbootstrap (offline?): {installed.stderr.strip()[-200:]}")
    listing = _run([uv, "pip", "list", "--python", str(python), "--format", "json"], timeout=60)
    names = {item["name"].lower().replace("_", "-") for item in json.loads(listing.stdout)}
    assert "ttkbootstrap" in names and not any(n.startswith("pyguibud") for n in names)

    ui = make_data_copy(tmp_path / "data") / "hello.ui"
    module = ui.with_name("hello_ui.py")
    module.write_text(generate(ui, module), encoding="utf-8", newline="\n")
    code = (
        "import json, sys, runpy;"
        "g = runpy.run_path(sys.argv[1], run_name='generated');"
        "ui = g['Ui_Main'](); ui.setup_ui(None, {}, strict=False);"
        "text = str(ui.btn_greet.cget('text')); ui.destroy();"
        "print(json.dumps([text, sorted(m for m in sys.modules if m.startswith('pyguibud'))]))"
    )
    ran = _run([str(python), "-c", code, str(module)], timeout=60, cwd=tmp_path)
    if "no display" in ran.stderr or "TclError" in ran.stderr:
        pytest.skip(f"no usable Tk display in the clean environment: {ran.stderr.strip()[-200:]}")
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert json.loads(ran.stdout.strip().splitlines()[-1]) == ["Say hello", []]
