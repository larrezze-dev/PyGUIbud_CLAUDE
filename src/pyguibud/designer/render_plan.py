"""The designer's build plan for one window (pure; spec dnd-selection 2.2, ADR-010).

The canvas never calls ``load_ui``: that is strict, needs handlers and paths, and refuses
component-only files. This plan wires no handler (opening a ``.ui`` never runs code), shows the
source texts, loads no image (Step 14) and leaves includes unexpanded (placeholders).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pyguibud.backends.base import BuildPlan, DocumentPlan, Instance, TextSlot
from pyguibud.core.model import Document, Window
from pyguibud.core.registry import Registry

__all__ = ["DESIGN_KEY", "RecordingScope", "design_plan", "source_text"]

#: The document key of the open document in every design plan.
DESIGN_KEY = "<designer>"


class RecordingScope:
    """A ``Scope`` that keeps nothing: the canvas maps nodes by identity (``Embed.on_node``).

    Ids cannot be trusted for that: an invalid document may have duplicate or empty ids.
    """

    def _attach(self, name: str, obj: object, *, window: bool = False) -> None:
        """Ignore ``ui.<id>`` (the canvas has no scope object)."""

    def _attach_var(self, name: str, var: object) -> None:
        """Ignore ``ui.vars.<id>``."""


def source_text(slot: TextSlot) -> str:
    """The text as written in the document (translated preview is Step 15)."""
    value = slot.prop.value
    return value if isinstance(value, str) else ""


def design_plan(
    document: Document,
    window: Window,
    registry: Registry,
    *,
    log: Callable[..., None],
) -> BuildPlan:
    """The plan that draws ``window`` of ``document`` on the canvas; one plan per window."""
    top = Instance(
        DocumentPlan(key=DESIGN_KEY, path=Path(), document=document),
        windows=(window,),
        scope=RecordingScope(),
    )
    return BuildPlan(
        path=DESIGN_KEY,
        top=top,
        handlers={},
        images={},
        registry=registry,
        theme="",
        text=source_text,
        runtime_text=str,
        log=log,
    )
