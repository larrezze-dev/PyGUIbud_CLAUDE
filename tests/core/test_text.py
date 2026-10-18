"""``printable`` and the line-forgery guarantees built on it (Step 19e, H81)."""

from __future__ import annotations

import pytest

from pyguibud.core.diagnostics import Finding
from pyguibud.core.text import printable

# The set pyguibud-uic has escaped since Step 17a: C0, DEL + C1, bidi embeddings and isolates.
_UNSAFE = [*range(0x20), *range(0x7F, 0xA0), *range(0x202A, 0x202F), *range(0x2066, 0x206A)]


@pytest.mark.parametrize("code", _UNSAFE)
def test_every_unsafe_character_is_escaped_repr_style(code: int) -> None:
    assert printable(chr(code)) == repr(chr(code))[1:-1]
    assert chr(code) not in printable(chr(code))


@pytest.mark.parametrize(
    "text", ["plain", "café \U0001f600", "a" + chr(0xA0) + "b", "back\\slash", ""]
)
def test_safe_text_is_unchanged(text: str) -> None:
    assert printable(text) == text


@pytest.mark.parametrize("text", ["a\nb", "x‮y", "\x85\x7f\x00", "\\n \n", "⁦⁩"])
def test_printable_is_idempotent_and_leaves_backslashes(text: str) -> None:
    once = printable(text)
    assert printable(once) == once
    assert once.isprintable()


def test_a_forged_id_cannot_make_a_second_line_or_reorder() -> None:
    finding = Finding(
        code="validate.duplicate_id",
        msgid="The id '{id}' is used more than once.",
        params={"id": "a'\nfake.ui:1: error: boom‮"},
        source="x\ny.ui",
    )
    shown = str(finding)
    assert "\n" not in shown
    assert "‮" not in shown
    assert "\\n" in shown
    assert "\\u202e" in shown
