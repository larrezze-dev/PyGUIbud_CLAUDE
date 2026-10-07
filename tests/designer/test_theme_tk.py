"""Theme installation and the live switch (Tk; shares the package root)."""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud.designer import app as app_module
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.theme import ROLES, contrast, spec_for_role
from pyguibud.designer.themes import NEUTRAL_SPECS

pytestmark = pytest.mark.gui


def _style() -> Any:
    from ttkbootstrap import Style

    style_cls: Any = Style  # ttkbootstrap ships no annotations for get_instance
    return style_cls.get_instance()


def test_all_roles_are_registered(shell: DesignerApp) -> None:
    names = set(_style().theme_names())
    assert {spec.name for spec in shell.specs} <= names


@pytest.mark.parametrize("role", ROLES)
def test_every_role_switches_the_live_theme(shell: DesignerApp, role: str) -> None:
    assert shell.set_theme(role)
    shell.flush_theme()
    spec = spec_for_role(shell.specs, role)
    assert spec is not None
    assert _style().theme_use() == spec.name
    assert shell.role == role


def test_theme_colours_are_exact(shell: DesignerApp) -> None:
    """The brand colour renders as itself (no re-ramping)."""
    shell.set_theme("dark")
    shell.flush_theme()
    spec = spec_for_role(shell.specs, "dark")
    assert spec is not None
    colours = _style().colors
    assert str(colours.primary).upper() == spec.colors["primary"]
    assert str(colours.bg).upper() == spec.colors["bg"]


@pytest.mark.parametrize("role", ROLES)
def test_painted_button_text_meets_aa(shell: DesignerApp, role: str) -> None:
    """Query the style ttkbootstrap actually built: text colour on a filled button."""
    shell.set_theme(role)
    shell.flush_theme()
    style = _style()
    for accent in ("primary", "success", "info", "warning", "danger", "secondary"):
        name = f"{accent}.TButton"
        from tkinter import ttk

        button = ttk.Button(shell.root, style=name)  # forces the style to be built
        try:
            fill = str(style.lookup(name, "background")).upper()
            text = str(style.lookup(name, "foreground")).upper()
        finally:
            button.destroy()
        assert fill.startswith("#") and text.startswith("#"), (name, fill, text)
        assert contrast(text, fill) >= 4.5, (role, name, fill, text)


def test_rapid_requests_coalesce_and_last_wins(shell: DesignerApp) -> None:
    for role in ("dark", "high_contrast", "light", "dark"):
        assert shell.set_theme(role)
    assert shell._idle_id is not None  # one pending callback, not four
    shell.flush_theme()
    assert shell.role == "dark"
    assert shell._idle_id is None


def test_after_idle_applies_the_theme(shell: DesignerApp) -> None:
    shell.set_theme("high_contrast")
    shell.root.update()  # runs the idle callbacks
    assert shell.role == "high_contrast"


def test_unknown_role_changes_nothing_and_reports(shell: DesignerApp) -> None:
    seen: list[str] = []
    shell.message.connect(seen.append)
    before = _style().theme_use()
    assert shell.set_theme("neon") is False
    shell.flush_theme()
    assert _style().theme_use() == before
    assert seen and "neon" in seen[0]


def test_many_toggles_leave_no_stray_state(shell: DesignerApp) -> None:
    from pyguibud import i18n

    for index in range(30):
        shell.set_theme(ROLES[index % 3])
        i18n.set_language("en_XA" if index % 2 else "en_GB")
    shell.flush_theme()
    assert shell.role == ROLES[29 % 3]
    assert len(i18n._listeners) == 1
    assert shell._pending is None


def test_dispose_removes_the_listener_and_pending_callback(designer_root: Any) -> None:
    from pyguibud import i18n

    app = DesignerApp(designer_root)
    app.set_theme("dark")
    app.dispose()
    assert app._idle_id is None
    assert not i18n._live_listeners()
    app.set_theme("light")  # harmless after dispose
    app.flush_theme()
    designer_root.update()


def test_neutral_themes_install_when_the_brand_is_absent(designer_root: Any) -> None:
    app = DesignerApp(designer_root, specs=NEUTRAL_SPECS, role="dark")
    try:
        assert _style().theme_use() == "pyguibud-dark"
    finally:
        app.set_theme("light")
        app.flush_theme()
        app.dispose()


def test_fonts_fall_back_without_error(shell: DesignerApp) -> None:
    from tkinter import font as tkfont

    shell._theme_tk.apply_fonts(shell.root, shell.specs[0])
    family = tkfont.nametofont("TkDefaultFont", root=shell.root).actual("family")
    assert isinstance(family, str) and family


def test_fonts_with_no_installed_family_keep_tk_defaults(shell: DesignerApp) -> None:
    from dataclasses import replace
    from tkinter import font as tkfont

    before = tkfont.nametofont("TkDefaultFont", root=shell.root).actual("family")
    ghost = replace(shell.specs[0], sans=("No Such Family",), mono=("No Such Mono",))
    shell._theme_tk.apply_fonts(shell.root, ghost)
    assert tkfont.nametofont("TkDefaultFont", root=shell.root).actual("family") == before


def test_scaled_is_positive(shell: DesignerApp) -> None:
    assert shell._theme_tk.scaled(shell.root, 800) >= 800 * 0.5


# ---------------------------------------------------------------- application icon
def test_brand_icon_becomes_the_window_default(designer_root: Any) -> None:
    image = app_module.apply_app_icon(designer_root)
    assert image is not None
    assert (image.width(), image.height()) == (32, 32)
    assert designer_root._pyguibud_icon is image  # kept alive on the root


def test_without_brand_icon_the_default_stays(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "load_app_icon", lambda: None)
    assert app_module.apply_app_icon(designer_root) is None


def test_icon_tk_rejects_is_logged_not_raised(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(app_module, "load_app_icon", lambda: b"\x89PNG\r\n\x1a\nbroken")
    with caplog.at_level("WARNING"):
        assert app_module.apply_app_icon(designer_root) is None
    assert any("Brand icon ignored" in r.getMessage() for r in caplog.records)
