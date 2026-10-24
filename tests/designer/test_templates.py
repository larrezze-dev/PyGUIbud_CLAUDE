"""Built-in templates: valid, canonical, clean and accepted by ``pyguibud-uic --check``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pyguibud import uic
from pyguibud.core import default_registry, dump_ui, read_ui
from pyguibud.core.files import DiskFiles
from pyguibud.core.validate import RESERVED_IDS
from pyguibud.designer import templates
from pyguibud.designer.templates import TEMPLATES, template_bytes, template_info

FOLDER = Path(templates.__file__).parent
PATHS = sorted(FOLDER.glob("*.ui"))


def test_manifest_matches_the_files_on_disk() -> None:
    assert sorted(info.file for info in TEMPLATES) == [p.name for p in PATHS]
    assert len({info.id for info in TEMPLATES}) == len(TEMPLATES)
    assert template_info("main_window") is not None
    assert template_info("nope") is None


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_template_has_no_errors_or_warnings(path: Path) -> None:
    result = read_ui(path)
    report = default_registry()
    from pyguibud.core import validate

    findings = validate(result.document, report, files=DiskFiles(path, result)).findings
    assert findings == ()
    assert result.warnings == ()


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_template_is_canonical(path: Path) -> None:
    assert dump_ui(read_ui(path).document) == path.read_bytes()


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_template_ids_are_not_reserved(path: Path) -> None:
    ids = {getattr(node, "id", None) for node in read_ui(path).document.walk()}
    assert not (ids & RESERVED_IDS)


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_template_passes_the_uic_check(path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert uic.main(["--check", str(path)]) == 0
    capsys.readouterr()


@pytest.mark.parametrize("path", PATHS, ids=lambda p: p.name)
def test_template_follows_the_house_rules(path: Path) -> None:
    result = read_ui(path)
    assert result.document.meta.source_locale == "en_GB"
    assert result.document.meta.theme == ""  # designer themes are chrome-only
    for window in result.document.children:
        assert window.layout is not None


def test_template_bytes_read_through_the_manifest() -> None:
    for info in TEMPLATES:
        assert template_bytes(info).startswith(b"<?xml")


def test_templates_are_package_data_of_the_wheel() -> None:
    """hatch ships every file of ``src/pyguibud`` but the catalogue sources; guard that nothing
    excludes the data."""
    text = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert 'packages = ["src/pyguibud"]' in text
    assert "*.ui" not in text.split("[tool.hatch.build.targets.wheel]")[1].split("[tool.")[0]


IDS = ("main_window", "dialog", "login_form", "settings", "empty_component")


def test_all_five_templates_are_listed_in_wizard_order() -> None:
    assert tuple(info.id for info in TEMPLATES) == IDS
    assert all(info.title and info.description for info in TEMPLATES)


def _nodes(name: str) -> dict[str, Any]:
    document = read_ui(FOLDER / f"{name}.ui").document
    return {str(getattr(n, "id", "")): n for n in document.walk()}


def test_dialog_template_is_a_modal_dialog_with_ok_and_cancel() -> None:
    window = _nodes("dialog")["dialog"]
    assert (window.kind, window.modal, window.buttons) == ("dialog", True, "ok,cancel")


def test_login_template_masks_the_password_and_binds_both_variables() -> None:
    document = read_ui(FOLDER / "login_form.ui").document
    assert list(document.variables) == ["username", "password"]
    nodes = _nodes("login_form")
    assert nodes["ent_password"].bind == "password"
    assert nodes["ent_password"].props["show"].value == "*"
    assert nodes["btn_login"].events[0].handler == "on_login"


def test_settings_template_has_a_notebook_with_two_pages() -> None:
    notebook = _nodes("settings")["nbk_settings"]
    assert len(notebook.children) == 2


def test_component_template_is_an_empty_component() -> None:
    window = _nodes("empty_component")["component"]
    assert window.kind == "component" and not window.children
