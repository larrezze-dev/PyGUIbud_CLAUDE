"""Icon names for palette items and object-tree nodes (pure: names only, no Tk, no pixels)."""

from __future__ import annotations

from typing import Final

from pyguibud.core import (
    CORE_CLASS_NAMES,
    Action,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    Registry,
    Statusbar,
    Widget,
    Window,
)

__all__ = ["class_icon", "node_icon"]

#: Widget classes that have an icon of their own (the core classes and the ttkbootstrap extras).
_CLASS_ICONS: Final = frozenset({*CORE_CLASS_NAMES, "Meter", "Floodgauge", "DateEntry"})
_PUZZLE: Final = "puzzle"


def class_icon(class_name: str, registry: Registry) -> str:
    """The icon of a widget class: its own, else the one of its core fallback, else a puzzle."""
    if class_name in _CLASS_ICONS:
        return class_name
    spec = registry.get(class_name)
    fallback = (spec.fallback or "") if spec is not None else ""
    return fallback if fallback in _CLASS_ICONS else _PUZZLE


def node_icon(node: object, registry: Registry | None = None) -> str:
    """The icon of an object-tree node. ``registry`` resolves plugin widgets to their fallback."""
    if isinstance(node, Window):
        return f"window_{node.kind}"
    if isinstance(node, Widget):
        if registry is not None:
            return class_icon(node.class_name, registry)
        return node.class_name if node.class_name in _CLASS_ICONS else _PUZZLE
    for kind, icon in (
        (Include, "include"), (Menubar, "Menubar"), (Menu, "Menu"), (Action, "Action"),
        (MenuSeparator, "separator"), (Statusbar, "Statusbar"),
    ):  # fmt: skip
        if isinstance(node, kind):
            return icon
    return _PUZZLE
