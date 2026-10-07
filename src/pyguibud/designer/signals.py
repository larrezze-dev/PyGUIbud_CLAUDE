"""A minimal observer: the pure side of the designer talks to the Tk views through signals."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Generic, TypeVar

__all__ = ["Signal"]

T = TypeVar("T")
_log = logging.getLogger(__name__)


class Signal(Generic[T]):
    """Calls its connected slots, in connection order, with one value."""

    def __init__(self) -> None:
        self._slots: list[Callable[[T], None]] = []

    def __len__(self) -> int:
        return len(self._slots)

    def connect(self, slot: Callable[[T], None]) -> Callable[[], None]:
        """Add ``slot``; the returned function disconnects it again (safe to call twice)."""
        self._slots.append(slot)

        def disconnect() -> None:
            for index, existing in enumerate(self._slots):
                if existing is slot:
                    del self._slots[index]
                    return

        return disconnect

    def emit(self, value: T) -> None:
        """Call every slot; a failing slot is logged and never stops the others."""
        for slot in tuple(self._slots):  # a slot may disconnect itself while running
            try:
                slot(value)
            except Exception:
                _log.exception("A signal slot failed: %r", slot)
