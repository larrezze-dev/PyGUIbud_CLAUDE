"""Hardened XML parsing and canonical serialisation for ``.ui`` files (stdlib only).

The parser is expat with every DTD feature refused; it builds plain
:class:`xml.etree.ElementTree.Element` trees with Clark names (``{uri}local``). The serialiser
writes the deterministic form of ADR-002: 2-space indent, ``\\n`` line ends, fixed attribute
order and namespace prefixes assigned by :func:`assign_prefixes`. This module knows nothing about
the document model beyond :data:`NS_UI` and :data:`KNOWN_NAMESPACES`.

``ElementTree`` is used for the ``Element`` type only; its parsers and serialisers are never
called (they are neither hardened nor deterministic enough).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final
from xml.parsers import expat

from pyguibud.core.errors import XmlIoError, format_message
from pyguibud.core.model import KNOWN_NAMESPACES, NS_UI
from pyguibud.i18n import N_

__all__ = [
    "MAX_DEPTH",
    "NS_XML",
    "NS_XMLNS",
    "LazyMessage",
    "ParsedTree",
    "assign_prefixes",
    "check_attribute_key",
    "check_chars",
    "check_namespaces",
    "display_name",
    "effective_namespaces",
    "first_illegal_char",
    "is_ncname",
    "is_whitespace",
    "parse",
    "parse_fragment",
    "serialise",
    "serialise_fragment",
    "split_name",
    "subtree_depth",
]

#: Maximum element nesting; keeps every recursive walk far below the recursion limit.
MAX_DEPTH: Final = 100

NS_XML: Final = "http://www.w3.org/XML/1998/namespace"
NS_XMLNS: Final = "http://www.w3.org/2000/xmlns/"

_INDENT: Final = "  "
_WHITESPACE: Final = " \t\n\r"
_NCNAME_RE: Final = re.compile(r"[^\W\d][\w.\-]*")
_ILLEGAL_CHAR_RE: Final = re.compile("[^\x09\x0a\x0d\x20-퟿-�\U00010000-\U0010ffff]")
_TEXT_ESCAPES: Final = str.maketrans({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\r": "&#13;"})
_ATTR_ESCAPES: Final = str.maketrans(
    {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "\n": "&#10;",
        "\t": "&#9;",
        "\r": "&#13;",
    }
)


class LazyMessage:
    """A message placeholder value that is translated when it is formatted, not when created."""

    __slots__ = ("msgid", "params")

    def __init__(self, msgid: str, /, **params: object) -> None:
        self.msgid = msgid
        self.params = params

    def __str__(self) -> str:
        return format_message(self.msgid, self.params)

    def __repr__(self) -> str:
        return f"LazyMessage({self.msgid!r})"


# ---------------------------------------------------------------- names and characters
def is_whitespace(text: str | None) -> bool:
    """True for None, ``""`` or text made only of XML whitespace (never ``str.isspace``)."""
    return text is None or not text.strip(_WHITESPACE)


def split_name(name: str) -> tuple[str | None, str]:
    """Split a Clark name ``{uri}local`` into ``(uri, local)``; a plain name has no uri."""
    if name.startswith("{"):
        uri, _sep, local = name[1:].rpartition("}")
        return uri, local
    return None, name


def display_name(tag: str) -> str:
    """The ``{element}`` placeholder value: the local name in ``NS_UI``, else the Clark name."""
    uri, local = split_name(tag)
    return local if uri == NS_UI else tag


@lru_cache(maxsize=1024)
def _expat_accepts_name(name: str) -> bool:
    # The regex of the spec is broader than XML's name rules (``\\w`` accepts characters such
    # as U+00B2); asking expat itself guarantees that the reader accepts what the writer emits.
    parser = expat.ParserCreate(encoding="UTF-8")
    try:
        parser.Parse(f"<{name}/>".encode(), True)
    except expat.ExpatError:
        return False
    return True


def is_ncname(name: str) -> bool:
    """True for an XML name without a colon (``NCName``)."""
    return _NCNAME_RE.fullmatch(name) is not None and _expat_accepts_name(name)


def first_illegal_char(text: str) -> str | None:
    """Return the first character of ``text`` that XML 1.0 cannot store, or None."""
    match = _ILLEGAL_CHAR_RE.search(text)
    return None if match is None else match.group()


def check_chars(text: str, where: str, *, source: str = "") -> None:
    """Raise ``xml.illegal_char`` if ``text`` contains a character XML 1.0 cannot store."""
    illegal = first_illegal_char(text)
    if illegal is not None:
        raise XmlIoError(
            "xml.illegal_char",
            # Translators: {where} is a technical path such as window[main]/widget[btn]@text;
            # {codepoint} is a hexadecimal character code such as 0001.
            N_("{where} contains the character U+{codepoint}, which XML cannot store."),
            source=source,
            where=where,
            codepoint=f"{ord(illegal):04X}",
        )


def _bad_name(name: str, where: str, source: str) -> XmlIoError:
    return XmlIoError(
        "xml.write_bad_name",
        # Translators: {name} is an XML attribute name; {where} is a technical path.
        N_("'{name}' is not a valid attribute name here ({where})."),
        source=source,
        name=name,
        where=where,
    )


def check_attribute_key(key: str, where: str, *, source: str = "") -> None:
    """Raise ``xml.write_bad_name`` unless ``key`` is a plain NCName or ``{uri}NCName``."""
    check_chars(key, where, source=source)
    uri, local = split_name(key)
    if key.startswith("xmlns") or uri == NS_XMLNS or uri == "" or not is_ncname(local):
        raise _bad_name(key, where, source)


def check_namespaces(namespaces: Mapping[str, str], *, source: str = "") -> None:
    """Raise ``xml.write_bad_namespace`` for a declaration the writer cannot emit.

    The default namespace entry (``""``) is ignored: the root always declares ``NS_UI``.
    """
    for prefix, uri in namespaces.items():
        if prefix == "":
            continue
        check_chars(prefix, f"xmlns:{prefix}", source=source)
        check_chars(uri, f"xmlns:{prefix}", source=source)
        if (
            prefix in ("xml", "xmlns")
            or not is_ncname(prefix)
            or not uri
            or uri in (NS_XML, NS_XMLNS)
        ):
            raise XmlIoError(
                "xml.write_bad_namespace",
                # Translators: {prefix} is an XML namespace prefix, {uri} its namespace URI.
                N_("The namespace declaration '{prefix}' = '{uri}' is not valid."),
                source=source,
                prefix=prefix,
                uri=uri,
            )


# ---------------------------------------------------------------- parser
@dataclass(frozen=True, slots=True)
class ParsedTree:
    """Result of :func:`parse`."""

    root: ET.Element
    positions: Mapping[ET.Element, tuple[int, int]]
    namespaces: Mapping[str, str]
    discarded: int
    #: A bound prefix declared again for another namespace (the first per prefix): the first
    #: declaration still wins; these are only reported (QA-19b-06).
    rebound: Mapping[str, str]


class _TreeBuilder:
    """Expat handlers that build an element tree and enforce the hardening rules."""

    def __init__(
        self,
        source: str,
        check_declared_encoding: bool,
        root_check: Callable[[str], None] | None,
    ) -> None:
        self.source = source
        self.check_declared_encoding = check_declared_encoding
        self.root_check = root_check
        self.parser = expat.ParserCreate(encoding="UTF-8", namespace_separator="}")
        self.stack: list[ET.Element] = []
        self.root: ET.Element | None = None
        self.positions: dict[ET.Element, tuple[int, int]] = {}
        self.namespaces: dict[str, str] = {}
        self.rebound: dict[str, str] = {}
        self.discarded = 0

        parser = self.parser
        parser.buffer_text = True
        parser.ordered_attributes = False
        parser.specified_attributes = True
        parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.data
        parser.StartNamespaceDeclHandler = self.namespace
        parser.CommentHandler = self.discard
        parser.ProcessingInstructionHandler = self.discard
        parser.XmlDeclHandler = self.xml_decl
        parser.StartDoctypeDeclHandler = self.forbidden
        parser.EntityDeclHandler = self.forbidden
        parser.UnparsedEntityDeclHandler = self.forbidden
        parser.NotationDeclHandler = self.forbidden
        parser.ExternalEntityRefHandler = self.forbidden

    def position(self) -> tuple[int, int]:
        return self.parser.CurrentLineNumber, self.parser.CurrentColumnNumber + 1

    def error(self, code: str, message: str, **params: object) -> XmlIoError:
        line, column = self.position()
        return XmlIoError(code, message, source=self.source, line=line, column=column, **params)

    @staticmethod
    def clark(name: str) -> str:
        uri, sep, local = name.rpartition("}")
        return f"{{{uri}}}{local}" if sep else name

    def start(self, name: str, attrs: dict[str, str]) -> None:
        depth = len(self.stack) + 1
        if depth > MAX_DEPTH:
            raise self.error(
                "xml.too_deep",
                # Translators: {limit} is a number of nesting levels.
                N_("Elements are nested more than {limit} levels deep."),
                limit=MAX_DEPTH,
            )
        tag = self.clark(name)
        position = self.position()
        if depth == 1 and self.root_check is not None:
            try:
                self.root_check(tag)
            except XmlIoError as exc:
                if exc.line is None:
                    exc.line, exc.column = position
                exc.source = exc.source or self.source
                raise
        if not tag.startswith("{"):
            raise self.error(
                "xml.no_namespace_element",
                # Translators: {element} is an XML element name; {attribute} is the literal XML
                # attribute to remove; keep it unchanged.
                N_("The element <{element}> has no namespace; remove {attribute} from the file."),
                element=tag,
                attribute='xmlns=""',
            )
        element = ET.Element(tag, {self.clark(key): value for key, value in attrs.items()})
        self.positions[element] = position
        if self.stack:
            self.stack[-1].append(element)
        else:
            self.root = element
        self.stack.append(element)

    def end(self, name: str) -> None:
        self.stack.pop()

    def data(self, text: str) -> None:
        if not self.stack:
            return  # only whitespace can occur outside the root element
        current = self.stack[-1]
        if len(current):
            last = current[-1]
            last.tail = (last.tail or "") + text
        else:
            current.text = (current.text or "") + text

    def namespace(self, prefix: str | None, uri: str | None) -> None:
        prefix = prefix or ""
        if not prefix or not uri or uri in (NS_UI, NS_XML):
            return
        if self.namespaces.get(prefix, uri) != uri:
            self.rebound.setdefault(prefix, uri)
        if prefix in self.namespaces or uri in self.namespaces.values():
            return  # first declaration wins
        self.namespaces[prefix] = uri

    def discard(self, *args: object) -> None:
        self.discarded += 1

    def xml_decl(self, version: str | None, encoding: str | None, standalone: int) -> None:
        if (
            self.check_declared_encoding
            and encoding is not None
            and encoding.lower() not in ("utf-8", "utf8")
        ):
            raise self.error(
                "xml.bad_encoding",
                # Translators: {encoding} is an encoding name such as ISO-8859-1.
                N_("The file declares the encoding '{encoding}'; only UTF-8 is supported."),
                encoding=encoding,
            )

    def forbidden(self, *args: object) -> int:
        raise self.error(
            "xml.doctype_forbidden",
            N_("DOCTYPE and entity declarations are not allowed in .ui files."),
        )

    def run(self, data: bytes) -> ParsedTree:
        try:
            self.parser.Parse(data, True)
        except expat.ExpatError as exc:
            raise XmlIoError(
                "xml.malformed",
                # Translators: {detail} is an English description from the XML parser.
                N_("The file is not well-formed XML: {detail}"),
                source=self.source,
                line=exc.lineno,
                column=exc.offset + 1,
                detail=expat.ErrorString(exc.code),
            ) from exc
        if self.root is None:  # pragma: no cover - expat reports "no element found" first
            raise XmlIoError(
                "xml.malformed",
                N_("The file is not well-formed XML: {detail}"),
                source=self.source,
                detail="no element found",
            )
        return ParsedTree(
            self.root, self.positions, dict(self.namespaces), self.discarded, dict(self.rebound)
        )


def parse(
    data: bytes,
    *,
    source: str,
    check_declared_encoding: bool,
    root_check: Callable[[str], None] | None = None,
) -> ParsedTree:
    """Parse UTF-8 ``data`` (BOM already stripped) with every DTD feature refused.

    Raises:
        XmlIoError: ``xml.malformed``, ``xml.doctype_forbidden``, ``xml.too_deep``,
            ``xml.no_namespace_element``, ``xml.bad_encoding`` or whatever ``root_check`` raises.
    """
    return _TreeBuilder(source, check_declared_encoding, root_check).run(data)


def _bad_raw(where: str, detail: object) -> XmlIoError:
    return XmlIoError(
        "xml.write_bad_raw",
        # Translators: {where} is a technical path; {detail} explains the damage.
        N_("Preserved XML content of {where} is damaged: {detail}"),
        where=where,
        detail=detail,
    )


def parse_fragment(xml: str) -> ET.Element:
    """Parse the ``xml`` of a :class:`~pyguibud.core.model.RawXml` (exactly one element).

    Raises:
        XmlIoError: ``xml.write_bad_raw`` (its ``where`` is ``"RawXml"``; callers that know the
            owner re-raise with a model path).
    """
    try:
        data = xml.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise _bad_raw("RawXml", LazyMessage(N_("it is not valid Unicode text"))) from exc
    try:
        tree = parse(data, source="", check_declared_encoding=True)
    except XmlIoError as exc:
        raise _bad_raw("RawXml", LazyMessage(exc.msgid, **exc.params)) from exc
    if tree.discarded:
        raise _bad_raw("RawXml", LazyMessage(N_("it contains comments or processing instructions")))
    return tree.root


def subtree_depth(element: ET.Element) -> int:
    """Number of element levels in ``element``'s subtree (1 for a childless element)."""
    deepest = 0
    pending: list[tuple[ET.Element, int]] = [(element, 1)]
    while pending:
        current, depth = pending.pop()
        deepest = max(deepest, depth)
        pending.extend((child, depth + 1) for child in current)
    return deepest


# ---------------------------------------------------------------- prefixes
def effective_namespaces(namespaces: Mapping[str, str]) -> dict[str, str]:
    """The part of ``namespaces`` the writer uses: what the reader can hoist back (spec §7).

    The default entry and prefixes bound to ``NS_UI`` are dropped (the reader skips them), and
    each URI keeps only its smallest prefix in code-point order (the reader keeps one per URI).
    Prefix choices therefore never depend on entries that a re-read would lose, which keeps a
    second save byte-identical. Entries are returned sorted by prefix. A known prefix bound to
    another URI (``xmlns:tb="urn:evil"``) is dropped, so that URI gets a generated prefix and
    ``tb`` always means ttkbootstrap (ADR-002 Addendum B).
    """
    winners: dict[str, str] = {}
    for prefix in sorted(namespaces):
        uri = namespaces[prefix]
        if KNOWN_NAMESPACES.get(prefix, uri) != uri:
            continue
        if prefix and uri != NS_UI and uri not in winners:
            winners[uri] = prefix
    return {prefix: uri for uri, prefix in sorted(winners.items(), key=lambda item: item[1])}


def assign_prefixes(namespaces: Mapping[str, str], uris_in_order: Iterable[str]) -> dict[str, str]:
    """Map every namespace URI used by the output (in first-use order) to its prefix.

    ``NS_UI`` *elements* use the default namespace and must not be passed here; ``NS_UI``
    attributes need a prefix like any other URI, but never one bound to ``NS_UI`` in
    ``namespaces``. Only :func:`effective_namespaces` of ``namespaces`` is taken into account.
    """
    namespaces = effective_namespaces(namespaces)
    result: dict[str, str] = {}
    generated: set[str] = set()

    def free(prefix: str) -> bool:
        return prefix not in namespaces and prefix not in generated

    for uri in uris_in_order:
        if uri in result:
            continue
        if uri == NS_XML:
            result[uri] = "xml"
            continue
        declared = next((p for p, u in namespaces.items() if u == uri), None)
        if declared is not None:
            result[uri] = declared
            continue
        known = next((p for p, u in KNOWN_NAMESPACES.items() if u == uri), None)
        if known is not None and free(known):
            prefix = known
        else:
            number = 1
            while not free(f"ns{number}"):
                number += 1
            prefix = f"ns{number}"
        generated.add(prefix)
        result[uri] = prefix
    return result


# ---------------------------------------------------------------- serialiser
def _escape_text(text: str) -> str:
    return text.translate(_TEXT_ESCAPES)


def _escape_attr(text: str) -> str:
    return text.translate(_ATTR_ESCAPES)


class _Serialiser:
    def __init__(self, prefixes: Mapping[str, str], known: Mapping[ET.Element, int]) -> None:
        self.prefixes = prefixes
        self.known = known

    def qname(self, name: str, *, attribute: bool) -> str:
        uri, local = split_name(name)
        if uri is None or (uri == NS_UI and not attribute):
            return local
        return f"{self.prefixes[uri]}:{local}"

    def ordered_attrs(self, element: ET.Element) -> list[tuple[str, str]]:
        items = list(element.attrib.items())
        count = self.known.get(element, 0)
        return items[:count] + sorted(items[count:])

    def start_tag(
        self, element: ET.Element, declarations: Sequence[tuple[str, str]], root: bool
    ) -> str:
        attrs = self.ordered_attrs(element)
        head = attrs[: self.known.get(element, 0)] if root else []
        tail = attrs[len(head) :] if root else attrs
        parts = [self.qname(element.tag, attribute=False)]
        if root:
            # Root order: known attributes (schema_version), declarations, then the extras.
            parts += [f'{self.qname(k, attribute=True)}="{_escape_attr(v)}"' for k, v in head]
        parts += [f'{name}="{_escape_attr(uri)}"' for name, uri in declarations]
        parts += [f'{self.qname(k, attribute=True)}="{_escape_attr(v)}"' for k, v in tail]
        return "<" + " ".join(parts)

    def write(
        self,
        element: ET.Element,
        out: list[str],
        *,
        pretty: bool,
        depth: int,
        declarations: Sequence[tuple[str, str]] = (),
        root: bool = False,
    ) -> None:
        start = self.start_tag(element, declarations, root)
        end = f"</{self.qname(element.tag, attribute=False)}>"
        children = list(element)
        text = element.text or ""
        if not children:
            out.append(start + ("/>" if not text else ">" + _escape_text(text) + end))
            return
        if not is_whitespace(text) or not all(is_whitespace(c.tail) for c in children):
            # Mixed content: the whole subtree is written verbatim, inline.
            out.append(start + ">" + _escape_text(text))
            for child in children:
                self.verbatim(child, out)
                out.append(_escape_text(child.tail or ""))
            out.append(end)
            return
        out.append(start + ">")
        for child in children:
            if pretty:
                out.append("\n" + _INDENT * (depth + 1))
            self.write(child, out, pretty=pretty, depth=depth + 1)
        if pretty:
            out.append("\n" + _INDENT * depth)
        out.append(end)

    def verbatim(self, element: ET.Element, out: list[str]) -> None:
        start = self.start_tag(element, (), False)
        text = element.text or ""
        if not len(element) and not text:
            out.append(start + "/>")
            return
        out.append(start + ">" + _escape_text(text))
        for child in element:
            self.verbatim(child, out)
            out.append(_escape_text(child.tail or ""))
        out.append(f"</{self.qname(element.tag, attribute=False)}>")


def _uris_in_order(root: ET.Element, known: Mapping[ET.Element, int]) -> list[str]:
    """Namespace URIs in first-use order of a pre-order walk (tag, attributes, children)."""
    order = _Serialiser({}, known)
    uris: list[str] = []
    pending = [root]
    while pending:
        element = pending.pop()
        uri, _local = split_name(element.tag)
        if uri is not None and uri != NS_UI:
            uris.append(uri)
        for key, _value in order.ordered_attrs(element):
            uri, _local = split_name(key)
            if uri is not None:
                uris.append(uri)
        pending.extend(reversed(list(element)))
    return uris


def _uses_ui(root: ET.Element) -> bool:
    return any(split_name(element.tag)[0] == NS_UI for element in root.iter())


def serialise(
    root: ET.Element,
    *,
    namespaces: Mapping[str, str],
    known: Mapping[ET.Element, int],
    source: str = "",
) -> bytes:
    """Return the canonical document bytes of ``root`` (declaration, pretty form, final LF).

    ``known`` maps the known model elements to the number of leading attributes that are
    already in schema order; the remaining attributes, and all attributes of other elements,
    are written sorted by key. Names and values must already be checked by the caller.

    Raises:
        XmlIoError: ``xml.write_bad_namespace`` or ``xml.illegal_char`` for ``namespaces``.
    """
    check_namespaces(namespaces, source=source)
    prefixes = assign_prefixes(namespaces, _uris_in_order(root, known))
    declared = effective_namespaces(namespaces)
    declared.update({p: u for u, p in prefixes.items() if p != "xml"})
    declarations = [("xmlns", NS_UI)] + [(f"xmlns:{p}", declared[p]) for p in sorted(declared)]
    out = ['<?xml version="1.0" encoding="UTF-8"?>\n']
    _Serialiser(prefixes, known).write(
        root, out, pretty=True, depth=0, declarations=declarations, root=True
    )
    out.append("\n")
    return "".join(out).encode("utf-8")


def serialise_fragment(element: ET.Element, *, namespaces: Mapping[str, str]) -> str:
    """Return the compact ``RawXml.xml`` form of ``element``'s subtree (its tail excluded).

    The top element declares every namespace the subtree uses, before its own attributes.
    """
    prefixes = assign_prefixes(namespaces, _uris_in_order(element, {}))
    declarations: list[tuple[str, str]] = []
    if _uses_ui(element):
        declarations.append(("xmlns", NS_UI))
    declarations += sorted((f"xmlns:{p}", u) for u, p in prefixes.items() if p != "xml")
    out: list[str] = []
    _Serialiser(prefixes, {}).write(element, out, pretty=False, depth=0, declarations=declarations)
    return "".join(out)
