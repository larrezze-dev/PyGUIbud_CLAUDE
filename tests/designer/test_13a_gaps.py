"""Step 13a gap tests against the spec dnd-selection 13 test plan (TESTING pass).

Pure (hypothesis): the selection never outlives its node on any stack event; delete confirmation
only for non-empty containers. Tk (``gui``): no listener re-enters the stack, Esc / a drop outside
the window cancel a drag, Edit menu labels and states, 100 rebuilds leak nothing, en_XA.
"""

from __future__ import annotations

import gc
import logging
import re
import weakref
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud import i18n
from pyguibud.core import default_registry
from pyguibud.core.commands import CommandStack, InsertNode
from pyguibud.core.model import GridCell, Widget
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas import design
from pyguibud.designer.canvas.design import DESIGN_TAG
from pyguibud.designer.edit import EditActions
from pyguibud.designer.editing import delete_command, insert_command, new_node
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.targets import Target

from .test_drag import _centre, _drag, _with_frame


# ---------------------------------------------------------------- helpers (pure)
def _session() -> DesignerSession:
    session = DesignerSession(default_registry())
    session.new_from_template("main_window")
    return session


def _members(session: DesignerSession) -> set[int]:
    assert session.document is not None
    return {id(node) for node in session.document.walk()}


def _parent(node: object) -> object:
    return getattr(node, "parent", None)


def _frame(session: DesignerSession, parent: Any, row: int = 0) -> Widget:
    assert session.document is not None and session.stack is not None
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=row, column=0, sticky="nsew")
    assert session.stack.execute(InsertNode(parent, frame)).accepted
    return frame


# ---------------------------------------------------------------- selection pruning (pure)
def test_deleting_an_ancestor_prunes_a_selected_descendant() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    outer = _frame(session, session.document.children[0])
    inner = _frame(session, outer)
    session.select(inner, origin="tree")
    assert session.stack.execute(delete_command(outer)).accepted
    assert session.selection.nodes == () and session.selection.origin == "session"
    session.stack.undo()  # the restored node is not re-selected: the selection stays empty
    assert session.selection.nodes == ()


def test_saved_and_clear_events_keep_a_valid_selection() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    frame = _frame(session, session.document.children[0])
    session.select(frame, origin="canvas")
    session.stack.mark_saved()
    session.stack.clear()
    assert session.selection.node is frame and session.selection.origin == "canvas"


_OPS = st.lists(st.sampled_from(["insert", "delete", "undo", "redo", "select"]), max_size=25)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops=_OPS, picks=st.lists(st.integers(0, 50), min_size=25, max_size=25))
def test_the_selection_never_outlives_its_node(ops: list[str], picks: list[int]) -> None:
    """After every stack event (execute, undo, redo) every selected node is in the document."""
    session = _session()
    assert session.document is not None and session.stack is not None
    stack, window = session.stack, session.document.children[0]
    for op, pick in zip(ops, picks, strict=False):
        nodes = [n for n in session.document.walk() if isinstance(n, Widget)]
        containers = [window, *(n for n in nodes if n.class_name == "Frame")]
        if op == "insert":
            parent = containers[pick % len(containers)]
            node = new_node(session.registry.require("Frame"), session.document)
            stack.execute(insert_command(Target(parent, "grid"), node))
        elif op == "delete" and nodes:
            stack.execute(delete_command(nodes[pick % len(nodes)]))
        elif op == "undo" and stack.can_undo:
            stack.undo()
        elif op == "redo" and stack.can_redo:
            stack.redo()
        elif op == "select" and nodes:
            session.select(nodes[pick % len(nodes)], origin="tree")
        members = _members(session)
        assert all(id(node) in members for node in session.selection.nodes)


# ---------------------------------------------------------------- delete confirmation (pure)
def test_an_empty_container_is_deleted_without_a_question() -> None:
    session = _session()
    assert session.document is not None
    frame = _frame(session, session.document.children[0])
    asked: list[str] = []
    edit = EditActions(session, lambda q, _then: asked.append(q), asked.append)
    session.select(frame, origin="tree")
    edit.delete()
    assert asked == [] and _parent(frame) is None
    assert session.selection.node is session.document.children[0]


def test_the_question_counts_every_nested_element_in_the_plural() -> None:
    session = _session()
    assert session.document is not None
    outer = _frame(session, session.document.children[0])
    _frame(session, _frame(session, outer))  # outer > frame > frame: 2 descendants
    asked: list[tuple[str, Callable[[], None]]] = []
    edit = EditActions(session, lambda q, then: asked.append((q, then)), lambda _m: None)
    session.select(outer, origin="tree")
    edit.delete()
    assert [q for q, _ in asked] == [f"Delete '{outer.id}' and its 2 elements?"]
    assert _parent(outer) is not None  # only asked
    stack = session.stack
    assert stack is not None
    depth = stack.index
    asked[0][1]()
    assert _parent(outer) is None and stack.index == depth + 1  # one undo step
    stack.undo()
    assert _parent(outer) is session.document.children[0] and len(outer.children) == 1


def test_a_confirmation_after_the_node_was_undone_away_changes_nothing() -> None:
    session = _session()
    assert session.document is not None and session.stack is not None
    outer = _frame(session, session.document.children[0])
    _frame(session, outer)
    asked: list[Callable[[], None]] = []
    edit = EditActions(session, lambda _q, then: asked.append(then), lambda _m: None)
    session.select(outer, origin="tree")
    edit.delete()
    session.stack.undo()
    session.stack.undo()  # the dialog was open while the user undid the insert of ``outer``
    index = session.stack.index
    asked[0]()
    assert session.stack.index == index and _parent(outer) is None


def test_undo_and_redo_labels_and_states() -> None:
    session = _session()
    edit = EditActions(session, lambda _q, then: then(), lambda _m: None)
    assert (edit.can_undo(), edit.can_redo(), edit.undo_text, edit.redo_text) == (
        False,
        False,
        None,
        None,
    )
    assert session.document is not None
    frame = _frame(session, session.document.children[0])
    assert (edit.can_undo(), edit.undo_text, edit.can_redo()) == (True, "Add element", False)
    session.select(frame, origin="tree")
    edit.delete()
    assert edit.undo_text == "Delete element"
    edit.undo()
    assert (edit.redo_text, edit.undo_text) == ("Delete element", "Add element")
    _frame(session, session.document.children[0], row=1)  # a new edit drops the redo branch
    assert not edit.can_redo() and edit.redo_text is None


# ---------------------------------------------------------------- Tk
@pytest.fixture
def no_reentry(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Record every CommandStack call made while the stack notifies its listeners."""
    calls: list[str] = []
    for name in ("execute", "undo", "redo", "check", "clear", "break_merge", "mark_saved"):
        original = getattr(CommandStack, name)

        def spy(self: CommandStack, *args: Any, _o: Any = original, _n: str = name) -> Any:
            if self._busy:
                calls.append(_n)
            return _o(self, *args)

        monkeypatch.setattr(CommandStack, name, spy)
    yield calls


@pytest.mark.gui
def test_no_listener_reenters_the_stack_in_any_designer_flow(
    shell: DesignerApp,
    designer_root: Any,
    no_reentry: list[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Swallowed listener errors are logged, so the log must stay clean as well (R5)."""
    with caplog.at_level(logging.ERROR):
        frame = _with_frame(shell, designer_root)
        stage = shell.shell.canvas.stages[0]
        assert stage.view is not None and shell.session.stack is not None
        _drag(shell, designer_root, "Button", _centre(stage.view.inner[id(frame)]))
        designer_root.update()
        shell.session.select(frame, origin="tree")
        shell.shell.drag.insert_widget("Label")
        shell.registry.invoke("edit.undo")
        shell.registry.invoke("edit.redo")
        shell.session.select(frame, origin="tree")
        shell.registry.invoke("edit.delete")  # frame has children: a dialog opens
        (dialog,) = shell._live_dialogs()
        dialog.confirm()  # type: ignore[attr-defined]
        shell.registry.invoke("edit.undo")
        shell.session.stack.mark_saved()
        designer_root.update()
    assert no_reentry == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.gui
def test_escape_mid_drag_cancels_through_the_key_binding(
    shell: DesignerApp, designer_root: Any
) -> None:
    """The bound Esc script itself runs (no focus needed: the binding is called directly)."""
    frame = _with_frame(shell, designer_root)
    stage = shell.shell.canvas.stages[0]
    assert stage.view is not None
    _drag(shell, designer_root, "Entry", _centre(stage.view.inner[id(frame)]), drop=False)
    drag: Any = shell.shell.drag
    assert drag.state == "dragging"
    tree = shell.shell.palette.tree
    assert tree is not None
    script = tree.bind("<Escape>")
    assert script
    # Tk routes key events to the focused widget, which a withdrawn root never has: run the
    # bound Esc script itself (the real binding, not the controller method).
    fields = {"%W": str(tree), "%K": "Escape", "%A": "{}"}
    tree.tk.eval(re.sub(r"%[#A-Za-z]", lambda m: fields.get(m.group(), "0"), script))
    assert drag.state == "idle" and not stage.overlay.target.shown()
    assert shell.shell._message == "Drag cancelled."
    stack = shell.session.stack
    assert stack is not None
    index = stack.index
    tree.event_generate("<ButtonRelease-1>", x=0, y=0, rootx=0, rooty=0)
    assert stack.index == index and list(frame.children) == []


@pytest.mark.gui
@pytest.mark.parametrize("where", ["far_outside", "on_the_palette"])
def test_a_drop_outside_the_canvas_cancels(
    shell: DesignerApp, designer_root: Any, where: str
) -> None:
    frame = _with_frame(shell, designer_root)
    stack = shell.session.stack
    assert stack is not None
    index = stack.index
    tree = shell.shell.palette.tree
    assert tree is not None
    point = (-20000, -20000) if where == "far_outside" else _centre(tree)
    _drag(shell, designer_root, "Button", point)
    # Read before update(): ttk queues the press's <<TreeviewSelect>> (the hint), which a real
    # event loop delivers before the motion, but synthetic events overtake it.
    assert shell.shell._message == "Drag cancelled."
    designer_root.update()
    drag: Any = shell.shell.drag
    assert drag.state == "idle" and stack.index == index and list(frame.children) == []
    assert not shell.shell.canvas.stages[0].overlay.target.shown()
    assert str(tree.cget("cursor")) == ""


@pytest.mark.gui
def test_deleting_an_empty_container_opens_no_dialog(
    shell: DesignerApp, designer_root: Any
) -> None:
    frame = _with_frame(shell, designer_root)
    shell.session.select(frame, origin="tree")
    shell.registry.invoke("edit.delete")
    assert shell._live_dialogs() == [] and _parent(frame) is None


def _entry(app: DesignerApp, action_id: str) -> tuple[str, str]:
    action = app.registry.get(action_id)
    app.shell.refresh_states()  # what the menu's postcommand runs when it opens
    for menu, index, item in app.shell._entries:
        if item is action:
            return str(menu.entrycget(index, "label")), str(menu.entrycget(index, "state"))
    raise AssertionError(action_id)


@pytest.mark.gui
def test_the_edit_menu_follows_selection_and_stack(shell: DesignerApp, designer_root: Any) -> None:
    frame = _with_frame(shell, designer_root)
    session = shell.session
    assert session.document is not None
    session.select(session.document.children[0], origin="tree")
    assert _entry(shell, "edit.delete")[1] == "disabled"  # windows belong to Step 14
    session.select(frame, origin="tree")
    assert _entry(shell, "edit.delete")[1] == "normal"
    shell.registry.invoke("edit.delete")
    assert _entry(shell, "edit.undo") == ("Undo Delete element", "normal")
    assert _entry(shell, "edit.redo") == ("Redo", "disabled")
    assert _entry(shell, "edit.delete")[1] == "disabled"  # the window is selected now
    shell.registry.invoke("edit.undo")
    assert _entry(shell, "edit.redo") == ("Redo Delete element", "normal")
    shell.registry.invoke("edit.undo")
    assert _entry(shell, "edit.undo") == ("Undo", "disabled")


@pytest.mark.gui
def test_keyboard_insertion_into_a_window_keeps_the_palette_selection(
    shell: DesignerApp, designer_root: Any
) -> None:
    """With a window selected, Enter inserts into it; the palette row stays picked."""
    shell.session.new_from_template("main_window")
    session = shell.session
    assert session.document is not None
    window = session.document.children[0]
    session.select(window, origin="tree")
    tree = shell.shell.palette.tree
    assert tree is not None
    tree.see("w:Frame")
    tree.selection_set("w:Frame")
    tree.focus("w:Frame")
    designer_root.update()
    assert shell.shell.palette._activate(tree.focus()) == "break"
    assert [getattr(c, "class_name", "") for c in window.children] == ["Frame"]
    assert tree.selection() == ("w:Frame",)
    assert shell.shell.palette._activate("c0") is None  # a category: the Treeview's own Enter


@pytest.mark.gui
def test_a_category_row_shows_no_hint(shell: DesignerApp, designer_root: Any) -> None:
    tree = shell.shell.palette.tree
    assert tree is not None
    designer_root.update()
    shell.shell.show_message("before")
    tree.selection_set("c0")
    designer_root.update()
    assert shell.shell._message == "before"


@pytest.mark.gui
def test_a_hundred_stack_rebuilds_leak_nothing(shell: DesignerApp, designer_root: Any) -> None:
    """The real path: each stack event schedules an after-idle rebuild that swaps one frame."""
    frame = _with_frame(shell, designer_root)
    stage = shell.shell.canvas.stages[0]
    stack = shell.session.stack
    assert stack is not None and stage.view is not None
    shell.session.select(frame, origin="tree")

    def state() -> tuple[Any, ...]:
        designer_root.update()
        return (
            set(designer_root.winfo_children()),
            len(designer_root.tk.call("image", "names")),
            {seq: designer_root.bind_class(DESIGN_TAG, seq) for seq in design.SEQUENCES},
            len(stage.stage.winfo_children()),
            len(designer_root.tk.call("after", "info")),
        )

    stack.undo()
    stack.redo()  # warm-up
    before = state()
    dead = weakref.ref(stage.view.frame)
    for _round in range(50):
        stack.undo()
        designer_root.update()
        stack.redo()
        designer_root.update()
    gc.collect()
    assert state() == before
    assert dead() is None


@pytest.mark.gui
def test_the_pseudo_locale_drives_the_whole_13a_flow(
    shell: DesignerApp, designer_root: Any, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.ERROR):
        frame = _with_frame(shell, designer_root)
        shell.set_language("en_XA")
        assert i18n.get_language() == "en_XA"
        designer_root.update()
        stage = shell.shell.canvas.stages[0]
        assert stage.error is None and stage.view is not None
        _drag(shell, designer_root, "Button", _centre(stage.view.inner[id(frame)]))
        designer_root.update()
        assert len(frame.children) == 1
        assert shell.shell._message.startswith("[")  # "Inserted ..." in en_XA
        label, state = _entry(shell, "edit.undo")
        assert label.startswith("[") and state == "normal"
        shell.session.select(frame, origin="tree")
        shell.registry.invoke("edit.delete")
        (dialog,) = shell._live_dialogs()
        dialog.close()
        shell.shell.drag.hint("Button")
        assert shell.shell._message.startswith("[")
        shell.registry.invoke("edit.undo")
        designer_root.update()
        assert stage.error is None and stage.view is not None
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []


def _pending_scripts(root: Any) -> list[str]:
    """The scripts of every pending ``after`` / ``after_idle`` job of the Tcl interpreter."""
    jobs = root.tk.splitlist(root.tk.call("after", "info"))
    return [str(root.tk.splitlist(root.tk.call("after", "info", job))[0]) for job in jobs]


@pytest.mark.gui
def test_disposing_right_after_a_palette_render_raises_nothing(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: the palette's end-of-render job outlived the panel (bgerror at exit).

    A render now ends with a queued marker event: it must arrive harmlessly after dispose().
    Tcl background errors are caught with ``interp bgerror``, not ``capfd``: fd-level capture
    closes the handles Tcl wrapped as stdout/stderr (QA-10-13, H07).
    """
    caught: list[BaseException] = []
    monkeypatch.setattr(
        designer_root, "report_callback_exception", lambda _k, value, _tb: caught.append(value)
    )
    tcl = designer_root.tk
    background: list[str] = []
    handler = designer_root.register(lambda message, *_options: background.append(message))
    previous = tcl.call("interp", "bgerror", "")
    tcl.call("interp", "bgerror", "", handler)
    try:
        app = DesignerApp(designer_root)
        app.shell.palette._render()  # a re-render, as retranslate() does, then close at once
        app.dispose()
        designer_root.update()  # delivers the queued marker (and anything else left behind)
    finally:
        tcl.call("interp", "bgerror", "", previous)
        designer_root.deletecommand(handler)
    assert caught == []
    assert background == []


@pytest.mark.gui
def test_palette_rerenders_mute_the_hint_until_their_events_arrive(designer_root: Any) -> None:
    """QA-13a-09: back-to-back renders stay muted until the last render's events are in."""
    app = DesignerApp(designer_root)
    try:
        palette = app.shell.palette
        designer_root.update()
        for _ in range(3):
            palette._render()
        assert palette._renders == 3
        designer_root.update_idletasks()  # what a later step of a language switch does
        assert palette._renders == 3
        designer_root.update()
        assert palette._renders == 0
    finally:
        app.dispose()


@pytest.mark.gui
def test_dispose_leaves_no_idle_job_of_the_object_tree(designer_root: Any) -> None:
    """Regression: a queued ellipsis re-fit (a <Configure>) outlived the object tree."""
    app = DesignerApp(designer_root)
    app.shell.tree._schedule_fit()  # what a resize of the tree does
    assert app.shell.tree._fit_job is not None
    app.dispose()
    try:
        assert not [s for s in _pending_scripts(designer_root) if "_fit_cells" in s]
    finally:
        designer_root.update()


@pytest.mark.gui
def test_dispose_leaves_no_job_calling_a_deleted_command(designer_root: Any) -> None:
    """After dispose, no pending job may name a Tcl command that went with its widget."""
    app = DesignerApp(designer_root)
    app.shell.palette._render()
    app.shell.tree._schedule_fit()
    app.set_theme("dark")
    app.shell.show_message("hello")
    app.dispose()
    try:
        # A per-name lookup also resolves namespaced Tk internals (``::ttk::...``).
        dangling = [
            script
            for script in _pending_scripts(designer_root)
            if not designer_root.tk.call("info", "commands", script.split()[0])
        ]
        assert dangling == []
    finally:
        designer_root.update()
