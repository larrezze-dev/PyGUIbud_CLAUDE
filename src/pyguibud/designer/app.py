"""The designer application window (Tk). Imported only from :func:`pyguibud.designer.launch`."""

from __future__ import annotations

import base64
import logging
import signal
import sys
import tkinter
from collections.abc import Callable
from typing import Any

from pyguibud.core import default_registry
from pyguibud.designer.actions import ActionRegistry
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.dialogs.confirm import ConfirmDialog
from pyguibud.designer.dialogs.new_file import NewFileDialog
from pyguibud.designer.dialogs.shortcuts import ShortcutsDialog
from pyguibud.designer.edit import EditActions
from pyguibud.designer.session import DesignerSession, TemplateError
from pyguibud.designer.shell import Shell
from pyguibud.designer.signals import Signal
from pyguibud.designer.standard_actions import ShellCallbacks, register_standard_actions
from pyguibud.designer.theme import ThemeSpec, load_app_icon, load_theme_specs, spec_for_role
from pyguibud.i18n import (
    N_,
    _,
    add_language_listener,
    get_language,
    remove_language_listener,
    set_language,
)

__all__ = ["CLI_THEMES", "DesignerApp", "apply_app_icon", "run"]

_log = logging.getLogger(__name__)

_M_TITLE = N_("PyGUIbud designer")
_M_UNKNOWN_THEME = N_("There is no theme called '{theme}'.")
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
    ) -> None:
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

        theme_tk.install_themes(_style(), self.specs)
        first = spec_for_role(self.specs, role) or self.specs[0]
        theme_tk.apply_fonts(root, first)
        theme_tk.use_theme(root, first)
        self.role = first.role
        root.minsize(*(theme_tk.scaled(root, size) for size in _MIN_SIZE))

        self.registry = ActionRegistry()
        register_standard_actions(
            self.registry,
            ShellCallbacks(
                new_document=self.open_new_file,
                show_shortcuts=self.open_shortcuts,
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
                ),
            ),
        )
        self.shell = Shell(
            root, self.session, self.registry, ring_px=theme_tk.scaled(root, _RING_PX)
        )
        self.message.connect(self.shell.show_message)
        self.registry.message.connect(self.shell.show_message)
        self.shell.restyle(first)
        self.retranslate()
        add_language_listener(self._on_language)

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

    def _on_language(self, _code: str) -> None:
        """The single i18n listener of the app: menus, toolbar, panels, title, status bar.

        Every step is isolated, so one failing panel never blocks the others.
        """
        steps: list[tuple[str, Callable[[], None]]] = [
            ("status message", self.shell.clear_message),  # first: keep messages of the switch
            ("menus", self.shell.retranslate_menus),
            ("toolbar", self.shell.retranslate_toolbar),
        ]
        steps += [(f"{panel.name} panel", panel.retranslate) for panel in self.shell.panels]
        steps += [("title", self.retranslate), ("status bar", self.shell.retranslate_status)]
        steps += [("dialog", dialog.retranslate) for dialog in self._live_dialogs()]
        for name, step in steps:
            try:
                step()
            except Exception:
                _log.exception("Retranslating failed in the %s", name)

    def retranslate(self) -> None:
        """Re-apply the translated texts of the window."""
        self.root.title(_(_M_TITLE))

    # ------------------------------------------------------------ dialogs and actions
    def _live_dialogs(self) -> list[ModalDialog]:
        self._dialogs = [d for d in self._dialogs if not d.closed]
        return list(self._dialogs)

    def _open_dialog(self, factory: Callable[[], ModalDialog]) -> None:
        """Open a dialog unless one is already open (then raise that one: one modal at a time)."""
        live = self._live_dialogs()
        if live:
            live[-1].window.lift()
            return
        dialog = factory()
        self._dialogs.append(dialog)
        dialog.open()

    def _confirm(self, question: str, then: Callable[[], None]) -> None:
        """Ask ``question`` in a modal dialog; ``then`` runs only when the user confirms."""
        self._open_dialog(lambda: ConfirmDialog(self.root, question, then))

    def open_new_file(self) -> None:
        """File > New from template...: the template wizard (Ctrl+N)."""
        self._open_dialog(lambda: NewFileDialog(self.root, self.new_from_template))

    def open_shortcuts(self) -> None:
        """Help > Keyboard shortcuts...: the cheat-sheet generated from the registry (F1)."""
        self._open_dialog(lambda: ShortcutsDialog(self.root, self.registry))

    def new_from_template(self, template_id: str) -> bool:
        """Replace the open document with a fresh one made from a template.

        Returns:
            False (and a status-bar message) when the document may not be discarded or the
            template is damaged.
        """
        if not self.session.can_discard():
            return False
        try:
            self.session.new_from_template(template_id)
        except TemplateError as exc:
            self.message.emit(str(exc))
            return False
        return True

    # ------------------------------------------------------------ lifecycle
    def quit(self) -> None:
        """Close the designer if the open document may be discarded."""
        if not self.session.can_discard():
            return
        self.dispose()
        self.root.destroy()

    def dispose(self) -> None:
        """Disconnect everything that outlives the widgets (listeners, pending callbacks)."""
        if self._disposed:
            return
        self._disposed = True
        remove_language_listener(self._on_language)
        for dialog in self._live_dialogs():
            dialog.close()
        self._cancel_idle()
        self.shell.dispose()


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


def run(lang: str, theme: str) -> int:
    """Create the root, show the designer and run its main loop (see ``designer.launch``)."""
    del lang  # the language is already active in pyguibud.i18n
    from ttkbootstrap import App

    from pyguibud.designer import report_cannot_open

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
    try:
        app = DesignerApp(root, role=CLI_THEMES.get(theme, "light"))
        root.protocol("WM_DELETE_WINDOW", app.quit)
        try:
            app.session.new_from_template("main_window")
        except TemplateError as exc:  # no traceback: the reason goes to the status bar
            _log.error("The start-up document could not be opened: %s", exc)
            app.message.emit(str(exc))
        _heartbeat(root)
        if not interrupted:  # Ctrl+C during start-up: Tk would forget that quit request
            root.deiconify()
            root.mainloop()
    except KeyboardInterrupt:
        interrupted.append(True)
    finally:
        _set_sigint(previous)
        if app is not None:
            app.dispose()
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
