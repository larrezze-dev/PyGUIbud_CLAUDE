"""The committed ``examples/hello_ui.py`` is a fresh generation of ``examples/hello.ui``."""

from __future__ import annotations

from pathlib import Path

from pyguibud.codegen import generate_python
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import EXAMPLES, normalise_version

REGENERATE = "uv run pyguibud-uic examples/hello.ui"


def test_hello_ui_has_not_drifted_from_hello_ui_file() -> None:
    source = EXAMPLES / "hello.ui"
    committed = EXAMPLES / "hello_ui.py"
    fresh = generate_python(read_ui(str(source)), str(source), output=str(committed)).text
    actual = committed.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert normalise_version(actual) == normalise_version(fresh), (
        "examples/hello_ui.py is out of date with examples/hello.ui or the generator; "
        f"regenerate it with `{REGENERATE}` and review the diff."
    )


def test_hello_app_imports_the_generated_names_only() -> None:
    text = (Path(EXAMPLES) / "hello_app.py").read_text("utf-8")
    assert "from hello_ui import Ui_Main, UiError" in text
    assert "pyguibud" not in text.replace("PyGUIbud", "").replace("pyguibud-uic", "")
