"""The "matches" proof of spec preview-export 9: the preview child and the exported module.

``python -m pyguibud.preview --describe FILE`` must equal the same description of the module
``generate_python`` writes, built the way ``python out.py`` builds it (``_preview``: with a main
window ``setup_ui(None, ...)``; without one a hidden ``App`` root, ``_apply_theme()`` first, then
``setup_ui(root, ...)``), with the same no-op handlers (D8). Each side runs in its own process:
ttkbootstrap allows one root, and the theme is part of the comparison.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pyguibud.codegen import generate_python
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import EXAMPLES
from tests.preview.conftest import ENV, describe_child

pytestmark = pytest.mark.gui

_HARNESS = """
import json, runpy, sys
import ttkbootstrap
from pyguibud.preview import NoHandlers
from pyguibud.preview._describe import describe
module, name, lang = sys.argv[1], sys.argv[2], sys.argv[3] or None
cls = runpy.run_path(module, run_name="generated")[name]
ui = cls()
if cls._has_main:
    ui.setup_ui(None, NoHandlers(), strict=False, lang=lang)
    root = next(iter(ui.windows.values()))
else:
    root = ttkbootstrap.App(title="")
    root.withdraw()
    ui._apply_theme()
    ui.setup_ui(root, NoHandlers(), strict=False, lang=lang)
    first = next(iter(ui.windows))
    ui.windows[first].transient("")
    ui.show(first)
root.update()
print(json.dumps(describe(ui), sort_keys=True))
"""


def describe_generated(ui: Path, lang: str | None, cwd: Path) -> dict[str, Any]:
    module = ui.with_name(ui.stem + "_gen_ui.py")
    generated = generate_python(read_ui(str(ui)), str(ui), output=str(module))
    module.write_text(generated.text, encoding="utf-8", newline="\n")
    result = subprocess.run(
        [sys.executable, "-c", _HARNESS, str(module), generated.class_name, lang or ""],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=cwd,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return data


def _source(name: str, tmp_path: Path, data_copy: Path) -> Path:
    if name != "examples/hello":
        return data_copy / f"{name}.ui"
    target = tmp_path / "examples"
    shutil.copytree(EXAMPLES, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target / "hello.ui"


# The spec names "events.ui"; the codegen fixture with events is "rich.ui".
@pytest.mark.parametrize("lang", [None, "de_DE"])
@pytest.mark.parametrize(
    "name", ["examples/hello", "hello", "includes", "dialogs", "rich", "images"]
)
def test_preview_matches_the_exported_module(
    name: str, lang: str | None, tmp_path: Path, data_copy: Path
) -> None:
    ui = _source(name, tmp_path, data_copy)
    args = ("--lang", lang) if lang else ()
    preview = describe_child(ui, *args, cwd=tmp_path)
    exported = describe_generated(ui, lang, tmp_path)
    assert preview == exported
    if name == "examples/hello" and lang == "de_DE":
        assert preview["widgets"]["btn_greet"]["text"] == "Hallo sagen"


@pytest.mark.parametrize(("name", "lang"), [("hello.ui", "de_DE"), ("preview/with_image.ui", None)])
def test_a_dirty_snapshot_shows_what_the_clean_file_shows(
    name: str, lang: str | None, tmp_path: Path
) -> None:
    """D3: the snapshot (rebased paths, ``--localedir``) describes like the saved file."""
    from pyguibud.core import default_registry
    from pyguibud.designer.files import FileStamp
    from pyguibud.designer.preview import (
        SNAPSHOT,
        PreparedPreview,
        PreviewRequest,
        child_argv,
        prepare_preview,
        preview_findings,
    )

    folder = tmp_path / "examples"
    shutil.copytree(EXAMPLES, folder, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    path, private = folder / name, tmp_path / "private"
    private.mkdir()
    document = read_ui(path).document
    request = PreviewRequest(document, path, True, False, "main", lang, None, FileStamp.of(path))
    findings = preview_findings(document, default_registry(), path, private)
    prepared = prepare_preview(request, private, findings)
    assert isinstance(prepared, PreparedPreview) and prepared.snapshot is not None
    (private / SNAPSHOT).write_bytes(prepared.snapshot)
    argv = child_argv(prepared, private, ui_lang="en_GB", lang=lang, theme=None)
    result = subprocess.run(
        [*argv[:3], "--describe", *argv[3:]],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=private,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    snapshot = json.loads(result.stdout.strip().splitlines()[-1])
    clean = describe_child(path, *(("--lang", lang) if lang else ()), cwd=tmp_path)
    assert snapshot == clean
