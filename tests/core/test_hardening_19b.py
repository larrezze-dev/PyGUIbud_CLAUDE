"""Step 19b (spec ``hardening.md``): huge files (H13) and the depth of preserved XML (H31)."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pytest

from pyguibud.core import XmlIoError, dump_ui, read_ui, read_ui_bytes, xml_io
from pyguibud.core.registry import default_registry
from pyguibud.core.validate import validate
from pyguibud.core.xml_io import MAX_DEPTH, MAX_UI_BYTES

_HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" xmlns:x="urn:x">'
)


def _doc(body: str) -> bytes:
    return f"{_HEAD}{body}</pyguibud-ui>".encode()


# ---------------------------------------------------------------- H13 huge files
class _EndlessStream(io.RawIOBase):
    """A "2 GiB" file without writing one: it records how much was asked for."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        assert size >= 0, "the reader must never read a whole file"
        self.asked.append(size)
        return b"<" * size


def test_a_2_gib_file_is_refused_after_reading_only_the_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "huge.ui"
    path.write_bytes(b"x")
    stream = _EndlessStream()
    monkeypatch.setattr(xml_io, "open", lambda *_a, **_k: stream, raising=False)
    started = time.perf_counter()
    with pytest.raises(XmlIoError) as info:
        read_ui(path)
    assert info.value.code == "xml.too_large" and stream.asked == [MAX_UI_BYTES + 1]
    assert time.perf_counter() - started < 1.0


def test_a_file_one_byte_over_10_mib_is_refused_fast(tmp_path: Path) -> None:
    path = tmp_path / "big.ui"
    with path.open("wb") as handle:
        handle.truncate(MAX_UI_BYTES + 1)  # sparse-ish; never 2 GiB on NTFS
    started = time.perf_counter()
    with pytest.raises(XmlIoError) as info:
        read_ui(path)
    assert info.value.code == "xml.too_large" and time.perf_counter() - started < 1.0


@pytest.mark.budget
def test_ten_thousand_widgets_read_and_validate_without_a_freeze() -> None:
    labels = "".join(f'<widget class="Label" id="w{i}"><pack/></widget>' for i in range(10_000))
    data = _doc(f'<window id="main" kind="main"><layout type="pack"/>{labels}</window>')
    started = time.perf_counter()
    result = read_ui_bytes(data)
    report = validate(result.document, default_registry())
    assert time.perf_counter() - started < 10.0
    assert not report.errors


# ---------------------------------------------------------------- H31 preserved XML depth
_OWNERS = {
    "window": '<window id="main" kind="main"><layout type="pack"/>{raw}</window>',
    "nested_widget": (
        '<window id="main" kind="main"><layout type="pack"/>'
        '<widget class="Frame" id="f"><pack/><layout type="pack"/>'
        '<widget class="Label" id="l"><pack/>{raw}</widget></widget></window>'
    ),
    "cell": (
        '<window id="main" kind="main"><layout type="grid"/>'
        '<widget class="Label" id="l"><cell row="0" column="0">{raw}</cell></widget></window>'
    ),
    "action": (
        '<window id="main" kind="main"><menubar><menu id="m"><action id="a">{raw}</action>'
        '</menu></menubar><layout type="pack"/></window>'
    ),
    "root": '{raw}<window id="main" kind="main"><layout type="pack"/></window>',
}


def _raw(levels: int) -> str:
    return "<x:a>" * levels + "</x:a>" * levels


@pytest.mark.parametrize("owner", sorted(_OWNERS))
def test_whatever_the_reader_accepts_the_writer_can_save(owner: str) -> None:
    """H31: the reader's depth cap (expat, MAX_DEPTH) also caps every ``RawXml`` subtree."""
    template = _OWNERS[owner]
    deepest = 0
    for levels in range(1, MAX_DEPTH + 1):
        try:
            result = read_ui_bytes(_doc(template.format(raw=_raw(levels))))
        except XmlIoError as exc:
            assert exc.code == "xml.too_deep"
            break
        deepest = levels
        saved = dump_ui(result.document)
        assert dump_ui(read_ui_bytes(saved).document) == saved
    assert 90 < deepest < MAX_DEPTH  # refused one level deeper, at the reader
