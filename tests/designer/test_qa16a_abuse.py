"""QA abuse tests of Step 16a (Preview > Toolkit, spec backends D16, D17, B14, B15).

Fixed findings are regression tests named after their QA-16a-NN id; the rest pin behaviour that
QA checked and found correct. They run on the real ``DesignerApp`` (the ``app`` fixture of
``test_preview_gui``) with a fake child process, so no real preview window opens.
"""

# ruff: noqa: F811 - the fixtures of test_preview_gui are re-used by import
from __future__ import annotations

from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core.keys import split_mnemonic
from pyguibud.designer import preview as pv
from pyguibud.designer.actions import ActionDef, MenuDef, label_of
from tests.designer.fakes import FakeProcess
from tests.designer.test_preview_gui import _poll, app, children  # noqa: F401

pytestmark = pytest.mark.gui

ALL_LANGUAGES = (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE)


def _argv_backend(child: FakeProcess) -> str:
    return child.argv[child.argv.index("--backend") + 1]


def _preview_marks(registry: Any) -> list[str]:
    marks: list[str] = []
    for item in registry.menu_items("preview"):
        if isinstance(item, MenuDef):
            text, at = split_mnemonic(i18n._(item.label))
        elif isinstance(item, ActionDef):
            text, at = split_mnemonic(label_of(item))
        else:
            continue
        if at >= 0:
            marks.append(text[at].casefold())
    return marks


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_qa16a_01_preview_menu_access_keys_are_unique_on_the_real_app(app: Any, lang: str) -> None:
    before = i18n.get_language()
    try:
        i18n.set_language(lang)
        assert app.registry.menu("preview.toolkit") is not None  # the real app always has it
        marks = _preview_marks(app.registry)
        assert len(marks) == len(set(marks)), (lang, marks)
    finally:
        i18n.set_language(before)


def test_the_real_app_lists_only_registered_toolkits(app: Any) -> None:
    """Since 16b the pyside6 entry point exists, so PySide6 is always listed (greyed when it is
    not installed: QA-16a-11, UAT 16b item 1)."""
    names = app._toolkit_names()
    assert names[0] == "ttkbootstrap" and "tkinter" in names and "pyside6" in names


@pytest.mark.parametrize("saved", ["qt5", "my_uninstalled_fork"])
def test_qa16a_02_an_unknown_saved_toolkit_previews_with_ttkbootstrap(
    app: Any, children: list[FakeProcess], saved: str
) -> None:
    app.settings.preview_backend = saved  # what a hand-edited or stale settings.json gives
    assert saved not in app._toolkit_names()
    app.preview.run()
    assert _argv_backend(children[0]) == "ttkbootstrap"
    assert app.preview.toolkit() == "ttkbootstrap"


def test_an_unknown_saved_toolkit_is_kept_reported_once_and_not_used(
    app: Any, children: list[FakeProcess]
) -> None:
    """D17 ruling (QA-16a-02): kept in the settings, ttkbootstrap is used and checked, and the
    status bar says so once."""
    app.settings.preview_backend = "qt5"
    note = "qt5 is not installed; the preview uses ttkbootstrap."
    for index in range(2):  # a second preview does not repeat it
        app.preview.run()
        children[-1].ready()
        _poll(app.preview)
        assert (note in app.shell._message) == (index == 0), app.shell._message
        children[-1].end(0, {"code": "ok"})
        _poll(app.preview)
    assert len(children) == 2 and _argv_backend(children[1]) == "ttkbootstrap"
    assert app.settings.preview_backend == "qt5"
    checked = [a.id for a in app.registry.actions() if app.registry.is_checked(a)]
    assert "preview.toolkit.ttkbootstrap" in checked


def test_a_storm_of_toolkit_switches_gives_one_restart_with_the_last_choice(
    app: Any, children: list[FakeProcess]
) -> None:
    preview = app.preview
    assert app.shell._invoke("preview.toolkit.ttkbootstrap")
    preview.run()
    children[0].ready()
    _poll(preview)
    for index in range(41):  # ends on tkinter
        app.shell._invoke("preview.toolkit." + ("tkinter" if index % 2 == 0 else "ttkbootstrap"))
    assert len(children) == 1 and children[0].stdin.lines == ["quit"]
    children[0].end(0, {"code": "ok"})
    _poll(preview)
    assert len(children) == 2 and _argv_backend(children[1]) == "tkinter"
    assert "--theme" not in children[1].argv
    children[1].ready(themes=())
    _poll(preview)
    assert "the exported module uses ttkbootstrap" in app.shell._message
    assert app.settings.preview_backend == "tkinter"


def test_a_theme_override_is_dropped_for_tkinter_and_kept_for_later(
    app: Any, children: list[FakeProcess]
) -> None:
    preview = app.preview
    preview.run()
    children[0].ready()
    _poll(preview)
    preview.set_theme("darkly")
    assert preview.can_use_theme()
    assert app.shell._invoke("preview.toolkit.tkinter")
    use = app.registry.get("preview.use_theme")
    assert use is not None and not app.registry.is_enabled(use)
    children[0].end(0, {"code": "ok"})
    _poll(preview)
    assert "--theme" not in children[1].argv
    children[1].ready(themes=())
    _poll(preview)
    assert "the theme is chosen for the preview only" not in app.shell._message


def test_a_hand_made_call_cannot_choose_a_malformed_toolkit(app: Any) -> None:
    for bad in ("", "Tk", "a b", "pyside6; rm -rf", "x" * 33, "../tkinter", "tkinter\n"):
        app.preview.set_toolkit(bad)
        assert app.settings.preview_backend == "ttkbootstrap", bad


def test_toolkit_labels_fit_and_never_translate_the_names(app: Any) -> None:
    before = i18n.get_language()
    try:
        for lang in ALL_LANGUAGES:
            i18n.set_language(lang)
            labels = {
                a.id: label_of(a) for a in app.registry.actions() if a.menu == "preview.toolkit"
            }
            assert labels["preview.toolkit.tkinter"] == "tkinter", lang
            assert labels["preview.toolkit.ttkbootstrap"] == "ttkbootstrap", lang
            assert all(len(text) < 60 for text in labels.values()), (lang, labels)
    finally:
        i18n.set_language(before)
    assert pv.toolkit_label("pyside6") == "PySide6"


def test_a_switch_while_the_child_is_still_starting_restarts_it(
    app: Any, children: list[FakeProcess]
) -> None:
    preview = app.preview
    assert app.shell._invoke("preview.toolkit.ttkbootstrap")
    preview.run()  # no ready.json yet: the phase is "starting"
    assert app.shell._invoke("preview.toolkit.tkinter")
    children[0].end(0, {"code": "ok"})
    _poll(preview)
    assert len(children) == 2 and _argv_backend(children[1]) == "tkinter"


def test_qa16a_10_the_theme_cascade_is_disabled_for_another_toolkit(app: Any) -> None:
    """Ruling QA-16a-10: Preview > Theme itself is greyed, not only its items."""
    [(menu, index)] = [
        (m, i) for m, i, item in app.shell._entries if getattr(item, "id", "") == "preview.theme"
    ]
    for name, state in (("tkinter", "disabled"), ("ttkbootstrap", "normal")):
        assert app.shell._invoke(f"preview.toolkit.{name}")
        app.shell.refresh_states()  # what posting the Preview menu does
        assert str(menu.entrycget(index, "state")) == state, name
