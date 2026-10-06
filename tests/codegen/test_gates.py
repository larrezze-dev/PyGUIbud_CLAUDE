"""Literal and identifier gates, refusals and ``probe_bytes`` (spec 2, 4.4, 6)."""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud import codegen
from pyguibud.codegen import CodegenError, _emit, generate_python
from pyguibud.core.files import MAX_IMAGE_BYTES, probe_bytes
from pyguibud.core.validate import ValidationReport
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import GIF, P5, P6, generate, png, write_ui


@pytest.mark.parametrize("value", [object(), [1], {"a": 1}, float("nan"), float("inf"), b"x"])
def test_lit_refuses_non_literals(value: object) -> None:
    with pytest.raises(TypeError):
        _emit.lit(value)


@given(st.recursive(st.none() | st.booleans() | st.integers() | st.text(), st.tuples))
def test_lit_round_trips(value: object) -> None:
    assert ast.literal_eval(_emit.lit(value)) == value


@pytest.mark.parametrize("name", ["class", "run", "vars", "_x", "a b", "a.b", "", "é", 3, "x" * 65])
def test_ident_refuses_unsafe_names(name: object) -> None:
    with pytest.raises(CodegenError) as info:
        _emit.ident(name)
    assert info.value.code == "codegen.unsafe_name"


@pytest.mark.parametrize("name", ["match", "type", "self", "print", "Ui_Main", "a_1"])
def test_ident_accepts_grammar_names(name: str) -> None:
    assert _emit.ident(name) == name


def test_handler_is_emitted_as_a_literal() -> None:
    assert _emit.handler("on_go") == "'on_go'"
    with pytest.raises(CodegenError):
        _emit.handler("__class__")


def _simple(tmp_path: Path, body: str = "", **parts: str) -> Path:
    return write_ui(
        tmp_path / "f.ui",
        f'<window id="main" kind="main"><layout type="grid"/>{body}</window>',
        **parts,
    )


def test_invalid_document_is_refused(tmp_path: Path) -> None:
    path = _simple(tmp_path, '<widget class="Button" id="run"><cell row="0" column="0"/></widget>')
    with pytest.raises(CodegenError) as info:
        generate(path)
    assert info.value.code == "codegen.invalid_document"
    assert info.value.findings and "1 error" in str(info.value)


def test_read_only_and_components_only_are_refused(tmp_path: Path) -> None:
    path = _simple(tmp_path)
    result = dataclasses.replace(read_ui(str(path)), read_only=True)
    with pytest.raises(CodegenError) as info:
        generate_python(result, str(path), output=str(tmp_path / "o.py"))
    assert info.value.code == "codegen.read_only"
    comp = write_ui(
        tmp_path / "c.ui", '<window id="part" kind="component"><layout type="grid"/></window>'
    )
    with pytest.raises(CodegenError) as info:
        generate(comp)
    assert info.value.code == "codegen.nothing_to_generate"


def test_unsafe_name_passed_by_a_broken_validator_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _simple(
        tmp_path, '<widget class="Button" id="ok_id"><cell row="0" column="0"/></widget>'
    )
    result = read_ui(str(path))
    widget = result.document.children[0].children[0]
    monkeypatch.setattr(widget, "id", "__class__")
    monkeypatch.setattr(codegen, "validate", lambda *_a, **_k: ValidationReport(()))
    with pytest.raises(CodegenError) as info:
        generate_python(result, str(path), output=str(tmp_path / "o.py"))
    assert info.value.code == "codegen.unsafe_name"


def test_texts_reach_the_output_only_as_constants(tmp_path: Path) -> None:
    nasty = "x'); import os; os.system('echo') #\\"
    path = _simple(
        tmp_path,
        '<widget class="Button" id="btn"><prop name="text" translatable="true" '
        f'context="{nasty}" comment="{nasty}">{nasty}</prop><cell row="0" column="0"/></widget>',
    )
    text = generate(path)
    tree = ast.parse(text)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "system" not in calls
    assert repr(nasty) in text


def test_image_changed_after_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "a.png").write_bytes(png())
    path = _simple(
        tmp_path,
        '<widget class="Label" id="lbl"><prop name="image" ref="img"/>'
        '<cell row="0" column="0"/></widget>',
        resources='<image id="img" src="a.png"/>',
    )
    from pyguibud.codegen import _plan

    monkeypatch.setattr(_plan, "probe_bytes", lambda data, suffix: probe_bytes(b"junk", suffix))
    with pytest.raises(CodegenError) as info:
        generate(path)
    assert info.value.code == "codegen.image_changed"


@pytest.mark.parametrize(
    ("data", "suffix", "status"),
    [
        (png(), ".png", "ok"),
        (GIF, ".gif", "ok"),
        (P6, ".ppm", "ok"),
        (P5, ".pgm", "ok"),
        (GIF, ".png", "invalid"),
        (b"", ".png", "invalid"),
        (png(5000, 1)[:40], ".png", "invalid"),
    ],
)
def test_probe_bytes(data: bytes, suffix: str, status: str) -> None:
    assert probe_bytes(data, suffix).status == status


def test_probe_bytes_refuses_too_many_bytes() -> None:
    assert probe_bytes(png() + bytes(MAX_IMAGE_BYTES), ".png").status == "invalid"
