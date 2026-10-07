"""Rows of the "New from template" wizard (pure): id, title and description per template."""

from __future__ import annotations

from dataclasses import dataclass

from pyguibud.designer.templates import TEMPLATES
from pyguibud.i18n import _

__all__ = ["TemplateRow", "step_index", "template_rows"]


@dataclass(frozen=True, slots=True)
class TemplateRow:
    """One wizard entry in the current language."""

    id: str
    title: str
    description: str


def template_rows() -> list[TemplateRow]:
    """Every built-in template, translated now (the dialog re-reads them on a language switch)."""
    return [TemplateRow(info.id, _(info.title), _(info.description)) for info in TEMPLATES]


def step_index(current: int, delta: int, count: int) -> int:
    """The list index after moving ``delta`` steps from ``current``, clamped (no wrap-around)."""
    if count <= 0:
        return -1
    return max(0, min(count - 1, current + delta))
