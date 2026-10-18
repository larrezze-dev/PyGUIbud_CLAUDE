"""Step 19d (hardening): the Tk plugin guard and session traces (H56, H60, H61, H62).

Spec ``docs/specs/hardening.md`` §3 "19d"; background ``docs/specs/plugins.md`` §14b.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import registry as registry_module
from pyguibud_runtime import LoadedUi, UiError
from tests.runtime.test_tb_factories import _registry
from tests.runtime.test_tb_factories_extra import _gauges, _load, _spec, loaded  # noqa: F401

pytestmark = pytest.mark.gui

_SIBLING = '<widget class="Label" id="keep"><prop name="text">Keep me</prop>'
_SIBLING += '<cell row="9" column="0"/></widget>'


def _failures(reg: Any) -> list[str]:
    return [d.params["stage"] for d in reg.diagnostics() if d.code == "registry.factory_failed"]


def _sibling(parent: Any) -> Any:
    """The ``keep`` Label built before the plugin widget (row 9 is placed, not built, last)."""
    return next(c for c in parent.winfo_children() if type(c).__name__ == "Label")


@pytest.mark.parametrize("shape", ["outer", "inner"])
def test_an_existing_widget_returned_by_a_factory_is_never_destroyed(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    """H61 (data loss): only what the factory made is swept."""

    def thief(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        victim = _sibling(parent)
        return victim if shape == "outer" else (ttkbootstrap.Frame(parent), victim)

    reg = _registry(_spec(thief))
    monkeypatch.setattr(registry_module, "_default", reg)
    ui = _load(tmp_path, tk_root, loaded, _SIBLING + _gauges(1))
    assert _failures(reg) == ["check"]
    assert ui.keep.winfo_exists() and ui.keep.cget("text") == "Keep me"
    assert type(ui.g0).__name__ == "Label" and ui.g0.cget("text") == "G0"  # the fallback
    names = sorted(type(c).__name__ for c in ui.keep.master.winfo_children())
    assert names == ["Label", "Label"]  # the new Frame was swept


def test_the_bootstyle_retry_sweeps_a_widget_made_outside_the_parent(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H60: the first (styled) attempt leaves a Label on the window; the retry removes it."""
    calls: list[object] = []

    def picky(parent: Any, _props: object, _var: object, bootstyle: object) -> Any:
        import ttkbootstrap

        calls.append(bootstyle)
        if bootstyle is not None:
            ttkbootstrap.Label(parent.winfo_toplevel(), text="stray")
            raise TypeError("no bootstyle here")
        return ttkbootstrap.Label(parent)

    monkeypatch.setattr(registry_module, "_default", _registry(_spec(picky)))
    body = (
        '<widget class="zz:Gauge" id="g" fallback="Label" tb:bootstyle="info">'
        '<prop name="text">Hi</prop><cell row="0" column="0"/></widget>'
    )
    ui = _load(tmp_path, tk_root, loaded, body)
    assert calls == ["info", None] and ui.g.cget("text") == "Hi"
    top = ui.g.winfo_toplevel()
    assert [type(c).__name__ for c in top.winfo_children()] == ["Frame"]  # the body only


def test_a_destroyed_parent_logs_no_fallback_warning(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H62: the build aborts, so "its fallback is shown" would be false."""

    def vandal(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        widget = ttkbootstrap.Label(parent)
        parent.destroy()
        return widget

    reg = _registry(_spec(vandal))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"), pytest.raises(UiError):
        _load(tmp_path, tk_root, loaded, _gauges(1))
    assert _failures(reg) == ["check"]
    assert "failed to build" not in caplog.text


def test_a_failing_factory_with_a_live_parent_still_logs_the_fallback(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raising(parent: Any, *_args: object) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(registry_module, "_default", _registry(_spec(raising)))
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        _load(tmp_path, tk_root, loaded, _gauges(1))
    assert caplog.text.count("failed to build") == 1


def test_a_destroyed_session_removes_its_traces(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
) -> None:
    """H56: a change handler never fires after destroy; the Meter link trace goes too."""
    calls: list[str] = []
    body = (
        '<widget class="Entry" id="en" bind="s"><event name="change" handler="h"/>'
        '<cell row="0" column="0"/></widget>'
        '<widget class="tb:Meter" id="mt" bind="d" fallback="Progressbar">'
        '<cell row="1" column="0"/></widget>'
    )
    variables = '<var id="s" type="string"/><var id="d" type="double"/>'
    ui = _load(tmp_path, tk_root, loaded, body, {"h": lambda: calls.append("h")}, variables)
    ui.vars.s.set("a")
    assert calls == ["h"] and ui.vars.d.trace_info() != []  # the Meter link
    ui.destroy()
    assert ui.vars.s.trace_info() == [] and ui.vars.d.trace_info() == []
    ui.vars.s.set("b")
    ui.vars.d.set(4.0)  # the destroyed meter's own variable is not reached
    assert calls == ["h"]


def test_a_text_setter_raising_after_the_build_is_isolated(
    tmp_path: Path,
    tk_root: Any,
    loaded: list[LoadedUi],  # noqa: F811
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """H49: the first text set passes the factory guard; a later one (apply_texts,
    retranslate) raises. It is logged once, reported, and the other slots still apply."""

    def fragile(parent: Any, *_args: object) -> Any:
        import ttkbootstrap

        class Fragile(ttkbootstrap.Label):
            sets = 0

            def configure(self, cnf: Any = None, **kw: Any) -> Any:
                if "text" in kw:
                    self.sets += 1
                    if self.sets >= 2:
                        raise RuntimeError("second text set")
                return super().configure(cnf, **kw)

        return Fragile(parent)

    reg = _registry(_spec(fragile))
    monkeypatch.setattr(registry_module, "_default", reg)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = _load(tmp_path, tk_root, loaded, _gauges(2) + _SIBLING)
        ui.retranslate()
    assert ui.keep.cget("text") == "Keep me"
    assert str(ui.g0.cget("text")) == "G0" and str(ui.g1.cget("text")) == "G1"
    assert caplog.text.count("could not show the new text") == 1
    assert _failures(reg) == ["wire"]
