"""QA 19c: editing and model abuse, end to end (``docs/specs/hardening.md`` section 3, H32-H43).

The M23 matrix goes through the real designer doors: the inspector fields, the Variables and
Events tabs, Document > Rename window, the object tree (mouse and keys), the canvas, the Edit
menu, the toolbar and the system clipboard. The new 19c code is attacked directly: the
read-only preview of a long text (H41), the paste interception, the failed undo/redo (H37), the
busy drag guard (H40), Cut on a window (H43), the D10 placement change (H38) and the sash clamp
on a shrunk root (H03, in a subprocess with a timeout). Open findings are strict xfails
``QA-19c-NN``.
"""

# ruff: noqa: RUF001
from __future__ import annotations

import contextlib
import logging
import random
import subprocess
import sys
import textwrap
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

import pytest

from pyguibud import i18n
from pyguibud.core import CommandStack, default_registry, dump_ui, read_ui, read_ui_string
from pyguibud.core import commands as cmds
from pyguibud.core.errors import XmlIoError
from pyguibud.core.model import Prop, Widget, Window
from pyguibud.designer import tree_dnd
from pyguibud.designer.editing import move_command
from pyguibud.designer.files import SavePlan
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT, clip_text
from pyguibud.designer.settings import Settings
from pyguibud.designer.targets import Target
from tests.conftest import BUDGET_FACTOR, reset_root
from tests.strategies_m23 import BAD_IDS, BAD_NAMES

ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"
REG = default_registry()
LOCALES = ("en_GB", "es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR", "en_XA")
HEAD = (
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"'
    ' xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">'
)
#: main: outer Frame (holding inner Frame), a Label, a Button, an Entry bound to an int var;
#: dlg: an empty dialog. Every widget is in a grid.
FORM = (
    f'{HEAD}<variables><var id="count" type="int"/><var id="name" type="string"/></variables>'
    '<window id="main" kind="main"><prop name="title">Main</prop><layout type="grid"/>'
    '<widget class="Frame" id="outer"><cell row="0" column="0"/><layout type="grid"/>'
    '<widget class="Frame" id="inner"><cell row="0" column="0"/><layout type="grid"/></widget>'
    "</widget>"
    '<widget class="Label" id="lbl"><cell row="1" column="0"/><prop name="text">Hi</prop>'
    "</widget>"
    '<widget class="Button" id="btn"><cell row="2" column="0"/><prop name="text">Go</prop>'
    "</widget>"
    '<widget class="Entry" id="ent" bind="name"><cell row="3" column="0"/></widget>'
    '</window><window id="dlg" kind="dialog"><layout type="pack"/></window></pyguibud-ui>'
)
LONG = "W" * 100_000
EMOJI = "\U0001f600"  # outside the BMP: two UTF-16 units, so two Tk 8.6 indices on Windows
CUT_REFUSAL = "Windows are deleted with Document > Delete window."
UNDO_FAILED = "Undo or redo failed; the document was left as it was."


@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings and recovery data go to temporary folders, never the real profile."""
    base = tmp_path_factory.mktemp("profile19c")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))


@pytest.fixture
def app(tk_root: Any) -> Iterator[Any]:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.recovery import RecoverySession

    reset_root(tk_root)
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(tk_root, settings=Settings(), recovery=recovery)
    yield designer
    tk_root.protocol("WM_DELETE_WINDOW", tk_root.destroy)
    for dialog in designer._live_dialogs():
        with contextlib.suppress(Exception):
            dialog.close()
    designer.set_language("en_GB")
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()
    with contextlib.suppress(Exception):
        tk_root.clipboard_clear()
    reset_root(tk_root)


# ================================================================ helpers
def _settle(root: Any, rounds: int = 3) -> None:
    for _ in range(rounds):
        root.update()


def _open(app: Any, text: str = FORM) -> Any:
    app.session.open_result(read_ui_string(text), name="qa19c")
    _settle(app.root)
    assert app.session.document is not None
    return app.session.document


def _node(app: Any, node_id: str) -> Any:
    document = app.session.document
    assert document is not None
    return next(n for n in document.walk() if getattr(n, "id", None) == node_id)


def _pick(app: Any, node: object) -> None:
    app.session.select(node, origin="tree")
    _settle(app.root)


def _editor(app: Any, key: str) -> Any:
    return app.shell.inspector._editors[key]


def _message(app: Any) -> str:
    return str(app.shell._message or "")


def _stack(app: Any) -> Any:
    stack = app.session.stack
    assert stack is not None
    return stack


def _snapshot(app: Any) -> tuple[bytes, int]:
    return dump_ui(app.session.document), _stack(app).index


@contextlib.contextmanager
def _focused(root: Any, widget: Any) -> Iterator[None]:
    """Map the shared root and give ``widget`` the keyboard focus (key events need it)."""
    root.deiconify()
    try:
        widget.focus_force()
        _settle(root, 10)
        if root.focus_get() is not widget:
            pytest.skip("the desktop did not give the test window the keyboard focus")
        yield
    finally:
        root.withdraw()
        _settle(root)


def _clipboard(root: Any, text: str) -> None:
    root.clipboard_clear()
    root.clipboard_append(text)


def _entry_state(app: Any, action_id: str) -> list[str]:
    """The state of every menu entry (main menus and the tree menu) of ``action_id``."""
    app.shell.refresh_states()
    action = app.registry.get(action_id)
    entries = app.shell._entries
    return [str(menu.entrycget(i, "state")) for menu, i, item in entries if item is action]


def _button_state(app: Any, action_id: str) -> list[tuple[str, ...]]:
    app.shell.refresh_states()
    action = app.registry.get(action_id)
    return [tuple(b.state()) for b, item in app.shell._buttons if item is action]


# ================================================================ M23 matrix: ids (H32)
@pytest.mark.gui
@pytest.mark.parametrize("bad", BAD_IDS, ids=[ascii(b)[:14] for b in BAD_IDS])
@pytest.mark.parametrize("target", ["lbl", "dlg"])
def test_m23_every_bad_id_in_the_inspector_is_refused_on_a_widget_and_a_window(
    app: Any, bad: str, target: str
) -> None:
    _open(app)
    _pick(app, _node(app, target))
    before = _snapshot(app)
    editor = _editor(app, "field:id")
    app.shell.clear_message()
    editor.var.set(bad)
    editor._enter()
    _settle(app.root)
    assert _snapshot(app) == before
    assert _message(app) and editor.invalid, bad  # a reason, and the field is marked
    editor._escape()
    assert editor.text() == target and not editor.invalid


@pytest.mark.gui
def test_m23_every_bad_id_in_the_variables_tab_and_rename_window_is_refused(app: Any) -> None:
    document = _open(app)
    before = _snapshot(app)
    panel = app.shell.variables
    assert panel.tree is not None
    panel.tree.selection_set("count")
    _settle(app.root)
    # The tab trims the typed id (a trailing newline gives the valid "x"): untrimmable ones only.
    for bad in (*(b for b in BAD_IDS if b == b.strip()), "name"):  # "name" is taken
        app.shell.clear_message()
        panel.id_var.set(bad)
        panel._commit_id()
        assert _snapshot(app) == before and _message(app), ascii(bad)[:20]
    panel.id_var.set("count")
    _pick(app, _node(app, "dlg"))
    assert app.shell._invoke("document.rename")
    (dialog,) = app._live_dialogs()
    live: Any = dialog
    for bad in (*(b for b in BAD_IDS if b == b.strip()), "main"):
        live.value.set(bad)
        live.accept()
        assert not live.closed and live.reason.cget("text"), ascii(bad)[:20]
        assert dump_ui(document) == before[0]
    live.close()


@pytest.mark.gui
@pytest.mark.parametrize("bad", BAD_NAMES, ids=[ascii(b) for b in BAD_NAMES])
def test_m23_a_handler_name_that_is_not_an_identifier_is_refused_in_the_events_tab(
    app: Any, bad: str
) -> None:
    _open(app)
    _pick(app, _node(app, "btn"))
    boxes = app.shell.inspector.events.editors()
    assert boxes
    box = boxes[0]
    before = _snapshot(app)
    app.shell.clear_message()
    box.var.set(bad)
    box.commit_pending()
    _settle(app.root)
    if bad.strip() == "":  # empty: "no handler", a valid no-op on an unbound event
        assert _snapshot(app)[0] == before[0]
        return
    assert _snapshot(app) == before and _message(app), bad


@pytest.mark.gui
def test_m23_an_int_variable_on_a_text_entry_is_accepted_and_a_bad_default_refused(
    app: Any,
) -> None:
    """Ruling 19c: Tk allows an IntVar on an Entry, so binding 'count' to 'ent' is accepted."""
    _open(app)
    ent = _node(app, "ent")
    _pick(app, ent)
    editor = _editor(app, "field:bind")
    assert app.shell.inspector.commit(editor, "count")
    assert ent.bind == "count"
    panel = app.shell.variables
    assert panel.tree is not None
    panel.tree.selection_set("count")
    _settle(app.root)
    before = _snapshot(app)
    for bad in ("abc", "1.5", "9" * 5000, "\x00"):
        app.shell.clear_message()
        panel.default_var.set(bad)
        assert not panel.flush(), ascii(bad)[:10]
        assert _snapshot(app) == before and _message(app)
    panel.default_var.set("")


@pytest.mark.gui
def test_m23_deleting_a_bound_variable_asks_and_unbinds_in_one_undoable_step(app: Any) -> None:
    document = _open(app)
    panel = app.shell.variables
    assert panel.tree is not None
    panel.tree.selection_set("name")
    _settle(app.root)
    before = _snapshot(app)
    panel.delete()
    _settle(app.root)
    (dialog,) = app._live_dialogs()
    live: Any = dialog
    live.close()  # cancelled: nothing changes
    _settle(app.root)
    assert _snapshot(app) == before and _node(app, "ent").bind == "name"
    panel.tree.selection_set("name")
    panel.delete()
    _settle(app.root)
    (dialog,) = app._live_dialogs()
    live = dialog
    live.confirm()
    _settle(app.root)
    assert "name" not in document.variables and _node(app, "ent").bind is None
    assert _stack(app).index == before[1] + 1  # one step
    assert app.shell._invoke("edit.undo")
    _settle(app.root)
    assert _snapshot(app)[0] == before[0]


@pytest.mark.gui
def test_m23_a_second_main_window_is_refused_in_the_inspector(app: Any) -> None:
    _open(app)
    _pick(app, _node(app, "dlg"))
    editor = _editor(app, "field:kind")
    before = _snapshot(app)
    app.shell.clear_message()
    assert not app.shell.inspector.commit(editor, "main")
    assert _snapshot(app) == before and _message(app)


# ================================================================ M23 drops (H34), real events
def _tree_point(app: Any, node: object, fraction: float) -> tuple[int, int]:
    tree, key = app.shell.tree.tree, app.shell.tree.key_of(node)
    assert tree is not None and key is not None
    tree.see(key)
    tree.update_idletasks()
    box = tree.bbox(key)
    if not box:
        pytest.skip("the tree row is not laid out (no display geometry)")
    x, y, w, h = (int(v) for v in box)
    return x + w // 2, y + int(h * fraction)


_CLOCK = iter(range(500_000, 10**9, 1_000))


def _tree_drag(app: Any, source: object, onto: object, fraction: float) -> None:
    tree = app.shell.tree.tree
    x, y = _tree_point(app, source, 0.5)
    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=next(_CLOCK))
    tx, ty = _tree_point(app, onto, fraction)
    for to in ((x + 12, y + 12), (tx, ty)):
        tree.event_generate("<B1-Motion>", x=to[0], y=to[1], state=0x100)
    app.root.after(150, lambda: None)
    for _ in range(30):
        app.root.update()
    tree.event_generate("<ButtonRelease-1>", x=tx, y=ty, state=0x100, time=next(_CLOCK))
    _settle(app.root)


@pytest.mark.gui
@pytest.mark.parametrize(
    ("moving", "onto", "fraction"),
    [("outer", "inner", 0.5), ("outer", "inner", 0.9), ("outer", "outer", 0.5),
     ("inner", "lbl", 0.5), ("main", "inner", 0.5), ("dlg", "outer", 0.5)],
    ids=["into-own-child", "after-own-child", "into-itself", "into-a-label", "window-into-frame",
         "dialog-into-frame"],
)  # fmt: skip
def test_m23_tree_mouse_drops_into_a_leaf_a_descendant_or_itself_change_nothing(
    app: Any, moving: str, onto: str, fraction: float
) -> None:
    _open(app)
    _pick(app, _node(app, moving))
    before = _snapshot(app)
    _tree_drag(app, _node(app, moving), _node(app, onto), fraction)
    if moving == "inner" and onto == "lbl":  # a centre drop on a leaf may go beside it ...
        assert not _node(app, "lbl").children  # ... but never inside it
        return
    assert _snapshot(app) == before
    assert _node(app, "inner").parent is _node(app, "outer")


@pytest.mark.gui
def test_m23_canvas_drag_of_a_frame_onto_a_label_never_nests_it(app: Any) -> None:
    document = _open(app)
    stage = app.shell.canvas.stage_of(document.children[0])
    assert stage is not None and stage.view is not None
    outer, lbl = _node(app, "outer"), _node(app, "lbl")
    _pick(app, outer)
    widget, target = stage.view.outer[id(outer)], stage.view.outer[id(lbl)]
    sx, sy = widget.winfo_rootx() + 2, widget.winfo_rooty() + 2
    tx = target.winfo_rootx() + target.winfo_width() // 2
    ty = target.winfo_rooty() + target.winfo_height() // 2
    widget.event_generate("<ButtonPress-1>", x=2, y=2, rootx=sx, rooty=sy, time=next(_CLOCK))
    widget.event_generate("<B1-Motion>", x=12, y=2, rootx=sx + 10, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=0, y=0, rootx=tx, rooty=ty, state=0x100)
    widget.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=tx, rooty=ty, state=0x100, time=next(_CLOCK)
    )
    _settle(app.root)
    assert not lbl.children and outer.parent is document.children[0]
    assert _stack(app).index <= 1


@pytest.mark.gui
@pytest.mark.parametrize("action", ["edit.left", "edit.up", "edit.narrower", "edit.shorter"])
def test_m23_keyboard_moves_off_the_grid_or_below_one_cell_are_refused(
    app: Any, action: str
) -> None:
    _open(app)
    _pick(app, _node(app, "outer"))  # row 0, column 0, spans 1
    before = _snapshot(app)
    app.shell.clear_message()
    app.shell._invoke(action)
    _settle(app.root)
    assert _snapshot(app) == before and _message(app), action


@pytest.mark.gui
@pytest.mark.parametrize("node_id", ["main", "dlg"])
def test_m23_keyboard_moves_on_a_window_are_refused(app: Any, node_id: str) -> None:
    _open(app)
    _pick(app, _node(app, node_id))
    before = _snapshot(app)
    for action in ("edit.left", "edit.right", "edit.up", "edit.down", "edit.wider"):
        app.shell.clear_message()
        app.shell._invoke(action)
        _settle(app.root)
        assert _snapshot(app) == before, action


# ================================================================ M23 clipboard garbage (H36)
_GARBAGE = {
    "lorem": "lorem ipsum dolor " * 300,
    "broken-widget": '<widget class="Label" id="x"><prop name="text">',
    "foreign-root": '<?xml version="1.0"?><html><body>hi</body></html>',
    "entity-bomb": '<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;">]>'
    f'{HEAD}<window id="w">&b;</window></pyguibud-ui>',
    "bad-id": f'{HEAD}<window id="w" kind="main"><widget class="Label" id="1bad"/></window>'
    "</pyguibud-ui>",
    "unknown-class": f'{HEAD}<window id="w" kind="main"><layout type="grid"/>'
    '<widget class="os.system" id="x"><cell row="0" column="0"/></widget></window></pyguibud-ui>',
    "100k-text": "Q" * 100_000,
    "nul": "a\x00b",
}


@pytest.mark.gui
@pytest.mark.parametrize("name", sorted(_GARBAGE))
def test_m23_garbage_on_the_system_clipboard_is_refused_by_ctrl_v_and_edit_paste(
    app: Any, name: str
) -> None:
    _open(app)
    _pick(app, _node(app, "outer"))
    before = _snapshot(app)
    _clipboard(app.root, _GARBAGE[name])
    app.shell.clear_message()
    started = time.perf_counter()
    app.shell._invoke("edit.paste")  # Edit > Paste
    _settle(app.root)
    first = _message(app)
    tree = app.shell.tree.tree
    with _focused(app.root, tree):
        app.shell.clear_message()
        tree.event_generate("<Control-v>")  # the key
        _settle(app.root)
    elapsed = time.perf_counter() - started
    if name == "unknown-class":  # a placeholder paste is acceptable: at most one step each
        assert _stack(app).index <= before[1] + 2
        return
    assert _snapshot(app) == before, name
    assert first and _message(app), name
    assert elapsed < 2.0 * BUDGET_FACTOR, elapsed


@pytest.mark.gui
def test_m23_a_multi_select_delete_through_the_delete_key_is_one_step_and_undo_restores(
    app: Any,
) -> None:
    document = _open(app)
    before = _snapshot(app)
    app.session.select_many([_node(app, n) for n in ("outer", "lbl", "ent")], origin="tree")
    _settle(app.root)
    tree = app.shell.tree.tree
    with _focused(app.root, tree):
        tree.event_generate("<Delete>")
        _settle(app.root)
        (dialog,) = app._live_dialogs()  # 'outer' holds 'inner': asked first
        dialog.confirm()
        _settle(app.root)
        assert [c.id for c in document.children[0].children] == ["btn"]
        assert _stack(app).index == before[1] + 1
        tree.focus_force()  # the dialog took the focus
        _settle(app.root, 5)
        tree.event_generate("<Control-z>")
        _settle(app.root)
    assert _snapshot(app) == before
    assert _node(app, "ent").bind == "name"  # the binding came back too


@pytest.mark.gui
def test_m23_a_selection_mixing_a_window_and_widgets_keeps_one_kind(app: Any) -> None:
    """A window never shares a selection with widgets (spec 7.1), so no gesture can cut or
    delete a window together with widgets."""
    _open(app)
    main, lbl = _node(app, "main"), _node(app, "lbl")
    app.session.select_many([main, lbl], origin="tree")
    assert main not in app.session.selection.nodes
    app.session.select_many([lbl, main], origin="tree")
    assert app.session.selection.nodes == (main,)


# ================================================================ H36 storm through the keys
@pytest.mark.gui
def test_h36_1000_key_presses_of_ctrl_z_and_ctrl_y_across_a_100k_preview(app: Any) -> None:
    """Eleven steps that switch the selected Label between a short text and 100,000 characters:
    the inspector shows the preview, then an editable field, then the preview again."""
    _open(app)
    lbl = _node(app, "lbl")
    _pick(app, lbl)
    stack = _stack(app)
    start = dump_ui(app.session.document)
    for k in range(11):  # ends on the long text
        value = LONG if k % 2 == 0 else f"short {k}"
        assert stack.execute(cmds.SetProp(lbl, Prop(name="text", value=value))).accepted
        stack.break_merge()
    _settle(app.root)
    end = dump_ui(app.session.document)
    tree = app.shell.tree.tree
    started = time.perf_counter()
    with _focused(app.root, tree):
        for k in range(1000):  # 4 runs of 250: undo to the start and back, the rest no-ops
            tree.event_generate("<Control-z>" if (k // 250) % 2 == 0 else "<Control-y>")
            if k % 25 == 0:
                app.root.update()
        _settle(app.root)
        assert dump_ui(app.session.document) == end and stack.index == 11
        for k in range(200):  # every press a real step across the preview
            tree.event_generate("<Control-y>" if k % 2 else "<Control-z>")
            app.root.update()
    elapsed = time.perf_counter() - started
    print(f"QA H36 key storm: {elapsed:.2f} s")  # timing: see the budget test below
    assert dump_ui(app.session.document) == end and lbl.props["text"].value == LONG
    editor = _editor(app, "prop:text")
    assert editor.long and editor.widget.instate(["readonly"]) and not editor.pending()
    while stack.can_undo:
        stack.undo()
    assert dump_ui(app.session.document) == start


@pytest.mark.gui
@pytest.mark.budget
def test_h36_one_undo_or_redo_step_across_the_100k_preview_takes_under_a_second(
    app: Any,
) -> None:
    """Acceptance (re-render <= 1 s) per step. QA-19c-08 (perf, minor): with the Label
    selected a step costs about 0.2 s, against 0.024 s unselected (the inspector refresh)."""
    _open(app)
    lbl = _node(app, "lbl")
    stack = _stack(app)
    for value in (LONG, "short", LONG):
        assert stack.execute(cmds.SetProp(lbl, Prop(name="text", value=value))).accepted
        stack.break_merge()
    timings: dict[str, list[float]] = {"selected": [], "unselected": []}
    for case, node in (("selected", lbl), ("unselected", _node(app, "dlg"))):
        _pick(app, node)
        for k in range(20):
            started = time.perf_counter()
            assert app.shell._invoke("edit.redo" if k % 2 else "edit.undo")
            app.root.update()
            timings[case].append(time.perf_counter() - started)
    worst = max(timings["selected"] + timings["unselected"])
    mean = {k: round(sum(v) / len(v), 3) for k, v in timings.items()}
    print(f"QA H36 step: {mean} worst {worst:.2f} s")
    assert worst <= 1.0 * BUDGET_FACTOR, worst


# ================================================================ H41: the read-only preview
def _long(app: Any, node_id: str, prop: str = "text", value: str = LONG) -> Any:
    node = _node(app, node_id)
    assert _stack(app).execute(cmds.SetProp(node, Prop(name=prop, value=value))).accepted
    _stack(app).break_merge()
    _pick(app, node)
    return node


def _locked(editor: Any) -> bool:
    button = getattr(editor, "button", None)
    return (
        editor.long
        and editor.widget.instate(["readonly"])
        and (button is None or button.instate(["disabled"]))
        and not editor.pending()
    )


@pytest.mark.gui
@pytest.mark.parametrize(("node_id", "prop"), [("lbl", "text"), ("btn", "text"), ("main", "title")])
def test_h41_every_gesture_on_the_preview_leaves_all_100k_characters(
    app: Any, node_id: str, prop: str, tmp_path: Path
) -> None:
    _open(app)
    node = _long(app, node_id, prop)
    stack = _stack(app)
    depth = stack.index
    editor = _editor(app, f"prop:{prop}")
    assert _locked(editor) and len(editor.text()) == CANVAS_TEXT_LIMIT
    widget = editor.widget
    _clipboard(app.root, "PASTED")
    with _focused(app.root, widget):
        for key in ("x", "BackSpace", "Delete", "space"):
            widget.event_generate(f"<KeyPress-{key}>")
        for virtual in ("<<Paste>>", "<<Cut>>", "<<Clear>>"):
            widget.event_generate(virtual)
        widget.icursor(5)
        widget.event_generate("<Return>")
        widget.event_generate("<Escape>")
        widget.event_generate("<Control-z>")  # undo the SetProp: an editable short text ...
        _settle(app.root)
        widget = _editor(app, f"prop:{prop}").widget
        widget.focus_force()
        _settle(app.root)
        widget.event_generate("<Control-y>")  # ... and the preview again
        _settle(app.root)
    editor = _editor(app, f"prop:{prop}")
    assert _locked(editor) and stack.index == depth
    assert app.shell.inspector.flush() and app.shell.flush()
    assert node.props[prop].value == LONG
    target = tmp_path / "long.ui"
    app._write(SavePlan(target=target), None)
    assert read_ui(target).document is not None
    assert target.read_bytes().count(LONG.encode()) == 1


@pytest.mark.gui
def test_h41_the_preview_stays_locked_across_themes_all_locales_undo_and_reselection(
    app: Any,
) -> None:
    document = _open(app)
    lbl = _long(app, "lbl")
    for theme in ("dark", "high_contrast", "light"):
        app.set_theme(theme)
        app.flush_theme()
        _settle(app.root)
        assert _locked(_editor(app, "prop:text")), theme
    for code in LOCALES:
        app.set_language(code)
        _settle(app.root)
        editor = _editor(app, "prop:text")
        assert _locked(editor), code
        note = str(editor.note.cget("text"))
        assert "100000" in note.replace(".", "").replace(",", "").replace(" ", ""), code
    app.set_language("en_GB")
    _pick(app, document.children[0])
    _pick(app, lbl)
    assert _locked(_editor(app, "prop:text"))
    assert app.shell._invoke("edit.undo")
    _settle(app.root)
    assert not _editor(app, "prop:text").long  # "Hi" again: editable
    assert app.shell._invoke("edit.redo")
    _settle(app.root)
    assert _locked(_editor(app, "prop:text")) and lbl.props["text"].value == LONG


@pytest.mark.gui
@pytest.mark.parametrize(
    ("length", "long"), [(CANVAS_TEXT_LIMIT, False), (CANVAS_TEXT_LIMIT + 1, True)]
)
def test_h41_the_preview_starts_one_character_past_the_canvas_limit(
    app: Any, length: int, long: bool
) -> None:
    document = _open(app)
    lbl = _long(app, "lbl", value="a" * length)
    editor = _editor(app, "prop:text")
    assert editor.long is long and len(editor.text()) == CANVAS_TEXT_LIMIT
    assert editor.widget.instate(["readonly"]) is long
    stage = app.shell.canvas.stage_of(document.children[0])
    drawn = str(stage.view.outer[id(lbl)].cget("text"))
    assert len(drawn) == CANVAS_TEXT_LIMIT and drawn.endswith("…") is long
    if not long:  # exactly 2,000 characters stay editable: one more typed one makes 2,001
        editor.widget.icursor("end")
        editor.var.set(editor.text() + "b")
        assert editor.commit_pending()
        _settle(app.root)
        assert len(lbl.props["text"].value) == length + 1 and _editor(app, "prop:text").long


@pytest.mark.gui
@pytest.mark.parametrize(
    "value",
    ["a" * 1998 + EMOJI * 5, "line\n" * 3_000, "é́" * 1_500, "‏‮" * 2_000],
    ids=["emoji-at-the-clip", "multi-line", "combining", "bidi-controls"],
)
def test_h41_odd_text_at_the_clip_boundary_never_crashes_and_saves_intact(
    app: Any, value: str, tmp_path: Path
) -> None:
    document = _open(app)
    lbl = _long(app, "lbl", value=value)
    editor = _editor(app, "prop:text")
    assert _locked(editor)
    assert editor.text() == clip_text(value)
    stage = app.shell.canvas.stage_of(document.children[0])
    assert stage.view is not None and id(lbl) in stage.view.outer
    target = tmp_path / "odd.ui"
    app._write(SavePlan(target=target), None)
    again = read_ui(target).document
    copy: Any = next(n for n in again.walk() if getattr(n, "id", None) == "lbl")
    assert copy.props["text"].value == value


@pytest.mark.gui
def test_h41_a_multi_selection_of_long_texts_previews_and_a_mixed_one_is_editable(
    app: Any,
) -> None:
    _open(app)
    lbl, btn = _node(app, "lbl"), _node(app, "btn")
    stack = _stack(app)
    for node in (lbl, btn):
        assert stack.execute(cmds.SetProp(node, Prop(name="text", value=LONG))).accepted
    app.session.select_many([lbl, btn], origin="tree")
    _settle(app.root)
    assert _locked(_editor(app, "prop:text"))
    assert stack.execute(cmds.SetProp(btn, Prop(name="text", value="Go"))).accepted
    _settle(app.root)
    editor = _editor(app, "prop:text")  # (mixed): editable and empty, never the preview
    assert not editor.long and editor.text() == "" and not editor.widget.instate(["readonly"])
    assert app.shell.inspector.flush()
    assert lbl.props["text"].value == LONG  # an untouched (mixed) field writes nothing


@pytest.mark.gui
def test_h41_copy_and_paste_of_a_long_text_widget_keeps_every_character(app: Any) -> None:
    _open(app)
    _long(app, "lbl")
    assert app.shell._invoke("edit.copy")
    copied = str(app.root.clipboard_get())
    assert copied.count("W" * 100_000) == 1
    assert app.shell._invoke("edit.paste")
    _settle(app.root)
    texts = [
        n.props["text"].value
        for n in app.session.document.walk()
        if isinstance(n, Widget) and n.class_name == "Label"
    ]
    assert texts.count(LONG) == 2


@pytest.mark.gui
def test_h41_reset_on_a_long_window_title_clears_it_and_unlocks_the_field(app: Any) -> None:
    _open(app)
    window = _long(app, "main", "title")
    app.shell.inspector.reset("prop:title")
    _settle(app.root)
    editor = _editor(app, "prop:title")
    assert "title" not in window.props or len(window.props["title"].value) < 100
    assert not editor.long and not editor.widget.instate(["readonly"])
    assert app.shell._invoke("edit.undo")
    _settle(app.root)
    assert window.props["title"].value == LONG and _locked(_editor(app, "prop:title"))


@pytest.mark.gui
@pytest.mark.budget
@pytest.mark.parametrize(
    "slot",
    [
        "title",
        "Label",
        "Button",
        "Checkbutton",
        "LabelFrame",
    ],
)
def test_h41_opening_a_file_with_a_100k_text_renders_and_inspects_within_a_second(
    app: Any, tmp_path: Path, slot: str
) -> None:
    big = "Z" * 100_000

    def text(name: str) -> str:
        return big if name == slot else "short"

    xml = (
        f'{HEAD}<window id="main" kind="main"><prop name="title">{text("title")}</prop>'
        '<layout type="grid"/>'
        '<widget class="Notebook" id="nb"><cell row="0" column="0"/>'
        f'<widget class="Frame" id="pg"><page><prop name="text">{text("page")}</prop></page>'
        '<layout type="grid"/></widget></widget>'
        + "".join(
            f'<widget class="{cls}" id="w{k}"><cell row="{k + 1}" column="0"/>'
            f'<prop name="text">{text(cls)}</prop></widget>'
            for k, cls in enumerate(("Label", "Button", "Checkbutton", "LabelFrame"))
        )
        + "</window></pyguibud-ui>"
    )
    path = tmp_path / "big.ui"
    path.write_text(xml, "utf-8")
    started = time.perf_counter()
    assert app.open_path(path)
    _settle(app.root)
    opened = time.perf_counter() - started
    classes = ["Label", "Button", "Checkbutton", "LabelFrame"]
    node_id, key = {"title": ("main", "prop:title"), "page": ("pg", "place:page:text")}.get(
        slot, (f"w{classes.index(slot)}" if slot in classes else "", "prop:text")
    )
    started = time.perf_counter()
    _pick(app, _node(app, node_id))
    inspected = time.perf_counter() - started
    print(f"QA H41 {slot}: open {opened:.2f} s, inspect {inspected:.2f} s")
    assert len(_editor(app, key).text()) <= CANVAS_TEXT_LIMIT
    assert opened <= 1.0 * BUDGET_FACTOR and inspected <= 1.0 * BUDGET_FACTOR


_NOTEBOOK = (
    f'{HEAD}<window id="main" kind="main"><layout type="grid"/>'
    '<widget class="Notebook" id="nb"><cell row="0" column="0"/>'
    '<widget class="Frame" id="pg"><page><prop name="text">{text}</prop></page>'
    '<layout type="grid"/></widget></widget></window></pyguibud-ui>'
)


@pytest.mark.gui
def test_qa_19c_06_a_100k_page_title_is_previewed_in_the_inspector(app: Any) -> None:
    """``place:page:text`` is not a ``prop:`` key, so the inspector Entry holds all 100,000
    characters: about 5 s per selection, undo or redo of the page."""
    _open(app, _NOTEBOOK.replace("{text}", "Z" * 100_000))
    _pick(app, _node(app, "pg"))
    assert len(_editor(app, "place:page:text").text()) <= CANVAS_TEXT_LIMIT


@pytest.mark.gui
@pytest.mark.budget
def test_qa_19c_07_re_rendering_a_100k_page_title_takes_under_a_second(app: Any) -> None:
    """The canvas clips the tab to 2,000 characters, but a ttk tab does not wrap: about
    0.65 ms per character, so 1.3 s per re-render (raw acceptance: 1 s). Page not selected."""
    from dataclasses import replace

    _open(app, _NOTEBOOK.replace("{text}", "short"))
    page = _node(app, "pg")
    big = replace(page.placement, text=Prop(name="text", value="Z" * 100_000))
    started = time.perf_counter()
    assert _stack(app).execute(cmds.SetField(page, "placement", big)).accepted
    app.root.update()
    elapsed = time.perf_counter() - started
    print(f"QA-19c-07 page title re-render: {elapsed:.2f} s")
    assert elapsed <= 1.0, elapsed


@pytest.mark.gui
def test_qa_19c_05_a_refused_reset_never_lets_the_preview_write_its_clip(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Latent: any refusal ``report()`` shows on the preview marks it invalid, and an invalid
    editor commits ``text()`` (the 2,000-character clip) on FocusOut or Enter. No real refusal
    of a Reset is known, so it is injected here."""
    _open(app)
    lbl = _long(app, "lbl")
    stack = _stack(app)
    real = stack.execute
    monkeypatch.setattr(
        stack, "execute", lambda _c: cmds.Outcome(accepted=False, changed=False, findings=())
    )
    app.shell.inspector.reset("prop:text")
    monkeypatch.setattr(stack, "execute", real)
    editor = _editor(app, "prop:text")
    editor.widget.event_generate("<FocusOut>")
    editor._enter()
    _settle(app.root)
    assert lbl.props["text"].value == LONG


@pytest.mark.gui
def test_qa_19c_05_the_edit_text_dialog_of_a_long_text_never_saves_the_clip(app: Any) -> None:
    """Latent: the "…" button is greyed on the preview, but ``special("text")`` seeds the
    dialog with ``editor.text()`` (the 2,000-character clip), so OK without a change writes the
    clip back over the 100,000 characters. Expected: the dialog gets the full value (or
    refuses), never the display clip."""
    _open(app)
    lbl = _long(app, "lbl")
    inspector = app.shell.inspector
    inspector.special(_editor(app, "prop:text"), "text")
    _settle(app.root)
    (dialog,) = app._live_dialogs()
    live: Any = dialog
    live.accept()  # OK, nothing changed
    _settle(app.root)
    assert lbl.props["text"].value == LONG


# ================================================================ H41: the paste interception
def _paste(app: Any, editor: Any, text: str, *, start: int | None = None, end: Any = None) -> None:
    _clipboard(app.root, text)
    widget = editor.widget
    widget.selection_clear()
    if end is not None:
        widget.selection_range(start, end)
        widget.icursor(end)
    elif start is not None:
        widget.icursor(start)
    widget.event_generate("<<Paste>>")
    _settle(app.root)


@pytest.mark.gui
@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [(0, None, "P{}Hello"), (5, None, "HelloP{}"), (2, None, "HeP{}llo"), (1, 4, "HP{}o"),
     (0, "end", "P{}")],
    ids=["at-start", "at-end", "middle", "replace-middle", "replace-all"],
)  # fmt: skip
def test_h41_a_long_paste_lands_where_the_cursor_or_the_selection_is(
    app: Any, start: int, end: Any, expected: str
) -> None:
    _open(app)
    lbl = _long(app, "lbl", value="Hello")
    editor = _editor(app, "prop:text")
    body = "P" * 2_500
    _paste(app, editor, body, start=start, end=end)
    assert lbl.props["text"].value == expected.replace("P{}", body)
    assert _locked(_editor(app, "prop:text"))
    assert _stack(app).index == 2  # the SetProp to "Hello", then one paste step


@pytest.mark.gui
def test_h41_a_long_paste_after_typed_text_keeps_the_typed_text(app: Any) -> None:
    _open(app)
    lbl = _long(app, "lbl", value="Hi")
    editor = _editor(app, "prop:text")
    editor.var.set("Hi there ")  # typed, not committed
    _paste(app, editor, "Z" * 3_000, start=len("Hi there "))
    assert lbl.props["text"].value == "Hi there " + "Z" * 3_000


@pytest.mark.gui
def test_h41_a_paste_of_exactly_the_limit_lands_in_the_field_and_commits_on_enter(
    app: Any,
) -> None:
    _open(app)
    lbl = _long(app, "lbl", value="")
    editor = _editor(app, "prop:text")
    _paste(app, editor, "k" * CANVAS_TEXT_LIMIT, start=0)
    assert editor.text() == "k" * CANVAS_TEXT_LIMIT and editor.pending()
    editor._enter()
    _settle(app.root)
    assert lbl.props["text"].value == "k" * CANVAS_TEXT_LIMIT


@pytest.mark.gui
@pytest.mark.parametrize("key", ["field:id", "prop:text"])
def test_h41_a_refused_long_paste_changes_nothing_and_says_why(app: Any, key: str) -> None:
    """Into the Id: 2,001 characters is not an id. Into a text: 100,001 is over the limit."""
    _open(app)
    _pick(app, _node(app, "lbl"))
    editor = _editor(app, key)
    old = editor.text()
    before = _snapshot(app)
    app.shell.clear_message()
    _paste(app, editor, "a" * (2_001 if key == "field:id" else 100_001), start=0)
    assert _snapshot(app) == before and _message(app)
    assert editor.text() == old and len(editor.text()) < 100  # the paste never landed


@pytest.mark.gui
@pytest.mark.parametrize(
    ("node_id", "value", "where"),
    [("lbl", EMOJI + "abc", (2, None)), ("lbl", EMOJI + "abc", (2, "end")),
     ("main", EMOJI * 2 + "xy", (4, None))],
    ids=["insert-after-emoji", "replace-after-emoji", "title-after-two-emoji"],
)  # fmt: skip
def test_qa_19c_02_a_long_paste_next_to_an_emoji_lands_at_the_cursor(
    app: Any, node_id: str, value: str, where: tuple[int, Any]
) -> None:
    """Tk 8.6 counts a non-BMP character as two indices; ``_paste`` slices the Python str
    with them, so the paste lands one character too far per emoji before the cursor (and a
    replaced selection keeps a character). Expected: the text a user sees is what is kept."""
    _open(app)
    prop = "title" if node_id == "main" else "text"
    node = _long(app, node_id, prop, value=value)
    editor = _editor(app, f"prop:{prop}")
    body = "Z" * 2_500
    start, end = where
    _paste(app, editor, body, start=start, end=end)
    emojis = value.count(EMOJI)
    head = value[:emojis]  # every emoji before the cursor, in the str
    tail = "" if end == "end" else value[emojis:]
    assert ascii(node.props[prop].value) == ascii(head + body + tail)


_PLAIN = {
    "row-spinbox": "place:grid:row",
    "padx-spinbox": "place:grid:padx",
    "bootstyle-combobox": "tb:bootstyle",
}


@pytest.mark.gui
@pytest.mark.parametrize("name", sorted(_PLAIN))
def test_qa_19c_01_a_long_paste_never_lands_in_a_spinbox_or_combobox_editor(
    app: Any, name: str
) -> None:
    """A 100,000-character paste into the Row/Padx spinboxes or the Bootstyle combobox lands
    in the widget: about 20 s to lay it out, 15 s more for the (refused) commit, and the
    designer is "Not responding". 2,001 characters show it in milliseconds."""
    _open(app)
    _pick(app, _node(app, "lbl"))
    editor = _editor(app, _PLAIN[name])
    _paste(app, editor, "9" * 2_001, start=0)
    assert len(editor.text()) <= CANVAS_TEXT_LIMIT


@pytest.mark.gui
def test_qa_19c_01_a_long_paste_never_lands_in_the_other_designer_text_fields(app: Any) -> None:
    """The Variables Id/Default entries, the Events handler box and the Rename window entry."""
    _open(app)
    panel = app.shell.variables
    assert panel.tree is not None
    panel.tree.selection_set("count")
    _pick(app, _node(app, "btn"))
    _clipboard(app.root, "9" * 2_001)
    fields: list[tuple[str, Any, Callable[[], str]]] = [
        ("variables-id", panel.id_entry, panel.id_var.get),
        ("variables-default", panel.default_entry, panel.default_var.get),
    ]
    box = app.shell.inspector.events.editors()[0]
    fields.append(("events-handler", box.widget, box.var.get))
    landed = []
    for name, widget, read in fields:
        widget.icursor(0)
        widget.event_generate("<<Paste>>")
        _settle(app.root)
        if len(read()) > CANVAS_TEXT_LIMIT:
            landed.append(name)
    box.revert()  # the typed texts would block Document > Rename (flushed first)
    panel.id_var.set("count")
    panel.default_var.set("")
    _pick(app, _node(app, "dlg"))
    assert app.shell._invoke("document.rename")
    (dialog,) = app._live_dialogs()
    live: Any = dialog
    live.entry.icursor(0)
    live.entry.event_generate("<<Paste>>")
    _settle(app.root)
    if len(live.value.get()) > CANVAS_TEXT_LIMIT:
        landed.append("rename-window")
    live.close()
    assert not landed, landed


@pytest.mark.gui
@pytest.mark.slow
@pytest.mark.budget
def test_qa_19c_01_a_100k_paste_into_the_row_spinbox_keeps_the_designer_responsive(
    app: Any,
) -> None:
    _open(app)
    _pick(app, _node(app, "lbl"))
    editor = _editor(app, "place:grid:row")
    before = _snapshot(app)
    started = time.perf_counter()
    _paste(app, editor, "9" * 100_000, start=0)
    editor.commit_pending()
    _settle(app.root)
    elapsed = time.perf_counter() - started
    print(f"QA-19c-01 spinbox paste: {elapsed:.2f} s")
    assert _snapshot(app) == before
    assert elapsed <= 1.0 * BUDGET_FACTOR, elapsed


# ================================================================ H37: failed undo/redo
@pytest.fixture
def quiet_log() -> Iterator[None]:
    """The stack logs the injected failure with a traceback; keep the output readable."""
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def _raise_first(monkeypatch: pytest.MonkeyPatch, cls: type, name: str, calls: int = 1) -> None:
    """``cls.name`` raises (before changing anything) on its next ``calls`` calls."""
    real = getattr(cls, name)
    left = [calls]

    def flaky(self: Any) -> None:
        if left[0] > 0:
            left[0] -= 1
            raise RuntimeError("injected by QA 19c")
        real(self)

    monkeypatch.setattr(cls, name, flaky)


@pytest.mark.gui
@pytest.mark.usefixtures("quiet_log")
def test_h37_a_failed_undo_via_the_menu_and_ctrl_z_keeps_document_canvas_and_history(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = _open(app)
    lbl = _node(app, "lbl")
    stack = _stack(app)
    assert stack.execute(cmds.SetProp(lbl, Prop(name="text", value="Changed"))).accepted
    _settle(app.root)
    before = _snapshot(app)
    stage = app.shell.canvas.stage_of(document.children[0])
    _raise_first(monkeypatch, cmds.SetProp, "revert", calls=2)
    app.shell.clear_message()
    assert app.shell._invoke("edit.undo")  # Edit > Undo
    _settle(app.root)
    assert _snapshot(app) == before and _message(app) == UNDO_FAILED
    assert stack.failure is not None and stack.failure.code == "command.undo_failed"
    assert str(stage.view.outer[id(lbl)].cget("text")) == "Changed"
    assert _entry_state(app, "edit.undo") == ["normal"] * len(_entry_state(app, "edit.undo"))
    tree = app.shell.tree.tree
    with _focused(app.root, tree):
        app.shell.clear_message()
        tree.event_generate("<Control-z>")  # the second injected failure, by the key
        _settle(app.root)
        assert _snapshot(app) == before and _message(app) == UNDO_FAILED
        tree.event_generate("<Control-z>")  # the patch is spent: a real undo now
        _settle(app.root)
    assert lbl.props["text"].value == "Hi" and stack.failure is None
    assert str(stage.view.outer[id(lbl)].cget("text")) == "Hi"


@pytest.mark.gui
@pytest.mark.usefixtures("quiet_log")
def test_h37_a_failed_redo_is_told_and_the_redo_stays_available(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _open(app)
    lbl = _node(app, "lbl")
    stack = _stack(app)
    assert stack.execute(cmds.SetProp(lbl, Prop(name="text", value="Changed"))).accepted
    assert stack.undo()
    _settle(app.root)
    before = _snapshot(app)
    _raise_first(monkeypatch, cmds.SetProp, "apply")
    app.shell.clear_message()
    assert app.shell._invoke("edit.redo")
    _settle(app.root)
    assert _snapshot(app) == before and _message(app) == UNDO_FAILED and stack.can_redo
    assert app.shell._invoke("edit.redo")
    _settle(app.root)
    assert lbl.props["text"].value == "Changed" and stack.failure is None


@pytest.mark.gui
@pytest.mark.usefixtures("quiet_log")
def test_h37_a_multi_delete_whose_second_restore_fails_is_left_exactly_deleted(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Macro.revert: the first RemoveNode is restored, the second raises; the first must be
    removed again, so the document is byte-identical to the deleted state."""
    _open(app)
    start = _snapshot(app)
    app.session.select_many([_node(app, n) for n in ("outer", "lbl", "btn")], origin="tree")
    app.shell._invoke("edit.delete")
    _settle(app.root)
    for dialog in app._live_dialogs():  # a confirmation, if any
        dialog.confirm()
    _settle(app.root)
    deleted = _snapshot(app)
    assert deleted[1] == start[1] + 1
    real = cmds.RemoveNode.revert
    calls = [0]

    def second_fails(self: Any) -> None:
        calls[0] += 1
        if calls[0] == 2:
            raise RuntimeError("injected by QA 19c")
        real(self)

    monkeypatch.setattr(cmds.RemoveNode, "revert", second_fails)
    app.shell.clear_message()
    assert app.shell._invoke("edit.undo")
    _settle(app.root)
    assert calls[0] >= 2, "the macro did not reach its second sub-command"
    assert _snapshot(app) == deleted and _message(app) == UNDO_FAILED
    monkeypatch.setattr(cmds.RemoveNode, "revert", real)
    assert app.shell._invoke("edit.undo")
    _settle(app.root)
    assert _snapshot(app) == start


@pytest.mark.gui
@pytest.mark.usefixtures("quiet_log")
def test_h37_a_failed_save_whose_rebase_undo_fails_says_both_reasons(
    app: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real stack (not a fake): write_ui fails, then the rebase's revert fails too."""
    document = _open(app)
    window = document.children[0]

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise XmlIoError("xml.write_failed", "The disk is full.")

    monkeypatch.setattr("pyguibud.designer.app.write_ui", refuse)
    _raise_first(monkeypatch, cmds.SetField, "revert")
    plan = SavePlan(target=tmp_path / "x.ui", rebase=cmds.SetField(window, "id", "rebased"))
    app._write(plan, None)
    _settle(app.root)
    (dialog,) = app._live_dialogs()
    live: Any = dialog
    assert str(live.label.cget("text")) == f"The disk is full.\n\n{UNDO_FAILED}"
    assert window.id == "rebased" and _stack(app).is_dirty
    assert not (tmp_path / "x.ui").exists()
    live.close()


@pytest.mark.usefixtures("quiet_log")
def test_qa_19c_03_a_revert_that_raises_after_changing_the_model_clears_the_history() -> None:
    """Spec 19c: "On an exception, the snapshot taken before undo/redo is restored". The stack
    only relies on each command compensating itself: a revert that changes the model and then
    raises leaves the change, the history index unchanged and the message "the document was
    left as it was"; every later undo then fails ("not applied") - the history is wedged."""
    document = read_ui_string(FORM).document
    stack = CommandStack(document, REG)
    lbl: Any = next(n for n in document.walk() if getattr(n, "id", None) == "lbl")
    assert stack.execute(cmds.SetProp(lbl, Prop(name="text", value="Changed"))).accepted
    before = dump_ui(document)
    real = cmds.SetProp.revert

    def late(self: Any) -> None:
        real(self)
        raise RuntimeError("injected by QA 19c after the change")

    cmds.SetProp.revert = late  # type: ignore[method-assign]
    try:
        assert stack.undo() is False
    finally:
        cmds.SetProp.revert = real  # type: ignore[method-assign]
    # Ruled behaviour: the model changed, so the history is dropped and the document stays dirty.
    assert dump_ui(document) != before
    assert stack.failure is not None and stack.failure.code == "command.history_cleared"
    assert "may have changed" in stack.failure.message
    assert not stack.can_undo and not stack.can_redo and stack.is_dirty


def test_h37_the_new_msgids_are_in_the_catalogue_template() -> None:
    """Read-only: the translator owns the catalogues; the template must hold the new texts."""
    pot = (ROOT / "src" / "pyguibud" / "locale" / "pyguibud.pot").read_text("utf-8")
    for msgid in (UNDO_FAILED, CUT_REFUSAL, "This text has {length} characters"):
        assert msgid in pot, msgid


# ================================================================ H40: busy guard
def _start_canvas_drag(app: Any, node_id: str) -> tuple[Any, Any]:
    document = app.session.document
    stage = app.shell.canvas.stage_of(document.children[0])
    node = _node(app, node_id)
    _pick(app, node)
    widget = stage.view.outer[id(node)]
    sx, sy = widget.winfo_rootx() + 2, widget.winfo_rooty() + 2
    widget.event_generate("<ButtonPress-1>", x=2, y=2, rootx=sx, rooty=sy, time=next(_CLOCK))
    widget.event_generate("<B1-Motion>", x=14, y=2, rootx=sx + 12, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=40, y=30, rootx=sx + 38, rooty=sy + 28, state=0x100)
    return widget, (sx + 38, sy + 28)


@pytest.mark.gui
def test_h40_a_palette_insert_or_hint_during_a_canvas_move_drag_changes_nothing(
    app: Any,
) -> None:
    _open(app)
    _start_canvas_drag(app, "lbl")
    drag = app.shell.drag
    if drag.state != "dragging":
        pytest.skip(f"the drag did not start (state {drag.state})")
    before, status = _snapshot(app), _message(app)
    try:
        assert app.shell.palette._activate("w:Button") == "break"
        drag.insert_widget("Button")
        drag.hint("Label")
        assert _snapshot(app) == before and _message(app) == status
        assert drag.state == "dragging"
    finally:
        drag.cancel()
    _settle(app.root)
    assert _snapshot(app) == before and not drag.busy
    _pick(app, _node(app, "outer"))
    drag.insert_widget("Label")  # once idle, the palette inserts again (the guard is not stuck)
    _settle(app.root)
    assert _stack(app).index == before[1] + 1


@pytest.mark.gui
def test_h40_a_palette_insert_during_a_rubber_band_changes_nothing(app: Any) -> None:
    document = _open(app)
    window = document.children[0]
    stage = app.shell.canvas.stage_of(window)
    drag = app.shell.drag
    _pick(app, window)
    x, y = stage.stage.winfo_rootx() + 300, stage.stage.winfo_rooty() + 200
    drag.press_band(window, (), None, x, y)
    drag.motion(x + 40, y + 40)
    if drag.state != "banding":
        pytest.skip(f"the band did not start (state {drag.state})")
    before, status = _snapshot(app), _message(app)
    try:
        assert app.shell.palette._activate("w:Label") == "break"
        drag.insert_widget("Label")
        drag.hint("Label")
        assert _snapshot(app) == before and _message(app) == status and drag.busy
    finally:
        drag.cancel()
    _settle(app.root)
    assert not drag.busy and _snapshot(app) == before


# ================================================================ H43: Cut on a window
@pytest.mark.gui
@pytest.mark.parametrize("node_id", ["main", "dlg"])
def test_h43_cut_on_a_window_is_greyed_everywhere_and_ctrl_x_says_why(
    app: Any, node_id: str
) -> None:
    _open(app)
    _pick(app, _node(app, node_id))
    states = _entry_state(app, "edit.cut")
    assert states and set(states) == {"disabled"}, states  # Edit menu and the tree menu
    assert all("disabled" in s for s in _button_state(app, "edit.cut"))  # the toolbar
    assert set(_entry_state(app, "edit.copy")) == {"normal"}
    assert set(_entry_state(app, "edit.duplicate")) == {"normal"}
    _clipboard(app.root, "SENTINEL")
    before = _snapshot(app)
    tree = app.shell.tree.tree
    with _focused(app.root, tree):
        app.shell.clear_message()
        tree.event_generate("<Control-x>")
        _settle(app.root)
        assert _message(app) == CUT_REFUSAL
    assert _snapshot(app) == before and str(app.root.clipboard_get()) == "SENTINEL"
    app.shell.clear_message()
    assert not app.shell._invoke("edit.cut")
    app.shell._explain_refusal("edit.cut")  # what a stale toolbar button press shows
    assert _message(app) == CUT_REFUSAL
    _pick(app, _node(app, "lbl"))
    assert set(_entry_state(app, "edit.cut")) == {"normal"}


@pytest.mark.gui
def test_h43_cut_on_a_window_in_every_locale_is_refused_in_that_language(app: Any) -> None:
    _open(app)
    _pick(app, _node(app, "dlg"))
    seen = set()
    for code in LOCALES:
        app.set_language(code)
        _settle(app.root)
        app.shell.clear_message()
        app.shell._explain_refusal("edit.cut")
        reason = _message(app)
        assert reason, code
        seen.add(reason)
    app.set_language("en_GB")
    print(f"QA H43: {len(seen)} distinct refusals over {len(LOCALES)} locales")


# ================================================================ H38: D10 placement change
def _grid(cells: dict[str, tuple[int, int, int, int]]) -> tuple[Any, dict[str, Any]]:
    body = "".join(
        f'<widget class="Label" id="{k}"><cell row="{r}" column="{c}" rowspan="{rs}"'
        f' columnspan="{cs}"/></widget>'
        for k, (r, c, rs, cs) in cells.items()
    )
    document = read_ui_string(
        f'{HEAD}<window id="main" kind="main"><layout type="grid"/>{body}</window></pyguibud-ui>'
    ).document
    return document, {n.id: n for n in document.walk() if isinstance(n, Widget)}


def test_h38_a_wide_block_dropped_after_a_tall_sibling_lands_below_it() -> None:
    document, n = _grid({"x": (0, 1, 2, 1), "a": (0, 0, 1, 1), "w": (3, 0, 1, 2)})
    found = tree_dnd.target(n["x"], "after", [n["w"]], REG)
    assert isinstance(found, Target)
    built = move_command([n["w"]], found)
    assert not isinstance(built, str)
    stack = CommandStack(document, REG)
    before = dump_ui(document)
    assert stack.execute(built).accepted
    assert n["w"].placement.row >= n["x"].placement.row + n["x"].placement.rowspan
    assert stack.undo() and dump_ui(document) == before


def _random_drops(
    zone: Literal["before", "after"], seed: int = 19, rounds: int = 3_000
) -> list[str]:
    rng = random.Random(seed)
    wrong: list[str] = []
    for _ in range(rounds):
        cells: dict[str, tuple[int, int, int, int]] = {}
        taken: set[tuple[int, int]] = set()
        for r in range(rng.randint(1, 5)):
            for c in range(rng.randint(1, 3)):
                if (r, c) in taken or rng.random() < 0.35:
                    continue
                rs, cs = rng.choice([1, 1, 2, 3]), rng.choice([1, 1, 2])
                area = {(rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs)}
                if area & taken:
                    rs = cs = 1
                    area = {(r, c)}
                taken |= area
                cells[f"n{r}{c}"] = (r, c, rs, cs)
        if len(cells) < 2:
            continue
        moving, onto = rng.sample(sorted(cells), 2)
        document, n = _grid(cells)
        found = tree_dnd.target(n[onto], zone, [n[moving]], REG)
        built = move_command([n[moving]], found) if isinstance(found, Target) else "no"
        if isinstance(built, str) or not CommandStack(document, REG).execute(built).accepted:
            continue
        w, t = n[moving].placement, n[onto].placement
        if zone == "after" and w.row + max(w.rowspan, 1) - 1 < t.row:
            wrong.append(f"{cells} {moving} after {onto} -> {w.row},{w.column}")
        if zone == "before" and w.row > t.row + max(t.rowspan, 1) - 1:
            wrong.append(f"{cells} {moving} before {onto} -> {w.row},{w.column}")
    return wrong


def test_h38_no_block_dropped_after_a_sibling_ever_lands_above_it() -> None:
    assert _random_drops("after") == []


def test_qa_19c_04_a_block_dropped_before_a_sibling_never_lands_below_it() -> None:
    """The D10 shift fires for any drop whose cells overlap a sibling starting above them,
    "before" drops included: y at (2, 0), a tall x at rows 1-3 of column 1, and a wide w
    dropped "before y" lands on row 4, under y. 10 of about 2,500 random drops do this."""
    document, n = _grid({"y": (2, 0, 1, 1), "x": (1, 1, 3, 1), "w": (5, 0, 1, 2)})
    found = tree_dnd.target(n["y"], "before", [n["w"]], REG)
    assert isinstance(found, Target)
    built = move_command([n["w"]], found)
    assert not isinstance(built, str)
    assert CommandStack(document, REG).execute(built).accepted
    assert n["w"].placement.row <= n["y"].placement.row
    assert _random_drops("before") == []


# ================================================================ H03: shrunk/huge withdrawn root
_H03 = textwrap.dedent(
    """
    import faulthandler, sys
    faulthandler.dump_traceback_later(45, exit=True)
    import ttkbootstrap
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings
    size = sys.argv[1]
    root = ttkbootstrap.App(title="qa19c-h03")
    root.geometry(size)
    root.update()                       # mapped at that size ...
    root.withdraw()                     # ... then withdrawn
    root.update_idletasks()
    app = DesignerApp(root, settings=Settings())
    root.update_idletasks()
    print("built", flush=True)
    root.deiconify(); root.geometry("1x1"); root.update(); root.update_idletasks()
    root.geometry(size); root.update(); root.update_idletasks()
    root.withdraw(); root.update_idletasks()
    print("idle ok", flush=True)
    app.dispose()
    root.destroy()
    """
)


@pytest.mark.gui
@pytest.mark.parametrize("size", ["1x1", "7680x4320", "200x200"])
def test_h03_a_designer_on_a_mapped_then_withdrawn_root_never_livelocks(
    size: str, tmp_path: Path
) -> None:
    env_dir = tmp_path / "profile"
    env = {
        **__import__("os").environ,
        "PYGUIBUD_CONFIG_DIR": str(env_dir / "c"),
        "PYGUIBUD_STATE_DIR": str(env_dir / "s"),
    }
    try:
        done = subprocess.run(
            [sys.executable, "-c", _H03, size],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"livelock at {size}: {exc.stderr!r}")
    assert done.returncode == 0 and "idle ok" in done.stdout, done.stderr[-2000:]


# keep the i18n import used (the autouse conftest resets it; the locale loop switches it)
assert i18n is not None and Window is not None
