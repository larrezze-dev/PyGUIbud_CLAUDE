"""``CommandStack(dirty=True)``: a restored recovery snapshot opens unsaved (spec 11.4)."""

from __future__ import annotations

from pyguibud.core import CommandStack, Widget, default_registry, read_ui_string
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop

UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Label" id="lbl_a"><cell row="0" column="0"/></widget>
  </window>
</pyguibud-ui>
"""


def _stack(*, dirty: bool) -> tuple[CommandStack, Widget]:
    document = read_ui_string(UI).document
    label = next(n for n in document.walk() if isinstance(n, Widget))
    return CommandStack(document, default_registry(), dirty=dirty), label


def dirty(stack: CommandStack) -> bool:
    """Through a call, so mypy does not narrow the property across mutations."""
    return stack.is_dirty


def test_default_stack_starts_clean() -> None:
    stack, _label = _stack(dirty=False)
    assert not dirty(stack)


def test_dirty_stack_stays_dirty_until_saved() -> None:
    stack, label = _stack(dirty=True)
    assert dirty(stack)
    assert stack.execute(SetProp(label, Prop(name="text", value="Hi"))).accepted
    assert stack.undo()
    assert stack.index == 0
    assert dirty(stack)  # index 0 is not the saved state
    stack.mark_saved()
    assert not dirty(stack)
    stack.clear()
    assert not dirty(stack)


def test_dirty_stack_clear_keeps_dirty() -> None:
    stack, _label = _stack(dirty=True)
    stack.clear()
    assert dirty(stack)
