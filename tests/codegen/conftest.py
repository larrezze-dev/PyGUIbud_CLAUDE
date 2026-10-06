"""Shared helpers of the code generator tests: .ui builders, image bytes, a headless runner."""

from __future__ import annotations

import base64
import functools
import gettext
import json
import re
import shutil
import struct
import subprocess
import sys
import zlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.codegen import generate_python
from pyguibud.core import reset_default_registry
from pyguibud.core.xml_io import read_ui

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
DATA = Path(__file__).resolve().parent / "data"
HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"'
    ' xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">\n'
)
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
P6 = b"P6\n# comment\n2 3\n255\n" + bytes(2 * 3 * 3)
P5 = b"P5\n2 3\n255\n" + bytes(2 * 3)


def png(width: int = 2, height: int = 3) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def ui_text(windows: str, *, meta: str = "", resources: str = "", variables: str = "") -> str:
    parts = [HEADER, f'<meta source_locale="en_GB" {meta}/>']
    if resources:
        parts.append(f"<resources>{resources}</resources>")
    if variables:
        parts.append(f"<variables>{variables}</variables>")
    parts += [windows, "</pyguibud-ui>\n"]
    return "".join(parts)


def write_ui(path: Path, windows: str, **parts: str) -> Path:
    path.write_text(ui_text(windows, **parts), encoding="utf-8")
    return path


def generate(path: Path, output: Path | None = None) -> str:
    out = output if output is not None else path.with_name(path.stem + "_ui.py")
    return generate_python(read_ui(str(path)), str(path), output=str(out)).text


@functools.cache
def _display() -> str | None:
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import tkinter; tkinter.Tk().destroy()"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "the Tk probe timed out"
    return None if result.returncode == 0 else result.stderr.strip()[-200:] or "no display"


def pytest_runtest_setup(item: pytest.Item) -> None:
    if item.get_closest_marker("gui") is not None:
        reason = _display()
        if reason is not None:
            pytest.skip(f"needs a Tk display: {reason}")


# A child process that cannot import PyGUIbud: a finder refuses pyguibud* and the modules are
# poisoned, so the generated module must be self-contained.
_PRELUDE = """
import os, sys, json, runpy, logging, importlib.abc
class _Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("pyguibud", "pyguibud_runtime"):
            raise ImportError("blocked: " + name)
        return None
sys.meta_path.insert(0, _Block())
sys.modules["pyguibud"] = None
sys.modules["pyguibud_runtime"] = None
logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
sys.path.insert(0, os.path.dirname(os.path.abspath(sys.argv[1])))
g = runpy.run_path(sys.argv[1], run_name="generated")
out = {}
"""


def run_generated(module: Path, body: str) -> dict[str, Any]:
    """Run ``body`` (it fills ``out``) after loading ``module`` in a PyGUIbud-free process."""
    code = _PRELUDE + body + "\nprint(json.dumps(out))\n"
    result = subprocess.run(
        [sys.executable, "-c", code, str(module)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        cwd=module.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    data["stderr"] = result.stderr
    return data


_VERSION = re.compile(r"pyguibud-uic \d+(?:\.\d+)*\S* \(format ")
_POT_VERSION = re.compile(r"(Generated-By: pyguibud-uic )\S+?(?=\\n)")
SUPPORT_PLACEHOLDER = "# <support block: identical in every module, compared with support_text()>"


def normalise_version(text: str) -> str:
    """Replace the PyGUIbud version in a header line (C6) so a version bump is not a diff."""
    text = _VERSION.sub("pyguibud-uic <version> (format ", text, count=1)
    return _POT_VERSION.sub(r"\1<version>", text, count=1)


def split_support(text: str) -> tuple[str, str]:
    """``(text with the support block replaced by a placeholder, the block)``."""
    begin = text.index("# --- support:")
    start = text.index("\n", begin) + 1
    end = text.index("# --- end of support ---")
    return text[:start] + SUPPORT_PLACEHOLDER + "\n" + text[end:], text[start:end]


def make_data_copy(target: Path) -> Path:
    """Copy ``tests/codegen/data`` to ``target`` and write the images its ``.ui`` files use.

    The images are built here (not stored) so the repository keeps no binary fixtures.
    """
    shutil.copytree(DATA, target, ignore=shutil.ignore_patterns("*.golden"))
    images = {
        "png.png": png(),
        "gif.gif": GIF,
        "ppm.ppm": P6,
        "pgm.pgm": P5,
        "pic.gif": GIF,
        "pic.ppm": P6,
    }
    for name, data in images.items():
        (target / name).write_bytes(data)
    return target


@pytest.fixture
def data_copy(tmp_path: Path) -> Path:
    return make_data_copy(tmp_path / "data")


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Untranslated en_GB and a fresh registry; the global state is restored afterwards."""
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    reset_default_registry()
    yield
    reset_default_registry()
