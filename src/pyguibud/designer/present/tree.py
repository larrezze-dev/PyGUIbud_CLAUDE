"""Object-tree rows (pure): the whole document as a flat, pre-order list with parent keys."""

from __future__ import annotations

from dataclasses import dataclass

from pyguibud.core import (
    Action,
    Document,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    Statusbar,
    ValidationReport,
    Widget,
    Window,
)
from pyguibud.designer.present import clip
from pyguibud.designer.present.canvas import kind_label
from pyguibud.i18n import N_, _

__all__ = ["TreeRow", "tree_rows"]

_M_WIDGET = N_("{id} ({class_name})")
_M_INCLUDE = N_("{id} (include)")
_M_MENUBAR = N_("Menu bar")
_M_SEPARATOR = N_("Separator")
_M_STATUSBAR = N_("Status bar: {id}")
_M_NO_ID = N_("(no id)")


@dataclass(frozen=True, slots=True)
class TreeRow:
    """One row. ``key`` is synthetic (``n0``, ``n1``...), never a model id (ids may repeat)."""

    key: str
    parent_key: str | None
    node: object
    text: str
    detail: str
    severity: str  # "" | "warning" | "error"


def _id(value: str) -> str:
    return clip(value) if value else _(_M_NO_ID)


def _describe(node: object) -> tuple[str, str]:
    if isinstance(node, Window):
        return _id(node.id), kind_label(node)
    if isinstance(node, Widget):
        return _(_M_WIDGET).format(id=_id(node.id), class_name=clip(node.class_name)), ""
    if isinstance(node, Include):
        return _(_M_INCLUDE).format(id=_id(node.id)), ""
    if isinstance(node, Menubar):
        return _(_M_MENUBAR), ""
    if isinstance(node, Menu | Action):
        return _id(node.id), ""
    if isinstance(node, MenuSeparator):
        return _(_M_SEPARATOR), ""
    if isinstance(node, Statusbar):
        return _(_M_STATUSBAR).format(id=_id(node.id)), ""
    return clip(type(node).__name__), ""


def _children(node: object) -> list[object]:
    if isinstance(node, Window):
        found: list[object] = []
        if node.menubar is not None:
            found.append(node.menubar)
        if node.statusbar is not None:
            found.append(node.statusbar)
        found.extend(node.children)
        return found
    if isinstance(node, Widget | Menubar | Menu):
        return list(node.children)
    return []


def _severities(report: ValidationReport) -> dict[int, str]:
    """The worst severity per anchor node (by identity)."""
    found: dict[int, str] = {}
    for finding in report.findings:
        if finding.anchor is None:
            continue
        key = id(finding.anchor)
        if found.get(key) != "error":
            found[key] = finding.severity
    return found


def tree_rows(document: Document, report: ValidationReport) -> list[TreeRow]:
    """Windows, then their menu bar, status bar and widgets, depth first (iterative)."""
    severities = _severities(report)
    rows: list[TreeRow] = []
    stack: list[tuple[object, str | None]] = [(w, None) for w in reversed(document.children)]
    while stack:
        node, parent_key = stack.pop()
        key = f"n{len(rows)}"
        text, detail = _describe(node)
        rows.append(TreeRow(key, parent_key, node, text, detail, severities.get(id(node), "")))
        stack.extend((child, key) for child in reversed(_children(node)))
    return rows
