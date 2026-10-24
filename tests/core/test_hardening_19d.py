"""Step 19d (core): plugin hardening H49, H52, H66, H67 and the H69 trim (docs/specs/hardening.md).

Pure: every registry is built from injected fake entry points; nothing creates a Tk root.
"""

from __future__ import annotations

import dataclasses
import logging
import time
from typing import Any

import pytest

from pyguibud.core import BACKENDS_GROUP, NS_TB, Registry
from pyguibud.core.validate import validate
from pyguibud.designer.present.plugins import plugin_rows
from pyguibud.preview import _Collect
from tests.core.test_plugins_17a import (
    _EP,
    _codes_of,
    _Dist,
    _doc,
    _plugin,
    _source,
    _spec,
    _widget,
)

BOOTSTYLE = f"{{{NS_TB}}}bootstyle"


# ---------------------------------------------------------------- H66: the Built-in row
def _spoof(obj: object, value: str = "evil.mod:specs", dist: str = "pyguibud") -> _EP:
    return _EP("evil", value, _Dist(dist), obj)


# ADR-016: the built-in distribution is pyguibud-runtime; a stale or forked "pyguibud" is not.
@pytest.mark.parametrize("dist", ["pyguibud", "pyguibud-runtime", "PyGUIbud_Runtime"])
def test_h66_a_foreign_entry_point_of_a_pyguibud_distribution_is_not_builtin(dist: str) -> None:
    reg = Registry(entry_points=_source(_spoof([_spec("evil:Gauge")], dist=dist)))
    spec = reg.require("evil:Gauge")
    assert spec.plugin == "evil"  # named after its module, never "pyguibud"
    rows = {row.key: row for row in plugin_rows(reg)}
    assert "evil:Gauge" not in rows["pyguibud-runtime"].classes
    assert rows["evil"].status == "loaded" and rows["evil"].classes == ("evil:Gauge",)


def test_h66_a_failing_foreign_entry_point_counts_for_r87() -> None:
    reg = Registry(entry_points=_source(_spoof(RuntimeError("boom"))))
    assert reg.failed_distributions() == frozenset({"evil"})
    assert {row.key: row.status for row in plugin_rows(reg)}["evil"] == "failed"


@pytest.mark.parametrize(
    "value", ["pyguibud.extra:specs", "PyGUIbud.x:specs", "pyguibud_runtime.x:specs", "?:x", ""]
)
def test_h66_an_unnameable_foreign_entry_point_is_unknown(value: str) -> None:
    reg = Registry(entry_points=_source(_spoof(RuntimeError("boom"), value)))
    (diagnostic,) = [d for d in reg.diagnostics() if d.code == "registry.load_failed"]
    assert diagnostic.distribution == "unknown"


def test_h66_builtin_needs_the_group_prefix_and_the_built_in_backends_stay_builtin() -> None:
    backends = [
        _EP(
            "tkinter",
            "pyguibud.backends.tkinter:TkinterBackend",
            _Dist("pyguibud-runtime"),
            object(),
            group=BACKENDS_GROUP,
        ),
        _EP(
            "odd",
            "pyguibud.core.widgets:x",
            _Dist("pyguibud-runtime"),
            object(),
            group=BACKENDS_GROUP,
        ),
    ]
    widgets = _source()

    def source(group: str) -> list[Any]:
        return backends if group == BACKENDS_GROUP else list(widgets(group))

    reg = Registry(entry_points=source)
    names = {info.name: info.distribution for info in reg.backends()}
    assert names == {"tkinter": "pyguibud-runtime", "odd": "unknown"}
    assert [row.key for row in plugin_rows(reg)] == ["pyguibud-runtime"]  # the core widgets only


# ---------------------------------------------------------------- H67: a misdeclared plugin=
def _swatch(plugin: str = "acme", class_name: str = "acme:Gauge") -> Any:
    return _doc(_widget(class_name, "Label", plugin=plugin))


def _finding(reg: Registry, document: Any) -> tuple[str, dict[str, object]]:
    (finding,) = validate(document, reg).findings
    return finding.code.removeprefix("validate."), dict(finding.params)


def test_h67_r87_uses_the_real_distribution_of_a_failed_plugin() -> None:
    reg = Registry(entry_points=_source(_plugin(RuntimeError("boom"), "acme-pyguibud")))
    code, params = _finding(reg, _swatch())
    assert code == "plugin_failed" and params["plugin"] == "acme-pyguibud"
    assert reg.resolve("acme:Gauge", "tkinter", "Label", plugin="acme").code == (
        "registry.plugin_failed"
    )


def test_h67_r88_uses_the_real_distribution_of_a_disabled_plugin() -> None:
    eps = _source(_plugin([_spec()], "acme-pyguibud"))
    reg = Registry(entry_points=eps, disabled=["acme-pyguibud"])
    assert _finding(reg, _swatch())[0] == "plugin_disabled"


def test_h67_r28_hints_the_real_pip_name_from_a_named_diagnostic() -> None:
    old = dataclasses.replace(_spec(), api_version=99)  # a warning naming the class, not R87
    reg = Registry(entry_points=_source(_plugin([old], "acme-pyguibud", name="widgets")))
    code, params = _finding(reg, _swatch())
    assert code == "plugin_missing" and params["command"] == "pip install acme-pyguibud"


def test_h67_r28_hints_the_real_pip_name_from_a_registered_sibling() -> None:
    reg = Registry(entry_points=_source(_plugin([_spec("acme:Other")], "acme-pyguibud", "x")))
    code, params = _finding(reg, _swatch(class_name="acme:Gone"))
    assert code == "plugin_missing" and params["command"] == "pip install acme-pyguibud"


def test_h67_an_unknown_prefix_keeps_the_file_name_and_tb_is_never_guessed() -> None:
    tb_named = _plugin(RuntimeError("boom"), "evil-tb", name="tb")
    reg = Registry(entry_points=_source(tb_named))
    assert reg.plugin_for_prefix("tb") is None
    code, params = _finding(reg, _swatch("zz-plugin", "zz:Gauge"))
    assert code == "plugin_missing" and params["command"] == "pip install zz-plugin"


# ---------------------------------------------------------------- H69 (trimmed)
def test_h69_a_bootstyle_on_a_registered_plugin_widget_gives_no_r84() -> None:
    # H69 trim T4: plugins may honour bootstyle; documented.
    reg = Registry(entry_points=_source(_plugin([_spec()])))
    widget = _widget("acme:Gauge", "Label", extra_attrs={BOOTSTYLE: "primary"})
    assert _codes_of(validate(_doc(widget), reg)) == []


# ---------------------------------------------------------------- H49: a slow import
def test_h49_a_slow_plugin_import_is_waited_for_and_safe_mode_skips_it() -> None:
    class _Slow(_EP):
        def load(self) -> object:
            time.sleep(0.2)  # no timeout (Step 17 ruling): safe mode is the way out
            return super().load()

    slow = _Slow("acme", "acme.mod:specs", _Dist("acme"), [_spec()])
    assert Registry(entry_points=_source(slow)).get("acme:Gauge") is not None
    assert slow.loads == 1
    safe = Registry(entry_points=_source(slow), disabled="all")
    assert safe.get("acme:Gauge") is None and slow.loads == 1  # --no-plugins: never imported
    assert safe.disabled_distributions() == frozenset({"acme"})


# ---------------------------------------------------------------- H52: the preview collector
def test_h52_a_bad_record_never_breaks_the_preview_collector() -> None:
    collect = _Collect()
    errors: list[logging.LogRecord] = []
    collect.handleError = errors.append  # type: ignore[method-assign,assignment]
    bad = logging.LogRecord("pyguibud_runtime", logging.WARNING, "x", 1, "%d", ("x",), None)
    collect.emit(bad)
    good = logging.LogRecord("pyguibud_runtime", logging.WARNING, "x", 1, "ok %s", ("y",), None)
    collect.emit(good)
    assert errors == [bad] and collect.messages == ["ok y"]


def test_h67_a_plugin_refused_for_the_tb_prefix_is_never_named_for_tb_classes() -> None:
    reg = Registry(entry_points=_source(_plugin([_spec("tb:Meter")], "evil-tb", name="tb")))
    assert reg.plugin_for_prefix("tb") is None
    document = _doc(_widget("tb:Future", "Entry", plugin="pyguibud"))
    code, params = _finding(reg, document)
    assert code == "plugin_missing" and "evil" not in str(params)


def test_h66_the_relabelled_entry_point_can_be_disabled() -> None:
    spoof = _spoof([_spec("evil:Gauge")])
    reg = Registry(entry_points=_source(spoof), disabled=["evil"])
    assert reg.get("evil:Gauge") is None and spoof.loads == 0
