"""Step 19f sweep (TESTING): H93 locales (no cut label, no stale English in any dialog), the
dialog-fit gate on a 1366 x 768 screen, H94 keyboard-only walk-through and H95 focus/contrast.

The screenshots of the real-desktop sweep are made by a separate script (not a test). Strict
``xfail`` marks the open findings QA-19f-T##; the debugger removes the mark with the fix.
"""

from __future__ import annotations

import datetime
import re
import shutil
import tkinter
from collections.abc import Callable, Iterator
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest
from babel.messages.pofile import read_po

from pyguibud import i18n
from pyguibud.core.keys import split_mnemonic, tk_shortcut
from pyguibud.core.model import Widget
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.theme import NON_TEXT_CONTRAST, ThemeSpec, contrast, load_theme_specs
from tests.conftest import reset_geometry
from tests.designer.test_qa18_abuse import (
    _KEYS,
    ALL_LANGUAGES,
    HELLO,
    ROOT,
    _designer,
    _document_tokens,
    _recovery,
    _settle,
    _switch,
)

pytestmark = pytest.mark.gui

AREA = (1366, 728)  # a 1366 x 768 screen minus a 40 px taskbar
_TEXT_CLASSES = {"TLabel", "Label", "TButton", "Button", "TCheckbutton", "Checkbutton",
                 "TRadiobutton", "Radiobutton", "TMenubutton"}  # fmt: skip


@pytest.fixture
def app(designer_root: Any, tmp_path: Path) -> Iterator[Any]:
    """The designer at its minimum size (800 x 500) on a copy of hello.ui."""
    shutil.copy(HELLO, tmp_path / "hello.ui")
    with _designer(designer_root, tmp_path / "hello.ui") as designer:
        yield designer


# ------------------------------------------------------------------ dialog openers
def _first_label(app: Any) -> Widget:
    document = app.session.document
    return next(n for n in document.walk() if isinstance(n, Widget) and n.class_name == "Label")


def _text_editor(app: Any, value: str | None = None) -> None:
    node = _first_label(app)
    app.session.select(node, origin="tree")
    _settle(app.root)
    inspector = app.shell.inspector
    editor = inspector._editors["prop:text"]
    if value is not None:
        editor.var.set(value)
    inspector.special(editor, "text")


def _dirty_then_guard(app: Any) -> None:
    app.session.select(_first_label(app), origin="tree")
    assert app.registry.invoke("edit.delete") is not False
    _settle(app.root)
    assert app.session.dirty
    app.guard(lambda: None)  # Save / Don't save / Cancel


def _question() -> str:
    from pyguibud.designer.dialogs import save_changes

    return i18n._(save_changes._M_QUESTION).format(name="main.ui")  # a real msgid


def _many_recoveries(app: Any) -> None:
    from pyguibud.designer.recovery import RecoveryEntry

    now = datetime.datetime.now(datetime.timezone.utc)
    deep = "Z:/" + "/".join(f"projekt_verzeichnis_{i}" for i in range(12))
    entries = [RecoveryEntry(ROOT, f"{deep}/f{i}.ui", f"f{i}.ui", now) for i in range(50)]
    app.open_recovery(entries)


def _export_long_path(app: Any) -> None:
    app.exporter.start()
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    dialog.output.set("Z:/no-such-folder/" + "d" * 4000 + "/x.py")
    dialog.accept()  # refused: the elided path is shown in the dialog


#: Every designer dialog (the OS file and colour pickers are native and out of scope).
DIALOGS: dict[str, Callable[[Any], None]] = {
    "about": lambda app: app.open_about(),
    "confirm": lambda app: app._confirm(_question(), lambda: None),
    "export": lambda app: app.exporter.start(),
    "export long path": _export_long_path,
    "message": lambda app: app._tell(_question),
    "new file": lambda app: app.open_new_file(),
    "plugins": lambda app: app.open_plugins(),
    "recovery": _recovery,
    "recovery 50 entries": _many_recoveries,
    "rename": lambda app: app._ask_name("main", lambda _t: None, lambda _t: None),
    "save changes": _dirty_then_guard,
    "shortcuts": lambda app: app.open_shortcuts(),
    "text editor": _text_editor,
    "text editor 5000 chars": lambda app: _text_editor(app, "Lorem ipsum dolor " * 280),
}


def _open(app: Any, name: str) -> ModalDialog:
    DIALOGS[name](app)
    _settle(app.root)
    live: list[ModalDialog] = app._live_dialogs()
    assert live, name
    return live[-1]


def _descendants(widget: Any) -> Iterator[Any]:
    for child in widget.winfo_children():
        yield child
        if not isinstance(child, tkinter.Toplevel):
            yield from _descendants(child)


def _buttons(window: Any) -> list[Any]:
    return [w for w in _descendants(window) if w.winfo_class() == "TButton"]


def _off_screen(dialog: ModalDialog, area: tuple[int, int]) -> list[str]:
    """What breaks the fit: a window larger than ``area``, or a button unmapped, squeezed or
    outside the window."""
    window = dialog.window
    problems = []
    if window.winfo_reqwidth() > area[0] or window.winfo_height() > area[1]:
        problems.append(f"window {window.winfo_reqwidth()}x{window.winfo_height()}")
    buttons = _buttons(window)
    if not buttons:
        problems.append("no button")
    for button in buttons:
        top = button.winfo_rooty() - window.winfo_rooty()
        left = button.winfo_rootx() - window.winfo_rootx()
        if not button.winfo_ismapped():
            problems.append(f"{button} unmapped")
        elif (button.winfo_height() < button.winfo_reqheight() - 1
              or button.winfo_width() < button.winfo_reqwidth() - 1):  # fmt: skip
            problems.append(f"{button} squeezed")
        elif top + button.winfo_height() > window.winfo_height():
            problems.append(f"{button} below the window ({top}+{button.winfo_height()})")
        elif left + button.winfo_width() > window.winfo_width():
            problems.append(f"{button} right of the window")
    return problems


def _assert_buttons_on_screen(dialog: ModalDialog, area: tuple[int, int]) -> None:
    assert _off_screen(dialog, area) == []


# ------------------------------------------------------------------ dialog-fit gate (F1)
@pytest.fixture
def plugins_app(designer_root: Any) -> Iterator[Any]:
    """A registry with 40 plugin distributions (the list scrolls inside the dialog)."""
    from tests.designer.test_plugins_17c import _EP, _Dist, _registry, _spec

    points = [
        _EP(f"p{i}", f"zz_p{i}:x", _Dist(f"zz-plugin-mit-langem-namen-{i}"), [_spec(f"zz:W{i}")])
        for i in range(40)
    ]
    with _designer(designer_root, HELLO, _registry(*points)) as designer:
        yield designer


@pytest.mark.parametrize("lang", ["de_DE", "nl_NL"])
def test_every_dialog_fits_1366x768_with_its_buttons_on_screen(
    app: Any, lang: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """All of ``DIALOGS`` in one designer (a fresh designer per dialog costs ~1 s each)."""
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: AREA)
    _switch(app, lang)
    problems: dict[str, list[str]] = {}
    for name in sorted(DIALOGS):
        dialog = _open(app, name)
        dialog.fit()
        _settle(app.root)
        problems[name] = _off_screen(dialog, AREA)
        dialog.close()
        _settle(app.root)
    assert {k: v for k, v in problems.items() if v} == {}
    assert len(problems) == len(DIALOGS) == 14


@pytest.mark.parametrize("lang", ["de_DE", "nl_NL"])
def test_the_plugins_dialog_with_40_rows_fits_1366x768(
    plugins_app: Any, lang: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: AREA)
    _switch(plugins_app, lang)
    plugins_app.open_plugins()
    _settle(plugins_app.root)
    dialog = plugins_app._live_dialogs()[-1]
    assert len(dialog.tree.get_children("")) == 41  # the built-in row plus 40
    dialog.fit()
    _settle(plugins_app.root)
    _assert_buttons_on_screen(dialog, AREA)


# ------------------------------------------------------------------ H93 cut labels
def _clipped(top: Any) -> list[str]:
    """Mapped single-line texts narrower than they need, and tree headings wider than the
    column: ``"<class> <path>: <text> (<shown>/<needed> px)"``."""
    found: list[str] = []
    style = ttk.Style()
    heading = tkfont.nametofont(str(style.lookup("Heading", "font") or "TkHeadingFont"))
    for widget in _descendants(top):
        try:
            if not widget.winfo_ismapped():
                continue
            cls = widget.winfo_class()
            if isinstance(widget, ttk.Treeview) and "headings" in str(widget.cget("show")):
                for column in ("#0", *widget["columns"]):
                    text = str(widget.heading(column, "text"))
                    width = int(widget.column(column, "width"))
                    need = heading.measure(text) + 8
                    if text and width and need > width:
                        found.append(f"Heading {widget}: {text!r} ({width}/{need} px)")
                continue
            if cls not in _TEXT_CLASSES:
                continue
            text = str(widget.cget("text"))
            if not text.strip() or "\n" in text:
                continue
            if str(widget.cget("compound")) == "image":
                continue
            wrap = str(widget.cget("wraplength") or "0")
            if wrap not in ("", "0") and float(widget.winfo_fpixels(wrap)) > 0:
                continue
            shown = _visible_width(widget)
            if shown < widget.winfo_reqwidth() - 1:
                found.append(f"{cls} {widget}: {text!r} ({shown}/"
                             f"{widget.winfo_reqwidth()} px)")  # fmt: skip
        except tkinter.TclError:
            continue
    return found


def _visible_width(widget: Any) -> int:
    """The width of ``widget`` that is really shown: its own, cut by every ancestor's right
    edge (a child larger than its parent is clipped, not reported by ``winfo_width``), up to
    the first canvas (a scrolled viewport, where the rest is reached by scrolling)."""
    left = widget.winfo_rootx()
    right = left + widget.winfo_width()
    parent = widget.master
    while parent is not None:
        if isinstance(parent, tkinter.Canvas):  # a scrolled viewport (the stage): not a cut
            break
        right = min(right, parent.winfo_rootx() + parent.winfo_width())
        if isinstance(parent, (tkinter.Toplevel, tkinter.Tk)):
            break
        parent = parent.master
    return int(max(0, right - left))


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_h93_no_label_is_cut_at_800x500_in_the_main_window_or_any_dialog(
    app: Any, lang: str
) -> None:
    _switch(app, lang)
    found: dict[str, list[str]] = {"main window": _clipped(app.root)}
    for name in sorted(DIALOGS):
        dialog = _open(app, name)
        found[name] = _clipped(dialog.window)
        dialog.close()
        _settle(app.root)
    cut = [f"{name}: {line}" for name, lines in found.items() for line in lines]
    assert cut == [], " | ".join(cut)


# ------------------------------------------------------------------ H93 untranslated
def _static_texts(top: Any) -> dict[str, str]:
    """``path -> text`` of the static texts of ``top`` (labels, buttons, headings, tabs)."""
    texts: dict[str, str] = {}
    for widget in _descendants(top):
        try:
            if not widget.winfo_ismapped():  # a hidden note is retranslated when shown
                continue
            cls = widget.winfo_class()
            if cls in _TEXT_CLASSES:
                texts[str(widget)] = str(widget.cget("text"))
            elif isinstance(widget, ttk.Treeview):
                for column in ("#0", *widget["columns"]):
                    texts[f"{widget}#{column}"] = str(widget.heading(column, "text"))
            elif isinstance(widget, ttk.Notebook):
                notebook: Any = widget
                for tab in notebook.tabs():
                    texts[f"{widget}@{tab}"] = str(notebook.tab(tab, "text"))
        except tkinter.TclError:
            continue
    if isinstance(top, tkinter.Toplevel):
        texts[f"{top}:title"] = top.title()
    return {path: text for path, text in texts.items() if text}


def _identical(lang: str) -> set[str]:
    """Texts a translator deliberately kept as in English (msgstr == msgid) in ``lang``."""
    path = i18n.LOCALE_DIR / lang / "LC_MESSAGES" / f"{i18n.DOMAIN}.po"
    if not path.is_file():
        return set()
    with path.open("rb") as handle:
        catalog = read_po(handle)
    shown = (
        (split_mnemonic(m.id)[0], split_mnemonic(str(m.string))[0])
        for m in catalog
        if m.id and isinstance(m.id, str)
    )
    return {source for source, text in shown if source == text}  # the access key may move


def _stale(before: dict[str, str], after: dict[str, str], allowed: set[str]) -> list[str]:
    return sorted(
        f"{path}: {text!r}"
        for path, text in after.items()
        if before.get(path) == text
        and re.search(r"[A-Za-z]{2}", text)
        and not _KEYS.match(text)
        and not _NODE_PATH.match(text)
        and text not in allowed
    )


#: A technical node path (``window[main]/widget[btn]``) is never translated (diagnostics).
_NODE_PATH = re.compile(r"^(?:window|widget|menu|action|include)\[")


def _english(lang: str) -> set[str]:
    """Every source text (access key removed) that ``lang`` translates differently."""
    with (i18n.LOCALE_DIR / f"{i18n.DOMAIN}.pot").open("rb") as handle:
        source = {split_mnemonic(str(m.id))[0] for m in read_po(handle) if isinstance(m.id, str)}
    return {text for text in source if re.search(r"[A-Za-z]{2}", text)} - _identical(lang)


@pytest.mark.parametrize("lang", [c for c in ALL_LANGUAGES if c != i18n.SOURCE_LANGUAGE])
def test_h93_no_english_text_is_left_in_the_main_window_or_any_dialog(app: Any, lang: str) -> None:
    """The main window after a switch (no text left as it was in en_GB), then every dialog
    opened in ``lang`` (no text equal to an English source the catalogue translates)."""
    allowed = _identical(lang) | _document_tokens(app) | set(i18n.LANGUAGES.values())
    allowed |= {"Ui_Main", "lost.ui", "pyguibud", "main", "main.ui", "f0.ui", "PyGUIbud"}
    stale: dict[str, list[str]] = {}
    before = _static_texts(app.root)
    _switch(app, lang)
    stale["main window"] = _stale(before, _static_texts(app.root), allowed)
    english = _english(lang) - allowed
    for name in sorted(DIALOGS):
        dialog = _open(app, name)
        texts = _static_texts(dialog.window)
        stale[name] = sorted(
            f"{p}: {t!r}" for p, t in texts.items() if t in english and not _KEYS.match(t)
        )  # key names (Delete, Tab) stay English in this step (QA-18 deferral)
        dialog.close()
        _settle(app.root)
    assert {k: v for k, v in stale.items() if v} == {}


def test_the_cut_label_detector_sees_a_cut_label(designer_root: Any) -> None:
    """Negative control of ``_clipped``: a label squeezed into a 20 px cell is reported."""
    top = tkinter.Toplevel(designer_root)
    try:
        holder = ttk.Frame(top, width=20, height=30)
        holder.grid_propagate(False)
        holder.pack()
        ttk.Label(holder, text="A much longer label than twenty pixels").grid(row=0, column=0)
        top.update()
        assert len(_clipped(top)) == 1
    finally:
        top.destroy()


# ------------------------------------------------------------------ H94 keyboard only
def _focused(app: Any) -> Any:
    widget = app.root.focus_get()
    assert widget is not None, "nothing has the keyboard focus"
    return widget


def _key(app: Any, sequence: str, **options: Any) -> None:
    """One key press, delivered where the keyboard focus is (as the OS would)."""
    _focused(app).event_generate(sequence, **options)
    _settle(app.root)


def _type(app: Any, text: str) -> None:
    for char in text:
        _key(app, "<KeyPress>", keysym="space" if char == " " else char)


def _panel_of(app: Any) -> int:
    return int(app.shell._panel_index_of(_focused(app)))


def _saved(session: Any) -> tuple[Any, bool]:
    return session.path, bool(session.dirty)


@pytest.fixture
def keyboard(app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The designer focused; the native Save-as picker and the preview child are stubbed."""
    from tests.designer.fakes import FakeProcess

    started: list[FakeProcess] = []

    def popen(argv: list[str], *, cwd: Path, **_options: Any) -> FakeProcess:
        started.append(FakeProcess(argv, Path(cwd)))
        return started[-1]

    app.preview.runner.popen = popen
    app.started = started
    monkeypatch.setattr(app, "_ask_target", lambda: tmp_path / "keyboard.ui")  # OS picker
    app.root.focus_force()
    _settle(app.root)
    yield app
    app.preview.dispose()


def test_h94_new_add_edit_save_preview_close_with_the_keyboard_only(
    keyboard: Any, tmp_path: Path
) -> None:
    app, session = keyboard, keyboard.session
    session.close_document()
    _settle(app.root)
    app.shell.palette.focus_first()
    _settle(app.root)
    # Ctrl+N: the template dialog takes the focus; Down picks a template, Enter creates it.
    _key(app, "<Control-n>")
    dialog = app._live_dialogs()[-1]
    assert str(_focused(app)).startswith(str(dialog.window))
    _key(app, "<Down>")
    _key(app, "<Return>")
    assert dialog.closed and session.document is not None and session.path is None
    # F6 to the palette, arrows to the Label item, Enter inserts it.
    for _step in range(4):
        if _panel_of(app) == 0:
            break
        _key(app, "<F6>")
    assert _panel_of(app) == 0
    tree, stack = app.shell.palette.tree, session.stack
    before = stack.index
    for _step in range(80):
        if tree.focus() == "w:Label":
            break
        _key(app, "<Down>")
    assert tree.focus() == "w:Label"
    _key(app, "<Return>")
    assert stack.index == before + 1
    added = session.selection.nodes[0]
    assert isinstance(added, Widget) and added.class_name == "Label"
    # Shift+F6 (wraps) to the inspector, Tab to the text editor, type, Enter commits.
    for _step in range(4):
        if _panel_of(app) == 3:
            break
        _key(app, "<Shift-F6>")
    assert _panel_of(app) == 3
    editor = app.shell.inspector._editors["prop:text"]
    for _step in range(60):
        if _focused(app) is editor.widget:
            break
        _key(app, "<Tab>")
    assert _focused(app) is editor.widget, "Tab never reached the Text editor"
    _key(app, "<Control-slash>")  # select all (Tk's Entry binding)
    _type(app, "Typed by keys")
    _key(app, "<Return>")
    assert added.props["text"].value == "Typed by keys"
    # Ctrl+S saves (the Save-as picker is the OS's: stubbed), F5 previews, Shift+F5 closes.
    _key(app, "<Control-s>")
    assert _saved(session) == (tmp_path / "keyboard.ui", False)  # a call: no stale narrowing
    assert "Typed by keys" in (tmp_path / "keyboard.ui").read_text(encoding="utf-8")
    _key(app, "<F5>")
    assert len(app.started) == 1 and app.preview.running
    _key(app, "<Shift-F5>")
    assert app.started[0].stdin.lines[-1:] == ["quit"]
    # File > Close (Ctrl+W) through the menu bar: Alt opens the menus, so use the accelerator.
    close = app.registry.get("file.close")
    assert close is not None and close.shortcut
    _key(app, tk_shortcut(close.shortcut, aqua=False).sequences[0])
    assert session.document is None


@pytest.mark.parametrize("start", [0, 2, 3])
def test_h94_tab_and_shift_tab_leave_every_panel_except_the_canvas(
    keyboard: Any, start: int
) -> None:
    """Tab from a panel's first widget eventually reaches another panel, Shift+Tab returns.
    The canvas keeps Tab for "select the next widget" by design: F6 is its exit."""
    app = keyboard
    app.shell.panels[start].focus_first()
    _settle(app.root)
    assert _panel_of(app) == start
    for sequence in ("<Tab>", "<Shift-Tab>"):
        app.shell.panels[start].focus_first()
        _settle(app.root)
        seen = []
        for _step in range(120):
            _key(app, sequence)
            seen.append(_panel_of(app))
            if seen[-1] not in (start, -1):
                break
        assert seen[-1] not in (start, -1), (sequence, seen[-10:])


def test_h94_f6_visits_the_four_panels_and_the_canvas_keeps_tab(keyboard: Any) -> None:
    app = keyboard
    app.shell.palette.focus_first()
    _settle(app.root)
    order = [_panel_of(app)]
    for _step in range(4):
        _key(app, "<F6>")
        order.append(_panel_of(app))
    assert order == [0, 1, 2, 3, 0]
    for _step in range(4):
        _key(app, "<Shift-F6>")
        order.append(_panel_of(app))
    assert order[-4:] == [3, 2, 1, 0]
    app.shell.canvas.focus_first()
    _settle(app.root)
    _key(app, "<Tab>")
    assert _panel_of(app) == 1  # Tab selects the next widget on the canvas


def _ctrl_tab(app: Any, stop: int, sequence: str) -> None:
    app.session.select(_first_label(app), origin="tree")  # the inspector has its tabs
    _settle(app.root)
    notebook = app.shell.side if stop == 2 else app.shell.inspector.notebook
    app.shell.panels[stop].focus_first()
    _settle(app.root)
    first = notebook.select()
    _key(app, sequence)
    assert notebook.select() != first and _panel_of(app) == stop


@pytest.mark.parametrize("stop", [2, 3])
def test_h94_ctrl_tab_switches_the_tab_of_the_side_and_the_inspector(
    keyboard: Any, stop: int
) -> None:
    _ctrl_tab(keyboard, stop, "<Control-Tab>")


@pytest.mark.parametrize("stop", [2, 3])
def test_h94_ctrl_shift_tab_switches_the_tab_back(keyboard: Any, stop: int) -> None:
    _ctrl_tab(keyboard, stop, "<Control-Shift-Tab>")


@pytest.mark.parametrize("name", ["about", "new file", "export", "shortcuts", "plugins",
                                  "rename", "save changes", "text editor", "message"])  # fmt: skip
def test_h94_escape_closes_every_dialog_and_gives_the_focus_back(keyboard: Any, name: str) -> None:
    app = keyboard
    app.shell.palette.focus_first()
    _settle(app.root)
    before = _focused(app)
    dialog = _open(app, name)
    assert str(_focused(app)).startswith(str(dialog.window)), _focused(app)
    _key(app, "<Escape>")
    assert dialog.closed and app._live_dialogs() == []
    if name not in ("save changes", "text editor"):  # those were opened from another panel
        assert _focused(app) is before
    else:
        assert str(_focused(app)).startswith(str(app.root.winfo_toplevel()))


def test_h94_tab_cycles_inside_a_dialog_and_never_escapes_to_the_main_window(
    keyboard: Any,
) -> None:
    app = keyboard
    dialog = _open(app, "export")
    seen = set()
    for _step in range(40):
        _key(app, "<Tab>")
        widget = _focused(app)
        assert str(widget).startswith(str(dialog.window)), widget
        seen.add(str(widget))
    assert len(seen) >= 3
    dialog.close()


def test_the_english_text_detector_sees_english(app: Any) -> None:
    """Negative control of ``_english``: the dialogs in en_GB are full of flagged texts."""
    english = _english("de_DE")
    for name in ("about", "export", "save changes"):
        dialog = _open(app, name)
        assert any(t in english for t in _static_texts(dialog.window).values()), name
        dialog.close()


# ------------------------------------------------------------------ H95 focus and contrast
SPECS: list[ThemeSpec] = [*load_theme_specs(), *load_theme_specs(brand=False)]
HC_SPECS = [s for s in SPECS if s.role == "high_contrast"]
#: The designer's own fields; the base styles are the user's (Rule S), QA-19f-T02.
_FIELD_STYLES = ("Designer.TEntry", "Designer.TCombobox", "Designer.TSpinbox")
_BASE_FIELDS = ("TEntry", "TCombobox", "TSpinbox")
_RING_STYLES = ("TButton", "Ghost.TButton", "TCheckbutton")


@pytest.fixture
def themed(designer_root: Any, request: pytest.FixtureRequest) -> Iterator[tuple[Any, ThemeSpec]]:
    """A designer in theme ``request.param`` (either family), with stock ttk widgets built
    under it (ttkbootstrap builds a style when the first widget of the class is made)."""
    from pyguibud.designer.app import DesignerApp

    spec: ThemeSpec = request.param
    family = tuple(s for s in SPECS if s.name.split("-")[0] == spec.name.split("-")[0])
    designer = DesignerApp(designer_root, specs=family, role=spec.role)
    holder = ttk.Frame(designer_root)
    for make in (ttk.Entry, ttk.Combobox, ttk.Spinbox, ttk.Button, ttk.Checkbutton, ttk.Treeview):
        make(holder)
    ttk.Entry(holder, style="Designer.TEntry")
    ttk.Spinbox(holder, style="Designer.TSpinbox")
    ttk.Button(holder, style="Ghost.TButton")
    try:
        yield designer, spec
    finally:
        holder.destroy()
        for dialog in designer._live_dialogs():
            dialog.close()
        designer.set_theme("light")
        designer.flush_theme()
        designer.dispose()
        reset_geometry(designer_root)


def _hex(widget: Any, colour: object) -> str:
    red, green, blue = widget.winfo_rgb(str(colour))
    return f"#{red >> 8:02X}{green >> 8:02X}{blue >> 8:02X}"


def _look(app: Any, style: str, option: str, state: str) -> str:
    value = ttk.Style().lookup(style, option, [state])
    return _hex(app.root, value) if value else ""


@pytest.mark.parametrize("themed", SPECS, ids=lambda s: s.name, indirect=True)
def test_h95_the_inspector_fields_take_the_theme_focus_colour(
    themed: tuple[Any, ThemeSpec],
) -> None:
    """QA-19f-T02, the designer-owned part, and QA-19f-T04: the editors' and the dialog lists'
    focus edge is the ring token, 3:1 on the field and on the window."""
    from pyguibud.designer.theme import design_tokens
    from pyguibud.designer.theme_tk import LIST_STYLE

    app, spec = themed
    ring = _hex(app.root, design_tokens(spec).ring)
    for style in (*_FIELD_STYLES, LIST_STYLE):
        for option in ("bordercolor", "lightcolor", "darkcolor"):
            assert _look(app, style, option, "focus") == ring, (style, option)
    for under in ("inputbg", "bg"):
        assert contrast(ring, spec.colors[under]) >= NON_TEXT_CONTRAST, under
    # Otherwise a designer field looks like the base field (the editors' read-only fill aside).
    looks = ttk.Style()
    for base in _BASE_FIELDS:
        for option in ("font", "padding", "borderwidth", "foreground", "fieldbackground",
                       "background", "bordercolor", "lightcolor", "darkcolor", "insertcolor",
                       "arrowcolor", "arrowsize"):  # fmt: skip
            for state in ("!focus", "disabled", "invalid"):
                look = looks.lookup(f"Designer.{base}", option, [state])
                assert look == looks.lookup(base, option, [state]), (base, option, state)


@pytest.mark.parametrize("themed", SPECS, ids=lambda s: s.name, indirect=True)
def test_h95_a_focused_field_has_a_thicker_border_that_clears_3_to_1(
    themed: tuple[Any, ThemeSpec],
) -> None:
    app, spec = themed
    colours = spec.colors
    for style in _FIELD_STYLES:
        focus = _look(app, style, "bordercolor", "focus")
        idle = _look(app, style, "bordercolor", "!focus")
        field = _look(app, style, "fieldbackground", "focus") or colours["inputbg"]
        # More than a colour change: the inner edge takes the focus colour too (1 px -> 2 px).
        assert _look(app, style, "lightcolor", "focus") == focus != idle, style
        assert _look(app, style, "lightcolor", "!focus") != idle, style
        assert contrast(focus, field) >= NON_TEXT_CONTRAST, (style, focus, field)
        assert contrast(focus, colours["bg"]) >= NON_TEXT_CONTRAST, (style, focus)


def _elements(layout: Any) -> Iterator[str]:
    for name, options in layout:
        yield name
        yield from _elements(options.get("children", []))


@pytest.mark.parametrize("themed", SPECS, ids=lambda s: s.name, indirect=True)
def test_h95_buttons_and_checkbuttons_draw_a_focus_ring_that_clears_3_to_1(
    themed: tuple[Any, ThemeSpec],
) -> None:
    app, _spec = themed
    style = ttk.Style()
    for name in _RING_STYLES:
        assert any(e.endswith(".focus") for e in _elements(style.layout(name))), name
        assert int(style.lookup(name, "focusthickness") or 0) >= 1, name
        ring = _look(app, name, "focuscolor", "focus")
        under = _look(app, name, "background", "focus")
        assert contrast(ring, under) >= NON_TEXT_CONTRAST, (name, ring, under)


def _own_focus(widget: Any) -> bool:
    """Whether ``widget``'s style itself changes on focus (a ring element or a state map)."""
    style = ttk.Style()
    try:
        name = str(widget.cget("style")) or widget.winfo_class()
        layout = style.layout(name)
    except tkinter.TclError:
        return False
    items = style.layout("Item") if widget.winfo_class() == "Treeview" else []
    if any(e.endswith(".focus") for e in (*_elements(layout), *_elements(items))):
        return True
    return any(
        style.lookup(name, o, ["focus"]) != style.lookup(name, o, ["!focus"])
        for o in ("bordercolor", "lightcolor", "darkcolor", "focuscolor", "background")
    )


_LIST_DIALOGS = {"new file": "list", "plugins": "tree", "recovery": "tree"}


@pytest.mark.parametrize("themed", HC_SPECS[:1], ids=lambda s: s.name, indirect=True)
@pytest.mark.parametrize("name", sorted(_LIST_DIALOGS))
def test_h95_a_focused_list_in_a_dialog_shows_the_focus(
    themed: tuple[Any, ThemeSpec], name: str
) -> None:
    app, _spec = themed
    dialog = _open(app, name)
    tree = getattr(dialog, _LIST_DIALOGS[name])
    tree.focus_force()
    _settle(app.root)
    shown = _own_focus(tree)
    dialog.close()
    assert shown


def _panel_ring(app: Any, widget: Any) -> bool:
    """Whether ``widget`` sits in the panel that now shows the thick focus ring."""
    index = app.shell._panel_index_of(widget)
    if index < 0 or app.shell.active_panel != index:
        return False
    frame = app.shell.panels[index].frame
    return bool(int(frame.cget("highlightthickness")) > frame._thin)


@pytest.mark.parametrize("themed", HC_SPECS, ids=lambda s: s.name, indirect=True)
def test_h95_every_tab_stop_of_the_main_window_shows_the_focus(
    themed: tuple[Any, ThemeSpec], tmp_path: Path
) -> None:
    app, _spec = themed
    shutil.copy(HELLO, tmp_path / "hello.ui")
    assert app.open_path(tmp_path / "hello.ui")
    app.session.select(_first_label(app), origin="tree")  # the inspector shows its editors
    app.root.deiconify()
    app.root.geometry("1400x800+0+0")
    _settle(app.root)
    widget = app.shell.palette.tree
    seen: list[str] = []
    hidden: list[str] = []
    for _step in range(300):
        widget.focus_force()
        _settle(app.root)
        if str(widget) in seen:
            break
        seen.append(str(widget))
        if not (_panel_ring(app, widget) or _own_focus(widget)):
            hidden.append(f"{widget.winfo_class()} {widget}")
        widget = widget.tk_focusNext()
    assert len(seen) >= 10, seen  # toolbar, palette, canvas, tree, inspector editors
    assert hidden == []


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_h95_ring_and_control_border_clear_3_to_1_on_the_list_rows_too(spec: ThemeSpec) -> None:
    """Pairs the 14p token table leaves out: the 2 px panel ring also borders the list rows
    (inputbg) of the palette, tree and inspector, and a field's border sits on inputbg."""
    from pyguibud.designer.theme import design_tokens

    colours, tokens = spec.colors, design_tokens(spec)
    assert contrast(tokens.ring, colours["inputbg"]) >= NON_TEXT_CONTRAST
    assert contrast(colours["border"], colours["inputbg"]) >= NON_TEXT_CONTRAST


def test_the_fit_detector_sees_a_window_too_large(app: Any) -> None:
    """Negative control of ``_off_screen``: the About box does not fit a 200 x 100 area."""
    dialog = _open(app, "about")
    assert _off_screen(dialog, (200, 100))
    dialog.close()


def _plain_focus(widget: Any) -> bool:
    """A plain Tk widget (Text, Canvas): a highlight ring that changes colour on focus, or the
    insertion caret of an editable text."""
    try:
        ring = int(widget.cget("highlightthickness")) > 0 and str(
            widget.cget("highlightcolor")
        ) != str(widget.cget("highlightbackground"))
        caret = (
            widget.winfo_class() == "Text"
            and str(widget.cget("state")) == "normal"
            and int(widget.cget("insertwidth")) > 0
        )
    except tkinter.TclError:
        return False
    return bool(ring or caret)


@pytest.mark.parametrize("themed", HC_SPECS, ids=lambda s: s.name, indirect=True)
def test_h95_every_tab_stop_of_every_dialog_shows_the_focus(
    themed: tuple[Any, ThemeSpec], tmp_path: Path
) -> None:
    """Tab stops of each dialog, in the high-contrast themes (lists: QA-19f-T04, T05)."""
    app, _spec = themed
    shutil.copy(HELLO, tmp_path / "hello.ui")
    assert app.open_path(tmp_path / "hello.ui")
    hidden: list[str] = []
    for name in sorted(DIALOGS):
        dialog = _open(app, name)
        widget, seen = dialog.initial_focus(), []
        for _step in range(80):
            widget.focus_force()
            _settle(app.root)
            if str(widget) in seen or not str(widget).startswith(str(dialog.window)):
                break
            seen.append(str(widget))
            if not (_own_focus(widget) or _plain_focus(widget)):
                hidden.append(f"{name}: {widget.winfo_class()} {widget}")
            widget = widget.tk_focusNext()
        dialog.close()
        _settle(app.root)
    assert hidden == []


@pytest.mark.parametrize("themed", HC_SPECS[:1], ids=lambda s: s.name, indirect=True)
def test_h95_the_plugin_details_box_shows_the_focus(themed: tuple[Any, ThemeSpec]) -> None:
    app, _spec = themed
    dialog: Any = _open(app, "plugins")
    details = dialog.details
    details.focus_force()
    _settle(app.root)
    values = {o: str(details.cget(o)) for o in
              ("highlightthickness", "highlightcolor", "highlightbackground", "state")}  # fmt: skip
    shown = _plain_focus(details)
    dialog.close()
    assert shown, values


def test_h95_the_plugin_details_box_scrolls_with_the_keyboard(keyboard: Any) -> None:
    """QA-19f-T05: the details box stays a Tab stop because keyboard users need to scroll it."""
    app = keyboard
    dialog: Any = _open(app, "plugins")
    details = dialog.details
    details.configure(state="normal")
    details.insert("1.0", "".join(f"line {n}\n" for n in range(200)))
    details.configure(state="disabled")
    details.focus_force()
    _settle(app.root)
    _key(app, "<Next>")
    paged = details.yview()[0]
    for _step in range(30):
        _key(app, "<Down>")
    lined = details.yview()[0]
    _key(app, "<Control-Home>")
    top = details.yview()[0]
    dialog.close()
    assert 0 < paged < lined and top == 0


def test_h95_an_open_dialog_takes_the_new_focus_colour_on_a_theme_switch(app: Any) -> None:
    from pyguibud.designer.theme import design_tokens, spec_for_role

    dialog: Any = _open(app, "plugins")
    try:
        for role in ("dark", "high_contrast", "light"):
            app.set_theme(role)
            app.flush_theme()
            spec = spec_for_role(app.specs, role)
            assert spec is not None
            ring = design_tokens(spec).ring
            assert _hex(app.root, dialog.details.cget("highlightcolor")) == ring.upper(), role
    finally:
        dialog.close()


def test_h95_no_designer_field_uses_a_base_field_style(app: Any, tmp_path: Path) -> None:
    """QA-19f-T02: dialog and panel fields take the Designer.* styles (focus ring = ring token);
    the base styles stay the user's (Rule S). The canvas holds the user's widgets: skipped."""
    shutil.copy(HELLO, tmp_path / "hello.ui")
    assert app.open_path(tmp_path / "hello.ui")
    app.session.select(_first_label(app), origin="tree")
    _settle(app.root)

    def base_fields(widget: Any) -> Iterator[str]:
        if widget is app.shell.canvas.frame:
            return
        if str(widget.winfo_class()) in _BASE_FIELDS and not str(widget.cget("style")):
            yield f"{widget.winfo_class()} {widget}"
        for child in widget.winfo_children():
            yield from base_fields(child)

    found = list(base_fields(app.root))
    for name in sorted(DIALOGS):
        dialog = _open(app, name)
        found += [f"{name}: {f}" for f in base_fields(dialog.window)]
        dialog.close()
        _settle(app.root)
    assert found == []
