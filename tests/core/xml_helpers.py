"""Helpers shared by the ``.ui`` I/O tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path

from pyguibud.core import NS_UI, XmlIoError, read_ui_bytes

DATA = Path(__file__).parent / "data" / "xml_io"
HELLO = Path(__file__).parents[2] / "examples" / "hello.ui"
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'

#: Fields that point back up the tree (they would make the dump cyclic).
_BACK_REFERENCES = frozenset({"parent"})


def structure(obj: object) -> object:
    """Return a recursive plain-data dump of a model object.

    Tree nodes compare by identity (``eq=False``), so tests compare these dumps instead.
    Dataclasses become ``{"__type__": name, field: ...}``, mappings become dicts (insertion
    order is irrelevant to ``==``), sequences become lists. Parent links are skipped.
    """
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        result: dict[str, object] = {"__type__": type(obj).__name__}
        for field in dataclasses.fields(obj):
            if field.name in _BACK_REFERENCES:
                continue
            result[field.name] = structure(getattr(obj, field.name))
        return result
    if isinstance(obj, Mapping):
        return {key: structure(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [structure(item) for item in obj]
    return obj


def doc(body: str = "", root_attrs: str = "", *, version: str = "1.0", ns: str = NS_UI) -> bytes:
    """Build a one-line-per-element document: the root is on line 2, ``body`` starts on line 3."""
    return (
        f'{HEAD}<pyguibud-ui schema_version="{version}" xmlns="{ns}"{root_attrs}>\n{body}\n'
        "</pyguibud-ui>\n"
    ).encode()


def read_error(data: bytes) -> XmlIoError:
    """Read ``data`` and return the :class:`XmlIoError` it must raise."""
    try:
        read_ui_bytes(data, source="t.ui")
    except XmlIoError as exc:
        return exc
    raise AssertionError("expected XmlIoError")
