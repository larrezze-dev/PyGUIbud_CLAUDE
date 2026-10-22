"""Designer theme data (pure: no Tk). Loads and validates the theme specs and checks contrast.

Two sources: the generated ``themes/sape.json`` (SAPE brand data, all rights reserved; see
NOTICE.md) and the built-in neutral MIT themes of :mod:`pyguibud.designer.themes`. A missing or
defective ``sape.json`` is logged and the neutral specs are used, so a fork that deletes the file
needs no code change.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib import resources
from types import MappingProxyType
from typing import Final, Literal

__all__ = [
    "COLOUR_KEYS",
    "ICON_FILE",
    "NON_TEXT_CONTRAST",
    "ROLES",
    "SPACE",
    "TEXT_CONTRAST",
    "DesignTokens",
    "ThemeSpec",
    "contrast",
    "design_tokens",
    "load_app_icon",
    "load_theme_specs",
    "parse_theme_data",
    "pick_family",
    "readable",
    "selection_colours",
    "spec_for_role",
    "tag_colours",
]

_log = logging.getLogger(__name__)

Role = Literal["light", "dark", "high_contrast"]
ROLES: Final[tuple[Role, ...]] = ("light", "dark", "high_contrast")

#: The 16 fields of ttkbootstrap's ``Colors``.
COLOUR_KEYS: Final[tuple[str, ...]] = (
    "primary",
    "secondary",
    "success",
    "info",
    "warning",
    "danger",
    "light",
    "dark",
    "bg",
    "fg",
    "selectbg",
    "selectfg",
    "border",
    "inputfg",
    "inputbg",
    "active",
)
_HEX = re.compile(r"#[0-9A-Fa-f]{6}")
MAX_JSON_BYTES: Final = 64 * 1024


@dataclass(frozen=True, slots=True)
class ThemeSpec:
    """One designer theme: exact colours, the focus-ring colour and font preferences."""

    name: str
    role: Role
    mode: Literal["light", "dark"]
    colors: Mapping[str, str]
    focus: str
    sans: tuple[str, ...]
    mono: tuple[str, ...]


# ---------------------------------------------------------------- contrast
def _linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def _luminance(colour: str) -> float:
    r, g, b = (int(colour[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def contrast(first: str, second: str) -> float:
    """WCAG 2.2 contrast ratio (1 to 21) of two ``#RRGGBB`` colours."""
    a, b = _luminance(first), _luminance(second)
    if a < b:
        a, b = b, a
    return (a + 0.05) / (b + 0.05)


#: WCAG 2.2 AA minimum for text.
TEXT_CONTRAST: Final = 4.5
#: WCAG 2.2 minimum for user-interface components and graphics (1.4.11).
NON_TEXT_CONTRAST: Final = 3.0


def _mix(first: str, second: str, amount: float) -> str:
    """``first`` moved ``amount`` (0 to 1) of the way towards ``second``."""
    channels = (
        round(int(first[i : i + 2], 16) * (1 - amount) + int(second[i : i + 2], 16) * amount)
        for i in (1, 3, 5)
    )
    return "#" + "".join(f"{value:02X}" for value in channels)


def readable(
    colour: str, backgrounds: Iterable[str], toward: str, minimum: float = TEXT_CONTRAST
) -> str:
    """``colour`` moved towards ``toward`` just enough to reach ``minimum`` on every background.

    Used for text tints (muted defaults, error rows) that would otherwise fall below AA in some
    themes, for example a dark grey "secondary" on a dark list (QA-12-01); non-text marks (a
    border, a drop target) pass ``minimum=NON_TEXT_CONTRAST``.
    """
    surfaces = tuple(backgrounds)
    for step in range(21):
        candidate = _mix(colour, toward, step / 20)
        if all(contrast(candidate, surface) >= minimum for surface in surfaces):
            return candidate
    return toward


def tag_colours(spec: ThemeSpec) -> dict[str, str]:
    """Foregrounds of the panels' row tags: readable on list rows and on selected rows."""
    colours = spec.colors
    rows = (colours["inputbg"], colours["selectbg"])
    return {
        "muted": readable(colours["secondary"], rows, colours["inputfg"]),
        "error": readable(colours["danger"], rows, colours["inputfg"]),
    }


# ---------------------------------------------------------------- design tokens
#: Spacing steps in px at 96 dpi (SAPE spacing.1-.4 plus a hairline); scale every use.
SPACE: Final[Mapping[str, int]] = MappingProxyType({"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16})
#: How far the canvas backdrop moves from ``bg`` towards ``fg``, per role.
_STAGE_TINT: Final[Mapping[str, float]] = {"light": 0.06, "dark": 0.10, "high_contrast": 0.0}


@dataclass(frozen=True, slots=True)
class DesignTokens:
    """The designer chrome's colour roles, derived from a theme's 16 colours (spec 14p 2)."""

    stage: str
    plate_border: str
    titlebar: str
    titlebar_fg: str
    header: str
    divider: str
    muted: str
    error_text: str
    error_border: str
    readonly_bg: str
    icon: str
    icon_disabled: str
    target_allowed: str
    target_denied: str
    ring: str


def design_tokens(spec: ThemeSpec) -> DesignTokens:
    """Derive the chrome colours of ``spec``; every gated pair passes by construction.

    Nothing is read from extra brand data (decision D1 (a)), so forks and the neutral themes
    follow the same rules. ``readable`` nudges a colour only where a theme needs it.
    """
    c = spec.colors
    bg, fg = c["bg"], c["fg"]
    hc = spec.role == "high_contrast"
    stage = _mix(bg, fg, _STAGE_TINT[spec.role])
    titlebar = bg if hc else _mix(bg, c["primary"], 0.08)
    header = readonly_bg = c["light"]
    # Every surface a designer label is painted on (readonly_bg is header).
    surfaces = (bg, c["inputbg"], c["selectbg"], header, titlebar)
    divider = c["border"] if hc else _mix(bg, c["border"], 0.45)
    # The error card (bg fill) sits on the plate (divider) inside the stage; the denied-drop
    # indicator on the stage: 3:1 against every one of them (H91, QA-14p-10).
    flanks = (c["inputbg"], bg, stage, divider)
    error_border = readable(c["danger"], flanks, fg, NON_TEXT_CONTRAST)
    if any(contrast(error_border, surface) < NON_TEXT_CONTRAST for surface in flanks):
        # High contrast: the divider is the text colour, so only a mid tone clears both ends.
        error_border = readable(c["danger"], flanks, bg, NON_TEXT_CONTRAST)
    return DesignTokens(
        stage=stage,
        plate_border=readable(c["border"], (stage, bg), fg, NON_TEXT_CONTRAST),
        titlebar=titlebar,
        titlebar_fg=fg,
        header=header,
        divider=divider,
        muted=readable(c["secondary"], surfaces, c["inputfg"]),
        error_text=readable(c["danger"], surfaces, fg),
        error_border=error_border,
        readonly_bg=readonly_bg,
        icon=fg,
        icon_disabled=_mix(fg, bg, 0.55),
        target_allowed=readable(c["primary"], (bg, stage, titlebar), fg, NON_TEXT_CONTRAST),
        target_denied=error_border,
        ring=readable(spec.focus, (bg, stage, titlebar, c["selectbg"]), fg, NON_TEXT_CONTRAST),
    )


#: Minimum contrast of a selected row against the list background (WCAG 2.2 non-text, 1.4.11).
ROW_CONTRAST: Final = 3.0


def selection_colours(spec: ThemeSpec) -> tuple[str, str]:
    """``(fill, text)`` of a selected list row (spec dnd-selection 10).

    ``fill`` is the first of ``selectbg``, ``primary`` and the focus colour that stands out from
    the list background by 3:1 (else the best of them); ``text`` is ``selectfg`` when it reads
    on ``fill`` (4.5:1), else white or black, whichever is stronger. Never a colour that only
    just passes: a mid grey on a dark fill reads as a disabled row (QA-13a-06).
    """
    colours = spec.colors
    candidates = (colours["selectbg"], colours["primary"], spec.focus)
    background = colours["inputbg"]
    fill = next(
        (c for c in candidates if contrast(c, background) >= ROW_CONTRAST),
        max(candidates, key=lambda c: contrast(c, background)),
    )
    text = colours["selectfg"]
    if contrast(text, fill) < TEXT_CONTRAST:
        text = max(("#FFFFFF", "#000000"), key=lambda c: contrast(c, fill))
    return fill, text


# ---------------------------------------------------------------- fonts
def pick_family(preferred: Iterable[str], available: Iterable[str]) -> str | None:
    """The first preferred family that is installed (case-insensitive), else None."""
    installed = {name.casefold() for name in available}
    for family in preferred:
        if family.casefold() in installed:
            return family
    return None


# ---------------------------------------------------------------- parsing
def _strings(value: object, what: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(v, str) and v.strip() for v in value)
    ):
        raise ValueError(f"{what} must be a non-empty list of font names")
    return tuple(str(v).strip() for v in value)


def _parse_spec(data: object) -> ThemeSpec:
    if not isinstance(data, dict):
        raise ValueError("a theme must be an object")
    name, role, mode = data.get("name"), data.get("role"), data.get("mode")
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,31}", name):
        raise ValueError(f"bad theme name {name!r}")
    if role not in ROLES:
        raise ValueError(f"bad role {role!r} in theme {name}")
    if mode not in ("light", "dark"):
        raise ValueError(f"bad mode {mode!r} in theme {name}")
    colours = data.get("colors")
    if not isinstance(colours, dict) or set(colours) != set(COLOUR_KEYS):
        raise ValueError(f"theme {name} must define exactly the colours {', '.join(COLOUR_KEYS)}")
    focus = data.get("focus")
    for value in (*colours.values(), focus):
        if not isinstance(value, str) or _HEX.fullmatch(value) is None:
            raise ValueError(f"bad colour {value!r} in theme {name}")
    return ThemeSpec(
        name=name,
        role=role,
        mode=mode,
        colors={key: str(colours[key]).upper() for key in COLOUR_KEYS},
        focus=str(focus).upper(),
        sans=_strings(data.get("sans"), "sans"),
        mono=_strings(data.get("mono"), "mono"),
    )


def parse_theme_data(text: str | bytes) -> tuple[ThemeSpec, ...]:
    """Parse and strictly validate a theme file (one spec per role).

    Raises:
        ValueError: the text is not valid JSON or any theme is defective.
    """
    if len(text) > MAX_JSON_BYTES:
        raise ValueError("theme data is too large")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    except RecursionError as exc:  # "[[[[..." nested deeper than Python allows (QA-12-05)
        raise ValueError("not valid JSON: nested too deeply") from exc
    themes = data.get("themes") if isinstance(data, dict) else None
    if not isinstance(themes, list):
        raise ValueError('the file must be an object with a "themes" list')
    specs = tuple(_parse_spec(item) for item in themes)
    if [spec.role for spec in specs] != list(ROLES):
        raise ValueError("the file must define the roles light, dark and high_contrast in order")
    if len({spec.name for spec in specs}) != len(specs):
        raise ValueError("duplicate theme names")
    return specs


_reported: set[str] = set()


def _warn_once(kind: str, message: str) -> None:
    """Log a brand-theme problem once per process and kind (spec 9), not on every reload."""
    if kind not in _reported:
        _reported.add(kind)
        _log.warning("%s", message)


def load_theme_specs(*, brand: bool = True) -> tuple[ThemeSpec, ...]:
    """The three themes: SAPE data if present and valid, else the neutral ones."""
    from pyguibud.designer.themes import NEUTRAL_SPECS

    if brand:
        try:
            resource = resources.files("pyguibud.designer.themes").joinpath("sape.json")
            if resource.is_file():
                return parse_theme_data(resource.read_bytes())
            _warn_once(
                "missing", "Brand themes file sape.json is missing, using the neutral themes"
            )
        except (OSError, ValueError) as exc:
            _warn_once("defective", f"Brand themes ignored, using the neutral themes: {exc}")
    return NEUTRAL_SPECS


ICON_FILE = "pyguibud.png"
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_ICON_BYTES = 1_000_000


def load_app_icon() -> bytes | None:
    """The PNG bytes of the brand application icon, or None (logged once) when absent or bad.

    Like ``sape.json`` the icon is SAPE brand data (NOTICE section 2): a fork deletes it and
    the window keeps ttkbootstrap's default icon.
    """
    try:
        resource = resources.files("pyguibud.designer.themes").joinpath(ICON_FILE)
        if not resource.is_file():
            _warn_once("icon_missing", f"Brand icon {ICON_FILE} is missing, using the default")
            return None
        data = resource.read_bytes()
    except OSError as exc:
        _warn_once("icon_defective", f"Brand icon ignored: {exc}")
        return None
    if not data.startswith(_PNG_SIGNATURE) or len(data) > _MAX_ICON_BYTES:
        _warn_once("icon_defective", f"Brand icon ignored: {ICON_FILE} is not a small PNG image")
        return None
    return data


def spec_for_role(specs: Iterable[ThemeSpec], role: str) -> ThemeSpec | None:
    """The spec of ``role``, or None for an unknown role."""
    return next((spec for spec in specs if spec.role == role), None)
