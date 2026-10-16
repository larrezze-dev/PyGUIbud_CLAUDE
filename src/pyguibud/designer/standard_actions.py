"""The actions of the designer shell (pure): which menus exist and what they call.

Only implemented actions are registered (spec decision D11): no disabled placeholders for
features of later steps. The Tk shell turns this registry into menus, toolbar and key bindings.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import dataclass

from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef
from pyguibud.designer.clipboard_actions import ClipboardActions
from pyguibud.designer.edit import EditActions
from pyguibud.designer.editing import MenuItem
from pyguibud.designer.preview import M_NOT_INSTALLED, toolkit_label
from pyguibud.designer.windows import WindowActions, WindowKind
from pyguibud.i18n import LANGUAGES, N_, PSEUDO_LANGUAGE

__all__ = [
    "THEME_ROLES",
    "FileCallbacks",
    "PreviewCallbacks",
    "ShellCallbacks",
    "register_standard_actions",
]

_M_FILE = N_("_File")
_M_EDIT = N_("_Edit")
_M_UNDO = N_("_Undo")
# Translators: {action} is the step that is undone, e.g. "Add element"; _ marks the access key.
_M_UNDO_ACTION = N_("_Undo {action}")
_M_REDO = N_("_Redo")
# Translators: {action} is the step that is redone, e.g. "Add element".
_M_REDO_ACTION = N_("_Redo {action}")
_M_DELETE = N_("_Delete")
_M_SELECT_NEXT = N_("Select _next widget")
_M_SELECT_PREVIOUS = N_("Select prev_ious widget")
_M_SELECT_CHILD = N_("Select _first child")
_M_SELECT_PARENT = N_("Select _parent")
_M_SELECT_ALL = N_("Select all in _container")
# Translators: the clipboard verbs of the Edit menu (cut, copy, paste, duplicate the selection).
_M_CUT = N_("Cu_t")
_M_COPY = N_("C_opy")
_M_PASTE = N_("Pa_ste")
_M_DUPLICATE = N_("Dup_licate")
# Translators: a sub-menu of Edit that adds menu bars, menus, actions and status bars.
_M_INSERT = N_("Ins_ert")
_M_MENUBAR = N_("_Menu bar")
_M_MENU = N_("M_enu")
_M_ACTION = N_("_Action")
_M_SEPARATOR = N_("_Separator")
_M_STATUSBAR = N_("Status _bar")
# Translators: the menu of the windows (main window, dialogs, components) of the open file.
_M_DOCUMENT = N_("_Document")
_M_ADD_MAIN = N_("Add _main window")
_M_ADD_DIALOG = N_("Add d_ialog")
_M_ADD_COMPONENT = N_("Add _component")
# Translators: the dots mean that a dialog opens; _ marks the access key.
_M_RENAME_WINDOW = N_("_Rename window…")
_M_DELETE_WINDOW = N_("_Delete window")
_M_NEXT_WINDOW = N_("_Next window")
_M_PREVIOUS_WINDOW = N_("_Previous window")
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
# Translators: change the width/height property of the selected element by one unit
# (a character, a line or 4 pixels), or the minimum size of a selected window.
_M_SIZE_WIDER = N_("_Increase width")
_M_SIZE_NARROWER = N_("De_crease width")
_M_SIZE_TALLER = N_("Increase _height")
_M_SIZE_SHORTER = N_("Decrease hei_ght")
# Translators: "Move earlier/later" change the order of an element among its siblings.
_M_EARLIER = N_("Move _earlier")
_M_LATER = N_("Move l_ater")
_M_VIEW = N_("_View")
_M_THEME = N_("_Theme")
_M_LANGUAGE = N_("_Language")
# Translators: the dots mean that a dialog opens; _ marks the access key.
_M_NEW = N_("_New from template…")
_M_QUIT = N_("_Quit")
_M_OPEN = N_("_Open…")
# Translators: a sub-menu listing the files opened last.
_M_RECENT = N_("Open _recent")
# Translators: reopen unsaved work kept after a crash; _ marks the access key (R is taken).
_M_RECOVER = N_("Reco_ver…")
_M_SAVE = N_("_Save")
_M_SAVE_AS = N_("Save _as…")
_M_CLOSE = N_("_Close")
# Translators: File menu; writes the .py module of the saved .ui file (Ctrl+E).
_M_EXPORT = N_("_Export Python code…")
_M_HELP = N_("_Help")
_M_SHORTCUTS = N_("_Keyboard shortcuts…")
_M_PLUGINS = N_("_Plugins…")
_M_NEXT_PANEL = N_("Next _panel")
_M_PREVIOUS_PANEL = N_("Previous pa_nel")
_M_PSEUDO = N_("Pseudo-locale (layout test)")
# Translators: the menu, and its action, that runs the document in a separate window (F5).
_M_PREVIEW = N_("_Preview")
_M_CLOSE_PREVIEW = N_("_Close preview")
# Translators: Preview > Language: show the texts as written in the document (no translation).
_M_DOCUMENT_LANGUAGE = N_("Document language")
_M_USE_THEME = N_("_Use this theme in the document")
# Translators: Preview > Toolkit: the sub-menu that chooses the GUI toolkit of the preview.
_M_TOOLKIT = N_("Tool_kit")

#: ``(role, label msgid)``; the roles are the ones of ``ThemeSpec.role``.
THEME_ROLES: tuple[tuple[str, str], ...] = (
    ("light", N_("_Light")),
    ("dark", N_("_Dark")),
    ("high_contrast", N_("_High contrast")),
)


@dataclass(frozen=True, slots=True)
class FileCallbacks:
    """The file lifecycle of the application (spec 14a section 9.1)."""

    open: Callable[[], None]
    save: Callable[[], None]
    save_as: Callable[[], None]
    close: Callable[[], None]
    recover: Callable[[], None]
    has_document: Callable[[], bool]
    export: Callable[[], None] | None = None  # File > Export Python code (Step 15b)


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
    clipboard: ClipboardActions | None = None  # Cut, Copy, Paste, Duplicate (needs ``edit``)
    windows: WindowActions | None = None  # the Document menu is registered only when given
    files: FileCallbacks | None = None  # Open, Open recent, Save, Close, Recover
    preview: PreviewCallbacks | None = None  # the Preview menu (Step 15a)
    show_plugins: Callable[[], None] | None = None  # Help > Plugins (Step 17c)


@dataclass(frozen=True, slots=True)
class PreviewCallbacks:
    """The Preview menu (spec preview-export 3); the app fills the Theme sub-menu itself."""

    run: Callable[[], None]
    close: Callable[[], None]
    has_document: Callable[[], bool]
    running: Callable[[], bool]
    set_language: Callable[[str | None], None]  # None = the document language
    language: Callable[[], str | None]
    use_theme: Callable[[], None]
    can_use_theme: Callable[[], bool]
    #: Preview > Toolkit (Step 16a): the listed backend names (empty: no sub-menu).
    toolkits: tuple[str, ...] = ()
    set_toolkit: Callable[[str], None] = lambda _name: None
    toolkit: Callable[[], str] = lambda: "ttkbootstrap"  # the toolkit in use
    toolkit_installed: Callable[[str], bool] = lambda _name: True


def register_standard_actions(registry: ActionRegistry, callbacks: ShellCallbacks) -> None:
    """Add the File, View and Help menus (New, Quit, Theme, Language, panels, shortcuts)."""
    registry.add_menu(MenuDef("file", _M_FILE))
    if callbacks.edit is not None:
        _register_edit(registry, callbacks.edit, callbacks.clipboard)
    if callbacks.windows is not None:
        _register_document(registry, callbacks.windows)
    if callbacks.preview is not None:
        _register_preview(registry, callbacks.preview)
    registry.add_menu(MenuDef("view", _M_VIEW))
    registry.add_menu(MenuDef("view.theme", _M_THEME, parent="view"))
    registry.add_menu(MenuDef("view.language", _M_LANGUAGE, parent="view"))

    # "New" opens the template wizard (Step 12h).
    registry.add(
        ActionDef(
            "file.new", "file", _M_NEW, callbacks.new_document, "Ctrl+N", toolbar=True, icon="new"
        )
    )
    if callbacks.files is not None:
        _register_files(registry, callbacks.files)
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
    if callbacks.show_plugins is not None:
        registry.add(ActionDef("help.plugins", "help", _M_PLUGINS, callbacks.show_plugins))


def _register_files(registry: ActionRegistry, files: FileCallbacks) -> None:
    """Open, Open recent (filled by the app), Recover, Save, Save as and Close."""
    has = files.has_document
    registry.add(
        ActionDef("file.open", "file", _M_OPEN, files.open, "Ctrl+O", toolbar=True, icon="open")
    )
    registry.add_menu(MenuDef("file.recent", _M_RECENT, parent="file"))
    registry.add(ActionDef("file.recover", "file", _M_RECOVER, files.recover))
    registry.add_separator("file")
    registry.add(
        ActionDef(
            "file.save", "file", _M_SAVE, files.save, "Ctrl+S", has, toolbar=True, icon="save"
        )
    )
    registry.add(ActionDef("file.save_as", "file", _M_SAVE_AS, files.save_as, "Ctrl+Shift+S", has))
    if files.export is not None:
        registry.add(
            ActionDef("file.export", "file", _M_EXPORT, files.export, "Ctrl+E", has,
                      toolbar=True, icon="export")
        )  # fmt: skip
    registry.add_separator("file")
    registry.add(ActionDef("file.close", "file", _M_CLOSE, files.close, "Ctrl+W", has))


def _register_edit(
    registry: ActionRegistry, edit: EditActions, clipboard: ClipboardActions | None
) -> None:
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
            toolbar=True,
            icon="undo",
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
            toolbar=True,
            icon="redo",
        )
    )
    registry.add_separator("edit")
    if clipboard is not None:
        _register_clipboard(registry, clipboard)
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
            toolbar=True,
            icon="delete",
        )
    )
    registry.add_separator("edit")
    _register_insert(registry, edit)
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
        ("size_wider", "edit.move", _M_SIZE_WIDER, "Ctrl+Shift+Right", "canvas",
         lambda: edit.size_step(0, 1)),
        ("size_narrower", "edit.move", _M_SIZE_NARROWER, "Ctrl+Shift+Left", "canvas",
         lambda: edit.size_step(0, -1)),
        ("size_taller", "edit.move", _M_SIZE_TALLER, "Ctrl+Shift+Down", "canvas",
         lambda: edit.size_step(1, 1)),
        ("size_shorter", "edit.move", _M_SIZE_SHORTER, "Ctrl+Shift+Up", "canvas",
         lambda: edit.size_step(1, -1)),
        ("earlier", "edit.move", _M_EARLIER, "Alt+Up", "tree", lambda: edit.reorder(-1)),
        ("later", "edit.move", _M_LATER, "Alt+Down", "tree", lambda: edit.reorder(1)),
    )  # fmt: skip
    for name, menu, label, chord, scope, handler in keys:
        enabled = edit.has_selection
        registry.add(
            ActionDef(f"edit.{name}", menu, label, handler, chord, enabled, scope=(scope,))
        )


def _register_clipboard(registry: ActionRegistry, clip: ClipboardActions) -> None:
    """Ctrl+X/C/V/D act on the canvas and the tree only: an inspector Entry keeps its text keys."""
    both = ("canvas", "tree")
    read_only = clip.read_only_refusal  # Copy still works in a read-only document
    for name, label, chord, handler, enabled, refusal in (
        ("cut", _M_CUT, "Ctrl+X", clip.cut, clip.can_cut, read_only),
        ("copy", _M_COPY, "Ctrl+C", clip.copy, clip.can_copy, None),
        ("paste", _M_PASTE, "Ctrl+V", clip.paste, clip.can_paste, read_only),
        ("duplicate", _M_DUPLICATE, "Ctrl+D", clip.duplicate, clip.can_cut, read_only),
    ):
        registry.add(
            ActionDef(
                f"edit.{name}",
                "edit",
                label,
                handler,
                chord,
                enabled,
                scope=both,
                refusal=refusal,
                toolbar=name != "duplicate",
                icon="" if name == "duplicate" else name,
            )
        )
    registry.add_separator("edit")


def _register_insert(registry: ActionRegistry, edit: EditActions) -> None:
    """Edit > Insert (spec 6): menu bar, menu, action, separator and status bar."""
    registry.add_menu(MenuDef("edit.insert", _M_INSERT, parent="edit"))
    kinds: tuple[tuple[MenuItem, str], ...] = (
        ("menubar", _M_MENUBAR),
        ("menu", _M_MENU),
        ("action", _M_ACTION),
        ("separator", _M_SEPARATOR),
        ("statusbar", _M_STATUSBAR),
    )
    for kind, label in kinds:
        registry.add(
            ActionDef(
                f"edit.insert.{kind}",
                "edit.insert",
                label,
                functools.partial(edit.insert, kind),
                enabled=functools.partial(edit.can_insert, kind),
                refusal=edit.read_only_refusal,
            )
        )


def _register_document(registry: ActionRegistry, windows: WindowActions) -> None:
    """The Document menu (spec 7): add, rename, delete and switch windows."""
    registry.add_menu(MenuDef("document", _M_DOCUMENT))
    adds: tuple[tuple[WindowKind, str], ...] = (
        ("main", _M_ADD_MAIN),
        ("dialog", _M_ADD_DIALOG),
        ("component", _M_ADD_COMPONENT),
    )
    for kind, label in adds:
        registry.add(
            ActionDef(
                f"document.add_{kind}",
                "document",
                label,
                functools.partial(windows.add, kind),
                enabled=windows.can_add,
                refusal=windows.read_only_refusal,
            )
        )
    registry.add_separator("document")
    registry.add(
        ActionDef(
            "document.rename",
            "document",
            _M_RENAME_WINDOW,
            windows.rename,
            "F2",
            windows.can_change,
            scope=("canvas",),
            refusal=windows.read_only_refusal,
        )
    )
    registry.add(
        ActionDef(
            "document.delete",
            "document",
            _M_DELETE_WINDOW,
            windows.delete,
            None,
            windows.can_change,
            refusal=windows.read_only_refusal,
        )
    )
    registry.add_separator("document")
    for name, label, chord, delta in (
        ("next", _M_NEXT_WINDOW, "Ctrl+PageDown", 1),
        ("previous", _M_PREVIOUS_WINDOW, "Ctrl+PageUp", -1),
    ):
        registry.add(
            ActionDef(
                f"document.{name}",
                "document",
                label,
                functools.partial(windows.step, delta),
                chord,
                windows.can_step,
            )
        )


def _register_preview(registry: ActionRegistry, preview: PreviewCallbacks) -> None:
    """Preview: run (F5), close (Shift+F5), Language and Theme (live), use the theme."""
    registry.add_menu(MenuDef("preview", _M_PREVIEW))
    registry.add(
        ActionDef("preview.run", "preview", _M_PREVIEW, preview.run, "F5", preview.has_document,
                  toolbar=True, icon="preview")
    )  # fmt: skip
    registry.add(
        ActionDef("preview.close", "preview", _M_CLOSE_PREVIEW, preview.close, "Shift+F5",
                  preview.running)
    )  # fmt: skip
    registry.add_separator("preview")
    registry.add_menu(MenuDef("preview.language", _M_LANGUAGE, parent="preview"))
    choices = [(None, _M_DOCUMENT_LANGUAGE, True), *((c, a, False) for c, a in LANGUAGES.items())]
    for code, label, translate in [*choices, (PSEUDO_LANGUAGE, _M_PSEUDO, True)]:
        registry.add(
            ActionDef(
                f"preview.language.{code or 'document'}",
                "preview.language",
                label,
                functools.partial(preview.set_language, code),
                checked=functools.partial(lambda c: preview.language() == c, code),
                translate=translate,
            )
        )
    if preview.toolkits:
        _register_toolkits(registry, preview)
    registry.add_menu(  # only ttkbootstrap has themes (QA-16a-10)
        MenuDef("preview.theme", _M_THEME, "preview", lambda: preview.toolkit() == "ttkbootstrap")
    )
    registry.add(
        ActionDef("preview.use_theme", "preview", _M_USE_THEME, preview.use_theme,
                  enabled=preview.can_use_theme)
    )  # fmt: skip


def _register_toolkits(registry: ActionRegistry, preview: PreviewCallbacks) -> None:
    """Preview > Toolkit: one radio per listed backend; an optional toolkit that is not
    installed is greyed and says so. Names are proper nouns (untranslated)."""
    registry.add_menu(MenuDef("preview.toolkit", _M_TOOLKIT, parent="preview"))
    for name in preview.toolkits:
        label = toolkit_label(name)
        registry.add(
            ActionDef(
                f"preview.toolkit.{name}",
                "preview.toolkit",
                label.replace("_", "__"),  # a "_" in a fork's name is not a mnemonic mark
                functools.partial(preview.set_toolkit, name),
                enabled=functools.partial(preview.toolkit_installed, name),
                checked=functools.partial(lambda n: preview.toolkit() == n, name),
                translate=False,
                dynamic_label=functools.partial(_toolkit_label, preview, name, label),
            )
        )


def _toolkit_label(
    preview: PreviewCallbacks, name: str, label: str
) -> tuple[str, dict[str, str]] | None:
    return None if preview.toolkit_installed(name) else (M_NOT_INSTALLED, {"name": label})


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
