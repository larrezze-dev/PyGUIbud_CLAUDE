"""Panel focus cycling (pure): which panel F6 / Shift+F6 moves to."""

from __future__ import annotations

__all__ = ["cycle"]


def cycle(current: int, delta: int, count: int) -> int:
    """The panel index after ``delta`` (+1 = F6, -1 = Shift+F6), wrapping around.

    ``current`` is -1 when no panel holds the focus: forward then starts at the first panel and
    backward at the last, so both directions always land on a panel.
    """
    if count <= 0:
        return -1
    if not 0 <= current < count:
        return 0 if delta >= 0 else count - 1
    return (current + delta) % count
