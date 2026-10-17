"""File > Export Python code: the pure part (spec preview-export 6.2, ADR-013).

``export_plan`` runs every check and generates the texts without writing anything (only stat
and read I/O); ``run_export`` writes them. Both go through :mod:`pyguibud.codegen.output`, so the
result is byte-identical to ``pyguibud-uic FILE -o OUT`` (and ``--extract -o POT``). The Tk
dialog is :mod:`pyguibud.designer.dialogs.export`.
"""

from __future__ import annotations

import hashlib
import keyword
import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from pyguibud.codegen import CodegenError, default_output, extract_pot, generate_python
from pyguibud.codegen._errors import M_ALREADY_WRITTEN, M_READ_ONLY, M_SAME_FILE, M_WRITE_FAILED
from pyguibud.codegen.output import (
    check_output,
    holds_translations,
    protected_ui_files,
    replaceable,
    same_file,
    write_atomic,
)
from pyguibud.core.diagnostics import Finding
from pyguibud.core.errors import XmlIoError, format_message
from pyguibud.core.files import is_network_or_device_path
from pyguibud.core.xml_io import read_ui
from pyguibud.designer.files import M_NETWORK, FileStamp
from pyguibud.i18n import N_, PSEUDO_LANGUAGE, ngettext

__all__ = [
    "ExportOutcome",
    "ExportPlan",
    "ExportRequest",
    "ExportSource",
    "Refusal",
    "default_paths",
    "export_plan",
    "intact",
    "more_text",
    "outside_paths",
    "run_argv",
    "run_export",
]

M_SAVE_FIRST = N_("Save the document before exporting it.")
M_CHANGED = N_("The file changed on disk since it was opened. Save or reopen it first.")
M_NO_NAME = N_("Choose a file name.")
# Translators: {output} is the file name the user typed.
M_IS_FOLDER = N_("'{output}' is a folder. Choose a file name.")
M_SUFFIX = N_("The file name must end in .py.")
# Translators: {name} is a Python module name such as "tkinter".
M_SHADOWS = N_(
    "A file named '{name}' would hide the Python module of the same name. Choose another name."
)
# Translators: {name} is a file name such as "my-form.py"; "import" is Python's keyword.
M_NOT_IMPORTABLE = N_("'{name}' cannot be imported with import; it can still be run.")
M_FOLDER = N_("The folder '{folder}' cannot be written to.")
# Translators: the quoted text is the label of the check box in the Export dialog.
M_OUTSIDE = N_(
    "The path '{src}' used by '{path}' is absolute or outside the folder of its .ui file. Tick "
    "'Allow images and included files outside the .ui folder' to export it anyway."
)
# The designer's wording of the shared output refusals: the CLI's mention --force and -o, which
# the dialog does not have (D12: no override in the GUI).
# Translators: {output} is a file path.
M_NOT_GENERATED = N_(
    "'{output}' was not written by PyGUIbud, so it is not replaced. Choose another name."
)
M_TRANSLATIONS = N_("'{output}' holds translations, so it is not replaced. Choose another name.")
# Translators: {output} is the Python file of this export, also chosen as the .pot file.
M_TEMPLATE_IS_MODULE = N_(
    "'{output}' is the Python file of this export. Choose another name for the template."
)
_GUI_WORDING = {M_ALREADY_WRITTEN: M_TEMPLATE_IS_MODULE}
M_EXPORTED = N_("Exported {output}.")
# Translators: {pot} is the translation template (.pot) written with the module {output}.
M_EXPORTED_POT = N_("Exported {output} and {pot}.")
M_RUN_PSEUDO = N_("The exported module cannot show the pseudo-locale.")
M_RUN_FAILED = N_("The exported module stopped with exit code {code}.")
_OUTSIDE_CODES = frozenset({"validate.absolute_path", "validate.path_escapes"})
#: A file with one of these stems would be imported instead of the module the code needs.
_SHADOWED = frozenset({"ttkbootstrap", "PIL"}) | frozenset(sys.stdlib_module_names)
_MAX_LISTED = 10


def more_text(count: int) -> str:
    """``… and {count} more`` (after a list cut short)."""
    # Translators: closes a list that was cut short; {count} is the number of items left out.
    return ngettext("… and {count} more", "… and {count} more", count).format(count=count)


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why the export does not happen, rendered when shown (so it follows a language switch).

    ``outside`` lists the images and included files outside the ``.ui`` folder (the dialog then
    shows its check box)."""

    msgid: str
    params: Mapping[str, object] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    outside: tuple[str, ...] = ()

    def text(self) -> str:
        lines = [format_message(self.msgid, self.params)]
        lines += [f"• {finding.message}" for finding in self.findings[:_MAX_LISTED]]
        if len(self.findings) > _MAX_LISTED:
            lines.append(more_text(len(self.findings) - _MAX_LISTED))
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class ExportSource:
    """The open document as the export sees it (``path`` None: untitled)."""

    path: Path | None
    dirty: bool
    stamp: FileStamp | None


@dataclass(frozen=True, slots=True)
class ExportRequest:
    """The dialog's choices; ``output`` and ``pot`` are the typed texts (relative to the
    ``.ui`` folder), ``pot`` None when no template is wanted."""

    output: str
    pot: str | None = None
    allow_outside: bool = False
    run_after: bool = False


@dataclass(frozen=True, slots=True)
class ExportPlan:
    """Everything checked and generated; nothing written yet."""

    output: str
    text: str
    pot: str | None
    pot_text: str | None
    run_after: bool
    notes: tuple[Refusal, ...] = ()  # warnings that do not stop the export


@dataclass(frozen=True, slots=True)
class ExportOutcome:
    """What ``run_export`` wrote, and why it stopped if it did."""

    plan: ExportPlan
    written: tuple[str, ...]
    failure: Refusal | None

    def text(self) -> str:
        """The status-bar text (spec 6.2): what was written, then the failure and the notes."""
        parts = []
        if len(self.written) == 2:
            parts.append(format_message(M_EXPORTED_POT, {"output": self.written[0],
                                                         "pot": self.written[1]}))  # fmt: skip
        elif self.written:
            parts.append(format_message(M_EXPORTED, {"output": self.written[0]}))
        failure = (self.failure,) if self.failure is not None else ()
        parts += [note.text() for note in (*failure, *self.plan.notes)]
        return " ".join(parts)


def default_paths(path: Path, domain: str | None, remembered: str | None) -> tuple[str, str]:
    """The proposed module (the remembered one, else ``<stem>_ui.py``) and template paths."""
    pot = path.parent / "locale" / f"{domain or path.stem}.pot"
    return remembered or default_output(str(path)), str(pot)


def outside_paths(findings: Iterable[Finding]) -> tuple[str, ...]:
    """The image and include paths that are absolute or leave the ``.ui`` folder."""
    return tuple(str(f.params.get("path", "")) for f in findings if f.code in _OUTSIDE_CODES)


def _resolve(text: str, folder: Path, suffix: str, *, strict: bool) -> str | Refusal:
    """The absolute file for ``text``; only string tests run before the disk is touched (R82)."""
    text = text.strip()
    if not text:
        return Refusal(M_NO_NAME)
    if is_network_or_device_path(text):
        return Refusal(M_NETWORK)
    path = os.path.abspath(os.path.join(folder, text))  # an absolute text wins
    if text.endswith(("/", os.sep)) or os.path.isdir(path):
        return Refusal(M_IS_FOLDER, {"output": text})
    extension = os.path.splitext(path)[1]
    if not extension:
        return path + suffix
    if strict and extension.lower() != suffix:
        return Refusal(M_SUFFIX)
    return path


def _codegen_refusal(exc: CodegenError) -> Refusal:
    if exc.code == "codegen.outside_path":
        return Refusal(M_OUTSIDE, exc.params, outside=outside_paths(exc.findings))
    return Refusal(exc.msgid, exc.params, exc.findings)


def _writable(folder: str) -> bool:
    return os.path.isdir(folder) and os.access(folder, os.W_OK)  # a hint: the write decides


def export_plan(source: ExportSource, req: ExportRequest) -> ExportPlan | Refusal:
    """Check and generate in the order of spec 6.2; the first failure is returned."""
    path = source.path
    if path is None or source.dirty:
        return Refusal(M_SAVE_FIRST)
    if source.stamp is None or source.stamp.changed(path):
        return Refusal(M_CHANGED)
    ui = str(path)
    try:
        result = read_ui(ui)
    except XmlIoError as exc:
        return Refusal(exc.msgid, exc.params)
    if result.read_only:
        return Refusal(M_READ_ONLY, {"path": ui, "version": result.source_version})
    output = _resolve(req.output, path.parent, ".py", strict=True)
    if isinstance(output, Refusal):
        return output
    name = os.path.basename(output)
    stem = name[: -len(".py")]
    if stem in _SHADOWED or stem.lower().startswith("pyguibud"):
        return Refusal(M_SHADOWS, {"name": stem})
    importable = stem.isidentifier() and not keyword.iskeyword(stem)
    notes = () if importable else (Refusal(M_NOT_IMPORTABLE, {"name": name}),)
    protected = protected_ui_files(ui, result)
    if (refused := check_output(output, protected, [])) is not None:
        return Refusal(refused, {"output": output})
    try:
        module = generate_python(result, ui, output=output, allow_outside=req.allow_outside)
    except CodegenError as exc:
        return _codegen_refusal(exc)
    if any(same_file(output, s) for s in module.sources):
        return Refusal(M_SAME_FILE, {"output": output})
    if not replaceable(output, extracting=False):  # D12: no override in the designer
        return Refusal(M_NOT_GENERATED, {"output": output})
    if not _writable(os.path.dirname(output)):
        return Refusal(M_FOLDER, {"folder": os.path.dirname(output)})
    if req.pot is None:
        return ExportPlan(output, module.text, None, None, req.run_after, notes)
    pot = _resolve(req.pot, path.parent, ".pot", strict=False)
    if isinstance(pot, Refusal):
        return pot
    if (refused := check_output(pot, protected, [output])) is not None:
        return Refusal(_GUI_WORDING.get(refused, refused), {"output": pot})
    if holds_translations(pot):  # first: the more precise reason (both refuse, D12)
        return Refusal(M_TRANSLATIONS, {"output": pot})
    if not replaceable(pot, extracting=True):
        return Refusal(M_NOT_GENERATED, {"output": pot})
    folder = os.path.dirname(pot)  # created at write time, one level only (locale/)
    creatable = not os.path.exists(folder) and _writable(os.path.dirname(folder))
    if not (_writable(folder) or creatable):
        return Refusal(M_FOLDER, {"folder": folder})
    text = extract_pot([(result, ui)], base_dir=folder)
    return ExportPlan(output, module.text, pot, text, req.run_after, notes)


def run_export(plan: ExportPlan) -> ExportOutcome:
    """Write the module, then the template; a failed template leaves the module in place."""
    written: list[str] = []
    target = plan.output
    try:
        write_atomic(plan.output, plan.text)
        written.append(plan.output)
        if plan.pot is not None and plan.pot_text is not None:
            target = plan.pot
            Path(plan.pot).parent.mkdir(exist_ok=True)
            write_atomic(plan.pot, plan.pot_text)
            written.append(plan.pot)
    except OSError as exc:
        reason = {"output": target, "reason": exc.strerror or str(exc)}
        return ExportOutcome(plan, tuple(written), Refusal(M_WRITE_FAILED, reason))
    return ExportOutcome(plan, tuple(written), None)


def intact(output: str, text: str) -> bool:
    """True if the file on disk holds exactly ``text`` (checked right before running it)."""
    try:
        with open(output, "rb") as stream:
            data = stream.read()
    except OSError:
        return False
    return hashlib.sha256(data).digest() == hashlib.sha256(text.encode("utf-8")).digest()


def run_argv(output: str, lang: str | None) -> list[str]:
    """``python OUT [--lang CODE]``; the pseudo-locale is not passed (the module cannot show it)."""
    argv = [sys.executable, output]
    return [*argv, "--lang", lang] if lang and lang != PSEUDO_LANGUAGE else argv
