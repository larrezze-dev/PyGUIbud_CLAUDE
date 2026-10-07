"""Theme data (pure): schema, strict loading, the contrast gate and the generator's drift test."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

from pyguibud.designer import theme as theme_module
from pyguibud.designer.theme import (
    COLOUR_KEYS,
    ICON_FILE,
    ROLES,
    ThemeSpec,
    contrast,
    load_app_icon,
    load_theme_specs,
    parse_theme_data,
    pick_family,
    selection_colours,
    spec_for_role,
)
from pyguibud.designer.themes import NEUTRAL_SPECS

ROOT = Path(__file__).resolve().parents[2]
SAPE_JSON = ROOT / "src" / "pyguibud" / "designer" / "themes" / "sape.json"
TOKENS = ROOT / "assets" / "brand" / "tokens"
ICON_PNG = SAPE_JSON.with_name(ICON_FILE)
ICON_SOURCE = ROOT / "assets" / "brand" / "logo" / ICON_FILE
_FILES = "pyguibud.designer.theme.resources.files"  # the resource lookup the loaders use
ACCENTS = ("primary", "secondary", "success", "info", "warning", "danger")


def _all_specs() -> list[ThemeSpec]:
    specs = list(NEUTRAL_SPECS)
    if SAPE_JSON.exists():
        specs += parse_theme_data(SAPE_JSON.read_bytes())
    return specs


def _spec_id(spec: ThemeSpec) -> str:
    return spec.name


# ---------------------------------------------------------------- contrast maths
def test_contrast_known_values() -> None:
    assert contrast("#000000", "#FFFFFF") == pytest.approx(21.0)
    assert contrast("#FFFFFF", "#FFFFFF") == pytest.approx(1.0)
    assert contrast("#777777", "#FFFFFF") == pytest.approx(4.48, abs=0.01)


def test_contrast_is_symmetric() -> None:
    assert contrast("#1C3FF0", "#F8FAFC") == contrast("#F8FAFC", "#1C3FF0")


def test_contrast_agrees_with_ttkbootstrap() -> None:
    from ttkbootstrap.style.theme import _contrast_ratio

    for first, second in (("#1C3FF0", "#FFFFFF"), ("#117047", "#FFFFFF"), ("#333C48", "#050608")):
        assert contrast(first, second) == pytest.approx(_contrast_ratio(first, second), abs=0.01)


# ---------------------------------------------------------------- the gate (WCAG 2.2 AA)
@pytest.mark.parametrize("spec", _all_specs(), ids=_spec_id)
def test_text_contrast_gate(spec: ThemeSpec) -> None:
    c = spec.colors
    assert contrast(c["fg"], c["bg"]) >= 4.5
    assert contrast(c["inputfg"], c["inputbg"]) >= 4.5
    assert contrast(c["selectfg"], c["selectbg"]) >= 4.5


@pytest.mark.parametrize("spec", _all_specs(), ids=_spec_id)
def test_non_text_contrast_gate(spec: ThemeSpec) -> None:
    c = spec.colors
    assert contrast(c["border"], c["bg"]) >= 3.0
    assert contrast(spec.focus, c["bg"]) >= 3.0
    assert contrast(spec.focus, c["selectbg"]) >= 3.0


@pytest.mark.parametrize("spec", _all_specs(), ids=_spec_id)
@pytest.mark.parametrize("accent", ACCENTS)
def test_painted_button_text_contrast_gate(spec: ThemeSpec, accent: str) -> None:
    """The colour ttkbootstrap really paints on a filled button (not the token's text colour)."""
    from ttkbootstrap.style.theme import _accent_on_color

    fill = spec.colors[accent]
    assert contrast(_accent_on_color(fill), fill) >= 4.5, f"{spec.name}.{accent} {fill}"


@pytest.mark.skipif(not TOKENS.is_dir(), reason="brand tokens are not in this checkout")
def test_sape_primary_text_token_on_primary() -> None:
    spec: dict[str, ThemeSpec] = {s.role: s for s in parse_theme_data(SAPE_JSON.read_bytes())}
    for role, file in (
        ("light", "sape.light.tokens.json"),
        ("dark", "sape.dark.tokens.json"),
        ("high_contrast", "sape.high-contrast.tokens.json"),
    ):
        text = json.loads((TOKENS / file).read_text(encoding="utf-8"))
        token = text["color"]["action"]["primary"]["text"]["$value"]
        assert contrast(token, spec[role].colors["primary"]) >= 4.5


# ---------------------------------------------------------------- schema
@pytest.mark.parametrize("spec", _all_specs(), ids=_spec_id)
def test_spec_schema(spec: ThemeSpec) -> None:
    assert set(spec.colors) == set(COLOUR_KEYS)
    assert spec.mode in ("light", "dark")
    assert spec.role in ROLES
    assert spec.sans and spec.mono


def test_neutral_specs_cover_every_role_once() -> None:
    assert [s.role for s in NEUTRAL_SPECS] == list(ROLES)
    assert [s.name for s in NEUTRAL_SPECS] == ["pyguibud-light", "pyguibud-dark", "pyguibud-hc"]
    assert NEUTRAL_SPECS[2].mode == "light"  # high contrast is a light variant


def test_shipped_sape_json_is_valid_and_named() -> None:
    specs = parse_theme_data(SAPE_JSON.read_bytes())
    assert [s.name for s in specs] == ["sape-light", "sape-dark", "sape-hc"]
    assert "All rights reserved" in json.loads(SAPE_JSON.read_text(encoding="utf-8"))["_licence"]


def test_spec_for_role() -> None:
    assert spec_for_role(NEUTRAL_SPECS, "dark") is NEUTRAL_SPECS[1]
    assert spec_for_role(NEUTRAL_SPECS, "neon") is None


# ---------------------------------------------------------------- strict loading
def _good() -> dict[str, object]:
    themes = [_as_dict(s) for s in NEUTRAL_SPECS]
    data: dict[str, object] = json.loads(json.dumps({"themes": themes}))
    return data


def _as_dict(spec: ThemeSpec) -> dict[str, object]:
    return {
        "name": spec.name,
        "role": spec.role,
        "mode": spec.mode,
        "colors": dict(spec.colors),
        "focus": spec.focus,
        "sans": list(spec.sans),
        "mono": list(spec.mono),
    }


def test_parse_accepts_well_formed_data() -> None:
    assert [s.role for s in parse_theme_data(json.dumps(_good()))] == list(ROLES)


def _break_colour(data: dict[str, object]) -> None:
    data["themes"][0]["colors"]["bg"] = "red"  # type: ignore[index]


def _drop_colour(data: dict[str, object]) -> None:
    del data["themes"][1]["colors"]["fg"]  # type: ignore[index]


def _extra_colour(data: dict[str, object]) -> None:
    data["themes"][1]["colors"]["extra"] = "#000000"  # type: ignore[index]


def _bad_mode(data: dict[str, object]) -> None:
    data["themes"][0]["mode"] = "sepia"  # type: ignore[index]


def _bad_role(data: dict[str, object]) -> None:
    data["themes"][0]["role"] = "neon"  # type: ignore[index]


def _bad_name(data: dict[str, object]) -> None:
    data["themes"][0]["name"] = "Bad Name!"  # type: ignore[index]


def _no_fonts(data: dict[str, object]) -> None:
    data["themes"][0]["sans"] = []  # type: ignore[index]


def _bad_focus(data: dict[str, object]) -> None:
    data["themes"][2]["focus"] = "#12345"  # type: ignore[index]


def _missing_role(data: dict[str, object]) -> None:
    del data["themes"][2]  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "damage",
    [
        _break_colour,
        _drop_colour,
        _extra_colour,
        _bad_mode,
        _bad_role,
        _bad_name,
        _no_fonts,
        _bad_focus,
        _missing_role,
    ],
)
def test_parse_rejects_defects(damage: object) -> None:
    data = _good()
    damage(data)  # type: ignore[operator]
    with pytest.raises(ValueError):
        parse_theme_data(json.dumps(data))


@pytest.mark.parametrize("text", ["", "{", "[]", '{"themes": 3}', "\x00\xff", '{"themes": [3]}'])
def test_parse_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError):
        parse_theme_data(text)


def test_parse_rejects_binary_and_oversized_input() -> None:
    with pytest.raises(ValueError):
        parse_theme_data(b"\xff\xfe\x00")
    with pytest.raises(ValueError):
        parse_theme_data(" " * (theme_module.MAX_JSON_BYTES + 1))


def test_colours_are_normalised_to_upper_case() -> None:
    data = _good()
    data["themes"][0]["colors"]["bg"] = "#f5f6f8"  # type: ignore[index]
    assert parse_theme_data(json.dumps(data))[0].colors["bg"] == "#F5F6F8"


# ---------------------------------------------------------------- fallback to neutral
class _FakeTree:
    """``importlib.resources.files`` stand-in: a directory holding a (possibly bad) sape.json."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def joinpath(self, name: str) -> Path:
        return self.folder / name


@pytest.fixture(autouse=True)
def _fresh_log_memory() -> None:
    """Brand-file problems are logged once per process: forget earlier ones for each test."""
    theme_module._reported.clear()


def test_load_uses_the_brand_file_when_valid() -> None:
    assert [s.name for s in load_theme_specs()] == ["sape-light", "sape-dark", "sape-hc"]


def test_load_brand_false_is_neutral() -> None:
    assert load_theme_specs(brand=False) == NEUTRAL_SPECS


def test_missing_sape_json_gives_neutral(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_FILES, lambda _pkg: _FakeTree(tmp_path))
    with caplog.at_level("WARNING"):
        assert load_theme_specs() == NEUTRAL_SPECS
        assert load_theme_specs() == NEUTRAL_SPECS
    # Spec 9 (QA-12-11): a missing file logs exactly once per process, like a defective one.
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "missing" in warnings[0].getMessage()


def test_defective_sape_json_logs_once_per_process(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (tmp_path / "sape.json").write_bytes(b"{")
    monkeypatch.setattr(_FILES, lambda _pkg: _FakeTree(tmp_path))
    with caplog.at_level("WARNING"):
        for _ in range(3):
            assert load_theme_specs() == NEUTRAL_SPECS
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


@pytest.mark.parametrize("content", [b"{", b"", b'{"themes": []}', "truncated"])
def test_corrupt_sape_json_gives_neutral_and_logs_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    content: bytes | str,
) -> None:
    if content == "truncated":  # read here, not at import (QA-12-14: no collection crash)
        content = SAPE_JSON.read_bytes()[:200]
    assert isinstance(content, bytes)
    (tmp_path / "sape.json").write_bytes(content)
    monkeypatch.setattr(_FILES, lambda _pkg: _FakeTree(tmp_path))
    with caplog.at_level("WARNING"):
        assert load_theme_specs() == NEUTRAL_SPECS
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


# ---------------------------------------------------------------- application icon
def test_load_app_icon_returns_the_shipped_png() -> None:
    data = load_app_icon()
    assert data is not None
    assert data == ICON_PNG.read_bytes()
    assert data.startswith(b"\x89PNG\r\n\x1a\n")


def test_missing_icon_gives_none_and_logs_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(_FILES, lambda _pkg: _FakeTree(tmp_path))
    with caplog.at_level("WARNING"):
        assert load_app_icon() is None
        assert load_app_icon() is None
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "missing" in warnings[0].getMessage()


@pytest.mark.parametrize(
    "content",
    [b"", b"GIF89a", b"\x89PNG\r\n\x1a\n" + b"\0" * 1_000_001],
    ids=["empty", "not-png", "too-big"],
)
def test_defective_icon_gives_none_and_logs_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    content: bytes,
) -> None:
    (tmp_path / ICON_FILE).write_bytes(content)
    monkeypatch.setattr(_FILES, lambda _pkg: _FakeTree(tmp_path))
    with caplog.at_level("WARNING"):
        assert load_app_icon() is None
        assert load_app_icon() is None
    assert len([r for r in caplog.records if r.levelname == "WARNING"]) == 1


@pytest.mark.skipif(not ICON_SOURCE.is_file(), reason="brand logo is not in this checkout")
def test_shipped_icon_is_a_copy_of_the_brand_logo() -> None:
    assert ICON_PNG.read_bytes() == ICON_SOURCE.read_bytes()


# ---------------------------------------------------------------- fonts
def test_pick_family_takes_the_first_installed() -> None:
    assert pick_family(["IBM Plex Sans", "Segoe UI"], ["Arial", "Segoe UI"]) == "Segoe UI"
    assert pick_family(["IBM Plex Sans", "Segoe UI"], ["ibm plex sans"]) == "IBM Plex Sans"


def test_pick_family_returns_none_when_nothing_is_installed() -> None:
    assert pick_family(["IBM Plex Sans"], ["Arial"]) is None
    assert pick_family([], ["Arial"]) is None


# ---------------------------------------------------------------- generator drift
def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_themes", ROOT / "tools" / "gen_themes.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not TOKENS.is_dir(), reason="brand tokens are not in this checkout")
def test_sape_json_is_up_to_date_with_the_tokens() -> None:
    assert SAPE_JSON.read_text(encoding="utf-8") == _generator().build(TOKENS)


@pytest.mark.skipif(not TOKENS.is_dir(), reason="brand tokens are not in this checkout")
def test_generator_check_mode() -> None:
    assert _generator().main(["--check"]) == 0


# ---------------------------------------------------------------- selected rows (spec 10)
def _six_specs() -> list[ThemeSpec]:
    return [*load_theme_specs(), *load_theme_specs(brand=False)]


@pytest.mark.parametrize("spec", _six_specs(), ids=_spec_id)
def test_selected_row_stands_out_and_reads(spec: ThemeSpec) -> None:
    fill, text = selection_colours(spec)
    assert contrast(fill, spec.colors["inputbg"]) >= 3.0  # WCAG 1.4.11
    assert contrast(text, fill) >= 4.5  # WCAG 1.4.3
    # QA-13a-06: the theme's own selectfg when it reads, else the strongest of white and black
    # (never a grey nudged just past 4.5:1, which looks like a disabled row).
    if text != spec.colors["selectfg"]:
        best = max(contrast("#FFFFFF", fill), contrast("#000000", fill))
        assert contrast(text, fill) == best


def test_high_contrast_selected_rows_use_white_text() -> None:
    """QA-13a-06: #999999 on the dark-blue HC fill looked disabled."""
    for spec in _six_specs():
        if spec.role == "high_contrast":
            fill, text = selection_colours(spec)
            assert (text, contrast(text, fill) > 10) == ("#FFFFFF", True), spec.name


def test_the_gate_covers_both_families() -> None:
    assert len({s.name for s in _six_specs()}) == 6
