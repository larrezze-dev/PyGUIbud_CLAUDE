"""QA abuse tests of Step 18 that drive the designer: live language switching with dialogs open,
the live menu bar's access keys, translated texts at the minimum window size and a corrupt
catalogue. Kept out of ``tests/qa`` because a designer session root there breaks
``tests/runtime`` (16c note). The pure cases are in ``tests/qa/test_step18_abuse.py``.

Strict ``xfail`` marks the open findings QA-18-NN; the debugger removes the mark with the fix.
"""

from __future__ import annotations

import contextlib
import datetime
import gettext
import re
import shutil
import tkinter
from collections.abc import Callable, Iterator
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest

import pyguibud_runtime._texts as runtime_texts
from pyguibud import i18n
from pyguibud.designer.theme_tk import underline_of
from tests.conftest import reset_geometry

pytestmark = pytest.mark.gui

ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"
ACME = ROOT / "examples" / "acme_demo.ui"
ALL_LANGUAGES = (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE)
#: Key names stay English in this step (accelerator names are deferred by the user).
_KEYS = re.compile(
    r"^(?:(?:Ctrl|Shift|Alt|Delete|Enter|Escape|Tab|Up|Down|Left|Right|PageUp|PageDown|Home|End"
    r"|Insert|F\d{1,2}|[A-Z0-9])(?:\+|, )?)+$"
)
_TEXT_CLASSES = {
    "TLabel", "Label", "TButton", "Button", "TCheckbutton", "Checkbutton", "TRadiobutton",
    "Radiobutton", "TLabelframe", "Labelframe", "TMenubutton",
}  # fmt: skip


@contextlib.contextmanager
def _designer(root: Any, path: Path, registry: Any = None) -> Iterator[Any]:
    """A designer on the shared root, mapped at its minimum size with ``path`` open."""
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.session import DesignerSession
    from pyguibud.designer.settings import Settings

    session = DesignerSession(registry) if registry is not None else None
    designer = DesignerApp(root, session, settings=Settings())
    assert designer.open_path(path)
    root.update_idletasks()
    root.deiconify()
    width, height = root.minsize()
    root.geometry(f"{width}x{height}+0+0")
    _settle(root)
    assert root.winfo_width() > 1  # really mapped: the measures below mean something
    try:
        yield designer
    finally:
        for dialog in designer._live_dialogs():
            dialog.close()
        designer.set_theme("light")
        designer.flush_theme()
        designer.dispose()
        reset_geometry(root)  # resized while mapped: a withdrawn root may ignore it (H01)


@pytest.fixture
def app(designer_root: Any) -> Iterator[Any]:
    with _designer(designer_root, HELLO) as designer:
        yield designer


@pytest.fixture
def acme_app(designer_root: Any) -> Iterator[Any]:
    """acme_demo.ui: tb: widgets plus a missing plugin (a finding and a status-bar note)."""
    with _designer(designer_root, ACME) as designer:
        yield designer


def _settle(root: Any) -> None:
    root.update()
    root.update_idletasks()


def _switch(app: Any, *codes: str) -> None:
    for code in codes:
        app.set_language(code)
        _settle(app.root)


def _texts(widget: Any, skip: tuple[Any, ...] = ()) -> list[tuple[str, str]]:
    """Static texts (labels, buttons, headings, tabs, titles), never user values or rows."""
    found: list[tuple[str, str]] = []
    for child in widget.winfo_children():
        if child in skip or isinstance(child, tkinter.Menu):
            continue
        cls = child.winfo_class()
        if cls in _TEXT_CLASSES:
            text = str(child.cget("text"))
            if text:
                found.append((cls, text))
        if isinstance(child, ttk.Treeview):
            found += [("Heading", child.heading(c, "text")) for c in ("#0", *child["columns"])]
        if isinstance(child, ttk.Notebook):
            notebook: Any = child  # ttk.Notebook.tab/tabs are untyped in typeshed
            found += [("Tab", str(notebook.tab(t, "text"))) for t in notebook.tabs()]
        if isinstance(child, tkinter.Toplevel):
            found.append(("Title", child.title()))
        found += _texts(child, skip)
    return [(cls, text) for cls, text in found if text]


def _not_pseudo(texts: list[tuple[str, str]], allowed: set[str]) -> list[tuple[str, str]]:
    """Texts that are not pseudo-localised: stale English after the switch to en_XA."""
    return sorted(
        {
            (cls, text)
            for cls, text in texts
            if "[" not in text
            and re.search(r"[A-Za-z]{2}", text)
            and not _KEYS.match(text)
            and text not in allowed
        }
    )


def _document_tokens(app: Any) -> set[str]:
    """Ids and class names of the open document: data, never translated."""
    tokens = {"PyGUIbud"}
    for node in app.session.document.walk():
        for name in ("id", "cls", "class_name"):
            value = getattr(node, name, None)
            if isinstance(value, str):
                tokens |= {value, value.split(":")[-1]}
    return tokens


# ------------------------------------------------------------------ live switching
def test_the_designer_helper_gives_the_shared_root_back_its_size(designer_root: Any) -> None:
    """Regression: ``_designer`` withdrew the root at the 800 x 500 minimum and then re-applied
    a stale geometry, which a withdrawn window ignores (a moved sash also made the root request
    the minimum), so every later designer on the shared root had a ~114 px wide canvas: 6
    order-dependent failures in test_reachable and test_resize_gui after Step 18."""

    def size_of_a_plain_designer() -> tuple[int, int]:
        from pyguibud.designer.app import DesignerApp
        from pyguibud.designer.settings import Settings

        designer = DesignerApp(designer_root, settings=Settings())
        try:
            assert designer.open_path(HELLO)
            _settle(designer_root)
            return designer_root.winfo_width(), designer_root.winfo_height()
        finally:
            designer.set_theme("light")
            designer.flush_theme()
            designer.dispose()

    reset_geometry(designer_root)  # a known start, whatever the previous test left
    before = size_of_a_plain_designer()
    with _designer(designer_root, HELLO) as app:
        _switch(app, "fr_FR", "en_GB")  # the wider palette moves a sash at the minimum size
    assert size_of_a_plain_designer() == before


@pytest.mark.parametrize("document", ["hello", "acme"])
def test_every_switch_leaves_no_stale_english_in_the_main_window(
    request: pytest.FixtureRequest, document: str
) -> None:
    app = request.getfixturevalue("app" if document == "hello" else "acme_app")
    for _round in range(3):
        _switch(app, *ALL_LANGUAGES)
    _switch(app, "de_DE", "en_XA")
    texts = _texts(app.root, skip=(app.shell.canvas.frame,))  # the canvas shows the document
    assert _not_pseudo(texts, _document_tokens(app)) == []
    menus = []
    for menu in (app.shell.menubar, app.shell.tree_menu):
        menus += [label for _path, label, _key in _menu_entries(menu)]
    data = set(i18n.LANGUAGES.values())  # autonyms, recent files, toolkit and theme names
    assert [
        label
        for label in menus
        if "[" not in label and label not in data and not re.match(r"^\d+ |^[\w-]+$", label)
    ] == []


def _recovery(app: Any) -> None:
    from pyguibud.designer.recovery import RecoveryEntry

    now = datetime.datetime.now(datetime.timezone.utc)
    app.open_recovery([RecoveryEntry(ROOT, str(ROOT / "lost.ui"), "lost.ui", now)])


_OPENERS: dict[str, Callable[[Any], None]] = {
    "keyboard shortcuts": lambda app: app.open_shortcuts(),
    "plugins": lambda app: app.open_plugins(),
    "new from template": lambda app: app.open_new_file(),
    "recovery": _recovery,
    "export": lambda app: app.exporter.start(),
}


@pytest.mark.parametrize("name", sorted(_OPENERS))
def test_an_open_dialog_follows_every_switch(app: Any, name: str) -> None:
    _OPENERS[name](app)
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    _switch(app, *ALL_LANGUAGES, *ALL_LANGUAGES, "fr_FR", "en_XA")
    allowed = {"Ui_Main", "lost.ui", "pyguibud"}
    assert _not_pseudo([*_texts(dialog.window), ("Title", dialog.window.title())], allowed) == []
    assert len(i18n._listeners) == 1  # the app's single listener; dialogs never leak theirs
    dialog.close()


def test_forty_switches_leak_no_listener_and_no_timer(app: Any) -> None:
    _switch(app, *ALL_LANGUAGES)
    before = set(app.root.tk.splitlist(app.root.tk.call("after", "info")))
    for _round in range(5):
        _switch(app, *ALL_LANGUAGES)
    after = set(app.root.tk.splitlist(app.root.tk.call("after", "info")))
    assert len(i18n._listeners) == 1
    assert len(after - before) <= 1


def test_the_empty_canvas_note_is_retranslated_without_a_document(app: Any) -> None:
    app.session.close_document()
    _settle(app.root)
    _switch(app, "de_DE", "en_XA")
    assert str(app.shell.canvas.empty.cget("text")).startswith("[")


def test_qa18_10_pseudo_locale_keeps_the_key_names_of_the_empty_canvas_note(app: Any) -> None:
    app.session.close_document()
    _settle(app.root)
    _switch(app, "en_XA")
    note = str(app.shell.canvas.empty.cget("text"))
    assert "Ctrl+N" in note and "Ctrl+O" in note, note
    _switch(app, "en_GB")
    expected = "No document. Press Ctrl+N for a new one or Ctrl+O to open a file."
    assert str(app.shell.canvas.empty.cget("text")) == expected  # en-GB unchanged


# ------------------------------------------------------------------ access keys
def _menu_entries(menu: Any, path: str = "") -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    refill = str(menu.cget("postcommand"))
    if refill:  # a menu filled when it opens (Preview > Theme): open it as the user would
        menu.tk.eval(refill)
    last = menu.index("end")
    if last is None:
        return entries
    for index in range(last + 1):
        kind = menu.type(index)
        if kind in ("separator", "tearoff"):
            continue
        label = str(menu.entrycget(index, "label"))
        underline = underline_of(menu.entrycget(index, "underline"))
        key = label[underline].casefold() if 0 <= underline < len(label) else ""
        entries.append((path, label, key))
        if kind == "cascade":
            entries += _menu_entries(
                menu.nametowidget(menu.entrycget(index, "menu")), f"{path}/{label}"
            )
    return entries


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_qa18_08_each_live_menu_has_unique_access_keys(app: Any, lang: str) -> None:
    """de_DE File: _Speichern / _Schließen (S); it_IT File: _Nuovo da modello / Salva con _nome."""
    _switch(app, lang)
    by_menu: dict[str, list[str]] = {}
    for path, _label, key in _menu_entries(app.shell.menubar):
        if key:
            by_menu.setdefault(path, []).append(key)
    duplicated = {path: keys for path, keys in by_menu.items() if len(keys) != len(set(keys))}
    assert duplicated == {}


# ------------------------------------------------------------------ room for the texts
def _palette_tree(app: Any) -> ttk.Treeview:
    stack = [app.shell.palette.frame]
    while stack:
        widget = stack.pop()
        if isinstance(widget, ttk.Treeview):
            return widget
        stack.extend(widget.winfo_children())
    raise AssertionError("no palette tree")


def test_qa18_05_palette_names_fit_at_the_minimum_size(app: Any) -> None:
    tree = _palette_tree(app)
    style = ttk.Style()
    indent = int(style.lookup("Treeview", "indent") or 20)
    font = tkfont.nametofont(str(style.lookup("Treeview", "font") or "TkDefaultFont"))
    cut: list[tuple[str, str]] = []
    for code in ALL_LANGUAGES:
        _switch(app, code)
        width = tree.winfo_width()
        assert width > 50
        for category in tree.get_children(""):
            for item in tree.get_children(category):
                image = tree.item(item, "image")
                icon = int(app.root.tk.call("image", "width", image[0])) if image else 0
                text = str(tree.item(item, "text"))
                if 2 * indent + icon - 4 + font.measure(text) > width:
                    cut.append((code, text))
    assert cut == []


@pytest.mark.parametrize("lang", ["fr_FR", "en_XA"])
def test_the_palette_fits_when_the_designer_starts_in_a_long_language(
    designer_root: Any, lang: str
) -> None:
    """A saved language never switches: the first render alone must size the palette."""
    i18n.set_language(lang)  # what launch() does before the window exists
    with _designer(designer_root, HELLO) as started:
        palette = started.shell.palette
        assert palette._fit > 0  # measured at the first render, not left at 0
        assert palette.frame.winfo_width() >= palette.fit_width() - 1


def test_a_huge_palette_need_is_capped_and_every_panel_stays_visible(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A plugin with an absurdly long name may not push the canvas and the inspector away."""
    from pyguibud.designer.shell import _PALETTE_SHARE

    shell = app.shell
    monkeypatch.setattr(shell.palette, "fit_width", lambda: 5000)
    shell.clamp_sashes()
    _settle(app.root)
    body = shell.body.winfo_width()
    assert shell.palette.frame.winfo_width() <= int(body * _PALETTE_SHARE) + 1
    for pane in shell._panes(shell.body):
        assert pane.winfo_width() >= shell._minimum(pane, True) - 1, pane


@pytest.mark.parametrize("lang", ["en_XA", "fr_FR", "de_DE"])
def test_every_panel_keeps_its_minimum_at_the_minimum_size(app: Any, lang: str) -> None:
    _switch(app, lang)
    shell = app.shell
    for pane in shell._panes(shell.body):
        assert pane.winfo_width() >= shell._minimum(pane, True) - 1, (lang, pane)
    # D5 (19f): the palette may give way below its fit width (names elide), never below this.
    assert shell.palette.frame.winfo_width() >= shell.palette.floor_width() - 1


def test_qa18_09_cheat_sheet_fits_a_full_hd_screen(app: Any) -> None:
    app.open_shortcuts()
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    _switch(app, "de_DE")
    dialog.window.update_idletasks()
    room = min(dialog.window.winfo_screenheight(), 1080) - 48  # minus a taskbar
    if dialog.rows.winfo_reqheight() <= room:  # the rows uncapped (19f: the dialog scrolls)
        pytest.skip("this display's fonts make the sheet short enough; QA-18-09 not visible")
    assert dialog.window.winfo_reqheight() <= room


# ------------------------------------------------------------------ corrupt catalogue
@pytest.fixture
def corrupt_de(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy = tmp_path / "locale"
    shutil.copytree(i18n.LOCALE_DIR, copy)
    mo = copy / "de_DE" / "LC_MESSAGES" / "pyguibud.mo"
    mo.write_bytes(mo.read_bytes()[:500])
    monkeypatch.setattr(i18n, "LOCALE_DIR", copy)
    monkeypatch.setattr(runtime_texts, "LOCALE_DIR", copy)
    monkeypatch.setattr(gettext, "_translations", {})
    return copy


def test_qa18_01_menu_switch_to_a_corrupt_catalogue_is_refused_gracefully(
    app: Any, corrupt_de: Path
) -> None:
    shown: list[str] = []
    app.message.connect(shown.append)
    app.set_language("de_DE")
    _settle(app.root)
    assert i18n.get_language() in ("en_GB", "de_DE")
    assert i18n._("_Open…") == "_Open…"  # English, never a half-loaded catalogue
    assert shown  # the user is told why the language did not change
    assert shown[-1] == i18n.catalogue_problem()
    assert app.settings.language != "de_DE"  # never remembered for the next start


def test_a_damaged_start_language_is_reported_on_the_status_line(
    designer_root: Any, corrupt_de: Path
) -> None:
    """launch() sets the saved language before the window exists; start() then reports it."""
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings

    i18n.set_language("de_DE")  # what launch() does with a saved (or --lang) language
    designer = DesignerApp(designer_root, settings=Settings())
    try:
        shown: list[str] = []
        designer.message.connect(shown.append)
        designer.start()
        _settle(designer.root)
        assert i18n.catalogue_problem() in shown
    finally:
        designer.dispose()


# ------------------------------------------------------------------ Plugins dialog statuses
@pytest.mark.parametrize("lang", ["de_DE", "nl_NL", "fr_FR", "pt_PT", "en_XA"])
def test_every_plugin_status_fits_its_column(designer_root: Any, lang: str) -> None:
    from tests.designer.test_plugins_17c import _all_statuses

    with _designer(designer_root, HELLO, _all_statuses()) as app:
        app.open_plugins()
        _settle(app.root)
        dialog = app._live_dialogs()[-1]
        _switch(app, *ALL_LANGUAGES, lang)
        dialog.window.update_idletasks()
        tree = dialog.tree
        font = tkfont.nametofont(str(ttk.Style().lookup("Treeview", "font") or "TkDefaultFont"))
        width = int(tree.column("status", "width"))
        statuses = [str(tree.item(row, "values")[1]) for row in tree.get_children("")]
        assert len(statuses) == 5
        assert [s for s in statuses if font.measure(s) > width] == []
        assert all("[" in s for s in statuses) if lang == "en_XA" else True


# ------------------------------------------------------------------ pass 2: object tree room
def _object_tree_cut(app: Any) -> set[str]:
    """Object-tree rows whose text is wider than the name column (#0)."""
    stack: list[Any] = [app.shell.tree.frame]
    tree: Any = None
    while stack and tree is None:
        widget = stack.pop()
        if isinstance(widget, ttk.Treeview):
            tree = widget
        stack.extend(widget.winfo_children())
    assert tree is not None
    style = ttk.Style()
    indent = int(style.lookup("Treeview", "indent") or 20)
    font = tkfont.nametofont(str(style.lookup("Treeview", "font") or "TkDefaultFont"))
    width = int(tree.column("#0", "width"))
    cut: set[str] = set()

    def walk(item: str, depth: int) -> None:
        for child in tree.get_children(item):
            image = tree.item(child, "image")
            icon = int(app.root.tk.call("image", "width", image[0])) if image else 0
            text = str(tree.item(child, "text"))
            if indent * (depth + 1) + icon + font.measure(text) > width:
                cut.add(text)
            walk(child, depth + 1)

    walk("", 0)
    return cut


@pytest.mark.parametrize("lang", ["fr_FR", "de_DE", "pt_PT"])
def test_qa18_16_object_tree_names_that_fit_in_english_fit_in_every_language(
    app: Any, lang: str
) -> None:
    _switch(app, "en_GB")
    english_cut = _object_tree_cut(app)
    _switch(app, lang)
    newly_cut = {text for text in _object_tree_cut(app) - english_cut if "(" in text}
    if not newly_cut and not english_cut and app.shell.palette.fit_width() < 200:
        pytest.skip("this display's fonts leave room; QA-18-16 not visible")
    assert newly_cut == set()
