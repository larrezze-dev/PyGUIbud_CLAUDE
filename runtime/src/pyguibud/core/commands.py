"""Undoable edit commands and the guarded command stack (ADR-006; spec section 6).

Every model mutation of the designer goes through :class:`CommandStack`. A command wraps the
Step 07 mutation primitives (``insert_child``, ``remove_child``, ``move_child``, ``set_prop``,
``remove_prop``) or a plain assignment of a whitelisted field, and knows how to revert itself
exactly. The stack guards each command: it applies it, runs the full validator, serialises the
result and rolls it back when the edit adds a new error or cannot be saved. A rejection is a
returned :class:`Outcome`, never an exception; exceptions are reserved for programming errors, and
the stack reverts the command before letting one through, so the document never keeps a half-done
edit (spec section 6.3).
"""

from __future__ import annotations

import abc
import logging
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Protocol, TypeAlias, cast

from pyguibud.core.diagnostics import Finding
from pyguibud.core.errors import ModelError, XmlIoError
from pyguibud.core.model import (
    NS_UI,
    Action,
    Document,
    Event,
    GridCell,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    Meta,
    PackPlacement,
    PagePlacement,
    Placement,
    Prop,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    Window,
    _insert_position,
)
from pyguibud.core.schema import CURRENT_SCHEMA_VERSION, parse_version
from pyguibud.core.validate import (
    ValidationReport,
    WidgetLookup,
    guard_key,
    new_errors,
    validate,
)
from pyguibud.core.xml_io import dump_ui
from pyguibud.core.xmltree import LazyMessage, check_attribute_key
from pyguibud.i18n import N_, _

__all__ = [
    "DEFAULT_LAYOUT",
    "EDITABLE_FIELDS",
    "Command",
    "CommandStack",
    "InsertNode",
    "Macro",
    "MoveNode",
    "Outcome",
    "RemoveNode",
    "RemoveProp",
    "RemoveResource",
    "RemoveVariable",
    "SetEvents",
    "SetExtraAttr",
    "SetField",
    "SetProp",
    "SetResource",
    "SetVariable",
    "StackEvent",
    "change_layout",
    "reparent",
]

_log = logging.getLogger(__name__)

#: The layout the designer palette and the demo give every new window or layout container.
DEFAULT_LAYOUT: Final = Layout(type="grid")

_M_READ_ONLY: Final = N_(
    "This document was opened read-only (schema version {version}); it cannot be changed."
)
_M_FOREIGN: Final = N_("This element does not belong to the open document.")
# Translators: {detail} is the reason the file writer gives, already translated.
_M_UNSAVEABLE: Final = N_(
    "This change would make the document impossible to save, so it was not applied: {detail}"
)
_M_UNDO_FAILED: Final = N_("Undo or redo failed; the document was left as it was.")
# Translators: {id} is a variable id; {user} the id of an element that is bound to it.
_M_HISTORY_CLEARED: Final = N_(
    "Undo or redo failed and the document may have changed; the undo history was cleared."
)
_M_VARIABLE_IN_USE: Final = N_("The variable '{id}' is still used by '{user}'; unbind it first.")
# Translators: {id} is an image resource id; {user} the id of an element that shows it.
_M_RESOURCE_IN_USE: Final = N_(
    "The image resource '{id}' is still used by '{user}'; remove that use first."
)

_NONE = type(None)
_STR: Final = (str,)
_OPT_STR: Final = (str, _NONE)
_OPT_INT: Final = (int, _NONE)
_PLACEMENT: Final = (GridCell, PackPlacement, PagePlacement, _NONE)
_LAYOUT: Final = (Layout, _NONE)

#: Fields :class:`SetField` may assign, with the accepted Python types (spec section 6.1).
EDITABLE_FIELDS: Final[Mapping[type, Mapping[str, tuple[type, ...]]]] = MappingProxyType(
    {
        Window: MappingProxyType(
            {
                "id": _STR,
                "kind": _STR,
                "layout": _LAYOUT,
                "menubar": (Menubar, _NONE),
                "statusbar": (Statusbar, _NONE),
                "min_width": _OPT_INT,
                "min_height": _OPT_INT,
                "modal": (bool,),
                "buttons": _OPT_STR,
            }
        ),
        Widget: MappingProxyType(
            {
                "id": _STR,
                "class_name": _STR,
                "bind": _OPT_STR,
                "fallback": _OPT_STR,
                "plugin": _OPT_STR,
                "placement": _PLACEMENT,
                "layout": _LAYOUT,
            }
        ),
        Include: MappingProxyType(
            {"id": _STR, "src": _STR, "component": _STR, "placement": _PLACEMENT}
        ),
        Menu: MappingProxyType({"id": _STR}),
        Action: MappingProxyType({"id": _STR, "handler": _OPT_STR, "shortcut": _OPT_STR}),
        Statusbar: MappingProxyType({"id": _STR}),
        Meta: MappingProxyType(
            {"generator": _STR, "source_locale": _STR, "i18n_domain": _STR, "theme": _STR}
        ),
    }
)

_PARENTS: Final = (Document, Window, Widget, Menubar, Menu)
_CHILDREN: Final = (Window, Widget, Include, Menu, Action, MenuSeparator)
_PROP_OWNERS: Final = (Window, Widget, Menu, Action, Statusbar)
_EXTRA_OWNERS: Final = (Window, Widget, Include, Menubar, Menu, Action, MenuSeparator, Statusbar)

#: Safety net against hand-built, cyclic parent chains.
_MAX_CLIMB: Final = 1_000_000


def _type_ok(value: object, types: tuple[type, ...]) -> bool:
    if isinstance(value, bool):
        # bool is a subclass of int: only fields that declare bool accept it.
        return bool in types
    return isinstance(value, types)


def _check_index(index: object, *, optional: bool = False) -> None:
    """Refuse a child index that is not an int (a bool too) before anything is applied."""
    if optional and index is None:
        return
    if not isinstance(index, int) or isinstance(index, bool):
        raise TypeError(f"a child index must be an int, not {type(index).__name__}")


_Bar: TypeAlias = Menubar | Statusbar


def _shallow(value: object) -> object:
    """A fresh dict or list for the mutable containers of a node; anything else is shared."""
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return list(value)
    return value


def _copy_bar(bar: _Bar) -> _Bar:
    """A deep copy of a menu bar or status bar (iterative; immutable values are shared).

    Commands attach a copy, never the caller's object: a bar has no parent pointer, so the stack
    could not tell whether it still belongs to another window or document (spec section 6.1).
    """
    if isinstance(bar, Statusbar):
        return Statusbar(
            id=bar.id,
            props=cast("dict[str, Prop]", _shallow(bar.props)),
            extra_attrs=cast("dict[str, str]", _shallow(bar.extra_attrs)),
            extra_children=cast("list[RawXml]", _shallow(bar.extra_children)),
        )
    root = Menubar(
        extra_attrs=cast("dict[str, str]", _shallow(bar.extra_attrs)),
        extra_children=cast("list[RawXml]", _shallow(bar.extra_children)),
    )
    pending: list[tuple[Menubar | Menu, Menubar | Menu]] = [(bar, root)]
    while pending:
        original, copy = pending.pop()
        for child in original.children:
            node: object = child
            attrs = cast("dict[str, str]", _shallow(child.extra_attrs))
            raws = cast("list[RawXml]", _shallow(child.extra_children))
            clone: Menu | Action | MenuSeparator
            if isinstance(node, Menu):
                props = cast("dict[str, Prop]", _shallow(node.props))
                clone = Menu(id=node.id, props=props, extra_attrs=attrs, extra_children=raws)
                pending.append((node, clone))
            elif isinstance(node, Action):
                clone = Action(
                    id=node.id,
                    props=cast("dict[str, Prop]", _shallow(node.props)),
                    handler=node.handler,
                    shortcut=node.shortcut,
                    extra_attrs=attrs,
                    extra_children=raws,
                )
            else:
                clone = MenuSeparator(extra_attrs=attrs, extra_children=raws)
            cast("_AnyParent", copy).insert_child(len(copy.children), clone)
    return root


def _rephrase(finding: Finding, code: str, msgid: str, **params: object) -> Finding:
    """A guard reason that explains ``finding`` in the terms of the command that caused it."""
    return Finding(
        code=code,
        msgid=msgid,
        params=params,
        source=finding.source,
        severity="error",
        path=finding.path,
        anchor=finding.anchor,
        part=finding.part,
    )


def _user_of(finding: Finding) -> str:
    """The id of the element a finding is about, or its path when it has no usable id."""
    node_id = getattr(finding.anchor, "id", None)
    return node_id if isinstance(node_id, str) and node_id else finding.path


# ---------------------------------------------------------------- commands
class Command(abc.ABC):
    """One undoable edit. ``apply``/``revert`` are called by the stack and by :class:`Macro`."""

    #: Message id of the undo/redo label (marked with ``N_``); translated by :meth:`text`.
    label: str = N_("Edit")

    def __init__(self) -> None:
        self._applied = False

    def text(self) -> str:
        """The label in the current language."""
        return _(self.label)

    def targets(self) -> tuple[object, ...]:
        """Objects that must belong to the stack's document."""
        return ()

    def is_noop(self) -> bool:
        """True when applying would not change anything (evaluated before applying)."""
        return False

    def explain(self, errors: tuple[Finding, ...]) -> tuple[Finding, ...]:
        """Reword the new errors that reject this command (default: unchanged)."""
        return errors

    @abc.abstractmethod
    def apply(self) -> None:
        """Apply the edit, capturing the undo state now."""

    @abc.abstractmethod
    def revert(self) -> None:
        """Exactly undo the last :meth:`apply`."""

    def merge(self, newer: Command) -> bool:
        """Absorb ``newer`` (already applied) into this command; True on success."""
        return False

    def _begin_apply(self) -> None:
        if self._applied:
            raise RuntimeError(f"{type(self).__name__} is already applied")

    def _begin_revert(self) -> None:
        if not self._applied:
            raise RuntimeError(f"{type(self).__name__} is not applied")


class InsertNode(Command):
    """Insert ``node`` into ``parent`` at ``index`` (``None`` appends)."""

    label = N_("Add element")

    def __init__(self, parent: object, node: object, index: int | None = None) -> None:
        super().__init__()
        if not isinstance(parent, _PARENTS):
            raise TypeError(f"{type(parent).__name__} cannot have children")
        if not isinstance(node, _CHILDREN):
            raise TypeError(f"{type(node).__name__} cannot be inserted")
        _check_index(index, optional=True)
        self.parent = parent
        self.node = node
        self.index = index
        # A window brings its bars: the stack attaches copies it owns (see SetField).
        self._bars: tuple[_Bar | None, _Bar | None] = (None, None)
        self._bar_copies: tuple[_Bar | None, _Bar | None] = (None, None)
        if isinstance(node, Window):
            self._bar_copies = (
                None if node.menubar is None else _copy_bar(node.menubar),
                None if node.statusbar is None else _copy_bar(node.statusbar),
            )

    def targets(self) -> tuple[object, ...]:
        return (self.parent,)

    def apply(self) -> None:
        self._begin_apply()
        parent = cast("_AnyParent", self.parent)
        index = len(parent.children) if self.index is None else self.index
        parent.insert_child(index, self.node)
        node = self.node
        if isinstance(node, Window):
            self._bars = (node.menubar, node.statusbar)
            node.menubar = cast("Menubar | None", self._bar_copies[0])
            node.statusbar = cast("Statusbar | None", self._bar_copies[1])
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        node = self.node
        cast("_AnyParent", self.parent).remove_child(node)
        if isinstance(node, Window):
            node.menubar = cast("Menubar | None", self._bars[0])
            node.statusbar = cast("Statusbar | None", self._bars[1])
            self._bars = (None, None)
        self._applied = False


class RemoveNode(Command):
    """Detach ``node`` from its parent (the index is kept for undo)."""

    label = N_("Delete element")

    def __init__(self, node: object) -> None:
        super().__init__()
        if not isinstance(node, _CHILDREN):
            raise TypeError(f"{type(node).__name__} has no parent to be removed from")
        self.node = node
        self._parent: object | None = None
        self._index = 0

    def targets(self) -> tuple[object, ...]:
        return (self.node,)

    def apply(self) -> None:
        self._begin_apply()
        parent = cast("_AnyParent | None", self.node.parent)
        if parent is None:
            raise ModelError(
                "model.not_a_child",
                N_("'{node}' has already been removed."),
                node=getattr(self.node, "id", None) or type(self.node).__name__,
            )
        self._index = parent.remove_child(self.node)
        self._parent = parent
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        cast("_AnyParent", self._parent).insert_child(self._index, self.node)
        self._parent = None
        self._applied = False


class MoveNode(Command):
    """Move ``node`` to ``new_parent`` at ``index`` (``list.insert`` semantics)."""

    label = N_("Move element")

    def __init__(self, node: object, new_parent: object, index: int) -> None:
        super().__init__()
        if not isinstance(node, _CHILDREN):
            raise TypeError(f"{type(node).__name__} cannot be moved")
        if not isinstance(new_parent, _PARENTS):
            raise TypeError(f"{type(new_parent).__name__} cannot have children")
        _check_index(index)
        self.node = node
        self.new_parent = new_parent
        self.index = index
        self._old_parent: object | None = None
        self._old_index = 0

    def targets(self) -> tuple[object, ...]:
        return (self.node, self.new_parent)

    def is_noop(self) -> bool:
        parent = self.node.parent
        if parent is not self.new_parent:
            return False
        siblings = cast("_AnyParent", parent)
        try:
            old = siblings.index_of(self.node)
        except ModelError:
            return False
        return _insert_position(len(siblings.children) - 1, self.index) == old

    def apply(self) -> None:
        self._begin_apply()
        old_parent = cast("_AnyParent | None", self.node.parent)
        new_parent = cast("_AnyParent", self.new_parent)
        if old_parent is None:
            new_parent.insert_child(self.index, self.node)
            old_index = -1
        elif old_parent is new_parent:
            old_index = new_parent.move_child(self.node, self.index)
        else:
            old_index = old_parent.remove_child(self.node)
            try:
                new_parent.insert_child(self.index, self.node)
            except BaseException:
                # Leaf commands are atomic: put the node back before reporting any failure.
                old_parent.insert_child(old_index, self.node)
                raise
        self._old_parent = old_parent
        self._old_index = old_index
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        new_parent = cast("_AnyParent", self.new_parent)
        old_parent = cast("_AnyParent | None", self._old_parent)
        if old_parent is None:
            new_parent.remove_child(self.node)
        elif old_parent is new_parent:
            new_parent.move_child(self.node, self._old_index)
        else:
            new_index = new_parent.remove_child(self.node)
            try:
                old_parent.insert_child(self._old_index, self.node)
            except BaseException:
                new_parent.insert_child(new_index, self.node)  # stay applied
                raise
        self._old_parent = None
        self._applied = False


class SetProp(Command):
    """Set ``prop`` on ``owner`` (keyed by the property name)."""

    label = N_("Set property")

    def __init__(self, owner: object, prop: Prop) -> None:
        super().__init__()
        if not isinstance(owner, _PROP_OWNERS):
            raise TypeError(f"{type(owner).__name__} has no properties")
        if not isinstance(prop, Prop):
            raise TypeError("prop must be a Prop")
        self.owner = owner
        self.prop = prop
        self._previous: Prop | None = None

    def targets(self) -> tuple[object, ...]:
        return (self.owner,)

    def is_noop(self) -> bool:
        return self.owner.props.get(self.prop.name) == self.prop

    def apply(self) -> None:
        self._begin_apply()
        self._previous = self.owner.set_prop(self.prop)
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        if self._previous is None:
            self.owner.remove_prop(self.prop.name)
        else:
            self.owner.set_prop(self._previous)
        self._applied = False

    def merge(self, newer: Command) -> bool:
        if (
            type(newer) is SetProp
            and newer.owner is self.owner
            and newer.prop.name == self.prop.name
        ):
            self.prop = newer.prop  # keep the oldest undo state, take the newest value
            return True
        return False


class RemoveProp(Command):
    """Remove the property ``name`` from ``owner``."""

    label = N_("Remove property")

    def __init__(self, owner: object, name: str) -> None:
        super().__init__()
        if not isinstance(owner, _PROP_OWNERS):
            raise TypeError(f"{type(owner).__name__} has no properties")
        self.owner = owner
        self.name = name
        self._removed: Prop | None = None
        self._position = 0

    def targets(self) -> tuple[object, ...]:
        return (self.owner,)

    def is_noop(self) -> bool:
        return self.name not in self.owner.props

    def apply(self) -> None:
        self._begin_apply()
        names = list(self.owner.props)
        self._position = names.index(self.name) if self.name in self.owner.props else 0
        self._removed = self.owner.remove_prop(self.name)
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        if self._removed is not None:
            props = self.owner.props
            self.owner.set_prop(self._removed)
            if self._position != len(props) - 1:
                # set_prop appends; restore the original key order in place (exact undo).
                entries = list(props.items())
                entries.insert(self._position, entries.pop())
                props.clear()
                props.update(entries)
        self._removed = None
        self._applied = False


class SetExtraAttr(Command):
    """Set (or, with ``value=None``, remove) one extension attribute such as ``tb:bootstyle``.

    ``key`` is a Clark name ``{namespace}local`` outside the ``.ui`` namespace (spec plugins D15).
    """

    label = N_("Change attribute")

    def __init__(self, node: object, key: str, value: str | None) -> None:
        super().__init__()
        if not isinstance(node, _EXTRA_OWNERS):
            raise TypeError(f"{type(node).__name__} has no extension attributes")
        uri, _sep, _local = key.partition("}") if isinstance(key, str) else ("", "", "")
        try:
            check_attribute_key(key, "")
        except (XmlIoError, TypeError):
            uri = ""
        if not uri.startswith("{") or uri[1:] in ("", NS_UI):
            raise TypeError(f"{key!r} is not an extension attribute name")
        if not isinstance(value, str | _NONE):
            raise TypeError("value must be a str or None")
        self.node = node
        self.key = key
        self.value = value
        self._old: str | None = None

    def targets(self) -> tuple[object, ...]:
        return (self.node,)

    def is_noop(self) -> bool:
        return self.node.extra_attrs.get(self.key) == self.value

    def apply(self) -> None:
        self._begin_apply()
        attrs = self.node.extra_attrs
        self._old = attrs.get(self.key)
        if self.value is None:
            attrs.pop(self.key, None)
        else:
            attrs[self.key] = self.value
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        attrs = self.node.extra_attrs
        if self._old is None:
            attrs.pop(self.key, None)
        else:
            attrs[self.key] = self._old
        self._old = None
        self._applied = False

    def merge(self, newer: Command) -> bool:
        if type(newer) is SetExtraAttr and newer.node is self.node and newer.key == self.key:
            self.value = newer.value
            return True
        return False


class SetField(Command):
    """Assign a whitelisted field (:data:`EDITABLE_FIELDS`) of a node or of ``Meta``."""

    label = N_("Change attribute")

    def __init__(self, target: object, name: str, value: object) -> None:
        super().__init__()
        fields = EDITABLE_FIELDS.get(type(target))
        if fields is None:
            raise TypeError(f"{type(target).__name__} has no editable fields")
        types = fields.get(name)
        if types is None:
            raise TypeError(f"{type(target).__name__}.{name} is not editable")
        if not _type_ok(value, types):
            raise TypeError(
                f"{type(target).__name__}.{name} does not accept {type(value).__name__}"
            )
        self.target = target
        self.name = name
        #: What the caller passed; a bar is attached as a copy owned by this command.
        self.given = value
        self.value = _copy_bar(value) if isinstance(value, Menubar | Statusbar) else value
        self._old: object = None

    def targets(self) -> tuple[object, ...]:
        return (self.target,)

    def is_noop(self) -> bool:
        old = getattr(self.target, self.name)
        return bool(old is self.value or old is self.given or old == self.value)

    def apply(self) -> None:
        self._begin_apply()
        self._old = getattr(self.target, self.name)
        setattr(self.target, self.name, self.value)
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        setattr(self.target, self.name, self._old)
        self._old = None
        self._applied = False

    def merge(self, newer: Command) -> bool:
        if type(newer) is SetField and newer.target is self.target and newer.name == self.name:
            self.given = newer.given
            self.value = newer.value
            return True
        return False


class SetEvents(Command):
    """Replace the event bindings of ``widget``."""

    label = N_("Change events")

    def __init__(self, widget: Widget, events: Sequence[Event]) -> None:
        super().__init__()
        if not isinstance(widget, Widget):
            raise TypeError("SetEvents needs a Widget")
        items = list(events)
        for item in items:
            if not isinstance(item, Event):
                raise TypeError(f"SetEvents needs Event items, not {type(item).__name__}")
        self.widget = widget
        self.events: list[Event] = items
        self._old: list[Event] = []

    def targets(self) -> tuple[object, ...]:
        return (self.widget,)

    def is_noop(self) -> bool:
        return list(self.widget.events) == self.events

    def apply(self) -> None:
        self._begin_apply()
        self._old = self.widget.events
        self.widget.events = list(self.events)
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        self.widget.events = self._old  # the previous list object itself
        self._applied = False


class _DictCommand(Command):
    """Shared undo of the variable and resource commands: an in-place shallow snapshot."""

    attribute: str = ""

    def __init__(self, document: Document) -> None:
        super().__init__()
        if not isinstance(document, Document):
            raise TypeError(f"{type(self).__name__} needs a Document")
        self.document = document
        self._snapshot: dict[str, object] = {}

    def _mapping(self) -> dict[str, object]:
        return cast("dict[str, object]", getattr(self.document, self.attribute))

    def targets(self) -> tuple[object, ...]:
        return (self.document,)

    def apply(self) -> None:
        self._begin_apply()
        mapping = self._mapping()
        self._snapshot = dict(mapping)
        self._change(mapping)
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        mapping = self._mapping()
        # In place: the insertion order, which the writer emits, comes back exactly.
        mapping.clear()
        mapping.update(self._snapshot)
        self._snapshot = {}
        self._applied = False

    @abc.abstractmethod
    def _change(self, mapping: dict[str, object]) -> None: ...


class SetVariable(_DictCommand):
    """Declare or replace a variable (a replace keeps its position)."""

    label = N_("Set variable")
    attribute = "variables"

    def __init__(self, document: Document, variable: Variable) -> None:
        super().__init__(document)
        if not isinstance(variable, Variable):
            raise TypeError("variable must be a Variable")
        self.item: Variable = variable

    def is_noop(self) -> bool:
        return self.document.variables.get(self.item.id) == self.item

    def _change(self, mapping: dict[str, object]) -> None:
        mapping[self.item.id] = self.item


class RemoveVariable(_DictCommand):
    """Remove the variable ``id``."""

    label = N_("Remove variable")
    attribute = "variables"

    def __init__(self, document: Document, id: str) -> None:
        super().__init__(document)
        self.id = id

    def is_noop(self) -> bool:
        return self.id not in self.document.variables

    def explain(self, errors: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(
            _rephrase(
                f, "command.variable_in_use", _M_VARIABLE_IN_USE, id=self.id, user=_user_of(f)
            )
            if f.code == "validate.unknown_variable" and f.params.get("bind") == self.id
            else f
            for f in errors
        )

    def _change(self, mapping: dict[str, object]) -> None:
        mapping.pop(self.id, None)


class SetResource(_DictCommand):
    """Declare or replace an image resource (a replace keeps its position)."""

    label = N_("Set image resource")
    attribute = "resources"

    def __init__(self, document: Document, image: ImageResource) -> None:
        super().__init__(document)
        if not isinstance(image, ImageResource):
            raise TypeError("image must be an ImageResource")
        self.item: ImageResource = image

    def is_noop(self) -> bool:
        return self.document.resources.get(self.item.id) == self.item

    def _change(self, mapping: dict[str, object]) -> None:
        mapping[self.item.id] = self.item


class RemoveResource(_DictCommand):
    """Remove the image resource ``id``."""

    label = N_("Remove image resource")
    attribute = "resources"

    def __init__(self, document: Document, id: str) -> None:
        super().__init__(document)
        self.id = id

    def is_noop(self) -> bool:
        return self.id not in self.document.resources

    def explain(self, errors: tuple[Finding, ...]) -> tuple[Finding, ...]:
        return tuple(
            _rephrase(
                f, "command.resource_in_use", _M_RESOURCE_IN_USE, id=self.id, user=_user_of(f)
            )
            if f.code == "validate.unknown_resource" and f.params.get("ref") == self.id
            else f
            for f in errors
        )

    def _change(self, mapping: dict[str, object]) -> None:
        mapping.pop(self.id, None)


class Macro(Command):
    """Several commands applied as one atomic, undoable step. It never merges."""

    def __init__(self, label: str, commands: Iterable[Command]) -> None:
        super().__init__()
        self.label = label
        self.commands: tuple[Command, ...] = tuple(commands)
        for command in self.commands:
            if not isinstance(command, Command):
                raise TypeError("a Macro holds commands only")

    def targets(self) -> tuple[object, ...]:
        return tuple(target for command in self.commands for target in command.targets())

    def is_noop(self) -> bool:
        return all(command.is_noop() for command in self.commands)

    def explain(self, errors: tuple[Finding, ...]) -> tuple[Finding, ...]:
        for command in self.commands:
            errors = command.explain(errors)
        return errors

    def apply(self) -> None:
        self._begin_apply()
        done: list[Command] = []
        try:
            for command in self.commands:
                command.apply()
                done.append(command)
        except ModelError:
            for command in reversed(done):
                command.revert()
            raise
        except Exception:
            # A bug, not a rejection: undo what we can, then let it surface.
            for command in reversed(done):
                try:
                    command.revert()
                except Exception:
                    _log.exception("reverting %r after a failure also failed", command)
            raise
        self._applied = True

    def revert(self) -> None:
        self._begin_revert()
        done: list[Command] = []
        try:
            for command in reversed(self.commands):
                command.revert()
                done.append(command)
        except BaseException:
            # Mirror of apply(): put back what was already reverted, in forward order, so the
            # macro is still fully applied (leaf commands restore themselves when they raise).
            for command in reversed(done):
                try:
                    command.apply()
                except Exception:
                    _log.exception("re-applying %r after a failed revert also failed", command)
            raise
        self._applied = False


def reparent(node: object, new_parent: object, index: int, placement: Placement) -> Macro:
    """Move ``node`` to ``new_parent`` and give it the placement the new layout needs."""
    return Macro(
        N_("Move element"),
        [MoveNode(node, new_parent, index), SetField(node, "placement", placement)],
    )


def change_layout(
    container: Window | Widget,
    layout: Layout,
    placements: Mapping[Widget | Include, Placement],
) -> Macro:
    """Replace the layout of ``container`` and re-place every child in one step.

    Raises:
        TypeError: ``container`` is not a window or widget, or ``layout`` is not a Layout.
        ValueError: a current child has no entry in ``placements``, or an entry is not a child.
    """
    if not isinstance(container, (Window, Widget)):
        raise TypeError(f"{type(container).__name__} has no layout")
    if not isinstance(layout, Layout):
        raise TypeError("change_layout needs a Layout; it never removes one")
    children = container.children
    for child in children:
        if child not in placements:
            raise ValueError(f"no placement for child {getattr(child, 'id', '?')!r}")
    child_ids = {id(child) for child in children}
    for node in placements:
        if id(node) not in child_ids:
            raise ValueError(f"{getattr(node, 'id', node)!r} is not a child of the container")
    commands: list[Command] = [SetField(container, "layout", layout)]
    commands.extend(SetField(child, "placement", placements[child]) for child in children)
    return Macro(N_("Change layout"), commands)


# ---------------------------------------------------------------- stack
@dataclass(frozen=True, slots=True)
class Outcome:
    """The result of :meth:`CommandStack.execute` or :meth:`CommandStack.check`."""

    accepted: bool
    changed: bool
    merged: bool = False
    #: Rejected: the new errors (the reasons). Accepted: the new warnings.
    findings: tuple[Finding, ...] = ()

    @property
    def message(self) -> str:
        """The first finding's message in the current language, or ``""``."""
        return self.findings[0].message if self.findings else ""

    def __bool__(self) -> bool:
        return self.accepted


_EventKind: TypeAlias = Literal["execute", "merge", "undo", "redo", "saved", "clear"]


@dataclass(frozen=True, slots=True)
class StackEvent:
    """Notification sent to :meth:`CommandStack.subscribe` listeners after a state change."""

    kind: _EventKind
    command: Command | None
    dirty: bool


def _new_warnings(before: Iterable[Finding], after: Iterable[Finding]) -> tuple[Finding, ...]:
    known = Counter(guard_key(f) for f in before if not f.is_error)
    fresh: list[Finding] = []
    for finding in after:
        if finding.is_error:
            continue
        key = guard_key(finding)
        if known[key] > 0:
            known[key] -= 1
        else:
            fresh.append(finding)
    return tuple(fresh)


class _AnyParent(Protocol):
    """Typing helper: the primitive surface shared by every parent node."""

    children: tuple[object, ...]

    def insert_child(self, index: int, node: object) -> None: ...
    def remove_child(self, node: object) -> int: ...
    def move_child(self, node: object, new_index: int) -> int: ...
    def index_of(self, node: object) -> int: ...


class CommandStack:
    """Undo/redo history of one document, with validation guards (spec section 6.2)."""

    def __init__(
        self,
        document: Document,
        registry: WidgetLookup,
        *,
        source: str = "<memory>",
        limit: int = 1000,
        dirty: bool = False,
    ) -> None:
        """``dirty=True`` starts unsaved (a restored recovery snapshot, ADR-011)."""
        if not isinstance(document, Document):
            raise TypeError("CommandStack needs a Document")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            raise ValueError(f"limit must be a whole number of at least 1, not {limit!r}")
        self._document = document
        self._registry = registry
        self._source = source
        self._limit = limit
        self._history: list[Command] = []
        self._index = 0
        self._saved_index: int | None = None if dirty else 0
        self._merge_open = False
        self._listeners: list[Callable[[StackEvent], None]] = []
        self._busy = False
        self._failure: Finding | None = None

    # ------------------------------------------------------------ properties
    @property
    def document(self) -> Document:
        """The edited document."""
        return self._document

    @property
    def read_only(self) -> bool:
        """True when the document's schema is newer than this PyGUIbud writes (D5)."""
        version = self._document.schema_version
        parsed = parse_version(version) if isinstance(version, str) else None
        current = parse_version(CURRENT_SCHEMA_VERSION)
        return parsed is not None and current is not None and parsed > current

    @property
    def limit(self) -> int:
        """The maximum number of undo steps."""
        return self._limit

    @property
    def index(self) -> int:
        """The number of applied commands (the undo depth)."""
        return self._index

    @property
    def can_undo(self) -> bool:
        """True when there is a step to undo."""
        return self._index > 0

    @property
    def can_redo(self) -> bool:
        """True when there is a step to redo."""
        return self._index < len(self._history)

    @property
    def undo_text(self) -> str | None:
        """The translated label of the step :meth:`undo` would revert."""
        return self._history[self._index - 1].text() if self.can_undo else None

    @property
    def redo_text(self) -> str | None:
        """The translated label of the step :meth:`redo` would apply."""
        return self._history[self._index].text() if self.can_redo else None

    @property
    def failure(self) -> Finding | None:
        """The finding of the last failed undo/redo (``command.undo_failed``), else None."""
        return self._failure

    @property
    def is_dirty(self) -> bool:
        """True when the document differs from the last saved (or loaded) state."""
        return self._saved_index != self._index

    # ------------------------------------------------------------ editing
    def execute(self, command: Command) -> Outcome:
        """Apply ``command`` if it adds no new error; otherwise leave everything untouched."""
        with _Busy(self):
            return self._run(command, commit=True)

    def check(self, command: Command) -> Outcome:
        """Dry run of :meth:`execute`: the command is always reverted and never pushed."""
        with _Busy(self):
            return self._run(command, commit=False)

    def undo(self) -> bool:
        """Revert the last step; False when there is nothing to undo or the revert failed.

        A failed revert leaves the document and the history as they were; see :attr:`failure`.
        """
        with _Busy(self):
            if not self.can_undo:
                return False
            command = self._history[self._index - 1]
            if not self._step(command.revert):
                return False
            self._index -= 1
            self._after_move()
            self._notify("undo", command)
            return True

    def redo(self) -> bool:
        """Re-apply the next step; False when there is nothing to redo or the apply failed."""
        with _Busy(self):
            if not self.can_redo:
                return False
            command = self._history[self._index]
            if not self._step(command.apply):
                return False
            self._index += 1
            self._after_move()
            self._notify("redo", command)
            return True

    def mark_saved(self) -> None:
        """Record the current state as saved (call it after ``write_ui`` succeeded)."""
        self._saved_index = self._index
        self._merge_open = False
        self._notify("saved", None)

    def break_merge(self) -> None:
        """Make the next edit a separate undo step."""
        self._merge_open = False

    def clear(self) -> None:
        """Drop the history; the document keeps its current state and dirty flag."""
        with _Busy(self):
            dirty = self.is_dirty
            self._history.clear()
            self._index = 0
            self._saved_index = None if dirty else 0
            self._merge_open = False
            self._failure = None
            self._notify("clear", None)

    def report(self) -> ValidationReport:
        """Full validation of the current state, capped at ``MAX_FINDINGS``.

        Never cached: an edit made behind the stack's back is always seen (spec section 6.3).
        """
        return validate(self._document, self._registry, source=self._source)

    def subscribe(self, callback: Callable[[StackEvent], None]) -> Callable[[], None]:
        """Call ``callback`` after every state change; returns a function that unsubscribes."""
        self._listeners.append(callback)

        def unsubscribe() -> None:
            for index, listener in enumerate(self._listeners):
                if listener is callback:
                    del self._listeners[index]
                    return

        return unsubscribe

    # ------------------------------------------------------------ internals
    def _validate(self) -> ValidationReport:
        return validate(self._document, self._registry, source=self._source, limit=None)

    def _after_move(self) -> None:
        self._merge_open = False

    def _finding(self, code: str, msgid: str, anchor: object = None, **params: object) -> Finding:
        return Finding(
            code=code,
            msgid=msgid,
            params=params,
            source=self._source,
            severity="error",
            anchor=anchor,
        )

    def _reject(self, code: str, msgid: str, anchor: object = None, **params: object) -> Outcome:
        return Outcome(
            accepted=False, changed=False, findings=(self._finding(code, msgid, anchor, **params),)
        )

    def _step(self, action: Callable[[], None]) -> bool:
        """Run one revert/apply; on failure say no, or drop the history if the model changed."""
        before = _dump_text(self._document)
        try:
            action()
        except Exception:
            _log.exception("undo or redo failed")
            if _dump_text(self._document) == before is not None:
                self._failure = self._finding("command.undo_failed", _M_UNDO_FAILED)
                return False
            # The command mutated the model and then raised: the history can no longer be
            # trusted, so drop it but keep the document dirty (it must still be saveable).
            self._history.clear()
            self._index = 0
            self._saved_index = None
            self._merge_open = False
            self._notify("clear", None)
            self._failure = self._finding("command.history_cleared", _M_HISTORY_CLEARED)
            return False
        self._failure = None
        return True

    def _run(self, command: Command, *, commit: bool) -> Outcome:
        if not isinstance(command, Command):
            raise TypeError("execute() needs a Command")
        if self.read_only:
            return self._reject(
                "command.read_only", _M_READ_ONLY, version=self._document.schema_version
            )
        for target in command.targets():
            if not self._belongs(target):
                return self._reject("command.foreign_node", _M_FOREIGN, target)
        if command.is_noop():
            return Outcome(accepted=True, changed=False)
        # Always the live state, never a cache: the document may have been edited behind the
        # stack's back, and a stale "before" would let new errors through (or block clean edits).
        before = self._validate()
        applied = False
        try:
            try:
                command.apply()
            except ModelError as error:
                # Leaf commands and macros undo their own partial work before raising.
                return self._reject(error.code, error.msgid, None, **error.params)
            applied = True
            after = self._validate()
            fresh = new_errors(before.findings, after.findings)
            if fresh:
                command.revert()
                applied = False
                return Outcome(accepted=False, changed=False, findings=command.explain(fresh))
            detail = _dump_problem(self._document)
            if detail is not None:
                command.revert()
                applied = False
                if _dump_problem(self._document) is None:
                    return self._reject("command.unsaveable", _M_UNSAVEABLE, None, detail=detail)
                # The document could not be saved before this command either: not a new problem
                # (the guard blocks only what an edit adds), so the edit is kept.
                command.apply()
                applied = True
            warnings = _new_warnings(before.findings, after.findings)
            if not commit:
                command.revert()
                applied = False
                return Outcome(accepted=True, changed=True, findings=warnings)
        except BaseException:
            # A programming error (or an interrupt): leave the document as it was, then raise.
            if applied:
                try:
                    command.revert()
                except Exception:
                    _log.exception("reverting %r after a failure also failed", command)
            raise
        self._failure = None
        merged = self._push(command)
        self._notify("merge" if merged else "execute", command)
        return Outcome(accepted=True, changed=True, merged=merged, findings=warnings)

    def _push(self, command: Command) -> bool:
        top = self._history[self._index - 1] if self._index else None
        if (
            top is not None
            and self._merge_open
            and self._index == len(self._history)
            and self._saved_index != self._index
            and type(command) is type(top)
            and top.merge(command)
        ):
            # ``top`` now owns the change and its undo state; the absorbed command is free to be
            # executed again (it captures a fresh undo state when it is applied).
            command._applied = False
            return True
        if self._index < len(self._history):
            del self._history[self._index :]
            if self._saved_index is not None and self._saved_index > self._index:
                self._saved_index = None  # the save point was in the dropped redo tail
        self._history.append(command)
        self._index += 1
        self._merge_open = True
        while len(self._history) > self._limit:
            del self._history[0]
            self._index -= 1
            if self._saved_index is not None:
                self._saved_index -= 1
                if self._saved_index < 0:
                    self._saved_index = None
        return False

    def _belongs(self, target: object) -> bool:
        document = self._document
        if target is document or target is document.meta:
            return True
        current: object | None = target
        for _step in range(_MAX_CLIMB):
            if current is None:
                return False
            if current is document:
                return True
            if isinstance(current, Menubar):
                return any(window.menubar is current for window in document.children)
            if isinstance(current, Statusbar):
                return any(window.statusbar is current for window in document.children)
            current = getattr(current, "parent", None)
        return False

    def _notify(self, kind: _EventKind, command: Command | None) -> None:
        event = StackEvent(kind=kind, command=command, dirty=self.is_dirty)
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                _log.exception("a command stack listener failed")


def _dump_text(document: Document) -> bytes | None:
    """The saved form of ``document``, or None when it cannot be written."""
    try:
        return dump_ui(document)
    except Exception:
        return None


def _dump_problem(document: Document) -> object | None:
    """Why ``dump_ui`` refuses ``document`` (a lazily translated reason), or None if it saves."""
    try:
        dump_ui(document)
    except XmlIoError as error:
        return LazyMessage(error.msgid, **error.params)
    except Exception as error:
        # Not a domain error: the validator missed a shape the writer cannot handle. The edit
        # is still refused (it would be unsaveable); keep the trace for whoever debugs it.
        _log.warning("the writer failed on an edited document", exc_info=True)
        return f"{type(error).__name__}: {error}"
    return None


class _Busy:
    """Re-entrancy guard: listeners must not edit the stack they are notified by."""

    __slots__ = ("_stack",)

    def __init__(self, stack: CommandStack) -> None:
        self._stack = stack

    def __enter__(self) -> None:
        if self._stack._busy:
            raise RuntimeError("the command stack cannot be changed from one of its listeners")
        self._stack._busy = True

    def __exit__(self, *exc: object) -> None:
        self._stack._busy = False
