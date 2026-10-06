"""Step 09 UAT demo: the validator and the guarded command stack, in plain text.

Run it with ``uv run python examples/validator_demo.py [--lang CODE]``. It edits ``hello.ui``
in memory only (nothing is saved), shows which edits are accepted and which are blocked (with
the translated reason), demonstrates undo/redo and the "unsaved changes" flag, and validates a
deliberately broken document.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pyguibud.cli import _language_arg
from pyguibud.core import (
    CommandStack,
    Document,
    Event,
    GridCell,
    PackPlacement,
    Prop,
    Widget,
    Window,
    default_registry,
    dump_ui,
    read_ui,
    read_ui_string,
    validate_read,
)
from pyguibud.core.commands import (
    DEFAULT_LAYOUT,
    Command,
    InsertNode,
    RemoveVariable,
    SetEvents,
    SetField,
    SetProp,
)
from pyguibud.i18n import SOURCE_LANGUAGE, _, ngettext, set_language

HELLO = Path(__file__).with_name("hello.ui")

#: A document with several different mistakes (and one harmless warning).
BROKEN_UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1">
  <variables>
    <var id="count" type="int"/>
  </variables>
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Button" id="btn_ok">
      <prop name="state">maybe</prop>
      <event name="command" handler="1abc"/>
      <cell row="0" column="0"/>
    </widget>
    <widget class="Label" id="btn_ok">
      <cell row="0" column="0"/>
    </widget>
    <widget class="Entry" id="class" bind="missing">
      <cell row="1" column="0"/>
    </widget>
    <widget class="Frame" id="frm_empty">
      <cell row="2" column="0"/>
    </widget>
    <widget class="Label" id="lbl_note">
      <prop name="colour">red</prop>
      <cell row="3" column="0"/>
    </widget>
  </window>
</pyguibud-ui>
"""


def _node(document: Document, node_id: str) -> Widget:
    node = document.find(node_id)
    if not isinstance(node, Widget):
        raise LookupError(node_id)
    return node


def blocked_scenarios(document: Document) -> list[tuple[str, Command]]:
    """The edits of section 2, each of which the guard must block (description, command)."""
    label = _node(document, "lbl_user")
    button = _node(document, "btn_greet")
    about = _node(document, "lbl_about")
    greeting = _node(document, "frm_greeting")
    notebook = _node(document, "nbk_main")
    return [
        (_("Rename '{old}' to '{new}'").format(old="lbl_user", new="class"),
         SetField(label, "id", "class")),
        (_("Rename '{old}' to '{new}'").format(old="lbl_user", new="btn_greet"),
         SetField(label, "id", "btn_greet")),
        (_("Rename '{old}' to '{new}'").format(old="lbl_user", new="_x"),
         SetField(label, "id", "_x")),
        (_("Put a label inside the label '{id}'").format(id="lbl_about"),
         InsertNode(about, Widget(class_name="Label", id="lbl_inner"))),
        (_("Add a widget with a pack placement to the grid frame '{id}'").format(
            id="frm_greeting"),
         InsertNode(greeting, Widget(class_name="Label", id="lbl_packed",
                                     placement=PackPlacement()))),
        (_("Add a label on top of '{id}' (row 0, column 0)").format(id="lbl_user"),
         InsertNode(greeting, Widget(class_name="Label", id="lbl_overlap",
                                     placement=GridCell(row=0, column=0)))),
        (_("Set the width of '{id}' to {value}").format(id="btn_greet", value="-5"),
         SetProp(button, Prop(name="width", value="-5"))),
        (_("Set the state of '{id}' to '{value}'").format(id="btn_greet", value="maybe"),
         SetProp(button, Prop(name="state", value="maybe"))),
        (_("Handle the event '{event}' on '{id}'").format(event="key:", id="btn_greet"),
         SetEvents(button, [Event(name="key:", handler="on_greet")])),
        (_("Use the handler '{handler}' on '{id}'").format(handler="1abc", id="btn_greet"),
         SetEvents(button, [Event(name="command", handler="1abc")])),
        (_("Add a check button bound to the text variable '{bind}'").format(bind="user_name"),
         InsertNode(greeting, Widget(class_name="Checkbutton", id="chk_remember",
                                     bind="user_name", placement=GridCell(row=2, column=1)))),
        (_("Give the notebook '{id}' a layout").format(id="nbk_main"),
         SetField(notebook, "layout", DEFAULT_LAYOUT)),
        (_("Add a second main window"),
         InsertNode(document, Window(id="win_second", kind="main", layout=DEFAULT_LAYOUT))),
        (_("Add an empty frame without a layout"),
         InsertNode(greeting, Widget(class_name="Frame", id="frm_empty",
                                     placement=GridCell(row=2, column=0)))),
        (_("Remove the variable '{id}', which '{widget}' uses").format(
            id="user_name", widget="ent_name"),
         RemoveVariable(document, "user_name")),
    ]  # fmt: skip


def _heading(number: int, title: str) -> None:
    print()
    print(f"{number}. {title}")


def _yes_no(value: bool) -> str:
    return _("yes") if value else _("no")


def _attempt(stack: CommandStack, description: str, command: Command) -> bool:
    outcome = stack.execute(command)
    if outcome.accepted:
        print(f"   {description}: " + _("OK"))
    else:
        print(f"   {description}: " + _("BLOCKED: {reason}").format(reason=outcome.message))
    return outcome.accepted


def _state(stack: CommandStack) -> None:
    print(
        "   "
        + _("Unsaved changes: {dirty} (undo steps: {depth})").format(
            dirty=_yes_no(stack.is_dirty), depth=stack.index
        )
    )


def _set_text(widget: Widget, text: str) -> SetProp:
    return SetProp(widget, Prop(name="text", value=text, translatable=True))


def main(argv: list[str] | None = None) -> int:
    """Run the demo; returns the exit code (0)."""
    parser = argparse.ArgumentParser(description=_("PyGUIbud validator and undo/redo demo"))
    parser.add_argument("--lang", type=_language_arg, default=SOURCE_LANGUAGE)
    args = parser.parse_args(argv)
    set_language(args.lang)

    document = read_ui(HELLO).document
    stack = CommandStack(document, default_registry(), source=HELLO.name)
    print(_("PyGUIbud validator demo - every edit is checked before it is kept."))

    _heading(1, _("Accepted edits"))
    _attempt(
        stack,
        _("Rename '{old}' to '{new}'").format(old="lbl_name", new="lbl_user"),
        SetField(_node(document, "lbl_name"), "id", "lbl_user"),
    )
    _attempt(
        stack,
        _("Change the text of '{id}'").format(id="btn_greet"),
        _set_text(_node(document, "btn_greet"), "Greet me"),
    )
    _state(stack)

    _heading(2, _("Blocked edits (the document is protected)"))
    stack.break_merge()
    before = dump_ui(document)
    depth = stack.index
    for description, command in blocked_scenarios(document):
        _attempt(stack, description, command)
    unchanged = dump_ui(document) == before and stack.index == depth
    print("   " + _("Document unchanged after the blocked edits: {answer}").format(
        answer=_yes_no(unchanged)))  # fmt: skip

    _heading(3, _("Typing merges into one undo step"))
    stack.break_merge()
    label = _node(document, "lbl_user")
    depth = stack.index
    for text in ("N", "Na", "Name:"):
        _attempt(stack, _("Type '{text}' into '{id}'").format(text=text, id="lbl_user"),
                 _set_text(label, text))  # fmt: skip
    steps = stack.index - depth
    print("   " + ngettext(
        "Three edits, {count} new undo step; the next undo is: {label}",
        "Three edits, {count} new undo steps; the next undo is: {label}",
        steps,
    ).format(count=steps, label=stack.undo_text))  # fmt: skip
    stack.break_merge()

    _heading(4, _("Undo, redo and unsaved changes"))
    stack.mark_saved()
    print("   " + _("Saved."))
    _state(stack)
    _attempt(stack, _("Change the text of '{id}'").format(id="btn_greet"),
             _set_text(_node(document, "btn_greet"), "Hello!"))  # fmt: skip
    _state(stack)
    stack.undo()
    print("   " + _("Undo."))
    _state(stack)
    stack.redo()
    print("   " + _("Redo."))
    _state(stack)
    stack.undo()
    stack.undo()
    print("   " + _("Undo twice (past the save point)."))
    _attempt(stack, _("Change the text of '{id}'").format(id="lbl_about"),
             _set_text(_node(document, "lbl_about"), "Something new"))  # fmt: skip
    print("   " + _("Same number of undo steps as when saved, but the saved state was replaced:"))
    _state(stack)

    _heading(5, _("Validation of a broken document"))
    result = read_ui_string(BROKEN_UI.format(version="1.0"), source="broken.ui")
    report = validate_read(result, default_registry())
    for finding in report.findings:
        severity = _("error") if finding.is_error else _("warning")
        print(f"   {finding.line}:{finding.column}  {severity}: {finding.message}")
    print("   " + _("Document is valid: {answer}").format(answer=_yes_no(report.ok)))

    _heading(6, _("A document from a newer PyGUIbud is read-only"))
    newer = read_ui_string(BROKEN_UI.format(version="1.1"), source="newer.ui").document
    newer_stack = CommandStack(newer, default_registry(), source="newer.ui")
    entry = _node(newer, "frm_empty")
    _attempt(newer_stack, _("Rename '{old}' to '{new}'").format(old="frm_empty", new="frm_ok"),
             SetField(entry, "id", "frm_ok"))  # fmt: skip
    _attempt(newer_stack, _("Give '{id}' a layout").format(id="frm_empty"),
             SetField(entry, "layout", DEFAULT_LAYOUT))  # fmt: skip
    return 0


def _safe_stdout() -> None:
    """Never crash on a console whose code page lacks a character (e.g. cp1252)."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")


if __name__ == "__main__":
    _safe_stdout()
    sys.exit(main())
