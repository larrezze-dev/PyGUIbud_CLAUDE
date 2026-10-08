"""QA regressions of Step 12 (designer shell): abuse that must be blocked gracefully.

Each test names its QA-12-NN finding (Step 12i QA pass). The Tk tests share the package root
(``conftest.designer_root``); anything that needs its own root runs in a subprocess.
"""

from __future__ import annotations

import subprocess
import sys
import time
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.core import Document, ReadResult, Widget, Window, default_registry
from pyguibud.designer import theme as theme_module
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.new_file import NewFileDialog
from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.theme import (
    contrast,
    load_theme_specs,
    parse_theme_data,
    readable,
    spec_for_role,
    tag_colours,
)
from pyguibud.designer.themes import NEUTRAL_SPECS

ALL_SPECS = (*load_theme_specs(), *NEUTRAL_SPECS)


# ---------------------------------------------------------------- QA-12-01: tag contrast
@pytest.mark.parametrize("spec", ALL_SPECS, ids=lambda s: s.name)
def test_row_tag_colours_are_readable_on_rows_and_selection(spec: Any) -> None:
    rows = (spec.colors["inputbg"], spec.colors["selectbg"])
    for tag, colour in tag_colours(spec).items():
        for background in rows:
            assert contrast(colour, background) >= 4.5, (spec.name, tag, colour, background)


def test_readable_keeps_a_colour_that_already_passes() -> None:
    assert readable("#000000", ("#FFFFFF",), "#333333") == "#000000"
    lifted = readable("#333C48", ("#15181D",), "#F2F4F6")  # sape-dark muted, 1.6:1 before
    assert lifted != "#333C48"
    assert contrast(lifted, "#15181D") >= 4.5


@pytest.mark.gui
@pytest.mark.parametrize("role", ["light", "dark", "high_contrast"])
def test_panels_paint_the_readable_tag_colours(shell: DesignerApp, role: str) -> None:
    shell.set_theme(role)
    shell.flush_theme()
    spec = spec_for_role(shell.specs, role)
    assert spec is not None
    expected = tag_colours(spec)
    tree = shell.shell.tree.tree
    assert tree is not None
    muted = ttk.Style().lookup("Muted.TLabel", "foreground")  # the inspector's default rows
    assert str(muted).upper() == expected["muted"]
    assert str(tree.tag_configure("error", "foreground")).upper() == expected["error"]


# ---------------------------------------------------------------- QA-12-02: dialog focus
@pytest.mark.gui
def test_wizard_opens_with_the_keyboard_on_the_template_list(shell: DesignerApp) -> None:
    shell.open_new_file()
    dialog = shell._live_dialogs()[0]
    assert isinstance(dialog, NewFileDialog)
    shell.root.update()
    assert str(dialog.window.focus_lastfor()) == str(dialog.list)


@pytest.mark.gui
def test_cheat_sheet_opens_with_the_keyboard_on_close(shell: DesignerApp) -> None:
    shell.open_shortcuts()
    dialog = shell._live_dialogs()[0]
    assert isinstance(dialog, ShortcutsDialog)
    shell.root.update()
    assert str(dialog.window.focus_lastfor()) == str(dialog.close_button)


# ---------------------------------------------------------------- QA-12-04: one modal at a time
@pytest.mark.gui
def test_a_second_dialog_never_stacks_on_an_open_one(shell: DesignerApp) -> None:
    shell.registry.invoke("file.new")
    shell.registry.invoke("help.shortcuts")
    shell.registry.invoke("file.new")
    live = shell._live_dialogs()
    assert [type(d) for d in live] == [NewFileDialog]


# ---------------------------------------------------------------- QA-12-03: sashes
@pytest.mark.gui
def test_sashes_dragged_to_the_edges_keep_every_heading_visible(shell: DesignerApp) -> None:
    root = shell.root
    root.deiconify()
    try:
        root.geometry("1000x600")
        root.update()
        body: Any = shell.shell.body  # ttk.PanedWindow.sashpos is unannotated
        right: Any = shell.shell.right
        body.sashpos(0, 0)
        body.sashpos(1, 100_000)
        right.sashpos(0, 0)
        root.update()
        shell.shell.clamp_sashes()
        root.update()
        for panel in shell.shell.panels:
            assert panel.heading.winfo_ismapped(), panel.name
            assert panel.frame.winfo_width() >= panel.heading.winfo_reqwidth(), panel.name
            assert panel.frame.winfo_height() >= panel.heading.winfo_reqheight(), panel.name
    finally:
        root.withdraw()


# ---------------------------------------------------------------- QA-12-05: corrupt sape.json
def test_deeply_nested_theme_json_is_a_defect_not_a_crash() -> None:
    with pytest.raises(ValueError, match="nested too deeply"):
        parse_theme_data(b"[" * 60_000)


def test_deeply_nested_sape_json_falls_back_to_neutral(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    (tmp_path / "sape.json").write_bytes(b'{"themes": ' + b"[" * 60_000)

    class Files:
        @staticmethod
        def files(_package: str) -> Any:
            return tmp_path

    monkeypatch.setattr(theme_module, "resources", Files)
    assert load_theme_specs() == NEUTRAL_SPECS


# ---------------------------------------------------------------- QA-12-06: big documents
def test_nodes_beyond_ten_thousand_can_be_selected() -> None:
    document = Document()
    window = Window(id="main")
    document.add_window(window)
    for index in range(10_050):
        window.append_child(Widget(class_name="Label", id=f"l{index}"))
    session = DesignerSession(default_registry())
    session.open_result(
        ReadResult(
            document=document, warnings=(), read_only=False, source_version="1.0", source="big"
        ),
        name="big",
    )
    last = window.children[-1]
    session.select(last, origin="tree")
    assert session.selection.node is last


# ---------------------------------------------------------------- QA-12-07/08: run() in a process
_RUN = """
import _thread, sys, threading, time
{patch}
threading.Thread(target=lambda: (time.sleep(1.5), _thread.interrupt_main()), daemon=True).start()
from pyguibud.designer import launch
start = time.perf_counter()
code = launch("en_GB", "light")
print(f"{{code}} {{time.perf_counter() - start:.1f}}")
"""
_DAMAGED = (
    "import pyguibud.designer.session as s\ns.template_bytes = lambda info: b'<ui><garbage'\n"
)


@pytest.mark.gui
@pytest.mark.parametrize("patch", ["", _DAMAGED], ids=["normal", "damaged-start-template"])
def test_ctrl_c_exits_130_promptly_and_quietly(patch: str) -> None:
    """Ctrl+C is noticed while the loop is idle (it waited for the next Tk event before)."""
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", _RUN.format(patch=patch)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    code, seconds = result.stdout.split()
    assert code == "130", result.stderr
    assert float(seconds) < 8, "Ctrl+C was only noticed late"
    assert time.perf_counter() - started < 60
    assert "Traceback" not in result.stderr
    if patch:
        assert "damaged" in result.stderr  # one log line, no traceback
