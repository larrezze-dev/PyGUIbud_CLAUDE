"""Pure presenters: they turn the model into plain rows in the current language (no Tk).

Views keep the rows' *current* text only for as long as the language does not change: on a
language switch the presenters simply run again.
"""

from __future__ import annotations

from collections.abc import Callable

from pyguibud.i18n import N_, _

__all__ = ["MAX_TEXT", "clip", "fit_text", "severity_label"]

#: User values (ids, titles) are shown verbatim but never longer than this.
MAX_TEXT = 100

_M_ERROR = N_("Error")
_M_WARNING = N_("Warning")


def clip(text: object, limit: int = MAX_TEXT) -> str:
    """``text`` as a string, cut to ``limit`` characters with an ellipsis."""
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def fit_text(text: str, width: int, measure: Callable[[str], int]) -> str:
    """``text`` unchanged if ``measure(text) <= width``, else the longest prefix plus "…" that fits.

    ``measure`` returns the pixel width of a string (a Tk font's ``measure``); keeping it a
    callback keeps this function Tk-free. A non-positive ``width`` (a column that is not laid
    out yet) leaves the text alone; a width too small even for "…" gives just "…".
    """
    if width <= 0 or measure(text) <= width:
        return text
    low, high = 0, len(text) - 1  # the longest kept prefix lies in [low, high]
    while low < high:
        middle = (low + high + 1) // 2
        if measure(text[:middle].rstrip() + "…") <= width:
            low = middle
        else:
            high = middle - 1
    return text[:low].rstrip() + "…"


def severity_label(severity: str) -> str:
    """The translated word for a finding severity ("" for no finding)."""
    if severity == "error":
        return _(_M_ERROR)
    if severity == "warning":
        return _(_M_WARNING)
    return ""
