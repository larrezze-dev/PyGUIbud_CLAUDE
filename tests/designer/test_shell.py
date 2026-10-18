"""The shell and the panels on the shared root: menus, live theme/language, selection sync."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import read_ui, read_ui_string
from pyguibud.designer.app import DesignerApp

pytestmark = pytest.mark.gui

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TWO_WINDOWS = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
    '<window id="one" kind="main"><layout type="grid"/>'
    '<widget class="Label" id="lbl"><cell row="0" column="0"/></widget></window>'
    '<window id="two" kind="dialog"><layout type="grid"/></window></pyguibud-ui>'
)
BROKEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
    '<window id="main" kind="main"><layout type="grid"/>'
    '<widget class="Nope" id="w"/></window></pyguibud-ui>'
)


def _labels(menu: Any) -> list[str]:
    last = menu.index("end")
    if last is None:
        return []
    return [menu.entrycget(i, "label") for i in range(last + 1) if menu.type(i) != "separator"]


def _submenu(menu: Any, label: str) -> Any:
    for index in range((menu.index("end") or 0) + 1):
        if menu.type(index) == "cascade" and menu.entrycget(index, "label") == label:
            return menu.nametowidget(menu.entrycget(index, "menu"))
    raise AssertionError(f"no menu called {label!r}")


def _open_hello(shell: DesignerApp) -> None:
    shell.session.open_result(read_ui(EXAMPLES / "hello.ui"), name="hello")


def test_shell_has_menus_toolbar_four_panels_and_status_bar(shell: DesignerApp) -> None:
    bar = shell.shell.menubar
    assert _labels(bar) == ["File", "Edit", "Document", "Preview", "View", "Help"]
    assert _labels(_submenu(bar, "File")) == [
        "New from template…", "Open…", "Open recent", "Recover…", "Save", "Save as…",
        "Export Python code…", "Close", "Quit",
    ]  # fmt: skip
    assert _labels(_submenu(_submenu(bar, "View"), "Theme")) == ["Light", "Dark", "High contrast"]
    languages = _labels(_submenu(_submenu(bar, "View"), "Language"))
    assert len(languages) == 8  # the pseudo-locale is hidden (QA-12-12)
    assert languages[0] == "English (United Kingdom)"
    assert "Pseudo-locale (layout test)" not in languages
    assert [p.name for p in shell.shell.panels] == ["palette", "canvas", "tree", "inspector"]
    assert shell.shell.toolbar.winfo_children()


def test_nothing_unimplemented_in_the_menus(shell: DesignerApp) -> None:
    ids = {action.id for action in shell.registry.actions()}
    assert "help.about" in ids  # Step 19e: the author credit (CLAUDE.md)
    assert {"file.open", "file.save", "file.save_as", "file.close", "file.quit"} <= ids
    assert {"edit.cut", "edit.paste", "edit.insert.menu", "document.rename"} <= ids  # 14a.2


def test_theme_radio_follows_the_live_theme(shell: DesignerApp) -> None:
    shell.registry.invoke("view.theme.dark")
    shell.flush_theme()
    assert shell.role == "dark"
    shell.shell.refresh_states()
    assert shell.shell._radio["view.theme"].get() == "view.theme.dark"
    shell.registry.invoke("view.theme.high_contrast")
    shell.flush_theme()
    assert shell.shell._radio["view.theme"].get() == "view.theme.high_contrast"


def test_language_switch_retranslates_everything(shell: DesignerApp) -> None:
    _open_hello(shell)
    shell.set_language("en_XA")  # as ``--lang en_XA`` would, though the menu does not list it
    assert i18n.get_language() == "en_XA"
    assert shell.root.title() == shell.session.title  # the file name, never translated
    assert _labels(shell.shell.menubar)[0].startswith("[")
    assert shell.shell.palette.heading.cget("text").startswith("[")
    assert shell.shell.inspector.heading.cget("text").startswith("[")
    tree = shell.shell.tree.tree
    assert tree is not None
    assert tree.item(tree.get_children()[0], "text").startswith("[") is False  # user ids verbatim
    assert shell.shell._summary.cget("text").startswith("[")
    first_button = shell.shell.toolbar.winfo_children()[0]
    assert first_button.cget("text").startswith("[")
    shell.registry.invoke("view.language.en_GB")
    assert shell.root.title() == "hello — PyGUIbud"
    assert _labels(shell.shell.menubar) == ["File", "Edit", "Document", "Preview", "View", "Help"]
    assert shell.shell._radio["view.language"].get() == "view.language.en_GB"


def test_a_failing_panel_does_not_block_the_others(
    shell: DesignerApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(shell.shell.tree, "retranslate", broken)
    i18n.set_language("en_XA")
    assert shell.shell.inspector.heading.cget("text").startswith("[")
    assert shell.root.title().startswith("[")


def test_palette_lists_categories_and_widgets(shell: DesignerApp) -> None:
    tree = shell.shell.palette.tree
    assert tree is not None
    categories = tree.get_children()
    assert categories
    assert any(tree.get_children(c) for c in categories)
    assert "w:Button" in {i for c in categories for i in tree.get_children(c)}


def test_new_document_fills_tree_canvas_and_inspector(shell: DesignerApp) -> None:
    shell.new_from_template("main_window")
    panels = shell.shell
    assert panels.tree.tree is not None
    assert len(panels.canvas.notebook.tabs()) == 1
    window = shell.session.document.children[0]  # type: ignore[union-attr]
    assert shell.session.selection.node is window
    assert panels.tree.tree.selection() == (panels.tree.key_of(window),)
    panels.inspector.frame.update()
    assert panels.inspector.value_of("field:id") == getattr(window, "id", None)  # the window's form
    assert "window[main]" in panels.statusbar.winfo_children()[0].cget("text")
    assert panels.statusbar.winfo_children()[1].cget("text") == "No problems found"


def test_selection_sync_tree_to_canvas_and_inspector(shell: DesignerApp) -> None:
    _open_hello(shell)
    panels = shell.shell
    document = shell.session.document
    assert document is not None
    entry = next(n for n in document.walk() if getattr(n, "id", "") == "ent_name")
    tree = panels.tree.tree
    assert tree is not None
    key = panels.tree.key_of(entry)
    assert key is not None
    tree.selection_set(key)  # what a click does
    tree.update()
    assert shell.session.selection.node is entry
    assert shell.session.selection.origin == "tree"
    stage = panels.canvas.stage_of(document.children[0])
    assert stage is not None and stage.view is not None
    stage.stage.update_idletasks()
    outline = stage.overlay.selection.shown()
    assert outline  # the canvas outlines the entry selected in the tree
    widget = stage.view.outer[id(entry)]
    # real positions (not place_info): the stage's padding must not shift the outline
    left = min(s.winfo_rootx() for s in outline)
    top = min(s.winfo_rooty() for s in outline)
    assert 0 < widget.winfo_rootx() - left <= 4 and 0 < widget.winfo_rooty() - top <= 4
    tree.update()
    assert panels.inspector.value_of("field:id") == "ent_name"


def test_selection_sync_canvas_tab_selects_the_window(shell: DesignerApp) -> None:
    shell.session.open_result(read_ui_string(TWO_WINDOWS, source="two"), name="two")
    document = shell.session.document
    assert document is not None
    first, second = document.children
    canvas = shell.shell.canvas
    canvas.notebook.update()
    # opening a document is not a click of the user
    assert shell.session.selection.node is None
    # a click on the second tab (not made by our own code) selects that window
    canvas.notebook.select(canvas.stages[1].page)
    canvas.notebook.update()
    selection: Any = shell.session.selection  # mypy would narrow `.node` to None above
    assert selection.node is second
    assert selection.origin == "canvas"
    # selecting a widget of the first window shows its tab and keeps the widget selected
    label = first.children[0]
    shell.session.select(label, origin="tree")
    canvas.notebook.update()
    assert canvas.notebook.select() == str(canvas.stages[0].page)
    assert shell.session.selection.node is label


def test_session_selection_reaches_the_tree(shell: DesignerApp) -> None:
    _open_hello(shell)
    document = shell.session.document
    assert document is not None
    label = next(n for n in document.walk() if getattr(n, "id", "") == "lbl_name")
    shell.session.select(label, origin="canvas")
    tree = shell.shell.tree.tree
    assert tree is not None
    assert tree.selection() == (shell.shell.tree.key_of(label),)


def test_findings_show_in_the_tree_and_the_status_bar(shell: DesignerApp) -> None:
    shell.session.open_result(read_ui_string(BROKEN, source="broken"), name="broken")
    panels = shell.shell
    assert "error" in panels.statusbar.winfo_children()[1].cget("text")
    tree = panels.tree.tree
    assert tree is not None
    document = shell.session.document
    assert document is not None
    nope = next(n for n in document.walk() if getattr(n, "class_name", "") == "Nope")
    key = panels.tree.key_of(nope)
    assert key is not None
    assert tree.set(key, "status") == "Error"  # a word as well as a colour


def test_panels_never_change_the_model(shell: DesignerApp) -> None:
    _open_hello(shell)
    document = shell.session.document
    assert document is not None
    before = [n for n in document.walk()]
    stack = shell.session.stack
    assert stack is not None
    shell.session.select(document.children[0].children[0], origin="tree")
    shell.shell.palette.retranslate()
    assert [n for n in document.walk()] == before
    assert not stack.can_undo


def test_quit_shortcut_and_disabled_state_do_not_crash(shell: DesignerApp) -> None:
    # Ctrl+Q is bound on the root; invoking the registry directly would destroy the shared root
    shell.root.update_idletasks()
    sequences = shell.root.bind_all()
    assert "<Control-Key-q>" in sequences and "<Control-Key-n>" in sequences


def test_toggling_theme_and_language_50_times_leaves_one_listener(shell: DesignerApp) -> None:
    for step in range(50):
        shell.set_theme(("light", "dark", "high_contrast")[step % 3])
        i18n.set_language(("en_XA", "en_GB", "de_DE")[step % 3])
    shell.flush_theme()
    assert len([cb for cb in i18n._live_listeners() if cb == shell._on_language]) == 1
    assert shell.role == ("light", "dark", "high_contrast")[49 % 3]
    i18n.set_language("en_GB")


def test_dispose_removes_menu_keys_and_panels(designer_root: Any) -> None:
    app = DesignerApp(designer_root)
    app.dispose()
    assert not designer_root.bind_all("<Control-Key-q>")
    assert str(designer_root.cget("menu")) == ""
    assert i18n._live_listeners() == []
    assert designer_root.winfo_children() == []


@pytest.mark.parametrize("lang", ["en_XA", "de_DE", "nl_NL", "fr_FR", "pt_PT"])
def test_long_language_still_fits_the_window(shell: DesignerApp, lang: str) -> None:
    """en_XA is about 40 percent longer (and these real locales the longest): the root keeps its
    minimum size and shows all menus."""
    shell.set_language(lang)
    shell.root.update_idletasks()
    assert shell.shell.toolbar.winfo_reqwidth() < shell.root.winfo_reqwidth() + 1
    assert shell.shell.statusbar.winfo_reqheight() > 0


def test_tree_detail_cells_end_with_an_ellipsis_and_the_status_bar_has_the_full_text(
    shell: DesignerApp,
) -> None:
    """QA-12-10: a clipped cell shows "…" and the whole row text goes to the status bar."""
    _open_hello(shell)
    shell.set_language("en_XA")
    panel = shell.shell.tree
    tree = panel.tree
    assert tree is not None
    tree.column("detail", width=45)
    panel._fit_cells()
    window_key = tree.get_children()[0]
    assert str(tree.set(window_key, "detail")).endswith("…")
    full = panel._full[window_key][0]
    assert full.startswith("[") and len(full) > len(str(tree.set(window_key, "detail")))
    tree.selection_set(window_key)
    shell.root.update()
    assert full in shell.shell._status.cget("text")
    # widening the column restores the whole text without a re-render
    tree.column("detail", width=900)
    panel._fit_cells()
    assert tree.set(window_key, "detail") == full
