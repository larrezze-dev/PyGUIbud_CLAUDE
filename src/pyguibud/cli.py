"""PyGUIbud command-line interface."""

from __future__ import annotations

import argparse
import contextlib
import sys
from typing import NoReturn

from .__about__ import __version__
from .i18n import (
    LANGUAGES,
    PSEUDO_LANGUAGE,
    _,
    detect_language,
    get_language,
    normalise_language,
    set_language,
)


class _PreParseError(Exception):
    """Raised by the pre-parser instead of exiting; the real parser reports the problem."""


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _PreParseError(message)


def _make_stdout_safe() -> None:
    """Never crash on characters the console encoding cannot represent."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")


def _select_initial_language(argv: list[str] | None) -> None:
    """Set the language before the real parser is built so --help is translated."""
    pre = _QuietParser(add_help=False, allow_abbrev=False)
    pre.add_argument("--lang", default=None)
    requested: str | None = None
    try:
        known, _rest = pre.parse_known_args(argv)
        requested = known.lang
    except _PreParseError:
        pass
    set_language(normalise_language(requested) or detect_language())


def _language_arg(value: str) -> str:
    code = normalise_language(value)
    if code is None:
        valid = ", ".join((*LANGUAGES, PSEUDO_LANGUAGE))
        raise argparse.ArgumentTypeError(
            # Translators: {code} is what the user typed, {valid} a list of language codes.
            _("unknown language '{code}'; valid codes are: {valid}").format(code=value, valid=valid)
        )
    return code


def _print_languages() -> None:
    active = get_language()
    # Translators: heading above the list of selectable interface languages.
    print(_("Available interface languages (* marks the active one):"))
    for code, autonym in LANGUAGES.items():
        print(f"{'*' if code == active else ' '} {code}  {autonym}")
    print()
    # Translators: {code} is the pseudo-locale code; it is not a real language.
    print(
        _("The pseudo-locale {code} is also accepted; it is meant for testing layouts.").format(
            code=PSEUDO_LANGUAGE
        )
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for the PyGUIbud CLI.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:].

    Returns:
        Exit code (0 on success).
    """
    _make_stdout_safe()
    _select_initial_language(argv)

    parser = argparse.ArgumentParser(
        prog="pyguibud",
        description=_("PyGUIbud: drag-and-drop GUI builder for Python."),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--lang",
        metavar="CODE",
        type=_language_arg,
        default=None,
        help=_("interface language code, for example de_DE or en_XA"),
    )
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help=_("list the available interface languages and exit"),
    )

    # Designer UI launch and other subcommands come in Step 12.
    args = parser.parse_args(argv)

    if args.lang is not None and args.lang != get_language():
        set_language(args.lang)

    if args.list_languages:
        _print_languages()
        return 0

    print(_("The designer window is not available yet; it arrives in a later development step."))
    return 0
