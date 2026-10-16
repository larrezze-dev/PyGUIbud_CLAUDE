"""Preview of the open document in a child process: the pure part (spec preview-export 4).

What to run (``prepare_preview``: the saved file itself, or a snapshot in a private folder), the
child's argv, the start/stop state machine and the readers of the files the child writes. The
Tk runner is :mod:`pyguibud.designer.preview_tk`.
"""

from __future__ import annotations

import gettext
import importlib.util
import json
import os
import sys
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pyguibud.core import Finding, ReadResult, Registry, XmlIoError, validate
from pyguibud.core.files import DiskFiles
from pyguibud.core.model import Document, GridCell, GridLine, Include, Layout, Prop, Window
from pyguibud.core.xml_io import dump_ui, read_ui_bytes
from pyguibud.designer.files import FileStamp, rebase_paths
from pyguibud.designer.present import severity_label
from pyguibud.designer.settings import DEFAULT_BACKEND
from pyguibud.i18n import N_, PSEUDO_LANGUAGE, _, ngettext

__all__ = [
    "SNAPSHOT",
    "TOOLKIT_NAMES",
    "PreparedPreview",
    "PreviewRequest",
    "PreviewState",
    "Refusal",
    "catalogue_note",
    "child_argv",
    "prepare_preview",
    "preview_findings",
    "read_ready",
    "read_result",
    "read_warnings",
    "stderr_tail",
    "toolkit_installed",
    "toolkit_label",
    "warning_note",
]

SNAPSHOT = "preview.ui"
M_STARTING = N_("Starting the preview…")
# Translators: {window} is a window id such as "main" or "dlg_about".
M_OPEN = N_("Preview of '{window}' open.")
M_HANDLERS = N_("Preview: handlers are not connected, so buttons and menus do nothing.")
# Translators: {reason} is one of the "differs" reasons below, e.g. "a component is shown ...".
M_DIFFERS = N_("This preview differs from the exported module: {reason}.")
M_CLOSED = N_("Preview closed.")
# Translators: the preview's first warning, then how many more there are; {first} is a sentence,
# {count} a number (at least 1).
M_WARNING_MORE = N_("{first} (+{count} more)")
# Translators: Preview > Theme: the theme that the document itself names.
M_DOCUMENT_THEME = N_("Document theme")
# Translators: {lang} is a language code such as de_DE; {folder} is a folder path.
M_NO_CATALOGUE = N_(
    "No translation catalogue for {lang} in {folder}: the texts are shown in the document language."
)
M_SAVE_FIRST = N_(
    "Save the document first: its images or included files are given relative to a folder it "
    "does not have yet."
)
M_UNSAVEABLE = N_("The document cannot be previewed: {reason}")
M_TIMEOUT = N_("The preview did not start within 20 seconds.")
M_CRASHED = N_("The preview stopped unexpectedly (exit code {code}).")
M_TEMP = N_("The preview needs a temporary folder: {reason}.")
M_NO_WINDOW = N_("The document has no window to preview.")
M_NO_PYTHON = N_("The preview cannot start: no Python interpreter was found.")
# Translators: Preview > Toolkit: {name} is a toolkit name (ttkbootstrap, tkinter, PySide6).
M_NOT_INSTALLED_USE = N_("{name} is not installed; the preview uses ttkbootstrap.")
# Translators: Preview > Toolkit menu entry of a toolkit that is not installed.
M_NOT_INSTALLED = N_("{name} (not installed)")
#: Toolkit names that are written differently from their backend name (proper nouns).
TOOLKIT_NAMES = {"pyside6": "PySide6"}
_IMPORT_NAMES = {"pyside6": "PySide6"}  # the importable top-level module of an optional toolkit
# Translators: the reasons that complete "This preview differs from the exported module: ...".
R_PSEUDO = N_("the exported module cannot show the pseudo-locale")
R_THEME = N_("the theme is chosen for the preview only")
R_TOOLKIT = N_("the exported module uses ttkbootstrap")
R_COMPONENT = N_("a component is shown inside a host dialog")
R_SNAPSHOT = N_("included files from other folders show their source texts until it is saved")
_MAX_RESULT = 64 * 1024
_TAIL_BYTES, _TAIL_LINES = 8 * 1024, 20


def toolkit_label(backend: str) -> str:
    """The toolkit's display name (a proper noun, never translated)."""
    return TOOLKIT_NAMES.get(backend, backend)


def toolkit_installed(backend: str) -> bool:
    """False only for a known optional toolkit whose package is missing (find_spec: nothing is
    imported, and a toolkit-less designer stays toolkit-less)."""
    module = _IMPORT_NAMES.get(backend)
    if module is None:
        return True
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class PreviewRequest:
    """The document to preview and how (``lang``/``theme`` None: the document's own)."""

    document: Document
    path: Path | None
    dirty: bool
    read_only: bool
    window_id: str
    lang: str | None
    theme: str | None
    stamp: FileStamp | None = None
    backend: str = DEFAULT_BACKEND


@dataclass(frozen=True, slots=True)
class PreparedPreview:
    """``source`` (a clean saved file) or ``snapshot`` (bytes for ``<private>/preview.ui``)."""

    source: Path | None
    snapshot: bytes | None
    localedir: Path | None
    window_id: str
    host_id: str | None
    differences: tuple[str, ...]  # msgids of section 1's "matches" exclusions (T3: no export hint)


@dataclass(frozen=True, slots=True)
class Refusal:
    """Why the preview does not start (translated). Trim T2: no findings dialog, the status bar
    names the count and the first error."""

    message: str


def preview_findings(
    document: Document, registry: Registry, path: Path | None, private: Path
) -> tuple[Finding, ...]:
    """The validator findings including the file rules (images, includes) as ``load_ui`` sees
    them; an untitled document is checked as if it were the snapshot."""
    root = path if path is not None else private / SNAPSHOT
    result = ReadResult(
        document=document,
        warnings=(),
        read_only=False,
        source_version=document.schema_version,
        source=str(root),
    )
    files = DiskFiles(root, result)
    return validate(document, registry, source=root.name, files=files).findings


def _relative(src: str) -> bool:
    return bool(src) and src != "#" and not os.path.isabs(src)


def _free(base: str, document: Document) -> str:
    taken = {getattr(node, "id", None) for node in document.walk()}
    taken |= set(document.resources) | set(document.variables)
    name, number = base, 1
    while name in taken:
        number += 1
        name = f"{base}_{number}"
    return name


def _add_host(document: Document, component: str) -> str:
    """A dialog ``preview_host`` that includes ``component`` in a 1x1 stretching grid (D5)."""
    grow = (GridLine(index=0, weight=1),)
    host = Window(
        id=_free("preview_host", document),
        kind="dialog",
        props={"title": Prop(name="title", value=component)},
        layout=Layout(type="grid", columns=grow, rows=grow),
    )
    document.add_window(host)
    cell = GridCell(row=0, column=0, sticky="nsew")
    include_id = _free("preview_include", document)
    host.append_child(Include(id=include_id, src="#", component=component, placement=cell))
    return host.id


def prepare_preview(
    req: PreviewRequest, private: Path, findings: Sequence[Finding]
) -> PreparedPreview | Refusal:
    """What the child loads (spec 4.1); the session's document and stack are never changed."""
    document = req.document
    sources = [image.src for image in document.resources.values()]
    sources += [n.src for n in document.walk() if isinstance(n, Include)]
    if req.path is None and any(_relative(s) for s in sources):
        return Refusal(_(M_SAVE_FIRST))
    errors = [f for f in findings if f.is_error]
    if errors:
        text = ngettext(
            "The document has {count} error. Fix it to preview.",
            "The document has {count} errors. Fix them to preview.",
            len(errors),
        ).format(count=len(errors))
        return Refusal(f"{text} {errors[0].message}")
    window = next((w for w in document.children if w.id == req.window_id), None)
    if window is None:  # QA-15a-02: a stale or unknown window id
        return Refusal(_(M_NO_WINDOW))
    component = window.kind == "component"
    differences = [R_PSEUDO] if req.lang == PSEUDO_LANGUAGE else []
    toolkit = req.backend == DEFAULT_BACKEND
    differences += [R_TOOLKIT] if not toolkit else []
    differences += [R_THEME] if req.theme and toolkit else []
    differences += [R_COMPONENT] if component else []
    stamp, path = req.stamp, req.path
    clean = path is not None and stamp is not None and not (req.dirty or component)
    if clean and path is not None and stamp is not None and not stamp.changed(path):
        return PreparedPreview(path, None, None, window.id, None, (*differences,))
    try:  # a copy through the format itself (model nodes cannot be deep-copied)
        snapshot = read_ui_bytes(dump_ui(document)).document
        macro = rebase_paths(snapshot, path.parent if path is not None else None, private)
        if macro is not None:
            macro.apply()
        host = _add_host(snapshot, window.id) if component else None
        data = dump_ui(snapshot)
    except XmlIoError as exc:
        return Refusal(_(M_UNSAVEABLE).format(reason=exc))
    if any(_relative(s) for s in sources if s.lower().endswith(".ui")):
        differences.append(R_SNAPSHOT)
    localedir = path.parent / "locale" if path is not None else None
    return PreparedPreview(None, data, localedir, host or window.id, host, (*differences,))


def child_argv(
    prepared: PreparedPreview,
    private: Path,
    *,
    ui_lang: str,
    lang: str | None,
    theme: str | None,
    backend: str = DEFAULT_BACKEND,
    plugins: Collection[str] | Literal["all"] = (),
) -> list[str]:
    """``python -m pyguibud.preview ...``; the file comes after ``--`` (a leading ``-`` is safe).

    ``plugins`` is the designer's disabled filter, so the child loads the same plugins (D7).
    """
    argv = [sys.executable, "-m", "pyguibud.preview", "--ui-lang", ui_lang, "--backend", backend]
    if plugins == "all":
        argv.append("--no-plugins")
    elif plugins:
        argv += ["--disable-plugins", plugins if isinstance(plugins, str) else ",".join(plugins)]
    for flag, value in (
        ("--lang", lang),
        ("--theme", theme),
        ("--window", prepared.window_id),
        ("--localedir", prepared.localedir),
    ):
        if value:
            argv += [flag, str(value)]
    return [*argv, "--", str(prepared.source or private / SNAPSHOT)]


def catalogue_note(document: Document, folder: Path | None, lang: str | None) -> str | None:
    """The missing-catalogue text for ``lang`` (spec 4.4), or None when it is found or moot."""
    domain, source = document.meta.i18n_domain, document.meta.source_locale or "en_GB"
    if folder is None or not lang or lang == PSEUDO_LANGUAGE or not domain:
        return None
    if lang.split("_")[0].lower() == source.split("_")[0].lower():
        return None
    if gettext.find(domain, str(folder), [lang]):
        return None
    return _(M_NO_CATALOGUE).format(lang=lang, folder=folder)


Phase = Literal["idle", "starting", "running", "stopping"]


@dataclass(slots=True)
class PreviewState:
    """``idle -> starting -> running -> stopping -> idle`` with one ``pending`` restart (4.3)."""

    phase: Phase = "idle"
    pending: bool = False

    def start(self) -> Literal["spawn", "quit", "wait"]:
        """F5: spawn when idle; else ask the child to quit and restart once it has ended."""
        if self.phase == "idle":
            self.phase = "starting"
            return "spawn"
        self.pending = True
        if self.phase == "stopping":
            return "wait"
        self.phase = "stopping"
        return "quit"

    def ready(self) -> None:
        if self.phase == "starting":
            self.phase = "running"

    def stop(self) -> bool:
        """Shift+F5: True when a child must be told to quit."""
        self.pending = False
        if self.phase in ("starting", "running"):
            self.phase = "stopping"
            return True
        return False

    def exited(self) -> bool:
        """The child has ended; True when a pending restart must spawn now."""
        restart, self.pending = self.pending, False
        self.phase = "starting" if restart else "idle"
        return restart


def _json(path: Path) -> object:
    with path.open("rb") as stream:
        data = stream.read(_MAX_RESULT + 1)
    if len(data) > _MAX_RESULT:
        raise ValueError("too large")
    return json.loads(data.decode("utf-8"))


def read_ready(path: Path) -> list[str] | None:
    """The theme names of ``ready.json``, or None while it is missing or not complete."""
    try:
        data = _json(path)
    except (OSError, ValueError):
        return None
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(themes, list):
        return None
    return [t for t in themes if isinstance(t, str)][:200]


def read_warnings(path: Path) -> list[str]:
    """The (already translated) warning messages of ``ready.json``; [] when absent or malformed."""
    try:
        data = _json(path)
    except (OSError, ValueError):
        return []
    items = data.get("warnings") if isinstance(data, dict) else None
    found = (
        [i.get("message") for i in items if isinstance(i, dict)] if isinstance(items, list) else []
    )
    return [m.strip() for m in found if isinstance(m, str) and m.strip()][:20]


def warning_note(warnings: list[str]) -> str:
    """ "Warning: first (+N more)" for the status bar; "" without warnings."""
    if not warnings:
        return ""
    first = (
        warnings[0]
        if len(warnings) == 1
        else _(M_WARNING_MORE).format(first=warnings[0], count=len(warnings) - 1)
    )
    return f"{severity_label('warning')}: {first}"


def read_result(path: Path) -> tuple[str, str]:
    """``(code, message)`` of ``result.json``; missing or malformed = ``"crash"``."""
    try:
        data = _json(path)
    except (OSError, ValueError):
        return "crash", ""
    if not isinstance(data, dict) or not isinstance(data.get("code"), str):
        return "crash", ""
    message = data.get("message")
    return data["code"], message if isinstance(message, str) else ""


def stderr_tail(path: Path) -> str:
    """The last 20 lines (at most 8 KiB) of the child's ``stderr.txt``."""
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - _TAIL_BYTES))
            text = stream.read(_TAIL_BYTES).decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-_TAIL_LINES:])
