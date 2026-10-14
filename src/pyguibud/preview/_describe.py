"""``describe(ui)``: a canonical, JSON-ready view of a built interface (spec preview-export 2).

The preview child prints it with ``--describe``; the parity tests describe a generated module the
same way, so "the preview matches the export" is a plain ``==``. ``tkinter`` is imported only
when describing (ADR-013: importing ``pyguibud.preview`` loads no toolkit).
"""

from __future__ import annotations

import re
from typing import Any

from pyguibud.core.keys import Chord, format_chord, parse_chord

__all__ = ["describe", "min_size", "pack_fill", "portable_describe", "portable_shortcut"]

_OPTIONS = (
    *("text", "underline", "compound", "state", "padding", "style", "orient", "from", "to"),
    *("wrap", "show", "value", "width", "height", "length", "maximum", "mode", "increment"),
    *("selectmode", "values", "justify", "anchor", "takefocus"),
)
_ENTRY_OPTIONS = ("label", "underline", "accelerator", "state", "compound")
#: The ttkbootstrap class of each tb: widget -> the core class it behaves as (portable view).
_TB_OUTER = {"Meter": "Progressbar", "Floodgauge": "Progressbar", "DateEntry": "Entry"} | {
    "Tableview": "Treeview"
}


def _text(value: Any) -> str:  # noqa: ANN401 - any Tcl value
    text = " ".join(str(part) for part in value) if isinstance(value, tuple) else str(value)
    return re.sub(r"PY_VAR\d+", "<variable>", text)  # variable names are numbered per process


def _option(read: Any, *args: Any) -> str | None:  # noqa: ANN401 - Tk methods
    import tkinter

    try:
        return _text(read(*args))
    except tkinter.TclError:
        return None


def _image(widget: Any, read: Any, *args: Any) -> list[int] | None:  # noqa: ANN401 - Tk objects
    value = _option(read, *args)
    if not value:
        return None
    name = value.split()[0]
    return [int(widget.tk.call("image", kind, name)) for kind in ("width", "height")]


def _menu(menu: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - a tkinter.Menu
    last = menu.index("end")
    entries: list[dict[str, Any]] = []
    for index in range(0 if last is None else last + 1):
        entry: dict[str, Any] = {"type": str(menu.type(index))}
        if entry["type"] != "separator":
            entry.update({o: _option(menu.entrycget, index, o) for o in _ENTRY_OPTIONS})
            entry["image"] = bool(menu.entrycget(index, "image"))
        entries.append(entry)
    return entries


def _tb_outer(widget: Any) -> Any:  # noqa: ANN401 - Tk widgets
    """The ttkbootstrap widget of a ``tb:`` widget (``ui.<id>`` holds its inner one), or None."""
    for _level in range(3):  # the widget, a DateEntry's entry, a Tableview's view
        if type(widget).__name__ in _TB_OUTER:
            return widget
        widget = getattr(widget, "master", None)
    return None


def _widget(widget: Any) -> dict[str, Any]:  # noqa: ANN401 - a Tk widget
    import tkinter

    outer = _tb_outer(widget)
    info: dict[str, Any] = {"class": type(outer).__name__ if outer else widget.winfo_class()}
    outer = outer or widget  # a tb: widget is placed by its outer widget
    info["manager"] = outer.winfo_manager()
    if info["manager"] in {"grid", "pack"}:
        placed = (outer.grid_info if info["manager"] == "grid" else outer.pack_info)()
        info["place"] = {k: _text(v) for k, v in sorted(placed.items()) if k != "in"}
    if isinstance(widget, tkinter.Menu):
        info["entries"] = _menu(widget)
        return info
    info.update({o: v for o in _OPTIONS if (v := _option(widget.cget, o)) is not None})
    info["image"] = _image(widget, widget.cget, "image")
    if info["class"] == "TNotebook":
        info["tabs"] = [
            {
                **{k: _option(widget.tab, t, k) for k in ("text", "underline", "sticky")},
                "image": _image(widget, widget.tab, t, "image"),
            }
            for t in widget.tabs()
        ]
    info["bindings"] = sorted(widget.bind())
    return info


def _scope(scope: Any, prefix: str = "") -> dict[str, Any]:  # noqa: ANN401 - a UiScope
    import tkinter

    found: dict[str, Any] = {}
    for key, obj in scope.widgets.items():
        if isinstance(obj, tkinter.Misc):
            found[prefix + key] = _widget(obj)
        elif isinstance(obj, int):
            found[prefix + key] = "<menu entry>"
        else:  # an include's scope
            found.update(_scope(obj, f"{prefix}{key}/"))
    return found


def describe(ui: Any, backend: str = "ttkbootstrap") -> dict[str, Any]:  # noqa: ANN401 - a LoadedUi
    """Windows (title, minimum size, state, menu bar), every widget by id, and the theme.

    ``backend`` only chooses where the theme is read: ttkbootstrap's ``Style`` (the default, also
    for generated modules) or the ``ttk.Style`` of a plain ``tkinter`` interface. A ``pyside6``
    interface has no Tk view: it gets the portable one.
    """
    if backend == "pyside6":
        return portable_describe(ui, backend)
    windows: dict[str, Any] = {}
    for key, top in ui.windows.items():
        bar = top.cget("menu")
        windows[key] = {
            "class": top.winfo_class(),
            "title": top.title(),
            "minsize": list(top.minsize()),
            "state": str(top.state()),
            "menubar": _menu(top.nametowidget(bar)) if bar else None,
        }
    if backend == "tkinter":
        from tkinter import ttk

        theme = str(ttk.Style(next(iter(ui.windows.values()))).theme_use())
    else:
        import ttkbootstrap

        style: Any = ttkbootstrap.Style
        theme = str(style.get_instance().theme_use())
    return {"theme": theme, "windows": windows, "widgets": _scope(ui)}


# ------------------------------------------------------------------ portable view (Tk reader)
_CORE = {
    "TFrame": "Frame",
    "TLabelframe": "LabelFrame",
    "TNotebook": "Notebook",
    "TPanedwindow": "PanedWindow",
    "TLabel": "Label",
    "TButton": "Button",
    "TEntry": "Entry",
    "TCheckbutton": "Checkbutton",
    "TRadiobutton": "Radiobutton",
    "TCombobox": "Combobox",
    "TSpinbox": "Spinbox",
    "TScale": "Scale",
    "TProgressbar": "Progressbar",
    "TSeparator": "Separator",
    "TScrollbar": "Scrollbar",
}  # the rest (Text, Listbox, Treeview, Canvas) keep their Tk class name
_NO_TEXT = {"Entry", "Combobox", "Spinbox"}  # their ``text`` is Tk's abbreviated textvariable
#: Qt key names (``QKeySequence`` PortableText) -> chord key names.
_QT_KEYS = {
    **{"Esc": "Escape", "Del": "Delete", "Ins": "Insert", "PgUp": "PageUp", "PgDown": "PageDown"},
    **{"+": "Plus", "-": "Minus", ",": "Comma", ".": "Period", "/": "Slash"},
}


def portable_shortcut(text: str) -> str:
    """A Tk accelerator or a Qt ``PortableText`` sequence in the ``.ui`` chord form.

    ``Return`` and ``Enter`` are one key (``Chord.identity``); anything else stays verbatim.
    """
    cut = len(text) - 1 if text.endswith("+") else text.rfind("+") + 1  # ``Ctrl++``
    key = text[cut:]
    chord = parse_chord(text[:cut] + _QT_KEYS.get(key, key))
    return text if chord is None else format_chord(Chord(*chord.identity))


def min_size(width: int, height: int) -> list[int]:
    """A window's minimum size; Tk reports an unset one as 1, Qt as 0 (both mean none)."""
    return [value if value > 1 else 0 for value in (width, height)]


def pack_fill(fill_x: bool, fill_y: bool, vertical: bool, expand: bool) -> str:
    """``fill`` as seen: along the packing axis a child that does not expand fills nothing."""
    if not expand:
        fill_x, fill_y = fill_x and vertical, fill_y and not vertical
    return "both" if fill_x and fill_y else "x" if fill_x else "y" if fill_y else "none"


def _flat(scope: Any, prefix: str = "") -> dict[str, Any]:  # noqa: ANN401 - a UiScope
    """Every object of ``scope`` and of its include scopes by (prefixed) id."""
    found: dict[str, Any] = {}
    for key, obj in scope.widgets.items():
        if hasattr(obj, "winfo_class") or isinstance(obj, int):
            found[prefix + key] = obj
        else:
            found.update(_flat(obj, f"{prefix}{key}/"))
    return found


def _mnemonic(value: Any) -> int | None:  # noqa: ANN401 - a Tcl value
    return int(value) if value is not None and int(value) >= 0 else None


def _portable_menu(menu: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - a tkinter.Menu
    last = menu.index("end")
    items: list[dict[str, Any]] = []
    for index in range(0 if last is None else last + 1):
        kind = str(menu.type(index))
        if kind == "separator":
            items.append({"separator": True})
            continue
        item: dict[str, Any] = {
            "text": str(menu.entrycget(index, "label")),
            "mnemonic": _mnemonic(menu.entrycget(index, "underline")),
            "shortcut": portable_shortcut(str(menu.entrycget(index, "accelerator"))),
            "enabled": str(menu.entrycget(index, "state")) != "disabled",
            "image": bool(menu.entrycget(index, "image")),
        }
        if kind == "cascade":
            item["items"] = _portable_menu(menu.nametowidget(str(menu.entrycget(index, "menu"))))
        items.append(item)
    return items


def _placement(outer: Any) -> dict[str, Any]:  # noqa: ANN401 - a Tk widget
    parent = outer.master
    kind = str(parent.winfo_class())
    if kind == "TNotebook":
        tab = str(outer)
        return {
            "page": parent.index(tab),
            "text": str(parent.tab(tab, "text")),
            "mnemonic": _mnemonic(parent.tab(tab, "underline")),
            "image": bool(parent.tab(tab, "image")),
        }
    if kind == "TPanedwindow":
        return {"page": [str(p) for p in parent.panes()].index(str(outer))}
    if outer.winfo_manager() == "grid":
        info = outer.grid_info()
        return {
            "cell": [int(info["row"]), int(info["column"])],
            "span": [int(info["rowspan"]), int(info["columnspan"])],
            "sticky": "".join(sorted(str(info["sticky"]))),
        }
    info = outer.pack_info()
    index = [str(w) for w in parent.pack_slaves()].index(str(outer))
    fill, expand = str(info["fill"]), bool(int(info["expand"]))
    vertical = str(info["side"]) in ("top", "bottom")
    return {
        "pack": index,
        "fill": pack_fill(fill in ("x", "both"), fill in ("y", "both"), vertical, expand),
        "expand": expand,
    }


def _parent_id(widget: Any, ids: dict[str, str]) -> str | None:  # noqa: ANN401 - a Tk widget
    parent = widget.master
    while parent is not None and str(parent) not in ids:
        parent = parent.master
    return ids.get(str(parent)) if parent is not None else None


def portable_describe(ui: Any, backend: str = "ttkbootstrap") -> dict[str, Any]:  # noqa: ANN401
    """A toolkit-neutral view of a built interface, read from the toolkit objects (spec 7).

    Per window: kind, title, minimum size, menu tree and status text (its id reads
    ``"<status bar>"``). Per id: core class, text and mnemonic, ``.ui`` state, image flag, parent
    id, placement (grid cell and spans with sticky, pack index with fill and expand, or page) and
    the value of the bound variable. Shortcuts, minimum sizes and pack fills are normalised so the
    Tk reader (both Tk backends) and the Qt reader (``_describe_qt``) compare equal. It leaves out
    what is toolkit specific on purpose: the look, the theme, paddings and bindings. With a
    ``master``, Tk builds the main window as a Toplevel, which reads as a dialog here.
    """
    if backend == "pyside6":
        from pyguibud.preview._describe_qt import qt_portable_describe

        return qt_portable_describe(ui)
    if backend not in {"ttkbootstrap", "tkinter"}:
        raise ValueError(f"no portable reader for {backend!r}")
    import tkinter

    windows: dict[str, Any] = {}
    for key, top in ui.windows.items():
        bar = top.cget("menu")
        windows[key] = {
            "kind": "main" if isinstance(top, tkinter.Tk) else "dialog",
            "title": top.title(),
            "minsize": min_size(*top.minsize()),
            "menubar": _portable_menu(top.nametowidget(bar)) if bar else None,
            "status": None,
        }
    found = _flat(ui)
    ids = {str(w): k for k, w in found.items() if hasattr(w, "winfo_class")}
    typed = _typed(ui)
    widgets: dict[str, Any] = {}
    for key, widget in found.items():
        if isinstance(widget, int):
            widgets[key] = "<menu entry>"
        elif key in windows:
            continue
        elif widget.winfo_class() == "Menu":
            widgets[key] = {"class": "Menu", "items": _portable_menu(widget)}
        elif (top := _status_top(widget)) is not None:  # the label of a window's status bar
            windows[ids[str(top)]]["status"] = str(widget.cget("text"))
            widgets[key] = "<status bar>"
        else:
            widgets[key] = _portable_widget(widget, ids, typed)
    return {"windows": windows, "widgets": widgets}


def _typed(scope: Any) -> dict[str, Any]:  # noqa: ANN401 - a UiScope
    """The declared variables of ``scope`` and its include scopes, by Tcl name."""
    found = {str(var): var for var in vars(scope.vars).values()}
    for obj in scope.widgets.values():
        if hasattr(obj, "vars") and hasattr(obj, "widgets"):  # an include's scope
            found.update(_typed(obj))
    return found


def _status_top(widget: Any) -> Any:  # noqa: ANN401 - Tk widgets
    """The window whose status bar ``widget`` is (``_tk`` grids its frame in row 2), or None."""
    frame = widget.master
    top = getattr(frame, "master", None)
    if (
        top is None
        or frame.winfo_manager() != "grid"
        or top.winfo_class() not in ("Tk", "Toplevel")
    ):
        return None
    return top if int(frame.grid_info()["row"]) == 2 else None


def _portable_widget(widget: Any, ids: dict[str, str], typed: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    scrolled = type(widget).__name__ == "ScrolledFrame"
    outer = widget.container if scrolled else (_tb_outer(widget) or widget)
    tk_class = str(widget.winfo_class())
    core = _TB_OUTER.get(type(widget).__name__) or _CORE.get(tk_class, tk_class)
    info: dict[str, Any] = {
        "class": "ScrolledFrame" if scrolled else core,
        "parent": _parent_id(outer, ids),
        "place": _placement(outer),
        "image": bool(_option(widget.cget, "image")),
    }
    for option in ("state",) if info["class"] in _NO_TEXT else ("text", "state"):
        if (value := _option(widget.cget, option)) is not None:
            info[option] = value
    if (mnemonic := _mnemonic(_option(widget.cget, "underline"))) is not None:
        info["mnemonic"] = mnemonic
    for option in ("textvariable", "variable"):
        name = str(widget.cget(option)) if _option(widget.cget, option) is not None else ""
        var = typed.get(name)  # declared variables only, not ttk's own auto variables
        if var is not None:
            info["value"] = var.get()
            if option == "textvariable":
                info.pop("text", None)  # the text option then only names the variable
    return info
