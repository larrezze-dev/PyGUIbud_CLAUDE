"""The Events tab of the inspector (Tk; spec properties-save-load 4, single selection only).

One editable combobox per abstract event of the widget's class, then its ``key:`` events. Every
change runs ONE ``SetEvents`` with the full new tuple, so the guard judges the whole set.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from tkinter import ttk
from typing import Any

from pyguibud.core.commands import Outcome, SetEvents
from pyguibud.core.model import Action, Document, Event, Widget
from pyguibud.designer.panels.editors import Editor, EditorHost, bind_history, history_action
from pyguibud.designer.properties import Field
from pyguibud.i18n import N_, _

__all__ = ["EventsTab", "HandlerBox"]

_M_SELECT_ONE = N_("Select one widget to edit its events.")
_M_ADD_KEY = N_("Add key event…")
_M_REMOVE = N_("Remove")
# Translators: the label of the field that takes a key sequence such as Ctrl+S or <F5>.
_M_KEY = N_("Key")


class HandlerBox(Editor):
    """An editable combobox of handler names for the event ``field.key[6:]``."""

    text_input = True

    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        self.widget = ttk.Combobox(self.frame, textvariable=self.var, values=field.choices)
        self.widget.grid(row=0, column=0, sticky="ew")
        self._bind(self.widget)
        for sequence in ("<Return>", "<KP_Enter>", "<<ComboboxSelected>>"):
            self.widget.bind(sequence, lambda _e: self.commit_pending() and None)
        self.widget.bind("<FocusOut>", lambda _e: self.commit_pending(), add="+")
        self.widget.bind("<Escape>", lambda _e: self.revert())
        bind_history(self.widget, lambda redo: host.history_key(self, redo))
        self.load(field)

    def text(self) -> str:
        return self.var.get().strip()


def handler_names(document: Document) -> tuple[str, ...]:
    """Every handler name already used in the document, sorted."""
    names = {e.handler for n in document.walk() for e in getattr(n, "events", ())}
    names |= {n.handler for n in document.walk() if isinstance(n, Action) and n.handler}
    return tuple(sorted(names))


class EventsTab:
    """The tab body; ``host`` is the inspector (commits, status, history keys)."""

    def __init__(self, parent: Any, host: Any) -> None:  # noqa: ANN401 - Tk parent, inspector
        self.host = host
        self.frame = ttk.Frame(parent, padding=6)
        self.frame.columnconfigure(1, weight=1)
        self.widget: Widget | None = None
        self.boxes: list[HandlerBox] = []
        self._shown_keys: tuple[str, ...] = ()

    def editors(self) -> list[HandlerBox]:
        return list(self.boxes)

    def render(self, nodes: tuple[object, ...], document: Document | None) -> None:
        """Rebuild the rows for ``nodes`` (one widget) or show why there are none."""
        for child in self.frame.winfo_children():
            child.destroy()
        self.boxes = []
        node = nodes[0] if len(nodes) == 1 else None
        spec = self.host.session.registry.get(node.class_name) if isinstance(node, Widget) else None
        self.widget = node if isinstance(node, Widget) and document is not None else None
        if self.widget is None or document is None:
            if nodes:
                ttk.Label(self.frame, text=_(_M_SELECT_ONE), wraplength=240).grid(sticky="w")
            return
        names = handler_names(document)
        handlers = {e.name: e.handler for e in self.widget.events}
        keys = tuple(n for n in handlers if n.startswith("key:"))
        self._shown_keys = keys
        for row, name in enumerate((*(spec.events if spec else ()), *keys)):
            ttk.Label(self.frame, text=name).grid(row=row, column=0, sticky="w", padx=(0, 8))
            field = Field(f"event:{name}", "", name, "handler", handlers.get(name, ""),
                          choices=names)  # fmt: skip
            box = HandlerBox(self.frame, field, self.host)
            box.frame.grid(row=row, column=1, sticky="ew", pady=1)
            self.boxes.append(box)
            if name in keys:
                remove = ttk.Button(self.frame, text=_(_M_REMOVE),
                                    command=partial(self.change, name, ""))  # fmt: skip
                remove.grid(row=row, column=2, padx=(4, 0))
        row = len(self.boxes)
        ttk.Label(self.frame, text=_(_M_KEY)).grid(row=row, column=0, sticky="w", pady=(8, 0))
        self.key_entry = ttk.Entry(self.frame)
        self.key_entry.grid(row=row, column=1, sticky="ew", pady=(8, 0))
        self.key_entry.bind("<Return>", lambda _e: self.add_key())
        bind_history(self.key_entry, self._key_history)
        add = ttk.Button(self.frame, text=_(_M_ADD_KEY), command=self.add_key)
        add.grid(row=row, column=2, padx=(4, 0), pady=(8, 0))
        if self.host.read_only:
            for box in self.boxes:
                box.set_enabled(False)
            self.key_entry.state(["disabled"])
            add.state(["disabled"])

    def refresh(self, document: Document | None) -> None:
        """Reload the values after a stack change (a changed set of key events rebuilds)."""
        widget = self.widget
        if widget is None or document is None:
            return
        keys = tuple(e.name for e in widget.events if e.name.startswith("key:"))
        if keys != self._shown_keys:
            self.render((widget,), document)
            return
        handlers, names = {e.name: e.handler for e in widget.events}, handler_names(document)
        for box in self.boxes:
            if not box.pending():
                name = box.field.key[6:]
                box.load(replace(box.field, value=handlers.get(name, ""), choices=names))
                box.widget.configure(values=names)

    def change(self, name: str, handler: str, editor: Editor | None = None) -> bool:
        """Bind ``name`` to ``handler`` ("" unbinds) with one ``SetEvents``."""
        widget, stack = self.widget, self.host.session.stack
        if widget is None or stack is None:
            return False
        events = list(widget.events)
        index = next((k for k, e in enumerate(events) if e.name == name), None)
        if index is not None and handler:
            events[index] = replace(events[index], handler=handler)  # keeps its extras
        elif index is not None:
            del events[index]
        elif handler:
            events.append(Event(name=name, handler=handler))
        outcome: Outcome = stack.execute(SetEvents(widget, events))
        return bool(self.host.report(editor, outcome))

    def _key_history(self, redo: bool) -> str:
        """Ctrl+Z/Ctrl+Y in the Key field: clear the typed sequence first, else undo/redo."""
        entry = self.key_entry
        return history_action(redo, pending=lambda: bool(entry.get()),
                              revert=lambda: entry.delete(0, "end"),
                              invoke=self.host.invoke)  # fmt: skip

    def add_key(self) -> None:
        """Add the typed key sequence (a handler named after the widget); the guard judges it."""
        sequence, widget = self.key_entry.get().strip(), self.widget
        stack = self.host.session.stack
        if widget is None or stack is None or not sequence:
            return
        event = Event(name=f"key:{sequence}", handler=f"on_{widget.id}_key")
        self.host.report(None, stack.execute(SetEvents(widget, [*widget.events, event])))
