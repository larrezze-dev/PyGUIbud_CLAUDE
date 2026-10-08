"""The designer's pure controller: the open document, its command stack, the selection.

No Tk here. Views connect to the signals and call :meth:`DesignerSession.select`; every model
change goes through the :class:`~pyguibud.core.CommandStack` (Step 13 onwards). Step 12 only
*replaces* the document, which creates a new stack and is not an undoable command.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pyguibud.core import (
    CommandStack,
    Document,
    ReadResult,
    Registry,
    StackEvent,
    ValidationReport,
    read_ui_bytes,
    validate,
    validate_read,
)
from pyguibud.core.errors import PyGUIbudError
from pyguibud.core.model import Include, Widget, Window
from pyguibud.designer.signals import Signal
from pyguibud.designer.templates import template_bytes, template_info
from pyguibud.i18n import N_, _

__all__ = ["UNTITLED", "DesignerSession", "Selection", "TemplateError"]

_log = logging.getLogger(__name__)

#: The msgid of the name of a document that has no file yet.
UNTITLED = N_("Untitled")
_M_BAD_TEMPLATE = N_("The template '{template}' is damaged and cannot be opened.")
_M_UNKNOWN_TEMPLATE = N_("There is no template called '{template}'.")
#: A bound on the membership walk of ``select`` (far above any real document; QA-12-06).
_MAX_SELECT_WALK = 1_000_000


def _nothing() -> None:
    return None


def _window_of(node: object) -> object | None:
    """The window above ``node`` (``Include`` has no ``window`` property)."""
    current: object | None = node
    while current is not None and not isinstance(current, Window):
        current = getattr(current, "parent", None)
    return current


class TemplateError(PyGUIbudError):
    """A template is unknown or does not read and validate."""


@dataclass(frozen=True, slots=True)
class Selection:
    """The selected model nodes (by identity, gesture order) and the view that selected them."""

    nodes: tuple[object, ...]
    origin: str  # "tree" | "canvas" | "inspector" | "palette" | "session"

    def __post_init__(self) -> None:
        if not isinstance(self.nodes, tuple):  # catches the Step 12 ``Selection(node, origin)``
            raise TypeError("Selection.nodes must be a tuple")

    @property
    def node(self) -> object | None:
        """The primary (last added) node, or None."""
        return self.nodes[-1] if self.nodes else None

    primary = node


class DesignerSession:
    """Document, command stack, selection and the cached validation report."""

    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self.document: Document | None = None
        self.stack: CommandStack | None = None
        self.name: str = UNTITLED
        self.selection: Selection = Selection((), "session")
        self.document_changed: Signal[DesignerSession] = Signal()
        self.selection_changed: Signal[Selection] = Signal()
        self.report_changed: Signal[ValidationReport] = Signal()
        self._report: ValidationReport | None = None
        self._unsubscribe: Callable[[], None] = _nothing

    @property
    def display_name(self) -> str:
        """The document name in the current language (only the untitled name is translated)."""
        return _(self.name) if self.name == UNTITLED else self.name

    # ------------------------------------------------------------ documents
    def open_result(self, result: ReadResult, *, name: str) -> None:
        """Make ``result.document`` the open document (new stack, selection cleared)."""
        self._unsubscribe()
        self.document = result.document
        self.name = name
        self.stack = CommandStack(result.document, self.registry, source=name)
        self._unsubscribe = self.stack.subscribe(self._on_stack_event)
        self._report = None
        self.selection = Selection((), "session")
        self.document_changed.emit(self)
        self.selection_changed.emit(self.selection)
        self.report_changed.emit(self.report())

    def new_from_template(self, template_id: str) -> None:
        """Open a fresh document made from a built-in template and select its first window.

        Raises:
            TemplateError: the template is unknown, unreadable or has validation errors.
        """
        info = template_info(template_id)
        if info is None:
            raise TemplateError(
                "designer.unknown_template", _M_UNKNOWN_TEMPLATE, template=template_id
            )
        source = f"template:{template_id}"
        try:
            result = read_ui_bytes(template_bytes(info), source=source)
        except (PyGUIbudError, OSError) as exc:
            _log.error("Template %s does not read: %s", template_id, exc)
            raise TemplateError(
                "designer.bad_template", _M_BAD_TEMPLATE, template=template_id
            ) from exc
        if not validate_read(result, self.registry, files=None).ok:
            raise TemplateError("designer.bad_template", _M_BAD_TEMPLATE, template=template_id)
        self.open_result(result, name=UNTITLED)
        windows = result.document.children
        if windows:
            self.select(windows[0], origin="session")

    # ------------------------------------------------------------ selection
    def select(self, node: object | None, *, origin: str) -> None:
        """Select ``node`` (identity). A foreign node or an unchanged selection is ignored."""
        nodes = () if node is None else (node,)
        if len(nodes) == len(self.selection.nodes) and node is self.selection.node:
            return
        if node is not None and id(node) not in self._members():
            return
        self.selection = Selection(nodes, origin)
        self.selection_changed.emit(self.selection)

    def select_many(self, nodes: Iterable[object], *, origin: str) -> None:
        """Select several nodes (gesture order; the last one is the primary), in one walk.

        Foreign nodes are dropped; a repeated node counts once, at its LAST occurrence, so a
        re-added node becomes the primary. Only widgets and includes of the primary's window
        are kept together; any other primary (a window, a bar) stands alone (spec 7.1).
        """
        members, unique = self._members(), dict[int, object]()
        for node in nodes:
            if id(node) in members:
                unique.pop(id(node), None)  # re-inserted at the end: the last one decides
                unique[id(node)] = node
        picked = list(unique.values())
        if picked and isinstance(picked[-1], Widget | Include):
            window = _window_of(picked[-1])
            picked = [
                n for n in picked if isinstance(n, Widget | Include) and _window_of(n) is window
            ]
        elif picked:
            picked = picked[-1:]
        current = self.selection.nodes
        same = len(picked) == len(current)
        if same and all(a is b for a, b in zip(picked, current, strict=True)):
            return
        self.selection = Selection(tuple(picked), origin)
        self.selection_changed.emit(self.selection)

    def _members(self) -> set[int]:
        """The identities of every node of the document (one bounded walk)."""
        found: set[int] = set()
        if self.document is not None:
            for count, candidate in enumerate(self.document.walk()):
                found.add(id(candidate))
                if count >= _MAX_SELECT_WALK:
                    break
        return found

    def _prune(self) -> None:
        """Drop selected nodes that left the document (an undone insert, a delete)."""
        nodes = self.selection.nodes
        if not nodes:
            return
        members = self._members()
        kept = tuple(n for n in nodes if id(n) in members)
        if len(kept) != len(nodes):
            self.selection = Selection(kept, "session")
            self.selection_changed.emit(self.selection)

    # ------------------------------------------------------------ validation
    def report(self) -> ValidationReport:
        """The cached validation report (refreshed on document and stack changes only)."""
        if self._report is None:
            if self.document is None:
                self._report = ValidationReport(findings=())
            else:
                self._report = validate(self.document, self.registry, source=self.name)
        return self._report

    def _on_stack_event(self, _event: StackEvent) -> None:
        # Runs inside the stack's _Busy guard: no listener below may call the stack.
        self._report = None
        self._prune()
        self.report_changed.emit(self.report())

    def can_discard(self) -> bool:
        """True when the open document may be replaced or closed (Step 14 adds the guard)."""
        return True
