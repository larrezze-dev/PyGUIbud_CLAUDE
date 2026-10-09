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
from pyguibud.designer.panels.variables import VariablesPanel
from pyguibud.designer.present.focus import cycle
from pyguibud.designer.present.status import findings_summary, selection_path
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.theme import ThemeSpec
from pyguibud.i18n import _, ngettext

__all__ = ["MESSAGE_MS", "Shell"]

_log = logging.getLogger(__name__)

#: How long a transient status-bar message stays (milliseconds).
MESSAGE_MS = 5000

#: Text-input classes keep their own keys: the document's undo must not steal a typed Ctrl+Z.
_TEXT_CLASSES = frozenset({"TEntry", "Entry", "Text", "TCombobox", "TSpinbox", "Spinbox"})
_TEXT_OWNED = frozenset({"edit.undo", "edit.redo"})
#: Act once per physical key press: a held Delete or Ctrl+X must not cascade onto the parent
#: that the removal selects (QA-13b-04), nor a held Ctrl+V/Ctrl+D multiply the pasted widgets.
_ONCE_PER_PRESS = frozenset({"edit.delete", "edit.cut", "edit.paste", "edit.duplicate"})
#: Actions that first commit the inspector's pending text (spec 14a 3.3, risk R2): every one
#: that reads or edits the document, so the typed value is one step of its own (undone after
#: the action) and a refused value stops the action with its reason (A15, QA-14a2-02).
_FLUSH_FIRST = frozenset(
    {
        "edit.undo",
        "edit.redo",
        "edit.copy",
        "edit.cut",
        "edit.paste",
        "edit.duplicate",
        "edit.delete",
        "document.rename",
        "document.delete",
    }
)
_FLUSH_FIRST_GROUPS = ("edit.insert.", "document.add_")


def _flush_first(action_id: str) -> bool:
    return action_id in _FLUSH_FIRST or action_id.startswith(_FLUSH_FIRST_GROUPS)


def unique_mnemonics(entries: list[tuple[str, int]]) -> list[int]:
    """One access key per entry of a menu, none shared (QA-14a2-03).

    The tree's context menu merges Edit > Insert and the clipboard group, whose translated
    mnemonics may clash. Each entry keeps its own key while it is free (in menu order); a
    clashing one moves to the first free letter or digit of its label, else it has none (-1).
    """
    taken: set[str] = set()
    result: list[int] = []
    for label, underline in entries:
        key = label[underline].lower() if 0 <= underline < len(label) else ""
        if key and key not in taken:
            taken.add(key)
            result.append(underline)
        else:
            result.append(-2)  # decided in the second pass
    for k, (label, _underline) in enumerate(entries):
        if result[k] != -2:
            continue
        free = next((i for i, c in enumerate(label) if c.isalnum() and c.lower() not in taken), -1)
        if free >= 0:
            taken.add(label[free].lower())
        result[k] = free
    return result


#: The actions of the object tree's context menu after the Insert group.
_TREE_MENU = ("edit.cut", "edit.copy", "edit.paste", "edit.duplicate", "edit.delete")

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
        #: Every sub-menu by its MenuDef id (the app fills "file.recent" itself).
        self.submenus: dict[str, tkinter.Menu] = {}
        self._entries: list[_Entry] = []
        self._radio: dict[str, tkinter.StringVar] = {}
        self._buttons: list[tuple[ttk.Button, ActionDef]] = []
        self._bound: list[str] = []
        self._held: tuple[str, str, int] | None = None  # (keysym, widget, release time or -1)
        self._active = -1  # index in ``panels`` of the panel that holds the focus, or -1
        self._message = ""
        self._in_command = False  # a command's own selection change keeps its message
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
        # D10: the object tree and the Variables tab share one pane (one F6 stop).
        self.side: Any = ttk.Notebook(self.right, takefocus=False)
        self.tree = TreePanel(self.side, session, ring_px=ring_px, on_full_text=self.show_message)
        self.variables = VariablesPanel(self.side, session, ring_px=ring_px)
        self.side.add(self.tree.frame, text=_(self.tree.HEADING))
        self.side.add(self.variables.frame, text=_(self.variables.HEADING))
        self.right.add(self.inspector.frame, weight=1)
        self.right.add(self.side, weight=1)
        self.inspector.status = self.variables.status = self._post
        self.inspector.invoke = self.variables.invoke = lambda action: self._invoker(action)()
        self.body.add(self.palette.frame, weight=0)
        self.body.add(self.canvas.frame, weight=1)
        self.body.add(self.right, weight=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.drag = DragController(self.canvas, status=self.show_message, source=self.palette.tree)
        self.palette.drag = self.drag
        self.canvas.drag = self.drag
        self.canvas.status = self.show_message

        bar = ttk.Frame(root, padding=(6, 2))
        bar.columnconfigure(0, weight=1)
        self._status = ttk.Label(bar, anchor="w")
        self._summary = ttk.Label(bar, anchor="e")
        self._status.grid(row=0, column=0, sticky="ew")
        self._summary.grid(row=0, column=1, sticky="e", padx=(12, 0))
        bar.grid(row=2, column=0, sticky="ew")
        self.statusbar = bar

        self._disconnects = [
            # A new selection supersedes a transient message about the old one (QA-13b-11),
            # except the selection a command makes itself (QA-13b-12: "Drag cancelled.").
            session.selection_changed.connect(lambda _s: self._on_selection()),
            session.report_changed.connect(lambda _r: self._on_report()),
            session.document_changed.connect(lambda _d: self._refresh_status()),
        ]
        self._bind_shortcuts()
        self._build_tree_menu()
        root.bind_all("<FocusIn>", self._on_focus_in, add="+")
        for sequence, step in (("<Control-Tab>", 1), ("<Control-Shift-Tab>", -1)):
            root.bind_all(sequence, lambda e, d=step: self._switch_tab(e, d))
            self._bound.append(sequence)
        root.bind_all("<KeyRelease>", self._on_key_release, add="+")
        self._keep_panels_visible()
        self.refresh_states()
        self._refresh_status()
        self._refresh_summary()

    @property
    def panels(self) -> list[PanelBase]:
        """The four focus stops: palette, canvas, the visible side tab (tree or variables) and
        the inspector."""
        side = self.variables if self.side.select() == str(self.variables.frame) else self.tree
        return [self.palette, self.canvas, side, self.inspector]

    @property
    def all_panels(self) -> list[PanelBase]:
        """Every panel, including the hidden side tab (restyle, retranslate, dispose)."""
        return [self.palette, self.canvas, self.tree, self.variables, self.inspector]

    def _post(self, text: str) -> None:
        """A panel's outcome: a reason is shown; "" clears an older refusal (rule C2)."""
        if text:
            self.show_message(text)
        else:
            self.clear_message()

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
        self.submenus[definition.id] = sub
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
            "command": self._invoker(action.id),
        }
        if action.shortcut is not None:
            options["accelerator"] = tk_shortcut(action.shortcut, aqua=self.aqua).accelerator
        if action.checked is not None:
            variable = self._radio.setdefault(action.menu, tkinter.StringVar(self.root))
            menu.add_radiobutton(variable=variable, value=action.id, **options)
        else:
            menu.add_command(**options)
        self._entries.append((menu, int(menu.index("end") or 0), action))

    def _build_tree_menu(self) -> None:
        """The object tree's context menu: Insert, the clipboard and Delete (registry actions)."""
        menu = tkinter.Menu(self.root, tearoff=False, postcommand=self.refresh_states)
        self._menus.append(menu)
        self.tree_menu = menu
        known = "edit.insert" in self.registry.menu_ids()
        items = self.registry.menu_items("edit.insert") if known else ()
        inserts = [i for i in items if isinstance(i, ActionDef)]
        groups = (inserts, [a for n in _TREE_MENU if (a := self.registry.get(n)) is not None])
        for group in (g for g in groups if g):
            if menu.index("end") is not None:
                menu.add_separator()
            for action in group:
                self._add_action(menu, action)
        self._unique_access_keys(menu)

        def popup(x: int, y: int) -> None:
            try:
                menu.tk_popup(x, y)
            finally:
                menu.grab_release()

        self.tree.popup = popup

    @staticmethod
    def _unique_access_keys(menu: tkinter.Menu) -> None:
        """Give the merged tree menu one access key per entry (after building or retranslating)."""
        last = menu.index("end")
        indices = [i for i in range(0 if last is None else last + 1) if menu.type(i) != "separator"]
        entries = [
            (str(menu.entrycget(i, "label")), int(menu.entrycget(i, "underline"))) for i in indices
        ]
        for index, underline in zip(indices, unique_mnemonics(entries), strict=True):
            menu.entryconfigure(index, underline=underline)

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
        self._unique_access_keys(self.tree_menu)
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
        tree = self.tree.tree
        assert tree is not None
        scoped: dict[str, Callable[[str, Any], object]] = {
            "canvas": self.canvas.bind_key,  # every stage's focus proxy, also after a re-render
            "tree": lambda sequence, handler: tree.bind(sequence, handler, add="+"),
        }
        for action in self.registry.actions():
            handler = self._key_handler(action.id)
            binders = [scoped[name] for name in action.scope]  # empty: every widget (bind_all)
            for chord in action.chords:
                for sequence in tk_shortcut(chord, aqua=self.aqua).sequences:
                    for bind in binders:
                        bind(sequence, handler)
                    if not binders:
                        self.root.bind_all(sequence, handler)
                        self._bound.append(sequence)

    def _invoker(self, action_id: str) -> Callable[[], None]:
        def run() -> None:
            self.clear_message()  # a new command supersedes an earlier refusal (QA-13b-11)
            self._invoke(action_id)

        return run

    def flush(self) -> bool:
        """Commit the pending text of the inspector and the Variables panel (risk R2).

        False when an editor refused its text: the caller aborts (A15).
        """
        return self.inspector.flush() and self.variables.flush()

    def typing(self) -> bool:
        """True while the keyboard focus is in an editor of the inspector or the Variables panel.

        The focus is read as a path name (``focus_get`` raises inside a Combobox drop-down), and
        ``-lastfor`` keeps the answer while the designer is in the background (Alt+Tab).
        """
        try:
            path = str(self.root.tk.call("focus")) or str(
                self.root.tk.call("focus", "-lastfor", self.root)
            )
        except tkinter.TclError:
            return False
        panels = (str(self.inspector.frame), str(self.variables.frame))
        return any(path == p or path.startswith(p + ".") for p in panels)

    def _invoke(self, action_id: str) -> bool:
        if _flush_first(action_id) and not self.flush():
            return True  # the refused text stays marked and its reason is shown
        self._in_command = True
        try:
            return self.registry.invoke(action_id)
        finally:
            self._in_command = False

    def _key_handler(self, action_id: str) -> Any:  # noqa: ANN401 - a Tk callback
        def handler(event: object) -> str | None:
            widget = getattr(event, "widget", None)
            if not self._in_main_window(widget):
                return None  # a dialog is open: its keys are its own
            if action_id in _TEXT_OWNED and _is_text_input(widget):
                return None
            if action_id in _ONCE_PER_PRESS and self._repeated(event):
                return "break"
            # A new command supersedes an earlier refusal (QA-13b-11). Cleared before it runs,
            # so what the command itself posts (its refusal, a drag it cancels) still shows.
            self.clear_message()
            if not self._invoke(action_id):  # disabled: say why, when it can
                self._explain_refusal(action_id)
            elif action_id in _ONCE_PER_PRESS:
                self._held = (str(getattr(event, "keysym", "")), str(widget), -1)
            return "break"

        return handler

    def _repeated(self, event: Any) -> bool:  # noqa: ANN401 - a Tk event
        """An auto-repeat of the press that acted: the same key on the same widget with no
        KeyRelease since (Windows, aqua) or one at the very same time (X11 repeat pairs)."""
        key = (str(getattr(event, "keysym", "")), str(getattr(event, "widget", None)))
        released = self._held[2] if self._held is not None and self._held[:2] == key else None
        time = int(getattr(event, "time", 0) or 0)
        repeated = released == -1 or (released == time != 0)
        self._held = (*key, -1) if repeated else None
        return repeated

    def _on_key_release(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self._held is not None and self._held[0] == getattr(event, "keysym", None):
            self._held = (*self._held[:2], int(getattr(event, "time", 0) or 0))

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
        self._held = None  # a focus change ends a held key (QA-13b-04)
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

    def _switch_tab(self, event: Any, step: int) -> str | None:  # noqa: ANN401 - a Tk event
        """Ctrl+Tab: the next tab of the notebook that holds the focus (spec 14a section 16)."""
        path = str(getattr(event, "widget", ""))
        stops = ((self.side, self.side, 2), (self.inspector.notebook, self.inspector.frame, 3))
        for notebook, owner, index in stops:
            if path == str(owner) or path.startswith(f"{owner}."):
                tabs = list(notebook.tabs())
                notebook.select(tabs[(tabs.index(notebook.select()) + step) % len(tabs)])
                self.panels[index].focus_first()
                self._mark(index)
                return "break"
        return None

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

    def _on_selection(self) -> None:
        if not self._in_command:
            self.clear_message()

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
        count = len(self.session.selection.nodes)
        path = selection_path(self.session.selection.node, self.session.document)
        if count > 1:
            path = ngettext("{count} element selected", "{count} elements selected", count).format(
                count=count
            )
        self._status.configure(text=self._message or path)

    def _on_report(self) -> None:
        self._refresh_summary()
        self.refresh_states()  # the Undo/Redo labels and the enabled state follow the stack

    def _refresh_summary(self) -> None:
        self._summary.configure(text=findings_summary(self.session.report()))

    def retranslate_status(self) -> None:
        """Re-render the side tab labels and the validator summary (the selection path is not
        translated)."""
        for panel in (self.tree, self.variables):
            self.side.tab(panel.frame, text=_(panel.HEADING))
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
        for panel in self.all_panels:
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
        for panel in self.all_panels:
            panel.dispose()
        try:
            for sequence in (*self._bound, "<FocusIn>", "<KeyRelease>"):
                self.root.unbind_all(sequence)
            self.root.configure(menu="")
            for widget in (self.menubar, self.tree_menu, self.toolbar, self.body, self.statusbar):
                widget.destroy()
        except tkinter.TclError:  # the root is already gone
            _log.debug("The window was already destroyed", exc_info=True)
