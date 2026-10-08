"""Canvas gestures, rubber band, keys, tree multi-selection and R-D (spec dnd-selection 5.4, 7)."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from pyguibud.core.model import GridCell, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.engine import widget_rect
from pyguibud.designer.geometry import Rect
from pyguibud.designer.theme import contrast, load_theme_specs
from tests.designer.conftest import best_of
from tests.designer.test_drag_move import _append_row, _drag, _outer, _two_labels
from tests.designer.test_edit import shown  # noqa: F401 - key events need a focused root
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _window,
    app,
    tk_errors,
)

pytestmark = pytest.mark.gui
_CLOCK = itertools.count(5_000_000, 1000)  # far apart: never a double click
_CTRL, _SHIFT = 0x4, 0x1


def _click(widget: Any, state: int = 0) -> None:
    x, y = widget.winfo_rootx() + 2, widget.winfo_rooty() + 2
    for sequence in ("<ButtonPress-1>", "<ButtonRelease-1>"):
        widget.event_generate(sequence, x=2, y=2, rootx=x, rooty=y, state=state, time=next(_CLOCK))


def _sel(session: Any) -> tuple[object, ...]:
    return tuple(session.selection.nodes)  # a call: mypy keeps no narrowing across the edits


def _state(app: DesignerApp) -> str:  # noqa: F811
    return str(app.shell.drag.state)


def _key(app: DesignerApp, root: Any, sequence: str) -> None:  # noqa: F811
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate(sequence)
    _settle(root)


# ---------------------------------------------------------------- gestures (7.2)
def test_click_ctrl_click_shift_click_and_the_empty_stage(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    session = app.session
    _click(_outer(app, first))
    assert _sel(session) == (first,)
    _click(_outer(app, second), _CTRL)
    assert _sel(session) == (first, second)
    _click(_outer(app, first), _CTRL)  # toggles off; the release never collapses
    assert _sel(session) == (second,)
    _click(_outer(app, first), _SHIFT)
    assert _sel(session) == (second, first)
    _click(_outer(app, second))  # a plain click on a member selects just that one
    _settle(designer_root)
    assert _sel(session) == (second,)
    _click(app.shell.canvas.stages[0].stage)
    assert _sel(session) == (window,)
    assert tk_errors == []


def test_a_drag_from_a_member_makes_it_the_anchor(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    session = app.session
    session.select_many([second, first], origin="canvas")  # first is the primary
    _drag(app, designer_root, second, _append_row(app, window))
    assert session.selection.node is second  # the grabbed widget led the move
    assert second.placement == GridCell(row=2, column=0)
    assert first.placement == GridCell(row=1, column=0)
    assert tk_errors == []


# ---------------------------------------------------------------- rubber band (D5)
def _band(app: DesignerApp, state: int = 0, *, drop: bool = True) -> Any:  # noqa: F811
    """Drag a band from the body's bottom-right corner over both labels."""
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    body = stage.view.inner[id(_window(app))]
    x0, y0 = (
        body.winfo_rootx() + body.winfo_width() - 3,
        body.winfo_rooty() + body.winfo_height() - 3,
    )
    x1, y1 = body.winfo_rootx() - 2, body.winfo_rooty() - 2
    body.event_generate("<ButtonPress-1>", rootx=x0, rooty=y0, state=state, time=next(_CLOCK))
    body.event_generate("<B1-Motion>", rootx=x1, rooty=y1, state=state | 0x100)
    if drop:
        body.event_generate("<ButtonRelease-1>", rootx=x1, rooty=y1, state=state | 0x100)
    return body


def test_a_rubber_band_selects_the_children_fully_inside(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    assert _keyboard_insert(app, designer_root, frame, "Label")
    inner = frame.children[0]
    session = app.session
    session.select(window, origin="tree")
    _settle(designer_root)
    _band(app)
    _settle(designer_root)
    picked = set(map(id, session.selection.nodes))
    assert picked == {id(first), id(second), id(frame)}  # direct children only
    assert id(inner) not in picked and app.shell.drag.state == "idle"
    session.select(first, origin="tree")
    _band(app, _CTRL)  # Ctrl adds to the selection
    assert len(session.selection.nodes) == 3
    assert tk_errors == []


def test_escape_cancels_a_band_before_it_can_select_a_parent(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _window_node, first, _second = _two_labels(app, designer_root)
    app.session.select(first, origin="tree")
    _settle(designer_root)
    body = _band(app, _CTRL, drop=False)  # Ctrl: the selection stays the band's base
    overlay = app.shell.canvas.stages[0].overlay
    assert _state(app) == "banding" and len(overlay.band.shown()) == 4
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    proxy.event_generate("<Escape>")
    assert _state(app) == "idle" and not overlay.band.shown()
    assert _sel(app.session) == (first,)  # the band took Esc: Select parent never ran
    body.event_generate("<ButtonRelease-1>", rootx=0, rooty=0)
    _settle(designer_root)
    assert _sel(app.session) == (first,)
    assert tk_errors == []


def test_tab_scrolls_an_off_screen_widget_into_view_but_a_click_never_scrolls(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, _second = _two_labels(app, designer_root)
    designer_root.geometry("900x380")  # the stage no longer fits: it scrolls
    _settle(designer_root)
    stage = app.shell.canvas.stages[0]
    scroll = stage.scroll
    app.session.select(window, origin="tree")
    scroll.yview_moveto(1)
    _settle(designer_root)
    assert scroll.yview()[0] > 0
    _key(app, designer_root, "<Tab>")
    rect = widget_rect(_outer(app, first), stage.stage)
    top = int(scroll.canvasy(0))
    assert rect is not None and top <= rect.y and rect.y + rect.h <= top + scroll.winfo_height()
    scroll.yview_moveto(1)
    _settle(designer_root)
    before = scroll.yview()
    assert stage.view is not None
    _click(stage.view.inner[id(window)])  # selects the window: the view stays where it is
    _settle(designer_root)
    assert _sel(app.session) == (window,) and scroll.yview() == before
    assert tk_errors == []


# ---------------------------------------------------------------- keys (7.3, 7.4)
def test_every_canvas_key(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    assert _keyboard_insert(app, designer_root, frame, "Label")
    inner = frame.children[0]
    session, stack = app.session, app.session.stack
    assert stack is not None
    session.select(window, origin="tree")
    _key(app, designer_root, "<Tab>")
    assert session.selection.node is first
    _key(app, designer_root, "<Shift-Tab>")
    assert session.selection.node is inner  # wraps to the last in pre-order
    _key(app, designer_root, "<Escape>")
    assert session.selection.node is frame
    _key(app, designer_root, "<Return>")
    assert session.selection.node is inner
    session.select(first, origin="tree")
    before = stack.index
    _key(app, designer_root, "<Right>")
    assert first.placement == GridCell(row=0, column=1) and stack.index == before + 1
    _key(app, designer_root, "<Left>")
    _key(app, designer_root, "<Up>")  # clamped at row 0: denied with the reason
    assert app.shell._message == "That would put an element outside the grid."
    _key(app, designer_root, "<Shift-Right>")
    assert first.placement == GridCell(row=0, column=0, columnspan=2)
    _key(app, designer_root, "<Shift-Left>")
    assert stack.index == before + 4
    _key(app, designer_root, "<Control-a>")
    assert len(session.selection.nodes) == 3 and session.selection.node is first
    session.select_many([first, second], origin="canvas")
    _key(app, designer_root, "<Delete>")  # no children: no question
    assert first.parent is None and second.parent is None
    assert stack.undo_text == "Delete elements"
    stack.undo()
    assert first.parent is window and second.parent is window
    assert tk_errors == []


def test_a_held_arrow_never_queues_edits(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _window_node, first, _second = _two_labels(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    app.session.select(first, origin="tree")
    _settle(designer_root)
    before = stack.index
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    for _ in range(3):  # auto-repeat: no idle time between the presses
        proxy.event_generate("<Right>")
    assert stack.index == before + 1 and app.shell.canvas.rebuild_pending
    _settle(designer_root)
    assert first.placement == GridCell(row=0, column=1)
    assert tk_errors == []


def test_f6_always_leaves_the_canvas_and_focus_shows_the_hint(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    shell = app.shell
    proxy = shell.canvas.focus_widget
    assert str(proxy.cget("takefocus")) == "1" and proxy.winfo_class() == "Canvas"
    assert not any("F6" in sequence for sequence in proxy.bind())  # F6 is never swallowed
    shell.clear_message()
    proxy.focus_force()
    _settle(designer_root)
    assert shell.active_panel == 1
    assert shell._message == "Tab selects the next widget; F6 moves to the next panel."
    proxy.event_generate("<F6>")
    _settle(designer_root)
    assert shell.active_panel == 2 and designer_root.focus_get() is not proxy
    proxy.focus_force()
    _settle(designer_root)
    proxy.event_generate("<Shift-F6>")
    _settle(designer_root)
    assert shell.active_panel == 0
    rows = [(r.label, r.accelerator) for r in app.registry.cheat_sheet()]
    assert ("Select next widget (canvas)", "Tab") in rows
    assert ("Move earlier (object tree)", "Alt+Up") in rows
    assert tk_errors == []


# ---------------------------------------------------------------- tree and counts (7.2, D8)
def test_tree_extended_selection_syncs_canvas_status_and_inspector(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    tree, panel = app.shell.tree.tree, app.shell.tree
    assert tree is not None and str(tree.cget("selectmode")) == "extended"
    keys = [str(panel.key_of(first)), str(panel.key_of(second))]
    tree.selection_set(keys)
    tree.focus(keys[0])  # the clicked row is the primary
    tree.event_generate("<<TreeviewSelect>>")
    _settle(designer_root)
    app.shell.clear_message()
    assert _sel(app.session) == (second, first)
    assert len(app.shell.canvas.stages[0].overlay.selection.shown()) == 16
    assert app.shell._status.cget("text") == "2 elements selected"
    header = app.shell.inspector.header
    assert header.winfo_manager() == "grid"
    assert header.cget("text") == f"2 elements selected; showing '{first.id}'."
    # A window row with a widget row: the widget (primary) stands alone; the tree follows.
    tree.selection_set([str(panel.key_of(window)), keys[1]])
    tree.focus(keys[1])
    tree.event_generate("<<TreeviewSelect>>")
    _settle(designer_root)
    assert _sel(app.session) == (second,)
    assert tree.selection() == (keys[1],) and header.winfo_manager() == ""
    assert tk_errors == []


def test_alt_up_and_down_reorder_in_the_tree(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, first, second = _two_labels(app, designer_root)
    stack, tree = app.session.stack, app.shell.tree.tree
    assert stack is not None and tree is not None
    app.session.select(second, origin="tree")
    _settle(designer_root)
    before = stack.index
    tree.focus_force()
    tree.event_generate("<Alt-Up>")
    _settle(designer_root)
    assert list(window.children[-2:]) == [second, first] and stack.index == before + 1
    assert second.placement == GridCell(row=1, column=0)  # the order, not the cell
    tree.event_generate("<Alt-Down>")
    _settle(designer_root)
    assert list(window.children[-2:]) == [first, second] and stack.index == before + 2
    assert tk_errors == []


# ---------------------------------------------------------------- R-D (5.4)
def test_border_reaches_three_to_one_in_every_theme() -> None:
    for spec in load_theme_specs():
        assert contrast(spec.colors["border"], spec.colors["bg"]) >= 3, spec.role


def test_an_empty_container_is_outlined_until_it_gets_a_child_or_is_selected(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    window = _window(app)
    overlay = app.shell.canvas.stages[0].overlay
    assert overlay.empty.shown() == []  # an empty window body is never outlined
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    assert isinstance(frame, Widget)
    assert overlay.empty.shown() == []  # selected: the selection outline replaces it
    assert len(overlay.selection.shown()) == 8
    app.session.select(window, origin="tree")
    _settle(designer_root)
    strips = overlay.empty.shown()
    assert strips and not any(s.bind() for s in strips)  # takes no input
    stage = app.shell.canvas.stages[0].stage
    rect = widget_rect(_outer(app, frame), stage)
    assert rect is not None  # the 1 px ring lies just outside the container's rect
    assert min(s.winfo_x() for s in strips) == rect.x - 1
    assert min(s.winfo_y() for s in strips) == rect.y - 1
    assert max(s.winfo_x() + s.winfo_width() for s in strips) == rect.x + rect.w + 1
    assert all(s.winfo_width() == 1 or s.winfo_height() == 1 for s in strips)
    assert _keyboard_insert(app, designer_root, frame, "Label")
    app.session.select(window, origin="tree")
    _settle(designer_root)
    assert overlay.empty.shown() == []  # it has a child now
    assert tk_errors == []


def test_the_empty_outlines_stay_within_the_overlay_budget(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    """Spec 13: an overlay update takes at most 5 ms (x3 for CI), even at the outline cap."""
    app.session.new_from_template("main_window")
    _settle(designer_root)
    overlay = app.shell.canvas.stages[0].overlay
    rects = [Rect(10 + 130 * (k % 4), 10 + 70 * (k // 4), 120, 64) for k in range(40)]
    overlay.show_empty(rects)  # creates the strip pool once
    assert best_of(lambda: overlay.show_empty(rects)) <= 0.015
    overlay.show_empty([])


def test_a_failed_rebuild_leaves_no_outline_behind(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    window = _window(app)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    app.session.select(window, origin="tree")
    _settle(designer_root)
    canvas = app.shell.canvas
    stage = canvas.stages[0]
    assert stage.overlay.empty.shown()

    def explode(*_args: object) -> object:
        raise RuntimeError("factory exploded")

    monkeypatch.setattr(canvas.engine, "build", explode)
    canvas._build(stage)
    assert stage.view is None and not stage.overlay.empty.shown()
