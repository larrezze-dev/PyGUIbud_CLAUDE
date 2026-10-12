"""The public output guards of ``pyguibud.codegen.output`` (ADR-013)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pyguibud.codegen import GENERATED_MARKER
from pyguibud.codegen._errors import M_ALREADY_WRITTEN, M_NOT_REGULAR, M_SAME_FILE
from pyguibud.codegen.output import (
    check_output,
    holds_translations,
    replaceable,
    same_file,
    write_atomic,
)

_POT_HEAD = 'msgid ""\nmsgstr ""\n"Generated-By: pyguibud-uic 1"\n'


def test_same_file_sees_aliases(tmp_path: Path) -> None:
    target = tmp_path / "a.ui"
    target.write_text("x", encoding="utf-8")
    assert same_file(str(target), str(tmp_path / "." / "a.ui"))
    assert same_file(str(target), str(tmp_path / "missing" / ".." / "a.ui"))
    assert not same_file(str(target), str(tmp_path / "b.ui"))


def test_check_output_refusals(tmp_path: Path) -> None:
    source = tmp_path / "a.ui"
    source.write_text("x", encoding="utf-8")
    other = tmp_path / "out.py"
    assert check_output(str(source), [str(source)], []) == M_SAME_FILE
    assert check_output(str(other), [str(source)], [str(other)]) == M_ALREADY_WRITTEN
    assert check_output(str(tmp_path), [str(source)], []) == M_NOT_REGULAR
    assert check_output(str(other), [str(source)], []) is None


def test_replaceable_marker_versus_hand_written(tmp_path: Path) -> None:
    generated = tmp_path / "g.py"
    generated.write_text(GENERATED_MARKER + " 1\n", encoding="utf-8")
    manual = tmp_path / "m.py"
    manual.write_text("print('mine')\n", encoding="utf-8")
    template = tmp_path / "t.pot"
    template.write_text(_POT_HEAD, encoding="utf-8")
    assert replaceable(str(generated), extracting=False)
    assert not replaceable(str(manual), extracting=False)
    assert replaceable(str(tmp_path / "new.py"), extracting=False)
    assert replaceable(str(template), extracting=True)
    assert not replaceable(str(manual), extracting=True)


def test_holds_translations(tmp_path: Path) -> None:
    empty = tmp_path / "e.pot"
    empty.write_text(_POT_HEAD + '\nmsgid "Hi"\nmsgstr ""\n', encoding="utf-8")
    translated = tmp_path / "t.pot"
    translated.write_text(_POT_HEAD + '\nmsgid "Hi"\nmsgstr "Hola"\n', encoding="utf-8")
    assert not holds_translations(str(empty))
    assert holds_translations(str(translated))
    assert holds_translations(str(tmp_path / "any.po"))
    assert not holds_translations(str(tmp_path / "absent.pot"))


def test_write_atomic_writes_lf_utf8(tmp_path: Path) -> None:
    target = tmp_path / "o.py"
    write_atomic(str(target), "a\nbé\n")
    assert target.read_bytes() == "a\nbé\n".encode()
    assert not list(tmp_path.glob(".pyguibud-*.tmp"))


def test_write_atomic_leaves_no_temporary_on_failure(tmp_path: Path) -> None:
    target = tmp_path / "dir"
    target.mkdir()  # os.replace onto a folder fails
    with pytest.raises(OSError):
        write_atomic(str(target), "x")
    assert not list(tmp_path.glob(".pyguibud-*.tmp"))
    assert os.path.isdir(target)
