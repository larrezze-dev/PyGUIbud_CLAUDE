"""``describe(ui)``: a canonical, JSON-ready view of a built interface (spec preview-export 2).

The preview child prints it with ``--describe``; the parity tests describe a generated module the
same way, so "the preview matches the export" is a plain ``==``. ``tkinter`` is imported only
when describing (ADR-013: importing ``pyguibud.preview`` loads no toolkit).
"""

from __future__ import annotations

import re
from typing import Any

__all__ = ["describe"]

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


def describe(ui: Any) -> dict[str, Any]:  # noqa: ANN401 - a LoadedUi or a generated Ui_X
    """Windows (title, minimum size, state, menu bar), every widget by id, and the theme."""
    import ttkbootstrap

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
    style: Any = ttkbootstrap.Style
    return {"theme": style.get_instance().theme_use(), "windows": windows, "widgets": _scope(ui)}
