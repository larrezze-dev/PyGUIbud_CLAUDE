"""The plain ``tkinter`` backend (spec backends D2-D5, D20), built into the session root."""

from __future__ import annotations

import logging
import subprocess
import sys
import tkinter
from collections.abc import Iterator
from pathlib import Path
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.backends.base import RootExistsError
from pyguibud.backends.tkinter import TkinterBackend
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.gui


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


def test_the_backends_tkinter_is_the_standard_library_one() -> None:
    import pyguibud.backends.tkinter as ours

    assert ours is not tkinter and tkinter.Tk.__module__ == "tkinter"
    assert "site-packages" not in str(tkinter.__file__)


def test_it_never_imports_ttkbootstrap() -> None:
    code = (
        "import sys, pyguibud.backends.tkinter, pyguibud.backends._tk;"
        "sys.exit('ttkbootstrap' in sys.modules)"
    )
    assert subprocess.run([sys.executable, "-c", code], check=False).returncode == 0


def test_hello_builds_with_plain_ttk_widgets(tk_root: Any, loaded: list[LoadedUi]) -> None:
    ui = load_ui(EXAMPLES / "hello.ui", None, strict=False, backend="tkinter", master=tk_root)
    loaded.append(ui)
    assert type(ui.btn_greet) is ttk.Button and type(ui.ent_name) is ttk.Entry
    assert ui.btn_greet.cget("style") == ""  # no bootstyle
    assert ui.mnu_file.entrycget(0, "accelerator") == "Ctrl+Q"


def test_a_tb_bootstyle_gives_one_log_line(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    buttons = "".join(
        f'<widget class="Button" id="b{i}" tb:bootstyle="success"><prop name="text">x</prop>'
        "<pack/></widget>"
        for i in range(5)
    )
    path = write_ui(
        tmp_path / "s.ui",
        f'<window id="main" kind="main"><layout type="pack"/>{buttons}</window>',
    )
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        loaded.append(load_ui(path, None, strict=False, backend="tkinter", master=tk_root))
    notes = [r.getMessage() for r in caplog.records if "ignored by the tkinter" in r.getMessage()]
    assert notes == ["5 ttkbootstrap styles (tb:bootstyle) are ignored by the tkinter toolkit."]


def test_a_scrolled_frame_scrolls_and_leaves_nothing_behind(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path
) -> None:
    labels = "".join(
        f'<widget class="Label" id="l{i}"><prop name="text">row {i}</prop><pack/></widget>'
        for i in range(40)
    )
    path = write_ui(
        tmp_path / "s.ui",
        '<window id="main" kind="main"><layout type="pack"/>'
        '<widget class="ScrolledFrame" id="sf"><prop name="height">60</prop>'
        f'<layout type="pack"/><pack fill="both" expand="true"/>{labels}</widget></window>',
    )
    ui = load_ui(path, None, strict=False, backend="tkinter", master=tk_root)
    loaded.append(ui)
    ui.main.update()
    first, last = ui.sf._canvas.yview()
    assert first == 0.0 and last < 1.0
    ui.sf._canvas.yview_scroll(2, "units")
    assert ui.sf._canvas.yview()[0] > 0.0


def test_prepare_checks_master_and_root() -> None:
    with pytest.raises(TypeError):
        TkinterBackend().prepare(object())
    root = tkinter.Tk()
    try:
        with pytest.raises(RootExistsError):
            TkinterBackend().prepare(None)
    finally:
        root.destroy()


def test_an_unknown_backend_name_is_backend_unavailable() -> None:
    with pytest.raises(UiError) as caught:
        load_ui(EXAMPLES / "hello.ui", None, strict=False, backend="nope")
    assert caught.value.code == "runtime.backend_unavailable"
