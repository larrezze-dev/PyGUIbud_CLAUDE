"""``describe(ui)``: a canonical, JSON-ready view of a built interface (spec preview-export 2).

The preview child prints it with ``--describe``; the parity tests describe a generated module the
same way, so "the preview matches the export" is a plain ``==``. ``tkinter`` is imported only
when describing (ADR-013: importing ``pyguibud.preview`` loads no toolkit).
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["describe", "portable_describe"]

_OPTIONS = (
    *("text", "underline", "compound", "state", "padding", "style", "orient", "from", "to"),
    *("wrap", "show", "value", "width", "height", "length", "maximum", "mode", "increment"),
    *("selectmode", "values", "justify", "anchor", "takefocus"),
)
_ENTRY_OPTIONS = ("label", "underline", "accelerator", "state", "compound")


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


def _widget(widget: Any) -> dict[str, Any]:  # noqa: ANN401 - a Tk widget
    import tkinter

    info: dict[str, Any] = {"class": widget.winfo_class(), "manager": widget.winfo_manager()}
    if info["manager"] in {"grid", "pack"}:
        placed = (widget.grid_info if info["manager"] == "grid" else widget.pack_info)()
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
    for generated modules) or the ``ttk.Style`` of a plain ``tkinter`` interface.
    """
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
            "shortcut": str(menu.entrycget(index, "accelerator")),
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
    return {"pack": index, "fill": str(info["fill"]), "expand": bool(int(info["expand"]))}


def _parent_id(widget: Any, ids: dict[str, str]) -> str | None:  # noqa: ANN401 - a Tk widget
    parent = widget.master
    while parent is not None and str(parent) not in ids:
        parent = parent.master
    return ids.get(str(parent)) if parent is not None else None


def portable_describe(ui: Any, backend: str = "ttkbootstrap") -> dict[str, Any]:  # noqa: ANN401
    """A toolkit-neutral view of a built interface, read from the toolkit objects (spec 7).

    Per window: kind, title, minimum size and menu tree. Per id: core class, text and mnemonic,
    ``.ui`` state, image flag, parent id, placement (grid cell and spans with sticky, pack index
    with fill and expand, or page) and the value of the bound variable. It leaves out what is
    toolkit specific on purpose: the look, the theme, paddings, bindings, and the status bar as
    a window attribute (it appears as a Label). The ttkbootstrap and plain tkinter interfaces
    share this Tk reader.
    """
    if backend not in {"ttkbootstrap", "tkinter"}:
        raise ValueError(f"no portable reader for {backend!r}")
    windows: dict[str, Any] = {}
    for key, top in ui.windows.items():
        bar = top.cget("menu")
        windows[key] = {
            "kind": "main" if top is getattr(ui, "main", None) else "dialog",
            "title": top.title(),
            "minsize": list(top.minsize()),
            "menubar": _portable_menu(top.nametowidget(bar)) if bar else None,
        }
    found = _flat(ui)
    ids = {str(w): k for k, w in found.items() if hasattr(w, "winfo_class")}
    typed = {str(v): v for v in vars(ui.vars).values()}
    widgets: dict[str, Any] = {}
    for key, widget in found.items():
        if isinstance(widget, int):
            widgets[key] = "<menu entry>"
        elif key in windows:
            continue
        elif widget.winfo_class() == "Menu":
            widgets[key] = {"class": "Menu", "items": _portable_menu(widget)}
        else:
            widgets[key] = _portable_widget(widget, ids, typed)
    return {"windows": windows, "widgets": widgets}


def _portable_widget(widget: Any, ids: dict[str, str], typed: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
    scrolled = type(widget).__name__ == "ScrolledFrame"
    outer = widget.container if scrolled else widget
    tk_class = str(widget.winfo_class())
    info: dict[str, Any] = {
        "class": "ScrolledFrame" if scrolled else _CORE.get(tk_class, tk_class),
        "parent": _parent_id(outer, ids),
        "place": _placement(outer),
        "image": bool(_option(widget.cget, "image")),
    }
    for option in ("text", "state"):
        if (value := _option(widget.cget, option)) is not None:
            info[option] = value
    if (mnemonic := _mnemonic(_option(widget.cget, "underline"))) is not None:
        info["mnemonic"] = mnemonic
    for option in ("textvariable", "variable"):
        if _option(widget.cget, option) and (name := str(widget.cget(option))):
            var = typed.get(name)
            info["value"] = var.get() if var is not None else widget.getvar(name)
            if option == "textvariable":
                info.pop("text", None)  # the text option then only names the variable
    return info
