"""Step 17c: Help > Plugins, safe mode, the disabled list, the palette flag, the canvas failure
card and the Bootstyle row (spec plugins 8, 11). Plugins are fake entry points: an installed
acme never changes these tests."""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.cli import main
from pyguibud.core import read_ui_string
from pyguibud.core.commands import CommandStack
from pyguibud.core.model import WIDGET_API_VERSION, WidgetSpec
from pyguibud.core.registry import WIDGETS_GROUP, Registry
from pyguibud.core.widgets import core_widgets, tb_widgets
from pyguibud.designer.present.palette import palette_groups
from pyguibud.designer.present.plugins import plugin_note, plugin_rows, toggled
from pyguibud.designer.preview import PreparedPreview, child_argv
from pyguibud.designer.properties import BOOTSTYLE_KEY, commit_commands, field_rows
from pyguibud.designer.settings import Settings, load_settings, parse_settings, save_settings
from pyguibud.i18n import set_language

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)


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
        if isinstance(self.obj, BaseException):
            raise self.obj
        return self.obj


def _spec(name: str, fallback: str = "Label", **kw: Any) -> WidgetSpec:
    return WidgetSpec(name=name, display_name=name.split(":")[-1], category="Zz",
                      api_version=kw.pop("api_version", WIDGET_API_VERSION), fallback=fallback,
                      **kw)  # fmt: skip


def _raising(*_args: Any) -> Any:
    raise RuntimeError("boom")


def _registry(*plugins: _EP, disabled: Any = ()) -> Registry:
    eps = [
        _EP("core", "pyguibud.core.widgets:core_widgets", _Dist("pyguibud-runtime"), core_widgets),
        _EP("tb", "pyguibud.core.widgets:tb_widgets", _Dist("pyguibud-runtime"), tb_widgets),
        *plugins,
    ]

    def source(group: str) -> Iterable[Any]:
        return [ep for ep in eps if ep.group == group]

    return Registry(entry_points=source, disabled=disabled)


def _all_statuses() -> Registry:
    return _registry(
        _EP("ok", "zz_ok:x", _Dist("Zz_OK"), [_spec("zz:Swatch")]),
        _EP("bad", "zz_bad:x", _Dist("zz-bad"), RuntimeError("import boom")),
        _EP("off", "zz_off:x", _Dist("zz.off"), [_spec("zz:Off")]),
        _EP("old", "zz_old:x", _Dist("zz-old"), [_spec("zz:Old", api_version=99)]),
        disabled=["ZZ_Off"],
    )


# ------------------------------------------------------------------ presenter (pure)
def test_rows_cover_every_status_built_in_first() -> None:
    rows = {row.key: row for row in plugin_rows(_all_statuses())}
    assert next(iter(rows)) == "pyguibud-runtime"
    assert {k: r.status for k, r in rows.items()} == {
        "pyguibud-runtime": "builtin",
        "zz-ok": "loaded",
        "zz-bad": "failed",
        "zz-off": "disabled",
        "zz-old": "incompatible",
    }
    assert rows["zz-ok"].classes == ("zz:Swatch",) and rows["zz-ok"].distribution == "Zz_OK"
    assert (
        "tb:Meter" in rows["pyguibud-runtime"].classes and not rows["pyguibud-runtime"].can_toggle
    )
    assert rows["zz-bad"].diagnostics[0].message.startswith("The entry point 'bad' from 'zz-bad'")
    details = rows["zz-bad"].details()
    assert "Traceback" in details and "import boom" in details
    assert rows["zz-ok"].details() == "No problems were reported."
    assert all(rows[k].can_toggle for k in ("zz-ok", "zz-bad", "zz-off", "zz-old"))


def test_status_text_names_the_change_on_next_start() -> None:
    rows = {row.key: row for row in plugin_rows(_all_statuses())}
    assert rows["zz-ok"].status_text(()) == "Loaded"
    assert rows["zz-ok"].status_text(("zz-ok",)) == "Loaded (disabled on next start)"
    assert rows["zz-off"].status_text(()) == "Disabled (enabled on next start)"
    assert rows["zz-off"].status_text(("zz-off",)) == "Disabled"
    assert rows["pyguibud-runtime"].status_text(("pyguibud-runtime",)) == "Built-in"


def test_the_start_up_note_counts_errors_and_names_safe_mode() -> None:
    assert plugin_note(_registry(), safe_mode=False) is None
    assert plugin_note(_all_statuses(), safe_mode=False) == (
        "1 plugin problem — see Help ▸ Plugins."
    )
    two = _registry(_EP("a", "a:x", _Dist("a"), RuntimeError()), _EP("b", "b:x", _Dist("b"), 1))
    assert plugin_note(two, safe_mode=False) == "2 plugin problems — see Help ▸ Plugins."
    assert plugin_note(two, safe_mode=True) == "Plugins are disabled (safe mode)."


def test_toggled_adds_and_removes() -> None:
    assert toggled((), "acme") == ("acme",)
    assert toggled(("x", "acme"), "acme") == ("x",)


def test_the_palette_marks_only_real_plugins() -> None:
    reg = _registry(_EP("ok", "zz_ok:x", _Dist("zz-ok"), [_spec("zz:Swatch")]))
    items = {i.name: i for g in palette_groups(reg) for i in g.items}
    assert not items["tb:Meter"].plugin and not items["Label"].plugin
    assert items["zz:Swatch"].plugin
    groups = {g.category_label: g for g in palette_groups(reg)}
    assert "tb:Meter" in {i.name for i in groups["ttkbootstrap"].items}


# ------------------------------------------------------------------ settings and argv (pure)
@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (["Acme_Plugin", "acme-plugin", "Other"], ("acme-plugin", "other")),
        ("all", ()),  # never safe mode from a hand edit
        ({"acme": 1}, ()),
        (["ok", 3, None, "bad name!", "-x", "y" * 101], ("ok",)),
    ],
)
def test_disabled_plugins_read_tolerantly(stored: object, expected: tuple[str, ...]) -> None:
    parsed = parse_settings(json.dumps({"disabled_plugins": stored}).encode())
    assert parsed is not None and parsed.disabled_plugins == expected
    assert "disabled_plugins" not in parsed.extra


def test_disabled_plugins_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    assert save_settings(Settings(disabled_plugins=("acme-pyguibud",)), path=path)
    assert load_settings(path)[0].disabled_plugins == ("acme-pyguibud",)


def test_the_preview_child_gets_the_designer_filter(tmp_path: Path) -> None:
    prepared = PreparedPreview(tmp_path / "a.ui", None, None, "main", None, ())

    def argv(plugins: Any) -> list[str]:
        return child_argv(prepared, tmp_path, ui_lang="en_GB", lang=None, theme=None,
                          plugins=plugins)  # fmt: skip

    assert "--no-plugins" not in argv(()) and "--disable-plugins" not in argv(())
    safe = argv("all")
    assert "--no-plugins" in safe and safe.index("--no-plugins") < safe.index("--")
    some = argv(("a", "b-c"))
    assert some[some.index("--disable-plugins") + 1] == "a,b-c"


class _Launch:
    def __init__(self) -> None:
        self.keywords: list[dict[str, object]] = []

    def __call__(self, _lang: str | None, _theme: str | None, **keywords: object) -> int:
        self.keywords.append(keywords)
        return 0


def test_cli_no_plugins_reaches_the_launcher(capsys: pytest.CaptureFixture[str]) -> None:
    fake = _Launch()
    assert main(["--no-plugins"], launch=fake) == 0
    assert main([], launch=fake) == 0
    assert fake.keywords == [{"no_plugins": True}, {}]
    with pytest.raises(SystemExit):
        main(["--lang", "en_GB", "--help"], launch=fake)  # not the machine's language
    assert "safe mode" in capsys.readouterr().out


# ------------------------------------------------------------------ Bootstyle row (pure)
def _doc(body: str) -> Any:
    text = HEADER + f'<window id="w" kind="main"><layout type="grid"/>{body}</window></pyguibud-ui>'
    return read_ui_string(text).document


def test_the_bootstyle_row_sets_and_removes_the_attribute() -> None:
    reg = _registry()
    document = _doc('<widget class="Button" id="b"><cell row="0" column="0"/></widget>'
                    '<widget class="Text" id="t"><cell row="1" column="0"/></widget>')  # fmt: skip
    button, text = document.children[0].children
    assert not any(f.key == "tb:bootstyle" for f in field_rows([text], reg, document))
    field = next(f for f in field_rows([button], reg, document) if f.key == "tb:bootstyle")
    assert field.kind == "bootstyle" and "success-outline" in field.choices
    stack = CommandStack(document, reg)
    assert stack.execute(commit_commands([button], field, "success-outline")).accepted
    assert button.extra_attrs[BOOTSTYLE_KEY] == "success-outline"
    refused = stack.execute(commit_commands([button], field, "Not Valid!"))
    assert not refused.accepted and "bootstyle" in refused.message
    assert stack.execute(commit_commands([button], field, None)).accepted
    assert BOOTSTYLE_KEY not in button.extra_attrs


# ------------------------------------------------------------------ Tk
@pytest.fixture
def app(designer_root: Any) -> Iterator[Any]:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.session import DesignerSession

    designer = DesignerApp(designer_root, DesignerSession(_all_statuses()), settings=Settings())
    yield designer
    designer.dispose()


@pytest.mark.gui
class TestPluginsDialog:
    def _open(self, app: Any) -> Any:
        from pyguibud.designer.dialogs.plugins import PluginsDialog

        assert app.registry.invoke("help.plugins")
        dialog = app._live_dialogs()[-1]
        assert isinstance(dialog, PluginsDialog)
        return dialog

    def test_opens_from_help_lists_rows_and_closes_on_escape(self, app: Any) -> None:
        dialog = self._open(app)
        tree = dialog.tree
        texts = [tree.item(i, "text") for i in tree.get_children()]
        assert texts == ["pyguibud-runtime", "zz-bad", "zz.off", "Zz_OK", "zz-old"]
        assert tree.set("1", "status") == "Failed"
        assert dialog.initial_focus() is tree  # the keys reach the list at once
        assert str(dialog.details.cget("takefocus")) == "1"  # Tab reaches the details
        assert dialog.toggle_button.instate(["disabled"])  # the built-in is selected
        dialog.window.event_generate("<Escape>")
        assert dialog.closed

    def test_copies_details_and_toggles_on_next_start(
        self, app: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        copied: list[str] = []
        monkeypatch.setattr(app, "_clipboard_put", copied.append)
        dialog = self._open(app)
        dialog.tree.selection_set("1")
        dialog.root.update_idletasks()
        dialog._show()
        assert "import boom" in dialog.details.get("1.0", "end")
        assert dialog.details.cget("state") == "disabled"
        dialog._on_alt(type("E", (), {"char": "c"})())
        assert copied and copied[0].startswith("zz-bad\n\n") and "Traceback" in copied[0]
        assert dialog.toggle_button.cget("text") == "Disable on next start"
        dialog._on_alt(type("E", (), {"char": "d"})())
        assert app.settings.disabled_plugins == ("zz-bad",)
        assert dialog.tree.set("1", "status") == "Failed (disabled on next start)"
        assert dialog.toggle_button.cget("text") == "Enable on next start"
        dialog.toggle()
        assert app.settings.disabled_plugins == ()
        dialog.close()

    def test_refreshes_when_the_registry_reports_a_failure(self, app: Any) -> None:
        dialog = self._open(app)
        reg = app.session.registry
        reg.report_failure("zz:Swatch", "ttkbootstrap", "create", RuntimeError("late"))
        dialog._poll()
        index = next(
            i for i in dialog.tree.get_children() if dialog.tree.item(i, "text") == "Zz_OK"
        )
        assert dialog.tree.set(index, "status") == "Failed"
        dialog.close()

    def test_retranslates_and_fits_in_the_pseudo_locale(self, app: Any) -> None:
        dialog = self._open(app)
        set_language("en_XA")
        dialog.retranslate()
        dialog.window.update_idletasks()
        for button in (dialog.copy_button, dialog.toggle_button, dialog.close_button):
            assert button.winfo_reqwidth() <= button.winfo_width() or not button.winfo_ismapped()
        assert dialog.window.winfo_width() >= dialog.window.winfo_reqwidth()
        dialog.close()


@pytest.mark.gui
def test_safe_mode_posts_its_note(app: Any) -> None:
    shown: list[str] = []
    app.message.connect(shown.append)
    app.plugins = "all"
    app.start()
    assert "Plugins are disabled (safe mode)." in shown


@pytest.mark.gui
def test_a_plugin_problem_posts_the_count(app: Any) -> None:
    shown: list[str] = []
    app.message.connect(shown.append)
    app.start()
    assert "1 plugin problem — see Help ▸ Plugins." in shown


@pytest.mark.gui
def test_the_canvas_shows_a_card_for_a_failing_widget_and_the_fallback_for_a_container(
    designer_root: Any,
) -> None:
    from pyguibud.designer.canvas.engine import CanvasEngine

    reg = _registry(
        _EP("zz", "zz:x", _Dist("zz"), [
            _spec("zz:Gauge", factories={"ttkbootstrap": _raising}),
            _spec("zz:Box", "Frame", children="layout", factories={"ttkbootstrap": _raising}),
        ])
    )  # fmt: skip
    document = _doc(
        '<widget class="zz:Gauge" id="g" fallback="Label"><cell row="0" column="0"/></widget>'
        '<widget class="zz:Box" id="box" fallback="Frame"><layout type="grid"/>'
        '<cell row="1" column="0"/>'
        '<widget class="Label" id="inside"><cell row="0" column="0"/></widget></widget>'
    )
    window = document.children[0]
    gauge, box = window.children
    host = ttk.Frame(designer_root)
    try:
        view = CanvasEngine(reg).build(document, window, host)
        card = view.outer[id(gauge)]
        assert card.winfo_class() == "TLabelframe"
        assert card.cget("text") == "zz:Gauge — the plugin failed"
        assert view.node_of(card) is gauge  # selectable
        assert view.outer[id(box)].winfo_class() == "TFrame"  # the fallback keeps its children
        assert id(box.children[0]) in view.outer
        codes = [d.params.get("stage") for d in reg.diagnostics() if d.code.endswith("_failed")]
        assert codes.count("create") == 2
        view.session.destroy()
    finally:
        host.destroy()
