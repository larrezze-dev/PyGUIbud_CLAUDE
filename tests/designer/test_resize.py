"""Resize handles and the cell-grid overlay on the canvas (spec dnd-selection 3, 8)."""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pytest

from pyguibud.core.model import GridCell, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.overlay import HANDLES
from pyguibud.designer.editing import Edge, move_command, resize_command
from pyguibud.designer.targets import Target
from pyguibud.designer.theme import spec_for_role
from tests.designer.conftest import best_of
from tests.designer.test_drag_move import _append_row, _drag
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _snapshot_box,
    _window,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui


def _three_labels(app: DesignerApp, root: Any) -> tuple[Any, Widget, Widget, Widget]:  # noqa: F811
    """``main_window`` with Labels at (0, 0), (1, 0) and (1, 1): the body grid has 2 columns."""
    session = app.session
    session.new_from_template("main_window")
    _settle(root)
    window = _window(app)
    for _ in range(3):
        assert _keyboard_insert(app, root, window, "Label")
    a, b, c = window.children[-3:]
    assert isinstance(a, Widget) and isinstance(b, Widget) and isinstance(c, Widget)
    assert session.stack is not None
    built = move_command((c,), Target(window, "grid", None, 1, 1))
    assert not isinstance(built, str) and session.stack.execute(built).accepted
    _settle(root)
    return window, a, b, c


def _handle(app: DesignerApp, root: Any, node: object, edge: Edge) -> Any:  # noqa: F811
    app.session.select(node, origin="canvas")
    _settle(root)
    shown = app.shell.canvas.stages[0].overlay.handles.shown()
    assert len(shown) == len(HANDLES)
    return shown[[e for e, _c in HANDLES].index(edge)]


def _press(handle: Any, to: tuple[int, int]) -> None:
    """Press ``handle`` with Ctrl held (span, not size: Step 14b D1) and drag it to the root
    point ``to`` (no release)."""
    x, y = handle.winfo_rootx() + 2, handle.winfo_rooty() + 2
    handle.event_generate("<ButtonPress-1>", x=2, y=2, rootx=x, rooty=y, state=0x4)
    handle.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)


def _release(root: Any, handle: Any, to: tuple[int, int]) -> None:
    handle.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
    _settle(root)


def _line(app: DesignerApp, window: object, column: int, row: int) -> tuple[int, int]:  # noqa: F811
    """The root point where column line ``column`` crosses the middle of row ``row``."""
    _snapshot, box = _snapshot_box(app, window)
    stage = app.shell.canvas.stages[0].stage
    y = (box.rows[row] + box.rows[row + 1]) // 2
    return stage.winfo_rootx() + box.columns[column], stage.winfo_rooty() + y


def test_the_right_handle_spans_two_columns_in_one_undo_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, a, _b, _c = _three_labels(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    handle = _handle(app, designer_root, a, "e")
    assert handle.winfo_width() >= 8 and str(handle.cget("cursor")) == "sb_h_double_arrow"
    before, to = stack.index, _line(app, window, 2, 0)
    _press(handle, to)
    assert app.shell.canvas.stages[0].overlay.grid.shown()  # the snap guide is drawn
    expected = f"Release to resize '{a.id}' to 2 × 1 cells."  # noqa: RUF001 - the sign is meant
    deadline = time.monotonic() + 3
    while app.shell._message != expected and time.monotonic() < deadline:
        designer_root.update()
    assert app.shell._message == expected
    _release(designer_root, handle, to)
    assert a.placement == GridCell(row=0, column=0, columnspan=2)
    assert stack.index == before + 1 and stack.undo_text == "Resize element"
    assert not app.shell.canvas.stages[0].overlay.grid.shown()
    stack.undo()
    assert a.placement == GridCell(row=0, column=0)
    assert tk_errors == []


def test_the_left_handle_moves_the_cell_and_keeps_the_right_edge(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, a, _b, _c = _three_labels(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    assert stack.execute(resize_command(a, 0, 0, 1, 2)).accepted  # type: ignore[arg-type]
    _settle(designer_root)
    handle = _handle(app, designer_root, a, "w")
    before, to = stack.index, _line(app, window, 1, 0)
    _press(handle, to)
    _release(designer_root, handle, to)
    assert a.placement == GridCell(row=0, column=1, columnspan=1)  # right edge still at 2
    assert stack.index == before + 1
    assert tk_errors == []


def test_a_collision_is_denied_live_and_nothing_is_recorded(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, _a, b, _c = _three_labels(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    handle = _handle(app, designer_root, b, "e")
    before, to = stack.index, _line(app, window, 2, 1)
    _press(handle, to)  # (1, 1) is taken by the third Label
    deadline = time.monotonic() + 3
    while str(handle.cget("cursor")) != "X_cursor" and time.monotonic() < deadline:
        designer_root.update()
    assert str(handle.cget("cursor")) == "X_cursor"
    reason = app.shell._message
    assert reason and not reason.startswith("Release")
    _release(designer_root, handle, to)
    assert b.placement == GridCell(row=1, column=0) and stack.index == before
    assert app.shell._message == reason  # the validator's reason again, from the execute
    assert str(handle.cget("cursor")) == "sb_h_double_arrow"
    assert tk_errors == []


def test_escape_or_focus_loss_cancels_a_resize_and_a_click_records_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, a, _b, _c = _three_labels(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    handle = _handle(app, designer_root, a, "se")
    before, to = stack.index, _line(app, window, 2, 0)
    _press(handle, to)
    drag: Any = app.shell.drag
    assert drag.state == "resizing" and drag.moving
    proxy = app.shell.canvas.focus_widget
    # A withdrawn root never has the keyboard focus: Esc and a focus loss share the handler.
    assert "<Key-Escape>" in proxy.bind()
    proxy.event_generate("<FocusOut>")
    assert drag.state == "idle" and app.shell._message == "Drag cancelled."
    _release(designer_root, handle, to)
    at = (handle.winfo_rootx() + 2, handle.winfo_rooty() + 2)
    _press(handle, at)  # a click on a handle without moving it
    _release(designer_root, handle, at)
    assert a.placement == GridCell(row=0, column=0) and stack.index == before
    assert tk_errors == []


def test_handles_only_for_grid_children_and_visible_in_every_theme(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, a, _b, _c = _three_labels(app, designer_root)
    overlay = app.shell.canvas.stages[0].overlay
    app.session.select(window, origin="canvas")
    _settle(designer_root)
    assert len(overlay.handles.shown()) == 3  # Step 14b: the window's e, se and s size handles
    for theme in ("light", "dark", "high_contrast"):
        assert app.set_theme(theme)
        app.flush_theme()
        handle = _handle(app, designer_root, a, "e")
        spec = spec_for_role(app.specs, theme)
        assert spec is not None
        assert str(handle.cget("background")).lower() == spec.colors["primary"].lower()
        assert str(handle.cget("highlightbackground")).lower() == spec.colors["bg"].lower()
    assert tk_errors == []


def test_a_move_drag_over_a_grid_shows_its_cell_lines_within_budget(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, _a, _b, c = _three_labels(app, designer_root)
    overlay = app.shell.canvas.stages[0].overlay
    _drag(app, designer_root, c, _append_row(app, window), drop=False)
    _snapshot, box = _snapshot_box(app, window)
    assert len(overlay.grid.shown()) == len(box.columns) + len(box.rows)
    app.shell.drag.cancel()
    assert overlay.grid.shown() == []
    # The overlay budget (spec 13): <= 5 ms per update, x3 for CI; 2 redraws of 128 lines.
    lines = tuple(range(0, 1000, 10))
    big = replace(box, columns=lines, rows=lines)
    other = replace(big, columns=lines[1:])

    def redraw() -> None:
        overlay.show_grid(big)
        overlay.show_grid(other)

    assert best_of(redraw) < 0.030
    overlay.show_grid(None)
    assert tk_errors == []
