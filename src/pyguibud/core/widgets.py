"""The 24 built-in widget specifications (ADR-001), registered through the ``pyguibud.widgets``
entry point like any plugin (ADR-004 dogfooding).

Pure data: importing this module translates nothing. Display names and categories are msgids
marked with ``N_()`` and are translated only when read.
"""

from __future__ import annotations

from pyguibud.core.model import WIDGET_API_VERSION, PropertyDef, WidgetSpec
from pyguibud.i18n import N_

__all__ = ["core_widgets"]

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
