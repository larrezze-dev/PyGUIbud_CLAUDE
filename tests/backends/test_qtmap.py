"""The pure Qt tables of the PySide6 backend (spec backends §7, pure part); no toolkit."""

from __future__ import annotations

import itertools

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.backends._qtmap import (
    SELECTMODE,
    SIGNALS,
    STEPS,
    UNITS,
    alignment,
    decimals,
    escape_title,
    pack_item,
    qt_key_sequences,
    qt_shortcut,
    qt_text,
    scaled_range,
    split_qt_text,
)
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.registry import default_registry
from pyguibud.core.widgets import core_widgets

STICKIES = ["".join(c) for n in range(5) for c in itertools.combinations("nsew", n)]


def _qt_parse(text: str) -> tuple[str, int]:
    """What Qt shows for a mnemonic text: ``&&`` is ``&``, the first ``&x`` marks ``x``."""
    out: list[str] = []
    marked = -1
    i = 0
    while i < len(text):
        char = text[i]
        if char == "&" and i + 1 < len(text):
            following = text[i + 1]
            if following != "&" and marked < 0:
                marked = len(out)
            out.append(following)
            i += 2
        else:
            out.append(char)
            i += 1
    return "".join(out), marked


@pytest.mark.parametrize("sticky", STICKIES)
def test_alignment_of_every_sticky_form(sticky: str) -> None:
    names = alignment(sticky)
    h = {"we": None, "w": "AlignLeft", "e": "AlignRight", "": "AlignHCenter"}
    v = {"ns": None, "n": "AlignTop", "s": "AlignBottom", "": "AlignVCenter"}
    expected = [
        h["".join(c for c in "we" if c in sticky)],
        v["".join(c for c in "ns" if c in sticky)],
    ]
    assert names == tuple(name for name in expected if name is not None)


def test_sixteen_sticky_forms() -> None:
    assert len(STICKIES) == 16 and alignment("nsew") == ()
    assert alignment("") == ("AlignHCenter", "AlignVCenter")


@pytest.mark.parametrize(
    ("orient", "fill", "expand", "expected"),
    [
        ("vertical", "none", False, (0, ("AlignHCenter",))),
        ("vertical", "x", False, (0, ())),
        ("vertical", "none", True, (1, ("AlignHCenter", "AlignVCenter"))),
        ("vertical", "y", True, (1, ("AlignHCenter",))),
        ("vertical", "both", True, (1, ())),
        ("horizontal", "none", False, (0, ("AlignVCenter",))),
        ("horizontal", "y", False, (0, ())),
        ("horizontal", "x", True, (1, ("AlignVCenter",))),
        ("horizontal", "none", True, (1, ("AlignVCenter", "AlignHCenter"))),
        ("horizontal", "both", True, (1, ())),
    ],
)
def test_pack_item(orient: str, fill: str, expand: bool, expected: object) -> None:
    assert pack_item(orient, fill, expand) == expected


@pytest.mark.parametrize(
    ("raw", "mnemonic", "expected"),
    [
        ("_File", True, "&File"),
        ("Save & _quit", True, "Save && &quit"),
        ("a__b", True, "a_b"),
        ("<b>x</b> & y", True, "<b>x</b> && y"),
        ("<b>x</b> & _y", False, "<b>x</b> & _y"),
        ("_&x", True, "&&x"),  # an ampersand is never marked
        ("", True, ""),
    ],
)
def test_qt_text_examples(raw: str, mnemonic: bool, expected: str) -> None:
    text, underline = split_mnemonic(raw) if mnemonic else (raw, -1)
    assert qt_text(text, underline, mnemonic) == expected


@given(st.text(alphabet="ab&_<> .", max_size=30))
def test_qt_text_round_trips_display_text_and_mnemonic(raw: str) -> None:
    text, underline = split_mnemonic(raw)
    shown, marked = _qt_parse(qt_text(text, underline, True))
    assert shown == text
    expected = underline if 0 <= underline < len(text) and text[underline] != "&" else -1
    assert marked == expected


@given(st.text(alphabet="ab&_<> .", max_size=30))
def test_split_qt_text_reads_what_qt_shows(raw: str) -> None:
    text, underline = split_mnemonic(raw)
    marked = qt_text(text, underline, True)
    assert split_qt_text(marked) == _qt_parse(marked)
    assert split_qt_text(marked)[0] == text


@given(st.text(max_size=40))
def test_qt_text_without_mnemonic_is_verbatim(text: str) -> None:
    assert qt_text(text, 0, False) == text


@pytest.mark.parametrize(
    ("title", "expected"),
    [("A [*] B", "A [*][*] B"), ("plain", "plain"), ("[*][*]", "[*][*][*][*]")],
)
def test_escape_title(title: str, expected: str) -> None:
    assert escape_title(title) == expected


@pytest.mark.parametrize(
    ("minimum", "maximum", "low", "high", "inverted"),
    [
        (0.0, 100.0, 0, 100, False),
        (-5.0, 5.0, -5, 5, False),
        (100.0, 0.0, 0, 100, True),
        (0.0, 1.0, 0, 1, False),
        (0.0, 0.5, 0, STEPS, False),
        (0.0, 20_000.0, 0, STEPS, False),
        (1.0, 0.25, 0, STEPS, False),
        (0.5, 0.5, 0, 0, False),
        (3.0, 3.0, 3, 3, False),
    ],
)
def test_scaled_range_shapes(
    minimum: float, maximum: float, low: int, high: int, inverted: bool
) -> None:
    scaled = scaled_range(minimum, maximum)
    assert (scaled.low, scaled.high, scaled.inverted) == (low, high, inverted)
    assert scaled.value(scaled.index(minimum)) == pytest.approx(minimum)


_BOUND = st.floats(min_value=-1e6, max_value=1e6, allow_nan=False).map(lambda v: round(v, 3))


@given(_BOUND, _BOUND, st.floats(min_value=0, max_value=1))
def test_scaled_range_round_trips_within_one_step(lo: float, hi: float, t: float) -> None:
    scaled = scaled_range(lo, hi)
    value = lo + (hi - lo) * t
    index = scaled.index(value)
    assert scaled.low <= index <= scaled.high
    assert abs(scaled.value(index) - value) <= abs(scaled.step) / 2 + 1e-6 * max(1, abs(value))
    assert abs(scaled.step) <= max(1.0, abs(hi - lo) / STEPS)
    # a reversed range runs backwards: the slider's start shows ``minimum``
    start = scaled.high if scaled.inverted else scaled.low
    assert scaled.value(start) == pytest.approx(lo)


@pytest.mark.parametrize(
    ("values", "expected"),
    [((0.0, 100.0, 1.0), 0), ((0.0, 1.0, 0.25), 2), ((0.1,), 1), ((1e-9,), 6), ((0.1234567,), 6)],
)
def test_decimals(values: tuple[float, ...], expected: int) -> None:
    assert decimals(*values) == expected


def test_units_name_real_properties_of_core_classes() -> None:
    registry = default_registry()
    for class_name, prop in UNITS:
        spec = registry.resolve(class_name, "pyside6", None).spec
        assert prop in {definition.name for definition in spec.properties}, (class_name, prop)
    assert set(UNITS.values()) == {"chars", "lines", "px"}


def test_selectmode_covers_every_choice() -> None:
    registry = default_registry()
    for class_name in ("Listbox", "Treeview"):
        spec = registry.resolve(class_name, "pyside6", None).spec
        (selectmode,) = (d for d in spec.properties if d.name == "selectmode")
        for choice in ("", *selectmode.choices):
            assert (class_name, choice) in SELECTMODE
    assert set(SELECTMODE.values()) <= {
        "SingleSelection",
        "MultiSelection",
        "ExtendedSelection",
        "NoSelection",
    }


# ---------------------------------------------------------------- 16c: keys and signals
@pytest.mark.parametrize(
    ("sequence", "mac", "expected"),
    [
        ("Ctrl+S", False, ("Ctrl+S", "Ctrl+Shift+S")),
        ("Ctrl+S", True, ("Ctrl+S", "Ctrl+Shift+S")),  # a chord follows Tk aqua: Ctrl = Command
        ("<Control-S>", False, ("Ctrl+Shift+S",)),
        ("<Control-s>", False, ("Ctrl+S",)),
        ("<Control-s>", True, ("Meta+S",)),
        ("<Command-s>", True, ("Ctrl+S",)),
        ("<Command-s>", False, ("Meta+S",)),
        ("<Option-x>", False, ("Alt+X",)),
        ("<Option-x>", True, ("Alt+X",)),
        ("<Alt-Shift-a>", False, ("Alt+Shift+A",)),
        ("<Meta-F5>", False, ("Meta+F5",)),
        ("<Shift-A>", False, ("Shift+A",)),
        ("<Control-5>", False, ("Ctrl+5",)),
        ("<KeyPress-Return>", False, ("Return",)),
        ("Enter", False, ("Enter", "Return")),
        ("Alt+PageUp", False, ("Alt+PgUp",)),
        ("Ctrl+Plus", False, ("Ctrl++",)),
        ("not valid", False, ()),
    ],
)
def test_qt_key_sequences(sequence: str, mac: bool, expected: tuple[str, ...]) -> None:
    assert qt_key_sequences(sequence, mac=mac) == expected


_KEYSYMS = {
    **{k: k for k in ("Return", "Tab", "Home", "End", "Up", "Down", "Left", "Right", "F1", "F24")},
    **{"KP_Enter": "Enter", "Escape": "Esc", "space": "Space", "BackSpace": "Backspace"},
    **{"Delete": "Del", "Insert": "Ins", "Prior": "PgUp", "Next": "PgDown", "plus": "+"},
    **{"minus": "-", "comma": ",", "period": ".", "slash": "/", "a": "A", "Z": "Shift+Z"},
}


@pytest.mark.parametrize("keysym", sorted(_KEYSYMS))
@pytest.mark.parametrize(
    ("tk", "qt"),
    [("Control", "Ctrl"), ("Alt", "Alt"), ("Shift", "Shift"), ("Option", "Alt"), ("Meta", "Meta")],
)
def test_every_modifier_and_keysym(keysym: str, tk: str, qt: str) -> None:
    key = _KEYSYMS[keysym]
    order = ("Ctrl", "Alt", "Shift", "Meta")
    *extra, last = key.split("+") if key != "+" else ["+"]
    mods = {qt, *extra}
    expected = "+".join([*(m for m in order if m in mods), last])
    assert qt_key_sequences(f"<{tk}-{keysym}>") == (expected,)


@pytest.mark.parametrize(
    ("shortcut", "expected"),
    [
        ("ctrl+q", "Ctrl+Q"),
        ("Shift+Alt+Ctrl+s", "Ctrl+Alt+Shift+S"),
        ("F5", "F5"),
        ("Ctrl+Enter", "Ctrl+Return"),
        ("Alt+Escape", "Alt+Esc"),
        ("Ctrl+Delete", "Ctrl+Del"),
        ("Ctrl+PageDown", "Ctrl+PgDown"),
        ("Ctrl+Minus", "Ctrl+-"),
        ("Ctrl+Comma", "Ctrl+,"),
        ("Ctrl+Period", "Ctrl+."),
        ("Ctrl+Slash", "Ctrl+/"),
        ("Ctrl+1", "Ctrl+1"),
    ],
)
def test_qt_shortcut(shortcut: str, expected: str) -> None:
    assert qt_shortcut(shortcut) == expected


def test_qt_shortcut_refuses_a_non_chord() -> None:
    with pytest.raises(ValueError, match="shortcut"):
        qt_shortcut("<Control-s>")


def test_signals_cover_every_core_event_except_the_filter_ones() -> None:
    """Every (class, event) pair is a signal, a variable trace (Radiobutton) or the D15 filter."""
    for spec in core_widgets():
        for event in spec.events:
            if event in ("focus_in", "focus_out") or spec.name in ("Menu", "Action", "Menubar"):
                continue
            assert (spec.name, event) in SIGNALS or (spec.name, event) == (
                "Radiobutton",
                "change",
            ), (spec.name, event)
