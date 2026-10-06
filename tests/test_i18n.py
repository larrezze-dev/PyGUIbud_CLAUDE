"""Tests for pyguibud.i18n."""

from __future__ import annotations

import gettext
import re
from collections.abc import Iterator

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud import i18n
from pyguibud.i18n import (
    LANGUAGES,
    PseudoTranslations,
    add_language_listener,
    detect_language,
    get_language,
    normalise_language,
    remove_language_listener,
    set_language,
)

_ENV_VARS = ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG")


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in _ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))
    yield


def test_languages_has_eight_entries_without_pseudo() -> None:
    assert list(LANGUAGES) == [
        "en_GB",
        "es_ES",
        "pt_PT",
        "pt_BR",
        "de_DE",
        "it_IT",
        "nl_NL",
        "fr_FR",
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("de-DE", "de_DE"),
        ("de_de", "de_DE"),
        ("de_DE.UTF-8", "de_DE"),
        ("de", "de_DE"),
        ("pt", "pt_PT"),
        ("pt-br", "pt_BR"),
        ("en", "en_GB"),
        ("en_US", "en_GB"),
        ("Spanish_Spain", "es_ES"),
        ("German_Germany.1252", "de_DE"),
        ("Portuguese_Brazil", "pt_BR"),
        ("Portuguese_Portugal", "pt_PT"),
        ("en_XA", "en_XA"),
        ("xx_YY", None),
        ("C", None),
        ("", None),
        (None, None),
    ],
)
def test_normalise_language(raw: str | None, expected: str | None) -> None:
    assert normalise_language(raw) == expected


def test_detect_default_and_env_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))
    assert detect_language() == "en_GB"
    monkeypatch.setenv("LANG", "fr_FR.UTF-8")
    assert detect_language() == "fr_FR"
    monkeypatch.setenv("LANGUAGE", "xx:it_IT:de")
    assert detect_language() == "it_IT"
    monkeypatch.setenv("PYGUIBUD_LANG", "nl")
    assert detect_language() == "nl_NL"


def test_detect_uses_locale_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: ("Spanish_Spain", "1252"))
    assert detect_language() == "es_ES"

    def boom(*_a: object, **_k: object) -> tuple[str, str]:
        raise ValueError("bad locale")

    monkeypatch.setattr("locale.getlocale", boom)
    assert detect_language() == "en_GB"


def test_set_language_unknown_raises() -> None:
    with pytest.raises(ValueError, match="de_DE"):
        set_language("xx_YY")


def test_underscore_follows_current_language() -> None:
    assert i18n._("Hello") == "Hello"
    assert set_language("en_XA") == "en_XA"
    assert get_language() == "en_XA"
    assert i18n._("Hello").startswith("[")
    set_language("de-DE")
    assert get_language() == "de_DE"
    assert i18n._("Hello") == "Hello"  # no catalogue yet: falls back to the source text


def test_ngettext_and_pgettext_pseudo() -> None:
    set_language("en_XA")
    assert i18n.ngettext("one file", "{n} files", 1) != "one file"
    assert "{n}" in i18n.ngettext("one file", "{n} files", 3)
    assert i18n.pgettext("menu", "Open").startswith("[")


def test_listeners_called_isolated_and_removable() -> None:
    seen: list[str] = []

    def bad(_code: str) -> None:
        raise RuntimeError("boom")

    add_language_listener(bad)
    add_language_listener(seen.append)
    set_language("es_ES")
    assert seen == ["es_ES"]
    remove_language_listener(seen.append)
    remove_language_listener(seen.append)  # idempotent
    set_language("fr_FR")
    assert seen == ["es_ES"]


# ---------------------------------------------------------------- pseudo-locale
_PSEUDO = PseudoTranslations()


@pytest.mark.parametrize(
    "message",
    [
        "Open file",
        "Save {name} now",
        "Item {0} of {1}",
        "Hello %(user)s, you have %d items (100%%)",
        "Copy %s",
        "_File and E_xit",
    ],
)
def test_pseudo_properties(message: str) -> None:
    out = _PSEUDO.gettext(message)
    assert out.startswith("[")
    assert out.endswith("]")
    assert len(out) >= len(message) * 1.3
    out.encode("cp1252")
    for token in re.findall(r"\{[^{}]*\}|%\([^)]*\)s|%[sd]|%%", message):
        assert token in out
    assert out.count("_") == message.count("_")


def test_pseudo_empty_and_formatting() -> None:
    assert _PSEUDO.gettext("") == ""
    assert _PSEUDO.gettext("Hello {name}").format(name="Ann").startswith("[")
    assert _PSEUDO.gettext("%(n)d files") % {"n": 3} != ""


_TOKEN = re.compile(r"\{[^{}]*\}|%\([^)]*\)s")
_pieces = st.one_of(
    st.sampled_from(["{name}", "{0}", "{count}", "%(user)s", "%(n)s"]),
    st.text(alphabet="abcdeiouyNCYE _-.,:", max_size=12),
)


@given(st.lists(_pieces, max_size=8))
def test_pseudo_preserves_placeholders(pieces: list[str]) -> None:
    message = "".join(pieces)
    out = _PSEUDO.gettext(message)
    assert _TOKEN.findall(out) == _TOKEN.findall(message)
    out.encode("cp1252")
