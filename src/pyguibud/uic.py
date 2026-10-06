"""``pyguibud-uic``: check ``.ui`` files, generate Python code from them, extract their texts.

Diagnostics go to stderr in GCC style, ``path:line:column: error: message``; the ``error`` and
``warning`` tokens stay in English so that editors and CI can parse them, while the messages
are translated. The generated module never depends on the CLI language (spec ``codegen.md`` 2).
"""

from __future__ import annotations

import argparse
import contextlib
import glob
import os
import re
import stat
import sys
import tempfile

from .__about__ import __version__
from .cli import _language_arg, _make_stdout_safe, _select_initial_language
from .codegen import (
    GENERATED_MARKER,
    CodegenError,
    default_output,
    extract_pot,
    generate_python,
)
from .codegen._errors import (
    M_ALREADY_WRITTEN,
    M_NOT_GENERATED,
    M_NOT_REGULAR,
    M_SAME_FILE,
    M_TRANSLATIONS,
    M_WRITE_FAILED,
)
from .core.diagnostics import Finding
from .core.errors import XmlIoError, format_message
from .core.files import MAX_INCLUDE_FILES, DiskFiles, is_device_name
from .core.model import Include
from .core.registry import default_registry
from .core.validate import validate_read
from .core.xml_io import ReadResult, read_ui
from .i18n import N_, _, get_language, set_language

_GLOB_CHARS = frozenset("*?[")
_MARKER = GENERATED_MARKER.encode("utf-8")
# The header line every template written by --extract carries (codegen/_pot.py).
_POT_MARKER = b'\n"Generated-By: pyguibud-uic '
_POT_HEAD_BYTES = 4096
_POT_LIMIT = 16 * 1024 * 1024  # a larger existing file is never replaced without --force
_PO_FIELD_RE = re.compile(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[[0-9]+\])?)\s+"(.*)"')
_PO_MORE_RE = re.compile(r'"(.*)"')
# Usage errors go through argparse, so the msgids are marked here and translated when used.
_M_O_CHECK = N_("-o cannot be used with --check")
_M_FORCE_CHECK = N_("--force cannot be used with --check")
_M_ONE_INPUT = N_("-o can be used with one input file only")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pyguibud-uic",
        description=_(
            "Check PyGUIbud .ui files, generate Python code from them and extract their texts "
            "for translation."
        ),
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
        help=_(
            "output file (generate: default <name>_ui.py next to the .ui file; --extract: "
            "default standard output)"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=_(
            "replace an output file even if pyguibud-uic did not generate it, and generate code "
            "from images and includes outside the folder of the .ui file"
        ),
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


def _read(path: str) -> ReadResult | None:
    """Read one file and print the reader's warnings; None (after a message) if it failed."""
    try:
        result = read_ui(path)
    except XmlIoError as exc:
        print(f"{exc.location}: error: {exc.message}", file=sys.stderr)
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


def _plain(path: str) -> str:
    r"""``path`` without a Win32 namespace prefix (``\\?\``, ``//?/``, ``\\.\``, ``\??\``).

    ``realpath`` keeps such a prefix, so ``\\?\C:\a.ui`` and ``C:\a.ui`` would look like two
    files (QA-11-13). ``\\?\UNC\host\share`` becomes ``\\host\share``.
    """
    if os.name != "nt":
        return path
    text = path.replace("/", "\\")
    for prefix in (r"\\?" + "\\", r"\\." + "\\", r"\??" + "\\"):
        if text.startswith(prefix):
            rest = text[len(prefix) :]
            return r"\\" + rest[4:] if rest[:4].upper() == "UNC\\" else rest
    return path


def _identity(path: str) -> str:
    """The identity of a path: real path without a namespace prefix, case-folded on Windows."""
    return os.path.normcase(os.path.realpath(_plain(path)))


def _same(first: str, second: str) -> bool:
    """True if both paths name one file: the same inode when both exist (hard links, aliases)."""
    try:
        if os.path.samefile(first, second):
            return True
    except (OSError, ValueError):  # one does not exist yet, or cannot be a path
        pass
    return _identity(first) == _identity(second)


def _ui_files(path: str, result: ReadResult) -> list[str]:
    """``path`` and every ``.ui`` file it includes, directly or not (bounded, best effort).

    Only used to protect these files from being overwritten, so an unreadable include still
    counts and nothing is validated.
    """
    files = DiskFiles(path, result)
    keys = [files.root]
    index = 0
    while index < len(keys) and len(keys) <= MAX_INCLUDE_FILES:
        key = keys[index]
        index += 1
        try:
            document = files.read(key).document
        except (OSError, XmlIoError):
            continue
        for node in document.walk():
            if isinstance(node, Include) and isinstance(node.src, str):
                try:
                    target = files.resolve(key, node.src)
                except OSError:
                    continue
                if target not in keys:
                    keys.append(target)
    return [files.path_of(key) for key in keys]


def _regular_or_absent(output: str) -> bool:
    """True if ``output`` does not exist or is a regular file; it is never opened (QA-11-05)."""
    if os.name == "nt" and is_device_name(os.path.basename(output)):  # CON, nul.txt, COM1 .py
        return False
    try:
        mode = os.stat(output).st_mode
    except (FileNotFoundError, NotADirectoryError):  # writing reports a bad folder itself
        return True
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(mode)


def _replaceable(output: str, extracting: bool) -> bool:
    """True if ``output`` (absent or a regular file) may be replaced without ``--force``.

    Only what pyguibud-uic itself wrote is: a module starting with its marker, or a template
    with its ``Generated-By`` header line (see also :func:`_catalogue`).
    """
    size = _POT_HEAD_BYTES if extracting else len(_MARKER)
    try:
        with open(output, "rb") as stream:
            head = stream.read(size)
    except (FileNotFoundError, NotADirectoryError):  # writing reports a bad folder itself
        return True
    except OSError:
        return False
    return _POT_MARKER in head if extracting else head.startswith(_MARKER)


def _catalogue(output: str) -> bool:
    """True if ``output`` is a ``.po`` file or an existing file holding translations.

    A ``.po`` file copied from the template keeps its ``Generated-By`` line, so the marker alone
    cannot protect the translations in it (QA-11-14).
    """
    if os.path.splitext(output)[1].lower() == ".po":
        return True
    try:
        with open(output, "rb") as stream:
            data = stream.read(_POT_LIMIT + 1)
    except OSError:  # absent (the marker check has already refused anything unreadable)
        return False
    if len(data) > _POT_LIMIT:
        return True
    return _has_translations(data.decode("utf-8", errors="replace"))


def _has_translations(text: str) -> bool:
    """True if a PO text has a non-empty ``msgstr`` outside its header (obsolete ``#~`` too)."""
    entry: dict[str, str] = {}
    field: str | None = None

    def translated() -> bool:
        header = entry.get("msgid") == "" and "msgctxt" not in entry
        return not header and any(v for k, v in entry.items() if k.startswith("msgstr"))

    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#~"):
            line = line[2:].strip()
        found = _PO_FIELD_RE.fullmatch(line)
        if found is not None:
            name, value = found.groups()
            if name == "msgctxt" or (name == "msgid" and "msgid" in entry):
                if translated():
                    return True
                entry = {}
            entry[name] = value
            field = name
        elif field is not None and (more := _PO_MORE_RE.fullmatch(line)) is not None:
            entry[field] += more.group(1)
        else:
            field = None
    return translated()


def _check_output(output: str, protected: list[str], written: list[str]) -> str | None:
    """The msgid that refuses ``output`` whatever ``--force`` says, or None."""
    if any(_same(output, path) for path in protected):
        return M_SAME_FILE
    if any(_same(output, path) for path in written):
        return M_ALREADY_WRITTEN
    if not _regular_or_absent(output):
        return M_NOT_REGULAR
    return None


def _write_atomic(output: str, text: str) -> None:
    """Write ``text`` (UTF-8, LF) through a temporary file in the target folder.

    Raises:
        OSError: the file cannot be written; no temporary file is left behind.
    """
    folder = os.path.dirname(os.path.abspath(output))
    descriptor, temporary = tempfile.mkstemp(prefix=".pyguibud-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        # mkstemp creates a private file; the result is an ordinary, non-executable one.
        with contextlib.suppress(OSError):
            os.chmod(temporary, 0o644)
        os.replace(temporary, output)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
        raise


def _refuse(output: str, msgid: str, **params: object) -> bool:
    """Print ``OUT: error: message`` for a refused or failed output; always False."""
    message = format_message(msgid, {"output": output, **params})
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
    refusal = _check_output(output, inputs, written)
    if refusal is not None:
        return _refuse(output, refusal)
    try:
        module = generate_python(result, path, output=output, allow_outside=force)
    except CodegenError as exc:
        for finding in exc.findings:
            _report(finding)
        print(f"{path}: error: {exc.message}", file=sys.stderr)
        return False
    if any(_same(output, source) for source in module.sources):
        return _refuse(output, M_SAME_FILE)
    if not force and not _replaceable(output, extracting=False):
        return _refuse(output, M_NOT_GENERATED)
    try:
        _write_atomic(output, module.text)
    except OSError as exc:
        return _refuse(output, M_WRITE_FAILED, reason=exc.strerror or str(exc))
    written.append(output)
    for finding in module.warnings:
        _report(finding)
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
        protected = [p for result, path in results for p in _ui_files(path, result)]
        refusal = _check_output(output, protected, [])
        if refusal is not None:
            return _refuse(output, refusal)
        if not force and not _replaceable(output, extracting=True):
            return _refuse(output, M_NOT_GENERATED)
        if not force and _catalogue(output):
            return _refuse(output, M_TRANSLATIONS)
    base_dir = os.path.dirname(os.path.abspath(output)) if output else os.getcwd()
    text = extract_pot(results, base_dir=base_dir)
    if output is not None:
        try:
            _write_atomic(output, text)
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
        parser.error(_(_M_O_CHECK))
    if args.force and args.check:
        parser.error(_(_M_FORCE_CHECK))

    ok = True
    paths: list[str] = []
    for argument in args.files:
        found = _expand(argument)
        if not found:
            print(f"{argument}: error: " + _("no file matches this pattern"), file=sys.stderr)
            ok = False
        paths += found
    generating = not (args.check or args.extract)
    if generating and args.output is not None and (len(args.files) > 1 or len(paths) > 1):
        parser.error(_(_M_ONE_INPUT))
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
