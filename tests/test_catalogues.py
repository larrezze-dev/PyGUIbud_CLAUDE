"""Tests for the gettext catalogues shipped in ``src/pyguibud/locale``."""

from __future__ import annotations

import gettext
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from babel.messages.catalog import Catalog, Message
from babel.messages.extract import extract_from_dir
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po

from pyguibud import i18n
from pyguibud.core.keys import split_mnemonic
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
        "NC_": ((1, "c"), 2),
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


@pytest.mark.parametrize("code", TARGETS)
def test_fully_translated(code: str) -> None:
    for message in _load(_po_path(code)):
        if message.id:
            forms = message.string if isinstance(message.string, tuple) else (message.string,)
            assert all(forms), f"untranslated: {message.id!r}"
            assert not message.fuzzy, f"fuzzy: {message.id!r}"


def test_catalogue_translates_at_runtime() -> None:
    msgid = "list the available interface languages and exit"
    assert set_language("de_DE") == "de_DE"
    assert _(msgid) not in ("", msgid)


# ---------------------------------------------------------------- Step 18 quality gates
_BRACE = re.compile(r"\{[^{}]*\}")
_PERCENT = re.compile(r"%\([^)]*\)[#0\- +]*\d*(?:\.\d+)?[a-zA-Z]")
#: Sources whose underscores are literal (language codes, identifiers), not access keys.
_NOT_MNEMONIC = re.compile(r"[a-z]{2}_[A-Z]{2}|'_'|\w\.\w")
_PLURAL_FORMS = {
    "fr_FR": "nplurals=2; plural=(n > 1);",
    "pt_BR": "nplurals=2; plural=(n > 1);",
}
_DEFAULT_PLURAL_FORMS = "nplurals=2; plural=(n != 1);"
_FORBIDDEN = {
    "pt_PT": re.compile(r"\barquivo|\btela\b|\bsalvar|\busuário|\bconfigurações", re.IGNORECASE),
    "pt_BR": re.compile(r"\bficheiro|\becrã|\bguardar\b|\butilizador", re.IGNORECASE),
}
_STICKY_LETTERS = ("N", "E", "S", "W")


def _fields(text: str) -> set[str]:
    """Named placeholders of one string: ``{name}`` and ``%(name)s``; ``{{``/``}}`` are literal."""
    plain = text.replace("{{", "").replace("}}", "")
    return set(_BRACE.findall(plain)) | set(_PERCENT.findall(plain))


def _strip_fields(text: str) -> str:
    return _PERCENT.sub("", _BRACE.sub("", text.replace("{{", "").replace("}}", "")))


def _marks(text: str) -> int:
    """How many access-key underscores ``text`` has (``__`` and a trailing/spaced ``_`` aren't)."""
    plain = _strip_fields(text).replace("__", "")
    return len(re.findall(r"_(?=[^\s_])", plain))


def _has_mnemonic(source: str) -> bool:
    return not _NOT_MNEMONIC.search(source) and split_mnemonic(_strip_fields(source))[1] >= 0


def _messages(code: str) -> list[Message]:
    return [m for m in _load(_po_path(code)) if m.id]


def _forms(message: Message) -> tuple[str, ...]:
    string = message.string
    return tuple(string) if isinstance(string, (list, tuple)) else (string or "",)


@pytest.mark.parametrize("code", TARGETS)
def test_every_form_keeps_the_placeholders_of_its_source(code: str) -> None:
    problems: list[tuple[object, int, str]] = []
    for message in _messages(code):
        if isinstance(message.id, (list, tuple)):
            singular, plural = message.id[0], message.id[1]
            wanted = _fields(plural)
            for index, form in enumerate(_forms(message)):
                allowed = [wanted]
                if index == 0 and "{count}" not in _fields(singular):
                    allowed.append(wanted - {"{count}"})
                if _fields(form) not in allowed:
                    problems.append((message.id, index, form))
        else:
            (form,) = _forms(message)
            if _fields(form) != _fields(message.id):
                problems.append((message.id, 0, form))
    assert problems == []


def test_the_mnemonic_gate_sees_the_menu_labels() -> None:
    sources = [m.id for m in _load(POT_PATH) if isinstance(m.id, str) and _has_mnemonic(m.id)]
    assert "_File" in sources and "C_reate" in sources and "Save _as…" in sources
    assert not any("de_DE" in s or "en_GB" in s for s in sources)


@pytest.mark.parametrize("code", TARGETS)
def test_a_source_mnemonic_has_exactly_one_translated_access_key(code: str) -> None:
    problems = []
    for message in _messages(code):
        if not isinstance(message.id, str) or not _has_mnemonic(message.id):
            continue
        (form,) = _forms(message)
        if _marks(form) != 1 or split_mnemonic(_strip_fields(form))[1] < 0:
            problems.append((message.id, form))
    assert problems == []


@pytest.mark.parametrize("code", TARGETS)
def test_plural_forms_header_matches_the_locale(code: str) -> None:
    text = _po_path(code).read_text("utf-8")
    found = re.search(r'^"Plural-Forms: ([^"\\]*)\\n"$', text, re.MULTILINE)
    assert found is not None
    assert found.group(1).strip() == _PLURAL_FORMS.get(code, _DEFAULT_PLURAL_FORMS)


@pytest.mark.parametrize("code", TARGETS)
def test_compiled_catalogue_picks_the_right_plural_form(code: str) -> None:
    mo = _po_path(code).with_suffix(".mo")
    with mo.open("rb") as handle:
        translations = gettext.GNUTranslations(handle)
    one = "{count} more problem was found but not listed."
    many = "{count} more problems were found but not listed."
    forms = _forms(next(m for m in _messages(code) if isinstance(m.id, tuple) and m.id[0] == one))
    zero_form = 0 if code in _PLURAL_FORMS else 1
    assert translations.ngettext(one, many, 0) == forms[zero_form]
    assert translations.ngettext(one, many, 1) == forms[0]
    assert translations.ngettext(one, many, 2) == forms[1]


@pytest.mark.parametrize("code", TARGETS)
def test_catalogue_check_reports_nothing(code: str) -> None:
    catalog = _load(_po_path(code))
    assert [(m.id, errors) for m, errors in catalog.check()] == []


@pytest.mark.parametrize("code", TARGETS)
def test_committed_mo_is_up_to_date_with_its_po(code: str, tmp_path: Path) -> None:
    fresh = tmp_path / f"{code}.mo"
    with fresh.open("wb") as handle:
        write_mo(handle, _load(_po_path(code)))
    catalogues = []
    for path in (fresh, _po_path(code).with_suffix(".mo")):
        with path.open("rb") as handle:
            entries = dict(gettext.GNUTranslations(handle)._catalog)  # type: ignore[attr-defined]
        entries.pop("", None)  # the header may differ in the generator line
        catalogues.append(entries)
    assert catalogues[0] == catalogues[1], "stale .mo: re-run pybabel compile"


@pytest.mark.parametrize("code", sorted(_FORBIDDEN))
def test_no_term_of_the_other_portuguese_variant(code: str) -> None:
    pattern = _FORBIDDEN[code]
    problems = [
        (message.id, form)
        for message in _messages(code)
        for form in _forms(message)
        if pattern.search(split_mnemonic(form)[0])
    ]
    assert problems == []


@pytest.mark.parametrize("code", TARGETS)
def test_sticky_letters_stay_the_compass_letters(code: str) -> None:
    strings = {m.id: m.string for m in _messages(code) if isinstance(m.id, str)}
    assert {letter: strings[letter] for letter in _STICKY_LETTERS} == {
        letter: letter for letter in _STICKY_LETTERS
    }
