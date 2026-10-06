"""Toolkit-agnostic document model of a ``.ui`` file (stdlib only).

Value objects are immutable and hashable; tree nodes are mutable, compare by identity and keep
a strong ``parent`` reference. The model does no validation of ids, ranges or container-ness:
that is the validator's job (Step 09). Anything the model has no field for is kept verbatim in
``extra_attrs`` / ``extra_children`` so that saving never loses third-party content (ADR-001/002).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Generic, Literal, TypeAlias, TypeVar, cast

from pyguibud.core.errors import ModelError
from pyguibud.i18n import N_, _

__all__ = [
    "ABSTRACT_EVENTS",
    "CORE_CLASS_NAMES",
    "KNOWN_NAMESPACES",
    "NS_TB",
    "NS_UI",
    "WIDGET_API_VERSION",
    "Action",
    "ContainerExtras",
    "Document",
    "Event",
    "GridCell",
    "GridLine",
    "ImageResource",
    "Include",
    "Layout",
    "Menu",
    "MenuSeparator",
    "Menubar",
    "Meta",
    "Node",
    "PackPlacement",
    "PagePlacement",
    "Placement",
    "Prop",
    "PropertyDef",
    "PropertyType",
    "RawXml",
    "Statusbar",
    "Variable",
    "Widget",
    "WidgetSpec",
    "Window",
    "is_extension",
    "is_valid_event",
    "qualify",
    "split_class_name",
]

# ---------------------------------------------------------------- constants
NS_UI: Final = "urn:pyguibud:ui:1"
NS_TB: Final = "urn:pyguibud:ext:ttkbootstrap:1"
KNOWN_NAMESPACES: Final[Mapping[str, str]] = MappingProxyType({"tb": NS_TB})

#: Version of the widget plugin API (provisional until 1.0; compatible means equal).
WIDGET_API_VERSION: Final = 1

CORE_CLASS_NAMES: Final[frozenset[str]] = frozenset(
    {
        "Frame",
        "LabelFrame",
        "Notebook",
        "PanedWindow",
        "ScrolledFrame",
        "Label",
        "Button",
        "Entry",
        "Text",
        "Checkbutton",
        "Radiobutton",
        "Combobox",
        "Spinbox",
        "Scale",
        "Progressbar",
        "Separator",
        "Listbox",
        "Treeview",
        "Scrollbar",
        "Canvas",
        "Menubar",
        "Menu",
        "Action",
        "Statusbar",
    }
)

ABSTRACT_EVENTS: Final[frozenset[str]] = frozenset(
    {"command", "change", "select", "activate", "focus_in", "focus_out"}
)

# ---------------------------------------------------------------- names and events
_PREFIX_RE = re.compile(r"[a-z][a-z0-9_-]*")
_LOCAL_RE = re.compile(r"[A-Z][A-Za-z0-9_]*")


def split_class_name(name: str) -> tuple[str | None, str]:
    """Split ``"tb:Meter"`` into ``("tb", "Meter")`` and ``"Button"`` into ``(None, "Button")``.

    Raises:
        ModelError: ``model.bad_class_name`` if ``name`` does not follow the grammar.
    """
    prefix: str | None
    if name.count(":") == 1:
        prefix, local = name.split(":")
    else:
        prefix, local = None, name
    ok = ":" not in local and _LOCAL_RE.fullmatch(local) is not None
    if prefix is not None and _PREFIX_RE.fullmatch(prefix) is None:
        ok = False
    if not ok:
        raise ModelError(
            "model.bad_class_name",
            N_("'{name}' is not a valid widget class name."),
            name=name,
        )
    return prefix, local


def qualify(prefix: str | None, local: str) -> str:
    """Join a prefix and a local name; the inverse of :func:`split_class_name`.

    Raises:
        ModelError: ``model.bad_class_name`` if the result is not a valid class name.
    """
    name = local if prefix is None else f"{prefix}:{local}"
    split_class_name(name)
    return name


def is_extension(name: str) -> bool:
    """Return True for a prefixed (extension) class name such as ``"tb:Meter"``."""
    return ":" in name


def is_valid_event(name: str) -> bool:
    """Return True for an abstract event or a ``key:<Sequence>`` event."""
    if name in ABSTRACT_EVENTS:
        return True
    if name.startswith("key:"):
        sequence = name[4:]
        return (
            bool(sequence)
            and sequence.isprintable()
            and not any(char.isspace() for char in sequence)
        )
    return False


# ---------------------------------------------------------------- value objects
def _freeze(obj: object, *names: str) -> None:
    """Replace mapping fields of a frozen dataclass by read-only copies."""
    for name in names:
        object.__setattr__(obj, name, MappingProxyType(dict(getattr(obj, name))))


@dataclass(frozen=True, slots=True, kw_only=True)
class RawXml:
    """One complete serialised XML element the model does not understand (kept verbatim)."""

    xml: str
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class Prop:
    """A property value as written in the file (raw text, never coerced)."""

    name: str
    value: str = ""
    ref: str | None = None
    translatable: bool = False
    context: str | None = None
    comment: str | None = None
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class Event:
    """Binding of an abstract event to a named handler."""

    name: str
    handler: str
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class GridCell:
    """Placement of a child in a grid layout."""

    row: int
    column: int
    rowspan: int = 1
    columnspan: int = 1
    sticky: str = ""
    padx: int = 0
    pady: int = 0
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class PackPlacement:
    """Placement of a child in a pack layout."""

    fill: Literal["none", "x", "y", "both"] = "none"
    expand: bool = False
    padx: int = 0
    pady: int = 0
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class PagePlacement:
    """Placement of a child of a page container (Notebook tab, PanedWindow pane)."""

    text: Prop | None = None
    image: str | None = None
    weight: int = 0
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class GridLine:
    """Configuration of one grid row or column."""

    index: int
    weight: int = 0
    minsize: int = 0
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class Layout:
    """The single layout of a layout container (ADR-005)."""

    type: Literal["grid", "pack"]
    orient: Literal["vertical", "horizontal"] = "vertical"
    padding: int = 0
    gap: int = 0
    columns: tuple[GridLine, ...] = ()
    rows: tuple[GridLine, ...] = ()
    extra_children: tuple[RawXml, ...] = ()
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class Variable:
    """A declared variable that widgets can bind to (ADR-003)."""

    id: str
    type: Literal["string", "int", "double", "bool"]
    default: str = ""
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class ImageResource:
    """An image resource; ``src`` is a relative path stored verbatim."""

    id: str
    src: str
    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


@dataclass(frozen=True, slots=True, kw_only=True)
class ContainerExtras:
    """Unknown attributes and children of ``<resources>`` or ``<variables>`` (flattened)."""

    extra_attrs: Mapping[str, str] = field(default_factory=dict, hash=False)
    extra_children: tuple[RawXml, ...] = ()

    def __post_init__(self) -> None:
        _freeze(self, "extra_attrs")


Placement: TypeAlias = GridCell | PackPlacement | PagePlacement


# ---------------------------------------------------------------- tree node mixins
def _describe(node: object) -> str:
    node_id = getattr(node, "id", None)
    kind = type(node).__name__
    return f"{kind} '{node_id}'" if node_id else kind


def _insert_position(length: int, index: object) -> int:
    """Where ``list.insert(index, x)`` puts ``x`` in a list of ``length`` items.

    Any int is accepted and clamped like ``list.insert`` does (``10**30`` appends instead of
    overflowing).

    Raises:
        TypeError: ``index`` is not an int (a bool is refused too).
    """
    if not isinstance(index, int) or isinstance(index, bool):
        raise TypeError(f"a child index must be an int, not {type(index).__name__}")
    if index < 0:
        return max(0, length + index)
    return min(index, length)


class _Node:
    """Behaviour shared by every tree node."""

    __slots__ = ()

    def ancestors(self) -> Iterator[Node]:
        """Yield the parent, the grandparent and so on up to the root."""
        current = getattr(self, "parent", None)
        while current is not None:
            yield current
            current = getattr(current, "parent", None)


class _Child(_Node):
    """A node that can be attached to a parent node."""

    __slots__ = ()
    parent: object | None


_C = TypeVar("_C", bound=_Child)


class _Parent(_Node, Generic[_C]):
    """A node with ordered children; holds the mutation primitives used by the command stack."""

    __slots__ = ()
    _children: list[_C]

    def _child_types(self) -> tuple[type[_Child], ...]:
        raise NotImplementedError

    @property
    def children(self) -> tuple[_C, ...]:
        """The children, read-only."""
        return tuple(self._children)

    def insert_child(self, index: int, node: _C) -> None:
        """Insert ``node`` at ``index`` (``list.insert`` semantics) and set its parent.

        Raises:
            ModelError: ``model.already_parented``, ``model.cycle`` or ``model.bad_child``.
            TypeError: ``index`` is not an int. Nothing is changed when anything is raised.
        """
        if node.parent is not None:
            raise ModelError(
                "model.already_parented",
                N_("{node} already has a parent; remove it first."),
                node=_describe(node),
            )
        target: object = node  # typed as object: a node may be both parent and child
        if target is self or any(ancestor is target for ancestor in self.ancestors()):
            raise ModelError(
                "model.cycle",
                N_("{node} cannot be placed inside itself or one of its descendants."),
                node=_describe(node),
            )
        if not isinstance(node, self._child_types()):
            raise ModelError(
                "model.bad_child",
                N_("{child} cannot be a child of {parent}."),
                child=_describe(node),
                parent=_describe(self),
            )
        # Checked last but before any change, so a failure leaves the tree untouched.
        position = _insert_position(len(self._children), index)
        self._children.insert(position, node)
        node.parent = self

    def append_child(self, node: _C) -> None:
        """Append ``node`` as the last child (same errors as :meth:`insert_child`)."""
        self.insert_child(len(self._children), node)

    def index_of(self, node: _C) -> int:
        """Return the index of ``node`` (by identity).

        Raises:
            ModelError: ``model.not_a_child``.
        """
        for index, child in enumerate(self._children):
            if child is node:
                return index
        raise ModelError(
            "model.not_a_child",
            N_("{node} is not a child of {parent}."),
            node=_describe(node),
            parent=_describe(self),
        )

    def remove_child(self, node: _C) -> int:
        """Detach ``node``, clear its parent and return its former index."""
        index = self.index_of(node)
        del self._children[index]
        node.parent = None
        return index

    def move_child(self, node: _C, new_index: int) -> int:
        """Move ``node`` to ``new_index`` (``list.insert`` semantics); return the old index.

        Raises:
            ModelError: ``model.not_a_child``.
            TypeError: ``new_index`` is not an int. Nothing is changed when anything is raised.
        """
        old_index = self.index_of(node)
        # Validated (and clamped) before the removal: a bad index must not drop the node.
        position = _insert_position(len(self._children) - 1, new_index)
        del self._children[old_index]
        self._children.insert(position, node)
        return old_index

    def _walk_children(self) -> Iterator[Node]:
        for child in self._children:
            node: object = child  # typed as object: a node may be both parent and child
            if isinstance(node, _Parent):
                yield from node.walk()
            else:
                yield cast("Node", node)

    def walk(self) -> Iterator[Node]:
        """Yield this node and its descendants, pre-order and depth-first."""
        yield cast("Node", self)
        yield from self._walk_children()


class _HasProps:
    """A node with a ``props`` mapping keyed by property name."""

    __slots__ = ()
    props: dict[str, Prop]

    def set_prop(self, prop: Prop) -> Prop | None:
        """Set ``prop`` (keyed by its name) and return the previous value, if any."""
        previous = self.props.get(prop.name)
        self.props[prop.name] = prop
        return previous

    def remove_prop(self, name: str) -> Prop | None:
        """Remove the property ``name`` and return it, or None if it was not set."""
        return self.props.pop(name, None)


# ---------------------------------------------------------------- tree nodes
@dataclass(eq=False, slots=True, kw_only=True)
class Meta:
    """Document metadata (``<meta>``)."""

    generator: str = ""
    source_locale: str = "en_GB"
    i18n_domain: str = ""
    theme: str = ""
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)


def _default_namespaces() -> dict[str, str]:
    return {"": NS_UI, "tb": NS_TB}


@dataclass(eq=False, slots=True, kw_only=True)
class Document(_Parent["Window"]):
    """Root of a ``.ui`` file; its children are the windows."""

    schema_version: str = "1.0"
    namespaces: dict[str, str] = field(default_factory=_default_namespaces)
    meta: Meta = field(default_factory=Meta)
    resources: dict[str, ImageResource] = field(default_factory=dict)
    variables: dict[str, Variable] = field(default_factory=dict)
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    resources_extra: ContainerExtras = field(default_factory=ContainerExtras)
    variables_extra: ContainerExtras = field(default_factory=ContainerExtras)
    _children: list[Window] = field(default_factory=list, init=False, repr=False)

    def _child_types(self) -> tuple[type[_Child], ...]:
        return (Window,)

    def add_window(self, window: Window) -> None:
        """Append a window."""
        self.append_child(window)

    def insert_window(self, index: int, window: Window) -> None:
        """Insert a window at ``index``."""
        self.insert_child(index, window)

    def remove_window(self, window: Window) -> int:
        """Remove a window and return its former index."""
        return self.remove_child(window)

    @property
    def main_window(self) -> Window | None:
        """The first window of kind ``main``, if any."""
        for window in self._children:
            if window.kind == "main":
                return window
        return None

    def find(self, node_id: str) -> Node | None:
        """Return the first node with ``id == node_id`` (windows, widgets, includes, menus…)."""
        for node in self.walk():
            if getattr(node, "id", None) == node_id:
                return node
        return None

    def iter_ids(self) -> Iterator[tuple[str, object]]:
        """Yield ``(id, owner)`` for every id-bearing node, resource and variable.

        Duplicates are deliberately kept: the validator reports them.
        """
        for node in self.walk():
            node_id = getattr(node, "id", None)
            if node_id is not None:
                yield node_id, node
        for resource in self.resources.values():
            yield resource.id, resource
        for variable in self.variables.values():
            yield variable.id, variable


@dataclass(eq=False, slots=True, kw_only=True)
class Window(_Parent["Widget | Include"], _Child, _HasProps):
    """A top-level window, dialog or reusable component."""

    id: str
    kind: Literal["main", "dialog", "component"] = "main"
    props: dict[str, Prop] = field(default_factory=dict)
    layout: Layout | None = None
    menubar: Menubar | None = None
    statusbar: Statusbar | None = None
    min_width: int | None = None
    min_height: int | None = None
    modal: bool = False
    buttons: str | None = None
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Document | None = field(default=None, init=False, repr=False, compare=False)
    _children: list[Widget | Include] = field(default_factory=list, init=False, repr=False)

    def _child_types(self) -> tuple[type[_Child], ...]:
        return (Widget, Include)

    @property
    def document(self) -> Document | None:
        """The owning document, if attached."""
        return self.parent

    def walk(self) -> Iterator[Node]:
        """Yield the window, its menubar tree, its statusbar, then its widget tree."""
        yield self
        if self.menubar is not None:
            yield from self.menubar.walk()
        if self.statusbar is not None:
            yield self.statusbar
        yield from self._walk_children()


@dataclass(eq=False, slots=True, kw_only=True)
class Widget(_Parent["Widget | Include"], _Child, _HasProps):
    """A widget instance; core classes are plain names, extensions are ``prefix:Local``."""

    class_name: str
    id: str
    props: dict[str, Prop] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    bind: str | None = None
    fallback: str | None = None
    plugin: str | None = None
    placement: Placement | None = None
    layout: Layout | None = None
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Window | Widget | None = field(default=None, init=False, repr=False, compare=False)
    _children: list[Widget | Include] = field(default_factory=list, init=False, repr=False)

    def _child_types(self) -> tuple[type[_Child], ...]:
        return (Widget, Include)

    @property
    def window(self) -> Window | None:
        """The window this widget belongs to, if attached."""
        for ancestor in self.ancestors():
            if isinstance(ancestor, Window):
                return ancestor
        return None


@dataclass(eq=False, slots=True, kw_only=True)
class Include(_Child):
    """Inclusion of a component window from another ``.ui`` file (leaf)."""

    id: str
    src: str
    component: str
    placement: Placement | None = None
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Window | Widget | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(eq=False, slots=True, kw_only=True)
class Menubar(_Parent["Menu"]):
    """The menu bar of a window; its children are menus."""

    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    _children: list[Menu] = field(default_factory=list, init=False, repr=False)

    def _child_types(self) -> tuple[type[_Child], ...]:
        return (Menu,)


@dataclass(eq=False, slots=True, kw_only=True)
class Menu(_Parent["Menu | Action | MenuSeparator"], _Child, _HasProps):
    """A (sub)menu."""

    id: str
    props: dict[str, Prop] = field(default_factory=dict)
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Menubar | Menu | None = field(default=None, init=False, repr=False, compare=False)
    _children: list[Menu | Action | MenuSeparator] = field(
        default_factory=list, init=False, repr=False
    )

    def _child_types(self) -> tuple[type[_Child], ...]:
        return (Menu, Action, MenuSeparator)


@dataclass(eq=False, slots=True, kw_only=True)
class Action(_Child, _HasProps):
    """A menu entry bound to a named handler (leaf)."""

    id: str
    props: dict[str, Prop] = field(default_factory=dict)
    handler: str | None = None
    shortcut: str | None = None
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Menu | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(eq=False, slots=True, kw_only=True)
class MenuSeparator(_Child):
    """A separator line in a menu (leaf)."""

    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)
    parent: Menu | None = field(default=None, init=False, repr=False, compare=False)


@dataclass(eq=False, slots=True, kw_only=True)
class Statusbar(_HasProps):
    """The status bar of a window (leaf)."""

    id: str
    props: dict[str, Prop] = field(default_factory=dict)
    extra_attrs: dict[str, str] = field(default_factory=dict)
    extra_children: list[RawXml] = field(default_factory=list)


Node: TypeAlias = (
    Document | Window | Widget | Include | Menubar | Menu | Action | MenuSeparator | Statusbar
)


# ---------------------------------------------------------------- widget specifications
PropertyType = Literal["string", "int", "float", "bool", "enum", "image", "colour"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PropertyDef:
    """Typed definition of one widget property; ``display_name`` is a msgid."""

    name: str
    type: PropertyType
    default: str | None = None
    translatable: bool = False
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    display_name: str | None = None

    def __post_init__(self) -> None:
        msgid: str | None = None
        if self.type == "enum":
            if not self.choices:
                msgid = N_("The enumeration property '{name}' has no choices.")
            elif self.default is not None and self.default not in self.choices:
                msgid = N_("The default of property '{name}' is not one of its choices.")
        elif self.choices:
            msgid = N_("Only enumeration properties may have choices ('{name}').")
        if msgid is None and self.translatable and self.type != "string":
            msgid = N_("Only string properties can be translatable ('{name}').")
        if msgid is not None:
            raise ModelError("model.bad_property_def", msgid, name=self.name)

    def label(self) -> str:
        """The display name in the current language (or the raw name)."""
        return _(self.display_name) if self.display_name else self.name


def _no_factories() -> Mapping[str, Callable[..., object]]:
    return {}


@dataclass(frozen=True, slots=True, kw_only=True)
class WidgetSpec:
    """Description of a widget class, contributed through the ``pyguibud.widgets`` entry point.

    ``display_name`` and ``category`` are msgids (mark them with ``N_()``); they are translated
    on read. Factories must import their toolkit lazily.
    """

    name: str
    display_name: str
    category: str
    api_version: int
    children: Literal["none", "layout", "pages", "menu"] = "none"
    properties: tuple[PropertyDef, ...] = ()
    events: tuple[str, ...] = ()
    fallback: str | None = None
    icon: str | None = None
    factories: Mapping[str, Callable[..., object]] = field(
        default_factory=_no_factories, compare=False, hash=False
    )
    plugin: str | None = None

    def __post_init__(self) -> None:
        _freeze(self, "factories")

    @property
    def container(self) -> bool:
        """True for layout and page containers."""
        return self.children in ("layout", "pages")

    @property
    def is_extension(self) -> bool:
        """True for a prefixed (plugin) class name."""
        return is_extension(self.name)

    def label(self) -> str:
        """The display name in the current language (or the class name if it is empty)."""
        # gettext("") returns the catalogue header, so an empty msgid must never reach ``_``.
        return _(self.display_name) if self.display_name else self.name

    def category_label(self) -> str:
        """The palette category in the current language."""
        return _(self.category) if self.category else ""

    # Defined last: inside the class body this name shadows the ``property`` builtin.
    def property(self, name: str) -> PropertyDef | None:
        """Return the property definition called ``name``, if any."""
        for definition in self.properties:
            if definition.name == name:
                return definition
        return None
