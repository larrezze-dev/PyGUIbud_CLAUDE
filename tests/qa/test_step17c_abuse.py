"""QA abuse tests of Step 17c (Help > Plugins, the disabled list, safe mode, the sample plugin):
the pure parts, without a Tk root (the designer-driving cases are in
``tests/designer/test_qa17c_abuse.py``, see the 16c note).

Passing tests pin behaviour QA checked and found correct. Strict ``xfail`` marks the findings
QA-17c-NN that are still open; the debugger removes the mark with the fix.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.cli import main
from pyguibud.core import registry as registry_module
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec, canonical_distribution
from pyguibud.core.registry import WIDGETS_GROUP, Registry, configure_default_registry
from pyguibud.core.widgets import core_widgets, tb_widgets
from pyguibud.designer.dialogs import plugins as dialog_module
from pyguibud.designer.present.plugins import (
    M_PROBLEMS,
    M_SAFE_MODE,
    plugin_note,
    plugin_rows,
    toggled,
)
from pyguibud.designer.preview import PreparedPreview, child_argv
from pyguibud.designer.settings import (
    MAX_DISABLED_PLUGINS,
    Settings,
    load_settings,
    parse_disabled_plugins,
    parse_settings,
    save_settings,
)
from pyguibud.i18n import LANGUAGES, PSEUDO_LANGUAGE, _, ngettext, plural_of, set_language
from pyguibud.preview import _configure_plugins, _parser

LOCALES = (*LANGUAGES, PSEUDO_LANGUAGE)


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


def _spec(name: str, **kw: Any) -> WidgetSpec:
    return WidgetSpec(name=name, display_name=name.split(":")[-1], category="Zz",
                      api_version=WIDGET_API_VERSION, fallback="Label", **kw)  # fmt: skip


def _source(*plugins: _EP) -> Any:
    eps = [
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud"), tb_widgets),
        *plugins,
    ]

    def source(group: str) -> Iterable[Any]:
        return [ep for ep in eps if ep.group == group]

    return source


def _registry(*plugins: _EP, disabled: Any = ()) -> Registry:
    return Registry(entry_points=_source(*plugins), disabled=disabled)


@pytest.fixture(autouse=True)
def _english() -> Any:
    set_language("en_GB")
    yield
    set_language("en_GB")
    registry_module.reset_default_registry()


# ------------------------------------------------------------------ corrupt settings.json
JUNK: list[Any] = [
    "all",
    "acme-pyguibud",
    {"acme-pyguibud": True},
    42,
    None,
    True,
    [1, 2.5, None, ["nested"], {"a": 1}],
    ["‮acme", "ac​me", "ac\x00me", "a\ncme", "  acme  ", "ácme"],
    ["x" * 101, "-acme", "acme-", ".acme", ""],
    [f"plugin-{i}" for i in range(10_000)],
    ["*"],
    ["ALL"],
]


@pytest.mark.parametrize("stored", JUNK, ids=lambda v: type(v).__name__ + str(len(str(v)))[:4])
def test_corrupt_disabled_plugins_never_mean_safe_mode_nor_crash(stored: Any) -> None:
    """Whatever the file holds: a tuple of valid names, <= 200, never the "all" filter."""
    settings = parse_settings(json.dumps({"disabled_plugins": stored}).encode())
    assert settings is not None
    names = settings.disabled_plugins
    assert isinstance(names, tuple) and len(names) <= MAX_DISABLED_PLUGINS
    assert all(isinstance(n, str) and n == canonical_distribution(n) for n in names)
    # The built-ins load whatever the list says.
    reg = _registry(disabled=names)
    assert reg.get("Button") is not None and reg.get("tb:Meter") is not None
    assert plugin_note(reg, safe_mode=False) is None


def test_a_settings_file_with_disabled_plugins_all_string_is_not_safe_mode(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"disabled_plugins": "all", "language": "de_DE"}), "utf-8")
    settings, problem = load_settings(path)
    assert problem is None and settings.disabled_plugins == () and settings.language == "de_DE"


def test_a_list_item_called_all_is_one_name_everywhere(tmp_path: Path) -> None:
    """``["all"]`` names a distribution called "all": no safe mode in the designer or child."""
    names = parse_disabled_plugins(["all"])
    assert names == ("all",)
    ok = _EP("ok", "zz_ok:x", _Dist("zz-ok"), [_spec("zz:Ok")])
    reg = _registry(ok, disabled=names)
    assert reg.get("zz:Ok") is not None and ok.loads == 1
    assert plugin_note(reg, safe_mode=names == "all") is None  # type: ignore[comparison-overlap]
    prepared = PreparedPreview(tmp_path / "x.ui", None, None, "main", None, ())
    argv = child_argv(prepared, tmp_path, ui_lang="en_GB", lang=None, theme=None, plugins=names)
    assert "--no-plugins" not in argv and argv[argv.index("--disable-plugins") + 1] == "all"
    args = _parser().parse_args(argv[argv.index("--ui-lang") :])
    _configure_plugins(args)
    child = registry_module.default_registry()
    assert child._disabled_filter == frozenset({"all"})  # not safe mode


def test_disabling_the_built_in_pyguibud_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    for spelling in ("pyguibud", "PyGUIbud", "py_gui_bud", "PYGUIBUD"):
        names = parse_disabled_plugins([spelling])
        reg = Registry(disabled=names)  # the real installed metadata
        assert reg.get("Button") is not None and reg.get("tb:ToggleButton") is not None
        assert not reg.disabled_distributions()
        assert not [d for d in reg.diagnostics() if d.code == "registry.disabled"]
        builtin = plugin_rows(reg)[0]
        assert builtin.key == "pyguibud" and builtin.status == "builtin"
        assert not builtin.can_toggle


def test_odd_distribution_spellings_disable_the_same_plugin() -> None:
    for real, stored in (("Acme_PyGUIbud", "acme.pyguibud"), ("ACME--x", "acme_x"), ("a.b", "A-B")):
        ep = _EP("acme", "acme:x", _Dist(real), [_spec("acme:Swatch")])
        reg = _registry(ep, disabled=parse_disabled_plugins([stored]))
        assert reg.get("acme:Swatch") is None and ep.loads == 0
        row = next(r for r in plugin_rows(reg) if r.key != "pyguibud")
        assert row.status == "disabled" and row.distribution == real


def test_the_default_registry_of_a_disabled_start_never_imports_the_plugin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``run()``'s order: load_settings, then configure_default_registry, then anything else."""
    ep = _EP("acme", "acme_pyguibud:widgets", _Dist("acme_pyguibud"), RuntimeError("imported!"))
    real = registry_module._metadata_entry_points

    def source(group: str) -> Iterable[Any]:
        found = list(real(group))
        return [*found, ep] if group == WIDGETS_GROUP else found

    monkeypatch.setattr(registry_module, "_metadata_entry_points", source)
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"disabled_plugins": ["ACME-PyGUIbud"]}), "utf-8")
    settings, _problem = load_settings(path)
    configure_default_registry(settings.disabled_plugins)
    reg = registry_module.default_registry()
    assert reg.get("Button") is not None and ep.loads == 0
    assert plugin_note(reg, safe_mode=False) is None  # disabled is a warning, not a problem
    assert [r.status for r in plugin_rows(reg) if r.key == "acme-pyguibud"] == ["disabled"]
    configure_default_registry("all")
    reg = registry_module.default_registry()
    assert reg.get("Button") is not None and ep.loads == 0


# ------------------------------------------------------------------ presenter
def test_toggle_storm_ends_where_it_started() -> None:
    names: tuple[str, ...] = ("a", "b")
    for _round in range(1001):
        names = toggled(names, "acme")
    assert names == ("a", "b", "acme")
    for _round in range(1001):
        names = toggled(names, "acme")
    assert names == ("a", "b")


def test_hostile_texts_in_the_registry_never_break_the_rows() -> None:
    message = "\ud800 lone \x00 nul ‮ bidi {0.__class__} %s " + "y" * 300_000
    bad = _EP("s", "s:x", _Dist("s‮ur{x}"), RuntimeError(message))
    reg = _registry(bad)
    row = next(r for r in plugin_rows(reg) if r.key != "pyguibud")
    assert row.status == "failed" and "{0.__class__}" in row.details()
    assert plugin_note(reg, safe_mode=False) == "1 plugin problem — see Help ▸ Plugins."


@pytest.mark.parametrize(
    ("declared", "real"),
    [("acme", "acme-pyguibud"), ("acme-pyguibud", "acme-fork"), ("pyguibud", "evil-dist")],
    ids=["typo", "fork", "posing-as-built-in"],
)
def test_qa17c_01_a_mismatched_spec_plugin_still_lands_on_its_distribution_row(
    declared: str, real: str, tmp_path: Path
) -> None:
    from pyguibud.designer.editing import new_node

    ep = _EP("y", "typo:x", _Dist(real), [_spec("ty:Thing", plugin=declared)])
    registry = _registry(ep)
    spec = registry.get("ty:Thing")
    assert spec is not None and spec.plugin == real
    rows = {r.key: r for r in plugin_rows(registry)}
    assert list(rows) == ["pyguibud", real]  # one row per real distribution
    assert rows[real].classes == ("ty:Thing",) and rows[real].can_toggle
    assert "ty:Thing" not in rows["pyguibud"].classes
    warned = [d for d in registry.diagnostics() if d.code == "registry.plugin_name_mismatch"]
    assert [(d.severity, d.params["declared"], d.distribution) for d in warned] == [
        ("warning", declared, real)
    ]
    assert f"'{declared}'" in warned[0].message
    assert getattr(new_node(spec, None), "plugin", None) == real  # what a document records
    # Disable writes the real name, and the plugin stays out after a restart.
    path = tmp_path / "settings.json"
    assert save_settings(Settings(disabled_plugins=toggled((), rows[real].key)), path=path)
    stored = load_settings(path)[0].disabled_plugins
    assert stored == (real,)
    assert _registry(ep, disabled=stored).get("ty:Thing") is None


def test_qa17c_01_the_same_name_spelt_differently_is_no_mismatch() -> None:
    ep = _EP("y", "y:x", _Dist("Acme_PyGUIbud"), [_spec("ty:Thing", plugin="acme-pyguibud")])
    registry = _registry(ep)
    spec = registry.get("ty:Thing")
    assert spec is not None and spec.plugin == "Acme_PyGUIbud"  # the distribution's spelling
    assert not [d for d in registry.diagnostics() if d.code == "registry.plugin_name_mismatch"]


@pytest.mark.parametrize("name", ["acme plugin", "ácme", "x" * 120, "-acme", "Acme_Plugin"])
def test_qa17c_02_a_toggleable_name_survives_the_settings_round_trip(
    name: str, tmp_path: Path
) -> None:
    ep = _EP("z", "z:x", _Dist(name), [_spec("zq:A")])
    row = next(r for r in plugin_rows(_registry(ep)) if r.key != "pyguibud")
    path = tmp_path / "settings.json"
    assert save_settings(Settings(disabled_plugins=toggled((), row.key)), path=path)
    survives = load_settings(path)[0].disabled_plugins == (row.key,)
    assert row.can_toggle == survives == (name == "Acme_Plugin")  # never offered when dropped


def test_qa17c_03_the_newest_disabled_plugin_survives_the_cap(tmp_path: Path) -> None:
    stored = tuple(f"old-{i}" for i in range(MAX_DISABLED_PLUGINS))
    path = tmp_path / "settings.json"
    assert save_settings(Settings(disabled_plugins=toggled(stored, "acme-pyguibud")), path=path)
    loaded = load_settings(path)[0].disabled_plugins
    assert len(loaded) == MAX_DISABLED_PLUGINS and loaded[-1] == "acme-pyguibud"
    assert "old-0" not in loaded  # the oldest is the one cut


def test_qa17c_04_a_second_instance_keeps_the_disabled_plugin(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert save_settings(Settings(), path=path)
    first, second = load_settings(path)[0], load_settings(path)[0]
    first.disabled_plugins = toggled(first.disabled_plugins, "acme-pyguibud")
    assert save_settings(first, path=path)
    second.theme = "dark"  # the other window changes something unrelated, then quits
    assert save_settings(second, path=path)
    assert load_settings(path)[0].disabled_plugins == ("acme-pyguibud",)


# ------------------------------------------------------------------ i18n
@pytest.mark.parametrize("lang", LOCALES)  # QA-17c-05: pt_PT/pt_BR shared Alt+C
def test_the_dialog_access_keys_are_unique_in_every_locale(lang: str) -> None:
    set_language(lang)
    for toggle in (dialog_module._M_DISABLE, dialog_module._M_ENABLE):
        keys = []
        for msgid in (dialog_module._M_COPY, toggle, dialog_module._M_CLOSE):
            text, index = split_mnemonic(_(msgid))
            assert index >= 0, (lang, msgid)
            keys.append(text[index].lower())
        assert len(set(keys)) == 3, (lang, keys)


@pytest.mark.parametrize("lang", LOCALES)
def test_the_new_placeholders_survive_in_every_locale(lang: str) -> None:
    from pyguibud.designer.canvas import engine
    from pyguibud.designer.present import plugins as present

    set_language(lang)
    for count in (0, 1, 2, 5, 21, 101):
        text = ngettext(M_PROBLEMS, plural_of(M_PROBLEMS) or M_PROBLEMS, count)
        assert str(count) in text.format(count=count), (lang, count)
    assert _(present._M_DISABLE_NEXT).format(status="S").count("S") >= 1
    assert "{status}" in _(present._M_ENABLE_NEXT)
    assert "{name}" in _(engine._M_PLUGIN_FAILED)
    assert _(M_SAFE_MODE).strip()


@pytest.mark.parametrize("lang", LOCALES)
def test_no_plugins_with_a_file_and_any_language_reaches_the_launcher(
    lang: str, tmp_path: Path
) -> None:
    seen: list[tuple[Any, ...]] = []

    def launch(language: Any, theme: Any, **keywords: Any) -> int:
        seen.append((language, theme, keywords))
        return 0

    target = tmp_path / "ünï cødé ✓.ui"
    target.write_text("<x/>", "utf-8")
    assert main(["--no-plugins", "--lang", lang, str(target)], launch=launch) == 0
    language, _theme, keywords = seen[0]
    assert language == lang and keywords["no_plugins"] is True
    assert Path(keywords["path"]).name == target.name
    seen.clear()
    assert main([str(target), "--no-plugins"], launch=launch) == 0
    assert seen[0][2]["no_plugins"] is True


def test_the_preview_child_refuses_nothing_odd_in_its_hidden_flags() -> None:
    """Hand-made hidden flags: empty names, spaces and both flags at once never crash."""
    for argv in (
        ["--disable-plugins", "", "x.ui"],
        ["--disable-plugins", " , ,acme , ", "x.ui"],
        ["--no-plugins", "--disable-plugins", "acme", "x.ui"],
    ):
        args = _parser().parse_args(argv)
        _configure_plugins(args)
        reg = registry_module.default_registry()
        assert reg.get("Button") is not None
        registry_module.reset_default_registry()
    assert sys.executable  # the child is this interpreter
