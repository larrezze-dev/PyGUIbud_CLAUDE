"""Size handles, window handles and size keys on the canvas (spec direct-manipulation 2-4, 10)."""

from __future__ import annotations

import itertools
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core.commands import CommandStack
from pyguibud.core.model import GridCell, Prop, Widget, Window
from pyguibud.designer import sizing
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.engine import widget_rect
from pyguibud.designer.editing import Edge
from tests.designer.conftest import best_of
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _window,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui
_CLOCK = itertools.count(10_000, 1_000)  # press times far apart: never a double-click


def _insert(app: DesignerApp, root: Any, name: str, **cell: Any) -> Widget:  # noqa: F811
    """``main_window`` with one ``name`` element in its body grid (``cell``: sticky etc.)."""
    app.session.new_from_template("main_window")
    _settle(root)
    window = _window(app)
    assert _keyboard_insert(app, root, window, name)
    node = window.children[-1]
    assert isinstance(node, Widget) and isinstance(node.placement, GridCell)
    if cell:
        node.placement = GridCell(row=node.placement.row, column=node.placement.column, **cell)
        app.session.stack.clear()  # type: ignore[union-attr]
        app.shell.canvas._render()
    app.session.select(node, origin="canvas")
    _settle(root)
    return node


def _stage(app: DesignerApp) -> Any:  # noqa: F811
    return app.shell.canvas.stages[0]


def _handle(app: DesignerApp, edge: Edge) -> Any:  # noqa: F811
    overlay = _stage(app).overlay
    edges = [e for e in sizing.EDGES if e in overlay.kinds]
    return overlay.handles.shown()[edges.index(edge)]


def _drag(
    root: Any, handle: Any, dx: int, dy: int, *, state: int = 0, release: bool = True
) -> None:
    x, y = handle.winfo_rootx() + 3, handle.winfo_rooty() + 3
    t = next(_CLOCK)
    handle.event_generate("<ButtonPress-1>", x=3, y=3, rootx=x, rooty=y, state=state, time=t)
    to = {"x": 0, "y": 0, "rootx": x + dx, "rooty": y + dy, "state": 0x100 | (state & 0x1)}
    handle.event_generate("<B1-Motion>", **to)
    if release:
        handle.event_generate("<ButtonRelease-1>", **to)
        _settle(root)


def _pitch(app: DesignerApp, node: object) -> tuple[float, float]:  # noqa: F811
    stage = _stage(app)
    return app.shell.canvas.engine.metrics(stage.view, node)


def test_a_button_right_handle_sets_the_width_in_one_undo_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    button = _insert(app, designer_root, "Button")
    stack, stage = app.session.stack, _stage(app)
    assert stack is not None and stage.view is not None
    kinds = stage.overlay.kinds
    assert {e for e, k in kinds.items() if k == "size"} == {"e", "w"}
    handle = _handle(app, "e")
    assert int(handle.cget("highlightthickness")) == 1  # filled
    assert int(_handle(app, "n").cget("highlightthickness")) == 2  # hollow: span
    handle.event_generate("<Enter>")
    assert app.shell._message.startswith("Drag to change the width. Hold Ctrl")
    pitch = _pitch(app, button)[0]
    rect = widget_rect(stage.view.outer[id(button)], stage.stage)
    assert rect is not None and pitch > 1
    start = sizing.start_value(button, "width", rect.w, pitch).value
    before = stack.index
    _drag(designer_root, handle, round(3 * pitch), 0, release=False)
    assert (
        app.shell._message
        == f"Release to set the width of '{button.id}' to {start + 3} characters."
    )
    assert stage.overlay.band.shown()  # the ghost
    assert stack.index == before  # no command during motion
    handle.event_generate(
        "<ButtonRelease-1>",
        x=0,
        y=0,
        rootx=handle.winfo_rootx() + 3 + round(3 * pitch),
        rooty=handle.winfo_rooty() + 3,
        state=0x100,
    )
    _settle(designer_root)
    assert button.props["width"].value == str(start + 3)
    assert stack.index == before + 1 and stack.undo_text == "Resize"
    assert app.shell._message == f"Resized '{button.id}'."
    assert not stage.overlay.band.shown()
    stack.undo()
    assert "width" not in button.props
    assert tk_errors == []


def test_an_empty_frame_corner_sets_both_sizes_and_r_a_keeps_them(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame = _insert(app, designer_root, "Frame")
    assert set(_stage(app).overlay.kinds.values()) == {"size"}
    _drag(designer_root, _handle(app, "se"), 50, 30)
    width, height = int(frame.props["width"].value), int(frame.props["height"].value)
    assert width % 4 == 0 and height % 4 == 0 and width > 120 and height > 64
    inner = _stage(app).view.inner[id(frame)]
    assert (int(inner.cget("width")), int(inner.cget("height"))) == (width, height)
    stack = app.session.stack
    assert stack is not None
    before = stack.index
    _drag(designer_root, _handle(app, "se"), 0, 0)  # a click on a 4 px-snapped size: no step
    _drag(designer_root, _handle(app, "e"), 1, 0, state=0x1)  # Shift: 1 px steps
    assert stack.index == before + 1 and frame.props["width"].value == str(width + 1)
    width += 1
    _drag(designer_root, _handle(app, "e"), 0, 0)  # 4 px snapping, but back at the press
    assert stack.index == before + 1
    _drag(designer_root, _handle(app, "e"), 1 - width, 0, state=0x1)
    assert frame.props["width"].value == "1"
    assert int(_stage(app).view.inner[id(frame)].cget("width")) >= 16  # the design floor
    assert tk_errors == []


def test_a_frame_with_contents_has_only_span_handles_and_says_why(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame = _insert(app, designer_root, "Frame")
    assert _keyboard_insert(app, designer_root, frame, "Label")
    app.session.select(frame, origin="canvas")
    _settle(designer_root)
    assert set(_stage(app).overlay.kinds.values()) == {"span"}
    _handle(app, "e").event_generate("<Enter>")
    assert app.shell._message.startswith("A frame with contents takes the size")
    assert tk_errors == []


def test_sticky_ew_makes_the_side_handles_hollow_and_ctrl_forces_span(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    entry = _insert(app, designer_root, "Entry", sticky="ew")
    assert _stage(app).overlay.kinds["e"] == "span"
    _handle(app, "e").event_generate("<Enter>")
    assert "(Sticky)" in app.shell._message
    app.session.select(_window(app), origin="canvas")
    entry.placement = GridCell(row=0, column=0)
    app.session.select(entry, origin="canvas")
    _settle(designer_root)
    assert _stage(app).overlay.kinds["e"] == "size"
    _drag(designer_root, _handle(app, "e"), 40, 0, state=0x4, release=False)
    drag: Any = app.shell.drag
    assert drag.state == "resizing" and drag._resize is not None and drag._size is None
    drag.cancel()
    assert app.shell._message == "Drag cancelled." and "width" not in entry.props
    assert tk_errors == []


def test_double_click_resets_and_escape_cancels_a_size_drag(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    label = _insert(app, designer_root, "Label")
    stack = app.session.stack
    assert stack is not None
    assert stack.execute(sizing.size_command(label, [("width", 9)])).accepted  # type: ignore[arg-type]
    _settle(designer_root)
    handle, before = _handle(app, "e"), stack.index
    _drag(designer_root, handle, 60, 0, release=False)
    app.shell.canvas.focus_widget.event_generate("<FocusOut>")  # Esc and focus loss share it
    assert app.shell.drag.state == "idle" and app.shell._message == "Drag cancelled."
    assert label.props["width"].value == "9" and stack.index == before
    app.shell.canvas._on_handle("e", "double", SimpleNamespace(state=0))
    _settle(designer_root)
    assert "width" not in label.props and stack.undo_text == "Reset width"
    assert tk_errors == []


def test_the_window_corner_writes_both_minimums_and_contents_clear_them(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    window, stack = _window(app), app.session.stack
    assert stack is not None and (window.min_width, window.min_height) == (480, 320)
    app.session.select(window, origin="canvas")
    _settle(designer_root)
    assert sorted(_stage(app).overlay.kinds) == ["e", "s", "se"]
    before = stack.index
    _drag(designer_root, _handle(app, "se"), 80, 40, release=False)
    assert app.shell._message.startswith(f"Release to set the minimum size of '{window.id}' to")
    _drag(designer_root, _handle(app, "se"), 80, 40)
    width, height = window.min_width, window.min_height
    assert width is not None and height is not None and width > 480 and height > 320
    assert stack.index == before + 1 and stack.undo_text == "Resize window"
    column = _stage(app).stage.grid_bbox(0, 0)
    assert column[2] >= width  # the rebuild applies the new minimum
    _drag(designer_root, _handle(app, "se"), -2000, -2000)
    assert (window.min_width, window.min_height) == (None, None)
    assert stack.index == before + 2 and "minimum size was cleared" in app.shell._message
    _drag(designer_root, _handle(app, "se"), 0, 0)  # a click records nothing
    assert stack.index == before + 2
    assert tk_errors == []


def test_size_keys_merge_and_shift_arrows_still_span(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    label = _insert(app, designer_root, "Label")
    stack = app.session.stack
    assert stack is not None
    label.set_prop(Prop(name="width", value="5"))  # a known start (outside the stack: no rebuild)
    before = stack.index
    for _ in range(3):
        app.registry.invoke("edit.size_wider")
        _settle(designer_root)
    assert label.props["width"].value == "8" and stack.index == before + 1
    app.registry.invoke("edit.wider")  # Shift+Right: still the span (here refused: one column)
    _settle(designer_root)
    assert app.shell._message == "That would put an element outside the grid."
    assert label.props["width"].value == "8" and stack.index == before + 1
    stack.undo()
    assert label.props["width"].value == "5"
    assert tk_errors == []


def test_no_handles_while_read_only(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    label = _insert(app, designer_root, "Label")
    monkeypatch.setattr(CommandStack, "read_only", property(lambda _self: True))
    app.session.select(_window(app), origin="canvas")
    app.session.select(label, origin="canvas")
    _settle(designer_root)
    assert _stage(app).overlay.handles.shown() == []
    assert isinstance(_window(app), Window)
    assert tk_errors == []


def test_resize_cycles_leak_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    label = _insert(app, designer_root, "Label")
    stage = _stage(app)

    def census() -> tuple[int, int]:
        return len(stage.stage.winfo_children()), len(designer_root.tk.call("image", "names"))

    _drag(designer_root, _handle(app, "e"), 30, 0)
    baseline = census()
    for k in range(20):
        _drag(designer_root, _handle(app, "e"), 30 if k % 2 else -30, 0)
    assert census() == baseline and "width" in label.props
    assert tk_errors == []


@pytest.mark.budget
def test_size_motion_stays_within_the_overlay_budget(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 8: <= 5 ms per motion event (x3 for CI), and no command or rebuild during motion."""
    _insert(app, designer_root, "Text")
    handle, stack = _handle(app, "se"), app.session.stack
    assert stack is not None
    _drag(designer_root, handle, 10, 10, release=False)
    drag: Any = app.shell.drag
    x, y, before = handle.winfo_rootx(), handle.winfo_rooty(), stack.index
    steps = itertools.cycle(range(0, 200, 7))

    def move() -> None:
        step = next(steps)
        drag.motion(x + step, y + step)

    assert best_of(move) < 0.015
    assert stack.index == before and not app.shell.canvas.rebuild_pending
    drag.cancel()
    assert tk_errors == []
