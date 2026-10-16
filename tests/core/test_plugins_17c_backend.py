"""Step 17c backend: configure_default_registry, the preview child's flags and the acme sample."""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core import default_registry
from pyguibud.core.registry import Registry, configure_default_registry, reset_default_registry
from pyguibud.preview import _configure_plugins, _parser

ACME_SRC = Path(__file__).resolve().parents[2] / "examples" / "acme_plugin" / "src"


class _EP:
    def __init__(self, name: str, dist: str, load: Any, value: str = "x:y") -> None:
        self.name, self.value, self.group = name, value, "pyguibud.widgets"
        self.dist = SimpleNamespace(name=dist)
        self._load = load

    def load(self) -> object:
        return self._load()


@pytest.fixture(autouse=True)
def _clean_default() -> Iterator[None]:
    reset_default_registry()
    yield
    reset_default_registry()


@pytest.fixture
def acme(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import ``acme_pyguibud`` from the examples folder (never from an installation)."""

    def load(mode: str | None = None) -> Any:
        if mode is None:
            monkeypatch.delenv("ACME_PYGUIBUD_BREAK", raising=False)
        else:
            monkeypatch.setenv("ACME_PYGUIBUD_BREAK", mode)
        monkeypatch.syspath_prepend(str(ACME_SRC))
        monkeypatch.delitem(sys.modules, "acme_pyguibud", raising=False)
        return importlib.import_module("acme_pyguibud")

    yield load
    sys.modules.pop("acme_pyguibud", None)


def _plugin_source(*eps: _EP) -> Any:
    return lambda group: list(eps) if group == "pyguibud.widgets" else []


def test_configure_default_registry_all_skips_non_builtin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _EP("fake", "fake-plugin", lambda: [])
    monkeypatch.setattr("pyguibud.core.registry._metadata_entry_points", _plugin_source(fake))
    configure_default_registry("all")
    registry = default_registry()
    assert registry.require("Label").name == "Label"
    assert registry.disabled_distributions() == frozenset({"fake-plugin"})


def test_configure_default_registry_replaces_and_stays_lazy() -> None:
    first = default_registry()
    configure_default_registry(["Acme_Pyguibud"])
    second = default_registry()
    assert second is not first
    assert second is default_registry()
    configure_default_registry()
    assert default_registry() is not second


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["f.ui"], None),
        (["--no-plugins", "f.ui"], "all"),
        (["--disable-plugins", " a, b ,,c", "f.ui"], ("a", "b", "c")),
        (["--disable-plugins", ",", "f.ui"], None),
    ],
)
def test_preview_flags(monkeypatch: pytest.MonkeyPatch, argv: list[str], expected: object) -> None:
    seen: list[object] = []
    monkeypatch.setattr("pyguibud.core.configure_default_registry", seen.append)
    _configure_plugins(_parser().parse_args(argv))
    assert seen == ([] if expected is None else [expected])


def test_preview_flags_are_hidden() -> None:
    help_text = _parser().format_help()
    assert "--no-plugins" not in help_text
    assert "--disable-plugins" not in help_text


def test_acme_spec_and_factories(acme: Any) -> None:
    module = acme()
    (spec,) = module.widgets()
    assert spec.name == "acme:ColourSwatch"
    assert spec.fallback == "Label"
    assert spec.plugin == "acme-pyguibud"
    assert spec.bind_types == ("string",)
    assert spec.property("colour").default == "#2E86DE"
    assert spec.property("text").translatable
    assert set(spec.factories) == {"ttkbootstrap", "tkinter", "pyside6"}
    registry = Registry(_plugin_source(_EP("acme", "acme-pyguibud", lambda: module.widgets)))
    assert registry.require("acme:ColourSwatch").category == "Acme"
    assert [d for d in registry.diagnostics() if d.distribution != "pyguibud"] == []


@pytest.mark.parametrize("mode", ["import", "spec", "exit"])
def test_acme_break_modes_give_one_diagnostic(acme: Any, mode: str) -> None:
    def load() -> object:
        return acme(mode).widgets

    sibling = _EP("zzz", "zzz-plugin", lambda: [])
    registry = Registry(_plugin_source(_EP("acme", "acme-pyguibud", load), sibling))
    registry.load()
    found = [d for d in registry.diagnostics() if d.distribution == "acme-pyguibud"]
    assert len(found) == 1 and found[0].code == "registry.load_failed"
    assert [d for d in registry.diagnostics() if d.distribution != "pyguibud"] == found
    assert registry.require("Label").name == "Label"


def test_acme_break_factory(acme: Any) -> None:
    module = acme("factory")
    registry = Registry(_plugin_source(_EP("acme", "acme-pyguibud", lambda: module.widgets)))
    spec = registry.require("acme:ColourSwatch")  # the spec itself loads fine
    with pytest.raises(RuntimeError, match="factory"):
        module.tk_swatch(None, {}, None, None)
    assert spec.name == "acme:ColourSwatch"
