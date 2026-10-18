"""PyGUIbud command-line interface."""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .__about__ import __version__
from ._argparse import (
    PyGUIbudParser,
    _make_stdout_safe,
    _requested_language,
    _select_initial_language,
)
from .credits import credit
from .i18n import (
    LANGUAGES,
    PSEUDO_LANGUAGE,
    _,
    get_language,
    set_language,
)


def version_text() -> str:
    """The ``--version`` text: program, version and the author credit (``%`` escaped)."""
    return "%(prog)s " + f"{__version__}\n{credit()}".replace("%", "%%")


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


def _default_launch(lang: str | None, theme: str | None, **keywords: Any) -> int:  # noqa: ANN401
    """Open the designer; Tk is imported only here, so --version and --help never load it."""
    from pyguibud.designer import launch

    return launch(lang, theme, **keywords)


def main(argv: list[str] | None = None, *, launch: Callable[..., int] | None = None) -> int:
    """Entry point for the PyGUIbud CLI.

    Args:
        argv: Command-line arguments; defaults to sys.argv[1:].
        launch: Opens the designer as ``launch(language, theme)`` (plus ``path=`` when a FILE
            is given) and returns the exit code; ``language`` and ``theme`` are None when not
            given, so the designer's settings decide; ``no_plugins=True`` only with
            ``--no-plugins``. Tests inject a fake. Defaults to
            :func:`pyguibud.designer.launch`.

    Returns:
        Exit code (0 on success).
    """
    _make_stdout_safe()
    _select_initial_language(argv)

    parser = PyGUIbudParser(
        prog="pyguibud",
        description=_("PyGUIbud: drag-and-drop GUI builder for Python."),
        epilog=credit(),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=version_text(),
        help=_("show the version number and exit"),
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
        default=None,
        # Translators: {default} is the --theme value used by default (light), inserted as it
        # is: the option accepts only the untranslated names shown in its list of choices.
        help=_("designer colour theme (default: the last one used, else {default})").format(
            default=THEME_CHOICES[0]
        ),
    )
    parser.add_argument(
        "--no-plugins",
        action="store_true",
        # Translators: the safe-mode option; plugins are widget packages installed separately.
        help=_("start without loading any plugin (safe mode)"),
    )
    parser.add_argument(
        "file",
        nargs="?",
        metavar="FILE",
        default=None,
        help=_("a .ui file to open"),
    )

    args = parser.parse_args(argv)

    if args.lang is not None and args.lang != get_language():
        set_language(args.lang)

    if args.list_languages:
        _print_languages()
        return 0

    keywords: dict[str, Any] = {"no_plugins": True} if args.no_plugins else {}
    if args.file is not None:
        from .core.files import is_network_or_device_path

        # Never touch a network path, not even to test that it exists (R82).
        if is_network_or_device_path(args.file):
            parser.error(_("Network and device paths cannot be opened."))
        if not os.path.exists(args.file):
            # Translators: {path} is the file named on the command line.
            parser.error(_("The file '{path}' does not exist.").format(path=args.file))
        keywords["path"] = Path(os.path.abspath(args.file))
    return (launch or _default_launch)(args.lang, args.theme, **keywords)
