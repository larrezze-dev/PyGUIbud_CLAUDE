"""A sample PyGUIbud widget plugin: ``acme:ColourSwatch`` (spec plugins section 9).

Registered through the ``pyguibud.widgets`` entry point. The toolkits are imported inside the
factories only, so reading the specification never needs Tk or Qt.
``ACME_PYGUIBUD_BREAK`` (``import``, ``spec``, ``factory`` or ``exit``) makes the plugin fail on
purpose, to try the designer's isolation of broken plugins.
"""

# ruff: noqa: ANN401  (toolkit widgets are untyped here: the toolkits are imported lazily)
from __future__ import annotations

import gettext
import os
import sys
from typing import Any

from pyguibud.core.model import WIDGET_API_VERSION, PropertyDef, WidgetSpec

__all__ = ["qt_swatch", "tk_swatch", "widgets"]

# The plugin's own gettext domain: a plugin ships and translates its strings itself.
_ = gettext.translation("acme_pyguibud", fallback=True).gettext
_BREAK = "ACME_PYGUIBUD_BREAK"


def _break(mode: str) -> None:
    """Fail on purpose when the environment asks for ``mode``."""
    if os.environ.get(_BREAK) == mode:
        raise RuntimeError(f"acme-pyguibud was told to break ({mode})")


if os.environ.get(_BREAK) == "exit":
    sys.exit(3)
_break("import")


def widgets() -> tuple[WidgetSpec, ...]:
    """The plugin's widget specifications."""
    _break("spec")
    return (
        WidgetSpec(
            api_version=WIDGET_API_VERSION,
            name="acme:ColourSwatch",
            display_name=_("Colour swatch"),
            category=_("Acme"),
            fallback="Label",
            plugin="acme-pyguibud",
            properties=(
                PropertyDef(name="text", type="string", translatable=True, display_name=_("Text")),
                PropertyDef(
                    name="colour", type="colour", default="#2E86DE", display_name=_("Colour")
                ),
            ),
            bind_types=("string",),
            factories={
                "ttkbootstrap": "acme_pyguibud:tk_swatch",
                "tkinter": "acme_pyguibud:tk_swatch",
                "pyside6": "acme_pyguibud:qt_swatch",
            },
        ),
    )


def tk_swatch(parent: Any, props: dict[str, Any], variable: Any, bootstyle: str | None) -> Any:
    """A ``tkinter.Label`` with a coloured background (``variable`` is bound as its text)."""
    _break("factory")
    import tkinter

    label = tkinter.Label(parent, bg=props.get("colour", "#2E86DE"), fg="white", padx=8, pady=4)
    if variable is not None:
        label.configure(textvariable=variable)
    return label


def qt_swatch(parent: Any, props: dict[str, Any]) -> Any:
    """A ``QLabel`` with a style sheet; it is its own ``inner`` widget."""
    _break("factory")
    from PySide6.QtWidgets import QLabel

    label = QLabel(parent)
    label.setStyleSheet(
        f"background: {props.get('colour', '#2E86DE')}; color: white; padding: 4px;"
    )
    return label
