"""QA pass of step 14p (designer visual polish): abuse cases and regression tests.

Tests named ``test_qa14p_NN_*`` reproduce an open finding of the QA report and FAIL until the
debugger fixes it (no xfail on purpose). The ``test_guard_*`` tests pass today and pin the
behaviour QA verified, so a later change cannot silently break it.

| id | severity | test |
|---|---|---|
| QA-14p-01 | MAJOR | toolbar states do not follow the selection |
| QA-14p-02 | BLOCKER | read-only spinbox: arrows/Up change the value, then flush() fails silently |
| QA-14p-03 | MAJOR | a toolbar click steals the canvas focus: Ctrl+V / Delete stop working |
| QA-14p-04 | MAJOR | the plate is misplaced (stage padding) for windows with min_height |
| QA-14p-05 | MAJOR | recovery dialog: paths are not re-elided after widening then narrowing |
| QA-14p-06 | MINOR | recovery dialog: elision counts characters; wide glyphs still clip |
| QA-14p-07 | MINOR | a deeply nested icons.json raises RecursionError instead of falling back |
"""

from __future__ import annotations

import datetime
import subprocess
import sys
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.core import read_ui_string
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.icons import parse_masks
from pyguibud.designer.recovery import RecoveryEntry
from pyguibud.designer.theme import (
    NON_TEXT_CONTRAST,
    contrast,
    design_tokens,
    load_theme_specs,
)
from tests.designer.test_canvas_engine import HEADER, TWO_WINDOWS
from tests.designer.test_qa13a_abuse import _focused, _settle, app  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[2]
SPECS = [*load_theme_specs(), *load_theme_specs(brand=False)]


def _states(shell: DesignerApp) -> dict[str, bool]:
    """Toolbar action id -> enabled."""
    return {a.id: not b.instate(["disabled"]) for b, a in shell.shell._buttons}


def _open_two(shell: DesignerApp) -> Any:
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    document = shell.session.document
    assert document is not None
    return document.children[0].children[0]  # the Button "btn"


# ---------------------------------------------------------------- QA-14p-01 (MAJOR)
@pytest.mark.gui
def test_qa14p_01_toolbar_states_follow_the_selection(shell: DesignerApp) -> None:
    """Repro: open a file, click a widget. The toolbar Cut/Copy/Delete stay grey (the menus
    are right: they refresh on post). shell.py refresh_states() runs on report/document
    changes only, never on selection_changed (shell.py:191, _on_selection at :626)."""
    button = _open_two(shell)
    shell.root.update()
    assert not _states(shell)["edit.copy"]  # nothing selected
    shell.session.select(button, origin="canvas")
    _settle(shell.root)
    states = _states(shell)
    assert states["edit.copy"] and states["edit.cut"] and states["edit.delete"], states
    shell.session.select(None, origin="canvas")
    _settle(shell.root)
    states = _states(shell)
    assert not (states["edit.copy"] or states["edit.cut"] or states["edit.delete"]), states


# ---------------------------------------------------------------- QA-14p-02 (BLOCKER)
def _read_only_file(tmp_path: Path) -> Path:
    text = TWO_WINDOWS.replace('schema_version="1.0"', 'schema_version="1.7"').replace(
        '<prop name="text">Go</prop>', '<prop name="text">Go</prop><prop name="width">5</prop>'
    )
    path = tmp_path / "newer.ui"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.gui
def test_qa14p_02_read_only_spinbox_cannot_change_its_value_or_block_close(
    shell: DesignerApp, tmp_path: Path
) -> None:
    """Repro: open a file written by a newer PyGUIbud (schema 1.7, read-only), select the
    Button, press Up (or click an arrow) in the Width spinbox. The box shows 6 while the model
    keeps 5; from then on flush() is False with no message and no mark, so File > Close / New /
    Open, Copy and even the window's X (app.quit -> guard) silently do nothing. Escape is the
    only way out. Cause: D9 made read-only spinboxes ``readonly`` (editors.py set_enabled), and
    ttk's spinbox still spins in that state; inspector.commit() then refuses silently."""
    assert shell.open_path(_read_only_file(tmp_path))
    document, stack = shell.session.document, shell.session.stack
    assert document is not None and stack is not None and stack.read_only
    button = document.children[0].children[0]
    shell.session.select(button, origin="tree")
    _settle(shell.root)
    editor = shell.shell.inspector._editors["prop:width"]
    box = editor.widget
    assert isinstance(box, ttk.Spinbox) and "readonly" in box.state()
    shell.root.tk.call("ttk::spinbox::Spin", str(box), 1)  # what an arrow click / Up runs
    _settle(shell.root)
    assert box.get() == "5", "a read-only document's value must not appear to change"
    assert shell.shell.flush(), "an untouchable read-only editor must never block flush()"
    ran: list[bool] = []
    shell.guard(lambda: ran.append(True))  # File > Close / New / Open / Quit all go here
    assert ran, "the guard (and so Quit / the window's X) was silently blocked"


# ---------------------------------------------------------------- QA-14p-03 (MAJOR)
@pytest.mark.gui
def test_qa14p_03_a_toolbar_click_keeps_the_canvas_keys_working(shell: DesignerApp) -> None:
    """Repro: select a widget on the canvas, click the toolbar Copy button with the mouse, press
    Ctrl+V: nothing happens (no paste, no message). The ttk button takes the focus on click
    (takefocus=True, shell.py _build_toolbar), and the clipboard/Delete keys are scoped to the
    canvas and the tree. Keyboard Tab must still reach the buttons (spec 14p 4)."""
    button = _open_two(shell)
    shell.session.select(button, origin="canvas")
    shell.shell.refresh_states()
    shell.root.update()
    # The canvas's focus proxy itself: focus_first() on the withdrawn shared root leaves
    # focus_get() at "." (where the canvas keys are not bound); _focused maps the root first.
    target = shell.shell.canvas.focus_widget
    with _focused(shell.root, target):
        copy = next(b for b, a in shell.shell._buttons if a.id == "edit.copy")
        copy.event_generate("<Enter>", x=4, y=4)
        copy.event_generate("<ButtonPress-1>", x=4, y=4)
        _settle(shell.root)
        copy.event_generate("<ButtonRelease-1>", x=4, y=4)
        _settle(shell.root)
        focus = shell.root.focus_get()
        assert focus is not copy, "a mouse click on the toolbar must not take the keyboard focus"
        window = shell.session.document.children[0]  # type: ignore[union-attr]
        before = len(window.children)
        (focus or target).event_generate("<Control-v>")
        _settle(shell.root)
        assert len(window.children) == before + 1, "Ctrl+V after a toolbar click did nothing"


# ---------------------------------------------------------------- QA-14p-04 (MAJOR)
@pytest.mark.gui
@pytest.mark.parametrize("size", ['min_height="300"', 'min_width="320" min_height="220"'])
def test_qa14p_04_the_plate_frames_a_window_with_a_min_height(
    shell: DesignerApp, size: str
) -> None:
    """Repro: open examples/hello.ui-like files whose window sets min_height (the main_window
    and settings templates do): the plate sits 12 px up-left of the window (at the stage
    origin), sticks out above/left of the title bar and leaves the right and bottom edges
    unframed. canvas.py _on_stage_configure reads grid_bbox() at the stage's only <Configure>,
    before grid has applied the stage padding (it returns (0, 0, ...)); the fixed min_height
    keeps the stage size, so no second <Configure> corrects it."""
    text = (
        HEADER + f'<window id="w" kind="main" {size}><layout type="grid"/></window></pyguibud-ui>'
    )
    shell.session.open_result(read_ui_string(text, source="m"), name="m")
    _settle(shell.root, 5)
    stage = shell.shell.canvas.stages[0]
    box = stage.stage.grid_bbox(0, 0, 0, 2)
    assert box is not None and stage.view is not None
    info = stage.plate.place_info()
    assert (int(info["x"]), int(info["y"])) == (box[0], box[1]), (info, box)
    frame, plate = stage.view.frame, stage.plate
    assert plate.winfo_x() <= frame.winfo_x() - 1
    assert plate.winfo_x() + plate.winfo_width() >= frame.winfo_x() + frame.winfo_width() + 1
    assert plate.winfo_y() + plate.winfo_height() >= frame.winfo_y() + frame.winfo_height() + 1


# ---------------------------------------------------------------- QA-14p-05/06 (recovery)
_NOW = datetime.datetime.now(datetime.timezone.utc)
_LONG = {
    "posix": "/home/user/" + "x" * 80 + "/main.ui",
    "cjk": "C:\\用户\\文档\\非常长的项目文件夹名称\\设计\\界面\\第二版本\\最终版本"
    "\\主窗口设计文件.ui",
    "wide": "C:\\WWWWWWWWWWWWWWWWWWWW\\MMMMMMMMMMMMMMMMMMMMMMMM\\WWWWWWWWWWWWWWWW\\MMMMWWWW.ui",
}


def _dialog(shell: DesignerApp, tmp_path: Path, paths: list[str]) -> RecoveryDialog:
    entries = [RecoveryEntry(tmp_path, p, Path(p).name, _NOW) for p in paths]
    dialog = RecoveryDialog(shell.root, entries, restore=lambda *_a: None,
                            confirm=lambda *_a: None)  # fmt: skip
    dialog.open()
    _settle(shell.root)
    return dialog


def _overflow(dialog: RecoveryDialog) -> list[tuple[str, int, int]]:
    """(shown text, its width, the column width) of every row whose text is clipped."""
    tree = dialog.tree
    name = str(ttk.Style(tree).lookup("Treeview", "font") or "TkDefaultFont")
    font = tkfont.nametofont(name)
    width = int(tree.column("path", "width"))
    shown = [str(tree.set(iid, "path")) for iid in tree.get_children()]
    return [(s, font.measure(s), width) for s in shown if font.measure(s) > width]


@pytest.mark.gui
def test_qa14p_05_recovery_paths_are_elided_again_after_a_resize(
    shell: DesignerApp, tmp_path: Path
) -> None:
    """Repro: open the recovery dialog with a long path, make it wide, then narrow again: the
    Location column shows the whole path again and the file name is clipped off at the end
    (QA-14a1-17 is back). recovery.py _locations runs on the tree's <Configure>, where the
    path column still has its old (wide) width."""
    dialog = _dialog(shell, tmp_path, [_LONG["posix"]])
    try:
        assert not _overflow(dialog)  # the first layout is right
        dialog.window.geometry("1400x500")
        _settle(shell.root, 5)
        dialog.window.geometry("300x300")  # clamped to the dialog's minimum size
        _settle(shell.root, 5)
        assert not _overflow(dialog), _overflow(dialog)
    finally:
        dialog.close()


@pytest.mark.gui
@pytest.mark.parametrize("key", ["cjk", "wide"])
def test_qa14p_06_recovery_elision_fits_wide_glyphs(
    shell: DesignerApp, tmp_path: Path, key: str
) -> None:
    """Repro: a path of CJK characters (or of wide Latin glyphs) is elided to a character count
    (``pixels // measure("0")``, recovery.py _locations), so it is still wider than the column
    and Tk clips the end: the file name. Measure the text instead (present.fit_text exists)."""
    dialog = _dialog(shell, tmp_path, [_LONG[key]])
    try:
        assert not _overflow(dialog), _overflow(dialog)
    finally:
        dialog.close()


# ---------------------------------------------------------------- QA-14p-07 (MINOR)
def test_qa14p_07_a_deeply_nested_icon_file_is_rejected_as_defective() -> None:
    """Repro: replace designer/icons/icons.json with ``[[[[...]]]]`` (under the 256 KiB cap):
    json raises RecursionError, which parse_masks / load_masks do not catch (they catch
    ValueError / OSError), so the designer crashes at start instead of showing text only."""
    with pytest.raises(ValueError):
        parse_masks(b"[" * 100_000 + b"]" * 100_000)


# ---------------------------------------------------------------- guards (pass today)
@pytest.mark.parametrize(
    "payload",
    [b"", b"{}", b'{"icons": null}', b'{"icons": []}', b'{"icons": {"a": NaN}}',
     b'{"icons": {"a": {"16.0": "AA=="}}}', b'{"icons": {"a": {"16": 5}}}',
     b'{"icons": {"a": {"' + b"9" * 5000 + b'": "AA=="}}}'],
)  # fmt: skip
def test_guard_defective_icon_files_raise_value_error(payload: bytes) -> None:
    with pytest.raises(ValueError):
        parse_masks(payload)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: f"{s.name}-{s.role}")
def test_guard_the_panel_ring_reads_against_the_header_band(spec: Any) -> None:
    """The focused panel's 2 px ring touches the header band inside the panel (not gated by
    the spec table, which lists bg/stage/titlebar/selectbg)."""
    tokens = design_tokens(spec)
    assert contrast(tokens.ring, tokens.header) >= NON_TEXT_CONTRAST


@pytest.mark.gui
def test_guard_a_keyboard_hint_never_hides_a_refusal(shell: DesignerApp) -> None:
    _open_two(shell)
    shell.shell.show_message("refused: a reason")
    save = next(b for b, a in shell.shell._buttons if a.id == "file.save")
    save.event_generate("<FocusIn>")
    shell.root.update()
    assert str(shell.shell._status.cget("text")) == "refused: a reason"
    shell.shell.clear_message()
    save.event_generate("<FocusIn>")
    shell.root.update()
    assert str(shell.shell._status.cget("text")) == "Save (Ctrl+S)"


# ---------------------------------------------------------------- canvas = runtime (rule S)
_RICH = ROOT / "tests" / "codegen" / "data" / "rich.ui"
_OPTS = ("foreground", "background", "fieldbackground", "bordercolor", "lightcolor", "darkcolor",
         "font", "padding", "relief", "borderwidth", "selectbackground", "selectforeground",
         "insertcolor", "troughcolor", "arrowcolor", "rowheight", "indicatorcolor")  # fmt: skip
_STATES = ((), ("disabled",), ("readonly",), ("focus",), ("selected",), ("active",),
           ("pressed",), ("invalid",), ("hover",))  # fmt: skip
_TK_OPTS = ("background", "foreground", "font", "selectbackground", "selectforeground",
            "highlightbackground", "highlightcolor", "insertbackground", "relief")  # fmt: skip


def _looks(root: Any, widgets: list[Any]) -> dict[str, dict[str, str]]:
    """``"class|style"`` -> every resolved option that decides how the widget looks."""
    import tkinter

    from ttkbootstrap import Style

    style_cls: Any = Style  # ttkbootstrap ships no annotations for get_instance
    style = style_cls.get_instance()

    def font(value: str) -> str:
        try:
            return repr(sorted(tkfont.Font(root=root, font=value).actual().items()))
        except tkinter.TclError:
            return value

    looks: dict[str, dict[str, str]] = {}
    for widget in widgets:
        if isinstance(widget, (tkinter.Menu, tkinter.Toplevel)):
            continue
        cls = widget.winfo_class()
        try:
            name, themed = str(widget.cget("style")) or cls, True
        except tkinter.TclError:
            name, themed = cls, False
        look: dict[str, str] = {}
        if themed:
            for state in _STATES:
                for opt in _OPTS:
                    value = str(style.lookup(name, opt, list(state) or None, ""))
                    look[f"{'/'.join(state) or 'normal'}:{opt}"] = (
                        font(value) if opt == "font" and value else value
                    )
            look["layout"] = repr(style.layout(name))
        else:
            for opt in _TK_OPTS:
                try:
                    value = str(widget.cget(opt))
                except tkinter.TclError:
                    continue
                look[opt] = font(value) if opt == "font" else value
        looks.setdefault(f"{cls}|{name}", look)
    return looks


def _walk(widget: Any) -> list[Any]:
    out: list[Any] = []
    for child in widget.winfo_children():
        out += [child, *_walk(child)]
    return out


def parity_runtime(folder: str, out: str) -> int:
    """Phase 1, fresh process: the runtime build of rich.ui per theme, before any chrome."""
    import json
    import shutil
    import tkinter

    from ttkbootstrap import App, Style

    from pyguibud.designer import theme_tk
    from pyguibud_runtime import load_ui
    from tests.designer.test_styling_layer import _base_part

    root = App(title="parity-runtime")
    root.withdraw()
    target = Path(folder) / "rich.ui"
    shutil.copy(_RICH, target)
    picture = tkinter.PhotoImage(master=root, width=8, height=8)
    picture.put("#336699", to=(0, 0, 8, 8))
    picture.write(str(Path(folder) / "pic.gif"), format="gif")
    picture.write(str(Path(folder) / "pic.ppm"), format="ppm")
    specs = load_theme_specs()
    style_cls: Any = Style  # ttkbootstrap ships no annotations for get_instance
    style = style_cls.get_instance()
    theme_tk.install_themes(style, specs)
    result = {}
    for spec in specs:
        _base_part(root, spec)
        ui = load_ui(target, strict=False, master=root)
        root.update_idletasks()
        tops = [w for w in root.winfo_children() if isinstance(w, tkinter.Toplevel)]
        result[spec.role] = _looks(root, [w for top in tops for w in _walk(top)] + _walk(root))
        ui.destroy()
    Path(out).write_text(json.dumps(result), encoding="utf-8")
    root.destroy()
    return 0


def parity_designer(folder: str, baseline_file: str) -> int:
    """Phase 2, fresh process: the designer after theme cycles and language switches."""
    import json

    from ttkbootstrap import App

    from pyguibud.designer import theme_tk
    from pyguibud.designer.theme import ROLES, spec_for_role

    baseline = json.loads(Path(baseline_file).read_text(encoding="utf-8"))
    root = App(title="parity-designer")
    root.withdraw()
    specs = load_theme_specs()
    designer = DesignerApp(root, specs=specs)
    designer.open_path(Path(folder) / "rich.ui")
    for role in (*ROLES, *ROLES):
        designer.set_theme(role)
        designer.flush_theme()
    for code in ("es_ES", "en_XA", "de_DE", "en_GB"):
        designer.set_language(code)
    root.update()
    leaks: list[str] = []
    panel = designer.shell.canvas
    for role in ROLES:
        designer.set_theme(role)
        designer.flush_theme()
        spec = spec_for_role(specs, role)
        assert spec is not None
        theme_tk.apply_fonts(root, spec)  # the baseline ran it last too
        looks: dict[str, dict[str, str]] = {}
        for stage in panel.stages:
            panel.show_window(stage.window)
            root.update_idletasks()
            if stage.view is not None:
                looks |= _looks(root, [stage.view.frame, *_walk(stage.view.frame)])
        for key, look in looks.items():
            base = baseline[role].get(key)
            if base is None:
                leaks.append(f"{role} {key}: not in the runtime build")
                continue
            leaks += [f"{role} {key} {o}: runtime={base.get(o)!r} canvas={v!r}"
                      for o, v in look.items() if base.get(o) != v]  # fmt: skip
    designer.dispose()
    root.destroy()
    for leak in leaks[:50]:
        print(leak)
    return 1 if leaks else 0


@pytest.mark.gui
def test_guard_canvas_widgets_look_exactly_like_a_runtime_build(tmp_path: Path) -> None:
    """Rule S end to end: every (class, style) of rich.ui resolves to the same colours, fonts,
    paddings and layout on the canvas (after theme cycles and language switches) as in a
    ``load_ui`` build of the same theme in a process that never built the designer."""
    out = tmp_path / "runtime.json"

    def run(code: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                              text=True, timeout=180, check=False)  # fmt: skip

    mod = "from tests.designer.test_qa14p_abuse import "
    first = run(f"{mod}parity_runtime; exit(parity_runtime({str(tmp_path)!r}, {str(out)!r}))")
    assert first.returncode == 0, first.stdout[-2000:] + first.stderr[-2000:]
    second = run(f"{mod}parity_designer; exit(parity_designer({str(tmp_path)!r}, {str(out)!r}))")
    assert second.returncode == 0, second.stdout[-3000:] + second.stderr[-2000:]
