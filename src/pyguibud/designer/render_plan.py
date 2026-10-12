"""The designer's build plan for one window (pure; spec dnd-selection 2.2, ADR-010).

The canvas never calls ``load_ui``: that is strict, needs handlers and paths, and refuses
component-only files. This plan wires no handler (opening a ``.ui`` never runs code), shows the
source texts and loads no image (Step 14). :class:`IncludeResolver` expands the includes
(spec direct-manipulation 6): it mirrors the runtime's ``_expand`` without importing it (ADR-007)
and reads included files with the hardened reader only, so opening them never runs code.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from pyguibud.backends.base import BuildPlan, DocumentPlan, Instance, TextSlot
from pyguibud.core.diagnostics import Finding
from pyguibud.core.errors import XmlIoError
from pyguibud.core.files import MAX_EXPANDED_NODES, MAX_INCLUDE_DEPTH, DiskFiles
from pyguibud.core.model import Document, Include, Widget, Window
from pyguibud.core.registry import Registry
from pyguibud.core.validate import validate
from pyguibud.core.xml_io import ReadResult, read_ui
from pyguibud.i18n import N_, _

__all__ = ["DESIGN_KEY", "IncludeResolver", "RecordingScope", "design_plan", "source_text"]

#: The document key of the open document in every design plan.
DESIGN_KEY = "<designer>"


class RecordingScope:
    """A ``Scope`` that keeps nothing: the canvas maps nodes by identity (``Embed.on_node``).

    Ids cannot be trusted for that: an invalid document may have duplicate or empty ids.
    """

    def _attach(self, name: str, obj: object, *, window: bool = False) -> None:
        """Ignore ``ui.<id>`` (the canvas has no scope object)."""

    def _attach_var(self, name: str, var: object) -> None:
        """Ignore ``ui.vars.<id>``."""


def source_text(slot: TextSlot) -> str:
    """The text as written in the document (translated preview is Step 15)."""
    value = slot.prop.value
    return value if isinstance(value, str) else ""


def design_plan(
    document: Document,
    window: Window,
    registry: Registry,
    *,
    log: Callable[..., None],
) -> BuildPlan:
    """The plan that draws ``window`` of ``document`` on the canvas; one plan per window."""
    top = Instance(
        DocumentPlan(key=DESIGN_KEY, path=Path(), document=document),
        windows=(window,),
        scope=RecordingScope(),
    )
    return BuildPlan(
        path=DESIGN_KEY,
        top=top,
        handlers={},
        images={},
        registry=registry,
        theme="",
        text=source_text,
        runtime_text=str,
        log=log,
    )


# Translators: in place of an included component of another file while the document has no file.
_M_SAVE_FIRST = N_("Save the document to show included files.")
# Translators: in place of an included component; {component} is its id, {src} its file.
_M_NOT_SHOWN = N_("The component '{component}' from '{src}' cannot be shown.")
# Translators: status bar for a selected include; {id} is the include, {component} the
# component it shows and {file} the file name (or "this document").
_M_SHOWS = N_("'{id}' shows '{component}' from {file} (read-only). Edit that file to change it.")
# Translators: the {file} of the message above when the component is in the open document.
_M_THIS_DOCUMENT = N_("this document")
# Translators: as above, when {file} uses a newer format than this version knows.
_M_SHOWS_NEWER = N_(
    "'{id}' shows '{component}' from {file} (newer format). It is read-only: a newer version"
    " of PyGUIbud is needed to change it."
)
# Translators: status bar for a selected include drawn as a placeholder; {id} is the include
# and {reason} the text on the placeholder.
_M_PLACEHOLDER = N_("'{id}' cannot be shown: {reason}")
#: What the include rules report (R49 to R53, R82): such an include is never expanded.
_RULES = ("validate.include_", "validate.network_path")
Stamp = tuple[int, int] | None  # (mtime_ns, size) of a file; None when it cannot be read


def _stamp(path: str) -> Stamp:
    try:
        info = os.stat(path)
    except (OSError, ValueError):
        return None
    return info.st_mtime_ns, info.st_size


class _Files(DiskFiles):
    """``DiskFiles`` whose reads come from the resolver's cache, keyed by the file's stamp."""

    def __init__(self, path: Path, root: ReadResult, cache: IncludeResolver) -> None:
        super().__init__(path, root)
        self._shared = cache

    def read(self, key: str) -> ReadResult:
        return super().read(key) if key == self.root else self._shared.read(self.path_of(key))


class IncludeResolver:
    """Fills ``Instance.includes`` for the canvas; every failure is a reason (a placeholder).

    The include rules run first (``validate(files=...)``, cached per document revision); a depth
    limit, the active ``(file, component)`` chain and a node budget stay as defence in depth.
    """

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._parsed: dict[str, tuple[Stamp, ReadResult | OSError | XmlIoError]] = {}
        self._used: dict[str, Stamp] = {}  # the files the current document's includes read
        self._findings: tuple[tuple[object, ...], dict[int, Finding]] | None = None
        # id(include) of those showing a newer-MINOR file, and why the others show a placeholder:
        # kept for every window built (only the rebuilt window's includes change), per document.
        self._document, self._newer, self._failed = 0, set[int](), dict[int, str]()
        self._unshown = set[int]()  # those whose reason is _M_NOT_SHOWN

    def read(self, path: str) -> ReadResult:
        """The ``.ui`` file ``path``, parsed again only when its stamp changed."""
        stamp = self._used[path] = _stamp(path)
        cached = self._parsed.get(path)
        if cached is None or cached[0] != stamp:
            result: ReadResult | OSError | XmlIoError = OSError(f"not a file: {path}")
            if stamp is not None and os.path.isfile(path):
                try:
                    result = read_ui(path)
                except XmlIoError as exc:
                    result = exc
            self._parsed[path] = cached = (stamp, result)
        if isinstance(cached[1], ReadResult):
            return cached[1]
        raise cached[1]

    def changed(self) -> bool:
        """True when a file read for the current document changed on disk, or failed to read
        (locked by another program, say) and reads now (focus-in, 6.2)."""
        # Every file, not ``any``'s first: each lock that went heals on this focus-in (QA-14b2-10).
        if any([_stamp(p) != stamp or self._reads_now(p) for p, stamp in list(self._used.items())]):
            self._findings = None
            return True
        return False

    def _reads_now(self, path: str) -> bool:
        """Read ``path`` again after a read error (a lock does not change the stamp). Runs on
        every focus change: a parse error, which cannot heal with the same stamp, is kept."""
        failure = self._parsed.get(path, (None, None))[1]
        if not isinstance(failure, XmlIoError) or failure.code != "xml.read_failed":
            return False
        del self._parsed[path]
        try:
            self.read(path)
        except (OSError, XmlIoError):
            return False
        return True

    def describe(self, node: Include) -> str:
        """The status-bar text of a selected include (spec 6.3)."""
        if (reason := self._failed.get(id(node))) is not None:
            if id(node) in self._unshown:  # it already says "cannot be shown" (QA-14b2-13)
                return reason
            return _(_M_PLACEHOLDER).format(id=node.id, reason=reason)
        file = _(_M_THIS_DOCUMENT) if node.src == "#" else os.path.basename(node.src)
        text = _M_SHOWS_NEWER if id(node) in self._newer else _M_SHOWS
        return _(text).format(id=node.id, component=node.component, file=file)

    def _files(self, document: Document, path: Path) -> _Files:
        root = ReadResult(
            document=document,
            warnings=(),
            read_only=False,
            source_version=document.schema_version,
            source=str(path),
        )
        return _Files(path, root, self)

    def _blocked(self, document: Document, path: Path | None, revision: int) -> dict[int, Finding]:
        """The include findings of ``document`` by anchor identity (one validation a revision)."""
        key = (id(document), revision, path)
        if self._findings is None or self._findings[0] != key:
            self._used = {}
            if self._document != id(document):
                self._document, self._newer, self._failed = id(document), set(), {}
                self._unshown.clear()
            external = any(
                isinstance(n, Include) and n.src != "#" for w in document.children for n in w.walk()
            )
            files = self._files(document, path) if path is not None and external else None
            name = path.name if path is not None else ""
            report = validate(document, self.registry, source=name, files=files)
            found = {
                id(f.anchor): f
                for f in report.findings
                if f.is_error and isinstance(f.anchor, Include) and f.code.startswith(_RULES)
            }
            self._findings = (key, found)
        return self._findings[1]

    def expand(self, top: Instance, path: Path | None, revision: int = 0) -> dict[int, str]:
        """Expand the includes below ``top``; return the reason of each one left a placeholder."""
        document = top.doc.document
        blocked = self._blocked(document, path, revision)
        files = None if path is None else self._files(document, path)
        key = top.doc.key if files is None else files.root
        chain = frozenset((key, w.id) for w in top.windows if w.kind == "component")
        reasons: dict[int, str] = {}
        self._fill(top, key, chain, (files, blocked, reasons), [MAX_EXPANDED_NODES])
        self._failed.update(reasons)
        return reasons

    def _fill(
        self,
        inst: Instance,
        key: str,
        chain: frozenset[tuple[str, str]],
        state: tuple[_Files | None, dict[int, Finding], dict[int, str]],
        budget: list[int],
    ) -> None:
        """One level of the expansion (the recursion is bounded by ``MAX_INCLUDE_DEPTH``)."""
        files, blocked, reasons = state
        for node in (n for w in inst.windows for n in w.walk() if isinstance(n, Include)):
            self._unshown.discard(id(node))
            if (finding := blocked.get(id(node))) is not None:
                reasons[id(node)] = finding.message
                continue
            if node.src != "#" and files is None:
                reasons[id(node)] = _(_M_SAVE_FIRST)
                continue
            target, included, newer = key, inst.doc.document, False
            try:
                if node.src != "#" and files is not None:
                    target = files.resolve(key, node.src)
                    result = files.read(target)
                    included, newer = result.document, result.read_only
            except (OSError, XmlIoError):
                included = Document()
            component = next(
                (w for w in included.children if w.id == node.component and w.kind == "component"),
                None,
            )
            size = (
                sum(isinstance(n, Widget | Include) for n in component.walk()) if component else 0
            )
            deep = len(chain) >= MAX_INCLUDE_DEPTH  # defence in depth: R53 stops it first
            if component is None or deep or (target, component.id) in chain or size > budget[0]:
                reasons[id(node)] = _(_M_NOT_SHOWN).format(component=node.component, src=node.src)
                self._unshown.add(id(node))
                continue
            budget[0] -= size
            where = Path(files.path_of(target)) if files is not None else Path()
            child = Instance(DocumentPlan(target, where, included), (component,), RecordingScope())
            child.host = inst if target == key else None  # "#" shares the variables (runtime)
            inst.includes[id(node)] = child
            self._failed.pop(id(node), None)
            (self._newer.add if newer else self._newer.discard)(id(node))
            self._fill(child, target, chain | {(target, component.id)}, state, budget)
