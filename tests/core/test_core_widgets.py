"""Tests for ``pyguibud.core.widgets`` (the 24 built-in specifications)."""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from pyguibud import i18n
from pyguibud.core import CORE_CLASS_NAMES, WIDGET_API_VERSION, WidgetSpec, is_valid_event
from pyguibud.core.widgets import core_widgets

POT = Path(i18n.__file__).parent / "locale" / "pyguibud.pot"

_EXPECTED_ORDER = [
    "Frame",
    "LabelFrame",
    "Notebook",
    "PanedWindow",
    "ScrolledFrame",
    "Label",
    "Button",
    "Entry",
    "Text",
    "Checkbutton",
    "Radiobutton",
    "Combobox",
    "Spinbox",
    "Scale",
    "Progressbar",
    "Separator",
    "Listbox",
    "Treeview",
    "Scrollbar",
    "Canvas",
    "Menubar",
    "Menu",
    "Action",
    "Statusbar",
]
_LAYOUT = {"Frame", "LabelFrame", "ScrolledFrame"}
_PAGES = {"Notebook", "PanedWindow"}
_MENU = {"Menubar", "Menu"}


@pytest.fixture(scope="module")
def pot_msgids() -> set[str]:
    with POT.open("rb") as handle:
        catalogue = read_po(handle)
    return {str(m.id) for m in catalogue if m.id and isinstance(m.id, str)}


def _by_name() -> dict[str, WidgetSpec]:
    return {spec.name: spec for spec in core_widgets()}


def test_exactly_24_unique_specs_in_order() -> None:
    names = [s.name for s in core_widgets()]
    assert names == _EXPECTED_ORDER
    assert len(set(names)) == 24
    assert set(names) == CORE_CLASS_NAMES


def test_core_widgets_returns_same_immutable_tuple() -> None:
    assert isinstance(core_widgets(), tuple)
    assert core_widgets() is core_widgets()


def test_every_spec_is_a_valid_core_spec() -> None:
    for spec in core_widgets():
        assert spec.api_version == WIDGET_API_VERSION
        assert not spec.is_extension
        assert spec.fallback is None
        assert spec.plugin is None
        assert spec.factories == {}
        assert spec.display_name
        assert spec.category


@pytest.mark.parametrize("name", sorted(CORE_CLASS_NAMES))
def test_children_kind_and_container_flag(name: str) -> None:
    spec = _by_name()[name]
    if name in _LAYOUT:
        assert spec.children == "layout"
    elif name in _PAGES:
        assert spec.children == "pages"
    elif name in _MENU:
        assert spec.children == "menu"
    else:
        assert spec.children == "none"
    assert spec.container is (name in _LAYOUT | _PAGES)


def test_events_are_valid_and_unique() -> None:
    for spec in core_widgets():
        assert len(set(spec.events)) == len(spec.events)
        assert all(is_valid_event(e) for e in spec.events), spec.name


def test_property_names_unique_and_defaults_consistent() -> None:
    for spec in core_widgets():
        names = [p.name for p in spec.properties]
        assert len(set(names)) == len(names), spec.name
        for prop in spec.properties:
            assert spec.property(prop.name) is prop
            if prop.type == "enum":
                assert prop.choices
                assert prop.default is None or prop.default in prop.choices


def test_all_msgids_are_in_the_catalogue(pot_msgids: set[str]) -> None:
    missing: list[str] = []
    for spec in core_widgets():
        for msgid in (spec.display_name, spec.category):
            if msgid not in pot_msgids:
                missing.append(f"{spec.name}: {msgid!r}")
        for prop in spec.properties:
            if prop.display_name is not None and prop.display_name not in pot_msgids:
                missing.append(f"{spec.name}.{prop.name}: {prop.display_name!r}")
    assert not missing, missing


def test_labels_untranslated_in_source_language() -> None:
    for spec in core_widgets():
        assert spec.label() == spec.display_name
        assert spec.category_label() == spec.category


def test_labels_translate_under_pseudo_locale() -> None:
    i18n.set_language("en_XA")
    for spec in core_widgets():
        assert spec.label().startswith("["), spec.name
        assert spec.category_label().startswith("["), spec.name
        for prop in spec.properties:
            if prop.display_name:
                assert prop.label().startswith("[")
    i18n.set_language("en_GB")
    assert _by_name()["LabelFrame"].label() == "Label frame"


def test_no_translation_at_import_time() -> None:
    """Importing the module under a non-source language must not bake a translation in."""
    i18n.set_language("en_XA")
    module = importlib.import_module("pyguibud.core.widgets")
    importlib.reload(module)
    try:
        specs = module.core_widgets()
        assert all(not s.display_name.startswith("[") for s in specs)
        assert all(not s.category.startswith("[") for s in specs)
    finally:
        i18n.set_language("en_GB")
        importlib.reload(module)


def test_import_in_pseudo_language_subprocess() -> None:
    code = (
        "from pyguibud import i18n; i18n.set_language('en_XA');"
        "from pyguibud.core.widgets import core_widgets;"
        "assert core_widgets()[0].display_name == 'Frame'"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_notebook_and_paned_window_are_page_containers() -> None:
    specs = _by_name()
    for name in _PAGES:
        assert specs[name].children == "pages"
        assert specs[name].container
    assert not specs["Menubar"].container
    assert not specs["Statusbar"].container
