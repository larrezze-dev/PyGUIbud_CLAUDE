"""ActionRegistry (pure): validation, ordering, invocation and the cheat-sheet."""

from __future__ import annotations

import pytest

from pyguibud import i18n
from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef, Separator, label_of


def _noop() -> None:
    return None


@pytest.fixture
def registry() -> ActionRegistry:
    reg = ActionRegistry()
    reg.add_menu(MenuDef("file", "_File"))
    reg.add_menu(MenuDef("view", "_View"))
    reg.add_menu(MenuDef("theme", "_Theme", parent="view"))
    return reg


def test_menu_items_keep_registration_order(registry: ActionRegistry) -> None:
    new = ActionDef("file.new", "file", "_New", _noop, shortcut="Ctrl+N")
    quit_ = ActionDef("file.quit", "file", "_Quit", _noop, shortcut="Ctrl+Q")
    registry.add(new)
    registry.add_separator("file")
    registry.add(quit_)
    items = registry.menu_items("file")
    assert items[0] is new and isinstance(items[1], Separator) and items[2] is quit_


def test_submenu_is_listed_in_its_parent(registry: ActionRegistry) -> None:
    registry.add(ActionDef("view.panel", "view", "Next _panel", _noop))
    items = registry.menu_items("view")
    assert items[0] == MenuDef("theme", "_Theme", parent="view")
    assert [type(item) for item in items] == [MenuDef, ActionDef]


def test_duplicate_id_is_refused(registry: ActionRegistry) -> None:
    registry.add(ActionDef("a", "file", "A", _noop))
    with pytest.raises(ValueError, match="duplicate action"):
        registry.add(ActionDef("a", "file", "B", _noop))


def test_unknown_menu_is_refused(registry: ActionRegistry) -> None:
    with pytest.raises(ValueError, match="unknown menu"):
        registry.add(ActionDef("a", "nowhere", "A", _noop))


def test_duplicate_and_unknown_menu_definitions_are_refused(registry: ActionRegistry) -> None:
    with pytest.raises(ValueError, match="duplicate menu"):
        registry.add_menu(MenuDef("file", "_File"))
    with pytest.raises(ValueError, match="unknown parent"):
        registry.add_menu(MenuDef("x", "X", parent="nowhere"))


@pytest.mark.parametrize("chord", ["", "Ctrl+", "Ctrl+Nope+N", "Hyper+X", "Ctrl + N"])
def test_bad_chord_is_refused(registry: ActionRegistry, chord: str) -> None:
    with pytest.raises(ValueError, match="bad shortcut"):
        registry.add(ActionDef("a", "file", "A", _noop, shortcut=chord))


def test_duplicate_chord_is_refused_even_when_spelled_differently(
    registry: ActionRegistry,
) -> None:
    registry.add(ActionDef("a", "file", "A", _noop, shortcut="Ctrl+N"))
    with pytest.raises(ValueError, match="is used by"):
        registry.add(ActionDef("b", "file", "B", _noop, shortcut="ctrl+n"))
    assert registry.get("b") is None  # nothing half-registered


def test_invoke_runs_handler_and_reports_state(registry: ActionRegistry) -> None:
    calls: list[str] = []
    registry.add(ActionDef("a", "file", "A", lambda: calls.append("a")))
    registry.add(
        ActionDef("off", "file", "Off", lambda: calls.append("off"), enabled=lambda: False)
    )
    assert registry.invoke("a") is True
    assert registry.invoke("off") is False
    assert registry.invoke("missing") is False
    assert calls == ["a"]


def test_invoke_isolates_a_failing_handler(
    registry: ActionRegistry, caplog: pytest.LogCaptureFixture
) -> None:
    def boom() -> None:
        raise RuntimeError("kaput")

    registry.add(ActionDef("a", "file", "A", boom))
    messages: list[str] = []
    registry.message.connect(messages.append)
    assert registry.invoke("a") is True
    assert messages and "kaput" in messages[0]
    assert "kaput" in caplog.text


def test_failing_enabled_predicate_counts_as_disabled(registry: ActionRegistry) -> None:
    def bad() -> bool:
        raise RuntimeError("no")

    registry.add(ActionDef("a", "file", "A", _noop, enabled=bad))
    assert registry.invoke("a") is False


def test_cheat_sheet_lists_only_shortcut_actions(registry: ActionRegistry) -> None:
    registry.add(ActionDef("file.new", "file", "_New from template...", _noop, shortcut="Ctrl+N"))
    registry.add(ActionDef("file.plain", "file", "_Plain", _noop))
    registry.add(ActionDef("help.keys", "file", "_Keyboard shortcuts", _noop, shortcut="F1"))
    rows = registry.cheat_sheet()
    assert [(r.menu, r.label, r.accelerator) for r in rows] == [
        ("File", "New from template...", "Ctrl+N"),
        ("File", "Keyboard shortcuts", "F1"),
    ]


def test_cheat_sheet_follows_the_language(registry: ActionRegistry) -> None:
    registry.add(ActionDef("file.new", "file", "_New", _noop, shortcut="Ctrl+N"))
    i18n.set_language("en_XA")
    row = registry.cheat_sheet()[0]
    assert row.menu.startswith("[") and row.label.startswith("[")
    assert "_" not in row.menu + row.label  # mnemonic marks are stripped


def test_literal_labels_are_not_translated(registry: ActionRegistry) -> None:
    action = ActionDef("lang.de", "file", "Deutsch (Deutschland)", _noop, translate=False)
    i18n.set_language("en_XA")
    assert label_of(action) == "Deutsch (Deutschland)"


def test_context_labels_use_pgettext(registry: ActionRegistry) -> None:
    action = ActionDef("a", "file", "_Open", _noop, context="verb")
    i18n.set_language("en_XA")
    assert label_of(action).startswith("[")


def test_checked_predicate_is_kept_for_radio_items(registry: ActionRegistry) -> None:
    state = {"on": True}
    action = ActionDef("a", "file", "A", _noop, checked=lambda: state["on"])
    registry.add(action)
    assert action.checked is not None and action.checked() is True
    state["on"] = False
    assert action.checked() is False
