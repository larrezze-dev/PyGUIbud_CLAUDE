"""The colour grammar of a ``colour`` property, without a toolkit (validator rule R31).

A colour is ``#rgb``, ``#rrggbb`` or ``#rrrrggggbbbb``, or a name from Tk's own colour table
(``xlib/xcolors.c`` of Tk 8.6.15, the table Tk uses on Windows and macOS), matched the way Tk
matches it: case-insensitive, an optional single space before each capital of the table name
(``alice blue``), and the numbered variants (``azure1``..``azure4``, ``gray0``..``gray100``).

Anything else fails somewhere: an unknown word such as ``blurple`` makes Tk raise "unknown
color name", and the ``System...`` colours (``SystemButtonFace``) exist on one platform only.
"""

from __future__ import annotations

import re
from typing import Final, Literal

__all__ = ["ColourProblem", "colour_problem"]

ColourProblem = Literal["unknown", "system"]

_HEX_RE: Final = re.compile(r"#(?:[0-9a-fA-F]{3}){1,2}|#[0-9a-fA-F]{12}")
#: Letters (single spaces allowed inside), then an optional variant number without a leading 0.
_NAME_RE: Final = re.compile(r"([A-Za-z](?: ?[A-Za-z])*)([1-9][0-9]{0,2})?")
_SYSTEM_RE: Final = re.compile(r"system[A-Za-z0-9 ]*", re.IGNORECASE)
#: Tk's names; ":n" is the number of numbered variants (8 means 1..100, as Tk does for grey).
_TK_TABLE: Final = (
    "AliceBlue AntiqueWhite:4 Aqua Aquamarine:4 Azure:4 Beige Bisque:4 Black BlanchedAlmond "
    "Blue:4 BlueViolet Brown:4 Burlywood:4 CadetBlue:4 Chartreuse:4 Chocolate:4 Coral:4 "
    "CornflowerBlue Cornsilk:4 Crimson Cyan:4 DarkBlue DarkCyan DarkGoldenrod:4 DarkGray "
    "DarkGreen DarkGrey DarkKhaki DarkMagenta DarkOliveGreen:4 DarkOrange:4 DarkOrchid:4 DarkRed "
    "DarkSalmon DarkSeaGreen:4 DarkSlateBlue DarkSlateGray:4 DarkSlateGrey DarkTurquoise "
    "DarkViolet DeepPink:4 DeepSkyBlue:4 DimGray DimGrey DodgerBlue:4 Firebrick:4 FloralWhite "
    "ForestGreen Fuchsia Gainsboro GhostWhite Gold:4 Goldenrod:4 Gray:8 Gray0 Green:4 GreenYellow "
    "Grey:8 Grey0 Honeydew:4 HotPink:4 IndianRed:4 Indigo Ivory:4 Khaki:4 Lavender "
    "LavenderBlush:4 LawnGreen LemonChiffon:4 LightBlue:4 LightCoral LightCyan:4 LightGoldenrod:4 "
    "LightGoldenrodYellow LightGray LightGreen LightGrey LightPink:4 LightSalmon:4 LightSeaGreen "
    "LightSkyBlue:4 LightSlateBlue LightSlateGray LightSlateGrey LightSteelBlue:4 LightYellow:4 "
    "Lime LimeGreen Linen Magenta:4 Maroon:4 MediumAquamarine MediumBlue MediumOrchid:4 "
    "MediumPurple:4 MediumSeaGreen MediumSlateBlue MediumSpringGreen MediumTurquoise "
    "MediumVioletRed MidnightBlue MintCream MistyRose:4 Moccasin NavajoWhite:4 Navy NavyBlue "
    "OldLace Olive OliveDrab:4 Orange:4 OrangeRed:4 Orchid:4 PaleGoldenrod PaleGreen:4 "
    "PaleTurquoise:4 PaleVioletRed:4 PapayaWhip PeachPuff:4 Peru Pink:4 Plum:4 PowderBlue "
    "Purple:4 Red:4 RosyBrown:4 RoyalBlue:4 SaddleBrown Salmon:4 SandyBrown SeaGreen:4 Seashell:4 "
    "Sienna:4 Silver SkyBlue:4 SlateBlue:4 SlateGray:4 SlateGrey Snow:4 SpringGreen:4 SteelBlue:4 "
    "Tan:4 Teal Thistle:4 Tomato:4 Turquoise:4 Violet VioletRed:4 Wheat:4 White WhiteSmoke "
    "Yellow:4 YellowGreen"
)
_GREY_VARIANTS: Final = 8  # the table marks gray/grey with 8; Tk then accepts 1..100
_GREY_MAX: Final = 100


def _table() -> dict[str, tuple[str, int]]:
    """Lower-case name -> (Tk's spelling, variant count)."""
    table: dict[str, tuple[str, int]] = {}
    for token in _TK_TABLE.split():
        name, _sep, count = token.partition(":")
        table[name.lower()] = (name, int(count or 0))
    return table


_NAMES: Final = _table()


def _spaces_fit(typed: str, name: str) -> bool:
    """True when every space in ``typed`` stands before a capital of Tk's spelling ``name``."""
    position = 0
    for index, char in enumerate(typed):
        if char != " ":
            position += 1
            continue
        if index == 0 or typed[index - 1] == " " or not name[position : position + 1].isupper():
            return False
    return True


def _known_name(text: str) -> bool:
    exact = _NAMES.get(text.replace(" ", "").lower())
    if exact is not None and _spaces_fit(text, exact[0]):
        return True  # also the two table names with a digit, gray0 and grey0
    match = _NAME_RE.fullmatch(text)
    if match is None:
        return False
    letters, digits = match.groups()
    entry = _NAMES.get(letters.replace(" ", "").lower())
    if entry is None or not _spaces_fit(letters, entry[0]):
        return False
    if digits is None:
        return True
    variants, number = entry[1], int(digits)
    if variants == _GREY_VARIANTS:
        return number <= _GREY_MAX
    return number <= variants


def colour_problem(text: object) -> ColourProblem | None:
    """None when ``text`` is a portable colour, else why not (``"system"``: one platform only)."""
    if not isinstance(text, str) or not text.isascii():
        return "unknown"
    if _HEX_RE.fullmatch(text) is not None or _known_name(text):
        return None
    return "system" if _SYSTEM_RE.fullmatch(text) is not None else "unknown"
