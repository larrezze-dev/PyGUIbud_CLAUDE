"""Object-tree drag-and-drop on the real panel (spec direct-manipulation 5, 10, 11 Q10/Q11)."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from pyguibud.core.model import Widget
from pyguibud.designer.app import DesignerApp
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _window,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui
_CLOCK = itertools.count(50_000, 1_000)


def _setup(app: DesignerApp, root: Any) -> tuple[Widget, Widget, Widget]:  # noqa: F811
    """``main_window`` with a Frame and two Labels in its body."""
    app.session.new_from_template("main_window")
    _settle(root)
    window = _window(app)
    for name in ("Frame", "Label", "Label"):
        assert _keyboard_insert(app, root, window, name)
    frame, first, second = window.children[-3:]
    assert isinstance(frame, Widget) and isinstance(first, Widget) and isinstance(second, Widget)
    app.session.select(second, origin="tree")
    _settle(root)
    return frame, first, second


def _point(app: DesignerApp, node: object, fraction: float) -> tuple[int, int]:  # noqa: F811
    tree, key = app.shell.tree.tree, app.shell.tree.key_of(node)
    assert tree is not None and key is not None
    tree.see(key)
    tree.update_idletasks()
    x, y, w, h = (int(v) for v in tree.bbox(key))
    return x + w // 2, y + int(h * fraction)


def _drag(app: DesignerApp, root: Any, source: object, onto: object, fraction: float,  # noqa: F811
          *, release: bool = True) -> None:  # fmt: skip
    tree = app.shell.tree.tree
    assert tree is not None
    x, y = _point(app, source, 0.5)
    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=next(_CLOCK))
    tx, ty = _point(app, onto, fraction)
    for to in ((x + 12, y + 12), (tx, ty)):
        tree.event_generate("<B1-Motion>", x=to[0], y=to[1], state=0x100)
    root.after(150, lambda: None)  # the 60 ms hover check
    for _ in range(30):
        root.update()
    if release:
        tree.event_generate("<ButtonRelease-1>", x=tx, y=ty, state=0x100, time=next(_CLOCK))
        _settle(root)


def test_reparent_into_a_frame_is_one_undo_step_and_keeps_the_selection(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame, _first, second = _setup(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    _drag(app, designer_root, second, frame, 0.5)
    assert second.parent is frame and stack.index == index + 1
    assert app.session.selection.nodes == (second,)
    stack.undo()
    _settle(designer_root)
    assert second.parent is not frame and second in _window(app).children
    assert tk_errors == []


def test_reorder_before_a_sibling(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame, first, _second = _setup(app, designer_root)
    placed = frame.placement
    _drag(app, designer_root, frame, first, 0.9)  # the bottom half of a leaf: after it
    assert frame.parent is _window(app) and frame.placement != placed
    assert tk_errors == []


def test_a_denied_target_is_tagged_and_says_why_and_esc_cancels(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame, _first, second = _setup(app, designer_root)
    _drag(app, designer_root, second, frame, 0.5)
    assert second.parent is frame
    tree = app.shell.tree.tree
    assert tree is not None
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    app.session.select(frame, origin="tree")
    _settle(designer_root)
    _drag(app, designer_root, frame, second, 0.75, release=False)  # Q10: into its own child
    key = app.shell.tree.key_of(second)
    assert key is not None and "drop-denied" in tree.item(key, "tags")
    assert app.shell._message == "A widget cannot be dropped into itself."
    # A withdrawn root never takes the focus, so the bound handler is called as Esc would.
    assert "_drag_cancel" in tree.bind("<Escape>")
    assert app.shell.tree._drag_cancel(None) == "break"
    assert "drop-denied" not in tree.item(key, "tags")
    assert app.shell._message == "Drag cancelled."
    x, y = _point(app, second, 0.5)
    tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert stack.index == index and frame.parent is _window(app)
    assert tk_errors == []


def test_a_release_outside_the_tree_cancels(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    frame, _first, second = _setup(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    _drag(app, designer_root, second, frame, 0.5, release=False)
    tree = app.shell.tree.tree
    assert tree is not None
    tree.event_generate("<ButtonRelease-1>", x=-50, y=-50, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert stack.index == index and app.shell._message == "Drag cancelled."
    assert tk_errors == []


def test_into_a_leaf_row_is_denied_with_its_reason(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 5/10: "denied into a Button (tag + status reason)"; Q11 for an include likewise."""
    _frame, first, second = _setup(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    _drag(app, designer_root, second, first, 0.5, release=False)
    tree, key = app.shell.tree.tree, app.shell.tree.key_of(first)
    assert tree is not None and key is not None and "drop-denied" in tree.item(key, "tags")
    assert app.shell._message == f"'{first.id}' cannot hold elements: drop them before or after it."
    x, y = _point(app, first, 0.5)
    tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert stack.index == index and second.parent is _window(app)
    assert tk_errors == []


def test_a_focus_in_checks_the_included_files(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """UAT 14b.2 step 4: coming back to the designer refreshes the includes (spec 6.2)."""
    calls: list[bool] = []
    monkeypatch.setattr(app.shell.canvas, "refresh_includes", lambda *a: calls.append(True))
    tree = app.shell.tree.tree
    assert tree is not None
    tree.event_generate("<FocusIn>")
    assert calls == [True]
