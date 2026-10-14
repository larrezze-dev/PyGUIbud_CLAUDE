"""QA abuse tests of Step 17b "Factories and codegen" (spec docs/specs/plugins.md §4, §5, §7, §10).

What a careless or hostile user does with the five native ``tb:`` widgets: hand-edited ``.ui``
files with extreme but validator-accepted values, injection-shaped texts that must survive code
generation, live retranslation, repeated builds, and the design canvas.

Passing tests pin behaviour QA verified. Strict xfails are the open findings QA-17b-NN; each
says what is expected. Every Tk scenario runs in a fresh interpreter with a hard timeout
(ttkbootstrap allows one root per process); generated modules run without PyGUIbud importable.
"""

# ruff: noqa: E501 - long literal .ui documents and subprocess scripts
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest

from pyguibud.codegen import generate_python
from pyguibud.core.xml_io import read_ui

pytestmark = pytest.mark.gui

ROOT = Path(__file__).resolve().parents[2]
ACME_DEMO = ROOT / "examples" / "acme_demo.ui"
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)
_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"'
    ' xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">\n<meta source_locale="en_GB"/>'
)


def _write(path: Path, body: str, variables: str = "") -> Path:
    var = f"<variables>{variables}</variables>" if variables else ""
    path.write_text(
        f'{_HEAD}{var}<window id="main" kind="main"><layout type="grid"/>{body}</window>'
        "</pyguibud-ui>\n",
        encoding="utf-8",
    )
    return path


def _w(cls: str, wid: str, fallback: str, props: str = "", attrs: str = "", row: int = 0) -> str:
    return f'<widget class="{cls}" id="{wid}" fallback="{fallback}" {attrs}>{props}<cell row="{row}" column="0"/></widget>'


def _p(name: str, value: str, translatable: bool = False) -> str:
    flag = ' translatable="true"' if translatable else ""
    return f'<prop name="{name}"{flag}>{value}</prop>'


def _run(
    code: str, *args: str, timeout: int = 120, env: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run ``code`` in a fresh interpreter; it prints one ``JSON`` line (or the run fails)."""
    result = subprocess.run(
        [sys.executable, "-c", code, *args],
        capture_output=True, text=True, encoding="utf-8", timeout=timeout, env={**ENV, **(env or {})}, cwd=ROOT, check=False,
    )  # fmt: skip
    for line in result.stdout.splitlines():
        if line.startswith("JSON"):
            data: dict[str, Any] = json.loads(line[4:])
            data["stderr"] = result.stderr
            return data
    return {"crashed": True, "rc": result.returncode, "stderr": result.stderr[-3000:]}


_LOAD = r"""
import json, logging, sys
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
from pyguibud_runtime import load_ui
from pyguibud.core import default_registry
out = {}
class H:
    def __getattr__(self, name): return lambda: None
ui = load_ui(sys.argv[1], H(), strict=False)
ui.main.update()
exec(sys.argv[2])
out["failed"] = [d.code for d in default_registry().diagnostics() if d.code == "registry.factory_failed"]
ui.destroy()
print("JSON" + json.dumps(out))
"""

# The generated module runs where PyGUIbud cannot be imported (as tests/codegen/conftest.py).
_GEN = r"""
import os, sys, json, runpy, logging, importlib.abc
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("pyguibud", "pyguibud_runtime"):
            raise ImportError("blocked: " + name)
        return None
sys.meta_path.insert(0, _Block())
sys.modules["pyguibud"] = None
sys.modules["pyguibud_runtime"] = None
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
g = runpy.run_path(sys.argv[1], run_name="generated")
out = {}
class H:
    def __getattr__(self, name): return lambda: None
try:
    ui = g["Ui_Main"]()
    ui.setup_ui(None, H())
except Exception as exc:
    out["error"] = repr(exc)
    print("JSON" + json.dumps(out)); raise SystemExit(0)
ui.main.update()
exec(sys.argv[2])
ui.destroy()
print("JSON" + json.dumps(out))
"""


def _generate(ui: Path) -> Path:
    module = ui.with_name(ui.stem + "_ui.py")
    module.write_text(
        generate_python(read_ui(str(ui)), str(ui), output=str(module)).text,
        encoding="utf-8", newline="\n",
    )  # fmt: skip
    return module


def _both(ui: Path, probe: str = "pass") -> tuple[dict[str, Any], dict[str, Any]]:
    """(load_ui result, generated-module result) of the same probe."""
    return _run(_LOAD, str(ui), probe), _run(_GEN, str(_generate(ui)), probe)


# ------------------------------------------------------------------ extreme accepted values
EXTREMES = {
    "meter_1000": _w("tb:Meter", "w", "Progressbar", _p("meter_size", "1000")),
    "meter_50_thick100": _w(
        "tb:Meter",
        "w",
        "Progressbar",
        _p("meter_size", "50") + _p("meter_thickness", "100") + _p("meter_type", "semi"),
    ),
    "meter_negative": _w(
        "tb:Meter",
        "w",
        "Progressbar",
        _p("value", "-50") + _p("maximum", "0") + _p("amount_format", "{:.6f}" + "x" * 26),
    ),
    "meter_subtext_10k": _w("tb:Meter", "w", "Progressbar", _p("subtext", "S" * 10000, True)),
    "flood_max0": _w(
        "tb:Floodgauge",
        "w",
        "Progressbar",
        _p("maximum", "0") + _p("value", "5") + _p("mask", "%%{}%%"),
    ),
    "flood_vertical_indeterminate": _w(
        "tb:Floodgauge",
        "w",
        "Progressbar",
        _p("orient", "vertical") + _p("mode", "indeterminate") + _p("length", "10000"),
    ),
    "date_1900": _w(
        "tb:DateEntry", "w", "Entry", _p("value", "1900-01-01") + _p("date_format", "%a %d %b %y")
    ),
    "date_9998": _w(
        "tb:DateEntry",
        "w",
        "Entry",
        _p("value", "9998-12-31") + _p("date_format", "%j %d %B %Y %A") + _p("first_weekday", "6"),
    ),
    "date_percent": _w(
        "tb:DateEntry", "w", "Entry", _p("date_format", "%%%d%%%m%%%Y%%") + _p("state", "readonly")
    ),
    "table_64x64": _w(
        "tb:Tableview",
        "w",
        "Treeview",
        _p("columns", ";".join(f"{i:02d}" + "c" * 62 for i in range(64)), True),
    ),
    "table_page1000": _w(
        "tb:Tableview",
        "w",
        "Treeview",
        _p("columns", "A;A; ", True)
        + _p("pagesize", "1000")
        + _p("paginated", "true")
        + _p("searchable", "true")
        + _p("autofit", "true")
        + _p("selectmode", "none"),
    ),
    "toggle_junk_style": _w(
        "tb:ToggleButton",
        "w",
        "Checkbutton",
        _p("text", "_" + "x" * 10000, True),
        'tb:bootstyle="zzz-qqq"',
    ),
    "toggle_two_colours": _w(
        "tb:ToggleButton",
        "w",
        "Checkbutton",
        _p("shape", "square"),
        'tb:bootstyle="light-dark striped"',
    ),
}
NATIVE_CLASS = {
    "meter": "TFrame",
    "flood": "Canvas",
    "date": "TEntry",
    "table": "Treeview",
    "toggle": "TCheckbutton",
}


@pytest.mark.parametrize("case", sorted(EXTREMES))
def test_extreme_accepted_values_build_natively_in_load_ui_and_the_export(
    tmp_path: Path, case: str
) -> None:
    loaded, generated = _both(
        _write(tmp_path / f"{case}.ui", EXTREMES[case]), 'out["cls"] = ui.w.winfo_class()'
    )
    expected = NATIVE_CLASS[case.split("_")[0]]
    assert loaded.get("cls") == expected and loaded["failed"] == [], loaded
    assert generated.get("cls") == expected and "error" not in generated, generated


# ------------------------------------------------------------------ codegen injection
NASTY = {
    "quotes": "a'b\"c'''d\"\"\"e",
    "backslashes": "C:\\new\\table\\x41\\u0041\\N{BULLET}\\",
    "braces": "{} {0} {name} {{x}} {:.2f} %s %(a)s",
    "control": "line1\nline2\rline3\ttab\n",
    "bidi": "abc\u202edef\u2066x\u2069\u200f\u200b\ufeffend",
    "tcl": "[exit] $var \\[list] {unbalanced",
    "code": '"""; import os; os.system("calc"); """',
}


def _xml_text(raw: str) -> str:
    """``raw`` as XML character data that keeps CR, LF and TAB (character references)."""
    return escape(raw, {"\r": "&#13;", "\n": "&#10;", "\t": "&#9;"})


_TEXTS = 'out["texts"] = [ui.m.cget("subtext"), ui.f.cget("text"), [ui.t.heading(c)["text"] for c in ui.t["columns"]], ui.g.cget("text")]'


@pytest.mark.parametrize("case", sorted(NASTY))
def test_hostile_translatable_texts_compile_and_show_the_same_text(
    tmp_path: Path, case: str
) -> None:
    text = _xml_text(NASTY[case])
    heading = _xml_text(NASTY[case].replace(";", ","))
    body = (
        _w("tb:Meter", "m", "Progressbar", _p("subtext", text, True))
        + _w("tb:Floodgauge", "f", "Progressbar", _p("text", text, True), row=1)
        + _w("tb:Tableview", "t", "Treeview", _p("columns", f"{heading};{heading}2", True), row=2)
        + _w("tb:ToggleButton", "g", "Checkbutton", _p("text", text, True), row=3)
    )
    loaded, generated = _both(_write(tmp_path / "nasty.ui", body), _TEXTS)
    assert "texts" in loaded, loaded
    assert generated.get("texts") == loaded["texts"], (generated, loaded)


def test_hostile_date_format_survives_codegen(tmp_path: Path) -> None:
    body = _w(
        "tb:DateEntry",
        "w",
        "Entry",
        _p("value", "2024-02-29") + _p("date_format", escape("%d'%m\"%Y\\")),
    )
    loaded, generated = _both(_write(tmp_path / "fmt.ui", body), 'out["text"] = ui.w.get()')
    assert loaded["text"] == generated.get("text") == "29'02\"2024\\", (loaded, generated)


# ------------------------------------------------------------------ locales
_RETRANSLATE = r"""
texts = {}
for lang in ("es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR", "en_XA", "en_GB"):
    ui.retranslate(lang=lang); ui.main.update()
    texts[lang] = [ui.mtr_level.cget("subtext"), [ui.tbl_items.heading(c)["text"] for c in ui.tbl_items["columns"]], ui.tgl_enabled.cget("text")]
out["texts"] = texts
"""


def test_live_retranslation_with_tb_widgets_in_every_locale() -> None:
    out = _run(_LOAD, str(ACME_DEMO), _RETRANSLATE)
    assert "texts" in out, out
    assert out["texts"]["de_DE"] == ["Level", ["Name", "Colour", "Amount"], "Enabled"]
    assert len(out["texts"]["en_XA"][1]) == 3  # the pseudo-locale keeps the heading count


@pytest.mark.xfail(strict=True, reason="QA-17b-05")
def test_qa17b_05_pseudo_locale_brackets_each_tableview_heading() -> None:
    """en_XA wraps the whole ';'-joined text, so only the first heading gets '[' and the last
    one gets all the padding and ']'. Expected: each heading is pseudo-localised on its own
    (bracketed and lengthened), so heading truncation can be checked in en_XA."""
    out = _run(_LOAD, str(ACME_DEMO), _RETRANSLATE)
    headings = out["texts"]["en_XA"][1]
    assert all(h.startswith("[") and h.endswith("]") for h in headings), headings


# ------------------------------------------------------------------ QA-17b-01: %y before 1900
@pytest.mark.skipif(
    sys.platform != "win32", reason="strftime('%y') refuses years < 1900 on Windows only"
)
def test_qa17b_01_the_first_accepted_year_with_a_two_digit_year_builds_in_both_paths(
    tmp_path: Path,
) -> None:
    """QA-17b-01 (fixed): 1899-12-31 is refused by the validator (R89, see the 17a refusal
    table), because ``strftime('%y')`` raises for years < 1900 on Windows and the generated
    module has no guard. The first accepted date, 1900-01-01 with %y, builds natively in both."""
    body = _w(
        "tb:DateEntry", "w", "Entry", _p("value", "1900-01-01") + _p("date_format", "%d/%m/%y")
    )
    loaded, generated = _both(_write(tmp_path / "y1900.ui", body), 'out["text"] = ui.w.get()')
    assert "error" not in generated, generated
    assert loaded["failed"] == [], loaded
    assert loaded["text"] == generated["text"] == "01/01/00", (loaded, generated)


# ------------------------------------------------------------------ QA-17b-03: picker range
_PICKER = r"""
import tkinter
errors = []
ui.main._root().report_callback_exception = lambda *a: errors.append(repr(a[1]))
def close():  # if the picker opens (fixed), close it so the click returns
    for top in ui.main.winfo_children():
        if isinstance(top, tkinter.Toplevel):
            top.destroy()
    ui.main.after(300, close)
ui.main.after(300, close)
ui.w.master.button.invoke()
out["errors"] = errors
"""


@pytest.mark.parametrize(("value", "weekday"), [("9998-12-31", "0"), ("1900-01-01", "6")])
def test_qa17b_03_the_calendar_button_works_at_the_ends_of_the_accepted_range(
    tmp_path: Path, value: str, weekday: str
) -> None:
    """QA-17b-03 (fixed): ttkbootstrap's DatePickerDialog builds a month grid with outside days
    and raised ``ValueError: year 10000 (or 0) is out of range`` for December 9999 and January
    0001. The validator now accepts 1900-01-01..9998-12-31 only (R89), where the picker opens.
    The %y format is used too: the outside days of January 1900 are never formatted."""
    body = _w(
        "tb:DateEntry",
        "w",
        "Entry",
        _p("value", value) + _p("first_weekday", weekday) + _p("date_format", "%d/%m/%y"),
    )
    out = _run(_LOAD, str(_write(tmp_path / "edge.ui", body)), _PICKER)
    assert out.get("errors") == [], out
    assert out.get("failed") == [], out


# ------------------------------------------------------------------ QA-17b-04: rebuild leak
_LEAK = r"""
import json, gc, logging, sys
logging.disable(logging.CRITICAL)
import ttkbootstrap
from pyguibud_runtime import load_ui
root = ttkbootstrap.Window(); root.withdraw()
def commands(): return len(root.tk.splitlist(root.tk.call("info", "commands")))
growth = []
for _ in range(4):
    before = commands()
    ui = load_ui(sys.argv[1], strict=False, master=root); ui.main.update(); ui.destroy()
    root.update(); gc.collect()
    growth.append(commands() - before)
root.destroy()
print("JSON" + json.dumps({"growth": growth}))
"""


def test_qa17b_04_rebuilding_a_tableview_leaks_nothing(tmp_path: Path) -> None:
    """Every build of a tb:Tableview leaves one Tcl command (``<id>_trace_pagesize``, a trace
    ttkbootstrap 2.2.3 never removes) and keeps the destroyed Tableview alive through it. The
    design canvas rebuilds on edits, so the designer grows for as long as a Tableview is on the
    canvas. Expected: no growth after the first build (PyGUIbud removes the trace on destroy)."""
    body = "".join(
        _w("tb:Tableview", f"t{i}", "Treeview", _p("columns", "A;B", True), row=i) for i in range(5)
    )
    out = _run(_LEAK, str(_write(tmp_path / "leak.ui", body)))
    assert out.get("growth", [None])[1:] == [0, 0, 0], out


def test_rebuilding_the_other_tb_widgets_leaks_nothing(tmp_path: Path) -> None:
    body = (
        _w("tb:Meter", "m", "Progressbar")
        + _w("tb:Floodgauge", "f", "Progressbar", row=1)
        + _w("tb:DateEntry", "d", "Entry", row=2)
        + _w("tb:ToggleButton", "g", "Checkbutton", row=3)
    )
    out = _run(_LEAK, str(_write(tmp_path / "noleak.ui", body)))
    assert out.get("growth", [None])[1:] == [0, 0, 0], out


# ------------------------------------------------------------------ the design canvas
_CANVAS = r"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, os.getcwd())
from ttkbootstrap import App
from pyguibud.core import Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.settings import Settings
root = App(title="qa17b"); root.withdraw()
app = DesignerApp(root, settings=Settings())
app.open_path(Path(sys.argv[1])); root.update()
view = app.shell.canvas.stages[0].view
nodes = {n.id: n for n in app.session.document.walk() if isinstance(n, Widget)}
out = {"classes": {k: type(view.outer[id(n)]).__name__ for k, n in nodes.items() if id(n) in view.outer}}
flood = view.outer[id(nodes["flg_level"])]
trough = flood.find_all()[0]
out["flood"] = [flood.winfo_width(), flood.coords(trough)]
date = view.outer[id(nodes["ent_day"])]
out["date_button_tags"] = list(date.button.bindtags())
app.dispose(); root.destroy()
print("JSON" + json.dumps(out))
"""


def _canvas(tmp_path: Path) -> dict[str, Any]:
    dirs = {"PYGUIBUD_CONFIG_DIR": str(tmp_path / "c"), "PYGUIBUD_STATE_DIR": str(tmp_path / "s")}
    return _run(_CANVAS, str(ACME_DEMO), timeout=180, env=dirs)


def test_the_design_canvas_builds_the_tb_widgets_and_the_date_button_is_inert(
    tmp_path: Path,
) -> None:
    out = _canvas(tmp_path)
    assert out["classes"]["mtr_level"] == "Meter" and out["classes"]["tbl_items"] == "Tableview", (
        out
    )
    assert out["classes"]["ent_day"] == "DateEntry" and out["classes"]["flg_level"] == "Floodgauge"
    tags = out["date_button_tags"]  # design bindtags: no class binding (QA-17b-02 keeps the
    assert tags[0] == "PyguibudDesign" and "TButton" not in tags  # icon's <<ThemeChanged>>)


_INERT = r"""
import json, os, sys, tkinter
from pathlib import Path
sys.path.insert(0, os.getcwd())
import ttkbootstrap
from pyguibud.core import Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.settings import Settings
root = ttkbootstrap.App(title="qa17b"); root.withdraw()
app = DesignerApp(root, settings=Settings())
app.open_path(Path(sys.argv[1])); root.update()
view = app.shell.canvas.stages[0].view
nodes = {n.id: n for n in app.session.document.walk() if isinstance(n, Widget)}
popups, base = [], set(root.winfo_children())
def watch():  # close any popup at once, so a modal picker never blocks the script
    for w in root.winfo_children():
        if isinstance(w, tkinter.Toplevel) and w not in base:
            popups.append(type(w).__name__); w.destroy()
    root.after(50, watch)
root.after(50, watch)
def click(w):
    for seq, x in (("<Enter>", 5), ("<ButtonPress-1>", 5), ("<B1-Motion>", 40), ("<ButtonRelease-1>", 40)):
        w.event_generate(seq, x=x, y=5)
    root.after(400, root.quit); root.mainloop()
def probe(meter, date):
    before = meter.amount_used_var.get()
    click(meter.indicator)
    click(date.button)
    return [meter.amount_used_var.get() != before, len(popups)]
out = {"canvas": probe(view.outer[id(nodes["m"])], view.outer[id(nodes["d"])])}
popups.clear()
frame = tkinter.Toplevel(root); base.add(frame)  # control: the same clicks outside design mode
meter = ttkbootstrap.Meter(frame, interactive=True, amountused=0); meter.pack()
date = ttkbootstrap.DateEntry(frame); date.pack(); root.update()
out["control"] = probe(meter, date)
app.dispose(); root.destroy()
print("JSON" + json.dumps(out))
"""


def test_the_canvas_keeps_an_interactive_meter_and_the_date_button_inert(tmp_path: Path) -> None:
    """QA verified (17b): on the design canvas a press/drag never changes an interactive Meter
    and the DateEntry button opens no picker; the control shows the same clicks do both."""
    body = _w("tb:Meter", "m", "Progressbar", _p("interactive", "true")) + _w(
        "tb:DateEntry", "d", "Entry", row=1
    )
    dirs = {"PYGUIBUD_CONFIG_DIR": str(tmp_path / "c"), "PYGUIBUD_STATE_DIR": str(tmp_path / "s")}
    out = _run(_INERT, str(_write(tmp_path / "inert.ui", body)), timeout=180, env=dirs)
    assert out.get("control") == [True, 1], out  # the clicks work outside design mode
    assert out["canvas"] == [False, 0], out


def test_qa17b_02_the_floodgauge_is_drawn_at_its_size_on_the_design_canvas(tmp_path: Path) -> None:
    """Design mode keeps a widget's own bindings only when they are all geometry events.
    Floodgauge binds ``<Configure>`` (its redraw) and ``<<ThemeChanged>>`` on itself, so it gets
    the design bindtags only, never redraws, and stays a 1x1 px drawing: the canvas shows an
    empty cell where the preview shows a 438 px gauge. Expected: the gauge fills its cell on
    the canvas, as at runtime."""
    width, trough = _canvas(tmp_path)["flood"]
    assert width > 1 and trough[2] == pytest.approx(width), (width, trough)
