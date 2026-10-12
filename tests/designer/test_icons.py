"""Designer icons (spec 14p section 5): pure masks and PNG tinting, the Tk cache, the generator."""

from __future__ import annotations

import base64
import importlib.util
import logging
import struct
import zlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pyguibud.designer import icons as icons_module
from pyguibud.designer.icons import ICON_SIZES, load_masks, parse_masks, pick_size, tinted_png

ROOT = Path(__file__).resolve().parents[2]
ICON_DIR = ROOT / "src" / "pyguibud" / "designer" / "icons"
TOOLBAR = ("new", "open", "save", "undo", "redo", "cut", "copy", "paste", "delete")
STATES = ("error", "warning", "info", "ok", "lock", "reset")


@pytest.fixture
def fresh_masks() -> Any:
    load_masks.cache_clear()
    yield
    load_masks.cache_clear()


# ---------------------------------------------------------------- pure
def test_the_shipped_file_is_valid_and_complete() -> None:
    masks = load_masks()
    assert len(masks) == 50  # 48 + "preview" (Step 15a) + "export" (15b)
    assert set(TOOLBAR) | set(STATES) | {"puzzle", "window_main"} <= set(masks)
    for sizes in masks.values():
        assert sorted(sizes) == list(ICON_SIZES)
        assert all(any(mask) for mask in sizes.values())  # not blank
    assert (ICON_DIR / "LICENSE-tabler.txt").read_text(encoding="utf-8").startswith("MIT License")


@pytest.mark.parametrize(
    ("factor", "expected"), [(1.0, 16), (1.25, 20), (1.5, 24), (2.0, 32), (3.0, 32), (0.5, 16)]
)
def test_pick_size(factor: float, expected: int) -> None:
    assert pick_size(16, factor) == expected


def _decode(png: bytes) -> tuple[int, int, bytes]:
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    width, height = struct.unpack(">II", png[16:24])
    start = png.index(b"IDAT") + 4
    length = struct.unpack(">I", png[start - 8 : start - 4])[0]
    return width, height, zlib.decompress(png[start : start + length])


@pytest.mark.parametrize("size", ICON_SIZES)
def test_tinted_png_carries_the_colour_and_the_mask(size: int) -> None:
    mask = bytes(range(size)) * size
    width, height, raw = _decode(tinted_png(mask, size, "#1C3FF0"))
    assert (width, height) == (size, size)
    row = raw[: 1 + 4 * size]
    assert row[0] == 0  # filter "none"
    assert row[1:5] == bytes((0x1C, 0x3F, 0xF0, 0))
    assert row[-4:] == bytes((0x1C, 0x3F, 0xF0, size - 1))


@pytest.mark.parametrize(
    "payload",
    [
        b"not json",
        b'{"icons": []}',
        b'{"icons": {"x": {"16": "!!"}}}',
        b'{"icons": {"x": {"17": "' + base64.b64encode(zlib.compress(bytes(289))) + b'"}}}',
        b'{"icons": {"x": {"16": "' + base64.b64encode(zlib.compress(bytes(10))) + b'"}}}',
        b'{"icons": {"x": {"16": "' + base64.b64encode(zlib.compress(bytes(10**6))) + b'"}}}',
        b" " * (300 * 1024),
    ],
    ids=["text", "list", "base64", "size", "short", "bomb", "huge"],
)
def test_parse_rejects_defective_data(payload: bytes) -> None:
    with pytest.raises(ValueError):
        parse_masks(payload)


def test_a_defective_file_gives_text_only_and_one_log_line(
    fresh_masks: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(_text: object) -> dict[str, dict[int, bytes]]:
        raise ValueError("broken")

    monkeypatch.setattr(icons_module, "parse_masks", broken)
    with caplog.at_level(logging.WARNING, logger="pyguibud.designer.icons"):
        assert load_masks() == {}
        assert load_masks() == {}
    assert len(caplog.records) == 1


# ---------------------------------------------------------------- generator drift
def _generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_icons", ROOT / "tools" / "gen_icons.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    importlib.util.find_spec("resvg_py") is None
    or not (ROOT / "tools" / "icons-src" / "tabler").is_dir(),
    reason="the dev-only rasteriser or the icon sources are absent",
)
def test_icons_json_is_up_to_date() -> None:
    """Compares the decoded masks: compressed bytes may differ between zlib builds."""
    fresh = parse_masks(_generator().build())
    assert fresh == parse_masks((ICON_DIR / "icons.json").read_bytes())


# ---------------------------------------------------------------- Tk
@pytest.mark.gui
@pytest.mark.parametrize("size", ICON_SIZES)
def test_tinted_png_loads_in_tk(designer_root: Any, size: int) -> None:
    import tkinter

    png = tinted_png(load_masks()["save"][size], size, "#212832")
    image = tkinter.PhotoImage(master=designer_root, data=base64.b64encode(png).decode())
    assert (image.width(), image.height()) == (size, size)


@pytest.mark.gui
def test_cache_creates_each_image_once_and_unknown_is_none(designer_root: Any) -> None:
    from pyguibud.designer.icons_tk import icons

    cache = icons(designer_root)
    assert icons(designer_root) is cache
    assert cache.get("save") is cache.get("save")
    assert cache.get("save", disabled=True) is not cache.get("save")
    assert cache.get("no-such-icon") is None


@pytest.mark.gui
def test_without_masks_every_icon_is_none(
    designer_root: Any, fresh_masks: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer.icons_tk import IconCache

    monkeypatch.setattr(icons_module, "parse_masks", lambda _t: {})
    assert IconCache(designer_root).get("save") is None


@pytest.mark.gui
def test_rescale_resizes_in_place(designer_root: Any) -> None:
    from pyguibud.designer.icons_tk import IconCache

    cache = IconCache(designer_root)
    image = cache.get("open")
    assert image is not None
    scaling = designer_root.tk.call("tk", "scaling")
    try:
        for factor, size in ((1.25, 20), (1.0, 16), (2.0, 32), (1.0, 16)):
            designer_root.tk.call("tk", "scaling", factor * 96 / 72)
            cache.rescale()
            assert (image.width(), image.height()) == (size, size)
            assert cache.get("open") is image
    finally:
        designer_root.tk.call("tk", "scaling", scaling)
        cache.rescale()


@pytest.mark.gui
def test_theme_switches_and_rebuilds_do_not_grow_the_image_count(shell: Any) -> None:
    from pyguibud.core import read_ui

    shell.session.open_result(read_ui(ROOT / "examples" / "hello.ui"), name="hello")
    root = shell.root
    for role in ("dark", "high_contrast", "light"):
        shell.set_theme(role)
        shell.flush_theme()
    root.update_idletasks()
    before = len(root.tk.call("image", "names"))
    for role in ("dark", "high_contrast", "light") * 2:
        shell.set_theme(role)
        shell.flush_theme()
    for _ in range(100):
        shell.shell.canvas._render()
    root.update_idletasks()
    assert len(root.tk.call("image", "names")) == before


@pytest.mark.gui
def test_retint_follows_the_theme(shell: Any) -> None:
    from pyguibud.designer.icons_tk import icons
    from pyguibud.designer.theme import design_tokens, spec_for_role

    image = icons(shell.root).get("save")
    assert image is not None
    for role in ("dark", "light"):
        shell.set_theme(role)
        shell.flush_theme()
        spec = spec_for_role(shell.specs, role)
        assert spec is not None
        expected = design_tokens(spec).icon
        size = image.width()
        opaque = {
            "#{:02X}{:02X}{:02X}".format(*image.get(x, y))
            for x in range(size)
            for y in range(size)
            if not image.transparency_get(x, y)
        }
        assert opaque == {expected}
