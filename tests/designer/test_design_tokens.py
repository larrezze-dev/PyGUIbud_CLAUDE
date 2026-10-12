"""Design tokens of step 14p (pure): every contrast gate of spec section 2, for all six themes."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from pyguibud.designer.theme import (
    NON_TEXT_CONTRAST,
    SPACE,
    TEXT_CONTRAST,
    DesignTokens,
    ThemeSpec,
    contrast,
    design_tokens,
    load_theme_specs,
    readable,
)

ROOT = Path(__file__).resolve().parents[2]
DESIGNER = ROOT / "src" / "pyguibud" / "designer"


def _six_specs() -> list[ThemeSpec]:
    return [*load_theme_specs(), *load_theme_specs(brand=False)]


def _id(spec: ThemeSpec) -> str:
    return spec.name


def _text_surfaces(spec: ThemeSpec, tokens: DesignTokens) -> tuple[str, ...]:
    colours = spec.colors
    return (
        colours["bg"],
        colours["inputbg"],
        colours["selectbg"],
        tokens.header,
        tokens.titlebar,
        tokens.readonly_bg,
    )


def test_six_distinct_specs_are_checked() -> None:
    assert len({spec.name for spec in _six_specs()}) == 6


@pytest.mark.parametrize("spec", _six_specs(), ids=_id)
def test_every_gate_of_the_token_table(spec: ThemeSpec) -> None:
    c, t = spec.colors, design_tokens(spec)
    surfaces = _text_surfaces(spec, t)
    assert contrast(c["border"], t.stage) >= NON_TEXT_CONTRAST
    assert contrast(t.plate_border, t.stage) >= NON_TEXT_CONTRAST
    assert contrast(t.titlebar_fg, t.titlebar) >= TEXT_CONTRAST
    assert contrast(c["fg"], t.header) >= TEXT_CONTRAST
    assert contrast(c["inputfg"], t.readonly_bg) >= TEXT_CONTRAST
    for surface in surfaces:
        assert contrast(t.muted, surface) >= TEXT_CONTRAST, surface
        assert contrast(t.error_text, surface) >= TEXT_CONTRAST, surface
    for surface in (c["inputbg"], c["bg"], t.stage):
        assert contrast(t.error_border, surface) >= NON_TEXT_CONTRAST
    for surface in (c["bg"], t.header):
        assert contrast(t.icon, surface) >= TEXT_CONTRAST
    for surface in (c["bg"], t.stage, t.titlebar):
        assert contrast(t.target_allowed, surface) >= NON_TEXT_CONTRAST
    for surface in (c["bg"], t.stage):
        assert contrast(t.target_denied, surface) >= NON_TEXT_CONTRAST
    for surface in (c["bg"], t.stage, t.titlebar, c["selectbg"]):
        assert contrast(t.ring, surface) >= NON_TEXT_CONTRAST


@pytest.mark.parametrize("spec", _six_specs(), ids=_id)
def test_tokens_are_hex_colours_and_stage_differs_except_in_high_contrast(spec: ThemeSpec) -> None:
    tokens = design_tokens(spec)
    for value in (getattr(tokens, name) for name in DesignTokens.__slots__):
        assert re.fullmatch(r"#[0-9A-F]{6}", value), value
    assert (tokens.stage == spec.colors["bg"]) == (spec.role == "high_contrast")
    assert tokens.target_denied == tokens.error_border


def test_readable_with_a_non_text_minimum() -> None:
    grey = "#9A9A9A"
    assert contrast(grey, "#FFFFFF") < NON_TEXT_CONTRAST
    nudged = readable(grey, ("#FFFFFF",), "#000000", minimum=NON_TEXT_CONTRAST)
    assert NON_TEXT_CONTRAST <= contrast(nudged, "#FFFFFF") < TEXT_CONTRAST
    text = readable(grey, ("#FFFFFF",), "#000000")
    assert contrast(text, "#FFFFFF") >= TEXT_CONTRAST
    assert readable("#000000", ("#FFFFFF",), "#FFFFFF", minimum=3.0) == "#000000"  # unchanged


def test_readable_falls_back_to_the_target() -> None:
    assert readable("#777777", ("#777777",), "#787878") == "#787878"


def test_space_scale() -> None:
    assert dict(SPACE) == {"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16}
    with pytest.raises(TypeError):
        SPACE["xs"] = 3  # type: ignore[index]


# ---------------------------------------------------------------- no hard-coded colours (test 4)
_COLOUR = re.compile(r"#[0-9A-Fa-f]{3}|#[0-9A-Fa-f]{6}")
_NAMES = frozenset(
    {"white", "black", "red", "green", "blue", "yellow", "grey", "gray", "orange", "silver"}
)
_EXEMPT = ("theme.py", "themes")
_MSGID_CALLS = frozenset({"_", "N_", "NP_"})


def _literals(tree: ast.AST) -> list[ast.Constant]:
    skipped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) in _MSGID_CALLS:
            skipped.update(id(arg) for arg in node.args)
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in skipped
    ]


def _offenders(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        f"{path.relative_to(DESIGNER)}:{node.lineno}: {node.value!r}"
        for node in _literals(tree)
        if isinstance(node.value, str)
        and (_COLOUR.fullmatch(node.value) or node.value.lower() in _NAMES)
    ]


def test_no_hard_coded_colours_in_the_designer() -> None:
    found: list[str] = []
    for path in sorted(DESIGNER.rglob("*.py")):
        if path.relative_to(DESIGNER).parts[0] in _EXEMPT:
            continue
        found += _offenders(path)
    assert found == []
