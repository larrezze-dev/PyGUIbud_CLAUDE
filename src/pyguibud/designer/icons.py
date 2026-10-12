"""The designer's icon data (pure: no Tk): alpha masks tinted into PNG bytes at runtime.

The masks are Tabler Icons (MIT, NOTICE section 4) rasterised at dev time by
``tools/gen_icons.py`` into ``icons/icons.json``. One mask serves every theme: the tint is the
theme's icon colour. A missing or defective file is logged once and the designer shows text.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import struct
import zlib
from collections.abc import Mapping
from functools import cache
from importlib import resources
from typing import Final

__all__ = ["ICON_SIZES", "load_masks", "pick_size", "tinted_png"]

_log = logging.getLogger(__name__)

ICON_SIZES: Final = (16, 20, 24, 32)
DATA_FILE: Final = "icons.json"
_MAX_BYTES: Final = 256 * 1024


def pick_size(base_px: int, factor: float) -> int:
    """The smallest mask size of at least ``base_px * factor``, else the largest."""
    wanted = base_px * factor - 0.05  # Tk stores its scaling rounded (1.25 reads 1.2500002)
    return next((size for size in ICON_SIZES if size >= wanted), ICON_SIZES[-1])


def _unpack(blob: str) -> bytes:
    """One mask; inflation stops past the largest valid mask (no zip bomb)."""
    limit = ICON_SIZES[-1] ** 2 + 1
    return zlib.decompressobj().decompress(base64.b64decode(blob, validate=True), limit)


def parse_masks(text: str | bytes) -> dict[str, dict[int, bytes]]:
    """Decode and strictly validate the icon file.

    Raises:
        ValueError: too large, not JSON (including nesting too deep for the decoder), or a mask
            of the wrong size.
    """
    if len(text) > _MAX_BYTES:
        raise ValueError("icon data is too large")
    try:
        data = json.loads(text)
        icons = data["icons"]
        result = {
            str(name): {int(size): _unpack(blob) for size, blob in sizes.items()}
            for name, sizes in icons.items()
        }
    except (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RecursionError,  # json's decoder recurses per nesting level: ``[[[[...]]]]`` (QA-14p-07)
        zlib.error,
        binascii.Error,
    ) as exc:
        raise ValueError(f"defective icon data: {exc}") from exc
    for name, sizes in result.items():
        for size, mask in sizes.items():
            if size not in ICON_SIZES or len(mask) != size * size:
                raise ValueError(f"icon {name!r} has a bad {size} px mask")
    return result


@cache
def load_masks() -> Mapping[str, Mapping[int, bytes]]:
    """``{name: {size: alpha bytes}}``, or ``{}`` (logged once) when the file is absent or bad."""
    try:
        resource = resources.files("pyguibud.designer").joinpath("icons").joinpath(DATA_FILE)
        return parse_masks(resource.read_bytes())
    except (OSError, ValueError) as exc:
        _log.warning("Designer icons unavailable, showing text only: %s", exc)
        return {}


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))


def tinted_png(mask: bytes, size: int, colour: str) -> bytes:
    """An RGBA PNG of ``size`` x ``size`` pixels: ``colour`` (``#RRGGBB``) with ``mask`` as alpha.

    Built row by row with filter 0 (no per-pixel Tk calls).
    """
    rgb = bytes.fromhex(colour[1:7])
    rows = bytearray()
    for y in range(size):
        rows.append(0)
        for alpha in mask[y * size : (y + 1) * size]:
            rows += rgb
            rows.append(alpha)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            _chunk(b"IHDR", header),
            _chunk(b"IDAT", zlib.compress(bytes(rows))),
            _chunk(b"IEND", b""),
        )
    )
