"""Disk access for the file rules of the validator (spec ``docs/specs/runtime.md`` 9.1).

The validator never touches the disk by itself; it asks an injected ``FileAccess`` (a protocol in
:mod:`pyguibud.core.validate`). :class:`DiskFiles` is the implementation for real files. It is
stdlib-only and toolkit-free: images are never decoded here, only their first bytes are read.
"""

from __future__ import annotations

import os
import re
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
    "DiskFiles",
    "ImageProbe",
]

MAX_INCLUDE_DEPTH: Final = 8  # levels of nested includes
MAX_INCLUDE_FILES: Final = 32  # distinct files read for one validation, the root included
MAX_EXPANDED_NODES: Final = 10_000  # widgets and includes instantiated through includes
MAX_IMAGE_BYTES: Final = 16 * 1024 * 1024
MAX_IMAGE_SIDE: Final = 4096  # pixels, each side
IMAGE_SUFFIXES: Final = (".png", ".gif", ".ppm", ".pgm")  # decoded natively by Tk, no Pillow

_HEADER_BYTES: Final = 64
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_GIF_SCREEN_END: Final = 13  # header (6) + logical screen descriptor (7)
_NETPBM_MAGICS: Final = (b"P2", b"P3", b"P5", b"P6")
_NETPBM_FIELD_RE: Final = re.compile(rb"(?:\s|#[^\n]*\n)+([0-9]{1,9})(?=\s)")

# Reasons are msgids (fixed text, no placeholders); the validator wraps them in a lazy message.
_R_NOT_FILE: Final = N_("it is not a regular file")
_R_UNREADABLE: Final = N_("it cannot be read")
_R_TOO_BIG: Final = N_("it is larger than 16 MiB")
_R_MISMATCH: Final = N_("its content does not match its file type")
_R_DAMAGED: Final = N_("its header is damaged")
_R_TOO_WIDE: Final = N_("it is wider or taller than 4096 pixels")


@dataclass(frozen=True, slots=True)
class ImageProbe:
    """Result of looking at an image file's first bytes."""

    status: Literal["ok", "missing", "invalid"]
    #: For ``invalid``: the msgid of the reason (it is shown after ``cannot be used:``).
    reason: str = ""
    width: int = 0
    height: int = 0


def _key(path: str) -> str:
    """The identity of a file: real path, case-folded on case-insensitive systems."""
    return os.path.normcase(os.path.realpath(path))


def _netpbm_size(header: bytes) -> tuple[int, int] | None:
    """Width and height from a PPM/PGM header (after the two magic bytes), or None."""
    position = 2
    sizes: list[int] = []
    for _ in range(2):
        # Each number must be followed by whitespace, so a header cut at 64 bytes is damaged.
        match = _NETPBM_FIELD_RE.match(header, position)
        if match is None:
            return None
        sizes.append(int(match.group(1)))
        position = match.end()
    return sizes[0], sizes[1]


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
    if header[:2] not in _NETPBM_MAGICS:
        return _R_MISMATCH
    size = _netpbm_size(header)
    return _R_DAMAGED if size is None else size


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
        """Check an image file without decoding it: size, magic, header dimensions."""
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
                header = stream.read(_HEADER_BYTES)
                sizes = [_read_size(header, suffix)]
                if suffix == ".gif" and not isinstance(sizes[0], str):
                    stream.seek(_GIF_SCREEN_END)
                    frame = _gif_frame_size(stream, header[10])
                    sizes.append(_R_DAMAGED if frame is None else frame)
        except OSError:
            return ImageProbe("invalid", _R_UNREADABLE)
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
        return ImageProbe("ok", "", *checked[0])
