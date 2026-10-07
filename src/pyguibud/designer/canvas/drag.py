"""Palette -> canvas drag-and-drop (spec dnd-selection 6; Step 13a: insertion only).

``idle --press on a widget item--> armed --motion > 4 px--> dragging --release--> drop | cancel``.
The palette Treeview keeps the implicit pointer grab, so its motion and release events carry the
root coordinates; they are mapped onto the shown stage and hit-tested on a snapshot taken once
per drag. A target is checked with ``CommandStack.check`` after the pointer rested on it for
60 ms (cached per drag); the drop runs a fresh ``execute``. None of this runs inside a stack
listener, so calling the stack here is safe.
"""

from __future__ import annotations

import logging
import tkinter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

from pyguibud.designer.editing import NewNode, insert_command, new_node, refusal
from pyguibud.designer.geometry import Snapshot
from pyguibud.designer.targets import NewWidget, Target, hit_test, keyboard_target
from pyguibud.designer.theme_tk import scaled
from pyguibud.i18n import N_, _

if TYPE_CHECKING:
    from pyguibud.designer.panels.canvas import CanvasPanel, _Stage

__all__ = ["DragController"]

_log = logging.getLogger(__name__)

# Translators: {widget} is a palette item ("Button"), {container} the id of a window or frame.
_M_RELEASE_INSERT = N_("Release to insert '{widget}' into '{container}'.")
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


class DragController:
    """Drives one palette drag at a time over the canvas panel's shown stage."""

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
        self.state: Literal["idle", "armed", "dragging"] = "idle"
        self._start = (0, 0)
        self._payload: NewWidget | None = None
        self._label = ""
        self._node: NewNode | None = None
        self._stage: _Stage | None = None
        self._snapshot: Snapshot | None = None
        self._target: Target | None = None
        self._checked: dict[tuple[int, str, int, int, int], tuple[bool, str]] = {}
        self._timer: str | None = None
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
        """A press on a palette widget item arms a drag."""
        self._end()
        if self.session.registry.get(spec_name) is not None:
            self.state, self._start = "armed", (x_root, y_root)
            self._payload = NewWidget(spec_name)

    def motion(self, x_root: int, y_root: int) -> None:
        if self.state == "armed" and self._payload is not None:
            dx, dy = x_root - self._start[0], y_root - self._start[1]
            if max(abs(dx), abs(dy)) <= scaled(self._source, _THRESHOLD):
                return
            spec = self.session.registry.require(self._payload.spec_name)
            self._payload, self._label = NewWidget.of(spec), spec.label()
            self._node = (
                None if self._payload.role == "menu" else new_node(spec, self.session.document)
            )
            self.state = "dragging"
        if self.state == "dragging":
            self._hover(x_root, y_root)

    def release(self, x_root: int, y_root: int) -> None:
        """Drop on the current target (a fresh, validated execute), else cancel."""
        if self.state != "dragging":
            self._end()
            return
        self._hover(x_root, y_root)
        target, node = self._target, self._node
        menu = self._payload is not None and self._payload.role == "menu"
        self._end()
        if target is None or node is None:
            self._status(_(_M_MENU_EDITOR if menu else _M_CANCELLED))
            return
        self.insert(target, node, label=self._label)

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
        dragging = self.state == "dragging"
        self._end()
        if dragging:
            self._status(_(_M_CANCELLED))

    def dispose(self) -> None:
        self._end()
        for disconnect in self._disconnects:
            disconnect()

    # ------------------------------------------------------------ hover
    def _hover(self, x_root: int, y_root: int) -> None:
        stage = self.canvas.current_stage()
        if stage is not self._stage:
            self._show(None)
            self._stage, self._snapshot = stage, None
        if stage is None or stage.view is None or self._payload is None:
            self._show(None)
            return
        if self._snapshot is None:
            self._snapshot = self.canvas.engine.snapshot(stage.view, stage.stage, stage.scroll)
        x, y = x_root - stage.stage.winfo_rootx(), y_root - stage.stage.winfo_rooty()
        px = scaled(self._source, 1)
        target = hit_test(self._snapshot, x, y, self._payload, band=6 * px, bar=3 * px)
        if target is None:
            self._show(None)
            menu = self._payload.role == "menu"
            self._status(_(_M_MENU_EDITOR if menu else _M_RELEASE_CANCEL))
            return
        if self._target is not None and target.key == self._target.key:
            return
        self._show(target)
        cached = self._checked.get(target.key)
        if cached is not None:
            self._draw(target, *cached)
        else:
            stage.overlay.show_target(target.rect, "pending", bar=target.bar)
            self._source.configure(cursor="plus")
            self._timer = self._source.after(_REST_MS, self._check)

    def _show(self, target: Target | None) -> None:
        """Make ``target`` current: cancel a pending check; None also clears the indicator."""
        self._target = target
        self._cancel_timer()
        if target is None:
            self._source.configure(cursor="")
            if self._stage is not None:
                self._stage.overlay.show_target(None, "pending")

    def _check(self) -> None:
        self._timer = None
        target, node, stack = self._target, self._node, self.session.stack
        if self.state != "dragging" or target is None or node is None or stack is None:
            return
        reason = refusal(target, node)
        if reason is None:
            outcome = stack.check(insert_command(target, node))
            container = getattr(target.container, "id", "")
            text = _(_M_RELEASE_INSERT).format(widget=self._label, container=container)
            if outcome.accepted and outcome.findings:
                text = f"{text} {outcome.message}"
            result = (outcome.accepted, text if outcome.accepted else outcome.message)
        else:
            result = (False, reason)
        self._checked[target.key] = result
        self._draw(target, *result)

    def _draw(self, target: Target, accepted: bool, message: str) -> None:
        if self._stage is not None:
            state: Literal["allowed", "denied"] = "allowed" if accepted else "denied"
            self._stage.overlay.show_target(target.rect, state, bar=target.bar)
        self._source.configure(cursor="plus" if accepted else "X_cursor")
        self._status(message)

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
            if self.state == "dragging":
                self._show(None)
            self._cancel_timer()
        finally:
            self.state, self._payload, self._node = "idle", None, None
            self._stage, self._snapshot, self._target = None, None, None
            self._checked.clear()
