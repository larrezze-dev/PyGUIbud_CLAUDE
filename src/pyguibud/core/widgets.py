"""The 24 built-in widget specifications (ADR-001), registered through the ``pyguibud.widgets``
entry point like any plugin (ADR-004 dogfooding).

Pure data: importing this module translates nothing. Display names and categories are msgids
marked with ``N_()`` and are translated only when read.
"""

from __future__ import annotations

from typing import Any, Literal

from pyguibud.core.model import WIDGET_API_VERSION, PropertyDef, PropertyType, WidgetSpec
from pyguibud.i18n import N_

__all__ = ["core_widgets", "tb_widgets"]

# ---------------------------------------------------------------- categories
_CONTAINERS = N_("Containers")
_CONTROLS = N_("Controls")
_DISPLAY = N_("Display")
_MENUS = N_("Menus")

# ---------------------------------------------------------------- shared properties
_TEXT = PropertyDef(name="text", type="string", translatable=True, display_name=N_("Text"))
_IMAGE = PropertyDef(name="image", type="image", display_name=N_("Image"))
_STATE = PropertyDef(
    name="state",
    type="enum",
    choices=("normal", "disabled"),
    default="normal",
    display_name=N_("State"),
)
_STATE3 = PropertyDef(
    name="state",
    type="enum",
    choices=("normal", "disabled", "readonly"),
    default="normal",
    display_name=N_("State"),
)
# Sizes (pixels, characters or lines) share the validator's MAX_PIXELS: Tk freezes on a geometry
# request of tens of millions of pixels, which an unbounded width or length could make.
_MAX_SIZE = 10_000
_WIDTH = PropertyDef(
    name="width", type="int", minimum=0, maximum=_MAX_SIZE, display_name=N_("Width")
)
_HEIGHT = PropertyDef(
    name="height", type="int", minimum=0, maximum=_MAX_SIZE, display_name=N_("Height")
)
_LENGTH = PropertyDef(
    name="length", type="int", minimum=0, maximum=_MAX_SIZE, display_name=N_("Length")
)
_MINIMUM = PropertyDef(name="minimum", type="float", default="0", display_name=N_("Minimum"))
_MAXIMUM = PropertyDef(name="maximum", type="float", default="100", display_name=N_("Maximum"))


def _orient(default: str) -> PropertyDef:
    return PropertyDef(
        name="orient",
        type="enum",
        choices=("horizontal", "vertical"),
        default=default,
        display_name=N_("Orientation"),
    )


_FOCUS = ("focus_in", "focus_out")


_CORE_WIDGETS: tuple[WidgetSpec, ...] = (
    # ------------------------------------------------------------ containers
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Frame",
        display_name=N_("Frame"),
        category=_CONTAINERS,
        children="layout",
        properties=(_WIDTH, _HEIGHT),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="LabelFrame",
        display_name=N_("Label frame"),
        category=_CONTAINERS,
        children="layout",
        properties=(_TEXT, _WIDTH, _HEIGHT),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Notebook",
        display_name=N_("Notebook"),
        category=_CONTAINERS,
        children="pages",
        properties=(_WIDTH, _HEIGHT),
        events=("select",),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="PanedWindow",
        display_name=N_("Paned window"),
        category=_CONTAINERS,
        children="pages",
        properties=(_orient("vertical"),),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="ScrolledFrame",
        display_name=N_("Scrolled frame"),
        category=_CONTAINERS,
        children="layout",
        properties=(
            _HEIGHT,
            PropertyDef(
                name="autohide",
                type="bool",
                default="true",
                display_name=N_("Hide scrollbars automatically"),
            ),
        ),
    ),
    # ------------------------------------------------------------ controls and display
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Label",
        display_name=N_("Label"),
        category=_DISPLAY,
        properties=(_TEXT, _IMAGE, _WIDTH),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Button",
        display_name=N_("Button"),
        category=_CONTROLS,
        properties=(_TEXT, _IMAGE, _STATE, _WIDTH),
        events=("command", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Entry",
        display_name=N_("Entry"),
        category=_CONTROLS,
        properties=(
            _WIDTH,
            _STATE3,
            PropertyDef(name="show", type="string", display_name=N_("Mask character")),
        ),
        events=("change", "activate", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Text",
        display_name=N_("Multi-line text"),
        category=_CONTROLS,
        properties=(
            _WIDTH,
            _HEIGHT,
            _STATE,
            PropertyDef(
                name="wrap",
                type="enum",
                choices=("none", "char", "word"),
                default="word",
                display_name=N_("Wrap"),
            ),
        ),
        events=("change", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Checkbutton",
        display_name=N_("Check button"),
        category=_CONTROLS,
        properties=(_TEXT, _STATE),
        events=("command", "change", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Radiobutton",
        display_name=N_("Radio button"),
        category=_CONTROLS,
        properties=(
            _TEXT,
            PropertyDef(name="value", type="string", display_name=N_("Value")),
            _STATE,
        ),
        events=("command", "change", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Combobox",
        display_name=N_("Combo box"),
        category=_CONTROLS,
        properties=(_WIDTH, _STATE3),
        events=("change", "select", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Spinbox",
        display_name=N_("Spin box"),
        category=_CONTROLS,
        properties=(
            _MINIMUM,
            _MAXIMUM,
            PropertyDef(name="increment", type="float", default="1", display_name=N_("Increment")),
            _WIDTH,
            _STATE3,
        ),
        events=("change", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Scale",
        display_name=N_("Scale"),
        category=_CONTROLS,
        properties=(_MINIMUM, _MAXIMUM, _orient("horizontal"), _LENGTH),
        events=("change",),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Progressbar",
        display_name=N_("Progress bar"),
        category=_DISPLAY,
        properties=(
            _MAXIMUM,
            PropertyDef(name="value", type="float", default="0", display_name=N_("Value")),
            PropertyDef(
                name="mode",
                type="enum",
                choices=("determinate", "indeterminate"),
                display_name=N_("Mode"),
            ),
            _orient("horizontal"),
            _LENGTH,
        ),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Separator",
        display_name=N_("Separator"),
        category=_DISPLAY,
        properties=(_orient("horizontal"),),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Listbox",
        display_name=N_("List box"),
        category=_CONTROLS,
        properties=(
            PropertyDef(
                name="height",
                type="int",
                minimum=0,
                maximum=_MAX_SIZE,
                default="10",
                display_name=N_("Height"),
            ),
            PropertyDef(
                name="selectmode",
                type="enum",
                choices=("browse", "single", "multiple", "extended"),
                display_name=N_("Selection mode"),
            ),
        ),
        events=("select", "activate", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Treeview",
        display_name=N_("Tree view"),
        category=_CONTROLS,
        properties=(
            _HEIGHT,
            PropertyDef(
                name="show",
                type="enum",
                choices=("tree", "headings", "tree headings"),
                display_name=N_("Show"),
            ),
            PropertyDef(
                name="selectmode",
                type="enum",
                choices=("browse", "extended", "none"),
                display_name=N_("Selection mode"),
            ),
        ),
        events=("select", "activate", *_FOCUS),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Scrollbar",
        display_name=N_("Scrollbar"),
        category=_CONTROLS,
        properties=(_orient("vertical"),),
        events=("change",),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Canvas",
        display_name=N_("Canvas"),
        category=_DISPLAY,
        properties=(
            _WIDTH,
            _HEIGHT,
            PropertyDef(name="background", type="colour", display_name=N_("Background colour")),
        ),
        events=_FOCUS,
    ),
    # ------------------------------------------------------------ menus and window chrome
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Menubar",
        display_name=N_("Menu bar"),
        category=_MENUS,
        children="menu",
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Menu",
        display_name=N_("Menu"),
        category=_MENUS,
        children="menu",
        properties=(_TEXT,),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Action",
        display_name=N_("Action"),
        category=_MENUS,
        properties=(
            _TEXT,
            _IMAGE,
            _STATE,
        ),
        events=("command",),
    ),
    WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name="Statusbar",
        display_name=N_("Status bar"),
        category=_MENUS,
        properties=(_TEXT,),
    ),
)


def core_widgets() -> tuple[WidgetSpec, ...]:
    """Return the built-in widget specifications (entry point ``pyguibud.widgets:core``)."""
    return _CORE_WIDGETS


# ---------------------------------------------------------------- ttkbootstrap extensions (tb:)
# Translators: the name of the ttkbootstrap library (a palette category); do not translate.
_TTKBOOTSTRAP = N_("ttkbootstrap")
_AMOUNT_RE = r"[^{}]*\{(:\.[0-6]f)?\}[^{}]*"
_AMOUNT_HINT = N_("use '{{}}' once, optionally as '{{:.2f}}' with 0 to 6 decimals")
# DateEntry refuses a format without day, month and year; a repeated code makes strptime raise
# re.error on focus-out. The lookaheads step over whole tokens, so '%%d' is no day.
_TOKENS = r"(?:[^%]|%.)*?"
_DATE_FORMAT_RE = (
    rf"(?={_TOKENS}%d)(?={_TOKENS}%[mbB])(?={_TOKENS}%[Yy])(?!{_TOKENS}(%[^%]){_TOKENS}\1)"
    r"(?:[^%{}\x00-\x1f]|%[dmyYbBaAj%])*"
)
_BIND_NUMBER: tuple[Literal["double", "int"], ...] = ("double", "int")


def _prop(name: str, kind: PropertyType, display_name: str, **kw: Any) -> PropertyDef:  # noqa: ANN401 - PropertyDef fields
    return PropertyDef(name=name, type=kind, display_name=display_name, **kw)


def _int(name: str, display_name: str, low: int, high: int, default: str) -> PropertyDef:
    return _prop(name, "int", display_name, minimum=low, maximum=high, default=default)


def _bool(name: str, display_name: str, default: str = "false") -> PropertyDef:
    return _prop(name, "bool", display_name, default=default)


def _shared(fallback: str, *names: str) -> tuple[PropertyDef, ...]:
    """Properties shared with the fallback keep its definitions (the fallback shows them too)."""
    spec = next(s for s in _CORE_WIDGETS if s.name == fallback)
    return tuple(d for name in names if (d := spec.property(name)) is not None)


def _tb(name: str, display_name: str, fallback: str, **kw: Any) -> WidgetSpec:  # noqa: ANN401 - WidgetSpec fields
    return WidgetSpec(
        api_version=WIDGET_API_VERSION,
        name=f"tb:{name}",
        display_name=display_name,
        category=_TTKBOOTSTRAP,
        fallback=fallback,
        **kw,
    )


_TB_WIDGETS: tuple[WidgetSpec, ...] = (
    _tb(
        "Meter",
        N_("Meter"),
        "Progressbar",
        bind_types=_BIND_NUMBER,
        properties=(
            *_shared("Progressbar", "value", "maximum"),
            _prop("subtext", "string", N_("Subtext"), translatable=True),
            _prop("meter_type", "enum", N_("Meter type"), choices=("full", "semi"), default="full"),
            _int("meter_size", N_("Meter size"), 50, 1000, "200"),
            _int("meter_thickness", N_("Meter thickness"), 1, 100, "10"),
            _prop(
                "amount_format",
                "string",
                N_("Amount format"),
                default="{}",
                pattern=_AMOUNT_RE,
                max_length=32,
                hint=_AMOUNT_HINT,
            ),
            _bool("show_text", N_("Show text"), "true"),
            _bool("interactive", N_("Interactive")),
        ),
    ),
    _tb(
        "Floodgauge",
        N_("Flood gauge"),
        "Progressbar",
        bind_types=_BIND_NUMBER,
        properties=(
            *_shared("Progressbar", "value", "maximum", "mode", "orient", "length"),
            _TEXT,
            _prop(
                "mask",
                "string",
                N_("Text mask"),
                pattern=_AMOUNT_RE,
                max_length=32,
                hint=_AMOUNT_HINT,
            ),
        ),
    ),
    _tb(
        "DateEntry",
        N_("Date entry"),
        "Entry",
        bind_types=("string",),
        events=("change", "activate", *_FOCUS),
        properties=(
            *_shared("Entry", "width", "state"),
            # ASCII classes, not \d: a non-ASCII digit would pass here and fail at build time.
            _prop(
                "value",
                "string",
                N_("Date"),
                pattern="[0-9]{4}-[0-9]{2}-[0-9]{2}",
                max_length=10,
                hint=N_("a date written as YYYY-MM-DD"),
            ),
            _prop(
                "date_format",
                "string",
                N_("Date format"),
                default="%Y-%m-%d",
                pattern=_DATE_FORMAT_RE,
                max_length=32,
                # Translators: keep the %-codes exactly as written.
                hint=N_("one each of day %d, month %m %b or %B, year %Y or %y; also %a %A %j %%"),
            ),
            _int("first_weekday", N_("First day of the week"), 0, 6, "0"),
        ),
    ),
    _tb(
        "Tableview",
        N_("Table view"),
        "Treeview",
        events=("select", "activate", *_FOCUS),
        properties=(
            *_shared("Treeview", "height", "selectmode"),
            _prop(
                "columns",
                "string",
                N_("Column headings"),
                translatable=True,
                pattern="[^;]{1,64}(;[^;]{1,64}){0,63}",
                max_length=64 * 64 + 63,
                hint=N_("up to 64 column headings separated by ';', each up to 64 characters"),
            ),
            _bool("paginated", N_("Paginated")),
            _bool("searchable", N_("Searchable")),
            _bool("yscrollbar", N_("Vertical scrollbar")),
            _bool("autofit", N_("Fit columns")),
            _int("pagesize", N_("Page size"), 1, 1000, "10"),
        ),
    ),
    _tb(
        "ToggleButton",
        N_("Toggle button"),
        "Checkbutton",
        bind_types=("bool", "int"),
        events=("command", "change", *_FOCUS),
        properties=(
            _TEXT,
            _STATE,
            _prop("shape", "enum", N_("Shape"), choices=("round", "square"), default="round"),
        ),
    ),
)


def tb_widgets() -> tuple[WidgetSpec, ...]:
    """The built-in ttkbootstrap extensions (entry point ``pyguibud.widgets:tb``).

    Their factories arrive with the backends (Step 17b); until then they render as fallbacks.
    """
    return _TB_WIDGETS
