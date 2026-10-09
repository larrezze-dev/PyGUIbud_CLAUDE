"""The inspector: typed editors for the selection, in Properties | Events tabs (Tk; spec 14a 3-4).

Commits come from user events only and go through the ``CommandStack``; listeners merely
schedule an ``after_idle`` refresh (risk R1), and a refresh never overwrites typed text.
"""

from __future__ import annotations

import os
import tkinter
from collections.abc import Callable
from dataclasses import replace
from functools import partial
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from pyguibud.core import ValidationReport
from pyguibud.core.commands import Macro, Outcome, SetField, SetResource
from pyguibud.core.diagnostics import Finding
from pyguibud.core.model import ImageResource, Prop, Widget, Window
from pyguibud.core.validate import BIND_TYPES
from pyguibud.designer.dialogs import files
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.dialogs.text import TextDialog
from pyguibud.designer.editing import M_EXTERNAL_INCLUDES, new_variable, unique_id
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.panels.editors import (
    ADD,
    INVALID,
    NEW,
    Editor,
    history_action,
    make_editor,
    retranslate,
)
from pyguibud.designer.panels.events import EventsTab
from pyguibud.designer.present import clip, severity_label
from pyguibud.designer.properties import (
    Field,
    commit_commands,
    dialog_commands,
    dialog_prop,
    field_rows,
    parse_value,
)
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.theme import ThemeSpec, tag_colours
from pyguibud.i18n import N_, _

__all__ = ["InspectorPanel"]

_M_PROPERTIES = N_("Properties")
_M_EVENTS = N_("Events")
_M_FINDINGS = N_("Findings")
# Translators: the button that resets one field of the inspector to its default value.
_M_RESET = N_("Reset to default")
_M_MIXED = N_("(mixed)")
_M_SHARED = N_("{count} elements selected; editing shared properties.")
# Translators: {reason} says why, e.g. "the file is write-protected".
_M_READ_ONLY = N_("This document is read-only: {reason}")
_M_NEW_BINDING = N_("Bind to a new variable")
_M_ADD_IMAGE = N_("Add image")
#: Fields without a Reset button (they have no default).
_NO_RESET = frozenset({"field:id", "field:src", "field:component", "field:kind", "layout:type"})
_NO_RESET |= {"place:grid:row", "place:grid:column"}
_SECTION, _MUTED = "Section.TLabel", "Muted.TLabel"
_RESET_STYLE = "Reset.TButton"


class InspectorPanel(PanelBase):
    """The form of the selected node(s); :meth:`flush` commits the editor's pending text."""

    name = "inspector"
    HEADING = N_("Inspector")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        #: Seams the shell sets: the status line ("" clears it, rule C2) and an action runner.
        self.status: Callable[[str], None] = lambda _text: None
        self.invoke: Callable[[str], None] = lambda _action: None
        self.open_dialog: Callable[[ModalDialog], None] = lambda dialog: dialog.open()
        self.ask_colour = files.ask_colour
        self.ask_image = files.ask_image
        self.frame.rowconfigure(1, weight=0)
        self.frame.rowconfigure(2, weight=1)
        self.header = ttk.Label(self.frame, anchor="w", justify="left")
        self.frame.bind(
            "<Configure>", lambda e: self.header.configure(wraplength=e.width - 12), add="+"
        )
        self.notebook: Any = ttk.Notebook(self.frame, takefocus=True)  # untyped tab API
        self.notebook.grid(row=2, column=0, columnspan=2, sticky="nsew")
        tab = self.form_tab = ttk.Frame(self.notebook)
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(0, weight=1)
        self.canvas = tkinter.Canvas(tab, highlightthickness=0, borderwidth=0, width=220)
        bar = ttk.Scrollbar(tab, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        self.form = ttk.Frame(self.canvas, padding=(6, 4))
        self.form.columnconfigure(1, weight=1)
        item = self.canvas.create_window(0, 0, window=self.form, anchor="nw")
        self.form.bind("<Configure>", lambda _e: self._fit_scroll(), add="+")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(item, width=e.width))
        self._wheel(self.canvas)
        self.events = EventsTab(self.notebook, self)
        self.notebook.add(tab, text=_(_M_PROPERTIES))
        self.notebook.add(self.events.frame, text=_(_M_EVENTS))
        self._nodes: tuple[object, ...] = ()
        self._editors: dict[str, Editor] = {}
        self._rows: dict[str, tuple[ttk.Label, ttk.Button | None, ttk.Label]] = {}
        self._findings: list[Any] = []
        self._pending_ids: dict[str, str] = {}
        self._connect(session.selection_changed, self._on_selection)
        self._connect(session.document_changed, lambda _s: self._schedule("rebuild"))
        self._connect(session.report_changed, self._on_report)
        self._render()

    # ------------------------------------------------------------ scheduling (R1, R5)
    def _on_selection(self, _selection: Selection) -> None:
        self._schedule("rebuild")

    def _on_report(self, _report: ValidationReport) -> None:
        self._schedule("refresh")

    def _schedule(self, what: str) -> None:
        if what not in self._pending_ids:
            run = self._rebuild if what == "rebuild" else self._refresh
            self._pending_ids[what] = self.frame.after_idle(run)

    @property
    def read_only(self) -> bool:
        stack = self.session.stack
        return stack is not None and stack.read_only

    # ------------------------------------------------------------ building
    def _rebuild(self) -> None:
        self._pending_ids.pop("rebuild", None)
        self.flush()  # pending text belongs to the nodes it was typed for (captured below)
        self._render()

    def _render(self) -> None:
        for child in self.form.winfo_children():
            child.destroy()
        self._editors, self._rows, self._findings = {}, {}, []
        session, document = self.session, self.session.document
        nodes = session.selection.nodes if document is not None else ()
        self._nodes = nodes
        self._header()
        fields = field_rows(nodes, session.registry, document) if document else ()
        section, row = "", 0
        for field in fields:
            if field.section != section:
                section = field.section
                ttk.Label(self.form, text=_(section), style=_SECTION).grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(6, 2)
                )
                row += 1
            self._add_row(field, row)
            row += 1
        self._findings_row = row
        self._show_findings()
        self.events.render(nodes, document)
        self.canvas.yview_moveto(0)

    def _add_row(self, field: Field, row: int) -> None:
        label = ttk.Label(self.form, text=_(field.label), anchor="w")
        label.grid(row=row, column=0, sticky="w", padx=(0, 8), pady=1)
        editor = make_editor(self.form, field, self)
        editor.frame.grid(row=row, column=1, sticky="ew", pady=1)
        mixed = ttk.Label(editor.frame, text=_(_M_MIXED), style=_MUTED)  # never in the entry
        reset = None
        if field.kind != "class" and field.key not in _NO_RESET:
            reset = ttk.Button(self.form, text="↺", width=2, style=_RESET_STYLE,
                               command=partial(self.reset, field.key))  # fmt: skip
            reset.grid(row=row, column=2, padx=(4, 0), pady=1)
            # The glyph has no words: say what it does when the keyboard reaches it.
            reset.bind("<FocusIn>", lambda _e: self.status(_(_M_RESET)), add="+")
        self._editors[field.key], self._rows[field.key] = editor, (label, reset, mixed)
        for widget in (label, editor.widget, editor.frame):
            self._wheel(widget)
        self._show_state(field)
        if self.read_only:
            editor.set_enabled(False)

    def _show_state(self, field: Field) -> None:
        label, reset, mixed = self._rows[field.key]
        label.configure(style=_MUTED if field.is_default else "TLabel")
        if reset is not None:
            reset.state(["disabled"] if field.is_default or self.read_only else ["!disabled"])
        if field.value is None:
            mixed.grid(row=0, column=9, padx=(4, 0))
        else:
            mixed.grid_remove()

    def _header(self) -> None:
        texts = []
        if len(self._nodes) > 1:
            texts.append(_(_M_SHARED).format(count=len(self._nodes)))
        reason = self.session.read_only_reason
        if self.read_only:
            texts.append(_(_M_READ_ONLY).format(reason=_(reason) if reason else ""))
        self.header.configure(text="\n".join(texts))
        if texts:
            self.header.grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 4))
        else:
            self.header.grid_remove()

    def _show_findings(self) -> None:
        for widget in self._findings:
            widget.destroy()
        self._findings = []
        findings = [f for f in self.session.report().findings if any(f.anchor is n for n in
                    self._nodes)]  # fmt: skip
        row = self._findings_row
        if findings:
            title = ttk.Label(self.form, text=_(_M_FINDINGS), style=_SECTION)
            title.grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 2))
            self._findings.append(title)
        for k, finding in enumerate(findings[:50], start=row + 1):
            text = f"{severity_label(finding.severity)}: {clip(finding.message, 200)}"
            line = ttk.Label(self.form, text=text, wraplength=260, justify="left")
            line.grid(row=k, column=0, columnspan=3, sticky="w")
            self._findings.append(line)

    def _refresh(self) -> None:
        """Values only (stack events); a changed set of fields rebuilds the form."""
        self._pending_ids.pop("refresh", None)
        document = self.session.document
        current = self.session.selection.nodes
        same = len(current) == len(self._nodes) and all(
            a is b for a, b in zip(current, self._nodes, strict=True)
        )  # identity: nodes are eq-dataclasses, deep equality would be slow and wrong
        if document is None or not same:
            self._schedule("rebuild")
            return
        fields = field_rows(self._nodes, self.session.registry, document)
        if [(f.key, f.kind) for f in fields] != [(k, e.field.kind) for k, e in
                                                 self._editors.items()]:  # fmt: skip
            self._render()
            return
        for field in fields:
            editor = self._editors[field.key]
            if not editor.pending():
                editor.load(field)
            else:
                editor.field = field
            self._show_state(field)
        self._header()
        self._show_findings()
        self.events.refresh(document)

    # ------------------------------------------------------------ EditorHost
    def commit(self, editor: Editor, value: str | Prop | None, *, merge: bool = False) -> bool:
        """Parse, build and run the command for ``editor``; a refusal marks the editor."""
        field = editor.field
        if field.key.startswith("event:"):
            if not self.events.change(field.key[6:], str(value or ""), editor):
                return False
            # The model now holds the text: no longer pending, so the tab reloads the box on
            # a stack change and Ctrl+Z undoes instead of reverting to the old handler.
            editor.shown = editor.text()
            return True
        stack = self.session.stack
        if stack is None or self.read_only or not self._nodes:
            return False
        if isinstance(value, str):
            parsed = parse_value(field, value)
            if isinstance(parsed, Finding):
                editor.set_invalid(True)
                self.status(parsed.message)
                return False
            reset = parsed == "" and field.kind in ("int", "float", "colour")
            value = None if reset else parsed
        renamed = self._component_id(field)
        if self.report(editor, stack.execute(commit_commands(self._nodes, field, value)), merge):
            editor.shown = editor.text() if editor.text_input else editor.shown
            if renamed is not None and renamed.id != field.value:
                # As Document > Rename: other files may include it by its old id (spec 14 A21).
                self.status(_(M_EXTERNAL_INCLUDES))
            return True
        return False

    def _component_id(self, field: Field) -> Window | None:
        """The component window whose Id ``field`` edits, else None."""
        node = self._nodes[0] if len(self._nodes) == 1 else None
        if field.key == "field:id" and isinstance(node, Window) and node.kind == "component":
            return node
        return None

    def report(self, editor: Editor | None, outcome: Outcome, merge: bool = False) -> bool:
        """Show the outcome of a commit: a refusal marks the editor; success clears (C2)."""
        if editor is not None:
            editor.set_invalid(not outcome.accepted)
        self.status(outcome.message)
        if outcome.accepted and not merge and self.session.stack is not None:
            self.session.stack.break_merge()
        return outcome.accepted

    def focus_in(self, editor: Editor) -> None:
        """A new editor session: its edits start a new undo step; scroll it into view."""
        if self.session.stack is not None:
            self.session.stack.break_merge()
        widget = editor.frame
        if str(widget).startswith(str(self.form)):
            self._see(widget)

    def history_key(self, editor: Editor, redo: bool) -> str:
        """Ctrl+Z/Ctrl+Y in an editor: revert typed text first, else undo/redo (spec 3.3)."""
        return history_action(redo, pending=editor.pending, revert=editor.revert,
                              invoke=self.invoke)  # fmt: skip

    def special(self, editor: Editor, what: str) -> None:
        """The "…", "Choose…", "New variable…" and "Add image…" entries of an editor."""
        field, nodes, document = editor.field, self._nodes, self.session.document
        stack = self.session.stack
        if not nodes or document is None or stack is None or self.read_only:
            return
        if what == "text":
            before = dialog_prop(nodes, field)  # the typed (pending) text is what it shows
            dialog = TextDialog(self.frame.winfo_toplevel(), replace(before, value=editor.text()),
                                lambda p: self._from_dialog(editor, before, p),
                                translatable=field.translatable,
                                check=lambda p: self._refusal(editor, before, p))  # fmt: skip
            self.open_dialog(dialog)
        elif what == "colour":
            colour = self.ask_colour(self.frame.winfo_toplevel(), editor.text())
            if colour:
                editor.var.set(colour)
                self.commit(editor, colour)
        elif what == NEW and isinstance(nodes[0], Widget):
            declare = new_variable(document, BIND_TYPES[nodes[0].class_name][0])
            bind = SetField(nodes[0], "bind", declare.item.id)
            self.report(editor, stack.execute(Macro(_M_NEW_BINDING, [declare, bind])))
        elif what == ADD:
            path = self.ask_image(self.frame.winfo_toplevel())
            if path:
                image = ImageResource(id=unique_id(document, "image"), src=self._src(path))
                use = commit_commands(nodes, field, image.id)
                add = Macro(_M_ADD_IMAGE, [SetResource(document, image), use])
                self.report(editor, stack.execute(add))

    def _refusal(self, editor: Editor, before: Prop, after: Prop) -> str | None:
        """Why the guard would refuse the dialog's edit (a dry run of the real command), or None."""
        stack = self.session.stack
        command = dialog_commands(self._nodes, editor.field, before, after)
        if command is None or stack is None or self.read_only or not self._nodes:
            return None
        outcome = stack.check(command)
        return None if outcome.accepted else outcome.message

    def _from_dialog(self, editor: Editor, before: Prop, after: Prop) -> None:
        """Apply what the user changed in the dialog, and nothing else (QA-14a1-06)."""
        stack = self.session.stack
        command = dialog_commands(self._nodes, editor.field, before, after)
        if command is None or stack is None or self.read_only or not self._nodes:
            return
        if self.report(editor, stack.execute(command)) and after.value != before.value:
            editor.var.set(after.value)
            editor.shown = after.value

    def _src(self, path: str) -> str:
        """``path`` relative to the document's folder when it has one (else as given)."""
        base = self.session.path
        if base is not None:
            try:
                return Path(os.path.relpath(path, base.parent)).as_posix()
            except ValueError:  # another drive (Windows)
                pass
        return Path(path).as_posix()

    def reset(self, key: str) -> None:
        """Reset the field ``key`` to its default on every selected node."""
        editor = self._editors.get(key)
        stack = self.session.stack
        if editor is None or stack is None or self.read_only:
            return
        if self.report(editor, stack.execute(commit_commands(self._nodes, editor.field, None))):
            editor.revert()

    def value_of(self, key: str) -> str | None:
        """The text the editor of field ``key`` shows (None: no such field on the form)."""
        editor = self._editors.get(key)
        return editor.text() if editor is not None else None

    # ------------------------------------------------------------ Panel protocol
    def flush(self) -> bool:
        """Commit every editor's pending text; False (the editor stays marked) on a refusal."""
        for editor in [*self._editors.values(), *self.events.editors()]:
            try:
                if editor.pending() and not editor.commit_pending():
                    return False
            except tkinter.TclError:  # the editor is being destroyed: nothing is pending
                continue
        return True

    def retranslate(self) -> None:
        super().retranslate()
        for tab, msgid in ((self.form_tab, _M_PROPERTIES), (self.events.frame, _M_EVENTS)):
            self.notebook.tab(tab, text=_(msgid))
        for editor in self._editors.values():
            retranslate(editor)

    def focus_first(self) -> None:
        """F6: the first editor of the active tab, else the notebook itself."""
        boxes = self.events.editors() if self.notebook.select() == str(self.events.frame) else None
        editors = boxes if boxes is not None else list(self._editors.values())
        for editor in editors:
            widget = editor.widget
            if widget is not None and "disabled" not in widget.state():
                widget.focus_set()
                return
        self.notebook.focus_set()

    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        style, colours = ttk.Style(), spec.colors
        style.configure(_MUTED, foreground=tag_colours(spec)["muted"])
        bold = tkfont.nametofont("TkDefaultFont").actual()
        style.configure(_SECTION, font=(bold["family"], bold["size"], "bold"))
        for base in ("TEntry", "TSpinbox", "TCombobox", "TLabel"):  # TLabel: the text dialog
            style.configure(f"{INVALID}.{base}", foreground=colours["danger"],
                            bordercolor=colours["danger"])  # fmt: skip
        self.canvas.configure(background=colours["bg"])

    def dispose(self) -> None:
        for after_id in self._pending_ids.values():
            try:
                self.frame.after_cancel(after_id)
            except tkinter.TclError:
                continue
        self._pending_ids.clear()
        super().dispose()

    # ------------------------------------------------------------ scrolling
    def _fit_scroll(self) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _see(self, widget: Any) -> None:  # noqa: ANN401 - a Tk widget
        self.form.update_idletasks()
        height = max(1, self.form.winfo_height())
        top, bottom = widget.winfo_y() / height, (widget.winfo_y() + widget.winfo_height()) / height
        first, last = self.canvas.yview()
        if top < first or bottom > last:
            self.canvas.yview_moveto(max(0.0, top - 0.05))

    def _wheel(self, widget: Any) -> None:  # noqa: ANN401 - a Tk widget
        if widget is None:
            return
        widget.bind("<MouseWheel>", lambda e: self._scroll(-1 if e.delta > 0 else 1), add="+")
        widget.bind("<Button-4>", lambda _e: self._scroll(-1), add="+")
        widget.bind("<Button-5>", lambda _e: self._scroll(1), add="+")

    def _scroll(self, step: int) -> str:
        self.canvas.yview_scroll(step * 3, "units")
        return "break"
