"""Step 17c gaps (TESTING): the real acme sample in the designer, disable/enable across a restart,
the preview child's filter round-trip, the Bootstyle row in the inspector and the en_XA fit.

Spec ``docs/specs/plugins.md`` 8, 9, 11 and 12 (17c UAT). ``acme_pyguibud`` comes from
``examples/acme_plugin/src`` through a fake entry point added to the metadata source: an
installed acme never changes these tests.
"""

from __future__ import annotations

import importlib
import json
import shutil
import sys
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.core import default_registry, dump_ui, read_ui_string, validate
from pyguibud.core import registry as registry_module
from pyguibud.core.commands import SetProp
from pyguibud.core.model import WIDGET_API_VERSION, Prop, WidgetSpec, canonical_distribution
from pyguibud.core.registry import WIDGETS_GROUP, Registry, configure_default_registry
from pyguibud.designer.present.plugins import plugin_note, plugin_rows
from pyguibud.designer.preview import PreparedPreview, child_argv
from pyguibud.designer.properties import BOOTSTYLE_KEY, field_rows
from pyguibud.designer.settings import Settings, load_settings, settings_path
from pyguibud.i18n import _, set_language
from pyguibud.preview import _configure_plugins, _parser

ROOT = Path(__file__).resolve().parents[2]
ACME_SRC = ROOT / "examples" / "acme_plugin" / "src"
DEMO = ROOT / "examples" / "acme_demo.ui"
ACME = "acme-pyguibud"
#: The pseudo-locale and the longest real locales (Step 18 fit checks).
LONG_LANGUAGES = ("en_XA", "de_DE", "nl_NL", "fr_FR", "pt_PT")
HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
)


@dataclass
class _Dist:
    name: str


class _AcmeEP:
    """The acme entry point; ``loads`` counts imports (a disabled plugin is never imported)."""

    name, value, group = "acme", "acme_pyguibud:widgets", WIDGETS_GROUP

    def __init__(self) -> None:
        self.dist = _Dist("acme_pyguibud")  # not canonical on purpose
        self.loads = 0

    def load(self) -> object:
        self.loads += 1
        sys.modules.pop("acme_pyguibud", None)
        return importlib.import_module("acme_pyguibud").widgets


@pytest.fixture
def acme(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str | None], _AcmeEP]]:
    """Add acme to the metadata entry points (so ``Registry()`` and the default see it)."""
    real = registry_module._metadata_entry_points
    ep = _AcmeEP()
    monkeypatch.syspath_prepend(str(ACME_SRC))

    def source(group: str) -> Iterable[Any]:
        # An installed acme-pyguibud would sort first and shadow the fake (QA-17c-09).
        found = [e for e in real(group)
                 if e.dist is None or canonical_distribution(e.dist.name) != ACME]  # fmt: skip
        return [*found, ep] if group == WIDGETS_GROUP else found

    monkeypatch.setattr(registry_module, "_metadata_entry_points", source)

    def make(mode: str | None) -> _AcmeEP:
        if mode is None:
            monkeypatch.delenv("ACME_PYGUIBUD_BREAK", raising=False)
        else:
            monkeypatch.setenv("ACME_PYGUIBUD_BREAK", mode)
        return ep

    yield make
    sys.modules.pop("acme_pyguibud", None)


def _settle(root: Any, rounds: int = 3) -> None:
    for _round in range(rounds):
        root.update()


def _status(registry: Registry, key: str = ACME) -> str:
    return next(row.status for row in plugin_rows(registry) if row.key == key)


def _failures(registry: Registry) -> list[Any]:
    return [d for d in registry.diagnostics() if d.code == "registry.factory_failed"]


# ------------------------------------------------------------------ pure
def test_child_argv_round_trips_to_the_child_registry(acme: Any, tmp_path: Path) -> None:
    ep = acme(None)
    prepared = PreparedPreview(tmp_path / "a.ui", None, None, "main", None, ())
    for plugins, disabled, loads in (
        ((), frozenset(), 1),
        (("Acme_PyGUIbud", "other"), frozenset({ACME}), 0),
        ("all", frozenset({ACME}), 0),
    ):
        ep.loads = 0
        argv = child_argv(prepared, tmp_path, ui_lang="en_GB", lang=None, theme=None,
                          plugins=plugins)  # fmt: skip
        assert argv[1:3] == ["-m", "pyguibud.preview"]
        args = _parser().parse_args(argv[3:])
        assert args.file == str(tmp_path / "a.ui")
        configure_default_registry()  # what the child starts with
        _configure_plugins(args)
        registry = default_registry()
        assert registry.disabled_distributions() == disabled, plugins
        assert (registry.get("acme:ColourSwatch") is None) == bool(disabled), plugins
        assert ep.loads == loads, plugins


def test_child_argv_never_splits_a_single_name(tmp_path: Path) -> None:
    """A bare ``str`` filter is one name (as ``Registry`` treats it), never its letters."""
    prepared = PreparedPreview(tmp_path / "a.ui", None, None, "main", None, ())
    argv = child_argv(prepared, tmp_path, ui_lang="en_GB", lang=None, theme=None,
                      plugins="acme")  # fmt: skip  # a str is a Collection[str] for mypy
    assert argv[argv.index("--disable-plugins") + 1] == "acme"


def _bootstyle_doc(cls: str, extra: str = "") -> Any:
    text = (
        HEADER + '<window id="w" kind="main"><layout type="grid"/>'
        f'<widget class="{cls}" id="x"{extra}><cell row="0" column="0"/></widget>'
        "</window></pyguibud-ui>"
    )
    return read_ui_string(text).document


@pytest.mark.parametrize(
    ("cls", "extra", "shown"),
    [
        ("Text", "", False),
        ("Listbox", "", False),
        ("Canvas", "", False),
        ("zz:Missing", ' fallback="Listbox"', False),  # an uninstalled plugin: its fallback
        ("zz:Missing", ' fallback="Label"', True),
        ("Button", "", True),
    ],
)
def test_the_bootstyle_row_follows_the_core_class(cls: str, extra: str, shown: bool) -> None:
    document = _bootstyle_doc(cls, extra)
    node = document.children[0].children[0]
    keys = [f.key for f in field_rows([node], Registry(), document)]
    assert ("tb:bootstyle" in keys) is shown


def test_disable_then_restart_gives_r88_and_enable_reverses(acme: Any) -> None:
    """Without Tk: the settings file → ``configure_default_registry`` → status and R88."""
    ep = acme(None)
    document = read_ui_string(DEMO.read_text(encoding="utf-8")).document
    for stored, status, r88 in ((["acme-pyguibud"], "disabled", 1), ([], "loaded", 0)):
        path = settings_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"disabled_plugins": stored}), encoding="utf-8")
        ep.loads = 0
        settings, _problem = load_settings()
        configure_default_registry(settings.disabled_plugins)
        registry = default_registry()
        assert _status(registry) == status
        codes = [f.code for f in validate(document, registry).findings]
        assert codes.count("validate.plugin_disabled") == r88
        assert ep.loads == (0 if r88 else 1)


# ------------------------------------------------------------------ Tk
def _app(root: Any, registry: Registry, settings: Settings | None = None) -> Any:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.session import DesignerSession

    return DesignerApp(root, DesignerSession(registry), settings=settings or Settings())


def _open_plugins(app: Any) -> Any:
    from pyguibud.designer.dialogs.plugins import PluginsDialog

    assert app.registry.invoke("help.plugins")
    dialog = app._live_dialogs()[-1]
    assert isinstance(dialog, PluginsDialog)
    return dialog


def _row_of(dialog: Any, key: str) -> str:
    return next(str(i) for i, row in enumerate(dialog.rows) if row.key == key)


@pytest.mark.gui
def test_the_failure_card_is_selectable_deletable_and_comes_back_on_undo(
    designer_root: Any, acme: Any, tmp_path: Path
) -> None:
    acme("factory")
    registry = Registry()
    app = _app(designer_root, registry)
    try:
        copy = tmp_path / "demo.ui"
        shutil.copyfile(DEMO, copy)
        assert app.open_path(copy)
        _settle(designer_root)
        document = app.session.document
        swatch = document.find("swt_colour")
        view = app.shell.canvas.stages[0].view
        assert view is not None
        card = view.outer[id(swatch)]
        assert card.winfo_class() == "TLabelframe"
        assert "acme:ColourSwatch" in card.cget("text")
        assert view.node_of(card) is swatch
        app.session.select(view.node_of(card), origin="canvas")
        before = dump_ui(document)
        assert app.registry.invoke("edit.delete")
        _settle(designer_root)
        assert document.find("swt_colour") is None
        assert app.registry.invoke("edit.undo")
        _settle(designer_root)
        assert dump_ui(document) == before
        restored = document.find("swt_colour")
        view = app.shell.canvas.stages[0].view
        assert view is not None and view.outer[id(restored)].winfo_class() == "TLabelframe"
        assert app.registry.invoke("edit.redo")
        _settle(designer_root)
        assert document.find("swt_colour") is None
        # Rebuilds report nothing new: one diagnostic per (class, backend, stage).
        assert [(d.distribution, d.params["stage"]) for d in _failures(registry)] == [
            ("acme_pyguibud", "create")  # the distribution's own spelling
        ]
    finally:
        app.dispose()


def _raising(*_args: Any) -> Any:
    raise RuntimeError("boom")


@pytest.mark.gui
def test_a_failing_container_keeps_editable_children(designer_root: Any, tmp_path: Path) -> None:
    from tests.designer.test_plugins_17c import _EP, _registry
    from tests.designer.test_plugins_17c import _Dist as Dist17c

    box = WidgetSpec(name="zz:Box", display_name="Box", category="Zz",
                     api_version=WIDGET_API_VERSION, fallback="Frame", children="layout",
                     factories={"ttkbootstrap": _raising})  # fmt: skip
    registry = _registry(_EP("zz", "zz:x", Dist17c("zz"), [box]))
    path = tmp_path / "box.ui"
    path.write_text(
        HEADER + '<window id="w" kind="main"><layout type="grid"/>'
        '<widget class="zz:Box" id="box" fallback="Frame"><layout type="grid"/>'
        '<cell row="0" column="0"/>'
        '<widget class="Label" id="inside"><prop name="text">Old</prop>'
        '<cell row="0" column="0"/></widget></widget></window></pyguibud-ui>',
        encoding="utf-8",
    )
    app = _app(designer_root, registry)
    try:
        assert app.open_path(path)
        _settle(designer_root)
        document, stack = app.session.document, app.session.stack
        inside = document.find("inside")
        app.session.select(inside, origin="tree")
        outcome = stack.execute(SetProp(inside, Prop(name="text", value="New")))
        assert outcome.accepted, outcome.message
        _settle(designer_root)
        view = app.shell.canvas.stages[0].view
        assert view is not None
        frame = view.outer[id(document.find("box"))]
        label = view.outer[id(inside)]
        assert frame.winfo_class() == "TFrame"
        assert str(label).startswith(str(frame) + ".")  # still inside the fallback
        assert label.cget("text") == "New"
        assert app.session.selection.nodes == (inside,)
    finally:
        app.dispose()


@pytest.mark.gui
def test_help_plugins_turns_failed_when_the_real_factory_breaks(
    designer_root: Any, acme: Any, tmp_path: Path
) -> None:
    acme("factory")
    registry = Registry()
    app = _app(designer_root, registry)
    try:
        dialog = _open_plugins(app)
        index = _row_of(dialog, ACME)
        assert dialog.tree.set(index, "status") == "Loaded"  # the spec itself loads
        copy = tmp_path / "demo.ui"
        shutil.copyfile(DEMO, copy)
        assert app.open_path(copy)  # builds the canvas: the factory raises
        _settle(designer_root)
        assert _failures(registry)
        dialog._poll()
        index = _row_of(dialog, ACME)
        assert dialog.tree.set(index, "status") == "Failed"
        dialog.tree.selection_set(index)
        dialog._show()
        details = dialog.details.get("1.0", "end")
        assert "Traceback" in details and "told to break (factory)" in details
        dialog.close()
    finally:
        app.dispose()


@pytest.mark.gui
def test_the_dialog_writes_settings_and_the_restart_disables_acme(
    designer_root: Any, acme: Any
) -> None:
    ep = acme(None)
    app = _app(designer_root, Registry(), Settings())
    try:
        dialog = _open_plugins(app)
        # The built-in row cannot be disabled: the button is off and toggle() does nothing.
        dialog.tree.selection_set(_row_of(dialog, "pyguibud"))
        dialog._show()
        assert dialog.toggle_button.instate(["disabled"])
        dialog.toggle()
        assert app.settings.disabled_plugins == ()
        assert not settings_path().exists() or "pyguibud" not in json.loads(
            settings_path().read_text(encoding="utf-8")
        ).get("disabled_plugins", [])
        dialog.tree.selection_set(_row_of(dialog, ACME))
        dialog._show()
        dialog.toggle()
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
        assert stored["disabled_plugins"] == [ACME]
        dialog.close()
    finally:
        app.dispose()
    # The restart, as ``app.run`` does it.
    ep.loads = 0
    settings, _problem = load_settings()
    configure_default_registry(settings.disabled_plugins)
    registry = default_registry()
    assert _status(registry) == "disabled" and ep.loads == 0
    document = read_ui_string(DEMO.read_text(encoding="utf-8")).document
    assert "validate.plugin_disabled" in [f.code for f in validate(document, registry).findings]
    app = _app(designer_root, registry, settings)
    try:
        dialog = _open_plugins(app)
        index = _row_of(dialog, ACME)
        assert dialog.tree.set(index, "status") == "Disabled"
        dialog.tree.selection_set(index)
        dialog._show()
        assert dialog.toggle_button.cget("text") == "Enable on next start"
        dialog.toggle()
        stored = json.loads(settings_path().read_text(encoding="utf-8"))
        assert stored.get("disabled_plugins", []) == []  # the default is omitted
        assert dialog.tree.set(index, "status") == "Disabled (enabled on next start)"
        dialog.close()
    finally:
        app.dispose()
    settings, _problem = load_settings()
    configure_default_registry(settings.disabled_plugins)
    assert _status(default_registry()) == "loaded" and ep.loads == 1


@pytest.mark.gui
def test_the_bootstyle_row_refuses_with_the_reason_and_undoes(designer_root: Any) -> None:
    app = _app(designer_root, default_registry())
    try:
        app.new_from_template("login_form")
        document, stack = app.session.document, app.session.stack
        button = document.find("btn_login")
        app.session.select(button, origin="tree")
        _settle(designer_root)
        editor = app.shell.inspector._editors["tb:bootstyle"]
        assert isinstance(editor.widget, ttk.Combobox)
        before, index = dump_ui(document), stack.index
        editor.var.set("primary;x")
        editor._enter()
        assert editor.invalid
        assert "bootstyle" in app.shell._message.lower()
        assert dump_ui(document) == before and stack.index == index
        editor.var.set("success-outline")
        editor._enter()
        assert not editor.invalid and button.extra_attrs[BOOTSTYLE_KEY] == "success-outline"
        _settle(designer_root)
        editor = app.shell.inspector._editors["tb:bootstyle"]
        editor.var.set("")
        editor._enter()
        assert BOOTSTYLE_KEY not in button.extra_attrs
        assert app.registry.invoke("edit.undo")
        assert button.extra_attrs[BOOTSTYLE_KEY] == "success-outline"
        assert app.registry.invoke("edit.undo")
        assert dump_ui(document) == before
        assert app.registry.invoke("edit.redo")
        assert button.extra_attrs[BOOTSTYLE_KEY] == "success-outline"
    finally:
        app.dispose()


@pytest.mark.gui
@pytest.mark.parametrize("lang", LONG_LANGUAGES)
def test_en_xa_dialog_opened_fresh_fits(designer_root: Any, lang: str) -> None:
    from tests.designer.test_plugins_17c import _all_statuses

    english = _("_Disable on next start")
    set_language(lang)
    assert _("_Disable on next start") != english  # really pseudo-localised
    app = _app(designer_root, _all_statuses())
    try:
        dialog = _open_plugins(app)
        dialog.window.deiconify()
        _settle(designer_root)
        assert dialog.window.winfo_ismapped()
        for button in (dialog.copy_button, dialog.toggle_button, dialog.close_button):
            assert button.winfo_ismapped()
            assert button.winfo_reqwidth() <= button.winfo_width(), button.cget("text")
        right = max(b.winfo_rootx() + b.winfo_width() for b in (dialog.close_button,))
        assert right <= dialog.window.winfo_rootx() + dialog.window.winfo_width()
        assert dialog.window.winfo_width() >= dialog.window.winfo_reqwidth()
        dialog.close()
    finally:
        app.dispose()


@pytest.mark.gui
@pytest.mark.parametrize("lang", LONG_LANGUAGES)
def test_en_xa_start_up_note_fits_the_minimum_window(designer_root: Any, lang: str) -> None:
    from pyguibud.designer import theme_tk
    from tests.designer.test_plugins_17c import _all_statuses

    english = plugin_note(_all_statuses(), safe_mode=False)
    set_language(lang)
    for safe in (False, True):
        note = plugin_note(_all_statuses(), safe_mode=safe)
        assert note is not None and note != english
        width = tkfont.nametofont("TkDefaultFont").measure(note)
        # Room left in an 800 px window for the message beside the findings summary.
        assert width <= theme_tk.scaled(designer_root, 800) * 0.6, (note, width)
