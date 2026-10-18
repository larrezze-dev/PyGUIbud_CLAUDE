"""Translated argparse plumbing shared by ``pyguibud``, ``pyguibud-uic`` and the preview child.

It lives outside :mod:`pyguibud.cli` because the preview child must not import the CLI
(ADR-007/013 import boundary); like the CLI it loads no GUI toolkit.
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import re
import sys
import threading
from collections.abc import Callable
from typing import Any, NoReturn, TypeVar, cast

from .credits import credit
from .i18n import (
    LANGUAGE_CODE_RE,
    N_,
    NP_,
    _,
    detect_language,
    ngettext,
    normalise_language,
    set_language,
)

_F = TypeVar("_F", bound=Callable[..., Any])


class _PreParseError(Exception):
    """Raised by the pre-parser instead of exiting; the real parser reports the problem."""


class _QuietParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _PreParseError(message)


# Every message of argparse that this parser can emit, marked so that ``pybabel extract`` keeps
# it in the catalogue (argparse's own catalogue has no pyguibud language). The set is the union of
# Python 3.10 to 3.13; unreachable texts (sub-commands, FileType, programmer errors) are left out.
# Translators: these are the texts of Python's argparse module. Keep every placeholder (%s,
# %(prog)s, %(value)r, ...) and the final newline of the "error" line exactly as in the source.
_ARGPARSE_MSGIDS = (
    N_("%(heading)s:"),
    N_("%(prog)s: error: %(message)s\n"),
    N_(" (default: %(default)s)"),
    N_("ambiguous option: %(option)s could match %(matches)s"),
    N_("argument %(argument_name)s: %(message)s"),
    N_("expected at least one argument"),
    N_("expected at most one argument"),
    N_("expected one argument"),
    NP_("expected %s argument", "expected %s arguments"),
    N_("ignored explicit argument %r"),
    N_("invalid %(type)s value: %(value)r"),
    N_("invalid choice: %(value)r (choose from %(choices)s)"),
    N_("not allowed with argument %s"),
    N_("one of the arguments %s is required"),
    N_("optional arguments"),  # Python 3.10 and older
    N_("options"),
    N_("positional arguments"),
    N_("show program's version number and exit"),
    N_("show this help message and exit"),
    N_("the following arguments are required: %s"),
    N_("unexpected option string: %s"),
    N_("unrecognized arguments: %s"),
    N_("usage: "),
)


class _Swap:
    """argparse's ``_``/``ngettext`` while any wrapped call runs, in any thread (QA-19e-03).

    The first call to enter saves and replaces them and the last to leave restores them, so
    concurrent or nested parses never restore each other's state. The lock guards only the
    swap: holding it during a parse would serialise every parser.
    """

    lock = threading.Lock()
    depth = 0
    saved: tuple[Any, Any] = (None, None)


def _bound(method: _F) -> _F:
    """Run ``method`` with argparse's ``_`` and ``ngettext`` replaced by ours, then restore them."""

    @functools.wraps(method)
    def wrapper(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        with _Swap.lock:
            if _Swap.depth == 0:
                _Swap.saved = argparse._, argparse.ngettext  # type: ignore[attr-defined]
                argparse._, argparse.ngettext = _, ngettext  # type: ignore[attr-defined]
            _Swap.depth += 1
        try:
            return method(*args, **kwargs)
        finally:
            with _Swap.lock:
                _Swap.depth -= 1
                if _Swap.depth == 0:
                    argparse._, argparse.ngettext = _Swap.saved  # type: ignore[attr-defined]

    return cast(_F, wrapper)


class _Formatter(argparse.HelpFormatter):
    """Help formatter that keeps line breaks in texts and translates hard-coded colons."""

    class _Section(argparse.HelpFormatter._Section):
        """A help section whose heading colon is translated (``%(heading)s:``; French puts a space).

        argparse translates it itself only from 3.11.9 and 3.12.3 (not 3.12.0), so an untranslated
        heading line is replaced: a feature test, not a version test (QA-19e-02). Where argparse
        translated the heading, the untranslated line is absent.
        """

        def format_help(self) -> str:
            text = super().format_help()
            if self.heading is None or self.heading is argparse.SUPPRESS:
                return text
            indent = " " * self.formatter._current_indent  # as argparse indented the heading
            plain = f"\n{indent}{self.heading}:\n"
            if not text.startswith(plain):
                return text
            heading = _("%(heading)s:") % {"heading": self.heading}
            return f"\n{indent}{heading}\n{text[len(plain) :]}"

    def _fill_text(self, text: str, width: int, indent: str) -> str:
        # The credit is never wrapped (--help, --version): a break could split "Claude Code".
        keep, fill = credit(), super()._fill_text
        lines = text.split("\n")
        return "\n".join(
            indent + line if line == keep else fill(line, width, indent) for line in lines
        )


_PLAIN_ARGUMENT = re.compile(r"argument (?P<argument_name>.+?): (?P<message>.*)", re.DOTALL)


class PyGUIbudParser(argparse.ArgumentParser):
    """An argument parser whose own texts (usage, titles, -h, errors) are translated.

    argparse translates them with its private catalogue, which has no pyguibud languages, so
    its ``_`` is bound to ours while this parser works. Build it only after the language is
    chosen (``_select_initial_language``).
    """

    @_bound
    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401 - argparse's own
        kwargs.setdefault("formatter_class", _Formatter)
        kwargs["add_help"] = False
        super().__init__(*args, **kwargs)
        self.add_argument("-h", "--help", action="help", help=_("show this help message and exit"))

    parse_known_args = _bound(argparse.ArgumentParser.parse_known_args)
    parse_args = _bound(argparse.ArgumentParser.parse_args)
    format_help = _bound(argparse.ArgumentParser.format_help)
    format_usage = _bound(argparse.ArgumentParser.format_usage)

    @_bound
    def error(self, message: str) -> NoReturn:
        # Before 3.11.9/3.12.3 ArgumentError.__str__ does not translate its prefix: a feature
        # test, as for the heading colon (a translated prefix never matches the English one).
        plain = _PLAIN_ARGUMENT.fullmatch(message)
        if plain is not None:
            message = _("argument %(argument_name)s: %(message)s") % plain.groupdict()
        argparse.ArgumentParser.error(self, message)


def _make_stdout_safe() -> None:
    """Never crash on characters the console encoding cannot represent."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")


def _select_initial_language(argv: list[str] | None, option: str = "--lang") -> None:
    """Set the language before the real parser is built so --help and errors are translated.

    ``option`` names the interface-language option (the preview child's is ``--ui-lang``).
    """
    pre = _QuietParser(add_help=False, allow_abbrev=False)
    pre.add_argument(option, dest="lang", default=None)
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
