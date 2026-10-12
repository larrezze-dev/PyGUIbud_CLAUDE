"""The step 14p styling layer (Tk): rule S, style names, painted contrast, toolbar, status bar."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from tkinter import font as tkfont
from typing import Any

import pytest
from ttkbootstrap.style.bootstyle import Bootstyle, Keywords

from pyguibud import i18n
from pyguibud.designer import theme_tk
from pyguibud.designer.actions import action_hint
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.icons import load_masks
from pyguibud.designer.shell import TOOLBAR_GROUPS
from pyguibud.designer.theme import ROLES, TEXT_CONTRAST, contrast, design_tokens, spec_for_role
from pyguibud.designer.theme_tk import (
    DESIGNER_FONTS,
    DESIGNER_STYLES,
    GHOST_STYLE,
    OWN_STYLES,
    STYLE_DIVIDER,
    TREE_STYLE,
    apply_designer_styles,
)

ROOT = Path(__file__).resolve().parents[2]
_TK_FONTS = ("TkDefaultFont", "TkHeadingFont", "TkTextFont", "TkFixedFont")


def _style() -> Any:
    from ttkbootstrap import Style

    style_cls: Any = Style
    return style_cls.get_instance()


# ---------------------------------------------------------------- style names (test 3)
def test_no_designer_style_name_contains_a_bootstyle_keyword() -> None:
    keywords = {k.lower() for k in (*Keywords.COLORS, *Keywords.TYPES)}
    keywords |= {"primary", "secondary", "success", "info", "warning", "danger", "light", "dark",
                 "inverse", "outline", "link", "ghost", "round", "square", "striped",
                 "toolbutton"}  # fmt: skip
    names = [*OWN_STYLES, f"{theme_tk.INVALID_PREFIX}.TEntry"]
    names += [getattr(theme_tk, n) for n in theme_tk.__all__ if n.startswith("STYLE_")]
    for name in names:
        assert name.startswith("Designer.")
        for part in name.lower().split(".")[:-1]:
            assert not any(keyword in part for keyword in keywords), (name, part)


# ---------------------------------------------------------------- rule S (test 2)
def _text(value: object) -> str:
    """One text form per value: Tcl hands the same option back as a list or as a string."""
    if isinstance(value, (list, tuple)):
        return " ".join(_text(part) for part in value)
    return str(value)


def _snapshot(root: Any) -> dict[str, Any]:
    style = _style()
    snap: dict[str, Any] = {}
    for name in (*DESIGNER_STYLES, GHOST_STYLE):
        options = style.configure(name) or {}
        snap[f"configure:{name}"] = {k: _text(v) for k, v in options.items()}
        maps = style.map(name) or {}
        snap[f"map:{name}"] = {k: [_text(state) for state in v] for k, v in maps.items()}
    snap |= {f"font:{f}": tkfont.nametofont(f, root=root).actual() for f in _TK_FONTS}
    return snap


def _base_part(root: Any, spec: Any) -> None:
    """``use_theme`` without the designer layer: the theme, the built base styles, the fonts."""
    style = _style()
    style.theme_use(spec.name)
    for name in (*DESIGNER_STYLES, GHOST_STYLE):
        Bootstyle.update_ttk_widget_style(style_string=name)
    theme_tk.apply_theme(root, spec)
    theme_tk.apply_fonts(root, spec)


def rule_s_check() -> int:
    """Run in a fresh process (a fresh ``Style``): snapshot the base part of every theme before
    any designer chrome exists, then build the designer, cycle the themes twice (every panel's
    ``restyle()`` runs) and compare. 0 = equal; 1 = a leak, printed."""
    from ttkbootstrap import App

    from pyguibud.designer.theme import load_theme_specs

    root = App(title="rule-s")
    root.withdraw()
    specs = load_theme_specs()
    theme_tk.install_themes(_style(), specs)
    baseline = {}
    for spec in specs:
        _base_part(root, spec)
        baseline[spec.role] = _snapshot(root)
    app = DesignerApp(root, specs=specs)
    leaks = []
    for role in (*ROLES, *ROLES):
        app.set_theme(role)
        app.flush_theme()
        root.update_idletasks()
        current = spec_for_role(specs, role)
        assert current is not None
        theme_tk.apply_fonts(root, current)  # the baseline ran it last too
        after = _snapshot(root)
        changed = (k for k, v in after.items() if baseline[role][k] != v)
        leaks += [f"{role} {k}: {baseline[role][k]} -> {after[k]}" for k in changed]
    app.dispose()
    root.destroy()
    for leak in leaks:
        print(leak)
    return 1 if leaks else 0


@pytest.mark.gui
def test_rule_s_base_styles_and_tk_fonts_are_untouched() -> None:
    """Rule S: the designer chrome never changes a base style or a Tk named font, so the user's
    widgets on the canvas look exactly as at run time (spec 14p section 0, ADR-012)."""
    code = "from tests.designer.test_styling_layer import rule_s_check; exit(rule_s_check())"
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]


# ---------------------------------------------------------------- painted contrast (test 1)
@pytest.mark.gui
@pytest.mark.parametrize("role", ROLES)
def test_configured_designer_styles_meet_aa(shell: DesignerApp, role: str) -> None:
    shell.set_theme(role)
    shell.flush_theme()
    spec = spec_for_role(shell.specs, role)
    assert spec is not None
    style = _style()
    checked = 0
    for name in OWN_STYLES:
        foreground = style.configure(name, "foreground")
        if not foreground:
            continue
        background = style.configure(name, "background") or spec.colors["bg"]
        assert contrast(str(foreground), str(background)) >= TEXT_CONTRAST, name
        checked += 1
    assert checked >= 8


@pytest.mark.gui
def test_designer_fonts_follow_the_default_font(shell: DesignerApp) -> None:
    base = tkfont.nametofont("TkDefaultFont", root=shell.root).actual()
    for name, offset, bold in DESIGNER_FONTS:
        actual = tkfont.nametofont(name, root=shell.root).actual()
        assert actual["family"] == base["family"]
        assert actual["weight"] == ("bold" if bold else "normal")
        if offset:
            assert actual["size"] != base["size"]
    apply_designer_styles(shell.root, shell.specs[0])  # idempotent: configures, never re-creates
    assert tkfont.names(shell.root).count("PyGUIbudTitle") == 1


@pytest.mark.gui
def test_tree_rows_fit_an_icon(shell: DesignerApp) -> None:
    from pyguibud.designer.icons_tk import icons

    rowheight = int(_style().configure(TREE_STYLE, "rowheight"))
    assert rowheight >= icons(shell.root).size + 4


@pytest.mark.gui
def test_editor_styles_map_readonly_and_invalid(shell: DesignerApp) -> None:
    style = _style()
    spec = spec_for_role(shell.specs, shell.role)
    assert spec is not None
    tokens = design_tokens(spec)
    for name in ("Designer.TEntry", "Designer.TSpinbox", "Designer.Invalid.TEntry"):
        states = style.map(name, "fieldbackground")
        assert tuple(map(str, states[0])) == ("readonly", tokens.readonly_bg), name
    assert str(style.configure("Designer.Invalid.TEntry", "bordercolor")) == tokens.error_border
    assert str(style.configure("Designer.Invalid.TLabel", "foreground")) == tokens.error_text


@pytest.mark.gui
def test_qa14p_08_a_focused_invalid_editor_keeps_its_error_border(shell: DesignerApp) -> None:
    """D8: the theme's focus map painted the focus colour over the error border."""
    style = _style()
    spec = spec_for_role(shell.specs, shell.role)
    assert spec is not None
    error = design_tokens(spec).error_border.lower()
    for base in ("TEntry", "TSpinbox", "TCombobox"):
        name = f"Designer.Invalid.{base}"
        for state in ([], ["focus"]):
            assert str(style.lookup(name, "bordercolor", state)).lower() == error, (name, state)
        for option in ("lightcolor", "darkcolor"):
            assert str(style.lookup(name, option, ["focus"])).lower() == error, (name, option)
        normal = str(style.lookup(f"Designer.{base}", "bordercolor", ["focus"])).lower()
        if base != "TCombobox":  # Designer.TCombobox does not exist: the class style is used
            assert normal != error, "a valid focused editor shows the focus colour"


# ---------------------------------------------------------------- toolbar and status bar (test 6)
@pytest.mark.gui
def test_toolbar_has_three_groups_of_icon_buttons(shell: DesignerApp) -> None:
    buttons = shell.shell._buttons
    assert [a.id for _b, a in buttons] == [i for group in TOOLBAR_GROUPS for i in group]
    bar = shell.shell.toolbar
    separators = [w for w in bar.winfo_children() if w.winfo_class() == "TSeparator"]
    assert len(separators) == len(TOOLBAR_GROUPS) - 1  # Preview is the fourth group (15a)
    for button, action in buttons:
        assert action.icon in load_masks()
        assert str(button.cget("style")) == GHOST_STYLE
        assert str(button.cget("compound")) == "image"
        image = button.cget("image")
        assert len(image) == 3 and str(image[1]) == "disabled"  # normal, "disabled", grey
        assert str(image[0]) != str(image[2])
    dividers = [w for w in bar.winfo_children() if str(w.cget("style")) == STYLE_DIVIDER]
    assert len(dividers) == 1


@pytest.mark.gui
def test_toolbar_tooltips_name_action_and_key_and_follow_the_language(
    shell: DesignerApp,
) -> None:
    tips = {a.id: tip for tip, a in shell.shell._tips}
    assert tips["file.save"].cget("text") == "Save (Ctrl+S)"
    assert tips["edit.undo"].cget("text") == "Undo (Ctrl+Z)"
    shell.set_language("en_XA")
    save = shell.registry.get("file.save")
    assert save is not None
    assert tips["file.save"].cget("text") == action_hint(save)
    assert tips["file.save"].cget("text").startswith("[")
    shell.registry.invoke("view.language.en_GB")
    assert tips["file.save"].cget("text") == "Save (Ctrl+S)"


def test_hint_uses_the_msgid_not_concatenation(monkeypatch: pytest.MonkeyPatch) -> None:
    from pyguibud.designer import actions

    seen: list[str] = []

    def spy(message: str) -> str:
        seen.append(message)
        return message

    monkeypatch.setattr(actions, "_", spy)
    action = actions.ActionDef("x.y", "x", "_Save", lambda: None, "Ctrl+S")
    assert action_hint(action) == "Save (Ctrl+S)"
    assert actions.M_ACTION_SHORTCUT in seen
    bare = actions.ActionDef("x.z", "x", "_Save", lambda: None)
    assert action_hint(bare) == "Save"
    assert i18n.get_language() == "en_GB"


@pytest.mark.gui
def test_toolbar_buttons_grey_out_and_keyboard_focus_names_them(shell: DesignerApp) -> None:
    buttons = {a.id: b for b, a in shell.shell._buttons}
    shell.shell.refresh_states()
    assert buttons["file.save"].instate(["disabled"])  # no document
    assert buttons["edit.undo"].instate(["disabled"])
    assert not buttons["file.open"].instate(["disabled"])
    buttons["file.open"].event_generate("<FocusIn>")
    assert shell.shell._status.cget("text") == "Open… (Ctrl+O)"
    buttons["file.save"].event_generate("<FocusIn>")  # the next hint replaces the last one
    assert shell.shell._status.cget("text") == "Save (Ctrl+S)"
    shell.shell.show_message("Saved.")
    buttons["file.open"].event_generate("<FocusIn>")  # back from a dialog: the result stays
    assert shell.shell._status.cget("text") == "Saved."


@pytest.mark.gui
def test_qa14p_01_a_stale_toolbar_button_says_why_it_refuses(
    shell: DesignerApp, tmp_path: Path
) -> None:
    """A click on a button whose action is disabled is never silent (as its shortcut)."""
    from tests.designer.test_qa14p_abuse import _read_only_file

    assert shell.open_path(_read_only_file(tmp_path))
    document = shell.session.document
    assert document is not None
    shell.session.select(document.children[0].children[0], origin="tree")
    shell.root.update()
    cut = next(b for b, a in shell.shell._buttons if a.id == "edit.cut")
    assert cut.instate(["disabled"])  # read-only: the selection change greyed it
    cut.state(["!disabled"])  # stale, as between a change and the next refresh
    cut.invoke()
    reason = shell.session.read_only_refusal()
    assert reason and shell.shell._message == reason


@pytest.mark.gui
def test_qa14p_03_toolbar_click_leaves_the_buttons_on_the_tab_path(shell: DesignerApp) -> None:
    """The click does not take the focus, but Tab still reaches the buttons (spec 14p 4)."""
    buttons = [b for b, _a in shell.shell._buttons if b.instate(["!disabled"])]
    first, second = buttons[:2]
    first.event_generate("<ButtonPress-1>", x=2, y=2)
    first.event_generate("<ButtonRelease-1>", x=2, y=2)
    shell.root.update()
    for button in buttons:
        assert str(button.cget("takefocus")) == "1"
    shell.root.deiconify()  # traversal skips windows that are not viewable
    try:
        shell.root.update()
        assert first.tk_focusNext() is second
    finally:
        shell.root.withdraw()
        shell.root.update()


@pytest.mark.gui
def test_status_summary_has_a_severity_icon(shell: DesignerApp) -> None:
    from pyguibud.designer.icons_tk import icons

    summary = shell.shell._summary
    assert str(summary.cget("image")[0]) == str(icons(shell.root).get("ok"))
    divider = shell.shell.statusbar.winfo_children()[-1]
    assert str(divider.cget("style")) == STYLE_DIVIDER
    assert int(divider.winfo_reqheight()) >= 1


@pytest.mark.gui
def test_toolbar_falls_back_to_text_without_icons(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer.icons_tk import IconCache

    monkeypatch.setattr(IconCache, "get", lambda *_a, **_k: None)
    app = DesignerApp(designer_root)
    try:
        button, _action = app.shell._buttons[0]
        assert str(button.cget("compound")) in ("", "none")
        assert button.cget("text") == "New from template…"
    finally:
        app.dispose()
