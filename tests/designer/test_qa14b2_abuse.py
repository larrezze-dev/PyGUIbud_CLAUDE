"""QA pass 1 of Step 14b.2 "Structure": abuse cases (spec direct-manipulation 5, 6, 11 Q7-Q11).

Findings are named QA-14b2-NN; a test for an open finding is ``xfail(strict=True)`` so that the
debugger flips it when the fix lands.
"""

from __future__ import annotations

import builtins
import os
import time
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import read_ui, read_ui_string
from pyguibud.core.model import Window
from pyguibud.core.xml_io import MAX_UI_BYTES, dump_ui, write_ui
from pyguibud.designer import tree_dnd
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.engine import widget_rect
from pyguibud.designer.edit import EditActions
from pyguibud.designer.render_plan import IncludeResolver, design_plan
from pyguibud.designer.targets import Target
from tests.conftest import reset_geometry
from tests.designer.test_include_render import (
    EXAMPLE,
    HEAD,
    REGISTRY,
    _component,
    _expand,
    _file,
    _inc,
    _include,
    _main,
)
from tests.designer.test_qa13a_abuse import (  # noqa: F401 - fixtures and helpers
    _keyboard_insert,
    _settle,
    _window,
    app,
    tk_errors,
)
from tests.designer.test_tree_dnd_gui import _CLOCK, _drag, _point, _setup

B = chr(92)  # a backslash, spelt out so that no escaping can hide a UNC prefix


# ---------------------------------------------------------------- hostile includes (pure)
def _hostile(case: str, folder: Path) -> str:
    """Write what ``case`` needs into ``folder``; return the ``src`` of the include."""
    card = folder / "card.ui"
    body = '<window id="card" kind="component"><layout type="grid"/>{{}}</window></pyguibud-ui>'
    if case == "directory":
        (folder / "sub.ui").mkdir()
        return "sub.ui"
    if case == "empty":
        card.write_bytes(b"")
    elif case == "binary":
        card.write_bytes(os.urandom(4096))
    elif case in ("bomb", "xxe"):
        entity = (
            '<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
            if case == "bomb"
            else '<!ENTITY b SYSTEM "file:///C:/Windows/win.ini">'
        )
        card.write_text(
            f'<?xml version="1.0"?><!DOCTYPE pyguibud-ui [{entity}]>'
            '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
            + body.format(
                '<widget class="Label" id="x"><prop name="text">&b;</prop>'
                '<cell row="0" column="0"/></widget>'
            ),
            "utf-8",
        )
    elif case == "latin1":
        card.write_bytes(
            b'<?xml version="1.0" encoding="ISO-8859-1"?>'
            b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
            + body.format(
                '<widget class="Label" id="x"><prop name="text">\xe9</prop>'
                '<cell row="0" column="0"/></widget>'
            ).encode("latin-1")
        )
    elif case == "utf16":
        card.write_bytes((HEAD.format(v="1.0") + _component() + "</pyguibud-ui>").encode("utf-16"))
    elif case == "huge":  # sparse: 2 GiB on paper, never read whole
        with card.open("wb") as handle:  # one byte over the limit (no 2 GiB written on NTFS)
            handle.truncate(MAX_UI_BYTES + 1)
    elif case == "invalid":
        card.write_text("<pyguibud-ui schema_version=", "utf-8")
    elif case == "major":
        _file(card, _component(), version="2.0")
    elif case == "main_kind":
        _file(card, '<window id="card" kind="main"><layout type="grid"/></window>')
    elif case == "empty_src":
        return ""
    return "card.ui"


@pytest.mark.parametrize(
    "case",
    [
        "directory",
        "empty",
        "binary",
        "bomb",
        "xxe",
        "latin1",
        "utf16",
        "huge",
        "invalid",
        "major",
        "main_kind",
        "empty_src",
    ],
)
def test_a_hostile_included_file_is_a_placeholder_with_a_reason(tmp_path: Path, case: str) -> None:
    src = _hostile(case, tmp_path)
    main = _main(tmp_path / "main.ui", _inc(src))
    document = read_ui(main).document
    top, reasons, _r = _expand(main, document)
    assert top.includes == {} and len(reasons) == 1, case
    assert all(reason.strip() for reason in reasons.values())


@pytest.mark.parametrize(
    "src",
    [
        B * 2 + "server" + B + "share" + B + "x.ui",
        "//server/share/x.ui",
        B * 2 + "?" + B + "UNC" + B + "server" + B + "share" + B + "x.ui",
        B * 2 + "." + B + "pipe" + B + "x.ui",
        "/" + B + "server/share/x.ui",
        "CON",
        "sub/NUL.ui",
        "C:NUL",
        "CONIN$",
    ],
)
def test_a_network_or_device_include_is_never_touched(
    tmp_path: Path, src: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Q8: no stat, no open, no realpath on the path; the reason is R82's."""
    main = _main(tmp_path / "main.ui", _inc(src))
    document = read_ui(main).document
    touched: list[str] = []
    real_stat, real_open = os.stat, builtins.open

    def stat(path: Any, *args: Any, **kwargs: Any) -> Any:
        touched.append(str(path))
        return real_stat(path, *args, **kwargs)

    def opened(path: Any, *args: Any, **kwargs: Any) -> Any:
        touched.append(str(path))
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os, "stat", stat)
    monkeypatch.setattr(builtins, "open", opened)
    _top, reasons, _r = _expand(main, document)
    monkeypatch.undo()
    assert [r for r in reasons.values() if "network share or a device" in r], reasons
    assert not [t for t in touched if "server" in t or "pipe" in t or t.upper().endswith(
        ("CON", "NUL.UI", "NUL", "CONIN$"))], touched  # fmt: skip


def test_cycles_chains_and_file_counts_stop_with_reasons(tmp_path: Path) -> None:
    """Q7: itself by path, A -> B -> A, 10 levels deep, 34 files."""
    main = _file(
        tmp_path / "self.ui",
        '<window id="main" kind="main"><layout type="grid"/>'
        f"{_inc('self.ui', 'comp')}</window>{_component('comp', _inc('self.ui', 'comp', 'loop'))}",
    )
    _top, reasons, _r = _expand(main, read_ui(main).document)
    assert any("cycle" in r for r in reasons.values()), reasons
    for level in range(10):
        nxt = _inc(f"c{level + 1}.ui", f"c{level + 1}", f"i{level}") if level < 9 else ""
        _file(tmp_path / f"c{level}.ui", _component(f"c{level}", nxt))
    main = _main(tmp_path / "deep.ui", _inc("c0.ui", "c0"))
    _top, reasons, _r = _expand(main, read_ui(main).document)
    assert any("deeper than 8" in r for r in reasons.values()), reasons
    incs = "".join(_inc(f"f{i}.ui", f"f{i}", f"j{i}", row=i + 1) for i in range(34))
    for index in range(34):
        _file(tmp_path / f"f{index}.ui", _component(f"f{index}"))
    _file(tmp_path / "many.ui", _component("many", incs))
    main = _main(tmp_path / "top.ui", _inc("many.ui", "many"))
    _top, reasons, _r = _expand(main, read_ui(main).document)
    assert any("more than 32 files" in r for r in reasons.values()), reasons


def test_an_included_file_never_wires_a_handler(tmp_path: Path) -> None:
    """Opening never runs code: events and bindings of an included file are inert."""
    _file(
        tmp_path / "card.ui",
        '<window id="card" kind="component"><layout type="grid"/>'
        '<widget class="Button" id="b"><event name="command" handler="system"/>'
        '<cell row="0" column="0"/></widget></window>',
    )
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    window = document.children[0]
    assert isinstance(window, Window)
    plan = design_plan(document, window, REGISTRY, log=lambda *_a, **_k: None)
    reasons = IncludeResolver(REGISTRY).expand(plan.top, main, 0)
    assert reasons == {} and plan.handlers == {}


@pytest.mark.skipif(os.name != "nt", reason="byte-range locks are a Windows test")
def test_qa_14b2_07_a_file_readable_again_is_shown_again(tmp_path: Path) -> None:
    """Q9: an included file locked by another program (unreadable) shows a placeholder. Once
    the lock is gone the file is unchanged (same mtime and size), so ``changed()`` stays False
    and even a rebuild after an edit reuses the cached failure: the placeholder never goes."""
    import msvcrt

    card = _file(tmp_path / "card.ui", _component())
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    size = card.stat().st_size
    with card.open("r+b") as handle:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, size)
        try:
            _top, reasons, resolver = _expand(main, document)
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, size)
    assert reasons  # unreadable: a placeholder, no traceback
    resolver.changed()  # the focus-in check
    _top, reasons, _r = _expand(main, document, resolver, revision=1)  # and a later edit
    assert reasons == {}


def test_an_include_without_a_component_name_is_a_placeholder(tmp_path: Path) -> None:
    _file(tmp_path / "card.ui", _component())
    text = HEAD.format(v="1.0") + (
        '<window id="main" kind="main"><layout type="grid"/>'
        '<include id="inc" src="card.ui" component=""><cell row="0" column="0"/></include>'
        "</window></pyguibud-ui>"
    )
    main = tmp_path / "main.ui"
    main.write_text(text, "utf-8")
    top, reasons, _r = _expand(main, read_ui(main).document)
    assert top.includes == {} and len(reasons) == 1


# ---------------------------------------------------------------- "(newer format)" evaluation
def test_a_current_schema_include_never_says_newer_format(tmp_path: Path) -> None:
    _file(tmp_path / "card.ui", _component())
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    _top, _reasons, resolver = _expand(main, document)
    assert "newer" not in resolver.describe(_include(document))


def _two_windows(tmp_path: Path) -> tuple[Path, Any]:
    _file(tmp_path / "card.ui", _component(), version="1.9")
    main = _file(
        tmp_path / "main.ui",
        f'<window id="main" kind="main"><layout type="grid"/>{_inc("card.ui")}</window>'
        f"{_component('other')}",
    )
    return main, read_ui(main).document


def test_qa_14b2_01_the_newer_format_flag_survives_a_rebuild_of_another_window(
    tmp_path: Path,
) -> None:
    """An edit in the 'other' tab rebuilds only that tab: the main tab's include must keep
    saying "(newer format)" (``_newer`` is reset per revision, refilled per built window)."""
    main, document = _two_windows(tmp_path)
    resolver = IncludeResolver(REGISTRY)
    for revision, window in ((0, document.children[0]), (1, document.children[1])):
        plan = design_plan(document, window, REGISTRY, log=lambda *_a, **_k: None)
        resolver.expand(plan.top, main, revision)
    assert "(newer format)" in resolver.describe(_include(document))


def test_qa_14b2_02_a_placeholder_include_does_not_claim_to_show_the_component(
    tmp_path: Path,
) -> None:
    """A missing file draws a placeholder, yet the status bar says "'inc' shows 'card' from
    nope.ui (read-only). Edit that file to change it." The status must not contradict the card."""
    main = _main(tmp_path / "main.ui", _inc("nope.ui"))
    document = read_ui(main).document
    _top, reasons, resolver = _expand(main, document)
    assert reasons
    assert " shows " not in resolver.describe(_include(document))


# ---------------------------------------------------------------- tree targets (pure)
def test_tree_targets_refuse_every_hostile_drop() -> None:
    text = HEAD.format(v="1.0") + (
        '<window id="main" kind="main"><layout type="grid"/>'
        '<menubar><menu id="m_file"><prop name="text">File</prop>'
        '<action id="act"><prop name="text">Quit</prop></action></menu></menubar>'
        '<statusbar id="sb"/>'
        '<widget class="Frame" id="frm"><layout type="pack"/>'
        '<widget class="Label" id="a"><pack/></widget>'
        '<widget class="Label" id="b"><pack/></widget></widget>'
        f"{_inc('#', 'card', 'inc', 1)}</window>{_component()}</pyguibud-ui>"
    )
    document = read_ui_string(text).document
    main, card = document.children
    assert isinstance(main, Window) and isinstance(card, Window)
    frm = next(n for n in main.walk() if getattr(n, "id", "") == "frm")
    a = next(n for n in main.walk() if getattr(n, "id", "") == "a")
    inc = _include(document)
    menu = main.menubar.children[0]  # type: ignore[union-attr]
    other = card.children[0]
    cases: list[tuple[object, tree_dnd.Zone, tuple[object, ...], str]] = [
        (a, "into", (frm,), "into itself"),  # its own child
        (frm, "into", (frm,), "into itself"),
        (a, "into", (inc,), "cannot hold"),  # a leaf
        (inc, "into", (a,), "cannot hold"),  # Q11: into an include
        (other, "after", (a,), "another window"),  # D7
        (card, "into", (a,), "another window"),
        (menu, "into", (a,), "Drop elements"),
        (main.statusbar, "into", (a,), "Drop elements"),
        (frm, "into", (menu,), "Only widgets"),
        (frm, "into", (main,), "Only widgets"),
        (frm, "into", (main.statusbar,), "Only widgets"),
        (a, "after", (a,), "already there"),
    ]
    for row, zone, payload, expected in cases:
        found = tree_dnd.target(row, zone, payload, REGISTRY)
        assert isinstance(found, str) and expected in found, (row, zone, payload, found)
    found = tree_dnd.target(a, "before", (inc,), REGISTRY)  # an include moves like a widget
    assert isinstance(found, Target) and found.container is frm


# ---------------------------------------------------------------- tree drag (Tk)
def _stale_commands(app: DesignerApp) -> list[str]:  # noqa: F811
    """Python callbacks the tree still owns although Tcl already deleted them (QA-14b2-09)."""
    tree = app.shell.tree.tree
    if tree is None:
        return []
    names = list(getattr(tree, "_tclCommands", None) or [])
    return [name for name in names if not tree.tk.call("info", "commands", name)]


@pytest.fixture(autouse=True)
def _purge_stale_commands(request: pytest.FixtureRequest) -> Any:
    """QA-14b2-09 leaves dead names in the tree's ``_tclCommands``; ``Shell.dispose`` then
    stops at the tree and leaves the whole shell on the shared root (``test_shell`` fails
    later in a full run). Purge them before ``app`` is disposed so other modules are safe."""
    shell = request.getfixturevalue("app") if "app" in request.fixturenames else None
    yield
    if shell is not None:
        tree = shell.shell.tree.tree
        for name in _stale_commands(shell):
            tree._tclCommands.remove(name)


@pytest.mark.gui
def test_qa_14b2_09_a_tree_drag_leaves_no_dead_callback_behind(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    """``_drag_hover`` schedules the check with ``tree.after`` but ``_cancel_job`` cancels it
    with ``self.frame.after_cancel``: Tcl deletes the command, the tree keeps its name, and
    ``tree.destroy()`` raises "can't delete Tcl command". ``Shell.dispose`` swallows that and
    stops: menubar, toolbar, body and status bar stay on the root (any drag over 2 rows)."""
    frame, first, second = _setup(app, designer_root)
    tree = app.shell.tree.tree
    assert tree is not None
    x, y = _point(app, second, 0.5)
    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=next(_CLOCK))
    for node in (frame, first, frame):  # each new row cancels the pending 60 ms check
        tx, ty = _point(app, node, 0.5)
        tree.event_generate("<B1-Motion>", x=tx, y=ty, state=0x100)
    _wait(designer_root)
    tree.event_generate("<ButtonRelease-1>", x=tx, y=ty, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert second.parent is frame
    assert _stale_commands(app) == []


def _wait(root: Any, seconds: float = 0.25) -> None:
    """Let the 60 ms hover check run (``after`` jobs need real time to pass)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()


@pytest.mark.gui
def test_qa_14b2_03_esc_mid_drag_of_a_multi_selection_cancels_it(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Select two Labels on the canvas (the canvas keeps the focus), drag them in the tree
    into the Frame, press Esc, release: nothing may move. The press on a multi-selected row
    returns "break", so the tree never takes the focus and Esc runs the canvas's "Select
    parent" instead of cancelling; the release then drops the payload anyway."""
    designer_root.geometry("1200x800")
    designer_root.deiconify()  # a withdrawn root never takes the focus
    try:
        frame, first, second = _setup(app, designer_root)
        app.session.select_many((second, first), origin="canvas")  # primary first: (0,0) fits
        _settle(designer_root)
        stack = app.session.stack
        assert stack is not None
        index = stack.index
        proxy = app.shell.canvas.focus_widget  # the user worked on the canvas
        proxy.focus_set()  # no focus_force: never take the OS focus from other windows
        _settle(designer_root)
        _drag(app, designer_root, first, frame, 0.5, release=False)
        _wait(designer_root)
        assert app.shell._message.startswith("Release to move")  # the drop would be accepted
        tree = app.shell.tree.tree
        assert tree is not None
        if str(designer_root.focus_lastfor()) != str(tree):  # root cause: the tree has no focus
            proxy.event_generate("<Escape>")  # so the key goes to the canvas ("Select parent")
            _settle(designer_root)
        else:
            tree.event_generate("<Escape>")
            _settle(designer_root)
        x, y = _point(app, frame, 0.5)
        tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=0x100, time=next(_CLOCK))
        _settle(designer_root)
    finally:
        reset_geometry(designer_root)
    assert stack.index == index and first.parent is not frame
    assert tk_errors == []


@pytest.mark.gui
def test_qa_14b2_05_two_labels_dragged_into_an_empty_grid_frame(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Ctrl+click label1 then label2 (label2 is the primary) and drag them in the tree into
    an empty grid Frame: refused with "That would put an element outside the grid." The
    tree always aims the primary at the first free cell (0, 0) and keeps the offsets, so
    label1 (one row above the primary) lands on row -1. The tree gives no way to pick a cell."""
    frame, first, second = _setup(app, designer_root)
    app.session.select_many((first, second), origin="canvas")
    _settle(designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    _drag(app, designer_root, second, frame, 0.5)
    assert stack.index == index + 1 and first.parent is frame and second.parent is frame
    assert tk_errors == []


@pytest.mark.gui
@pytest.mark.parametrize("language", ["de_DE", "en_XA"])
def test_a_denied_tree_drop_speaks_the_interface_language(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    language: str,
) -> None:
    """Q13: the refusal is the translated text (no settings are written: i18n directly)."""
    from pyguibud import i18n

    frame, _first, second = _setup(app, designer_root)
    app.session.select(frame, origin="tree")
    _settle(designer_root)
    i18n.set_language(language)
    try:
        _settle(designer_root)
        _drag(app, designer_root, frame, second, 0.5, release=False)
        _wait(designer_root)
        leaf = "'{id}' cannot hold elements: drop them before or after it."
        expected = i18n._(leaf).format(id=second.id)  # a Label is a leaf: "into" it is refused
        assert app.shell._message == expected
        tree = app.shell.tree.tree
        assert tree is not None
        tree.event_generate("<ButtonRelease-1>", x=-50, y=-50, state=0x100, time=next(_CLOCK))
        _settle(designer_root)
        assert app.shell._message == i18n._("Drag cancelled.") != "Drag cancelled."
    finally:
        i18n.set_language("en_GB")
        _settle(designer_root)
    assert frame.parent is _window(app) and tk_errors == []


@pytest.mark.gui
def test_qa_14b2_06_leaving_the_tree_while_a_hover_check_is_pending(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Move onto a valid row and leave the tree within 60 ms: the scheduled check still fires
    and replaces "Release to cancel." with "Release to move ...", although a release there
    cancels (``_drag_hover`` leaves the job pending on its outside branch)."""
    frame, _first, second = _setup(app, designer_root)
    tree = app.shell.tree.tree
    assert tree is not None
    x, y = _point(app, second, 0.5)
    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=next(_CLOCK))
    tx, ty = _point(app, frame, 0.5)
    tree.event_generate("<B1-Motion>", x=x + 12, y=y + 12, state=0x100)
    tree.event_generate("<B1-Motion>", x=tx, y=ty, state=0x100)  # schedules the check
    tree.event_generate("<B1-Motion>", x=-40, y=-40, state=0x100)  # leaves before 60 ms
    _wait(designer_root)
    assert tk_errors == []
    assert app.shell._message == "Release to cancel."
    tree.event_generate("<ButtonRelease-1>", x=-40, y=-40, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert second.parent is not frame
    assert tk_errors == []


@pytest.mark.gui
def test_a_read_only_document_refuses_a_tree_drop(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    path = _file(
        tmp_path / "ro.ui",
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="Frame" id="frm"><layout type="grid"/><cell row="0" column="0"/></widget>'
        '<widget class="Label" id="lbl"><cell row="1" column="0"/></widget></window>',
        version="1.9",
    )
    app.session.open_document(read_ui(path), path=path)
    _settle(designer_root)
    stack = app.session.stack
    assert stack is not None and stack.read_only
    window = _window(app)
    frm, lbl = window.children
    index = stack.index
    app.session.select(lbl, origin="tree")
    _settle(designer_root)
    _drag(app, designer_root, lbl, frm, 0.5, release=False)
    _wait(designer_root)
    hover = app.shell._message
    tree = app.shell.tree.tree
    key = app.shell.tree.key_of(frm)
    assert tree is not None and key is not None and "drop-denied" in tree.item(key, "tags")
    x, y = _point(app, frm, 0.5)
    tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert lbl.parent is window and stack.index == index
    assert "read-only" in hover.lower() or "read only" in hover.lower(), hover
    assert tk_errors == []


@pytest.mark.gui
def test_a_payload_spanning_two_windows_is_refused(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    text = HEAD.format(v="1.0") + (
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="Frame" id="frm"><layout type="grid"/><cell row="0" column="0"/></widget>'
        '<widget class="Label" id="lbl"><cell row="1" column="0"/></widget></window>'
        f"{_component()}</pyguibud-ui>"
    )
    app.session.open_document(read_ui_string(text), path=None)
    _settle(designer_root)
    main, card = app.session.document.children  # type: ignore[union-attr]
    frm, lbl = main.children
    other = card.children[0]
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    app.session.select_many((other, lbl), origin="canvas")  # normalised to one window
    _settle(designer_root)
    assert app.session.selection.nodes == (lbl,)
    app.session.select(other, origin="tree")
    _settle(designer_root)
    _drag(app, designer_root, other, frm, 0.5, release=False)  # D7
    _wait(designer_root)
    assert app.shell._message == "Elements cannot be dragged to another window. Use Cut and Paste."
    x, y = _point(app, frm, 0.5)
    tree = app.shell.tree.tree
    assert tree is not None
    tree.event_generate("<ButtonRelease-1>", x=x, y=y, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert stack.index == index and other.parent is card
    assert tk_errors == []


@pytest.mark.gui
def test_an_include_row_moves_renders_and_undoes_in_one_step(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Q11 + UAT 2/6: drag the example's include into a new Frame, undo, redo, save, reopen."""
    copy = tmp_path / "with_include.ui"
    copy.write_bytes(EXAMPLE.read_bytes())
    (tmp_path / "address_card.ui").write_bytes((EXAMPLE.parent / "address_card.ui").read_bytes())
    app.session.open_document(read_ui(copy), path=copy)
    _settle(designer_root)
    document = app.session.document
    assert document is not None
    original = dump_ui(document)
    window = _window(app)
    assert _keyboard_insert(app, designer_root, window, "Frame")
    frame = window.children[-1]
    include = _include(document)
    after_insert = dump_ui(document)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    app.session.select(include, origin="tree")
    _settle(designer_root)
    _drag(app, designer_root, include, frame, 0.5)
    assert include.parent is frame and stack.index == index + 1
    stage = app.shell.canvas.stages[0]
    view = stage.view
    assert view is not None and id(include) in view.included  # still expanded where it went
    app.session.select(window, origin="tree")
    _settle(designer_root)
    rect = widget_rect(view.outer[id(include)], stage.stage)
    assert rect is not None and rect in stage.overlay._empty  # R-E outline where it is now
    stack.undo()
    _settle(designer_root)
    assert dump_ui(document) == after_insert
    stack.redo()
    stack.undo()
    stack.undo()
    _settle(designer_root)
    assert dump_ui(document) == original
    stack.redo()
    stack.redo()  # the include inside the Frame again: save and reopen it
    _settle(designer_root)
    saved = tmp_path / "saved.ui"
    write_ui(document, saved, backup=False)
    data = saved.read_bytes()
    assert b"ent_city" not in data and b"inc_address" in data  # no expansion leaks in
    again = tmp_path / "again.ui"
    write_ui(read_ui(saved).document, again, backup=False)
    assert again.read_bytes() == data
    assert tk_errors == []


@pytest.mark.gui
def test_deleting_an_included_inner_widget_deletes_the_whole_include(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Q11: a click inside an expanded include selects the include; Delete removes it in one
    undo step; Ctrl+Z restores it expanded."""
    app.session.open_document(read_ui(EXAMPLE), path=EXAMPLE)
    _settle(designer_root)
    document = app.session.document
    assert document is not None
    include = _include(document)
    view = app.shell.canvas.stages[0].view
    assert view is not None
    inner = next(w for w in view.outer[id(include)].winfo_children() if w.winfo_class() == "TEntry")
    assert view.node_of(inner) is include
    app.session.select(view.node_of(inner), origin="canvas")
    _settle(designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    EditActions(app.session, lambda _q, then: then(), lambda *_a: None).delete()
    _settle(designer_root)
    assert include not in _window(app).children and stack.index == index + 1
    stack.undo()
    _settle(designer_root)
    view = app.shell.canvas.stages[0].view
    assert view is not None and id(include) in view.included
    assert tk_errors == []


@pytest.mark.gui
def test_qa_14b2_04_a_nested_external_include_under_a_same_file_include_refreshes(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """main shows the same-file component 'comp', which includes card.ui. Editing card.ui on
    disk and coming back (focus-in) must refresh the main tab too: only windows with an
    *external* include of their own are marked stale."""
    card = _file(tmp_path / "card.ui", _component())
    main = _file(
        tmp_path / "main.ui",
        f'<window id="main" kind="main"><layout type="grid"/>{_inc("#", "comp")}</window>'
        f"{_component('comp', _inc('card.ui', 'card', 'nested'))}",
    )
    app.session.open_document(read_ui(main), path=main)
    _settle(designer_root)

    def labels() -> int:
        stage = app.shell.canvas.stages[0]
        assert stage.view is not None
        frame = stage.view.outer[id(_include(app.session.document))]  # type: ignore[arg-type]
        found, todo = 0, [frame]
        while todo:
            widget = todo.pop()
            found += widget.winfo_class() == "TLabel"
            todo.extend(widget.winfo_children())
        return found

    before = labels()
    _file(
        card,
        _component("card", '<widget class="Label" id="more"><cell row="1" column="0"/></widget>'),
    )
    stat = card.stat()
    os.utime(card, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    app.shell.canvas.refresh_includes()  # what the shell's <FocusIn> calls
    _settle(designer_root)
    app.shell.canvas.show_window(_window(app))
    _settle(designer_root)
    assert labels() == before + 1
    assert tk_errors == []


@pytest.mark.gui
def test_qa_14b2_08_an_empty_included_component_can_be_clicked(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """An include of an empty component draws a 1 x 1 px frame with a 1 px dashed outline:
    practically invisible and impossible to click on the canvas (only the tree reaches it).
    Expected: at least a clickable minimum (like R-A for empty containers) or the card."""
    _file(tmp_path / "card.ui", '<window id="card" kind="component"><layout type="grid"/></window>')
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    app.session.open_document(read_ui(main), path=main)
    _settle(designer_root)
    include = _include(app.session.document)  # type: ignore[arg-type]
    view = app.shell.canvas.stages[0].view
    assert view is not None and id(include) in view.included
    frame = view.outer[id(include)]
    frame.update_idletasks()
    assert tk_errors == []
    assert min(frame.winfo_reqwidth(), frame.winfo_reqheight()) >= 16


# ---------------------------------------------------------------- QA pass 2 (after the fixes)
def test_qa_14b2_10_one_focus_in_heals_every_include_that_reads_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two included files are locked by another program (a read error, same stamp), then both
    locks go. ``IncludeResolver.changed()`` stops at the first file that reads again (``any``),
    and the rebuild's validation still finds the other one's cached read error: the second
    include stays a placeholder until another focus change, and each heal costs a rebuild."""
    from pyguibud.core.errors import XmlIoError
    from pyguibud.designer import render_plan
    from pyguibud.i18n import N_

    for k in range(2):
        _file(tmp_path / f"c{k}.ui", _component(f"c{k}"))
    body = "".join(_inc(f"c{k}.ui", f"c{k}", f"i{k}", row=k + 1) for k in range(2))
    main = _main(tmp_path / "main.ui", body)
    document = read_ui(main).document
    locked = {"c0.ui", "c1.ui"}
    real = read_ui

    def read(path: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(path).name in locked:
            raise XmlIoError(
                "xml.read_failed", N_("The file could not be read: {reason}"),
                source=str(path), reason="locked",
            )  # fmt: skip
        return real(path, *args, **kwargs)

    monkeypatch.setattr(render_plan, "read_ui", read)
    _top, reasons, resolver = _expand(main, document)
    assert len(reasons) == 2
    locked.clear()  # both programs let go
    assert resolver.changed()  # the one focus-in
    _top, reasons, _r = _expand(main, document, resolver)
    assert reasons == {}


@pytest.mark.gui
def test_qa_14b2_11_a_tree_drag_survives_the_commit_of_a_pending_inspector_edit(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Type a new Text in the inspector (no Enter) and drag the selected row in the tree into
    the Frame. The press moves the focus to the tree, the inspector commits on FocusOut, the
    report change re-renders the tree and ``_render`` ends the drag: the drop does nothing and
    says nothing. (Single-row drags too: the class binding moves the focus the same way.)"""
    from pyguibud.designer.panels.inspector import InspectorPanel

    frame, _first, second = _setup(app, designer_root)
    stack = app.session.stack
    assert stack is not None
    index = stack.index
    inspector: InspectorPanel = app.shell.inspector
    editor = inspector._editors["prop:text"]
    editor.var.set("typed")
    assert editor.pending()
    tree = app.shell.tree.tree
    assert tree is not None
    x, y = _point(app, second, 0.5)
    tree.event_generate("<ButtonPress-1>", x=x, y=y, time=next(_CLOCK))
    editor.commit_pending()  # what the FocusOut of the focus moving to the tree runs
    designer_root.update()
    tx, ty = _point(app, frame, 0.5)
    for to in ((x + 12, y + 12), (tx, ty)):
        tree.event_generate("<B1-Motion>", x=to[0], y=to[1], state=0x100)
    _wait(designer_root)
    tree.event_generate("<ButtonRelease-1>", x=tx, y=ty, state=0x100, time=next(_CLOCK))
    _settle(designer_root)
    assert tk_errors == []
    assert second.props["text"].value == "typed"  # the edit is never lost
    assert second.parent is frame and stack.index == index + 2


_COLUMN = HEAD.format(v="1.0") + (
    '<window id="main" kind="main"><layout type="grid"/>'
    + "".join(
        f'<widget class="Label" id="{k}"><cell row="{r}" column="0"/></widget>'
        for r, k in enumerate(("a", "b", "c"))
    )
    + "</window></pyguibud-ui>"
)


@pytest.mark.parametrize(("moved", "onto"), [("c", "b"), ("b", "a")])
def test_qa_14b2_12_dropping_before_a_sibling_in_a_full_grid_column(moved: str, onto: str) -> None:
    """UAT 14b.2 step 1 ("drag a row above a sibling") in a one-column grid (every template):
    with no free cell before the sibling the drop goes to a new last row. Dropping c before b
    says "'c' is already there."; dropping b before a sends b below c. Expected: the element
    lands above the sibling, or a refusal that says why (never a move to the end)."""
    from pyguibud.core import CommandStack
    from pyguibud.core.model import GridCell
    from pyguibud.designer.editing import move_command

    document = read_ui_string(_COLUMN).document
    n = {getattr(x, "id", ""): x for x in document.children[0].walk()}
    stack = CommandStack(document, REGISTRY)
    found = tree_dnd.target(n[onto], "before", [n[moved]], REGISTRY)
    if isinstance(found, str):
        assert found != f"'{moved}' is already there."
        return
    built = move_command([n[moved]], found)
    if isinstance(built, str):
        assert built != f"'{moved}' is already there."
        return
    assert stack.execute(built).accepted
    cells = [getattr(n[k], "placement", None) for k in (moved, onto)]
    assert isinstance(cells[0], GridCell) and isinstance(cells[1], GridCell)
    assert cells[0].row < cells[1].row


def test_qa_14b2_13_a_placeholder_status_does_not_repeat_itself(tmp_path: Path) -> None:
    """A placeholder whose reason is not an include rule's (a missing src here; also a cycle
    or a budget stop) reads "'inc' cannot be shown: The component 'card' from '' cannot be
    shown." in the status bar."""
    src = _hostile("empty_src", tmp_path)
    main = _main(tmp_path / "main.ui", _inc(src))
    document = read_ui(main).document
    _top, _reasons, resolver = _expand(main, document)
    assert resolver.describe(_include(document)).count("cannot be shown") == 1


# ---------------------------------------------------------------- QA pass 3 (make room)
def _grid_doc(cells: dict[str, tuple[int, int, int, int]]) -> tuple[Any, dict[str, Any]]:
    body = "".join(
        f'<widget class="Label" id="{k}"><cell row="{r}" column="{c}" rowspan="{rs}"'
        f' columnspan="{cs}"/></widget>'
        for k, (r, c, rs, cs) in cells.items()
    )
    xml = (
        HEAD.format(v="1.0")
        + f'<window id="main" kind="main"><layout type="grid"/>{body}</window></pyguibud-ui>'
    )
    document = read_ui_string(xml).document
    return document, {getattr(x, "id", ""): x for x in document.children[0].walk()}


def _random_grid(rng: Any) -> dict[str, tuple[int, int, int, int]]:
    """A random grid of up to 5 x 4 cells, spans included, without collisions."""
    cells: dict[str, tuple[int, int, int, int]] = {}
    taken: set[tuple[int, int]] = set()
    for r in range(rng.randint(1, 5)):
        for c in range(rng.randint(1, 4)):
            if (r, c) in taken or rng.random() < 0.3:
                continue
            rs, cs = rng.choice([1, 1, 1, 2, 3]), rng.choice([1, 1, 1, 2])
            area = {(rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs)}
            if area & taken:
                rs = cs = 1
                area = {(r, c)}
            taken |= area
            cells[f"w{len(cells)}"] = (r, c, rs, cs)
    return cells


def test_tree_drops_next_to_a_grid_sibling_never_overlap_and_undo_exactly() -> None:
    """QA pass 3: random grids (spans, several columns), random before/after drops of one or two
    nodes. Every accepted drop leaves no overlap, saves and reopens byte for byte, and one undo
    restores every pushed sibling (redo too); a refusal is a translated reason, never a crash."""
    import random

    from pyguibud.core import CommandStack
    from pyguibud.designer.editing import move_command

    rng, accepted = random.Random(1), 0
    for _trial in range(600):
        cells = _random_grid(rng)
        if len(cells) < 2:
            continue
        document, n = _grid_doc(cells)
        stack = CommandStack(document, REGISTRY)
        before = dump_ui(document)
        nodes = [n[k] for k in rng.sample(list(cells), rng.choice([1, 1, 2]))]
        found = tree_dnd.target(n[rng.choice(list(cells))], rng.choice(["before", "after"]),
                                nodes, REGISTRY)  # fmt: skip
        built = move_command(nodes, found) if isinstance(found, Target) else found
        if isinstance(built, str):
            assert built  # a reason
            continue
        assert stack.execute(built).accepted, cells
        accepted += 1
        seen: set[tuple[int, int]] = set()
        for child in document.children[0].children:
            p = child.placement
            area = {(r, c) for r in range(p.row, p.row + p.rowspan)
                    for c in range(p.column, p.column + p.columnspan)}  # fmt: skip
            assert not area & seen, cells
            seen |= area
        after = dump_ui(document)
        assert dump_ui(read_ui_string(after.decode("utf-8")).document) == after
        assert stack.undo() and dump_ui(document) == before
        assert stack.redo() and dump_ui(document) == after
    assert accepted > 200


def test_qa_14b2_14_a_wide_block_dropped_after_a_tall_sibling_lands_above_it() -> None:
    """x spans rows 0-1 in column 1; w spans columns 0-1 in row 3. Dropping w "after" x puts
    w on (1, 0) (the next cell in reading order), which overlaps x's lower half, so x is pushed
    down to rows 2-3: w ends up visually above x although the tree says "after x".
    Expected: w lands below/right of x's whole area (or x is not pushed above-to-below).
    Fixed in Step 19c (H38, ruling D10 a): the block goes under the taller sibling."""
    from pyguibud.core import CommandStack
    from pyguibud.designer.editing import move_command

    document, n = _grid_doc(
        {"x": (0, 1, 2, 1), "a": (0, 0, 1, 1), "c": (1, 0, 1, 1), "w": (3, 0, 1, 2)}
    )
    found = tree_dnd.target(n["x"], "after", [n["w"]], REGISTRY)
    assert isinstance(found, Target)
    built = move_command([n["w"]], found)
    assert not isinstance(built, str)
    assert CommandStack(document, REGISTRY).execute(built).accepted
    x, w = n["x"].placement, n["w"].placement
    assert w.row >= x.row + x.rowspan or (w.row >= x.row and w.column >= x.column + 1)


@pytest.mark.gui
def test_qa_14b2_15_a_canvas_rebuild_mid_drag_leaves_the_drop_targets_stale(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    """Edit an included file elsewhere, come back with a press-and-drag on a canvas widget: the
    focus-in rebuilds the stage mid-drag (``refresh_includes``) but the drag keeps the snapshot
    taken before it. The component grew 152 px; the pointer over 'a' where it is now hit-tests
    to nothing ("Release to cancel.") and the drop is lost. When the component shrinks instead,
    the stale snapshot executes a move to a cell the user does not point at (row 0 for a pointer
    on row 1; one undo step). Expected: the drag re-snapshots after a rebuild, or is cancelled."""
    from pyguibud.core.model import GridCell
    from tests.designer.test_drag_move import _outer

    card = _file(tmp_path / "card.ui", _component())
    main = _main(
        tmp_path / "main.ui",
        f'<include id="inc" src="{card.name}" component="card"><cell row="0" column="0"/>'
        '</include><widget class="Label" id="a"><cell row="1" column="0"/></widget>'
        '<widget class="Label" id="b"><cell row="2" column="0"/></widget>',
    )
    app.session.open_document(read_ui(main), path=main)
    _settle(designer_root)
    _inc_node, a, b = _window(app).children
    app.session.select(b, origin="tree")
    _settle(designer_root)
    widget = _outer(app, b)
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    widget.event_generate("<ButtonPress-1>", x=3, y=3, rootx=sx, rooty=sy, time=next(_CLOCK))
    widget.event_generate("<B1-Motion>", x=13, y=3, rootx=sx + 10, rooty=sy, state=0x100)
    body = "".join(
        f'<widget class="Label" id="x{k}"><cell row="{k + 1}" column="0"/></widget>'
        for k in range(8)
    )
    card.write_text(card.read_text("utf-8").replace("</window>", body + "</window>", 1), "utf-8")
    stat = os.stat(card)
    os.utime(card, (stat.st_atime, stat.st_mtime + 5))
    app.shell.canvas.refresh_includes()  # what the focus-in of the press runs
    _settle(designer_root)
    drag = app.shell.canvas.drag
    if drag.state == "idle":  # cancelled on the rebuild: acceptable
        return
    now = _outer(app, a)
    px, py = now.winfo_rootx() + 4, now.winfo_rooty() + now.winfo_height() // 2
    now.event_generate("<B1-Motion>", x=0, y=0, rootx=px, rooty=py, state=0x100)
    _wait(designer_root)
    now.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=px, rooty=py, state=0x100, time=next(_CLOCK)
    )
    _settle(designer_root)
    assert tk_errors == []
    cell = b.placement
    assert isinstance(cell, GridCell) and cell.row == 1  # beside 'a', where the pointer is


@pytest.mark.gui
@pytest.mark.parametrize("change", ["shrink", "same"])
def test_qa_14b2_15_a_rebuild_mid_drag_drops_where_the_pointer_is(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
    change: str,
) -> None:
    """Regression QA-14b2-15: the component shrinks (the stale snapshot dropped on row 0), or
    the file is rewritten unchanged (the drag must survive the rebuild): the drop resolves
    against the rebuilt layout and lands where the pointer is, as one undo step."""
    from pyguibud.core.model import GridCell
    from tests.designer.test_drag_move import _outer

    rows = "".join(
        f'<widget class="Label" id="x{k}"><cell row="{k + 1}" column="0"/></widget>'
        for k in range(8)
    )
    card = _file(tmp_path / "card.ui", _component("card", rows))
    main = _main(
        tmp_path / "main.ui",
        f'<include id="inc" src="{card.name}" component="card"><cell row="0" column="0"/>'
        '</include><widget class="Label" id="a"><cell row="1" column="0"/></widget>'
        '<widget class="Label" id="b"><cell row="2" column="0"/></widget>',
    )
    app.session.open_document(read_ui(main), path=main)
    _settle(designer_root)
    _inc_node, a, b = _window(app).children
    app.session.select(b, origin="tree")
    _settle(designer_root)
    widget = _outer(app, b)
    sx, sy = widget.winfo_rootx() + 3, widget.winfo_rooty() + 3
    widget.event_generate("<ButtonPress-1>", x=3, y=3, rootx=sx, rooty=sy, time=next(_CLOCK))
    widget.event_generate("<B1-Motion>", x=13, y=3, rootx=sx + 10, rooty=sy, state=0x100)
    _file(card, _component("card", rows if change == "same" else ""))
    stat = os.stat(card)
    os.utime(card, (stat.st_atime, stat.st_mtime + 5))
    app.shell.canvas.refresh_includes()  # what the focus-in of the press runs
    _settle(designer_root)
    assert app.shell.canvas.drag.state == "dragging"
    depth = app.session.stack.index  # type: ignore[union-attr]
    now = _outer(app, a)
    px, py = now.winfo_rootx() + 4, now.winfo_rooty() + now.winfo_height() // 2
    now.event_generate("<B1-Motion>", x=0, y=0, rootx=px, rooty=py, state=0x100)
    _wait(designer_root)
    now.event_generate(
        "<ButtonRelease-1>", x=0, y=0, rootx=px, rooty=py, state=0x100, time=next(_CLOCK)
    )
    _settle(designer_root)
    assert tk_errors == []
    cell = b.placement
    assert isinstance(cell, GridCell) and cell.row == 1  # beside 'a', where the pointer is
    assert app.session.stack.index == depth + 1  # type: ignore[union-attr]
