"""Tk side of the designer themes: register them with ttkbootstrap, switch live, set fonts.

ttkbootstrap's ``Style`` is a process-wide singleton that is reset when a root is destroyed, so
the themes are re-registered for every root. ``Theme`` families are deliberately not used: they
re-ramp the anchor colours, so a brand colour would not render as itself (spec section 4.1).
"""

from __future__ import annotations

import logging
import tkinter
from collections.abc import Iterable
from tkinter import font as tkfont
from typing import Any

from ttkbootstrap import Fonts, Style
from ttkbootstrap.style import Colors, ThemeDefinition

from pyguibud.designer.theme import ThemeSpec, pick_family, selection_colours

__all__ = ["TREE_STYLE", "apply_fonts", "apply_theme", "install_themes", "scaled", "use_theme"]

_log = logging.getLogger(__name__)


def install_themes(
    style: Any,  # noqa: ANN401 - ttkbootstrap's Style is untyped
    specs: Iterable[ThemeSpec],
) -> None:
    """Register every spec as an exact-colour ttkbootstrap theme (idempotent)."""
    for spec in specs:
        style.register_theme(ThemeDefinition(spec.name, Colors(**spec.colors), spec.mode))


def use_theme(root: tkinter.Misc, spec: ThemeSpec) -> None:
    """Switch the live widget tree to ``spec`` and repaint the designer's own chrome."""
    style = Style.get_instance()
    if style is None:
        raise RuntimeError("no ttkbootstrap Style: the root was not created with ttkbootstrap")
    if style.theme_use() != spec.name:
        style.theme_use(spec.name)
    apply_theme(root, spec)


def apply_theme(root: tkinter.Misc, spec: ThemeSpec) -> None:
    """Colour the plain-Tk parts that ttk styling does not reach (root, menus, text widgets)."""
    colours = spec.colors
    option = root.option_add
    for widget in ("Menu", "Listbox", "Text"):
        is_menu = widget == "Menu"
        option(f"*{widget}.background", colours["bg"] if is_menu else colours["inputbg"])
        option(f"*{widget}.foreground", colours["fg"] if is_menu else colours["inputfg"])
        option(f"*{widget}.selectBackground", colours["selectbg"])
        option(f"*{widget}.selectForeground", colours["selectfg"])
    _fill_empty_tree_area()
    _designer_treeview(spec)
    option("*Menu.activeBackground", colours["selectbg"])
    option("*Menu.activeForeground", colours["selectfg"])
    try:
        root.configure(**{"background": colours["bg"]})
    except tkinter.TclError:  # the root is being destroyed
        _log.debug("Could not recolour the root", exc_info=True)


def _fill_empty_tree_area() -> None:
    """Colour the empty area under a Treeview's rows like the rows (it stays white otherwise)."""
    style = Style.get_instance()
    if style is None:
        return
    row_background = style.lookup("Treeview", "background")
    if row_background:
        style.configure("Treeview", fieldbackground=row_background)


#: The style of the designer's own lists; user Treeviews on the canvas keep the runtime look.
TREE_STYLE = "Designer.Treeview"


def _designer_treeview(spec: ThemeSpec) -> None:
    """A solid, 3:1 selected row for the palette, tree and inspector (re-applied per theme)."""
    style = Style.get_instance()
    if style is not None:
        fill, text = selection_colours(spec)
        style.map(TREE_STYLE, background=[("selected", fill)], foreground=[("selected", text)])


def apply_fonts(root: tkinter.Misc, spec: ThemeSpec) -> None:
    """Use the first installed family of the spec for the UI and for code; else keep Tk's own."""
    try:
        available = tkfont.families(root)
    except tkinter.TclError:
        return
    sans = pick_family(spec.sans, available)
    mono = pick_family(spec.mono, available)
    if sans is not None:
        Fonts.set_global_family(sans, mono_family=mono)
    elif mono is not None:
        tkfont.nametofont("TkFixedFont", root=root).configure(family=mono)


def scaled(root: tkinter.Misc, pixels: int) -> int:
    """``pixels`` (designed for 96 dpi) scaled to the display's Tk scaling factor."""
    factor = float(root.tk.call("tk", "scaling")) / (96 / 72)
    return max(1, round(pixels * factor))
