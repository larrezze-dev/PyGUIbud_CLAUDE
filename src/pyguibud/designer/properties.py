"""The inspector's editable fields (pure; spec properties-save-load 3.1, 3.4).

``field_rows`` describes what the inspector shows for a selection, ``parse_value`` checks the
grammar of typed text at once (so an editor can say *why*), and ``commit_commands`` turns a value
into the one command the ``CommandStack`` runs. The stack's guard stays the final judge.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal

from pyguibud.core.colours import colour_problem
from pyguibud.core.commands import Command, Macro, RemoveProp, SetExtraAttr, SetField, SetProp
from pyguibud.core.diagnostics import Finding
from pyguibud.core.model import (
    NS_TB,
    Action,
    Document,
    GridCell,
    GridLine,
    Include,
    Layout,
    Menu,
    PackPlacement,
    PagePlacement,
    Prop,
    PropertyDef,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.core.registry import Registry
from pyguibud.core.validate import (
    _FLOAT_RE,
    _INT_RE,
    BIND_TYPES,
    MAX_GRID_INDEX,
    MAX_PIXELS,
    MAX_WEIGHT,
    WINDOW_PROPERTIES,
)
from pyguibud.designer.editing import relayout_command, rename_window
from pyguibud.i18n import N_, NP_, _, ngettext, plural_of

__all__ = [
    "EditorKind",
    "Field",
    "commit_commands",
    "dialog_commands",
    "dialog_prop",
    "field_rows",
    "parse_value",
]

EditorKind = Literal[
    "string", "int", "float", "bool", "enum", "colour", "image", "variable",
    "id", "class", "handler", "shortcut", "sticky", "buttons", "bootstyle",
]  # fmt: skip

S_GENERAL = N_("General")
S_PROPERTIES = N_("Properties")
S_LAYOUT = N_("Layout")
S_PLACEMENT = N_("Placement")
S_WINDOW = N_("Window")
S_ACTION = N_("Action")
_M_NOT_INT = N_("Not a whole number.")
_LONG_INT_RE = re.compile(r"-?[0-9]+", re.ASCII)  # any length: "12345678901" is a number
_M_NOT_NUMBER = N_("Not a number.")
# Translators: {minimum} and {maximum} are the limits of a number field.
_M_RANGE = N_("Must be between {minimum} and {maximum}.")
_M_NOT_COLOUR = N_("Not a colour such as #1C3FF0.")
_M_SYSTEM_COLOUR = N_("A system colour exists on one platform only; use a colour such as #1C3FF0.")
# Translators: the Undo label of one edit on several elements; {name} is the field's label.
_M_SET_MANY = NP_("Set '{name}' on {count} element", "Set '{name}' on {count} elements")
#: The limits of a number field the definition leaves open; the placement, layout and window
#: fields use the validator's own bounds (``MAX_GRID_INDEX``, ``MAX_PIXELS``, ``MAX_WEIGHT``).
LIMIT = 10_000
_KIND_NAMES = {Window: N_("Window"), Include: N_("Include"), Menu: N_("Menu")}
_KIND_NAMES |= {Action: N_("Action"), Statusbar: N_("Status bar")}


@dataclass(frozen=True, slots=True)
class Field:
    """One editable row: ``key`` says what it edits; ``value`` None = mixed (multi-edit)."""

    key: str  # "prop:text", "field:id", "place:grid:row", "layout:orient", "line:col:2:weight"
    section: str  # msgid
    label: str  # msgid, or a raw property name
    kind: EditorKind
    value: str | None
    default: str | None = None
    is_default: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    multi: bool = True  # False: shown for a single selection only
    translatable: bool = False  # a string property whose definition is translatable


def _signature(f: Field) -> tuple[object, ...]:
    return (f.section, f.label, f.kind, f.default, f.choices, f.minimum, f.maximum)


# ---------------------------------------------------------------- rows
_SECTION = {"prop": S_PROPERTIES, "layout": S_LAYOUT, "place": S_PLACEMENT, "line": S_PLACEMENT}
_SECTION["tb"] = S_PROPERTIES
BOOTSTYLE_KEY = f"{{{NS_TB}}}bootstyle"
_COLOURS = ("primary", "secondary", "success", "info", "warning", "danger", "light", "dark")
_TYPES = ("", "outline", "link", "inverse", "striped", "round-toggle", "square-toggle")
#: The Bootstyle row's suggestions (colour x type); any text is allowed, the guard judges it.
BOOTSTYLE_CHOICES = tuple(f"{c}-{t}" if t else c for t in _TYPES for c in _COLOURS)
_NO_BOOTSTYLE = frozenset({"Text", "Listbox", "Canvas"})  # plain Tk widgets (R84)
_FIELD_SECTION = {"handler": S_ACTION, "shortcut": S_ACTION, "kind": S_WINDOW, "modal": S_WINDOW}
_FIELD_SECTION |= {"min_width": S_WINDOW, "min_height": S_WINDOW, "buttons": S_WINDOW}
_SINGLE = frozenset({"field:class", "field:id", "field:src", "field:component", "field:bind"})
_SINGLE |= {"field:kind", "place:grid:row", "place:grid:column"}


def _f(key: str, label: str, kind: EditorKind, value: object, default: object = None,
       **extra: Any) -> Field:  # noqa: ANN401 - Field keywords  # fmt: skip
    """A row; the section follows from the key, "unset" (None) shows as an empty value."""
    family, _sep, name = key.partition(":")
    section = _FIELD_SECTION.get(name, S_GENERAL) if family == "field" else _SECTION[family]
    text = "" if value is None else _text(value)
    shown = None if default is None else _text(default)
    extra.setdefault("is_default", value is None or text == shown)
    extra.setdefault("multi", key not in _SINGLE and not key.startswith("line:"))
    return Field(key, section, label, kind, text, shown, **extra)


def _text(value: object) -> str:
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


def _num(
    key: str, label: str, value: int, default: int = 0, low: int = 0, high: int = MAX_PIXELS
) -> Field:
    return _f(key, label, "int", value, default, minimum=low, maximum=high)


def _prop_fields(props: dict[str, Prop], definitions: Sequence[PropertyDef]) -> list[Field]:
    rows: list[Field] = []
    for d in definitions:
        prop = props.get(d.name)
        value = d.default if prop is None else prop.ref if d.type == "image" else prop.value
        extra = {"choices": d.choices, "minimum": d.minimum, "maximum": d.maximum}
        rows.append(_f(f"prop:{d.name}", d.display_name or d.name, d.type, value, d.default,
                       is_default=prop is None, translatable=d.translatable, **extra))  # fmt: skip
    known = {d.name for d in definitions}
    rows += [_f(f"prop:{n}", n, "string", p.value) for n, p in props.items() if n not in known]
    return rows


def _general(node: Any, document: Document) -> list[Field]:  # noqa: ANN401 - any node
    name = node.class_name if isinstance(node, Widget) else _(_KIND_NAMES.get(type(node), ""))
    rows = [_f("field:class", N_("Class"), "class", name)]
    if isinstance(node, Window | Widget | Include | Menu | Action | Statusbar):
        rows.append(_f("field:id", N_("Id"), "id", node.id))
    if isinstance(node, Include):
        rows.append(_f("field:src", N_("Source"), "string", node.src))
        rows.append(_f("field:component", N_("Component"), "string", node.component))
    if isinstance(node, Widget) and BIND_TYPES.get(node.class_name):
        types = BIND_TYPES[node.class_name]
        names = tuple(v.id for v in document.variables.values() if v.type in types)
        rows.append(_f("field:bind", N_("Variable"), "variable", node.bind, choices=names))
    if isinstance(node, Action):
        rows.append(_f("field:handler", N_("Handler"), "handler", node.handler))
        rows.append(_f("field:shortcut", N_("Shortcut"), "shortcut", node.shortcut))
    if isinstance(node, Window):
        kinds = ("main", "dialog", "component")
        rows.append(_f("field:kind", N_("Kind"), "enum", node.kind, choices=kinds))
        # A component is expanded into a Frame: its minimum is a canvas preview size (D4).
        preview = node.kind == "component"
        width, height = N_("Preview width"), N_("Preview height")
        if not preview:
            width, height = N_("Minimum width"), N_("Minimum height")
        rows.append(_f("field:min_width", width, "int", node.min_width,
                       minimum=0, maximum=MAX_PIXELS))  # fmt: skip
        rows.append(_f("field:min_height", height, "int", node.min_height,
                       minimum=0, maximum=MAX_PIXELS))  # fmt: skip
        rows.append(_f("field:modal", N_("Modal"), "bool", node.modal, False))
        if node.kind == "dialog":
            rows.append(_f("field:buttons", N_("Buttons"), "buttons", node.buttons))
    return rows


def _layout(layout: Layout) -> list[Field]:
    return [
        _f("layout:type", N_("Layout"), "enum", layout.type, choices=("grid", "pack")),
        _f("layout:orient", N_("Orientation"), "enum", layout.orient, "vertical",
           choices=("vertical", "horizontal")),
        _num("layout:padding", N_("Padding"), layout.padding),
        _num("layout:gap", N_("Gap"), layout.gap),
    ]  # fmt: skip


def _line(layout: Layout, axis: str, index: int) -> GridLine:
    lines = layout.columns if axis == "col" else layout.rows
    return next((line for line in lines if line.index == index), GridLine(index=index))


_LINES = (
    ("col", N_("Column weight"), N_("Column minimum size")),
    ("row", N_("Row weight"), N_("Row minimum size")),
)


_SPAN = MAX_GRID_INDEX + 1  # a span may reach the end of Tk's grid


def _placement(node: Widget | Include) -> list[Field]:
    p = node.placement
    if isinstance(p, GridCell):
        rows = [
            _num("place:grid:row", N_("Row"), p.row, high=MAX_GRID_INDEX),
            _num("place:grid:column", N_("Column"), p.column, high=MAX_GRID_INDEX),
            _num("place:grid:rowspan", N_("Row span"), p.rowspan, 1, 1, _SPAN),
            _num("place:grid:columnspan", N_("Column span"), p.columnspan, 1, 1, _SPAN),
            _f("place:grid:sticky", N_("Sticky"), "sticky", p.sticky, ""),
            _num("place:grid:padx", N_("Horizontal padding"), p.padx),
            _num("place:grid:pady", N_("Vertical padding"), p.pady),
        ]
        layout: Layout | None = getattr(node.parent, "layout", None)
        for axis, weight, minsize in _LINES if layout is not None else ():
            assert layout is not None
            index = p.column if axis == "col" else p.row
            line = _line(layout, axis, index)
            rows.append(_num(f"line:{axis}:{index}:weight", weight, line.weight, high=MAX_WEIGHT))
            rows.append(_num(f"line:{axis}:{index}:minsize", minsize, line.minsize))
        return rows
    if isinstance(p, PackPlacement):
        return [
            _f("place:pack:fill", N_("Fill"), "enum", p.fill, "none",
               choices=("none", "x", "y", "both")),
            _f("place:pack:expand", N_("Expand"), "bool", p.expand, False),
            _num("place:pack:padx", N_("Horizontal padding"), p.padx),
            _num("place:pack:pady", N_("Vertical padding"), p.pady),
        ]  # fmt: skip
    if isinstance(p, PagePlacement):
        text = None if p.text is None else p.text.value
        return [
            _f("place:page:text", N_("Page title"), "string", text, translatable=True),
            _f("place:page:image", N_("Image"), "image", p.image),
            _num("place:page:weight", N_("Weight"), p.weight, high=MAX_WEIGHT),
        ]
    return []


def _fields(node: object, registry: Registry, document: Document) -> list[Field]:
    rows = _general(node, document)
    if isinstance(node, Window):
        rows += _prop_fields(node.props, WINDOW_PROPERTIES)
    elif isinstance(node, Widget | Menu | Action | Statusbar):
        name = node.class_name if isinstance(node, Widget) else type(node).__name__
        spec = registry.get(name)
        rows += _prop_fields(node.props, spec.properties if spec is not None else ())
        core = (spec.fallback or spec.name) if spec is not None else getattr(node, "fallback", "")
        if isinstance(node, Widget) and core not in _NO_BOOTSTYLE:  # T5: the designer is ttkbs
            # Translators: "Bootstyle" is a ttkbootstrap term (the widget's colour and type).
            rows.append(
                _f(
                    "tb:bootstyle",
                    N_("Bootstyle"),
                    "bootstyle",
                    node.extra_attrs.get(BOOTSTYLE_KEY),
                    choices=BOOTSTYLE_CHOICES,
                )
            )
    if isinstance(node, Window | Widget) and node.layout is not None:
        rows += _layout(node.layout)
    if isinstance(node, Widget | Include):
        rows += _placement(node)
    images = tuple(document.resources)
    return [replace(f, choices=images) if f.kind == "image" else f for f in rows]


def field_rows(
    nodes: Sequence[object], registry: Registry, document: Document
) -> tuple[Field, ...]:
    """The fields of one node, or those shared (same key and definition) by every node."""
    if not nodes:
        return ()
    first = _fields(nodes[0], registry, document)
    if len(nodes) == 1:
        return tuple(first)
    others = [{f.key: f for f in _fields(n, registry, document)} for n in nodes[1:]]
    shared: list[Field] = []
    for f in first:
        matches = [o.get(f.key) for o in others]
        if not f.multi or any(m is None or _signature(m) != _signature(f) for m in matches):
            continue
        same = all(m is not None and m.value == f.value for m in matches)
        shared.append(f if same else replace(f, value=None, is_default=False))
    return tuple(shared)


# ---------------------------------------------------------------- parsing
def _reason(msgid: str, **params: object) -> Finding:
    return Finding(
        code="inspector.bad_value", msgid=msgid, params=params, source="inspector", severity="error"
    )


def parse_value(field: Field, text: str) -> str | Finding:
    """``text`` as the value to commit ("" resets a number or colour), or why it is not one."""
    if field.kind not in ("int", "float", "colour"):
        return text
    text = text.strip()
    if not text:
        return ""
    if field.kind == "colour":
        problem = colour_problem(text)
        if problem is None:
            return text
        return _reason(_M_SYSTEM_COLOUR if problem == "system" else _M_NOT_COLOUR)
    pattern, msgid = (_INT_RE, _M_NOT_INT) if field.kind == "int" else (_FLOAT_RE, _M_NOT_NUMBER)
    # A whole number with more digits than the file allows is out of range, not "not a number".
    too_long = field.kind == "int" and _LONG_INT_RE.fullmatch(text) is not None
    if pattern.fullmatch(text) is None and not too_long:
        return _reason(msgid)
    low = -LIMIT if field.minimum is None else field.minimum
    high = LIMIT if field.maximum is None else field.maximum
    if not low <= float(text) <= high:
        shown = [int(b) if float(b).is_integer() else b for b in (low, high)]
        return _reason(_M_RANGE, minimum=shown[0], maximum=shown[1])
    return text


# ---------------------------------------------------------------- commands
class _SetMany(Macro):
    """One undo step for several nodes; its label names the field and counts the nodes."""

    def __init__(self, name: str, commands: Sequence[Command]) -> None:
        super().__init__(_M_SET_MANY, commands)
        self.name = name

    def text(self) -> str:
        count = len(self.commands)
        plural = plural_of(self.label) or self.label
        return ngettext(self.label, plural, count).format(name=_(self.name), count=count)


def _typed(field: Field, value: str | None) -> Any:  # noqa: ANN401 - the field's own type
    if value is None:
        return None
    if field.kind == "int":
        return int(value) if value else None
    if field.kind == "bool":
        return value == "true"
    if value == "" and field.kind in ("handler", "shortcut", "buttons", "variable", "image"):
        return None
    return value


def _with_line(layout: Layout, axis: str, index: int, attr: str, value: int) -> Layout:
    """``layout`` with one grid line changed; an all-default line is dropped (canonical form)."""
    line = _line(layout, axis, index)
    line = replace(line, weight=value) if attr == "weight" else replace(line, minsize=value)
    lines = [x for x in (layout.columns if axis == "col" else layout.rows) if x.index != index]
    if line.weight or line.minsize or line.extra_attrs or line.extra_children:
        lines = sorted([*lines, line], key=lambda x: x.index)
    if axis == "col":
        return replace(layout, columns=tuple(lines))
    return replace(layout, rows=tuple(lines))


def _command(node: Any, field: Field, value: str | Prop | None) -> Command:  # noqa: ANN401
    family, _sep, rest = field.key.partition(":")
    if family == "prop":
        old = node.props.get(rest)
        if value is None or (field.kind == "image" and value == ""):
            return RemoveProp(node, rest)
        if isinstance(value, Prop):
            return SetProp(node, value)
        if field.kind == "image":
            prop = replace(old, value="", ref=value) if old else Prop(name=rest, ref=value)
        elif old is not None:
            prop = replace(old, value=value, ref=None)  # keeps translatable, context, comment
        else:
            prop = Prop(name=rest, value=value, translatable=field.translatable)
        return SetProp(node, prop)
    text = value.value if isinstance(value, Prop) else value
    if family == "tb":  # "" or a reset removes the attribute
        return SetExtraAttr(node, BOOTSTYLE_KEY, text or None)
    if text is None:
        text = field.default
    typed = _typed(field, text)
    if family == "field" and rest == "id" and isinstance(node, Window):
        document = node.parent
        if isinstance(document, Document):  # its same-file includes follow (spec 14 A21)
            return rename_window(document, node, str(typed))
    if family == "field":
        return SetField(node, rest, typed)
    if family == "layout":
        if rest == "type":
            return relayout_command(node, str(typed))
        return SetField(node, "layout", replace(node.layout, **{rest: typed}))
    if family == "line":
        axis, index, attr = rest.split(":")
        parent = node.parent
        return SetField(
            parent, "layout", _with_line(parent.layout, axis, int(index), attr, typed or 0)
        )
    name = rest.partition(":")[2]
    placement = node.placement
    if name == "text" and isinstance(value, Prop | None):
        typed = value
    elif name == "text":
        page = placement.text
        new = Prop(name="text", value=str(text), translatable=True)
        typed = replace(page, value=text) if page else new
    return SetField(node, "placement", replace(placement, **{name: typed}))


_PROP_PARTS = ("value", "translatable", "context", "comment")


def _node_prop(node: object, field: Field) -> Prop:
    """The property ``field`` of ``node`` as stored, or as a new one would be (default value)."""
    name = field.key.partition(":")[2]
    prop: Prop | None = getattr(node, "props", {}).get(name)
    if prop is not None:
        return prop
    return Prop(name=name, value=field.default or "", translatable=field.translatable)


def dialog_prop(nodes: Sequence[object], field: Field) -> Prop:
    """What the text dialog starts from: the model value and the translation data every node
    shares; a part that differs (a mixed selection) starts empty, or as on the first node."""
    props = [_node_prop(node, field) for node in nodes]
    first = props[0]

    def shared(part: str) -> Any:  # noqa: ANN401 - str, bool or None
        values = {getattr(prop, part) for prop in props}
        return values.pop() if len(values) == 1 else None

    translatable = shared("translatable")
    return replace(
        first,
        value=field.value or "",
        translatable=first.translatable if translatable is None else translatable,
        context=shared("context"),
        comment=shared("comment"),
    )


def dialog_commands(
    nodes: Sequence[object], field: Field, before: Prop, after: Prop
) -> Command | None:
    """The text dialog's edit: only the parts the user changed from ``before`` are applied, on
    each node's own property (the others are kept); None when nothing changed."""
    changes = {p: getattr(after, p) for p in _PROP_PARTS if getattr(after, p) != getattr(before, p)}
    if not changes:
        return None
    commands = [SetProp(node, replace(_node_prop(node, field), **changes)) for node in nodes]
    return commands[0] if len(commands) == 1 else _SetMany(field.label, commands)


def commit_commands(nodes: Sequence[object], field: Field, value: str | Prop | None) -> Command:
    """The command that sets ``field`` to ``value`` on every node (None = reset to default)."""
    commands = [_command(node, field, value) for node in nodes]
    if len(commands) == 1:
        return commands[0]
    return _SetMany(field.label, commands)
