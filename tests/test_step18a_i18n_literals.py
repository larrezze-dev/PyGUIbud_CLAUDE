"""Step 18a: literals stay out of translatable msgids, and runtime and CLI texts are translated.

Everything runs in the pseudo-locale ``en_XA``, which accents every letter of a msgid but keeps
``{placeholders}``: a literal (environment variable, option, command) that stays intact in the
output was passed as a placeholder, not written into the msgid.
"""

from __future__ import annotations

import gettext
import logging
from collections.abc import Iterator

import pytest

from pyguibud import i18n
from pyguibud.backends._tkmap import iso_date, split_headings
from pyguibud.backends.pyside6 import display_problem
from pyguibud.cli import main as cli_main
from pyguibud.core.model import Event
from pyguibud.uic import main as uic_main
from tests.core.test_plugins_17a import _check, _doc, _widget


@pytest.fixture(autouse=True)
def pseudo_language(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Run in ``en_XA`` and put the language state back afterwards."""
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    for variable in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(variable, raising=False)
    i18n.set_language("en_XA")
    yield


def _translated(text: str) -> bool:
    """True if ``text`` went through the pseudo-locale (bracketed, not the English source)."""
    return text.startswith("[") and "·" in text


def test_a_calendar_invalid_date_is_logged_in_the_interface_language(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        assert iso_date("2023-02-29") is None
    (message,) = [record.getMessage() for record in caplog.records]
    assert _translated(message)
    assert "2023-02-29" in message  # the value is a placeholder, not accented


def test_a_wrong_heading_count_is_logged_in_the_interface_language(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        assert split_headings("A;B", 3) == ["A", "B", ""]
    (message,) = [record.getMessage() for record in caplog.records]
    assert _translated(message)
    assert "2 " in message and " 3 " in message and "A;B" in message


def test_the_source_language_still_logs_the_english_sentences(
    caplog: pytest.LogCaptureFixture,
) -> None:
    i18n.set_language("en_GB")
    with caplog.at_level(logging.WARNING):
        iso_date("2023-02-29")
        split_headings("A", 2)
    assert [r.getMessage() for r in caplog.records] == [
        "The date '2023-02-29' is not a valid calendar date; it is ignored.",
        "1 column headings for 2 columns: 'A'",
    ]


@pytest.mark.parametrize(
    ("platform", "environ"),
    [("win32", {"QT_QPA_PLATFORM": "bogus"}), ("linux", {})],
)
def test_environment_variable_names_are_not_pseudo_localised(
    platform: str, environ: dict[str, str]
) -> None:
    reason = display_problem(platform, environ, ("qwindows.dll",))
    assert reason is not None and _translated(reason)
    assert "QT_QPA_PLATFORM" in reason
    if platform == "linux":
        assert "DISPLAY, WAYLAND_DISPLAY, QT_QPA_PLATFORM" in reason


def test_the_install_command_of_a_missing_plugin_is_not_pseudo_localised() -> None:
    report = _check(_doc(_widget("zz:Gauge", "Label", plugin="zz-gauge")))
    (finding,) = [f for f in report.findings if f.code == "validate.plugin_missing"]
    assert _translated(finding.message) and "pip install zz-gauge" in finding.message


def test_an_invalid_event_lists_its_names_untouched() -> None:
    report = _check(_doc(_widget("Label", events=(Event(name="nonsense", handler="on_x"),))))
    (finding,) = [f for f in report.findings if f.code == "validate.bad_event"]
    assert (
        "command, change, select, activate, focus_in, focus_out, key:<sequence>" in finding.message
    )


def test_cli_help_is_translated_including_the_argparse_texts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as stopped:
        cli_main(["--lang", "en_XA", "--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    for english in ("usage:", "positional arguments", "options:", "show this help message"):
        assert english not in out, english
    assert "--list-languages" in out and "--no-plugins" in out  # option names stay
    assert "show the version number" not in out  # translated as well


def test_uic_help_and_usage_errors_are_translated_and_keep_the_option_names(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        uic_main(["--lang", "en_XA", "--help"])
    out = capsys.readouterr().out
    assert "--extract" in out and "pyguibud-uic" in out and "<name>_ui.py" in out
    assert "usage:" not in out and "show this help message" not in out
    assert "pyguibud.widgets" in out
    with pytest.raises(SystemExit) as stopped:
        uic_main(["--lang", "en_XA", "--check", "-o", "x", "a.ui"])
    assert stopped.value.code == 2
    error = capsys.readouterr().err
    assert "-o" in error and "--check" in error and "cannot be used" not in error
