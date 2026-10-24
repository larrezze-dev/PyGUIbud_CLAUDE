"""Pure Qt mapping tables of the PySide6 backend (spec backends §2, §4).

Toolkit-free (ADR-007): nothing here imports PySide6. Qt enums are returned by *name* (for
example ``"AlignLeft"``) and resolved by ``_qt``, so the tables are testable without Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pyguibud.core.keys import key_bindings, parse_chord

__all__ = [
    "SELECTMODE",
    "SIGNALS",
    "STEPS",
    "UNITS",
    "ScaledRange",
    "alignment",
    "decimals",
    "escape_title",
    "pack_item",
    "qt_key_sequences",
    "qt_shortcut",
    "qt_text",
    "scaled_range",
]

Unit = Literal["chars", "lines", "px"]

#: (core class, property) -> the Tk unit of a requested size (D10); "length" is along ``orient``.
UNITS: dict[tuple[str, str], Unit] = {
    **dict.fromkeys(
        (
            ("Label", "width"),
            ("Button", "width"),
            ("Entry", "width"),
            ("Text", "width"),
            ("Combobox", "width"),
            ("Spinbox", "width"),
        ),
        "chars",
    ),
    **dict.fromkeys((("Text", "height"), ("Listbox", "height"), ("Treeview", "height")), "lines"),
    **dict.fromkeys(
        (
            *(
                (cls, side)
                for cls in ("Frame", "LabelFrame", "Notebook", "Canvas")
                for side in ("width", "height")
            ),
            ("ScrolledFrame", "height"),
            ("Scale", "length"),
            ("Progressbar", "length"),
        ),
        "px",
    ),
}

#: (core class, Tk selectmode) -> ``QAbstractItemView.SelectionMode`` name; key mode "" = default.
SELECTMODE: dict[tuple[str, str], str] = {
    ("Listbox", ""): "SingleSelection",
    ("Listbox", "browse"): "SingleSelection",
    ("Listbox", "single"): "SingleSelection",
    ("Listbox", "multiple"): "MultiSelection",
    ("Listbox", "extended"): "ExtendedSelection",
    ("Treeview", ""): "ExtendedSelection",
    ("Treeview", "browse"): "SingleSelection",
    ("Treeview", "extended"): "ExtendedSelection",
    ("Treeview", "none"): "NoSelection",
}

#: Integer steps of a non-integral (or wider than this) Scale or Progressbar range (D11).
STEPS = 10_000
_MAX_DECIMALS = 6


def _axis(low: bool, high: bool, flags: tuple[str, str, str]) -> tuple[str, ...]:
    """One axis: both sides fill (no flag), one side aligns to it, none centres."""
    if low and high:
        return ()
    return (flags[0],) if low else (flags[1],) if high else (flags[2],)


def alignment(sticky: str) -> tuple[str, ...]:
    """``Qt.AlignmentFlag`` names of a grid cell's ``sticky`` (an empty tuple fills the cell)."""
    return _axis("w" in sticky, "e" in sticky, ("AlignLeft", "AlignRight", "AlignHCenter")) + (
        _axis("n" in sticky, "s" in sticky, ("AlignTop", "AlignBottom", "AlignVCenter"))
    )


def pack_item(orient: str, fill: str, expand: bool) -> tuple[int, tuple[str, ...]]:
    """``(stretch, alignment names)`` of a packed child in a box layout of ``orient``.

    Across the axis a child fills when ``fill`` covers that axis, else it is centred. Along the
    axis an expanding child that does not fill is centred in its parcel, as Tk's ``expand``.
    """
    horizontal = orient == "horizontal"
    fill_x, fill_y = fill in ("x", "both"), fill in ("y", "both")
    along_fill, across_fill = (fill_x, fill_y) if horizontal else (fill_y, fill_x)
    h_centre, v_centre = "AlignHCenter", "AlignVCenter"
    names: list[str] = []
    if not across_fill:
        names.append(v_centre if horizontal else h_centre)
    if expand and not along_fill:
        names.append(h_centre if horizontal else v_centre)
    return (1 if expand else 0), tuple(names)


def qt_text(text: str, underline: int, mnemonic: bool) -> str:
    """The text for a Qt widget; with ``mnemonic`` the widget interprets ``&`` (spec 4.5).

    Every literal ``&`` is doubled and a single ``&`` marks the character at ``underline``.
    An ``&`` itself is never marked. Without ``mnemonic`` the text is returned verbatim (labels,
    the status bar and window titles are PlainText).
    """
    if not mnemonic:
        return text
    out: list[str] = []
    for index, char in enumerate(text):
        if index == underline and char != "&":
            out.append("&")
        out.append("&&" if char == "&" else char)
    return "".join(out)


def split_qt_text(text: str) -> tuple[str, int]:
    """The inverse of :func:`qt_text` with ``mnemonic``: ``(display text, underline or -1)``."""
    out: list[str] = []
    underline, index = -1, 0
    while index < len(text):
        if text[index] == "&" and index + 1 < len(text):
            index += 1
            if text[index] != "&" and underline < 0:
                underline = len(out)
        out.append(text[index])
        index += 1
    return "".join(out), underline


def escape_title(text: str) -> str:
    """A window title Qt shows literally: ``[*]`` is Qt's modified marker, ``[*][*]`` a literal."""
    return text.replace("[*]", "[*][*]")


@dataclass(frozen=True, slots=True)
class ScaledRange:
    """An integer slider range ``[low, high]`` standing for a float range (D11)."""

    low: int
    high: int
    inverted: bool  # Qt draws ``high`` on the start side
    offset: float
    step: float

    def value(self, index: int) -> float:
        """The float value of slider position ``index``."""
        return self.offset + index * self.step

    def index(self, value: float) -> int:
        """The slider position nearest to ``value``, clamped to the range."""
        position = round((value - self.offset) / self.step)
        return min(max(position, self.low), self.high)


def scaled_range(minimum: float, maximum: float) -> ScaledRange:
    """The integer range of a Scale or Progressbar from ``minimum`` to ``maximum`` (D11).

    An integral range at most :data:`STEPS` wide maps 1:1 (reversed: an inverted slider);
    any other maps linearly onto ``0..STEPS``, so a reversed one runs backwards on its own.
    """
    width = abs(maximum - minimum)
    if minimum.is_integer() and maximum.is_integer() and width <= STEPS:
        low, high = sorted((int(minimum), int(maximum)))
        return ScaledRange(low, high, minimum > maximum, 0.0, 1.0)
    if width == 0:  # a single non-integral value: one position
        return ScaledRange(0, 0, False, minimum, 1.0)
    return ScaledRange(0, STEPS, False, minimum, (maximum - minimum) / STEPS)


def decimals(*values: float) -> int:
    """The decimals a ``QDoubleSpinBox`` needs to show every value exactly (at most 6)."""
    places = 0
    for value in values:
        text = repr(float(value))
        if "e" in text or "E" in text:
            return _MAX_DECIMALS
        fraction = text.partition(".")[2].rstrip("0")
        places = max(places, len(fraction))
    return min(places, _MAX_DECIMALS)


#: (core class, event) -> the Qt signal of the event (spec 4.3). ``change`` of a bound widget
#: goes through its variable instead; an unbound Radiobutton uses ``toggled(True)``.
SIGNALS: dict[tuple[str, str], str] = {
    **dict.fromkeys(
        (("Button", "command"), ("Checkbutton", "command"), ("Radiobutton", "command")), "clicked"
    ),
    ("Scrollbar", "change"): "actionTriggered",
    ("Entry", "change"): "textChanged",
    ("Text", "change"): "textChanged",
    ("Combobox", "change"): "currentTextChanged",
    ("Spinbox", "change"): "valueChanged",
    ("Scale", "change"): "valueChanged",
    ("Checkbutton", "change"): "toggled",
    ("Notebook", "select"): "currentChanged",
    ("Combobox", "select"): "activated",
    ("Listbox", "select"): "itemSelectionChanged",
    ("Treeview", "select"): "itemSelectionChanged",
    ("Entry", "activate"): "returnPressed",
    ("Listbox", "activate"): "itemActivated",
    ("Treeview", "activate"): "itemActivated",
}

#: Tk keysym -> ``QKeySequence`` key name, where they differ (letters, digits, F-keys are kept).
_QT_KEYS = {
    **{name: name for name in ("Return", "Tab", "Home", "End", "Up", "Down", "Left", "Right")},
    **{"KP_Enter": "Enter", "Escape": "Esc", "space": "Space", "BackSpace": "Backspace"},
    **{"Delete": "Del", "Insert": "Ins", "Prior": "PgUp", "Next": "PgDown"},
    **{"plus": "+", "minus": "-", "comma": ",", "period": ".", "slash": "/"},
}
#: Chord key -> Qt key name, where they differ.
_CHORD_KEYS = {
    **{"Enter": "Return", "Escape": "Esc", "Delete": "Del", "Insert": "Ins"},
    **{"PageUp": "PgUp", "PageDown": "PgDown", "Plus": "+", "Minus": "-", "Comma": ","},
    **{"Period": ".", "Slash": "/"},
}
#: Tk modifier -> Qt modifier. Off macOS Tk's ``Command`` has no key of its own: Meta.
_QT_MODIFIERS = {
    **{"Control": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Option": "Alt"},
    **{"Command": "Meta", "Meta": "Meta"},
}
#: On macOS Qt's ``Ctrl`` is the Command key and ``Meta`` the Control key (Tk aqua names).
_QT_MAC_MODIFIERS = _QT_MODIFIERS | {"Control": "Meta", "Command": "Ctrl"}
_QT_ORDER = ("Ctrl", "Alt", "Shift", "Meta")


def _join(modifiers: set[str], key: str) -> str:
    return "+".join([*(name for name in _QT_ORDER if name in modifiers), key])


def qt_key_sequences(sequence: str, *, mac: bool = False) -> tuple[str, ...]:
    """``QKeySequence`` texts matching what a validated ``key:`` sequence binds in Tk.

    Built from :func:`core.keys.key_bindings`, so Tk's case rule holds: ``<Control-S>`` is
    ``Ctrl+Shift+S`` and the chord ``Ctrl+S`` gives ``Ctrl+S`` and ``Ctrl+Shift+S``. A chord's
    ``Ctrl`` is Qt's ``Ctrl`` everywhere (Command on macOS, as Tk aqua); on macOS (``mac``) a
    Tk-native ``Control`` is Qt's ``Meta`` and ``Command`` is ``Ctrl``. Empty when invalid.
    """
    names = _QT_MAC_MODIFIERS if mac and parse_chord(sequence) is None else _QT_MODIFIERS
    found: list[str] = []
    for modifiers, keysym in sorted(
        key_bindings(sequence), key=lambda b: (sorted(b[0]), b[1].isupper(), b[1])
    ):
        qt_modifiers = {names[name] for name in modifiers}
        if len(keysym) == 1 and keysym.isalpha():
            if keysym.isupper():
                qt_modifiers.add("Shift")
            keysym = keysym.upper()
        text = _join(qt_modifiers, _QT_KEYS.get(keysym, keysym))
        if text not in found:
            found.append(text)
    return tuple(found)


def qt_shortcut(shortcut: str) -> str:
    """The ``QKeySequence`` text of a validated Action ``shortcut`` (``Ctrl+Q`` stays ``Ctrl+Q``).

    One canonical sequence, so ``Ctrl+S`` never claims ``Ctrl+Shift+S`` from another action.

    Raises:
        ValueError: ``shortcut`` is not a chord (the validator refuses such a file earlier).
    """
    chord = parse_chord(shortcut)
    if chord is None:
        raise ValueError(f"not a valid shortcut: {shortcut!r}")
    return _join(set(chord.modifiers), _CHORD_KEYS.get(chord.key, chord.key))
