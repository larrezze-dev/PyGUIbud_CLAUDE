"""Disk access for the file rules of the validator (spec ``docs/specs/runtime.md`` 9.1).

The validator never touches the disk by itself; it asks an injected ``FileAccess`` (a protocol in
:mod:`pyguibud.core.validate`). :class:`DiskFiles` is the implementation for real files. It is
stdlib-only and toolkit-free: images are never decoded here; their headers are read, and the
chunk structure (PNG) or raster length (PPM/PGM) is checked so that Tk can load what passes.
"""

from __future__ import annotations

import io
import os
import re
import zlib
from dataclasses import dataclass
from typing import BinaryIO, Final, Literal

from pyguibud.core.errors import XmlIoError
from pyguibud.core.xml_io import ReadResult, read_ui
from pyguibud.i18n import N_

__all__ = [
    "IMAGE_SUFFIXES",
    "MAX_EXPANDED_NODES",
    "MAX_IMAGE_BYTES",
    "MAX_IMAGE_SIDE",
    "MAX_INCLUDE_DEPTH",
    "MAX_INCLUDE_FILES",
    "WINDOWS_DEVICE_NAMES",
    "DiskFiles",
    "ImageProbe",
    "is_device_name",
    "is_network_or_device_path",
    "probe_bytes",
]

MAX_INCLUDE_DEPTH: Final = 8  # levels of nested includes
MAX_INCLUDE_FILES: Final = 32  # distinct files read for one validation, the root included
MAX_EXPANDED_NODES: Final = 10_000  # widgets and includes instantiated through includes
MAX_IMAGE_BYTES: Final = 16 * 1024 * 1024
MAX_IMAGE_SIDE: Final = 4096  # pixels, each side
IMAGE_SUFFIXES: Final = (".png", ".gif", ".ppm", ".pgm")  # decoded natively by Tk, no Pillow

#: Win32 device names: a path segment named so (with any extension, trailing dots or spaces, in
#: any letter case) opens the device, not a file.
WINDOWS_DEVICE_NAMES: Final = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$", "CLOCK$"}
    | {f"{port}{n}" for port in ("COM", "LPT") for n in (*"0123456789", "¹", "²", "³")}
)
# UNC: two leading separators (which also covers the Win32 namespaces), or the NT prefix.
_NETWORK_OR_DEVICE_RE: Final = re.compile(r"[\\/]{2}|[\\/]\?\?[\\/]")
_SEPARATORS_RE: Final = re.compile(r"[\\/]+")

_HEADER_BYTES: Final = 64
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_GIF_SCREEN_END: Final = 13  # header (6) + logical screen descriptor (7)
_NETPBM_MAGICS: Final = (b"P5", b"P6")  # binary only: Tk 8.6 cannot read plain P2/P3
_NETPBM_PLAIN: Final = (b"P2", b"P3")
_NETPBM_MAX_VALUE: Final = 65535
_PNG_CRITICAL: Final = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND"})  # what Tk decodes
# Colour type -> samples per pixel, and the bit depths PNG allows for it (spec 11.2.2).
_PNG_CHANNELS: Final = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
_PNG_DEPTHS: Final = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
# Adam7 passes: first column, first row, column step, row step.
_ADAM7: Final = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)
_INFLATE_STEP: Final = 1 << 20  # bytes of inflated output per call, counted and dropped
_NETPBM_FIELD_RE: Final = re.compile(rb"(?:\s|#[^\n]*\n)+([0-9]{1,9})(?=\s)")

# Reasons are msgids (fixed text, no placeholders); the validator wraps them in a lazy message.
_R_NOT_FILE: Final = N_("it is not a regular file")
_R_UNREADABLE: Final = N_("it cannot be read")
_R_TOO_BIG: Final = N_("it is larger than 16 MiB")
_R_MISMATCH: Final = N_("its content does not match its file type")
_R_DAMAGED: Final = N_("its header is damaged")
_R_TOO_WIDE: Final = N_("it is wider or taller than 4096 pixels")
_R_INCOMPLETE: Final = N_("its data is incomplete or damaged")
_R_PLAIN_NETPBM: Final = N_("plain-text PPM/PGM is not supported; save it as binary PPM/PGM or PNG")


@dataclass(frozen=True, slots=True)
class ImageProbe:
    """Result of looking at an image file's first bytes."""

    status: Literal["ok", "missing", "invalid"]
    #: For ``invalid``: the msgid of the reason (it is shown after ``cannot be used:``).
    reason: str = ""
    width: int = 0
    height: int = 0


def is_device_name(name: str) -> bool:
    """True if the path segment ``name`` is a Win32 device (``CON``, ``nul.png``, ``COM1 .gif``)."""
    return any(
        piece.split(".")[0].rstrip(" ").upper() in WINDOWS_DEVICE_NAMES for piece in name.split(":")
    )


def is_network_or_device_path(src: str) -> bool:
    """True if ``src`` names a network share or a device; it is never opened (QA-11-03).

    A pure string test, so it runs before any file access: even resolving a UNC path makes
    Windows contact (and log in to) the server. Covers ``//host/share``, ``\\\\?\\``, ``\\\\.\\``
    and any segment that is a device name, on every system (a ``.ui`` file travels).
    """
    if _NETWORK_OR_DEVICE_RE.match(src):
        return True
    return any(is_device_name(segment) for segment in _SEPARATORS_RE.split(src) if segment)


def _key(path: str) -> str:
    """The identity of a file: real path, case-folded on case-insensitive systems."""
    return os.path.normcase(os.path.realpath(path))


def _netpbm_fields(header: bytes) -> tuple[int, int, int, int] | None:
    """Width, height, maximum value and data offset of a PPM/PGM header, or None.

    The raster starts after the single whitespace character that follows the maximum value.
    """
    position = 2
    fields: list[int] = []
    for _ in range(3):
        # Each number must be followed by whitespace, so a header cut at 64 bytes is damaged.
        match = _NETPBM_FIELD_RE.match(header, position)
        if match is None:
            return None
        fields.append(int(match.group(1)))
        position = match.end()
    if not 1 <= fields[2] <= _NETPBM_MAX_VALUE:
        return None
    return fields[0], fields[1], fields[2], position + 1


def _read_size(header: bytes, suffix: str) -> tuple[int, int] | str:
    """Dimensions announced by ``header``, or the msgid of what is wrong with it."""
    if not header:
        return _R_DAMAGED
    if suffix == ".png":
        if not header.startswith(_PNG_SIGNATURE):
            return _R_MISMATCH
        if len(header) < 24 or header[12:16] != b"IHDR":
            return _R_DAMAGED
        return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")
    if suffix == ".gif":
        if header[:6] not in (b"GIF87a", b"GIF89a"):
            return _R_MISMATCH
        if len(header) < _GIF_SCREEN_END:
            return _R_DAMAGED
        return int.from_bytes(header[6:8], "little"), int.from_bytes(header[8:10], "little")
    if header[:2] in _NETPBM_PLAIN:
        return _R_PLAIN_NETPBM
    if header[:2] not in _NETPBM_MAGICS:
        return _R_MISMATCH
    fields = _netpbm_fields(header)
    return _R_DAMAGED if fields is None else (fields[0], fields[1])


def _gif_frame_size(stream: BinaryIO, flags: int) -> tuple[int, int] | None:
    """Size of the first image descriptor of a GIF, read just after its screen descriptor.

    Tk allocates the first frame from this size, which the screen size does not bound (R76).
    Skips the global colour table and the extension blocks; None when the stream ends, or
    reaches the trailer or an unknown block, before an image.
    """
    if flags & 0x80:  # global colour table: 3 bytes per entry, 2 ** (n + 1) entries
        stream.seek(3 << ((flags & 0x07) + 1), os.SEEK_CUR)
    while True:
        introducer = stream.read(1)
        if introducer == b"\x2c":  # image descriptor: left, top, width, height (LE), flags
            fields = stream.read(8)
            if len(fields) < 8:
                return None
            return int.from_bytes(fields[4:6], "little"), int.from_bytes(fields[6:8], "little")
        if introducer != b"\x21" or len(stream.read(1)) < 1:  # trailer, garbage or end
            return None
        while True:  # after the extension label: data sub-blocks up to the empty one
            size = stream.read(1)
            if not size:
                return None
            if size == b"\x00":
                break
            stream.seek(size[0], os.SEEK_CUR)


def _png_raw_size(width: int, height: int, bits: int, interlaced: bool) -> int:
    """Bytes of the filtered image data: one filter byte plus the packed samples per row."""
    passes = _ADAM7 if interlaced else ((0, 0, 1, 1),)
    total = 0
    for x0, y0, dx, dy in passes:
        columns = (width - x0 + dx - 1) // dx if width > x0 else 0
        rows = (height - y0 + dy - 1) // dy if height > y0 else 0
        if columns and rows:
            total += rows * (1 + (columns * bits + 7) // 8)
    return total


def _png_header(data: bytes) -> tuple[int, bool] | None:
    """Bits per pixel and interlacing of a valid ``IHDR`` body, or None (Tk would refuse it)."""
    depth, colour, compression, filtering, interlace = data[8:13]
    channels = _PNG_CHANNELS.get(colour)
    if channels is None or depth not in _PNG_DEPTHS[colour]:
        return None
    if compression != 0 or filtering != 0 or interlace not in (0, 1):
        return None
    return channels * depth, interlace == 1


def _png_problem(stream: BinaryIO) -> str | None:
    """The msgid of what stops Tk from decoding a PNG, or None (QA-11-06, QA-11-15).

    The chunks must be intact up to ``IEND`` (lengths, CRCs, no unknown critical chunk), the
    ``IHDR`` fields a combination PNG allows, a palette image needs ``PLTE``, and the ``IDAT``
    data must be one complete zlib stream that inflates to at most the size the header implies,
    with no image data after its end. This is what Tk 8.6 enforces (measured): it accepts less
    data than the header implies (it fills the rest) and bytes after the stream end in the same
    chunk, but not a cut or corrupt stream, more data, or a further ``IDAT``. Inflating is bounded
    by that size (at most about 128 MiB for 4096 x 4096 at 64 bits), counted and never kept, so
    a zip bomb costs no memory. The caller bounds the stream to ``MAX_IMAGE_BYTES``.
    """
    stream.seek(len(_PNG_SIGNATURE))
    header: tuple[int, bool] | None = None
    palette = False
    inflater = zlib.decompressobj()
    expected = produced = 0
    seen_data = False
    while True:
        head = stream.read(8)
        if len(head) < 8:
            return _R_INCOMPLETE
        length, kind = int.from_bytes(head[:4], "big"), head[4:]
        if length > MAX_IMAGE_BYTES or not kind.isalpha():
            return _R_INCOMPLETE
        data = stream.read(length)
        crc = stream.read(4)
        if len(data) < length or len(crc) < 4:
            return _R_INCOMPLETE
        if zlib.crc32(kind + data) != int.from_bytes(crc, "big"):
            return _R_INCOMPLETE
        if header is None:  # the first chunk
            if kind != b"IHDR" or length != 13:
                return _R_INCOMPLETE
            header = _png_header(data)
            if header is None:
                return _R_DAMAGED
            width, height = int.from_bytes(data[:4], "big"), int.from_bytes(data[4:8], "big")
            expected = _png_raw_size(width, height, *header)
            colour = data[9]
            continue
        if kind == b"IEND":
            if not seen_data or not inflater.eof:
                return _R_INCOMPLETE
            return None
        if kind == b"PLTE":
            palette = True
        elif kind == b"IDAT":
            if colour == 3 and not palette:  # a palette image without its palette
                return _R_DAMAGED
            if inflater.eof and data:  # image data after the end of the stream
                return _R_INCOMPLETE
            seen_data = True
            produced = _inflate(inflater, data, produced, expected)
            if produced < 0:
                return _R_INCOMPLETE
        elif kind[:1].isupper() and kind not in _PNG_CRITICAL:  # unknown critical chunk
            return _R_INCOMPLETE


def _inflate(inflater: zlib._Decompress, data: bytes, produced: int, limit: int) -> int:
    """Feed ``data`` to ``inflater``; the new output count, or -1 if invalid or over ``limit``."""
    pending = data
    try:
        while pending and not inflater.eof:
            out = inflater.decompress(pending, _INFLATE_STEP)
            produced += len(out)
            if produced > limit:
                return -1
            pending = inflater.unconsumed_tail
            while len(out) == _INFLATE_STEP and not pending and not inflater.eof:
                out = inflater.decompress(b"", _INFLATE_STEP)  # drain buffered output
                produced += len(out)
                if produced > limit:
                    return -1
    except zlib.error:
        return -1
    return produced


def _netpbm_complete(stream: BinaryIO, header: bytes) -> bool:
    """True if a binary PPM/PGM holds the whole raster its header announces."""
    fields = _netpbm_fields(header)
    if fields is None:
        return False
    width, height, max_value, offset = fields
    channels = 3 if header[:2] == b"P6" else 1
    sample = 2 if max_value > 255 else 1
    return stream.seek(0, os.SEEK_END) - offset >= width * height * channels * sample


class DiskFiles:
    """``FileAccess`` for real files; the runtime reuses one instance for validation and build.

    Files are identified by :func:`_key`. Relative paths resolve against the folder of the
    *including* file, ``"#"`` means the including file itself, and results (also failures) are
    cached so that a file is read at most once.
    """

    def __init__(self, path: str | os.PathLike[str], root_result: ReadResult) -> None:
        self._root = _key(os.fspath(path))
        self._root_result = root_result
        self._paths: dict[str, str] = {self._root: os.path.realpath(os.fspath(path))}
        self._cache: dict[str, ReadResult | XmlIoError] = {}

    @property
    def root(self) -> str:
        """The key of the document being validated."""
        return self._root

    def path_of(self, key: str) -> str:
        """The real path to open for ``key`` (the key itself may be case-folded)."""
        return self._paths.get(key, key)

    def resolve(self, including: str, src: str) -> str:
        """Return the key of ``src`` as seen from the file ``including``.

        Raises:
            OSError: ``src`` is empty or cannot be a path.
        """
        if src == "#":
            return including
        if not src or "\x00" in src:
            raise OSError(f"invalid path {src!r}")
        if is_network_or_device_path(src):  # before realpath can touch the disk or network
            raise OSError(f"network or device path {src!r}")
        base = os.path.dirname(self.path_of(including))
        try:
            real = os.path.realpath(os.path.join(base, src))
        except (ValueError, RuntimeError) as exc:  # NUL bytes, symlink loops
            raise OSError(str(exc)) from exc
        key = os.path.normcase(real)
        self._paths.setdefault(key, real)
        return key

    def read(self, key: str) -> ReadResult:
        """Read (once) and return the ``.ui`` file ``key``.

        Raises:
            OSError: not a regular file, or unreadable.
            XmlIoError: not a valid ``.ui`` file (also size and depth limits).
        """
        if key == self._root:
            return self._root_result
        cached = self._cache.get(key)
        if cached is None:
            path = self.path_of(key)
            if not os.path.isfile(path):
                raise OSError(f"not a file: {path}")
            try:
                cached = read_ui(path)
            except XmlIoError as exc:
                cached = exc
            self._cache[key] = cached
        if isinstance(cached, XmlIoError):
            raise cached
        return cached

    def probe_image(self, including: str, src: str) -> ImageProbe:
        """Check an image file without decoding it: size, magic, dimensions, complete body."""
        try:
            path = self.path_of(self.resolve(including, src))
            stat = os.stat(path)
        except (FileNotFoundError, NotADirectoryError):
            return ImageProbe("missing")
        except OSError:
            return ImageProbe("invalid", _R_UNREADABLE)
        if not os.path.isfile(path):
            return ImageProbe("invalid", _R_NOT_FILE)
        if stat.st_size > MAX_IMAGE_BYTES:
            return ImageProbe("invalid", _R_TOO_BIG)
        suffix = os.path.splitext(src)[1].lower()
        try:
            with open(path, "rb") as stream:
                return _probe_stream(stream, suffix)
        except OSError:
            return ImageProbe("invalid", _R_UNREADABLE)


def _probe_stream(stream: BinaryIO, suffix: str) -> ImageProbe:
    """Check an image read from ``stream`` (positioned at its start): header, then body."""
    header = stream.read(_HEADER_BYTES)
    sizes = [_read_size(header, suffix)]
    if suffix == ".gif" and not isinstance(sizes[0], str):
        stream.seek(_GIF_SCREEN_END)
        frame = _gif_frame_size(stream, header[10])
        sizes.append(_R_DAMAGED if frame is None else frame)
    checked: list[tuple[int, int]] = []
    for size in sizes:  # the screen (or only) size first, then a GIF's first frame
        if isinstance(size, str):
            return ImageProbe("invalid", size)
        width, height = size
        if width < 1 or height < 1:
            return ImageProbe("invalid", _R_DAMAGED)
        if width > MAX_IMAGE_SIDE or height > MAX_IMAGE_SIDE:
            return ImageProbe("invalid", _R_TOO_WIDE, width, height)
        checked.append(size)
    # GIF stays at its first frame: Tk 8.6 loads a GIF with cut image data or no trailer.
    if suffix == ".png":
        problem = _png_problem(stream)
        if problem is not None:
            return ImageProbe("invalid", problem)
    elif suffix in (".ppm", ".pgm") and not _netpbm_complete(stream, header):
        return ImageProbe("invalid", _R_INCOMPLETE)
    return ImageProbe("ok", "", *checked[0])


def probe_bytes(data: bytes, suffix: str) -> ImageProbe:
    """Check image bytes already read into memory, as :meth:`DiskFiles.probe_image` checks files.

    ``suffix`` is the lower-case file suffix (``".png"``). The code generator re-checks the bytes
    it embeds with this, closing the gap between the validator's probe and its own read.
    """
    if len(data) > MAX_IMAGE_BYTES:
        return ImageProbe("invalid", _R_TOO_BIG)
    return _probe_stream(io.BytesIO(data), suffix)
