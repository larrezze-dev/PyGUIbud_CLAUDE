"""Canvas drag-move, multi-selection outlines and spec 5.4 acceptance 7 (dnd-selection 7.1, 8)."""

from __future__ import annotations

import itertools
from dataclasses import replace
from typing import Any

import pytest

from pyguibud.core.model import GridCell, Layout, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.targets import Moving, NewWidget, hit_test
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _snapshot_box,
    _window,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui
_CLOCK = itertools.count(1_000_000, 1000)  # far apart: never a double click


def _two_labels(app: DesignerApp, root: Any) -> tuple[Any, Widget, Widget]:  # noqa: F811
    """``main_window`` with two Labels in the body grid, at (0, 0) and (1, 0)."""
    app.session.new_from_template("main_window")
    _settle(root)
    window = _window(app)
    assert _keyboard_insert(app, root, window, "Label")
    assert _keyboard_insert(app, root, window, "Label")
    first, second = window.children[-2], window.children[-1]
    assert isinstance(first, Widget) and isinstance(second, Widget)
    assert first.placement == GridCell(row=0, column=0)
    assert second.placement == GridCell(row=1, column=0)
    return window, first, second


def _outer(app: DesignerApp, node: object) -> Any:  # noqa: F811
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    return stage.view.outer[id(node)]


def _drag(app: DesignerApp, root: Any, node: object, to: tuple[int, int], drop: bool = True) -> Any:  # noqa: F811
    """Press on ``node``'s canvas widget, move past the threshold, then to ``to``."""
    widget = _outer(app, node)
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    widget.event_generate("<ButtonPress-1>", x=3, y=3, rootx=sx, rooty=sy, time=next(_CLOCK))
    widget.event_generate("<B1-Motion>", x=13, y=3, rootx=sx + 10, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
    if drop:
        widget.event_generate(
            "<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100, time=next(_CLOCK)
        )
        _settle(root)
    return widget


def _root_point(app: DesignerApp, x: int, y: int) -> tuple[int, int]:  # noqa: F811
    stage = app.shell.canvas.stages[0]
    return stage.stage.winfo_rootx() + x, stage.stage.winfo_rooty() + y


def _append_row(app: DesignerApp, window: object) -> tuple[int, int]:  # noqa: F811
    """A root point in the body's append row, column 0 (the append column is off-view)."""
    _snapshot, box = _snapshot_box(app, window)
    return _root_point(app, box.columns[0] + 4, box.rows[-1] + 4)


def test_dragging_a_widget_to_the_append_row_moves_it_in_one_undo_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, _first, second = _two_labels(app, designer_root)
    session = app.session
    assert session.stack is not None
    before = session.stack.index
    _drag(app, designer_root, second, _append_row(app, window))
    assert second.placement == GridCell(row=2, column=0)
    assert session.stack.index == before + 1 and session.stack.undo_text == "Move element"
    assert session.selection.node is second and session.selection.origin == "canvas"
    session.stack.undo()
    assert second.placement == GridCell(row=1, column=0)
    assert tk_errors == []


def test_a_drag_into_a_frame_reparents_and_a_click_does_not_move(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, _second = _two_labels(app, designer_root)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    assert isinstance(frame, Widget) and frame.layout is not None
    session = app.session
    assert session.stack is not None
    inner = app.shell.canvas.stages[0].view.inner[id(frame)]  # type: ignore[union-attr]
    centre = (inner.winfo_rootx() + 30, inner.winfo_rooty() + 20)
    before = session.stack.index
    _drag(app, designer_root, first, centre)
    assert first.parent is frame and first.placement == GridCell(row=0, column=0)
    assert session.stack.index == before + 1
    # A press and release without motion selects, and never records a move.
    widget = _outer(app, first)
    point = (widget.winfo_rootx() + 2, widget.winfo_rooty() + 2)
    widget.event_generate("<ButtonPress-1>", x=2, y=2, rootx=point[0], rooty=point[1])
    widget.event_generate("<ButtonRelease-1>", x=2, y=2, rootx=point[0], rooty=point[1])
    _settle(designer_root)
    assert session.stack.index == before + 1 and session.selection.node is first
    assert tk_errors == []


def test_dropping_on_the_current_place_is_a_denied_no_op(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _window_node, first, _second = _two_labels(app, designer_root)
    session = app.session
    assert session.stack is not None
    widget = _outer(app, first)
    before = session.stack.index
    _drag(app, designer_root, first, (widget.winfo_rootx() + 5, widget.winfo_rooty() + 5))
    assert session.stack.index == before and first.placement == GridCell(row=0, column=0)
    assert app.shell._message == f"'{first.id}' is already there."
    assert tk_errors == []


def test_escape_or_focus_loss_cancels_a_canvas_move(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, _first, second = _two_labels(app, designer_root)
    to = _append_row(app, window)
    widget = _drag(app, designer_root, second, to, drop=False)
    drag: Any = app.shell.drag
    assert drag.state == "dragging" and drag.moving
    proxy = app.shell.canvas.focus_widget
    # A withdrawn root never has the keyboard focus: Esc and a focus loss share the handler.
    assert "<Key-Escape>" in proxy.bind()
    proxy.event_generate("<FocusOut>")
    assert drag.state == "idle"
    widget.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1])
    _settle(designer_root)
    assert second.placement == GridCell(row=1, column=0)
    assert app.shell._message == "Drag cancelled."
    assert tk_errors == []


def test_a_multi_selection_survives_the_panels_and_is_outlined_and_moved_together(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    session = app.session
    assert session.stack is not None
    session.select_many([first, second], origin="canvas")  # the tree re-renders and echoes
    _settle(designer_root)
    assert session.selection.nodes == (first, second)  # the tree echo did not collapse it
    overlay = app.shell.canvas.stages[0].overlay
    assert len(overlay.selection.shown()) == 16  # two two-tone rings of four strips each
    widget = _outer(app, second)
    assert overlay.primary is not None and overlay.primary.w == widget.winfo_width()
    # Pressing a member keeps both; dragging moves both (anchor: second) as one step.
    before = session.stack.index
    _drag(app, designer_root, second, _append_row(app, window))
    assert first.placement == GridCell(row=1, column=0)
    assert second.placement == GridCell(row=2, column=0)
    assert session.stack.index == before + 1 and session.stack.undo_text == "Move elements"
    assert session.selection.nodes == (first, second)
    assert tk_errors == []


@pytest.mark.parametrize("layout", ["grid", "pack"])
def test_a_moving_payload_over_a_frames_append_zone_matches_an_insert(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    layout: str,
) -> None:
    """Spec 5.4 acceptance 7: no special case for moves in a frame's zone."""
    window, first, _second = _two_labels(app, designer_root)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    assert isinstance(frame, Widget)
    if layout == "pack":
        assert app.session.stack is not None
        from pyguibud.core.commands import change_layout

        assert app.session.stack.execute(change_layout(frame, Layout(type="pack"), {})).accepted
        _settle(designer_root)
    assert _keyboard_insert(app, designer_root, frame, "Label")
    snapshot, box = _snapshot_box(app, frame)
    snapshot = replace(snapshot, visible=None)  # the test window is smaller than the stage
    assert box is not None and box.kind == layout and len(box.children) == 1
    point = (box.inner.x + box.inner.w - 10, box.inner.y + box.inner.h - 10)
    new = hit_test(snapshot, *point, NewWidget("Label"))
    moved = hit_test(snapshot, *point, Moving((first,)))
    assert new is not None and moved is not None and new.container is frame
    assert new.key == moved.key
    assert (new.row, new.column) == (1, 1) if layout == "grid" else new.index == 1
    assert tk_errors == []
