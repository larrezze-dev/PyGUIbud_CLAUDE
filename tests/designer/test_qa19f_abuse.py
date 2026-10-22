"""QA abuse pass of Step 19f (layout, accessibility, locales; H85-H96).

Careless and hostile use of what 19f changed: restarts with saved sashes (D4), the F1 sheet
(D6) placed low on a real screen or re-fitted by a language/theme switch, the grouped Theme
menu, dialogs under resize/theme storms, huge pasted texts in every dialog field, and bidi or
control characters in every place an id or a title is shown.

Every "no crash" check is real: the Tk callback errors and the ERROR log records (the app's
language and theme steps catch and log) are collected and must stay empty. Open defects are
strict ``xfail`` marks named ``QA-19f-NN``; the debugger removes the mark with the fix.
"""

from __future__ import annotations

import ctypes
import json
import logging
import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core.model import Widget, Window
from pyguibud.core.text import printable
from pyguibud.designer.dialogs.base import ModalDialog
from tests.conftest import reset_geometry
from tests.designer.test_qa18_abuse import ALL_LANGUAGES, HELLO, _designer, _settle, _switch
from tests.designer.test_sweep_19f import DIALOGS, _buttons, _descendants, _open

pytestmark = pytest.mark.gui

RLO = "\u202e"
_BIDI_UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta generator="pyguibud" source_locale="en_GB"/>
  <variables>
    <var id="v_{rlo}txt" type="string"/>
  </variables>
  <window id="w_{rlo}gnp" kind="main">
    <prop name="title">Evil {rlo}exe.txt&#155;&#8232;</prop>
    <layout type="grid" padding="12" gap="6">
      <column index="0" weight="1"/>
      <row index="0" weight="1"/>
    </layout>
    <widget class="Button" id="btn_{rlo}gnp">
      <cell row="0" column="0"/>
      <prop name="text">Click {rlo}me</prop>
    </widget>
  </window>
  <window id="second" kind="dialog">
    <layout type="grid" padding="12" gap="6"/>
  </window>
</pyguibud-ui>
"""


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def errors(designer_root: Any, caplog: pytest.LogCaptureFixture) -> Iterator[list[str]]:
    """Tk callback errors and ERROR log records seen during the test (must stay empty)."""
    found: list[str] = []
    original = designer_root.report_callback_exception

    def collect(kind: type[BaseException], value: BaseException, _tb: object) -> None:
        found.append(f"{kind.__name__}: {value}")

    designer_root.report_callback_exception = collect
    caplog.set_level(logging.ERROR)
    try:
        yield found
    finally:
        designer_root.report_callback_exception = original
    found += [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.fixture
def app(designer_root: Any, tmp_path: Path) -> Iterator[Any]:
    """The designer at its minimum size (800 x 500) on a copy of hello.ui."""
    shutil.copy(HELLO, tmp_path / "hello.ui")
    with _designer(designer_root, tmp_path / "hello.ui") as designer:
        yield designer


def _work_area() -> tuple[int, int, int, int]:
    """The real work area of the primary screen (left, top, right, bottom), Windows only."""
    from ctypes import wintypes

    rect = wintypes.RECT()
    if sys.platform == "win32":  # the callers skip elsewhere; the check keeps mypy portable
        ctypes.windll.user32.SystemParametersInfoW(
            0x30, 0, ctypes.byref(rect), 0
        )  # SPI_GETWORKAREA
    return rect.left, rect.top, rect.right, rect.bottom


def _commands(root: Any) -> int:
    return len(root.tk.splitlist(root.tk.call("info", "commands")))


def _scroll_consistent(dialog: Any) -> list[str]:
    """What is wrong with the F1 sheet's scroll area: stale region, hidden bar, lost Close."""
    canvas, bar, inner = dialog._scroll
    problems = []
    region = [int(float(v)) for v in str(canvas.cget("scrollregion")).split()]
    if region and region[3] != inner.winfo_reqheight():
        problems.append(f"scrollregion {region[3]} != content {inner.winfo_reqheight()}")
    needs = inner.winfo_reqheight() > canvas.winfo_height() + 1
    if needs and not bar.winfo_ismapped():
        problems.append("content taller than the view, but no scrollbar")
    window, close = dialog.window, dialog.close_button
    if close.winfo_rooty() + close.winfo_height() > window.winfo_rooty() + window.winfo_height():
        problems.append("Close is below the dialog's edge")
    return problems


# ------------------------------------------------------------------ D4 across a restart
def test_qa19f_01_an_auto_grown_palette_shrinks_back_after_a_restart(
    designer_root: Any, errors: list[str]
) -> None:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings

    def start(settings: Settings) -> Any:
        designer = DesignerApp(designer_root, settings=settings)
        assert designer.open_path(HELLO)
        designer_root.deiconify()
        designer_root.geometry("1200x700+0+0")
        for _round in range(3):
            _settle(designer_root)
        return designer

    first = start(Settings())
    try:
        english = int(first.shell.body.sashpos(0))
        _switch(first, "de_DE")  # never dragged: the palette only grows to the German names
        german = int(first.shell.body.sashpos(0))
        assert german > english + 10
        first._remember_window()  # what Quit stores
        saved = dict(first.settings.sashes)
    finally:
        first.dispose()
    second = start(Settings(sashes=saved, language="de_DE"))
    try:
        second._apply_sashes()  # what the first real size does
        _settle(designer_root)
        # Preconditions, so a fix flips this to XPASS for the right reason: the restart is in
        # German with the palette at the width it auto-grew to.
        assert i18n.get_language() == "de_DE"
        assert abs(int(second.shell.body.sashpos(0)) - german) <= 2
        _switch(second, "en_GB")
        _settle(designer_root)
        assert abs(int(second.shell.body.sashpos(0)) - english) <= 2
    finally:
        i18n.set_language("en_GB")
        second.dispose()
        reset_geometry(designer_root)
    assert errors == []


def test_qa19f_02_squeezed_palette_names_come_back_at_the_next_switch(
    app: Any, errors: list[str]
) -> None:
    """Ruled 2026-10-19 (user): enlarging the window keeps the elided names (tooltips stay);
    D4 re-fits on a language/theme switch only. Pins that ruling."""
    root, palette = app.root, app.shell.palette
    minimum = root.minsize()
    try:
        root.minsize(1, 1)
        root.geometry("700x500")
        _switch(app, "fr_FR")
        tree = palette.tree
        elided = [i for i, (full, _ic, _c) in palette._rows.items() if tree.item(i, "text") != full]
        assert elided  # squeezed
        root.geometry("1600x900")
        for _round in range(3):
            _settle(root)
        still = [i for i, (full, _ic, _c) in palette._rows.items() if tree.item(i, "text") != full]
        assert still  # kept until the next switch (ruling)
        _switch(app, "en_GB", "fr_FR")
        cut = [i for i, (full, _ic, _c) in palette._rows.items() if tree.item(i, "text") != full]
        assert cut == []
    finally:
        root.minsize(*minimum)
        reset_geometry(root)
    assert errors == []


@pytest.mark.parametrize(
    "sashes",
    [
        {"main": ["x"]},
        {"main": [-5, 10**12]},
        {"main": [[1, 2]]},
        {"main": []},
        {"main": [99999, 99999], "right": [99999]},
        {"main": [0, 0]},
        "nonsense",
        {"main": [200, 900], "palette_user": [100_000]},  # QA-19f-01: the dragged width
        {"main": [200, 900], "palette_user": ["x"]},
        {"palette_user": []},
    ],
    ids=[
        "text",
        "negative-huge",
        "nested",
        "empty",
        "beyond-window",
        "zero",
        "not-a-dict",
        "dragged-huge",
        "dragged-text",
        "dragged-empty",
    ],
)
def test_hand_edited_saved_sashes_never_break_the_start(
    designer_root: Any, errors: list[str], tmp_path: Path, sashes: object
) -> None:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import load_settings, settings_path

    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": 1, "sashes": sashes}), encoding="utf-8")
    settings, _problem = load_settings()
    designer = DesignerApp(designer_root, settings=settings)
    try:
        assert designer.open_path(HELLO)
        designer_root.deiconify()
        designer_root.geometry("800x500+0+0")
        for _round in range(3):
            _settle(designer_root)
        designer._apply_sashes()
        _settle(designer_root)
        _switch(designer, "de_DE", "en_GB")
        from pyguibud.designer.shell import CANVAS_FLOOR
        from pyguibud.designer.theme_tk import scaled

        assert designer.shell.canvas.frame.winfo_width() >= scaled(designer_root, CANVAS_FLOOR) - 1
        assert designer.shell.palette.frame.winfo_width() > 20  # never collapsed
    finally:
        i18n.set_language("en_GB")
        designer.dispose()
        reset_geometry(designer_root)
    assert errors == []


# ------------------------------------------------------------------ F1 sheet (H85, D6)
@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows work area")
def test_qa19f_03_f1_close_stays_on_the_work_area_under_a_low_window(
    app: Any, errors: list[str]
) -> None:
    root = app.root
    _left, _top, _right, bottom = _work_area()
    try:
        root.geometry(f"800x500+120+{bottom - 540}")  # a normal window near the taskbar
        _settle(root)
        app.open_shortcuts()
        _settle(root)
        dialog: Any = app._live_dialogs()[-1]
        close = dialog.close_button
        assert close.winfo_rooty() + close.winfo_height() <= bottom
    finally:
        reset_geometry(root)
    assert errors == []


#: Tall dialogs besides F1: the shared ModalDialog._centre()/work_area() places them all.
_TALL = ("plugins", "recovery 50 entries", "text editor 5000 chars", "export long path")


@pytest.mark.skipif(sys.platform != "win32", reason="reads the Windows work area")
@pytest.mark.parametrize("name", _TALL)
def test_tall_dialogs_keep_their_buttons_on_the_work_area_under_a_low_window(
    app: Any, errors: list[str], name: str
) -> None:
    root = app.root
    _left, _top, _right, bottom = _work_area()
    try:
        root.geometry(f"800x500+120+{bottom - 540}")
        _settle(root)
        dialog = _open(app, name)
        lowest = max(b.winfo_rooty() + b.winfo_height() for b in _buttons(dialog.window))
        dialog.close()
        assert lowest <= bottom, (name, lowest, bottom)
    finally:
        reset_geometry(root)
    assert errors == []


@pytest.mark.parametrize("codes", [("de_DE", "en_GB"), ("en_XA", "fr_FR", "en_GB"), ALL_LANGUAGES])
def test_f1_follows_a_language_switch_with_a_consistent_scroll_area(
    app: Any, errors: list[str], monkeypatch: pytest.MonkeyPatch, codes: tuple[str, ...]
) -> None:
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: (1366, 728))
    app.open_shortcuts()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    for code in codes:
        _switch(app, code)
        _settle(app.root)
        assert _scroll_consistent(dialog) == [], code
        assert dialog.window.winfo_height() <= 728, code
    assert len(app._live_dialogs()) == 1
    assert errors == []


def test_f1_follows_a_theme_switch_with_a_consistent_scroll_area(
    app: Any, errors: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: (1366, 728))
    _switch(app, "de_DE")
    app.open_shortcuts()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    for role in ("dark", "high_contrast", "light", "high_contrast"):
        app.set_theme(role)
        app.flush_theme()
        _settle(app.root)
        assert _scroll_consistent(dialog) == [], role
    canvas = dialog._scroll[0]
    dialog.close_button.event_generate("<End>")
    _settle(app.root)
    assert canvas.yview()[1] >= 0.999  # the last row (the F6 hint) is reachable
    assert errors == []


def test_f1_scroll_keys_never_reach_the_document(app: Any, errors: list[str]) -> None:
    """Arrows/Page/Home/End scroll the sheet; edit keys pressed in it never edit the form."""
    session = app.session
    node = next(n for n in session.document.walk() if isinstance(n, Widget))
    session.select(node, origin="canvas")
    _settle(app.root)
    depth, before = session.stack.can_undo, session.document
    app.open_shortcuts()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    keys = ("<Down>", "<Next>", "<End>", "<Up>", "<Prior>", "<Home>", "<Delete>", "<Left>",
            "<Control-x>", "<Control-v>", "<Control-d>", "<Control-z>", "<Right>")  # fmt: skip
    for key in keys:
        dialog.close_button.focus_force()
        dialog.close_button.event_generate(key)
        _settle(app.root)
    assert not dialog.closed
    assert session.stack.can_undo == depth and not session.dirty
    assert session.document is before and node in list(session.document.walk())
    assert errors == []


# ------------------------------------------------------------------ Theme menu (H89, H11)
def test_qa19f_04_opening_the_theme_menu_again_and_again_leaks_nothing(
    app: Any, errors: list[str]
) -> None:
    menu = app.shell.submenus["preview.theme"]
    app.preview.themes = ["flatly", "darkly", "cyborg", "sape-light", "sape-dark", "mystery"]
    app.preview.fill_theme_menu(menu)  # warm-up
    _settle(app.root)
    children, commands = len(menu.winfo_children()), _commands(app.root)
    for _opening in range(20):
        app.preview.fill_theme_menu(menu)
    _settle(app.root)
    assert len(menu.winfo_children()) == children
    assert _commands(app.root) - commands == 0
    assert errors == []


@pytest.mark.parametrize("code", ALL_LANGUAGES)
def test_theme_menu_groups_have_unique_access_keys_in_every_language(
    app: Any, errors: list[str], code: str
) -> None:
    menu = app.shell.submenus["preview.theme"]
    app.preview.themes = ["flatly", "darkly", "mystery"]
    _switch(app, code)
    app.preview.fill_theme_menu(menu)
    keys = []
    for index in range(int(menu.index("end")) + 1):
        if menu.type(index) in ("cascade", "radiobutton", "command"):
            underline = int(menu.entrycget(index, "underline"))
            if underline >= 0:
                keys.append(str(menu.entrycget(index, "label"))[underline].lower())
    assert len(keys) == 3 and len(set(keys)) == 3, keys
    assert errors == []


# ------------------------------------------------------------------ storms with a dialog open
_STORM_DIALOGS = ("about", "confirm", "export", "message", "new file", "plugins", "recovery",
                  "rename", "save changes", "shortcuts", "text editor")  # fmt: skip


@pytest.mark.parametrize("name", _STORM_DIALOGS)
def test_resize_and_theme_storm_while_a_dialog_is_open(
    app: Any, errors: list[str], name: str
) -> None:
    root = app.root
    minimum = root.minsize()
    dialog = _open(app, name)
    try:
        root.minsize(1, 1)
        for size in ("1x1", "7680x4320", "1x1", "1366x768", "1x1", "800x500") * 2:
            root.geometry(size)
            root.update_idletasks()
        _settle(root)
        for role in ("dark", "high_contrast", "light"):
            app.set_theme(role)
            app.flush_theme()
        _settle(root)
        assert not dialog.closed and dialog.window.winfo_exists()
        assert app._live_dialogs() == [dialog]
        grab: Any = dialog.window
        assert str(grab.grab_current()) == str(dialog.window)  # still modal
        for button in _buttons(dialog.window):
            assert button.winfo_ismapped(), button
    finally:
        root.minsize(*minimum)
        dialog.close()
        reset_geometry(root)
    assert errors == []


@pytest.mark.parametrize("name", ["shortcuts", "export", "about", "plugins"])
def test_a_dialog_opened_over_an_8k_window_lands_on_the_screen(
    app: Any, errors: list[str], name: str
) -> None:
    from pyguibud.designer import screen

    root = app.root
    minimum = root.minsize()
    try:
        root.minsize(1, 1)
        root.geometry("7680x4320+0+0")
        _settle(root)
        dialog = _open(app, name)
        window = dialog.window
        width, height, left, top = screen.desktop_bounds(root)
        assert (
            left <= window.winfo_rootx()
            and window.winfo_rootx() + window.winfo_width() <= left + width
        )
        assert (
            top <= window.winfo_rooty()
            and window.winfo_rooty() + window.winfo_height() <= top + height
        )
        dialog.close()
    finally:
        root.minsize(*minimum)
        reset_geometry(root)
    assert errors == []


# ------------------------------------------------------------------ one press, one action
def test_one_return_on_each_question_runs_its_answer_once(app: Any, errors: list[str]) -> None:
    calls: list[str] = []
    app._confirm("Delete it?", lambda: calls.append("confirm"))
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    dialog.confirm_button.focus_force()
    for _press in range(4):  # a held Enter repeats
        dialog.window.event_generate("<Return>") if dialog.window.winfo_exists() else None
    _settle(app.root)
    app._ask(lambda: "Which?", [("_OK", lambda: calls.append("ok")), ("_Cancel", None)])
    _settle(app.root)
    choice: Any = app._live_dialogs()[-1]
    for _press in range(4):
        choice.window.event_generate("<Return>") if choice.window.winfo_exists() else None
    _settle(app.root)
    app._ask_name("main", lambda _t: None, lambda t: calls.append(f"rename {t}"))
    _settle(app.root)
    rename: Any = app._live_dialogs()[-1]
    rename.value.set("other")
    for _press in range(4):
        rename.entry.event_generate("<Return>") if rename.window.winfo_exists() else None
    _settle(app.root)
    assert calls == ["confirm", "ok", "rename other"]
    assert app._live_dialogs() == []
    assert errors == []


# ------------------------------------------------------------------ huge pasted texts
#: The longest paste a field takes: the paste guard (QA-19c-01) refuses more than 2,000
#: characters in every ttk field; non-ASCII on purpose (Tk lays it out slowest).
_HUGE = ("Z:/" + "überlange_ordnerstruktur_" * 80)[:1990] + "/datei.ui"
#: A Text widget has no paste guard: about 100,000 characters.
_HUGE_TEXT = "Z:/" + "überlange_ordnerstruktur_" * 4000 + "/datei.ui"


def _assert_buttons_on_screen(dialog: Any) -> None:
    window = dialog.window
    assert window.winfo_height() <= window.winfo_screenheight()
    assert window.winfo_width() <= window.winfo_screenwidth()
    for button in _buttons(window):
        right = button.winfo_rootx() - window.winfo_rootx() + button.winfo_width()
        bottom = button.winfo_rooty() - window.winfo_rooty() + button.winfo_height()
        assert button.winfo_ismapped(), button
        assert right <= window.winfo_width() and bottom <= window.winfo_height(), button


def test_a_huge_pasted_id_in_the_rename_dialog_is_refused_and_fits(
    app: Any, errors: list[str]
) -> None:
    app.session.select(app.session.document.children[0], origin="tree")
    app.registry.invoke("document.rename")  # the real check: a dry run of the rename
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    dialog.value.set(_HUGE)
    dialog.accept()
    _settle(app.root)
    assert not dialog.closed
    _assert_buttons_on_screen(dialog)
    assert errors == []


def test_a_huge_pasted_export_pot_path_keeps_the_buttons(app: Any, errors: list[str]) -> None:
    app.exporter.start()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    dialog.want_pot.set(True)
    dialog._pot_state()
    dialog.pot.set(_HUGE.replace(".ui", ".pot"))
    dialog.output.set(_HUGE.replace(".ui", ".py"))
    dialog.accept()
    _settle(app.root)
    _assert_buttons_on_screen(dialog)
    assert len(str(dialog.message.cget("text"))) < 1000
    assert errors == []


def test_a_huge_text_in_the_text_dialog_and_its_fields_keeps_the_buttons(
    app: Any, errors: list[str]
) -> None:
    DIALOGS["text editor"](app)
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", _HUGE_TEXT)
    dialog.context.set(_HUGE)
    dialog.comment.set(_HUGE)
    _settle(app.root)
    _assert_buttons_on_screen(dialog)
    assert errors == []


def test_huge_pastes_in_the_panel_fields_never_break_the_window(
    app: Any, errors: list[str]
) -> None:
    from pyguibud.designer.shell import CANVAS_FLOOR
    from pyguibud.designer.theme_tk import scaled

    variables = app.shell.variables
    variables.id_var.set(_HUGE)
    variables.default_var.set(_HUGE)
    _settle(app.root)
    node = next(n for n in app.session.document.walk() if isinstance(n, Widget))
    app.session.select(node, origin="tree")
    _settle(app.root)
    editor: Any = app.shell.inspector._editors["field:id"]
    editor.var.set(_HUGE)
    editor._enter()
    _settle(app.root)
    assert node.id != _HUGE  # refused: not an identifier
    assert app.shell.canvas.frame.winfo_width() >= scaled(app.root, CANVAS_FLOOR) - 1
    assert app.root.winfo_width() <= app.root.winfo_screenwidth()
    assert errors == []


def test_a_2000_character_window_id_keeps_the_export_dialog_on_screen(
    app: Any, errors: list[str]
) -> None:
    window = app.session.document.children[0]
    assert isinstance(window, Window)
    window.id = "w" * 2000  # a valid identifier, only absurdly long (loaded from a file)
    app.exporter.start()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    _assert_buttons_on_screen(dialog)
    browse = dialog.output_browse
    assert (
        browse.winfo_rootx() + browse.winfo_width()
        <= dialog.window.winfo_rootx() + dialog.window.winfo_width()
    )
    assert errors == []


# ------------------------------------------------------------------ bidi / control ids
@pytest.fixture
def bidi(app: Any, tmp_path: Path) -> Any:
    """``_BIDI_UI`` opened from a file whose name holds U+202E (``evil<RLO>lmx.ui``)."""
    path = tmp_path / f"evil{RLO}lmx.ui"
    path.write_text(_BIDI_UI.format(rlo=RLO), encoding="utf-8")
    assert app.open_path(path)
    _settle(app.root)
    return app


def _shown_texts(widget: Any) -> list[str]:
    """Display-only texts: labels, buttons, list rows and tabs (never an editable field)."""
    texts = []
    for child in [widget, *_descendants(widget)]:
        cls = child.winfo_class()
        if cls in ("TLabel", "Label", "TButton", "TCheckbutton"):
            texts.append(str(child.cget("text")))
        if cls == "Treeview":
            stack = list(child.get_children(""))
            while stack:
                item = stack.pop()
                texts.append(str(child.item(item, "text")))
                texts += [str(v) for v in child.item(item, "values")]
                stack += list(child.get_children(item))
        if cls == "TNotebook":
            texts += [str(child.tab(t, "text")) for t in child.tabs()]
    return texts


def _raw(texts: list[str]) -> list[str]:
    return [t for t in texts if t != printable(t)]


def _menu_labels(menu: Any) -> list[str]:
    last = menu.index("end")
    count = int(last) + 1 if last is not None else 0
    return [str(menu.entrycget(i, "label")) for i in range(count) if menu.type(i) == "command"]


def test_bidi_ids_are_escaped_in_the_status_bar_tree_inspector_canvas_and_title(
    bidi: Any, errors: list[str]
) -> None:
    app = bidi
    session = app.session
    for node in session.document.walk():
        if isinstance(node, (Widget, Window)):
            session.select(node, origin="tree")
            _settle(app.root)
            assert _raw([str(app.shell._status.cget("text"))]) == [], node.id
            for panel in (app.shell.tree.frame, app.shell.inspector.frame):
                assert _raw(_shown_texts(panel)) == [], (node.id, panel)
    canvas = app.shell.canvas
    user_widgets = set(_shown_texts(canvas.frame)) - {
        str(canvas.notebook.tab(t, "text")) for t in canvas.notebook.tabs()
    }
    shown = [t for t in _shown_texts(canvas.frame) if t not in user_widgets]
    shown += [t for t in _shown_texts(canvas.frame) if t.startswith(("w_", "Evil"))]
    assert _raw(shown) == []  # tab texts and the stage title (the user's widgets keep theirs)
    assert errors == []


def test_qa19f_05_bidi_variable_ids_are_escaped_in_the_variables_panel(
    bidi: Any, errors: list[str]
) -> None:
    assert _raw(_shown_texts(bidi.shell.variables.frame)) == []
    assert errors == []


def test_qa19f_06_the_delete_window_question_escapes_a_bidi_id(
    bidi: Any, errors: list[str]
) -> None:
    app = bidi
    app.session.select(app.session.document.children[0], origin="tree")
    app.registry.invoke("document.delete")
    _settle(app.root)
    dialogs = app._live_dialogs()
    assert dialogs
    texts = _shown_texts(dialogs[-1].window)
    for dialog in dialogs:
        dialog.close()
    assert _raw(texts) == []
    assert errors == []


def test_qa19f_07_recent_files_and_title_escape_a_bidi_file_name(
    bidi: Any, errors: list[str]
) -> None:
    app = bidi
    recent = app.shell.submenus["file.recent"]
    app._fill_recent()
    labels = _menu_labels(recent)
    assert any("evil" in label for label in labels)
    assert _raw([*labels, app.root.title()]) == []
    assert errors == []


def test_bidi_ids_are_escaped_in_the_export_dialog(bidi: Any, errors: list[str]) -> None:
    app = bidi
    app.exporter.start()
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    texts = _shown_texts(dialog.window)
    dialog.close()
    assert _raw(texts) == []
    assert errors == []


# ------------------------------------------------------------------ tree name priority (D5)
def _nested_ui(depth: int, leaf_id: str, labels: int = 0) -> str:
    """A main window with ``depth`` nested frames, a leaf label and ``labels`` siblings."""
    inner = f'<widget class="Label" id="{leaf_id}"><cell row="0" column="0"/></widget>'
    for level in reversed(range(depth)):
        inner = (
            f'<widget class="Frame" id="f{level}"><cell row="0" column="0"/>'
            f'<layout type="grid"/>{inner}</widget>'
        )
    extra = "".join(
        f'<widget class="Label" id="l{i}"><cell row="{i + 1}" column="0"/></widget>'
        for i in range(labels)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<meta generator="pyguibud" source_locale="en_GB"/>'
        f'<window id="main" kind="main"><layout type="grid"/>{inner}{extra}</window>'
        "</pyguibud-ui>"
    )


@pytest.mark.parametrize(
    ("depth", "leaf"),
    [(0, "x" * 300), (25, "deep_label"), (8, "a_rather_long_identifier_" * 4)],
    ids=["300-char-id", "25-levels", "8-levels-100-char-id"],
)
def test_long_ids_and_deep_nesting_never_push_the_canvas_below_its_floor(
    app: Any, errors: list[str], tmp_path: Path, depth: int, leaf: str
) -> None:
    from pyguibud.designer.shell import CANVAS_FLOOR
    from pyguibud.designer.theme_tk import scaled

    path = tmp_path / "nested.ui"
    path.write_text(_nested_ui(depth, leaf), encoding="utf-8")
    assert app.open_path(path)
    for _round in range(3):
        _settle(app.root)
    shell = app.shell
    assert shell.canvas.frame.winfo_width() >= scaled(app.root, CANVAS_FLOOR) - 1
    assert shell.palette.frame.winfo_width() >= shell.palette.heading.winfo_reqwidth()
    assert shell.right.winfo_width() > 0 and shell.right.winfo_ismapped()
    assert errors == []


@pytest.mark.budget
def test_the_tree_name_fit_stays_cheap_on_a_large_document(
    app: Any, errors: list[str], tmp_path: Path
) -> None:
    from tests.designer.conftest import best_of

    path = tmp_path / "large.ui"
    path.write_text(_nested_ui(40, "leaf", labels=1500), encoding="utf-8")
    assert app.open_path(path)
    _settle(app.root)
    tree = app.shell.tree
    took = best_of(tree._fit_cells, repeat=3)
    assert took < 0.050, f"{took * 1000:.1f} ms"  # a tenth of it would do; 100 ms per edit
    assert errors == []


# ------------------------------------------------------------------ long texts that reach a field
def _timed_select(app: Any, node: Any) -> float:
    import time

    started = time.perf_counter()
    app.session.select(node, origin="tree")
    _settle(app.root)
    return time.perf_counter() - started


@pytest.mark.parametrize("length", [2_000, 10_000, 40_000])
def test_a_long_non_ascii_text_from_the_text_dialog_never_freezes_the_inspector(
    app: Any, errors: list[str], length: int
) -> None:
    """The Text dialog has no paste guard: its value lands in the one-line inspector field."""
    DIALOGS["text editor"](app)
    _settle(app.root)
    dialog: Any = app._live_dialogs()[-1]
    dialog.text.delete("1.0", "end")
    dialog.text.insert("1.0", ("überlänge " * (length // 10 + 1))[:length])
    dialog.accept()
    _settle(app.root)
    label = next(
        n for n in app.session.document.walk() if isinstance(n, Widget) and n.class_name == "Label"
    )
    other = app.session.document.children[0]
    _timed_select(app, other)
    took = _timed_select(app, label)
    assert took < 1.0, f"{took:.2f} s to show the label in the inspector"
    assert errors == []


@pytest.mark.parametrize("length", [2_000, 10_000, 40_000])
def test_a_file_with_a_long_non_ascii_id_and_title_never_freezes_the_designer(
    app: Any, errors: list[str], tmp_path: Path, length: int
) -> None:
    import time

    long_id = ("ü" * length)[:length]
    path = tmp_path / "long.ui"
    path.write_text(_nested_ui(0, long_id).replace(
        '<layout type="grid"/>', f'<prop name="title">{"Länge " * (length // 6)}</prop>'
        '<layout type="grid"/>', 1), encoding="utf-8")  # fmt: skip
    started = time.perf_counter()
    assert app.open_path(path)
    _settle(app.root)
    opened = time.perf_counter() - started
    node = next(n for n in app.session.document.walk() if isinstance(n, Widget))
    took = _timed_select(app, node)
    window = _timed_select(app, app.session.document.children[0])
    assert max(opened, took, window) < 1.0, (opened, took, window)
    # The id field shows a read-only clip that is never committed (Enter, focus out, flush).
    _timed_select(app, node)
    editor = app.shell.inspector._editors["field:id"]
    assert editor.long == (length > 2_000)
    assert editor.widget.instate(["readonly"]) == editor.long
    depth = app.session.stack.can_undo
    editor._enter()
    assert app.shell.inspector.flush()
    assert node.id == long_id and app.session.stack.can_undo == depth
    assert errors == []
