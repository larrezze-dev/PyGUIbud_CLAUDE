"""Shortcut and key-sequence grammar, plus the mnemonic split (spec ``docs/specs/runtime.md`` 6).

Pure and toolkit-free: the validator uses it to accept or refuse a ``shortcut`` attribute or a
``key:<sequence>`` event, and every backend uses it to turn an accepted value into toolkit
input (:func:`tk_shortcut`, :func:`tk_key_sequences`). Nothing here imports ``tkinter``.

Grammar (case-insensitive, no spaces)::

    chord    := (modifier "+")* key               each modifier at most once
    modifier := Ctrl | Alt | Shift                canonical order: Ctrl, Alt, Shift
    key      := A-Z | 0-9 | F1-F24 | Enter | Return | Escape | Tab | Space | Backspace | Delete
              | Insert | Home | End | PageUp | PageDown | Up | Down | Left | Right
              | Plus | Minus | Comma | Period | Slash
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

__all__ = [
    "MAX_SEQUENCE_LENGTH",
    "Chord",
    "TkShortcut",
    "format_chord",
    "is_valid_key_sequence",
    "key_bindings",
    "parse_chord",
    "shortcut_problem",
    "split_mnemonic",
    "tk_key_sequences",
    "tk_shortcut",
]

#: Longest shortcut or key sequence accepted; the longest valid one is far shorter.
MAX_SEQUENCE_LENGTH: Final = 64

_MODIFIER_ORDER: Final = ("Ctrl", "Alt", "Shift")
_MODIFIERS: Final = {name.casefold(): name for name in _MODIFIER_ORDER}
_NAMED_KEYS: Final = [
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
_FUNCTION_KEY_RE: Final = re.compile(r"[Ff](?:[1-9]|1[0-9]|2[0-4])")
_KEYS: Final = {name.casefold(): name for name in _NAMED_KEYS}

#: Chord key to Tk keysym, for the keys whose Tk name differs or that have a second keysym.
_TK_KEYSYMS: Final = {
    "Enter": ("Return", "KP_Enter"),
    "Return": ("Return", "KP_Enter"),
    "Space": ("space",),
    "Backspace": ("BackSpace",),
    "PageUp": ("Prior",),
    "PageDown": ("Next",),
    "Plus": ("plus",),
    "Minus": ("minus",),
    "Comma": ("comma",),
    "Period": ("period",),
    "Slash": ("slash",),
}

_TK_MODIFIERS: Final = ("Control", "Alt", "Shift", "Option", "Command", "Meta")
_TK_NAMED_KEYSYMS: Final = frozenset(
    [
        "Return",
        "KP_Enter",
        "Escape",
        "Tab",
        "space",
        "BackSpace",
        "Delete",
        "Insert",
        "Home",
        "End",
        "Prior",
        "Next",
        "Up",
        "Down",
        "Left",
        "Right",
        "plus",
        "minus",
        "comma",
        "period",
        "slash",
    ]
)
_TK_FUNCTION_KEYSYM_RE: Final = re.compile(r"F(?:[1-9]|1[0-9]|2[0-4])")
_TK_SEQUENCE_RE: Final = re.compile(
    r"<((?:(?:" + "|".join(_TK_MODIFIERS) + r")-)*)(?:(?:KeyPress|Key)-)?([A-Za-z0-9_]+)>"
)


@dataclass(frozen=True, slots=True)
class Chord:
    """A parsed shortcut in canonical form.

    ``modifiers`` holds canonical names (``Ctrl``, ``Alt``, ``Shift``); ``key`` is the canonical
    key name (a letter is upper case, a function key is ``F5``, a named key is capitalised).
    """

    modifiers: frozenset[str]
    key: str

    @property
    def is_function_key(self) -> bool:
        """True for F1 to F24."""
        return _FUNCTION_KEY_RE.fullmatch(self.key) is not None

    @property
    def identity(self) -> tuple[frozenset[str], str]:
        """Comparison key for duplicate detection (``Enter`` and ``Return`` are the same key)."""
        return self.modifiers, "Enter" if self.key == "Return" else self.key


@dataclass(frozen=True, slots=True)
class TkShortcut:
    """What a Tk backend needs for a menu shortcut."""

    #: Tk event sequences to bind on the toplevel, for example ``("<Control-q>", "<Control-Q>")``.
    sequences: tuple[str, ...]
    #: Canonical, untranslated text for the menu entry's ``accelerator`` option.
    accelerator: str


def _canonical_key(token: str) -> str | None:
    if len(token) == 1 and token.isascii() and token.isalnum():
        return token.upper()
    if _FUNCTION_KEY_RE.fullmatch(token):
        return token.upper()
    return _KEYS.get(token.casefold()) if token.isascii() else None


def parse_chord(text: object) -> Chord | None:
    """Parse ``text`` (for example ``"ctrl+shift+s"``) into a canonical :class:`Chord`.

    Returns None for anything that is not a chord: non-text, empty or over-long text, spaces,
    an unknown modifier or key, or a repeated modifier.
    """
    if not isinstance(text, str) or not 0 < len(text) <= MAX_SEQUENCE_LENGTH or not text.isascii():
        return None
    *modifier_tokens, key_token = text.split("+")
    key = _canonical_key(key_token)
    if key is None:
        return None
    found: set[str] = set()
    for token in modifier_tokens:
        modifier = _MODIFIERS.get(token.casefold())
        if modifier is None or modifier in found:
            return None
        found.add(modifier)
    return Chord(frozenset(found), key)


def format_chord(chord: Chord) -> str:
    """Return the canonical text of ``chord``, for example ``"Ctrl+Shift+S"``."""
    ordered = [name for name in _MODIFIER_ORDER if name in chord.modifiers]
    return "+".join([*ordered, chord.key])


def shortcut_problem(text: object) -> Literal["syntax", "modifier"] | None:
    """Judge an Action ``shortcut``: None if valid, else why not.

    ``"syntax"``: not a chord. ``"modifier"``: a chord without Ctrl or Alt that is not a function
    key, which would steal typing from entries because it is bound on the toplevel.
    """
    chord = parse_chord(text)
    if chord is None:
        return "syntax"
    if not chord.modifiers & {"Ctrl", "Alt"} and not chord.is_function_key:
        return "modifier"
    return None


def _tk_native(sequence: str) -> bool:
    """True for the Tk-native form ``<(Mod-)*(KeyPress-|Key-)?keysym>`` of the spec."""
    match = _TK_SEQUENCE_RE.fullmatch(sequence)
    if match is None:
        return False
    modifiers = [part for part in match.group(1).split("-") if part]
    if len(set(modifiers)) != len(modifiers):
        return False
    keysym = match.group(2)
    if len(keysym) == 1:
        return keysym.isalnum()
    return keysym in _TK_NAMED_KEYSYMS or _TK_FUNCTION_KEYSYM_RE.fullmatch(keysym) is not None


def is_valid_key_sequence(sequence: object) -> bool:
    """True if ``sequence`` (the part after ``key:``) is a chord or a Tk-native sequence."""
    if not isinstance(sequence, str) or not 0 < len(sequence) <= MAX_SEQUENCE_LENGTH:
        return False
    return parse_chord(sequence) is not None or _tk_native(sequence)


def _chord_sequences(chord: Chord, aqua: bool) -> tuple[str, ...]:
    names = {"Ctrl": "Command" if aqua else "Control", "Alt": "Option" if aqua else "Alt"}
    prefix = "".join(
        f"{names.get(name, name)}-" for name in _MODIFIER_ORDER if name in chord.modifiers
    )
    key = chord.key
    if len(key) == 1 and key.isalpha():
        keysyms: tuple[str, ...] = (key.lower(), key)
    elif len(key) == 1:
        # A bare digit after the modifiers is a mouse button in Tk (<Control-1> = Ctrl+click).
        keysyms = (f"Key-{key}",)
    else:
        keysyms = _TK_KEYSYMS.get(key, (key,))
    return tuple(f"<{prefix}{keysym}>" for keysym in keysyms)


def tk_shortcut(shortcut: str, *, aqua: bool = False) -> TkShortcut:
    """Turn a validated Action ``shortcut`` into Tk sequences and accelerator text.

    ``Ctrl+Q`` gives ``<Control-q>`` and ``<Control-Q>`` (``Command`` on aqua) and ``"Ctrl+Q"``.

    Raises:
        ValueError: ``shortcut`` is not a chord (the validator refuses such a file earlier).
    """
    chord = parse_chord(shortcut)
    if chord is None:
        raise ValueError(f"not a valid shortcut: {shortcut!r}")
    return TkShortcut(_chord_sequences(chord, aqua), format_chord(chord))


def tk_key_sequences(sequence: str, *, aqua: bool = False) -> tuple[str, ...]:
    """Turn a validated ``key:`` event sequence into Tk sequences to bind on the widget.

    A chord expands as in :func:`tk_shortcut`; a Tk-native sequence is returned verbatim, except
    that ``Key-`` is inserted before a bare digit (``<Control-5>`` becomes ``<Control-Key-5>``).

    Raises:
        ValueError: ``sequence`` is neither form.
    """
    chord = parse_chord(sequence)
    if chord is not None:
        return _chord_sequences(chord, aqua)
    if isinstance(sequence, str) and len(sequence) <= MAX_SEQUENCE_LENGTH and _tk_native(sequence):
        match = _TK_SEQUENCE_RE.fullmatch(sequence)
        prefixed = match is not None and sequence.startswith(("Key-", "KeyPress-"), match.end(1))
        if match is not None and match.group(2).isdigit() and not prefixed:
            # Without a KeyPress-/Key- prefix, Tk reads a digit as a mouse button.
            return (f"<{match.group(1)}Key-{match.group(2)}>",)
        return (sequence,)
    raise ValueError(f"not a valid key sequence: {sequence!r}")


def key_bindings(sequence: str) -> frozenset[tuple[frozenset[str], str]]:
    """The Tk bindings a ``key:`` event makes, as ``(Tk modifiers, keysym)`` pairs.

    Two events bind the same key when their sets intersect, whatever the spelling: ``Ctrl+S``,
    ``<Control-s>`` and ``<Control-KeyPress-s>`` all bind ``<Control-s>``, and Tk keeps only the
    last handler of a sequence. Empty for an invalid sequence.
    """
    try:
        sequences = tk_key_sequences(sequence)
    except ValueError:
        return frozenset()
    found: set[tuple[frozenset[str], str]] = set()
    for item in sequences:
        match = _TK_SEQUENCE_RE.fullmatch(item)
        if match is not None:
            modifiers = frozenset(part for part in match.group(1).split("-") if part)
            found.add((modifiers, match.group(2)))
    return frozenset(found)


def split_mnemonic(text: str) -> tuple[str, int]:
    """Split a label with an accelerator mark into ``(display text, underline index)``.

    ``__`` is a literal underscore. The first ``_`` followed by a character other than ``_`` or
    a space marks that character; later single underscores and a trailing ``_`` stay literal.
    The index is ``-1`` when nothing is marked.
    """
    out: list[str] = []
    underline = -1
    i = 0
    size = len(text)
    while i < size:
        char = text[i]
        following = text[i + 1] if i + 1 < size else ""
        if char != "_":
            out.append(char)
            i += 1
        elif following == "_":
            out.append("_")
            i += 2
        elif underline < 0 and following not in ("", " "):
            underline = len(out)
            out.append(following)
            i += 2
        else:
            out.append("_")
            i += 1
    return "".join(out), underline
