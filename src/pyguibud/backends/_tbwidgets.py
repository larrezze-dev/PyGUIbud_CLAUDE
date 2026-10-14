"""The ttkbootstrap factories of the five built-in ``tb:`` widgets (spec plugins 4.1, 5).

Referenced as ``"pyguibud.backends._tbwidgets:<name>"`` by ``core.widgets.tb_widgets()``.
``ttkbootstrap`` is imported only inside the functions, so the registry and the other backends
can name this module without loading a toolkit. Each factory follows the Tk contract
``factory(parent, props, variable, bootstyle) -> widget | (outer, inner)``.
"""

from __future__ import annotations

from typing import Any

from pyguibud.backends._tkmap import TB_EXT, iso_date, toggle_style
from pyguibud.i18n import _

__all__ = ["date_entry", "floodgauge", "meter", "tableview", "toggle_button"]


def link(own: Any, bound: Any) -> None:  # noqa: ANN401 - Tk variables
    """Keep a widget's own variable and the bound one equal; the bound value wins at first."""
    busy = [False]

    def copy(source: Any, target: Any) -> Any:  # noqa: ANN401 - Tk variables and callback
        def callback(*_args: object) -> None:
            if not busy[0]:
                busy[0] = True
                try:
                    target.set(source.get())
                finally:
                    busy[0] = False

        return callback

    own.set(bound.get())
    bound.trace_add("write", copy(bound, own))
    own.trace_add("write", copy(own, bound))


def _make(
    name: str,
    parent: Any,  # noqa: ANN401 - a Tk widget
    props: dict[str, Any],
    variable: Any,  # noqa: ANN401 - a Tk variable or None
    bootstyle: str | None,
    **extra: Any,  # noqa: ANN401 - constructor keywords
) -> Any:  # noqa: ANN401 - the widget or (outer, inner)
    import ttkbootstrap

    ext = TB_EXT[name]
    options = {ext.options[key]: value for key, value in props.items() if key in ext.options}
    options.update(extra)
    if bootstyle:
        options["bootstyle"] = bootstyle
    if variable is not None and ext.link == "option" and ext.variable:
        options[ext.variable] = variable
    outer = getattr(ttkbootstrap, ext.cls)(parent, **options)
    inner = getattr(outer, ext.inner) if ext.inner else outer
    for key in ext.after:
        if key in props:
            inner.configure(**{key: props[key]})
    if variable is not None and ext.link == "inner":
        inner.configure(**{str(ext.variable): variable})
    elif variable is not None and ext.link == "link":
        link(getattr(outer, str(ext.variable)), variable)
    return outer if inner is outer else (outer, inner)


def meter(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:  # noqa: ANN401
    """``tb:Meter``: the bound variable follows the meter's amount used."""
    return _make("tb:Meter", parent, props, variable, bootstyle)


def floodgauge(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:  # noqa: ANN401
    """``tb:Floodgauge`` (the Canvas-based 2.2 widget)."""
    return _make("tb:Floodgauge", parent, props, variable, bootstyle)


def date_entry(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:  # noqa: ANN401
    """``tb:DateEntry``: an ISO value; a calendar-invalid date is logged and left out."""
    date = iso_date(props.pop("value")) if "value" in props else None
    if date is not None:
        props["value"] = date
    made = _make("tb:DateEntry", parent, props, variable, bootstyle, popup_title=_("Select a date"))
    if "state" in props:  # the date entry passes it to its button as well
        made[0].configure(state=props["state"])
    return made


def tableview(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:  # noqa: ANN401
    """``tb:Tableview``: headings only; rows come from handler code."""
    props["columns"] = props["columns"].split(";") if props.get("columns") else []
    made = _make("tb:Tableview", parent, props, variable, bootstyle, rowdata=[])
    # QA-17b-04: ttkbootstrap 2.2 never removes this trace; tkinter destroys children by destroy()
    table, size = made[0], made[0]._pagesize
    close, names = table.destroy, [name for modes, name in size.trace_info() if "write" in modes]

    def destroy() -> None:
        while names:  # once: a second trace_remove would delete a missing command
            size.trace_remove("write", names.pop())
        close()

    table.destroy = destroy
    return made


def toggle_button(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:  # noqa: ANN401
    """``tb:ToggleButton``: a Checkbutton with a round or square toggle style."""
    style = toggle_style(bootstyle, props.get("shape", "round"))
    return _make("tb:ToggleButton", parent, props, variable, style)
