"""Step 11b smoke: generate ``hello.ui``, check the module statically, run it without PyGUIbud."""

from __future__ import annotations

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pyguibud.codegen import GENERATED_MARKER, default_output, generate_python
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import EXAMPLES, GIF, P5, P6, generate, png, run_generated, write_ui

ALLOWED_IMPORTS = {
    *("__future__", "argparse", "base64", "collections.abc", "contextlib", "gettext"),
    *("logging", "os", "re", "sys", "tkinter", "types", "typing", "warnings", "ttkbootstrap"),
}


def _hello(tmp_path: Path) -> Path:
    target = tmp_path / "examples"
    shutil.copytree(EXAMPLES, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target / "hello.ui"


def _imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    return names


def test_hello_parses_with_allowed_imports_only() -> None:
    text = generate(EXAMPLES / "hello.ui", EXAMPLES.parent / "hello.py")
    assert text.startswith(GENERATED_MARKER + " ")
    assert text.endswith("\n") and not text.endswith("\n\n")
    assert "\r" not in text
    assert not any(line != line.rstrip() for line in text.split("\n"))
    tree = ast.parse(text)
    compile(tree, "hello_ui.py", "exec")
    assert _imports(tree) <= ALLOWED_IMPORTS
    assert "pyguibud_runtime" not in text and "import pyguibud" not in text
    assert "_DOCS = (('hello', 'en_GB', 'examples/locale'),)" in text
    assert "_HANDLERS = ('on_greet', 'on_quit')" in text
    assert "class Ui_Main(_Ui):" in text
    # No absolute path of the machine appears in the output.
    assert str(EXAMPLES) not in text and str(EXAMPLES).replace("\\", "/") not in text


def test_output_is_deterministic_and_independent_of_cwd_and_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud import i18n

    path = EXAMPLES / "hello.ui"
    output = EXAMPLES / "hello_ui.py"
    first = generate(path, output)
    monkeypatch.chdir(tmp_path)
    i18n.set_language("de_DE")
    assert generate(path, output) == first


def test_hash_seed_does_not_change_the_output(tmp_path: Path) -> None:
    code = (
        "import sys; from pyguibud.codegen import generate_python;"
        "from pyguibud.core.xml_io import read_ui;"
        "p = sys.argv[1]; sys.stdout.buffer.write("
        "generate_python(read_ui(p), p, output=sys.argv[2]).text.encode())"
    )
    outputs = []
    for seed in ("0", "1"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        result = subprocess.run(
            [sys.executable, "-c", code, str(EXAMPLES / "hello.ui"), str(tmp_path / "x.py")],
            capture_output=True,
            env=env,
            check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1]


def test_default_output() -> None:
    assert default_output(os.path.join("dir", "my-form.ui")) == os.path.join("dir", "my_form_ui.py")
    assert default_output("9x.ui") == "_9x_ui.py"


def test_import_boundary_of_codegen() -> None:
    forbidden = ("tkinter", "ttkbootstrap", "pyguibud_runtime", "pyguibud.codegen._support")
    code = (
        "import sys, pyguibud.codegen;"
        f"bad = sorted(m for m in sys.modules if m.startswith({forbidden!r}));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.gui
def test_hello_runs_without_pyguibud(tmp_path: Path) -> None:
    ui = _hello(tmp_path)
    module = tmp_path / "hello_ui.py"
    module.write_text(generate(ui, module), encoding="utf-8", newline="\n")
    out = run_generated(
        module,
        """
calls = []
class H:
    def on_greet(self): calls.append("greet")
    def on_quit(self): calls.append("quit")
ui = g["Ui_Main"]()
ui.setup_ui(None, H())
ui.btn_greet.invoke()
ui.update_ok = True
out["before"] = str(ui.btn_greet.cget("text"))
ui.retranslate("de_DE")
out["after"] = str(ui.btn_greet.cget("text"))
out["menu"] = [ui.mnu_file.entrycget(ui.act_quit, k) for k in ("label", "accelerator")]
out["underline"] = int(ui.mnu_file.entrycget(ui.act_quit, "underline"))
out["calls"] = calls
out["widgets"] = sorted(ui.widgets)
out["windows"] = sorted(ui.windows)
out["var"] = ui.vars.user_name.get()
ui.destroy()
ui.destroy()
try:
    ui.show("main")
except g["UiError"] as exc:
    out["after_destroy"] = exc.code
""",
    )
    assert out["calls"] == ["greet"]
    assert out["before"] == "Say hello"
    assert out["after"] == "Hallo sagen"
    assert out["menu"] == ["Beenden", "Ctrl+Q"]
    assert out["underline"] == 0
    assert out["windows"] == ["main"]
    assert "act_quit" in out["widgets"] and "sts_main" in out["widgets"]
    assert out["var"] == ""
    assert out["after_destroy"] == "runtime.destroyed"


@pytest.mark.gui
def test_strict_missing_handlers_and_a_second_setup_ui(tmp_path: Path) -> None:
    ui = _hello(tmp_path)
    module = tmp_path / "hello_ui.py"
    module.write_text(generate(ui, module), encoding="utf-8", newline="\n")
    out = run_generated(
        module,
        """
import tkinter
ui = g["Ui_Main"]()
try:
    ui.setup_ui(None, object())
except g["UiError"] as exc:
    out["strict"] = [exc.code, list(exc.names)]
out["no_root"] = tkinter._default_root is None
ui.setup_ui(None, {}, strict=False)
try:
    ui.setup_ui(None, {}, strict=False)
except g["UiError"] as exc:
    out["again"] = exc.code
ui.destroy()
""",
    )
    assert out["strict"] == ["runtime.missing_handlers", ["on_greet", "on_quit"]]
    assert out["no_root"] is True
    assert out["again"] == "runtime.already_built"
    assert "on_quit" in out["stderr"]


IMAGES = (
    ("i_png", "a.png", png()),
    ("i_gif", "b.gif", GIF),
    ("i_ppm", "c.ppm", P6),
    ("i_pgm", "d.pgm", P5),
)


@pytest.mark.gui
def test_images_are_embedded_and_load_through_data(tmp_path: Path) -> None:
    """Spec 4.4 gate: PNG, GIF, P6 PPM and P5 PGM all load from embedded ``data=``."""
    resources = ""
    widgets = ""
    for row, (image_id, name, data) in enumerate(IMAGES):
        (tmp_path / name).write_bytes(data)
        resources += f'<image id="{image_id}" src="{name}"/>'
        widgets += (
            f'<widget class="Label" id="lbl_{row}"><prop name="image" ref="{image_id}"/>'
            f'<prop name="text">x</prop><cell row="{row}" column="0"/></widget>'
        )
    ui = write_ui(
        tmp_path / "pics.ui",
        f'<window id="main" kind="main"><layout type="grid"/>{widgets}</window>',
        resources=resources,
    )
    module = tmp_path / "pics_ui.py"
    text = generate(ui, module)
    assert "file=" not in text
    module.write_text(text, encoding="utf-8", newline="\n")
    out = run_generated(
        module,
        """
ui = g["Ui_Main"]()
ui.setup_ui()
out["sizes"] = [[ui._img[i].width(), ui._img[i].height()] for i in range(4)]
out["compound"] = str(ui.lbl_0.cget("compound"))
ui.destroy()
""",
    )
    assert out["sizes"] == [[2, 3], [1, 1], [2, 3], [2, 3]]
    assert out["compound"] == "left"


@pytest.mark.gui
def test_includes_scopes_and_variables(tmp_path: Path) -> None:
    write_ui(
        tmp_path / "part.ui",
        '<window id="part" kind="component"><layout type="pack"/>'
        '<widget class="Entry" id="ent" bind="name"><event name="change" handler="on_change"/>'
        '<pack fill="x"/></widget></window>',
        variables='<var id="name" type="string" default="part"/>',
    )
    ui = write_ui(
        tmp_path / "host.ui",
        '<window id="main" kind="main"><layout type="pack"/>'
        '<include id="inc_a" src="part.ui" component="part"><pack/></include>'
        '<include id="inc_b" src="part.ui" component="part"><pack/></include>'
        '<include id="inc_c" src="#" component="local"><pack/></include>'
        "</window>"
        '<window id="local" kind="component"><layout type="grid"/>'
        '<widget class="Label" id="lbl" bind="title"><cell row="0" column="0"/></widget>'
        "</window>"
        '<window id="dlg" kind="dialog"><prop name="title">Dialog</prop>'
        '<layout type="grid"/></window>',
        variables='<var id="title" type="string" default="host"/>',
    )
    module = tmp_path / "host_ui.py"
    text = generate(ui, module)
    assert text.count("def _component_") == 2
    module.write_text(text, encoding="utf-8", newline="\n")
    out = run_generated(
        module,
        """
calls = []
ui = g["Ui_Main"]()
ui.setup_ui(None, {"on_change": lambda: calls.append(1)})
ui.inc_a.vars.name.set("changed")
out["calls"] = len(calls)
out["b"] = ui.inc_b.vars.name.get()
out["shared"] = ui.inc_c.vars.title is ui.vars.title
out["scope"] = [sorted(ui.inc_a.widgets), dict(ui.inc_a.windows)]
out["windows"] = sorted(ui.windows)
out["dialog_shown"] = ui.dlg.winfo_ismapped()
ui.show("dlg")
try:
    ui.show("part")
except g["UiError"] as exc:
    out["unknown"] = exc.code
ui.destroy()
""",
    )
    assert out["calls"] == 1
    assert out["b"] == "part"
    assert out["shared"] is True
    assert out["scope"] == [["ent", "part"], {}]
    assert out["windows"] == ["dlg", "main"]
    assert out["unknown"] == "runtime.unknown_window"


def test_generated_text_does_not_depend_on_output_name(tmp_path: Path) -> None:
    path = EXAMPLES / "hello.ui"
    result = read_ui(str(path))
    first = generate_python(result, str(path), output=str(EXAMPLES.parent / "a.py")).text
    second = generate_python(result, str(path), output=str(EXAMPLES.parent / "b.py")).text
    assert first == second
