"""The Variables tab beside the object tree (Tk; spec properties-save-load 5, D10).

The list shows every declared variable and its users; the row below edits the selected one.
Renames and deletes are the ``editing`` macros, so every binding follows in one undo step.
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import Any

from ttkbootstrap.widgets.tooltip import ToolTip

from pyguibud.core.commands import Command, Macro, Outcome, SetField, SetVariable
from pyguibud.core.model import Variable, Widget
from pyguibud.core.text import printable
from pyguibud.designer.editing import (
    new_variable,
    remove_and_unbind,
    rename_variable,
    variable_users,
)
from pyguibud.designer.files import M_READ_ONLY
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.panels.editors import _M_CLIPPED, _M_TOO_LONG, bind_history, history_action
from pyguibud.designer.present import clip, inserted
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT, clip_text
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.theme import ThemeSpec
from pyguibud.designer.theme_tk import GHOST_STYLE, STYLE_COMBOBOX, STYLE_ENTRY
from pyguibud.i18n import N_, _, ngettext

__all__ = ["VariablesPanel"]

_M_ID = N_("Id")
_M_TYPE = N_("Type")
_M_DEFAULT = N_("Default")
_M_USED_BY = N_("Used by")
_M_ADD = N_("Add")
_M_RENAME = N_("Rename…")
_M_DELETE = N_("Delete")
_M_BIND = N_("Bind to selection")
_M_RESET = N_("Reset to default")  # the inspector's msgid
# Translators: {count} is the number of users; {ids} lists their ids.
_M_USERS = N_("{count} ({ids})")
_TYPES = ("string", "int", "double", "bool")


def _breaking(handler: Callable[[], None]) -> Callable[[object], str]:
    """A Tk callback that runs ``handler`` and stops the event there."""

    def run(_event: object) -> str:
        handler()
        return "break"

    return run


class VariablesPanel(PanelBase):
    """A list of variables with Add / Rename / Delete / Bind; Insert, F2 and Delete keys."""

    name = "variables"
    HEADING = N_("Variables")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        #: Seams the shell sets: the status line ("" clears it) and the confirmation dialog.
        self.status: Callable[[str], None] = lambda _text: None
        self.confirm: Callable[[str, Callable[[], None]], None] = lambda _q, then: then()
        #: Runs a registry action (Ctrl+Z/Ctrl+Y in the fields: "edit.undo", "edit.redo").
        self.invoke: Callable[[str], None] = lambda _action: None
        tree = self._new_tree(("type", "default", "used"))
        tree.configure(show="tree headings")
        tree.bind("<<TreeviewSelect>>", lambda _e: self._load_row(), add="+")
        for sequence, handler in (
            ("<Insert>", self.add),
            ("<F2>", self.start_rename),
            ("<Delete>", self.delete),
        ):
            tree.bind(sequence, _breaking(handler))
        tree.bind("<Button-3>", self._context_menu, add="+")
        edit = ttk.Frame(self.frame, padding=(6, 4))
        edit.grid(row=2, column=0, columnspan=2, sticky="ew")
        edit.columnconfigure(1, weight=1)
        self.id_var, self.default_var = tkinter.StringVar(edit), tkinter.StringVar(edit)
        self.type_var = tkinter.StringVar(edit)
        self.id_entry = ttk.Entry(edit, textvariable=self.id_var, style=STYLE_ENTRY)
        self.type_box = ttk.Combobox(edit, textvariable=self.type_var, values=_TYPES, width=8,
                                     state="readonly", style=STYLE_COMBOBOX)  # fmt: skip
        self.default_entry = ttk.Entry(edit, textvariable=self.default_var, style=STYLE_ENTRY)
        self._labels: list[tuple[Any, str]] = []
        for row, (msgid, widget) in enumerate(
            ((_M_ID, self.id_entry), (_M_TYPE, self.type_box), (_M_DEFAULT, self.default_entry))
        ):
            label = ttk.Label(edit)
            label.grid(row=row, column=0, sticky="w", padx=(0, 6), pady=1)
            widget.grid(row=row, column=1, sticky="ew", pady=1)
            self._labels.append((label, msgid))
        # A default too long to edit here gets the inspector's Reset: it clears it (QA-19g-10).
        self.reset = ttk.Button(edit, text="↺", style=GHOST_STYLE, command=self.reset_default)
        self.reset.grid(row=2, column=2, padx=(4, 0))
        self._reset_tip = ToolTip(self.reset)
        self.note = ttk.Label(edit, wraplength=edit.winfo_fpixels("2.2i"))  # why it is read-only
        self.note.grid(row=3, column=0, columnspan=3, sticky="w")
        for widget, commit in ((self.id_entry, self._commit_id),
                               (self.default_entry, self._commit_default)):  # fmt: skip
            widget.bind("<Return>", _breaking(commit))
            widget.bind("<FocusOut>", _breaking(commit), add="+")
            widget.bind("<Escape>", lambda _e: self._load_row())
        bind_history(self.id_entry, lambda redo: self._history(redo, self.id_var, "id"))
        bind_history(self.default_entry,
                     lambda redo: self._history(redo, self.default_var, "default"))  # fmt: skip
        self.type_box.bind("<<ComboboxSelected>>", lambda _e: self._commit_type())
        buttons = ttk.Frame(self.frame, padding=(6, 0, 6, 4))
        buttons.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.actions = ((_M_ADD, self.add), (_M_RENAME, self.start_rename),
                        (_M_DELETE, self.delete), (_M_BIND, self.bind_selection))  # fmt: skip
        self.buttons = [ttk.Button(buttons, command=handler) for _m, handler in self.actions]
        for button in self.buttons:
            button.pack(side="left", padx=(0, 4), pady=2)
        self.menu = tkinter.Menu(self.frame, tearoff=False)
        for _msgid, handler in self.actions:
            self.menu.add_command(command=handler)
        self._render_id: str | None = None
        self._ids: tuple[str, ...] = ()  # the ids the list showed at the last render
        self._connect(session.document_changed, lambda _s: self._schedule())
        self._connect(session.report_changed, lambda _r: self._schedule())
        self.retranslate()

    # ------------------------------------------------------------ view
    def _schedule(self) -> None:
        if self._render_id is None:
            self._render_id = self.frame.after_idle(self._render)

    def _render(self) -> None:
        self._render_id = None
        tree = self.tree
        document = self.session.document
        if tree is None:
            return
        keep = self.current()
        scroll = self._scroll_state()
        before, self._ids = self._ids, tuple(document.variables) if document is not None else ()
        if keep is not None and keep not in self._ids:
            # The selected variable vanished and exactly one appeared: a rename, done, undone or
            # redone (QA-14a1-21). The selection follows it instead of falling off the list.
            appeared = [name for name in self._ids if name not in before]
            gone = [name for name in before if name not in self._ids]
            keep = appeared[0] if gone == [keep] and len(appeared) == 1 else keep
        tree.delete(*tree.get_children())
        for variable in document.variables.values() if document is not None else ():
            users = [w.id for w in variable_users(document, variable.id)] if document else []
            ids = clip(printable(", ".join(users)), 60)  # display only: bidi escaped (H81)
            used = _(_M_USERS).format(count=len(users), ids=ids)
            values = (variable.type, clip(printable(variable.default), 40), used if users else "0")
            tree.insert("", "end", iid=variable.id, text=inserted(variable.id), values=values)
        if keep is not None and tree.exists(keep):
            tree.selection_set(keep)
            tree.focus(keep)
        self._restore_scroll(scroll)
        self._load_row()

    def retranslate(self) -> None:
        super().retranslate()
        tree = self.tree
        if tree is not None:
            for column, msgid in (("#0", _M_ID), ("type", _M_TYPE), ("default", _M_DEFAULT),
                                  ("used", _M_USED_BY)):  # fmt: skip
                tree.heading(column, text=_(msgid))
        for label, msgid in self._labels:
            label.configure(text=_(msgid))
        self._reset_tip.text = _(_M_RESET)
        for index, (button, (msgid, _h)) in enumerate(zip(self.buttons, self.actions, strict=True)):
            button.configure(text=_(msgid))
            self.menu.entryconfigure(index, label=_(msgid))

    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        colours = spec.colors
        self.menu.configure(background=colours["bg"], foreground=colours["fg"],
                            activebackground=colours["selectbg"],
                            activeforeground=colours["selectfg"])  # fmt: skip

    def dispose(self) -> None:
        if self._render_id is not None:
            self.frame.after_cancel(self._render_id)
            self._render_id = None
        super().dispose()

    # ------------------------------------------------------------ helpers
    def current(self) -> str | None:
        """The id of the selected variable, or None."""
        tree = self.tree
        picked = tree.selection() if tree is not None else ()
        return str(picked[0]) if picked else None

    def _variable(self) -> Variable | None:
        document, var_id = self.session.document, self.current()
        return document.variables.get(var_id) if document and var_id else None

    def _load_row(self) -> None:
        variable = self._variable()
        self.id_var.set(clip_text(variable.id) if variable else "")
        self.type_var.set(variable.type if variable else "")
        self.default_var.set(clip_text(variable.default) if variable else "")
        state = ["!disabled"] if variable and not self._read_only() else ["disabled"]
        for widget in (self.id_entry, self.type_box, self.default_entry):
            widget.state(state)
        # A text too long for an Entry shows as a read-only clip that never commits (QA-19f-08);
        # every other row clears the flag again (QA-19g-05). A read-only document stays disabled.
        for attribute, entry in (("id", self.id_entry), ("default", self.default_entry)):
            long = self._long(attribute) and "disabled" not in state
            entry.state(["readonly"] if long else ["!readonly"])
        notes = []  # why a clip cannot be typed; Reset clears a long default (QA-19g-06, 10)
        if variable is not None and self._long("id"):
            length = len(variable.id)
            notes.append(_(_M_CLIPPED).format(id=_(_M_ID), length=length, limit=CANVAS_TEXT_LIMIT))
        if variable is not None and self._long("default"):
            notes.append(_(_M_TOO_LONG).format(length=len(variable.default)))
        self.note.configure(text="\n".join(notes))
        for item, shown in ((self.note, bool(notes)), (self.reset, self._long("default"))):
            if shown:
                item.grid()
            else:
                item.grid_remove()
        # A20: a read-only document offers no variable action (the keys say why, _refused).
        locked = self._read_only()
        self.reset.state(["disabled"] if locked else ["!disabled"])
        for index, button in enumerate(self.buttons):
            button.state(["disabled"] if locked else ["!disabled"])
            self.menu.entryconfigure(index, state="disabled" if locked else "normal")

    def _long(self, attribute: str) -> bool:
        variable = self._variable()
        return variable is not None and len(getattr(variable, attribute)) > CANVAS_TEXT_LIMIT

    def _typed(self, attribute: str) -> str:
        """The text of the id or default entry; the model's own while it shows a clip."""
        variable = self._variable()
        if variable is not None and self._long(attribute):
            return str(getattr(variable, attribute))
        text = (self.id_var if attribute == "id" else self.default_var).get()
        return text.strip(" ") if attribute == "id" else text  # "x\n" is refused (QA-19c-09)

    def _read_only(self) -> bool:
        stack = self.session.stack
        return stack is None or stack.read_only

    def _refused(self) -> bool:
        """True (and the reason is posted) when the open document is read-only (A20)."""
        stack = self.session.stack
        if stack is None or not stack.read_only:
            return False
        reason = self.session.read_only_reason
        self.status(_(M_READ_ONLY).format(reason=_(reason) if reason else ""))
        return True

    def _run(self, command: Command | str, select: str | None = None) -> bool:
        stack = self.session.stack
        if isinstance(command, str):
            self.status(command)
            return False
        if stack is None:
            return False
        outcome: Outcome = stack.execute(command)
        self.status(outcome.message)  # "" clears an older refusal (rule C2)
        if outcome.accepted and select is not None and self.tree is not None:
            self.frame.after_idle(lambda: self._select(select))
        return outcome.accepted

    def _select(self, var_id: str) -> None:
        if self._render_id is not None:
            self._render()
        tree = self.tree
        if tree is not None and tree.exists(var_id):
            tree.selection_set(var_id)
            tree.focus(var_id)
            tree.see(var_id)

    # ------------------------------------------------------------ actions
    def add(self) -> None:
        """Declare a new string variable and select it (Insert)."""
        document = self.session.document
        if document is not None and not self._refused():
            command = new_variable(document)
            self._run(command, select=command.item.id)

    def start_rename(self) -> None:
        """Put the keyboard in the id field of the selected variable (F2)."""
        if self._variable() is not None and not self._refused():
            self.id_entry.focus_set()
            self.id_entry.select_range(0, "end")

    def delete(self) -> None:
        """Delete the selected variable; a used one is unbound after a confirmation (Delete)."""
        document, variable = self.session.document, self._variable()
        if document is None or variable is None or self._refused():
            return
        count = len(variable_users(document, variable.id))
        if not count:
            self._run(remove_and_unbind(document, variable.id))
            return
        # Translators: {id} is the identifier of a variable and {count} the number of widgets bound
        # to it.
        question = ngettext(
            "'{id}' is bound to {count} widget. Unbind it and delete it?",
            "'{id}' is bound to {count} widgets. Unbind them and delete it?",
            count,
        ).format(id=inserted(variable.id), count=count)

        def unbind_and_delete() -> None:
            self._run(remove_and_unbind(document, variable.id))  # rebuilt: the users may differ

        self.confirm(question, unbind_and_delete)

    def bind_selection(self) -> None:
        """Bind the selected widgets to the selected variable (one step)."""
        variable = self._variable()
        widgets = [n for n in self.session.selection.nodes if isinstance(n, Widget)]
        if variable is None or not widgets or self._refused():
            return
        binds: list[Command] = [SetField(w, "bind", variable.id) for w in widgets]
        self._run(binds[0] if len(binds) == 1 else Macro(_M_BIND, binds))

    def flush(self) -> bool:
        """Commit the typed id and default (Save, the guard, autosave); False on a refusal.

        Unlike Return, a refusal here never moves the focus: autosave runs on a timer (and
        skips the flush while the focus is in this panel or the inspector).
        """
        document, variable = self.session.document, self._variable()
        if document is None or variable is None or self._read_only():
            return True
        new = self._typed("id")
        if new != variable.id:
            if not self._run(rename_variable(document, variable.id, new), select=new):
                return False
            variable = document.variables.get(new, variable)
        text = self._typed("default")
        if text != variable.default:
            return self._run(SetVariable(document, replace(variable, default=text)))
        return True

    def _history(self, redo: bool, var: tkinter.StringVar, attribute: str) -> str:
        """Ctrl+Z/Ctrl+Y in the id or default field: revert typed text first, else undo/redo."""
        variable = self._variable()
        model = "" if variable is None else str(getattr(variable, attribute))

        def typed() -> str:
            return self._typed(attribute)

        return history_action(redo, pending=lambda: typed() != model,
                              revert=lambda: var.set(model), invoke=self.invoke)  # fmt: skip

    def _commit_id(self) -> None:
        document, variable = self.session.document, self._variable()
        new = self._typed("id")
        if document is None or variable is None or new == variable.id:
            return
        if not self._run(rename_variable(document, variable.id, new), select=new):
            self.id_entry.focus_set()

    def _commit_type(self) -> None:
        document, variable = self.session.document, self._variable()
        if document is not None and variable is not None:
            kind: Any = self.type_var.get()
            if not self._run(SetVariable(document, replace(variable, type=kind))):
                self._load_row()

    def _commit_default(self) -> None:
        document, variable = self.session.document, self._variable()
        text = self._typed("default")
        if document is not None and variable is not None and text != variable.default:
            self._run(SetVariable(document, replace(variable, default=text)))

    def reset_default(self) -> None:
        """↺: clear a default too long to edit here, as one undoable step (QA-19g-10)."""
        document, variable = self.session.document, self._variable()
        if document is not None and variable is not None and not self._refused():
            self._run(SetVariable(document, replace(variable, default="")))

    def _context_menu(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        tree = self.tree
        if tree is not None and (row := tree.identify_row(event.y)):
            tree.selection_set(row)
        self.menu.tk_popup(event.x_root, event.y_root)
