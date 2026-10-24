"""Schema version constants and the published XSD of the ``.ui`` format (stdlib only).

The XSD documents the format for external tools; PyGUIbud never loads it at runtime.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from importlib.resources import files
from types import MappingProxyType
from typing import Final

__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "KNOWN_ATTRIBUTES",
    "UI_VOCABULARY",
    "XSD_FILENAME",
    "parse_version",
    "xsd_text",
]

CURRENT_SCHEMA_VERSION: Final = "1.0"
XSD_FILENAME: Final = "pyguibud-ui-1.0.xsd"

_VERSION_RE: Final = re.compile(r"^(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})$")

#: Local names of the elements of the ``.ui`` namespace (``NS_UI``).
UI_VOCABULARY: Final = frozenset(
    (
        *("pyguibud-ui", "meta", "resources", "image", "variables", "var", "window"),
        *("menubar", "menu", "action", "separator", "statusbar", "layout", "column", "row"),
        *("widget", "include", "prop", "event", "cell", "pack", "page"),
    )
)

#: Known attributes per element, in canonical (schema) order. Shared by the reader, the writer
#: and the validator, so an extra attribute can never shadow a known one.
KNOWN_ATTRIBUTES: Final[Mapping[str, tuple[str, ...]]] = MappingProxyType(
    {
        "pyguibud-ui": ("schema_version",),
        "meta": ("generator", "source_locale", "i18n_domain", "theme"),
        "resources": (),
        "image": ("id", "src"),
        "variables": (),
        "var": ("id", "type", "default"),
        "window": ("id", "kind", "min_width", "min_height", "modal", "buttons"),
        "menubar": (),
        "menu": ("id",),
        "action": ("id", "handler", "shortcut"),
        "separator": (),
        "statusbar": ("id",),
        "layout": ("type", "orient", "padding", "gap"),
        "column": ("index", "weight", "minsize"),
        "row": ("index", "weight", "minsize"),
        "widget": ("class", "id", "bind", "fallback", "plugin"),
        "include": ("id", "src", "component"),
        "prop": ("name", "ref", "translatable", "context", "comment"),
        "event": ("name", "handler"),
        "cell": ("row", "column", "rowspan", "columnspan", "sticky", "padx", "pady"),
        "pack": ("fill", "expand", "padx", "pady"),
        "page": ("image", "weight"),
    }
)


def parse_version(text: str) -> tuple[int, int] | None:
    """Return ``(major, minor)`` for a ``MAJOR.MINOR`` string, or None if it is malformed."""
    # fullmatch: ``$`` alone would accept a trailing newline.
    match = _VERSION_RE.fullmatch(text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def xsd_text() -> str:
    """Return the text of the published XSD."""
    return files(__name__).joinpath(XSD_FILENAME).read_text(encoding="utf-8")
