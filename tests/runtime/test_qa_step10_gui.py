"""QA regressions of Step 10 that need real Tk widgets (the one session root, ``master=``)."""

from __future__ import annotations

import logging
import subprocess
import sys
import textwrap
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.gui


@pytest.fixture
def loaded(tk_root: Any) -> Iterator[list[LoadedUi]]:
    before = set(tk_root.winfo_children())
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    tk_root.update()
    assert set(tk_root.winfo_children()) == before


def test_digit_shortcut_fires_on_the_key_not_on_ctrl_click(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path
) -> None:
    # QA-10-01: "Ctrl+1" used to bind <Control-1>, which Tk reads as Ctrl + mouse button 1.
    path = write_ui(
        tmp_path / "t.ui",
        '<window id="main" kind="main"><menubar><menu id="mnu"><prop name="text">_View</prop>'
        '<action id="act_one" handler="on_one" shortcut="Ctrl+1"/></menu></menubar>'
        '<layout type="grid"/>'
        '<widget class="Entry" id="ent"><event name="key:&lt;Alt-5&gt;" handler="on_five"/>'
        '<cell row="0" column="0"/></widget></window>',
    )
    calls: list[str] = []
    handlers = {"on_one": lambda: calls.append("one"), "on_five": lambda: calls.append("five")}
    ui = load_ui(path, handlers, master=tk_root)
    loaded.append(ui)
    ui.main.update()
    # Ctrl+click on the toplevel (shortcut binding) and Alt+button 5 on the entry (key: event),
    # each with its release so that no widget is left in a pressed state.
    for widget, button in ((ui.main, "Control-%s-1"), (ui.ent, "Alt-%s-5")):
        widget.event_generate(f"<{button % 'Button'}>", x=1, y=1)
        widget.event_generate(f"<{button % 'ButtonRelease'}>", x=1, y=1)
    ui.main.update()
    assert calls == []
    ui.ent.focus_force()  # generated key events go to the focus widget
    ui.main.update()
    ui.ent.event_generate("<Control-Key-1>")
    ui.ent.event_generate("<Alt-Key-5>")
    ui.main.update()
    assert calls == ["one", "five"]


def test_bad_translator_is_refused_before_any_change(tk_root: Any, loaded: list[LoadedUi]) -> None:
    # QA-10-04: a translator without pgettext used to raise AttributeError mid-way and stay stored.
    handlers = {"on_greet": lambda: None, "on_quit": lambda: None}
    ui = load_ui(EXAMPLES / "hello.ui", handlers, master=tk_root, lang="de_DE")
    loaded.append(ui)
    with pytest.raises(TypeError, match="translator"):
        ui.retranslate(translator=object())  # type: ignore[arg-type]
    ui.retranslate()
    assert ui.main.title() == "Hallo PyGUIbud"


_CHROME = (
    '<window id="main" kind="main"><prop name="title" translatable="true">Title</prop>'
    '<menubar><menu id="mnu"><prop name="text" translatable="true">_Menu</prop>'
    '<action id="act"><prop name="text" translatable="true">_Act</prop></action></menu>'
    '</menubar><layout type="grid"/>'
    '<widget class="Notebook" id="nbk"><cell row="0" column="0"/>'
    '<widget class="Frame" id="pg"><page><prop name="text" translatable="true">_Tab</prop>'
    '</page><layout type="grid"/>'
    '<widget class="Label" id="lbl"><prop name="text" translatable="true">Label</prop>'
    '<cell row="0" column="0"/></widget>'
    '<widget class="Button" id="btn"><prop name="text" translatable="true">_Button</prop>'
    '<cell row="1" column="0"/></widget></widget></widget>'
    '<statusbar id="sts"><prop name="text" translatable="true">Ready</prop></statusbar></window>'
    '<window id="dlg" kind="dialog"><prop name="title" translatable="true">Dialog</prop>'
    '<layout type="grid"/></window>'
)


class _Long:
    """Translations far longer than any display needs (a hostile or broken catalogue)."""

    def __init__(self, length: int) -> None:
        self.length = length

    def gettext(self, message: str) -> str:
        # Keep the source's mnemonic marker at the start, and add one past the cut.
        return message + "x" * self.length + "_Z"

    def pgettext(self, context: str, message: str) -> str:
        return self.gettext(message)


def test_overlong_translations_are_clipped_and_logged_once(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    # QA-10-07: a msgstr of millions of characters froze Tk; a translation is never validated.
    from pyguibud.core.validate import MAX_TEXT_LENGTH

    path = write_ui(tmp_path / "t.ui", _CHROME)
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        ui = load_ui(path, master=tk_root, translator=_Long(MAX_TEXT_LENGTH + 1000))
        loaded.append(ui)
        ui.main.update()
        menubar = ui.main.nametowidget(ui.main.cget("menu"))
        texts = {
            "title": ui.main.title(),
            "dialog": ui.dlg.title(),
            "menu": menubar.entrycget(0, "label"),
            "action": ui.mnu.entrycget(ui.act, "label"),
            "tab": ui.nbk.tab(0, "text"),
            "label": ui.lbl.cget("text"),
            "button": ui.btn.cget("text"),
            "status": ui.sts.cget("text"),
        }
        for name, shown in texts.items():
            assert len(shown) == MAX_TEXT_LENGTH and shown.endswith("\N{HORIZONTAL ELLIPSIS}"), name
        assert ui.btn.cget("underline") == 0 and ui.nbk.tab(0, "underline") == 0
        assert menubar.entrycget(0, "underline") == 0
        ui.retranslate()  # still clipped, but each slot is logged only once
    clipped = [r for r in caplog.records if "only the first" in r.getMessage()]
    assert len(clipped) == len(texts)
    assert {"'main'", "'btn'", "'pg'", "'sts'", "'act'", "'mnu'", "'dlg'", "'lbl'"} == {
        r.getMessage().split(" has ")[0].removeprefix("The text of ") for r in clipped
    }


def test_text_at_the_limit_is_kept_whole(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path
) -> None:
    from pyguibud.core.validate import MAX_TEXT_LENGTH

    path = write_ui(tmp_path / "t.ui", _CHROME)
    ui = load_ui(path, master=tk_root, translator=_Long(MAX_TEXT_LENGTH - len("Label_Z")))
    loaded.append(ui)
    assert len(ui.lbl.cget("text")) == MAX_TEXT_LENGTH
    assert ui.lbl.cget("text").endswith("_Z")


def test_closed_main_window_reports_destroyed(
    tk_root: Any, loaded: list[LoadedUi], tmp_path: Path
) -> None:
    # QA-10-09: closing the main window (its X button destroys it) made show() raise TclError.
    path = write_ui(tmp_path / "t.ui", _CHROME)
    ui = load_ui(path, master=tk_root)
    loaded.append(ui)
    ui.main.destroy()  # what the window manager's close button does to a Toplevel
    calls: tuple[Callable[[], object], ...] = (lambda: ui.show("dlg"), ui.retranslate, ui.run)
    for call in calls:
        with pytest.raises(UiError) as info:
            call()
        assert info.value.code == "runtime.destroyed"
    assert not ui.dlg.winfo_exists()  # the dialog left behind is destroyed with the session


def test_destroyed_master_reports_destroyed() -> None:
    # QA-10-09: the application destroys the root it passed as master= (own process: the
    # session root of the test run must survive).
    code = textwrap.dedent(
        f"""
        import ttkbootstrap
        from pyguibud_runtime import UiError, load_ui
        root = ttkbootstrap.App(title="t")
        root.withdraw()
        ui = load_ui({str(EXAMPLES / "hello.ui")!r}, {{"on_greet": print, "on_quit": print}},
                     master=root)
        root.destroy()
        for call in (lambda: ui.show("main"), ui.retranslate, ui.run):
            try:
                call()
            except UiError as exc:
                print(exc.code)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.stdout.split() == ["runtime.destroyed"] * 3, result.stderr


class _NotText:
    def gettext(self, message: str) -> object:
        return None if message == "Ready" else message.upper()

    def pgettext(self, context: str, message: str) -> object:
        return message.upper()


def test_failed_retranslate_changes_no_text(tk_root: Any, loaded: list[LoadedUi]) -> None:
    # QA-10-11: a translator returning a non-str left half the texts changed and stayed stored.
    handlers = {"on_greet": lambda: None, "on_quit": lambda: None}
    ui = load_ui(EXAMPLES / "hello.ui", handlers, master=tk_root, lang="de_DE")
    loaded.append(ui)
    with pytest.raises(TypeError, match="NoneType, not str"):
        ui.retranslate(translator=_NotText())  # type: ignore[arg-type]
    assert ui.main.title() == "Hallo PyGUIbud" and ui.sts_main.cget("text") == "Bereit"
    ui.retranslate()  # the German catalogue is still the current translation
    assert ui.main.title() == "Hallo PyGUIbud"
    ui.retranslate("en_GB")
    assert ui.main.title() == "Hello PyGUIbud"
