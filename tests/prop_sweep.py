"""A ``.ui`` with every core widget class, each carrying every property its spec defines and the
property names other classes use but it does not define (the "kept but ignored" warning).

Shared by the runtime/codegen parity sweep and the designer canvas sweep: no builder may pass a
property the built class does not define to Tk (``unknown option "-text"``).
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from pyguibud.core.model import PropertyDef
from pyguibud.core.registry import Registry

#: A 1 x 1 GIF (the resource of every ``image`` property).
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
#: The chrome classes, which are never a ``<widget>``.
CHROME = frozenset({"Menubar", "Menu", "Action", "Statusbar"})
#: Property names some classes define and others do not; ``state`` is read outside the options.
FOREIGN = {"text": "Foreign", "state": "disabled", "value": "v", "image": "img", "show": "*"}


def sample(definition: PropertyDef) -> str:
    """A valid, non-default value for ``definition``."""
    if definition.type == "enum":
        return definition.choices[-1]
    return {"int": "7", "float": "3", "bool": "false", "colour": "#1C3FF0"}.get(
        definition.type, "Sample"
    )


def widget_classes(registry: Registry) -> list[str]:
    """Every registered core widget class that can be a ``<widget>``."""
    return sorted(s.name for s in registry.specs() if s.name not in CHROME and not s.is_extension)


def _prop(name: str, value: str, *, ref: bool = False) -> str:
    if ref:
        return f"<prop name={quoteattr(name)} ref={quoteattr(value)}/>"
    return f"<prop name={quoteattr(name)}>{escape(value)}</prop>"


def sweep_ui(folder: Path, registry: Registry) -> Path:
    """Write ``sweep.ui`` (and its image) into ``folder``; one widget per core class."""
    (folder / "pixel.gif").write_bytes(GIF)
    widgets = []
    for name in widget_classes(registry):
        spec = registry.require(name)
        props = {d.name: _prop(d.name, sample(d), ref=d.type == "image") for d in spec.properties}
        if "image" in props:
            props["image"] = _prop("image", "img", ref=True)
        for key, value in FOREIGN.items():
            props.setdefault(key, _prop(key, value))
        layout = '<layout type="pack"/>' if spec.children == "layout" else ""
        body = "".join(props[k] for k in sorted(props))
        head = f'<widget class="{name}" id="w_{name.lower()}">'
        widgets.append(f"{head}{body}<pack/>{layout}</widget>")
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<meta source_locale="en_GB"/>'
        '<resources><image id="img" src="pixel.gif"/></resources>'
        '<window id="main" kind="main"><layout type="pack"/>'
        + "".join(widgets)
        + "</window></pyguibud-ui>\n"
    )
    path = folder / "sweep.ui"
    path.write_text(text, encoding="utf-8")
    return path
