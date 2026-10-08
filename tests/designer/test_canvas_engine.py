"""The canvas engine, design mode, overlay and stage (spec dnd-selection 2-4, 13; Step 13a)."""

from __future__ import annotations

import gc
import tkinter
import weakref
from pathlib import Path
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.core import Prop, default_registry, read_ui, read_ui_string
from pyguibud.core.commands import InsertNode, SetProp
from pyguibud.core.model import GridCell, Include, Widget, Window
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas import design, engine
from pyguibud.designer.canvas.design import DESIGN_BINDTAGS, DESIGN_TAG, apply_design_mode
from pyguibud.designer.canvas.engine import CanvasEngine
from pyguibud.designer.editing import new_node
from pyguibud.designer.templates import TEMPLATES
from tests.codegen.test_parity import _widget, diff
from tests.designer.conftest import best_of

pytestmark = pytest.mark.gui

RICH = Path(__file__).resolve().parents[1] / "codegen" / "data" / "rich.ui"
HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"
HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)
TWO_WINDOWS = (
    HEADER + '<window id="one" kind="main"><layout type="grid"/>'
    '<widget class="Button" id="btn"><prop name="text">Go</prop><cell row="0" column="0"/>'
    "</widget></window>"
    '<window id="two" kind="dialog"><layout type="grid"/>'
    '<widget class="Label" id="lbl"><cell row="0" column="0"/></widget></window></pyguibud-ui>'
)
WITH_INCLUDE = (
    HEADER + '<window id="main" kind="main"><layout type="grid"/>'
    '<include id="inc" src="#" component="part"><cell row="0" column="0"/></include></window>'
    '<window id="part" kind="component"><layout type="grid"/></window></pyguibud-ui>'
)


@pytest.fixture
def host(designer_root: Any) -> Any:
    frame = ttk.Frame(designer_root)
    yield frame
    frame.destroy()


def _rich_view(host: Any, monkeypatch: pytest.MonkeyPatch | None = None) -> Any:
    document = read_ui(str(RICH)).document
    if monkeypatch is not None:  # the embed-only build, before design mode
        monkeypatch.setattr(engine, "apply_design_mode", lambda _frame: None)
    return CanvasEngine(default_registry()).build(document, document.children[0], host)


# ---------------------------------------------------------------- engine
def test_every_template_renders_without_an_error_card(shell: DesignerApp) -> None:
    for template in TEMPLATES:
        assert shell.new_from_template(template.id)
        for stage in shell.shell.canvas.stages:
            shell.shell.canvas.show_window(stage.window)
            assert stage.error is None and stage.view is not None, template.id
            in_row = [c for c in stage.stage.grid_slaves(row=2, column=0) if c is not stage.card]
            assert in_row == [stage.view.frame]  # exactly one window frame on the stage


def test_node_of_round_trips_for_every_node(host: Any) -> None:
    view = _rich_view(host)
    assert len(view.nodes) >= 20
    for key, node in view.nodes.items():
        assert view.node_of(view.outer[key]) is node
        assert view.node_of(view.inner[key]) is node
    scrolled = next(
        n for n in view.nodes.values() if getattr(n, "class_name", "") == "ScrolledFrame"
    )
    # internal parts (the ScrolledFrame's viewport canvas and scrollbar) map to their node
    parts = view.outer[id(scrolled)].winfo_children()
    assert len(parts) == 2 and all(view.node_of(part) is scrolled for part in parts)
    view.destroy()


def test_the_main_window_template_shows_caption_strip_and_status(shell: DesignerApp) -> None:
    shell.new_from_template("main_window")
    stage = shell.shell.canvas.stages[0]
    assert stage.title.cget("text") == "Main window"
    assert stage.kind.cget("text") == "Main window"
    labels = [w.cget("text") for w in stage.strip.winfo_children()]
    assert labels == ["File"]  # the mnemonic underscore became an underline
    assert int(stage.strip.winfo_children()[0].cget("underline")) == 0
    window = stage.window
    assert window.statusbar is not None and id(window.statusbar) in stage.view.outer  # type: ignore[union-attr]
    assert str(stage.stage.grid_columnconfigure(0)["minsize"]) == "480"


def test_a_failing_window_shows_an_error_card_and_the_others_render(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = shell.shell.canvas
    real = panel.engine.build

    def build(document: Any, window: Window, host: Any) -> Any:
        if window.id == "one":
            raise RuntimeError("factory exploded")
        return real(document, window, host)

    monkeypatch.setattr(panel.engine, "build", build)
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    first, second = panel.stages
    panel.show_window(first.window)
    assert first.view is None and first.error == "factory exploded"
    texts = [c.cget("text") for c in first.card.winfo_children()]
    assert texts[0] == "This window cannot be drawn on the canvas: factory exploded"
    assert texts[1] == "0 errors"
    panel.show_window(second.window)
    assert second.view is not None and second.error is None


def test_an_unexpanded_include_is_a_placeholder(shell: DesignerApp) -> None:
    shell.session.open_result(read_ui_string(WITH_INCLUDE, source="inc"), name="inc")
    stage = shell.shell.canvas.stages[0]
    include = next(n for n in stage.window.walk() if isinstance(n, Include))
    placeholder = stage.view.outer[id(include)]  # type: ignore[union-attr]
    assert placeholder.winfo_class() == "TLabelframe"
    assert placeholder.cget("text") == "Included: part"


# ---------------------------------------------------------------- design mode
def test_design_mode_changes_only_takefocus_and_the_bindtags(
    host: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    view = _rich_view(host, monkeypatch)
    widgets = {key: view.outer[key] for key in view.nodes} | {
        -key: view.inner[key] for key in view.nodes
    }
    before = {key: _widget(w) for key, w in widgets.items()}
    apply_design_mode(view.frame)
    after = {key: _widget(w) for key, w in widgets.items()}
    for key in before:
        before[key].pop("takefocus", None)
        after[key].pop("takefocus", None)
    assert diff(before, after) == []
    kept = []
    for widget in design.descendants(view.frame):
        tags = widget.bindtags()
        if tags != DESIGN_BINDTAGS:
            assert tags == (DESIGN_TAG, str(widget))
            assert set(widget.bind()) <= {"<Configure>", "<Map>", "<Unmap>"}
            kept.append(widget)
    # R3: exactly the ScrolledFrame's content frame and its viewport canvas keep their tag
    scrolled = next(
        n for n in view.nodes.values() if getattr(n, "class_name", "") == "ScrolledFrame"
    )
    content = view.inner[id(scrolled)]
    assert sorted(map(str, kept)) == sorted([str(content), str(content.master)])
    view.destroy()


def test_scrolled_frame_still_sizes_itself_in_design_mode(host: Any) -> None:
    host.pack()
    view = _rich_view(host)
    view.frame.pack()
    host.update_idletasks()
    scrolled = next(
        n for n in view.nodes.values() if getattr(n, "class_name", "") == "ScrolledFrame"
    )
    viewport = view.inner[id(scrolled)].master
    assert viewport.cget("scrollregion")  # the <Configure> binding ran
    view.destroy()


def test_input_reaches_no_canvas_widget(host: Any) -> None:
    host.pack()
    view = _rich_view(host)
    view.frame.pack()
    host.update()
    by_class = {}
    for node in view.nodes.values():
        if isinstance(node, Widget) and node.class_name not in by_class:
            by_class[node.class_name] = view.inner[id(node)]
    entry, check, combo, button = (
        by_class[name] for name in ("Entry", "Checkbutton", "Combobox", "Button")
    )
    states = [(entry.get(), check.instate(["selected"]), combo.get())]
    for widget in (entry, check, combo, button):
        widget.event_generate("<ButtonPress-1>", x=3, y=3)
        widget.event_generate("<ButtonRelease-1>", x=3, y=3)
        widget.event_generate("<KeyPress>", keysym="a")
        widget.event_generate("<KeyPress>", keysym="space")
    host.update()
    assert [(entry.get(), check.instate(["selected"]), combo.get())] == states
    assert not button.instate(["pressed"])
    popdown = f"{combo}.popdown"
    assert not int(host.tk.call("winfo", "exists", popdown)) or not int(
        host.tk.call("winfo", "ismapped", popdown)
    )
    assert host.focus_get() not in (entry, check, combo, button)
    view.destroy()


def test_a_click_on_a_canvas_button_selects_it(shell: DesignerApp, designer_root: Any) -> None:
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    button_node = next(n for n in stage.window.walk() if getattr(n, "id", "") == "btn")
    button = stage.view.inner[id(button_node)]
    designer_root.update_idletasks()
    button.event_generate("<ButtonPress-1>", x=2, y=2)
    assert shell.session.selection.node is button_node
    assert shell.session.selection.origin == "canvas"
    assert not button.instate(["pressed"])
    assert stage.overlay.selection.shown()  # outlined


# ---------------------------------------------------------------- rebuilds
def test_an_edit_rebuilds_after_idle_and_swaps_one_frame(
    shell: DesignerApp, designer_root: Any
) -> None:
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    panel = shell.shell.canvas
    stage = panel.stages[0]
    old = stage.view
    assert old is not None and shell.session.stack is not None
    button = next(n for n in stage.window.walk() if getattr(n, "id", "") == "btn")
    shell.session.select(button, origin="tree")
    outcome = shell.session.stack.execute(SetProp(button, Prop(name="text", value="Changed")))
    assert outcome.accepted
    assert stage.view is old  # listeners only schedule
    designer_root.update()
    assert stage.view is not old and stage.view is not None
    assert stage.view.inner[id(button)].cget("text") == "Changed"
    assert not old.frame.winfo_exists()
    assert [c for c in stage.stage.grid_slaves(row=2, column=0)] == [stage.view.frame]
    assert shell.session.selection.node is button and stage.overlay.selection.shown()
    shell.session.stack.undo()
    designer_root.update()
    assert stage.view.inner[id(button)].cget("text") == "Go"


def _window_with_labels(shell: DesignerApp, count: int) -> tuple[Any, Window, Widget]:
    """``main_window`` with a Frame of ``count`` Labels in a 10-column grid (one edit)."""
    session = shell.session
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    assert isinstance(window, Window)
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    for index in range(count):
        label = new_node(session.registry.require("Label"), None)
        assert isinstance(label, Widget)
        label.id = f"lbl{index}"
        label.placement = GridCell(row=index // 10, column=index % 10)
        frame.insert_child(index, label)
    assert session.stack.execute(InsertNode(window, frame)).accepted
    return session.document, window, frame


def test_render_budget_of_a_200_widget_window(shell: DesignerApp, designer_root: Any) -> None:
    """Spec 13: rendering a 200-widget window takes at most 250 ms (x3 for CI and coverage)."""
    document, window, _frame = _window_with_labels(shell, 200)
    designer_root.update()
    stage = shell.shell.canvas.stages[0]
    views: list[Any] = []
    try:
        took = best_of(
            lambda: views.append(shell.shell.canvas.engine.build(document, window, stage.stage)),
            repeat=5,
        )
    finally:
        for view in views:
            view.destroy()
    assert took < 0.250 * 3


def test_an_edit_outlines_the_shown_tab_at_most_twice(
    shell: DesignerApp, designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QA-13a-05: the selection outline ran four times per edit (twice on a stale view)."""
    _document, _window, frame = _window_with_labels(shell, 20)
    designer_root.update()
    shell.session.select(frame, origin="tree")
    designer_root.update()
    canvas, calls = shell.shell.canvas, []
    real = canvas._outline

    def counted(stage: Any, *, reveal_node: bool) -> None:
        calls.append(stage)
        real(stage, reveal_node=reveal_node)

    monkeypatch.setattr(canvas, "_outline", counted)
    shell.shell.drag.insert_widget("Button")  # one edit that also selects the new widget
    designer_root.update()
    assert 1 <= len(calls) <= 2  # the rebuild, plus a <Configure> of the stage at most
    stage = canvas.stages[0]
    assert stage.view is not None and stage.overlay.selection.shown()  # still outlined


def test_rebuilds_leak_nothing(shell: DesignerApp, designer_root: Any) -> None:
    shell.session.open_result(read_ui(str(RICH)), name="rich")
    panel = shell.shell.canvas
    stage = panel.stages[0]

    def state() -> tuple[Any, ...]:
        designer_root.update_idletasks()
        return (
            set(designer_root.winfo_children()),
            len(designer_root.tk.call("image", "names")),
            {seq: designer_root.bind_class(DESIGN_TAG, seq) for seq in design.SEQUENCES},
            len(stage.stage.winfo_children()),
        )

    panel._build(stage)
    before = state()
    globals_before = len(designer_root.tk.call("info", "globals"))
    old = stage.view
    assert old is not None
    dead = [weakref.ref(old.frame), *(weakref.ref(w) for w in list(old.inner.values())[:5])]
    del old
    for _round in range(50):
        panel._build(stage)
    gc.collect()
    assert state() == before
    assert len(designer_root.tk.call("info", "globals")) <= globals_before
    assert all(ref() is None for ref in dead)  # the swapped-out widgets are released


def test_dispose_removes_the_design_bindings(designer_root: Any) -> None:
    app = DesignerApp(designer_root)
    assert designer_root.bind_class(DESIGN_TAG)
    app.dispose()
    assert not designer_root.bind_class(DESIGN_TAG)


def test_overlay_draws_a_dashed_denied_target(host: Any) -> None:
    from pyguibud.designer.canvas.overlay import Overlay
    from pyguibud.designer.geometry import Rect
    from pyguibud.designer.theme import load_theme_specs

    overlay = Overlay(host)
    overlay.restyle(load_theme_specs()[0])
    overlay.show_target(Rect(10, 10, 60, 30), "allowed")
    assert len(overlay.target.shown()) == 4
    overlay.show_target(Rect(10, 10, 60, 30), "denied")
    denied = overlay.target.shown()
    assert len(denied) > 4 and all(str(s.cget("cursor")) == "X_cursor" for s in denied)
    overlay.show_target(Rect(10, 10, 60, 3), "pending", bar=True)
    assert len(overlay.target.shown()) == 1
    overlay.show_target(None, "allowed")
    assert not overlay.target.shown()
    assert isinstance(denied[0], tkinter.Frame)


INVALID = (
    HEADER + '<variables><var id="n" type="int"/></variables>'
    '<window id="main" kind="main"><menubar><menu id="mnu"><prop name="text">_File</prop>'
    '<action id="act"><prop name="image" ref="gone"/><prop name="text">Quit</prop></action>'
    '</menu></menubar><layout type="grid"/>'
    '<widget class="Label" id="lbl"><prop name="image" ref="gone"/><prop name="text">x</prop>'
    '<cell row="0" column="0"/></widget>'
    '<widget class="Entry" id="ent" bind="undeclared"><cell row="1" column="0"/></widget>'
    '<widget class="Radiobutton" id="rad" bind="n"><prop name="value">abc</prop>'
    '<cell row="2" column="0"/></widget>'
    '<widget class="Notebook" id="nbk"><cell row="3" column="0"/>'
    '<widget class="Frame" id="pg"><layout type="grid"/>'
    '<page image="gone"><prop name="text">P</prop></page></widget></widget>'
    "</window></pyguibud-ui>"
)


def test_lenient_lookups_draw_an_invalid_document(shell: DesignerApp) -> None:
    """Unknown images, an undeclared variable and a non-int radio value (spec 2.1, 2.7)."""
    shell.session.open_result(read_ui_string(INVALID, source="invalid"), name="invalid")
    assert shell.session.report().errors  # it really is invalid
    stage = shell.shell.canvas.stages[0]
    assert stage.error is None and stage.view is not None
    radio = next(n for n in stage.window.walk() if getattr(n, "id", "") == "rad")
    assert str(stage.view.inner[id(radio)].cget("value")) == "abc"


def test_a_failure_inside_the_build_leaves_no_frame_behind(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    import ttkbootstrap

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("no buttons today")

    monkeypatch.setattr(ttkbootstrap, "Button", explode)
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    stage = shell.shell.canvas.stages[0]
    assert stage.view is None and stage.error == "no buttons today"
    assert stage.stage.grid_slaves(row=2, column=0) == [stage.card]
    chrome = {str(w) for w in (stage.card, stage.strip, stage.title.master)}
    leftovers = [
        w
        for w in stage.stage.winfo_children()
        if str(w) not in chrome and w.winfo_class() != "Frame"  # overlay strips are tk Frames
    ]
    assert leftovers == []


def test_a_rebuild_keeps_the_shown_notebook_page(shell: DesignerApp, designer_root: Any) -> None:
    shell.new_from_template("settings")
    stage = shell.shell.canvas.stages[0]
    check = next(n for n in stage.window.walk() if getattr(n, "id", "") == "chk_logging")
    shell.session.select(check, origin="tree")
    designer_root.update_idletasks()
    page = next(n for n in stage.window.walk() if getattr(n, "id", "") == "frm_advanced")
    notebook = stage.view.inner[id(page.parent)]  # type: ignore[union-attr]
    assert str(notebook.select()) == str(stage.view.outer[id(page)])  # type: ignore[union-attr]
    assert shell.session.stack is not None
    assert shell.session.stack.execute(SetProp(check, Prop(name="text", value="Log more"))).accepted
    designer_root.update()
    notebook = stage.view.inner[id(page.parent)]  # type: ignore[union-attr]
    assert str(notebook.select()) == str(stage.view.outer[id(page)])  # type: ignore[union-attr]
    assert stage.overlay.selection.shown()


def test_a_theme_switch_rebuilds_the_canvas(shell: DesignerApp, designer_root: Any) -> None:
    shell.new_from_template("login_form")
    stage = shell.shell.canvas.stages[0]
    old = stage.view
    assert shell.set_theme("dark")
    shell.flush_theme()
    designer_root.update()
    assert stage.view is not None and stage.view is not old


# ---------------------------------------------------------------- properties a class lacks
def _drawn(app: DesignerApp) -> None:
    app.root.update()
    for stage in app.shell.canvas.stages:
        app.shell.canvas.show_window(stage.window)
        assert stage.error is None and stage.view is not None, stage.error


def test_a_text_on_the_hello_notebook_is_kept_and_the_window_still_draws(
    shell: DesignerApp,
) -> None:
    """Regression: SetProp(text) on a Notebook (no such property: a validator warning) was
    accepted, then the canvas failed with ``unknown option "-text"``."""
    assert shell.open_path(HELLO)
    document, stack = shell.session.document, shell.session.stack
    assert document is not None and stack is not None
    notebook = document.find("nbk_main")
    assert isinstance(notebook, Widget) and notebook.class_name == "Notebook"
    for name, value in (("text", "Tab strip"), ("state", "disabled")):
        assert stack.execute(SetProp(notebook, Prop(name=name, value=value))).accepted
        _drawn(shell)
    assert notebook.props["text"].value == "Tab strip"  # kept (and saved), only ignored


def test_every_offered_field_of_every_class_draws(shell: DesignerApp, tmp_path: Path) -> None:
    """Each core class x each property field the inspector offers (foreign ones included):
    reset, then set to a sample value; the guard accepts or refuses, and the canvas draws."""
    from pyguibud.designer.properties import commit_commands, field_rows
    from tests.prop_sweep import sample, sweep_ui, widget_classes

    registry = default_registry()
    assert shell.open_path(sweep_ui(tmp_path, registry))
    _drawn(shell)
    document, stack = shell.session.document, shell.session.stack
    assert document is not None and stack is not None
    widgets = [n for n in document.walk() if isinstance(n, Widget)]
    assert len(widgets) == len(widget_classes(registry)) >= 20
    edits = [
        (node, field, registry.require(node.class_name).property(field.key[5:]))
        for node in widgets
        for field in field_rows([node], registry, document)
        if field.key.startswith("prop:")
    ]
    for phase in ("reset", "sample"):
        accepted = 0
        for node, field, definition in edits:
            if phase == "reset":
                value = None
            elif definition is None:
                value = "Foreign"
            else:
                value = "img" if definition.type == "image" else sample(definition)
            accepted += stack.execute(commit_commands([node], field, value)).accepted
        assert accepted >= 60, phase  # the sweep really edits
        _drawn(shell)
