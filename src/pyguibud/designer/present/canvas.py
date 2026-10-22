"""Canvas summary cards (pure): one tab per window with a short description (placeholder)."""

from __future__ import annotations

from dataclasses import dataclass

from pyguibud.core import Document, Include, Widget, Window
from pyguibud.core.text import printable
from pyguibud.designer.present import clip
from pyguibud.i18n import N_, _, ngettext

__all__ = ["CanvasTab", "canvas_tabs", "kind_label", "window_of"]

_KINDS = {
    "main": N_("Main window"),
    "dialog": N_("Dialog"),
    "component": N_("Component"),
}
_M_LAYOUT = N_("Layout: {type}")
_M_NO_LAYOUT = N_("No layout")
_M_NO_ID = N_("(no id)")


@dataclass(frozen=True, slots=True)
class CanvasTab:
    """The tab of one window: its text, its kind and the lines of its summary card."""

    window: Window
    text: str
    kind_label: str
    summary: tuple[str, ...]


def kind_label(window: Window) -> str:
    """The window kind in the current language."""
    msgid = _KINDS.get(window.kind)
    return _(msgid) if msgid else clip(window.kind)


def window_of(node: object, document: Document | None = None) -> Window | None:
    """The window that owns ``node``.

    A menu bar and a status bar have no parent pointer, so ``document`` is searched for them.
    """
    current: object | None = node
    for _hop in range(100_000):  # safety net against hand-built cyclic parent chains
        if isinstance(current, Window):
            return current
        parent = getattr(current, "parent", None)
        if parent is None:
            break
        current = parent
    if document is not None and current is not None:
        for window in document.children:
            if any(candidate is current for candidate in window.walk()):
                return window
    return None


def _widget_count(window: Window) -> int:
    return sum(1 for node in window.walk() if isinstance(node, Widget | Include))


def canvas_tabs(document: Document) -> list[CanvasTab]:
    """One tab per window; the tab text is the ``title`` property, else the id."""
    tabs: list[CanvasTab] = []
    for window in document.children:
        title = window.props.get("title")
        text = clip(printable(title.value if title is not None and title.value else window.id))
        if not text:
            text = _(_M_NO_ID)
        layout = (
            _(_M_LAYOUT).format(type=window.layout.type)
            if window.layout is not None
            else _(_M_NO_LAYOUT)
        )
        count = _widget_count(window)
        summary = (
            layout,
            # Translators: summary under a window tab; {count} is the number of widgets in it.
            ngettext("{count} widget", "{count} widgets", count).format(count=count),
        )
        tabs.append(CanvasTab(window, text, kind_label(window), summary))
    return tabs
