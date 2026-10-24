"""Read and write ``.ui`` files (ADR-002 + Addendum A; spec ``docs/specs/xml-io.md``).

The reader is fail-fast: it raises :class:`XmlIoError` on the first error and returns every
non-fatal finding as an :class:`XmlWarning`. The writer produces canonical bytes and never emits
a file its own reader would reject. Opening a file never executes code.
"""

from __future__ import annotations

import codecs
import contextlib
import errno
import os
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, cast

from pyguibud.core import migrations, xmltree
from pyguibud.core.atomic import backup_path, create_temporary
from pyguibud.core.diagnostics import EMPTY_SOURCE_MAP, Finding, SourceMap
from pyguibud.core.errors import ModelError, XmlIoError
from pyguibud.core.model import (
    KNOWN_NAMESPACES,
    NS_UI,
    Action,
    ContainerExtras,
    Document,
    Event,
    GridCell,
    GridLine,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    Meta,
    PackPlacement,
    PagePlacement,
    Placement,
    Prop,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    Window,
    split_class_name,
)
from pyguibud.core.schema import (
    CURRENT_SCHEMA_VERSION,
    KNOWN_ATTRIBUTES,
    UI_VOCABULARY,
    parse_version,
)
from pyguibud.core.xmltree import MAX_DEPTH, LazyMessage, is_whitespace, split_name
from pyguibud.i18n import N_

__all__ = [
    "MAX_DEPTH",
    "MAX_UI_BYTES",
    "ReadResult",
    "XmlWarning",
    "dump_ui",
    "read_ui",
    "read_ui_bytes",
    "read_ui_string",
    "write_ui",
]

#: Size limit of a ``.ui`` file, checked before parsing.
MAX_UI_BYTES: Final = 10 * 1024 * 1024

#: Leading bytes checked for NUL: enough for BOM-less UTF-16 and UTF-32 in either byte order.
_SNIFF_BYTES: Final = 4
_ROOT: Final = "pyguibud-ui"
_ROOT_NS_RE: Final = re.compile(r"urn:pyguibud:ui:([1-9][0-9]{0,8})")
_INT_RE: Final = re.compile(r"-?[0-9]{1,9}")
_INT_LIMIT: Final = 999_999_999
_MEMORY: Final = "<memory>"
_REPLACE_RETRIES: Final = 5
_REPLACE_DELAY: Final = 0.05

#: Known local names in ``NS_UI`` and known attributes per element, in canonical (schema)
#: order. They live in :mod:`pyguibud.core.schema` so the validator checks the same tables.
_VOCABULARY: Final = UI_VOCABULARY
_ATTRS: Final = KNOWN_ATTRIBUTES

_PLACEMENTS: Final = frozenset({"cell", "pack", "page"})

#: Known children allowed per known parent.
_ALLOWED: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        _ROOT: frozenset({"meta", "resources", "variables", "window"}),
        "meta": frozenset(),
        "resources": frozenset({"image"}),
        "image": frozenset(),
        "variables": frozenset({"var"}),
        "var": frozenset(),
        "window": frozenset({"prop", "menubar", "statusbar", "layout", "widget", "include"}),
        "menubar": frozenset({"menu"}),
        "menu": frozenset({"prop", "menu", "action", "separator"}),
        "action": frozenset({"prop"}),
        "separator": frozenset(),
        "statusbar": frozenset({"prop"}),
        "layout": frozenset({"column", "row"}),
        "column": frozenset(),
        "row": frozenset(),
        "widget": frozenset({"prop", "event", "layout", "widget", "include"} | _PLACEMENTS),
        "include": _PLACEMENTS,
        "event": frozenset(),
        "cell": frozenset(),
        "pack": frozenset(),
        "page": frozenset({"prop"}),
    }
)

_KINDS: Final = ("main", "dialog", "component")
_VAR_TYPES: Final = ("string", "int", "double", "bool")
_LAYOUT_TYPES: Final = ("grid", "pack")
_ORIENTS: Final = ("vertical", "horizontal")
_FILLS: Final = ("none", "x", "y", "both")


# ---------------------------------------------------------------- public types
#: Reader warnings are :class:`Finding` objects with ``severity="warning"`` and no path (D1).
XmlWarning = Finding


@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ReadResult:
    """Outcome of reading a ``.ui`` file."""

    document: Document
    warnings: tuple[XmlWarning, ...]
    #: True only for a file with a newer MINOR schema version; the writer refuses it.
    read_only: bool
    #: The schema version as written in the file, before any migration.
    source_version: str
    source: str
    #: Positions of the model nodes as read; elements created by a migration have none.
    positions: SourceMap = EMPTY_SOURCE_MAP


# ---------------------------------------------------------------- reading
def read_ui(path: str | os.PathLike[str]) -> ReadResult:
    """Read a ``.ui`` file.

    Raises:
        XmlIoError: the file cannot be read or is not a valid ``.ui`` file (fail-fast).
    """
    source = os.fspath(path)
    # Windows raises PermissionError when opening a folder, so check this first.
    if os.path.isdir(path):
        raise XmlIoError("xml.is_directory", N_("This is a folder, not a .ui file."), source=source)
    # A device (CON, NUL) or a FIFO would block on read or return endless data.
    if os.path.exists(path) and not os.path.isfile(path):
        raise XmlIoError(
            "xml.not_a_file",
            N_("This is a device or another special file, not a .ui file."),
            source=source,
        )
    try:
        with open(path, "rb") as stream:
            data = stream.read(MAX_UI_BYTES + 1)
    except FileNotFoundError as exc:
        raise XmlIoError(
            "xml.file_not_found", N_("The file does not exist."), source=source
        ) from exc
    except OSError as exc:
        raise XmlIoError(
            "xml.read_failed",
            # Translators: {reason} is an error description from the operating system.
            N_("The file could not be read: {reason}"),
            source=source,
            reason=exc.strerror or str(exc),
        ) from exc
    return _read(data, source=source, check_declared_encoding=True)


def read_ui_bytes(data: bytes, *, source: str = "<bytes>") -> ReadResult:
    """Read a ``.ui`` document from bytes (same rules as :func:`read_ui`)."""
    return _read(bytes(data), source=source, check_declared_encoding=True)


def read_ui_string(text: str, *, source: str = "<string>") -> ReadResult:
    """Read a ``.ui`` document from already decoded text; the declared encoding is ignored."""
    text = text.removeprefix("﻿")
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _bad_encoding(source) from exc
    return _read(data, source=source, check_declared_encoding=False)


def _bad_encoding(source: str, line: int | None = None, column: int | None = None) -> XmlIoError:
    return XmlIoError(
        "xml.bad_encoding",
        N_("The file is not valid UTF-8 text; save it with UTF-8 encoding."),
        source=source,
        line=line,
        column=column,
    )


def _root_check(tag: str) -> None:
    uri, local = split_name(tag)
    if local != _ROOT or uri is None or _ROOT_NS_RE.fullmatch(uri) is None:
        raise XmlIoError(
            "xml.bad_root",
            # Translators: {namespace} is the XML namespace URI of PyGUIbud files.
            N_(
                "This is not a PyGUIbud .ui file: the root element must be <pyguibud-ui> "
                "in the namespace {namespace}."
            ),
            namespace=NS_UI,
        )


def _read(data: bytes, *, source: str, check_declared_encoding: bool) -> ReadResult:
    if len(data) > MAX_UI_BYTES:
        raise XmlIoError(
            "xml.too_large",
            # Translators: {limit} is a whole number of mebibytes.
            N_("The file is larger than the limit of {limit} MiB for .ui files."),
            source=source,
            limit=MAX_UI_BYTES // (1024 * 1024),
        )
    data = data.removeprefix(codecs.BOM_UTF8)
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        line_start = data.rfind(b"\n", 0, exc.start) + 1
        raise _bad_encoding(
            source, data.count(b"\n", 0, exc.start) + 1, exc.start - line_start + 1
        ) from exc
    # NUL bytes are valid UTF-8, but expat sniffs a leading "<\0" or "\0<" as UTF-16 despite
    # the UTF-8 override, so BOM-less UTF-16 would pass the check above. No UTF-8 .ui file can
    # hold U+0000 in its first characters; a NUL there means a wider encoding (UTF-16/32, no
    # BOM). A NUL further on is left to expat, which reports it as xml.malformed.
    nul = data.find(b"\0", 0, _SNIFF_BYTES)
    if nul >= 0:
        raise _bad_encoding(
            source, data.count(b"\n", 0, nul) + 1, nul - (data.rfind(b"\n", 0, nul) + 1) + 1
        )

    tree = xmltree.parse(
        data, source=source, check_declared_encoding=check_declared_encoding, root_check=_root_check
    )
    root = tree.root
    line, column = tree.positions.get(root, (None, None))
    warnings: list[XmlWarning] = []

    namespace_match = _ROOT_NS_RE.fullmatch(split_name(root.tag)[0] or "")
    major_ns = int(namespace_match.group(1)) if namespace_match else 0
    version = root.get("schema_version")
    if version is None:
        raise XmlIoError(
            "xml.missing_attribute",
            # Translators: {element} is an XML element name, {attribute} an attribute name.
            N_("The element <{element}> needs the attribute '{attribute}'."),
            source=source,
            line=line,
            column=column,
            element=_ROOT,
            attribute="schema_version",
        )
    parsed = parse_version(version)
    if parsed is None:
        raise XmlIoError(
            "xml.bad_version",
            # Translators: {version} is the text found in the file; keep MAJOR.MINOR as it is.
            N_("'{version}' is not a valid schema version; expected MAJOR.MINOR, for example 1.0."),
            source=source,
            line=line,
            column=column,
            version=version,
        )
    current = cast("tuple[int, int]", parse_version(CURRENT_SCHEMA_VERSION))
    if major_ns > 1 or parsed[0] > current[0]:
        raise XmlIoError(
            "xml.newer_major",
            # Translators: {version} and {current} are schema versions such as 2.0 and 1.0.
            N_(
                "This file uses schema version {version}; it needs a newer PyGUIbud "
                "(this one supports {current})."
            ),
            source=source,
            line=line,
            column=column,
            version=version,
            current=CURRENT_SCHEMA_VERSION,
        )
    read_only = parsed > current
    document_version = CURRENT_SCHEMA_VERSION
    if read_only:
        document_version = version
        warnings.append(
            XmlWarning(
                code="xml.newer_minor",
                # Translators: {version} and {current} are schema versions such as 1.1 and 1.0.
                msgid=N_(
                    "This file uses schema version {version}, newer than {current}; it is "
                    "opened read-only so that nothing is lost."
                ),
                params={"version": version, "current": CURRENT_SCHEMA_VERSION},
                source=source,
                line=line,
                column=column,
            )
        )
    elif parsed < current:
        root, document_version, _steps = migrations.migrate(root, version, source=source)
        warnings.append(
            XmlWarning(
                code="xml.migrated",
                # Translators: {version} and {current} are schema versions such as 0.9 and 1.0.
                msgid=N_(
                    "The file was upgraded from schema version {version} to {current}; saving "
                    "writes the new version."
                ),
                params={"version": version, "current": CURRENT_SCHEMA_VERSION},
                source=source,
                line=line,
                column=column,
            )
        )

    for prefix, uri in (*tree.namespaces.items(), *tree.rebound.items()):
        if KNOWN_NAMESPACES.get(prefix, uri) != uri:  # xmlns:tb="urn:evil" (ADR-002 Addendum B)
            warnings.append(
                XmlWarning(
                    code="xml.foreign_prefix",
                    # Translators: {prefix} is an XML namespace prefix such as tb; {uri} is the
                    # namespace it is bound to in the file. Keep both unchanged.
                    msgid=N_(
                        "The prefix '{prefix}' is bound to the foreign namespace '{uri}'; this "
                        "content is not for ttkbootstrap and is saved under another prefix."
                    ),
                    params={"prefix": prefix, "uri": uri},
                    source=source,
                )
            )
    namespaces = {"": NS_UI, **tree.namespaces}
    reader = _Reader(source, tree.positions, namespaces, newer_minor=read_only)
    document = reader.document(root, document_version)
    warnings += reader.warnings
    if tree.discarded:
        warnings.append(
            XmlWarning(
                code="xml.discarded_content",
                # Translators: {count} is a number of XML comments and processing instructions.
                msgid=N_(
                    "Comments and processing instructions ({count}) are not kept when the file "
                    "is saved."
                ),
                params={"count": tree.discarded},
                source=source,
            )
        )
    return ReadResult(
        document=document,
        warnings=tuple(warnings),
        read_only=read_only,
        source_version=version,
        source=source,
        positions=SourceMap(reader.entries),
    )


class _Reader:
    """Maps a parsed element tree to the model (fail-fast, warnings in document order)."""

    def __init__(
        self,
        source: str,
        positions: Mapping[ET.Element, tuple[int, int]],
        namespaces: Mapping[str, str],
        *,
        newer_minor: bool,
    ) -> None:
        self.source = source
        self.positions = positions
        self.namespaces = namespaces
        self.newer_minor = newer_minor
        self.warnings: list[XmlWarning] = []
        #: ``(node, part)`` -> ``(line, column)`` for :class:`SourceMap`.
        self.entries: dict[tuple[object, str], tuple[int, int]] = {}

    # ------------------------------------------------ diagnostics
    def record(self, anchor: object, part: str, element: ET.Element) -> None:
        position = self.positions.get(element)
        if position is not None:
            self.entries[(anchor, part)] = position

    def error(self, code: str, msgid: str, node: ET.Element, /, **params: object) -> XmlIoError:
        line, column = self.positions.get(node, (None, None))
        return XmlIoError(code, msgid, source=self.source, line=line, column=column, **params)

    def warn(self, code: str, msgid: str, node: ET.Element, /, **params: object) -> None:
        line, column = self.positions.get(node, (None, None))
        self.warnings.append(
            XmlWarning(
                code=code, msgid=msgid, params=params, source=self.source, line=line, column=column
            )
        )

    # ------------------------------------------------ structure
    def raw(self, element: ET.Element) -> RawXml:
        return RawXml(xml=xmltree.serialise_fragment(element, namespaces=self.namespaces))

    def unexpected_text(self, element: ET.Element, local: str) -> XmlIoError:
        return self.error(
            "xml.unexpected_text",
            # Translators: {element} is an XML element name.
            N_("Text is not allowed directly inside <{element}>."),
            element,
            element=local,
        )

    def children(
        self, element: ET.Element, local: str, raws: list[RawXml]
    ) -> Iterator[tuple[ET.Element, str]]:
        """Yield the known children in document order; collect the others in ``raws``."""
        if not is_whitespace(element.text):
            raise self.unexpected_text(element, local)
        allowed = _ALLOWED[local]
        for child in element:
            uri, name = split_name(child.tag)
            if uri != NS_UI:
                raws.append(self.raw(child))
            elif name not in _VOCABULARY:
                self.warn(
                    "xml.unknown_element",
                    # Translators: {element} and {parent} are XML element names.
                    N_(
                        "Unknown element <{element}> inside <{parent}> is kept as it is; check "
                        "its spelling."
                    ),
                    child,
                    element=name,
                    parent=local,
                )
                raws.append(self.raw(child))
            elif name not in allowed:
                if not self.newer_minor:
                    raise self.error(
                        "xml.misplaced_element",
                        # Translators: {element} and {parent} are XML element names.
                        N_("<{element}> is not allowed inside <{parent}>."),
                        child,
                        element=name,
                        parent=local,
                    )
                self.warn(
                    "xml.misplaced_kept",
                    # Translators: {element} and {parent} are XML element names.
                    N_(
                        "<{element}> inside <{parent}> belongs to a newer schema and is kept as "
                        "it is."
                    ),
                    child,
                    element=name,
                    parent=local,
                )
                raws.append(self.raw(child))
            else:
                yield child, name
            if not is_whitespace(child.tail):
                raise self.unexpected_text(element, local)

    def duplicate(self, element: ET.Element, local: str, parent: str) -> XmlIoError:
        return self.error(
            "xml.duplicate_element",
            # Translators: {element} and {parent} are XML element names.
            N_("<{element}> appears more than once inside <{parent}>."),
            element,
            element=local,
            parent=parent,
        )

    # ------------------------------------------------ attributes
    def attrs(self, element: ET.Element, local: str) -> tuple[dict[str, str], dict[str, str]]:
        """Split the attributes into known ones and extras (warning for likely typos)."""
        names = _ATTRS[local]
        known: dict[str, str] = {}
        extras: dict[str, str] = {}
        for key, value in element.attrib.items():
            if key in names:
                known[key] = value
                continue
            extras[key] = value
            uri, _name = split_name(key)
            if (uri is None or uri == NS_UI) and not self.newer_minor:
                self.warn(
                    "xml.unknown_attribute",
                    # Translators: {attribute} is an XML attribute name, {element} an element.
                    N_(
                        "Unknown attribute '{attribute}' on <{element}> is kept as it is; check "
                        "its spelling."
                    ),
                    element,
                    attribute=key,
                    element=local,
                )
        return known, extras

    def required(self, element: ET.Element, local: str, attrs: Mapping[str, str], name: str) -> str:
        value = attrs.get(name)
        if value is None:
            raise self.error(
                "xml.missing_attribute",
                # Translators: {element} is an XML element name, {attribute} an attribute name.
                N_("The element <{element}> needs the attribute '{attribute}'."),
                element,
                element=local,
                attribute=name,
            )
        return value

    def to_int(self, element: ET.Element, local: str, name: str, value: str) -> int:
        if _INT_RE.fullmatch(value) is None:
            raise self.error(
                "xml.bad_int",
                # Translators: {attribute} is an attribute name, {element} an element name and
                # {value} the text found in the file.
                N_(
                    "The attribute '{attribute}' of <{element}> must be a whole number, "
                    "not '{value}'."
                ),
                element,
                attribute=name,
                element=local,
                value=value,
            )
        return int(value)

    def int_attr(
        self, element: ET.Element, local: str, attrs: Mapping[str, str], name: str, default: int
    ) -> int:
        value = attrs.get(name)
        return default if value is None else self.to_int(element, local, name, value)

    def opt_int(
        self, element: ET.Element, local: str, attrs: Mapping[str, str], name: str
    ) -> int | None:
        value = attrs.get(name)
        return None if value is None else self.to_int(element, local, name, value)

    def req_int(self, element: ET.Element, local: str, attrs: Mapping[str, str], name: str) -> int:
        return self.to_int(element, local, name, self.required(element, local, attrs, name))

    def bool_attr(
        self, element: ET.Element, local: str, attrs: Mapping[str, str], name: str
    ) -> bool:
        value = attrs.get(name)
        if value is None:
            return False
        if value not in ("true", "false"):
            raise self.error(
                "xml.bad_bool",
                # Translators: {attribute} is an attribute name, {element} an element name and
                # {value} the text found in the file; keep true and false untranslated.
                N_(
                    "The attribute '{attribute}' of <{element}> must be true or false, "
                    "not '{value}'."
                ),
                element,
                attribute=name,
                element=local,
                value=value,
            )
        return value == "true"

    def enum(
        self,
        element: ET.Element,
        local: str,
        attrs: Mapping[str, str],
        name: str,
        choices: Sequence[str],
        default: str | None,
    ) -> str:
        value = (
            self.required(element, local, attrs, name)
            if default is None
            else attrs.get(name, default)
        )
        if value not in choices:
            raise self.error(
                "xml.bad_enum",
                # Translators: {attribute} is an attribute name, {element} an element name,
                # {choices} a comma-separated list of allowed values and {value} the text found.
                N_(
                    "The attribute '{attribute}' of <{element}> must be one of {choices}, "
                    "not '{value}'."
                ),
                element,
                attribute=name,
                element=local,
                choices=", ".join(choices),
                value=value,
            )
        return value

    # ------------------------------------------------ elements
    def document(self, root: ET.Element, version: str) -> Document:
        _known, extras = self.attrs(root, _ROOT)
        document = Document(schema_version=version, namespaces=dict(self.namespaces))
        document.extra_attrs = extras
        self.record(document, "", root)
        seen: set[str] = set()
        raws: list[RawXml] = []
        for child, local in self.children(root, _ROOT, raws):
            if local != "window":
                if local in seen:
                    raise self.duplicate(child, local, _ROOT)
                seen.add(local)
            if local == "meta":
                document.meta = self.meta(child)
                self.record(document, "meta", child)
            elif local == "resources":
                document.resources, document.resources_extra = self.resources(child, document)
            elif local == "variables":
                document.variables, document.variables_extra = self.variables(child, document)
            else:
                document.add_window(self.window(child))
        document.extra_children = raws
        return document

    def meta(self, element: ET.Element) -> Meta:
        attrs, extras = self.attrs(element, "meta")
        raws: list[RawXml] = []
        for _child, _local in self.children(element, "meta", raws):
            pass  # pragma: no cover - <meta> has no known children
        meta = Meta(
            generator=attrs.get("generator", ""),
            i18n_domain=attrs.get("i18n_domain", ""),
            theme=attrs.get("theme", ""),
            extra_attrs=extras,
            extra_children=raws,
        )
        if "source_locale" in attrs:
            meta.source_locale = attrs["source_locale"]
        return meta

    def resources(
        self, element: ET.Element, owner: Document
    ) -> tuple[dict[str, ImageResource], ContainerExtras]:
        _known, extras = self.attrs(element, "resources")
        resources: dict[str, ImageResource] = {}
        raws: list[RawXml] = []
        for child, _local in self.children(element, "resources", raws):
            attrs, image_extras = self.attrs(child, "image")
            image_raws: list[RawXml] = []
            image = ImageResource(
                id=self.required(child, "image", attrs, "id"),
                src=self.required(child, "image", attrs, "src"),
                extra_attrs=image_extras,
                extra_children=self.leaf_children(child, "image", image_raws),
            )
            if image.id in resources:
                raise self.error(
                    "xml.duplicate_resource",
                    # Translators: {id} is an identifier from the file.
                    N_("The resource id '{id}' is declared more than once."),
                    child,
                    id=image.id,
                )
            resources[image.id] = image
            self.record(owner, f"resources/image[{image.id}]", child)
        return resources, ContainerExtras(extra_attrs=extras, extra_children=tuple(raws))

    def variables(
        self, element: ET.Element, owner: Document
    ) -> tuple[dict[str, Variable], ContainerExtras]:
        _known, extras = self.attrs(element, "variables")
        variables: dict[str, Variable] = {}
        raws: list[RawXml] = []
        for child, _local in self.children(element, "variables", raws):
            attrs, var_extras = self.attrs(child, "var")
            var_id = self.required(child, "var", attrs, "id")
            var_type = self.enum(child, "var", attrs, "type", _VAR_TYPES, None)
            variable = Variable(
                id=var_id,
                type=cast("Literal['string', 'int', 'double', 'bool']", var_type),
                default=attrs.get("default", ""),
                extra_attrs=var_extras,
                extra_children=self.leaf_children(child, "var", []),
            )
            if variable.id in variables:
                raise self.error(
                    "xml.duplicate_variable",
                    # Translators: {id} is an identifier from the file.
                    N_("The variable id '{id}' is declared more than once."),
                    child,
                    id=variable.id,
                )
            variables[variable.id] = variable
            self.record(owner, f"variables/var[{variable.id}]", child)
        return variables, ContainerExtras(extra_attrs=extras, extra_children=tuple(raws))

    def leaf_children(
        self, element: ET.Element, local: str, raws: list[RawXml]
    ) -> tuple[RawXml, ...]:
        """Children of an element without known children: all of them are kept raw."""
        for _child, _name in self.children(element, local, raws):
            pass  # pragma: no cover - leaf elements have no allowed known children
        return tuple(raws)

    def prop(self, element: ET.Element) -> Prop:
        attrs, extras = self.attrs(element, "prop")
        name = self.required(element, "prop", attrs, "name")
        if len(element):
            raise self.error(
                "xml.prop_has_children",
                # Translators: {name} is a property name.
                N_("The property '{name}' must contain plain text only, not elements."),
                element,
                name=name,
            )
        return Prop(
            name=name,
            value=element.text or "",
            ref=attrs.get("ref"),
            translatable=self.bool_attr(element, "prop", attrs, "translatable"),
            context=attrs.get("context"),
            comment=attrs.get("comment"),
            extra_attrs=extras,
        )

    def add_prop(
        self, props: dict[str, Prop], element: ET.Element, owner: str, node: object
    ) -> None:
        prop = self.prop(element)
        if prop.name in props:
            raise self.duplicate_prop(element, prop.name, owner)
        props[prop.name] = prop
        self.record(node, f"prop[{prop.name}]", element)

    def duplicate_prop(self, element: ET.Element, name: str, owner: str) -> XmlIoError:
        return self.error(
            "xml.duplicate_prop",
            # Translators: {name} is a property name, {element} an XML element name.
            N_("The property '{name}' is set more than once on <{element}>."),
            element,
            name=name,
            element=owner,
        )

    def window(self, element: ET.Element) -> Window:
        attrs, extras = self.attrs(element, "window")
        window = Window(
            id=self.required(element, "window", attrs, "id"),
            kind=cast(
                "Literal['main', 'dialog', 'component']",
                self.enum(element, "window", attrs, "kind", _KINDS, "main"),
            ),
            min_width=self.opt_int(element, "window", attrs, "min_width"),
            min_height=self.opt_int(element, "window", attrs, "min_height"),
            modal=self.bool_attr(element, "window", attrs, "modal"),
            buttons=attrs.get("buttons"),
            extra_attrs=extras,
        )
        self.record(window, "", element)
        raws: list[RawXml] = []
        for child, local in self.children(element, "window", raws):
            if local == "prop":
                self.add_prop(window.props, child, "window", window)
            elif local == "menubar":
                if window.menubar is not None:
                    raise self.duplicate(child, local, "window")
                window.menubar = self.menubar(child)
            elif local == "statusbar":
                if window.statusbar is not None:
                    raise self.duplicate(child, local, "window")
                window.statusbar = self.statusbar(child)
            elif local == "layout":
                if window.layout is not None:
                    raise self.duplicate(child, local, "window")
                window.layout = self.layout(child, window)
            elif local == "widget":
                window.append_child(self.widget(child))
            else:
                window.append_child(self.include(child))
        window.extra_children = raws
        return window

    def menubar(self, element: ET.Element) -> Menubar:
        _known, extras = self.attrs(element, "menubar")
        menubar = Menubar(extra_attrs=extras)
        self.record(menubar, "", element)
        raws: list[RawXml] = []
        for child, _local in self.children(element, "menubar", raws):
            menubar.append_child(self.menu(child))
        menubar.extra_children = raws
        return menubar

    def menu(self, element: ET.Element) -> Menu:
        attrs, extras = self.attrs(element, "menu")
        menu = Menu(id=self.required(element, "menu", attrs, "id"), extra_attrs=extras)
        self.record(menu, "", element)
        raws: list[RawXml] = []
        for child, local in self.children(element, "menu", raws):
            if local == "prop":
                self.add_prop(menu.props, child, "menu", menu)
            elif local == "menu":
                menu.append_child(self.menu(child))
            elif local == "action":
                menu.append_child(self.action(child))
            else:
                _known, separator_extras = self.attrs(child, "separator")
                separator = MenuSeparator(extra_attrs=separator_extras)
                self.record(separator, "", child)
                separator.extra_children = list(self.leaf_children(child, "separator", []))
                menu.append_child(separator)
        menu.extra_children = raws
        return menu

    def action(self, element: ET.Element) -> Action:
        attrs, extras = self.attrs(element, "action")
        action = Action(
            id=self.required(element, "action", attrs, "id"),
            handler=attrs.get("handler"),
            shortcut=attrs.get("shortcut"),
            extra_attrs=extras,
        )
        self.record(action, "", element)
        raws: list[RawXml] = []
        for child, _local in self.children(element, "action", raws):
            self.add_prop(action.props, child, "action", action)
        action.extra_children = raws
        return action

    def statusbar(self, element: ET.Element) -> Statusbar:
        attrs, extras = self.attrs(element, "statusbar")
        statusbar = Statusbar(
            id=self.required(element, "statusbar", attrs, "id"), extra_attrs=extras
        )
        self.record(statusbar, "", element)
        raws: list[RawXml] = []
        for child, _local in self.children(element, "statusbar", raws):
            self.add_prop(statusbar.props, child, "statusbar", statusbar)
        statusbar.extra_children = raws
        return statusbar

    def layout(self, element: ET.Element, owner: object) -> Layout:
        self.record(owner, "layout", element)
        attrs, extras = self.attrs(element, "layout")
        layout_type = self.enum(element, "layout", attrs, "type", _LAYOUT_TYPES, None)
        orient = self.enum(element, "layout", attrs, "orient", _ORIENTS, "vertical")
        padding = self.int_attr(element, "layout", attrs, "padding", 0)
        gap = self.int_attr(element, "layout", attrs, "gap", 0)
        columns: list[GridLine] = []
        rows: list[GridLine] = []
        raws: list[RawXml] = []
        for child, local in self.children(element, "layout", raws):
            line_attrs, line_extras = self.attrs(child, local)
            line = GridLine(
                index=self.req_int(child, local, line_attrs, "index"),
                weight=self.int_attr(child, local, line_attrs, "weight", 0),
                minsize=self.int_attr(child, local, line_attrs, "minsize", 0),
                extra_attrs=line_extras,
                extra_children=self.leaf_children(child, local, []),
            )
            lines = columns if local == "column" else rows
            self.record(owner, f"layout/{local}[{len(lines)}]", child)
            lines.append(line)
        return Layout(
            type=cast("Literal['grid', 'pack']", layout_type),
            orient=cast("Literal['vertical', 'horizontal']", orient),
            padding=padding,
            gap=gap,
            columns=tuple(columns),
            rows=tuple(rows),
            extra_children=tuple(raws),
            extra_attrs=extras,
        )

    def widget(self, element: ET.Element) -> Widget:
        attrs, extras = self.attrs(element, "widget")
        class_name = self.required(element, "widget", attrs, "class")
        try:
            split_class_name(class_name)
        except ModelError as exc:
            raise self.error(
                "xml.bad_class_name",
                # Translators: {name} is the class name found in the file.
                N_("'{name}' is not a valid widget class name."),
                element,
                name=class_name,
            ) from exc
        widget = Widget(
            class_name=class_name,
            id=self.required(element, "widget", attrs, "id"),
            bind=attrs.get("bind"),
            fallback=attrs.get("fallback"),
            plugin=attrs.get("plugin"),
            extra_attrs=extras,
        )
        self.record(widget, "", element)
        raws: list[RawXml] = []
        for child, local in self.children(element, "widget", raws):
            if local == "prop":
                self.add_prop(widget.props, child, "widget", widget)
            elif local == "event":
                self.record(widget, f"event[{len(widget.events)}]", child)
                widget.events.append(self.event(child))
            elif local in _PLACEMENTS:
                if widget.placement is not None:
                    raise self.duplicate_placement(child, "widget")
                widget.placement = self.placement(child, local, widget)
            elif local == "layout":
                if widget.layout is not None:
                    raise self.duplicate(child, local, "widget")
                widget.layout = self.layout(child, widget)
            elif local == "widget":
                widget.append_child(self.widget(child))
            else:
                widget.append_child(self.include(child))
        widget.extra_children = raws
        return widget

    def include(self, element: ET.Element) -> Include:
        attrs, extras = self.attrs(element, "include")
        include = Include(
            id=self.required(element, "include", attrs, "id"),
            src=self.required(element, "include", attrs, "src"),
            component=self.required(element, "include", attrs, "component"),
            extra_attrs=extras,
        )
        self.record(include, "", element)
        raws: list[RawXml] = []
        for child, local in self.children(element, "include", raws):
            if include.placement is not None:
                raise self.duplicate_placement(child, "include")
            include.placement = self.placement(child, local, include)
        include.extra_children = raws
        return include

    def duplicate_placement(self, element: ET.Element, owner: str) -> XmlIoError:
        return self.error(
            "xml.duplicate_placement",
            # Translators: {element} is an XML element name; keep <cell>, <pack> and <page>.
            N_("<{element}> has more than one placement (<cell>, <pack> or <page>)."),
            element,
            element=owner,
        )

    def event(self, element: ET.Element) -> Event:
        attrs, extras = self.attrs(element, "event")
        return Event(
            name=self.required(element, "event", attrs, "name"),
            handler=self.required(element, "event", attrs, "handler"),
            extra_attrs=extras,
            extra_children=self.leaf_children(element, "event", []),
        )

    def placement(self, element: ET.Element, local: str, owner: object) -> Placement:
        self.record(owner, local, element)
        attrs, extras = self.attrs(element, local)
        if local == "cell":
            return GridCell(
                row=self.req_int(element, local, attrs, "row"),
                column=self.req_int(element, local, attrs, "column"),
                rowspan=self.int_attr(element, local, attrs, "rowspan", 1),
                columnspan=self.int_attr(element, local, attrs, "columnspan", 1),
                sticky=attrs.get("sticky", ""),
                padx=self.int_attr(element, local, attrs, "padx", 0),
                pady=self.int_attr(element, local, attrs, "pady", 0),
                extra_attrs=extras,
                extra_children=self.leaf_children(element, local, []),
            )
        if local == "pack":
            fill = self.enum(element, local, attrs, "fill", _FILLS, "none")
            return PackPlacement(
                fill=cast("Literal['none', 'x', 'y', 'both']", fill),
                expand=self.bool_attr(element, local, attrs, "expand"),
                padx=self.int_attr(element, local, attrs, "padx", 0),
                pady=self.int_attr(element, local, attrs, "pady", 0),
                extra_attrs=extras,
                extra_children=self.leaf_children(element, local, []),
            )
        image = attrs.get("image")
        weight = self.int_attr(element, local, attrs, "weight", 0)
        text: Prop | None = None
        raws: list[RawXml] = []
        for child, _name in self.children(element, "page", raws):
            prop = self.prop(child)
            if text is not None:
                raise self.duplicate_prop(child, prop.name, "page")
            if prop.name != "text":
                raise self.error(
                    "xml.bad_page_prop",
                    # Translators: {name} is a property name; keep 'text' untranslated.
                    N_("A <page> can only hold the property 'text', not '{name}'."),
                    child,
                    name=prop.name,
                )
            text = prop
            self.record(owner, "page/prop[text]", child)
        return PagePlacement(
            text=text, image=image, weight=weight, extra_attrs=extras, extra_children=tuple(raws)
        )


# ---------------------------------------------------------------- writing
def dump_ui(document: Document) -> bytes:
    """Return the canonical bytes of ``document`` without changing it.

    Raises:
        XmlIoError: ``xml.read_only``, ``xml.write_bad_version`` or another write error
            (the document cannot be stored losslessly).
    """
    return _dump(document, _MEMORY)


def write_ui(document: Document, path: str | os.PathLike[str], *, backup: bool = True) -> None:
    """Save ``document`` atomically (temporary file + rename), keeping a ``.bak`` copy.

    Symbolic links are replaced, not followed.

    Raises:
        XmlIoError: a write error from :func:`dump_ui` (nothing touched) or
            ``xml.write_failed`` (the original file and any earlier backup stay intact).
    """
    source = os.fspath(path)
    data = _dump(document, source)
    target = Path(path)
    temporary: str | None = None
    copying: str | None = None
    try:
        if target.is_dir():
            raise IsADirectoryError(errno.EISDIR, os.strerror(errno.EISDIR), source)
        handle, temporary = create_temporary(target.parent)
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.name == "posix":  # pragma: no cover - exercised on POSIX CI only
            # Undo the temporary file's 0600 so the saved file keeps normal permissions.
            if target.exists():
                shutil.copymode(target, temporary)
            else:
                os.chmod(temporary, 0o644)
        if backup and target.exists():
            # Copy, never rename: the target must exist until the final replace. The copy is
            # made beside it first, so a failed copy (a full disk) keeps the earlier .bak whole.
            handle, copying = create_temporary(target.parent)
            os.close(handle)
            shutil.copy2(target, copying)
            _replace(copying, backup_path(target))
            copying = None
        _replace(temporary, target)
        temporary = None
        if os.name == "posix":  # pragma: no cover - exercised on POSIX CI only
            _fsync_directory(target.parent)
    except OSError as exc:
        for leftover in (temporary, copying):
            if leftover is not None:
                with contextlib.suppress(OSError):
                    os.remove(leftover)
        raise XmlIoError(
            "xml.write_failed",
            # Translators: {reason} is an error description from the operating system.
            N_("The file could not be saved: {reason}"),
            source=source,
            reason=exc.strerror or str(exc),
        ) from exc


def _replace(temporary: str, target: Path) -> None:
    # Windows antivirus or indexer processes may hold the target briefly.
    for attempt in range(_REPLACE_RETRIES + 1):
        try:
            os.replace(temporary, target)
        except PermissionError:
            if attempt == _REPLACE_RETRIES:
                raise
            time.sleep(_REPLACE_DELAY)
        else:
            return


def _fsync_directory(directory: Path) -> None:  # pragma: no cover - POSIX only
    with contextlib.suppress(OSError):
        handle = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(handle)
        finally:
            os.close(handle)


def _dump(document: Document, source: str) -> bytes:
    version: object = document.schema_version
    parsed = parse_version(version) if isinstance(version, str) else None
    current = cast("tuple[int, int]", parse_version(CURRENT_SCHEMA_VERSION))
    if parsed is not None and parsed > current:
        raise XmlIoError(
            "xml.read_only",
            # Translators: {version} and {current} are schema versions such as 1.1 and 1.0.
            N_(
                "This document uses schema version {version}, newer than {current}; it was "
                "opened read-only and cannot be saved."
            ),
            source=source,
            version=version,
            current=CURRENT_SCHEMA_VERSION,
        )
    if version != CURRENT_SCHEMA_VERSION:
        raise XmlIoError(
            "xml.write_bad_version",
            # Translators: {version} is the version stored in the document, {current} the
            # version this PyGUIbud writes.
            N_("The document's schema version '{version}' cannot be saved; expected {current}."),
            source=source,
            version=version,
            current=CURRENT_SCHEMA_VERSION,
        )
    builder = _Builder(source)
    root = builder.document(document)
    data = xmltree.serialise(
        root, namespaces=document.namespaces, known=builder.known, source=source
    )
    # The writer must never produce a file its own reader rejects.
    if len(data) > MAX_UI_BYTES:
        raise XmlIoError(
            "xml.too_large",
            N_("The file is larger than the limit of {limit} MiB for .ui files."),
            source=source,
            limit=MAX_UI_BYTES // (1024 * 1024),
        )
    return data


class _Builder:
    """Builds the output element tree from the model, checking every value on the way."""

    def __init__(self, source: str) -> None:
        self.source = source
        #: known element -> number of leading attributes already in schema order
        self.known: dict[ET.Element, int] = {}

    # ------------------------------------------------ value checks
    def bad_value(self, where: str, value: object) -> XmlIoError:
        return XmlIoError(
            "xml.write_bad_value",
            # Translators: {where} is a technical path such as window[main]@kind; {value} is
            # the offending value.
            N_("{where} has the value '{value}', which the .ui format cannot store."),
            source=self.source,
            where=where,
            value=value,
        )

    def text(self, value: object, where: str) -> str:
        if not isinstance(value, str):
            raise self.bad_value(where, value)
        xmltree.check_chars(value, where, source=self.source)
        return value

    def opt_text(self, value: object, where: str, omit: str | None = None) -> str | None:
        return None if value is None or value == omit else self.text(value, where)

    def req_integer(self, value: object, where: str) -> str:
        # ``type(...) is int`` also refuses bool, which is an int subclass.
        if type(value) is not int or not -_INT_LIMIT <= value <= _INT_LIMIT:
            raise self.bad_value(where, value)
        return str(value)

    def integer(self, value: object, where: str, omit: int | None = None) -> str | None:
        if value is None and omit is None:
            return None
        text = self.req_integer(value, where)
        return None if value == omit else text

    def boolean(self, value: object, where: str) -> str | None:
        if not isinstance(value, bool):
            raise self.bad_value(where, value)
        return "true" if value else None

    def choice(
        self, value: object, choices: Sequence[str], where: str, omit: str | None = None
    ) -> str | None:
        if not isinstance(value, str) or value not in choices:
            raise self.bad_value(where, value)
        return None if value == omit else value

    def key_matches(self, key: str, name: object, where: str) -> None:
        if key != name:
            raise XmlIoError(
                "xml.write_key_mismatch",
                # Translators: {where} is a technical path; {key} and {name} are identifiers.
                N_("{where}: the key '{key}' does not match the name '{name}'."),
                source=self.source,
                where=where,
                key=key,
                name=name,
            )

    # ------------------------------------------------ elements
    def element(
        self,
        parent: ET.Element | None,
        local: str,
        where: str,
        depth: int,
        known: Sequence[tuple[str, str | None]],
        extras: Mapping[str, str],
    ) -> ET.Element:
        if depth > MAX_DEPTH:
            raise XmlIoError(
                "xml.too_deep",
                N_("Elements are nested more than {limit} levels deep."),
                source=self.source,
                limit=MAX_DEPTH,
            )
        attrib = {name: value for name, value in known if value is not None}
        names = _ATTRS[local]
        for key in sorted(extras):
            key_where = f"{where}@{key}"
            xmltree.check_attribute_key(key, key_where, source=self.source)
            if key in names:
                raise XmlIoError(
                    "xml.write_bad_name",
                    # Translators: {name} is an XML attribute name; {where} is a technical path.
                    N_("'{name}' is not a valid attribute name here ({where})."),
                    source=self.source,
                    name=key,
                    where=key_where,
                )
            attrib[key] = self.text(extras[key], key_where)
        tag = f"{{{NS_UI}}}{local}"
        element = ET.Element(tag, attrib) if parent is None else ET.SubElement(parent, tag, attrib)
        self.known[element] = sum(1 for _name, value in known if value is not None)
        return element

    def raws(self, parent: ET.Element, raws: Iterable[RawXml], where: str, depth: int) -> None:
        """Splice preserved content after the known children of ``parent`` (at ``depth``)."""
        for raw in raws:
            if raw.extra_attrs:
                raise self.bad_raw(where, LazyMessage(N_("RawXml.extra_attrs must be empty")))
            try:
                fragment = xmltree.parse_fragment(raw.xml)
            except XmlIoError as exc:
                raise self.bad_raw(where, exc.params.get("detail", "")) from exc
            uri, local = split_name(fragment.tag)
            if uri == NS_UI and local in _VOCABULARY:
                raise self.bad_raw(
                    where,
                    LazyMessage(
                        # Translators: {element} is an XML element name.
                        N_("<{element}> is a .ui element and cannot be kept as preserved XML"),
                        element=local,
                    ),
                )
            if depth + xmltree.subtree_depth(fragment) > MAX_DEPTH:
                raise XmlIoError(
                    "xml.too_deep",
                    N_("Elements are nested more than {limit} levels deep."),
                    source=self.source,
                    limit=MAX_DEPTH,
                )
            parent.append(fragment)

    def bad_raw(self, where: str, detail: object) -> XmlIoError:
        return XmlIoError(
            "xml.write_bad_raw",
            N_("Preserved XML content of {where} is damaged: {detail}"),
            source=self.source,
            where=where,
            detail=detail,
        )

    def document(self, document: Document) -> ET.Element:
        where = _ROOT
        root = self.element(
            None,
            _ROOT,
            where,
            1,
            [("schema_version", CURRENT_SCHEMA_VERSION)],
            document.extra_attrs,
        )
        self.meta(root, document.meta)
        if document.resources or _has_extras(document.resources_extra):
            self.resources(root, document)
        if document.variables or _has_extras(document.variables_extra):
            self.variables(root, document)
        for window in document.children:
            self.window(root, window)
        self.raws(root, document.extra_children, where, 1)
        return root

    def meta(self, parent: ET.Element, meta: Meta) -> None:
        where = "meta"
        element = self.element(
            parent,
            "meta",
            where,
            2,
            [
                ("generator", self.opt_text(meta.generator, f"{where}@generator", "")),
                ("source_locale", self.text(meta.source_locale, f"{where}@source_locale")),
                ("i18n_domain", self.opt_text(meta.i18n_domain, f"{where}@i18n_domain", "")),
                ("theme", self.opt_text(meta.theme, f"{where}@theme", "")),
            ],
            meta.extra_attrs,
        )
        self.raws(element, meta.extra_children, where, 2)

    def resources(self, parent: ET.Element, document: Document) -> None:
        where = "resources"
        extras = document.resources_extra
        element = self.element(parent, "resources", where, 2, [], extras.extra_attrs)
        for key, image in document.resources.items():
            image_where = f"{where}/image[{key}]"
            self.key_matches(key, image.id, image_where)
            child = self.element(
                element,
                "image",
                image_where,
                3,
                [
                    ("id", self.text(image.id, f"{image_where}@id")),
                    ("src", self.text(image.src, f"{image_where}@src")),
                ],
                image.extra_attrs,
            )
            self.raws(child, image.extra_children, image_where, 3)
        self.raws(element, extras.extra_children, where, 2)

    def variables(self, parent: ET.Element, document: Document) -> None:
        where = "variables"
        extras = document.variables_extra
        element = self.element(parent, "variables", where, 2, [], extras.extra_attrs)
        for key, variable in document.variables.items():
            var_where = f"{where}/var[{key}]"
            self.key_matches(key, variable.id, var_where)
            child = self.element(
                element,
                "var",
                var_where,
                3,
                [
                    ("id", self.text(variable.id, f"{var_where}@id")),
                    ("type", self.choice(variable.type, _VAR_TYPES, f"{var_where}@type")),
                    ("default", self.opt_text(variable.default, f"{var_where}@default", "")),
                ],
                variable.extra_attrs,
            )
            self.raws(child, variable.extra_children, var_where, 3)
        self.raws(element, extras.extra_children, where, 2)

    def props(self, parent: ET.Element, props: Mapping[str, Prop], owner: str, depth: int) -> None:
        for key in sorted(props):
            prop = props[key]
            where = f"{owner}/prop[{key}]"
            self.key_matches(key, prop.name, where)
            self.prop(parent, prop, where, depth)

    def prop(self, parent: ET.Element, prop: Prop, where: str, depth: int) -> None:
        element = self.element(
            parent,
            "prop",
            where,
            depth,
            [
                ("name", self.text(prop.name, f"{where}@name")),
                ("ref", self.opt_text(prop.ref, f"{where}@ref")),
                ("translatable", self.boolean(prop.translatable, f"{where}@translatable")),
                ("context", self.opt_text(prop.context, f"{where}@context")),
                ("comment", self.opt_text(prop.comment, f"{where}@comment")),
            ],
            prop.extra_attrs,
        )
        element.text = self.text(prop.value, where) or None

    def window(self, parent: ET.Element, window: Window) -> None:
        where = f"window[{window.id}]"
        element = self.element(
            parent,
            "window",
            where,
            2,
            [
                ("id", self.text(window.id, f"{where}@id")),
                ("kind", self.choice(window.kind, _KINDS, f"{where}@kind")),
                ("min_width", self.integer(window.min_width, f"{where}@min_width")),
                ("min_height", self.integer(window.min_height, f"{where}@min_height")),
                ("modal", self.boolean(window.modal, f"{where}@modal")),
                ("buttons", self.opt_text(window.buttons, f"{where}@buttons")),
            ],
            window.extra_attrs,
        )
        self.props(element, window.props, where, 3)
        if window.menubar is not None:
            self.menubar(element, window.menubar, f"{where}/menubar", 3)
        if window.statusbar is not None:
            self.statusbar(element, window.statusbar, where, 3)
        if window.layout is not None:
            self.layout(element, window.layout, f"{where}/layout", 3)
        self.child_nodes(element, window.children, where, 3)
        self.raws(element, window.extra_children, where, 2)

    def child_nodes(
        self, parent: ET.Element, nodes: Iterable[Widget | Include], owner: str, depth: int
    ) -> None:
        for node in nodes:
            if isinstance(node, Widget):
                self.widget(parent, node, owner, depth)
            else:
                self.include(parent, node, owner, depth)

    def menubar(self, parent: ET.Element, menubar: Menubar, where: str, depth: int) -> None:
        element = self.element(parent, "menubar", where, depth, [], menubar.extra_attrs)
        for menu in menubar.children:
            self.menu(element, menu, where, depth + 1)
        self.raws(element, menubar.extra_children, where, depth)

    def menu(self, parent: ET.Element, menu: Menu, owner: str, depth: int) -> None:
        where = f"{owner}/menu[{menu.id}]"
        element = self.element(
            parent,
            "menu",
            where,
            depth,
            [("id", self.text(menu.id, f"{where}@id"))],
            menu.extra_attrs,
        )
        self.props(element, menu.props, where, depth + 1)
        for entry in menu.children:
            if isinstance(entry, Menu):
                self.menu(element, entry, where, depth + 1)
            elif isinstance(entry, Action):
                self.action(element, entry, where, depth + 1)
            else:
                separator_where = f"{where}/separator"
                child = self.element(
                    element, "separator", separator_where, depth + 1, [], entry.extra_attrs
                )
                self.raws(child, entry.extra_children, separator_where, depth + 1)
        self.raws(element, menu.extra_children, where, depth)

    def action(self, parent: ET.Element, action: Action, owner: str, depth: int) -> None:
        where = f"{owner}/action[{action.id}]"
        element = self.element(
            parent,
            "action",
            where,
            depth,
            [
                ("id", self.text(action.id, f"{where}@id")),
                ("handler", self.opt_text(action.handler, f"{where}@handler")),
                ("shortcut", self.opt_text(action.shortcut, f"{where}@shortcut")),
            ],
            action.extra_attrs,
        )
        self.props(element, action.props, where, depth + 1)
        self.raws(element, action.extra_children, where, depth)

    def statusbar(self, parent: ET.Element, statusbar: Statusbar, owner: str, depth: int) -> None:
        where = f"{owner}/statusbar[{statusbar.id}]"
        element = self.element(
            parent,
            "statusbar",
            where,
            depth,
            [("id", self.text(statusbar.id, f"{where}@id"))],
            statusbar.extra_attrs,
        )
        self.props(element, statusbar.props, where, depth + 1)
        self.raws(element, statusbar.extra_children, where, depth)

    def layout(self, parent: ET.Element, layout: Layout, where: str, depth: int) -> None:
        element = self.element(
            parent,
            "layout",
            where,
            depth,
            [
                ("type", self.choice(layout.type, _LAYOUT_TYPES, f"{where}@type")),
                ("orient", self.choice(layout.orient, _ORIENTS, f"{where}@orient", "vertical")),
                ("padding", self.integer(layout.padding, f"{where}@padding", 0)),
                ("gap", self.integer(layout.gap, f"{where}@gap", 0)),
            ],
            layout.extra_attrs,
        )
        for local, lines in (("column", layout.columns), ("row", layout.rows)):
            for line in lines:
                line_where = f"{where}/{local}[{line.index}]"
                child = self.element(
                    element,
                    local,
                    line_where,
                    depth + 1,
                    [
                        ("index", self.req_integer(line.index, f"{line_where}@index")),
                        ("weight", self.integer(line.weight, f"{line_where}@weight", 0)),
                        ("minsize", self.integer(line.minsize, f"{line_where}@minsize", 0)),
                    ],
                    line.extra_attrs,
                )
                self.raws(child, line.extra_children, line_where, depth + 1)
        self.raws(element, layout.extra_children, where, depth)

    def widget(self, parent: ET.Element, widget: Widget, owner: str, depth: int) -> None:
        where = f"{owner}/widget[{widget.id}]"
        class_name = self.text(widget.class_name, f"{where}@class")
        try:
            split_class_name(class_name)
        except ModelError as exc:
            raise XmlIoError(
                "xml.bad_class_name",
                N_("'{name}' is not a valid widget class name."),
                source=self.source,
                name=class_name,
            ) from exc
        element = self.element(
            parent,
            "widget",
            where,
            depth,
            [
                ("class", class_name),
                ("id", self.text(widget.id, f"{where}@id")),
                ("bind", self.opt_text(widget.bind, f"{where}@bind")),
                ("fallback", self.opt_text(widget.fallback, f"{where}@fallback")),
                ("plugin", self.opt_text(widget.plugin, f"{where}@plugin")),
            ],
            widget.extra_attrs,
        )
        self.props(element, widget.props, where, depth + 1)
        for event in widget.events:
            event_where = f"{where}/event[{event.name}]"
            child = self.element(
                element,
                "event",
                event_where,
                depth + 1,
                [
                    ("name", self.text(event.name, f"{event_where}@name")),
                    ("handler", self.text(event.handler, f"{event_where}@handler")),
                ],
                event.extra_attrs,
            )
            self.raws(child, event.extra_children, event_where, depth + 1)
        if widget.placement is not None:
            self.placement(element, widget.placement, where, depth + 1)
        if widget.layout is not None:
            self.layout(element, widget.layout, f"{where}/layout", depth + 1)
        self.child_nodes(element, widget.children, where, depth + 1)
        self.raws(element, widget.extra_children, where, depth)

    def include(self, parent: ET.Element, include: Include, owner: str, depth: int) -> None:
        where = f"{owner}/include[{include.id}]"
        element = self.element(
            parent,
            "include",
            where,
            depth,
            [
                ("id", self.text(include.id, f"{where}@id")),
                ("src", self.text(include.src, f"{where}@src")),
                ("component", self.text(include.component, f"{where}@component")),
            ],
            include.extra_attrs,
        )
        if include.placement is not None:
            self.placement(element, include.placement, where, depth + 1)
        self.raws(element, include.extra_children, where, depth)

    def placement(self, parent: ET.Element, placement: object, owner: str, depth: int) -> None:
        if isinstance(placement, GridCell):
            where = f"{owner}/cell"
            element = self.element(
                parent,
                "cell",
                where,
                depth,
                [
                    ("row", self.req_integer(placement.row, f"{where}@row")),
                    ("column", self.req_integer(placement.column, f"{where}@column")),
                    ("rowspan", self.integer(placement.rowspan, f"{where}@rowspan", 1)),
                    ("columnspan", self.integer(placement.columnspan, f"{where}@columnspan", 1)),
                    ("sticky", self.opt_text(placement.sticky, f"{where}@sticky", "")),
                    ("padx", self.integer(placement.padx, f"{where}@padx", 0)),
                    ("pady", self.integer(placement.pady, f"{where}@pady", 0)),
                ],
                placement.extra_attrs,
            )
        elif isinstance(placement, PackPlacement):
            where = f"{owner}/pack"
            element = self.element(
                parent,
                "pack",
                where,
                depth,
                [
                    ("fill", self.choice(placement.fill, _FILLS, f"{where}@fill", "none")),
                    ("expand", self.boolean(placement.expand, f"{where}@expand")),
                    ("padx", self.integer(placement.padx, f"{where}@padx", 0)),
                    ("pady", self.integer(placement.pady, f"{where}@pady", 0)),
                ],
                placement.extra_attrs,
            )
        elif isinstance(placement, PagePlacement):
            where = f"{owner}/page"
            element = self.element(
                parent,
                "page",
                where,
                depth,
                [
                    ("image", self.opt_text(placement.image, f"{where}@image")),
                    ("weight", self.integer(placement.weight, f"{where}@weight", 0)),
                ],
                placement.extra_attrs,
            )
            if placement.text is not None:
                text_where = f"{where}/prop[text]"
                if placement.text.name != "text":
                    raise self.bad_value(f"{text_where}@name", placement.text.name)
                self.prop(element, placement.text, text_where, depth + 1)
        else:
            raise self.bad_value(f"{owner}/placement", placement)
        self.raws(element, placement.extra_children, where, depth)


def _has_extras(extras: ContainerExtras) -> bool:
    return bool(extras.extra_attrs or extras.extra_children)
