"""Read-only inspector rows (pure): general data, properties, placement and findings of a node."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from pyguibud.core import (
    Action,
    GridCell,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    Prop,
    PropertyDef,
    Registry,
    Statusbar,
    ValidationReport,
    Widget,
    Window,
)
from pyguibud.core.validate import WINDOW_PROPERTIES
from pyguibud.designer.present import clip, severity_label
from pyguibud.designer.present.canvas import kind_label
from pyguibud.i18n import N_, _

__all__ = ["InspectorRow", "display_value", "inspector_rows"]

_S_GENERAL = N_("General")
_S_PROPERTIES = N_("Properties")
_S_PLACEMENT = N_("Placement")
_S_FINDINGS = N_("Findings")
_M_VARIABLE = N_("variable {name}")
_M_DEFAULT = N_("{value} (default)")
_M_YES = N_("Yes")
_M_NO = N_("No")


@dataclass(frozen=True, slots=True)
class InspectorRow:
    """One line: the section it belongs to, a label, the value and whether it is the default."""

    section: str
    label: str
    value: str
    is_default: bool = False


def display_value(row: InspectorRow) -> str:
    """The value as shown, with the "(default)" mark for an unset property."""
    return _(_M_DEFAULT).format(value=row.value) if row.is_default else row.value


def _yes_no(flag: bool) -> str:
    return _(_M_YES) if flag else _(_M_NO)


def _class_and_id(node: object) -> list[tuple[str, str]]:
    if isinstance(node, Window):
        return [(_("Class"), _("Window")), (_("Id"), clip(node.id)), (_("Kind"), kind_label(node))]
    if isinstance(node, Widget):
        rows = [(_("Class"), clip(node.class_name)), (_("Id"), clip(node.id))]
        return rows + ([(_("Plugin"), clip(node.plugin))] if node.plugin else [])
    if isinstance(node, Include):
        return [
            (_("Class"), _("Include")),
            (_("Id"), clip(node.id)),
            (_("Source"), clip(node.src)),
            (_("Component"), clip(node.component)),
        ]
    if isinstance(node, Menubar):
        return [(_("Class"), _("Menu bar"))]
    if isinstance(node, Menu):
        return [(_("Class"), _("Menu")), (_("Id"), clip(node.id))]
    if isinstance(node, Action):
        rows = [(_("Class"), _("Action")), (_("Id"), clip(node.id))]
        if node.handler:
            rows.append((_("Handler"), clip(node.handler)))
        if node.shortcut:
            rows.append((_("Shortcut"), clip(node.shortcut)))
        return rows
    if isinstance(node, MenuSeparator):
        return [(_("Class"), _("Separator"))]
    if isinstance(node, Statusbar):
        return [(_("Class"), _("Status bar")), (_("Id"), clip(node.id))]
    return []


def _prop_value(prop: Prop) -> str:
    return _(_M_VARIABLE).format(name=clip(prop.ref)) if prop.ref else clip(prop.value)


def _property_rows(
    props: Mapping[str, Prop], definitions: Iterable[PropertyDef]
) -> list[InspectorRow]:
    section = _(_S_PROPERTIES)
    rows: list[InspectorRow] = []
    known: set[str] = set()
    for definition in definitions:
        known.add(definition.name)
        prop = props.get(definition.name)
        if prop is not None:
            rows.append(InspectorRow(section, definition.label(), _prop_value(prop)))
        else:
            rows.append(InspectorRow(section, definition.label(), definition.default or "", True))
    rows.extend(
        InspectorRow(section, clip(name), _prop_value(prop))
        for name, prop in props.items()
        if name not in known
    )
    return rows


def _placement_rows(node: object) -> list[InspectorRow]:
    section = _(_S_PLACEMENT)
    pairs: list[tuple[str, str]] = []
    layout = getattr(node, "layout", None)
    if layout is not None:
        pairs += [
            (_("Layout"), clip(layout.type)),
            (_("Padding"), str(layout.padding)),
            (_("Gap"), str(layout.gap)),
        ]
    placement = getattr(node, "placement", None)
    if isinstance(placement, GridCell):
        pairs += [
            (_("Row"), str(placement.row)),
            (_("Column"), str(placement.column)),
            (_("Row span"), str(placement.rowspan)),
            (_("Column span"), str(placement.columnspan)),
            (_("Sticky"), clip(placement.sticky)),
        ]
    elif isinstance(placement, PackPlacement):
        pairs += [(_("Fill"), clip(placement.fill)), (_("Expand"), _yes_no(placement.expand))]
    elif isinstance(placement, PagePlacement) and placement.text is not None:
        pairs.append((_("Page title"), _prop_value(placement.text)))
    return [InspectorRow(section, label, value) for label, value in pairs]


def inspector_rows(
    node: object | None, registry: Registry, report: ValidationReport
) -> list[InspectorRow]:
    """The rows for ``node``, grouped by section (General, Properties, Placement, Findings)."""
    if node is None:
        return []
    general = _(_S_GENERAL)
    rows = [InspectorRow(general, label, value) for label, value in _class_and_id(node)]
    if isinstance(node, Window):
        rows += _property_rows(node.props, WINDOW_PROPERTIES)
    elif isinstance(node, Widget):
        spec = registry.get(node.class_name)
        rows += _property_rows(node.props, spec.properties if spec is not None else ())
    elif isinstance(node, Menu | Action | Statusbar):
        rows += _property_rows(node.props, ())
    rows += _placement_rows(node)
    findings = _(_S_FINDINGS)
    rows += [
        InspectorRow(findings, severity_label(finding.severity), clip(finding.message, 200))
        for finding in report.findings
        if finding.anchor is node
    ]
    return rows
