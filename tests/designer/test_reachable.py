"""Spec dnd-selection 5.4 (ADR-010 Addendum 2): every container is reachable by the mouse."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from pyguibud.core.commands import SetField, SetProp
from pyguibud.core.model import Layout, PackPlacement, Prop, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas import engine as engine_module
from pyguibud.designer.targets import Moving, NewWidget, hit_test
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _snapshot_box,
    _window,
    app,
    tk_errors,
)


def test_design_affordances_are_pinned() -> None:
    """A third design-only deviation needs an addendum to ADR-010 (Addendum 2)."""
    assert engine_module.DESIGN_AFFORDANCES == (
        "empty-minimum-size",
        "append-zone-padding",
        "paned-append-pane",
    )


def _body_with_label(app: DesignerApp, root: Any) -> tuple[Any, Any]:  # noqa: F811
    app.session.new_from_template("main_window")
    _settle(root)
    window = _window(app)
    assert _keyboard_insert(app, root, window, "Label")
    label = window.children[-1]
    return window, label


@pytest.mark.gui
def test_the_zones_of_a_window_body_give_the_append_row_and_column(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, label = _body_with_label(app, designer_root)
    snapshot, box = _snapshot_box(app, window)
    snapshot = replace(snapshot, visible=None)  # the test window is smaller than the body
    assert box is not None
    child = next(c for c in box.children if c.node is label).rect
    right = hit_test(
        snapshot, box.inner.x + box.inner.w - 10, child.y + child.h // 2, NewWidget("Label")
    )
    bottom = hit_test(
        snapshot, child.x + child.w // 2, box.inner.y + box.inner.h - 10, NewWidget("Label")
    )
    assert right is not None and (right.row, right.column) == (0, 1)
    assert bottom is not None and (bottom.row, bottom.column) == (1, 0)
    for x in range(box.inner.x, box.inner.x + box.inner.w, 7):
        for y in range(box.inner.y, box.inner.y + box.inner.h, 7):
            target = hit_test(snapshot, x, y, NewWidget("Label"))
            if target is not None and target.container is window:
                assert target.column <= 1 and target.row <= 1, (x, y, target)
    assert tk_errors == []


@pytest.mark.gui
def test_a_pack_frame_whose_only_child_fills_it_offers_the_append_slot(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 5.4 acceptance 3, built through the command stack (new Frames default to grid)."""
    session = app.session
    session.new_from_template("main_window")
    _settle(designer_root)
    assert session.stack is not None
    assert _keyboard_insert(app, designer_root, _window(app), "Frame")
    outer = session.selection.node
    assert isinstance(outer, Widget)
    assert session.stack.execute(SetField(outer, "layout", Layout(type="pack"))).accepted
    assert _keyboard_insert(app, designer_root, outer, "Frame")
    (inner,) = outer.children
    fill = PackPlacement(fill="both", expand=True)
    assert session.stack.execute(SetField(inner, "placement", fill)).accepted
    _settle(designer_root)
    snapshot, box = _snapshot_box(app, outer)
    assert box is not None and box.kind == "pack", box
    assert [c.node for c in box.children] == [inner]
    indexes = {
        target.index
        for x in range(box.rect.x, box.rect.x + box.rect.w)
        for y in range(box.rect.y, box.rect.y + box.rect.h)
        if (target := hit_test(snapshot, x, y, NewWidget("Label"))) is not None
        and target.container is outer
    }
    assert 1 in indexes, indexes
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("orient", ["horizontal", "vertical"])
def test_a_paned_window_append_pane_lies_along_its_orient_axis_and_keeps_no_slack(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    orient: str,
) -> None:
    """R-C: the append pane maps to the append slot; the real pane keeps the slack (runtime)."""
    session = app.session
    session.new_from_template("main_window")
    _settle(designer_root)
    assert session.stack is not None
    assert _keyboard_insert(app, designer_root, _window(app), "PanedWindow")
    paned = session.selection.node
    assert session.stack.execute(SetProp(paned, Prop(name="orient", value=orient))).accepted
    assert _keyboard_insert(app, designer_root, paned, "Frame")
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    inner = stage.view.inner[id(paned)]
    assert str(inner.cget("orient")) == orient
    snapshot, _box = _snapshot_box(app, paned)
    spacer = inner.nametowidget(str(inner.panes()[-1]))
    x = spacer.winfo_rootx() - stage.stage.winfo_rootx() + spacer.winfo_width() // 2
    y = spacer.winfo_rooty() - stage.stage.winfo_rooty() + spacer.winfo_height() // 2
    target = hit_test(snapshot, x, y, NewWidget("Frame"))
    assert target is not None and target.container is paned and target.index == 1, target
    axis = "width" if orient == "horizontal" else "height"
    inner.configure(**{axis: 400})
    _settle(designer_root)
    real, extra = (
        int(getattr(inner.nametowidget(str(pane)), f"winfo_{axis}")()) for pane in inner.panes()
    )
    zone = app.shell.canvas.engine._scale(engine_module._ZONE)
    assert extra == zone and real > 400 - 2 * zone, (real, extra)
    assert tk_errors == []


@pytest.mark.gui
def test_building_the_same_window_twice_gives_identical_rects(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, _label = _body_with_label(app, designer_root)
    canvas = app.shell.canvas
    stage = canvas.stages[0]
    assert stage.view is not None
    assert app.session.document is not None
    first = str(stage.view.inner[id(window)].cget("padding"))
    view = canvas.engine.build(app.session.document, window, stage.stage)
    try:
        second = str(view.inner[id(window)].cget("padding"))
    finally:
        view.destroy()
    left, _top, right, _bottom = (int(v) for v in first.strip("()").split(","))
    assert first == second and right > left  # extra zone applied once, never cumulative
    assert tk_errors == []


@pytest.mark.gui
def test_a_notebook_with_a_page_follows_the_page_size_not_the_empty_minimum(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), "Notebook")
    notebook = app.session.selection.node
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    assert int(stage.view.inner[id(notebook)].cget("width")) > 0  # empty: the minimum applies
    assert _keyboard_insert(app, designer_root, notebook, "Frame")
    _settle(designer_root)
    assert stage.view is not None
    assert int(stage.view.inner[id(notebook)].cget("width")) == 0
    assert tk_errors == []


@pytest.mark.gui
def test_a_moving_payload_over_a_zone_gives_the_same_append_target(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    window, label = _body_with_label(app, designer_root)
    assert _keyboard_insert(app, designer_root, window, "Entry")
    other = window.children[-1]
    snapshot, box = _snapshot_box(app, window)
    snapshot = replace(snapshot, visible=None)  # the test window is smaller than the body
    assert box is not None
    point = (box.inner.x + box.inner.w - 10, box.inner.y + box.inner.h - 10)
    new = hit_test(snapshot, *point, NewWidget("Label"))
    moved = hit_test(snapshot, *point, Moving((label,)))
    assert new is not None and moved is not None
    assert (new.container, new.row, new.column) == (moved.container, moved.row, moved.column)
    assert other is not label
    assert tk_errors == []
