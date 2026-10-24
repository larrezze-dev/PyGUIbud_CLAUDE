"""Tests for ``pyguibud.core.registry`` using injected fake entry points."""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import (
    BACKENDS_GROUP,
    CORE_CLASS_NAMES,
    WIDGET_API_VERSION,
    WIDGETS_GROUP,
    Diagnostic,
    EntryPointSource,
    Registry,
    RegistryError,
    WidgetSpec,
    default_registry,
    reset_default_registry,
)
from pyguibud.core.widgets import core_widgets, tb_widgets

#: Every built-in class: the core vocabulary and the ttkbootstrap extensions (Step 17a).
BUILTIN_NAMES = CORE_CLASS_NAMES | {s.name for s in tb_widgets()}


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
    loads: int = 0

    def load(self) -> object:
        self.loads += 1
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


def _source(*eps: _EP) -> EntryPointSource:
    return lambda group: [ep for ep in eps if ep.group == group]


def _wep(name: str, obj: object, dist: str | None = "acme", value: str = "acme.mod:x") -> _EP:
    return _EP(name, value, WIDGETS_GROUP, _Dist(dist) if dist else None, obj)


def _bep(name: str, obj: object, dist: str | None = "acme") -> _EP:
    return _EP(name, f"{dist}.be:{name}", BACKENDS_GROUP, _Dist(dist) if dist else None, obj)


def _spec(
    name: str = "acme:Box",
    *,
    fallback: str | None = "Frame",
    children: Any = "layout",
    api_version: int = WIDGET_API_VERSION,
    **kw: Any,
) -> WidgetSpec:
    return WidgetSpec(
        name=name,
        display_name=name.split(":")[-1],
        category="Test",
        api_version=api_version,
        children=children,
        fallback=fallback,
        **kw,
    )


def _tb_ep() -> _EP:
    return _wep("tb", tb_widgets, "pyguibud-runtime", "pyguibud.core.widgets:tb_widgets")


def _codes(reg: Registry) -> list[str]:
    return [d.code for d in reg.diagnostics()]


def _only(reg: Registry, code: str) -> Diagnostic:
    found = [d for d in reg.diagnostics() if d.code == code]
    assert len(found) == 1, _codes(reg)
    return found[0]


# ------------------------------------------------------------------ loading
def test_constructor_does_no_io() -> None:
    calls: list[str] = []

    def source(group: str) -> Iterable[_EP]:
        calls.append(group)
        return []

    reg = Registry(entry_points=source)
    assert calls == []
    reg.specs()
    assert sorted(calls) == [BACKENDS_GROUP, WIDGETS_GROUP]
    reg.specs()
    reg.get("Frame")
    assert len(calls) == 2  # loaded exactly once


def test_empty_source_falls_back_to_core_with_warning() -> None:
    reg = Registry(entry_points=_source())
    assert {s.name for s in reg.specs()} == BUILTIN_NAMES
    diag = _only(reg, "registry.core_fallback")
    assert diag.severity == "warning"
    assert diag.entry_point == ""
    assert diag.distribution == "pyguibud-runtime"
    assert "Frame" in diag.message and "Statusbar" in diag.message
    assert "tb:Meter" in diag.message


def test_builtin_entry_point_no_diagnostics() -> None:
    builtin = _wep("core", core_widgets, "pyguibud-runtime", "pyguibud.core.widgets:core_widgets")
    reg = Registry(entry_points=_source(builtin, _tb_ep()))
    assert reg.diagnostics() == ()
    assert len(reg.specs()) == 29
    assert all(spec.plugin is None for spec in reg.specs())


def test_valid_plugin_spec_registered_with_distribution_as_plugin() -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec())))
    spec = reg.require("acme:Box")
    assert spec.plugin == "acme"
    assert reg.get("acme:Box") is spec
    assert spec in reg.specs()
    assert reg.is_container("acme:Box")
    assert not reg.is_container("Button")


def test_explicit_plugin_name_replaced_by_the_distribution() -> None:
    # QA-17c-01: the real distribution wins, so Help > Plugins groups and disables it.
    reg = Registry(entry_points=_source(_wep("box", _spec(plugin="custom"))))
    assert reg.require("acme:Box").plugin == "acme"
    assert "registry.plugin_name_mismatch" in [d.code for d in reg.diagnostics()]


def test_unknown_distribution_gets_plugin_name_unknown() -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec(), dist=None)))
    assert reg.require("acme:Box").plugin == "unknown"


@pytest.mark.parametrize(
    "provider",
    [
        lambda: _spec(),
        lambda: [_spec()],
        lambda: (s for s in [_spec()]),
        lambda: lambda: _spec(),
        lambda: lambda: [_spec()],
    ],
    ids=["spec", "list", "generator", "callable-spec", "callable-list"],
)
def test_entry_point_return_shapes(provider: Callable[[], object]) -> None:
    obj = provider()
    reg = Registry(entry_points=_source(_wep("box", obj)))
    assert reg.get("acme:Box") is not None
    assert "registry.bad_entry_point" not in _codes(reg)


def test_callable_returning_callable_is_bad_entry_point() -> None:
    reg = Registry(entry_points=_source(_wep("box", lambda: lambda: _spec())))
    assert "registry.bad_entry_point" in _codes(reg)
    assert reg.get("acme:Box") is None


@pytest.mark.parametrize("obj", [42, "text", None, object()])
def test_bad_entry_point_object(obj: object) -> None:
    reg = Registry(entry_points=_source(_wep("box", obj)))
    diag = _only(reg, "registry.bad_entry_point")
    assert diag.entry_point == "box"
    assert diag.distribution == "acme"
    assert diag.severity == "error"
    assert "box" in diag.message


def test_non_spec_items_diagnosed_but_others_kept() -> None:
    reg = Registry(entry_points=_source(_wep("box", [_spec(), 42, "x"])))
    assert reg.get("acme:Box") is not None
    assert _codes(reg).count("registry.bad_spec") == 2
    assert "42" in next(d for d in reg.diagnostics() if d.code == "registry.bad_spec").message


def test_loader_exception_becomes_diagnostic() -> None:
    reg = Registry(entry_points=_source(_wep("broken", RuntimeError("boom"))))
    diag = _only(reg, "registry.load_failed")
    assert diag.entry_point == "broken"
    assert diag.distribution == "acme"
    assert diag.group == WIDGETS_GROUP
    assert diag.severity == "error"
    assert diag.exception is not None and "boom" in diag.exception
    assert diag.traceback is not None and "RuntimeError" in diag.traceback
    assert "boom" in diag.message
    assert {s.name for s in reg.specs()} == BUILTIN_NAMES  # designer still works


def test_callable_raising_is_isolated() -> None:
    def explode() -> None:
        raise ValueError("kaput")

    reg = Registry(entry_points=_source(_wep("bad", explode), _wep("ok", _spec())))
    assert _only(reg, "registry.load_failed").entry_point == "bad"
    assert reg.get("acme:Box") is not None


def test_partial_iteration_failure_discards_whole_entry_point() -> None:
    def gen() -> Iterable[WidgetSpec]:
        yield _spec("acme:A")
        raise RuntimeError("mid-iteration")

    reg = Registry(entry_points=_source(_wep("partial", gen)))
    assert reg.get("acme:A") is None
    assert _only(reg, "registry.load_failed").entry_point == "partial"


def test_source_raising_gives_load_failed_with_empty_entry_point() -> None:
    def source(group: str) -> Iterable[_EP]:
        raise OSError("metadata gone")

    reg = Registry(entry_points=source)
    failed = [d for d in reg.diagnostics() if d.code == "registry.load_failed"]
    assert {d.group for d in failed} == {WIDGETS_GROUP, BACKENDS_GROUP}
    assert all(d.entry_point == "" for d in failed)
    assert all("metadata gone" in d.message for d in failed)
    assert {s.name for s in reg.specs()} == BUILTIN_NAMES
    assert reg.backends() == ()


def test_incompatible_api_listed_not_registered() -> None:
    spec = _spec(api_version=WIDGET_API_VERSION + 1)
    reg = Registry(entry_points=_source(_wep("box", spec)))
    diag = _only(reg, "registry.incompatible_api")
    assert diag.severity == "warning"
    assert reg.get("acme:Box") is None
    assert str(WIDGET_API_VERSION + 1) in diag.message
    assert diag.params["required"] == str(WIDGET_API_VERSION)


def test_incompatible_api_on_older_version_too() -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec(api_version=0))))
    assert "registry.incompatible_api" in _codes(reg)


def test_invalid_class_name_rejected() -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec("acme:bad name"))))
    assert "registry.bad_name" in _codes(reg)
    assert reg.get("acme:bad name") is None


def test_unprefixed_plugin_name_is_reserved() -> None:
    for name in ("Button", "Gadget"):
        reg = Registry(entry_points=_source(_wep("x", _spec(name, fallback=None))))
        diag = _only(reg, "registry.reserved_name")
        assert diag.params["name"] == name
        assert reg.get("Gadget") is None


@pytest.mark.parametrize("display_name", ["", "   ", "\t\n"])
def test_empty_display_name_is_rejected_and_siblings_survive(display_name: str) -> None:
    nameless = dataclasses.replace(_spec("acme:Nameless"), display_name=display_name)
    sibling = _spec("acme:Sibling")
    reg = Registry(entry_points=_source(_wep("pair", [nameless, sibling])))
    diag = _only(reg, "registry.bad_display_name")
    assert diag.severity == "error" and diag.params["name"] == "acme:Nameless"
    assert diag.message == (
        "The widget 'acme:Nameless' from 'acme' has no display name and was ignored."
    )
    assert reg.get("acme:Nameless") is None and reg.get("acme:Sibling") is not None


def test_non_string_display_name_is_rejected() -> None:
    odd = dataclasses.replace(_spec("acme:Odd"), display_name=None)  # type: ignore[arg-type]
    reg = Registry(entry_points=_source(_wep("x", odd)))
    assert "registry.bad_display_name" in _codes(reg) and reg.get("acme:Odd") is None


def test_builtin_specs_all_have_display_names() -> None:
    assert not default_registry().diagnostics()


def test_core_cannot_be_overridden_by_plugin() -> None:
    fake = _spec("Button", fallback=None, children="layout")
    builtin = _wep("core", core_widgets, "pyguibud-runtime", "pyguibud.core.widgets:core_widgets")
    reg = Registry(entry_points=_source(builtin, _wep("evil", fake, "evil")))
    assert reg.require("Button").children == "none"
    assert "registry.reserved_name" in _codes(reg)


def test_duplicate_names_first_wins() -> None:
    first = _spec("acme:Box")
    second = _spec("acme:Box", children="layout", icon="second")
    reg = Registry(
        entry_points=_source(_wep("a", first, "aaa"), _wep("b", second, "bbb")),
    )
    assert reg.require("acme:Box").plugin == "aaa"
    diag = _only(reg, "registry.duplicate")
    assert diag.severity == "warning"
    assert diag.distribution == "bbb"
    assert diag.params["first"] == "aaa"


def test_duplicate_inside_one_entry_point() -> None:
    reg = Registry(entry_points=_source(_wep("a", [_spec(), _spec()])))
    assert _codes(reg).count("registry.duplicate") == 1
    assert [s.name for s in reg.specs()].count("acme:Box") == 1


def test_load_order_builtin_first_then_distribution_then_name() -> None:
    builtin = _wep("core", core_widgets, "pyguibud-runtime", "pyguibud.core.widgets:core_widgets")
    eps = [
        _wep("z", _spec("z:One"), "zeta"),
        _wep("b", _spec("b:Two"), "alpha"),
        _wep("a", _spec("a:Three"), "alpha"),
        _tb_ep(),
        builtin,
    ]
    names = [s.name for s in Registry(entry_points=_source(*eps)).specs()]
    assert names[:29] == [s.name for s in (*core_widgets(), *tb_widgets())]
    assert names[29:] == ["a:Three", "b:Two", "z:One"]


def test_core_safety_net_runs_before_extension_check() -> None:
    """Without the built-in entry point, extensions can still use core fallbacks."""
    reg = Registry(entry_points=_source(_wep("box", _spec())))
    assert reg.get("acme:Box") is not None
    assert "registry.core_fallback" in _codes(reg)
    assert "registry.bad_fallback" not in _codes(reg)


def test_core_safety_net_failure_is_diagnosed(monkeypatch: pytest.MonkeyPatch) -> None:
    import pyguibud.core.widgets as widgets_module

    def boom() -> tuple[WidgetSpec, ...]:
        raise RuntimeError("no widgets")

    monkeypatch.setattr(widgets_module, "core_widgets", boom)
    reg = Registry(entry_points=_source())
    diag = _only(reg, "registry.load_failed")
    assert diag.distribution == "pyguibud-runtime"
    assert "no widgets" in diag.message
    assert reg.specs() == ()


def test_core_safety_net_only_fills_missing() -> None:
    partial = [s for s in core_widgets() if s.name != "Statusbar"]
    reg = Registry(
        entry_points=_source(
            _wep("core", partial, "pyguibud-runtime", "pyguibud.core.widgets:x"), _tb_ep()
        )
    )
    diag = _only(reg, "registry.core_fallback")
    assert diag.params["names"] == "Statusbar"
    assert len(reg.specs()) == 29


# ------------------------------------------------------------------ fallbacks
@pytest.mark.parametrize("fallback", [None, "", "Nope", "acme:Other", "tb:Meter"])
def test_bad_fallback_removes_extension(fallback: str | None) -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec(fallback=fallback))))
    diag = _only(reg, "registry.bad_fallback")
    assert diag.severity == "error"
    assert diag.params["name"] == "acme:Box"
    assert reg.get("acme:Box") is None


def test_fallback_container_mismatch_removes_extension() -> None:
    reg = Registry(entry_points=_source(_wep("box", _spec(fallback="Button", children="layout"))))
    assert "registry.fallback_mismatch" in _codes(reg)
    assert reg.get("acme:Box") is None
    reg2 = Registry(entry_points=_source(_wep("box", _spec(fallback="Frame", children="none"))))
    assert "registry.fallback_mismatch" in _codes(reg2)


def test_pages_container_matches_layout_fallback_flag() -> None:
    """Both layout and pages are containers, so Notebook fallback is accepted for a layout."""
    reg = Registry(entry_points=_source(_wep("box", _spec(fallback="Notebook", children="pages"))))
    assert reg.get("acme:Box") is not None


# ------------------------------------------------------------------ lookups and resolve
def test_require_and_is_container_unknown() -> None:
    reg = Registry(entry_points=_source())
    for call in (reg.require, reg.is_container):
        with pytest.raises(RegistryError) as info:
            call("Nope")
        assert info.value.code == "registry.unknown_class"
        assert info.value.params["name"] == "Nope"
        assert "Nope" in str(info.value)
    assert reg.get("Nope") is None


def test_resolve_core_widget() -> None:
    reg = Registry(entry_points=_source())
    res = reg.resolve("Button", "ttkbootstrap")
    assert res.spec.name == "Button"
    assert res.requested == "Button"
    assert not res.is_fallback
    assert res.code is None


def test_resolve_extension_with_backend_factory() -> None:
    spec = _spec(factories={"ttkbootstrap": lambda: 1})
    reg = Registry(entry_points=_source(_wep("box", spec)))
    res = reg.resolve("acme:Box", "ttkbootstrap")
    assert res.spec.name == "acme:Box"
    assert not res.is_fallback


def test_resolve_extension_without_backend_factory_uses_fallback() -> None:
    spec = _spec(factories={"pyside6": lambda: 1})
    reg = Registry(entry_points=_source(_wep("box", spec)))
    res = reg.resolve("acme:Box", "ttkbootstrap")
    assert res.is_fallback
    assert res.spec.name == "Frame"
    assert res.requested == "acme:Box"
    assert res.code == "registry.no_factory"


def test_resolve_missing_plugin_with_core_fallback() -> None:
    reg = Registry(entry_points=_source())
    res = reg.resolve("zz:Gone", "ttkbootstrap", fallback="Label")
    assert res.is_fallback
    assert res.spec.name == "Label"
    assert res.requested == "zz:Gone"
    assert res.code == "registry.plugin_missing"


@pytest.mark.parametrize(
    ("cls", "fallback"),
    [
        ("zz:Gone", None),
        ("zz:Gone", "NotCore"),
        ("zz:Gone", "zz:Other"),
        ("Gone", "Label"),  # a core-style unknown name never falls back
        ("Gone", None),
    ],
)
def test_resolve_unknown_raises(cls: str, fallback: str | None) -> None:
    reg = Registry(entry_points=_source())
    with pytest.raises(RegistryError) as info:
        reg.resolve(cls, "ttkbootstrap", fallback)
    assert info.value.code == "registry.unknown_class"


def test_resolve_fallback_core_missing_raises() -> None:
    reg = Registry(entry_points=_source())
    reg.load()
    reg._specs.pop("Label")  # simulate a core class absent from the registry
    with pytest.raises(RegistryError):
        reg.resolve("zz:Gone", "ttkbootstrap", fallback="Label")


# ------------------------------------------------------------------ backends
def test_backends_listed_not_loaded_until_requested() -> None:
    qt = _bep("qt", object())
    tk = _bep("tk", object(), "zed")
    reg = Registry(entry_points=_source(tk, qt))
    infos = reg.backends()
    assert [b.name for b in infos] == ["qt", "tk"]  # sorted by distribution then name
    assert infos[0].distribution == "acme"
    assert infos[0].value == "acme.be:qt"
    assert qt.loads == 0 and tk.loads == 0


def test_load_backend_loads_once_and_caches() -> None:
    sentinel = object()
    qt = _bep("qt", sentinel)
    reg = Registry(entry_points=_source(qt))
    assert reg.load_backend("qt") is sentinel
    assert reg.load_backend("qt") is sentinel
    assert qt.loads == 1


def test_load_backend_unknown() -> None:
    reg = Registry(entry_points=_source())
    with pytest.raises(RegistryError) as info:
        reg.load_backend("nope")
    assert info.value.code == "registry.unknown_backend"
    assert "nope" in info.value.message


def test_load_backend_failure_raises_and_diagnoses() -> None:
    reg = Registry(entry_points=_source(_bep("qt", ImportError("no PySide6"))))
    with pytest.raises(RegistryError) as info:
        reg.load_backend("qt")
    assert info.value.code == "registry.backend_failed"
    assert isinstance(info.value.__cause__, ImportError)
    assert "no PySide6" in info.value.message
    diag = _only(reg, "registry.backend_failed")
    assert diag.entry_point == "qt"
    assert diag.group == BACKENDS_GROUP
    assert diag.traceback is not None
    # a failed load is not cached: a second attempt fails the same way
    with pytest.raises(RegistryError):
        reg.load_backend("qt")


def test_duplicate_backend_names_first_wins_with_warning() -> None:
    first = _bep("qt", "first", "aaa")
    second = _bep("qt", "second", "bbb")
    reg = Registry(entry_points=_source(second, first))
    assert [b.distribution for b in reg.backends()] == ["aaa"]
    diag = _only(reg, "registry.duplicate")
    assert diag.severity == "warning"
    assert diag.group == BACKENDS_GROUP
    assert reg.load_backend("qt") == "first"


def test_load_resets_state() -> None:
    sentinel = object()
    qt = _bep("qt", sentinel)
    reg = Registry(entry_points=_source(qt))
    reg.load_backend("qt")
    n = len(reg.diagnostics())
    reg.load()
    reg.load()
    assert len(reg.diagnostics()) == n  # not accumulating
    reg.load_backend("qt")
    assert qt.loads == 2  # cache cleared by load()


# ------------------------------------------------------------------ diagnostics
def test_diagnostic_message_is_lazy_and_translated() -> None:
    reg = Registry(entry_points=_source(_wep("broken", RuntimeError("boom"))))
    diag = _only(reg, "registry.load_failed")
    plain = diag.message
    assert "'broken'" in plain and "'acme'" in plain
    i18n.set_language("en_XA")
    assert diag.message != plain
    assert diag.message.startswith("[")
    assert "boom" in diag.message


def test_diagnostic_params_readonly_and_message_never_raises() -> None:
    diag = Diagnostic(
        group="g",
        entry_point="e",
        distribution="d",
        code="c",
        msgid="needs {missing}",
        params={"a": "1"},
    )
    with pytest.raises(TypeError):
        diag.params["b"] = "2"  # type: ignore[index]
    assert diag.message == "needs {missing}"
    with pytest.raises(AttributeError):
        diag.code = "x"  # type: ignore[misc]


def test_diagnostics_tuple_in_occurrence_order() -> None:
    reg = Registry(
        entry_points=_source(
            _wep("a", RuntimeError("1")),
            _wep("b", 42),
        )
    )
    codes = _codes(reg)
    assert codes.index("registry.load_failed") < codes.index("registry.bad_entry_point")
    assert isinstance(reg.diagnostics(), tuple)


# ------------------------------------------------------------------ default registry
def test_default_registry_caches_and_resets() -> None:
    first = default_registry()
    assert default_registry() is first
    reset_default_registry()
    assert default_registry() is not first


def test_real_entry_point_loads_the_builtin_specs_without_diagnostics() -> None:
    reg = default_registry()
    # An installed third-party plugin may add specs and diagnostics; the built-ins never do.
    assert not [d for d in reg.diagnostics() if d.distribution == "pyguibud-runtime"]
    specs = [s for s in reg.specs() if s.name in BUILTIN_NAMES]
    assert [s.name for s in specs] == [s.name for s in (*core_widgets(), *tb_widgets())]
    assert all(s.plugin is None for s in specs)
    assert reg.backends() == () or all(b.name for b in reg.backends())


def test_real_registry_resolves_every_core_class() -> None:
    reg = default_registry()
    for name in CORE_CLASS_NAMES:
        res = reg.resolve(name, "ttkbootstrap")
        assert res.spec.name == name and not res.is_fallback
