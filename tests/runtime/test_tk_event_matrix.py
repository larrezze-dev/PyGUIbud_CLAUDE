"""The Tk half of the event matrix (spec backends §7): every ``(class, event)`` pair of the core
specs, triggered through ``invoke``/``event_generate``/a real edit, calls its handler exactly once,
on ttkbootstrap and on plain tkinter. The Qt half is ``tests/qt/test_qt_behaviour.py``."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.keys import tk_key_sequences
from pyguibud.core.widgets import core_widgets
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui

pytestmark = pytest.mark.gui

_SKIP = {"Menubar", "Menu", "Action", "Statusbar"}
_P = "<pack/>"
_MENU = (
    '<menubar><menu id="mnu"><prop name="text">_File</prop>'
    '<action id="act" handler="h_action_0"><prop name="text">_Go</prop></action>'
    "</menu></menubar>"
)


class Calls(Counter[str]):
    def handlers(self, names: list[str]) -> dict[str, Callable[[], None]]:
        def handler(name: str) -> Callable[[], None]:
            return lambda: self.update([name])

        return {name: handler(name) for name in names}


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


def _matrix_ui() -> tuple[str, list[tuple[str, str]]]:
    """One widget per core class with every event it supports (+ a key on focusable classes)."""
    pairs: list[tuple[str, str]] = []
    body: list[str] = []
    for spec in core_widgets():
        if spec.name in _SKIP or not spec.events:
            continue
        events = [*spec.events, *(("key:Ctrl+K",) if "focus_in" in spec.events else ())]
        wid = spec.name.lower()
        tags = "".join(f'<event name="{e}" handler="h_{wid}_{i}"/>' for i, e in enumerate(events))
        pairs += [(spec.name, e) for e in events]
        inner = ""
        if spec.name == "Notebook":
            inner = "".join(
                f'<widget class="Frame" id="pg{i}"><layout type="pack"/>'
                f'<page><prop name="text">P{i}</prop></page></widget>'
                for i in range(2)
            )
        if spec.name in ("Frame", "LabelFrame", "ScrolledFrame"):
            inner = '<layout type="pack"/>'
        body.append(f'<widget class="{spec.name}" id="{wid}">{tags}{inner}{_P}</widget>')
    pairs.append(("Action", "command"))
    windows = f'<window id="main" kind="main">{_MENU}<layout type="pack"/>{"".join(body)}</window>'
    return windows, pairs


def _key(w: Any, sequence: str) -> None:
    w.focus_force()
    w.update()
    w.event_generate(sequence, when="now")


def _trigger(ui: LoadedUi, name: str, event: str) -> None:
    if name == "Action":
        ui.mnu.invoke(ui.act)
        return
    w: Any = getattr(ui, name.lower())
    aqua = w.tk.call("tk", "windowingsystem") == "aqua"
    if event in ("focus_in", "focus_out"):
        w.event_generate("<FocusIn>" if event == "focus_in" else "<FocusOut>", when="now")
    elif event.startswith("key:"):
        _key(w, tk_key_sequences(event[4:], aqua=aqua)[0])
    elif event == "command" or (name, event) in (
        ("Checkbutton", "change"),
        ("Radiobutton", "change"),
    ):
        w.invoke()  # a radio invoke writes its variable even when it is already selected
    elif (name, event) == ("Scrollbar", "change"):  # what a click on the arrow calls
        w.tk.call(*w.tk.splitlist(w.cget("command")), "scroll", 1, "units")
    elif event == "change":
        {
            "Entry": lambda: w.insert(0, "x"),
            "Text": lambda: w.insert("1.0", "x"),
            "Combobox": lambda: w.insert(0, "x"),
            "Spinbox": lambda: w.insert(0, "5"),
            "Scale": lambda: w.set(5),
        }[name]()
    elif (name, event) == ("Notebook", "select"):
        w.select(1)
    elif (name, event) == ("Combobox", "select"):
        w.configure(values=("a",))
        w.current(0)
        w.event_generate("<<ComboboxSelected>>", when="now")  # what Tk sends on a pick
    elif (name, event) == ("Listbox", "select"):
        w.insert("end", "row")
        w.selection_set(0)
        w.event_generate("<<ListboxSelect>>", when="now")  # what Tk sends on a click
    elif (name, event) == ("Treeview", "select"):
        w.selection_set(w.insert("", "end", text="row"))  # Tk itself sends <<TreeviewSelect>>
    else:  # activate of Entry, Listbox, Treeview
        _key(w, "<Return>")
    w.update()


#: Regression (Step 16c): Tk calls a Scrollbar ``command`` with ``("scroll", 1, "units")`` /
#: ``("moveto", f)``; ``_tk._events`` and the generated ``_command`` must drop those arguments
#: (runtime spec §4.1: every handler is called with none).
_SCROLLBAR = {("Scrollbar", "change")}


def _build(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    backend: str,
) -> tuple[LoadedUi, Calls, list[tuple[str, str]]]:
    windows, pairs = _matrix_ui()
    names = [f"h_{c.lower()}_{i}" for c in dict.fromkeys(c for c, _ in pairs) for i in range(30)]
    calls = Calls()
    path = write_ui(tmp_path / "m.ui", windows)
    ui = load_ui(path, calls.handlers(names), backend=backend, master=tk_root)
    loaded.append(ui)
    ui.main.deiconify()
    ui.main.update()
    assert not calls  # building fires nothing
    return ui, calls, pairs


def _check(
    ui: LoadedUi, calls: Calls, pairs: list[tuple[str, str]], only: set[tuple[str, str]]
) -> None:
    index: Counter[str] = Counter()
    for name, event in pairs:
        handler = f"h_{name.lower()}_{index[name]}"
        index[name] += 1
        if (name, event) not in only:
            continue
        calls.clear()
        _trigger(ui, name, event)
        assert calls[handler] == 1, (name, event, dict(calls))


@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_event_matrix_each_pair_calls_its_handler_once(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    backend: str,
) -> None:
    ui, calls, pairs = _build(tmp_path, tk_root, loaded, backend)
    _check(ui, calls, pairs, set(pairs))
    assert len(pairs) > 30 and set(pairs) >= _SCROLLBAR


@pytest.mark.parametrize("backend", ["ttkbootstrap", "tkinter"])
def test_scrollbar_change_calls_its_handler_with_no_arguments(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],
    backend: str,
) -> None:
    ui, calls, pairs = _build(tmp_path, tk_root, loaded, backend)
    _check(ui, calls, pairs, _SCROLLBAR)


def test_generated_scrollbar_change_calls_its_handler_with_no_arguments(
    tmp_path: Path,
    tk_root: Any,
) -> None:
    import runpy

    from pyguibud.codegen import generate_python
    from pyguibud.core.xml_io import read_ui

    body = '<widget class="Scrollbar" id="sbr"><event name="change" handler="h"/><pack/></widget>'
    path = write_ui(
        tmp_path / "s.ui", f'<window id="main" kind="main"><layout type="pack"/>{body}</window>'
    )
    module = tmp_path / "s_ui.py"
    generated = generate_python(read_ui(str(path)), str(path), output=str(module))
    module.write_text(generated.text, encoding="utf-8", newline="\n")
    ui = runpy.run_path(str(module), run_name="generated")[generated.class_name]()
    calls = Calls()
    ui.setup_ui(tk_root, calls.handlers(["h"]))
    try:
        w = ui.sbr
        w.tk.call(*w.tk.splitlist(w.cget("command")), "scroll", 1, "units")
        w.update()
        assert calls["h"] == 1
    finally:
        ui.destroy()
