"""Palette rows (pure): the registered widget classes grouped by category."""

from __future__ import annotations

from dataclasses import dataclass

from pyguibud.core import Registry
from pyguibud.i18n import N_, _

__all__ = ["PaletteGroup", "PaletteItem", "palette_groups"]

_M_OTHER = N_("Other")


@dataclass(frozen=True, slots=True)
class PaletteItem:
    """One widget class: its class ``name``, its ``label`` and whether a plugin provides it."""

    name: str
    label: str
    plugin: bool


@dataclass(frozen=True, slots=True)
class PaletteGroup:
    """A palette category and its widget classes."""

    category_label: str
    items: tuple[PaletteItem, ...]


def palette_groups(registry: Registry) -> list[PaletteGroup]:
    """Categories sorted by translated label; items sorted by label, then by class name."""
    grouped: dict[str, list[PaletteItem]] = {}
    for spec in registry.specs():
        category = spec.category_label() or _(_M_OTHER)
        grouped.setdefault(category, []).append(
            PaletteItem(spec.name, spec.label(), spec.plugin is not None)  # tb: is built in
        )
    return [
        PaletteGroup(
            category, tuple(sorted(items, key=lambda item: (item.label.casefold(), item.name)))
        )
        for category, items in sorted(grouped.items(), key=lambda pair: pair[0].casefold())
    ]
