"""Step 17a: the headless plugin API (spec ``docs/specs/plugins.md`` sections 3, 5, 6 and 11).

Every registry here is built from injected fake entry points, so an installed plugin never
changes the outcome.
"""

from __future__ import annotations

import sys
import time
import types
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from pyguibud.core import (
    NS_TB,
    NS_UI,
    WIDGETS_GROUP,
    Document,
    EntryPointSource,
    GridCell,
    Layout,
    Prop,
    PropertyDef,
    Registry,
    Variable,
    Widget,
    WidgetSpec,
    Window,
)
from pyguibud.core.commands import CommandStack, SetExtraAttr
from pyguibud.core.errors import ModelError
from pyguibud.core.model import BACKEND_NAME, canonical_distribution
from pyguibud.core.validate import BIND_TYPES, ValidationReport, validate
from pyguibud.core.widgets import core_widgets, tb_widgets

BOOTSTYLE = f"{{{NS_TB}}}bootstyle"


# ---------------------------------------------------------------- fake entry points
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
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud"), tb_widgets),
    ]


def _plugin(obj: object, dist: str = "acme", name: str = "acme") -> _EP:
    return _EP(name, f"{dist.replace('-', '_')}.mod:specs", _Dist(dist), obj)


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


# ---------------------------------------------------------------- model
def test_backend_name_moved_to_core_and_re_exported() -> None:
    from pyguibud import backends

    assert backends.BACKEND_NAME is BACKEND_NAME


def test_canonical_distribution_is_pep_503() -> None:
    assert canonical_distribution("Acme_Plugin.X--y") == "acme-plugin-x-y"


def test_pattern_gets_a_default_max_length() -> None:
    definition = PropertyDef(name="p", type="string", pattern="[a-z]+")
    assert definition.max_length == 256


@pytest.mark.parametrize(
    "kw",
    [
        {"type": "int", "pattern": "x"},
        {"type": "string", "pattern": "("},
        {"type": "string", "max_length": 0},
        {"type": "string", "max_length": 100_001},
        {"type": "string", "max_length": True},
    ],
)
def test_bad_constraints_are_refused(kw: dict[str, Any]) -> None:
    with pytest.raises(ModelError):
        PropertyDef(name="p", **kw)


# ---------------------------------------------------------------- registry
def test_tb_widgets_register_without_diagnostics() -> None:
    reg = Registry(entry_points=_source())
    assert reg.diagnostics() == ()
    for spec in tb_widgets():
        registered = reg.require(spec.name)
        # Step 17b: one string reference, for ttkbootstrap only (D3, D11).
        assert registered.plugin is None and set(registered.factories) == {"ttkbootstrap"}
        assert str(registered.factories["ttkbootstrap"]).startswith("pyguibud.backends._tbwidgets:")
        assert not reg.resolve(spec.name, "ttkbootstrap").is_fallback
        for backend in ("tkinter", "pyside6"):
            resolved = reg.resolve(spec.name, backend)
            assert resolved.is_fallback and resolved.code == "registry.no_factory"


def test_tb_widgets_obey_the_fallback_parity() -> None:
    by_name = {spec.name: spec for spec in core_widgets()}
    for spec in tb_widgets():
        fallback = by_name[spec.fallback or ""]
        assert set(spec.events) <= set(fallback.events), spec.name
        assert set(spec.bind_types or ()) <= set(BIND_TYPES[fallback.name]), spec.name
        for definition in spec.properties:
            shared = fallback.property(definition.name)
            assert shared is None or shared == definition, (spec.name, definition.name)


def test_safety_net_registers_tb_widgets_when_metadata_is_stale() -> None:
    core_only = _builtins()[0]
    reg = Registry(entry_points=lambda group: [core_only] if group == WIDGETS_GROUP else [])
    assert reg.get("tb:Meter") is not None
    assert _codes(reg) == ["registry.core_fallback"]


def test_value_prefix_alone_is_not_builtin() -> None:
    spoof = _EP("x", "pyguibud.core.widgets:x", _Dist("evil"), [_spec("tb:Evil", "Label")])
    reg = Registry(entry_points=_source(spoof))
    assert reg.get("tb:Evil") is None
    assert _codes(reg) == ["registry.reserved_prefix"]


def test_system_exit_at_import_and_in_the_spec_callable_is_caught() -> None:
    def leave() -> None:
        raise SystemExit(3)

    eps = (_plugin(SystemExit(2), "a-one"), _plugin(leave, "b-two"), _plugin(_spec(), "c-ok"))
    reg = Registry(entry_points=_source(*eps))
    failed = [d for d in reg.diagnostics() if d.code == "registry.load_failed"]
    assert [d.distribution for d in failed] == ["a-one", "b-two"]
    assert "SystemExit(2)" in failed[0].message and "SystemExit(3)" in failed[1].message
    assert reg.get("acme:Gauge") is not None  # siblings still load
    assert reg.failed_distributions() == {"a-one", "b-two"}


def test_keyboard_interrupt_propagates() -> None:
    reg = Registry(entry_points=_source(_plugin(KeyboardInterrupt())))
    with pytest.raises(KeyboardInterrupt):
        reg.load()


def test_disabled_filters_before_load_once_per_distribution() -> None:
    first, second = _plugin(_spec(), "Acme_Plugin", "a"), _plugin(_spec("acme:B"), "acme-plugin")
    reg = Registry(entry_points=_source(first, second), disabled=["ACME.plugin"])
    assert first.loads == second.loads == 0
    assert _codes(reg) == ["registry.disabled"]
    assert reg.disabled_distributions() == {"acme-plugin"}
    assert reg.get("acme:Gauge") is None


def test_disabled_all_is_safe_mode_but_keeps_builtins() -> None:
    plugin = _plugin(_spec())
    reg = Registry(entry_points=_source(plugin), disabled="all")
    assert plugin.loads == 0
    assert reg.get("tb:Meter") is not None and reg.get("Frame") is not None
    assert reg.disabled_distributions() == {"acme"}


def test_reserved_tb_prefix() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec("tb:Gauge"))))
    assert reg.get("tb:Gauge") is None
    assert _codes(reg) == ["registry.reserved_prefix"]


@pytest.mark.parametrize(
    "kw", [{"events": ("command",)}, {"bind_types": ("bool",)}, {"bind_types": ("string",)}]
)
def test_fallback_parity_violations_are_ignored(kw: dict[str, Any]) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(fallback="Progressbar", **kw))))
    assert reg.get("acme:Gauge") is None
    assert _codes(reg) == ["registry.not_fallback_compatible"]


def test_a_compatible_bind_types_subset_is_accepted() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(bind_types=("string",)))))
    assert reg.require("acme:Gauge").bind_types == ("string",)


@pytest.mark.parametrize(
    "factories",
    [{"Tk!": print}, {"tkinter": "not a ref"}, {"tkinter": "mod:attr.sub"}, {"tkinter": 3}],
)
def test_bad_factories_are_refused(factories: dict[str, Any]) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(factories=factories))))
    assert reg.get("acme:Gauge") is None
    assert _codes(reg) == ["registry.bad_factory"]


def test_load_factory_resolves_lazily_and_caches() -> None:
    spec = _spec(factories={"tkinter": "os.path:join", "pyside6": print})
    reg = Registry(entry_points=_source(_plugin(spec)))
    import os.path

    assert reg.load_factory(reg.require("acme:Gauge"), "tkinter") is os.path.join
    assert reg.load_factory(reg.require("acme:Gauge"), "pyside6") is print
    assert reg.load_factory(reg.require("acme:Gauge"), "ttkbootstrap") is None
    assert reg.diagnostics() == ()


@pytest.mark.parametrize("ref", ["no_such_module_xyz:f", "os.path:no_such_attr", "os:sep"])
def test_load_factory_failure_is_reported_once(ref: str) -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(factories={"tkinter": ref}))))
    spec = reg.require("acme:Gauge")
    before = reg.revision
    assert reg.load_factory(spec, "tkinter") is None
    assert reg.load_factory(spec, "tkinter") is None
    assert _codes(reg) == ["registry.factory_failed"]
    assert reg.revision == before + 1
    assert reg.failed_distributions() == {"acme"}


def test_load_factory_catches_system_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("acme_exit_mod")
    monkeypatch.setitem(sys.modules, "acme_exit_mod", module)
    leave = (_ for _ in ()).throw
    monkeypatch.setattr(module, "__getattr__", lambda name: leave(SystemExit(5)), raising=False)
    reg = Registry(entry_points=_source(_plugin(_spec(factories={"tkinter": "acme_exit_mod:f"}))))
    assert reg.load_factory(reg.require("acme:Gauge"), "tkinter") is None
    assert "SystemExit(5)" in reg.diagnostics()[0].message


def test_report_failure_deduplicates_and_bumps_revision() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec(), "Acme_Plugin")))
    reg.load()
    start = reg.revision
    reg.report_failure("acme:Gauge", "tkinter", "create", ValueError("x"))
    reg.report_failure("acme:Gauge", "tkinter", "create", ValueError("y"))
    reg.report_failure("acme:Gauge", "tkinter", "check", ValueError("z"))
    assert _codes(reg) == ["registry.factory_failed"] * 2
    assert reg.revision == start + 2
    first = reg.diagnostics()[0]
    assert first.distribution == "Acme_Plugin" and first.traceback is not None
    assert "create the widget" in first.message
    assert reg.failed_distributions() == {"acme-plugin"}


def test_resolve_names_a_failed_plugin() -> None:
    reg = Registry(entry_points=_source(_plugin(RuntimeError("boom"), "acme-pyguibud")))
    failed = reg.resolve("acme:Gauge", "tkinter", "Label", plugin="Acme_PyGUIbud")
    missing = reg.resolve("acme:Gauge", "tkinter", "Label", plugin="other")
    assert failed.code == "registry.plugin_failed" and missing.code == "registry.plugin_missing"


# ---------------------------------------------------------------- validator
def _doc(*widgets: Widget, variables: dict[str, str] | None = None) -> Document:
    document = Document()
    for name, kind in (variables or {}).items():
        document.variables[name] = Variable(id=name, type=kind)  # type: ignore[arg-type]
    window = Window(id="main", layout=Layout(type="grid"))
    for row, widget in enumerate(widgets):
        widget.placement = GridCell(row=row, column=0)
        window.append_child(widget)
    document.add_window(window)
    return document


def _widget(class_name: str, fallback: str | None = None, **kw: Any) -> Widget:
    props = kw.pop("props", {})
    widget = Widget(class_name=class_name, id=kw.pop("id", "w"), fallback=fallback, **kw)
    for name, value in props.items():
        widget.set_prop(Prop(name=name, value=value))
    return widget


def _check(document: Document, reg: Registry | None = None) -> ValidationReport:
    return validate(document, reg or Registry(entry_points=_source()))


def _codes_of(report: ValidationReport) -> list[str]:
    return [f.code.removeprefix("validate.") for f in report.findings]


@pytest.mark.parametrize("value", ["primary;x", "Primary", "a" * 65, "primary  x", "-x"])
def test_r83_bad_bootstyle_is_an_error(value: str) -> None:
    widget = _widget("Button", extra_attrs={BOOTSTYLE: value})
    assert _codes_of(_check(_doc(widget))) == ["bad_bootstyle"]


@pytest.mark.parametrize(
    ("class_name", "value", "expected"),
    [
        ("Button", "success-outline", []),
        ("tb:ToggleButton", "danger round-toggle", []),
        ("Button", "nonsense", ["bootstyle_ignored"]),
        ("Text", "info", ["bootstyle_ignored"]),
    ],
)
def test_r84_unknown_tokens_and_classes_without_bootstyle(
    class_name: str, value: str, expected: list[str]
) -> None:
    fallback = "Checkbutton" if class_name.startswith("tb:") else None
    widget = _widget(class_name, fallback, extra_attrs={BOOTSTYLE: value})
    report = _check(_doc(widget))
    assert _codes_of(report) == expected
    assert report.ok


def test_r85_unknown_tb_attribute_but_foreign_namespaces_untouched() -> None:
    widget = _widget("Label", extra_attrs={f"{{{NS_TB}}}colour": "x", "{urn:other}y": "z"})
    report = _check(_doc(widget))
    assert _codes_of(report) == ["unknown_extension_attr"]
    assert "tb:colour" in report.findings[0].message


@pytest.mark.parametrize("plugin", ["not valid!", "-acme", "a" * 101])
def test_r86_bad_plugin_name_uses_the_nameless_r28(plugin: str) -> None:
    widget = _widget("zz:Gauge", "Label", plugin=plugin)
    report = _check(_doc(widget))
    assert _codes_of(report) == ["bad_plugin_name", "plugin_missing"]
    assert "pip install" not in report.findings[1].message


def test_r87_r88_and_r28_selection() -> None:
    broken = _plugin(RuntimeError("boom"), "acme-broken", "a")
    off = _plugin(_spec("off:Gauge"), "acme-off", "b")
    reg = Registry(entry_points=_source(broken, off), disabled=["acme_off"])
    document = _doc(
        _widget("acme:Gauge", "Label", id="a", plugin="Acme.Broken"),
        _widget("off:Gauge", "Label", id="b", plugin="acme-off"),
        _widget("zz:Gauge", "Label", id="c", plugin="zz-gauge"),
    )
    report = _check(document, reg)
    assert _codes_of(report) == ["plugin_failed", "plugin_disabled", "plugin_missing"]
    assert "Help ▸ Plugins" in report.findings[0].message
    assert "pip install zz-gauge" in report.findings[2].message


def test_r87_needs_a_registry_that_knows_failures() -> None:
    document = _doc(_widget("acme:Gauge", "Label", plugin="acme"))
    assert _codes_of(validate(document, _CoreOnly())) == ["plugin_missing"]


@pytest.mark.parametrize(
    ("prop", "value"),
    [
        ("amount_format", "{0.__class__}"),
        ("amount_format", "{:>99999}"),
        ("amount_format", "{}{}"),
    ],
)
def test_r89_bad_pattern_on_meter(prop: str, value: str) -> None:
    widget = _widget("tb:Meter", "Progressbar", props={prop: value})
    report = _check(_doc(widget))
    assert _codes_of(report) == ["bad_pattern"]
    message = report.findings[0].message
    assert "'amount_format' on 'w'" in message and "'{}'" in message


def test_r89_r90_on_date_entry_and_good_values_pass() -> None:
    good = _widget("tb:DateEntry", "Entry", id="a", props={"value": "2026-10-14"})
    bad = _widget("tb:DateEntry", "Entry", id="b", props={"value": "14/10/2026"})
    digits = _widget("tb:DateEntry", "Entry", id="c", props={"value": "٢٠٢٦-10-14"})
    fmt = _widget("tb:DateEntry", "Entry", id="d", props={"date_format": "%Y" * 20})
    report = _check(_doc(good, bad, digits, fmt))
    assert _codes_of(report) == ["bad_pattern", "bad_pattern", "value_too_long"]


def test_tableview_columns_accept_64_headings() -> None:
    columns = ";".join(["x" * 64] * 64)
    ok = _widget("tb:Tableview", "Treeview", id="a", props={"columns": columns})
    bad = _widget("tb:Tableview", "Treeview", id="b", props={"columns": ";".join("y" * 65)})
    assert _codes_of(_check(_doc(ok, bad))) == ["bad_pattern"]


class _CoreOnly:
    """A lookup without the tb: specs: tb:Meter is then rendered in fallback mode."""

    def get(self, name: str) -> WidgetSpec | None:
        return {s.name: s for s in core_widgets()}.get(name)


def test_fallback_mode_skips_r89_r90() -> None:
    props = {"amount_format": "{0.__class__}", "subtext": "x" * 300}
    widget = _widget("tb:Meter", "Progressbar", props=props)
    assert _codes_of(validate(_doc(widget), _CoreOnly())) == ["plugin_missing"]


def test_redos_shaped_value_is_rejected_by_max_length_quickly() -> None:
    slow = WidgetSpec(
        name="acme:Slow",
        display_name="Slow",
        category="Acme",
        api_version=1,
        fallback="Label",
        properties=(PropertyDef(name="p", type="string", pattern=r"(a+)+$"),),
    )
    reg = Registry(entry_points=_source(_plugin(slow)))
    document = _doc(_widget("acme:Slow", "Label", props={"p": "a" * 5000 + "!"}))
    _check(document, reg)  # warm the caches
    best = min(_timed(document, reg) for _ in range(3))
    assert _codes_of(_check(document, reg)) == ["value_too_long"]
    assert best < 0.01


def _timed(document: Document, reg: Registry) -> float:
    started = time.perf_counter()
    _check(document, reg)
    return time.perf_counter() - started


@pytest.mark.parametrize(
    ("class_name", "fallback", "kind", "codes"),
    [
        ("tb:Meter", "Progressbar", "double", []),
        ("tb:Meter", "Progressbar", "string", ["bind_type_mismatch"]),
        ("tb:DateEntry", "Entry", "int", ["bind_type_mismatch"]),
        ("tb:Tableview", "Treeview", "string", ["bind_not_supported"]),
        ("tb:ToggleButton", "Checkbutton", "bool", []),
    ],
)
def test_bind_types(class_name: str, fallback: str, kind: str, codes: list[str]) -> None:
    widget = _widget(class_name, fallback, bind="v")
    assert _codes_of(_check(_doc(widget, variables={"v": kind}))) == codes


def test_bind_types_none_uses_the_fallback_row() -> None:
    reg = Registry(entry_points=_source(_plugin(_spec("acme:Gauge", "Entry"))))
    widget = _widget("acme:Gauge", "Entry", bind="v")
    assert _codes_of(_check(_doc(widget, variables={"v": "int"}), reg)) == []


# ---------------------------------------------------------------- SetExtraAttr
def _stack() -> tuple[CommandStack, Widget]:
    widget = _widget("Button")
    return CommandStack(_doc(widget), Registry(entry_points=_source())), widget


def test_set_extra_attr_set_remove_merge_undo() -> None:
    stack, widget = _stack()
    assert stack.execute(SetExtraAttr(widget, BOOTSTYLE, "primary"))
    assert stack.execute(SetExtraAttr(widget, BOOTSTYLE, "danger"))
    assert widget.extra_attrs == {BOOTSTYLE: "danger"}
    stack.undo()
    assert widget.extra_attrs == {}  # the two edits merged into one step
    stack.redo()
    assert stack.execute(SetExtraAttr(widget, BOOTSTYLE, None))
    assert widget.extra_attrs == {}
    stack.undo()
    assert widget.extra_attrs == {BOOTSTYLE: "danger"}


def test_set_extra_attr_is_guarded_by_r83() -> None:
    stack, widget = _stack()
    outcome = stack.execute(SetExtraAttr(widget, BOOTSTYLE, "primary;x"))
    assert not outcome
    assert [f.code for f in outcome.findings] == ["validate.bad_bootstyle"]
    assert widget.extra_attrs == {}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("bootstyle", "x"),
        (f"{{{NS_UI}}}id", "x"),
        ("{urn:x}not a name", "x"),
        ("{}x", "x"),
        (BOOTSTYLE, 3),
    ],
)
def test_set_extra_attr_type_errors(key: str, value: Any) -> None:
    with pytest.raises(TypeError):
        SetExtraAttr(_widget("Button"), key, value)
    with pytest.raises(TypeError):
        SetExtraAttr(Prop(name="x"), BOOTSTYLE, "x")


def test_set_extra_attr_blocked_on_read_only_documents() -> None:
    widget = _widget("Button")
    document = _doc(widget)
    document.schema_version = "1.1"  # a newer MINOR opens read-only
    stack = CommandStack(document, Registry(entry_points=_source()))
    outcome = stack.execute(SetExtraAttr(widget, BOOTSTYLE, "primary"))
    assert not outcome and outcome.findings[0].code == "command.read_only"
