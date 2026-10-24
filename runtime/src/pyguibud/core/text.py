"""Text helpers that keep user-supplied text from forging or reordering output lines."""

from __future__ import annotations

__all__ = ["printable"]

# Control, DEL, C1, the line and paragraph separators, the bidi marks (ALM, LRM, RLM) and the
# bidi embedding/override/isolate characters. Backslash is left alone so that applying
# :func:`printable` twice equals applying it once.
_UNSAFE = [*range(0x20), *range(0x7F, 0xA0), 0x061C, 0x200E, 0x200F, 0x2028, 0x2029]
_UNSAFE += [*range(0x202A, 0x202F), *range(0x2066, 0x206A)]
_TABLE = {code: repr(chr(code))[1:-1] for code in _UNSAFE}  # "\n", "\x85", "‮"


def printable(text: str) -> str:
    """Escape control and bidi characters repr-style; other text is unchanged."""
    return text.translate(_TABLE)
