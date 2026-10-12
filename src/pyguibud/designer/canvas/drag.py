"""Drag-and-drop onto the canvas (spec dnd-selection 6, 8): palette inserts, moves and resizes.

``idle --press on a palette item / a canvas widget--> armed --motion > 4 px--> dragging
--release--> drop | cancel``. The pressed widget (the palette Treeview, or a design-mode canvas
widget) keeps the implicit pointer grab, so its motion and release events carry the root
coordinates; they are mapped onto the shown stage and hit-tested on a snapshot taken once
per drag. A target is checked with ``CommandStack.check`` after the pointer rested on it for
60 ms (cached per drag); the drop runs a fresh ``execute``. None of this runs inside a stack
listener, so calling the stack here is safe.

A resize starts on a handle of the primary grid child: the dragged edge snaps to the parent's
cell lines (shown as the snap guide, as during a drag over a grid) and gets the same checks.
A size drag (spec direct-manipulation 2.7, 3) starts on a size handle or a window handle: motion
only draws a ghost and the value in the status bar; the release runs one command.
A rubber band (D5) starts on a container's empty area and selects the container's direct
children that lie fully inside it.
"""

from __future__ import annotations

import contextlib
import logging
import tkinter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pyguibud.core.commands import Command
from pyguibud.core.model import GridCell, Include, Widget, Window
from pyguibud.designer import sizing
from pyguibud.designer.canvas.engine import widget_rect
from pyguibud.designer.editing import (
    Edge,
    NewNode,
    insert_command,
    move_command,
    new_node,
    refusal,
    resize_cell,
    resize_command,
    span_rect,
)
from pyguibud.designer.geometry import ContainerBox, Rect, Snapshot
from pyguibud.designer.targets import Moving, NewWidget, Target, hit_test, keyboard_target
from pyguibud.designer.theme_tk import scaled
from pyguibud.i18n import N_, _, ngettext

if TYPE_CHECKING:
    from pyguibud.designer.panels.canvas import CanvasPanel, _Stage

__all__ = ["DragController"]

_log = logging.getLogger(__name__)

# Translators: {widget} is a palette item ("Button"), {container} the id of a window or frame.
_M_RELEASE_INSERT = N_("Release to insert '{widget}' into '{container}'.")
# Translators: {id} is the element being moved, {container} the id of a window or frame.
_M_RELEASE_MOVE = N_("Release to move '{id}' into '{container}'.")
# Translators: {id} is the element being resized; {columns} and {rows} are cell counts.
_M_RELEASE_RESIZE = N_("Release to resize '{id}' to {columns} × {rows} cells.")  # noqa: RUF001 - the sign is meant
_M_RELEASE_CANCEL = N_("Release to cancel.")
_M_CANCELLED = N_("Drag cancelled.")
# Translators: {id} is the id of the element that was just added.
_M_INSERTED = N_("Inserted '{id}'.")
# Translators: {widget} is a palette item ("Button").
_M_HINT = N_(
    "Drag '{widget}' onto the canvas, or press Enter to insert it into the selected container."
)
_M_MENU_EDITOR = N_("Menus and actions are edited in the menu editor.")
_THRESHOLD = 4  # px at 96 dpi before a press becomes a drag
_REST_MS = 60  # the pointer rests this long on a target before it is checked
_PITCH = 16  # px at 96 dpi: where the one append line lies past a grid's last boundary
#: One axis of a size drag: (property or window field, unit, start, px per unit).
_SizeAxis = tuple[str, sizing.Unit, sizing.Start, float]


class DragController:
    """Drives one drag at a time (a palette insert or a canvas move) over the shown stage."""

    def __init__(
        self,
        canvas: CanvasPanel,
        *,
        status: Callable[[str], None],
        source: Any,  # noqa: ANN401 - the palette Treeview (holds the grab; shows the cursor)
    ) -> None:
        self.canvas = canvas
        self.session = canvas.session
        self._status = status
        self._source = source
        self.state: Literal["idle", "armed", "dragging", "resizing", "banding"] = "idle"
        self._start = (0, 0)
        self._payload: NewWidget | Moving | None = None
        self._cursor: Any = source  # the widget holding the grab shows the cursor
        self._pressed: object | None = None  # the canvas node a move press landed on
        self._label = ""
        self._node: NewNode | None = None
        self._stage: _Stage | None = None
        self._snapshot: Snapshot | None = None
        self._view: object | None = None  # the stage's WindowView the snapshot was taken of
        self._target: Target | None = None
        self._checked: dict[tuple[object, ...], tuple[bool, str]] = {}
        self._ok_cursor = "plus"  # the cursor over an accepted target
        # A resize: (the node, the dragged edge, its parent's box), and the area under the
        # pointer as (row, column, rowspan, columnspan) with its indicator rectangle.
        self._resize: tuple[Widget | Include, Edge, ContainerBox] | None = None
        self._area: tuple[tuple[int, int, int, int], Rect] | None = None
        self._timer: str | None = None
        # A size drag: (node, edge, press point, start rect in stage coordinates, its two axes),
        # the values a release would write now, which axes moved, and a window's natural size.
        self._size: tuple[object, Edge, tuple[int, int], Rect, tuple[_SizeAxis | None, ...]] | None
        self._values: tuple[int | None, int | None]
        self._size, self._values, self._natural = None, (None, None), (0, 0)
        self._moved = (False, False)
        # A rubber band: (its container, the selection it adds to) and the action of a press
        # released without a drag (a Ctrl+click on a container toggles it).
        self._band: tuple[object, tuple[object, ...]] | None = None
        self._click: Callable[[], None] | None = None
        # A new document or any stack change (an undo mid-drag) makes the snapshot stale. Safe in
        # a stack listener: cancelling never calls the stack. Hover checks emit no event. A
        # re-render (new document, language switch) destroys the held stage: the canvas warns
        # first, because its own document_changed slot runs before ours (QA-13a-01).
        self._disconnects = [
            canvas.stages_closing.connect(lambda _c: self.cancel()),
            self.session.document_changed.connect(lambda _s: self.cancel()),
            self.session.report_changed.connect(lambda _r: self.cancel()),
        ]

    # ------------------------------------------------------------ gestures
    def press(self, spec_name: str, x_root: int, y_root: int) -> None:
        """A press on a palette widget item arms a drag; never during a resize (Q12)."""
        if self.state == "resizing":  # QA-14b1-11: the size or span drag keeps running
            return
        self._end()
        if self.session.registry.get(spec_name) is not None:
            self.state, self._start = "armed", (x_root, y_root)
            self._payload = NewWidget(spec_name)

    def press_move(
        self,
        nodes: tuple[object, ...],
        pressed: object,
        x_root: int,
        y_root: int,
        widget: Any,  # noqa: ANN401 - the pressed canvas widget (holds the grab)
    ) -> None:
        """A press on a selected canvas widget arms a move of ``nodes`` (spec 8)."""
        self._end()
        if any(pressed is n for n in nodes):
            self.state, self._start = "armed", (x_root, y_root)
            self._payload, self._pressed, self._cursor = Moving(nodes), pressed, widget

    def press_resize(
        self,
        node: object,
        edge: Edge,
        x_root: int,
        y_root: int,
        handle: Any,  # noqa: ANN401 - the pressed handle (holds the grab; shows the cursor)
    ) -> None:
        """A press on a resize handle of ``node``, a grid child, starts a resize (spec 8)."""
        self._end()
        stage = self.canvas.current_stage()
        if stage is None or stage.view is None or not isinstance(node, Widget | Include):
            return
        if not isinstance(node.placement, GridCell):
            return
        snapshot = self.canvas.engine.snapshot(stage.view, stage.stage, stage.scroll)
        box = next((c for c in snapshot.containers if c.node is node.parent), None)
        if box is None or box.kind != "grid":
            return
        self.state, self._resize, self._stage, self._snapshot = (
            "resizing",
            (node, edge, box),
            stage,
            snapshot,
        )
        self._cursor, self._ok_cursor = handle, str(handle.cget("cursor"))
        stage.overlay.show_grid(box)
        self._resize_hover(x_root, y_root)

    def press_size(
        self,
        node: object,
        edge: Edge,
        x_root: int,
        y_root: int,
        handle: Any,  # noqa: ANN401 - the pressed handle (holds the grab; shows the cursor)
    ) -> None:
        """A press on a size handle of ``node`` or of a window: measure and freeze the start."""
        self._end()
        stage, canvas = self.canvas.current_stage(), self.canvas
        if stage is None or stage.view is None or self.session.stack is None:
            return
        on = (any(c in "ew" for c in edge), any(c in "ns" for c in edge))
        axes: tuple[_SizeAxis | None, ...]
        if isinstance(node, Window):
            box = canvas.window_box(stage)
            if box is None:
                return
            rect, self._natural = box
            starts = (rect.w, rect.h)
            axes = tuple(
                (name, "px", sizing.Start(starts[k], True), 1.0) if on[k] else None
                for k, name in enumerate(sizing.WINDOW_FIELDS)
            )
        else:
            outer = stage.view.outer.get(id(node))
            found = widget_rect(outer, stage.stage) if outer is not None else None
            if found is None:
                return
            rect, spec = found, self.session.registry.get(getattr(node, "class_name", ""))
            metrics, shown = canvas.engine.metrics(stage.view, node), (rect.w, rect.h)
            built: list[_SizeAxis | None] = []
            for k, (axis, _why) in enumerate(sizing.sized_axes(node, spec)):
                pitch = metrics[k] if axis is not None and axis[1] != "px" else 1.0
                start = sizing.start_value(node, axis[0], shown[k], pitch) if axis else None
                built.append((axis[0], axis[1], start, pitch) if axis and start and on[k] else None)
            axes = tuple(built)
        if not any(axes):
            return
        self.session.stack.break_merge()  # one gesture = one undo step
        self.state, self._stage = "resizing", stage
        self._size = (node, edge, (x_root, y_root), rect, axes)
        self._cursor, self._ok_cursor = handle, str(handle.cget("cursor"))

    def reset_size(self, node: object, edge: Edge) -> None:
        """A double-click on a size handle: back to the natural size (``Reset width``, T1)."""
        if isinstance(node, Window):
            fields = [f for f, c in zip(sizing.WINDOW_FIELDS, "es", strict=True) if c in edge]
            built = sizing.window_size_command(node, dict.fromkeys(fields))
        else:
            spec = self.session.registry.get(getattr(node, "class_name", ""))
            built = sizing.reset_size_command(node, spec, edge)
        if built is not None:
            self._execute(built)

    def press_band(
        self,
        container: object,
        base: tuple[object, ...],
        click: Callable[[], None] | None,
        x_root: int,
        y_root: int,
    ) -> None:
        """A press on ``container``'s empty area arms a rubber band that adds to ``base``."""
        self._end()
        self.state, self._start = "armed", (x_root, y_root)
        self._band, self._click = (container, base), click

    @property
    def moving(self) -> bool:
        """True while a canvas move or rubber band is armed or dragging, or a resize runs."""
        return isinstance(self._payload, Moving) or self.state == "resizing" or bool(self._band)

    def motion(self, x_root: int, y_root: int, *, fine: bool = False) -> None:
        """``fine`` (Shift held) gives a pixel size drag 1 px steps instead of 4 px."""
        if self.state == "resizing" and self._size is not None:
            self._size_hover(x_root, y_root, fine=fine)
        elif self.state == "resizing":
            self._resize_hover(x_root, y_root)
        if self.state == "banding":
            self._band_rect(x_root, y_root)
        if self.state == "armed" and self._payload is None and self._band is not None:
            self._start_band(x_root, y_root)
        if self.state == "armed" and self._payload is not None:
            dx, dy = x_root - self._start[0], y_root - self._start[1]
            if max(abs(dx), abs(dy)) <= scaled(self._source, _THRESHOLD):
                return
            if isinstance(self._payload, Moving):
                # The grabbed member becomes the anchor, so it is what follows the pointer.
                pressed = self._pressed
                nodes = (*(n for n in self._payload.nodes if n is not pressed), pressed)
                self._payload, self._label = Moving(nodes), str(getattr(pressed, "id", ""))
                self.session.select_many(nodes, origin="canvas")
            else:
                spec = self.session.registry.require(self._payload.spec_name)
                self._payload, self._label = NewWidget.of(spec), spec.label()
                menu = self._payload.role == "menu"
                self._node = None if menu else new_node(spec, self.session.document)
            self.state = "dragging"
        if self.state == "dragging":
            self._hover(x_root, y_root)

    def release(self, x_root: int, y_root: int, *, fine: bool = False) -> None:
        """Drop on the current target (a fresh, validated execute), else cancel."""
        if self.state == "resizing" and self._size is not None:
            self._size_release(x_root, y_root, fine=fine)
            return
        if self._band is not None:
            picked = self._band_pick(x_root, y_root) if self.state == "banding" else None
            click = self._click if self.state == "armed" else None
            self._end()
            if picked:
                self.session.select_many(picked, origin="canvas")
            elif click is not None:
                click()
            return
        if self.state == "resizing" and self._resize is not None:
            self._resize_hover(x_root, y_root)
            resized, area = self._resize[0], self._area
            self._end()
            if area is not None and area[0] != _area_of(resized):  # a no-op is never recorded
                self._execute(resize_command(resized, *area[0]))
            return
        if self.state != "dragging":
            pressed = self._pressed if self.state == "armed" else None
            self._end()
            if pressed is not None:  # a plain click on a member selects just that one
                self.session.select(pressed, origin="canvas")
            return
        self._hover(x_root, y_root)
        target, node, payload = self._target, self._node, self._payload
        self._end()
        if isinstance(payload, Moving) and target is not None:
            self.move(target, payload.nodes)
        elif target is None or node is None:
            menu = isinstance(payload, NewWidget) and payload.role == "menu"
            self._status(_(_M_MENU_EDITOR if menu else _M_CANCELLED))
        else:
            self.insert(target, node, label=self._label)

    def move(self, target: Target, nodes: tuple[object, ...]) -> bool:
        """Move ``nodes`` to ``target`` as one undo step; they stay selected."""
        if not self._execute(move_command(nodes, target)):
            return False
        self.session.select_many(nodes, origin="canvas")
        return True

    def _execute(self, built: Command | str) -> bool:
        """Run ``built`` as one undo step; a refusal shows its reason in the status bar."""
        stack = self.session.stack
        if stack is None or isinstance(built, str):
            self._status(built if isinstance(built, str) else "")
            return False
        stack.break_merge()  # one gesture = one undo step
        outcome = stack.execute(built)
        self._status("" if outcome.accepted else outcome.message)
        return outcome.accepted

    def insert(self, target: Target, node: NewNode, *, label: str) -> bool:
        """Insert ``node`` at ``target`` as one undo step, select it and report in the status bar.

        Shared by the drop and keyboard insertion (palette Enter / double-click).
        """
        stack = self.session.stack
        reason = refusal(target, node)
        if stack is None or reason is not None:
            self._status(reason or "")
            return False
        stack.break_merge()  # one gesture = one undo step
        outcome = stack.execute(insert_command(target, node))
        if not outcome.accepted:
            self._status(outcome.message)
            return False
        bar = {"statusbar": "statusbar", "menubar": "menubar"}.get(type(node).__name__.lower())
        # A bar is attached as a copy: select the window's own one, never the given object.
        selected = node if bar is None else getattr(target.container, bar)
        self.session.select(selected, origin="canvas")
        self._status(_(_M_INSERTED).format(id=getattr(selected, "id", "") or label))
        return True

    def insert_widget(self, spec_name: str) -> None:
        """Palette Enter or double-click: insert into the selected container (spec 9)."""
        stage, spec = self.canvas.current_stage(), self.session.registry.get(spec_name)
        if stage is None or spec is None or self.session.document is None:
            return
        registry = self.session.registry
        payload = NewWidget.of(spec)
        target = keyboard_target(stage.window, self.session.selection.node, payload, registry)
        if target is None:
            self._status(_(_M_MENU_EDITOR))
            return
        self.insert(target, new_node(spec, self.session.document), label=spec.label())

    def hint(self, spec_name: str) -> None:
        """The status-bar hint of a palette item that was just picked (QA-12-13)."""
        spec = self.session.registry.get(spec_name)
        if spec is not None:
            menu = NewWidget.of(spec).role == "menu"
            self._status(_(_M_MENU_EDITOR) if menu else _(_M_HINT).format(widget=spec.label()))

    def cancel(self) -> None:
        """Esc, focus loss or a new document: drop the drag; nothing changes."""
        dragging = self.state in ("dragging", "resizing", "banding")
        self._end()
        if dragging:
            self._status(_(_M_CANCELLED))

    def dispose(self) -> None:
        self._end()
        for disconnect in self._disconnects:
            disconnect()

    # ------------------------------------------------------------ rubber band
    def _start_band(self, x_root: int, y_root: int) -> None:
        dx, dy = x_root - self._start[0], y_root - self._start[1]
        if max(abs(dx), abs(dy)) > scaled(self._source, _THRESHOLD):
            self.state, self._stage = "banding", self.canvas.current_stage()
            self._band_rect(x_root, y_root)

    def _band_rect(self, x_root: int, y_root: int) -> Rect | None:
        """Draw the band from the press to the pointer; returns it in stage coordinates."""
        stage = self._stage
        if stage is None:
            return None
        left, top = stage.stage.winfo_rootx(), stage.stage.winfo_rooty()
        (x0, y0), x1, y1 = self._start, x_root, y_root
        rect = Rect(min(x0, x1) - left, min(y0, y1) - top, abs(x1 - x0), abs(y1 - y0))
        stage.overlay.show_band(rect)
        return rect

    def _band_pick(self, x_root: int, y_root: int) -> list[object]:
        """The selection after the band: its base plus the children fully inside."""
        band, stage = self._band_rect(x_root, y_root), self._stage
        if band is None or stage is None or stage.view is None or self._band is None:
            return []
        container, base = self._band
        snapshot = self.canvas.engine.snapshot(stage.view, stage.stage, stage.scroll)
        box = next((c for c in snapshot.containers if c.node is container), None)
        inside = [c.node for c in box.children if band.covers(c.rect)] if box else []
        return [*base, *inside] if inside else []

    # ------------------------------------------------------------ hover
    def _hover(self, x_root: int, y_root: int) -> None:
        stage = self.canvas.current_stage()
        # A rebuild keeps the stage but swaps its view (an include changed on disk, focus-in):
        # the snapshot's geometry is stale, so the targets are resolved again (QA-14b2-15).
        if stage is not self._stage or (stage is not None and stage.view is not self._view):
            self._show(None)
            self._stage, self._snapshot = stage, None
            self._checked.clear()
        if stage is None or stage.view is None or self._payload is None:
            self._show(None)
            return
        menu = isinstance(self._payload, NewWidget) and self._payload.role == "menu"
        if self._snapshot is None:
            self._snapshot = self.canvas.engine.snapshot(stage.view, stage.stage, stage.scroll)
            self._view = stage.view
        x, y = x_root - stage.stage.winfo_rootx(), y_root - stage.stage.winfo_rooty()
        px = scaled(self._source, 1)
        target = hit_test(self._snapshot, x, y, self._payload, band=6 * px, bar=3 * px)
        if target is None:
            self._show(None)
            self._status(_(_M_MENU_EDITOR if menu else _M_RELEASE_CANCEL))
            return
        if self._target is not None and target.key == self._target.key:
            return
        self._show(target)
        grid = target.kind == "grid"
        boxes = self._snapshot.containers if grid else ()
        stage.overlay.show_grid(next((b for b in boxes if b.node is target.container), None))
        self._pend(target.key, target.rect, target.bar)

    def _size_hover(self, x_root: int, y_root: int, *, fine: bool) -> None:
        """Values, ghost and status text of a size drag: no command and no check (spec 2.7)."""
        if self._size is None or self._stage is None:
            return
        node, edge, press, rect, axes = self._size
        window = isinstance(node, Window)
        values: list[int | None] = [None, None]
        grow, moved = [0, 0], [False, False]
        for k, axis in enumerate(axes):
            if axis is None:
                continue
            _name, unit, start, pitch = axis
            # A widget has no position: its left/top handle grows it to the left/top.
            delta = ((x_root, y_root)[k] - press[k]) * (-1 if "wn"[k] in edge else 1)
            moved[k] = abs(delta) >= (1 if fine else sizing.PIXEL_SNAP / 2)  # QA-14b1-09
            if window and not moved[k]:  # at the press: no change
                values[k] = getattr(node, _name)
            elif window:
                value = values[k] = sizing.window_value(
                    start.value + delta, self._natural[k], fine=fine
                )
                grow[k] = max(value or 0, self._natural[k]) - start.value
            else:
                value = values[k] = sizing.drag_value(start, delta, pitch, unit, fine=fine)
                grow[k] = round(((value or start.value) - start.value) * pitch)
        self._values, self._moved = (values[0], values[1]), (moved[0], moved[1])
        x = rect.x - (grow[0] if "w" in edge else 0)
        y = rect.y - (grow[1] if "n" in edge else 0)
        self._stage.overlay.show_band(
            Rect(x, y, max(1, rect.w + grow[0]), max(1, rect.h + grow[1]))
        )
        ident = str(getattr(node, "id", ""))
        if window:  # QA-14b1-03: only a moved axis can be "cleared"
            self._status(sizing.window_release_text(ident, self._values, self._moved))
            return
        units = [
            (a[1], v) if a and v is not None else None for a, v in zip(axes, values, strict=True)
        ]
        outside = not self._inside(node, x_root, y_root)  # QA-14b1-01: a release cancels there
        self._status(sizing.release_text(ident, units, outside=outside))

    def _inside(self, node: object, x_root: int, y_root: int) -> bool:
        """On the canvas tab; a window drag may go past it (a window larger than the shown area
        grows beyond it)."""
        assert self._stage is not None
        page = self._stage.page
        return isinstance(node, Window) or Rect(page.winfo_rootx(), page.winfo_rooty(),
                      page.winfo_width(), page.winfo_height()).contains(x_root, y_root)  # fmt: skip

    def _size_release(self, x_root: int, y_root: int, *, fine: bool) -> None:
        """One ``Resize`` step; a release off the stage cancels; no change records nothing."""
        assert self._size is not None and self._stage is not None
        node, axes = self._size[0], self._size[4]
        inside = self._inside(node, x_root, y_root)
        self._size_hover(x_root, y_root, fine=fine)
        values, moved, ident = self._values, self._moved, str(getattr(node, "id", ""))
        self._end()
        if not inside:
            self._status(_(_M_CANCELLED))
            return
        pairs = [(a[0], v) for a, v in zip(axes, values, strict=True) if a is not None]
        if isinstance(node, Window):
            built = sizing.window_size_command(node, dict(pairs))
        else:
            built = sizing.size_command(node, [(n, v) for n, v in pairs if v is not None])
            if built is None and not any(values):
                self._status(_(sizing.M_NATURAL).format(id=ident))
                return
        if built is not None and self._execute(built):
            text = _(sizing.M_RESIZED).format(id=ident)
            if isinstance(node, Window):  # D5: say which minimum was cleared; D4: the note
                if any(on and v is None for on, v in zip(moved, values, strict=True)):
                    text = sizing.window_release_text(ident, values, moved)
                text += f" {_(sizing.M_COMPONENT)}" if node.kind == "component" else ""
            self._status(text)

    def _resize_hover(self, x_root: int, y_root: int) -> None:
        """Snap the dragged edge to the pointer; check the new area after a rest."""
        if self._resize is None or self._stage is None:
            return
        node, edge, box = self._resize
        stage, pitch = self._stage.stage, scaled(self._source, _PITCH)
        x, y = x_root - stage.winfo_rootx(), y_root - stage.winfo_rooty()
        assert isinstance(node.placement, GridCell)  # checked by press_resize
        area = resize_cell(node.placement, edge, box.columns, box.rows, x, y, pitch=pitch)
        if self._area is not None and area == self._area[0]:
            return
        self._area = area, span_rect(box.columns, box.rows, area, pitch=pitch)
        self._cancel_timer()
        if area == _area_of(node):  # back where it started: nothing to check
            self._stage.overlay.show_target(self._area[1], "pending")
            self._set_cursor(self._ok_cursor)
            self._status(_(_M_RELEASE_CANCEL))
            return
        self._pend(area, self._area[1], False)

    def _pend(self, key: tuple[object, ...], rect: Rect, bar: bool) -> None:
        """Draw a cached result for ``key``, or a neutral indicator and check after a rest."""
        cached = self._checked.get(key)
        if cached is not None:
            self._draw(rect, bar, *cached)
        elif self._stage is not None:
            self._stage.overlay.show_target(rect, "pending", bar=bar)
            self._set_cursor(self._ok_cursor)
            self._timer = self._source.after(_REST_MS, self._check)

    def _show(self, target: Target | None) -> None:
        """Make ``target`` current: cancel a pending check; None also clears the indicator."""
        self._target = target
        self._cancel_timer()
        if target is None:
            self._set_cursor("")
            if self._stage is not None:
                self._stage.overlay.show_target(None, "pending")
                self._stage.overlay.show_grid(None)

    def _check(self) -> None:
        self._timer = None
        pending, stack = self._pending(), self.session.stack
        if pending is None or stack is None:
            return
        key, built, text, rect, bar = pending
        if isinstance(built, Command):
            outcome = stack.check(built)
            if outcome.accepted and outcome.findings:
                text = f"{text} {outcome.message}"
            result = (outcome.accepted, text if outcome.accepted else outcome.message)
        else:
            result = (False, built)
        self._checked[key] = result
        self._draw(rect, bar, *result)

    def _pending(self) -> tuple[tuple[object, ...], Command | str, str, Rect, bool] | None:
        """(cache key, command, release text, indicator, bar) of what a release would do."""
        if self.state == "resizing" and self._resize is not None and self._area is not None:
            node, (area, rect) = self._resize[0], self._area
            text = _(_M_RELEASE_RESIZE).format(id=node.id, columns=area[3], rows=area[2])
            return area, resize_command(node, *area), text, rect, False
        target = self._target
        if self.state != "dragging" or target is None:
            return None
        built = self._command(target)
        return target.key, built, self._release_text(target), target.rect, target.bar

    def _draw(self, rect: Rect, bar: bool, accepted: bool, message: str) -> None:
        if self._stage is not None:
            state: Literal["allowed", "denied"] = "allowed" if accepted else "denied"
            self._stage.overlay.show_target(rect, state, bar=bar)
        self._set_cursor(self._ok_cursor if accepted else "X_cursor")
        self._status(message)

    def _command(self, target: Target) -> Command | str:
        """The command a drop on ``target`` would execute, or why there is none."""
        if isinstance(self._payload, Moving):
            return move_command(self._payload.nodes, target)
        if self._node is None:
            return _(_M_MENU_EDITOR)
        reason = refusal(target, self._node)
        return insert_command(target, self._node) if reason is None else reason

    def _release_text(self, target: Target) -> str:
        container = getattr(target.container, "id", "")
        if not isinstance(self._payload, Moving):
            return _(_M_RELEASE_INSERT).format(widget=self._label, container=container)
        count = len(self._payload.nodes)
        if count == 1:
            return _(_M_RELEASE_MOVE).format(id=self._label, container=container)
        return ngettext(
            "Release to move {count} element.", "Release to move {count} elements.", count
        ).format(count=count)

    def _set_cursor(self, cursor: str) -> None:
        with contextlib.suppress(tkinter.TclError):  # a canvas widget may be gone already
            self._cursor.configure(cursor=cursor)

    # ------------------------------------------------------------ helpers
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            try:
                self._source.after_cancel(self._timer)
            except tkinter.TclError:
                _log.debug("after_cancel failed", exc_info=True)
            self._timer = None

    def _end(self) -> None:
        """Back to idle: no timer, no indicator, no cached state.

        The state is reset even when clearing the indicator fails, so one error never leaves
        the controller stuck in "dragging" (every later gesture would fail on it).
        """
        try:
            if self.state in ("dragging", "resizing"):
                self._show(None)
            if self.state == "banding" and self._stage is not None:
                self._stage.overlay.show_band(None)
            if self.state == "resizing":
                self._set_cursor(self._ok_cursor)  # the handle's own resize cursor
            if self._size is not None and self._stage is not None:
                self._stage.overlay.show_band(None)  # the ghost
            self._cancel_timer()
        finally:
            self.state, self._payload, self._node = "idle", None, None
            self._cursor, self._pressed, self._ok_cursor = self._source, None, "plus"
            self._resize, self._area, self._band, self._click = None, None, None, None
            self._size, self._values = None, (None, None)
            self._stage, self._snapshot, self._target, self._view = None, None, None, None
            self._checked.clear()


def _area_of(node: Widget | Include) -> tuple[int, int, int, int]:
    """(row, column, rowspan, columnspan) of a grid child."""
    cell = node.placement
    assert isinstance(cell, GridCell)
    return cell.row, cell.column, max(cell.rowspan, 1), max(cell.columnspan, 1)
