"""Tests for the PyGUIbud CLI."""

from __future__ import annotations

import gettext
import os
import subprocess
import sys
from collections.abc import Iterator

import pytest

import pyguibud
import pyguibud_runtime
from pyguibud import i18n
from pyguibud.cli import main


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))
    yield


def test_main_version(capsys: pytest.CaptureFixture[str]) -> None:
    """Test that --version flag exits with code 0 and prints the version."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert captured.out == f"pyguibud {pyguibud.__version__}\n"


class _Launch:
    """A fake designer launcher: records its arguments and returns a canned exit code."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[str, str]] = []

    def __call__(self, lang: str, theme: str) -> int:
        self.calls.append((lang, theme))
        return self.code


def test_main_no_args() -> None:
    """No arguments launches the designer with the default language and theme."""
    fake = _Launch()
    assert main([], launch=fake) == 0
    assert fake.calls == [("en_GB", "light")]


@pytest.mark.parametrize("theme", ["light", "dark", "high-contrast"])
def test_theme_option_is_passed_on(theme: str) -> None:
    fake = _Launch()
    assert main(["--theme", theme], launch=fake) == 0
    assert fake.calls == [("en_GB", theme)]


def test_launch_exit_code_is_returned() -> None:
    assert main([], launch=_Launch(1)) == 1


def test_invalid_theme_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _Launch()
    with pytest.raises(SystemExit) as exc_info:
        main(["--theme", "neon"], launch=fake)
    assert exc_info.value.code == 2
    assert fake.calls == []
    assert "Traceback" not in capsys.readouterr().err


def test_info_options_never_launch(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _Launch()
    assert main(["--list-languages"], launch=fake) == 0
    with pytest.raises(SystemExit):
        main(["--version"], launch=fake)
    with pytest.raises(SystemExit):
        main(["--help"], launch=fake)
    capsys.readouterr()
    assert fake.calls == []


def test_info_options_do_not_load_tk() -> None:
    code = (
        "import sys; from pyguibud.cli import main; main(['--list-languages']);"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('tkinter', 'ttkbootstrap')"
        " or m.startswith('pyguibud.designer'));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_version_sync() -> None:
    """Guard that runtime version matches designer version."""
    assert pyguibud_runtime.__version__ == pyguibud.__version__


def test_main_via_subprocess() -> None:
    """Test python -m pyguibud --version via subprocess."""
    result = subprocess.run(
        [sys.executable, "-m", "pyguibud", "--version"],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0
    assert result.stdout == f"pyguibud {pyguibud.__version__}\n"


def test_list_languages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--list-languages"]) == 0
    lines = capsys.readouterr().out.splitlines()
    rows = [line for line in lines if line[2:7] in i18n.LANGUAGES]
    assert [row[2:7] for row in rows] == list(i18n.LANGUAGES)
    assert rows[0].startswith("* en_GB")
    assert any("en_XA" in line for line in lines if line not in rows)
    assert "" in lines


def test_list_languages_marks_active(capsys: pytest.CaptureFixture[str]) -> None:
    main(["--lang", "de-DE", "--list-languages"])
    out = capsys.readouterr().out
    assert "* de_DE  Deutsch (Deutschland)" in out
    assert "  en_GB  English (United Kingdom)" in out


def test_pseudo_no_args() -> None:
    """--lang en_XA is active (and passed on) when the designer is launched."""
    fake = _Launch()
    assert main(["--lang", "en_XA"], launch=fake) == 0
    assert fake.calls == [("en_XA", "light")]
    assert i18n.get_language() == "en_XA"
    assert i18n._("Ready").startswith("[")


def test_pseudo_list_languages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "en_XA", "--list-languages"]) == 0
    out = capsys.readouterr().out
    assert "[" in out
    assert any(ch in out for ch in "áéíóúñ")


def test_pseudo_help(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--lang", "en_XA", "--help"])
    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    assert "[PýGÚÍbúd:" in out


def test_invalid_lang_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--lang", "xx_YY"])
    assert exc_info.value.code == 2
    err = capsys.readouterr().err
    assert "xx_YY" in err
    assert "de_DE" in err
    assert "Traceback" not in err


def test_missing_lang_value_exits_2() -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--lang"])
    assert exc_info.value.code == 2


def test_subprocess_pseudo_utf8() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(
        [sys.executable, "-m", "pyguibud", "--lang", "en_XA", "--list-languages"],
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    assert result.stdout.decode("utf-8").startswith("[")


def test_subprocess_survives_narrow_encoding() -> None:
    env = {**os.environ, "PYTHONIOENCODING": "ascii"}
    result = subprocess.run(
        [sys.executable, "-m", "pyguibud", "--list-languages"],
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0
    assert b"es_ES" in result.stdout
