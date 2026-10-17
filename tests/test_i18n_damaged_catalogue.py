"""A damaged ``pyguibud.mo`` falls back to the source texts with one warning (QA-18-01).

``gettext.translation(fallback=True)`` falls back only when no file is found; a file that is found
but cannot be parsed raised out of ``set_language`` (``pyguibud --help`` crashed). Every case
damages a *copy* of the package's locale folder in ``tmp_path``; the real files are never touched.
"""

from __future__ import annotations

import gettext
import logging
import shutil
from collections.abc import Callable
from pathlib import Path

import pytest

import pyguibud_runtime._texts as runtime_texts
from pyguibud import cli, i18n, uic

ROOT = Path(__file__).resolve().parents[1]
HELLO = ROOT / "examples" / "hello.ui"
_I18N_LOG = "pyguibud.i18n"


def _replace(old: bytes, new: bytes) -> Callable[[bytes], bytes]:
    """A same-length replacement in the header, so every offset of the file stays valid."""
    assert len(old) == len(new)

    def damage(data: bytes) -> bytes:
        assert data.count(old) == 1
        return data.replace(old, new)

    return damage


#: name -> how the de_DE file is damaged; the comment is what gettext raised before the fix.
DAMAGE: dict[str, Callable[[bytes], bytes]] = {
    "truncated": lambda data: data[: len(data) // 2],  # OSError: File is corrupt
    "empty": lambda _data: b"",  # struct.error
    "bad magic": lambda data: b"XXXX" + data[4:],  # OSError: Bad magic number
    "header only": lambda data: data[:28],  # struct.error
    "unknown charset": _replace(b"charset=utf-8", b"charset=utf-9"),  # LookupError
    "bad plural": _replace(b"plural=(n != 1)", b"plural=(n !! 1)"),  # ValueError
}


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))


def _locale_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy = tmp_path / "locale"
    shutil.copytree(i18n.LOCALE_DIR, copy)
    monkeypatch.setattr(i18n, "LOCALE_DIR", copy)
    monkeypatch.setattr(runtime_texts, "LOCALE_DIR", copy)
    monkeypatch.setattr(gettext, "_translations", {})  # never reuse a parsed good catalogue
    return copy


@pytest.fixture(params=sorted(DAMAGE))
def damaged_de(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Path:
    copy = _locale_copy(tmp_path, monkeypatch)
    mo = copy / "de_DE" / "LC_MESSAGES" / "pyguibud.mo"
    mo.write_bytes(DAMAGE[request.param](mo.read_bytes()))
    return copy


def _warnings(caplog: pytest.LogCaptureFixture, name: str) -> list[str]:
    return [
        r.getMessage() for r in caplog.records if r.name == name and r.levelno == logging.WARNING
    ]


def test_the_damage_really_breaks_gettext(damaged_de: Path) -> None:
    """Guards the cases themselves: each one makes the plain gettext call raise."""
    with pytest.raises(Exception):  # noqa: B017 - several gettext error types
        gettext.translation("pyguibud", str(damaged_de), ["de_DE"], fallback=True)


def test_set_language_falls_back_to_the_source_texts_with_one_warning(
    damaged_de: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    assert i18n.set_language("de_DE") == "de_DE"  # like a missing file: the code is kept
    assert i18n._("_Open…") == "_Open…"
    problem = i18n.catalogue_problem()
    assert problem is not None
    assert "'pyguibud'" in problem and "'de_DE'" in problem and str(damaged_de) in problem
    assert _warnings(caplog, _I18N_LOG) == [problem]
    i18n.set_language("de_DE")  # the CLI sets the language twice: still one warning
    assert len(_warnings(caplog, _I18N_LOG)) == 1


def test_a_good_language_after_a_damaged_one_is_translated_again(damaged_de: Path) -> None:
    i18n.set_language("de_DE")
    i18n.set_language("fr_FR")
    assert i18n.catalogue_problem() is None
    assert i18n._("_Open…") != "_Open…"


def test_a_missing_catalogue_falls_back_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The existing behaviour: a missing file is gettext's own fallback, without a warning."""
    copy = _locale_copy(tmp_path, monkeypatch)
    shutil.rmtree(copy / "nl_NL")
    caplog.set_level(logging.WARNING)
    assert i18n.set_language("nl_NL") == "nl_NL"
    assert i18n._("_Open…") == "_Open…"
    assert i18n.catalogue_problem() is None
    assert _warnings(caplog, _I18N_LOG) == []


def test_load_catalogue_tells_a_damaged_file_from_a_missing_one(damaged_de: Path) -> None:
    damaged = i18n.load_catalogue("pyguibud", damaged_de, "de_DE")
    assert isinstance(damaged, i18n.UnusableCatalogue)
    assert damaged.params == {"domain": "pyguibud", "lang": "de_DE", "directory": str(damaged_de)}
    missing = i18n.load_catalogue("pyguibud", damaged_de, "ja_JP")
    assert type(missing) is gettext.NullTranslations
    good = i18n.load_catalogue("pyguibud", damaged_de, "fr_FR")
    assert not isinstance(good, i18n.UnusableCatalogue)


def test_the_cli_runs_in_english_and_warns_once(
    damaged_de: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    caplog.set_level(logging.WARNING)
    with pytest.raises(SystemExit) as stop:
        cli.main(["--lang", "de_DE", "--help"], launch=lambda *_a, **_k: 0)
    assert stop.value.code == 0
    assert "show the version number and exit" in capsys.readouterr().out
    assert len(_warnings(caplog, _I18N_LOG)) == 1


def test_a_cli_launch_sets_the_damaged_language_twice_but_warns_once(
    damaged_de: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The pre-parse and the real ``--lang`` both call set_language; one warning is enough."""
    caplog.set_level(logging.WARNING)
    launched: list[object] = []

    def launch(*args: object, **_keywords: object) -> int:
        launched.append(args)
        return 0

    assert cli.main(["--lang", "de_DE"], launch=launch) == 0
    assert launched and i18n.get_language() == "de_DE"
    assert len(_warnings(caplog, _I18N_LOG)) == 1


def test_uic_checks_in_english(
    damaged_de: Path, capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    assert uic.main(["--lang", "de_DE", "--check", str(HELLO)]) == 0
    assert "no errors found" in capsys.readouterr().out
    assert len(_warnings(caplog, _I18N_LOG)) == 1


def test_the_runtime_buttons_fall_back_with_one_warning(
    damaged_de: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.WARNING)
    texts = runtime_texts.Texts({}, "de_DE", None)
    assert texts.runtime_text("_Open…") == "_Open…"  # the runtime shares the pyguibud domain
    texts.rebuild("fr_FR", None)
    assert texts.runtime_text("_Open…") != "_Open…"  # a good catalogue is still used
    assert len(_warnings(caplog, "pyguibud_runtime")) == 1
    assert _warnings(caplog, _I18N_LOG) == []  # the runtime reports on its own logger
