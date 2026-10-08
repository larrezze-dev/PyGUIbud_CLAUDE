"""Step 14a.1 wiring: File menu, unsaved-changes guard, recovery and settings (UAT 4-7).

Native file dialogs are replaced through the ``dialogs.files`` seam and the designer's own
dialogs are answered through ``DesignerApp._live_dialogs()``; no real dialog blocks a test.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import Widget, XmlIoError, dump_ui
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop
from pyguibud.designer import app as app_module
from pyguibud.designer.app import DesignerApp, fit_geometry
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.confirm import ConfirmDialog
from pyguibud.designer.dialogs.message import ChoiceDialog
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.recovery import RecoverySession
from pyguibud.designer.settings import (
    M_SETTINGS_RESET,
    Settings,
    load_settings,
    settings_path,
    state_dir,
)

HELLO = Path(__file__).resolve().parents[2] / "examples" / "hello.ui"


# ---------------------------------------------------------------- pure
def test_fit_geometry_keeps_shrinks_or_drops() -> None:
    assert fit_geometry("1280x800+40+30", 1920, 1080) == "1280x800+40+30"
    assert fit_geometry("3000x2000+0+0", 1920, 1080) == "1920x1080+0+0"
    assert fit_geometry("800x600+5000+0", 1920, 1080) is None  # a removed monitor (A10)
    assert fit_geometry("800x600+1800+0", 1920, 1080) is None  # only 120 px visible
    # A bare "-X" is read as a negative position; it is written back as "+-X", since Tk reads
    # "-X" as a distance from the right edge (the old output kept "-100-50").
    assert fit_geometry("800x600-100-50", 1920, 1080) == "800x600+-100+-50"
    assert fit_geometry("garbage", 1920, 1080) is None
    assert fit_geometry("800x600--100+0", 1920, 1080) is None


def test_fit_geometry_keeps_a_window_on_a_second_monitor() -> None:
    """Regression: the bounds were the primary monitor only, so a window closed on a second
    monitor came back at the default place, and Tk's "+-1500" (a monitor on the left) raised
    ``ValueError`` at start-up."""
    right = (3840, 1080, 0, 0)  # a second monitor right of the primary one
    assert fit_geometry("800x600+2000+10", *right) == "800x600+2000+10"
    assert fit_geometry("800x600+2000+10", 1920, 1080) is None  # primary only: default place
    left = (3840, 1080, -1920, 0)  # a second monitor left of the primary one
    assert fit_geometry("800x600+-1500+10", *left) == "800x600+-1500+10"
    assert fit_geometry("800x600+-1500+10", 1920, 1080) is None  # unplugged: no exception
    above = (1920, 2160, 0, -1080)
    assert fit_geometry("800x600+10+-1000", *above) == "800x600+10+-1000"
    assert fit_geometry("800x600+-1900+10", *left) == "800x600+-1900+10"  # 780 px still on it
    assert fit_geometry("800x600+-2700+10", *left) is None  # 20 px left on the desktop


@pytest.mark.gui
def test_desktop_bounds_cover_the_primary_screen(designer_root: Any) -> None:
    width, height, left, top = app_module.desktop_bounds(designer_root)
    assert left <= 0 and top <= 0
    assert left + width >= designer_root.winfo_screenwidth()
    assert top + height >= designer_root.winfo_screenheight()


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def app(designer_root: Any) -> Iterator[DesignerApp]:
    """An app that persists its settings and autosaves (into the test's private profile)."""
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(designer_root, settings=Settings(), recovery=recovery)
    designer.exits = []  # type: ignore[attr-defined]
    designer.on_exit = lambda: designer.exits.append(True)  # type: ignore[attr-defined]
    yield designer
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()


@pytest.fixture
def hello(tmp_path: Path) -> Path:
    copy = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, copy)
    return copy


def edit(designer: DesignerApp, text: str = "Edited") -> None:
    session = designer.session
    assert session.stack is not None and session.document is not None
    label = next(
        n for n in session.document.walk() if isinstance(n, Widget) and n.class_name == "Label"
    )
    assert session.stack.execute(SetProp(label, Prop(name="text", value=text))).accepted


def dialog(designer: DesignerApp) -> Any:
    live = designer._live_dialogs()
    assert live, "no dialog is open"
    return live[-1]


def answer(designer: DesignerApp, index: int) -> None:
    box = dialog(designer)
    assert isinstance(box, ChoiceDialog)
    box.press(index)


def status(designer: DesignerApp) -> str:
    return str(designer.shell._status.cget("text"))


# ---------------------------------------------------------------- UAT 4: save, close, reopen
@pytest.mark.gui
def test_save_as_close_and_reopen_from_recent_is_byte_identical(
    app: DesignerApp, hello: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert app.open_path(hello)
    assert app.root.title() == "hello.ui — PyGUIbud"
    edit(app)
    assert app.root.title() == "hello.ui* — PyGUIbud"
    target = tmp_path / "out" / "uat.ui"
    target.parent.mkdir()
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(target))
    app.registry.invoke("file.save_as")
    saved = target.read_bytes()
    assert saved == dump_ui(app.session.document)  # type: ignore[arg-type]
    assert not app.session.dirty and app.session.path == target
    assert app.root.title() == "uat.ui — PyGUIbud"
    assert status(app) == "Saved 'uat.ui'."
    assert app.recent.entries[0] == str(target)
    app.registry.invoke("file.close")
    assert app.session.document is None
    assert app.root.title() == "PyGUIbud designer"
    app.open_recent(str(target))
    assert app.session.path == target
    assert dump_ui(app.session.document) == saved  # type: ignore[arg-type]
    assert target.read_bytes() == saved
    # The settings file got the recent list, and the File menu lists it with a mnemonic.
    stored = json.loads(settings_path().read_text(encoding="utf-8"))
    assert stored["recent_files"][0] == str(target)
    menu = app.shell.submenus["file.recent"]
    assert menu.entrycget(0, "label") == f"1 {target}"


@pytest.mark.gui
def test_save_of_an_untitled_document_asks_for_a_file(
    app: DesignerApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.start()  # the start-up template, untitled
    asked: list[str] = []

    def ask_save(_root: object, name: str, _folder: str | None) -> str:
        asked.append(name)
        return str(tmp_path / "new.ui")

    monkeypatch.setattr(file_dialogs, "ask_save", ask_save)
    app.registry.invoke("file.save")
    assert asked == ["Untitled.ui"]
    assert (tmp_path / "new.ui").is_file() and app.session.path == tmp_path / "new.ui"


@pytest.mark.gui
def test_cancelled_save_as_and_cancelled_open_change_nothing(
    app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.open_path(hello)
    edit(app)
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: None)
    monkeypatch.setattr(file_dialogs, "ask_open", lambda *_a: None)
    app.registry.invoke("file.save_as")
    app.registry.invoke("file.open")  # the picker comes first: no save question
    assert app.session.dirty and not app._live_dialogs()


@pytest.mark.gui
def test_conflict_offers_overwrite(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    edit(app)
    hello.write_bytes(hello.read_bytes() + b"\n<!-- another program -->\n")
    app.save()
    box = dialog(app)
    assert "was changed by another program" in str(box.label.cget("text"))
    answer(app, 0)  # Overwrite
    assert not app.session.dirty
    assert b"another program" not in hello.read_bytes()


@pytest.mark.gui
def test_a_failed_write_keeps_the_document_dirty(
    app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.open_path(hello)
    edit(app)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise XmlIoError("xml.write_failed", "Disk full.")

    monkeypatch.setattr(app_module, "write_ui", refuse)
    app.save()
    assert "Disk full." in str(dialog(app).label.cget("text"))
    answer(app, 0)
    assert app.session.dirty


@pytest.mark.gui
def test_missing_recent_file_is_reported_and_dropped(app: DesignerApp, tmp_path: Path) -> None:
    gone = tmp_path / "gone.ui"
    app.recent.add(gone)
    app.open_recent(str(gone))
    assert "does not exist" in str(dialog(app).label.cget("text"))
    answer(app, 0)
    assert str(gone) not in app.recent.entries


@pytest.mark.gui
def test_a_bad_file_shows_why_and_keeps_the_document(app: DesignerApp, tmp_path: Path) -> None:
    app.start()
    before = app.session.document
    bad = tmp_path / "bad.ui"
    bad.write_text("not xml", encoding="utf-8")
    assert not app.open_path(bad)
    assert isinstance(dialog(app), ChoiceDialog)
    answer(app, 0)
    assert app.session.document is before


# ---------------------------------------------------------------- UAT 5: the guard
@pytest.mark.gui
def test_quit_guard_cancel_dont_save_and_save(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    edit(app)
    app.registry.invoke("file.quit")
    assert "Save the changes to 'hello.ui'" in str(dialog(app).label.cget("text"))
    answer(app, 2)  # Cancel
    assert app.exits == [] and app.session.dirty  # type: ignore[attr-defined]
    app.quit()
    answer(app, 1)  # Don't save
    assert app.exits == [True]  # type: ignore[attr-defined]
    assert app.session.dirty  # nothing was written
    original = hello.read_bytes()
    app.quit()
    answer(app, 0)  # Save
    assert app.exits == [True, True]  # type: ignore[attr-defined]
    assert hello.read_bytes() != original and not app.session.dirty


@pytest.mark.gui
def test_guard_runs_on_new_open_and_close(
    app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.open_path(hello)
    edit(app)
    monkeypatch.setattr(file_dialogs, "ask_open", lambda *_a: str(hello))
    for action in ("file.new", "file.open", "file.close"):
        app.registry.invoke(action)
        assert "Save the changes" in str(dialog(app).label.cget("text")), action
        answer(app, 2)
        assert app.session.dirty
    app.registry.invoke("file.close")
    answer(app, 1)  # Don't save
    assert app.session.document is None


@pytest.mark.gui
def test_a_refused_flush_aborts_the_guard(
    app: DesignerApp, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.open_path(hello)
    monkeypatch.setattr(app.shell, "flush", lambda: False)  # invalid pending text (A15)
    app.quit()
    assert app.exits == [] and not app._live_dialogs()  # type: ignore[attr-defined]


@pytest.mark.gui
def test_variables_flush_commits_a_typed_default(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    panel = app.shell.variables
    panel.add()
    panel._render()
    tree = panel.tree
    assert tree is not None
    var_id = tree.get_children()[-1]
    tree.selection_set(var_id)
    panel._load_row()
    panel.default_var.set("typed, not committed")
    assert app.shell.flush()
    assert app.session.document is not None
    assert app.session.document.variables[var_id].default == "typed, not committed"


@pytest.mark.gui
def test_inspector_dialogs_go_through_the_app(app: DesignerApp) -> None:
    from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog

    app.open_shortcuts()
    second = ShortcutsDialog(app.root, app.registry)
    app.shell.inspector.open_dialog(second)
    assert second.closed  # one modal at a time: the refused dialog is destroyed
    assert len(app._live_dialogs()) == 1
    assert app.shell.variables.confirm == app._confirm


# ---------------------------------------------------------------- UAT 6: recovery
_CRASH = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from pyguibud.core import Widget, default_registry, read_ui
    from pyguibud.core.commands import SetProp
    from pyguibud.core.model import Prop
    from pyguibud.designer.recovery import RecoverySession
    from pyguibud.designer.session import DesignerSession

    path = Path(sys.argv[1])
    session = DesignerSession(default_registry())
    session.recovery = RecoverySession()
    session.recovery.start()
    session.open_document(read_ui(path), path=path)
    label = next(n for n in session.document.walk()
                 if isinstance(n, Widget) and n.class_name == "Label")
    session.stack.execute(SetProp(label, Prop(name="text", value="Recovered edit")))
    session.recovery.autosave(session)
    print("ready", flush=True)
    time.sleep(120)
    """
)


@pytest.mark.gui
def test_restore_after_a_killed_process(app: DesignerApp, hello: Path) -> None:
    child = subprocess.Popen(
        [sys.executable, "-c", _CRASH, str(hello)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready", child.stderr
    finally:
        child.kill()  # this PID only: the crash
        child.wait(timeout=30)
    # Windows releases a killed process's file lock "after a time that depends on available
    # system resources" (LockFileEx): until then the snapshot is rightly seen as alive.
    deadline = time.monotonic() + 10
    while not RecoverySession().scan_orphans() and time.monotonic() < deadline:
        time.sleep(0.05)
    app.start()
    box = dialog(app)
    assert isinstance(box, RecoveryDialog)
    box.restore()
    assert app.session.dirty and app.session.path == hello
    assert app.root.title() == "hello.ui* — PyGUIbud"
    assert b"Recovered edit" in dump_ui(app.session.document)  # type: ignore[arg-type]
    assert app.recovery is not None
    assert app.recovery.scan_orphans() == []  # adopted into this session


@pytest.mark.gui
def test_damaged_snapshot_is_marked_and_later_opens_the_start_document(
    app: DesignerApp,
) -> None:
    folder = state_dir() / "recovery" / ("a" * 32)
    folder.mkdir(parents=True)
    (folder / "owner.lock").touch()  # a dead process's folder: lockable
    (folder / "document.ui").write_text("<truncated", encoding="utf-8")
    app.start()
    box = dialog(app)
    box.restore()
    assert not box.closed and box.tree.set(box._current(), "time") == "damaged"
    assert "disabled" in box.buttons[0][0].state()
    box.discard()
    confirm = dialog(app)
    assert isinstance(confirm, ConfirmDialog)
    confirm.confirm()
    assert box.closed and not folder.exists()
    assert app.session.document is not None  # "later": the start-up template opened


@pytest.mark.gui
def test_ctrl_c_with_a_dirty_document_keeps_a_snapshot(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    edit(app)
    app.shutdown(interrupted=True)
    orphans = RecoverySession().scan_orphans()
    assert [entry.name for entry in orphans] == ["hello.ui"]
    orphans[0].discard()


@pytest.mark.gui
def test_autosave_tick_writes_a_snapshot(app: DesignerApp, hello: Path) -> None:
    app.open_path(hello)
    edit(app)
    app.autosave()
    assert app.recovery is not None and app.recovery.folder is not None
    assert (app.recovery.folder / "document.ui").is_file()
    assert app._autosave_id is not None  # rescheduled


@pytest.fixture
def shown(designer_root: Any) -> Iterator[Any]:
    """The root mapped: a withdrawn window never takes the keyboard focus."""
    designer_root.deiconify()
    designer_root.update()
    yield designer_root
    designer_root.withdraw()


def _focus(root: Any, widget: Any) -> None:
    widget.focus_force()
    root.update()


@pytest.mark.gui
def test_autosave_never_flushes_the_editor_being_typed_in(
    app: DesignerApp, hello: Path, shown: Any
) -> None:
    """Regression: the autosave tick flushed the inspector and the Variables panel, so a
    half-typed number turned red and a half-typed variable id was renamed."""
    app.open_path(hello)
    edit(app)
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    notebook = document.find("nbk_main")
    assert isinstance(notebook, Widget)
    app.session.select(notebook, origin="tree")
    shown.update()
    editor = app.shell.inspector._editors["prop:width"]
    _focus(shown, editor.widget)
    editor.var.set("-")  # half-typed: not a number yet
    assert app.shell.typing() and editor.pending()
    count = stack.index
    app.autosave()
    assert editor.pending() and editor.widget.cget("style") == editor.widget.winfo_class()
    assert stack.index == count and "width" not in notebook.props
    assert app.recovery is not None and app.recovery.folder is not None
    assert (app.recovery.folder / "document.ui").is_file()  # the committed document
    editor.revert()

    panel = app.shell.variables
    app.shell.side.select(panel.frame)
    panel._render()
    assert panel.tree is not None
    panel.tree.selection_set("user_name")
    panel._load_row()
    _focus(shown, panel.id_entry)
    panel.id_var.set("user_na")  # half-typed id
    assert app.shell.typing()
    app.autosave()
    assert set(document.variables) == {"user_name"}
    assert document.find("ent_name").bind == "user_name"  # type: ignore[union-attr]

    _focus(shown, app.shell.canvas.notebook)  # the focus left the editors: a tick flushes
    assert not app.shell.typing()
    app.autosave()
    assert set(document.variables) == {"user_na"}


# ---------------------------------------------------------------- UAT 7: settings
@pytest.mark.gui
def test_settings_round_trip(app: DesignerApp) -> None:
    app.start()
    app.registry.invoke("view.language.de_DE")
    app.registry.invoke("view.theme.dark")
    app.flush_theme()
    app.registry.invoke("view.language.en_GB")
    app.quit()
    assert app.exits == [True]  # type: ignore[attr-defined]
    stored, problem = load_settings()
    assert problem is None
    assert stored.language == "en_GB" and stored.theme == "dark"
    assert set(stored.sashes) == {"main", "right"}
    assert len(stored.sashes["main"]) == 2


@pytest.mark.gui
def test_cli_language_is_never_stored(app: DesignerApp) -> None:
    from pyguibud import i18n

    i18n.set_language("de_DE")  # as ``--lang de_DE`` would
    app.quit()
    assert load_settings()[0].language is None


@pytest.mark.gui
def test_stored_sashes_are_restored_then_clamped(
    designer_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(sashes={"main": (180, 900, 5000), "right": (300,)})
    designer = DesignerApp(designer_root, settings=settings)
    moved: list[tuple[str, int, int]] = []
    clamped: list[bool] = []
    try:
        for key, paned in (("main", designer.shell.body), ("right", designer.shell.right)):
            monkeypatch.setattr(paned, "sashpos", lambda i, p=None, k=key: moved.append((k, i, p)))
        monkeypatch.setattr(designer.shell, "clamp_sashes", lambda: clamped.append(True))
        designer._apply_sashes()
        assert moved == [("main", 0, 180), ("main", 1, 900), ("right", 0, 300)]  # extra dropped
        assert clamped == [True]
    finally:
        designer.dispose()


@pytest.mark.gui
def test_corrupt_settings_start_with_defaults_and_say_so(app: DesignerApp) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x00garbage{")
    settings, problem = load_settings()
    assert settings == Settings() and problem == M_SETTINGS_RESET
    assert path.with_name("settings.json.corrupt").is_file()
    app.start(notice=problem)
    assert status(app) == "Your settings could not be read and were reset."


@pytest.mark.gui
def test_cli_file_opens_at_start(app: DesignerApp, hello: Path) -> None:
    app.start(hello)
    assert app.session.path == hello
    assert app.session.selection.node is app.session.document.children[0]  # type: ignore[union-attr]


@pytest.mark.gui
def test_teardown_with_the_recovery_list_open_opens_nothing(app: DesignerApp) -> None:
    folder = state_dir() / "recovery" / ("b" * 32)
    folder.mkdir(parents=True)
    (folder / "owner.lock").touch()
    (folder / "document.ui").write_text("<truncated", encoding="utf-8")
    app.start()
    assert isinstance(dialog(app), RecoveryDialog)
    app.dispose()  # the window's X or Ctrl+C while the list is open
    assert app.session.document is None
