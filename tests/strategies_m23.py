"""Shared M23 abuse values (docs/specs/hardening.md, step 19c): plain lists and strategies.

Reused by the core storm tests and, later, by QA. Pure data: no Tk, no model imports.
"""

# ruff: noqa: RUF001
from __future__ import annotations

from hypothesis import strategies as st

#: Strings that are not valid ids (ASCII ``^[A-Za-z][A-Za-z0-9_]{0,63}$``, no keywords).
BAD_IDS: tuple[str, ...] = (
    "",
    "class",
    "None",
    "_private",
    "1abc",
    "a-b",
    "a b",
    "a" * 10_000,
    "a" * 65,
    "ａｂｃ",  # full-width "abc"
    "аbc",  # Cyrillic a
    "café",
    "x\n",
)

#: Valid, distinct ids for building documents.
GOOD_IDS: tuple[str, ...] = ("alpha", "beta", "gamma", "delta", "w_1", "A9")

#: Handler / variable names that are not Python identifiers (or are keywords).
BAD_NAMES: tuple[str, ...] = ("on-click", "1go", "", "def", "a b", "x.y", "ｈ")

#: Absurd grid/pack numbers.
BAD_INTS: tuple[int, ...] = (-1, -(10**9), 10_001, 10**9, 10**30)
HUGE_INTS: tuple[int, ...] = (10_001, 10**9, 10**30)

bad_ids = st.sampled_from(BAD_IDS)
good_ids = st.sampled_from(GOOD_IDS)
#: Mostly good ids, with a share of abusive ones.
any_ids = st.one_of(good_ids, good_ids, bad_ids)
bad_names = st.sampled_from(BAD_NAMES)
any_ints = st.one_of(st.integers(-3, 12), st.sampled_from(BAD_INTS))
small_ints = st.integers(0, 3)
