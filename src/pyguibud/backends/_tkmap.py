"""Pure Tk mapping tables, shared by the Tk builder (``_tk``) and the code generator (ADR-008).

The single source of how the abstract ``.ui`` vocabulary maps to Tk/ttkbootstrap: ``_tk`` uses it
when building, ``pyguibud.codegen`` evaluates it at generation time and emits the results as
literals. Toolkit-free and side-effect-free (ADR-007): nothing here imports ``tkinter``.
"""

from __future__ import annotations

import datetime
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from pyguibud.core.errors import format_message
from pyguibud.core.model import NS_TB
from pyguibud.core.validate import BOOTSTYLE_RE, MAX_TEXT_LENGTH
from pyguibud.i18n import N_

__all__ = [
    "TB_EXT",
    "TbExt",
    "Wiring",
    "clip_text",
    "event_wiring",
    "iso_date",
    "split_headings",
    "toggle_style",
]

_logger = logging.getLogger(__name__)

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
_BOOTSTYLE_RE = BOOTSTYLE_RE  # the grammar lives in core (R83)
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
# Translators: {value} is the text of a date property that is not a real calendar date.
_M_BAD_DATE = N_("The date '{value}' is not a valid calendar date; it is ignored.")
# Translators: {given} and {expected} are numbers; {text} is the ';'-separated headings text.
_M_HEADINGS = N_("{given} column headings for {expected} columns: '{text}'")
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


# ---------------------------------------------------------------- ttkbootstrap extensions (tb:)
@dataclass(frozen=True, slots=True)
class TbExt:
    """How a built-in ``tb:`` widget is made from ttkbootstrap (factories and codegen)."""

    cls: str  # attribute of the ttkbootstrap module
    options: Mapping[str, str]  # property -> constructor keyword; other properties are not passed
    inner: str | None = None  # attribute holding the widget that behaves as the fallback
    variable: str | None = None  # where the variable goes, see ``link``
    #: ``option``: a constructor keyword; ``inner``: an option of the inner widget; ``link``: an
    #: attribute holding the widget's own variable, kept in sync with the bound one.
    link: Literal["option", "inner", "link"] = "option"
    after: tuple[str, ...] = field(default=())  # properties configured on the inner widget


def _same(*names: str) -> dict[str, str]:
    return {name: name for name in names}


TB_EXT: Mapping[str, TbExt] = {
    "tb:Meter": TbExt(
        "Meter",
        {"value": "amount_used", "maximum": "amount_total"}
        | _same("subtext", "meter_type", "meter_size", "meter_thickness", "amount_format")
        | _same("show_text", "interactive"),
        variable="amount_used_var",
        link="link",
    ),
    "tb:Floodgauge": TbExt(
        "Floodgauge",
        _same("value", "maximum", "mode", "orient", "length", "mask"),
        variable="variable",
    ),
    "tb:DateEntry": TbExt(
        "DateEntry",
        _same("width", "date_format", "first_weekday", "value"),
        "entry",
        "textvariable",
        "inner",
    ),
    "tb:Tableview": TbExt(
        "Tableview",
        {"columns": "coldata"}
        | _same("height", "paginated", "searchable", "yscrollbar", "autofit", "pagesize"),
        "view",
        after=("selectmode",),
    ),
    "tb:ToggleButton": TbExt("Checkbutton", {}, None, "variable"),
}
_COLOURS = ("primary", "secondary", "success", "info", "warning", "danger", "light", "dark")


def toggle_style(bootstyle: str | None, shape: str) -> str:
    """ToggleButton's bootstyle: ``"{colour}-{shape}-toggle"`` with the first colour token."""
    tokens = (bootstyle or "").replace("-", " ").split()
    colour = next((token for token in tokens if token in _COLOURS), None)
    return f"{colour}-{shape}-toggle" if colour else f"{shape}-toggle"


def _warn(msgid: str, **params: object) -> None:
    """Log a runtime warning in the current pyguibud language (as the loader's own ones)."""
    _logger.warning("%s", format_message(msgid, params))


def iso_date(value: str) -> datetime.date | None:
    """A ``YYYY-MM-DD`` value as a date; a calendar-invalid one is logged and gives None."""
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        _warn(_M_BAD_DATE, value=value)
        return None


def split_headings(text: str, count: int) -> list[str]:
    """``count`` headings from a ``;``-separated text, padded or truncated (logged, D12)."""
    headings = text.split(";")
    if len(headings) != count:
        _warn(_M_HEADINGS, given=len(headings), expected=count, text=text)
    return (headings + [""] * count)[:count]
