"""File > Export in the Tk designer: Ctrl+E, the dialog and "Run the module after export" with
a fake process (spec preview-export 9 "Tk designer")."""

from __future__ import annotations

import shutil
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.core.commands import SetField
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.export import ExportDialog
from pyguibud.designer.dialogs.message import ChoiceDialog
from pyguibud.designer.files import open_document, path_key
from tests.designer.fakes import FakeProcess

pytestmark = pytest.mark.gui

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _open(app: DesignerApp, path: Path) -> None:
    opened = open_document(path)
    app.session.open_document(opened.result, path=opened.path, stamp=opened.stamp)


@pytest.fixture
def app(shell: DesignerApp, tmp_path: Path) -> Iterator[DesignerApp]:
    shutil.copytree(EXAMPLES / "locale", tmp_path / "doc" / "locale")
    shutil.copy(EXAMPLES / "hello.ui", tmp_path / "doc")
    _open(shell, tmp_path / "doc" / "hello.ui")
    yield shell
    for dialog in shell._live_dialogs():
        dialog.close()
    shell.exporter.dispose()


@pytest.fixture
def runs(app: DesignerApp) -> list[FakeProcess]:
    started: list[FakeProcess] = []

    def popen(argv: list[str], *, cwd: Path, **_options: Any) -> FakeProcess:
        started.append(FakeProcess(argv, Path(cwd)))
        return started[-1]

    app.exporter.runner.popen = popen
    return started


def _dialog(app: DesignerApp) -> ExportDialog:
    app.exporter.start()
    dialog = app._live_dialogs()[-1]
    assert isinstance(dialog, ExportDialog)
    dialog.window.update()  # mapped: the focus traversal skips unmapped widgets
    return dialog


def _dirty(app: DesignerApp) -> bool:
    return app.session.dirty


def test_ctrl_e_menu_toolbar_and_enabled_state(app: DesignerApp) -> None:
    action = app.registry.get("file.export")
    assert action is not None
    assert (action.shortcut, action.icon, action.toolbar) == ("Ctrl+E", "export", True)
    assert app.registry.is_enabled(action)
    rows = {row.label: row.accelerator for row in app.registry.cheat_sheet()}
    assert rows["Export Python code…"] == "Ctrl+E"
    app.session.close_document()
    assert not app.registry.is_enabled(action)


def test_dialog_rows_tab_order_enter_and_escape(app: DesignerApp) -> None:
    dialog = _dialog(app)
    assert dialog.output.get() == str(app.session.path.parent / "hello_ui.py")  # type: ignore[union-attr]
    assert not dialog.allow_check.winfo_manager()  # no outside paths: no check box
    assert str(dialog.pot_entry.cget("state")) == "disabled"
    order: list[Any] = []
    widget: Any = dialog.output_entry
    for _step in range(6):
        order.append(widget)
        widget = widget.tk_focusNext()
    expected = [dialog.output_entry, dialog.output_browse, dialog.pot_check, dialog.run_check,
                dialog.export_button, dialog.cancel_button]  # fmt: skip
    assert order == expected and widget is dialog.output_entry
    dialog.window.event_generate("<Escape>")
    assert dialog.closed and not (app.session.path.parent / "hello_ui.py").exists()  # type: ignore[union-attr]
    dialog = _dialog(app)
    dialog.want_pot.set(True)
    dialog._pot_state()
    dialog.output_entry.event_generate("<Return>")
    out = app.session.path.parent / "hello_ui.py"  # type: ignore[union-attr]
    assert dialog.closed and out.is_file() and (out.parent / "locale" / "hello.pot").is_file()
    assert app.shell._message.startswith(f"Exported {out} and ")
    assert app.settings.exports[path_key(app.session.path)] == str(out)  # type: ignore[arg-type]


def test_a_refusal_keeps_the_dialog_open_with_the_reason(app: DesignerApp) -> None:
    dialog = _dialog(app)
    dialog.output.set("tkinter.py")
    dialog.accept()
    assert not dialog.closed and dialog.message.winfo_manager()
    assert "tkinter" in str(dialog.message.cget("text"))


def test_the_outside_check_box_appears_only_when_needed(app: DesignerApp, tmp_path: Path) -> None:
    (tmp_path / "logo.ppm").write_bytes(b"P6 1 1 255\n\x00\x00\x00")
    path = tmp_path / "doc" / "hello.ui"
    text = path.read_text(encoding="utf-8")
    text = text.replace("<window ", '<resources><image id="logo" src="../logo.ppm"/></resources>'
                        "<window ", 1)  # fmt: skip
    path.write_text(text, encoding="utf-8")
    _open(app, path)
    dialog = _dialog(app)
    assert dialog.allow_check.winfo_manager() and "../logo.ppm" in str(dialog.paths.cget("text"))
    dialog.accept()
    assert not dialog.closed and "Allow images" in str(dialog.message.cget("text"))
    dialog.allow.set(True)
    dialog.accept()
    assert dialog.closed


def test_a_dirty_document_asks_save_and_export(app: DesignerApp) -> None:
    document, stack = app.session.document, app.session.stack
    assert document is not None and stack is not None
    stack.execute(SetField(document.meta, "theme", "darkly"))
    assert app.session.dirty
    app.exporter.start()
    prompt = app._live_dialogs()[-1]
    assert isinstance(prompt, ChoiceDialog)
    assert [m for _b, m, _a in prompt.buttons] == ["_Save and export", "_Cancel"]
    prompt.press(0)  # saves, then the export dialog opens
    assert not _dirty(app)
    assert isinstance(app._live_dialogs()[-1], ExportDialog)


@pytest.mark.parametrize(("lang", "passed"), [("de_DE", ["--lang", "de_DE"]), ("en_XA", [])])
def test_run_after_export_runs_the_written_module_in_its_folder(
    app: DesignerApp, runs: list[FakeProcess], lang: str, passed: list[str]
) -> None:
    app.settings.preview_lang = lang
    dialog = _dialog(app)
    dialog.run_after.set(True)
    dialog.accept()
    out = app.session.path.parent / "hello_ui.py"  # type: ignore[union-attr]
    assert [r.argv for r in runs] == [[sys.executable, str(out), *passed]]
    assert runs[0].cwd == out.parent
    assert ("pseudo-locale" in app.shell._message) is (lang == "en_XA")
    private = app.exporter.runner.folder
    assert private is not None and private != out.parent
    runs[0].code = 0
    app.exporter.runner._poll()
    assert out.is_file() and out.parent.is_dir() and not private.exists()  # never the user's


def test_a_file_changed_before_the_run_is_not_run(
    app: DesignerApp, runs: list[FakeProcess], monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer import export as ex

    monkeypatch.setattr(ex, "intact", lambda _o, _t: False)
    dialog = _dialog(app)
    dialog.run_after.set(True)
    dialog.accept()
    assert runs == [] and "was not run" in app.shell._message


def test_enter_on_cancel_cancels(app: DesignerApp) -> None:
    dialog = _dialog(app)
    dialog._on_return(SimpleNamespace(widget=dialog.cancel_button))
    assert dialog.closed and not (app.session.path.parent / "hello_ui.py").exists()  # type: ignore[union-attr]


def test_a_failed_save_does_not_export(app: DesignerApp, monkeypatch: pytest.MonkeyPatch) -> None:
    from pyguibud.core import XmlIoError
    from pyguibud.designer import app as app_module

    def fail(*_args: object, **_kwargs: object) -> None:
        raise XmlIoError("xml.write_failed", "disk full")

    monkeypatch.setattr(app_module, "write_ui", fail)
    app.session.stack.execute(SetField(app.session.document.meta, "theme", "darkly"))  # type: ignore[union-attr]
    app.exporter.start()
    prompt = app._live_dialogs()[-1]
    assert isinstance(prompt, ChoiceDialog)
    prompt.press(0)
    assert _dirty(app)
    assert not any(isinstance(d, ExportDialog) for d in app._live_dialogs())


def test_ctrl_e_in_a_text_field_is_not_swallowed_on_win32(app: DesignerApp) -> None:
    """Observed on win32 (a mapped designer, a focused ttk.Entry): Ctrl+E opens the dialog and
    the text and cursor stay. Checked here without OS focus: no Entry class binding takes the
    chord, and the application-wide binding exists (the cheat sheet notes other systems)."""
    root = app.root
    assert root.bind_all("<Control-Key-e>")
    if sys.platform == "win32":
        for name in ("TEntry", "Entry", "Text"):
            assert not root.bind_class(name, "<Control-Key-e>"), name
        assert "<Control-Key-e>" not in str(root.event_info("<<LineEnd>>"))
