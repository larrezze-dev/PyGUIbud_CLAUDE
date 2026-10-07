"""The main window layout: menubar, toolbar, four panels and a status bar (Tk).

Menus, toolbar buttons and key bindings are all generated from the :class:`ActionRegistry`.
The shell stores msgids and registry entries, never translated text: ``retranslate_*`` re-reads
them, so a live language switch needs no rebuild.
"""

from __future__ import annotations

import logging
import tkinter
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from pyguibud.core.keys import split_mnemonic, tk_shortcut
from pyguibud.designer.actions import ActionDef, ActionRegistry, MenuDef, Separator, label_of
from pyguibud.designer.canvas.drag import DragController
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.panels.canvas import CanvasPanel
from pyguibud.designer.panels.inspector import InspectorPanel
from pyguibud.designer.panels.palette import PalettePanel
from pyguibud.designer.panels.tree import TreePanel
from pyguibud.designer.present.focus import cycle
from pyguibud.designer.present.status import findings_summary, selection_path
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.theme import ThemeSpec
from pyguibud.i18n import _

__all__ = ["MESSAGE_MS", "Shell"]

_log = logging.getLogger(__name__)

#: How long a transient status-bar message stays (milliseconds).
MESSAGE_MS = 5000

#: Text-input classes keep their own keys: the document's undo must not steal a typed Ctrl+Z.
_TEXT_CLASSES = frozenset({"TEntry", "Entry", "Text", "TCombobox", "TSpinbox", "Spinbox"})
_TEXT_OWNED = frozenset({"edit.undo", "edit.redo"})

_Entry = tuple[tkinter.Menu, int, "ActionDef | MenuDef"]


def _is_text_input(widget: object) -> bool:
    try:
        return widget.winfo_class() in _TEXT_CLASSES  # type: ignore[attr-defined]
    except (AttributeError, tkinter.TclError):
        return False


class Shell:
    """Builds the window contents on ``root``; :meth:`dispose` removes them again."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - a ttkbootstrap App (or the tests' shared root)
        session: DesignerSession,
        registry: ActionRegistry,
        *,
        ring_px: int = 2,
    ) -> None:
        self.root = root
        self.session = session
        self.registry = registry
        self.aqua = str(root.tk.call("tk", "windowingsystem")) == "aqua"
        self._menus: list[tkinter.Menu] = []
        self._entries: list[_Entry] = []
        self._radio: dict[str, tkinter.StringVar] = {}
        self._buttons: list[tuple[ttk.Button, ActionDef]] = []
        self._bound: list[str] = []
        self._active = -1  # index in ``panels`` of the panel that holds the focus, or -1
        self._message = ""
        self._message_id: str | None = None
        self._clamp_id: str | None = None
        self._disposed = False

        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)
        self._build_menubar()
        self.toolbar = self._build_toolbar()
        self.toolbar.grid(row=0, column=0, sticky="ew")

        self.body = ttk.PanedWindow(root, orient="horizontal")
        self.right = ttk.PanedWindow(self.body, orient="vertical")
        self.palette = PalettePanel(self.body, session, ring_px=ring_px)
        self.canvas = CanvasPanel(self.body, session, ring_px=ring_px)
        self.inspector = InspectorPanel(self.right, session, ring_px=ring_px)
        self.tree = TreePanel(self.right, session, ring_px=ring_px, on_full_text=self.show_message)
        self.right.add(self.inspector.frame, weight=1)
        self.right.add(self.tree.frame, weight=1)
        self.body.add(self.palette.frame, weight=0)
        self.body.add(self.canvas.frame, weight=1)
        self.body.add(self.right, weight=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.drag = DragController(self.canvas, status=self.show_message, source=self.palette.tree)
        self.palette.drag = self.drag

        bar = ttk.Frame(root, padding=(6, 2))
        bar.columnconfigure(0, weight=1)
        self._status = ttk.Label(bar, anchor="w")
        self._summary = ttk.Label(bar, anchor="e")
        self._status.grid(row=0, column=0, sticky="ew")
        self._summary.grid(row=0, column=1, sticky="e", padx=(12, 0))
        bar.grid(row=2, column=0, sticky="ew")
        self.statusbar = bar

        self._disconnects = [
            session.selection_changed.connect(lambda _s: self._refresh_status()),
            session.report_changed.connect(lambda _r: self._on_report()),
            session.document_changed.connect(lambda _d: self._refresh_status()),
        ]
        self._bind_shortcuts()
        root.bind_all("<FocusIn>", self._on_focus_in, add="+")
        self._keep_panels_visible()
        self.refresh_states()
        self._refresh_status()
        self._refresh_summary()

    @property
    def panels(self) -> list[PanelBase]:
        """The four panels in focus-cycle order: palette, canvas, tree, inspector."""
        return [self.palette, self.canvas, self.tree, self.inspector]

    # ------------------------------------------------------------ menus
    def _build_menubar(self) -> None:
        self.menubar = tkinter.Menu(self.root, tearoff=False)
        self._menus.append(self.menubar)
        for menu_id in self.registry.menu_ids():
            definition = self.registry.menu(menu_id)
            if definition.parent is None:
                self._add_cascade(self.menubar, definition)
        self.root.configure(menu=self.menubar)

    def _add_cascade(self, parent: tkinter.Menu, definition: MenuDef) -> None:
        sub = tkinter.Menu(parent, tearoff=False, postcommand=self.refresh_states)
        self._menus.append(sub)
        text, underline = split_mnemonic(_(definition.label))
        parent.add_cascade(label=text, underline=underline, menu=sub)
        self._entries.append((parent, int(parent.index("end") or 0), definition))
        for item in self.registry.menu_items(definition.id):
            if isinstance(item, Separator):
                sub.add_separator()
            elif isinstance(item, MenuDef):
                self._add_cascade(sub, item)
            else:
                self._add_action(sub, item)

    def _add_action(self, menu: tkinter.Menu, action: ActionDef) -> None:
        text, underline = split_mnemonic(label_of(action))
        options: dict[str, Any] = {
            "label": text,
            "underline": underline,
            "command": lambda: self.registry.invoke(action.id),
        }
        if action.shortcut is not None:
            options["accelerator"] = tk_shortcut(action.shortcut, aqua=self.aqua).accelerator
        if action.checked is not None:
            variable = self._radio.setdefault(action.menu, tkinter.StringVar(self.root))
            menu.add_radiobutton(variable=variable, value=action.id, **options)
        else:
            menu.add_command(**options)
        self._entries.append((menu, int(menu.index("end") or 0), action))

    def refresh_states(self) -> None:
        """Bring enabled state and radio selection of every menu entry and button up to date."""
        for menu, index, item in self._entries:
            if not isinstance(item, ActionDef):
                continue
            state = "normal" if self.registry.is_enabled(item) else "disabled"
            menu.entryconfigure(index, state=state)
            if item.dynamic_label is not None:
                text, underline = split_mnemonic(label_of(item))
                menu.entryconfigure(index, label=text, underline=underline)
            variable = self._radio.get(item.menu)
            if variable is not None and self.registry.is_checked(item):
                variable.set(item.id)
        for button, action in self._buttons:
            button.state(["!disabled"] if self.registry.is_enabled(action) else ["disabled"])

    def retranslate_menus(self) -> None:
        """Re-read every label and mnemonic from the registry in the current language."""
        for menu, index, item in self._entries:
            if isinstance(item, MenuDef):
                text, underline = split_mnemonic(_(item.label))
            else:
                text, underline = split_mnemonic(label_of(item))
            menu.entryconfigure(index, label=text, underline=underline)
        self.refresh_states()

    # ------------------------------------------------------------ toolbar
    def _build_toolbar(self) -> ttk.Frame:
        bar = ttk.Frame(self.root, padding=(4, 2))
        for action in self.registry.actions():
            if not action.toolbar:
                continue
            button = ttk.Button(
                bar,
                text=split_mnemonic(label_of(action))[0],
                command=self._invoker(action.id),
                takefocus=True,
            )
            button.pack(side="left", padx=2)
            self._buttons.append((button, action))
        return bar

    def retranslate_toolbar(self) -> None:
        """Re-read the toolbar button texts."""
        for button, action in self._buttons:
            button.configure(text=split_mnemonic(label_of(action))[0])

    # ------------------------------------------------------------ keys
    def _bind_shortcuts(self) -> None:
        scoped = {"canvas": self.canvas.notebook, "tree": self.tree.tree}
        for action in self.registry.actions():
            handler = self._key_handler(action.id)
            widgets = [scoped[name] for name in action.scope]  # empty: every widget (bind_all)
            for chord in action.chords:
                for sequence in tk_shortcut(chord, aqua=self.aqua).sequences:
                    for widget in widgets:
                        widget.bind(sequence, handler, add="+")
                    if not widgets:
                        self.root.bind_all(sequence, handler)
                        self._bound.append(sequence)

    def _invoker(self, action_id: str) -> Callable[[], None]:
        def run() -> None:
            self.registry.invoke(action_id)

        return run

    def _key_handler(self, action_id: str) -> Any:  # noqa: ANN401 - a Tk callback
        def handler(event: object) -> str | None:
            widget = getattr(event, "widget", None)
            if not self._in_main_window(widget):
                return None  # a dialog is open: its keys are its own
            if action_id in _TEXT_OWNED and _is_text_input(widget):
                return None
            if not self.registry.invoke(action_id):  # disabled: say why, when it can
                self._explain_refusal(action_id)
            return "break"

        return handler

    def _explain_refusal(self, action_id: str) -> None:
        action = self.registry.get(action_id)
        if action is None or action.refusal is None:
            return
        reason = action.refusal()
        if reason:
            self.show_message(reason)

    # ------------------------------------------------------------ panel focus
    def _in_main_window(self, widget: object) -> bool:
        """Whether ``widget`` belongs to the main window (not to a dialog)."""
        if widget is None:
            return True  # a synthetic call without an event
        try:
            return str(widget.winfo_toplevel()) == str(self.root.winfo_toplevel())  # type: ignore[attr-defined]
        except (AttributeError, tkinter.TclError):
            return False

    def _panel_index_of(self, widget: object) -> int:
        """Index of the panel containing ``widget`` (a Tk path prefix test), or -1."""
        path = str(widget)
        for index, panel in enumerate(self.panels):
            frame = str(panel.frame)
            if path == frame or path.startswith(frame + "."):
                return index
        return -1

    def _on_focus_in(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self._disposed or not self._in_main_window(event.widget):
            return
        index = self._panel_index_of(event.widget)
        if str(event.widget) == str(self.root.winfo_toplevel()):
            return  # the window itself gained the focus; the focused child follows
        self._mark(index)

    def _mark(self, active: int) -> None:
        """Draw the focus-within ring around panel ``active`` only (-1 = none)."""
        self._active = active
        for index, panel in enumerate(self.panels):
            panel.frame.mark(index == active)

    @property
    def active_panel(self) -> int:
        """Index in :attr:`panels` of the panel holding the focus, or -1."""
        return self._active

    def cycle_focus(self, delta: int) -> None:
        """Move the focus to the next (+1) or previous (-1) panel, wrapping around."""
        panels = self.panels
        target = cycle(self._active, delta, len(panels))
        if target < 0:
            return
        panels[target].focus_first()
        self._mark(target)

    # ------------------------------------------------------------ sashes
    def _keep_panels_visible(self) -> None:
        """Re-check the sashes whenever a pane or the window changes size (spec section 9)."""
        for paned in (self.body, self.right):
            for sequence in ("<Configure>", "<ButtonRelease-1>"):
                paned.bind(sequence, self._schedule_clamp, add="+")
            for pane in self._panes(paned):
                pane.bind("<Configure>", self._schedule_clamp, add="+")

    def _panes(self, paned: Any) -> list[Any]:  # noqa: ANN401 - a ttk PanedWindow
        return [self.root.nametowidget(str(pane)) for pane in paned.panes()]

    def _schedule_clamp(self, _event: object = None) -> None:
        if self._clamp_id is None and not self._disposed:
            self._clamp_id = self.root.after_idle(self.clamp_sashes)

    def _minimum(self, pane: Any, horizontal: bool) -> int:  # noqa: ANN401 - a Tk widget
        """The smallest extent of a pane: its panel heading (and a row) must stay visible."""
        panels = [p for p in self.panels if p.frame is pane or str(p.frame).startswith(f"{pane}.")]
        if not panels:
            return 0
        if horizontal:
            return max(p.heading.winfo_reqwidth() for p in panels) + 24
        return max(p.heading.winfo_reqheight() for p in panels) * 3

    def clamp_sashes(self) -> None:
        """Move any sash that hides a panel back, so no panel collapses below its heading."""
        self._clamp_id = None
        if self._disposed:
            return
        try:
            for paned in (self.body, self.right):
                self._clamp(paned, horizontal=paned is self.body)
        except tkinter.TclError:  # the window is being destroyed
            _log.debug("Could not check the sashes", exc_info=True)

    def _clamp(self, paned: Any, *, horizontal: bool) -> None:  # noqa: ANN401 - a ttk widget
        panes = self._panes(paned)
        size = paned.winfo_width() if horizontal else paned.winfo_height()
        if len(panes) < 2 or size <= 1:
            return
        minimum = [self._minimum(pane, horizontal) for pane in panes]
        positions = [int(paned.sashpos(index)) for index in range(len(panes) - 1)]
        start = panes[1].winfo_x() if horizontal else panes[1].winfo_y()
        sash = max(1, start - positions[0]) if start > positions[0] else 5
        wanted = list(positions)
        for index in range(len(wanted)):  # every pane keeps its minimum on its far side ...
            before = wanted[index - 1] + sash if index else 0
            wanted[index] = max(wanted[index], before + minimum[index])
        for index in reversed(range(len(wanted))):  # ... and the next pane on its near side
            after = wanted[index + 1] if index + 1 < len(wanted) else size + sash
            wanted[index] = min(wanted[index], after - sash - minimum[index + 1])
        for index, (old, new) in enumerate(zip(positions, wanted, strict=True)):
            if new != old:
                paned.sashpos(index, max(0, new))

    # ------------------------------------------------------------ status bar
    def show_message(self, text: str) -> None:
        """Show a transient message in the status bar for a few seconds."""
        if self._disposed:
            return
        self._cancel_message_timer()
        self._message = text
        self._refresh_status()
        self._message_id = self.root.after(MESSAGE_MS, self.clear_message)

    def clear_message(self) -> None:
        """Drop the transient message (also on a language switch: it would stay untranslated)."""
        self._cancel_message_timer()
        self._message = ""
        if not self._disposed:
            self._refresh_status()

    def _cancel_message_timer(self) -> None:
        if self._message_id is not None:
            try:
                self.root.after_cancel(self._message_id)
            except tkinter.TclError:
                _log.debug("after_cancel failed", exc_info=True)
            self._message_id = None

    def _refresh_status(self) -> None:
        text = self._message or selection_path(self.session.selection.node, self.session.document)
        self._status.configure(text=text)

    def _on_report(self) -> None:
        self._refresh_summary()
        self.refresh_states()  # the Undo/Redo labels and the enabled state follow the stack

    def _refresh_summary(self) -> None:
        self._summary.configure(text=findings_summary(self.session.report()))

    def retranslate_status(self) -> None:
        """Re-render the validator summary (the selection path is not translated)."""
        self._refresh_summary()
        self._refresh_status()

    # ------------------------------------------------------------ theme
    def restyle(self, spec: ThemeSpec) -> None:
        """Recolour what ttk styling does not reach: plain-Tk menus and the focus rings."""
        colours = spec.colors
        for menu in self._menus:
            try:
                menu.configure(
                    background=colours["bg"],
                    foreground=colours["fg"],
                    activebackground=colours["selectbg"],
                    activeforeground=colours["selectfg"],
                )
            except tkinter.TclError:
                _log.debug("Could not recolour a menu", exc_info=True)
        for panel in self.panels:
            panel.restyle(spec)

    # ------------------------------------------------------------ lifecycle
    def dispose(self) -> None:
        """Remove everything this shell added to the (possibly shared) root."""
        if self._disposed:
            return
        self._disposed = True
        self._cancel_message_timer()
        if self._clamp_id is not None:
            try:
                self.root.after_cancel(self._clamp_id)
            except tkinter.TclError:
                _log.debug("after_cancel failed", exc_info=True)
            self._clamp_id = None
        for disconnect in self._disconnects:
            disconnect()
        self.drag.dispose()
        for panel in self.panels:
            panel.dispose()
        try:
            for sequence in (*self._bound, "<FocusIn>"):
                self.root.unbind_all(sequence)
            self.root.configure(menu="")
            for widget in (self.menubar, self.toolbar, self.body, self.statusbar):
                widget.destroy()
        except tkinter.TclError:  # the root is already gone
            _log.debug("The window was already destroyed", exc_info=True)
