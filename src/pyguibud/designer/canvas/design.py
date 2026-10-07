"""Design mode (spec dnd-selection 2.4): canvas widgets never react to input.

Every widget of a rendered window gets the bindtags :data:`DESIGN_BINDTAGS`. That drops the class
tag (pressing, typing, toggling, Combobox popdowns, sash drags), the instance tag (anything
``_tk.py`` bound) and ``all`` (the designer's own ``bind_all`` shortcuts; canvas widgets never
have the focus anyway). The handlers of :data:`DESIGN_TAG` are bound once per application and
return ``"break"``.

Exception (spec risk R3, checked in ttkbootstrap 2.2.3 ``widgets/scrolled.py``): a ScrolledFrame
sizes itself through instance ``<Configure>`` bindings on its content frame and on its internal
canvas. A widget whose own bindings are geometry-only keeps its instance tag after the design
tag; :data:`DESIGN_TAG` binds no geometry event, so those events reach it and nothing else does.
"""

from __future__ import annotations

import tkinter
from collections.abc import Callable, Iterator
from typing import Any

__all__ = [
    "DESIGN_BINDTAGS",
    "DESIGN_TAG",
    "SEQUENCES",
    "apply_design_mode",
    "descendants",
    "install",
    "uninstall",
]

DESIGN_TAG = "PyguibudDesign"
DESIGN_BINDTAGS = (DESIGN_TAG,)
#: Every sequence DESIGN_TAG handles; the handler of each one returns "break".
SEQUENCES = (
    "<ButtonPress-1>",
    "<B1-Motion>",
    "<ButtonRelease-1>",
    "<Double-Button-1>",
    "<ButtonPress-3>",
    "<Motion>",
    "<MouseWheel>",
    "<Button-4>",
    "<Button-5>",
    "<KeyPress>",
)
#: Instance bindings that only keep a widget's geometry right (never user behaviour).
_GEOMETRY = frozenset({"<Configure>", "<Map>", "<Unmap>"})

Handler = Callable[[Any], object]


def descendants(widget: Any) -> Iterator[Any]:  # noqa: ANN401 - a Tk widget
    """``widget`` and every widget below it (iterative: no recursion limit)."""
    stack = [widget]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.winfo_children())


def apply_design_mode(frame: Any) -> None:  # noqa: ANN401 - a Tk widget
    """Put ``frame`` and everything below it in design mode (bindtags, no keyboard focus)."""
    for widget in descendants(frame):
        own = set(widget.bind())
        keep = bool(own) and own <= _GEOMETRY
        widget.bindtags((*DESIGN_BINDTAGS, str(widget)) if keep else DESIGN_BINDTAGS)
        try:
            widget.configure(takefocus=0)
        except tkinter.TclError:  # the widget has no -takefocus option
            continue


def install(root: Any, handlers: dict[str, Handler]) -> None:  # noqa: ANN401 - a Tk root
    """Bind the design handlers on the class tag (replacing earlier ones); unknown -> "break"."""
    for sequence in SEQUENCES:
        handler = handlers.get(sequence)
        root.bind_class(DESIGN_TAG, sequence, _breaking(handler))


def uninstall(root: Any) -> None:  # noqa: ANN401 - a Tk root
    """Remove every design binding (the panel is disposed)."""
    for sequence in SEQUENCES:
        root.unbind_class(DESIGN_TAG, sequence)


def _breaking(handler: Handler | None) -> Callable[[Any], str]:
    def callback(event: Any) -> str:  # noqa: ANN401 - a Tk event
        if handler is not None:
            handler(event)
        return "break"

    return callback
