"""Tests for the gettext catalogues shipped in ``src/pyguibud/locale``."""

from __future__ import annotations

import gettext
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from babel.messages.catalog import Catalog
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

from pyguibud import i18n
from pyguibud.i18n import DOMAIN, LANGUAGES, LOCALE_DIR, SOURCE_LANGUAGE, _, set_language

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
POT_PATH = LOCALE_DIR / f"{DOMAIN}.pot"
TARGETS = [code for code in LANGUAGES if code != SOURCE_LANGUAGE]
_PLACEHOLDER = re.compile(r"\{[^{}]*\}|%\([^)]*\)[#0\- +]*\d*(?:\.\d+)?[a-zA-Z]")

MsgKey = tuple[str | tuple[str, ...], str | None]


def _po_path(code: str) -> Path:
    return LOCALE_DIR / code / "LC_MESSAGES" / f"{DOMAIN}.po"


def _load(path: Path) -> Catalog:
    with path.open("rb") as handle:
        return read_po(handle)


def _norm(text: str | list[str] | tuple[str, ...]) -> str | tuple[str, ...]:
    return text if isinstance(text, str) else tuple(text)


def _keys(catalog: Catalog) -> set[MsgKey]:
    return {(_norm(m.id), m.context) for m in catalog if m.id}


def _extract_keys() -> set[MsgKey]:
    keywords: dict[str, object] = {
        "_": None,
        "N_": None,
        "NP_": (1, 2),
        "gettext": None,
        "ngettext": (1, 2),
        "pgettext": ((1, "c"), 2),
        "npgettext": ((1, "c"), 2, 3),
    }
    found: set[MsgKey] = set()
    for _file, _line, message, _comments, context in extract_from_dir(
        str(SRC_DIR),
        method_map=[("**.py", "python")],
        keywords=keywords,  # type: ignore[arg-type]
        comment_tags=["Translators:"],
    ):
        found.add((message if isinstance(message, str) else tuple(message), context))
    return found


@pytest.fixture(autouse=True)
def reset_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", SOURCE_LANGUAGE)
    monkeypatch.setattr(i18n, "_listeners", [])
    yield


def _placeholders(text: str | tuple[str, ...]) -> set[str]:
    parts = (text,) if isinstance(text, str) else text
    return {p for part in parts for p in _PLACEHOLDER.findall(part)}


def test_pot_matches_fresh_extraction() -> None:
    assert POT_PATH.is_file()
    assert _keys(_load(POT_PATH)) == _extract_keys(), "stale .pot: re-run pybabel extract"


@pytest.mark.parametrize("code", list(LANGUAGES))
def test_po_exists_parses_and_matches_pot(code: str) -> None:
    path = _po_path(code)
    assert path.is_file()
    catalog = _load(path)
    assert str(catalog.locale) == code
    assert _keys(catalog) == _keys(_load(POT_PATH))


@pytest.mark.parametrize("code", list(LANGUAGES))
def test_placeholders_match_source(code: str) -> None:
    for message in _load(_po_path(code)):
        if not message.id:
            continue
        strings = _norm(message.string or "")
        for string in (strings,) if isinstance(strings, str) else strings:
            if string:
                assert _placeholders(string) == _placeholders(_norm(message.id)), message.id


@pytest.mark.parametrize("code", list(LANGUAGES))
def test_po_compiles(code: str, tmp_path: Path) -> None:
    target = tmp_path / f"{code}.mo"
    with target.open("wb") as handle:
        write_mo(handle, _load(_po_path(code)))
    assert target.stat().st_size > 0


@pytest.mark.xfail(reason="Translations complete in Step 18", strict=False)
@pytest.mark.parametrize("code", TARGETS)
def test_fully_translated(code: str) -> None:
    for message in _load(_po_path(code)):
        if message.id:
            assert message.string, f"untranslated: {message.id!r}"
            assert not message.fuzzy, f"fuzzy: {message.id!r}"


def test_stub_catalogue_falls_back_to_source() -> None:
    msgid = "list the available interface languages and exit"
    assert set_language("de_DE") == "de_DE"
    assert _(msgid) == msgid
