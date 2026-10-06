"""The output depends only on the ``.ui`` files: not on hash seed, cwd, CLI language or newlines."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import pyguibud.codegen as codegen
from pyguibud.codegen import generate_python
from pyguibud.core.xml_io import read_ui

_MAIN = "import sys; from pyguibud.uic import main; sys.exit(main(sys.argv[1:]))"
NAMES = ("hello", "includes", "rich", "images", "dialogs")
# (PYTHONHASHSEED, working-directory name, --lang)
VARIANTS = (("0", "cwd_a", "en_GB"), ("1", "cwd_b", "de_DE"), ("4242", "cwd_c", "en_XA"))


def _uic(tmp_path: Path, seed: str, cwd: str, lang: str, *args: str) -> None:
    folder = tmp_path / cwd
    folder.mkdir(exist_ok=True)
    env = {**os.environ, "PYTHONHASHSEED": seed}
    result = subprocess.run(
        [sys.executable, "-c", _MAIN, "--lang", lang, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=folder,
        check=False,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("name", NAMES)
def test_module_is_identical_across_processes_cwds_and_languages(
    data_copy: Path, tmp_path: Path, name: str
) -> None:
    outputs = []
    for index, (seed, cwd, lang) in enumerate(VARIANTS):
        target = data_copy / f"{name}_{index}_ui.py"
        _uic(tmp_path, seed, cwd, lang, str(data_copy / f"{name}.ui"), "-o", str(target))
        outputs.append(target.read_bytes())
    # The output name is not part of the text (spec 3), so the three files are the same bytes.
    assert outputs[0] == outputs[1] == outputs[2]
    assert b"\r" not in outputs[0]


@pytest.mark.parametrize("name", ("hello", "includes", "rich"))
def test_pot_is_identical_across_processes_cwds_and_languages(
    data_copy: Path, tmp_path: Path, name: str
) -> None:
    outputs = []
    for index, (seed, cwd, lang) in enumerate(VARIANTS):
        target = data_copy / f"{name}_{index}.pot"
        _uic(
            tmp_path, seed, cwd, lang, "--extract", str(data_copy / f"{name}.ui"), "-o", str(target)
        )
        outputs.append(target.read_bytes())
    assert outputs[0] == outputs[1] == outputs[2]


def test_a_crlf_support_file_gives_the_same_module(
    data_copy: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = data_copy / "hello.ui"
    output = str(data_copy / "hello_ui.py")
    first = generate_python(read_ui(str(path)), str(path), output=output).text
    original = Path(codegen.__file__).with_name("_support.py").read_bytes()
    crlf = tmp_path / "_support.py"
    crlf.write_bytes(original.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    monkeypatch.setattr(codegen, "_SUPPORT_FILE", crlf)
    second = generate_python(read_ui(str(path)), str(path), output=output).text
    assert second == first and "\r" not in second
