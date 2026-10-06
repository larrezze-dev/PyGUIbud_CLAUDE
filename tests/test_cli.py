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


def test_main_no_args() -> None:
    """Test that main with no arguments returns 0."""
    result = main([])
    assert result == 0


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


def test_pseudo_no_args(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--lang", "en_XA"]) == 0
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
        [sys.executable, "-m", "pyguibud", "--lang", "en_XA"],
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
