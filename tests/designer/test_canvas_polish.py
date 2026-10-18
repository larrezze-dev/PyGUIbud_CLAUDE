"""Step 14p, Task C: the canvas stage chrome and the overlay colours."""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud.core import read_ui_string
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.overlay import HANDLES, Overlay
from pyguibud.designer.geometry import Rect
from pyguibud.designer.theme import (
    NON_TEXT_CONTRAST,
    ThemeSpec,
    contrast,
    design_tokens,
    load_theme_specs,
)
from tests.designer.test_canvas_engine import TWO_WINDOWS, host  # noqa: F401 - fixture

pytestmark = pytest.mark.gui

SPECS = [*load_theme_specs(), *load_theme_specs(brand=False)]
MENU = TWO_WINDOWS.replace(
    '<layout type="grid"/><widget class="Button"',
    '<menubar><menu id="mnu"><prop name="text">_File</prop></menu></menubar>'
    '<layout type="grid"/><widget class="Button"',
    1,
)


def _open(shell: DesignerApp, text: str = MENU) -> Any:
    shell.session.open_result(read_ui_string(text, source="two"), name="two")
    panel = shell.shell.canvas
    panel.show_window(panel.stages[0].window)
    return panel


def _order(stage: Any) -> list[str]:
    """The stage's children from the bottom of the stacking order to the top."""
    return [str(w) for w in stage.stage.winfo_children()]


def _assert_plate_beneath(stage: Any) -> None:
    order, plate = _order(stage), str(stage.plate)
    assert order.index(plate) == 0, "the plate is the lowest child of the stage"
    if stage.view is not None:
        above = [str(stage.view.frame), str(stage.strip), str(stage.title.master)]
    else:
        above = [str(stage.card), str(stage.title.master)]
    assert all(order.index(plate) < order.index(w) for w in above)
    strips = [str(s) for layer in (stage.overlay.selection, stage.overlay.target)
              for s in layer.shown()]  # fmt: skip
    assert all(order.index(str(stage.view.frame)) < order.index(s) for s in strips) or not (
        stage.view and strips
    )


def test_the_plate_stays_beneath_the_window_and_every_strip(shell: DesignerApp) -> None:
    panel = _open(shell)
    stage = panel.stages[0]
    shell.session.select(stage.window.children[0], origin="tree")
    panel.show_window(stage.window)
    shell.root.update_idletasks()
    assert stage.overlay.selection.shown()
    _assert_plate_beneath(stage)
    for _round in range(3):  # a theme cycle restyles and rebuilds the stage
        for role in ("dark", "high_contrast", "light"):
            shell.set_theme(role)
            shell.flush_theme()
            panel._flush()
            panel.show_window(stage.window)
            _assert_plate_beneath(stage)
    for _round in range(10):
        panel._build(stage)
        _assert_plate_beneath(stage)


def test_the_plate_frames_the_window_and_is_a_click_target(shell: DesignerApp) -> None:
    panel = _open(shell)
    stage = panel.stages[0]
    shell.root.update()
    tokens = design_tokens(panel._spec)
    frame, plate = stage.view.frame, stage.plate
    assert str(plate.master) == str(stage.stage)
    assert plate.winfo_rootx() <= frame.winfo_rootx() - 1
    assert plate.winfo_rooty() <= stage.title.master.winfo_rooty() - 1
    assert plate.winfo_rootx() + plate.winfo_width() >= frame.winfo_rootx() + frame.winfo_width()
    assert plate.winfo_rooty() + plate.winfo_height() >= frame.winfo_rooty() + frame.winfo_height()
    assert str(plate.cget("highlightbackground")).lower() == tokens.plate_border.lower()
    assert str(stage.scroll.cget("background")).lower() == tokens.stage.lower()
    assert plate.bind("<ButtonPress-1>")  # a click on the edge selects the window


def test_the_title_bar_and_strip_use_the_designer_styles(shell: DesignerApp) -> None:
    panel = _open(shell)
    stage = panel.stages[0]
    assert str(stage.title.cget("style")) == "Designer.Titlebar.TLabel"
    assert str(stage.kind.cget("style")) == "Designer.Caption.TLabel"
    assert str(stage.title.master.cget("style")) == "Designer.Titlebar.TFrame"
    assert str(stage.stage.cget("style")) == "Designer.Stage.TFrame"
    labels = stage.strip.winfo_children()
    assert labels and all(str(w.cget("style")) == "Designer.Strip.TLabel" for w in labels)
    assert stage.title.cget("text") and stage.kind.cget("text")


def test_the_users_widgets_keep_their_own_styles(shell: DesignerApp) -> None:
    panel = _open(shell)
    stage = panel.stages[0]
    styles = [
        str(w.cget("style"))
        for w in stage.view.inner.values()
        if "style" in w.keys()  # noqa: SIM118 - a Tk widget, not a dict
    ]
    assert styles and not any(style.startswith("Designer") for style in styles)


def test_the_error_card_is_framed_in_the_error_colour(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = _open(shell)
    stage = panel.stages[0]
    monkeypatch.setattr(panel.engine, "build", lambda *_a: (_ for _ in ()).throw(RuntimeError("x")))
    panel._build(stage)
    tokens = design_tokens(panel._spec)
    assert stage.view is None and stage.error is not None
    assert str(stage.card.cget("highlightbackground")).lower() == tokens.error_border.lower()
    assert [str(c.cget("style")) for c in stage.card.winfo_children()][:2] == [
        "Designer.Error.TLabel",
        "Designer.Muted.TLabel",
    ]
    _assert_plate_beneath(stage)


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: f"{s.name}-{s.role}")
def test_indicator_colours_come_from_the_tokens_and_reach_3_to_1(
    host: Any,  # noqa: F811
    spec: ThemeSpec,
) -> None:
    tokens = design_tokens(spec)
    overlay = Overlay(host)
    overlay.restyle(spec)
    box = Rect(10, 10, 60, 30)
    for state, expected in (("allowed", tokens.target_allowed), ("denied", tokens.target_denied)):
        overlay.show_target(box, state)  # type: ignore[arg-type]
        colours = {str(s.cget("background")).lower() for s in overlay.target.shown()}
        assert colours == {expected.lower()}
        for surface in (spec.colors["bg"], tokens.stage, tokens.titlebar):
            assert contrast(expected, surface) >= NON_TEXT_CONTRAST, (state, surface)
    overlay.show_target(Rect(10, 10, 60, 3), "pending", bar=True)
    assert (
        str(overlay.target.shown()[0].cget("background")).lower() == spec.colors["border"].lower()
    )
    overlay.show_selection([box], primary=box)
    ring = {str(s.cget("background")).lower() for s in overlay.selection.shown()}
    assert tokens.ring.lower() in ring and spec.colors["bg"].lower() in ring
    overlay.show_band(Rect(5, 5, 40, 20))
    assert {str(s.cget("background")).lower() for s in overlay.band.shown()} == {
        tokens.ring.lower()
    }
    assert contrast(tokens.ring, tokens.stage) >= NON_TEXT_CONTRAST


def test_the_resize_handles_are_unchanged(host: Any) -> None:  # noqa: F811
    spec = load_theme_specs()[0]
    overlay = Overlay(host)
    overlay.restyle(spec)
    box = Rect(40, 40, 80, 30)
    overlay.show_selection([box], primary=box, handles=True)
    handles = overlay.handles.shown()
    assert len(handles) == len(HANDLES) == 8
    assert {str(h.cget("background")).lower() for h in handles} == {spec.colors["primary"].lower()}
    assert {int(h.place_info()["width"]) for h in handles} == {9}
    assert [str(h.cget("cursor")) for h in handles] == [cursor for _edge, cursor in HANDLES]
