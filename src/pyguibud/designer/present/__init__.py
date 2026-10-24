"""Pure presenters: they turn the model into plain rows in the current language (no Tk).

Views keep the rows' *current* text only for as long as the language does not change: on a
language switch the presenters simply run again.
"""

from __future__ import annotations

from collections.abc import Callable

from pyguibud.core.text import printable
from pyguibud.i18n import N_, _

__all__ = ["MAX_TEXT", "clip", "elide_middle", "fit_text", "inserted", "severity_label"]

#: User values (ids, titles) are shown verbatim but never longer than this.
MAX_TEXT = 100

_M_ERROR = N_("Error")
_M_WARNING = N_("Warning")


def clip(text: object, limit: int = MAX_TEXT) -> str:
    """``text`` as a string, cut to ``limit`` characters with an ellipsis."""
    value = str(text)
    return value if len(value) <= limit else value[: limit - 1] + "…"


def inserted(value: object) -> str:
    """An id put into a message: escaped first (H81), then clipped, so 10,000 bidi characters
    never become a 60,000-character label (QA-19g-09). Not for paths: their name would go."""
    return clip(printable(str(value)))


def fit_text(text: str, width: int, measure: Callable[[str], int], *, words: bool = False) -> str:
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
    kept = text[:low]
    if words and text[low : low + 1].strip() and " " in kept:  # never cut mid-word
        kept = kept[: kept.rfind(" ")]
    return kept.rstrip() + "…"


def elide_middle(path: str, limit: int, measure: Callable[[str], int] | None = None) -> str:
    """``path`` cut in the middle to about ``limit`` characters, keeping its start (the drive)
    and its last part (the file name): ``C:\\Users\\...\\project\\main.ui``.

    With ``measure`` (a Tk font's ``measure``), ``limit`` is a width in pixels and the text is
    measured, so wide glyphs (CJK, "W") fit too; a non-positive ``limit`` (a column that is not
    laid out yet) leaves the path alone. A file name longer than ``limit`` is kept whole, so the
    name is never the part that is lost.
    """
    if measure is None:
        if len(path) <= limit:
            return path
    elif limit <= 0 or measure(path) <= limit:
        return path
    cut = max(path.rfind("/"), path.rfind("\\"))
    if cut < 0:  # no folders: a plain name is cut at its end
        return clip(path, limit) if measure is None else fit_text(path, limit, measure)
    tail = path[cut:]  # the separator and the file name
    if measure is None:
        room = limit - len(tail) - 1
    else:  # the longest kept start that fits, found by bisection (``measure`` grows with it)
        low, high = 0, cut
        while low < high:
            middle = (low + high + 1) // 2
            if measure(path[:middle] + "…" + tail) <= limit:
                low = middle
            else:
                high = middle - 1
        room = low
    return path[:room] + "…" + tail if room > 0 else "…" + tail


def severity_label(severity: str) -> str:
    """The translated word for a finding severity ("" for no finding)."""
    if severity == "error":
        return _(_M_ERROR)
    if severity == "warning":
        return _(_M_WARNING)
    return ""
