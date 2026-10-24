"""Toolkit-free control variables for backends without Tk variables (spec backends D12).

The tkinter subset ``get()``, ``set(v)``, ``trace_add("write", cb)`` and
``trace_remove("write", token)``, so handler code reading ``ui.vars.x.get()`` runs unchanged on
every toolkit. Pure: nothing here imports a GUI toolkit (ADR-007).
"""

from __future__ import annotations

import itertools
import math
import string
import sys
from collections.abc import Callable
from typing import ClassVar, Generic, TypeVar

__all__ = ["BooleanVar", "DoubleVar", "IntVar", "StringVar", "Var"]

T = TypeVar("T")
#: A trace callback: ``(variable name, index (always ""), mode (always "write"))``, as tkinter.
Trace = Callable[[str, str, str], object]
_COUNTER = itertools.count()
_TRUE, _FALSE = frozenset({"1", "true", "yes", "on"}), frozenset({"0", "false", "no", "off"})


def _number_text(value: str) -> str:
    """``value`` stripped, if Tcl 8.6 could read it as a number (QA-16c-05): Python's ``int``
    and ``float`` also take ``_`` separators and non-ASCII digits; Tcl 8.6 refuses both."""
    text = value.strip(string.whitespace)  # ASCII only: Tcl does not strip U+00A0
    if "_" in text or not text.isascii():
        raise ValueError(f"not a number: {value!r}")
    return text


def _write_mode(mode: str) -> None:
    if mode != "write":
        raise ValueError(f"only the 'write' trace mode is supported, not {mode!r}")


class Var(Generic[T]):
    """A typed value with write traces; ``set`` always notifies, even with an equal value."""

    _default: ClassVar[object]

    def __init__(self, value: object = None, name: str | None = None) -> None:
        self._name = name if name is not None else f"PY_VAR{next(_COUNTER)}"
        self._traces: dict[str, Trace] = {}
        self._value: T = self._convert(self._default if value is None else value)

    def _convert(self, value: object) -> T:
        raise NotImplementedError

    def __str__(self) -> str:
        return self._name

    def get(self) -> T:
        """The current value."""
        return self._value

    def set(self, value: object) -> None:
        """Store ``value`` (converted to the variable's type), then call every write trace.

        Raises:
            ValueError, TypeError or OverflowError: ``value`` does not convert; nothing changes.
        """
        self._value = self._convert(value)
        for callback in list(self._traces.values()):
            try:
                callback(self._name, "", "write")
            except Exception:  # as a Tk trace: reported, and the other traces still run
                sys.excepthook(*sys.exc_info())

    def trace_add(self, mode: str, callback: Trace) -> str:
        """Call ``callback`` after every ``set``; returns the token for :meth:`trace_remove`."""
        _write_mode(mode)
        token = f"trace{next(_COUNTER)}"
        self._traces[token] = callback
        return token

    def trace_remove(self, mode: str, token: str) -> None:
        """Remove the trace ``token`` (an unknown token is ignored, as tkinter does)."""
        _write_mode(mode)
        self._traces.pop(token, None)


class StringVar(Var[str]):
    """A text variable."""

    _default = ""

    def _convert(self, value: object) -> str:
        return str(value)


class IntVar(Var[int]):
    """An integer variable; texts convert as tkinter's ``get`` does (Tcl 8.6 ``getint``, else
    ``getdouble``): ``"0x10"`` 16, ``"3.7"`` 3, except that leading zeros are decimal (``"010"``
    is 10, not octal 8)."""

    _default = 0

    def _convert(self, value: object) -> int:
        if isinstance(value, str):
            text = _number_text(value)
            try:
                return int(text, 0)  # sign, 0x/0o/0b and any size, as Tcl
            except ValueError:
                return int(float(text))  # "3.7", "1e3"; "nan" raises ValueError
        if isinstance(value, (int, float)):
            return int(value)
        raise TypeError(f"not a number: {value!r}")


class DoubleVar(Var[float]):
    """A floating-point variable."""

    _default = 0.0

    def _convert(self, value: object) -> float:
        if not isinstance(value, str):
            return float(value)  # type: ignore[arg-type]
        text = _number_text(value)
        try:
            number = float(text)  # "inf", and 400 nines -> inf as Tcl
        except ValueError:
            number = float(int(text, 0))  # "0x10", "0o17", "0b11"
        if math.isnan(number):  # Tcl getdouble refuses "nan"
            raise ValueError(f"not a number: {value!r}")
        return number


class BooleanVar(Var[bool]):
    """A boolean variable; texts follow Tcl (``1 true yes on`` / ``0 false no off``)."""

    _default = False

    def _convert(self, value: object) -> bool:
        if not isinstance(value, str):
            return bool(value)
        text = value.strip().lower()
        if text in _TRUE or text in _FALSE:
            return text in _TRUE
        raise ValueError(f"not a boolean: {value!r}")
