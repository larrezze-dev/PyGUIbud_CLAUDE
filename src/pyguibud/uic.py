"""``pyguibud-uic``: check ``.ui`` files, their includes and image files (code generation later).

Diagnostics go to stderr in GCC style, ``path:line:column: error: message``; the ``error`` and
``warning`` tokens stay in English so that editors and CI can parse them, while the messages
are translated.
"""

from __future__ import annotations

import argparse
import glob
import os
import sys

from .__about__ import __version__
from .cli import _language_arg, _make_stdout_safe, _select_initial_language
from .core.diagnostics import Finding
from .core.errors import XmlIoError
from .core.files import DiskFiles
from .core.registry import default_registry
from .core.validate import validate_read
from .core.xml_io import read_ui
from .i18n import _, get_language, set_language

_GLOB_CHARS = frozenset("*?[")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyguibud-uic",
        description=_("Check PyGUIbud .ui files."),
        epilog=_(
            "The check loads the installed widget plugins (entry point pyguibud.widgets), which "
            "runs their code; only check files with plugins you trust."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--lang",
        metavar="CODE",
        type=_language_arg,
        default=None,
        help=_("interface language code, for example de_DE or en_XA"),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=_("read and validate each file and report errors and warnings"),
    )
    parser.add_argument("files", metavar="FILE", nargs="+", help=_(".ui file to process"))
    return parser


def _expand(argument: str) -> list[str]:
    """Expand a glob pattern ourselves: PowerShell passes patterns through unexpanded."""
    if not os.path.exists(argument) and _GLOB_CHARS.intersection(argument):
        return sorted(glob.glob(argument))
    return [argument]


def _report(finding: Finding) -> None:
    """Print one finding in GCC style; the severity token stays in English."""
    if finding.line is None and finding.path:
        where = f"{finding.source}: {finding.severity}: {finding.path}"
    else:
        where = f"{finding.location}: {finding.severity}"
    print(f"{where}: {finding.message}", file=sys.stderr)


def _check(path: str) -> bool:
    """Check one file; return True if it was read and has no validator error."""
    try:
        result = read_ui(path)
    except XmlIoError as exc:
        print(f"{exc.location}: error: {exc.message}", file=sys.stderr)
        return False
    for warning in result.warnings:
        _report(warning)
    # The file rules (includes, image files) need the disk; the designer's guards skip them.
    report = validate_read(result, default_registry(), files=DiskFiles(path, result))
    for finding in report.findings:
        _report(finding)
    if not report.ok:
        return False
    # Translators: {path} is a file name as typed by the user.
    print(_("{path}: no errors found").format(path=path))
    return True


def main(argv: list[str] | None = None) -> int:
    """Entry point of ``pyguibud-uic``.

    Returns:
        0 if every file was read and has no error (warnings are fine), 1 if any file failed to
        read or has a validator error, 2 for a usage error.
    """
    _make_stdout_safe()
    _select_initial_language(argv)
    args = _build_parser().parse_args(argv)
    if args.lang is not None and args.lang != get_language():
        set_language(args.lang)

    if not args.check:
        print(
            _(
                "Generating Python code from .ui files arrives in a later development step; "
                "use --check to verify files."
            ),
            file=sys.stderr,
        )
        return 2

    ok = True
    for argument in args.files:
        paths = _expand(argument)
        if not paths:
            print(f"{argument}: error: " + _("no file matches this pattern"), file=sys.stderr)
            ok = False
            continue
        for path in paths:
            ok = _check(path) and ok
    return 0 if ok else 1
