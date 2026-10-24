"""Toolkit backends, registered under the ``pyguibud.backends`` entry point (built-ins included).

Importing this package never imports a toolkit (ADR-007).
"""

from __future__ import annotations

import importlib

from pyguibud.backends.base import Backend, BuildPlan, Session, TextSlot
from pyguibud.core.errors import RegistryError
from pyguibud.core.model import BACKEND_NAME
from pyguibud.core.registry import Registry

__all__ = [
    "BACKEND_NAME",
    "BUILTIN_BACKENDS",
    "Backend",
    "BuildPlan",
    "Session",
    "TextSlot",
    "load_backend",
]

#: Safety net: built-in backends load even when the entry points are missing (editable installs).
BUILTIN_BACKENDS: dict[str, str] = {
    "ttkbootstrap": "pyguibud.backends.ttkbootstrap:TtkbootstrapBackend",
    "tkinter": "pyguibud.backends.tkinter:TkinterBackend",
    "pyside6": "pyguibud.backends.pyside6:PySide6Backend",
}


def load_backend(name: str, registry: Registry) -> type[Backend]:
    """Return the backend class registered as ``name``.

    Raises:
        RegistryError: unknown backend, or it failed to load.
        TypeError: the entry point is not a class.
    """
    try:
        loaded = registry.load_backend(name)
    except RegistryError as exc:
        target = BUILTIN_BACKENDS.get(name)
        if exc.code != "registry.unknown_backend" or target is None:
            raise
        module, _sep, attribute = target.partition(":")
        loaded = getattr(importlib.import_module(module), attribute)
    if not isinstance(loaded, type):
        raise TypeError(f"backend {name!r} is not a class")
    backend: type[Backend] = loaded
    return backend
