"""PyGUIbud command-line interface."""

from __future__ import annotations

import argparse
import contextlib
import sys
from collections.abc import Callable
from typing import NoReturn

from .__about__ import __version__
from .i18n import (
    LANGUAGE_CODE_RE,
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
    set_language(_requested_language(requested) or detect_language())


def _requested_language(value: str | None) -> str | None:
    """The supported code of a ``--lang`` value, or None.

    Unlike an environment variable (``de_DE.UTF-8``), the option must be a plain language code,
    so ``de_DE/../x`` or ``en_XA;rm`` is refused instead of being cut down to a language (QA-11-12).
    """
    if value is None or LANGUAGE_CODE_RE.fullmatch(value) is None:
        return None
    return normalise_language(value)


def _language_arg(value: str) -> str:
    code = _requested_language(value)
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


#: The ``--theme`` choices are fixed tokens (never translated), like option names.
THEME_CHOICES = ("light", "dark", "high-contrast")


def _default_launch(lang: str, theme: str) -> int:
    """Open the designer; Tk is imported only here, so --version and --help never load it."""
    from pyguibud.designer import launch

    return launch(lang, theme)


def main(argv: list[str] | None = None, *, launch: Callable[[str, str], int] | None = None) -> int:
    """Entry point for the PyGUIbud CLI.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:].
        launch: Opens the designer as ``launch(language, theme)`` and returns the exit code;
            tests inject a fake. Defaults to :func:`pyguibud.designer.launch`.

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

    parser.add_argument(
        "--theme",
        choices=THEME_CHOICES,
        default="light",
        help=_("designer colour theme (default: %(default)s)"),
    )

    args = parser.parse_args(argv)

    if args.lang is not None and args.lang != get_language():
        set_language(args.lang)

    if args.list_languages:
        _print_languages()
        return 0

    return (launch or _default_launch)(get_language(), args.theme)
