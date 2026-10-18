"""QA abuse tests of Step 18 (the seven filled catalogues): the pure parts, without a Tk root
(the designer-driving cases are in ``tests/designer/test_qa18_abuse.py``, see the 16c note).

Passing tests pin behaviour QA checked and found correct. Strict ``xfail`` marks the findings
QA-18-NN that are still open; the debugger removes the mark with the fix.

A corrupt catalogue is always a *copy* of the package's locale folder in ``tmp_path``; the real
``.mo`` files are never touched.
"""

from __future__ import annotations

import gettext
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

import pyguibud_runtime._texts as runtime_texts
from pyguibud import cli, i18n, uic
from pyguibud.core.keys import split_mnemonic

TARGETS = ("es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR")
ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"


def _po(code: str) -> list[tuple[str, tuple[str, ...]]]:
    with open(i18n.LOCALE_DIR / code / "LC_MESSAGES" / "pyguibud.po", "rb") as stream:
        catalogue = read_po(stream)
    found = []
    for message in catalogue:
        if not message.id:
            continue
        msgid = message.id[0] if isinstance(message.id, (list, tuple)) else message.id
        forms = message.string if isinstance(message.string, (list, tuple)) else (message.string,)
        found.append((msgid, tuple(form or "" for form in forms)))
    return found


def _msgstr(code: str, msgid: str) -> str:
    return dict((key, forms[0]) for key, forms in _po(code))[msgid]


# ------------------------------------------------------------------ corrupt catalogues
@pytest.fixture(params=["truncated", "empty", "bad magic", "header only"])
def corrupt_de(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[Path]:
    """A copy of the locale folder whose de_DE ``pyguibud.mo`` is damaged in one way."""
    copy = tmp_path / "locale"
    shutil.copytree(i18n.LOCALE_DIR, copy)
    mo = copy / "de_DE" / "LC_MESSAGES" / "pyguibud.mo"
    data = mo.read_bytes()
    damaged = {
        "truncated": data[: len(data) // 2],
        "empty": b"",
        "bad magic": b"XXXX" + data[4:],
        "header only": data[:28],
    }[request.param]
    mo.write_bytes(damaged)
    monkeypatch.setattr(i18n, "LOCALE_DIR", copy)
    monkeypatch.setattr(runtime_texts, "LOCALE_DIR", copy)
    monkeypatch.setattr(gettext, "_translations", {})  # never reuse a parsed good catalogue
    yield copy


def test_qa18_01_a_corrupt_catalogue_falls_back_to_english(corrupt_de: Path) -> None:
    i18n.set_language("de_DE")
    assert i18n._("_Open…") == "_Open…"


def test_qa18_01_cli_version_survives_a_corrupt_catalogue(
    corrupt_de: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", "de_DE")
    with pytest.raises(SystemExit) as stop:
        cli.main(["--version"], launch=lambda *_a, **_k: 0)
    assert stop.value.code == 0


def test_qa18_01_uic_check_survives_a_corrupt_catalogue(
    corrupt_de: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert uic.main(["--lang", "de_DE", "--check", str(HELLO)]) == 0
    assert "no errors found" in capsys.readouterr().out


def test_qa18_01_runtime_texts_survive_a_corrupt_runtime_catalogue(corrupt_de: Path) -> None:
    texts = runtime_texts.Texts({}, "de_DE", None)
    assert texts.runtime_text("OK") == "OK"


def test_a_missing_catalogue_falls_back_to_english(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    copy = tmp_path / "locale"
    shutil.copytree(i18n.LOCALE_DIR, copy)
    shutil.rmtree(copy / "nl_NL")
    monkeypatch.setattr(i18n, "LOCALE_DIR", copy)
    monkeypatch.setattr(gettext, "_translations", {})
    assert i18n.set_language("nl_NL") == "nl_NL"
    assert i18n._("_Open…") == "_Open…"


def test_a_msgid_missing_from_a_catalogue_shows_the_english_source() -> None:
    i18n.set_language("fr_FR")
    assert i18n._("A sentence QA made up that no catalogue has.") == (
        "A sentence QA made up that no catalogue has."
    )
    assert i18n._("_Open…") != "_Open…"  # the catalogue itself is in use


# ------------------------------------------------------------------ language codes
@pytest.mark.parametrize(
    "value",
    ["", "   ", "../", "..\\..\\x", "xx_YY", "de_DE/../x", "x" * 10_000, "C", "POSIX"],
)
def test_garbage_in_pyguibud_lang_never_raises(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", value)
    found = i18n.detect_language()
    assert found in i18n.LANGUAGES or found == i18n.PSEUDO_LANGUAGE


@pytest.mark.parametrize(
    ("value", "expected"),
    [("de-DE", "de_DE"), ("DE_de", "de_DE"), ("pt-br", "pt_BR"), ("pt", "pt_PT"),
     ("fr_CA", "fr_FR"), ("de_DE.UTF-8", "de_DE"), ("en_xa", "en_XA")],
)  # fmt: skip
def test_spellings_of_a_language_resolve(value: str, expected: str) -> None:
    assert i18n.normalise_language(value) == expected


@pytest.mark.parametrize("value", ["", "../", "xx_YY", "de_DE/../x", "en_XA;rm", "DE DE"])
def test_cli_refuses_a_bad_lang_with_a_usage_error(
    value: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as stop:
        cli.main(["--lang", value], launch=lambda *_a, **_k: 0)
    assert stop.value.code == 2
    assert "Traceback" not in capsys.readouterr().err


# ------------------------------------------------------------------ console encodings
@pytest.mark.parametrize("encoding", ["cp1252", "cp850", "ascii"])
@pytest.mark.parametrize("code", ["pt_BR", "de_DE", "nl_NL", "fr_FR"])
def test_help_on_a_legacy_console_never_crashes(encoding: str, code: str, tmp_path: Path) -> None:
    env = {**os.environ, "PYGUIBUD_LANG": code, "PYTHONIOENCODING": encoding}
    env.pop("PYTHONUTF8", None)
    out = tmp_path / "help.txt"
    with open(out, "wb") as stream:
        done = subprocess.run(
            [sys.executable, "-m", "pyguibud", "--help"],
            stdout=stream, stderr=subprocess.PIPE, env=env, timeout=60, check=False,
        )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode(encoding, "replace")
    assert b"Traceback" not in done.stderr
    assert out.stat().st_size > 200


# ------------------------------------------------------------------ catalogue quality
@pytest.mark.parametrize("code", TARGETS)
def test_qa18_02_usage_prefix_keeps_its_trailing_space(code: str) -> None:
    """The translator note says to keep the space; fr gives ``usage :pyguibud``."""
    assert _msgstr(code, "usage: ").endswith(" ")


def test_qa18_02_french_help_separates_usage_from_the_program(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.main(["--lang", "fr_FR", "--help"], launch=lambda *_a, **_k: 0)
    first = capsys.readouterr().out.splitlines()[0]
    assert first.startswith("usage" + _NBSP + ": pyguibud"), first


_NBSP, _NNBSP = chr(0xA0), chr(0x202F)
_FR_SPACE = re.compile(r"\S [:;?!](?:\s|$)")
_FR_GLUED = re.compile(r"[^\s" + _NBSP + _NNBSP + r""":{}'"/\\\d][;?!](?:\s|$)""")


def test_qa18_03_french_high_punctuation_uses_a_non_breaking_space() -> None:
    plain = [
        (msgid, form)
        for msgid, forms in _po("fr_FR")
        for form in forms
        if form and _FR_SPACE.search(form) and "://" not in form
    ]
    assert plain == []


def test_french_never_glues_high_punctuation_to_the_word() -> None:
    glued = [
        form for _msgid, forms in _po("fr_FR") for form in forms if form and _FR_GLUED.search(form)
    ]
    assert glued == []


def test_qa18_06_german_names_the_panel_consistently() -> None:
    """One German word for "panel" everywhere (``panel`` is missing from the glossary)."""
    words = set()
    for msgid, msgs in _po("de_DE"):
        if re.search(r"\bpa_?n_?e_?l\b", msgid, re.IGNORECASE):
            for form in msgs:
                shown = split_mnemonic(form)[0]
                words |= {w for w in ("Panel", "Bereich", "Fenster") if w in shown}
    assert len(words) == 1, words


def test_qa18_07_european_portuguese_possessives_take_the_article() -> None:
    bare = [
        form
        for _msgid, forms in _po("pt_PT")
        for form in forms
        if re.search(r"\be (seu|sua|seus|suas) ", form)
    ]
    assert bare == []


@pytest.mark.parametrize("code", TARGETS)
@pytest.mark.parametrize("count", [0, 1, 2, 5])
def test_plural_sentences_render_their_number(code: str, count: int) -> None:
    i18n.set_language(code)
    text = i18n.ngettext(
        "{count} plugin problem — see Help ▸ Plugins.",
        "{count} plugin problems — see Help ▸ Plugins.",
        count,
    ).format(count=count)
    assert str(count) in text and "{" not in text
    help_menu = split_mnemonic(i18n._("_Help"))[0]
    plugins_item = split_mnemonic(i18n._("_Plugins…"))[0].rstrip("…")
    assert f"{help_menu} ▸ {plugins_item}" in text  # the cited path matches the real menu


@pytest.mark.parametrize("argv", [["--bogus"], ["--theme", "hell"], ["--lang"]])
def test_qa18_04_argparse_errors_are_translated(
    argv: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", "de_DE")
    with pytest.raises(SystemExit):
        cli.main(argv, launch=lambda *_a, **_k: 0)
    err = capsys.readouterr().err
    english = ("unrecognized arguments", "invalid choice", "expected one argument")
    assert not any(word in err for word in english), err


_KEY_TOKEN = re.compile(r"(?:key:)?((?:[A-Za-z]+\+)+[A-Za-z0-9]+)")


def test_qa18_11_the_key_examples_are_placeholders_not_text() -> None:
    """fr_FR suggested ``Ctrl+Maj+F5``, which the validator refuses: the examples are now
    placeholders filled with literal key names, so no translation can change them."""
    from pyguibud.core.validate import _M_BAD_KEY_SEQUENCE, _M_BAD_SHORTCUT

    for msgid in (_M_BAD_SHORTCUT, _M_BAD_KEY_SEQUENCE):
        assert _KEY_TOKEN.findall(msgid) == [], msgid
        assert "{example}" in msgid and "{other}" in msgid


@pytest.mark.parametrize("code", (*TARGETS, "en_XA"))
def test_qa18_11_the_shortcut_examples_in_the_errors_are_valid(code: str) -> None:
    from pyguibud.core.errors import format_message
    from pyguibud.core.keys import is_valid_key_sequence
    from pyguibud.core.validate import (
        _KEY_EXAMPLES,
        _M_BAD_KEY_SEQUENCE,
        _M_BAD_SHORTCUT,
        _SHORTCUT_EXAMPLES,
    )

    i18n.set_language(code)
    cases = (
        (_M_BAD_SHORTCUT, _SHORTCUT_EXAMPLES, ""),
        (_M_BAD_KEY_SEQUENCE, _KEY_EXAMPLES, "key:"),
    )
    for msgid, examples, prefix in cases:
        text = format_message(msgid, {"value": "?", **examples})
        assert all(example in text for example in examples.values()), text
        assert all(example.startswith(prefix) for example in examples.values())
        sequences = [example[len(prefix) :] for example in examples.values()]
        assert [s for s in sequences if not is_valid_key_sequence(s)] == []


def _theme_help(capsys: pytest.CaptureFixture[str], code: str) -> str:
    """The --theme paragraph of ``pyguibud --help``, without argparse's own list of choices."""
    with pytest.raises(SystemExit):
        cli.main(["--lang", code, "--help"], launch=lambda *_a, **_k: 0)
    out = capsys.readouterr().out
    paragraph = out[out.rindex("--theme") : out.rindex("--no-plugins")]  # not the usage line
    return " ".join(paragraph.replace("{light,dark,high-contrast}", "").split())


@pytest.mark.parametrize("code", (*TARGETS, "en_XA"))
def test_qa18_12_theme_help_names_the_accepted_token(
    code: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default theme is a placeholder: the help names ``light``, the token --theme accepts."""
    assert re.search(r"\blight\b", _theme_help(capsys, code))


def test_theme_help_in_british_english_is_unchanged(capsys: pytest.CaptureFixture[str]) -> None:
    expected = "designer colour theme (default: the last one used, else light)"
    assert expected in _theme_help(capsys, "en_GB")


# ------------------------------------------------------------------ pass 2: exotic damage
def _damaged_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A copy of the locale folder, active for the i18n module; returns the de_DE .mo path."""
    copy = tmp_path / "locale"
    shutil.copytree(i18n.LOCALE_DIR, copy)
    monkeypatch.setattr(i18n, "LOCALE_DIR", copy)
    monkeypatch.setattr(runtime_texts, "LOCALE_DIR", copy)
    monkeypatch.setattr(gettext, "_translations", {})
    return copy / "de_DE" / "LC_MESSAGES" / "pyguibud.mo"


def _rewrite_header(mo: Path, old: bytes, new: bytes) -> None:
    """Replace header bytes in place: same length, so every string offset stays valid."""
    assert len(new) == len(old)
    data = mo.read_bytes()
    start = data.lower().index(old.lower())  # babel writes ``charset=utf-8`` in lower case
    mo.write_bytes(data[:start] + new + data[start + len(old) :])


_PLURAL = (
    "{count} plugin problem — see Help ▸ Plugins.",
    "{count} plugin problems — see Help ▸ Plugins.",
)


@pytest.mark.parametrize("damage", ["directory", "unknown charset", "bad plural"])
def test_exotic_damage_to_a_catalogue_falls_back_to_english(
    damage: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mo = _damaged_copy(tmp_path, monkeypatch)
    if damage == "directory":  # a .mo path that is a folder: open() raises PermissionError
        mo.unlink()
        mo.mkdir()
    elif damage == "unknown charset":
        _rewrite_header(mo, b"charset=utf-8", b"charset=xxx-9")
    else:
        _rewrite_header(mo, b"plural=(n != 1)", b"plural=(n!=! 1)")
    i18n.set_language("de_DE", force=True)
    assert i18n._("_Open…") == "_Open…"
    assert i18n.ngettext(*_PLURAL, 3) == _PLURAL[1]
    assert i18n.catalogue_problem()


def test_a_plural_rule_past_the_forms_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valid but wrong Plural-Forms (index 8 of 2 forms): German texts, English plurals."""
    mo = _damaged_copy(tmp_path, monkeypatch)
    _rewrite_header(mo, b"plural=(n != 1)", b"plural=(n + 7) ")
    i18n.set_language("de_DE", force=True)
    assert i18n._("_Open…") != "_Open…"  # the catalogue itself is read
    assert i18n.ngettext(*_PLURAL, 3) == _PLURAL[1]  # the lookup misses: the source plural
    assert i18n.catalogue_problem() is None


@pytest.mark.parametrize(
    "tool, argv, code",
    [
        ("pyguibud", ["--version"], 0),
        ("pyguibud", ["--list-languages"], 0),
        ("uic", ["--check", str(HELLO)], 0),
        ("pyguibud", ["--bogus"], 2),
    ],
)
def test_the_cli_with_a_damaged_catalogue_warns_once_and_exits_cleanly(
    tool: str,
    argv: list[str],
    code: int,
    corrupt_de: Path,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    try:
        result: object = (
            cli.main(["--lang", "de_DE", *argv], launch=lambda *_a, **_k: 0)
            if tool == "pyguibud"
            else uic.main(["--lang", "de_DE", *argv])
        )
    except SystemExit as stop:
        result = stop.code
    assert (result or 0) == code
    assert "Traceback" not in capsys.readouterr().err
    warnings = [r for r in caplog.records if "No usable translations" in r.getMessage()]
    assert len(warnings) == 1


# ------------------------------------------------------------------ pass 2: new findings
def _help(capsys: pytest.CaptureFixture[str], tool: str, code: str) -> str:
    with pytest.raises(SystemExit):
        if tool == "pyguibud":
            cli.main(["--lang", code, "--help"], launch=lambda *_a, **_k: 0)
        else:
            uic.main(["--lang", code, "--help"])
    return capsys.readouterr().out


@pytest.mark.parametrize("tool", ["pyguibud", "uic"])
def test_qa18_13_french_help_section_titles_space_their_colon(
    tool: str, capsys: pytest.CaptureFixture[str]
) -> None:
    headings = [
        line for line in _help(capsys, tool, "fr_FR").splitlines() if re.match(r"^\S.*:$", line)
    ]
    assert headings  # "arguments positionnels:", "options:"
    assert all(line.endswith(_NBSP + ":") for line in headings), headings


_GENERATE_HELP = (
    "output file (generate: default {pattern} next to the .ui file; {extract}: "
    "default standard output)"
)


def test_qa18_14_the_generate_mode_is_translated() -> None:
    english = [code for code in TARGETS if "(generate:" in _msgstr(code, _GENERATE_HELP)]
    assert english == []


def test_qa18_15_french_trust_sentence_is_grammatical() -> None:
    msgid = (
        "The check loads the installed widget plugins (entry point {group}), which runs "
        "their code; only check files with plugins you trust."
    )
    assert "dont vous faites confiance" not in _msgstr("fr_FR", msgid)
