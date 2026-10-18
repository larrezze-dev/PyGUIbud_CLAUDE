"""Findings (reader warnings and validator results), source positions and node paths.

A :class:`Finding` is one problem found in a document. The reader emits warnings, the validator
emits warnings and errors, and the designer shows them. The message is translated when it is read,
not when the finding is created (ADR-006; spec ``docs/specs/validate-commands.md`` section 3).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, TypeAlias

from pyguibud.core.errors import ModelError, _format_location, format_message
from pyguibud.core.model import (
    Action,
    Document,
    Include,
    Menu,
    Menubar,
    MenuSeparator,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.core.text import printable

__all__ = [
    "EMPTY_SOURCE_MAP",
    "Finding",
    "Severity",
    "SourceMap",
    "node_path",
]

Severity: TypeAlias = Literal["error", "warning"]

#: Safety net against hand-built, cyclic parent chains.
_MAX_PATH_SEGMENTS: Final = 100_000


@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:
    """One finding; ``message`` is translated on read and never raises.

    Equality ignores ``anchor`` and ``related`` (model nodes), so tests compare plain data.
    """

    code: str
    msgid: str
    params: Mapping[str, object] = field(default_factory=dict, hash=False)
    source: str
    line: int | None = None
    column: int | None = None
    severity: Severity = "warning"
    #: Untranslated node path, for example ``window[main]/widget[btn]`` (see :func:`node_path`).
    path: str = ""
    #: The model node the finding is about (the designer selects it).
    anchor: object | None = field(default=None, compare=False, hash=False, repr=False)
    #: Sub-element of the anchor, for example ``prop[text]`` or ``cell``.
    part: str = ""
    #: The second node of a symmetric finding (grid collision); used by the command guards.
    related: object | None = field(default=None, compare=False, hash=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    @property
    def message(self) -> str:
        """The message in the current language (never raises)."""
        return format_message(self.msgid, self.params)

    @property
    def location(self) -> str:
        """``source:line:column`` (parts omitted when unknown)."""
        return _format_location(self.source, self.line, self.column)

    @property
    def is_error(self) -> bool:
        """True when the severity is ``error``."""
        return self.severity == "error"

    def __str__(self) -> str:
        # Ids and values come from the file: they must not forge or reorder output lines.
        return printable(f"{self.location}: {self.message}")


class SourceMap:
    """Positions ``(line, column)`` of model nodes as read from a file (immutable).

    Keys are ``(anchor, part)``; tree nodes hash by identity, and value objects (properties,
    events, cells) are addressed through ``part`` on their owner.
    """

    __slots__ = ("_entries",)

    def __init__(self, entries: Mapping[tuple[object, str], tuple[int, int]] | None = None) -> None:
        self._entries: dict[tuple[object, str], tuple[int, int]] = dict(entries or {})

    def get(self, anchor: object, part: str = "") -> tuple[int, int] | None:
        """Exact ``(anchor, part)``; else the part before the first ``/``; else the anchor."""
        try:
            hit = self._entries.get((anchor, part))
            if hit is None and "/" in part:
                hit = self._entries.get((anchor, part.split("/", 1)[0]))
            if hit is None and part:
                hit = self._entries.get((anchor, ""))
        except TypeError:  # an unhashable anchor in a hand-built model
            return None
        return hit

    def __len__(self) -> int:
        return len(self._entries)


EMPTY_SOURCE_MAP: Final = SourceMap()


def _id_or_index(node: object, text: object) -> str:
    if isinstance(text, str) and text:
        return text
    parent = getattr(node, "parent", None)
    index = 0
    if parent is not None:
        try:
            index = parent.index_of(node)
        except (ModelError, AttributeError):
            index = 0
    return f"#{index}"


def node_path(anchor: object, part: str = "", *, window: Window | None = None) -> str:
    """Return the untranslated, slash-separated path of ``anchor`` (plus ``part``).

    Iterative. A menu bar and a status bar have no parent pointer, so ``window`` (the window
    that owns them) supplies the leading segment; without it the path starts at ``menubar`` or
    ``statusbar[...]``. A detached node gets the path of its own subtree root.
    """
    segments: list[str] = []
    current: object | None = anchor
    visited = 0
    while current is not None and visited < _MAX_PATH_SEGMENTS:
        visited += 1
        following: object | None
        if isinstance(current, Document):
            break
        if isinstance(current, Window):
            segments.append(f"window[{_id_or_index(current, current.id)}]")
            following = current.parent
        elif isinstance(current, Widget):
            segments.append(f"widget[{_id_or_index(current, current.id)}]")
            following = current.parent
        elif isinstance(current, Include):
            segments.append(f"include[{_id_or_index(current, current.id)}]")
            following = current.parent
        elif isinstance(current, Menu):
            segments.append(f"menu[{_id_or_index(current, current.id)}]")
            following = current.parent
        elif isinstance(current, Action):
            segments.append(f"action[{_id_or_index(current, current.id)}]")
            following = current.parent
        elif isinstance(current, MenuSeparator):
            parent = current.parent
            index = 0
            if parent is not None:
                try:
                    index = parent.index_of(current)
                except ModelError:
                    index = 0
            segments.append(f"separator[{index}]")
            following = parent
        elif isinstance(current, Menubar):
            segments.append("menubar")
            following = window
            window = None
        elif isinstance(current, Statusbar):
            segments.append(f"statusbar[{_id_or_index(current, current.id)}]")
            following = window
            window = None
        else:
            break
        current = following
    if part:
        segments.reverse()
        segments.append(part)
        return "/".join(segments)
    segments.reverse()
    return "/".join(segments)
