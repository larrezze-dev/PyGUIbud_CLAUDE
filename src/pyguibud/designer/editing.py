"""Turning insertion targets into commands (pure; spec dnd-selection 5.3).

The canvas and the palette build commands here and hand them to the ``CommandStack``; nothing
in this module mutates a document. Move, resize and nudge builders arrive in Step 13b.
"""

from __future__ import annotations

import keyword
import re

from pyguibud.core.commands import DEFAULT_LAYOUT, Command, InsertNode, RemoveNode, SetField
from pyguibud.core.model import (
    Document,
    GridCell,
    Menubar,
    PackPlacement,
    PagePlacement,
    Prop,
    Statusbar,
    Widget,
    WidgetSpec,
)
from pyguibud.core.validate import RESERVED_IDS
from pyguibud.designer.targets import Target
from pyguibud.i18n import N_, _

__all__ = ["delete_command", "insert_command", "new_node", "refusal", "unique_id"]

_M_STATUSBAR_EXISTS = N_("This window already has a status bar.")
_M_MENUBAR_EXISTS = N_("This window already has a menu bar.")
_STEM_MAX = 58  # leaves room for a 6-digit counter within the 64-character id limit
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")

#: A node the palette can create: a widget, or one of the two window bars.
NewNode = Widget | Statusbar | Menubar


def _stem(class_name: str) -> str:
    """``ScrolledFrame`` -> ``scrolled_frame``; ``tb:Meter`` -> ``meter``; always id-safe."""
    local = class_name.rpartition(":")[2]
    stem = re.sub(r"[^A-Za-z0-9_]", "", _CAMEL.sub("_", local)).lower()
    if not stem or not stem[0].isalpha():
        stem = "widget" + stem
    return stem[:_STEM_MAX]


def unique_id(document: Document | None, stem: str) -> str:
    """``f"{stem}{n}"`` for the smallest n >= 1 that is free in the one id namespace."""
    stem = _stem(stem)
    used: set[str] = set()
    if document is not None:
        used.update(document.variables, document.resources)
        used.update(i for n in document.walk() if isinstance(i := getattr(n, "id", None), str))
    n = 1
    while (
        (candidate := f"{stem}{n}") in used
        or candidate in RESERVED_IDS
        or keyword.iskeyword(candidate)
    ):
        n += 1
    return candidate


def new_node(spec: WidgetSpec, document: Document | None) -> NewNode:
    """A detached node for ``spec`` with a free id and its default text (user content, en-GB)."""
    if spec.name == "Menubar":
        return Menubar()
    if spec.name == "Statusbar":
        return Statusbar(id=unique_id(document, spec.name))
    text = spec.property("text")
    props = {}
    if text is not None and text.translatable:
        props["text"] = Prop(name="text", value=spec.display_name, translatable=True)
    return Widget(
        class_name=spec.name,
        id=unique_id(document, spec.name),
        props=props,
        fallback=spec.fallback,
        plugin=spec.plugin,
        layout=DEFAULT_LAYOUT if spec.children == "layout" else None,
    )


def _bar_name(node: NewNode) -> str:
    return "statusbar" if isinstance(node, Statusbar) else "menubar"


def refusal(target: Target, node: NewNode) -> str | None:
    """Why ``node`` cannot go to ``target`` before any check (a window already has that bar)."""
    if isinstance(node, Widget) or getattr(target.container, _bar_name(node), None) is None:
        return None
    return _(_M_STATUSBAR_EXISTS if isinstance(node, Statusbar) else _M_MENUBAR_EXISTS)


def insert_command(target: Target, node: NewNode) -> Command:
    """The command that puts ``node`` at ``target``; presets the placement of a widget.

    A drag reuses one node for every hover check, so the placement is set again each time.
    """
    if not isinstance(node, Widget):
        return SetField(target.container, _bar_name(node), node)
    container = target.container
    if target.kind == "grid":
        node.placement = GridCell(row=target.row, column=target.column)
    elif target.kind == "slot":
        node.placement = PackPlacement()
    elif isinstance(container, Widget) and "Notebook" in (container.class_name, container.fallback):
        node.placement = PagePlacement(text=Prop(name="text", value=node.id, translatable=True))
    else:
        node.placement = PagePlacement()
    return InsertNode(container, node, target.index)


def delete_command(node: object) -> Command:
    """Remove one widget or include (multi-delete is Step 13b)."""
    return RemoveNode(node)
