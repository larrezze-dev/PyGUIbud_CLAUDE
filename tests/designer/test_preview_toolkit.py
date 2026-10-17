"""Preview > Toolkit (spec backends D17, B14): the pure side and the menu with a fake child."""

# ruff: noqa: F811 - the fixtures of test_preview_gui are re-used by import
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import default_registry
from pyguibud.core.xml_io import read_ui_bytes
from pyguibud.designer import preview as pv
from pyguibud.designer.actions import ActionRegistry, MenuDef, label_of
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.settings import Settings, parse_settings, save_settings
from pyguibud.designer.standard_actions import PreviewCallbacks, register_standard_actions
from pyguibud.designer.standard_actions import ShellCallbacks as _Shell
from tests.designer.fakes import FakeProcess
from tests.designer.test_preview_gui import _poll, app, children  # noqa: F401

HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"


def _fake_install(monkeypatch: pytest.MonkeyPatch, present: bool) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if present else None)


def test_pyside6_is_greyed_and_named_when_not_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_install(monkeypatch, present=False)
    chosen: list[str] = []
    noop: Any = lambda *_a: None  # noqa: E731
    callbacks = PreviewCallbacks(
        noop, noop, lambda: True, lambda: False, noop, lambda: None, noop, lambda: False,
        ("ttkbootstrap", "tkinter", "pyside6", "my_fork"), chosen.append,
        lambda: "tkinter", pv.toolkit_installed,
    )  # fmt: skip
    registry = ActionRegistry()
    register_standard_actions(
        registry,
        _Shell(
            noop,
            noop,
            noop,
            noop,
            noop,
            noop,
            lambda: "light",
            noop,
            lambda: "en_GB",
            preview=callbacks,
        ),
    )
    items = {a.id: a for a in registry.actions() if a.menu == "preview.toolkit"}
    assert list(items) == [f"preview.toolkit.{n}" for n in callbacks.toolkits]
    pyside = items["preview.toolkit.pyside6"]
    assert label_of(pyside) == "PySide6 (not installed)" and not registry.is_enabled(pyside)
    assert label_of(items["preview.toolkit.tkinter"]) == "tkinter"
    assert registry.is_checked(items["preview.toolkit.tkinter"])
    assert not registry.is_checked(items["preview.toolkit.ttkbootstrap"])
    assert label_of(items["preview.toolkit.my_fork"]) == "my__fork"  # no mnemonic from "_"
    _fake_install(monkeypatch, present=True)
    assert label_of(pyside) == "PySide6" and registry.is_enabled(pyside)


def test_the_toolkit_sub_menu_follows_language_and_precedes_theme() -> None:
    chosen: Any = lambda *_a: None  # noqa: E731
    registry = ActionRegistry()
    callbacks = PreviewCallbacks(
        chosen, chosen, lambda: True, lambda: False, chosen, lambda: None, chosen,
        lambda: False, ("ttkbootstrap",), chosen, lambda: "ttkbootstrap", lambda _n: True,
    )  # fmt: skip
    register_standard_actions(
        registry,
        _Shell(
            chosen,
            chosen,
            chosen,
            chosen,
            chosen,
            chosen,
            lambda: "light",
            chosen,
            lambda: "en_GB",
            preview=callbacks,
        ),
    )
    order = [i.id for i in registry.menu_items("preview") if isinstance(i, MenuDef)]
    assert order == ["preview.language", "preview.toolkit", "preview.theme"]


def test_a_toolkit_change_adds_the_reason_and_drops_the_theme(tmp_path: Path) -> None:
    session = DesignerSession(default_registry())
    session.open_document(read_ui_bytes(HELLO.read_bytes()), path=None)
    assert session.document is not None
    for backend, expected in (("ttkbootstrap", ["the theme is chosen for the preview only"]),
                              ("tkinter", ["the exported module uses ttkbootstrap"])):  # fmt: skip
        request = pv.PreviewRequest(
            session.document, None, True, False, "main", None, "darkly", None, backend
        )
        prepared = pv.prepare_preview(request, tmp_path, ())
        assert isinstance(prepared, pv.PreparedPreview)
        assert [pv.reason_text(r) for r in prepared.differences] == expected
    assert isinstance(prepared, pv.PreparedPreview)
    assert "--backend" in pv.child_argv(prepared, tmp_path, ui_lang="en_GB", lang=None, theme=None,
                                        backend="tkinter")  # fmt: skip


@pytest.mark.parametrize(
    "value", ["pyside6; rm -rf", "", "x" * 10_240, 5, None, ["tkinter"], "PySide6", "tk\n"]
)
def test_b14_a_malformed_setting_falls_back(value: object, tmp_path: Path) -> None:
    parsed = parse_settings(json.dumps({"preview_backend": value}).encode())
    assert parsed is not None and parsed.preview_backend == "ttkbootstrap"
    assert "preview_backend" not in parsed.extra


def test_the_toolkit_is_stored_only_when_it_is_not_the_default(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert save_settings(Settings(preview_backend="tkinter"), path=path)
    assert json.loads(path.read_text("utf-8"))["preview_backend"] == "tkinter"
    parsed = parse_settings(path.read_bytes())
    assert parsed is not None and parsed.preview_backend == "tkinter"
    assert save_settings(Settings(), path=tmp_path / "other.json")
    assert "preview_backend" not in json.loads((tmp_path / "other.json").read_text("utf-8"))


@pytest.mark.gui
def test_choosing_a_toolkit_restarts_the_preview_with_backend(
    app: Any,
    children: list[FakeProcess],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preview = app.preview
    assert app.shell._invoke("preview.toolkit.ttkbootstrap")
    preview.run()
    children[0].ready()
    _poll(preview)
    assert app.shell._invoke("preview.toolkit.tkinter")
    assert app.settings.preview_backend == "tkinter"
    children[0].end(0, {"code": "ok"})
    _poll(preview)
    argv = children[1].argv
    assert argv[argv.index("--backend") + 1] == "tkinter" and "--theme" not in argv
    children[1].ready(themes=())
    _poll(preview)
    assert "the exported module uses ttkbootstrap" in app.shell._message
    use = app.registry.get("preview.use_theme")
    assert use is not None and not app.registry.is_enabled(use)
    menu = app.shell.submenus["preview.theme"]
    menu.tk.eval(str(menu.cget("postcommand")))
    assert str(menu.entrycget(0, "state")) == "disabled"


@pytest.mark.gui
def test_a_saved_toolkit_that_is_not_installed_is_kept_but_not_used(
    app: Any,
    children: list[FakeProcess],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_install(monkeypatch, present=False)
    app.settings.preview_backend = "pyside6"
    app.preview.run()
    argv = children[0].argv
    assert argv[argv.index("--backend") + 1] == "ttkbootstrap"
    children[0].ready()
    _poll(app.preview)
    note = "PySide6 is not installed; the preview uses ttkbootstrap."
    assert note in app.shell._message
    assert app.settings.preview_backend == "pyside6"  # kept
    children[0].end(0, {"code": "ok"})
    _poll(app.preview)
    app.preview.run()
    children[1].ready()
    _poll(app.preview)
    assert note not in app.shell._message  # said once
    app.preview.set_toolkit("pyside6")  # a hand-made call cannot choose it either
    assert app.preview.toolkit() == "ttkbootstrap"
