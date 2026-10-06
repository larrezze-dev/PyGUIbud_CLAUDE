"""Backend contract (provisional until 1.0, like ``WidgetSpec``); toolkit-free.

A backend turns a :class:`BuildPlan` prepared by ``pyguibud_runtime`` into real windows. It imports
its toolkit only inside :meth:`Backend.prepare` and :meth:`Backend.build` (ADR-007).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Protocol

if TYPE_CHECKING:
    from pyguibud.core.model import Document, Include, Prop, Window
    from pyguibud.core.registry import Registry

__all__ = [
    "Backend",
    "BuildPlan",
    "DocumentPlan",
    "Instance",
    "NoDisplayError",
    "RootExistsError",
    "Scope",
    "Session",
    "TextSlot",
]


class RootExistsError(RuntimeError):
    """``prepare(None)`` found a live root window (mapped to ``runtime.root_exists``)."""


class NoDisplayError(RuntimeError):
    """The toolkit could not open a display (mapped to ``runtime.no_display``)."""


@dataclass(frozen=True, slots=True, eq=False)
class TextSlot:
    """One translatable text of a document: the runtime turns it into display text."""

    document: str  # DiskFiles key of the owning .ui file
    prop: Prop


@dataclass(frozen=True, slots=True, eq=False)
class DocumentPlan:
    """One ``.ui`` file taking part in the build."""

    key: str
    path: Path
    document: Document


class Scope(Protocol):
    """What a backend may do with a ``UiScope``: attach an id, fill ``vars`` and ``windows``."""

    def _attach(self, name: str, obj: object, *, window: bool = False) -> None: ...
    def _attach_var(self, name: str, var: object) -> None: ...


@dataclass(eq=False, slots=True)
class Instance:
    """One document instance: the top document, or one ``<include>`` occurrence."""

    doc: DocumentPlan
    windows: tuple[Window, ...]  # top: main + dialogs; include: the component window
    scope: Scope
    host: Instance | None = None  # set when the variables are shared with the host instance
    includes: dict[int, Instance] = field(default_factory=dict)  # id(Include) -> instance
    vars: dict[str, Any] = field(default_factory=dict)  # filled by the backend

    def include(self, node: Include) -> Instance:
        """The child instance built for ``node``."""
        return self.includes[id(node)]


@dataclass(frozen=True, slots=True, eq=False)
class BuildPlan:
    """Everything a backend needs; built before any toolkit object exists."""

    path: str
    top: Instance
    handlers: Mapping[str, Callable[[], object]]
    images: Mapping[tuple[str, str], Path]
    registry: Registry
    theme: str
    text: Callable[[TextSlot], str]  # initial display text of a slot
    runtime_text: Callable[[str], str]  # runtime-owned msgids (dialog buttons)
    log: Callable[..., None]  # log(msgid, **params): a runtime warning


class Session(Protocol):
    """A built interface, owned by a ``LoadedUi``."""

    def apply_texts(
        self, text: Callable[[TextSlot], str], runtime_text: Callable[[str], str]
    ) -> None:
        """Set every text slot; all-or-nothing when ``text`` raises (compute, then apply)."""
        ...

    def alive(self) -> bool:
        """False once any window of the session (or the toolkit root) is gone; never raises."""
        ...

    def show(self, window_id: str) -> str | None: ...
    def run(self) -> None: ...
    def destroy(self) -> None: ...


class Backend(Protocol):
    """A toolkit backend registered under the ``pyguibud.backends`` entry point."""

    name: ClassVar[str]

    def prepare(self, master: object | None) -> None: ...
    def build(self, plan: BuildPlan, master: object | None) -> Session: ...
