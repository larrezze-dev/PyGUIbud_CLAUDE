"""Smoke tests for the core model and registry (the full suite is written by TESTING)."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

import pytest

from pyguibud.core import (
    CORE_CLASS_NAMES,
    WIDGET_API_VERSION,
    Document,
    EntryPointSource,
    Include,
    Menu,
    Menubar,
    ModelError,
    Registry,
    RegistryError,
    Widget,
    WidgetSpec,
    Window,
    default_registry,
    reset_default_registry,
)
from pyguibud.core.widgets import core_widgets


@dataclass
class _Dist:
    name: str


@dataclass
class _EP:
    name: str
    value: str
    group: str
    dist: _Dist | None
    obj: object

    def load(self) -> object:
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


def _source(*eps: _EP) -> EntryPointSource:
    return lambda group: [ep for ep in eps if ep.group == group]


def _ext(name: str, fallback: str | None = "Frame", children: str = "layout") -> WidgetSpec:
    return WidgetSpec(
        name=name,
        display_name=name,
        category="Test",
        api_version=WIDGET_API_VERSION,
        children=children,  # type: ignore[arg-type]
        fallback=fallback,
    )


def test_core_widgets_match_core_names() -> None:
    names = [spec.name for spec in core_widgets()]
    assert len(names) == 24
    assert set(names) == CORE_CLASS_NAMES


def test_default_registry_loads_core_without_diagnostics() -> None:
    reset_default_registry()
    registry = default_registry()
    assert registry is default_registry()
    assert {spec.name for spec in registry.specs()} == CORE_CLASS_NAMES
    assert registry.diagnostics() == ()
    reset_default_registry()


def test_tree_walk_order_and_errors() -> None:
    doc = Document()
    win = Window(id="main", menubar=Menubar())
    doc.add_window(win)
    assert win.menubar is not None
    win.menubar.append_child(Menu(id="file"))
    frame = Widget(class_name="Frame", id="frame")
    button = Widget(class_name="Button", id="button")
    win.append_child(frame)
    frame.append_child(button)
    win.append_child(Include(id="inc", src="c.ui", component="c"))
    ids = [getattr(node, "id", None) for node in doc.walk()]
    assert ids == [None, "main", None, "file", "frame", "button", "inc"]
    assert button.window is win and win.document is doc and doc.main_window is win
    with pytest.raises(ModelError) as info:
        button.append_child(frame)
    assert info.value.code == "model.already_parented"
    assert frame.remove_child(button) == 0
    root = Widget(class_name="Frame", id="root")
    inner = Widget(class_name="Frame", id="inner")
    root.append_child(inner)
    with pytest.raises(ModelError, match="cannot be placed"):
        inner.append_child(root)


def test_registry_isolation_and_resolution() -> None:
    eps = (
        _EP("broken", "acme.mod:x", "pyguibud.widgets", _Dist("acme"), RuntimeError("boom")),
        _EP("good", "acme.mod:y", "pyguibud.widgets", _Dist("acme"), [_ext("acme:Box"), 42]),
        _EP("bad", "acme.mod:z", "pyguibud.widgets", None, lambda: _ext("Button")),
        _EP("qt", "acme.qt:b", "pyguibud.backends", _Dist("acme"), RuntimeError("no Qt")),
    )
    registry = Registry(entry_points=_source(*eps))
    codes = [d.code for d in registry.diagnostics()]
    assert "registry.load_failed" in codes
    assert "registry.bad_spec" in codes
    assert "registry.reserved_name" in codes
    assert "registry.core_fallback" in codes
    assert registry.require("acme:Box").plugin == "acme"
    resolved = registry.resolve("acme:Box", "ttkbootstrap")
    assert resolved.is_fallback and resolved.spec.name == "Frame"
    assert resolved.code == "registry.no_factory"
    missing = registry.resolve("zz:Gone", "ttkbootstrap", fallback="Label")
    assert missing.code == "registry.plugin_missing"
    with pytest.raises(RegistryError):
        registry.resolve("zz:Gone", "ttkbootstrap")
    assert [b.name for b in registry.backends()] == ["qt"]
    with pytest.raises(RegistryError) as info:
        registry.load_backend("qt")
    assert info.value.code == "registry.backend_failed"


def test_core_imports_no_toolkit() -> None:
    code = (
        "import sys, pyguibud.core; from pyguibud.core.registry import default_registry; "
        "default_registry().specs(); "
        "assert not {'tkinter','ttkbootstrap','PySide6'} & set(sys.modules)"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
