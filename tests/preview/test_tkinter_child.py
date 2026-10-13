"""The plain ``tkinter`` preview host and the portable view (spec backends 7, part 16a)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.codegen.conftest import EXAMPLES
from tests.preview.conftest import CHILD, ENV

pytestmark = pytest.mark.gui


SENTINEL = object()


class Fork:
    """A fork's backend class with the optional ``preview_host`` capability."""

    @staticmethod
    def preview_host() -> object:
        return SENTINEL


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        cwd=cwd,
        env=ENV,
    )


def portable(ui: Path, backend: str, cwd: Path, *args: str) -> dict[str, Any]:
    argv = [*CHILD, "--describe", "--portable", "--backend", backend, *args, "--", str(ui)]
    result = _run(argv, cwd)
    assert result.returncode == 0, result.stdout + result.stderr
    data: dict[str, Any] = json.loads(result.stdout.strip().splitlines()[-1])
    return data


@pytest.mark.parametrize("lang", [None, "de_DE"])
@pytest.mark.parametrize(
    "name", ["examples/hello", "hello", "includes", "dialogs", "rich", "images"]
)
def test_portable_view_is_equal_in_both_tk_backends(
    name: str, lang: str | None, tmp_path: Path, data_copy: Path
) -> None:
    if name == "examples/hello":
        target = tmp_path / "examples"
        shutil.copytree(EXAMPLES, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
        ui = target / "hello.ui"
    else:
        ui = data_copy / f"{name}.ui"
    args = ("--lang", lang) if lang else ()
    plain = portable(ui, "tkinter", tmp_path, *args)
    assert plain == portable(ui, "ttkbootstrap", tmp_path, *args)
    assert plain["widgets"]
    if name == "examples/hello" and lang == "de_DE":
        assert plain["widgets"]["btn_greet"]["text"] == "Hallo sagen"


def test_the_tkinter_child_reports_no_themes_and_never_loads_ttkbootstrap(tmp_path: Path) -> None:
    hello = str(EXAMPLES / "hello.ui")
    code = (
        "import sys; from pyguibud.preview import run;"
        f"rc = run(['--describe', '--backend', 'tkinter', '--theme', 'darkly', {hello!r}]);"
        "print(rc, 'ttkbootstrap' in sys.modules)"
    )
    result = _run([sys.executable, "-c", code], tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "0 False"
    ready = json.loads((tmp_path / "ready.json").read_text(encoding="utf-8"))
    assert ready["themes"] == [] and ready["theme"] == ""


def test_an_unknown_backend_is_backend_unavailable_not_a_usage_error(tmp_path: Path) -> None:
    result = _run([*CHILD, "--backend", "nope", "--", str(EXAMPLES / "hello.ui")], tmp_path)
    assert result.returncode == 1
    written = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert written["code"] == "runtime.backend_unavailable"


def test_a_malformed_backend_name_is_backend_unavailable(tmp_path: Path) -> None:
    """D16 (QA-16a-05): checked by name, so a malformed one is refused like an unknown one."""
    result = _run([*CHILD, "--backend", "x; rm -rf", "--", str(EXAMPLES / "hello.ui")], tmp_path)
    assert result.returncode == 1
    written = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert written["code"] == "runtime.backend_unavailable"


def test_host_for_uses_a_backend_preview_host_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    from pyguibud.backends import BUILTIN_BACKENDS
    from pyguibud.preview import _host

    monkeypatch.setitem(BUILTIN_BACKENDS, "fork", f"{__name__}:Fork")
    assert _host.host_for("fork") is SENTINEL
    assert isinstance(_host.host_for("tkinter"), _host.TkinterHost)
