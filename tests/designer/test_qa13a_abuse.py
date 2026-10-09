"""QA abuse pass of Step 13a (spec dnd-selection 2-6, 9-11): "idiot-proof" checks.

Every Tk test collects the exceptions that Tk callbacks raise (they are printed, never raised,
so a broken binding would otherwise pass silently) and asserts there are none.

Synthetic presses carry an increasing ``time``: with the default ``time=0`` two presses on the
shared root, however far apart, look like a double-click and insert through ``<Double-Button-1>``.

Known bugs are ``xfail(strict=True)`` with their QA id, so a fix turns them into passing tests.
"""

from __future__ import annotations

import contextlib
import itertools
import logging
from collections.abc import Iterator
from tkinter import ttk
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import default_registry, dump_ui
from pyguibud.core.commands import InsertNode
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.model import GridCell, Layout, PackPlacement, Widget, Window
from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef, label_of
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.edit import EditActions
from pyguibud.designer.editing import insert_command, new_node
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.standard_actions import ShellCallbacks, register_standard_actions
from pyguibud.designer.targets import NewWidget, hit_test, keyboard_target
from pyguibud.designer.theme import selection_colours, spec_for_role
from pyguibud.designer.theme_tk import TREE_STYLE

ALL_LANGUAGES = (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE)
_CLOCK = itertools.count(10_000_000, 5_000)  # ms; 5 s apart: never a double-click


# ---------------------------------------------------------------- mnemonics (pure, all locales)
def _registry(session: DesignerSession, lang: str) -> ActionRegistry:
    callbacks = ShellCallbacks(
        new_document=lambda: None,
        show_shortcuts=lambda: None,
        next_panel=lambda: None,
        previous_panel=lambda: None,
        quit=lambda: None,
        set_theme=lambda _role: None,
        current_theme=lambda: "light",
        set_language=lambda _code: None,
        current_language=lambda: lang,
        edit=EditActions(session, lambda _question, _then: None, lambda _text: None),
    )
    registry = ActionRegistry()
    register_standard_actions(registry, callbacks)
    return registry


def _undo_and_redo_session() -> DesignerSession:
    """A session where Undo and Redo both have a live label (insert, insert, undo)."""
    session = DesignerSession(default_registry())
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    for name in ("Label", "Entry"):
        spec = session.registry.require(name)
        target = keyboard_target(window, window, NewWidget.of(spec), session.registry)
        assert target is not None
        command = insert_command(target, new_node(spec, session.document))
        assert session.stack.execute(command).accepted
    session.stack.undo()
    assert session.stack.can_undo and session.stack.can_redo
    return session


def _menu_groups(registry: ActionRegistry) -> dict[str, list[ActionDef | MenuDef]]:
    """Every menu's items, plus the menu bar row itself (the top-level menus)."""
    groups: dict[str, list[ActionDef | MenuDef]] = {
        "<menubar>": [
            registry.menu(m) for m in registry.menu_ids() if registry.menu(m).parent is None
        ]
    }
    for menu_id in registry.menu_ids():
        groups[menu_id] = [
            item for item in registry.menu_items(menu_id) if isinstance(item, ActionDef | MenuDef)
        ]
    return groups


def _text(item: ActionDef | MenuDef, *, live: bool) -> str:
    if isinstance(item, MenuDef):
        return i18n._(item.label)
    return label_of(item, live=live)


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_every_menu_has_unique_mnemonics_in_every_locale(lang: str) -> None:
    """Menu bar row and every menu, Edit included, with static and live Undo/Redo labels."""
    session = _undo_and_redo_session()
    i18n.set_language(lang)
    groups = _menu_groups(_registry(session, lang))
    assert "edit" in groups and len(groups["<menubar>"]) >= 4
    for name, items in groups.items():
        for live in (False, True):
            marks: list[str] = []
            for item in items:
                text, at = split_mnemonic(_text(item, live=live))
                if split_mnemonic(item.label)[1] >= 0:  # the en-GB msgid has an access key
                    assert at >= 0, (lang, name, item.id, text)  # ... so must the translation
                if at >= 0:
                    marks.append(text[at].casefold())
            assert len(marks) == len(set(marks)), (lang, name, live, marks)


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_live_undo_and_redo_labels_keep_their_access_key(lang: str) -> None:
    """The live label ("Undo Add element") keeps the key of "Undo": it never jumps."""
    session = _undo_and_redo_session()
    i18n.set_language(lang)
    registry = _registry(session, lang)
    for action_id in ("edit.undo", "edit.redo"):
        action = registry.get(action_id)
        assert action is not None
        static, s_at = split_mnemonic(label_of(action, live=False))
        live, l_at = split_mnemonic(label_of(action))
        assert live != static, (lang, action_id)  # the live label really is in use
        assert static[s_at].casefold() == live[l_at].casefold(), (lang, action_id, static, live)


# ---------------------------------------------------------------- Tk helpers
@pytest.fixture
def tk_errors(designer_root: Any, monkeypatch: pytest.MonkeyPatch) -> list[BaseException]:
    """The exceptions raised inside Tk callbacks during the test (Tk only prints them)."""
    caught: list[BaseException] = []

    def report(_kind: object, value: BaseException, _tb: object) -> None:
        caught.append(value)

    monkeypatch.setattr(designer_root, "report_callback_exception", report)
    return caught


@pytest.fixture
def app(shell: DesignerApp, designer_root: Any) -> Iterator[DesignerApp]:
    """The shell; pending Tk events are flushed afterwards."""
    yield shell
    designer_root.update()


def _settle(root: Any, rounds: int = 3) -> None:
    for _ in range(rounds):
        root.update()


def _centre(widget: Any) -> tuple[int, int]:
    return (
        widget.winfo_rootx() + widget.winfo_width() // 2,
        widget.winfo_rooty() + widget.winfo_height() // 2,
    )


def _press(app: DesignerApp, root: Any, name: str) -> None:
    """Press on the palette item ``name`` and move past the drag threshold."""
    tree = app.shell.palette.tree
    assert tree is not None
    for category in tree.get_children():  # the withdrawn root is short: show one category
        tree.item(category, open=f"w:{name}" in tree.get_children(category))
    root.update_idletasks()
    tree.see(f"w:{name}")
    root.update_idletasks()
    x, y, _w, h = (int(v) for v in tree.bbox(f"w:{name}"))
    sx, sy = tree.winfo_rootx() + x + 4, tree.winfo_rooty() + y + h // 2
    tree.event_generate(
        "<ButtonPress-1>", x=x + 4, y=y + h // 2, rootx=sx, rooty=sy, time=next(_CLOCK)
    )
    for step in (10, 30):
        tree.event_generate("<B1-Motion>", x=x + step, y=y, rootx=sx + step, rooty=sy, state=0x100)


def _move(app: DesignerApp, to: tuple[int, int]) -> None:
    tree = app.shell.palette.tree
    assert tree is not None
    tree.event_generate("<B1-Motion>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100)


def _release(app: DesignerApp, to: tuple[int, int]) -> None:
    tree = app.shell.palette.tree
    assert tree is not None
    tree.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=to[0], rooty=to[1], state=0x100, time=next(_CLOCK)
    )


def _rest(root: Any) -> None:
    """Let the 60 ms hover check run."""
    root.after(150, lambda: None)
    for _ in range(40):
        root.update()
        root.after(5)


def _holder(focus: Any) -> Any:
    """The focused widget; skip when the desktop took the keyboard focus away mid-test."""
    if focus is None:
        pytest.skip("the desktop took the keyboard focus away mid-test")
    return focus


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


def _window(app: DesignerApp) -> Window:
    assert app.session.document is not None
    window = app.session.document.children[0]
    assert isinstance(window, Window)
    return window


def _with_frame(app: DesignerApp, root: Any) -> Widget:
    """``main_window`` with a Frame filling its single grid cell."""
    session = app.session
    session.new_from_template("main_window")
    assert session.document is not None and session.stack is not None
    frame = new_node(session.registry.require("Frame"), session.document)
    assert isinstance(frame, Widget)
    frame.placement = GridCell(row=0, column=0, sticky="nsew")
    assert session.stack.execute(InsertNode(_window(app), frame)).accepted
    _settle(root)
    return frame


def _frame_centre(app: DesignerApp, frame: Widget) -> tuple[int, int]:
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    return _centre(stage.view.inner[id(frame)])


def _clean_drag_inserts(app: DesignerApp, root: Any, frame: Widget) -> bool:
    """After an abuse, an ordinary drag into the empty ``frame`` adds exactly one Label."""
    assert not frame.children, "aim at an empty frame: an occupied cell refuses the drop"
    point = _frame_centre(app, frame)
    _press(app, root, "Label")
    _move(app, point)
    _rest(root)
    _release(app, point)
    _settle(root)
    return [getattr(child, "class_name", "") for child in frame.children] == ["Label"]


def _keyboard_insert(app: DesignerApp, root: Any, selected: object, name: str) -> bool:
    session = app.session
    assert session.stack is not None
    session.select(selected, origin="tree")
    before = session.stack.index
    app.shell.drag.insert_widget(name)  # what Enter / double-click in the palette call
    _settle(root)
    return session.stack.index != before


# ---------------------------------------------------------------- drag abuse
@pytest.mark.gui
def test_ctrl_z_mid_drag_cancels_and_the_next_drag_works(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    frame = _with_frame(app, designer_root)
    session = app.session
    assert session.stack is not None
    _press(app, designer_root, "Label")
    _move(app, _frame_centre(app, frame))
    _rest(designer_root)
    drag: Any = app.shell.drag
    assert drag.state == "dragging"
    app.registry.invoke("edit.undo")  # removes the frame: the snapshot is stale
    _settle(designer_root)
    assert drag.state == "idle"
    _release(app, (0, 0))
    _settle(designer_root)
    assert session.stack.index == 0 and session.stack.can_redo
    app.registry.invoke("edit.redo")
    _settle(designer_root)
    assert _clean_drag_inserts(app, designer_root, frame)
    assert tk_errors == []


@pytest.mark.gui
def test_a_theme_switch_mid_drag_never_breaks_the_drag(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    frame = _with_frame(app, designer_root)
    _press(app, designer_root, "Label")
    _move(app, _frame_centre(app, frame))
    _rest(designer_root)
    for role in ("dark", "high_contrast", "light"):
        app.set_theme(role)
        app.flush_theme()
        _settle(designer_root)
    point = _frame_centre(app, frame)
    _move(app, point)
    _rest(designer_root)
    _release(app, point)
    _settle(designer_root)
    drag: Any = app.shell.drag
    assert drag.state == "idle"
    assert len(frame.children) <= 1  # dropped once or cancelled, never twice
    assert _clean_drag_inserts(app, designer_root, _with_frame(app, designer_root))
    assert tk_errors == []


@pytest.mark.gui
def test_switching_the_canvas_tab_mid_drag_drops_on_the_shown_window(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    from pyguibud.core import read_ui_string

    from .test_canvas_engine import TWO_WINDOWS

    app.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    _settle(designer_root)
    canvas = app.shell.canvas
    first, second = canvas.stages
    assert first.view is not None
    _press(app, designer_root, "Label")
    _move(app, _centre(first.view.inner[id(first.window)]))
    _rest(designer_root)
    canvas.notebook.select(second.page)
    _settle(designer_root)
    assert second.view is not None
    point = _centre(second.view.inner[id(second.window)])
    _move(app, point)
    _rest(designer_root)
    _release(app, point)
    _settle(designer_root)
    labels = [c for c in second.window.children if getattr(c, "class_name", "") == "Label"]
    assert len(labels) == 2 and len(first.window.children) == 1
    assert tk_errors == []


@pytest.mark.gui
def test_a_language_switch_mid_drag_leaves_a_working_drag(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    frame = _with_frame(app, designer_root)
    _press(app, designer_root, "Label")
    _move(app, _frame_centre(app, frame))
    _rest(designer_root)
    app.set_language("de_DE")  # re-renders every canvas tab
    drag: Any = app.shell.drag
    assert drag.state == "idle"  # QA-13a-01: cancelled before the stages were destroyed
    _settle(designer_root)
    point = _frame_centre(app, frame)
    _move(app, point)
    _release(app, point)  # the gesture was cancelled: this release drops nothing
    _settle(designer_root)
    assert tk_errors == []
    assert drag.state == "idle"
    assert _clean_drag_inserts(app, designer_root, frame)


@pytest.mark.gui
def test_a_new_document_mid_drag_cancels_cleanly(
    app: DesignerApp,
    designer_root: Any,
    tk_errors: list[BaseException],
    caplog: pytest.LogCaptureFixture,
) -> None:
    frame = _with_frame(app, designer_root)
    _press(app, designer_root, "Label")
    _move(app, _frame_centre(app, frame))
    _rest(designer_root)
    app.session.new_from_template("dialog")  # document_changed mid-drag (spec 6: cancel)
    drag: Any = app.shell.drag
    assert drag.state == "idle"  # QA-13a-01: cancelled before the stages were destroyed
    _settle(designer_root)
    assert tk_errors == []
    # A signal slot that fails is only logged: the cancel must not have touched a dead stage.
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
    frame = _with_frame(app, designer_root)
    assert _clean_drag_inserts(app, designer_root, frame)
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("name", ["Statusbar", "Menubar"])
def test_a_second_bar_is_refused_by_drag_and_by_keyboard(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException], name: str
) -> None:
    frame = _with_frame(app, designer_root)
    session, window = app.session, _window(app)
    assert session.stack is not None
    before, bar = session.stack.index, (window.statusbar, window.menubar)
    reason = i18n._(
        "This window already has a status bar."
        if name == "Statusbar"
        else "This window already has a menu bar."
    )
    point = _frame_centre(app, frame)
    _press(app, designer_root, name)
    _move(app, point)
    _rest(designer_root)
    tree = app.shell.palette.tree
    assert tree is not None
    assert str(tree.cget("cursor")) == "X_cursor" and app.shell._message == reason
    _release(app, point)
    _settle(designer_root)
    assert not _keyboard_insert(app, designer_root, window, name)
    assert app.shell._message == reason
    assert session.stack.index == before and (window.statusbar, window.menubar) == bar
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("name", ["Statusbar", "Menubar"])
def test_a_component_refuses_bars_with_the_validator_reason(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException], name: str
) -> None:
    app.session.new_from_template("empty_component")
    _settle(designer_root)
    window = _window(app)
    assert not _keyboard_insert(app, designer_root, window, name)
    assert window.statusbar is None and window.menubar is None
    assert "component" in app.shell._message  # the validator's translated reason
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("name", ["Menu", "Action"])
def test_menu_items_never_land_on_the_canvas(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException], name: str
) -> None:
    frame = _with_frame(app, designer_root)
    session = app.session
    assert session.stack is not None
    point = _frame_centre(app, frame)
    _press(app, designer_root, name)
    _move(app, point)
    _rest(designer_root)
    _release(app, point)
    _settle(designer_root)
    assert session.stack.index == 1 and frame.children == ()
    assert app.shell._message == i18n._("Menus and actions are edited in the menu editor.")
    assert not _keyboard_insert(app, designer_root, frame, name)
    assert tk_errors == []


@pytest.mark.gui
def test_a_drop_on_the_caption_menubar_strip_or_status_bar_inserts_nothing(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    session, window = app.session, _window(app)
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None and session.stack is not None
    for widget in (stage.title, stage.strip, stage.view.outer[id(window.statusbar)]):
        point = _centre(widget)
        _press(app, designer_root, "Label")
        _move(app, point)
        _rest(designer_root)
        _release(app, point)
        _settle(designer_root)
        assert session.stack.index == 0, widget
    assert tk_errors == []


# ---------------------------------------------------------------- delete, undo and redo abuse
_NOT_DELETABLE = "Windows are deleted with Document > Delete window."


def _has_statusbar(window: Any) -> bool:
    return bool(window.statusbar is not None)


@pytest.mark.gui
def test_the_delete_key_never_removes_a_window_but_removes_a_menubar_and_statusbar(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    session, window = app.session, _window(app)
    assert session.stack is not None and session.document is not None
    before = dump_ui(session.document)
    tree = app.shell.tree.tree
    assert tree is not None
    with _focused(designer_root, tree):
        session.select(window, origin="tree")
        _settle(designer_root)
        app.registry.invoke("edit.delete")  # the menu item
        app.shell.show_message("")
        tree.event_generate("<Delete>")  # the key, on the focused object tree
        _settle(designer_root)
        assert app._live_dialogs() == []
        # QA-13a-07: the key is never silently ignored.
        assert app.shell._message == _NOT_DELETABLE
        # 14a.2 lifts the guard for the bars: Delete removes the status bar (one undo step).
        session.select(window.statusbar, origin="tree")
        tree.event_generate("<Delete>")
        _settle(designer_root)
        assert not _has_statusbar(window)
        app.registry.invoke("edit.undo")
        assert _has_statusbar(window)
    assert session.stack.index == 0 and dump_ui(session.document) == before
    # Control: the same key on the focused tree does delete a widget (the key path is live).
    assert _keyboard_insert(app, designer_root, window, "Label")
    label = session.selection.node
    with _focused(designer_root, tree):
        session.select(label, origin="tree")
        tree.event_generate("<Delete>")
        _settle(designer_root)
    assert getattr(label, "parent", None) is None
    assert tk_errors == []


@pytest.mark.gui
def test_deleting_nested_containers_round_trips_through_undo_and_redo(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    frame = _with_frame(app, designer_root)
    session = app.session
    assert session.stack is not None and session.document is not None
    inner = frame
    for name in ("LabelFrame", "Frame", "Notebook"):
        assert _keyboard_insert(app, designer_root, inner, name)
        node = session.selection.node
        assert isinstance(node, Widget)
        inner = node
    for name in ("Label", "Entry"):
        assert _keyboard_insert(app, designer_root, inner, name)
    built = dump_ui(session.document)
    session.select(frame, origin="tree")
    app.registry.invoke("edit.delete")
    _settle(designer_root)
    (dialog,) = app._live_dialogs()
    dialog.confirm()  # type: ignore[attr-defined]
    _settle(designer_root)
    assert frame.parent is None and session.selection.node is _window(app)
    deleted = dump_ui(session.document)
    stage = app.shell.canvas.stages[0]
    for step, expected in (("undo", built), ("redo", deleted), ("undo", built)):
        app.registry.invoke(f"edit.{step}")
        _settle(designer_root)
        assert dump_ui(session.document) == expected, step
        assert stage.view is not None and stage.error is None, step
    assert session.report().errors == ()
    assert tk_errors == []


@pytest.mark.gui
def test_an_undo_redo_storm_through_the_keys_stays_consistent(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    frame = _with_frame(app, designer_root)
    session = app.session
    assert session.stack is not None and session.document is not None
    for name in ("Label", "Entry", "Button", "Checkbutton"):
        assert _keyboard_insert(app, designer_root, frame, name)
    full, top = dump_ui(session.document), session.stack.index
    tree = app.shell.tree.tree
    assert tree is not None
    keys = ("<Control-z>", "<Control-y>", "<Control-Z>")  # Z with Shift: redo
    with _focused(designer_root, tree):
        for i in range(300):
            tree.event_generate(keys[i % 3])
        for _ in range(top + 50):
            tree.event_generate("<Control-z>")
        _settle(designer_root)
        assert session.stack.index == 0 and not session.stack.can_undo
        for _ in range(top + 50):
            tree.event_generate("<Control-y>")
        _settle(designer_root)
    assert session.stack.index == top and dump_ui(session.document) == full
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None and stage.error is None
    assert tk_errors == []


@pytest.mark.gui
def test_endless_nesting_by_keyboard_stops_at_the_depth_limit(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    session = app.session
    assert session.stack is not None and session.document is not None
    original = dump_ui(session.document)
    session.select(_window(app), origin="tree")
    refused = False
    for _ in range(120):  # Enter on "Frame" nests one level deeper each time
        before = session.stack.index
        app.shell.drag.insert_widget("Frame")
        if session.stack.index == before:
            refused = True
            break
    _settle(designer_root)
    assert refused and "nested too deeply" in app.shell._message
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None and stage.error is None
    while session.stack.can_undo:
        session.stack.undo()
    _settle(designer_root)
    assert dump_ui(session.document) == original
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("container", ["Notebook", "PanedWindow", "ScrolledFrame", "LabelFrame"])
def test_keyboard_insertion_fills_every_container_kind(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException], container: str
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    session = app.session
    assert _keyboard_insert(app, designer_root, _window(app), container)
    node = session.selection.node
    assert isinstance(node, Widget) and node.class_name == container
    for name in ("Label", "Entry", "Frame", "Button"):
        assert _keyboard_insert(app, designer_root, node, name), (container, name)
    assert len(node.children) == 4 and session.report().errors == ()
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None and stage.error is None
    for child in node.children:  # a hidden Notebook page is revealed and outlined
        session.select(child, origin="tree")
        _settle(designer_root)
        assert stage.overlay.selection.shown(), (container, getattr(child, "id", ""))
    assert tk_errors == []


@pytest.mark.gui
def test_an_error_card_survives_language_and_theme_switches_and_recovers(
    app: DesignerApp,
    designer_root: Any,
    tk_errors: list[BaseException],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    panel = app.shell.canvas
    real = panel.engine.build

    def broken(*_args: object) -> Any:
        raise RuntimeError("factory exploded")

    monkeypatch.setattr(panel.engine, "build", broken)
    app.session.new_from_template("login_form")
    _settle(designer_root)
    for lang, role in (("fr_FR", "dark"), ("en_XA", "high_contrast"), ("en_GB", "light")):
        app.set_language(lang)
        app.set_theme(role)
        app.flush_theme()
        _settle(designer_root)
        stage = panel.stages[0]
        texts = [c.cget("text") for c in stage.card.winfo_children()]
        assert stage.view is None and "factory exploded" in texts[0], (lang, texts)
        assert stage.card.winfo_manager() == "grid"
    window = _window(app)
    for node in list(window.walk())[:8]:  # the tree and inspector keep working
        app.session.select(node, origin="tree")
    assert _keyboard_insert(app, designer_root, window, "Label")
    monkeypatch.setattr(panel.engine, "build", real)
    app.registry.invoke("edit.undo")
    _settle(designer_root)
    stage = panel.stages[0]
    assert stage.view is not None and stage.error is None and not stage.card.winfo_ismapped()
    assert tk_errors == []


# ---------------------------------------------------------------- unreachable drop targets


def _snapshot_box(app: DesignerApp, node: object) -> Any:
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    snapshot = app.shell.canvas.engine.snapshot(stage.view, stage.stage, stage.scroll)
    box = next((b for b in snapshot.containers if b.node is node), None)
    return snapshot, box


@pytest.mark.gui
@pytest.mark.parametrize(
    "container",
    [
        "Notebook",
        "PanedWindow",
        "Frame",
        "LabelFrame",
        "ScrolledFrame",
    ],
)
def test_a_dropped_empty_container_can_be_dragged_into(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException], container: str
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), container)
    node = app.session.selection.node
    snapshot, box = _snapshot_box(app, node)
    assert box is not None and box.rect.w >= 24 and box.rect.h >= 24, box
    x, y = box.inner.x + box.inner.w // 2, box.inner.y + box.inner.h // 2
    target = hit_test(snapshot, x, y, NewWidget("Label"), band=6, bar=3)
    assert target is not None and target.container is node
    assert tk_errors == []


@pytest.mark.gui
def test_a_frame_with_one_child_still_offers_a_free_cell_to_the_mouse(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), "Frame")
    frame = app.session.selection.node
    assert _keyboard_insert(app, designer_root, frame, "Label")
    snapshot, box = _snapshot_box(app, frame)
    assert box is not None
    free = {
        (target.row, target.column)
        for x in range(box.rect.x - 8, box.rect.x + box.rect.w + 8)
        for y in range(box.rect.y - 8, box.rect.y + box.rect.h + 8)
        if (target := hit_test(snapshot, x, y, NewWidget("Entry"), band=6, bar=3)) is not None
        and target.container is frame
    } - {(0, 0)}
    assert free, "only the occupied cell of the frame can be reached"
    assert tk_errors == []


@pytest.mark.gui
def test_the_empty_component_template_is_a_usable_drop_target(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("empty_component")
    _settle(designer_root)
    window = _window(app)
    snapshot, box = _snapshot_box(app, window)
    assert box is not None and box.rect.h >= 24, box
    target = hit_test(
        snapshot, box.inner.x + box.inner.w // 2, box.inner.y + 12, NewWidget("Label")
    )
    assert target is not None and target.container is window
    assert tk_errors == []


# ---------------------------------------------------------------- keyboard only (mapped root)
@pytest.mark.gui
def test_keyboard_only_palette_insert_tree_delete_and_undo(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    """Palette Enter x3 -> F6 to the tree -> Delete (confirm with Enter) -> Ctrl+Z -> Ctrl+Y."""
    session = app.session
    session.new_from_template("main_window")
    designer_root.deiconify()
    try:
        palette, tree = app.shell.palette.tree, app.shell.tree.tree
        assert palette is not None and tree is not None
        palette.focus_force()
        _settle(designer_root, 10)
        if designer_root.focus_get() is not palette:
            pytest.skip("the desktop did not give the test window the keyboard focus")
        assert session.document is not None and session.stack is not None
        session.select(_window(app), origin="tree")
        for name in ("Frame", "Label", "Entry"):
            palette.selection_set(f"w:{name}")
            palette.focus(f"w:{name}")
            palette.event_generate("<Return>")
            _settle(designer_root)
            assert designer_root.focus_get() is palette, name  # D7: the focus stays here
        frame = next(c for c in _window(app).children if getattr(c, "class_name", "") == "Frame")
        assert isinstance(frame, Widget)
        assert [getattr(c, "class_name", "") for c in frame.children] == ["Label", "Entry"]
        built = dump_ui(session.document)
        palette.event_generate("<F6>")
        _settle(designer_root)
        focus = designer_root.focus_get()
        for _ in range(8):  # F6 cycles the four panels; walk to the object tree
            if focus is tree:
                break
            _holder(focus).event_generate("<F6>")
            _settle(designer_root)
            focus = designer_root.focus_get()
        assert focus is tree, f"F6 never reached the object tree (focus: {focus})"
        session.select(frame, origin="tree")
        _settle(designer_root)
        tree.event_generate("<Delete>")
        _settle(designer_root, 6)
        (dialog,) = app._live_dialogs()
        _holder(designer_root.focus_get()).event_generate("<Return>")  # default button: Delete
        _settle(designer_root, 6)
        assert frame.parent is None and dialog.closed
        tree.focus_force()
        _settle(designer_root)
        tree.event_generate("<Control-z>")
        _settle(designer_root)
        assert dump_ui(session.document) == built
        tree.event_generate("<Control-y>")
        _settle(designer_root)
        assert frame.parent is None
    finally:
        designer_root.withdraw()
    assert tk_errors == []


# ================================================================ second QA pass (after the fixes)
# ---------------------------------------------------------------- QA-13a-03 reopened: PanedWindow
@pytest.mark.gui
def test_a_paned_window_with_a_frame_pane_still_accepts_a_second_pane_by_mouse(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), "PanedWindow")
    paned = app.session.selection.node
    assert _keyboard_insert(app, designer_root, paned, "Frame")
    _settle(designer_root)
    snapshot, box = _snapshot_box(app, paned)
    assert box is not None
    reachable = {
        target.index
        for x in range(box.rect.x - 8, box.rect.x + box.rect.w + 8)
        for y in range(box.rect.y - 8, box.rect.y + box.rect.h + 8)
        if (target := hit_test(snapshot, x, y, NewWidget("Frame"), band=6, bar=3)) is not None
        and target.container is paned
    }
    assert tk_errors == []
    assert reachable == {1}, "no point of the paned window offers a second pane (QA-13a-03)"
    # R-C: the append pane is design-only chrome; a press on it selects the paned window
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    inner = stage.view.inner[id(paned)]
    spacer = inner.nametowidget(str(inner.panes()[-1]))
    assert len(inner.panes()) == 2 and stage.view.node_of(spacer) is paned


@pytest.mark.gui
def test_a_notebook_with_a_frame_page_accepts_a_second_page_on_its_tab_strip(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    """The control of the test above: a Notebook keeps its tab strip as a target."""
    app.session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), "Notebook")
    notebook = app.session.selection.node
    assert _keyboard_insert(app, designer_root, notebook, "Frame")
    _settle(designer_root)
    snapshot, box = _snapshot_box(app, notebook)
    assert box is not None
    hits = [
        target.container is notebook
        for y in range(box.rect.y, box.rect.y + 16)
        if (target := hit_test(snapshot, box.rect.x + box.rect.w - 8, y, NewWidget("Frame")))
        is not None
    ]
    assert True in hits, hits
    assert tk_errors == []


# ---------------------------------------------------------------- R-B in a pack container
@pytest.mark.gui
def test_a_pack_frame_whose_only_child_fills_it_offers_the_append_slot_for_real(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    """Spec 5.4 acceptance 3 with a real pack layout (new Frames default to grid)."""
    session = app.session
    session.new_from_template("main_window")
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, _window(app), "Frame")
    outer = session.selection.node
    assert isinstance(outer, Widget)
    outer.layout = Layout(type="pack")
    app.shell.canvas._render()
    _settle(designer_root)
    assert _keyboard_insert(app, designer_root, outer, "Frame")
    (inner,) = outer.children
    assert isinstance(inner, Widget)
    inner.placement = PackPlacement(fill="both", expand=True)
    app.shell.canvas._render()
    _settle(designer_root)
    snapshot, box = _snapshot_box(app, outer)
    assert box is not None and box.kind == "pack", box
    indexes = {
        target.index
        for x in range(box.rect.x, box.rect.x + box.rect.w)
        for y in range(box.rect.y, box.rect.y + box.rect.h)
        if (target := hit_test(snapshot, x, y, NewWidget("Label"))) is not None
        and target.container is outer
    }
    assert 1 in indexes, indexes
    assert tk_errors == []


# ---------------------------------------------------------------- QA-13a-07 reopened: canvas chrome
@pytest.mark.gui
def test_a_click_on_the_window_body_gives_the_keys_to_the_canvas(
    app: DesignerApp, designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control of the test below: a press on a design widget focuses the canvas."""
    app.session.new_from_template("main_window")
    _settle(designer_root)
    calls: list[int] = []
    monkeypatch.setattr(app.shell.canvas.focus_widget, "focus_set", lambda: calls.append(1))
    stage = app.shell.canvas.stages[0]
    assert stage.view is not None
    stage.view.inner[id(_window(app))].event_generate("<ButtonPress-1>", x=5, y=5)
    _settle(designer_root)
    assert calls


@pytest.mark.gui
@pytest.mark.parametrize("piece", ["title", "kind", "strip", "stage"])
def test_a_click_on_canvas_chrome_gives_the_keys_to_the_canvas(
    app: DesignerApp, designer_root: Any, monkeypatch: pytest.MonkeyPatch, piece: str
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    calls: list[int] = []
    monkeypatch.setattr(app.shell.canvas.focus_widget, "focus_set", lambda: calls.append(1))
    stage = app.shell.canvas.stages[0]
    widget = {
        "title": stage.title,
        "kind": stage.kind,
        "strip": stage.strip.winfo_children()[0],  # the "File" menu of the menu bar strip
        "stage": stage.stage,
    }[piece]
    app.session.select(None, origin="session")
    widget.event_generate("<ButtonPress-1>", x=2, y=2)
    _settle(designer_root)
    assert app.session.selection.node is not None, "the press did not reach the chrome"
    assert calls, f"a click on the {piece} leaves the keyboard focus where it was"


# ---------------------------------------------------------------- status bar, language switch
def _status(app: DesignerApp) -> str:
    return str(app.shell._status.cget("text"))


@pytest.mark.gui
def test_a_language_switch_never_posts_the_selected_row_text_to_the_status_bar(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    window = _window(app)
    app.session.select(window, origin="canvas")
    tree = app.shell.tree.tree
    assert tree is not None
    tree.column("detail", width=40)  # a narrow tree: the window title is cut short
    app.shell.tree._fit_cells()
    _settle(designer_root)
    app.shell.show_message("")
    app.set_language("en_XA")
    _settle(designer_root, 6)
    assert tk_errors == []
    assert not _status(app).startswith(f"{window.id} - "), _status(app)


@pytest.mark.gui
def test_a_language_switch_leaves_no_message_in_the_old_language(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    app.session.new_from_template("main_window")
    _settle(designer_root)
    tree = app.shell.tree.tree
    assert tree is not None
    tree.column("detail", width=600)  # no clipped row: keeps QA-13a-12 out of this test
    assert _keyboard_insert(app, designer_root, _window(app), "Label")
    english = _status(app)
    assert english.startswith("Inserted '"), english
    app.set_language("de_DE")
    _settle(designer_root, 6)
    assert tk_errors == []
    assert _status(app) != english


@pytest.mark.gui
def test_a_canvas_selection_never_posts_the_clipped_row_text_to_the_status_bar(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    """QA-13a-12: only a pick in the tree offers the row text, not a selection made elsewhere."""
    app.session.new_from_template("main_window")
    _settle(designer_root)
    window = _window(app)
    tree = app.shell.tree.tree
    assert tree is not None
    tree.column("detail", width=40)
    app.shell.tree._fit_cells()
    app.session.select(None, origin="tree")
    _settle(designer_root)
    assert tree.selection() == ()  # an empty selection from the tree clears its rows too
    app.shell.show_message("")
    app.session.select(window, origin="canvas")
    _settle(designer_root, 6)
    assert tk_errors == []
    assert tree.selection() == (app.shell.tree.key_of(window),)
    assert not _status(app).startswith(f"{window.id} - "), _status(app)


# ---------------------------------------------------------------- QA-13a-15: rapid clicks
def _clicks(app: DesignerApp, name: str, count: int) -> None:
    """One burst of ``count`` clicks 40 ms apart on the palette item ``name``."""
    tree = app.shell.palette.tree
    assert tree is not None
    for category in tree.get_children():
        tree.item(category, open=f"w:{name}" in tree.get_children(category))
    tree.update_idletasks()
    tree.see(f"w:{name}")
    tree.update_idletasks()
    x, y, _w, h = (int(v) for v in tree.bbox(f"w:{name}"))
    x, y = x + 4, y + h // 2
    start, rootx, rooty = next(_CLOCK), tree.winfo_rootx() + x, tree.winfo_rooty() + y
    for at in range(start, start + 40 * count, 40):
        for sequence, time in (("<ButtonPress-1>", at), ("<ButtonRelease-1>", at + 10)):
            tree.event_generate(sequence, x=x, y=y, rootx=rootx, rooty=rooty, time=time)


@pytest.mark.gui
def test_rapid_clicks_on_a_palette_item_insert_once_per_burst(
    app: DesignerApp, designer_root: Any, tk_errors: list[BaseException]
) -> None:
    """Tk matches <Double-Button-1> on the 3rd and later rapid clicks unless they are bound."""
    session = app.session
    session.new_from_template("main_window")
    _settle(designer_root)
    assert session.stack is not None
    session.select(_window(app), origin="tree")
    before = session.stack.index
    _clicks(app, "Label", 10)
    _settle(designer_root)
    assert session.stack.index == before + 1
    _clicks(app, "Label", 2)  # 5 s later: a new, genuine double-click
    _settle(designer_root)
    assert session.stack.index == before + 2
    assert tk_errors == []


# ---------------------------------------------------------------- selected tagged rows (risk b)
@pytest.mark.gui
@pytest.mark.parametrize("role", ["light", "dark", "high_contrast"])
def test_selected_rows_draw_the_selection_text_colour_over_any_row_tag(
    app: DesignerApp, designer_root: Any, role: str
) -> None:
    """Muted/error tag colours fall to 1.0-2.6:1 on the selection fill; only the style map's
    ``selected`` foreground (Tk applies it over tag options) keeps those rows readable."""
    app.set_theme(role)
    app.flush_theme()
    _settle(designer_root)
    spec = spec_for_role(app.specs, role)
    assert spec is not None
    mapped = ttk.Style(designer_root).map(TREE_STYLE, "foreground")
    selected = [entry[-1] for entry in mapped if "selected" in (str(s) for s in entry[:-1])]
    assert [str(c).upper() for c in selected] == [selection_colours(spec)[1].upper()], mapped
