"""Panel cycling, the focus-within ring, the cheat-sheet and the new-file wizard (shared root)."""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core.keys import split_mnemonic
from pyguibud.designer.actions import label_of
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs.new_file import NewFileDialog
from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
from pyguibud.designer.present.focus import cycle
from pyguibud.designer.present.new_file import step_index, template_rows
from pyguibud.designer.templates import TEMPLATES


def test_cycle_wraps_in_both_directions() -> None:
    assert [cycle(i, 1, 4) for i in range(4)] == [1, 2, 3, 0]
    assert [cycle(i, -1, 4) for i in range(4)] == [3, 0, 1, 2]
    assert cycle(-1, 1, 4) == 0
    assert cycle(-1, -1, 4) == 3
    assert cycle(0, 1, 0) == -1


def test_step_index_clamps_and_handles_empty() -> None:
    assert step_index(0, -1, 5) == 0
    assert step_index(4, 1, 5) == 4
    assert step_index(1, 1, 5) == 2
    assert step_index(0, 1, 0) == -1


def test_template_rows_follow_the_language() -> None:
    assert [r.id for r in template_rows()] == [t.id for t in TEMPLATES]
    i18n.set_language("en_XA")
    assert all(r.title.startswith("[") for r in template_rows())


@pytest.mark.gui
class TestPanelFocus:
    def test_f6_and_shift_f6_cycle_the_four_panels(self, shell: DesignerApp) -> None:
        shell.session.new_from_template("main_window")
        panels = shell.shell
        seen = []
        for _ in range(5):
            shell.registry.invoke("view.next_panel")
            seen.append(panels.active_panel)
        assert seen == [0, 1, 2, 3, 0]  # palette, canvas, tree, inspector, wrap
        shell.registry.invoke("view.previous_panel")
        assert panels.active_panel == 3
        shell.registry.invoke("view.previous_panel")
        assert panels.active_panel == 2

    def test_only_the_active_panel_has_the_focus_colour(self, shell: DesignerApp) -> None:
        panels = shell.shell
        spec = next(s for s in shell.specs if s.role == "light")
        panels.cycle_focus(1)
        panels.cycle_focus(1)
        frames = [p.frame for p in panels.panels]
        assert str(frames[1].cget("highlightcolor")) == spec.focus
        for other in (f for f in frames if f is not frames[1]):
            assert str(other.cget("highlightcolor")) == spec.colors["bg"]
        assert int(frames[1].cget("highlightthickness")) >= 2

    def test_focus_in_marks_the_containing_panel(self, shell: DesignerApp) -> None:
        panels = shell.shell
        tree = panels.tree.tree
        assert tree is not None
        panels._on_focus_in(type("E", (), {"widget": tree})())
        assert panels.active_panel == 2
        panels._on_focus_in(type("E", (), {"widget": panels.toolbar})())
        assert panels.active_panel == -1  # focus left every panel: no ring

    def test_f6_keys_are_bound_and_move_the_focus(
        self, shell: DesignerApp, designer_root: Any
    ) -> None:
        """Delivery of real key events needs OS focus (flaky in a test run): test the binding."""
        for sequence in ("<F6>", "<Shift-F6>", "<F1>"):
            assert designer_root.bind_all(sequence), sequence
        panels = shell.shell
        widget = panels.palette.tree
        assert widget is not None
        event = type("E", (), {"widget": widget})()
        handler = panels._key_handler("view.next_panel")
        assert handler(event) == "break"
        assert panels.active_panel == 0
        assert panels._key_handler("view.previous_panel")(event) == "break"
        assert panels.active_panel == 3

    def test_every_panel_has_a_focusable_widget(self, shell: DesignerApp) -> None:
        for panel in shell.shell.panels:
            classes = {w.winfo_class() for w in panel.frame.winfo_children()}
            assert classes & {"Treeview", "TNotebook"}, panel.name
            assert str(panel.frame.cget("takefocus")) in {"0", "False"}

    def test_every_action_has_a_mnemonic(self, shell: DesignerApp) -> None:
        for action in shell.registry.actions():
            if action.translate and action.checked is None:  # radio items need no key
                assert split_mnemonic(label_of(action))[1] >= 0, action.id


@pytest.mark.gui
class TestShortcutsDialog:
    def test_lists_every_shortcut_from_the_registry(self, shell: DesignerApp) -> None:
        shell.open_shortcuts()
        dialog = shell._live_dialogs()[0]
        assert isinstance(dialog, ShortcutsDialog)
        texts = [w.cget("text") for w in dialog.rows.winfo_children()]
        for accelerator in ("Ctrl+N", "Ctrl+Q", "F6", "Shift+F6", "F1"):
            assert accelerator in texts
        assert "Keyboard shortcuts…" in texts
        assert "File" in texts
        assert "View" in texts
        dialog.close()

    def test_escape_closes_and_a_second_open_reuses_it(self, shell: DesignerApp) -> None:
        shell.open_shortcuts()
        shell.open_shortcuts()
        assert len(shell._live_dialogs()) == 1
        dialog = shell._live_dialogs()[0]
        dialog.window.event_generate("<Escape>")
        dialog.window.update()
        assert dialog.closed
        assert shell._live_dialogs() == []

    def test_retranslates_and_sizes_to_content(self, shell: DesignerApp) -> None:
        shell.open_shortcuts()
        dialog: Any = shell._live_dialogs()[0]
        narrow = dialog.window.winfo_reqwidth()
        shell.set_language("en_XA")
        texts = [w.cget("text") for w in dialog.rows.winfo_children()]
        assert any(str(t).startswith("[") for t in texts)
        assert dialog.window.winfo_reqwidth() >= narrow
        assert str(dialog.window.title()).startswith("[")
        dialog.close()

    def test_dispose_closes_open_dialogs(self, designer_root: Any) -> None:
        app = DesignerApp(designer_root)
        app.open_shortcuts()
        dialog = app._live_dialogs()[0]
        app.dispose()
        assert dialog.closed


@pytest.mark.gui
class TestNewFileWizard:
    def _open(self, shell: DesignerApp) -> NewFileDialog:
        shell.registry.invoke("file.new")
        dialog = shell._live_dialogs()[0]
        assert isinstance(dialog, NewFileDialog)
        return dialog

    def test_lists_the_five_templates_with_descriptions(self, shell: DesignerApp) -> None:
        dialog = self._open(shell)
        assert list(dialog.list.get_children()) == [t.id for t in TEMPLATES]
        assert dialog.selected_id() == "main_window"
        assert dialog.description.cget("text")
        dialog.close()

    def test_selection_updates_the_description(self, shell: DesignerApp) -> None:
        dialog = self._open(shell)
        first = dialog.description.cget("text")
        dialog.select("login_form")
        assert dialog.description.cget("text") != first
        dialog.close()

    @pytest.mark.parametrize("template_id", [t.id for t in TEMPLATES])
    def test_enter_replaces_the_document(self, shell: DesignerApp, template_id: str) -> None:
        dialog = self._open(shell)
        dialog.select(template_id)
        dialog.window.event_generate("<Return>")
        dialog.window.update()
        assert dialog.closed
        window = shell.session.document.children[0]  # type: ignore[union-attr]
        assert shell.session.selection.node is window
        assert shell.session.report().ok

    def test_escape_cancels_and_changes_nothing(self, shell: DesignerApp) -> None:
        shell.new_from_template("login_form")
        before = shell.session.document
        dialog = self._open(shell)
        dialog.select("dialog")
        dialog.window.event_generate("<Escape>")
        dialog.window.update()
        assert dialog.closed
        assert shell.session.document is before

    def test_down_arrow_moves_the_highlight(self, shell: DesignerApp, designer_root: Any) -> None:
        dialog = self._open(shell)
        dialog.list.focus_force()
        designer_root.update()
        dialog.list.event_generate("<Down>")
        designer_root.update()
        assert dialog.selected_id() == "dialog"
        dialog.close()

    def test_language_switch_keeps_the_selection_and_button_creates(
        self, shell: DesignerApp
    ) -> None:
        dialog = self._open(shell)
        dialog.select("settings")
        shell.set_language("en_XA")
        assert dialog.selected_id() == "settings"
        assert str(dialog.list.item("settings", "text")).startswith("[")
        dialog.create_button.invoke()
        assert dialog.closed

    def test_shortcuts_do_not_fire_through_a_dialog(self, shell: DesignerApp) -> None:
        dialog = self._open(shell)
        dialog.list.focus_force()
        dialog.window.update()
        dialog.list.event_generate("<Control-n>")
        dialog.window.update()
        assert len(shell._live_dialogs()) == 1
        dialog.close()

    def test_damaged_template_reports_in_the_status_bar(self, shell: DesignerApp) -> None:
        seen: list[str] = []
        shell.message.connect(seen.append)
        assert shell.new_from_template("nope") is False
        assert seen
        assert "nope" in seen[0]

    def test_toolbar_new_button_opens_the_wizard(self, shell: DesignerApp) -> None:
        shell.shell._buttons[0][0].invoke()
        dialogs = shell._live_dialogs()
        assert dialogs
        assert isinstance(dialogs[0], NewFileDialog)
        dialogs[0].close()
