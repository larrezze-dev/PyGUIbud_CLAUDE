"""One inspector editor per field kind (Tk; spec properties-save-load 3.2).

An editor only shows a value and reports what the user typed or picked; the inspector (its
``host``) parses, builds the command and runs it. ``shown`` is the text last loaded from the
model, so an untouched editor never commits (no phantom edits of defaults or mixed values).
"""

from __future__ import annotations

import bisect
import contextlib
import itertools
import tkinter
from collections.abc import Callable
from dataclasses import replace
from tkinter import ttk
from typing import Any, Protocol

from ttkbootstrap.widgets.tooltip import ToolTip

from pyguibud.core.keys import tk_shortcut
from pyguibud.core.model import Prop
from pyguibud.core.text import printable
from pyguibud.designer.icons_tk import icons
from pyguibud.designer.properties import Field
from pyguibud.designer.render_plan import CANVAS_TEXT_LIMIT, clip_text
from pyguibud.designer.theme_tk import INVALID_PREFIX, STYLE_COMBOBOX, STYLE_ENTRY, STYLE_SPINBOX
from pyguibud.i18n import N_, _

__all__ = [
    "INVALID",
    "Editor",
    "EditorHost",
    "after_paste",
    "bind_history",
    "guard_pastes",
    "history_action",
    "make_editor",
]

#: Style prefix of an editor whose text was refused (configured with the other Designer styles).
INVALID = INVALID_PREFIX
_M_NONE = N_("(none)")
_M_NEW_VARIABLE = N_("New variable…")
_M_ADD_IMAGE = N_("Add image…")
_M_CHOOSE = N_("Choose…")
_M_EDIT_TEXT = N_("Edit text…")
# Translators: under a read-only preview of a very long text; {length} is its number of
# characters. "Reset" is the ↺ button at the end of the row, which clears the text.
_M_TOO_LONG = N_(
    "This text has {length} characters: too long to edit here. Reset it to type a shorter one."
)
#: Under a read-only id (no Reset): the msgid of ``backends._tk`` (the field label as {id}).
_M_CLIPPED = N_("The text of '{id}' has {length} characters; only the first {limit} are shown.")
# Translators: the sticky sides of a grid cell: North, East, South, West (one letter each).
# Keep the letters N, E, S, W: they are the values stored in the .ui file and named in messages.
_STICKY = (("n", N_("N")), ("e", N_("E")), ("s", N_("S")), ("w", N_("W")))
_BUTTONS = tuple((token, token) for token in ("ok", "cancel", "yes", "no", "close"))
#: Pseudo values of the choice editors (never a valid id, so they cannot clash).
NEW, ADD = "\x00new", "\x00add"


class EditorHost(Protocol):
    """What an editor calls on the inspector."""

    def commit(self, editor: Editor, value: str | Prop | None, *, merge: bool = False) -> bool: ...
    def focus_in(self, editor: Editor) -> None: ...
    def history_key(self, editor: Editor, redo: bool) -> str: ...
    def special(self, editor: Editor, what: str) -> None: ...


class Editor:
    """Base editor: ``widget`` is the focusable part, placed in ``frame`` by the subclass."""

    text_input = False  # True: Ctrl+Z reverts typed text first (spec 3.3)
    locked = False  # a read-only document: the editor stays disabled whatever it loads
    long = False  # a read-only preview of a text too long for an Entry (H41)

    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        self.field, self.host = field, host
        self.frame = ttk.Frame(parent)
        self.frame.columnconfigure(0, weight=1)
        self.shown = ""
        self.widget: Any = None
        self.var = tkinter.StringVar(parent)
        self.invalid = False  # marked red after a refusal
        self.style = ""  # the editor's own (normal) style; "" keeps the class style
        self.alert: ttk.Label | None = None  # the non-colour cue of an invalid editor (D8)

    def _bind(self, widget: Any) -> None:  # noqa: ANN401 - a Tk widget
        widget.bind("<FocusIn>", lambda _e: self.host.focus_in(self), add="+")

    def load(self, field: Field) -> None:
        """Show the model value of ``field`` (the text is replaced; marks are cleared)."""
        self.field, self.shown = field, field.value or ""
        self.var.set(self.shown)
        self.set_invalid(False)

    def text(self) -> str:
        return self.var.get()

    def pending(self) -> bool:
        """True while the shown text differs from the model value (typed, not committed)."""
        return self.text_input and self.text() != self.shown

    def commit_pending(self) -> bool:
        """Commit typed text. Text typed back to the model value after a refusal commits too:
        the (no-op) command is accepted and clears the mark and the old reason (rule C2)."""
        if not self.pending() and not self.invalid:
            return True
        return self.host.commit(self, self.text())

    def revert(self) -> None:
        self.var.set(self.shown)
        self.set_invalid(False)

    def _pick(self, value: str) -> None:
        """Commit a picked value (a toggle, a list choice). A refused pick shows the model value
        again: unlike typed text there is nothing to correct, and the reason stays in the status
        bar (spec 3.3, QA-14a2 N5)."""
        if not self.host.commit(self, value):
            self.load(self.field)

    def set_invalid(self, invalid: bool) -> None:
        widget = self.widget
        if widget is None or not self.text_input:
            return
        self.invalid = invalid
        base = widget.winfo_class()
        widget.configure(style=f"{INVALID}.{base}" if invalid else self.style or base)
        if self.alert is None and invalid:
            image = icons(self.frame).get("error")
            self.alert = ttk.Label(self.frame, image=image or "", text="" if image else "!")
        if self.alert is not None:
            if invalid:
                self.alert.grid(row=0, column=8, padx=(4, 0))
            else:
                self.alert.grid_remove()

    def set_enabled(self, enabled: bool) -> None:
        """Enable the editor, or make it read-only: entries and spinboxes stay selectable and
        copyable (``readonly``); everything else is ``disabled`` (D9). A combobox is readonly
        in its normal state, so it must never get that flag removed."""
        enabled = enabled and not self.locked
        for child in self.frame.winfo_children():
            if isinstance(child, ttk.Widget) and not isinstance(child, ttk.Label | ttk.Frame):
                text = isinstance(child, ttk.Entry) and not isinstance(child, ttk.Combobox)
                if enabled:
                    child.state(["!disabled", "!readonly"] if text else ["!disabled"])
                else:
                    child.state(["readonly"] if text else ["disabled"])


class _Label(Editor):
    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        ttk.Label(self.frame, textvariable=self.var, anchor="w").grid(row=0, column=0, sticky="ew")


class _Text(Editor):
    """Entry for strings, ids, handlers, shortcuts, numbers and colours."""

    text_input = True
    note: ttk.Label | None = None
    hint: ToolTip | None = None

    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        if field.kind in ("int", "float"):
            low, high = field.minimum, field.maximum
            self.style = STYLE_SPINBOX
            self.widget = ttk.Spinbox(self.frame, textvariable=self.var, width=8, style=self.style,
                                      from_=-10_000 if low is None else low,
                                      to=10_000 if high is None else high,
                                      increment=1 if field.kind == "int" else 0.1,
                                      command=self._arrow)  # fmt: skip
        elif field.kind == "bootstyle":  # an editable combobox: pick a suggestion or type
            self.style = STYLE_COMBOBOX
            self.widget = ttk.Combobox(self.frame, textvariable=self.var, values=field.choices,
                                       width=12, style=self.style)  # fmt: skip
            self.widget.bind("<<ComboboxSelected>>", lambda _e: self._enter())
        else:
            self.style = STYLE_ENTRY
            self.widget = ttk.Entry(self.frame, textvariable=self.var, width=12, style=self.style)
            self.widget.bind("<<Paste>>", lambda _e: self._paste())
        self.widget.grid(row=0, column=0, sticky="ew")
        self._bind(self.widget)
        for sequence in ("<Return>", "<KP_Enter>"):
            self.widget.bind(sequence, lambda _e: self._enter())
        self.widget.bind("<FocusOut>", lambda _e: self.commit_pending(), add="+")
        self.widget.bind("<Escape>", lambda _e: self._escape())
        if field.kind == "colour":
            self.swatch = tkinter.Frame(self.frame, width=16, height=16, borderwidth=1,
                                        relief="solid")  # fmt: skip
            self.swatch.grid(row=0, column=1, padx=(4, 0))
            self._button(_M_CHOOSE, "colour", 2)
        elif field.key.startswith("prop:") and field.kind == "string":
            self._button(_M_EDIT_TEXT, "text", 1, glyph="…")

    def _button(self, msgid: str, what: str, column: int, glyph: str | None = None) -> None:
        button = ttk.Button(self.frame, text=glyph or _(msgid),
                            command=lambda: self.host.special(self, what))  # fmt: skip
        button.grid(row=0, column=column, padx=(4, 0))
        self.button, self.button_msgid = button, msgid if glyph is None else None

    def load(self, field: Field) -> None:
        # Tk takes seconds to lay out a 100,000-character Entry: show the canvas clip read-only.
        # ``field`` keeps the full value and an untouched preview is never pending (H41).
        length = len(field.value or "")
        texts = field.key.startswith("prop:") or field.key == "place:page:text"  # QA-19c-06
        long = length > CANVAS_TEXT_LIMIT  # an id or handler too (from a file, QA-19f-08)
        super().load(replace(field, value=clip_text(field.value or "")) if long else field)
        self.field = field
        if long != self.long:
            self.long = long
            self.set_enabled(not long)
        if long and self.note is None:
            self.note = ttk.Label(self.frame, wraplength=self.frame.winfo_fpixels("2.2i"))
        if self.note is not None and long:
            note = _(_M_TOO_LONG).format(length=length) if texts else _(_M_CLIPPED).format(
                id=_(field.label), length=length, limit=CANVAS_TEXT_LIMIT)  # fmt: skip
            self.note.configure(text=note)
            self.note.grid(row=1, column=0, columnspan=3, sticky="w")
        elif self.note is not None:
            self.note.grid_remove()
        self._escaped_hint()
        swatch = getattr(self, "swatch", None)
        if swatch is not None:
            # A colour Tk does not know leaves the swatch as it is (the guard judges the text).
            with contextlib.suppress(tkinter.TclError):
                swatch.configure(background=self.shown or self.frame.winfo_toplevel()["bg"])

    def _escaped_hint(self) -> None:
        """Show control and bidi characters of the model text escaped in a tooltip. The entry
        keeps the raw text, so an untouched field never commits the escaped form (H61)."""
        safe = printable(self.shown)
        if safe == self.shown and self.hint is None:
            return
        if self.hint is None:
            self.hint = ToolTip(self.widget, text=safe)
        self.hint.text = safe

    def _enter(self) -> str:
        # Only typed text commits (QA-14a1-18): Enter in an untouched field, above all a "(mixed)"
        # one whose entry is empty, must not write that empty text to every selected node.
        if self.commit_pending():
            self.shown = self.text()
        return "break"

    def _escape(self) -> str:
        self.revert()
        return "break"

    def commit_pending(self) -> bool:
        # The preview is read-only, so nothing was typed; its text is the clip, never the model
        # value, so it must not be committed, even after a refusal marked it (QA-19c-05).
        return self.long or super().commit_pending()

    def _paste(self) -> str | None:
        """A paste that makes the text too long for the Entry is committed without landing in
        it (H41); ``guard_pastes`` refuses one in any other entry."""
        text = None if self.widget.instate(["readonly"]) else after_paste(self.widget)
        if text is None or len(text) <= CANVAS_TEXT_LIMIT:
            return None
        self.host.commit(self, text)
        return "break"

    def _arrow(self) -> None:
        # ttk's spin (arrows, Up/Down, the wheel) only stops at ``disabled``, and a read-only
        # spinbox is ``readonly`` so its text stays copyable (D9): it has already set the new
        # value when it runs this command, so show the model value again (QA-14p-02).
        if self.widget.instate(["readonly"]):
            self.revert()
            return
        self.host.commit(self, self.text(), merge=True)  # one undo step per focus session


class _Bool(Editor):
    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        self.widget = ttk.Checkbutton(self.frame, variable=self.var, onvalue="true",
                                      offvalue="false", command=self._toggle)  # fmt: skip
        self.widget.grid(row=0, column=0, sticky="w")
        self._bind(self.widget)

    def load(self, field: Field) -> None:
        super().load(field)
        self.widget.state(["alternate"] if field.value is None else ["!alternate"])

    def _toggle(self) -> None:
        self.widget.state(["!alternate"])
        self._pick(self.var.get())


_EXTRA = {
    "image": [("", _M_NONE), (ADD, _M_ADD_IMAGE)],
    "variable": [("", _M_NONE), (NEW, _M_NEW_VARIABLE)],
}


class _Choice(Editor):
    """Read-only combobox: enums, images and variables (with "(none)" and "New…" entries)."""

    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        self.widget = ttk.Combobox(self.frame, textvariable=self.var, state="readonly", width=12,
                                   style=STYLE_COMBOBOX)  # fmt: skip
        self.widget.grid(row=0, column=0, sticky="ew")
        self.widget.bind("<<ComboboxSelected>>", lambda _e: self._picked())
        self._bind(self.widget)
        self._values: list[str] = []

    def load(self, field: Field) -> None:
        self.field = field
        extra = _EXTRA.get(field.kind, [])
        self._values = [v for v, _m in extra[:1]] + list(field.choices) + [v for v, _m in extra[1:]]
        names = {v: _(m) for v, m in extra}
        self.widget.configure(values=[names.get(v, v) for v in self._values])
        self.shown = field.value or ""
        self.var.set("" if field.value is None else names.get(self.shown, self.shown))

    def _picked(self) -> None:
        index = int(self.widget.current())
        value = self._values[index] if 0 <= index < len(self._values) else ""
        if value in (NEW, ADD):
            self.load(self.field)
            self.host.special(self, value)
        elif value != self.shown:
            self._pick(value)


class _Flags(Editor):
    """Checkbuttons for the sticky sides (``"nsew"``) or the dialog buttons (``"ok,cancel"``)."""

    def __init__(self, parent: Any, field: Field, host: EditorHost) -> None:  # noqa: ANN401
        super().__init__(parent, field, host)
        self.tokens = _STICKY if field.kind == "sticky" else _BUTTONS
        self.sep = "" if field.kind == "sticky" else ","
        self.flags: list[tuple[str, tkinter.BooleanVar, ttk.Checkbutton]] = []
        for k, (token, msgid) in enumerate(self.tokens):
            flag = tkinter.BooleanVar(parent)
            box = ttk.Checkbutton(self.frame, text=_(msgid) if self.sep == "" else msgid,
                                  variable=flag, command=self._toggle)  # fmt: skip
            box.grid(row=0, column=k, sticky="w", padx=(0, 4))
            self._bind(box)
            self.flags.append((token, flag, box))
        self.widget = self.flags[0][2]

    def _split(self, value: str) -> list[str]:
        return list(value) if self.sep == "" else [t for t in value.split(",") if t]

    def load(self, field: Field) -> None:
        super().load(field)
        on = self._split(field.value or "")
        for token, flag, box in self.flags:
            flag.set(token in on)
            box.state(["alternate"] if field.value is None else ["!alternate"])

    def _toggle(self) -> None:
        # Keep the order of an opened file: unticked tokens go, new ones are appended.
        ticked = {token for token, flag, _box in self.flags if flag.get()}
        kept = [t for t in self._split(self.shown) if t in ticked]
        kept += [t for t, _f, _b in self.flags if t in ticked and t not in kept]
        self._pick(self.sep.join(kept))

    def retranslate(self) -> None:
        for (_token, msgid), (_t, _f, box) in zip(self.tokens, self.flags, strict=True):
            box.configure(text=_(msgid) if self.sep == "" else msgid)


_KINDS: dict[str, Callable[[Any, Field, EditorHost], Editor]] = {
    "class": _Label, "bool": _Bool, "enum": _Choice, "image": _Choice, "variable": _Choice,
    "sticky": _Flags, "buttons": _Flags,
}  # fmt: skip


def make_editor(parent: Any, field: Field, host: EditorHost) -> Editor:  # noqa: ANN401
    """The editor for ``field.kind`` (an Entry or Spinbox for every text-like kind)."""
    editor = _KINDS.get(field.kind, _Text)(parent, field, host)
    editor.load(field)
    if editor.widget is not None and editor.text_input:
        bind_history(editor.widget, lambda redo: editor.host.history_key(editor, redo))
    return editor


def after_paste(widget: Any, primary: bool = False) -> str | None:  # noqa: ANN401 - a ttk entry
    """The text of ``widget`` once the clipboard is pasted at its cursor, over its selection
    (None: nothing to paste). Tk 8.6 counts a character outside the BMP as two indices
    (UTF-16), the Python string as one: the indices are converted (QA-19c-02). ``primary``:
    the X11 middle-click paste, which inserts the PRIMARY selection at the mouse (only the
    length is exact) and replaces nothing."""
    try:
        which = "PRIMARY" if primary else "CLIPBOARD"  # "clipboard get" reads CLIPBOARD too
        pasted, text = str(widget.selection_get(selection=which)), str(widget.get())
        first = last = int(widget.index("insert"))
        if widget.selection_present() and not primary:  # the paste replaces the selection
            first, last = int(widget.index("sel.first")), int(widget.index("sel.last"))
    except tkinter.TclError:
        return None
    if int(widget.tk.call("string", "length", "\U0001f600")) > 1:  # Tk 8.6: UTF-16 indices
        units = list(itertools.accumulate((1 + (ord(c) > 0xFFFF) for c in text), initial=0))
        first, last = bisect.bisect_left(units, first), bisect.bisect_left(units, last)
    return text[:first] + pasted + text[last:]


def guard_pastes(root: tkinter.Misc, refuse: Callable[[], None]) -> Callable[[], None]:
    """Refuse, in every ttk entry, spinbox and combobox, a paste that would leave more than
    :data:`CANVAS_TEXT_LIMIT` characters: Tk lays a long Entry out for seconds, per key press
    too (QA-19c-01). A class binding, so a ``_Text`` editor's own binding runs first (and
    commits a long text). ``<<PasteSelection>>`` (X11 middle click) is guarded the same way.
    ``refuse()`` says why; the returned function removes the guard."""

    def check(path: str, primary: str) -> str:
        widget = root.nametowidget(path)
        if widget.instate(["readonly"]) or widget.instate(["disabled"]):
            return ""  # ttk pastes nothing there
        text = after_paste(widget, primary == "1")
        if text is None or len(text) <= CANVAS_TEXT_LIMIT:
            return ""
        refuse()
        return "break"

    name, mark, scripts = root.register(check), ";# pyguibud paste guard\n", {}
    for cls in ("TEntry", "TSpinbox", "TCombobox"):
        for primary, event in enumerate(("<<Paste>>", "<<PasteSelection>>")):
            script = scripts[cls, event] = str(root.bind_class(cls, event)).split(mark)[-1]
            guard = f'if {{"[{name} %W {primary}]" == "break"}} break {mark}{script}'
            root.tk.call("bind", cls, event, guard)  # a second app replaces the first's guard

    def remove() -> None:
        for (cls, event), script in scripts.items():
            if name in str(root.bind_class(cls, event)):  # not a later app's guard
                root.tk.call("bind", cls, event, script)
        root.deletecommand(name)

    return remove


def bind_history(widget: Any, handler: Callable[[bool], str]) -> None:  # noqa: ANN401
    """Bind the shell's Undo/Redo chords on a text editor (``handler(redo)``; spec 3.3)."""
    aqua = str(widget.tk.call("tk", "windowingsystem")) == "aqua"
    for chord, redo in (("Ctrl+Z", False), ("Ctrl+Y", True), ("Ctrl+Shift+Z", True)):
        for sequence in tk_shortcut(chord, aqua=aqua).sequences:
            widget.bind(sequence, lambda _e, r=redo: handler(r))


def history_action(
    redo: bool,
    *,
    pending: Callable[[], bool],
    revert: Callable[[], None],
    invoke: Callable[[str], None],
) -> str:
    """Ctrl+Z/Ctrl+Y in a text field: revert the typed text first, else undo/redo (spec 3.3).

    Shared by the inspector's editors, the Events tab and the Variables panel, so every text
    field of the designer answers the history keys the same way.
    """
    if pending():
        revert()
    else:
        invoke("edit.redo" if redo else "edit.undo")
    return "break"


def retranslate(editor: Editor) -> None:
    """Re-read the translated texts of ``editor`` (buttons, sticky letters, choice names)."""
    msgid = getattr(editor, "button_msgid", None)
    if msgid:
        editor.button.configure(text=_(msgid))  # type: ignore[attr-defined]
    if isinstance(editor, _Flags):
        editor.retranslate()
    elif isinstance(editor, _Choice) or (isinstance(editor, _Text) and editor.long):
        editor.load(editor.field)
