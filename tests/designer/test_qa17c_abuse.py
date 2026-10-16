"""QA abuse tests of Step 17c that drive the designer (Help > Plugins, the failure card, the
Bootstyle row). Kept out of ``tests/qa`` because a designer session root there breaks
``tests/runtime`` (16c note). The pure cases are in ``tests/qa/test_step17c_abuse.py``.

Plugins are fake entry points (an installed acme never changes these tests). Strict ``xfail``
marks the open findings QA-17c-NN.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

import pytest

from pyguibud.core import dump_ui, read_ui
from pyguibud.core.commands import CommandStack
from pyguibud.core.registry import Registry
from pyguibud.designer.canvas.engine import CanvasEngine
from pyguibud.designer.dialogs.plugins import _M_TRUST as _M_TRUST_SOURCE
from pyguibud.designer.properties import BOOTSTYLE_KEY, commit_commands, field_rows
from pyguibud.designer.settings import Settings, load_settings
from pyguibud.i18n import LANGUAGES, PSEUDO_LANGUAGE, set_language
from tests.designer.test_plugins_17c import _EP, _Dist, _doc, _raising, _registry, _spec

pytestmark = pytest.mark.gui

_HOSTILE = "\ud800 lone \x00 nul ‮ bidi {brace \\ back \t tab " + "y" * 600_000


def _hostile_registry() -> Registry:
    return _registry(
        _EP("a", "a:x", _Dist("s‮ur{x}"), RuntimeError(_HOSTILE)),
        _EP("b", "b:x", _Dist("nul\x00dist"), RuntimeError("short")),
        _EP("c", "c:x", _Dist("ok-dist"), [_spec("zz:Swatch")]),
    )


def _app(root: Any, registry: Registry, settings: Settings | None = None) -> Any:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.session import DesignerSession

    return DesignerApp(root, DesignerSession(registry), settings=settings or Settings())


@pytest.fixture
def app(designer_root: Any) -> Iterator[Any]:
    designer = _app(designer_root, _hostile_registry())
    yield designer
    designer.dispose()


def _open(app: Any) -> Any:
    from pyguibud.designer.dialogs.plugins import PluginsDialog

    assert app.registry.invoke("help.plugins")
    dialog = app._live_dialogs()[-1]
    assert isinstance(dialog, PluginsDialog)
    return dialog


def _afters(root: Any) -> set[str]:
    return set(root.tk.splitlist(root.tk.call("after", "info")))


# ------------------------------------------------------------------ the dialog
def test_hostile_names_and_a_huge_traceback_show_copy_and_stay_fast(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    copied: list[str] = []
    real_put = app._clipboard_put

    def put(text: str) -> None:
        copied.append(text)
        real_put(text)

    monkeypatch.setattr(app, "_clipboard_put", put)
    dialog = _open(app)
    tree = dialog.tree
    assert len(tree.get_children()) == 4
    for iid in tree.get_children():
        start = time.perf_counter()
        tree.selection_set(iid)
        dialog._show()
        dialog.copy()
        app.root.update_idletasks()
        assert time.perf_counter() - start < 3.0, iid
    assert any("y" * 1000 in text for text in copied)
    app.root.clipboard_clear()
    dialog.close()


def test_keyboard_only_walks_rows_reaches_the_buttons_and_escapes(app: Any) -> None:
    dialog = _open(app)
    tree, window = dialog.tree, dialog.window
    app.root.update()
    tree.focus_set()
    seen = []
    for _press in range(5):
        tree.event_generate("<Down>")
        app.root.update()
        seen.append(tree.selection())
    assert len({s for s in seen if s}) >= 3  # the arrow keys move the selection
    tree.event_generate("<Up>")  # to ok-dist: the hostile names cannot be toggled (QA-17c-02)
    app.root.update()
    assert dialog.selected().key == "ok-dist" and dialog.selected().can_toggle
    chain, widget = [], tree
    for _press in range(8):
        widget = widget.tk_focusNext()
        chain.append(widget)
    assert dialog.details in chain
    assert all(b in chain for b in (dialog.copy_button, dialog.toggle_button, dialog.close_button))
    window.event_generate("<Escape>")
    assert dialog.closed


@pytest.mark.parametrize("how", ["escape", "wm-close", "close-button", "alt-key", "dispose"])
def test_no_poll_callback_outlives_the_dialog(designer_root: Any, how: str) -> None:
    designer = _app(designer_root, _hostile_registry())
    try:
        before = _afters(designer_root)
        dialog = _open(designer)
        designer_root.update()
        poll = dialog._poll_id
        assert poll in _afters(designer_root)
        if how == "escape":
            dialog.window.event_generate("<Escape>")
        elif how == "wm-close":
            designer_root.tk.call(dialog.window.protocol("WM_DELETE_WINDOW"))
        elif how == "close-button":
            dialog.close_button.invoke()
        elif how == "alt-key":
            dialog._on_alt(type("E", (), {"char": "l"})())
        else:
            designer.dispose()
        assert dialog.closed
        leaked = _afters(designer_root) - before
        assert dialog._poll_id not in leaked and poll not in leaked
        dialog._poll()  # a late tick after close schedules nothing
        assert dialog._poll_id not in (_afters(designer_root) - before)
    finally:
        designer.dispose()


def test_opening_twice_keeps_one_dialog(app: Any) -> None:
    from pyguibud.designer.dialogs.plugins import PluginsDialog

    first = _open(app)
    for _press in range(5):
        app.registry.invoke("help.plugins")
    live = [d for d in app._live_dialogs() if isinstance(d, PluginsDialog)]
    assert live == [first]
    first.close()
    second = _open(app)
    assert second is not first
    second.close()


def test_toggle_storm_writes_the_final_state(designer_root: Any) -> None:
    designer = _app(designer_root, _hostile_registry(), Settings())
    try:
        dialog = _open(designer)
        row = next(i for i, r in enumerate(dialog.rows) if r.key == "ok-dist")
        dialog.tree.selection_set(str(row))
        dialog._show()
        for _press in range(301):
            dialog._on_alt(type("E", (), {"char": "d" if _press % 2 == 0 else "e"})())
        assert designer.settings.disabled_plugins == ("ok-dist",)
        assert load_settings()[0].disabled_plugins == ("ok-dist",)
        # The built-in row: every key is refused, nothing is written.
        dialog.tree.selection_set("0")
        dialog._show()
        for char in "de":
            dialog._on_alt(type("E", (), {"char": char})())
        assert designer.settings.disabled_plugins == ("ok-dist",)
        dialog.close()
    finally:
        designer.dispose()


def test_a_revision_storm_while_open_refreshes_and_keeps_the_selection(app: Any) -> None:
    dialog = _open(app)
    key = "ok-dist"
    dialog.tree.selection_set(next(str(i) for i, r in enumerate(dialog.rows) if r.key == key))
    reg = app.session.registry
    for index in range(100):
        reg.report_failure("zz:Swatch", "ttkbootstrap", "create", RuntimeError(f"late {index}"))
        reg.report_failure(f"zz:Ghost{index}", "ttkbootstrap", "import", RuntimeError("x"))
    dialog._poll()
    selected = dialog.selected()
    assert selected is not None and selected.key == key and selected.status == "failed"
    details = dialog.details.get("1.0", "end")
    assert "late 0" in details and "late 1" not in details  # deduplicated per stage
    dialog.close()


# ------------------------------------------------------------------ the canvas
def test_a_hundred_failing_widgets_give_one_diagnostic_and_stay_responsive(
    designer_root: Any,
) -> None:
    reg = _registry(_EP("zz", "zz:x", _Dist("zz"), [
        _spec("zz:Gauge", factories={"ttkbootstrap": _raising}),
    ]))  # fmt: skip
    body = "".join(
        f'<widget class="zz:Gauge" id="g{i}" fallback="Label" plugin="zz">'
        f'<cell row="{i // 10}" column="{i % 10}"/></widget>'
        for i in range(100)
    )
    document = _doc(body)
    window = document.children[0]
    host = ttk.Frame(designer_root)
    try:
        start = time.perf_counter()
        view = CanvasEngine(reg).build(document, window, host)
        designer_root.update_idletasks()
        assert time.perf_counter() - start < 10.0
        cards = [view.outer[id(child)] for child in window.children]
        assert {c.winfo_class() for c in cards} == {"TLabelframe"}
        failures = [d for d in reg.diagnostics() if d.code == "registry.factory_failed"]
        assert len(failures) == 1
        view.session.destroy()
        again = CanvasEngine(reg).build(document, window, host)  # a rebuild adds nothing
        assert len([d for d in reg.diagnostics() if d.code == "registry.factory_failed"]) == 1
        again.session.destroy()
    finally:
        host.destroy()


def _destroys_parent(parent: Any, *_args: Any) -> Any:
    parent.destroy()
    return ttk.Label(parent.master)


def test_a_factory_that_destroys_its_parent_leaves_the_designer_usable(
    designer_root: Any, tmp_path: Path
) -> None:
    """17b risk 4 (accepted): the design build fails cleanly, the stage shows its "cannot be
    drawn" card, one diagnostic (stage check); the document stays editable and saveable."""
    reg = _registry(_EP("zz", "zz:x", _Dist("zz"), [
        _spec("zz:Wrecker", factories={"ttkbootstrap": _destroys_parent}),
    ]))  # fmt: skip
    document = _doc(
        '<widget class="Frame" id="box"><layout type="grid"/><cell row="0" column="0"/>'
        '<widget class="zz:Wrecker" id="w1" fallback="Label" plugin="zz">'
        '<cell row="0" column="0"/></widget></widget>'
        '<widget class="Label" id="after"><cell row="1" column="0"/></widget>'
    )
    source = tmp_path / "wreck.ui"
    source.write_bytes(dump_ui(document))
    designer = _app(designer_root, reg)
    try:
        assert designer.open_path(source)
        for _round in range(3):
            designer_root.update()
        stage = designer.shell.canvas.stages[0]
        assert stage.view is None and stage.error  # the window card, not a crash
        stages = [d.params.get("stage") for d in reg.diagnostics()
                  if d.code == "registry.factory_failed"]  # fmt: skip
        assert stages == ["check"]
        doc = designer.session.document
        designer.session.select(doc.find("w1"), origin="tree")
        assert designer.registry.invoke("edit.delete")
        for _round in range(3):
            designer_root.update()
        assert designer.shell.canvas.stages[0].view is not None  # drawable again
        assert designer.registry.invoke("edit.undo")
        designer_root.update()
        assert doc.find("w1") is not None
    finally:
        designer.dispose()


def test_the_card_copies_pastes_cuts_and_saves_as_with_its_plugin_attributes(
    designer_root: Any, tmp_path: Path
) -> None:
    reg = _registry(_EP("zz", "zz:x", _Dist("zz"), [
        _spec("zz:Gauge", factories={"ttkbootstrap": _raising}),
    ]))  # fmt: skip
    source = tmp_path / "in.ui"
    document = _doc(
        '<widget class="zz:Gauge" id="gauge" fallback="Label" plugin="zz">'
        '<prop name="text" translatable="true">Hé ✓</prop><cell row="0" column="0"/></widget>'
        '<widget class="Label" id="keep"><prop name="text">K</prop>'
        '<cell row="0" column="1"/></widget>'
    )
    source.write_bytes(dump_ui(document))
    original = source.read_bytes()
    designer = _app(designer_root, reg)
    try:
        assert designer.open_path(source)
        designer_root.update()
        doc = designer.session.document
        gauge = doc.find("gauge")
        designer.session.select(gauge, origin="canvas")
        assert designer.registry.invoke("edit.copy")
        assert "zz:Gauge" in designer._clipboard_get()
        assert designer.registry.invoke("edit.paste")
        designer_root.update()
        gauges = [w for w in doc.children[0].children if w.class_name == "zz:Gauge"]
        assert len(gauges) == 2
        pasted = next(w for w in gauges if w.id != "gauge")
        assert pasted.plugin == "zz" and pasted.fallback == "Label"
        assert pasted.props["text"].value == "Hé ✓"
        view = designer.shell.canvas.stages[0].view
        assert view is not None and view.outer[id(pasted)].winfo_class() == "TLabelframe"
        designer.session.select(doc.find("gauge"), origin="canvas")
        assert designer.registry.invoke("edit.cut")
        designer_root.update()
        assert doc.find("gauge") is None
        target = tmp_path / "out.ui"
        designer._ask_target = lambda: target
        designer.save(as_new=True)
        designer_root.update()
        assert source.read_bytes() == original  # Save As never touches the source
        saved = read_ui(target).document
        assert saved is not None
        again: Any = next(w for w in saved.children[0].children if w.id == pasted.id)
        assert (again.class_name, again.plugin, again.fallback) == ("zz:Gauge", "zz", "Label")
        assert saved.find("keep") is not None and saved.find("gauge") is None
    finally:
        designer_root.clipboard_clear()
        designer.dispose()


# ------------------------------------------------------------------ the Bootstyle row
JUNK_BOOTSTYLE = [
    "  ",
    " primary",
    "Primary",
    "primary  outline",
    "primary;x",
    "prímary",
    "‮primary",
    "a" * 65,
    "primary\noutline",
    "{primary}",
    "primary-",
]


@pytest.mark.parametrize("value", JUNK_BOOTSTYLE, ids=range(len(JUNK_BOOTSTYLE)))
def test_bootstyle_junk_is_refused_with_a_reason_and_changes_nothing(value: str) -> None:
    reg = _registry()
    document = _doc('<widget class="Button" id="b"><cell row="0" column="0"/></widget>')
    button = document.children[0].children[0]
    field = next(f for f in field_rows([button], reg, document) if f.key == "tb:bootstyle")
    stack = CommandStack(document, reg)
    before = dump_ui(document)
    result = stack.execute(commit_commands([button], field, value))
    assert not result.accepted and result.message
    assert dump_ui(document) == before and not stack.can_undo


def test_bootstyle_on_a_multi_selection_is_one_undo_step() -> None:
    reg = _registry()
    document = _doc(
        '<widget class="Button" id="b"><cell row="0" column="0"/></widget>'
        '<widget class="Label" id="l"><cell row="0" column="1"/></widget>'
        '<widget class="Text" id="t"><cell row="1" column="0"/></widget>'
    )
    button, label, text = document.children[0].children
    assert not any(f.key == "tb:bootstyle" for f in field_rows([button, text], reg, document))
    field = next(f for f in field_rows([button, label], reg, document) if f.key == "tb:bootstyle")
    stack = CommandStack(document, reg)
    before = dump_ui(document)
    assert stack.execute(commit_commands([button, label], field, "danger")).accepted
    assert button.extra_attrs[BOOTSTYLE_KEY] == label.extra_attrs[BOOTSTYLE_KEY] == "danger"
    refused = stack.execute(commit_commands([button, label], field, "danger;x"))
    assert not refused.accepted and label.extra_attrs[BOOTSTYLE_KEY] == "danger"
    stack.undo()
    assert dump_ui(document) == before
    assert stack.execute(commit_commands([button, label], field, "")).accepted
    assert dump_ui(document) == before


# ------------------------------------------------------------------ every locale
@pytest.mark.parametrize("lang", [*LANGUAGES, PSEUDO_LANGUAGE])
def test_the_dialog_fits_and_is_translated_in_every_locale(app: Any, lang: str) -> None:
    set_language(lang)
    try:
        dialog = _open(app)
        dialog.window.update()  # mapped, as a user sees it before pressing a key
        row = next(i for i, r in enumerate(dialog.rows) if r.key == "ok-dist")
        dialog.tree.selection_set(str(row))
        dialog._show()
        dialog.toggle()  # the longest status: "... (disabled on next start)"
        dialog.window.update()
        for button in (dialog.copy_button, dialog.toggle_button, dialog.close_button):
            assert button.winfo_reqwidth() <= button.winfo_width(), (lang, button.cget("text"))
            assert int(str(button.cget("underline"))) >= 0, (lang, button.cget("text"))
        assert dialog.window.winfo_width() >= dialog.window.winfo_reqwidth()
        if lang != "en_GB":
            assert dialog.header.cget("text") != _M_TRUST_SOURCE  # translated
        dialog.toggle()
        dialog.close()
    finally:
        set_language("en_GB")


@pytest.mark.parametrize("lang", ["en_GB", "de_DE", PSEUDO_LANGUAGE])
def test_qa17c_07_the_status_column_shows_the_whole_next_start_status(app: Any, lang: str) -> None:
    set_language(lang)
    try:
        dialog = _open(app)
        dialog.window.update()
        row = next(i for i, r in enumerate(dialog.rows) if r.key == "ok-dist")
        dialog.tree.selection_set(str(row))
        dialog._show()
        dialog.toggle()
        dialog.window.update()
        status = dialog.tree.set(str(row), "status")
        width = int(dialog.tree.column("status", "width"))
        try:
            assert tkfont.nametofont("TkDefaultFont").measure(status) < width, (lang, status)
        finally:
            dialog.toggle()
            dialog.close()
    finally:
        set_language("en_GB")


def test_a_long_traceback_scrolls_with_the_keyboard(app: Any) -> None:
    dialog = _open(app)
    dialog.window.update()
    row = next(i for i, r in enumerate(dialog.rows) if r.status == "failed" and r.key != "pyguibud")
    dialog.tree.selection_set(str(row))
    dialog._show()
    dialog.details.focus_set()
    dialog.window.update()
    top = dialog.details.yview()[0]
    for key in ("<Next>", "<Next>", "<Control-End>"):
        dialog.details.event_generate(key)
        dialog.window.update()
    assert dialog.details.yview()[0] > top  # read-only, yet the keys page through it
    dialog.close()


def test_qa17c_08_the_details_box_has_a_scrollbar(app: Any) -> None:
    dialog = _open(app)
    try:
        bars = [w for w in dialog.details.master.winfo_children()
                if w.winfo_class() in {"TScrollbar", "Scrollbar"}]  # fmt: skip
        assert len(bars) == 1
        row = next(i for i, r in enumerate(dialog.rows) if r.status == "failed")
        dialog.tree.selection_set(str(row))
        dialog._show()
        dialog.window.update()
        assert bars[0].get()[1] < 1.0  # the huge traceback: the bar shows there is more
    finally:
        dialog.close()


def test_safe_mode_rows_say_disabled_without_a_next_start_promise(designer_root: Any) -> None:
    ep = _EP("c", "c:x", _Dist("ok-dist"), [_spec("zz:Swatch")])
    settings = Settings()
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.session import DesignerSession

    session = DesignerSession(_registry(ep, disabled="all"))  # what --no-plugins builds
    app = DesignerApp(designer_root, session, settings=settings, plugins="all")
    try:
        dialog = _open(app)
        row = next(i for i, r in enumerate(dialog.rows) if r.key == "ok-dist")
        assert dialog.tree.set(str(row), "status") == "Disabled"
        dialog.tree.selection_set(str(row))
        dialog._show()
        dialog.toggle()  # the list is still editable in safe mode
        assert settings.disabled_plugins == ("ok-dist",)
        assert dialog.tree.set(str(row), "status") == "Disabled"
        dialog.close()
    finally:
        app.dispose()
