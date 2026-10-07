"""Built-in neutral designer themes (MIT). The SAPE themes live in the generated ``sape.json``.

These hand-picked greys and blues are the fallback when ``sape.json`` is absent or defective
(for example in a fork). They pass the same contrast gate as the brand themes.
"""

from __future__ import annotations

from pyguibud.designer.theme import ThemeSpec

__all__ = ["NEUTRAL_SPECS"]

_SANS = ("Segoe UI", "Aptos", "Arial")
_MONO = ("Consolas", "Menlo", "DejaVu Sans Mono")

NEUTRAL_SPECS: tuple[ThemeSpec, ...] = (
    ThemeSpec(
        name="pyguibud-light",
        role="light",
        mode="light",
        colors={
            "primary": "#1A4FD6",
            "secondary": "#4B5563",
            "success": "#1B7A43",
            "info": "#0B5CAD",
            "warning": "#8A5300",
            "danger": "#B3261E",
            "light": "#E8EAED",
            "dark": "#1F2328",
            "bg": "#F5F6F8",
            "fg": "#1F2328",
            "selectbg": "#D6E4FF",
            "selectfg": "#1F2328",
            "border": "#6B7280",
            "inputfg": "#1F2328",
            "inputbg": "#FFFFFF",
            "active": "#FFFFFF",
        },
        focus="#1A4FD6",
        sans=_SANS,
        mono=_MONO,
    ),
    ThemeSpec(
        name="pyguibud-dark",
        role="dark",
        mode="dark",
        colors={
            "primary": "#2F5BE0",
            "secondary": "#4B5563",
            "success": "#1B7A43",
            "info": "#0B5CAD",
            "warning": "#8A5300",
            "danger": "#B3261E",
            "light": "#262B33",
            "dark": "#0B0D10",
            "bg": "#14171C",
            "fg": "#E6E8EB",
            "selectbg": "#22305F",
            "selectfg": "#E6E8EB",
            "border": "#8B9095",
            "inputfg": "#E6E8EB",
            "inputbg": "#1D2128",
            "active": "#262B33",
        },
        focus="#8FA8FF",
        sans=_SANS,
        mono=_MONO,
    ),
    ThemeSpec(
        name="pyguibud-hc",
        role="high_contrast",
        mode="light",
        colors={
            "primary": "#0A1A7A",
            "secondary": "#333333",
            "success": "#0B5A2E",
            "info": "#0A3F8F",
            "warning": "#6B3F00",
            "danger": "#8F1A14",
            "light": "#F0F0F0",
            "dark": "#000000",
            "bg": "#FFFFFF",
            "fg": "#000000",
            "selectbg": "#DCE6FF",
            "selectfg": "#000000",
            "border": "#000000",
            "inputfg": "#000000",
            "inputbg": "#FFFFFF",
            "active": "#FFFFFF",
        },
        focus="#0A1A7A",
        sans=_SANS,
        mono=_MONO,
    ),
)
