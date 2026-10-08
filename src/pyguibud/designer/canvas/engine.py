"""The canvas engine (spec dnd-selection 2.1-2.3): the runtime's own builder, embedded.

Each window is built by ``TtkbootstrapBackend.build_embedded`` from the pure design plan into a
frame of its stage, put in design mode, and mapped node <-> widget by identity.
"""

from __future__ import annotations

import contextlib
import logging
import re
import tkinter
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any

from pyguibud.backends._tk import Embed, TkSession
from pyguibud.backends.ttkbootstrap import TtkbootstrapBackend
from pyguibud.core.errors import format_message
from pyguibud.core.model import Document, Include, Widget, Window
from pyguibud.core.registry import Registry
from pyguibud.designer.canvas.design import apply_design_mode
from pyguibud.designer.geometry import ChildBox, ContainerBox, Rect, Snapshot
from pyguibud.designer.render_plan import design_plan
from pyguibud.i18n import N_, _

__all__ = ["CanvasEngine", "WindowView", "reveal", "widget_rect"]

_log = logging.getLogger(__name__)

# Translators: drawn on the canvas in place of an included component; {component} is its id.
_M_INCLUDED = N_("Included: {component}")
_PLACEHOLDER_SIZE = (120, 48)  # px at 96 dpi


@dataclass(eq=False, slots=True)
class WindowView:
    """One rendered window: its session, frame and the node <-> widget maps."""

    window: Window
    session: TkSession
    frame: Any
    title: str | None = None
    outer: dict[int, Any] = field(default_factory=dict)  # id(node) -> gridded/packed widget
    inner: dict[int, Any] = field(default_factory=dict)  # id(node) -> widget holding children
    nodes: dict[int, object] = field(default_factory=dict)  # id(node) -> node (keeps it alive)
    owner: dict[str, object] = field(default_factory=dict)  # Tk path -> node

    def node_of(self, widget: Any) -> object | None:  # noqa: ANN401 - a Tk widget
        """The node that owns ``widget`` (internal sub-widgets map to their node)."""
        path = str(widget)
        while path and path != ".":
            node = self.owner.get(path)
            if node is not None:
                return node
            path = path.rpartition(".")[0]
        return None

    def menubar(self) -> Any:  # noqa: ANN401 - a Tk menu or None
        """The hidden ``Menu`` tree of the window (built, never attached), or None."""
        menus = [c for c in self.frame.winfo_children() if isinstance(c, tkinter.Menu)]
        return menus[0] if menus else None

    def destroy(self) -> None:
        leaked, root = _wheel_commands(self), self.frame._root()
        self.session.destroy()
        for name in leaked:
            try:
                root.deletecommand(name)  # also forgets it in the root's cleanup list
            except tkinter.TclError:  # already gone
                continue


#: The Tcl command name in a script made by tkinter's ``bind``: ``if {"[<name> %# ...]" ...``.
_FUNCID = re.compile(r"\[(\S+) ")


def _wheel_commands(view: WindowView) -> list[str]:
    """The wheel callbacks of the view's ScrolledFrames (ttkbootstrap 2.2.3).

    ScrolledFrame binds them with ``bind_class``, which tkinter registers without cleanup, so
    their Tcl commands outlive ``destroy()`` and keep every rebuilt widget alive.
    """
    names: list[str] = []
    for inner in view.inner.values():
        tag = getattr(inner, "_wheel_tag", None)
        if isinstance(tag, str):
            for sequence in inner.bind_class(tag):
                names += _FUNCID.findall(inner.bind_class(tag, sequence))
    return names


#: Design-time size (px at 96 dpi) of an empty container.
_EMPTY_W, _EMPTY_H = 120, 64
#: Design-time append zone (px at 96 dpi) added to a non-empty container's right/bottom padding.
_ZONE = 20

#: ADR-010 Addenda 2-3: every design-only deviation from the runtime output (the last one is
#: a drawing of the overlay, not a geometry change).
DESIGN_AFFORDANCES = (
    "empty-minimum-size",
    "append-zone-padding",
    "paned-append-pane",
    "empty-container-outline",
)


def _padding(inner: Any) -> tuple[int, int, int, int]:  # noqa: ANN401 - a Tk widget
    """The ttk ``padding`` of ``inner`` as (left, top, right, bottom) pixels (1-4 values or '')."""
    px = [int(inner.winfo_pixels(v)) for v in inner.tk.splitlist(inner.cget("padding"))]
    if not px:
        px = [0]
    if len(px) == 1:
        return px[0], px[0], px[0], px[0]
    if len(px) == 2:
        return px[0], px[1], px[0], px[1]
    if len(px) == 3:
        return px[0], px[1], px[2], px[1]
    return px[0], px[1], px[2], px[3]


class CanvasEngine:
    """Builds :class:`WindowView` objects; a failing build raises (the caller shows a card)."""

    def __init__(self, registry: Registry, *, scale: Callable[[int], int] = lambda px: px) -> None:
        self.registry = registry
        self._scale = scale
        self._backend = TtkbootstrapBackend()

    def build(self, document: Document, window: Window, host: Any) -> WindowView:  # noqa: ANN401
        """Build ``window`` (ungridded) inside ``host`` and put it in design mode."""
        found: list[tuple[object, Any, Any]] = []
        titles: dict[int, str] = {}
        embed = Embed(
            host=host,
            on_node=lambda node, outer, inner: found.append((node, outer, inner)),
            on_title=lambda win, text: titles.__setitem__(id(win), text),
            placeholder=self._placeholder,
        )
        plan = design_plan(document, window, self.registry, log=_log_note)
        session = self._backend.build_embedded(plan, embed)
        try:
            frame = next(outer for node, outer, _inner in found if node is window)
            view = WindowView(window, session, frame, titles.get(id(window)))
            for node, outer, inner in found:
                view.outer[id(node)], view.inner[id(node)] = outer, inner
                view.nodes[id(node)] = node
            for node, _outer, inner in found:
                self._reachable(node, inner)
            _map_owners(view)  # after _reachable: a press on an append pane finds its owner
            apply_design_mode(frame)
        except BaseException:
            session.destroy()  # never leave a half-mapped frame behind the error card
            raise
        return view

    def _reachable(self, node: object, inner: Any) -> None:  # noqa: ANN401 - a Tk widget
        """Make every container reachable by the mouse (spec dnd-selection 5.4, DESIGN_AFFORDANCES).

        R-A: an empty layout/page container or window body gets a minimum size. R-B: a non-empty
        grid/pack container gets a trailing append zone as extra right/bottom padding. R-C: a
        non-empty PanedWindow (no padding option) gets it as a trailing empty pane. Design
        canvas only: the runtime and the parity tests never see it.
        """
        if not isinstance(node, Window | Widget):
            return
        spec = self.registry.get(node.class_name) if isinstance(node, Widget) else None
        pages = spec is not None and spec.children == "pages"
        if node.layout is None and not pages:
            return
        if pages and node.children and inner.winfo_class() == "TPanedwindow":
            self._append_pane(inner)
            return
        with contextlib.suppress(tkinter.TclError):  # not every container has these options
            if not node.children:
                inner.configure(width=self._scale(_EMPTY_W), height=self._scale(_EMPTY_H))
            elif not pages:
                left, top, right, bottom = _padding(inner)
                zone = self._scale(_ZONE)
                inner.configure(padding=(left, top, right + zone, bottom + zone))

    def _append_pane(self, paned: Any) -> None:  # noqa: ANN401 - a ttk Panedwindow
        """R-C: a trailing empty pane, ``_ZONE`` px along the orient axis; ``hit_test`` maps it
        to the append slot. ttk gives the slack to the last pane, so a real one keeps it.
        """
        panes = paned.panes()
        if panes and not any(int(paned.pane(pane, "weight")) for pane in panes):
            paned.pane(panes[-1], weight=1)  # where the runtime's slack goes (all weights 0)
        zone, across = self._scale(_ZONE), str(paned.cget("orient")) == "horizontal"
        spacer = ttk.Frame(paned, width=zone if across else 1, height=1 if across else zone)
        paned.add(spacer, weight=0)

    @staticmethod
    def pages(view: WindowView) -> dict[int, int]:
        """The shown page index of every rendered Notebook, by ``id(node)`` (kept on rebuild)."""
        shown: dict[int, int] = {}
        for key, inner in view.inner.items():
            node = view.nodes[key]
            if isinstance(node, Widget) and inner.winfo_class() == "TNotebook" and inner.tabs():
                shown[key] = int(inner.index("current"))
        return shown

    @staticmethod
    def restore_pages(view: WindowView, shown: dict[int, int]) -> None:
        """Show the Notebook pages recorded by :meth:`pages` again (where they still exist)."""
        for key, index in shown.items():
            inner: Any = view.inner.get(key)
            if inner is None or inner.winfo_class() != "TNotebook":
                continue
            if 0 <= index < len(inner.tabs()):
                inner.select(index)

    def snapshot(self, view: WindowView, stage: Any, scroll: Any = None) -> Snapshot:  # noqa: ANN401
        """The viewable geometry of ``view`` in ``stage`` coordinates (spec 5.1).

        ``scroll`` (the scroll host) bounds where a pointer may find a target.
        """
        stage.update_idletasks()
        rects: dict[int, Rect] = {}
        for key, node in view.nodes.items():
            if isinstance(node, Window | Widget | Include):
                rect = widget_rect(view.outer[key], stage)
                if rect is not None:
                    rects[key] = rect
        containers: list[ContainerBox] = []
        leaves: list[ChildBox] = []
        for key, rect in rects.items():
            node = view.nodes[key]
            kind, orient = self._kind(node, view.inner[key])
            if kind is None:
                leaves.append(ChildBox(node, rect, getattr(node, "placement", None)))
                continue
            inner_widget = view.inner[key]
            inner = widget_rect(inner_widget, stage) or rect
            kids = tuple(
                ChildBox(child, rects[id(child)], child.placement)
                for child in getattr(node, "children", ())
                if id(child) in rects
            )
            columns: tuple[int, ...] = ()
            rows: tuple[int, ...] = ()
            if kind == "grid":
                columns, rows = _grid_lines(inner_widget, stage)
            containers.append(
                ContainerBox(node, rect, inner, kind, orient, kids, _depth(node), columns, rows)
            )
        visible = None
        if scroll is not None:
            ox, oy = stage.winfo_rootx(), stage.winfo_rooty()
            visible = Rect(
                scroll.winfo_rootx() - ox,
                scroll.winfo_rooty() - oy,
                scroll.winfo_width(),
                scroll.winfo_height(),
            )
        return Snapshot(tuple(containers), tuple(leaves), visible)

    def _kind(self, node: object, inner: Any) -> tuple[Any, str]:  # noqa: ANN401 - a Tk widget
        """(grid | pack | pages | None, orient) of a rendered node."""
        if isinstance(node, Widget):
            spec = self.registry.get(node.class_name) or self.registry.get(node.fallback or "")
            if spec is not None and spec.children == "pages":
                is_notebook = inner.winfo_class() == "TNotebook"
                return "pages", "" if is_notebook else str(inner.cget("orient"))
        layout = getattr(node, "layout", None)
        if isinstance(node, Window | Widget) and layout is not None:
            return layout.type, layout.orient
        return None, ""

    def _placeholder(self, node: Include, parent: Any) -> Any:  # noqa: ANN401 - Tk widgets
        width, height = (self._scale(px) for px in _PLACEHOLDER_SIZE)
        text = _(_M_INCLUDED).format(component=node.component)
        return ttk.Labelframe(parent, text=text, width=width, height=height)


def _log_note(msgid: str, **params: object) -> None:
    """Runtime notes of a design build (clipping, fallbacks) go to the designer log."""
    _log.info("%s", format_message(msgid, params))


def _map_owners(view: WindowView) -> None:
    """Fill ``view.owner``: each widget maps to the nearest registered node above it."""
    registered: dict[str, object] = {}
    for key, node in view.nodes.items():
        registered[str(view.outer[key])] = node
        registered.setdefault(str(view.inner[key]), node)
    stack: list[tuple[Any, object]] = [(view.frame, view.window)]
    while stack:
        widget, node = stack.pop()
        node = registered.get(str(widget), node)
        view.owner[str(widget)] = node
        stack.extend((child, node) for child in widget.winfo_children())


def _depth(node: object) -> int:
    """0 for a window, 1 for its direct children, and so on."""
    depth, current = 0, node
    while isinstance(current, Widget | Include):
        depth, current = depth + 1, current.parent
    return depth


def _grid_lines(inner: Any, stage: Any) -> tuple[tuple[int, ...], tuple[int, ...]]:  # noqa: ANN401
    """Column and row boundaries of a grid master, in stage coordinates (from ``grid_bbox``)."""
    ox = inner.winfo_rootx() - stage.winfo_rootx()
    oy = inner.winfo_rooty() - stage.winfo_rooty()
    columns, rows = inner.grid_size()
    xs = [ox + int(inner.grid_bbox(c, 0)[0]) for c in range(columns)]
    ys = [oy + int(inner.grid_bbox(0, r)[1]) for r in range(rows)]
    if columns and rows:
        x, y, w, h = (int(v) for v in inner.grid_bbox(columns - 1, rows - 1))
        xs.append(ox + x + w)
        ys.append(oy + y + h)
    return tuple(xs), tuple(ys)


def widget_rect(widget: Any, stage: Any) -> Rect | None:  # noqa: ANN401 - Tk widgets
    """``widget``'s rectangle in ``stage`` coordinates, clipped by scrolling ancestors.

    None when it is not shown (unmanaged, or on an unselected Notebook page) or clipped out
    entirely. Visibility is decided structurally rather than with ``winfo_viewable``, so it
    also holds while the designer window is withdrawn or not yet mapped.
    """
    current = widget
    while current is not None and current is not stage:
        parent = current.master
        if not current.winfo_manager():
            return None
        on_page = parent is not None and parent.winfo_class() == "TNotebook"
        if on_page and str(parent.select()) != str(current):
            return None
        current = parent
    ox, oy = stage.winfo_rootx(), stage.winfo_rooty()

    def rect_of(w: Any) -> Rect:  # noqa: ANN401 - a Tk widget
        return Rect(w.winfo_rootx() - ox, w.winfo_rooty() - oy, w.winfo_width(), w.winfo_height())

    rect = rect_of(widget)
    current = widget.master
    while current is not None and current is not stage:
        if isinstance(current, tkinter.Canvas):  # a ScrolledFrame viewport
            rect = rect.intersection(rect_of(current))
        current = current.master
    return None if rect.empty else rect


def reveal(view: WindowView, node: object) -> None:
    """Select the rendered Notebook pages that hold ``node`` (chrome state, not the model)."""
    current: object | None = node
    while isinstance(current, Widget | Include):
        parent = current.parent
        if isinstance(parent, Widget) and parent.class_name == "Notebook":
            notebook, page = view.inner.get(id(parent)), view.outer.get(id(current))
            if notebook is not None and page is not None:
                try:
                    notebook.select(page)
                except tkinter.TclError:  # not a page of that notebook (a fallback widget)
                    _log.debug("Cannot reveal a Notebook page", exc_info=True)
        current = parent
