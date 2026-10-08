"""The actions of the designer shell (pure): which menus exist and what they call.

Only implemented actions are registered (spec decision D11): no disabled placeholders for
features of later steps. The Tk shell turns this registry into menus, toolbar and key bindings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef
from pyguibud.designer.edit import EditActions
from pyguibud.i18n import LANGUAGES, N_, PSEUDO_LANGUAGE

__all__ = ["THEME_ROLES", "ShellCallbacks", "register_standard_actions"]

_M_FILE = N_("_File")
_M_EDIT = N_("_Edit")
_M_UNDO = N_("_Undo")
# Translators: {action} is the step that is undone, e.g. "Add element"; _ marks the access key.
_M_UNDO_ACTION = N_("_Undo {action}")
_M_REDO = N_("_Redo")
# Translators: {action} is the step that is redone, e.g. "Add element".
_M_REDO_ACTION = N_("_Redo {action}")
_M_DELETE = N_("_Delete")
_M_SELECT_NEXT = N_("Select nex_t widget")
_M_SELECT_PREVIOUS = N_("Select prev_ious widget")
_M_SELECT_CHILD = N_("Select _first child")
_M_SELECT_PARENT = N_("Select _parent")
_M_SELECT_ALL = N_("Select all in _container")
# Translators: a sub-menu of Edit: moving and sizing the selected elements on the canvas.
_M_MOVE = N_("_Move")
_M_LEFT = N_("Move _left")
_M_RIGHT = N_("Move _right")
_M_UP = N_("Move _up")
_M_DOWN = N_("Move _down")
# Translators: "Wider" to "Shorter" make a grid element span one more or one less column/row.
_M_WIDER = N_("_Wider")
_M_NARROWER = N_("_Narrower")
_M_TALLER = N_("_Taller")
_M_SHORTER = N_("_Shorter")
# Translators: "Move earlier/later" change the order of an element among its siblings.
_M_EARLIER = N_("Move _earlier")
_M_LATER = N_("Move l_ater")
_M_VIEW = N_("_View")
_M_THEME = N_("_Theme")
_M_LANGUAGE = N_("_Language")
# Translators: the dots mean that a dialog opens; _ marks the access key.
_M_NEW = N_("_New from template…")
_M_QUIT = N_("_Quit")
_M_HELP = N_("_Help")
_M_SHORTCUTS = N_("_Keyboard shortcuts…")
_M_NEXT_PANEL = N_("Next _panel")
_M_PREVIOUS_PANEL = N_("Previous pa_nel")
_M_PSEUDO = N_("Pseudo-locale (layout test)")

#: ``(role, label msgid)``; the roles are the ones of ``ThemeSpec.role``.
THEME_ROLES: tuple[tuple[str, str], ...] = (
    ("light", N_("_Light")),
    ("dark", N_("_Dark")),
    ("high_contrast", N_("_High contrast")),
)


@dataclass(frozen=True, slots=True)
class ShellCallbacks:
    """What the shell actions need from the application (so this module stays Tk-free)."""

    new_document: Callable[[], None]
    show_shortcuts: Callable[[], None]
    next_panel: Callable[[], None]
    previous_panel: Callable[[], None]
    quit: Callable[[], None]
    set_theme: Callable[[str], object]
    current_theme: Callable[[], str]
    set_language: Callable[[str], None]
    current_language: Callable[[], str]
    edit: EditActions | None = None  # the Edit menu is registered only when given


def register_standard_actions(registry: ActionRegistry, callbacks: ShellCallbacks) -> None:
    """Add the File, View and Help menus (New, Quit, Theme, Language, panels, shortcuts)."""
    registry.add_menu(MenuDef("file", _M_FILE))
    if callbacks.edit is not None:
        _register_edit(registry, callbacks.edit)
    registry.add_menu(MenuDef("view", _M_VIEW))
    registry.add_menu(MenuDef("view.theme", _M_THEME, parent="view"))
    registry.add_menu(MenuDef("view.language", _M_LANGUAGE, parent="view"))

    # "New" opens the template wizard (Step 12h).
    registry.add(
        ActionDef(
            "file.new", "file", _M_NEW, callbacks.new_document, shortcut="Ctrl+N", toolbar=True
        )
    )
    registry.add_separator("file")
    registry.add(ActionDef("file.quit", "file", _M_QUIT, callbacks.quit, shortcut="Ctrl+Q"))

    for role, label in THEME_ROLES:
        registry.add(
            ActionDef(
                f"view.theme.{role}",
                "view.theme",
                label,
                _theme_handler(callbacks, role),
                checked=_theme_checked(callbacks, role),
            )
        )

    for code, autonym in LANGUAGES.items():
        registry.add(_language_action(callbacks, code, autonym, translate=False))
    # The pseudo-locale is a layout-testing tool (``--lang en_XA``): listed only when it is the
    # language the designer started with, so that the current selection stays visible (QA-12-12).
    if callbacks.current_language() == PSEUDO_LANGUAGE:
        registry.add_separator("view.language")
        registry.add(_language_action(callbacks, PSEUDO_LANGUAGE, _M_PSEUDO, translate=True))

    registry.add_separator("view")
    registry.add(
        ActionDef("view.next_panel", "view", _M_NEXT_PANEL, callbacks.next_panel, shortcut="F6")
    )
    registry.add(
        ActionDef(
            "view.previous_panel",
            "view",
            _M_PREVIOUS_PANEL,
            callbacks.previous_panel,
            shortcut="Shift+F6",
        )
    )

    registry.add_menu(MenuDef("help", _M_HELP))
    registry.add(
        ActionDef("help.shortcuts", "help", _M_SHORTCUTS, callbacks.show_shortcuts, shortcut="F1")
    )


def _register_edit(registry: ActionRegistry, edit: EditActions) -> None:
    """Edit menu (spec 11): live Undo/Redo labels, Delete bound on the canvas and the tree."""

    def live(
        msgid: str, text: Callable[[], str | None]
    ) -> Callable[[], tuple[str, dict[str, str]] | None]:
        return lambda: (msgid, {"action": t}) if (t := text()) else None

    registry.add_menu(MenuDef("edit", _M_EDIT))
    registry.add(
        ActionDef(
            "edit.undo",
            "edit",
            _M_UNDO,
            edit.undo,
            shortcut="Ctrl+Z",
            enabled=edit.can_undo,
            dynamic_label=live(_M_UNDO_ACTION, lambda: edit.undo_text),
        )
    )
    registry.add(
        ActionDef(
            "edit.redo",
            "edit",
            _M_REDO,
            edit.redo,
            shortcut="Ctrl+Y",
            alt_shortcuts=("Ctrl+Shift+Z",),
            enabled=edit.can_redo,
            dynamic_label=live(_M_REDO_ACTION, lambda: edit.redo_text),
        )
    )
    registry.add_separator("edit")
    registry.add(
        ActionDef(
            "edit.delete",
            "edit",
            _M_DELETE,
            edit.delete,
            shortcut="Delete",
            enabled=edit.can_delete,
            scope=("canvas", "tree"),
            refusal=edit.delete_refusal,
        )
    )
    registry.add_separator("edit")
    registry.add_menu(MenuDef("edit.move", _M_MOVE, parent="edit"))
    # Keys of the canvas focus proxy and the tree (spec 7.3): scoped, so a Treeview keeps Tab,
    # Enter and the arrows. (id, menu, label, chord, scope, handler)
    keys: tuple[tuple[str, str, str, str, str, Callable[[], None]], ...] = (
        ("select_next", "edit", _M_SELECT_NEXT, "Tab", "canvas", lambda: edit.select_step(1)),
        ("select_previous", "edit", _M_SELECT_PREVIOUS, "Shift+Tab", "canvas",
         lambda: edit.select_step(-1)),
        ("select_child", "edit", _M_SELECT_CHILD, "Enter", "canvas", edit.select_child),
        ("select_parent", "edit", _M_SELECT_PARENT, "Escape", "canvas", edit.select_parent),
        ("select_all", "edit", _M_SELECT_ALL, "Ctrl+A", "canvas", edit.select_all),
        ("left", "edit.move", _M_LEFT, "Left", "canvas", lambda: edit.nudge(0, -1)),
        ("right", "edit.move", _M_RIGHT, "Right", "canvas", lambda: edit.nudge(0, 1)),
        ("up", "edit.move", _M_UP, "Up", "canvas", lambda: edit.nudge(-1, 0)),
        ("down", "edit.move", _M_DOWN, "Down", "canvas", lambda: edit.nudge(1, 0)),
        ("wider", "edit.move", _M_WIDER, "Shift+Right", "canvas", lambda: edit.span(0, 1)),
        ("narrower", "edit.move", _M_NARROWER, "Shift+Left", "canvas", lambda: edit.span(0, -1)),
        ("taller", "edit.move", _M_TALLER, "Shift+Down", "canvas", lambda: edit.span(1, 0)),
        ("shorter", "edit.move", _M_SHORTER, "Shift+Up", "canvas", lambda: edit.span(-1, 0)),
        ("earlier", "edit.move", _M_EARLIER, "Alt+Up", "tree", lambda: edit.reorder(-1)),
        ("later", "edit.move", _M_LATER, "Alt+Down", "tree", lambda: edit.reorder(1)),
    )  # fmt: skip
    for name, menu, label, chord, scope, handler in keys:
        enabled = edit.has_selection
        registry.add(
            ActionDef(f"edit.{name}", menu, label, handler, chord, enabled, scope=(scope,))
        )


def _theme_handler(callbacks: ShellCallbacks, role: str) -> Callable[[], None]:
    def handler() -> None:
        callbacks.set_theme(role)

    return handler


def _theme_checked(callbacks: ShellCallbacks, role: str) -> Callable[[], bool]:
    def checked() -> bool:
        return callbacks.current_theme() == role

    return checked


def _language_action(
    callbacks: ShellCallbacks, code: str, label: str, *, translate: bool
) -> ActionDef:
    def handler() -> None:
        callbacks.set_language(code)

    def checked() -> bool:
        return callbacks.current_language() == code

    return ActionDef(
        f"view.language.{code}",
        "view.language",
        label,
        handler,
        checked=checked,
        translate=translate,
    )
