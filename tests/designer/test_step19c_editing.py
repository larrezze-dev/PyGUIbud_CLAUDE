"""Step 19c (frontend): editing and model abuse through the designer (spec hardening 19c).

H03 livelock, H32 ids through the GUI, H33/H34 drops and grid values, H36 storms and
clipboard garbage, H37 failed undo/redo told to the user, H39/H40 race guards, H41 the
100,000-character text on the canvas, H43 Cut on a window.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import CommandStack, default_registry, dump_ui, read_ui_string
from pyguibud.core.commands import SetField, SetProp
from pyguibud.core.diagnostics import Finding
from pyguibud.core.errors import XmlIoError
from pyguibud.core.model import Prop, Widget
from pyguibud.core.xml_io import MAX_UI_BYTES
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.clipboard_actions import ClipboardActions
from pyguibud.designer.edit import EditActions
from pyguibud.designer.files import SavePlan
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT
from pyguibud.designer.session import DesignerSession
from tests.conftest import BUDGET_FACTOR

REG = default_registry()
ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"
HEAD = '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
FORM = (
    f'{HEAD}<window id="main" kind="main"><layout type="grid"/>'
    '<widget class="Frame" id="outer"><cell row="0" column="0"/><layout type="grid"/>'
    '<widget class="Frame" id="inner"><cell row="0" column="0"/><layout type="grid"/></widget>'
    "</widget>"
    '<widget class="Label" id="lbl"><cell row="1" column="0"/>'
    '<prop name="text">Hi</prop></widget>'
    '</window><window id="dlg" kind="dialog"><layout type="pack"/></window></pyguibud-ui>'
)
FINDING = Finding(
    code="command.undo_failed",
    msgid="The step could not be undone; the document was kept as it was.",
    source="<stack>",
    severity="error",
)
FULL_WIDTH = "".join(map(chr, (0xFF41, 0xFF42, 0xFF43)))  # Unicode lookalikes of "abc"
BAD_IDS = ("class", "None", "_private", "1abc", "a-b", FULL_WIDTH, "x" * 10_000)


def _session(text: str = FORM) -> DesignerSession:
    session = DesignerSession(REG)
    session.open_result(read_ui_string(text), name="t")
    return session


def _node(session: DesignerSession, node_id: str) -> Any:
    assert session.document is not None
    return next(n for n in session.document.walk() if getattr(n, "id", None) == node_id)


# ---------------------------------------------------------------- H03 (subprocess)
_H03 = textwrap.dedent(
    """
    import faulthandler, sys
    faulthandler.dump_traceback_later(40, exit=True)
    import ttkbootstrap
    from pyguibud.designer.app import DesignerApp
    root = ttkbootstrap.App(title="h03")
    root.update()
    root.geometry("")  # an empty root that was mapped shrinks to 200 x 200 ...
    root.update_idletasks()
    root.withdraw()  # ... and is then withdrawn
    root.update_idletasks()
    app = DesignerApp(root)
    root.update_idletasks()  # livelocked here before Step 19c
    print("idle ok", flush=True)
    app.dispose()
    root.destroy()
    """
)


@pytest.mark.gui
def test_h03_a_designer_on_a_shrunk_withdrawn_root_leaves_update_idletasks() -> None:
    """The sash clamp re-wrote an unchanged (clipped) sash, whose <Configure> queued the next
    clamp for ever. Run apart, so a regression fails here instead of hanging the suite."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", _H03], capture_output=True, text=True, timeout=90, check=False
        )
    except subprocess.TimeoutExpired as exc:
        pytest.fail(f"the designer livelocked in update_idletasks: {exc.stderr!r}")
    assert done.returncode == 0 and "idle ok" in done.stdout, done.stderr[-2000:]


# ---------------------------------------------------------------- H37 (fake stack)
def _failing(monkeypatch: pytest.MonkeyPatch, stack: CommandStack, *, redo: bool = True) -> None:
    """``stack`` behaves as the backend contract says when a revert raises (H37)."""
    monkeypatch.setattr(stack, "undo", lambda: False)
    monkeypatch.setattr(type(stack), "failure", property(lambda _s: FINDING))
    if redo:
        monkeypatch.setattr(stack, "redo", lambda: False)
        monkeypatch.setattr(type(stack), "can_redo", property(lambda _s: True))


def test_h37_a_failed_undo_or_redo_is_told_in_the_status_bar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _session()
    stack = session.stack
    assert stack is not None
    assert stack.execute(SetField(_node(session, "lbl"), "id", "label")).accepted
    messages: list[str] = []
    edit = EditActions(session, lambda _q, _then: None, messages.append)
    _failing(monkeypatch, stack)
    edit.undo()
    edit.redo()
    assert messages == [FINDING.message, FINDING.message]


def test_h37_nothing_is_told_when_there_is_nothing_to_undo() -> None:
    session = _session()
    messages: list[str] = []
    edit = EditActions(session, lambda _q, _then: None, messages.append)
    edit.undo()
    edit.redo()
    assert messages == []


@pytest.mark.gui
def test_h37_a_failed_rebase_undo_after_a_failed_save_is_told(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shell.session.new_from_template("main_window")
    stack, document = shell.session.stack, shell.session.document
    assert stack is not None and document is not None
    window = document.children[0]

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise XmlIoError("xml.write_failed", "The disk is full.")

    monkeypatch.setattr("pyguibud.designer.app.write_ui", refuse)
    plan = SavePlan(target=tmp_path / "x.ui", rebase=SetField(window, "id", "rebased"))
    _failing(monkeypatch, stack, redo=False)
    shell._write(plan, None)
    (dialog,) = shell._live_dialogs()  # the OS reason, then why the rebase stays
    shown: Any = dialog
    assert str(shown.label.cget("text")) == f"The disk is full.\n\n{FINDING.message}"
    assert window.id == "rebased" and stack.is_dirty  # still rebased and unsaved
    shown.close()


# ---------------------------------------------------------------- H43
def test_h43_cut_is_greyed_and_refused_on_a_window_but_duplicate_is_not() -> None:
    session = _session()
    store = {"text": "SENTINEL"}
    messages: list[str] = []
    clip = ClipboardActions(
        session, messages.append, lambda t: store.__setitem__("text", t), lambda: store["text"]
    )
    document = session.document
    assert document is not None
    before = dump_ui(document)
    session.select(_node(session, "dlg"), origin="tree")
    assert not clip.can_cut() and clip.can_duplicate() and clip.can_copy()
    assert clip.cut_refusal() == "Windows are deleted with Document ▸ Delete window."
    clip.cut()
    assert messages == [clip.cut_refusal()] and store["text"] == "SENTINEL"
    assert dump_ui(document) == before
    session.select(_node(session, "lbl"), origin="tree")
    assert clip.can_cut() and clip.cut_refusal() is None


# ---------------------------------------------------------------- H41
@pytest.mark.gui
@pytest.mark.budget
def test_h41_a_100k_text_re_renders_within_a_second_and_is_clipped_only_on_the_canvas(
    shell: DesignerApp, designer_root: Any
) -> None:
    assert shell.open_path(HELLO)
    designer_root.update()
    document, stack = shell.session.document, shell.session.stack
    assert document is not None and stack is not None
    label = next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label")
    texts = iter(("W" * 100_000, "M" * 100_000) * 4)

    def render() -> None:
        assert stack.execute(SetProp(label, Prop(name="text", value=next(texts)))).accepted
        designer_root.update()

    started = time.perf_counter()
    render()
    first = time.perf_counter() - started
    assert first <= 1.0 * BUDGET_FACTOR, first
    assert len(label.props["text"].value) == 100_000  # the model keeps every character
    assert b"W" * 100_000 in dump_ui(document)
    stage = shell.shell.canvas.stage_of(document.children[0])
    assert stage is not None and stage.view is not None
    drawn = str(stage.view.outer[id(label)].cget("text"))
    assert len(drawn) == CANVAS_TEXT_LIMIT and drawn.endswith("…")


# ---------------------------------------------------------------- H32 ids through the GUI
def _settle(root: Any, rounds: int = 3) -> None:
    for _ in range(rounds):
        root.update()


def _form(app: DesignerApp, root: Any) -> Any:
    app.session.open_result(read_ui_string(FORM), name="t")
    _settle(root)
    document = app.session.document
    assert document is not None
    return document


@pytest.mark.gui
@pytest.mark.parametrize("bad", [*BAD_IDS, "outer"], ids=[*BAD_IDS[:6], "10000-chars", "dup"])
def test_h32_the_inspector_id_field_refuses_a_bad_id_with_a_reason(
    shell: DesignerApp, designer_root: Any, bad: str
) -> None:
    document = _form(shell, designer_root)
    shell.session.select(_node(shell.session, "lbl"), origin="tree")
    _settle(designer_root)
    before = dump_ui(document)
    editor: Any = shell.shell.inspector._editors["field:id"]
    shell.shell.clear_message()
    editor.var.set(bad)
    editor._enter()
    _settle(designer_root)
    assert dump_ui(document) == before and shell.session.stack is not None
    assert not shell.session.stack.can_undo
    assert shell.shell._message, bad  # the reason is in the status bar
    editor._escape()


@pytest.mark.gui
def test_h32_the_rename_window_dialog_refuses_every_bad_id(
    shell: DesignerApp, designer_root: Any
) -> None:
    document = _form(shell, designer_root)
    shell.session.select(_node(shell.session, "dlg"), origin="tree")
    before = dump_ui(document)
    assert shell.shell._invoke("document.rename")
    (dialog,) = shell._live_dialogs()
    live: Any = dialog
    for bad in (*BAD_IDS, "main"):
        live.value.set(bad)
        live.accept()
        assert not live.closed, bad
        assert live.reason.cget("text"), bad
        assert dump_ui(document) == before
    live.close()


@pytest.mark.gui
def test_h32_the_variables_id_field_refuses_every_bad_id(
    shell: DesignerApp, designer_root: Any
) -> None:
    from pyguibud.designer.editing import new_variable

    document = _form(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None
    for _ in range(2):
        assert stack.execute(new_variable(document)).accepted
    first, second = list(document.variables)
    panel = shell.shell.variables
    _settle(designer_root)
    tree = panel.tree
    assert tree is not None
    tree.selection_set(second)
    _settle(designer_root)
    before, depth = dump_ui(document), stack.index
    for bad in (*BAD_IDS, first):
        shell.shell.clear_message()
        panel.id_var.set(bad)
        panel._commit_id()
        assert dump_ui(document) == before and stack.index == depth, bad
        assert shell.shell._message, bad
    panel.id_var.set(second)


# ---------------------------------------------------------------- H33 grid values
@pytest.mark.gui
@pytest.mark.parametrize(
    ("key", "text"),
    [("place:grid:row", "-1"), ("place:grid:row", "99999999"), ("place:grid:column", "-7"),
     ("place:grid:rowspan", "0"), ("place:grid:rowspan", "-2"), ("place:grid:columnspan", "100000"),
     ("place:grid:padx", "-5"), ("place:grid:pady", "999999999"), ("place:grid:row", "1e3"),
     ("place:grid:row", "0"), ("place:grid:column", "abc")],
)  # fmt: skip
def test_h33_absurd_grid_values_in_the_inspector_are_refused_with_a_reason(
    shell: DesignerApp, designer_root: Any, key: str, text: str
) -> None:
    """Row 0 collides with 'outer': the validator refuses it as well."""
    document = _form(shell, designer_root)
    shell.session.select(_node(shell.session, "lbl"), origin="tree")
    _settle(designer_root)
    before = dump_ui(document)
    editor: Any = shell.shell.inspector._editors[key]
    shell.shell.clear_message()
    editor.var.set(text)
    assert not editor.commit_pending()
    assert dump_ui(document) == before and shell.shell._message, (key, text)
    editor._escape()


# ---------------------------------------------------------------- H34 cyclic and leaf drops
INTO_ITSELF = "A widget cannot be dropped into itself."


@pytest.mark.parametrize(
    ("row", "zone", "moving", "reason"),
    [("inner", "into", "outer", INTO_ITSELF), ("inner", "after", "outer", INTO_ITSELF),
     ("outer", "into", "outer", INTO_ITSELF),
     ("lbl", "into", "inner", "'lbl' cannot hold elements: drop them before or after it."),
     ("main", "into", "main", "Only widgets and included components can be moved."),
     ("dlg", "into", "main", "Only widgets and included components can be moved.")],
)  # fmt: skip
def test_h34_tree_drops_into_a_leaf_itself_or_a_descendant_are_refused(
    row: str, zone: str, moving: str, reason: str
) -> None:
    from pyguibud.designer import tree_dnd

    session = _session()
    found = tree_dnd.target(_node(session, row), zone, [_node(session, moving)], REG)  # type: ignore[arg-type]
    assert found == reason


def test_h34_keyboard_moves_never_reparent_and_refuse_a_window() -> None:
    from pyguibud.designer.editing import nudge_command, reorder_command

    session = _session()
    assert session.document is not None
    before = dump_ui(session.document)
    window = _node(session, "main")
    for built in (nudge_command([window], 1, 0), reorder_command([window], 1)):
        assert isinstance(built, str) and built
    built = nudge_command([_node(session, "inner")], 0, -1)  # off the grid's left edge
    assert isinstance(built, str) and built
    assert dump_ui(session.document) == before


def test_h34_paste_on_a_leaf_never_nests_inside_it() -> None:
    session = _session()
    store = {"text": ""}
    messages: list[str] = []
    clip = ClipboardActions(
        session, messages.append, lambda t: store.__setitem__("text", t), lambda: store["text"]
    )
    outer = _node(session, "outer")
    session.select(outer, origin="tree")
    clip.copy()
    session.select(_node(session, "lbl"), origin="tree")
    clip.paste()  # beside the Label, never inside it
    assert not _node(session, "lbl").children and "pasted" in messages[-1].lower()
    session.select(_node(session, "inner"), origin="tree")
    clip.paste()  # a copy into its own child is a copy, not a cycle
    assert session.document is not None
    assert sum(getattr(w, "id", "") == "outer" for w in session.document.walk()) == 1


@pytest.mark.gui
def test_h34_a_canvas_drag_of_a_frame_onto_its_own_child_changes_nothing(
    shell: DesignerApp, designer_root: Any
) -> None:
    document = _form(shell, designer_root)
    stage = shell.shell.canvas.stage_of(document.children[0])
    assert stage is not None and stage.view is not None
    outer, inner = _node(shell.session, "outer"), _node(shell.session, "inner")
    shell.session.select(outer, origin="canvas")  # a press on a selected frame drags it
    _settle(designer_root)
    before = dump_ui(document)
    widget, target = stage.view.outer[id(outer)], stage.view.inner[id(inner)]
    sx, sy = widget.winfo_rootx() + 2, widget.winfo_rooty() + 2
    tx = target.winfo_rootx() + target.winfo_width() // 2
    ty = target.winfo_rooty() + target.winfo_height() // 2
    widget.event_generate("<ButtonPress-1>", x=2, y=2, rootx=sx, rooty=sy, time=10_000)
    widget.event_generate("<B1-Motion>", x=12, y=2, rootx=sx + 10, rooty=sy, state=0x100)
    widget.event_generate("<B1-Motion>", x=0, y=0, rootx=tx, rooty=ty, state=0x100)
    assert shell.shell.drag.state == "dragging"
    widget.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=tx, rooty=ty, state=0x100, time=20_000
    )
    _settle(designer_root)
    assert dump_ui(document) == before and inner.parent is outer
    assert shell.shell._message  # e.g. "'outer' is already there.": its own area is no target
    assert shell.session.stack is not None and not shell.session.stack.can_undo


# ---------------------------------------------------------------- H36 storms
@pytest.mark.gui
def test_h36_a_storm_of_1000_undo_and_redo_presses_never_freezes(
    shell: DesignerApp, designer_root: Any
) -> None:
    document = _form(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None
    label = _node(shell.session, "lbl")
    start = dump_ui(document)
    for k in range(25):
        assert stack.execute(SetProp(label, Prop(name="text", value=f"step {k}"))).accepted
        stack.break_merge()
    end = dump_ui(document)
    started = time.perf_counter()
    for k in range(1000):  # key repeat: undo all the way and back, twice, with presses to spare
        shell.shell._invoke("edit.undo" if (k // 250) % 2 == 0 else "edit.redo")
        designer_root.update()
    elapsed = time.perf_counter() - started
    assert dump_ui(document) == end and stack.index == 25
    for k in range(1000):  # every press a real step: undo, redo, undo, ...
        shell.shell._invoke("edit.redo" if k % 2 else "edit.undo")
        designer_root.update()
    elapsed = time.perf_counter() - started
    assert dump_ui(document) == end and stack.index == 25
    assert elapsed < 60 * BUDGET_FACTOR, elapsed
    print(f"H36 storm: {elapsed:.2f} s")
    while stack.can_undo:
        stack.undo()
    assert dump_ui(document) == start


@pytest.mark.parametrize(
    "text",
    ["lorem ipsum " * 400, '<widget class="Label" id="x"><prop name="text">', f"{HEAD}<window",
     f'{HEAD}<window id="w"><widget class="Label" id="1bad"/></window></pyguibud-ui>',
     "<" * 200_000, "W" * 6_000_000, "", "\x00\ud800"],
    ids=["random-text", "broken-widget", "truncated-doc", "bad-id", "angles", "huge", "empty",
         "nul-surrogate"],
)  # fmt: skip
def test_h36_garbage_on_the_clipboard_is_refused_with_no_change(
    text: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    read: list[str] = []

    def spy(text: str, **kwargs: Any) -> Any:
        read.append(text)
        return read_ui_string(text, **kwargs)

    monkeypatch.setattr("pyguibud.designer.clipboard.read_ui_string", spy)
    session = _session()
    messages: list[str] = []
    clip = ClipboardActions(session, messages.append, lambda _t: None, lambda: text)
    assert session.document is not None and session.stack is not None
    before = dump_ui(session.document)
    session.select(_node(session, "outer"), origin="tree")
    clip.paste()
    assert dump_ui(session.document) == before and not session.stack.can_undo
    assert messages and messages[-1]
    assert read == ([] if len(text) > MAX_UI_BYTES else [text])  # the File > Open reader


def test_h36_a_multi_select_delete_is_one_step_and_undo_restores_all() -> None:
    session = _session()
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    before = dump_ui(document)
    edit = EditActions(session, lambda _q, then: then(), lambda _m: None)
    session.select_many([_node(session, "outer"), _node(session, "lbl")], origin="canvas")
    edit.delete()
    assert [c.id for c in document.children[0].children] == [] and stack.index == 1
    edit.undo()
    assert dump_ui(document) == before


# ---------------------------------------------------------------- H39 / H40 (Q12 races)
def _resizing(app: DesignerApp, root: Any) -> tuple[Any, Any, Any]:
    """'lbl' selected and a span resize of its east edge running (Ctrl on a handle)."""
    from types import SimpleNamespace

    document = _form(app, root)
    label = _node(app.session, "lbl")
    app.session.select(label, origin="canvas")
    _settle(root)
    stage = app.shell.canvas.stage_of(document.children[0])
    assert stage is not None and stage.view is not None
    handle = stage.overlay.handles.shown()[0]
    x, y = handle.winfo_rootx() + 2, handle.winfo_rooty() + 2
    app.shell.canvas._on_handle(
        "e", "press", SimpleNamespace(state=0x4, x_root=x, y_root=y, widget=handle)
    )
    drag: Any = app.shell.drag
    assert drag.state == "resizing"
    return drag, stage, label


@pytest.mark.gui
def test_h40_palette_insert_hint_and_a_second_press_never_disturb_a_resize(
    shell: DesignerApp, designer_root: Any
) -> None:
    from types import SimpleNamespace

    drag, stage, label = _resizing(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None
    before, status = dump_ui(stack.document), shell.shell._message
    try:
        palette = shell.shell.palette
        assert palette._activate("w:Label") == "break"  # Enter / double-click on an item
        drag.insert_widget("Button")
        drag.hint("Button")
        assert dump_ui(stack.document) == before and shell.shell._message == status
        widget = stage.view.outer[id(label)]
        press = SimpleNamespace(widget=widget, state=0x100, x_root=5, y_root=5)
        shell.shell.canvas._on_press(press)  # a second pointer while Button-1 is held
        assert drag.state == "resizing"
    finally:
        drag.cancel()
    _settle(designer_root)
    assert dump_ui(stack.document) == before


@pytest.mark.gui
def test_h40_a_press_after_a_lost_release_still_selects(
    shell: DesignerApp, designer_root: Any
) -> None:
    from types import SimpleNamespace

    drag, stage, _label = _resizing(shell, designer_root)
    outer = _node(shell.session, "outer")
    widget = stage.view.outer[id(outer)]
    shell.shell.canvas._on_press(SimpleNamespace(widget=widget, state=0, x_root=5, y_root=5))
    assert shell.session.selection.node is outer and drag.state != "resizing"
    drag.cancel()


@pytest.mark.gui
def test_h39_a_rebuild_mid_resize_cancels_it_and_clears_the_grid_lines(
    shell: DesignerApp, designer_root: Any
) -> None:
    drag, stage, _label = _resizing(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None and stage.overlay._grid is not None  # the snap guide is drawn
    before = dump_ui(stack.document)
    stage.stale = True  # what a focus-in include refresh does
    shell.shell.canvas._flush()
    assert stage.view is not drag._view
    drag.motion(stage.stage.winfo_rootx() + 400, stage.stage.winfo_rooty() + 5)
    drag.release(stage.stage.winfo_rootx() + 400, stage.stage.winfo_rooty() + 5)
    _settle(designer_root)
    assert drag.state == "idle" and stage.overlay._grid is None
    assert dump_ui(stack.document) == before and not stack.can_undo


# ---------------------------------------------------------------- H41 inspector preview
def _long_label(app: DesignerApp, root: Any) -> tuple[Any, Any]:
    """hello.ui with its Label holding 100,000 characters (set while it is not selected)."""
    assert app.open_path(HELLO)
    root.update()
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    label = next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label")
    assert stack.execute(SetProp(label, Prop(name="text", value="W" * 100_000))).accepted
    root.update()
    return document, label


@pytest.mark.gui
@pytest.mark.budget
def test_h41_a_long_text_shows_as_a_read_only_preview_that_never_writes_back(
    shell: DesignerApp, designer_root: Any, tmp_path: Path
) -> None:
    document, label = _long_label(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None
    depth = stack.index
    started = time.perf_counter()
    shell.session.select(label, origin="tree")
    designer_root.update()
    elapsed = time.perf_counter() - started
    assert elapsed <= 1.0 * BUDGET_FACTOR, elapsed
    editor: Any = shell.shell.inspector._editors["prop:text"]
    assert len(editor.text()) == CANVAS_TEXT_LIMIT and editor.widget.instate(["readonly"])
    assert editor.button.instate(["disabled"]) and not editor.pending()
    assert editor.note is not None and "100000" in str(editor.note.cget("text"))
    editor._enter()
    editor.widget.event_generate("<FocusOut>")
    shell.session.select(document.children[0], origin="tree")  # away and back
    designer_root.update()
    shell.session.select(label, origin="tree")
    shell.set_theme("dark")
    shell.flush_theme()
    shell.set_language("de_DE")
    designer_root.update()
    shell.set_language("en_GB")
    designer_root.update()
    assert shell.shell.inspector.flush() and stack.index == depth
    target = tmp_path / "long.ui"
    shell._write(SavePlan(target=target), None)
    assert target.read_bytes().count(b"W" * 100_000) == 1  # every character was saved
    assert label.props["text"].value == "W" * 100_000


@pytest.mark.gui
def test_h41_reset_clears_a_long_text_and_the_field_is_editable_again(
    shell: DesignerApp, designer_root: Any
) -> None:
    _document, label = _long_label(shell, designer_root)
    shell.session.select(label, origin="tree")
    designer_root.update()
    inspector = shell.shell.inspector
    inspector.reset("prop:text")
    designer_root.update()
    editor: Any = inspector._editors["prop:text"]
    assert len(label.props.get("text", Prop(name="text", value="")).value) < 100
    assert not editor.widget.instate(["readonly"]) and not editor.long
    assert editor.note is not None and not editor.note.winfo_manager()
    assert editor.button.instate(["!disabled"])


@pytest.mark.gui
@pytest.mark.budget
def test_h41_pasting_100k_characters_into_the_field_commits_without_landing_in_it(
    shell: DesignerApp, designer_root: Any
) -> None:
    assert shell.open_path(HELLO)
    designer_root.update()
    document = shell.session.document
    assert document is not None
    label = next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label")
    shell.session.select(label, origin="tree")
    designer_root.update()
    editor: Any = shell.shell.inspector._editors["prop:text"]
    old = editor.text()
    editor.widget.icursor("end")
    designer_root.clipboard_clear()
    designer_root.clipboard_append("M" * 100_000)
    editor.widget.event_generate("<<Paste>>")  # appended: 100,010 characters, one too many
    designer_root.update()
    assert label.props["text"].value == old and editor.text() == old
    assert "at most 100000" in shell.shell._message
    editor.widget.selection_range(0, "end")  # the paste replaces the selected text
    started = time.perf_counter()
    editor.widget.event_generate("<<Paste>>")
    designer_root.update()
    elapsed = time.perf_counter() - started
    print(f"H41 paste: {elapsed:.2f} s")
    assert elapsed <= 1.0 * BUDGET_FACTOR, elapsed
    assert label.props["text"].value == "M" * 100_000
    assert editor.long and len(editor.text()) == CANVAS_TEXT_LIMIT
    designer_root.clipboard_clear()


# ---------------------------------------------------------------- QA-19c fixes (debugger)
@pytest.mark.gui
def test_qa_19c_01_a_short_paste_still_lands_and_a_long_one_is_refused_with_a_reason(
    shell: DesignerApp, designer_root: Any
) -> None:
    session = shell.session
    session.open_result(read_ui_string(FORM), name="t")
    designer_root.update()
    session.select(_node(session, "lbl"), origin="tree")
    designer_root.update()
    widget = shell.shell.inspector._editors["place:grid:row"].widget
    designer_root.clipboard_clear()
    designer_root.clipboard_append("7")
    widget.selection_range(0, "end")
    widget.event_generate("<<Paste>>")  # an ordinary paste is ttk's own
    designer_root.update()
    assert widget.get() == "7"
    designer_root.clipboard_clear()
    designer_root.clipboard_append("9" * CANVAS_TEXT_LIMIT)  # 2,001 characters with the "7"
    widget.selection_clear()
    widget.icursor(0)
    shell.shell.clear_message()
    widget.event_generate("<<Paste>>")
    designer_root.update()
    assert widget.get() == "7" and f"at most {CANVAS_TEXT_LIMIT}" in shell.shell._message
    designer_root.clipboard_clear()


@pytest.mark.gui
def test_qa_19c_01_the_paste_guard_is_installed_once_and_removed_with_its_app(
    designer_root: Any,
) -> None:
    original = designer_root.bind_class("TSpinbox", "<<Paste>>")
    first = DesignerApp(designer_root)
    second = DesignerApp(designer_root)  # replaces the first app's guard, never stacks on it
    script = designer_root.bind_class("TSpinbox", "<<Paste>>")
    assert script.count("pyguibud paste guard") == 1 and script.endswith(original)
    first.dispose()  # the second app's guard stays
    assert designer_root.bind_class("TSpinbox", "<<Paste>>") == script
    second.dispose()
    assert designer_root.bind_class("TSpinbox", "<<Paste>>") == original


def test_qa_19c_07_a_page_title_is_clipped_far_shorter_than_the_other_canvas_texts() -> None:
    from pyguibud.backends.base import TextSlot
    from pyguibud.designer.render_plan import DESIGN_KEY, TAB_TEXT_LIMIT, design_plan

    long = "Z" * 5_000
    document = read_ui_string(
        f'{HEAD}<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="Notebook" id="nb"><cell row="0" column="0"/>'
        f'<widget class="Frame" id="pg"><page><prop name="text">{long}</prop></page>'
        '<layout type="grid"/></widget></widget>'
        f'<widget class="Label" id="lbl"><cell row="1" column="0"/><prop name="text">{long}'
        "</prop></widget></window></pyguibud-ui>"
    ).document
    window = document.children[0]
    plan = design_plan(document, window, REG, log=lambda *_a, **_k: None)
    page: Any
    label: Any
    page, label = (n for n in window.walk() if getattr(n, "id", "") in ("pg", "lbl"))
    title = plan.text(TextSlot(DESIGN_KEY, page.placement.text))
    assert len(title) == TAB_TEXT_LIMIT and title.endswith("…")
    assert len(plan.text(TextSlot(DESIGN_KEY, label.props["text"]))) == CANVAS_TEXT_LIMIT
    assert page.placement.text.value == long  # display only


@pytest.mark.gui
def test_qa_19c_06_a_long_page_title_is_a_preview_that_reset_unlocks(
    shell: DesignerApp, designer_root: Any
) -> None:
    session = shell.session
    session.open_result(
        read_ui_string(
            f'{HEAD}<window id="main" kind="main"><layout type="grid"/>'
            '<widget class="Notebook" id="nb"><cell row="0" column="0"/>'
            f'<widget class="Frame" id="pg"><page><prop name="text">{"Z" * 5_000}</prop>'
            '</page><layout type="grid"/></widget></widget></window></pyguibud-ui>'
        ),
        name="t",
    )
    designer_root.update()
    page = _node(session, "pg")
    session.select(page, origin="tree")
    designer_root.update()
    inspector = shell.shell.inspector
    editor: Any = inspector._editors["place:page:text"]
    assert editor.long and editor.widget.instate(["readonly"])
    editor._enter()  # nothing typed: the clip is never written back
    assert len(page.placement.text.value) == 5_000
    inspector.reset("place:page:text")
    designer_root.update()
    editor = inspector._editors["place:page:text"]
    assert page.placement.text is None and not editor.long
    assert not editor.widget.instate(["readonly"])
