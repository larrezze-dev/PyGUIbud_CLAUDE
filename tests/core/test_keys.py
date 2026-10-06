"""Tests of the shortcut grammar and the mnemonic split (``pyguibud.core.keys``)."""

from __future__ import annotations

import subprocess
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core import keys
from pyguibud.core.keys import (
    Chord,
    format_chord,
    is_valid_key_sequence,
    parse_chord,
    shortcut_problem,
    split_mnemonic,
    tk_key_sequences,
    tk_shortcut,
)

NAMED = [
    "Enter",
    "Return",
    "Escape",
    "Tab",
    "Space",
    "Backspace",
    "Delete",
    "Insert",
    "Home",
    "End",
    "PageUp",
    "PageDown",
    "Up",
    "Down",
    "Left",
    "Right",
    "Plus",
    "Minus",
    "Comma",
    "Period",
    "Slash",
]


@pytest.mark.parametrize(
    ("text", "modifiers", "key"),
    [
        ("Ctrl+Q", {"Ctrl"}, "Q"),
        ("ctrl+q", {"Ctrl"}, "Q"),
        ("CTRL+SHIFT+s", {"Ctrl", "Shift"}, "S"),
        ("Shift+Ctrl+S", {"Ctrl", "Shift"}, "S"),
        ("Alt+Shift+Ctrl+9", {"Ctrl", "Alt", "Shift"}, "9"),
        ("f5", set(), "F5"),
        ("F24", set(), "F24"),
        ("Ctrl+pageup", {"Ctrl"}, "PageUp"),
        ("alt+RETURN", {"Alt"}, "Return"),
        ("Ctrl+plus", {"Ctrl"}, "Plus"),
        ("Escape", set(), "Escape"),
    ],
)
def test_parse_chord_valid(text: str, modifiers: set[str], key: str) -> None:
    assert parse_chord(text) == Chord(frozenset(modifiers), key)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Q+",
        "+Q",
        "Ctrl+",
        "Ctrl++",
        "Ctrl+Ctrl+Q",
        "Ctrl+ctrl+Q",
        "Ctrl+Q+W",
        "Ctrl Q",
        "Ctrl+ Q",
        " Ctrl+Q",
        "Ctrl+Q ",
        "Ctrl+Meta+Q",
        "Ctrl+F0",
        "Ctrl+F25",
        "Ctrl+F100",
        "Ctrl+AB",
        "Ctrl+é",
        "Ctrl+Ｑ",  # full-width Q  # noqa: RUF001
        "Ctrl+ı",  # dotless i  # noqa: RUF001
        "Strg+Q",
        "Ctrl+-",
        "Ctrl+,",
        "Ctrl+Q\x00",
        "Ctrl+Q\n",
        "<Control-q>",
        "Ctrl+" + "Q" * 100,
        "Ctrl+" * 40 + "Q",
    ],
)
def test_parse_chord_invalid(text: str) -> None:
    assert parse_chord(text) is None


@pytest.mark.parametrize("value", [None, 5, b"Ctrl+Q", ["Ctrl+Q"], object()])
def test_non_text_is_refused_everywhere(value: object) -> None:
    assert parse_chord(value) is None
    assert shortcut_problem(value) == "syntax"
    assert not is_valid_key_sequence(value)


def test_format_is_canonical() -> None:
    assert format_chord(parse_chord("shift+ctrl+alt+f5")) == "Ctrl+Alt+Shift+F5"  # type: ignore[arg-type]
    assert format_chord(Chord(frozenset(), "Escape")) == "Escape"


@given(
    st.sets(st.sampled_from(["Ctrl", "Alt", "Shift"])),
    st.one_of(
        st.sampled_from(NAMED),
        st.integers(1, 24).map(lambda n: f"F{n}"),
        st.sampled_from(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")),
    ),
)
def test_format_parse_round_trip(mods: set[str], key: str) -> None:
    chord = Chord(frozenset(mods), key)
    assert parse_chord(format_chord(chord)) == chord


@given(st.text())
def test_parse_never_raises_and_is_idempotent(text: str) -> None:
    chord = parse_chord(text)
    if chord is not None:
        assert parse_chord(format_chord(chord)) == chord
        assert len(text) <= keys.MAX_SEQUENCE_LENGTH and text.isascii()


def test_enter_and_return_are_one_key_for_duplicates() -> None:
    first, second = parse_chord("Ctrl+Enter"), parse_chord("ctrl+return")
    assert first != second
    assert first is not None and second is not None
    assert first.identity == second.identity


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("Ctrl+S", None),
        ("Alt+F4", None),
        ("Ctrl+Shift+F5", None),
        ("F1", None),
        ("Shift+F24", None),
        ("Q", "modifier"),
        ("Shift+Q", "modifier"),
        ("Enter", "modifier"),
        ("Shift+Delete", "modifier"),
        ("", "syntax"),
        ("Ctrl+Nope", "syntax"),
        ("fine", "syntax"),
        ("x" * 5000, "syntax"),
    ],
)
def test_shortcut_problem(text: str, problem: str | None) -> None:
    assert shortcut_problem(text) == problem


@pytest.mark.parametrize(
    "sequence",
    [
        "Return",
        "F5",
        "Ctrl+S",
        "<Control-s>",
        "<Return>",
        "<Key-Return>",
        "<KeyPress-F12>",
        "<Control-Shift-Key-a>",
        "<Alt-Option-Command-Meta-x>",
        "<Escape>",
        "<KP_Enter>",
        "<space>",
        "<Control-5>",
        "<Prior>",
    ],
)
def test_valid_key_sequences(sequence: str) -> None:
    assert is_valid_key_sequence(sequence)


@pytest.mark.parametrize(
    "sequence",
    [
        "",
        "<>",
        "<Button-1>",
        "<Double-Button-1>",
        "<Control-Control-s>",
        "<Control-s",
        "Control-s>",
        "<Control-s><Control-q>",
        "<Control-ss>",
        "<Control->",
        "<Key-Key-a>",
        "<KeyPress>",
        "<Control-Key>",
        "<control-s>",
        "<Control-F25>",
        "<Control-F0>",
        "<Control-é>",
        "<Control-_>",
        "<Return>>",
        "<<Copy>>",
        "<Motion>",
        "<Control-" + "a" * 100 + ">",
        "nope",
        "Ctrl+Ctrl+S",
    ],
)
def test_invalid_key_sequences(sequence: str) -> None:
    assert not is_valid_key_sequence(sequence)


def test_tk_shortcut() -> None:
    assert tk_shortcut("Ctrl+Q") == keys.TkShortcut(("<Control-q>", "<Control-Q>"), "Ctrl+Q")
    assert tk_shortcut("ctrl+shift+alt+s").sequences == (
        "<Control-Alt-Shift-s>",
        "<Control-Alt-Shift-S>",
    )
    assert tk_shortcut("F5").sequences == ("<F5>",)
    assert tk_shortcut("Ctrl+1").sequences == ("<Control-Key-1>",)  # not Ctrl+click (QA-10-01)
    assert tk_shortcut("Ctrl+Enter").sequences == ("<Control-Return>", "<Control-KP_Enter>")
    assert tk_shortcut("Alt+Space").sequences == ("<Alt-space>",)
    assert tk_shortcut("Ctrl+PageUp").sequences == ("<Control-Prior>",)
    assert tk_shortcut("Ctrl+PageDown").sequences == ("<Control-Next>",)
    assert tk_shortcut("Ctrl+Backspace").sequences == ("<Control-BackSpace>",)
    assert tk_shortcut("Ctrl+Plus").sequences == ("<Control-plus>",)
    assert tk_shortcut("Ctrl+Down").sequences == ("<Control-Down>",)
    assert tk_shortcut("Ctrl+Q", aqua=True).sequences == ("<Command-q>", "<Command-Q>")
    assert tk_shortcut("Alt+Shift+Q", aqua=True).sequences == (
        "<Option-Shift-q>",
        "<Option-Shift-Q>",
    )
    assert tk_shortcut("Ctrl+Q", aqua=True).accelerator == "Ctrl+Q"


@pytest.mark.parametrize("bad", ["", "Q+", "Ctrl+Ctrl+Q", "<Control-q>"])
def test_tk_shortcut_refuses_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="not a valid shortcut"):
        tk_shortcut(bad)


def test_tk_key_sequences() -> None:
    assert tk_key_sequences("Return") == ("<Return>", "<KP_Enter>")
    assert tk_key_sequences("Ctrl+S") == ("<Control-s>", "<Control-S>")
    assert tk_key_sequences("<Control-s>") == ("<Control-s>",)
    assert tk_key_sequences("<Key-Return>") == ("<Key-Return>",)
    assert tk_key_sequences("F5") == ("<F5>",)


@pytest.mark.parametrize("bad", ["", "<Button-1>", "x" * 100, "<Control-s><Control-q>", "q w"])
def test_tk_key_sequences_refuses_invalid(bad: str) -> None:
    with pytest.raises(ValueError, match="not a valid key sequence"):
        tk_key_sequences(bad)


@pytest.mark.parametrize(
    ("text", "shown", "underline"),
    [
        ("_File", "File", 0),
        ("Save _as", "Save as", 5),
        ("Say hello", "Say hello", -1),
        ("", "", -1),
        ("__", "_", -1),
        ("Snake__case", "Snake_case", -1),
        ("A__b _c", "A_b c", 4),
        ("_a_b", "a_b", 0),
        ("a_ b", "a_ b", -1),
        ("trailing_", "trailing_", -1),
        ("_", "_", -1),
        ("_ x", "_ x", -1),
        ("__x", "_x", -1),
        ("___x", "_x", 1),
        ("_été", "été", 0),
        ("a_b_c", "ab_c", 1),
    ],
)
def test_split_mnemonic(text: str, shown: str, underline: int) -> None:
    assert split_mnemonic(text) == (shown, underline)


@given(st.text(alphabet=st.sampled_from(list("ab _")), max_size=40))
def test_split_mnemonic_properties(text: str) -> None:
    shown, underline = split_mnemonic(text)
    assert len(shown) <= len(text)
    assert -1 <= underline < max(len(shown), 1)
    if underline >= 0:
        assert shown[underline] not in (" ",)
    if "_" not in text:
        assert (shown, underline) == (text, -1)


def test_split_mnemonic_huge_text_is_linear() -> None:
    shown, underline = split_mnemonic("_" + "a_" * 200_000)
    assert underline == 0
    assert shown.startswith("a_a_a") and len(shown) == 1 + 2 * 199_999 + 1


_TK_PROBE = """
import sys, tkinter
from pyguibud.core import keys
try:
    root = tkinter.Tk()
except tkinter.TclError:
    sys.exit(3)
root.withdraw()
bad = []
chords = []
for mods in ([], ["Ctrl"], ["Alt"], ["Shift"], ["Ctrl", "Alt", "Shift"]):
    for key in list("aZ09") + ["F1", "F24"] + %(named)r:
        chords.append("+".join([*mods, key]))
for text in chords:
    for aqua in (False, True):
        for seq in keys.tk_key_sequences(text, aqua=aqua):
            try:
                root.bind(seq, lambda e: None)
            except tkinter.TclError as exc:
                bad.append((text, aqua, seq, str(exc)))
SYMS = "Return KP_Enter Escape Tab space BackSpace Delete Insert Home End Prior Next".split()
SYMS += "Up Down Left Right plus minus comma period slash a Z 5 F1 F24".split()
MODS = ["", "Control-", "Alt-Shift-", "Option-", "Command-", "Meta-"]
MODS.append("Control-Alt-Option-Command-Meta-Shift-")
for sym in SYMS:
    for mods in MODS:
        for form in (sym, "Key-" + sym, "KeyPress-" + sym):
            seq = "<" + mods + form + ">"
            assert keys.is_valid_key_sequence(seq), seq
            try:
                root.bind(seq, lambda e: None)
            except tkinter.TclError as exc:
                bad.append((seq, str(exc)))
root.destroy()
print(bad)
sys.exit(1 if bad else 0)
"""


def test_every_accepted_sequence_is_accepted_by_tk() -> None:
    """The validator must never approve a sequence that Tk refuses at build time."""
    code = _TK_PROBE % {"named": NAMED}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    if result.returncode == 3:
        pytest.skip("no Tk display available")
    assert result.returncode == 0, result.stdout + result.stderr
