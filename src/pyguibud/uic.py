"""``pyguibud-uic``: check ``.ui`` files, generate Python code from them, extract their texts.

Diagnostics go to stderr in GCC style, ``path:line:column: error: message``; the ``error`` and
``warning`` tokens stay in English so that editors and CI can parse them, while the messages
are translated. The generated module never depends on the CLI language (spec ``codegen.md`` 2).
"""

from __future__ import annotations

import argparse
import dataclasses
import glob
import os
import sys

from ._argparse import PyGUIbudParser, _make_stdout_safe, _select_initial_language
from .cli import _language_arg, version_text
from .codegen import (
    CodegenError,
    default_output,
    extract_pot,
    generate_python,
)
from .codegen._errors import M_NOT_GENERATED, M_SAME_FILE, M_TRANSLATIONS, M_WRITE_FAILED
from .codegen.output import _has_translations as _has_translations
from .codegen.output import (
    check_output,
    holds_translations,
    protected_ui_files,
    replaceable,
    same_file,
    write_atomic,
)
from .core.diagnostics import Finding
from .core.errors import XmlIoError, format_message
from .core.files import DiskFiles, is_network_or_device_path
from .core.registry import WIDGETS_GROUP, default_registry
from .core.text import printable
from .core.validate import validate_read
from .core.xml_io import ReadResult, read_ui
from .credits import credit
from .i18n import N_, _, get_language, set_language

_GLOB_CHARS = frozenset("*?[")
# Usage errors go through argparse, so the msgids are marked here and translated when used.
# Translators: {option} and {other} are command-line options such as "-o" and "--check"; they
# are never translated.
_M_EXCLUSIVE = N_("{option} cannot be used with {other}")
# Translators: {option} is a command-line option ("-o"); it is never translated.
_M_ONE_INPUT = N_("{option} can be used with one input file only")
_M_NETWORK = N_("Network and device paths cannot be opened.")  # the designer's wording


def _build_parser() -> argparse.ArgumentParser:
    parser = PyGUIbudParser(
        prog="pyguibud-uic",
        description=_(
            "Check PyGUIbud .ui files, generate Python code from them and extract their texts "
            "for translation."
        ),
        # Translators: {group} is the name of a Python entry-point group; it is never translated.
        epilog=_(
            "The check loads the installed widget plugins (entry point {group}), which "
            "runs their code; only check files with plugins you trust."
        ).format(group=WIDGETS_GROUP)
        + "\n\n"
        + credit(),
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help=_("read and validate each file and report errors and warnings"),
    )
    mode.add_argument(
        "--extract",
        action="store_true",
        help=_("write a translation template (.pot) with the translatable texts of the files"),
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="OUT",
        default=None,
        # Translators: {pattern} is a file name pattern and {extract} a command-line option; both
        # are never translated.
        help=_(
            "output file (generate: default {pattern} next to the .ui file; {extract}: "
            "default standard output)"
        ).format(pattern="<name>_ui.py", extract="--extract"),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        # Translators: {program} is the name of this command; it is never translated.
        help=_(
            "replace an output file even if {program} did not generate it, and generate code "
            "from images and includes outside the folder of the .ui file"
        ).format(program="pyguibud-uic"),
    )
    parser.add_argument("files", metavar="FILE", nargs="+", help=_(".ui file to process"))
    return parser


def _expand(argument: str) -> list[str]:
    """Expand a glob pattern ourselves: PowerShell passes patterns through unexpanded."""
    if not os.path.exists(argument) and _GLOB_CHARS.intersection(argument):
        return sorted(glob.glob(argument))
    return [argument]


def _report(finding: Finding, source: str = "") -> None:
    """Print one finding in GCC style; the severity token stays in English.

    ``source`` names the file for findings that carry none (the code generator's warnings).
    """
    if source and not finding.source:
        finding = dataclasses.replace(finding, source=source)
    if finding.line is None and finding.path:
        where = f"{finding.source}: {finding.severity}: {finding.path}"
    else:
        where = f"{finding.location}: {finding.severity}"
    print(printable(f"{where}: {finding.message}"), file=sys.stderr)


def _read(path: str) -> ReadResult | None:
    """Read one file and print the reader's warnings; None (after a message) if it failed."""
    try:
        result = read_ui(path)
    except XmlIoError as exc:
        print(printable(f"{exc.location}: error: {exc.message}"), file=sys.stderr)
        return None
    for warning in result.warnings:
        _report(warning)
    return result


def _check(path: str) -> bool:
    """Check one file; return True if it was read and has no validator error."""
    result = _read(path)
    if result is None:
        return False
    # The file rules (includes, image files) need the disk; the designer's guards skip them.
    report = validate_read(result, default_registry(), files=DiskFiles(path, result))
    for finding in report.findings:
        _report(finding)
    if not report.ok:
        return False
    # Translators: {path} is a file name as typed by the user.
    print(_("{path}: no errors found").format(path=path))
    return True


def _refuse(output: str, msgid: str, **params: object) -> bool:
    """Print ``OUT: error: message`` for a refused or failed output; always False."""
    # The option and program names are literals, kept out of the translatable text.
    fixed = {"force": "--force", "option": "-o", "program": "pyguibud-uic"}
    message = format_message(msgid, {"output": output, **fixed, **params})
    print(f"{output}: error: {message}", file=sys.stderr)
    return False


def _generate(
    path: str, output_arg: str | None, force: bool, inputs: list[str], written: list[str]
) -> bool:
    """Generate the module of one file; True if it was written (it then joins ``written``).

    ``inputs`` are all the ``.ui`` files of this run: none of them is ever an output.
    """
    output = output_arg or default_output(path)
    result = _read(path)
    if result is None:
        return False
    refusal = check_output(output, inputs, written)
    if refusal is not None:
        return _refuse(output, refusal)
    try:
        module = generate_python(result, path, output=output, allow_outside=force)
    except CodegenError as exc:
        for finding in exc.findings:
            _report(finding)
        print(printable(f"{path}: error: {exc.message}"), file=sys.stderr)
        return False
    if any(same_file(output, source) for source in module.sources):
        return _refuse(output, M_SAME_FILE)
    if not force and not replaceable(output, extracting=False):
        return _refuse(output, M_NOT_GENERATED)
    try:
        write_atomic(output, module.text)
    except OSError as exc:
        return _refuse(output, M_WRITE_FAILED, reason=exc.strerror or str(exc))
    written.append(output)
    for finding in module.warnings:
        _report(finding, path)
    # Translators: {path} is the .ui file, {output} the Python file written from it.
    print(_("{path}: wrote {output}").format(path=path, output=output))
    return True


def _extract(paths: list[str], output: str | None, force: bool) -> bool:
    """Write one ``.pot`` for all ``paths``; nothing is written if any file fails."""
    results: list[tuple[ReadResult, str]] = []
    ok = True
    for path in paths:
        result = _read(path)
        if result is None:
            ok = False
            continue
        # No include or image I/O is needed to find the texts.
        report = validate_read(result, default_registry(), files=None)
        for finding in report.findings:
            _report(finding)
        if report.ok:
            results.append((result, path))
        else:
            ok = False
    if not ok:
        return False
    if output is not None:
        # The same protection as generation (QA-11-01): never a .ui file of the run, never a
        # folder or device, and only a template pyguibud-uic wrote unless --force is given.
        protected = [p for result, path in results for p in protected_ui_files(path, result)]
        refusal = check_output(output, protected, [])
        if refusal is not None:
            return _refuse(output, refusal)
        if not force and not replaceable(output, extracting=True):
            return _refuse(output, M_NOT_GENERATED)
        if not force and holds_translations(output):
            return _refuse(output, M_TRANSLATIONS)
    base_dir = os.path.dirname(os.path.abspath(output)) if output else os.getcwd()
    text = extract_pot(results, base_dir=base_dir)
    if output is not None:
        try:
            write_atomic(output, text)
        except OSError as exc:
            return _refuse(output, M_WRITE_FAILED, reason=exc.strerror or str(exc))
        # Translators: {output} is the translation template (.pot) that was written.
        print(_("wrote {output}").format(output=output))
        return True
    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        sys.stdout.write(text)
    else:  # bytes, so that a legacy console code page cannot change the file
        sys.stdout.flush()
        buffer.write(text.encode("utf-8"))
        buffer.flush()
    return True


def main(argv: list[str] | None = None) -> int:
    """Entry point of ``pyguibud-uic``.

    Returns:
        0 if every file was processed (warnings are fine), 1 if any file failed to read, failed
        validation, was refused or could not be written, 2 for a usage error.
    """
    _make_stdout_safe()
    _select_initial_language(argv)
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.lang is not None and args.lang != get_language():
        set_language(args.lang)
    if args.check and args.output is not None:
        parser.error(_(_M_EXCLUSIVE).format(option="-o", other="--check"))
    if args.force and args.check:
        parser.error(_(_M_EXCLUSIVE).format(option="--force", other="--check"))

    ok = True
    paths: list[str] = []
    for argument in args.files:
        if is_network_or_device_path(argument):  # never contacted, not even to test it (R82)
            print(printable(f"{argument}: error: ") + _(_M_NETWORK), file=sys.stderr)
            ok = False
            continue
        found = _expand(argument)
        if not found:
            print(f"{argument}: error: " + _("no file matches this pattern"), file=sys.stderr)
            ok = False
        paths += found
    generating = not (args.check or args.extract)
    if generating and args.output is not None and (len(args.files) > 1 or len(paths) > 1):
        parser.error(_(_M_ONE_INPUT).format(option="-o"))
    if args.check:
        for path in paths:
            ok = _check(path) and ok
    elif args.extract:
        ok = bool(paths) and _extract(paths, args.output, args.force) and ok
    else:
        written: list[str] = []
        for path in paths:
            ok = _generate(path, args.output, args.force, paths, written) and ok
    return 0 if ok else 1


if __name__ == "__main__":  # python -m pyguibud.uic (QA-11-16)
    raise SystemExit(main())
