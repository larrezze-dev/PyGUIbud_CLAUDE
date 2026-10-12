"""Step 14p Task B: panel headers, list icons, inspector states, recovery dialog (spec 9.5-9.9)."""

from __future__ import annotations

import datetime
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud import i18n
from pyguibud.core import CORE_CLASS_NAMES, default_registry
from pyguibud.core.commands import CommandStack
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.dialogs.rename import RenameDialog
from pyguibud.designer.icons import load_masks
from pyguibud.designer.present import elide_middle
from pyguibud.designer.present.icons import class_icon, node_icon
from pyguibud.designer.recovery import RecoveryEntry
from pyguibud.designer.theme import design_tokens, load_theme_specs, spec_for_role
from pyguibud.designer.theme_tk import STYLE_DIVIDER, STYLE_HEADER, STYLE_HEADER_LABEL
from tests.designer.test_inspector_gui import _editor, _open
from tests.designer.test_qa13a_abuse import _settle, app  # noqa: F401 - fixtures and helpers


# ---------------------------------------------------------------- pure: icon names, elision
def test_every_icon_name_the_presenters_return_exists() -> None:
    masks, registry = load_masks(), default_registry()
    names = {class_icon(name, registry) for name in (*CORE_CLASS_NAMES, "Meter", "DateEntry")}
    names |= {class_icon("NoSuchPlugin", registry), "window_main", "window_dialog"}
    names |= {"window_component", "include", "Menubar", "Menu", "Action", "separator", "Statusbar"}
    assert names <= set(masks)
    assert class_icon("NoSuchPlugin", registry) == "puzzle" and node_icon(object()) == "puzzle"


def test_a_plugin_widget_takes_the_icon_of_its_core_fallback() -> None:
    class Spec:
        fallback = "Entry"

    class Plugins:
        def get(self, name: str) -> Spec | None:
            return Spec() if name == "FancyEntry" else None

    assert class_icon("FancyEntry", Plugins()) == "Entry"  # type: ignore[arg-type]


@given(
    folders=st.lists(st.text("abcdefgh ", min_size=1, max_size=12), min_size=1, max_size=6),
    name=st.text("abcdefgh.", min_size=1, max_size=15),
    limit=st.integers(min_value=1, max_value=80),
)
def test_elide_middle_keeps_the_drive_and_the_file_name(
    folders: list[str], name: str, limit: int
) -> None:
    path = "C:\\" + "\\".join(folders) + "\\" + name
    shown = elide_middle(path, limit)
    assert shown.endswith("\\" + name)  # the name is the part that is never lost
    if len(path) <= limit:
        assert shown == path
    elif limit >= len(name) + 6:
        assert shown.startswith("C:\\") and len(shown) <= limit and "…" in shown


def _wide(text: str) -> int:
    """A stand-in font: CJK glyphs are twice as wide as Latin ones (QA-14p-06)."""
    return sum(14 if ord(ch) > 0x2E80 else 7 for ch in text)


@given(
    folders=st.lists(st.text("ab用户文档W ", min_size=1, max_size=12), min_size=1, max_size=6),
    name=st.text("ab界面.", min_size=1, max_size=15),
    width=st.integers(min_value=-5, max_value=600),
)
def test_elide_middle_by_measure_fits_wide_glyphs_and_keeps_the_name(
    folders: list[str], name: str, width: int
) -> None:
    path = "C:\\" + "\\".join(folders) + "\\" + name
    shown = elide_middle(path, width, _wide)
    assert shown.endswith("\\" + name)
    if width <= 0 or _wide(path) <= width:
        assert shown == path  # not laid out yet, or it fits
    elif _wide("C:\\…\\" + name) <= width:
        assert shown.startswith("C:\\") and "…" in shown and _wide(shown) <= width


# ---------------------------------------------------------------- panels (Tk)
@pytest.mark.gui
def test_every_panel_has_a_header_band_and_a_divider_edge(shell: DesignerApp) -> None:
    spec = spec_for_role(load_theme_specs(), "light") or load_theme_specs()[0]
    tokens = design_tokens(spec)
    panels = (shell.shell.palette, shell.shell.tree, shell.shell.inspector, shell.shell.variables)
    for panel in panels:
        assert str(panel.band.cget("style")) == STYLE_HEADER
        assert str(panel.heading.cget("style")) == STYLE_HEADER_LABEL
        assert [str(c.cget("style")) for c in panel.band.winfo_children()][-1] == STYLE_DIVIDER
        panel.restyle(spec)
        panel.frame.mark(False)
        assert str(panel.frame.cget("highlightbackground")) == tokens.divider  # D10
        panel.frame.mark(True)
        assert str(panel.frame.cget("highlightbackground")) == tokens.ring


@pytest.mark.gui
def test_palette_and_tree_rows_carry_icons(app: DesignerApp, designer_root: Any) -> None:  # noqa: F811
    _open(app, designer_root, "lbl_username")
    palette, tree = app.shell.palette.tree, app.shell.tree.tree
    assert palette is not None and tree is not None
    assert str(palette.item("w:Button", "image")) and not str(palette.item("c0", "image"))
    assert "category" in palette.item("c0", "tags")
    rows = list(tree.get_children(""))
    assert rows and all(str(tree.item(k, "image")) for k in rows)  # a window icon each


# ---------------------------------------------------------------- inspector (Tk)
@pytest.mark.gui
def test_invalid_shows_colour_border_and_an_alert_icon_then_restores_its_own_style(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root, "lbl_username")
    entry = _editor(app.shell.inspector, "prop:text")
    spin = _editor(app.shell.inspector, "prop:width")
    for editor, normal in ((entry, "Designer.TEntry"), (spin, "Designer.TSpinbox")):
        assert str(editor.widget.cget("style")) == normal
        editor.set_invalid(True)
        assert str(editor.widget.cget("style")) == f"Designer.Invalid.{normal[9:]}"
        assert editor.alert is not None and editor.alert.winfo_manager() == "grid"
        assert str(editor.alert.cget("image")) or editor.alert.cget("text")
        editor.set_invalid(False)
        assert str(editor.widget.cget("style")) == normal  # never the bare class style
        assert editor.alert.winfo_manager() == ""


@pytest.mark.gui
def test_read_only_entries_stay_selectable_and_other_editors_are_disabled(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open(app, designer_root, "lbl_username")
    monkeypatch.setattr(CommandStack, "read_only", property(lambda _s: True))
    app.session.read_only_reason = "the file is write-protected"
    inspector = app.shell.inspector
    inspector._render()
    _settle(designer_root)
    entry = _editor(inspector, "prop:text")
    state = entry.widget.state()
    assert "readonly" in state and "disabled" not in state
    entry.widget.selection_range(0, "end")
    assert entry.widget.selection_present()  # its text can be selected, hence copied
    combos = [e for e in inspector._editors.values() if isinstance(e.widget, ttk.Combobox)]
    assert combos and all("disabled" in e.widget.state() for e in combos)
    assert str(inspector.header.cget("image"))  # the lock icon of the banner
    assert str(inspector.header.cget("compound")) == "left"


@pytest.mark.gui
def test_the_combobox_keeps_its_readonly_state_and_gets_no_text_style(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root, "lbl_username")
    editors = app.shell.inspector._editors.values()
    combos = [e for e in editors if isinstance(e.widget, ttk.Combobox)]
    assert combos
    for editor in combos:
        assert "readonly" in editor.widget.state()
        assert str(editor.widget.cget("style")) in ("", "TCombobox")  # not Designer.TEntry
        editor.set_enabled(True)
        assert "readonly" in editor.widget.state()  # enabling never removes its normal state


@pytest.mark.gui
def test_default_rows_are_muted_and_the_reset_button_is_an_icon(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root, "lbl_username")
    label, reset, _mixed = app.shell.inspector._rows["prop:width"]
    assert str(label.cget("style")) == "Designer.Muted.TLabel"  # a default value
    assert reset is not None and str(reset.cget("image")) and str(reset.cget("compound")) == "image"
    assert "disabled" in reset.state()


@pytest.mark.gui
def test_label_column_fits_the_widest_label_in_the_pseudo_locale(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
) -> None:
    _open(app, designer_root, "lbl_username")
    inspector = app.shell.inspector
    i18n.set_language("en_XA")
    try:
        inspector.retranslate()
        _settle(designer_root)
        labels = [row[0] for row in inspector._rows.values()]
        font = ttk.Style(inspector.form).lookup("TLabel", "font") or "TkDefaultFont"
        widest = max(tkfont.nametofont(str(font)).measure(str(lb.cget("text"))) for lb in labels)
        room = max(inspector.canvas.winfo_width(), inspector.canvas.winfo_reqwidth())
        minsize = int(inspector.form.grid_columnconfigure(0)["minsize"])
        assert minsize == min(widest, int(room * 0.45)) and minsize > 0
        if widest > minsize:  # too wide for the share: wrapped, not cut
            assert all(int(lb.cget("wraplength")) == minsize for lb in labels)
        assert all(str(lb.cget("text")).startswith("[") for lb in labels)
    finally:
        i18n.set_language("en_GB")


@pytest.mark.gui
def test_the_rename_dialogs_refusal_uses_the_designer_invalid_label(shell: DesignerApp) -> None:
    dialog = RenameDialog(shell.root, "a", lambda _t: None, lambda _t: None)
    try:
        assert str(dialog.reason.cget("style")) == "Designer.Invalid.TLabel"
    finally:
        dialog.close()


# ---------------------------------------------------------------- recovery dialog (Tk)
def _entry(folder: Path, path: str | None) -> RecoveryEntry:
    name = Path(path).name if path else "Untitled"
    return RecoveryEntry(folder, path, name, datetime.datetime.now(datetime.timezone.utc))


@pytest.mark.gui
def test_recovery_list_has_headings_elides_the_middle_and_marks_unsaved(
    shell: DesignerApp, tmp_path: Path
) -> None:
    deep = str(tmp_path.resolve() / ("very_long_folder_name_" * 4) / "project" / "main.ui")
    entries = [_entry(tmp_path, deep), _entry(tmp_path, None)]
    dialog = RecoveryDialog(shell.root, entries, restore=lambda *_a: None, confirm=lambda *_a: None)
    try:
        shell.root.update()
        tree = dialog.tree
        assert [str(part) for part in tree.cget("show")] == ["tree", "headings"]
        headings = [tree.heading(c, "text") for c in ("#0", "path", "time")]
        assert headings == ["Name", "Location", "Saved"]
        long_row, unsaved = tree.get_children()
        shown = str(tree.set(long_row, "path"))
        assert shown.endswith("main.ui") and "…" in shown and len(shown) < len(deep)
        assert tree.set(unsaved, "path") == "(not saved)" and "muted" in tree.item(unsaved, "tags")
        tree.selection_set(long_row)
        shell.root.update()
        assert str(dialog.where.cget("text")) == f"Location: {deep}"  # nothing lost to eliding
        tree.selection_set(unsaved)
        shell.root.update()
        assert str(dialog.where.cget("text")) == "Location: (not saved)"
    finally:
        dialog.close()


@pytest.mark.gui
def test_recovery_dialog_retranslates_headings_and_unsaved(
    shell: DesignerApp, tmp_path: Path
) -> None:
    dialog = RecoveryDialog(shell.root, [_entry(tmp_path, None)], restore=lambda *_a: None,
                            confirm=lambda *_a: None)  # fmt: skip
    try:
        i18n.set_language("en_XA")
        dialog.retranslate()
        assert str(dialog.tree.heading("path", "text")).startswith("[")
        row = dialog.tree.get_children()[0]
        assert str(dialog.tree.set(row, "path")).startswith("[")
    finally:
        i18n.set_language("en_GB")
        dialog.close()
