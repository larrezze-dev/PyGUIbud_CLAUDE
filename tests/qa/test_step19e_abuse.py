"""QA 19e: CLI, messages and catalogues (``docs/specs/hardening.md`` section 3, H70-H83).

Attacks the argparse binding of ``PyGUIbudParser`` (every locale, bad arguments, reentrancy,
threads, the < 3.12 heading fallback), the shared ``core.text.printable`` escape on every
output it is meant to protect (uic, ``Finding``, ``UiError``, export, clipboard, the designer
status bar), the catalogue hygiene (obsolete entries, contexts, printf placeholders, the credit
line) and the new designer texts (About dialog, "Opened with N error(s)", the Delete window
hint, menu access keys). Findings keep their ids ``QA-19e-NN``.
"""

from __future__ import annotations

import argparse
import contextlib
import gettext
import io
import os
import re
import subprocess
import sys
import threading
import types
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from babel.messages.catalog import Catalog
from babel.messages.pofile import read_po

from pyguibud import _argparse, cli, i18n, uic
from pyguibud.core.diagnostics import Finding
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.text import printable
from pyguibud.credits import AUTHOR, TOOL, credit

ROOT = Path(__file__).resolve().parents[2]
LOCALE_DIR = ROOT / "src" / "pyguibud" / "locale"
POT = LOCALE_DIR / "pyguibud.pot"
BIDI = ROOT / "tests" / "data" / "hardening" / "bidi_id.ui"
TARGETS = ("es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR")
LOCALES = ("en_GB", *TARGETS, "en_XA")
NBSP = "\u00a0"
HEAD = (
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"'
    ' xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">'
)
#: Every character class ``printable`` must neutralise, plus a forged GCC line.
FORGED = "a\nx.ui:1:1: error: forged\r\x1b[31m\x00\x7f\x85\u202e\u2066gnp.exe\u2069\u202c"
#: Raw characters that must never reach an output line.
UNSAFE = re.compile("[\x00-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
#: Line or bidi controls that ``printable`` once let through (QA-19e-04).
LEFT_OUT = "\u2028\u2029\u200e\u200f\u061c"


@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings and recovery data go to temporary folders, never the real profile."""
    base = tmp_path_factory.mktemp("profile19e")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))


@pytest.fixture(autouse=True)
def cli_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """A known wrap width (argparse reads COLUMNS) and a PYGUIBUD_LANG that monkeypatch
    removes again, so ``_run`` never leaks a language into later tests."""
    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setenv("PYGUIBUD_LANG", "en_GB")


@pytest.fixture(autouse=True)
def argparse_untouched() -> Iterator[None]:
    """Every test must leave argparse's module globals as it found them."""
    saved = argparse._, argparse.ngettext  # type: ignore[attr-defined]
    yield
    leaked = (argparse._, argparse.ngettext) != saved  # type: ignore[attr-defined]
    argparse._, argparse.ngettext = saved  # type: ignore[attr-defined]
    assert not leaked, "argparse's _/ngettext were left patched"


def _write(path: Path, body: str) -> Path:
    path.write_text(f"{HEAD}{body}</pyguibud-ui>", encoding="utf-8")
    return path


# ================================================================ A. argparse in every locale
_TOOLS: dict[str, Callable[[list[str]], object]] = {
    "pyguibud": lambda argv: cli.main(argv, launch=lambda *_a, **_k: 0),
    "pyguibud-uic": uic.main,
}


def _preview(argv: list[str]) -> object:
    from pyguibud import preview

    return preview._parser().parse_args(argv)  # the child's parser, in the active language


_BAD: list[tuple[str, list[str]]] = [
    ("pyguibud", ["--bogus"]),
    ("pyguibud", ["--l", "x"]),  # ambiguous: --lang, --list-languages
    ("pyguibud", ["--theme", "hell"]),
    ("pyguibud", ["--theme", "dark", "--theme", "x"]),
    ("pyguibud", ["--lang"]),
    ("pyguibud", ["--lang", "de_DE/../x"]),
    ("pyguibud", ["a.ui", "b.ui"]),
    ("pyguibud", ["--no-plugins=1"]),
    ("pyguibud-uic", []),
    ("pyguibud-uic", ["--bogus", "a.ui"]),
    ("pyguibud-uic", ["-o"]),
    ("pyguibud-uic", ["--check", "--extract", "a.ui"]),
    ("pyguibud-uic", ["-o", "x.py", "--check", "a.ui"]),
    ("pyguibud-uic", ["--force", "--check", "a.ui"]),
    ("pyguibud.preview", []),
    ("pyguibud.preview", ["--bogus", "f.ui"]),
    ("pyguibud.preview", ["--window"]),
]


def _run(tool: str, argv: list[str], code: str) -> tuple[object, str, str]:
    os.environ["PYGUIBUD_LANG"] = code  # undone by cli_environment's monkeypatch.setenv
    out, err = io.StringIO(), io.StringIO()
    status: object = None
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            if tool == "pyguibud.preview":
                i18n.set_language(code)
                _preview(argv)
            else:
                _TOOLS[tool](argv)
        except SystemExit as exc:
            status = exc.code
    return status, out.getvalue(), err.getvalue()


_FORMAT = re.compile(r"%\([^)]*\)[a-z]|%[a-z]")


def _english_fragments(code: str) -> list[str]:
    """Fixed English text of every argparse msgid that this locale translates differently."""
    i18n.set_language(code)
    fragments: list[str] = []
    for msgid in _argparse._ARGPARSE_MSGIDS:
        translated = i18n._(msgid)
        for part in _FORMAT.split(msgid):
            part = part.strip(" :\n()")
            if len(part) >= 6 and part not in translated:
                fragments.append(part)
    return fragments


@pytest.mark.parametrize("code", [*TARGETS, "en_XA"])
@pytest.mark.parametrize(("tool", "argv"), _BAD, ids=[f"{t}:{' '.join(a)}" for t, a in _BAD])
def test_argparse_usage_errors_are_translated(tool: str, argv: list[str], code: str) -> None:
    """H70: no English argparse text, exit 2, the translated "usage" and "error" prefixes."""
    status, _out, err = _run(tool, argv, code)
    assert status == 2, err
    leaks = [f for f in _english_fragments(code) if f in err]
    assert leaks == [], err
    i18n.set_language(code)
    assert err.startswith(i18n._("usage: ").strip()), err
    prog = tool
    prefix = i18n._("%(prog)s: error: %(message)s\n") % {"prog": prog, "message": "\x00"}
    assert prefix.partition("\x00")[0] in err, err


@pytest.mark.parametrize("code", LOCALES)
@pytest.mark.parametrize("tool", ["pyguibud", "pyguibud-uic"])
def test_the_error_line_ends_with_its_newline(tool: str, code: str) -> None:
    _status, _out, err = _run(tool, ["--bogus", "a.ui"], code)
    assert err.endswith("\n") and not err.endswith("\n\n"), repr(err[-60:])


def _headings(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.match(r"^\S.*:$", line)]


@pytest.mark.parametrize("code", LOCALES)
@pytest.mark.parametrize("tool", ["pyguibud", "pyguibud-uic"])
def test_help_is_translated_and_credits_the_author(tool: str, code: str) -> None:
    status, out, err = _run(tool, ["--lang", code, "--help"], code)
    assert status == 0 and err == "", err
    i18n.set_language(code)
    assert out.startswith(i18n._("usage: ")), out[:40]
    assert "%(" not in out and "%%" not in out
    assert " ".join(out.split()).endswith(" ".join(credit().split()))  # the epilog, wrapped
    lines = out.splitlines()
    for title in ("options", "positional arguments"):  # each heading alone on its line
        assert i18n._("%(heading)s:") % {"heading": i18n._(title)} in lines, title
    if code == "fr_FR":  # H71
        headings = _headings(out)
        assert len(headings) == 2 and all(h.endswith(NBSP + ":") for h in headings), headings


@pytest.mark.parametrize("code", ["de_DE", "nl_NL"])
def test_the_help_never_splits_the_product_name(code: str) -> None:
    _status, out, _err = _run("pyguibud", ["--lang", code, "--help"], code)
    assert TOOL in out
    for english in ("show this help message and exit", "positional arguments"):
        if i18n._(english) != english:
            assert english not in out


@pytest.mark.parametrize("code", LOCALES)
@pytest.mark.parametrize("tool", ["pyguibud", "pyguibud-uic"])
def test_version_is_two_lines_with_the_translated_credit(tool: str, code: str) -> None:
    status, out, _err = _run(tool, ["--lang", code, "--version"], code)
    i18n.set_language(code)
    assert status == 0
    lines = out.splitlines()
    assert len(lines) == 2, lines
    assert lines[0].startswith(f"{tool} ") and lines[1] == credit()


def test_a_percent_in_the_credit_does_not_break_version(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "credit", lambda: "100 % sûr %(prog)s %s")
    with pytest.raises(SystemExit) as info:
        cli.main(["--version"], launch=lambda *_a, **_k: 0)
    assert info.value.code == 0
    assert capsys.readouterr().out.splitlines()[1] == "100 % sûr %(prog)s %s"


@pytest.mark.skipif(sys.version_info[:2] != (3, 12), reason="the msgid list of argparse 3.12")
def test_every_reachable_argparse_text_is_marked() -> None:
    """The running argparse's msgids are all in ``_ARGPARSE_MSGIDS`` but for unreachable ones
    (sub-commands, FileType, programmer errors)."""
    import ast
    import inspect

    unreachable = {
        "%r is not callable",
        "'required' is an invalid argument for positionals",
        ".__call__() not defined",
        'argument "-" with mode %r',
        "can't open '%(filename)s': %(error)s",
        "cannot have multiple subparser arguments",
        "cannot merge actions - two groups are named %r",
        "conflicting option string: %s",
        "conflicting subparser alias: %s",
        "conflicting subparser: %s",
        "dest= is required for options like %r",
        "invalid conflict_resolution value: %r",
        "invalid option string %(option)r: must start with a character %(prefix_chars)r",
        "mutually exclusive arguments must be optional",
        "subcommands",
        "unknown parser %(parser_name)r (choices: %(choices)s)",
    }
    found = set()
    for node in ast.walk(ast.parse(inspect.getsource(argparse))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_", "ngettext"):
            texts = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if texts and isinstance(texts[0], str):
                found.add(texts[0])
    assert found - set(_argparse._ARGPARSE_MSGIDS) - unreachable == set()


@pytest.mark.parametrize("code", TARGETS)
def test_every_argparse_text_is_translated_with_its_placeholders(code: str) -> None:
    i18n.set_language(code)
    for msgid in _argparse._ARGPARSE_MSGIDS:
        translated = i18n._(msgid)
        assert sorted(_FORMAT.findall(translated)) == sorted(_FORMAT.findall(msgid)), msgid
        assert translated.endswith("\n") == msgid.endswith("\n"), msgid
        if code == "fr_FR":
            assert not re.search(r"[^\u00a0]:", translated.replace("://", "")), translated


# ---------------------------------------------------------------- reentrancy and restoring
def test_globals_are_restored_after_a_type_callable_raises() -> None:
    def boom(_value: str) -> str:
        raise RuntimeError("boom")

    parser = _argparse.PyGUIbudParser(prog="p")
    parser.add_argument("--x", type=boom)
    with pytest.raises(RuntimeError):
        parser.parse_args(["--x", "1"])
    assert argparse._ is gettext.gettext  # type: ignore[attr-defined]


def test_globals_are_restored_after_keyboard_interrupt() -> None:
    def stop(_value: str) -> str:
        raise KeyboardInterrupt

    parser = _argparse.PyGUIbudParser(prog="p")
    parser.add_argument("x", type=stop)
    with pytest.raises(KeyboardInterrupt):
        parser.parse_known_args(["1"])
    assert argparse._ is gettext.gettext  # type: ignore[attr-defined]


def test_a_parser_built_and_failing_inside_another_parse_restores_both(
    capsys: pytest.CaptureFixture[str],
) -> None:
    i18n.set_language("de_DE")
    seen: list[object] = []

    def nested(value: str) -> str:
        inner = _argparse.PyGUIbudParser(prog="inner")
        inner.add_argument("--y", choices=["a"])
        with pytest.raises(SystemExit):
            inner.parse_args(["--y", value])
        seen.append(argparse._)  # type: ignore[attr-defined]  # still ours: the outer parse
        return value

    outer = _argparse.PyGUIbudParser(prog="outer")
    outer.add_argument("--x", type=nested)
    with pytest.raises(SystemExit):
        outer.parse_args(["--x", "b", "--bogus"])
    err = capsys.readouterr().err
    assert seen == [i18n._] and "ungültige Auswahl" in err and "nicht erkannte" in err
    assert argparse._ is gettext.gettext  # type: ignore[attr-defined]


def test_two_threads_parsing_leave_argparse_clean() -> None:
    a_in, b_in, a_go, b_go = (threading.Event() for _ in range(4))

    def waiter(entered: threading.Event, go: threading.Event) -> Callable[[str], str]:
        def convert(value: str) -> str:
            entered.set()
            go.wait(5)
            return value

        return convert

    def parse(convert: Callable[[str], str]) -> None:
        parser = _argparse.PyGUIbudParser(prog="t")
        parser.add_argument("x", type=convert)
        parser.parse_args(["1"])

    first = threading.Thread(target=parse, args=(waiter(a_in, a_go),))
    second = threading.Thread(target=parse, args=(waiter(b_in, b_go),))
    first.start()
    assert a_in.wait(5)
    second.start()
    assert b_in.wait(5)
    a_go.set()
    first.join(5)
    b_go.set()
    second.join(5)
    patched = argparse._ is not gettext.gettext  # type: ignore[attr-defined]
    argparse._, argparse.ngettext = gettext.gettext, gettext.ngettext  # type: ignore[attr-defined]
    assert not patched


# ---------------------------------------------------------------- the < 3.12 fallback (R6)
class _Sys311(types.ModuleType):
    """``sys`` as seen on Python 3.11: every attribute is the real one but ``version_info``."""

    version_info = (3, 11, 0)

    def __getattr__(self, name: str) -> Any:
        return getattr(sys, name)


def _format_help_311(self: Any) -> str:
    """``HelpFormatter._Section.format_help`` of Python 3.10/3.11 (no translated colon)."""
    if self.parent is not None:
        self.formatter._indent()
    join = self.formatter._join_parts
    item_help = join([func(*args) for func, args in self.items])
    if self.parent is not None:
        self.formatter._dedent()
    if not item_help:
        return ""
    if self.heading is not argparse.SUPPRESS and self.heading is not None:
        current_indent = self.formatter._current_indent
        heading = "%*s%s:\n" % (current_indent, "", self.heading)  # noqa: UP031 - argparse 3.11 verbatim
    else:
        heading = ""
    return str(join(["\n", heading, item_help, "\n"]))


@pytest.mark.parametrize("tool", ["pyguibud", "pyguibud-uic"])
def test_french_headings_on_python_3_11(tool: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(argparse.HelpFormatter._Section, "format_help", _format_help_311)
    monkeypatch.setattr(_argparse, "sys", _Sys311("sys"))
    _status, out, _err = _run(tool, ["--lang", "fr_FR", "--help"], "fr_FR")
    headings = _headings(out)
    assert headings and all(h.endswith(NBSP + ":") for h in headings), out


def test_the_fallback_replacement_keeps_the_heading_on_its_own_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(argparse.HelpFormatter._Section, "format_help", _format_help_311)
    monkeypatch.setattr(_argparse, "sys", _Sys311("sys"))
    formatter = _argparse._Formatter("p")
    formatter.start_section("options")
    formatter.add_text("body")
    section = formatter._current_section
    lines = section.format_help().splitlines()
    assert lines[1].strip() == "options:" and "body" not in lines[1], lines  # its own line


# ---------------------------------------------------------------- the preview child (H72)
def test_the_preview_child_speaks_the_interface_language() -> None:
    env = {**os.environ, "PYGUIBUD_LANG": "de_DE", "PYTHONIOENCODING": "utf-8"}
    done = subprocess.run(
        [sys.executable, "-m", "pyguibud.preview", "--ui-lang", "de_DE", "--lang", "../x", "f.ui"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=60,
        check=False,
    )
    assert done.returncode == 2
    assert "Fehler" in done.stderr and "error:" not in done.stderr, done.stderr


# ================================================================ B. catalogues
def _po(code: str) -> Path:
    return LOCALE_DIR / code / "LC_MESSAGES" / "pyguibud.po"


@pytest.mark.parametrize("code", ("en_GB", *TARGETS))
def test_no_obsolete_entries_are_left(code: str) -> None:
    """H75."""
    assert "#~" not in _po(code).read_text(encoding="utf-8")


@pytest.mark.parametrize("code", TARGETS)
def test_the_two_previews_have_their_own_context(code: str) -> None:
    """H78: msgctxt "menu" and "action" both exist, translated and with one access key."""
    catalogue = read_po(_po(code).open("rb"))
    for context in ("menu", "action"):
        message = catalogue.get("_Preview", context=context)
        assert message is not None and message.string, context
        assert message.string.count("_") == 1
    assert catalogue.get("_Preview") is None  # the old context-less msgid is gone


def test_every_percent_msgid_is_flagged_python_format() -> None:
    """Babel's ``check()`` only checks printf placeholders of flagged messages."""
    for message in read_po(POT.open("rb")):
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        if message.id and any(_FORMAT.search(str(i)) for i in ids):
            assert "python-format" in message.flags, message.id


@pytest.mark.parametrize(
    "broken",
    ["nicht erkannte Argumente", "nicht erkannte Argumente: %s %s", "nicht erkannt: %d"],
)
def test_the_gate_catches_a_broken_printf_translation(broken: str) -> None:
    """A dropped, doubled or retyped ``%s`` would crash argparse at run time."""
    catalogue = Catalog(locale="de_DE")
    catalogue.add("unrecognized arguments: %s", broken, flags=("python-format",))
    assert [m.id for m, errors in catalogue.check() if errors] == ["unrecognized arguments: %s"]


@pytest.mark.parametrize("code", TARGETS)
def test_the_credit_is_translated_with_both_names(code: str) -> None:
    i18n.set_language(code)
    text = credit()
    assert AUTHOR in text and TOOL in text
    assert text != f"Created by {AUTHOR} and programmed with the support of {TOOL}"
    if code == "es_ES":  # the CLAUDE.md wording
        assert text == f"Creado por {AUTHOR} y programado con el soporte de {TOOL}"


def test_no_literal_key_name_in_any_msgid() -> None:
    """H79 acceptance: key names are placeholders, never text a translator could change."""
    keys = re.compile(
        r"Ctrl\b|\bF\d{1,2}\b|\bEnter\b|\bEsc(ape)?\b|\bShift\b|\bAlt\b|\bTab\b|\bSpace\b|"
        r"Page(Up|Down)|\bBackspace\b|\bReturn\b"
    )
    hits = []
    for message in read_po(POT.open("rb")):
        ids = message.id if isinstance(message.id, tuple) else (message.id,)
        hits += [i for i in ids if i and keys.search(str(i))]
    assert hits == []


@pytest.mark.parametrize("code", LOCALES)
def test_the_shortcut_modifier_error_names_real_keys(code: str, tmp_path: Path) -> None:
    from pyguibud.core import default_registry, read_ui
    from pyguibud.core.validate import validate_read

    path = _write(
        tmp_path / "keys.ui",
        '<window id="main" kind="main"><layout type="grid"/><menubar><menu id="m">'
        '<action id="act" shortcut="Q"/></menu></menubar></window>',
    )
    i18n.set_language(code)
    report = validate_read(read_ui(str(path)), default_registry())
    texts = [f.message for f in report.findings if "shortcut" in f.code]
    assert texts, [f.code for f in report.findings]
    for text in texts:
        assert "{" not in text and "Ctrl" in text and "F24" in text, text


# ================================================================ C. printable (H81)
@pytest.mark.parametrize(
    "char",
    [
        *map(chr, range(0x20)),
        "\x7f",
        "\x85",
        "\x9f",
        *map(chr, [0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069]),
    ],
)
def test_printable_escapes_every_control(char: str) -> None:
    shown = printable(f"a{char}b")
    assert UNSAFE.search(shown) is None and len(shown.splitlines()) == 1
    assert shown.startswith("a\\") and shown.endswith("b")


def test_printable_is_idempotent_and_leaves_ordinary_text_alone() -> None:
    once = printable(FORGED)
    assert printable(once) == once
    plain = "Größe ½ — ok\\n 😀 漢字 \u00a0: \t?"
    assert printable(plain) == plain.replace("\t", "\\t")
    assert printable("C:\\new\\temp") == "C:\\new\\temp"  # a backslash is never doubled


@pytest.mark.parametrize("char", list(LEFT_OUT))
def test_printable_escapes_the_other_line_and_bidi_controls(char: str) -> None:
    shown = printable(f"a{char}b")
    assert char not in shown and len(shown.splitlines()) == 1


def test_a_finding_prints_on_one_line() -> None:
    finding = Finding(code="x", msgid="{v}", params={"v": FORGED}, source="f.ui", line=3)
    text = str(finding)
    assert UNSAFE.search(text) is None and len(text.splitlines()) == 1
    assert text.startswith("f.ui:3")


def test_a_ui_error_prints_one_line_per_finding() -> None:
    from pyguibud_runtime import UiError

    findings = [Finding(code="x", msgid="{v}", params={"v": FORGED}, source="f.ui")] * 2
    error = UiError("runtime.build_failed", "{path}: {reason}", path=FORGED, reason=FORGED)
    error.findings = tuple(findings)
    lines = str(error).splitlines()
    assert len(lines) == 3 and all(UNSAFE.search(line) is None for line in lines)


def test_uic_never_prints_a_forged_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    style = "x&#10;y.ui:1: error: z&#x202E;&#x85;&#x2066;[31m"  # XML forbids a raw ESC
    path = _write(
        tmp_path / "forged.ui",
        f'<window id="main" kind="main"><layout type="grid"/><widget class="Button" id="b" '
        f'tb:bootstyle="{style}"><cell row="0" column="0"/></widget></window>',
    )
    assert uic.main(["--check", str(path)]) == 1
    err = capsys.readouterr().err
    lines = err.splitlines()
    assert lines and all(line.startswith(str(path)) for line in lines), err
    assert UNSAFE.search(err.replace("\n", "")) is None
    assert "\\\\" not in err  # escaped once, never twice (Finding.__str__ is not reused)
    assert "\\n" in err and "\\u202e" in err and "\\x85" in err and "\\u2066" in err


def test_every_uic_stderr_line_names_its_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "dates.ui",
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="tb:DateEntry" id="bad" fallback="Entry">'
        '<prop name="value">2023-02-30</prop><cell row="0" column="0"/></widget></window>',
    )
    done = subprocess.run(
        [sys.executable, "-m", "pyguibud.uic", "-o", str(tmp_path / "x_ui.py"), str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYGUIBUD_LANG": "en_GB"},
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    lines = done.stderr.splitlines()
    assert any("2023-02-30" in line for line in lines)
    assert all(line.startswith(f"{path}:") for line in lines), lines


def test_runtime_check_lang_is_translated_and_escaped() -> None:
    from pyguibud_runtime._texts import check_lang

    i18n.set_language("de_DE")
    with pytest.raises(ValueError) as info:
        check_lang("de\n\u202eDE")
    text = str(info.value)
    assert "lang must be" not in text and "de_DE" in text
    assert UNSAFE.search(text) is None and "\\n" in text


def test_export_refusals_and_outcomes_are_escaped() -> None:
    from pyguibud.codegen._errors import M_WRITE_FAILED
    from pyguibud.designer import export

    refusal = export.Refusal(M_WRITE_FAILED, {"output": FORGED, "reason": FORGED})
    for sep in ("\n", " "):
        text = refusal.text(sep)
        assert UNSAFE.search(text.replace(sep, "") if sep == "\n" else text) is None
    plan = export.ExportPlan(FORGED, "", FORGED, "", False, (refusal,))
    for written in ((FORGED,), (FORGED, FORGED)):
        text = export.ExportOutcome(plan, written, refusal).text()
        assert UNSAFE.search(text) is None and len(text.splitlines()) == 1


def test_a_pasted_clip_with_a_forged_value_is_refused_on_one_line() -> None:
    from pyguibud.core import default_registry, read_ui_string
    from pyguibud.designer.clipboard import CLIP_NS, paste_command

    doc = read_ui_string(
        f'{HEAD}<window id="main" kind="main"><layout type="grid"/></window></pyguibud-ui>'
    ).document
    clip = (
        f'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" '
        f'xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1" xmlns:clip="{CLIP_NS}" '
        f'clip:mode="widgets"><window id="w" kind="main"><layout type="grid"/>'
        f'<widget class="Button" id="b" tb:bootstyle="x&#10;y&#x202E;"><cell row="0" '
        f'column="0"/></widget></window></pyguibud-ui>'
    )
    result = paste_command(doc, doc.children[0], clip, default_registry(), None)
    assert isinstance(result, str), result
    assert UNSAFE.search(result) is None and "\\n" in result, result


# ================================================================ D. designer
@pytest.fixture
def app(tk_root: Any) -> Iterator[Any]:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.recovery import RecoverySession
    from pyguibud.designer.settings import Settings
    from tests.conftest import reset_root

    reset_root(tk_root)
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(tk_root, settings=Settings(), recovery=recovery)
    yield designer
    tk_root.protocol("WM_DELETE_WINDOW", tk_root.destroy)
    for dialog in designer._live_dialogs():
        with contextlib.suppress(Exception):
            dialog.close()
    designer.set_language("en_GB")
    designer.dispose()
    recovery.close()
    reset_root(tk_root)


def _settle(root: Any, rounds: int = 3) -> None:
    for _ in range(rounds):
        root.update()


def _status(app: Any) -> str:
    return str(app.shell._status.cget("text"))


@pytest.mark.gui
def test_the_status_bar_never_shows_a_raw_control(app: Any) -> None:
    app.shell.show_message(FORGED)
    _settle(app.root)
    assert UNSAFE.search(_status(app)) is None
    assert UNSAFE.search(str(app.shell._status_tip.cget("text") or "")) is None


@pytest.mark.gui
@pytest.mark.parametrize("code", LOCALES)
def test_opening_the_bidi_fixture_says_errors_then_shows_the_id_escaped(
    app: Any, code: str
) -> None:
    """UAT 3/4: "Opened with 1 error." first; the id is shown escaped once it is selected."""
    app.set_language(code)
    assert app.open_path(BIDI)
    _settle(app.root)
    expected = i18n.ngettext("Opened with {count} error.", "Opened with {count} errors.", 1)
    assert app.shell._message == expected.format(count=1)
    app.shell.clear_message()
    button = next(n for n in app.session.document.walk() if getattr(n, "id", "").startswith("btn_"))
    app.session.select(button, origin="tree")
    _settle(app.root)
    shown = _status(app) + str(app.shell._status_tip.cget("text") or "")
    assert "\u202e" not in shown and "\\u202e" in shown, shown


def _open(app: Any, tmp_path: Path, name: str, body: str) -> str:
    path = _write(tmp_path / name, body)
    assert app.open_path(path)
    _settle(app.root)
    return str(app.shell._message)


_EMPTY = '<window id="main" kind="main"><layout type="grid"/></window>'
_WARN = (  # a Text ignores a bootstyle: a validator warning
    '<window id="main" kind="main"><layout type="grid"/><widget class="Text" id="t" '
    'tb:bootstyle="info"><cell row="0" column="0"/></widget></window>'
)
_ERR = (
    '<window id="main" kind="main"><layout type="grid"/><widget class="Button" id="1a">'
    '<cell row="0" column="0"/></widget><widget class="Button" id="2b">'
    '<cell row="1" column="0"/></widget></window>'
)
_BOTH = (
    '<window id="main" kind="main"><layout type="grid"/><widget class="Text" id="t" '
    'tb:bootstyle="info"><cell row="0" column="0"/></widget><widget class="Button" id="1a">'
    '<cell row="1" column="0"/></widget></window>'
)


@pytest.mark.gui
def test_opened_with_counts(app: Any, tmp_path: Path) -> None:
    """H82: errors only / warnings only / both (errors win) / none."""
    assert not _open(app, tmp_path, "empty.ui", _EMPTY).startswith("Opened with")
    assert _open(app, tmp_path, "warn.ui", _WARN) == "Opened with 1 warning."
    assert _open(app, tmp_path, "err.ui", _ERR) == "Opened with 2 errors."
    assert _open(app, tmp_path, "both.ui", _BOTH) == "Opened with 1 error."


@pytest.mark.gui
def test_the_about_dialog(app: Any) -> None:
    from pyguibud.designer.dialogs.about import AboutDialog

    app.open_about()
    app.open_about()  # a second request raises the first one
    _settle(app.root)
    live = app._live_dialogs()
    assert len(live) == 1 and isinstance(live[0], AboutDialog)
    about = live[0]
    assert about.credit.cget("text") == credit() and "MIT" in about.details.cget("text")
    app.set_language("de_DE")  # a language switch while it is open
    _settle(app.root)
    assert about.window.title() == i18n._("About PyGUIbud") != "About PyGUIbud"
    assert about.credit.cget("text") == credit() and "Erstellt" in credit()
    text, underline = split_mnemonic(i18n._("_Close"))
    assert about.close_button.cget("text") == text and underline >= 0
    # Alt + the German access key closes it
    about._on_alt(types.SimpleNamespace(char=text[underline].lower()))
    _settle(app.root)
    assert about.closed
    for key in ("<Escape>", "<Return>"):
        app.open_about()
        _settle(app.root)
        (again,) = app._live_dialogs()
        again.window.focus_force()
        _settle(app.root)
        again.window.event_generate(key)
        _settle(app.root)
        assert again.closed, key


def _entries(menu: Any) -> list[tuple[str, int]]:
    rows = []
    end = menu.index("end")
    for index in range(0 if end is None else int(end) + 1):
        if menu.type(index) in ("command", "cascade", "radiobutton", "checkbutton"):
            rows.append(
                (str(menu.entrycget(index, "label")), int(menu.entrycget(index, "underline")))
            )
    return rows


@pytest.mark.gui
@pytest.mark.parametrize("code", LOCALES)
def test_every_menu_has_unique_access_keys_and_clean_labels(app: Any, code: str) -> None:
    app.set_language(code)
    _settle(app.root)
    problems = []
    for menu in app.shell._menus:
        keys: dict[str, str] = {}
        for label, underline in _entries(menu):
            assert "\x04" not in label and "{" not in label, label
            if underline < 0:
                continue
            key = label[underline].lower()
            if key in keys:
                problems.append((keys[key], label))
            keys[key] = label
    assert problems == []
    i18n.set_language(code)
    menu_label = split_mnemonic(i18n._(i18n.NC_("menu", "_Preview")))[0]
    labels = [label for label, _u in _entries(app.shell.menubar)]
    assert menu_label in labels
    preview = [label for label, _u in _entries(app.shell.submenus["preview"])]
    assert split_mnemonic(i18n._(i18n.NC_("action", "_Preview")))[0] in preview
    if code != "en_GB":
        assert "Preview" not in labels or code == "en_XA"


@pytest.mark.gui
@pytest.mark.parametrize("code", LOCALES)
def test_the_delete_window_hint_cites_the_real_menu(app: Any, code: str) -> None:
    """H77: the hint quotes the Document menu and its Delete window entry as shown."""
    from pyguibud.designer.actions import window_delete_hint

    app.set_language(code)
    _settle(app.root)
    labels = dict(_entries(app.shell.menubar))
    document = next(name for name in labels if name == split_mnemonic(i18n._("_Document"))[0])
    items = [label for label, _u in _entries(app.shell.submenus["document"])]
    item = split_mnemonic(i18n._("_Delete window"))[0]
    assert item in items
    assert f"{document} ▸ {item}" in window_delete_hint()
    assert ">" not in window_delete_hint()


@pytest.mark.gui
def test_the_object_tree_does_not_reorder_a_bidi_id(app: Any) -> None:
    assert app.open_path(BIDI)
    _settle(app.root)
    tree = app.shell.tree.tree

    def walk(item: str = "") -> Iterator[str]:
        for child in tree.get_children(item):
            yield str(tree.item(child, "text"))
            yield from walk(child)

    texts = list(walk())
    assert any("btn_" in t for t in texts), texts
    assert all(UNSAFE.search(t) is None for t in texts), texts
