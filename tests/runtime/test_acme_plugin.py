"""Step 17c: the sample plugin ``acme:ColourSwatch`` built for real by the Tk backends.

Spec ``docs/specs/plugins.md`` 9 and 11. ``acme_pyguibud`` is imported from
``examples/acme_plugin/src`` through a fake entry point: an installed acme never changes
these tests.
"""

from __future__ import annotations

import importlib
import logging
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import registry as registry_module
from pyguibud.core.registry import WIDGETS_GROUP, Registry, _metadata_entry_points
from pyguibud.core.widgets import core_widgets, tb_widgets
from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import write_ui

pytestmark = pytest.mark.gui

ACME_SRC = Path(__file__).resolve().parents[2] / "examples" / "acme_plugin" / "src"
BACKENDS = ("ttkbootstrap", "tkinter")


@dataclass
class _Dist:
    name: str


@dataclass
class _EP:
    name: str
    value: str
    dist: _Dist | None
    obj: object
    group: str = WIDGETS_GROUP

    def load(self) -> object:
        return self.obj


@pytest.fixture
def acme(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str | None], Registry]]:
    """Import acme (optionally broken) and install a default registry that knows it."""

    def make(mode: str | None) -> Registry:
        if mode is None:
            monkeypatch.delenv("ACME_PYGUIBUD_BREAK", raising=False)
        else:
            monkeypatch.setenv("ACME_PYGUIBUD_BREAK", mode)
        monkeypatch.syspath_prepend(str(ACME_SRC))  # load_factory imports the string ref later
        monkeypatch.delitem(sys.modules, "acme_pyguibud", raising=False)
        module = importlib.import_module("acme_pyguibud")
        widgets = [
            _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud"), core_widgets),
            _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud"), tb_widgets),
            _EP("acme", "acme_pyguibud:widgets", _Dist("acme-pyguibud"), module.widgets),
        ]

        def source(group: str) -> Iterable[Any]:
            return widgets if group == WIDGETS_GROUP else _metadata_entry_points(group)

        reg = Registry(entry_points=source)
        monkeypatch.setattr(registry_module, "_default", reg)
        return reg

    yield make
    sys.modules.pop("acme_pyguibud", None)


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before  # no stray widgets


def _swatch(index: int, extra: str = "", bind: str = "") -> str:
    bound = f' bind="{bind}"' if bind else ""
    return (
        f'<widget class="acme:ColourSwatch" id="swt{index}" fallback="Label"'
        f' plugin="acme-pyguibud"{bound}><prop name="text" translatable="true">Swatch</prop>'
        f'{extra}<cell row="{index}" column="0"/></widget>'
    )


def _load(tmp_path: Path, body: str, backend: str, tk_root: Any, **parts: str) -> LoadedUi:
    path = write_ui(tmp_path / "acme.ui", f'<window id="w"><layout type="grid"/>{body}</window>',
                    **parts)  # fmt: skip
    return load_ui(path, None, strict=False, backend=backend, master=tk_root)


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_swatch_builds_with_its_colour_and_text(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], acme: Any, backend: str,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    reg = acme(None)
    body = _swatch(0) + _swatch(1, '<prop name="colour">#AA0011</prop>')
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, body, backend, tk_root)
    loaded.append(ui)
    tk_root.update_idletasks()
    first, second = ui.swt0, ui.swt1
    assert first.winfo_class() == "Label" and type(first).__module__ == "tkinter"
    assert first.cget("bg").lower() == "#2e86de"  # the PropertyDef default reaches the factory
    assert second.cget("bg").lower() == "#aa0011"  # the file's value reaches the factory
    assert first.cget("text") == "Swatch"
    assert "failed to build" not in caplog.text and "shown as its fallback" not in caplog.text
    assert [d for d in reg.diagnostics() if d.code == "registry.factory_failed"] == []


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_bound_string_variable_drives_the_text(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], acme: Any, backend: str
) -> None:
    acme(None)
    ui = _load(tmp_path, _swatch(0, bind="name"), backend, tk_root,
               variables='<var id="name" type="string" default="Start"/>')  # fmt: skip
    loaded.append(ui)
    assert ui.swt0.cget("text") == "Start"
    ui.vars.name.set("Changed")
    tk_root.update_idletasks()
    assert ui.swt0.cget("text") == "Changed"


@pytest.mark.parametrize("backend", BACKENDS)
def test_a_breaking_factory_falls_back_once(
    tmp_path: Path, tk_root: Any, loaded: list[LoadedUi], acme: Any, backend: str,
    caplog: pytest.LogCaptureFixture,
) -> None:  # fmt: skip
    reg = acme("factory")
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, _swatch(0) + _swatch(1), backend, tk_root)
    loaded.append(ui)
    for widget in (ui.swt0, ui.swt1):
        assert widget.winfo_class() in ("TLabel", "Label")
        assert widget.cget("text") == "Swatch"
        assert str(widget.cget("background")).lower() != "#2e86de"  # not the swatch
    failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
    assert [(d.distribution, d.params["stage"]) for d in failures] == [("acme-pyguibud", "create")]
    assert caplog.text.count("'acme:ColourSwatch' failed to build") == 1
