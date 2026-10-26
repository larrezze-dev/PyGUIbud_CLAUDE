"""Step 19e: argparse's own messages are translated; credit in --help/--version."""

from __future__ import annotations

import argparse
import ast
import gettext
from pathlib import Path

import pytest

from pyguibud import _argparse, cli, i18n, uic
from pyguibud.credits import credit
from pyguibud.preview import _parser as preview_parser
from tests._paths import DESIGNER_SRC

NBSP = chr(0xA0)

# Texts of argparse that pyguibud's parsers cannot emit (sub-commands, FileType, programmer
# errors raised while building a parser, abstract methods).
_UNREACHABLE = {
    ".__call__() not defined",
    "conflicting subparser: %s",
    "conflicting subparser alias: %s",
    "unknown parser %(parser_name)r (choices: %(choices)s)",
    'argument "-" with mode %r',
    "can't open '%(filename)s': %(error)s",
    "cannot merge actions - two groups are named %r",
    "'required' is an invalid argument for positionals",
    "invalid option string %(option)r: must start with a character %(prefix_chars)r",
    "dest= is required for options like %r",
    "invalid conflict_resolution value: %r",
    "conflicting option string: %s",
    "conflicting option strings: %s",
    "mutually exclusive arguments must be optional",
    "cannot have multiple subparser arguments",
    "subcommands",
    "%r is not callable",
}
# Python 3.13 warns only about actions and sub-commands declared with ``deprecated=True``, which
# no pyguibud parser uses (test_no_parser_declares_a_deprecated_action).
_DEPRECATION = {
    "%(prog)s: warning: %(message)s\n",
    "argument '%(argument_name)s' is deprecated",
    "command '%(parser_name)s' is deprecated",
    "option '%(option)s' is deprecated",
}


@pytest.fixture(autouse=True)
def _restore_language() -> object:
    before = i18n.get_language()
    yield
    i18n.set_language(before)


def _argparse_msgids() -> set[str]:
    tree = ast.parse(Path(argparse.__file__).read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"_", "ngettext"}
        ):
            found.update(str(a.value) for a in node.args if isinstance(a, ast.Constant))
    return found


def test_every_reachable_argparse_msgid_is_marked() -> None:
    marked = set(_argparse._ARGPARSE_MSGIDS) | {"expected %s arguments"}
    missing = _argparse_msgids() - marked - _UNREACHABLE - _DEPRECATION
    assert not missing, sorted(missing)


def test_no_parser_declares_a_deprecated_action() -> None:
    """Keeps the deprecation warnings of Python 3.13's argparse unreachable (see _DEPRECATION)."""
    for path in sorted(DESIGNER_SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                assert all(k.arg != "deprecated" for k in node.keywords), (path, node.lineno)


def test_binding_is_restored_after_help_error_and_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = (argparse._, argparse.ngettext)  # type: ignore[attr-defined]
    assert original[0] is gettext.gettext
    parser = uic._build_parser()
    parser.parse_args(["a.ui"])
    for argv in (["--help"], ["--bogus"], ["--version"], []):
        with pytest.raises(SystemExit):
            parser.parse_args(argv)
        assert (argparse._, argparse.ngettext) == original  # type: ignore[attr-defined]
    capsys.readouterr()


@pytest.mark.parametrize("argv", [["--bogus"], ["--theme", "hell"], ["--lang"]])
def test_errors_use_the_interface_language(
    argv: list[str], capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", "en_XA")
    with pytest.raises(SystemExit) as exc:
        cli.main(argv, launch=lambda *_a, **_k: 0)
    err = capsys.readouterr().err
    assert exc.value.code == 2
    for english in ("unrecognized arguments", "invalid choice", "expected one argument", "usage:"):
        assert english not in err, err
    assert "[" in err and "%" not in err


def test_required_argument_error_is_translated(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    portuguese = {"the following arguments are required: %s": "são obrigatórios: %s"}
    monkeypatch.setattr(_argparse, "_", lambda m: portuguese.get(m, m))
    with pytest.raises(SystemExit):
        uic.main([])
    assert "são obrigatórios: FILE" in capsys.readouterr().err


def test_an_untranslated_argument_prefix_is_translated(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before 3.11.9/3.12.3 ``ArgumentError.__str__`` leaves "argument X: " in English."""
    german = {"argument %(argument_name)s: %(message)s": "Argument %(argument_name)s: %(message)s"}
    monkeypatch.setattr(_argparse, "_", lambda m: german.get(m, m))
    parser = _argparse.PyGUIbudParser(prog="p")
    with pytest.raises(SystemExit):
        parser.error("argument --window: expected: one")
    assert capsys.readouterr().err.endswith("p: error: Argument --window: expected: one\n")


def test_section_headings_can_take_a_non_breaking_space(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        _argparse, "_", lambda m: m.replace(":", NBSP + ":") if "heading" in m else m
    )
    with pytest.raises(SystemExit):
        cli.main(["--help"], launch=lambda *_a, **_k: 0)
    out = capsys.readouterr().out
    assert f"options{NBSP}:" in out and f"positional arguments{NBSP}:" in out


@pytest.mark.parametrize("module", [cli.main, uic.main])
def test_help_and_version_carry_the_credit(
    module: object, capsys: pytest.CaptureFixture[str]
) -> None:
    for flag in ("--help", "--version"):
        with pytest.raises(SystemExit) as exc:
            module(["--lang", "en_GB", flag])  # type: ignore[operator]
        assert exc.value.code == 0
        assert credit() in capsys.readouterr().out.replace("\n", " ").replace("  ", " ")


def test_uic_codegen_warnings_name_the_file(capsys: pytest.CaptureFixture[str]) -> None:
    from pyguibud.core.diagnostics import Finding

    finding = Finding(code="x.y", msgid="text", params={}, source="", path="window/button")
    uic._report(finding, "a.ui")
    assert capsys.readouterr().err.startswith("a.ui: warning: window/button: ")


def test_preview_parser_is_translated() -> None:
    assert isinstance(preview_parser(), _argparse.PyGUIbudParser)
