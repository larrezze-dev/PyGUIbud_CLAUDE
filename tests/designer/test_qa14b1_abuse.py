"""QA pass 1 of Step 14b.1 "Resize": abuse cases (spec direct-manipulation 11, Q1-Q6, Q12-Q13).

Findings are named QA-14b1-NN; a test for an open finding is ``xfail(strict=True)`` so that the
debugger flips it when the fix lands.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core.commands import CommandStack, SetField
from pyguibud.core.model import Widget, Window
from pyguibud.core.registry import default_registry
from pyguibud.core.xml_io import read_ui, write_ui
from pyguibud.designer import sizing
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.properties import field_rows
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _settle,
    app,
    tk_errors,
)
from tests.designer.test_resize_gui import _drag, _pitch

DATA = Path(__file__).parent / "data" / "qa14b1_sizes.ui"


# ---------------------------------------------------------------- helpers
@pytest.fixture(autouse=True)
def _withdraw_after(designer_root: Any) -> Iterator[None]:
    """``_open`` maps the shared root (an unmapped canvas tab is 1 x 1 px); withdraw it after."""
    yield
    designer_root.withdraw()
    designer_root.geometry("")


def _open(app: DesignerApp, root: Any) -> None:  # noqa: F811
    """The fixture document on a mapped root (no focus is taken from other windows)."""
    root.geometry("1400x900")
    root.deiconify()
    app.session.open_document(read_ui(DATA), path=None)
    _settle(root, 5)
    assert not app.session.report().errors  # the fixture itself is valid
    said: list[str] = []
    drag: Any = app.shell.drag
    status = drag._status

    def spy(text: str) -> None:
        said.append(text)
        status(text)

    drag._status = spy
    app._qa_said = said  # type: ignore[attr-defined]


def _said(app: DesignerApp) -> list[str]:  # noqa: F811
    """What the drag controller posted (a later focus hint may replace it in the status bar)."""
    return list(app._qa_said)  # type: ignore[attr-defined]


def _node(app: DesignerApp, ident: str) -> Any:  # noqa: F811
    document = app.session.document
    assert document is not None
    return next(n for n in document.walk() if getattr(n, "id", None) == ident)


def _pick(app: DesignerApp, root: Any, ident: str, origin: str = "tree") -> Any:  # noqa: F811
    node = _node(app, ident)
    app.session.select(node, origin=origin)
    _settle(root)
    return node


def _kinds(app: DesignerApp) -> dict[str, str]:  # noqa: F811
    return dict(_stage_of(app).overlay.kinds)


def _stage_of(app: DesignerApp) -> Any:  # noqa: F811
    stage = app.shell.canvas.current_stage()
    assert stage is not None
    return stage


def _stack(app: DesignerApp) -> CommandStack:  # noqa: F811
    stack = app.session.stack
    assert stack is not None
    return stack


def _shown_handle(app: DesignerApp, edge: str) -> Any:  # noqa: F811
    overlay = _stage_of(app).overlay
    edges: list[str] = [e for e in sizing.EDGES if e in overlay.kinds]
    return overlay.handles.shown()[edges.index(edge)]


# ---------------------------------------------------------------- Q1 clamping
@pytest.mark.gui
def test_q1_far_drags_clamp_to_one_unit_and_never_write_zero(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set")
    stack, before = _stack(app), _stack(app).index
    handle = _shown_handle(app, "e")
    page = _stage_of(app).page
    # Motion far off-screen: the value shown is clamped to 1 unit.
    _drag(designer_root, handle, -50_000, 0, release=False)
    assert "to 1 character." in _said(app)[-1]
    # Release far off-screen cancels; nothing recorded.
    handle.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=-50_000, rooty=0, state=0x100)
    _settle(designer_root)
    assert label.props["width"].value == "9" and stack.index == before
    # Release at the page's left edge (inside): clamped to 1, never 0.
    inside = page.winfo_rootx() + 1 - (handle.winfo_rootx() + 3)
    _drag(designer_root, _shown_handle(app, "e"), inside, 0)
    assert label.props["width"].value == "1" and stack.index == before + 1
    # The left handle dragged right past the opposite edge: also 1.
    _drag(designer_root, _shown_handle(app, "w"), 400, 0)
    assert label.props["width"].value == "1"
    assert tk_errors == []


@pytest.mark.gui
def test_q1_status_does_not_promise_a_value_where_a_release_cancels(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Off the stage a release cancels (spec 2.7), so the status must not say "Release to set"."""
    _open(app, designer_root)
    _pick(app, designer_root, "lbl_set")
    _drag(designer_root, _shown_handle(app, "e"), -50_000, 0, release=False)
    try:
        assert not _said(app)[-1].startswith("Release to set")
    finally:
        app.shell.drag.cancel()
    assert tk_errors == []


# ---------------------------------------------------------------- Q2 read-only
@pytest.mark.gui
def test_q2_read_only_documents_never_change_by_handle_key_or_double_click(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    monkeypatch.setattr(CommandStack, "read_only", property(lambda _self: True))
    label = _pick(app, designer_root, "lbl_set")
    assert _kinds(app) == {}
    stack = _stack(app)
    before = stack.index
    for action in ("edit.size_wider", "edit.size_narrower", "edit.size_taller"):
        app.registry.invoke(action)
        _settle(designer_root)
    assert "read-only" in app.shell._message
    # The safety net: a press reached programmatically still changes nothing.
    drag: Any = app.shell.drag
    drag.reset_size(label, "e")
    window = _pick(app, designer_root, "main")
    assert _kinds(app) == {}
    drag.reset_size(window, "se")
    app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert label.props["width"].value == "9" and stack.index == before
    assert (window.min_width, window.min_height) == (480, 320)
    assert tk_errors == []


# ---------------------------------------------------------------- Q3 interruptions
@pytest.mark.gui
def test_q3_undo_mid_drag_cancels_and_keeps_the_redo(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set")
    stack = _stack(app)
    assert stack.execute(sizing.size_command(label, [("width", 12)])).accepted  # type: ignore[arg-type]
    _settle(designer_root)
    _pick(app, designer_root, "lbl_set")
    handle = _shown_handle(app, "e")
    _drag(designer_root, handle, 60, 0, release=False)
    app.registry.invoke("edit.undo")  # Ctrl+Z with the button still held
    _settle(designer_root)
    assert app.shell.drag.state == "idle"
    handle.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=0, rooty=0, state=0x100)
    _settle(designer_root)
    assert label.props["width"].value == "9" and stack.can_redo
    assert tk_errors == []


@pytest.mark.gui
def test_q3_delete_mid_drag_never_writes_to_the_deleted_element(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set", origin="canvas")
    stack = _stack(app)
    before = stack.index
    handle = _shown_handle(app, "e")
    x = handle.winfo_rootx() + 60
    _drag(designer_root, handle, 60, 0, release=False)
    app.registry.invoke("edit.delete")
    _settle(designer_root)
    handle.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=x, rooty=0, state=0x100)
    _settle(designer_root)
    assert stack.index == before + 1 and stack.undo_text != "Resize"
    assert label.props["width"].value == "9"
    stack.undo()
    assert label.parent is not None and label.props["width"].value == "9"
    assert tk_errors == []


@pytest.mark.gui
def test_q3_theme_switch_mid_drag_raises_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set")
    pitch = _pitch(app, label)[0]
    handle = _shown_handle(app, "e")
    x, y = handle.winfo_rootx() + 3, handle.winfo_rooty() + 3
    _drag(designer_root, handle, round(2 * pitch), 0, release=False)
    app.set_theme("dark")
    app.flush_theme()
    _settle(designer_root)
    handle.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=x + round(2 * pitch), rooty=y, state=0x100
    )
    _settle(designer_root)
    assert label.props["width"].value in ("9", "11")  # applied or cancelled, never garbage
    assert not _stage_of(app).overlay.band.shown()
    assert tk_errors == []


# ---------------------------------------------------------------- Q4 pack children
@pytest.mark.gui
def test_q4_ctrl_drag_on_a_pack_child_sizes_and_fill_hides_the_axis(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    button = _pick(app, designer_root, "btn_pack")
    assert _kinds(app) == {"e": "size", "w": "size"}  # no span handles under pack
    _drag(designer_root, _shown_handle(app, "e"), 60, 0, state=0x4)  # Ctrl held
    assert "width" in button.props and _stack(app).undo_text == "Resize"
    _pick(app, designer_root, "ent_fill")
    assert _kinds(app) == {}  # Entry: only a width axis, and pack fill x hides it
    app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert "(Fill)" in app.shell._message
    assert "width" not in _node(app, "ent_fill").props
    assert tk_errors == []


# ---------------------------------------------------------------- Q5 key storms
@pytest.mark.gui
def test_q5_held_size_keys_clamp_at_the_maximum_in_one_undo_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set")
    stack = _stack(app)
    assert stack.execute(sizing.size_command(label, [("width", 9_995)])).accepted  # type: ignore[arg-type]
    _settle(designer_root)
    label = _pick(app, designer_root, "lbl_set")
    before = stack.index
    for _ in range(12):
        app.registry.invoke("edit.size_wider")
        _settle(designer_root, 1)
    for _ in range(200):  # auto-repeat without idle time: dropped, never a storm
        app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert label.props["width"].value == str(sizing.MAX_SIZE)
    assert stack.index == before + 1
    stack.undo()
    assert label.props["width"].value == "9995"
    assert tk_errors == []


# ---------------------------------------------------------------- Q6 window clamping
@pytest.mark.gui
def test_q6_window_corner_to_50000_px_clamps_to_10000(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    window = _pick(app, designer_root, "main")
    assert sorted(_kinds(app)) == ["e", "s", "se"]
    _drag(designer_root, _shown_handle(app, "se"), 50_000, 50_000)
    assert (window.min_width, window.min_height) == (sizing.MAX_SIZE, sizing.MAX_SIZE)
    assert _stack(app).undo_text == "Resize window"
    assert tk_errors == []


def test_qa14b1_02_window_step_without_a_measure_never_builds_a_negative_minimum() -> None:
    """Pure: with no shown stage, a step down from an unset minimum built min_width = -8."""
    document = read_ui(DATA).document
    window = next(n for n in document.walk() if isinstance(n, Window))
    window.min_width = None
    built = sizing.step_command(window, None, 0, -1, None)
    assert isinstance(built, str) or (isinstance(built, SetField) and built.value is None)


def test_qa14b1_02_widget_step_without_a_measure_never_shrinks() -> None:
    """Pure: an unset Text width (80 characters by default) stepped "wider" with nothing
    measured estimated the start from 0 px and wrote width = 2."""
    document = read_ui(DATA).document
    text = next(n for n in document.walk() if getattr(n, "id", None) == "txt")
    built = sizing.step_command(text, default_registry().get("Text"), 0, 1, None)
    assert isinstance(built, str)


@pytest.mark.gui
def test_qa14b1_02_size_keys_on_a_window_that_failed_to_draw_change_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """A window whose canvas build failed (a plugin raising while rendering, M25) shows the
    error card; nothing can be measured, so a size key must refuse, not guess."""
    _open(app, designer_root)
    canvas = app.shell.canvas

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("a plugin factory failed")

    monkeypatch.setattr(canvas.engine, "build", boom)
    canvas._render()
    _settle(designer_root)
    assert _stage_of(app).view is None  # the error card
    text = _pick(app, designer_root, "txt")
    app.registry.invoke("edit.size_wider")  # "Increase width"
    _settle(designer_root)
    window = _pick(app, designer_root, "main")
    window.min_width = None  # automatic (outside the stack: no rebuild)
    app.registry.invoke("edit.size_narrower")
    _settle(designer_root)
    assert "width" not in text.props and window.min_width is None
    assert tk_errors == []


# ---------------------------------------------------------------- pages, classes, axes
@pytest.mark.gui
def test_page_children_have_no_handles_and_keys_change_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    stack = _stack(app)
    before = stack.index
    for ident in ("frm_page", "pane_a"):
        node = _pick(app, designer_root, ident)
        assert _kinds(app) == {}
        app.registry.invoke("edit.size_wider")
        _settle(designer_root)
        assert app.shell._message and "width" not in node.props
    assert stack.index == before
    assert tk_errors == []


@pytest.mark.gui
def test_vertical_scale_text_treeview_and_checkbutton_axes(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    stack = _stack(app)
    scale = _pick(app, designer_root, "scl_v")
    kinds = _kinds(app)
    assert kinds["n"] == kinds["s"] == "size" and kinds["e"] == kinds["se"] == "span"
    _drag(designer_root, _shown_handle(app, "s"), 0, 40)
    assert "length" in scale.props and int(scale.props["length"].value) % 4 == 0
    text = _pick(app, designer_root, "txt")
    assert set(_kinds(app).values()) == {"size"}
    pitch = _pitch(app, text)
    before = stack.index
    _drag(designer_root, _shown_handle(app, "se"), round(3 * pitch[0]), round(2 * pitch[1]))
    assert {"width", "height"} <= set(text.props) and stack.index == before + 1
    stack.undo()
    assert "width" not in text.props and "height" not in text.props
    tree = _pick(app, designer_root, "tree")
    assert _kinds(app)["s"] == "size" and _kinds(app)["e"] == "span"
    _drag(designer_root, _shown_handle(app, "s"), 0, round(2 * _pitch(app, tree)[1]))
    assert "height" in tree.props
    check = _pick(app, designer_root, "chk")
    assert set(_kinds(app).values()) == {"span"}
    app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert app.shell._message == "'chk' has no width that can be changed."
    assert "width" not in check.props
    assert tk_errors == []


# ---------------------------------------------------------------- undo grouping
@pytest.mark.gui
def test_key_steps_then_selection_change_then_undo_are_separate_steps(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    stack = _stack(app)
    label = _pick(app, designer_root, "lbl_set")
    for _ in range(2):
        app.registry.invoke("edit.size_wider")
        _settle(designer_root)
    _pick(app, designer_root, "chk")
    _pick(app, designer_root, "lbl_set")
    app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert label.props["width"].value == "12"
    stack.undo()
    assert label.props["width"].value == "11"
    stack.undo()
    assert label.props["width"].value == "9"
    stack.redo()
    stack.redo()
    _settle(designer_root)  # a pending rebuild drops size keys (key repeat guard)
    assert label.props["width"].value == "12"
    app.registry.invoke("edit.size_taller")
    _settle(designer_root)
    assert app.shell._message == "'lbl_set' has no height that can be changed."
    assert tk_errors == []


@pytest.mark.gui
def test_window_key_steps_below_the_contents_clear_then_refuse(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    window = _pick(app, designer_root, "main")
    measured = app.shell.canvas.measure(window)
    assert measured is not None
    stack = _stack(app)
    assert stack.execute(SetField(window, "min_width", measured.natural[0] + 4)).accepted
    _settle(designer_root)
    _pick(app, designer_root, "main")
    app.registry.invoke("edit.size_narrower")
    _settle(designer_root)
    assert window.min_width is None
    before = stack.index
    app.registry.invoke("edit.size_narrower")
    _settle(designer_root)
    assert app.shell._message == "'main' cannot be narrower." and stack.index == before
    assert tk_errors == []


# ---------------------------------------------------------------- feedback honesty
@pytest.mark.gui
def test_window_drag_on_one_axis_does_not_report_the_other_as_cleared(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    window = _pick(app, designer_root, "main")
    stack = _stack(app)
    assert stack.execute(SetField(window, "min_height", None)).accepted
    _settle(designer_root)
    _pick(app, designer_root, "main")
    _drag(designer_root, _shown_handle(app, "se"), 80, 0)  # only the width moves
    assert window.min_width is not None and window.min_width > 480
    assert window.min_height is None
    assert "cleared" not in _said(app)[-1]
    assert tk_errors == []


@pytest.mark.gui
def test_a_one_pixel_wobble_on_an_unset_pixel_size_records_nothing(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 2.3/2.7: back at the press (within half a 4 px snap) an unset size writes nothing."""
    _open(app, designer_root)
    notebook = _pick(app, designer_root, "nbk")
    assert _kinds(app)["e"] == "size"
    before = _stack(app).index
    _drag(designer_root, _shown_handle(app, "e"), 1, 0)
    assert "width" not in notebook.props and _stack(app).index == before
    assert tk_errors == []


# ---------------------------------------------------------------- Q12 second gesture
@pytest.mark.gui
def test_q12_a_handle_press_during_a_palette_drag_is_ignored(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    _pick(app, designer_root, "lbl_set", origin="canvas")
    drag: Any = app.shell.drag
    drag.press("Button", 10, 10)
    drag.motion(60, 60)
    assert drag.state == "dragging"
    handle = _shown_handle(app, "e")
    event = SimpleNamespace(state=0, x_root=100, y_root=100, widget=handle)
    app.shell.canvas._on_handle("e", "press", event)
    try:
        assert drag.state == "dragging" and drag._size is None
    finally:
        drag.cancel()
    assert tk_errors == []


# ---------------------------------------------------------------- component and round trip
@pytest.mark.gui
def test_component_window_drag_says_preview_and_the_inspector_labels_it(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    part = _pick(app, designer_root, "part")
    assert _stage_of(app).window is part and sorted(_kinds(app)) == ["e", "s", "se"]
    _drag(designer_root, _shown_handle(app, "se"), 120, 80)
    assert part.min_width is not None and part.min_height is not None
    assert "canvas only" in _said(app)[-1]
    document = app.session.document
    assert document is not None
    labels = {f.label for f in field_rows([part], app.session.registry, document)}
    assert {"Preview width", "Preview height"} <= labels
    assert tk_errors == []


@pytest.mark.gui
def test_save_and_reopen_after_resizes_is_identical(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    _open(app, designer_root)
    text = _pick(app, designer_root, "txt")
    pitch = _pitch(app, text)
    _drag(designer_root, _shown_handle(app, "se"), round(4 * pitch[0]), round(3 * pitch[1]))
    _pick(app, designer_root, "lbl_set")
    for _ in range(3):
        app.registry.invoke("edit.size_wider")
        _settle(designer_root)
    _pick(app, designer_root, "main")
    _drag(designer_root, _shown_handle(app, "se"), 64, 48)
    _pick(app, designer_root, "nbk")
    _drag(designer_root, _shown_handle(app, "se"), 40, 40)
    document = app.session.document
    assert document is not None
    first, second = tmp_path / "a.ui", tmp_path / "b.ui"
    write_ui(document, first)
    reopened = read_ui(first)
    assert not reopened.read_only
    write_ui(reopened.document, second)
    assert first.read_bytes() == second.read_bytes()

    def sizes(doc: Any) -> dict[str, tuple[object, ...]]:
        out: dict[str, tuple[object, ...]] = {}
        for n in doc.walk():
            if isinstance(n, Widget):
                out[n.id] = tuple(
                    (k, n.props[k].value) for k in ("width", "height", "length") if k in n.props
                )
            elif isinstance(n, Window):
                out[n.id] = (n.min_width, n.min_height)
        return out

    assert sizes(reopened.document) == sizes(document)
    assert sizes(document)["lbl_set"] == (("width", "12"),)
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("lang", ["en_XA", "de_DE", "nl_NL", "fr_FR", "pt_PT"])
def test_qa14b1_06_q13_the_longest_resize_message_fits_the_minimum_window(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    lang: str,
) -> None:
    """Spec 11 Q13 / 9: en_XA texts fit the status bar, elided with the full text on hover.
    At the minimum window size (800 x 500) the component release text is cut mid-word.
    Step 18: the longest real locales too (a text that fits is shown whole)."""
    from pyguibud import i18n

    _open(app, designer_root)
    language = i18n.get_language()
    designer_root.geometry("800x500")
    i18n.set_language(lang)
    try:
        _settle(designer_root, 5)
        cleared = sizing.window_release_text("part", (None, None), (True, True))
        app.shell.show_message(f"{cleared} {i18n._(sizing.M_COMPONENT)}")
        _settle(designer_root, 5)
        status = app.shell._status
        shown = str(status.cget("text"))
        assert status.winfo_reqwidth() <= status.winfo_width()  # it fits ...
        message = app.shell._message
        if lang == "en_XA" or shown != message:
            assert shown.endswith("…") and message.startswith(shown[:-1].rstrip())  # elided, ...
            assert message[len(shown[:-1].rstrip())] == " "  # ... at a word boundary
            assert app.shell._status_tip.cget("text") == message  # the full text on hover
    finally:  # a withdrawn root keeps its last size: the next files' canvas must stay wide
        i18n.set_language(language)
        designer_root.geometry("1400x900")
        _settle(designer_root)
    assert tk_errors == []


# ---------------------------------------------------------------- QA pass 2
_LONG = (
    "This deliberately long status message names 'lbl_set' and keeps going far beyond the "
    "width of the status bar at the minimum window size, so that it is cut at a word boundary "
    "with an ellipsis and its full text is shown in the tooltip on hover, as spec 11 Q13 says."
)


@pytest.mark.gui
def test_qa14b1_07_the_status_tooltip_never_stays_up_empty(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Hovering an elided message shows its full text; when the message clears (5 s timer,
    a selection change) or is replaced by one that fits, no empty tooltip box may remain."""
    _open(app, designer_root)
    designer_root.geometry("800x500")
    tip: Any = app.shell._status_tip  # Any: mypy would narrow ``toplevel`` to None
    try:
        _settle(designer_root, 5)
        app.shell.show_message(_LONG)
        _settle(designer_root)
        assert tip.cget("text") == _LONG  # elided: the full text is the tooltip
        tip.show_tip()  # what hovering the status bar does after the delay
        _settle(designer_root)
        assert tip.toplevel is not None
        app.shell.clear_message()
        _settle(designer_root)
        assert tip.toplevel is None or tip.cget("text")  # hidden, or still has a text
    finally:
        tip.hide_tip()
        designer_root.geometry("1400x900")
        _settle(designer_root)
    assert tk_errors == []


@pytest.mark.gui
def test_qa14b1_08_increase_width_on_a_window_never_clears_its_minimum(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 4 T3: window size keys start from the *shown* size. A minimum below the contents
    (an older file, or contents added later) must grow on Ctrl+Shift+Right, not be removed."""
    _open(app, designer_root)
    window = _pick(app, designer_root, "main")
    measured = app.shell.canvas.measure(window)
    assert measured is not None and measured.natural[0] > 100
    assert _stack(app).execute(SetField(window, "min_width", 50)).accepted
    _settle(designer_root)
    _pick(app, designer_root, "main")
    app.registry.invoke("edit.size_wider")
    _settle(designer_root)
    assert window.min_width is not None and window.min_width > measured.natural[0]
    assert tk_errors == []


@pytest.mark.gui
def test_qa14b1_09_a_shift_drag_of_one_pixel_sets_a_window_minimum_one_pixel_larger(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 3: the window value is the pointer extent snapped to 4 px, **Shift: 1 px**. The
    half-snap "moved" threshold (QA-14b1-03/04) also swallows a deliberate 1 px Shift drag."""
    _open(app, designer_root)
    window = _pick(app, designer_root, "main", origin="canvas")
    _drag(designer_root, _shown_handle(app, "e"), 80, 0)
    start = window.min_width
    assert start is not None
    _drag(designer_root, _shown_handle(app, "e"), 1, 0, state=0x1)  # Shift held
    assert window.min_width == start + 1
    assert tk_errors == []


@pytest.mark.gui
def test_qa14b1_10_a_handle_double_click_during_a_palette_drag_is_ignored(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 11 Q12 (two pointers): the second gesture is ignored until the first ends. The
    "double" branch of ``_on_handle`` has no drag-state guard (the "press" branch has, QA-05)."""
    _open(app, designer_root)
    label = _pick(app, designer_root, "lbl_set", origin="canvas")
    drag: Any = app.shell.drag
    before = _stack(app).index
    drag.press("Button", 10, 10)
    drag.motion(60, 60)
    assert drag.state == "dragging"
    event = SimpleNamespace(state=0, x_root=100, y_root=100, widget=_shown_handle(app, "e"))
    app.shell.canvas._on_handle("e", "double", event)
    _settle(designer_root)
    try:
        assert "width" in label.props and _stack(app).index == before  # not reset
        assert drag.state == "dragging"
    finally:
        drag.cancel()
    assert tk_errors == []


@pytest.mark.gui
def test_qa14b1_11_a_palette_press_during_a_size_drag_is_ignored(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 11 Q12 the other way round: a palette press while a size handle is dragged must
    leave the size drag running (today ``press()`` ends it silently; nothing is written)."""
    _open(app, designer_root)
    _pick(app, designer_root, "lbl_set", origin="canvas")
    drag: Any = app.shell.drag
    handle = _shown_handle(app, "e")
    x, y = handle.winfo_rootx() + 3, handle.winfo_rooty() + 3
    app.shell.canvas._on_handle("e", "press", SimpleNamespace(state=0, x_root=x, y_root=y,
                                                              widget=handle))  # fmt: skip
    assert drag.state == "resizing" and drag._size is not None
    drag.press("Button", 10, 10)  # what PalettePanel._on_press does
    try:
        assert drag.state == "resizing" and drag._size is not None
    finally:
        drag.cancel()
    assert tk_errors == []
