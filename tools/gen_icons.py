"""Generate ``src/pyguibud/designer/icons/icons.json`` from Tabler Icons SVGs (dev tool).

Usage: ``uv run python tools/gen_icons.py [--check]``. ``--check`` exits 1 when the committed
file differs from a fresh generation (a test does the same; it is skipped without the
rasteriser). The output is deterministic.

The sources are Tabler Icons (MIT, (c) Pawel Kuna, https://github.com/tabler/tabler-icons,
commit a4ce1404), copied verbatim into ``tools/icons-src/tabler`` with their licence. They are
rasterised by ``resvg-py`` (MIT binding of resvg; a static extension, no system library such as
cairo), a dev-only dependency: the designer itself only reads the generated masks
(ADR-012, spec 14p section 5).
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "tools" / "icons-src" / "tabler"
TARGET = ROOT / "src" / "pyguibud" / "designer" / "icons" / "icons.json"
SIZES = (16, 20, 24, 32)
#: Stroke width (in the 24-unit view box) per size: about 1 px lines at 16 px stay crisp.
STROKES = {16: "1.5", 20: "1.75", 24: "2", 32: "2"}
LICENCE = "Tabler Icons, MIT, (c) Pawel Kuna; see LICENSE-tabler.txt. Made by tools/gen_icons.py."

#: Our icon name -> Tabler outline icon (spec 14p section 5).
ICONS = {
    # toolbar
    "new": "file-plus", "open": "folder-open", "save": "device-floppy",
    "undo": "arrow-back-up", "redo": "arrow-forward-up", "cut": "scissors", "copy": "copy",
    "paste": "clipboard", "delete": "trash", "preview": "player-play", "export": "file-export",
    # containers
    "Frame": "square", "LabelFrame": "box-margin", "Notebook": "layout-navbar",
    "PanedWindow": "layout-columns", "ScrolledFrame": "layout-sidebar-right",
    # widgets
    "Label": "letter-t", "Button": "click", "Entry": "forms", "Text": "align-left",
    "Checkbutton": "checkbox", "Radiobutton": "circle-dot", "Combobox": "selector",
    "Spinbox": "arrows-up-down", "Scale": "adjustments-horizontal", "Progressbar": "progress",
    "Separator": "separator-horizontal", "Listbox": "list", "Treeview": "list-tree",
    "Scrollbar": "arrows-vertical", "Canvas": "brush",
    # menus
    "Menubar": "menu-2", "Menu": "menu", "Action": "point", "separator": "separator",
    "Statusbar": "layout-bottombar",
    # ttkbootstrap extensions
    "Meter": "gauge", "Floodgauge": "battery-2", "DateEntry": "calendar",
    # windows and other nodes ("message-square" does not exist in Tabler: "message-2")
    "window_main": "app-window", "window_dialog": "message-2", "window_component": "components",
    "include": "link", "puzzle": "puzzle",
    # states
    "error": "alert-circle", "warning": "alert-triangle", "info": "info-circle",
    "ok": "circle-check", "lock": "lock", "reset": "restore",
}  # fmt: skip


def _alpha(svg: str, size: int) -> bytes:
    import resvg_py  # dev-only dependency
    from PIL import Image

    markup = svg.replace("currentColor", "#000000")
    markup = markup.replace('stroke-width="2"', f'stroke-width="{STROKES[size]}"', 1)
    png = resvg_py.svg_to_bytes(svg_string=markup, width=size, height=size)
    with Image.open(io.BytesIO(bytes(png))) as image:
        alpha = image.convert("RGBA").getchannel("A").tobytes()
    if len(alpha) != size * size:
        raise ValueError(f"unexpected raster size for {size} px")
    return alpha


def build() -> str:
    """The JSON text of the icon file."""
    icons: dict[str, dict[str, str]] = {}
    for name, source in sorted(ICONS.items()):
        svg = (SOURCES / f"{source}.svg").read_text(encoding="utf-8")
        icons[name] = {
            str(size): base64.b64encode(zlib.compress(_alpha(svg, size), 9)).decode("ascii")
            for size in SIZES
        }
    data = {"_licence": LICENCE, "sizes": list(SIZES), "icons": icons}
    return json.dumps(data, indent=0, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when the file is out of date")
    args = parser.parse_args(argv)
    data = build().encode("utf-8")
    if args.check:
        if not TARGET.exists() or TARGET.read_bytes() != data:
            print(f"{TARGET} is out of date; run tools/gen_icons.py", file=sys.stderr)
            return 1
        return 0
    TARGET.write_bytes(data)
    print(f"wrote {TARGET} ({len(data)} bytes, {len(ICONS)} icons)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
