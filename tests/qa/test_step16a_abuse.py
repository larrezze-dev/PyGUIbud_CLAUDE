"""QA abuse tests of Step 16a (plain tkinter backend, preview child, ``examples/show_ui.py``).

Fixed findings are regression tests named after their QA-16a-NN id; the other tests pin behaviour
QA checked and found correct. Everything that builds Tk widgets runs in a subprocess, so no Tk
root is shared with the rest of the suite and a stray ``ttkbootstrap`` import is visible.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from pyguibud.designer.settings import BACKEND_NAME
from pyguibud.preview import BACKEND_RE

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
CHILD = [sys.executable, "-m", "pyguibud.preview"]
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)
ENV["PYGUIBUD_LANG"] = "en_GB"  # children must not follow the host locale

_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n<pyguibud-ui schema_version="1.0" '
    'xmlns="urn:pyguibud:ui:1" xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">\n'
    '<meta generator="pyguibud" source_locale="en_GB" theme="{theme}"/>\n'
)


def _run(args: list[str], cwd: Path, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False,
        cwd=cwd, env=ENV,
    )  # fmt: skip


def _probe(code: str, cwd: Path) -> dict[str, Any]:
    """Run ``code`` in a fresh interpreter; its last stdout line is a JSON object."""
    result = _run([sys.executable, "-c", textwrap.dedent(code)], cwd)
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return data


def _scrolled_ui(folder: Path, height: int) -> Path:
    rows = "".join(
        f'<widget class="Label" id="lbl_{i}"><cell row="{i}" column="0" sticky="w"/>'
        f'<prop name="text">Row {i}</prop></widget>\n'
        for i in range(60)
    )
    path = folder / f"scrolled_{height}.ui"
    path.write_text(
        _HEAD.format(theme="flatly")
        + '<window id="main" kind="main"><prop name="title">Scrolled</prop>'
        '<layout type="grid"><column index="0" weight="1"/><row index="0" weight="1"/></layout>'
        '<widget class="ScrolledFrame" id="scr"><cell row="0" column="0" sticky="nsew"/>'
        f'<prop name="height">{height}</prop>'
        '<layout type="grid"><column index="0" weight="1"/></layout>'
        f"{rows}</widget></window></pyguibud-ui>\n",
        "utf-8",
    )
    return path


_SIZE = """
import json, sys
from pyguibud_runtime import load_ui
class N(dict):
    def __missing__(self, key): return lambda *a: None
ui = load_ui(sys.argv[1] if len(sys.argv) > 1 else {path!r}, N(), strict=False, backend={backend!r})
ui.main.update()
box = ui.scr.container
print(json.dumps({{"w": box.winfo_reqwidth(), "h": box.winfo_reqheight()}}))
ui.destroy()
"""


# ------------------------------------------------------------------ QA-16a-03 ScrolledFrame size
@pytest.mark.gui
@pytest.mark.parametrize("height", [50, 600])
def test_qa16a_03_tkinter_scrolled_frame_honours_height(tmp_path: Path, height: int) -> None:
    ui = _scrolled_ui(tmp_path, height)
    tk_box = _probe(_SIZE.format(path=str(ui), backend="tkinter"), tmp_path)
    tb_box = _probe(_SIZE.format(path=str(ui), backend="ttkbootstrap"), tmp_path)
    assert tb_box["h"] == height  # the reference
    assert tk_box == tb_box


# ------------------------------------------------------------------ QA-16a-04 wheel bind_all
_WHEEL = """
import json, tkinter
from pyguibud_runtime import load_ui
class N(dict):
    def __missing__(self, key): return lambda *a: None
root = tkinter.Tk()
errors, mine = [], []
root.report_callback_exception = lambda kind, exc, tb: errors.append(repr(exc))
root.bind_all("<MouseWheel>", lambda e: mine.append(1))  # the application's own wheel handler
ui = load_ui({path!r}, N(), strict=False, backend="tkinter", master=root)
root.update()
box = ui.scr.container
box.event_generate("<Enter>", x=5, y=5)  # the pointer comes over the frame
root.update()
ui.destroy()  # e.g. a button in the frame closes this part of the app; no <Leave> comes
root.update()
root.event_generate("<MouseWheel>", delta=-120, when="now")
root.update()
print(json.dumps({{"errors": errors, "app_handler_calls": len(mine)}}))
root.destroy()
"""


@pytest.mark.gui
def test_qa16a_04_the_scrolled_frame_wheel_binding_is_local(tmp_path: Path) -> None:
    ui = _scrolled_ui(tmp_path, 150)
    result = _probe(_WHEEL.format(path=str(ui)), tmp_path)
    assert result == {"errors": [], "app_handler_calls": 1}


# ------------------------------------------------------------------ QA-16a-05 name grammars
@pytest.mark.parametrize("name", ["my-fork", "qt-6"])
def test_qa16a_05_every_offered_toolkit_name_is_accepted_by_the_child(
    name: str, tmp_path: Path
) -> None:
    assert BACKEND_NAME.fullmatch(name)  # the designer lists it and saves it
    result = _run([*CHILD, "--backend", name, "--", str(EXAMPLES / "hello.ui")], tmp_path)
    assert result.returncode == 1, result.stderr
    assert BACKEND_RE.fullmatch(name)


# ------------------------------------------------------------------ QA-16a-06 preview_host raises
class RaisingHost:
    """A fork backend whose optional ``preview_host`` capability raises."""

    @staticmethod
    def preview_host() -> object:
        raise RuntimeError("fork host exploded")


def test_qa16a_06_a_raising_preview_host_is_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.backends import BUILTIN_BACKENDS
    from pyguibud.preview import _host
    from pyguibud_runtime import UiError

    monkeypatch.setitem(BUILTIN_BACKENDS, "fork", f"{__name__}:RaisingHost")
    with pytest.raises(UiError) as caught:
        _host.host_for("fork")
    assert caught.value.code == "runtime.backend_unavailable"


def test_a_fork_that_crashes_on_import_is_backend_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.backends import BUILTIN_BACKENDS
    from pyguibud.preview import _host
    from pyguibud_runtime import UiError

    monkeypatch.setitem(BUILTIN_BACKENDS, "fork", "tests.qa._no_such_module_16a:Backend")
    with pytest.raises(UiError) as caught:
        _host.host_for("fork")
    assert caught.value.code == "runtime.backend_unavailable"


# ------------------------------------------------------------------ QA-16a-07 show_ui --lang
@pytest.mark.gui
@pytest.mark.parametrize("lang", ["", "../../etc", "de DE"])
def test_qa16a_07_show_ui_refuses_a_bad_lang_without_a_traceback(lang: str, tmp_path: Path) -> None:
    script = str(EXAMPLES / "show_ui.py")
    result = _run(
        [sys.executable, script, str(EXAMPLES / "hello.ui"), "--backend", "tkinter",
         "--lang", lang],
        tmp_path, timeout=30,
    )  # fmt: skip
    assert result.returncode != 0
    assert "Traceback" not in result.stderr, result.stderr


# ------------------------------------------------ QA-16a-08 show_ui on a dialog-only document
_DIALOGS = """
import json, runpy
show_ui = runpy.run_path({script!r})
ui = show_ui["load"]({path!r}, {backend!r}, None)
tops = ui.windows
root = next(iter(tops.values())).master
root.update()
states = {{key: top.state() for key, top in tops.items()}}
for top in tops.values():  # the user closes every dialog, then the main loop must end
    root.after(10, lambda t=top: t.tk.call(t.protocol("WM_DELETE_WINDOW")))
ui.run()
print(json.dumps({{"states": states, "windows": sorted(tops)}}))
"""


@pytest.mark.gui
@pytest.mark.parametrize("backend", ["tkinter", "ttkbootstrap"])
def test_qa16a_08_show_ui_shows_the_dialogs_of_a_dialog_only_document(
    tmp_path: Path, backend: str
) -> None:
    """Ruling QA-16a-08: a hidden root, every dialog shown, closing the last one ends run()."""
    path = ROOT / "tests" / "codegen" / "data" / "dialogs.ui"
    code = _DIALOGS.format(script=str(EXAMPLES / "show_ui.py"), path=str(path), backend=backend)
    result = _probe(code, tmp_path)
    assert result["windows"] == ["dlg_about", "dlg_ask"]
    assert set(result["states"].values()) == {"normal"}


@pytest.mark.parametrize(
    ("args", "needle"),
    [
        (["missing.ui"], "does not exist"),
        (["examples/preview/logo.png"], "UTF-8"),
        (["pyproject.toml"], "well-formed"),
        (["examples"], "folder"),
        (["examples/hello.ui", "--backend", "bogus"], "not available"),
        (["examples/hello.ui", "--backend", "pyside6; rm -rf"], "not available"),
        (["examples/hello.ui", "--backend", ""], "not available"),
        (["examples/include/address_card.ui", "--backend", "tkinter"], "only components"),
    ],
)
def test_show_ui_refuses_bad_input_with_a_reason(args: list[str], needle: str) -> None:
    result = _run([sys.executable, str(EXAMPLES / "show_ui.py"), *args], ROOT, timeout=30)
    assert result.returncode == 1
    assert needle in result.stderr and "Traceback" not in result.stderr


# ------------------------------------------------ pinned: D4, D5/B6, no ttkbootstrap
_BUILD = """
import json, logging, sys
from tkinter import ttk
from pyguibud_runtime import load_ui
logs = []
class Grab(logging.Handler):
    def emit(self, record): logs.append(record.getMessage())
logging.getLogger("pyguibud_runtime").addHandler(Grab())
class N(dict):
    def __missing__(self, key): return lambda *a: None
ui = load_ui({path!r}, N(), strict=False, backend="tkinter")
ui.main.update()
theme = ttk.Style(ui.main).theme_use()
ui.destroy()
print(json.dumps({{"logs": logs, "theme": theme, "tb": "ttkbootstrap" in sys.modules}}))
"""


def _styled_doc(folder: Path, theme: str, count: int) -> Path:
    buttons = "".join(
        f'<widget class="Button" id="b{i}" tb:bootstyle="danger-outline">'
        f'<cell row="{i // 25}" column="{i % 25}"/><prop name="text">{i}</prop></widget>\n'
        for i in range(count)
    )
    path = folder / f"styled_{theme}_{count}.ui"
    path.write_text(
        _HEAD.format(theme=theme)
        + f'<window id="main" kind="main"><layout type="grid"/>{buttons}</window></pyguibud-ui>\n',
        "utf-8",
    )
    return path


@pytest.mark.gui
@pytest.mark.parametrize(("theme", "expected"), [("clam", "clam"), ("darkly", None)])
def test_tkinter_applies_only_ttk_theme_names_and_never_loads_ttkbootstrap(
    tmp_path: Path, theme: str, expected: str | None
) -> None:
    result = _probe(_BUILD.format(path=str(_styled_doc(tmp_path, theme, 500))), tmp_path)
    styled = [m for m in result["logs"] if "tb:bootstyle" in m]
    assert styled == ["500 ttkbootstrap styles (tb:bootstyle) are ignored by the tkinter toolkit."]
    assert not any("theme" in m.casefold() for m in result["logs"])  # D4: silently
    assert result["theme"] == (expected or result["theme"]) and result["theme"] != "darkly"
    assert result["tb"] is False


@pytest.mark.gui
@pytest.mark.parametrize("name", ["hello.ui", "include/with_include.ui", "preview/with_image.ui"])
def test_the_tkinter_child_never_loads_ttkbootstrap(name: str, tmp_path: Path) -> None:
    code = f"""
    import json, sys, runpy
    sys.argv = ["pyguibud.preview", "--backend", "tkinter", "--describe", "--",
                {str(EXAMPLES / name)!r}]
    try:
        runpy.run_module("pyguibud.preview", run_name="__main__")
    except SystemExit as exc:
        code = exc.code
    print(json.dumps({{"tb": "ttkbootstrap" in sys.modules, "code": code}}))
    """
    result = _probe(code, tmp_path)
    assert result == {"tb": False, "code": 0}
    ready = json.loads((tmp_path / "ready.json").read_text("utf-8"))
    assert ready["themes"] == [] and ready["theme"] == ""


# ------------------------------------------------ QA-16a-09 D4 for dialog-only docs
@pytest.mark.gui
def test_qa16a_09_the_tkinter_preview_applies_a_ttk_theme_without_a_main_window(
    tmp_path: Path,
) -> None:
    doc = tmp_path / "dialogs_clam.ui"
    doc.write_text(
        _HEAD.format(theme="clam")
        + '<window id="dlg" kind="dialog"><prop name="title">D</prop><layout type="pack"/>'
        '<widget class="Label" id="lbl"><prop name="text">x</prop><pack/></widget></window>'
        "</pyguibud-ui>\n",
        "utf-8",
    )
    result = _run([*CHILD, "--backend", "tkinter", "--describe", "--", str(doc)], tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.strip().splitlines()[-1])["theme"] == "clam"
