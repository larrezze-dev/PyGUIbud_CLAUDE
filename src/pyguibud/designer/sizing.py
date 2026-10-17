"""Widget and window sizes by direct manipulation (pure; spec direct-manipulation 2-4).

Which size property each handle drags, in which unit (px, characters, lines, rows), how a
pointer delta becomes a value, and the commands a drag, a double-click or a key step runs.
The canvas measures (font metrics, pixels); everything here is arithmetic on those numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Literal

from pyguibud.core.commands import Command, Macro, RemoveProp, SetField, SetProp
from pyguibud.core.model import GridCell, PackPlacement, PagePlacement, Prop, Widget, WidgetSpec
from pyguibud.core.model import Window as _Window
from pyguibud.designer.editing import Edge
from pyguibud.i18n import N_, _, ngettext

__all__ = [
    "EDGES", "MAX_SIZE", "SIZE_AXES", "Axis", "HandleKind", "Measured", "Start", "drag_size",
    "drag_value", "grid_child", "handle_kinds", "hover_text", "release_text",
    "reset_size_command", "size_axes", "size_command", "sized_axes", "start_value",
    "step_command", "unit_text", "window_release_text", "window_size_command", "window_value",
]  # fmt: skip

Unit = Literal["px", "chars", "lines", "rows"]
#: A size axis: (property name, unit).
Axis = tuple[str, Unit]
#: A filled handle changes a size property; a hollow one the grid cells a widget spans.
HandleKind = Literal["size", "span"]
MAX_SIZE = 10_000  # the registry's maximum and the validator's MAX_PIXELS
PIXEL_SNAP = 4  # px: a pixel size snaps to this (Shift: 1 px)
WINDOW_STEP = 8  # px: one key step of a window's minimum size
#: The 8 handles, in the overlay's pool order.
EDGES: tuple[Edge, ...] = ("nw", "n", "ne", "e", "se", "s", "sw", "w")
WINDOW_FIELDS = ("min_width", "min_height")

_PX: tuple[Axis | None, Axis | None] = (("width", "px"), ("height", "px"))
_CHARS: tuple[Axis | None, Axis | None] = (("width", "chars"), None)
_ROWS: tuple[Axis | None, Axis | None] = (None, ("height", "rows"))
#: (horizontal, vertical) size axes of the core classes (D8 a); Scale and Progressbar follow
#: their ``orient``; every other class (and every extension) has none.
SIZE_AXES: Mapping[str, tuple[Axis | None, Axis | None]] = {
    "Frame": _PX,
    "LabelFrame": _PX,
    "Notebook": _PX,
    "Canvas": _PX,
    "ScrolledFrame": (None, ("height", "px")),
    "Label": _CHARS,
    "Button": _CHARS,
    "Entry": _CHARS,
    "Combobox": _CHARS,
    "Spinbox": _CHARS,
    "Text": (("width", "chars"), ("height", "lines")),
    "Listbox": _ROWS,
    "Treeview": _ROWS,
}
_ORIENTED = frozenset({"Scale", "Progressbar"})
#: Tk geometry propagation: with managed children these ignore their width/height (D2 a).
_PROPAGATING = frozenset({"Frame", "LabelFrame"})

_M_RESIZE = N_("Resize")
_M_RESIZE_WINDOW = N_("Resize window")
_M_RESET = (N_("Reset width"), N_("Reset height"))
# Translators: hover text of a size handle of a grid element ("Ctrl" is the key).
_M_HOVER_GRID = (
    N_("Drag to change the width. Hold Ctrl to change the cells it spans."),
    N_("Drag to change the height. Hold Ctrl to change the cells it spans."),
    N_("Drag to change the size. Hold Ctrl to change the cells it spans."),
)
_M_HOVER = (
    N_("Drag to change the width."),
    N_("Drag to change the height."),
    N_("Drag to change the size."),
)
_M_HOVER_SPAN = N_("Drag to change the cells it spans.")
# Translators: {id} is an element; "Sticky" is the name of the property in the inspector.
_M_STICKY = (
    N_("'{id}' fills its cell horizontally (Sticky): drag to change the cells it spans."),
    N_("'{id}' fills its cell vertically (Sticky): drag to change the cells it spans."),
)
# Translators: {id} is an element; "Fill" is the name of the property in the inspector.
_M_FILL = (
    N_("'{id}' fills its space (Fill), so its width follows the container."),
    N_("'{id}' fills its space (Fill), so its height follows the container."),
)
_M_CONTENTS = N_(
    "A frame with contents takes the size of its contents. Use the column and row weights,"
    " Sticky or Fill to make it larger."
)
# Translators: {id} is an element without a width (or height) property, e.g. a Check button.
_M_NO_SIZE = (
    N_("'{id}' has no width that can be changed."),
    N_("'{id}' has no height that can be changed."),
)
_M_MIN = (N_("'{id}' cannot be narrower."), N_("'{id}' cannot be shorter."))
# Translators: {id} is an element; {value} a size such as "14 characters".
_M_RELEASE = (
    N_("Release to set the width of '{id}' to {value}."),
    N_("Release to set the height of '{id}' to {value}."),
)
# Translators: {width} and {height} are sizes such as "14 characters" or "3 lines".
_M_RELEASE_BOTH = N_("Release to set the size of '{id}' to {width} × {height}.")  # noqa: RUF001
# Translators: off the canvas tab; {value} is a size such as "14 characters" (or width and
# height), what a release back on the canvas would set (QA-14b1-01).
_M_OUTSIDE = N_("Release here to cancel. On the canvas, '{id}' would be set to {value}.")
# Translators: {id} is an element whose canvas drawing failed, so nothing could be measured.
_M_UNMEASURED = N_("'{id}' could not be measured on the canvas; set its size in the inspector.")
# Translators: {id} is a window; {width} and {height} are numbers of pixels.
_M_RELEASE_WINDOW = N_(
    "Release to set the minimum size of '{id}' to {width} × {height} px."  # noqa: RUF001
)
# Translators: {id} is a window dragged smaller than what it contains.
_M_CLEARED = (
    N_("'{id}' is as small as its contents allow; the minimum width was cleared."),
    N_("'{id}' is as small as its contents allow; the minimum height was cleared."),
    N_("'{id}' is as small as its contents allow; the minimum size was cleared."),
)
M_NATURAL = N_("'{id}' keeps its natural size.")
M_RESIZED = N_("Resized '{id}'.")
M_COMPONENT = N_(
    "A component takes its size from the window that includes it; this size is for the canvas only."
)


@dataclass(frozen=True, slots=True)
class Start:
    """Where a size drag or key step starts: the set value, or an estimate of the natural one."""

    value: int
    set: bool


@dataclass(frozen=True, slots=True)
class Measured:
    """What the canvas measured of a node: its shown size and the pixels of one unit per axis.

    For a window, ``size`` is the shown body (stage column 0, row 2) and ``natural`` its
    contents' natural size (spec 3).
    """

    size: tuple[int, int]
    pitch: tuple[float, float] = (1.0, 1.0)
    natural: tuple[int, int] = (0, 0)


def unit_text(value: int, unit: Unit) -> str:
    """``value`` with its unit, e.g. "14 characters" (one plural form per unit, spec 9)."""
    # Translators: {count} is a size in characters.
    if unit == "chars":
        text = ngettext("{count} character", "{count} characters", value)
    elif unit == "lines":
        # Translators: {count} is a size in text lines.
        text = ngettext("{count} line", "{count} lines", value)
    elif unit == "rows":
        # Translators: {count} is a size in list rows.
        text = ngettext("{count} row", "{count} rows", value)
    else:
        # Translators: {count} is a size in screen pixels.
        text = ngettext("{count} pixel", "{count} pixels", value)
    return text.format(count=value)


def size_axes(node: object, spec: WidgetSpec | None) -> tuple[Axis | None, Axis | None]:
    """(horizontal, vertical) size axes of ``node`` that its registry spec really declares."""
    if not isinstance(node, Widget) or spec is None or spec.is_extension:
        return None, None
    if node.class_name in _ORIENTED:
        prop, definition = node.props.get("orient"), spec.property("orient")
        orient = prop.value if prop else (definition.default if definition else None)
        length: Axis = ("length", "px")
        axes: tuple[Axis | None, Axis | None] = (
            (None, length) if orient == "vertical" else (length, None)
        )
    else:
        axes = SIZE_AXES.get(node.class_name, (None, None))
    h, v = (a if a is not None and spec.property(a[0]) is not None else None for a in axes)
    return h, v


def grid_child(node: object) -> bool:
    """A grid child of a grid container: its handles can change the cells it spans."""
    parent = getattr(node, "parent", None)
    layout = getattr(parent, "layout", None)
    placement = getattr(node, "placement", None)
    return isinstance(placement, GridCell) and layout is not None and layout.type == "grid"


def sized_axes(
    node: object, spec: WidgetSpec | None
) -> tuple[tuple[Axis | None, str], tuple[Axis | None, str]]:
    """Per axis: the size axis a handle drags, or None and why it is hidden ('' = no reason).

    Hidden (spec 2.4-2.5): page children, a frame with contents, grid sticky on both sides
    (the cells size the widget) and pack fill along the axis.
    """
    found: list[tuple[Axis | None, str]] = []
    placement, ident = getattr(node, "placement", None), str(getattr(node, "id", ""))
    for k, axis in enumerate(size_axes(node, spec)):
        reason = ""
        if axis is None or isinstance(placement, PagePlacement):
            axis = None
        elif isinstance(node, Widget) and node.class_name in _PROPAGATING and node.children:
            axis, reason = None, _(_M_CONTENTS)
        elif grid_child(node) and isinstance(placement, GridCell):
            if set("ew" if k == 0 else "ns") <= set(placement.sticky.lower()):
                axis, reason = None, _(_M_STICKY[k]).format(id=ident)
        elif isinstance(placement, PackPlacement) and placement.fill in ("both", "xy"[k]):
            axis, reason = None, _(_M_FILL[k]).format(id=ident)
        found.append((axis, reason))
    return found[0], found[1]


def _axes_of(edge: str) -> tuple[bool, bool]:
    return any(c in "ew" for c in edge), any(c in "ns" for c in edge)


def handle_kinds(node: object, spec: WidgetSpec | None) -> dict[Edge, HandleKind]:
    """The handles of the primary ``node`` (D1 a): size where every axis of a handle has a size
    property, else span for a grid child; a page child and a node with neither get none."""
    if isinstance(getattr(node, "placement", None), PagePlacement):
        return {}
    (h, _hr), (v, _vr) = sized_axes(node, spec)
    grid, kinds = grid_child(node), dict[Edge, HandleKind]()
    for edge in EDGES:
        across, along = _axes_of(edge)
        if (not across or h is not None) and (not along or v is not None):
            kinds[edge] = "size"
        elif grid:
            kinds[edge] = "span"
    return kinds


def hover_text(node: object, spec: WidgetSpec | None, edge: Edge, kind: HandleKind) -> str:
    """The status text of a hovered handle (spec 2.2, 2.4, 2.5)."""
    across, along = _axes_of(edge)
    if kind == "size":
        which = 2 if across and along else (0 if across else 1)
        return _((_M_HOVER_GRID if grid_child(node) else _M_HOVER)[which])
    (_h, h_reason), (_v, v_reason) = sized_axes(node, spec)
    return (h_reason if across else "") or (v_reason if along else "") or _(_M_HOVER_SPAN)


def drag_size(start: int, delta: float, pitch: float, *, snap: int = 0) -> int:
    """The size after dragging ``delta`` px: whole units (``snap`` 0), else pixels snapped to
    multiples of ``snap``; rounded half away from the press and clamped (never 0)."""

    def half_away(x: float) -> int:
        return int(abs(x) + 0.5) * (1 if x >= 0 else -1)

    if snap > 0:
        value = half_away((start + delta) / snap) * snap
    else:
        value = start + half_away(delta / (pitch if pitch > 0 else 1.0))
    return max(1, min(MAX_SIZE, value))


def start_value(node: object, prop: str, shown_px: int, pitch: float) -> Start:
    """The set value of ``prop``, or the natural size estimated from the shown pixels (2.3)."""
    props = getattr(node, "props", {})
    current = props.get(prop)
    if current is not None and current.ref is None:
        try:
            return Start(int(current.value), True)
        except ValueError:  # not a number (the validator reports it): estimate instead
            pass
    return Start(max(1, round(shown_px / (pitch if pitch > 0 else 1.0))), False)


def drag_value(start: Start, delta: float, pitch: float, unit: Unit, *, fine: bool) -> int | None:
    """What a drag writes, or None: an unset size dragged back past the press keeps its
    natural size (spec 2.3)."""
    snap = (1 if fine else PIXEL_SNAP) if unit == "px" else 0
    if not start.set and delta <= (snap or pitch) / 2:  # QA-14b1-04: also a 1 px wobble
        return None
    if abs(delta) < (snap or pitch) / 2:  # back at the press: never a snapped "change"
        return start.value
    return drag_size(start.value, delta, pitch, snap=snap)


def _prop(node: Widget, name: str, value: int) -> Prop:
    current = node.props.get(name)
    if current is None:
        return Prop(name=name, value=str(value))
    return replace(current, value=str(value), ref=None)


def size_command(node: object, values: Sequence[tuple[str, int]]) -> Command | None:
    """One ``Resize`` step setting the changed size properties; None when nothing changes."""
    if not isinstance(node, Widget):
        return None
    commands: list[Command] = [
        SetProp(node, _prop(node, name, value))
        for name, value in values
        if node.props.get(name) != _prop(node, name, value)
    ]
    return Macro(_M_RESIZE, commands) if commands else None


def reset_size_command(node: object, spec: WidgetSpec | None, edge: Edge) -> Command | None:
    """Double-click on a size handle: back to the natural size on its axes (``Reset width``)."""
    if not isinstance(node, Widget):
        return None
    axes = [a for a, on in zip(size_axes(node, spec), _axes_of(edge), strict=True) if on and a]
    names = [a[0] for a in axes if a[0] in node.props]
    if not names:
        return None
    label = _M_RESIZE if len(names) > 1 else _M_RESET[0 if names[0] != "height" else 1]
    return Macro(label, [RemoveProp(node, name) for name in names])


def window_value(extent: int, natural: int, *, fine: bool) -> int | None:
    """A window minimum from the pointer extent; at or below the contents it is cleared (D5).

    Above the contents the extent snaps to the grid, but never back to or below them: a
    minimum there would not show (and 0 is no size), so it takes the next grid step instead.
    """
    if extent <= natural:
        return None
    step = 1 if fine else PIXEL_SNAP
    value = round(extent / step) * step
    if value <= natural:
        value = (natural // step + 1) * step
    return min(MAX_SIZE, value)


def window_size_command(window: object, values: Mapping[str, int | None]) -> Command | None:
    """One ``Resize window`` step with the changed ``min_width``/``min_height`` only."""
    if not isinstance(window, _Window):
        return None
    commands: list[Command] = [
        SetField(window, name, value)
        for name, value in values.items()
        if name in WINDOW_FIELDS and getattr(window, name) != value
    ]
    return Macro(_M_RESIZE_WINDOW, commands) if commands else None


def release_text(
    ident: str, values: Sequence[tuple[Unit, int] | None], *, outside: bool = False
) -> str:
    """The status text while a size drag runs (spec 7); ``outside`` the canvas tab a release
    cancels (2.7), so the value is shown without promising it."""
    sizes = [unit_text(a[1], a[0]) for a in values if a is not None]
    if not sizes:
        return _(M_NATURAL).format(id=ident)
    if outside:
        return _(_M_OUTSIDE).format(id=ident, value=" × ".join(sizes))  # noqa: RUF001
    if len(sizes) == 2:
        return _(_M_RELEASE_BOTH).format(id=ident, width=sizes[0], height=sizes[1])
    return _(_M_RELEASE[0 if values[0] is not None else 1]).format(id=ident, value=sizes[0])


def window_release_text(
    ident: str, values: tuple[int | None, int | None], shown: tuple[bool, bool]
) -> str:
    """The status text while a window drag runs: the new minimum, or which one is cleared.

    ``shown`` says which axes the handle drags: (width, height).
    """
    width, height = values
    cleared = [k for k, on in enumerate(shown) if on and values[k] is None]
    if cleared:
        return _(_M_CLEARED[2 if len(cleared) == 2 else cleared[0]]).format(id=ident)
    return _(_M_RELEASE_WINDOW).format(id=ident, width=width or "-", height=height or "-")


def step_command(
    node: object, spec: WidgetSpec | None, k: int, step: int, measured: Measured | None
) -> Command | str:
    """A Ctrl+Shift+Arrow size step: a bare (mergeable) ``SetProp``/``SetField``, or why not."""
    ident = str(getattr(node, "id", ""))  # k: 0 = width, 1 = height
    if isinstance(node, _Window):
        name, current = WINDOW_FIELDS[k], getattr(node, WINDOW_FIELDS[k])
        if current is None and measured is None:  # QA-14b1-02: never guess from 0 px
            return _(_M_UNMEASURED).format(id=ident)
        shown = max(measured.size[k], measured.natural[k]) if measured else 0
        floor = measured.natural[k] if measured else 0  # QA-14b1-08: a lower minimum is not shown
        start = current if current is not None and current > floor else shown
        value = min(MAX_SIZE, start + step * WINDOW_STEP)
        if value <= floor:
            if current is None:
                return _(_M_MIN[k]).format(id=ident)
            return SetField(node, name, None)
        return SetField(node, name, value)
    axis, reason = sized_axes(node, spec)[k]
    if axis is None or not isinstance(node, Widget):
        return reason or _(_M_NO_SIZE[k]).format(id=ident)
    prop, unit = axis
    pitch = 1.0 if unit == "px" else (measured.pitch[k] if measured else 1.0)
    start = start_value(node, prop, measured.size[k] if measured else 0, pitch)
    if measured is None and not start.set:  # QA-14b1-02: an estimate from 0 px would shrink it
        return _(_M_UNMEASURED).format(id=ident)
    value = start.value + step * (PIXEL_SNAP if unit == "px" else 1)
    if value < 1:
        return _(_M_MIN[k]).format(id=ident)
    return SetProp(node, _prop(node, prop, min(MAX_SIZE, value)))
