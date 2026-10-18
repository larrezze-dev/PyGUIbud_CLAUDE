"""QA abuse pass of Step 13b (spec dnd-selection 7, 8): regressions of the findings QA-13b-NN.

The real-input pass (Win32 SendInput on the real designer) found these; each is reproduced here
with synthetic Tk events or the pure builders. A finding that is still open is
``xfail(strict=True)``, so its fix turns the test into a pass that must then lose the marker.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import read_ui_string
from pyguibud.core.model import GridCell, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.edit import EditActions
from pyguibud.designer.present.status import selection_path
from pyguibud.designer.session import DesignerSession
from tests.designer.test_drag_move import _append_row, _outer, _two_labels
from tests.designer.test_edit import shown  # noqa: F401 - key events need a focused root
from tests.designer.test_move import FORM, _session
from tests.designer.test_qa13a_abuse import _settle, app, tk_errors  # noqa: F401 - fixtures

_FAR = itertools.count(20_000_000, 5_000)  # ms; 5 s apart: never a double-click


def _edit(session: DesignerSession) -> tuple[EditActions, list[str]]:
    said: list[str] = []

    def confirm(_question: str, then: Callable[[], None]) -> None:
        then()

    return EditActions(session, confirm, said.append), said


def _cell(node: object) -> GridCell:
    cell = node.placement  # type: ignore[attr-defined]
    assert isinstance(cell, GridCell)
    return cell


# ---------------------------------------------------------------- QA-13b-01 (major)
@pytest.mark.gui
def test_a_press_right_after_a_click_still_starts_a_move(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Click a widget to select it, then press on it again 150 ms later and drag it away."""
    window, first, _second = _two_labels(app, designer_root)
    widget = _outer(app, first)
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    t = next(_FAR)
    for sequence, at in (("<ButtonPress-1>", t), ("<ButtonRelease-1>", t + 60)):
        widget.event_generate(sequence, x=3, y=3, rootx=sx, rooty=sy, time=at)
    _settle(designer_root)
    assert app.session.selection.node is first
    widget.event_generate("<ButtonPress-1>", x=3, y=3, rootx=sx, rooty=sy, time=t + 210)
    assert app.shell.drag.state == "armed"  # the press was seen and arms a move
    to = _append_row(app, window)
    widget.event_generate("<B1-Motion>", x=13, y=3, rootx=sx + 10, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
    widget.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100, time=t + 900
    )
    _settle(designer_root)
    assert first.placement != GridCell(row=0, column=0)
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-02 (major)
# The bound (orchestrator ruling, spec 7.3): one row/column past the last one the OTHER children
# of the grid use (the append cell); a further key is denied with the reason, nothing recorded.
_PAST_THE_GRID = [
    # (node, rows, columns, the furthest allowed far edge: last row/column in use + 1 append)
    pytest.param("c", 0, 1, 4, id="right"),  # columns 0-2 are in use
    pytest.param("b", 1, 0, 7, id="down"),  # rows 0-5 are in use
]


@pytest.mark.parametrize(("name", "rows", "columns", "far"), _PAST_THE_GRID)
def test_a_held_arrow_stops_one_cell_past_the_grid(
    name: str, rows: int, columns: int, far: int
) -> None:
    session, n = _session()
    edit, said = _edit(session)
    session.select(n[name], origin="canvas")
    for _ in range(20):
        edit.nudge(rows, columns)
    cell = _cell(n[name])
    edge = cell.row + cell.rowspan if rows else cell.column + cell.columnspan
    assert edge == far, cell  # the append cell is reached, never passed
    assert said, "the refusal says why the motion stopped"


@pytest.mark.parametrize(("name", "rows", "columns", "far"), _PAST_THE_GRID)
def test_a_held_shift_arrow_stops_one_cell_past_the_grid(
    name: str, rows: int, columns: int, far: int
) -> None:
    session, n = _session()
    edit, _said = _edit(session)
    session.select(n[name], origin="canvas")
    for _ in range(20):
        edit.span(rows, columns)
    cell = _cell(n[name])
    edge = cell.row + cell.rowspan if rows else cell.column + cell.columnspan
    assert edge == far, cell


def test_arrows_never_reach_a_negative_cell_and_say_why() -> None:
    """The left/top clamp that does work (guard for the QA-13b-02 fix)."""
    session, n = _session()
    edit, said = _edit(session)
    session.select(n["a"], origin="canvas")
    before = _cell(n["a"])
    for _ in range(5):
        edit.nudge(0, -1)
        edit.nudge(-1, 0)
    assert _cell(n["a"]) == before and said


# ---------------------------------------------------------------- QA-13b-03 (major)
def _tree_key(app: DesignerApp, node: object) -> str:  # noqa: F811 - the fixture name
    key = app.shell.tree._keys.get(id(node))
    assert key is not None
    return str(key)


@pytest.mark.gui
@pytest.mark.parametrize("extra", ["x", "w"])
def test_the_tree_never_shows_rows_the_session_did_not_select(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    extra: str,
) -> None:
    app.session.open_result(read_ui_string(FORM), name="form")
    _settle(designer_root)
    assert app.session.document is not None
    n: dict[str, Any] = {getattr(node, "id", ""): node for node in app.session.document.walk()}
    tree = app.shell.tree.tree
    assert tree is not None
    app.session.select(n["a"], origin="canvas")
    _settle(designer_root)
    # What the Treeview's own Ctrl+click does: toggle the row in, keep the focus row.
    tree.selection_add(_tree_key(app, n[extra]))
    _settle(designer_root)
    assert [getattr(s, "id", "") for s in app.session.selection.nodes] == ["a"]
    assert tree.selection() == (_tree_key(app, n["a"]),)  # the tree agrees with the session
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-04 (major)
@pytest.mark.gui
def test_a_held_delete_never_cascades_onto_the_parent(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    app.session.open_result(read_ui_string(FORM), name="form")
    _settle(designer_root)
    assert app.session.document is not None
    n: dict[str, Any] = {getattr(node, "id", ""): node for node in app.session.document.walk()}
    frame, child = n["g"], n["g1"]
    assert isinstance(frame, Widget) and list(frame.children) == [child]
    app.session.select(child, origin="canvas")
    _settle(designer_root)
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    _settle(designer_root)
    if designer_root.focus_get() is not proxy:
        pytest.skip("the desktop did not give the test window the keyboard focus")
    # What Tk on Windows delivers for a held key (recorded with real input): KeyPress every
    # ~31 ms and a single KeyRelease at the end.
    t = next(_FAR)
    for k in range(2):
        proxy.event_generate("<KeyPress-Delete>", time=t + 31 * k)
        _settle(designer_root)
    proxy.event_generate("<KeyRelease-Delete>", time=t + 100)
    _settle(designer_root)
    assert child.parent is None  # the press did delete the child ...
    assert frame.parent is n["w"]  # ... and the auto-repeat left the frame alone
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize(("scope", "x11"), [("tree", False), ("canvas", True)])
def test_a_held_delete_acts_once_per_press_on_the_tree_and_with_x11_repeats(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
    scope: str,
    x11: bool,
) -> None:
    """The same guard on the object tree; X11 repeats as KeyRelease + KeyPress at one time."""
    app.session.open_result(read_ui_string(FORM), name="form")
    _settle(designer_root)
    assert app.session.document is not None
    n: dict[str, Any] = {getattr(node, "id", ""): node for node in app.session.document.walk()}
    frame, child = n["g"], n["g1"]
    app.session.select(child, origin=scope)
    _settle(designer_root)
    target = app.shell.tree.tree if scope == "tree" else app.shell.canvas.focus_widget
    assert target is not None
    target.focus_force()
    _settle(designer_root)
    if designer_root.focus_get() is not target:
        pytest.skip("the desktop did not give the test window the keyboard focus")
    t = next(_FAR)
    for k in range(3):
        if x11 and k:
            target.event_generate("<KeyRelease-Delete>", time=t + 31 * k)
        target.event_generate("<KeyPress-Delete>", time=t + 31 * k)
        _settle(designer_root)
    target.event_generate("<KeyRelease-Delete>", time=t + 200)
    _settle(designer_root)
    assert child.parent is None and frame.parent is n["w"]
    target.event_generate("<KeyPress-Delete>", time=t + 400)  # a new press acts again
    _settle(designer_root)
    assert frame.parent is None
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-09 (minor)
@pytest.mark.gui
def test_the_multi_selection_line_is_the_inspector_header(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Spec 7.2: the 'n elements selected' line heads the inspector, above the property tree."""
    _window, first, second = _two_labels(app, designer_root)
    app.session.select_many([first, second], origin="canvas")
    _settle(designer_root)
    panel = app.shell.inspector
    assert panel.header.winfo_manager() == "grid"
    row = int(panel.header.grid_info()["row"])
    assert int(panel.heading.grid_info()["row"]) < row < int(panel.notebook.grid_info()["row"])
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-05 (major)
#: The msgids Step 13b adds (pyguibud.pot diff); 13a translated its own new strings at once.
_NEW_13B = (
    "Release to move '{id}' into '{container}'.",
    "Release to resize '{id}' to {columns} × {rows} cells.",  # noqa: RUF001 - the sign is meant
    "Release to move {count} element.",
    "Delete {count} element and the elements inside it?",
    "A widget cannot be dropped into itself.",
    "'{id}' is already there.",
    "That would put an element outside the grid.",
    "An element must span at least one row and one column.",
    "Only elements of the same container can be moved together.",
    "Only widgets and included components can be moved.",
    "Only elements of a grid can be resized.",
    "This container arranges its children side by side; use Left and Right.",
    "This container arranges its children top to bottom; use Up and Down.",
    "Move elements",
    "Resize element",
    "Delete elements",
    "{next} selects the next widget; {panel} moves to the next panel.",  # key names: 19e H79
    # "{count} elements selected; showing '{id}'." was replaced in 14a (spec 3.4).
    "{count} element selected",
    "Select _next widget",
    "Select prev_ious widget",
    "Select _first child",
    "Select _parent",
    "Select all in _container",
    "_Move",
    "Move _left",
    "Move _right",
    "Move _up",
    "Move _down",
    "_Wider",
    "_Narrower",
    "_Taller",
    "_Shorter",
    "Move _earlier",
    "Move l_ater",
)


@pytest.mark.parametrize("lang", [code for code in i18n.LANGUAGES if code != "en_GB"])
def test_every_13b_string_is_translated(lang: str) -> None:
    from babel.messages.pofile import read_po

    path = Path(i18n.__file__).parent / "locale" / lang / "LC_MESSAGES" / "pyguibud.po"
    with path.open("rb") as handle:
        catalogue = read_po(handle)
    missing = []
    for msgid in _NEW_13B:
        message = catalogue.get(msgid)
        if message is None:
            message = next(
                (m for m in catalogue if isinstance(m.id, tuple) and m.id[0] == msgid), None
            )
        strings = message.string if message is not None else ""
        texts = strings if isinstance(strings, tuple) else (strings,)
        if message is None or message.fuzzy or not all(texts):
            missing.append(msgid)
    assert missing == [], f"{lang}: {len(missing)} untranslated"


# ---------------------------------------------------------------- QA-13b-10 (major, fixed)
@pytest.mark.gui
@pytest.mark.parametrize("gesture", ["move", "band", "resize"])
def test_a_canvas_gesture_survives_the_palette_losing_the_focus(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
    gesture: str,
) -> None:
    """Insert from the palette (the focus stays there, D7), then press-drag on the canvas at once.

    Real input: the first move of the just-inserted widget, the first rubber band and the first
    resize-handle drag after any palette click all do nothing; only a second attempt works.
    """
    window, first, _second = _two_labels(app, designer_root)
    app.session.select(first, origin="canvas")
    _settle(designer_root)
    palette = app.shell.palette.tree
    assert palette is not None
    palette.focus_force()
    _settle(designer_root)
    if designer_root.focus_get() is not palette:
        pytest.skip("the desktop did not give the test window the keyboard focus")
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    if gesture == "move":
        widget = _outer(app, first)
        x, y = 3, 3
    elif gesture == "resize":  # the east handle of the selected Label
        widget = stage.overlay.handles.shown()[3]
        x, y = widget.winfo_width() // 2, widget.winfo_height() // 2
    else:  # the window body's empty bottom-right corner
        widget = stage.view.inner[id(window)]
        x, y = widget.winfo_width() - 4, widget.winfo_height() - 4
    sx, sy = widget.winfo_rootx() + x, widget.winfo_rooty() + y
    widget.event_generate("<ButtonPress-1>", x=x, y=y, rootx=sx, rooty=sy, time=next(_FAR))
    _settle(designer_root)  # the palette's FocusOut is delivered here
    assert app.shell.drag.state == ("resizing" if gesture == "resize" else "armed")
    if gesture == "move":
        to = _append_row(app, window)
        widget.event_generate("<B1-Motion>", x=x + 10, y=y, rootx=sx + 10, rooty=sy, state=0x100)
        widget.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
        widget.event_generate(
            "<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100, time=next(_FAR)
        )
        _settle(designer_root)
        assert first.placement != GridCell(row=0, column=0)
    else:
        app.shell.drag.cancel()
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-11 (minor)
@pytest.mark.gui
def test_a_refusal_leaves_the_status_bar_once_an_edit_succeeds_or_the_selection_changes(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Left on the first label is refused; Right then moves it, and a click picks the other one.

    Real input: the stale refusal stayed for its full five seconds over the new state.
    """
    _window_node, first, second = _two_labels(app, designer_root)
    app.session.select(first, origin="tree")
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    _settle(designer_root)
    status, refused = app.shell._status, "That would put an element outside the grid."
    proxy.event_generate("<Left>")  # column 0: denied with the reason
    assert app.shell._message == refused and str(status.cget("text")) == refused
    proxy.event_generate("<Right>")
    _settle(designer_root)
    assert _cell(first) == GridCell(row=0, column=1)
    assert app.shell._message == ""
    assert str(status.cget("text")) == selection_path(first, app.session.document)
    proxy.event_generate("<Up>")  # row 0: denied again
    assert app.shell._message == refused
    widget = _outer(app, second)  # a click, not a key: no command runs, only the pick
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    for sequence in ("<ButtonPress-1>", "<ButtonRelease-1>"):
        widget.event_generate(sequence, x=3, y=3, rootx=sx, rooty=sy, time=next(_FAR))
    _settle(designer_root)
    assert app.session.selection.node is second and app.shell._message == ""
    assert str(status.cget("text")) == selection_path(second, app.session.document)
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13b-12 (minor, fixed)
@pytest.mark.gui
def test_delete_mid_drag_still_says_the_drag_was_cancelled(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    shown: Any,  # noqa: F811
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Press-drag a label, press Delete with the button still held.

    Real input (pass 3): the label is deleted and the drag ends, but the status bar shows only the
    window path; pass 2 showed "Drag cancelled." (the QA-13b-11 selection_changed clear wipes it).
    """
    window, first, _second = _two_labels(app, designer_root)
    app.session.select(first, origin="canvas")
    proxy = app.shell.canvas.focus_widget
    proxy.focus_force()
    _settle(designer_root)
    if designer_root.focus_get() is not proxy:
        pytest.skip("the desktop did not give the test window the keyboard focus")
    widget = _outer(app, first)
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    to = _append_row(app, window)
    widget.event_generate("<ButtonPress-1>", x=3, y=3, rootx=sx, rooty=sy, time=next(_FAR))
    widget.event_generate("<B1-Motion>", x=13, y=3, rootx=sx + 10, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)
    assert app.shell.drag.state == "dragging"
    proxy.event_generate("<Delete>")
    _settle(designer_root)
    state: str = app.shell.drag.state  # a fresh read: mypy keeps the narrowing from above
    assert state == "idle"
    assert first.parent is None or first not in window.children
    assert app.shell._message == "Drag cancelled."
    assert tk_errors == []
