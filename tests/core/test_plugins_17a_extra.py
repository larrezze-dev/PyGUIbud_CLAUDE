"""Step 17a, independent pass: hostile plugins, isolation, boundary and property tests.

Every registry is built from injected fake entry points (never the installed ones).
"""

from __future__ import annotations

import re
import sys
import types
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pyguibud.core import (
    NS_TB,
    WIDGETS_GROUP,
    Document,
    EntryPointSource,
    GridCell,
    Layout,
    Prop,
    PropertyDef,
    Registry,
    Widget,
    WidgetSpec,
    Window,
    read_ui_string,
)
from pyguibud.core.commands import CommandStack, SetExtraAttr
from pyguibud.core.errors import ModelError
from pyguibud.core.model import canonical_distribution
from pyguibud.core.validate import validate
from pyguibud.core.widgets import core_widgets, tb_widgets

BOOTSTYLE = f"{{{NS_TB}}}bootstyle"


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
    loads: int = 0

    def load(self) -> object:
        self.loads += 1
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


def _builtins() -> list[_EP]:
    return [
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud-runtime"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud-runtime"), tb_widgets),
    ]


def _plugin(obj: object, dist: str = "acme", name: str = "acme", value: str | None = None) -> _EP:
    return _EP(name, value or f"{dist.replace('-', '_')}.mod:specs", _Dist(dist), obj)


def _source(*eps: _EP) -> EntryPointSource:
    every = [*_builtins(), *eps]

    def source(group: str) -> Iterable[_EP]:
        return [ep for ep in every if ep.group == group]

    return source


def _spec(name: str = "acme:Gauge", fallback: str = "Label", **kw: Any) -> WidgetSpec:
    return WidgetSpec(
        name=name, display_name="Gauge", category="Acme", api_version=1, fallback=fallback, **kw
    )


def _codes(reg: Registry) -> list[str]:
    return [d.code for d in reg.diagnostics()]


# ---------------------------------------------------------------- hostile entry points
class _Boom(BaseException):
    """A BaseException that is neither Exception, SystemExit nor KeyboardInterrupt."""


@pytest.mark.parametrize(
    "garbage", [None, 42, "text", b"bytes", object(), {"a": 1}, [1, "x", None], lambda: 7]
)
def test_garbage_from_an_entry_point_gives_diagnostics_not_a_crash(garbage: object) -> None:
    reg = Registry(entry_points=_source(_plugin(garbage), _plugin(_spec(), "good", "good")))
    assert reg.get("acme:Gauge") is not None  # sibling unaffected
    assert _codes(reg), "garbage must produce at least one diagnostic"
    assert all(c.startswith("registry.") for c in _codes(reg))


def test_iterable_failing_midway_is_caught() -> None:
    def gen() -> Iterator[object]:
        yield _spec("acme:One")
        raise RuntimeError("mid-iteration")

    reg = Registry(entry_points=_source(_plugin(gen)))
    assert _codes(reg) == ["registry.load_failed"]


def test_other_base_exceptions_propagate_by_design() -> None:
    """Only (Exception, SystemExit) are isolated (spec section 3); others propagate."""
    reg = Registry(entry_points=_source(_plugin(_Boom())))
    with pytest.raises(_Boom):
        reg.load()


def test_entry_point_with_no_distribution_is_not_builtin_and_named_unknown() -> None:
    ep = _EP("x", "pyguibud.core.widgets:x", None, [_spec("tb:Evil")])
    reg = Registry(entry_points=_source(ep))
    assert reg.get("tb:Evil") is None
    assert [d.distribution for d in reg.diagnostics()] == ["unknown"]


@pytest.mark.parametrize("dist", ["PyGUIbud-evil", "pyguibud2", "pyguibud.plugins", "xpyguibud"])
def test_lookalike_distribution_cannot_impersonate_builtin(dist: str) -> None:
    ep = _plugin([_spec("tb:Evil"), _spec("Frame2", "Label")], dist, "x", "pyguibud.core.widgets:x")
    reg = Registry(entry_points=_source(ep))
    assert reg.get("tb:Evil") is None and reg.get("Frame2") is None
    assert set(_codes(reg)) == {"registry.reserved_prefix", "registry.reserved_name"}


def test_duplicate_names_across_plugins_first_wins_with_a_warning() -> None:
    a, b = _plugin(_spec(), "aaa", "a"), _plugin(_spec(), "bbb", "b")
    reg = Registry(entry_points=_source(b, a))
    assert reg.require("acme:Gauge").plugin == "aaa"
    dup = [d for d in reg.diagnostics() if d.code == "registry.duplicate"]
    assert len(dup) == 1 and dup[0].severity == "warning" and dup[0].distribution == "bbb"


def test_plugin_cannot_override_a_tb_widget_or_core_widget() -> None:
    reg = Registry(entry_points=_source(_plugin([_spec("tb:Meter"), _spec("Label", "Label")])))
    assert reg.require("tb:Meter").plugin is None
    assert set(_codes(reg)) == {"registry.reserved_prefix", "registry.reserved_name"}


@pytest.mark.parametrize("name", ["", ":", "a:", ":b", "a:b:c", "a b:c", "1a:b", "ac me:x"])
def test_bad_class_names_are_diagnosed(name: str) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(name))))
    assert reg.get(name) is None
    assert _codes(reg) and all(c.startswith("registry.") for c in _codes(reg))


@pytest.mark.parametrize("version", [0, 2, -1, 99])
def test_incompatible_api_version_is_a_warning(version: int) -> None:
    spec = WidgetSpec(
        name="acme:G", display_name="G", category="A", api_version=version, fallback="Label"
    )
    reg = Registry(entry_points=_source(_plugin(spec)))
    assert reg.get("acme:G") is None
    assert [(d.code, d.severity) for d in reg.diagnostics()] == [
        ("registry.incompatible_api", "warning")
    ]


@pytest.mark.parametrize("fallback", ["acme:Other", "Nonexistent", "tb:Meter", ""])
def test_bad_fallbacks_are_diagnosed(fallback: str) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(fallback=fallback))))
    assert reg.get("acme:Gauge") is None
    assert _codes(reg) == ["registry.bad_fallback"]


def test_container_mismatch_with_fallback() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(fallback="Frame", children="none"))))
    assert reg.get("acme:Gauge") is None
    assert _codes(reg) == ["registry.fallback_mismatch"]


@pytest.mark.parametrize(
    "kw",
    [
        {"events": ("command", "bogus")},
        {"events": ("select",)},  # Label has no select
        {"bind_types": ("string", "bool")},
    ],
)
def test_parity_violations_on_label_fallback(kw: dict[str, Any]) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(**kw))))
    assert reg.get("acme:Gauge") is None
    assert _codes(reg) == ["registry.not_fallback_compatible"]


def test_a_blank_display_name_is_diagnosed() -> None:
    spec = WidgetSpec(
        name="acme:G", display_name="  ", category="A", api_version=1, fallback="Label"
    )
    reg = Registry(entry_points=_source(_plugin(spec)))
    assert reg.get("acme:G") is None and _codes(reg) == ["registry.bad_display_name"]


def test_many_failing_plugins_one_diagnostic_each_and_siblings_load() -> None:
    eps = [_plugin(RuntimeError(str(i)), f"bad-{i:03d}", f"b{i}") for i in range(100)]
    eps.append(_plugin(_spec(), "good", "good"))
    reg = Registry(entry_points=_source(*eps))
    assert _codes(reg).count("registry.load_failed") == 100
    assert reg.get("acme:Gauge") is not None
    assert len(reg.failed_distributions()) == 100


def test_source_that_raises_is_diagnosed_and_core_still_works() -> None:
    def broken(group: str) -> Iterable[_EP]:
        raise OSError("metadata gone")

    reg = Registry(entry_points=broken)
    assert reg.get("Label") is not None  # core safety net
    assert "registry.load_failed" in _codes(reg)


def test_disabled_with_garbage_names_does_not_crash() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec())), disabled=["", "  ", "!!!"])
    assert reg.get("acme:Gauge") is not None


def test_load_is_repeatable_and_resets_diagnostics() -> None:
    reg = Registry(entry_points=_source(_plugin(RuntimeError("x"))))
    first = _codes(reg)
    reg.load()
    reg.load()
    assert _codes(reg) == first


# ---------------------------------------------------------------- load_factory
@pytest.mark.parametrize(
    "ref",
    ["x", "a:b:c", "", ":", "a:", ":b", "no_such_module_xyz:f", "os:sep", "os.path:nope", "os:"],
)
def test_load_factory_with_bad_refs_never_raises(ref: str) -> None:
    # Specs bypassing registration (hand-built) must still be safe to resolve.
    reg = Registry(entry_points=_source())
    spec = _spec(factories={"tkinter": ref})
    assert reg.load_factory(spec, "tkinter") is None
    assert _codes(reg) == ["registry.factory_failed"]


@pytest.mark.parametrize("ref", [3, None, 1.5, ["a:b"], object()])
def test_load_factory_with_non_string_non_callable_refs(ref: Any) -> None:
    reg = Registry(entry_points=_source())
    spec = _spec(factories={"tkinter": ref})
    assert reg.load_factory(spec, "tkinter") is None  # no crash


def test_load_factory_non_callable_attribute(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("acme_nc_mod")
    module.__dict__["f"] = 5
    monkeypatch.setitem(sys.modules, "acme_nc_mod", module)
    reg = Registry(entry_points=_source())
    assert reg.load_factory(_spec(factories={"tkinter": "acme_nc_mod:f"}), "tkinter") is None
    assert _codes(reg) == ["registry.factory_failed"]


# ---------------------------------------------------------------- a .ui never imports anything
_UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"
    xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="zz_evil_pkg:Gauge" id="g" fallback="Label" plugin="os-system"
        tb:bootstyle="primary">
      <cell row="0" column="0"/>
    </widget>
    <widget class="tb:Meter" id="m" fallback="Progressbar" plugin="zz_evil_mod:thing">
      <cell row="1" column="0"/>
    </widget>
  </window>
</pyguibud-ui>
"""


def test_opening_and_validating_a_ui_with_plugin_attrs_imports_nothing() -> None:
    reg = Registry(entry_points=_source())
    reg.load()  # warm: registry imports are not what is under test
    before = set(sys.modules)
    result = read_ui_string(_UI)
    report = validate(result.document, reg)
    new = set(sys.modules) - before
    assert not new, sorted(new)
    assert not {"tkinter", "ttkbootstrap", "PySide6"} & new
    assert "zz_evil_pkg" not in sys.modules and "zz_evil_mod" not in sys.modules
    assert report is not None


def test_a_file_cannot_select_a_plugin_that_is_not_installed() -> None:
    reg = Registry(entry_points=_source())
    report = validate(read_ui_string(_UI).document, reg)
    assert "plugin_missing" in {f.code.removeprefix("validate.") for f in report.findings}


# ---------------------------------------------------------------- property tests
def _doc(widget: Widget) -> Document:
    document = Document()
    window = Window(id="main", layout=Layout(type="grid"))
    widget.placement = GridCell(row=0, column=0)
    window.append_child(widget)
    document.add_window(window)
    return document


_BOOT = st.one_of(st.none(), st.text(alphabet="abcdefghijklmnopqrstuvwxyz -", max_size=70))


@settings(max_examples=60, deadline=None)
@given(values=st.lists(_BOOT, min_size=1, max_size=6))
def test_set_extra_attr_undo_redo_round_trip(values: list[str | None]) -> None:
    widget = Widget(class_name="Button", id="w")
    reg = Registry(entry_points=_source())
    stack = CommandStack(_doc(widget), reg)
    for value in values:
        before = dict(widget.extra_attrs)
        outcome = stack.execute(SetExtraAttr(widget, BOOTSTYLE, value))
        if not outcome:  # rejected: the model must be untouched
            assert dict(widget.extra_attrs) == before
        findings = validate(stack.document, reg).findings
        assert "validate.bad_bootstyle" not in {f.code for f in findings}
    final = dict(widget.extra_attrs)
    while stack.can_undo:
        stack.undo()
    assert widget.extra_attrs == {}
    while stack.can_redo:
        stack.redo()
    assert dict(widget.extra_attrs) == final


def _prop_codes(class_name: str, fallback: str, prop: str, value: str) -> set[str]:
    widget = Widget(class_name=class_name, id="w", fallback=fallback)
    widget.set_prop(Prop(name=prop, value=value))
    report = validate(_doc(widget), Registry(entry_points=_source()))
    return {f.code.removeprefix("validate.") for f in report.findings}


def _definition(class_name: str, prop: str) -> PropertyDef:
    found = Registry(entry_points=_source()).require(class_name).property(prop)
    assert found is not None
    return found


@settings(max_examples=150, deadline=None)
@given(value=st.text(max_size=80))
def test_amount_format_validation_matches_its_pattern(value: str) -> None:
    definition = _definition("tb:Meter", "amount_format")
    assert definition.pattern is not None and definition.max_length is not None
    expected_ok = (
        len(value) <= definition.max_length and re.fullmatch(definition.pattern, value) is not None
    )
    codes = _prop_codes("tb:Meter", "Progressbar", "amount_format", value)
    assert bool(codes & {"bad_pattern", "value_too_long"}) is (not expected_ok)
    if expected_ok:  # an accepted value can never raise in str.format with a float
        value.format(1.5)


@settings(max_examples=100, deadline=None)
@given(n=st.integers(min_value=0, max_value=600))
def test_max_length_boundary_on_subtext(n: int) -> None:
    limit = _definition("tb:Meter", "subtext").max_length or 100_000
    codes = _prop_codes("tb:Meter", "Progressbar", "subtext", "x" * n)
    assert ("value_too_long" in codes) == (n > limit)


@settings(max_examples=50, deadline=None)
@given(disabled=st.sets(st.sampled_from(["a-one", "b-two", "c-three", "A_One", "B.Two"])))
def test_disabled_filter_never_loads_a_disabled_distribution(disabled: set[str]) -> None:
    names = ["a-one", "b-two", "c-three"]
    eps = [_plugin(_spec(f"p{i}:G"), d, f"e{i}") for i, d in enumerate(names)]
    reg = Registry(entry_points=_source(*eps), disabled=disabled)
    reg.load()
    wanted = {canonical_distribution(d) for d in disabled}
    for ep, dist in zip(eps, names, strict=True):
        assert (ep.loads == 0) == (canonical_distribution(dist) in wanted)
    assert reg.disabled_distributions() == wanted & set(names)
    assert _codes(reg).count("registry.disabled") == len(reg.disabled_distributions())


def test_property_def_pattern_rejects_non_string_types() -> None:
    with pytest.raises(ModelError):
        PropertyDef(name="p", type="int", pattern="x")
