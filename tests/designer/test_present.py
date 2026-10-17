"""Presenters and shell actions (pure): palette, tree, inspector, canvas cards, status texts."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import (
    Document,
    ReadResult,
    Widget,
    Window,
    default_registry,
    read_ui,
    read_ui_string,
    validate,
)
from pyguibud.core.keys import split_mnemonic
from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef
from pyguibud.designer.present import clip, fit_text, severity_label
from pyguibud.designer.present.canvas import canvas_tabs, window_of
from pyguibud.designer.present.inspector import display_value, inspector_rows
from pyguibud.designer.present.palette import palette_groups
from pyguibud.designer.present.status import findings_summary, selection_path
from pyguibud.designer.present.tree import tree_rows
from pyguibud.designer.standard_actions import (
    PreviewCallbacks,
    ShellCallbacks,
    register_standard_actions,
)
from tests.designer.conftest import best_of

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"

BROKEN = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
    '<window id="main" kind="main"><layout type="grid"/>'
    '<widget class="Nope" id="w"/><widget class="Label" id="w"/>'
    "</window></pyguibud-ui>"
)


def _hello() -> ReadResult:
    return read_ui(EXAMPLES / "hello.ui")


# ---------------------------------------------------------------- helpers
def test_clip_cuts_with_an_ellipsis() -> None:
    assert clip("abc", 5) == "abc"
    assert clip("x" * 200) == "x" * 99 + "…"
    assert len(clip("x" * 200)) == 100


def test_severity_label_is_translated() -> None:
    assert severity_label("") == ""
    assert severity_label("error") == "Error"
    i18n.set_language("en_XA")
    assert severity_label("warning").startswith("[")


# ---------------------------------------------------------------- palette
def test_palette_groups_are_sorted_and_complete() -> None:
    registry = default_registry()
    groups = palette_groups(registry)
    assert [g.category_label.casefold() for g in groups] == sorted(
        g.category_label.casefold() for g in groups
    )
    names = {item.name for group in groups for item in group.items}
    assert names == {spec.name for spec in registry.specs()}
    for group in groups:
        labels = [(i.label.casefold(), i.name) for i in group.items]
        assert labels == sorted(labels)


def test_palette_follows_the_language() -> None:
    before = palette_groups(default_registry())[0].category_label
    i18n.set_language("en_XA")
    assert palette_groups(default_registry())[0].category_label != before


# ---------------------------------------------------------------- tree
def test_tree_rows_cover_windows_menus_and_widgets() -> None:
    result = _hello()
    registry = default_registry()
    rows = tree_rows(result.document, validate(result.document, registry))
    nodes = [row.node for row in rows]
    assert nodes[0] is result.document.children[0]
    assert {id(n) for n in result.document.walk() if n is not result.document} == {
        id(n) for n in nodes
    }
    assert rows[0].parent_key is None
    keys = [row.key for row in rows]
    assert keys == [f"n{i}" for i in range(len(rows))]
    by_key = {row.key: row for row in rows}
    assert all(row.parent_key is None or row.parent_key in by_key for row in rows)
    assert any(row.text == "Menu bar" for row in rows)


def test_tree_rows_flag_findings_without_using_ids_as_keys() -> None:
    result = read_ui_string(BROKEN, source="broken")
    registry = default_registry()
    report = validate(result.document, registry)
    rows = tree_rows(result.document, report)
    flagged = {row.severity for row in rows}
    assert "error" in flagged
    assert len({row.key for row in rows}) == len(rows)  # duplicate ids: keys stay unique


def test_tree_rows_large_document_is_fast_and_iterative() -> None:
    document = Document()
    window = Window(id="main")
    document.add_window(window)
    parent: Window | Widget = window
    for index in range(150):  # depth: no RecursionError
        node = Widget(class_name="Frame", id=f"f{index}")
        parent.append_child(node)
        parent = node
    for index in range(2000):
        window.append_child(Widget(class_name="Label", id=f"l{index}"))
    report = validate(document, default_registry())
    rows = tree_rows(document, report)
    assert len(rows) == 1 + 150 + 2000
    # The spec asks 150 ms (x3 for slow CI); the best of 3 runs with the GC paused, as a gen-2
    # collection on the whole suite's heap can be longer than the budget itself.
    assert best_of(lambda: tree_rows(document, report), repeat=3) < 0.15 * 3


# ---------------------------------------------------------------- inspector
def test_inspector_sections_and_defaults() -> None:
    result = _hello()
    registry = default_registry()
    report = validate(result.document, registry)
    label = next(n for n in result.document.walk() if getattr(n, "id", "") == "lbl_name")
    rows = inspector_rows(label, registry, report)
    sections = list(dict.fromkeys(row.section for row in rows))
    assert sections[:2] == ["General", "Properties"]
    assert "Placement" in sections
    assert ("Id", "lbl_name") in {(r.label, r.value) for r in rows}
    defaults = [r for r in rows if r.is_default]
    assert defaults
    assert display_value(defaults[0]).endswith("(default)")
    assert not any(r.is_default for r in rows if r.section != "Properties")


def test_inspector_window_and_nothing_selected() -> None:
    result = _hello()
    registry = default_registry()
    report = validate(result.document, registry)
    assert inspector_rows(None, registry, report) == []
    rows = inspector_rows(result.document.children[0], registry, report)
    assert any(r.value == "Hello PyGUIbud" and r.section == "Properties" for r in rows)


def test_the_window_title_property_has_a_translated_label() -> None:
    """QA-13a-08: the inspector showed the raw property name "title" for a window."""
    result = _hello()
    registry = default_registry()
    window = result.document.children[0]
    rows = inspector_rows(window, registry, validate(result.document, registry))
    assert [r.label for r in rows if r.value == "Hello PyGUIbud"] == ["Title"]
    i18n.set_language("en_XA")
    rows = inspector_rows(window, registry, validate(result.document, registry))
    (label,) = (r.label for r in rows if r.value == "Hello PyGUIbud")
    assert label.startswith("[") and label != "Title"


def test_inspector_lists_findings_of_the_node() -> None:
    result = read_ui_string(BROKEN, source="broken")
    registry = default_registry()
    report = validate(result.document, registry)
    nope = next(n for n in result.document.walk() if getattr(n, "class_name", "") == "Nope")
    rows = inspector_rows(nope, registry, report)
    assert any(r.section == "Findings" and r.label == "Error" for r in rows)


def test_inspector_clips_user_values() -> None:
    document = Document()
    window = Window(id="x" * 500)
    document.add_window(window)
    rows = inspector_rows(window, default_registry(), validate(document, default_registry()))
    assert all(len(r.value) <= 200 for r in rows)


# ---------------------------------------------------------------- canvas cards and status
def test_canvas_tabs_one_per_window() -> None:
    result = _hello()
    tabs = canvas_tabs(result.document)
    assert len(tabs) == len(result.document.children) == 1
    assert tabs[0].text == "Hello PyGUIbud"
    assert tabs[0].kind_label == "Main window"
    assert tabs[0].summary[0] == "Layout: grid"
    assert tabs[0].summary[1].endswith("widgets")


def test_window_of_finds_the_owner_even_for_menubar_and_statusbar() -> None:
    result = _hello()
    window = result.document.children[0]
    for node in window.walk():
        assert window_of(node, result.document) is window
    assert window_of(object()) is None


def test_selection_path_and_findings_summary() -> None:
    result = _hello()
    registry = default_registry()
    window = result.document.children[0]
    assert selection_path(None, result.document) == ""
    assert selection_path(window, result.document) == "window[main]"
    assert selection_path(window.menubar, result.document) == "window[main]/menubar"
    assert findings_summary(validate(result.document, registry)) == "No problems found"
    broken = read_ui_string(BROKEN, source="broken")
    text = findings_summary(validate(broken.document, registry))
    assert "error" in text
    i18n.set_language("en_XA")
    assert findings_summary(validate(broken.document, registry)).startswith("[")


# ---------------------------------------------------------------- standard actions
def _callbacks(log: list[str], *, preview: bool = False) -> ShellCallbacks:
    """``preview=True`` adds the Preview menu with its Toolkit sub-menu (the mnemonic gates)."""
    state = {"theme": "light", "lang": "en_GB"}
    menu = PreviewCallbacks(*(lambda *_a: None,) * 2, *(lambda: True,) * 2, lambda _code: None,
                            lambda: None, lambda: None, lambda: True,
                            toolkits=("ttkbootstrap", "tkinter"))  # fmt: skip
    return ShellCallbacks(
        new_document=lambda: log.append("new"),
        show_shortcuts=lambda: log.append("keys"),
        next_panel=lambda: log.append("next"),
        previous_panel=lambda: log.append("previous"),
        quit=lambda: log.append("quit"),
        set_theme=lambda role: state.update(theme=role),
        current_theme=lambda: state["theme"],
        set_language=lambda code: state.update(lang=code),
        current_language=lambda: state["lang"],
        preview=menu if preview else None,
    )


def test_standard_actions_menus_and_radio_groups() -> None:
    registry = ActionRegistry()
    log: list[str] = []
    register_standard_actions(registry, _callbacks(log))
    assert [registry.menu(m).parent for m in registry.menu_ids()] == [
        None,
        None,
        "view",
        "view",
        None,
    ]
    themes = [i for i in registry.menu_items("view.theme") if isinstance(i, ActionDef)]
    assert [a.id for a in themes] == [
        "view.theme.light",
        "view.theme.dark",
        "view.theme.high_contrast",
    ]
    languages = [i for i in registry.menu_items("view.language") if isinstance(i, ActionDef)]
    assert len(languages) == 8  # the pseudo-locale is hidden unless it is the start language
    assert "view.language.en_XA" not in [a.id for a in languages]
    assert [registry.is_checked(a) for a in themes] == [True, False, False]
    registry.invoke("view.theme.dark")
    assert [registry.is_checked(a) for a in themes] == [False, True, False]
    registry.invoke("view.language.de_DE")
    assert registry.is_checked(registry.get("view.language.de_DE"))  # type: ignore[arg-type]
    registry.invoke("file.new")
    registry.invoke("view.next_panel")
    registry.invoke("view.previous_panel")
    registry.invoke("help.shortcuts")
    registry.invoke("file.quit")
    assert log == ["new", "next", "previous", "keys", "quit"]


def test_pseudo_locale_is_listed_when_it_is_the_start_language() -> None:
    callbacks = _callbacks([])
    shown = replace(callbacks, current_language=lambda: "en_XA")
    registry = ActionRegistry()
    register_standard_actions(registry, shown)
    languages = [i for i in registry.menu_items("view.language") if isinstance(i, ActionDef)]
    assert [a.id for a in languages][-1] == "view.language.en_XA"
    assert len(languages) == 9
    assert registry.is_checked(languages[-1])


def test_every_menu_mnemonic_survives_the_pseudo_locale() -> None:
    registry = ActionRegistry()
    register_standard_actions(registry, _callbacks([], preview=True))
    for menu_id in registry.menu_ids():
        items = [registry.menu(menu_id), *registry.menu_items(menu_id)]
        for item in items:
            if not isinstance(item, MenuDef | ActionDef) or (
                isinstance(item, ActionDef) and not item.translate
            ):
                continue
            i18n.set_language("en_GB")
            plain, plain_at = split_mnemonic(i18n._(item.label))
            i18n.set_language("en_XA")
            text, at = split_mnemonic(i18n._(item.label))
            assert (at >= 0) == (plain_at >= 0), item.label
            if at >= 0:
                assert text[at] == plain[plain_at], item.label


def _live_access_keys(menu: Any, path: str = "") -> dict[str, list[tuple[str, str]]]:
    """``{menu path: [(label, access key)]}`` of a built Tk menu and all its cascades."""
    refill = str(menu.cget("postcommand"))
    if refill:  # filled when it opens (Open recent, Preview > Theme): open it as the user would
        menu.tk.eval(refill)
    found: dict[str, list[tuple[str, str]]] = {path: []}
    last = menu.index("end")
    for index in range(last + 1 if last is not None else 0):
        kind = menu.type(index)
        if kind in ("separator", "tearoff"):
            continue
        label = str(menu.entrycget(index, "label"))
        underline = int(menu.entrycget(index, "underline"))
        if 0 <= underline < len(label):
            found[path].append((label, label[underline].casefold()))
        if kind == "cascade":
            sub = menu.nametowidget(menu.entrycget(index, "menu"))
            found.update(_live_access_keys(sub, f"{path}/{label}"))
    return found


@pytest.mark.gui
@pytest.mark.parametrize("lang", (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE))
def test_mnemonics_are_unique_per_menu(shell: Any, lang: str) -> None:
    """Every built menu, the menu bar itself included, has one access key per entry (QA-18-08).

    It walks the menus the designer really builds: a registry of the standard actions alone has
    no Open, Save or Close and no Edit or Document menu, so it missed de_DE _Speichern /
    _Schließen and it_IT _Nuovo da modello / Salva con _nome.
    """
    shell.set_language(lang)
    menus = _live_access_keys(shell.shell.menubar)
    top = [label for label, _key in menus[""]]  # the menu bar's own entries are checked too
    assert len(top) == 6, top  # File, Edit, Document, Preview, View, Help
    assert {"/" + label for label in top} <= set(menus)
    assert len(menus) >= 10, sorted(menus)  # plus Open recent, Insert, Move, Theme, Language...
    clashes = {
        path: entries
        for path, entries in menus.items()
        if len({key for _label, key in entries}) != len(entries)
    }
    assert clashes == {}


def test_shortcuts_are_registered_once() -> None:
    registry = ActionRegistry()
    register_standard_actions(registry, _callbacks([]))
    rows = {row.label: row.accelerator for row in registry.cheat_sheet()}
    assert rows == {
        "New from template…": "Ctrl+N",
        "Quit": "Ctrl+Q",
        "Next panel": "F6",
        "Previous panel": "Shift+F6",
        "Keyboard shortcuts…": "F1",
    }


# ---------------------------------------------------------------- ellipsis fitting (QA-12-10)
def _measure(text: str) -> int:
    return 7 * len(text)  # a fixed-pitch stand-in for a Tk font


def test_fit_text_leaves_short_text_alone() -> None:
    assert fit_text("Main window", 7 * 11, _measure) == "Main window"
    assert fit_text("anything", 0, _measure) == "anything"  # not laid out yet


@pytest.mark.parametrize("width", [7, 14, 35, 70, 140])
def test_fit_text_ends_with_an_ellipsis_that_fits(width: int) -> None:
    text = "[Ventana principal ······]"
    out = fit_text(text, width, _measure)
    assert out.endswith("…") and _measure(out) <= max(width, 7)
    assert text.startswith(out[:-1])


def test_fit_text_is_monotonic_and_survives_odd_input() -> None:
    lengths = [len(fit_text("x" * 50, w, _measure)) for w in range(1, 400, 9)]
    assert lengths == sorted(lengths)
    assert fit_text("", 5, _measure) == ""
    assert fit_text("ab cd", 24, _measure) == "ab…"  # no dangling space before the ellipsis


def test_fit_text_by_words_never_cuts_mid_word() -> None:
    """QA-14b1-06: the status bar elides at a word boundary."""
    text = "Release here to cancel the drag"
    assert fit_text(text, 7 * 18, _measure, words=True) == "Release here to…"  # not "to ca…"
    assert fit_text(text, 7 * 14, _measure, words=True) == "Release here…"  # cut at a space
    assert fit_text("Unbreakable", 7 * 5, _measure, words=True) == "Unbr…"  # one word: chars
    assert fit_text(text, 7 * 40, _measure, words=True) == text
