"""QA-18-10/11/12: literal tokens in sentences are placeholders (key chords, ``ttkbootstrap``, the
``--theme`` default). The en-GB text is unchanged, and the pseudo-locale ``en_XA``, which accents
every letter of a msgid but keeps ``{placeholders}``, leaves the tokens intact.
"""

from __future__ import annotations

import gettext
from collections.abc import Iterator

import pytest

from pyguibud import i18n
from pyguibud.backends._tk import _M_IGNORED_STYLES
from pyguibud.core.errors import format_message
from pyguibud.core.validate import (
    _KEY_EXAMPLES,
    _M_BAD_KEY_SEQUENCE,
    _M_BAD_SHORTCUT,
    _M_UNKNOWN_TB_ATTR,
    _SHORTCUT_EXAMPLES,
)
from pyguibud.designer import preview as pv
from pyguibud.designer.panels.canvas import _EMPTY_KEYS, _M_EMPTY


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    yield


#: (rendered in the current language, the en-GB text before QA-18, the literal tokens)
def _cases() -> list[tuple[str, str, tuple[str, ...]]]:
    return [
        (
            format_message(_M_EMPTY, _EMPTY_KEYS),
            "No document. Press Ctrl+N for a new one or Ctrl+O to open a file.",
            ("Ctrl+N", "Ctrl+O"),
        ),
        (
            format_message(_M_BAD_SHORTCUT, {"value": "Strg+S", **_SHORTCUT_EXAMPLES}),
            "'Strg+S' is not a valid shortcut, for example Ctrl+S or Ctrl+Shift+F5.",
            ("Ctrl+S", "Ctrl+Shift+F5"),
        ),
        (
            format_message(_M_BAD_KEY_SEQUENCE, {"value": "nope", **_KEY_EXAMPLES}),
            "'nope' is not a valid key, for example key:Ctrl+S or key:<Control-s>.",
            ("key:Ctrl+S", "key:<Control-s>"),
        ),
        (
            format_message(
                _M_UNKNOWN_TB_ATTR, {"name": "tb:x", "id": "w", "package": "ttkbootstrap"}
            ),
            "The attribute 'tb:x' on 'w' is not a ttkbootstrap attribute; it is kept but ignored.",
            ("ttkbootstrap",),
        ),
        (
            format_message(
                _M_IGNORED_STYLES,
                {
                    "count": 2,
                    "package": "ttkbootstrap",
                    "attribute": "tb:bootstyle",
                    "toolkit": "tkinter",
                },
            ),
            "2 ttkbootstrap styles (tb:bootstyle) are ignored by the tkinter toolkit.",
            ("ttkbootstrap",),
        ),
        (
            pv.not_installed_text("pyside6"),
            "PySide6 is not installed; the preview uses ttkbootstrap.",
            ("ttkbootstrap",),
        ),
        (
            pv.reason_text(pv.R_TOOLKIT),
            "the exported module uses ttkbootstrap",
            ("ttkbootstrap",),
        ),
    ]


def test_the_british_english_texts_are_unchanged() -> None:
    assert [(text, before) for text, before, _tokens in _cases() if text != before] == []


def test_the_pseudo_locale_keeps_the_literal_tokens() -> None:
    i18n.set_language("en_XA")
    for text, _before, tokens in _cases():
        assert text.startswith("["), text
        assert all(token in text for token in tokens), text


def test_the_other_differences_render_unchanged() -> None:
    """``reason_text`` fills ``{toolkit}`` only; a reason without a placeholder is untouched."""
    for reason in (pv.R_PSEUDO, pv.R_THEME, pv.R_COMPONENT, pv.R_SNAPSHOT):
        assert pv.reason_text(reason) == reason
