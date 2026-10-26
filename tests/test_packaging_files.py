"""Spec packaging 20b: the files each distribution ships with, and the release workflows."""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

from tests._paths import ROOT

CREDIT = "Created by Luciano Arrezze and programmed with the support of Claude Code."
WORKFLOWS = ROOT / ".github" / "workflows"


def _check_dist() -> ModuleType:
    spec = importlib.util.spec_from_file_location("check_dist", ROOT / "tools" / "check_dist.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE.md"])
def test_the_runtime_ships_byte_copies_of_the_licence_files(name: str) -> None:
    # Line endings are a checkout artefact (core.autocrlf rewrites only the files it touches).
    copy, original = (
        path.read_bytes().replace(b"\r\n", b"\n") for path in (ROOT / "runtime" / name, ROOT / name)
    )
    assert copy == original


#: Tool outputs that ``--check`` compares byte for byte with a fresh build (LF line endings).
GENERATED = ["src/pyguibud/designer/themes/sape.json", "src/pyguibud/designer/icons/icons.json"]


@pytest.mark.skipif(
    shutil.which("git") is None or not (ROOT / ".git").exists(), reason="not a git checkout"
)
@pytest.mark.parametrize("path", GENERATED)
def test_generated_files_keep_lf_in_an_autocrlf_checkout(path: str) -> None:
    # Regression (CI, Step 20b.1): the Windows runner checks out with core.autocrlf=true, which
    # turned sape.json into CRLF, so `tools/gen_themes.py --check` reported it out of date.
    result = subprocess.run(
        ["git", "check-attr", "eol", "--", path],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == f"{path}: eol: lf"


@pytest.mark.parametrize("readme", ["README.md", "runtime/README.md"])
def test_each_readme_carries_the_credit_and_only_absolute_links(readme: str) -> None:
    text = (ROOT / readme).read_text(encoding="utf-8")
    assert CREDIT in text
    # PyPI renders the README without the repository, so relative links would break there.
    assert re.findall(r"\]\((?!https://)([^)]*)\)", text) == []


def test_both_projects_declare_readme_licence_files_and_urls() -> None:
    for project in (ROOT / "pyproject.toml", ROOT / "runtime" / "pyproject.toml"):
        text = project.read_text(encoding="utf-8")
        assert 'readme = "README.md"' in text
        assert 'license-files = ["LICENSE", "NOTICE.md"]' in text
        assert 'Source = "https://github.com/larrezze-dev/PyGUIbud_CLAUDE"' in text
        assert '"Development Status :: 4 - Beta"' in text
        assert text.count('"Natural Language :: ') == 8


def test_ci_runs_on_master_and_checks_the_built_distributions() -> None:
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    assert "branches: [master]" in text and "branches: [main]" not in text
    assert "workflow_dispatch:" in text
    for command in (
        "uv build --all-packages",
        "uvx twine check --strict dist/*",
        "tools/check_dist.py dist",
        "install-smoke:",
    ):
        assert command in text


def test_release_publishes_through_oidc_with_no_secrets() -> None:
    text = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert 'tags: ["v*"]' in text
    assert "${{ secrets." not in text and "password:" not in text
    assert text.count("id-token: write") == 2
    assert "repository-url: https://test.pypi.org/legacy/" in text
    assert "if: needs.build.outputs.prerelease == 'false'" in text
    assert "environment:\n      name: pypi" in text


def test_check_dist_reads_entry_point_sections() -> None:
    sections = _check_dist()._sections(
        "[console_scripts]\na = m:f\n\n[pyguibud.widgets]\ncore = x\n"
    )
    assert sections == {"console_scripts": {"a"}, "pyguibud.widgets": {"core"}}


def test_check_dist_refuses_a_folder_without_the_four_artefacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "pyguibud-0.0.1-py3-none-any.whl").write_bytes(b"")
    assert _check_dist().main([str(tmp_path)]) == 1
    assert "expected" in capsys.readouterr().err
