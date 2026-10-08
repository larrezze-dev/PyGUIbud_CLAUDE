"""Regression tests for the core side of QA pass 1 of Step 14a.1 (grid limit, colours, chords)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pyguibud.core import default_registry, read_ui, validate
from pyguibud.core.colours import colour_problem
from pyguibud.core.commands import CommandStack, SetEvents, SetField
from pyguibud.core.keys import key_bindings
from pyguibud.core.model import Document, Event, GridCell, Widget
from pyguibud.core.validate import MAX_GRID_INDEX

HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"


def _stack() -> tuple[Document, CommandStack]:
    document = read_ui(HELLO).document
    return document, CommandStack(document, default_registry(), source="qa")


def _first(document: Document, class_name: str) -> Widget:
    return next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == class_name)


# ---------------------------------------------------------------- QA-14a1-01: Tk's grid limit
@pytest.mark.parametrize(
    ("row", "column", "rowspan", "columnspan", "ok"),
    [
        (9998, 0, 1, 1, True),
        (9999, 0, 1, 1, False),
        (0, 9998, 1, 1, True),
        (0, 9998, 1, 2, False),
        (0, 0, 9999, 1, True),
        (0, 0, 10_000, 1, False),
        (9997, 0, 2, 1, True),
        (9997, 0, 3, 1, False),
    ],
)
def test_grid_cells_follow_tk_limits(
    row: int, column: int, rowspan: int, columnspan: int, ok: bool
) -> None:
    document, stack = _stack()
    label = _first(document, "Label")
    cell = GridCell(row=row, column=column, rowspan=rowspan, columnspan=columnspan)
    assert stack.execute(SetField(label, "placement", cell)).accepted is ok


def test_grid_limit_is_shared_with_the_designer() -> None:
    from pyguibud.designer.properties import field_rows
    from pyguibud.designer.targets import MAX_INDEX

    document = _stack()[0]
    rows = {f.key: f for f in field_rows([_first(document, "Label")], default_registry(), document)}
    assert MAX_INDEX == MAX_GRID_INDEX == 9998
    assert rows["place:grid:row"].maximum == rows["place:grid:column"].maximum == MAX_GRID_INDEX
    assert rows["place:grid:rowspan"].maximum == MAX_GRID_INDEX + 1


_TK_GRID = """
import sys, tkinter
from pyguibud.core.validate import MAX_GRID_INDEX as M
try:
    root = tkinter.Tk()
except tkinter.TclError:
    sys.exit(3)
root.withdraw()
tkinter.Label(root).grid(row=M, column=M)
tkinter.Label(root).grid(row=0, column=0, rowspan=M + 1, columnspan=M + 1)
for options in ({"row": M + 1, "column": 0}, {"row": 0, "column": M, "columnspan": 2}):
    try:
        tkinter.Label(root).grid(**options)
    except tkinter.TclError:
        continue
    sys.exit("Tk accepted %r" % options)
"""


def _in_tk(code: str) -> None:
    """Run ``code`` with a Tk root in a subprocess (core tests never share the designer root)."""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            timeout=120, check=False)  # fmt: skip
    if result.returncode == 3:
        pytest.skip("needs a Tk display")
    assert result.returncode == 0, result.stderr[-800:] or result.stdout[-800:]


def test_the_validator_grid_limit_is_tks() -> None:
    _in_tk(_TK_GRID)


# ---------------------------------------------------------------- QA-14a1-02: colours
@pytest.mark.parametrize(
    "text",
    ["#abc", "#AABBCC", "#aabbccddeeff", "red", "RED", "light blue", "LightBlue", "alice blue",
     "Light Goldenrod Yellow", "azure4", "gray0", "grey100", "Gray57", "crimson", "DarkSlateGray3"],
)  # fmt: skip
def test_portable_colours_are_accepted(text: str) -> None:
    assert colour_problem(text) is None


@pytest.mark.parametrize(
    "text",
    ["blurple", "transparent", "al ice blue", " red", "red ", "light  blue", "azure5", "azure0",
     "gray101", "gray01", "AntiqueWhite 1", "darkslategrey1", "#abcd", "#12345", "", "réd",
     "rgb(0,0,0)", "red;", "Red2 "],
)  # fmt: skip
def test_unknown_colour_names_are_refused(text: str) -> None:
    assert colour_problem(text) == "unknown"


@pytest.mark.parametrize("text", ["SystemButtonFace", "systemWindowBody", "SYSTEMHIGHLIGHT"])
def test_system_colours_are_refused_as_not_portable(text: str) -> None:
    assert colour_problem(text) == "system"


_TK_COLOURS = """
import sys, tkinter
from pyguibud.core.colours import _NAMES, colour_problem
try:
    root = tkinter.Tk()
except tkinter.TclError:
    sys.exit(3)
root.withdraw()
for low, (name, variants) in _NAMES.items():
    last = 100 if variants == 8 else variants
    for text in (low, name, *(f"{name}{n}" for n in range(1, last + 1))):
        assert colour_problem(text) is None, text
        root.winfo_rgb(text)  # raises "unknown color name" if Tk does not know it
    for text in (f"{name}{last + 1}", f"{name}0", f" {name}", f"{name} "):
        if colour_problem(text) is not None:
            try:
                root.winfo_rgb(text)
            except tkinter.TclError:
                continue
            sys.exit("Tk knows %r" % text)
"""


def test_every_table_colour_is_known_to_tk() -> None:
    """The frozen table (Tk 8.6.15 ``xcolors.c``) agrees with the Tk that runs the tests."""
    _in_tk(_TK_COLOURS)


def test_the_validator_explains_a_system_colour(tmp_path: Path) -> None:
    text = HELLO.read_text(encoding="utf-8")
    start = text.index('<widget class="Label" id="lbl_about">')
    end = text.index("</widget>", start) + len("</widget>")
    canvas = (
        '<widget class="Canvas" id="cnv"><prop name="background">{}</prop>'
        '<pack fill="both"/></widget>'
    )
    messages = {}
    for value in ("SystemButtonFace", "blurple", "light blue"):
        target = tmp_path / f"{value.replace(' ', '_')}.ui"
        target.write_text(text[:start] + canvas.format(value) + text[end:], encoding="utf-8")
        report = validate(read_ui(target).document, default_registry())
        messages[value] = [f.message for f in report.errors if f.code == "validate.bad_prop_value"]
    assert "one platform" in messages["SystemButtonFace"][0]
    assert "must be a colour" in messages["blurple"][0]
    assert messages["light blue"] == []


# ---------------------------------------------------------------- QA-14a1-14: chords
@pytest.mark.parametrize(
    ("first", "second", "same"),
    [
        ("Ctrl+S", "<Control-s>", True),
        ("Ctrl+S", "<Control-S>", True),
        ("ctrl+s", "<Control-KeyPress-s>", True),
        ("<Control-Key-s>", "<Control-s>", True),
        ("Ctrl+Shift+S", "<Shift-Control-s>", True),
        ("Ctrl+5", "<Control-Key-5>", True),
        ("Enter", "<Return>", True),
        ("Ctrl+S", "Ctrl+Shift+S", False),
        ("Ctrl+S", "<Alt-s>", False),
        ("F5", "<F6>", False),
    ],
)
def test_key_bindings_compare_spellings(first: str, second: str, same: bool) -> None:
    assert bool(key_bindings(first) & key_bindings(second)) is same


def test_key_bindings_of_an_invalid_sequence_is_empty() -> None:
    assert key_bindings("<<Nope>>") == frozenset()


@pytest.mark.parametrize("other", ["<Control-KeyPress-s>", "<Control-S>", "ctrl+s"])
def test_the_validator_refuses_one_chord_in_two_spellings(other: str) -> None:
    document, stack = _stack()
    button = _first(document, "Button")
    events = [*button.events, Event(name="key:Ctrl+S", handler="on_a"),
              Event(name=f"key:{other}", handler="on_b")]  # fmt: skip
    outcome = stack.execute(SetEvents(button, events))
    assert not outcome.accepted and "more than once" in outcome.message


def test_different_chords_are_still_two_events() -> None:
    document, stack = _stack()
    button = _first(document, "Button")
    events = [*button.events, Event(name="key:Ctrl+S", handler="on_a"),
              Event(name="key:Ctrl+Shift+S", handler="on_b")]  # fmt: skip
    assert stack.execute(SetEvents(button, events)).accepted


@pytest.mark.parametrize(("index", "ok"), [(9999, True), (10_000, False)])
def test_grid_lines_follow_tk_rowconfigure(index: int, ok: bool) -> None:
    from dataclasses import replace

    from pyguibud.core.model import GridLine, Window

    document, stack = _stack()
    owner = next(
        n
        for n in document.walk()
        if isinstance(n, Widget | Window) and n.layout is not None and n.layout.type == "grid"
    )
    assert owner.layout is not None
    layout = replace(owner.layout, rows=(GridLine(index=index, weight=1),))
    assert stack.execute(SetField(owner, "layout", layout)).accepted is ok
