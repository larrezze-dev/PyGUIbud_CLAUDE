"""The designer application window (Tk). Imported only from :func:`pyguibud.designer.launch`."""

from __future__ import annotations

import base64
import contextlib
import functools
import logging
import os
import re
import signal
import sys
import tkinter
from collections.abc import Callable, Collection
from pathlib import Path
from typing import Any, Literal

from pyguibud.core import PyGUIbudError, ReadResult, XmlIoError, default_registry, write_ui
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.registry import configure_default_registry
from pyguibud.designer.actions import ActionRegistry
from pyguibud.designer.clipboard_actions import ClipboardActions
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.dialogs.confirm import ConfirmDialog
from pyguibud.designer.dialogs.export import ExportController
from pyguibud.designer.dialogs.message import Answer, ChoiceDialog, message_dialog
from pyguibud.designer.dialogs.new_file import NewFileDialog
from pyguibud.designer.dialogs.plugins import PluginsDialog
from pyguibud.designer.dialogs.recovery import RecoveryDialog
from pyguibud.designer.dialogs.rename import RenameDialog
from pyguibud.designer.dialogs.save_changes import save_changes_dialog
from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
from pyguibud.designer.edit import EditActions
from pyguibud.designer.files import (
    M_READ_ONLY,
    SAVE_AS_REASONS,
    FileStamp,
    RecentFiles,
    SavePlan,
    open_document,
    save_plan,
)
from pyguibud.designer.present.plugins import plugin_note
from pyguibud.designer.preview_tk import PreviewController, sweep_stale
from pyguibud.designer.recovery import RecoveryEntry, RecoverySession
from pyguibud.designer.screen import desktop_bounds
from pyguibud.designer.session import DesignerSession, TemplateError
from pyguibud.designer.settings import (
    BACKEND_NAME,
    DEFAULT_BACKEND,
    Settings,
    load_settings,
    resolve_language,
    resolve_theme,
    save_settings,
)
from pyguibud.designer.shell import Shell
from pyguibud.designer.signals import Signal
from pyguibud.designer.standard_actions import (
    FileCallbacks,
    PreviewCallbacks,
    ShellCallbacks,
    register_standard_actions,
)
from pyguibud.designer.theme import ThemeSpec, load_app_icon, load_theme_specs, spec_for_role
from pyguibud.designer.windows import WindowActions
from pyguibud.i18n import (
    LANGUAGES,
    N_,
    _,
    add_language_listener,
    catalogue_problem,
    get_language,
    ngettext,
    remove_language_listener,
    set_language,
)

__all__ = ["CLI_THEMES", "DesignerApp", "apply_app_icon", "desktop_bounds", "fit_geometry", "run"]

_log = logging.getLogger(__name__)

_M_TITLE = N_("PyGUIbud designer")
_M_UNKNOWN_THEME = N_("There is no theme called '{theme}'.")
# Translators: {name} is a file name such as "main.ui".
_M_SAVED = N_("Saved '{name}'.")
# Translators: {name} is a file name such as "main.ui".
_M_CONFLICT = N_("'{name}' was changed by another program since it was opened.")
# Translators: the answers when the file changed on disk; _ marks the access key.
_M_OVERWRITE = N_("_Overwrite")
_M_SAVE_AS = N_("Save _as…")
_M_CANCEL = N_("_Cancel")
_M_OK = N_("_OK")
# Translators: the confirmation button of "The document has {count} errors. Save anyway?".
_M_SAVE = N_("_Save")
# Translators: {path} is the full path of a file.
_M_MISSING = N_("The file '{path}' does not exist.")
_M_CLEAR = N_("_Clear list")
_M_SETTINGS_NOT_SAVED = N_("Your settings could not be saved.")
_M_NOTHING_TO_RECOVER = N_("There is no unsaved work to recover.")
_M_DISCARD = N_("_Discard")
# Tk writes a position left of or above the primary monitor as "+-1500"; a bare "-N" is kept as
# a negative position too (a hand edit), and "--N" is refused.
_GEOMETRY = re.compile(r"(\d+)x(\d+)(\+-?\d+|-\d+)(\+-?\d+|-\d+)")
_MIN_VISIBLE = (200, 150)
_RETRY_MS = 2000  # autosave waits this long while a drag runs
_MIN_SIZE = (800, 500)
_RING_PX = 2  # width of the panel focus ring at 96 dpi
#: Windows taskbar grouping: the designer's own button and icon, not python.exe's.
_APP_USER_MODEL_ID = "SAPE.PyGUIbud.Designer"
#: The command-line spelling of a theme role.
CLI_THEMES = {"light": "light", "dark": "dark", "high-contrast": "high_contrast"}


class DesignerApp:
    """The shell on an injected root (tests pass the shared root; ``run`` creates its own)."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - a ttkbootstrap App; tests inject the shared root
        session: DesignerSession | None = None,
        *,
        role: str = "light",
        specs: tuple[ThemeSpec, ...] | None = None,
        settings: Settings | None = None,
        recovery: RecoverySession | None = None,
        plugins: Collection[str] | Literal["all"] = (),
    ) -> None:
        """``settings`` given: they are written back (``run`` passes them; tests may). Without
        ``recovery`` there is no autosave timer. ``plugins`` is the disabled filter this run
        started with (``"all"``: safe mode); the preview child gets the same one."""
        from pyguibud.designer import theme_tk

        self.root = root
        self.session = session if session is not None else DesignerSession(default_registry())
        self.specs = specs if specs is not None else load_theme_specs()
        self.message: Signal[str] = Signal()  # transient status-bar text
        self.role = ""
        self._pending: str | None = None
        self._idle_id: str | None = None
        self._disposed = False
        self._dialogs: list[ModalDialog] = []
        self._theme_tk = theme_tk
        self._persist = settings is not None
        self.settings = settings if settings is not None else Settings()
        self.recent = RecentFiles(self.settings.recent_files)
        self.recovery = recovery
        self.session.recovery = recovery
        self._autosave_id: str | None = None
        self._notice: str | None = None  # a start-up message, posted after the first selection
        self.plugins = plugins
        self._plugins_due = False  # the plugin note is posted once, with the start-up notice
        self._settings_warned = False  # "settings not saved" is said once per run
        self._sashes_done = False
        #: How the window ends after Quit (tests replace it: the shared root must stay).
        self.on_exit: Callable[[], None] = self._destroy

        theme_tk.install_themes(_style(), self.specs)
        first = spec_for_role(self.specs, role) or self.specs[0]
        theme_tk.apply_fonts(root, first)
        theme_tk.use_theme(root, first)
        self.role = first.role
        root.minsize(*(theme_tk.scaled(root, size) for size in _MIN_SIZE))

        self.preview = PreviewController(
            root, self.session, self.settings, post=self.message.emit,
            tell=lambda text: self._tell(lambda: text), save_settings=self._save_settings,
            current_window=self._canvas_window, toolkits=self._toolkit_names, plugins=plugins,
        )  # fmt: skip
        preview = self.preview
        self.exporter = ExportController(
            root, self.session, self.settings, post=self.message.emit,
            tell=lambda text: self._tell(lambda: text), ask=self._ask,
            save=lambda then: self.save(then=then), open_dialog=self._open_dialog,
            save_settings=self._save_settings,
        )  # fmt: skip
        self.registry = ActionRegistry()
        register_standard_actions(
            self.registry,
            ShellCallbacks(
                new_document=self.open_new_file,
                show_shortcuts=self.open_shortcuts,
                show_plugins=self.open_plugins,
                next_panel=lambda: self.shell.cycle_focus(1),
                previous_panel=lambda: self.shell.cycle_focus(-1),
                quit=self.quit,
                set_theme=self.set_theme,
                current_theme=lambda: self._pending or self.role,
                set_language=self.set_language,
                current_language=get_language,
                edit=EditActions(
                    self.session,
                    self._confirm,
                    self.message.emit,
                    busy=lambda: self.shell.canvas.rebuild_pending,  # drops key repeats
                    measure=lambda node: self.shell.canvas.measure(node),
                ),
                clipboard=ClipboardActions(
                    self.session,
                    self.message.emit,
                    self._clipboard_put,
                    self._clipboard_get,
                    current_window=self._canvas_window,
                ),
                windows=WindowActions(
                    self.session, self._confirm, self.message.emit, self._ask_name
                ),
                files=FileCallbacks(
                    open=self.open_file,
                    save=self.save,
                    save_as=lambda: self.save(as_new=True),
                    close=lambda: self.guard(self.session.close_document),
                    recover=self.recover,
                    has_document=lambda: self.session.document is not None,
                    export=self.exporter.start,
                ),
                preview=PreviewCallbacks(
                    preview.run,
                    preview.close,
                    lambda: self.session.document is not None,
                    lambda: preview.running,
                    preview.set_language,
                    lambda: self.settings.preview_lang,
                    preview.use_theme,
                    preview.can_use_theme,
                    self._toolkit_names(),
                    preview.set_toolkit,
                    preview.toolkit,
                    preview.installed,
                ),
            ),
        )
        self.shell = Shell(
            root, self.session, self.registry, ring_px=theme_tk.scaled(root, _RING_PX)
        )
        self.message.connect(self.shell.show_message)
        self.registry.message.connect(self.shell.show_message)
        self.shell.inspector.open_dialog = self._show_built
        self.shell.variables.confirm = self._confirm
        self.shell.restyle(first)
        self._disconnect_title = self.session.file_changed.connect(lambda _s: self.retranslate())
        self._recent_menu = self.shell.submenus.get("file.recent")
        if self._recent_menu is not None:
            self._recent_menu.configure(postcommand=self._fill_recent)
        if (themes := self.shell.submenus.get("preview.theme")) is not None:
            themes.configure(postcommand=lambda: preview.fill_theme_menu(themes))
            preview.fill_theme_menu(themes)
        self.shell.body.bind("<Configure>", self._restore_sashes, add="+")
        self.retranslate()
        self._fill_recent()
        add_language_listener(self._on_language)
        self._schedule_autosave()

    # ------------------------------------------------------------ theme
    def set_theme(self, role: str) -> bool:
        """Request a theme role; rapid requests coalesce and the last one wins.

        Returns:
            False (and a message) for an unknown role.
        """
        if spec_for_role(self.specs, role) is None:
            self.message.emit(_(_M_UNKNOWN_THEME).format(theme=role))
            return False
        self._pending = role
        if self._idle_id is None and not self._disposed:
            self._idle_id = self.root.after_idle(self.flush_theme)
        return True

    def flush_theme(self) -> None:
        """Apply the pending theme request now (also what ``after_idle`` runs)."""
        self._cancel_idle()
        role, self._pending = self._pending, None
        spec = spec_for_role(self.specs, role) if role is not None else None
        if spec is None or self._disposed:
            return
        try:
            self._theme_tk.use_theme(self.root, spec)
            self.role = spec.role
            self.shell.restyle(spec)
            self.shell.refresh_states()
            for dialog in self._live_dialogs():
                dialog.restyle()
        except tkinter.TclError:
            _log.exception("Switching to theme %s failed", spec.name)
            return
        if self.settings.theme != spec.role:
            self.settings.theme = spec.role
            self._save_settings()

    def _cancel_idle(self) -> None:
        if self._idle_id is not None:
            try:
                self.root.after_cancel(self._idle_id)
            except tkinter.TclError:
                _log.debug("after_cancel failed", exc_info=True)
            self._idle_id = None

    # ------------------------------------------------------------ language
    def set_language(self, code: str) -> None:
        """Switch the interface language live (the i18n listener retranslates the window)."""
        try:
            set_language(code)
        except ValueError as exc:
            self.message.emit(str(exc))
            return
        problem = catalogue_problem()
        if problem is not None:  # a damaged catalogue: English is shown, and the user is told
            self.message.emit(problem)  # after the switch, which clears the status line
            return  # never remembered: the next start would only fall back again
        if code in LANGUAGES:  # only a menu choice is remembered, never ``--lang`` (spec 12)
            self.settings.language = code
            self._save_settings()

    def _on_language(self, _code: str) -> None:
        """The single i18n listener of the app: menus, toolbar, panels, title, status bar.

        Every step is isolated, so one failing panel never blocks the others.
        """
        steps: list[tuple[str, Callable[[], None]]] = [
            ("status message", self.shell.clear_message),  # first: keep messages of the switch
            ("menus", self.shell.retranslate_menus),
            ("toolbar", self.shell.retranslate_toolbar),
        ]
        steps += [(f"{panel.name} panel", panel.retranslate) for panel in self.shell.all_panels]
        steps += [("title", self.retranslate), ("status bar", self.shell.retranslate_status)]
        steps += [("panel widths", self.shell.clamp_sashes)]  # new names may need a wider palette
        steps += [("recent files", self._fill_recent)]
        steps += [("dialog", dialog.retranslate) for dialog in self._live_dialogs()]
        for name, step in steps:
            try:
                step()
            except Exception:
                _log.exception("Retranslating failed in the %s", name)

    def retranslate(self) -> None:
        """Re-apply the window title: the document's name and state, else the product name."""
        document = self.session.document
        self.root.title(_(_M_TITLE) if document is None else self.session.title)

    # ------------------------------------------------------------ dialogs and actions
    def _live_dialogs(self) -> list[ModalDialog]:
        self._dialogs = [d for d in self._dialogs if not d.closed]
        return list(self._dialogs)

    def _open_dialog(
        self, factory: Callable[[], ModalDialog], *, nested: bool = False
    ) -> ModalDialog | None:
        """Open a dialog unless one is already open (then raise that one: one modal at a time).

        ``nested`` opens it over the current one (a confirmation inside a dialog).
        """
        live = self._live_dialogs()
        if live and not nested:
            live[-1].window.lift()
            return None
        dialog = factory()
        self._dialogs.append(dialog)
        dialog.open()
        return dialog

    def _show_built(self, dialog: ModalDialog) -> None:
        """The inspector's seam: it builds the dialog itself, so a refused one is destroyed."""
        if self._open_dialog(lambda: dialog) is None:
            dialog.close()

    def _confirm(
        self, question: str, then: Callable[[], None], *, label: str | None = None
    ) -> None:
        """Ask ``question`` in a modal dialog; ``then`` runs only when the user confirms."""
        extra = {} if label is None else {"confirm_label": label}
        self._open_dialog(lambda: ConfirmDialog(self.root, question, then, **extra))

    def _ask_name(
        self, current: str, check: Callable[[str], str | None], then: Callable[[str], None]
    ) -> None:
        """Document > Rename window...: a one-line dialog that judges the id before it closes."""
        self._open_dialog(lambda: RenameDialog(self.root, current, check, then))

    def _clipboard_put(self, text: str) -> None:
        """Copy and Cut: the text goes to the system clipboard (readable by other processes)."""
        self.root.clipboard_clear()
        self.root.clipboard_append(text)

    def _clipboard_get(self) -> str:
        """Paste: the clipboard text; "" when it is empty or not text (then: no elements)."""
        try:
            return str(self.root.clipboard_get())
        except tkinter.TclError:
            return ""

    def _toolkit_names(self) -> tuple[str, ...]:
        """Preview > Toolkit: the backends the registry lists (never loaded here), ttkbootstrap
        first; a name outside the id grammar is not offered."""
        listed = {
            b.name for b in self.session.registry.backends() if BACKEND_NAME.fullmatch(b.name)
        }
        return (DEFAULT_BACKEND, *sorted(listed - {DEFAULT_BACKEND}))

    def _canvas_window(self) -> object | None:
        """The window of the visible canvas tab (the paste target when nothing is selected)."""
        stage = self.shell.canvas.current_stage()
        return None if stage is None else stage.window

    def _ask(self, text: Callable[[], str], buttons: list[tuple[str, Answer]]) -> None:
        self._open_dialog(lambda: ChoiceDialog(self.root, text, buttons))

    def _tell(self, text: Callable[[], str]) -> None:
        """An error or information message with one OK button."""
        self._open_dialog(lambda: message_dialog(self.root, text))

    def open_new_file(self) -> None:
        """File > New from template...: the guard, then the template wizard (Ctrl+N)."""
        self.guard(
            lambda: self._open_dialog(lambda: NewFileDialog(self.root, self.new_from_template))
        )

    def open_shortcuts(self) -> None:
        """Help > Keyboard shortcuts...: the cheat-sheet generated from the registry (F1)."""
        self._open_dialog(lambda: ShortcutsDialog(self.root, self.registry))

    def open_plugins(self) -> None:
        """Help > Plugins...: the registry's distributions, their status and problems."""
        self._open_dialog(
            lambda: PluginsDialog(
                self.root,
                self.session.registry,
                self.settings,
                copy=self._clipboard_put,
                save=self._save_settings,
                safe_mode=self.plugins == "all",
            )
        )

    def new_from_template(self, template_id: str) -> bool:
        """Replace the open document with a fresh one made from a template (no guard here: the
        wizard opens only after it).

        Returns:
            False (and a status-bar message) when the template is damaged.
        """
        try:
            self.session.new_from_template(template_id)
        except TemplateError as exc:
            self.message.emit(str(exc))
            return False
        return True

    # ------------------------------------------------------------ guard and files
    def guard(self, then: Callable[[], object]) -> None:
        """Run ``then`` once the open document may be replaced or closed (spec section 10).

        Pending editor text is committed first; a refusal aborts (A15). A dirty document asks
        Save / Don't save / Cancel; Save continues only after a successful write.
        """
        if not self.shell.flush():
            return
        if not self.session.dirty:
            then()
            return
        self._open_dialog(
            lambda: save_changes_dialog(
                self.root,
                lambda: self.session.display_name,
                save=lambda: self.save(then=then),
                discard=then,
            )
        )

    def _folder(self) -> str | None:
        path = self.session.path or (Path(self.recent.entries[0]) if self.recent.entries else None)
        return None if path is None else str(path.parent)

    def open_file(self) -> None:
        """File > Open... (Ctrl+O): the picker first, so cancelling it never asks to save."""
        chosen = file_dialogs.ask_open(self.root, self._folder())
        if chosen:
            self.guard(lambda: self.open_path(Path(chosen)))

    def open_path(self, path: Path) -> bool:
        """Open ``path`` now (spec 9.2); a failure shows why and keeps the current document."""
        try:
            opened = open_document(path)
        except PyGUIbudError as exc:
            self._tell(_lazy(exc))
            return False
        self.session.open_document(
            opened.result,
            path=opened.path,
            stamp=opened.stamp,
            read_only_reason=opened.read_only_reason,
        )
        self._select_first()
        self._remember(opened.path)
        report = self.session.report()
        count = len(opened.result.warnings) + len(report.errors) + len(report.warnings)
        if count:  # rule C1: after the first window is selected
            # Translators: status bar after opening a file; {count} is the number of warnings.
            text = ngettext("Opened with {count} warning.", "Opened with {count} warnings.", count)
            self.message.emit(text.format(count=count))
        elif opened.read_only_reason is not None:
            self.message.emit(_(M_READ_ONLY).format(reason=_(opened.read_only_reason)))
        self._post_notice()
        return True

    def open_recent(self, path: str) -> None:
        """File > Open recent > one entry; a missing file is reported and dropped (A19)."""
        if not os.path.isfile(path):
            self.recent.remove(path)
            self._save_settings()
            self._fill_recent()
            self._tell(lambda: _(_M_MISSING).format(path=path))
            return
        self.guard(lambda: self.open_path(Path(path)))

    def clear_recent(self) -> None:
        """File > Open recent > Clear list."""
        self.recent.clear()
        self._save_settings()
        self._fill_recent()

    def _fill_recent(self) -> None:
        menu = self._recent_menu
        if menu is None:
            return
        menu.delete(0, "end")
        entries = self.recent.entries
        for number, path in enumerate(entries, 1):
            mark = f"_{number}" if number < 10 else "1_0"
            text, underline = split_mnemonic(f"{mark} {path.replace('_', '__')}")
            menu.add_command(label=text, underline=underline,
                             command=functools.partial(self.open_recent, path))  # fmt: skip
        if entries:
            menu.add_separator()
        text, underline = split_mnemonic(_(_M_CLEAR))
        menu.add_command(label=text, underline=underline, command=self.clear_recent,
                         state="normal" if entries else "disabled")  # fmt: skip

    def _remember(self, path: Path) -> None:
        self.recent.add(path)
        self._save_settings()
        self._fill_recent()

    def _select_first(self) -> None:
        document = self.session.document
        if document is not None and document.children:
            self.session.select(document.children[0], origin="session")

    def save(self, *, as_new: bool = False, then: Callable[[], object] | None = None) -> None:
        """File > Save (Ctrl+S) or Save as... (Ctrl+Shift+S); ``then`` runs after a success."""
        if self.session.document is None or not self.shell.flush():
            return
        target = None
        if as_new:
            target = self._ask_target()
            if target is None:
                return
        self._save_to(target, then)

    def _ask_target(self) -> Path | None:
        name = self.session.display_name
        name = name if name.lower().endswith(".ui") else f"{name}.ui"
        chosen = file_dialogs.ask_save(self.root, name, self._folder())
        return Path(chosen) if chosen else None

    def _save_to(self, target: Path | None, then: Callable[[], object] | None) -> None:
        session, stack, document = self.session, self.session.stack, self.session.document
        if stack is None or document is None:
            return
        plan = save_plan(
            document,
            path=session.path,
            stamp=session.stamp,
            read_only=stack.read_only,
            write_protected=session.read_only_reason in SAVE_AS_REASONS,
            error_count=len(session.report().errors),
            target=target,
        )
        if plan.refusal is not None:
            self._tell(lambda: plan.refusal_text() or "")
            return
        if plan.ask_target:
            chosen = self._ask_target()
            if chosen is not None:
                self._save_to(chosen, then)
            return

        def write() -> None:
            self._write(plan, then)

        def check_conflict() -> None:
            if not plan.conflict:
                write()
                return
            self._ask(
                lambda: _(_M_CONFLICT).format(name=session.display_name),
                [(_M_OVERWRITE, write), (_M_SAVE_AS, lambda: self.save(as_new=True, then=then)),
                 (_M_CANCEL, None)],
            )  # fmt: skip

        if plan.error_count:
            # Translators: asked before saving; {count} is the number of errors in the document.
            question = ngettext(
                "The document has {count} error. Save anyway?",
                "The document has {count} errors. Save anyway?",
                plan.error_count,
            ).format(count=plan.error_count)
            self._confirm(question, check_conflict, label=_M_SAVE)
        else:
            check_conflict()

    def _write(self, plan: SavePlan, then: Callable[[], object] | None) -> None:
        """Rebase (undoable), write with a backup, then record the save (spec 9.3 steps 4-5)."""
        stack, document, target = self.session.stack, self.session.document, plan.target
        if stack is None or document is None or target is None:
            return
        rebased = False
        if plan.rebase is not None:
            outcome = stack.execute(plan.rebase)
            if not outcome.accepted:
                self._tell(lambda: outcome.message)
                return
            rebased = True
        try:
            write_ui(document, target, backup=True)
        except XmlIoError as exc:  # still dirty; the recovery snapshot stays (A1, A2)
            if rebased:
                stack.undo()
            # Spec 9.3 step 4: the OS reason, and Save as... to put the work somewhere else.
            save_as = functools.partial(self.save, as_new=True, then=then)
            self._ask(_lazy(exc), [(_M_OK, None), (_M_SAVE_AS, save_as)])
            return
        self.session.mark_saved(target)
        self._remember(target)
        self.message.emit(_(_M_SAVED).format(name=target.name))
        if then is not None:
            then()

    # ------------------------------------------------------------ recovery
    def start(self, path: Path | None = None, *, notice: str | None = None) -> None:
        """The start-up document: the recovery prompt first, then ``path`` or a new document.

        ``notice`` (a msgid, e.g. reset settings) is shown once after the first selection.
        """
        self._notice, self._plugins_due = notice, True
        orphans = self.recovery.scan_orphans() if self.recovery is not None else []
        if orphans:
            self.open_recovery(orphans, later=lambda: self._open_start(path))
        else:
            self._open_start(path)

    def _open_start(self, path: Path | None) -> None:
        if self._disposed:  # the recovery list was closed by the app's own teardown
            return
        if path is not None:
            if not self.open_path(path):
                self._post_notice()
            return
        try:
            self.session.new_from_template("main_window")
        except TemplateError as exc:  # no traceback: the reason goes to the status bar
            _log.error("The start-up document could not be opened: %s", exc)
            self.message.emit(str(exc))
            return
        self._post_notice()

    def _post_notice(self) -> None:
        notice, self._notice = self._notice, None
        due, self._plugins_due = self._plugins_due, False
        # One status line: a settings reset outranks the plugin note (Help > Plugins keeps it).
        text = _(notice) if notice else catalogue_problem()  # e.g. a damaged saved language
        if text is None and due:
            text = plugin_note(self.session.registry, safe_mode=self.plugins == "all")
        if text:
            self.message.emit(text)

    def recover(self) -> None:
        """File > Recover...: the recovery list, or a message when there is nothing to recover."""
        orphans = self.recovery.scan_orphans() if self.recovery is not None else []
        if orphans:
            self.open_recovery(orphans)
        else:
            self.message.emit(_(_M_NOTHING_TO_RECOVER))

    def open_recovery(
        self, entries: list[RecoveryEntry], *, later: Callable[[], None] | None = None
    ) -> None:
        """The recovery list (Restore / Discard / Later)."""

        def confirm(question: str, then: Callable[[], None]) -> None:
            self._open_dialog(
                lambda: ConfirmDialog(self.root, question, then, confirm_label=_M_DISCARD),
                nested=True,
            )

        self._open_dialog(
            lambda: RecoveryDialog(
                self.root, entries, restore=self.restore, confirm=confirm, later=later
            )
        )

    def restore(self, entry: RecoveryEntry, result: ReadResult) -> None:
        """Open a recovered snapshot as an unsaved document of its original file (11.3)."""

        def install() -> None:
            if self._disposed:
                return
            path = Path(entry.path) if entry.path else None
            # The stamp from before the crash, never the file as it is now: a change made by
            # another program since then must still ask before Save overwrites it (A3).
            stamp = (entry.stamp or FileStamp.unknown()) if path is not None else None
            self.session.open_document(result, path=path, dirty=True, stamp=stamp)
            self._select_first()
            if self.recovery is not None and (message := self.recovery.adopt(entry, self.session)):
                self.message.emit(message)
            self._post_notice()

        self.guard(install)

    def _schedule_autosave(self, delay_ms: int | None = None) -> None:
        if self.recovery is None or self._disposed:
            return
        delay = delay_ms if delay_ms is not None else self.settings.autosave_seconds * 1000
        self._autosave_id = self.root.after(delay, self.autosave)

    def autosave(self) -> None:
        """The timer tick: a snapshot of a dirty, changed document (never during a drag).

        While the user types in the inspector or the Variables panel nothing is flushed: a
        half-typed number would turn red and a half-typed variable id would be renamed. The
        snapshot then holds the committed document only (Save, the guard and Copy still flush).
        """
        self._autosave_id = None
        if self.recovery is None or self._disposed:
            return
        if self.shell.drag.state != "idle":
            self._schedule_autosave(_RETRY_MS)
            return
        if not self.shell.typing():
            self.shell.flush()
        message = self.recovery.autosave(self.session)
        if message:
            self.message.emit(message)
        self._schedule_autosave()

    # ------------------------------------------------------------ settings
    def _save_settings(self) -> None:
        if self._persist:
            self.settings.recent_files = self.recent.entries
            if not save_settings(self.settings, removed=self.recent.removed) and (
                not self._settings_warned
            ):
                self._settings_warned = True
                self.message.emit(_(_M_SETTINGS_NOT_SAVED))

    def restore_window(self) -> None:
        """Apply the stored geometry, clamped to the desktop (before the window is shown)."""
        geometry = self.settings.geometry
        if geometry:
            fitted = fit_geometry(geometry, *desktop_bounds(self.root))
            if fitted is not None:
                self.root.geometry(fitted)

    def restore_zoom(self) -> None:
        """Maximise the window again when it was maximised at Quit (after it is shown)."""
        if self.settings.zoomed:
            try:
                self.root.state("zoomed")
            except tkinter.TclError:  # X11 has no "zoomed" state
                with contextlib.suppress(tkinter.TclError):
                    self.root.attributes("-zoomed", True)

    def _restore_sashes(self, _event: object = None) -> None:
        """At the first real size: put the stored sashes back, then keep every panel visible."""
        if self._sashes_done or self.shell.body.winfo_width() <= 1:
            return
        self._sashes_done = True
        if self.settings.sashes:
            self.root.after_idle(self._apply_sashes)

    def _apply_sashes(self) -> None:
        if self._disposed:
            return
        for key, paned in (("main", self.shell.body), ("right", self.shell.right)):
            count = len(paned.panes()) - 1
            for index, position in enumerate(self.settings.sashes.get(key, ())[:count]):
                paned.sashpos(index, position)
        self.shell.clamp_sashes()

    def _remember_window(self) -> None:
        """Store geometry, maximised state and sashes (once, at Quit)."""
        try:
            state = str(self.root.state())
            self.settings.zoomed = state == "zoomed"
            if state == "normal":
                self.settings.geometry = str(self.root.geometry())
            self.settings.sashes = {
                key: tuple(int(paned.sashpos(i)) for i in range(len(paned.panes()) - 1))
                for key, paned in (("main", self.shell.body), ("right", self.shell.right))
            }
        except tkinter.TclError:
            _log.debug("The window state could not be read", exc_info=True)

    # ------------------------------------------------------------ lifecycle
    def quit(self) -> None:
        """Close the designer after the unsaved-changes guard (Ctrl+Q, the window's X)."""

        def leave() -> None:
            self._remember_window()
            self._save_settings()
            self.on_exit()

        self.guard(leave)

    def _destroy(self) -> None:
        self.dispose()
        self.root.destroy()

    def shutdown(self, *, interrupted: bool) -> None:
        """The end of ``run``: Ctrl+C keeps a snapshot of a dirty document (A16), no dialog."""
        keep = False
        if interrupted and self.recovery is not None and self.session.dirty:
            self.recovery.autosave(self.session, force=True)
            keep = True
        self.dispose()
        if self.recovery is not None:
            self.recovery.close(keep_snapshot=keep)

    def dispose(self) -> None:
        """Disconnect everything that outlives the widgets (listeners, pending callbacks)."""
        if self._disposed:
            return
        self._disposed = True
        remove_language_listener(self._on_language)
        self._disconnect_title()
        for dialog in self._live_dialogs():
            dialog.close()
        self._cancel_idle()
        if self._autosave_id is not None:
            with contextlib.suppress(tkinter.TclError):
                self.root.after_cancel(self._autosave_id)
            self._autosave_id = None
        self.preview.dispose()
        self.exporter.dispose()
        self.shell.dispose()


def _lazy(error: PyGUIbudError) -> Callable[[], str]:
    """The error's message, translated when shown (also after a language switch)."""
    return lambda: str(error)


def fit_geometry(
    geometry: str, screen_width: int, screen_height: int, left: int = 0, top: int = 0
) -> str | None:
    """``geometry`` (``WxH+X+Y``) shrunk to the desktop, or None when too little would show.

    The desktop is ``screen_width`` x ``screen_height`` pixels from ``(left, top)``, which is
    negative when a monitor lies left of or above the primary one. At least 200 x 150 pixels of
    the window must lie on it (A10: a removed monitor). The position is always written as
    ``+X+Y``: Tk reads ``-X`` as a distance from the right edge.
    """
    match = _GEOMETRY.fullmatch(geometry)
    if match is None:
        return None
    width, height = min(int(match[1]), screen_width), min(int(match[2]), screen_height)
    x, y = int(match[3].removeprefix("+")), int(match[4].removeprefix("+"))
    visible_x = min(x + width, left + screen_width) - max(x, left)
    visible_y = min(y + height, top + screen_height) - max(y, top)
    if visible_x < _MIN_VISIBLE[0] or visible_y < _MIN_VISIBLE[1]:
        return None
    return f"{width}x{height}+{x}+{y}"


def _style() -> Any:  # noqa: ANN401 - ttkbootstrap's Style is untyped
    from ttkbootstrap import Style

    style = Style.get_instance()
    if style is None:
        raise RuntimeError("the root was not created with ttkbootstrap")
    return style


def apply_app_icon(root: tkinter.Tk) -> tkinter.PhotoImage | None:
    """Make the brand icon the default of every designer window (root and dialogs).

    Without the brand file, or when Tk rejects it, ttkbootstrap's default icon stays. The
    image is kept on the root: a garbage-collected PhotoImage silently drops the icon.
    """
    data = load_app_icon()
    if data is None:
        return None
    try:
        image = tkinter.PhotoImage(master=root, data=base64.b64encode(data).decode("ascii"))
        root.iconphoto(True, image)  # True: also the default of every later Toplevel
    except tkinter.TclError as exc:
        _log.warning("Brand icon ignored: %s", exc)
        return None
    root._pyguibud_icon = image  # type: ignore[attr-defined]  # keep it alive
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_APP_USER_MODEL_ID)
        except (AttributeError, OSError):
            pass
    return image


def run(
    lang: str | None, theme: str | None, *, path: Path | None = None, no_plugins: bool = False
) -> int:
    """Create the root, show the designer and run its main loop (see ``designer.launch``).

    ``lang`` and ``theme`` are None when not given on the command line: the settings decide.
    ``no_plugins`` is safe mode; otherwise ``Settings.disabled_plugins`` are not loaded.
    """
    from ttkbootstrap import App

    from pyguibud.designer import report_cannot_open

    settings, problem = load_settings()
    # Before anything reads the registry: a disabled plugin is never imported (D7).
    plugins: Collection[str] | Literal["all"] = "all" if no_plugins else settings.disabled_plugins
    configure_default_registry(plugins)
    code = resolve_language(lang, settings)
    if code != get_language():
        with contextlib.suppress(ValueError):
            set_language(code)
    try:
        root = App(title=_(_M_TITLE))
    except tkinter.TclError as exc:  # no display
        return report_cannot_open(exc, tk_missing=False)
    root.withdraw()
    apply_app_icon(root)
    app: DesignerApp | None = None
    interrupted: list[bool] = []

    def on_interrupt(_signum: int, _frame: object) -> None:
        interrupted.append(True)
        root.quit()  # leave the main loop; the clean-up below runs as for a normal close

    previous = _set_sigint(on_interrupt)
    recovery = RecoverySession()
    recovery.start()
    sweep_stale()  # preview folders a crashed designer left behind (spec preview-export 4.3)
    try:
        role = resolve_theme(theme, settings)
        app = DesignerApp(root, role=role, settings=settings, recovery=recovery, plugins=plugins)
        root.protocol("WM_DELETE_WINDOW", app.quit)
        app.restore_window()
        _heartbeat(root)
        if not interrupted:  # Ctrl+C during start-up: Tk would forget that quit request
            root.deiconify()
            app.restore_zoom()
            app.start(path, notice=problem)
            root.mainloop()
    except KeyboardInterrupt:
        interrupted.append(True)
    finally:
        _set_sigint(previous)
        if app is not None:
            app.shutdown(interrupted=bool(interrupted))
        else:
            recovery.close()
        try:
            root.destroy()
        except tkinter.TclError:
            _log.debug("The root was already destroyed", exc_info=True)
    return 130 if interrupted else 0


#: How often (ms) the idle main loop wakes up, so that Ctrl+C in the console is noticed.
_HEARTBEAT_MS = 200


def _heartbeat(root: Any) -> None:  # noqa: ANN401 - the app root
    """Keep the Tk loop running Python code: a blocked loop only sees Ctrl+C at the next event."""

    def beat() -> None:
        try:
            root.after(_HEARTBEAT_MS, beat)
        except tkinter.TclError:  # the root is gone
            return

    beat()


def _set_sigint(handler: Any) -> Any:  # noqa: ANN401 - a signal handler or None
    """Install a SIGINT handler and return the previous one (None: not possible here)."""
    if handler is None:
        return None
    try:
        return signal.signal(signal.SIGINT, handler)
    except ValueError:  # not the main thread (embedded use): keep the default behaviour
        return None
