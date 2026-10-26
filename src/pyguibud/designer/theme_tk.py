"""Tk side of the designer themes: register them with ttkbootstrap, switch live, set fonts.

ttkbootstrap's ``Style`` is a process-wide singleton that is reset when a root is destroyed, so
the themes are re-registered for every root. ``Theme`` families are deliberately not used: they
re-ramp the anchor colours, so a brand colour would not render as itself (spec section 4.1).

Rule S (spec 14p, ADR-012): the canvas renders the user's widgets with the same ``Style``, so
the designer chrome only configures its own ``Designer.*`` styles and ``PyGUIbud*`` named fonts,
never a base style (``TButton``, ``TLabel``, ...) nor a Tk named font.
"""

from __future__ import annotations

import logging
import tkinter
from collections.abc import Iterable
from tkinter import font as tkfont
from typing import Any, Final

from ttkbootstrap import Fonts, Style
from ttkbootstrap.style import Colors, ThemeDefinition
from ttkbootstrap.style.bootstyle import Bootstyle

from pyguibud.designer.icons import pick_size
from pyguibud.designer.theme import (
    SPACE,
    DesignTokens,
    ThemeSpec,
    design_tokens,
    pick_family,
    selection_colours,
)

__all__ = [
    "DESIGNER_FONTS",
    "DESIGNER_STYLES",
    "FONT_BODY",
    "FONT_CAPTION",
    "FONT_HEADER",
    "FONT_TITLE",
    "GHOST_STYLE",
    "INVALID_PREFIX",
    "LIST_STYLE",
    "OWN_STYLES",
    "STYLE_CAPTION",
    "STYLE_COMBOBOX",
    "STYLE_DIVIDER",
    "STYLE_ENTRY",
    "STYLE_ERROR",
    "STYLE_HEADER",
    "STYLE_HEADER_LABEL",
    "STYLE_MUTED",
    "STYLE_SECTION",
    "STYLE_SPINBOX",
    "STYLE_STAGE",
    "STYLE_STRIP",
    "STYLE_TITLEBAR",
    "STYLE_TITLE_LABEL",
    "TREE_STYLE",
    "apply_designer_styles",
    "apply_fonts",
    "apply_theme",
    "clear_menu",
    "install_themes",
    "menu_end",
    "scaled",
    "scaling_factor",
    "space",
    "underline_of",
    "use_theme",
]

_log = logging.getLogger(__name__)

#: The base styles of the plain ``tkinter.ttk`` widgets the designer builds. ttkbootstrap builds a
#: style for a theme only when one of its own widgets asks, or when a theme switch walks the live
#: widgets; the inspector's editors are created after the start-up switch, so without this their
#: fields keep clam's white background under a dark theme (QA-14a1-03).
DESIGNER_STYLES = (
    "TButton", "TCheckbutton", "TCombobox", "TEntry", "TFrame", "TLabel", "TLabelframe",
    "TNotebook", "TSpinbox", "Treeview", "Horizontal.TScrollbar", "Vertical.TScrollbar",
)  # fmt: skip
#: ttkbootstrap's own ghost button (its builder's output, never reconfigured): the toolbar.
GHOST_STYLE: Final = "Ghost.TButton"

# Designer-owned style names. None may contain a bootstyle keyword ("primary", "light",
# "outline", ...): ttkbootstrap parses style strings and would build its own look instead.
STYLE_HEADER: Final = "Designer.Header.TFrame"
STYLE_HEADER_LABEL: Final = "Designer.Header.TLabel"
STYLE_DIVIDER: Final = "Designer.Divider.TFrame"
STYLE_STAGE: Final = "Designer.Stage.TFrame"
STYLE_TITLEBAR: Final = "Designer.Titlebar.TFrame"
STYLE_TITLE_LABEL: Final = "Designer.Titlebar.TLabel"
STYLE_CAPTION: Final = "Designer.Caption.TLabel"
STYLE_STRIP: Final = "Designer.Strip.TLabel"
STYLE_SECTION: Final = "Designer.Section.TLabel"
STYLE_MUTED: Final = "Designer.Muted.TLabel"
STYLE_ERROR: Final = "Designer.Error.TLabel"
#: The designer's own fields (inspector, panels, dialogs): the base look, the theme's focus ring.
STYLE_ENTRY: Final = "Designer.TEntry"
STYLE_COMBOBOX: Final = "Designer.TCombobox"
STYLE_SPINBOX: Final = "Designer.TSpinbox"
#: Prefix of the invalid editor styles: ``f"{INVALID_PREFIX}.TEntry"`` and so on.
INVALID_PREFIX: Final = "Designer.Invalid"
#: The style of the designer's own lists; user Treeviews on the canvas keep the runtime look.
TREE_STYLE: Final = "Designer.Treeview"
#: The style of the dialogs' lists: they show the focus themselves (no panel ring around them).
LIST_STYLE: Final = "Designer.List.Treeview"

FONT_TITLE: Final = "PyGUIbudTitle"
FONT_HEADER: Final = "PyGUIbudHeader"
FONT_BODY: Final = "PyGUIbudBody"
FONT_CAPTION: Final = "PyGUIbudCaption"
#: (name, offset in points from TkDefaultFont, bold): the type scale (spec 14p 2, D6).
DESIGNER_FONTS: Final = (
    (FONT_TITLE, 2, True),
    (FONT_HEADER, 0, True),
    (FONT_BODY, 0, False),
    (FONT_CAPTION, -1, False),
)
_MIN_POINTS: Final = 7

#: Every ``Designer.*`` style :func:`apply_designer_styles` configures (the tests iterate it).
OWN_STYLES: Final = (
    STYLE_HEADER, STYLE_HEADER_LABEL, STYLE_DIVIDER, STYLE_STAGE, STYLE_TITLEBAR,
    STYLE_TITLE_LABEL, STYLE_CAPTION, STYLE_STRIP, STYLE_SECTION, STYLE_MUTED, STYLE_ERROR,
    STYLE_ENTRY, STYLE_SPINBOX, STYLE_COMBOBOX, f"{INVALID_PREFIX}.TEntry",
    f"{INVALID_PREFIX}.TSpinbox", f"{INVALID_PREFIX}.TCombobox", f"{INVALID_PREFIX}.TLabel",
    TREE_STYLE, LIST_STYLE,
)  # fmt: skip


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
    for name in (*DESIGNER_STYLES, GHOST_STYLE):  # idempotent: a built style is kept
        Bootstyle.update_ttk_widget_style(style_string=name)
    apply_theme(root, spec)
    apply_designer_styles(root, spec)


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


def menu_end(menu: tkinter.Menu) -> int | None:
    """The index of the last entry of ``menu``; None when it is empty.

    Tk 9 answers "" for an empty menu, which ``Menu.index`` of Python 3.10 cannot read
    (CPython GH-103685): with uv's Python 3.10 on Linux and macOS (Tk 9) the designer did not
    start (CI 20b.1)."""
    value = menu.tk.call(str(menu), "index", "end")
    return None if value in ("", "none") else int(menu.tk.getint(value))


def underline_of(value: object) -> int:
    """A read ``underline`` option as an index, -1 for none: Tk 9 answers "" when it is unset,
    where Tk 8.6 answered -1 (``int("")`` broke on Linux and macOS, CI 20b.1)."""
    text = str(value).strip()
    return int(text) if text.isdigit() else -1


def clear_menu(menu: tkinter.Menu) -> None:
    """Delete every entry; an empty menu stays as it is (``Menu.delete`` reads ``index`` too,
    see :func:`menu_end`)."""
    if menu_end(menu) is not None:
        menu.delete(0, "end")


def scaling_factor(root: tkinter.Misc) -> float:
    """The display's scale relative to 96 dpi (1.0, 1.25, 1.5, ...)."""
    return float(root.tk.call("tk", "scaling")) / (96 / 72)


def scaled(root: tkinter.Misc, pixels: int) -> int:
    """``pixels`` (designed for 96 dpi) scaled to the display's Tk scaling factor."""
    return max(1, round(pixels * scaling_factor(root)))


def space(root: tkinter.Misc, key: str) -> int:
    """A spacing step of :data:`SPACE` (``"xs"`` to ``"xl"``), scaled to the display."""
    return scaled(root, SPACE[key])


# ---------------------------------------------------------------- designer styling layer
def apply_designer_styles(root: tkinter.Misc, spec: ThemeSpec) -> None:
    """Configure the ``Designer.*`` styles and fonts for the current theme, then re-tint the
    icons. Runs on every switch: ``style.configure`` applies to the current theme only."""
    style = Style.get_instance()
    if style is None:
        return
    _designer_fonts(root)
    tokens = design_tokens(spec)
    fg, bg = spec.colors["fg"], spec.colors["bg"]
    xs, s, m, large = (space(root, key) for key in ("xs", "s", "m", "l"))
    conf = style.configure
    conf(STYLE_HEADER, background=tokens.header)
    conf(STYLE_HEADER_LABEL, background=tokens.header, foreground=fg, font=FONT_HEADER,
         padding=(large, s))  # fmt: skip
    conf(STYLE_DIVIDER, background=tokens.divider)
    conf(STYLE_STAGE, background=tokens.stage)
    conf(STYLE_TITLEBAR, background=tokens.titlebar)
    conf(STYLE_TITLE_LABEL, background=tokens.titlebar, foreground=tokens.titlebar_fg,
         font=FONT_TITLE)  # fmt: skip
    conf(STYLE_CAPTION, background=tokens.titlebar, foreground=tokens.muted, font=FONT_CAPTION)
    conf(STYLE_STRIP, background=bg, foreground=fg, padding=(m, xs))
    conf(STYLE_SECTION, background=tokens.header, foreground=fg, font=FONT_HEADER,
         padding=(s, xs))  # fmt: skip
    conf(STYLE_MUTED, foreground=tokens.muted, font=FONT_CAPTION)
    conf(STYLE_ERROR, foreground=tokens.error_text)
    _editor_styles(style, tokens)
    _focus_maps(style, tokens)
    icon_px = pick_size(16, scaling_factor(root))
    body = int(tkfont.nametofont(FONT_BODY, root=root).metrics("linespace"))
    conf(TREE_STYLE, rowheight=max(icon_px, body) + scaled(root, 6))
    from pyguibud.designer.icons_tk import icons  # icons_tk imports this module

    icons(root).retint(spec)


def _designer_fonts(root: tkinter.Misc) -> None:
    """Create or update the ``PyGUIbud*`` named fonts from ``TkDefaultFont``, in points so Tk
    scaling handles HiDPI (Tk has normal and bold only: the brand's "medium" is bold)."""
    base = tkfont.nametofont("TkDefaultFont", root=root).actual()
    size = int(base["size"])
    if size < 0:  # pixels: convert with Tk's pixels per point
        size = max(1, round(-size / float(root.tk.call("tk", "scaling"))))
    existing = set(tkfont.names(root))
    for name, offset, bold in DESIGNER_FONTS:
        # Plain Tcl: a tkinter ``Font`` object deletes its named font when it is collected.
        verb = "configure" if name in existing else "create"
        root.tk.call("font", verb, name, "-family", base["family"],
                     "-size", max(_MIN_POINTS, size + offset),
                     "-weight", "bold" if bold else "normal", "-slant", "roman")  # fmt: skip


def _editor_styles(style: Any, tokens: DesignTokens) -> None:  # noqa: ANN401 - ttkbootstrap
    """The inspector editors' normal and invalid looks; the user's ``TEntry`` is untouched.

    ttk resolves ``Designer.Invalid.TEntry`` via ``Invalid.TEntry`` to ``TEntry``, never via
    ``Designer.TEntry``, so the read-only map is repeated on the invalid styles. A derived map
    replaces the inherited one, so the theme's own field states are carried over.
    """
    for base in ("TEntry", "TSpinbox"):
        inherited = [tuple(map(str, entry)) for entry in style.map(base, "fieldbackground")]
        fill = [("readonly", tokens.readonly_bg), *(e for e in inherited if e[0] != "readonly")]
        style.map(f"Designer.{base}", fieldbackground=fill)
        style.map(f"{INVALID_PREFIX}.{base}", fieldbackground=fill)
    for base in ("TEntry", "TSpinbox", "TCombobox", "TLabel"):
        style.configure(f"{INVALID_PREFIX}.{base}", foreground=tokens.error_text)
    for base in ("TEntry", "TSpinbox", "TCombobox"):
        style.configure(f"{INVALID_PREFIX}.{base}", bordercolor=tokens.error_border)
        # The base map (focus colour on focus) outranks a derived style's configured value, and
        # clam draws the focus ring with the inner light/dark colours too: an invalid editor
        # keeps a (thicker) error ring when focused (QA-14p-08). Other states fall through to
        # the base map (the read-only fill).
        focus = [("focus", tokens.error_border)]
        style.map(f"{INVALID_PREFIX}.{base}", bordercolor=focus, lightcolor=focus, darkcolor=focus)


def _focus_maps(style: Any, tokens: DesignTokens) -> None:  # noqa: ANN401 - ttkbootstrap
    """The theme's focus colour, not ttkbootstrap's ``primary`` (2.84:1 on the field in the
    neutral dark theme, QA-19f-T02), on the editors and the dialog lists (QA-19f-T04). clam
    paints the border and its inner light and dark edges: the focus edge is 2 px, not 1 px."""
    for name, base in ((STYLE_ENTRY, "TEntry"), (STYLE_SPINBOX, "TSpinbox"),
                       (STYLE_COMBOBOX, "TCombobox"), (LIST_STYLE, "Treeview")):  # fmt: skip
        maps = {}
        for option in ("bordercolor", "lightcolor", "darkcolor"):
            inherited = [tuple(map(str, entry)) for entry in style.map(base, option)]
            maps[option] = [
                (*e[:-1], tokens.ring) if "focus" in e[:-1] and "invalid" not in e[:-1] else e
                for e in inherited
            ] or [("focus", "!disabled", tokens.ring)]
        style.map(name, **maps)
