"""Palette -> canvas drag-and-drop and single selection (spec dnd-selection 6, 7; Step 13a)."""

from __future__ import annotations

import time
from typing import Any

import pytest

from pyguibud.core.commands import InsertNode
from pyguibud.core.model import GridCell, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.editing import new_node
from pyguibud.designer.targets import NewWidget, hit_test
from tests.designer.conftest import best_of

pytestmark = pytest.mark.gui


def _with_frame(shell: DesignerApp, root: Any) -> Widget:
    """``main_window`` with a Frame filling its single grid cell (no template has one)."""
    session = shell.session
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    assert session.stack.execute(InsertNode(window, frame)).accepted
    root.update()
    return frame


def _centre(widget: Any) -> tuple[int, int]:
    return (
        widget.winfo_rootx() + widget.winfo_width() // 2,
        widget.winfo_rooty() + widget.winfo_height() // 2,
    )


def _drag(
    shell: DesignerApp, root: Any, name: str, to: tuple[int, int], *, drop: bool = True
) -> None:
    """A synthetic drag of the palette item ``name`` to the root point ``to``."""
    tree = shell.shell.palette.tree
    assert tree is not None
    root.update_idletasks()
    tree.see(f"w:{name}")
    root.update_idletasks()
    x, y, _w, h = (int(v) for v in tree.bbox(f"w:{name}"))
    sx, sy = tree.winfo_rootx() + x + 4, tree.winfo_rooty() + y + h // 2
    tree.event_generate("<ButtonPress-1>", x=x + 4, y=y + h // 2, rootx=sx, rooty=sy)
    for step in (10, 30):
        tree.event_generate("<B1-Motion>", x=x + step, y=y, rootx=sx + step, rooty=sy, state=0x100)
    tree.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
    if drop:
        tree.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)


def test_dragging_a_button_into_a_grid_frame_inserts_selects_and_undoes(
    shell: DesignerApp, designer_root: Any
) -> None:
    frame = _with_frame(shell, designer_root)
    session, stage = shell.session, shell.shell.canvas.stages[0]
    assert stage.view is not None and session.stack is not None
    _drag(shell, designer_root, "Button", _centre(stage.view.inner[id(frame)]))
    assert len(frame.children) == 1
    button = frame.children[0]
    assert isinstance(button, Widget) and button.class_name == "Button"
    assert button.id == "button1" and button.placement == GridCell(row=0, column=0)
    assert session.selection.node is button and session.selection.origin == "canvas"
    assert session.stack.undo_text is not None
    assert shell.shell._message == "Inserted 'button1'."
    designer_root.update()
    assert stage.overlay.selection.shown()  # the outline follows the rebuild
    tree = shell.shell.tree
    assert tree.tree is not None and tree.tree.selection() == (tree.key_of(button),)
    designer_root.update()
    assert shell.shell.inspector.value_of("field:id") == "button1"  # the 14a editable form
    session.stack.undo()
    assert list(frame.children) == []
    assert not session.selection.nodes  # pruned
    designer_root.update()
    session.stack.redo()
    assert list(frame.children) == [button]


def test_an_occupied_cell_is_denied_with_the_reason(shell: DesignerApp, designer_root: Any) -> None:
    _with_frame(shell, designer_root)
    session, stage = shell.session, shell.shell.canvas.stages[0]
    assert stage.view is not None and session.stack is not None and session.document is not None
    window = session.document.children[0]
    # The window's only cell holds the frame: aim at the body just inside the frame's edge band.
    body = stage.view.inner[id(window)]
    point = (body.winfo_rootx() + 14, body.winfo_rooty() + 14)
    view = stage.view
    _drag(shell, designer_root, "Label", point, drop=False)
    tree = shell.shell.palette.tree
    assert tree is not None
    deadline = time.monotonic() + 2
    while str(tree.cget("cursor")) != "X_cursor" and time.monotonic() < deadline:
        designer_root.update()  # the check runs after the pointer rested 60 ms
    assert str(tree.cget("cursor")) == "X_cursor"
    assert stage.view is view  # a hover check() is a dry run: no stack event, no rebuild
    message = shell.shell._message
    assert "overlaps" in message  # the validator's collision reason
    before = session.stack.index
    tree.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=point[0], rooty=point[1])
    assert session.stack.index == before and len(window.children) == 1
    assert not stage.overlay.target.shown()


def test_escape_or_focus_loss_cancels_a_drag(shell: DesignerApp, designer_root: Any) -> None:
    frame = _with_frame(shell, designer_root)
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    target = _centre(stage.view.inner[id(frame)])
    _drag(shell, designer_root, "Entry", target, drop=False)
    drag: Any = shell.shell.drag  # Any: mypy would keep the narrowed state literal
    assert drag.state == "dragging" and stage.overlay.target.shown()
    tree = shell.shell.palette.tree
    assert tree is not None
    # Key events only reach a focused widget, which a withdrawn root never has: Esc and a focus
    # loss share the cancel binding, so the focus loss stands in for the key here.
    assert "<Key-Escape>" in tree.bind()
    tree.event_generate("<FocusOut>")
    assert drag.state == "idle" and not stage.overlay.target.shown()
    tree.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=target[0], rooty=target[1])
    assert list(frame.children) == []
    assert shell.shell._message == "Drag cancelled."


def test_a_listener_path_never_reenters_the_stack(shell: DesignerApp, designer_root: Any) -> None:
    """R5: execute, undo (prune -> selection_changed -> every panel) and redo raise nothing."""
    frame = _with_frame(shell, designer_root)
    session = shell.session
    assert session.stack is not None
    shell.session.select(frame, origin="tree")
    session.stack.undo()
    assert session.selection.nodes == ()
    session.stack.redo()
    designer_root.update()


def test_snapshot_and_hit_test_budgets(shell: DesignerApp, designer_root: Any) -> None:
    session = shell.session
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    for index in range(200):
        label = new_node(session.registry.require("Label"), None)
        assert isinstance(label, Widget)
        label.id = f"lbl{index}"
        label.placement = GridCell(row=index // 10, column=index % 10)
        frame.insert_child(index, label)
    assert session.stack.execute(InsertNode(window, frame)).accepted
    designer_root.update()
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    engine = shell.shell.canvas.engine
    view = stage.view
    snapshot = engine.snapshot(view, stage.stage, stage.scroll)
    box = next(b for b in snapshot.containers if b.node is frame)
    assert len(box.columns) == 11 and len(box.rows) == 21
    point = (box.columns[3] + 1, box.rows[5] + 1)
    target = hit_test(snapshot, *point, NewWidget("Label"))
    assert target is not None and (target.row, target.column) == (5, 3)
    # Spec 13 budgets (x3 for CI and coverage). The best of several runs with the collector
    # paused: one gen-2 GC pause on the whole suite's heap is longer than the 3 ms hit budget.
    assert best_of(lambda: engine.snapshot(view, stage.stage, stage.scroll)) < 0.030 * 3
    assert best_of(lambda: hit_test(snapshot, *point, NewWidget("Label"))) < 0.001 * 3
