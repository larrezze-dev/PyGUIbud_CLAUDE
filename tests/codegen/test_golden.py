"""Golden files: generated modules and ``.pot`` templates of ``tests/codegen/data/*.ui``.

Each ``<name>_ui.py.golden`` is the module with two normalisations: the PyGUIbud version in the
header line (spec C6) and the support block, which is identical in every module and is compared
once, against ``support_text()``, by ``test_support_block_equals_the_support_region``.

To rewrite the goldens after an intended change of the generator, run::

    PYGUIBUD_REGEN_GOLDEN=1 uv run python -m pytest tests/codegen/test_golden.py

and review the ``git diff`` of ``tests/codegen/data``. The comparison ignores CRLF (a checkout
with ``autocrlf``); the files are stored with LF (``.gitattributes``).
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from pyguibud.codegen import GENERATED_MARKER, extract_pot, generate_python, support_text
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import DATA, normalise_version, split_support

REGEN = os.environ.get("PYGUIBUD_REGEN_GOLDEN") == "1"
MODULES = ("hello", "dialogs", "includes", "images", "rich", "tb_widgets")
POTS = ("hello", "dialogs", "includes", "rich")


def _compare(golden: Path, actual: str) -> None:
    if REGEN:
        golden.write_text(actual, encoding="utf-8", newline="\n")
        return
    assert golden.exists(), (
        f"{golden.name} is missing: run PYGUIBUD_REGEN_GOLDEN=1 uv run python -m pytest "
        "tests/codegen/test_golden.py"
    )
    expected = golden.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert actual == expected, (
        f"{golden.name} differs from the generated text; if the change is intended, regenerate "
        "it with PYGUIBUD_REGEN_GOLDEN=1 uv run python -m pytest tests/codegen/test_golden.py"
    )


def _module(folder: Path, name: str) -> str:
    path = folder / f"{name}.ui"
    return generate_python(read_ui(str(path)), str(path), output=str(folder / f"{name}_ui.py")).text


@pytest.mark.parametrize("name", MODULES)
def test_generated_module_matches_its_golden(data_copy: Path, name: str) -> None:
    text = _module(data_copy, name)
    body, _ = split_support(normalise_version(text))
    _compare(DATA / f"{name}_ui.py.golden", body)


@pytest.mark.parametrize("name", MODULES)
def test_support_block_equals_the_support_region(data_copy: Path, name: str) -> None:
    _, block = split_support(_module(data_copy, name))
    assert block.strip("\n") == support_text()


@pytest.mark.parametrize("name", POTS)
def test_pot_matches_its_golden(
    data_copy: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.chdir(data_copy)
    result = read_ui(f"{name}.ui")
    text = normalise_version(extract_pot([(result, f"{name}.ui")], base_dir="."))
    _compare(DATA / f"{name}.pot.golden", text)


def test_goldens_are_lf_text_with_the_normalised_header() -> None:
    names = [*(f"{n}_ui.py.golden" for n in MODULES), *(f"{n}.pot.golden" for n in POTS)]
    for name in names:
        data = (DATA / name).read_bytes()
        assert data.endswith(b"\n"), name
        if b"\r\n" in data:
            pytest.skip("a CRLF checkout (autocrlf); the comparison normalises it")
    first = (DATA / "hello_ui.py.golden").read_text("utf-8").split("\n", 1)[0]
    assert first.startswith(f"{GENERATED_MARKER} <version> (format 1) from 'hello.ui'.")
    pot = (DATA / "hello.pot.golden").read_text("utf-8")
    assert 'Generated-By: pyguibud-uic <version>\\n"' in pot


@pytest.mark.parametrize("name", POTS)
def test_pot_goldens_are_babel_readable(name: str) -> None:
    catalogue = read_po(io.StringIO((DATA / f"{name}.pot.golden").read_text("utf-8")))
    assert [m for m in catalogue if m.id]


def test_the_goldens_cover_the_special_shapes() -> None:
    dialogs = (DATA / "dialogs_ui.py.golden").read_text("utf-8")
    assert "    _has_main = False\n" in dialogs and "class Ui_dialogs(_Ui):" in dialogs
    assert "_has_main" not in (DATA / "hello_ui.py.golden").read_text("utf-8")
    assert (DATA / "includes_ui.py.golden").read_text("utf-8").count("def _component_") == 2
    assert "_IMG_3" in (DATA / "images_ui.py.golden").read_text("utf-8")
