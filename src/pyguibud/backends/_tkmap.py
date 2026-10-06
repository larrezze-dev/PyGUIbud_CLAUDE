"""Pure Tk mapping tables, shared by the Tk builder (``_tk``) and the code generator (ADR-008).

The single source of how the abstract ``.ui`` vocabulary maps to Tk/ttkbootstrap: ``_tk`` uses it
when building, ``pyguibud.codegen`` evaluates it at generation time and emits the results as
literals. Toolkit-free and side-effect-free (ADR-007): nothing here imports ``tkinter``.
"""

from __future__ import annotations

import re
from typing import Literal

from pyguibud.core.model import NS_TB
from pyguibud.core.validate import MAX_TEXT_LENGTH
from pyguibud.i18n import N_

__all__ = ["Wiring", "clip_text", "event_wiring"]

_SELECT = {
    "Notebook": "<<NotebookTabChanged>>",
    "Combobox": "<<ComboboxSelected>>",
    "Listbox": "<<ListboxSelect>>",
    "Treeview": "<<TreeviewSelect>>",
}
_DOUBLE = ("<Double-Button-1>", "<Return>", "<KP_Enter>")
_ACTIVATE = {"Entry": ("<Return>", "<KP_Enter>"), "Listbox": _DOUBLE, "Treeview": _DOUBLE}
_VAR_OPTION = dict.fromkeys(
    ("Entry", "Combobox", "Spinbox", "Label"), "textvariable"
) | dict.fromkeys(("Scale", "Progressbar", "Checkbutton", "Radiobutton"), "variable")
# The private variable an unbound widget gets so that ``change`` can be traced.
_TRACE_VAR = {"Checkbutton": "bool", "Scale": "double"} | dict.fromkeys(
    ("Entry", "Combobox", "Spinbox", "Radiobutton"), "string"
)
_OPTION = {
    ("Scale", "minimum"): "from_",
    ("Scale", "maximum"): "to",
    ("Spinbox", "minimum"): "from_",
    ("Spinbox", "maximum"): "to",
    ("ScrolledFrame", "autohide"): "auto_hide",
}
_MNEMONIC = frozenset({"Button", "Checkbutton", "Radiobutton"})  # underline only (trim 2)
_TK_BASED = frozenset({"Text", "Listbox", "Canvas"})  # no ``bootstyle``
_PADDED = frozenset({"Frame", "LabelFrame", "ScrolledFrame"})
_BOOTSTYLE_RE = re.compile(r"[a-z]+(-[a-z]+)*( [a-z]+(-[a-z]+)*)*")
_BOOTSTYLE = f"{{{NS_TB}}}bootstyle"
# Core class -> ttkbootstrap attribute (runtime spec 8.4); the rest use the same name.
_RENAMED = {"LabelFrame": "Labelframe", "PanedWindow": "Panedwindow"}
_CLASSES = (
    *("Frame", "LabelFrame", "Notebook", "PanedWindow", "ScrolledFrame", "Label", "Button"),
    *("Entry", "Text", "Checkbutton", "Radiobutton", "Combobox", "Spinbox", "Scale"),
    *("Progressbar", "Separator", "Listbox", "Treeview", "Scrollbar", "Canvas", "Menu"),
    "Toplevel",
)
# Translators: logged when a .ui uses an extension widget the runtime cannot render yet.
_M_FALLBACK = N_("The widget class '{name}' is shown as its fallback '{fallback}'.")
# Translators: a ttkbootstrap style name from a .ui file was not applied.
_M_BOOTSTYLE = N_("The bootstyle '{value}' of '{id}' is ignored.")
_ELLIPSIS = "…"

Wiring = tuple[Literal["command", "trace", "modified", "virtual", "bind", "key"], tuple[str, ...]]


def event_wiring(class_name: str, event: str) -> Wiring:
    """How an abstract event of a core class is wired in Tk (pure; the validator vetted it)."""
    if event == "command" or (event == "change" and class_name == "Scrollbar"):
        return "command", ()
    if event == "change":
        return ("modified", ("<<Modified>>",)) if class_name == "Text" else ("trace", ())
    if event == "select":
        return "virtual", (_SELECT[class_name],)
    if event == "activate":
        return "bind", _ACTIVATE[class_name]
    if event.startswith("key:"):
        return "key", (event[4:],)
    return "bind", ("<FocusIn>" if event == "focus_in" else "<FocusOut>",)


def clip_text(text: str, underline: int) -> tuple[str, int] | None:
    """``text`` cut to ``MAX_TEXT_LENGTH`` characters with an ellipsis, or None if it fits.

    Tk freezes for minutes on a one-line text of a few million characters, and a translation
    is never validated, so every display text is bounded here. ``underline`` is dropped when it
    falls in the removed part.
    """
    if len(text) <= MAX_TEXT_LENGTH:
        return None
    kept = MAX_TEXT_LENGTH - len(_ELLIPSIS)
    return text[:kept] + _ELLIPSIS, underline if underline < kept else -1
