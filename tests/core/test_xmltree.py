"""Tests of the hardened parser and the canonical serialiser (``pyguibud.core.xmltree``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pyguibud.core import NS_UI, XmlIoError, schema, xmltree
from pyguibud.core.xmltree import NS_XML, NS_XMLNS

NS_A = "urn:a"
NS_B = "urn:b"
NS_TB = "urn:pyguibud:ext:ttkbootstrap:1"


def _parse(text: str | bytes, **kwargs: object) -> xmltree.ParsedTree:
    data = text.encode() if isinstance(text, str) else text
    options: dict[str, object] = {"source": "t.ui", "check_declared_encoding": True}
    options.update(kwargs)
    return xmltree.parse(data, **options)  # type: ignore[arg-type]


def _error(text: str | bytes, **kwargs: object) -> XmlIoError:
    with pytest.raises(XmlIoError) as info:
        _parse(text, **kwargs)
    return info.value


def _ser(root: ET.Element, namespaces: dict[str, str] | None = None) -> str:
    return xmltree.serialise(root, namespaces=namespaces or {}, known={}).decode()


def _el(tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    element = ET.Element(tag, attrs)
    element.text = text
    return element


# ---------------------------------------------------------------- parser
def test_parse_builds_clark_names_positions_and_text() -> None:
    tree = _parse(f'<r xmlns="{NS_UI}" xmlns:a="{NS_A}" a:k="v" p="q">\n  <a:c>hi</a:c>tail</r>')
    root = tree.root
    assert root.tag == f"{{{NS_UI}}}r"
    assert root.attrib == {f"{{{NS_A}}}k": "v", "p": "q"}
    child = root[0]
    assert child.tag == f"{{{NS_A}}}c" and child.text == "hi" and child.tail == "tail"
    assert tree.positions[root] == (1, 1)
    assert tree.positions[child] == (2, 3)
    assert tree.discarded == 0


def test_parse_joins_text_arriving_in_chunks() -> None:
    # A large text node is delivered by expat in several chunks; they must be joined.
    big = "x" * 100_000
    tree = _parse(f'<r xmlns="{NS_UI}">{big}<c/>{big}</r>')
    assert tree.root.text == big and tree.root[0].tail == big


def test_parse_entities_and_char_refs_are_decoded() -> None:
    tree = _parse(f'<r xmlns="{NS_UI}" a="&lt;&#65;&#10;">&amp;&#x41;</r>')
    assert tree.root.get("a") == "<A\n" and tree.root.text == "&A"


def test_parse_hoists_namespaces_first_wins() -> None:
    text = (
        f'<r xmlns="{NS_UI}" xmlns:a="{NS_A}" xmlns:dup="{NS_A}" xmlns:ui="{NS_UI}" '
        f'><c xmlns:b="{NS_B}" xmlns:a="{NS_B}"/></r>'
    )
    assert _parse(text).namespaces == {"a": NS_A, "b": NS_B}


def test_parse_counts_comments_and_processing_instructions() -> None:
    tree = _parse(f'<?xml version="1.0"?><!--a--><r xmlns="{NS_UI}"><!--b--><?pi x?></r><!--c-->')
    assert tree.discarded == 4
    assert len(tree.root) == 0 and not tree.root.text


@pytest.mark.parametrize("encoding", ["utf-8", "UTF-8", "utf8", "Utf-8"])
def test_declared_utf8_is_accepted(encoding: str) -> None:
    _parse(f'<?xml version="1.0" encoding="{encoding}"?><r xmlns="{NS_UI}"/>')


@pytest.mark.parametrize("encoding", ["ISO-8859-1", "us-ascii", "UTF-16"])
def test_declared_other_encoding_is_refused_with_position(encoding: str) -> None:
    exc = _error(f'<?xml version="1.0" encoding="{encoding}"?><r xmlns="{NS_UI}"/>')
    assert exc.code == "xml.bad_encoding" and exc.params["encoding"] == encoding
    assert (exc.line, exc.column) == (1, 1)
    assert encoding in exc.message


def test_declared_encoding_check_can_be_disabled() -> None:
    text = f'<?xml version="1.0" encoding="ISO-8859-1"?><r xmlns="{NS_UI}"/>'
    assert _parse(text, check_declared_encoding=False).root.tag.endswith("}r")


def test_malformed_has_detail_line_and_column() -> None:
    exc = _error(f'<r xmlns="{NS_UI}">\n  <c>&nope;</c></r>')
    assert exc.code == "xml.malformed"
    assert (exc.line, exc.column) == (2, 6)
    assert exc.params["detail"] == "undefined entity"
    assert exc.location == "t.ui:2:6"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "<r",
        f'<r xmlns="{NS_UI}">',
        f'<r xmlns="{NS_UI}"></x>',
        f'<r xmlns="{NS_UI}"/><r2/>',
        f'<r xmlns="{NS_UI}" a="1" a="2"/>',
        "<p:r/>",
    ],
)
def test_malformed_inputs(text: str) -> None:
    exc = _error(text)
    assert exc.code == "xml.malformed" and exc.line is not None and exc.column is not None


@pytest.mark.parametrize(
    "text",
    [
        f"<!DOCTYPE r><r xmlns='{NS_UI}'/>",
        f"<!DOCTYPE r [<!ENTITY e 'v'>]><r xmlns='{NS_UI}'>&e;</r>",
        f"<!DOCTYPE r [<!ENTITY % p 'v'>]><r xmlns='{NS_UI}'/>",
        f"<!DOCTYPE r [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><r xmlns='{NS_UI}'>&e;</r>",
        f"<!DOCTYPE r SYSTEM 'http://example.invalid/x.dtd'><r xmlns='{NS_UI}'/>",
        f"<!DOCTYPE r [<!NOTATION n SYSTEM 'x'>]><r xmlns='{NS_UI}'/>",
        f"<!DOCTYPE r [<!ENTITY u SYSTEM 'x' NDATA n>]><r xmlns='{NS_UI}'/>",
    ],
)
def test_doctype_forms_are_forbidden(text: str) -> None:
    exc = _error(text)
    assert exc.code == "xml.doctype_forbidden" and exc.line == 1 and exc.column is not None


def test_billion_laughs_is_refused_before_expansion() -> None:
    entities = '<!ENTITY l0 "lol">' + "".join(
        f'<!ENTITY l{i} "{f"&l{i - 1};" * 10}">' for i in range(1, 10)
    )
    exc = _error(f"<!DOCTYPE r [{entities}]><r xmlns='{NS_UI}'>&l9;</r>")
    assert exc.code == "xml.doctype_forbidden"


def test_depth_limit_boundary() -> None:
    def nested(levels: int) -> str:
        return f'<r xmlns="{NS_UI}">' + "<e>" * (levels - 1) + "</e>" * (levels - 1) + "</r>"

    assert _parse(nested(xmltree.MAX_DEPTH)).root is not None
    exc = _error(nested(xmltree.MAX_DEPTH + 1))
    assert exc.code == "xml.too_deep" and exc.params["limit"] == xmltree.MAX_DEPTH
    assert exc.line == 1 and exc.column is not None


def test_no_namespace_element_names_it_and_points_at_it() -> None:
    exc = _error(f'<r xmlns="{NS_UI}">\n <z xmlns=""/></r>')
    assert exc.code == "xml.no_namespace_element" and exc.params["element"] == "z"
    assert (exc.line, exc.column) == (2, 2)


def test_root_check_runs_before_the_no_namespace_test() -> None:
    def refuse(tag: str) -> None:
        raise XmlIoError("custom.refused", "no", tag=tag)

    exc = _error("\n<r/>", root_check=refuse)
    assert exc.code == "custom.refused"
    assert (exc.source, exc.line, exc.column) == ("t.ui", 2, 1)
    assert exc.params["tag"] == "r"


def test_root_check_only_sees_the_root() -> None:
    seen: list[str] = []
    _parse(f'<r xmlns="{NS_UI}"><c/><c/></r>', root_check=seen.append)
    assert seen == [f"{{{NS_UI}}}r"]


def test_parse_fragment_accepts_one_element() -> None:
    element = xmltree.parse_fragment(f'<a:x xmlns:a="{NS_A}" a:k="1">t<a:y/></a:x>')
    assert element.tag == f"{{{NS_A}}}x" and element[0].tag == f"{{{NS_A}}}y"


@pytest.mark.parametrize(
    ("text", "detail"),
    [
        ("<broken", "not well-formed"),
        (f'<a xmlns="{NS_A}"/><b xmlns="{NS_A}"/>', "not well-formed"),
        ("", "not well-formed"),
        (f'<a xmlns="{NS_A}"><!--c--></a>', "comments"),
        (f'<a xmlns="{NS_A}"><?pi x?></a>', "comments"),
        (f'<!DOCTYPE a><a xmlns="{NS_A}"/>', "DOCTYPE"),
        ("<a>\ud800</a>", "Unicode"),
    ],
)
def test_parse_fragment_failures_are_write_bad_raw(text: str, detail: str) -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.parse_fragment(text)
    assert info.value.code == "xml.write_bad_raw"
    assert info.value.params["where"] == "RawXml"
    assert detail in info.value.message


def test_parse_fragment_enforces_the_depth_limit() -> None:
    levels = xmltree.MAX_DEPTH + 1
    deep = f'<a xmlns="{NS_A}">' + "<a>" * (levels - 1) + "</a>" * levels
    with pytest.raises(XmlIoError, match="levels") as info:
        xmltree.parse_fragment(deep)
    assert info.value.code == "xml.write_bad_raw"


# ---------------------------------------------------------------- small helpers
def test_subtree_depth() -> None:
    root = ET.Element("a")
    assert xmltree.subtree_depth(root) == 1
    ET.SubElement(ET.SubElement(root, "b"), "c")
    ET.SubElement(root, "d")
    assert xmltree.subtree_depth(root) == 3


def test_split_name_and_display_name() -> None:
    assert xmltree.split_name("{urn:a}x") == ("urn:a", "x")
    assert xmltree.split_name("x") == (None, "x")
    assert xmltree.split_name("{}x") == ("", "x")
    assert xmltree.display_name(f"{{{NS_UI}}}window") == "window"
    assert xmltree.display_name("{urn:a}x") == "{urn:a}x"


def test_is_whitespace_is_ascii_only() -> None:
    assert xmltree.is_whitespace(None)
    assert xmltree.is_whitespace("")
    assert xmltree.is_whitespace(" \t\r\n")
    assert not xmltree.is_whitespace("\u00a0")
    assert not xmltree.is_whitespace(" x ")


@pytest.mark.parametrize("name", ["a", "a1", "a.b", "a-b", "_x", "é", "ñandú"])
def test_is_ncname_accepts(name: str) -> None:
    assert xmltree.is_ncname(name)


@pytest.mark.parametrize("name", ["", "1a", "a b", "a:b", "-a", ".a", "a<b", "a²", "²"])
def test_is_ncname_rejects(name: str) -> None:
    assert not xmltree.is_ncname(name)


@pytest.mark.parametrize("char", ["\x00", "\x01", "\x0b", "\x1f", "\ud800", "\udfff", "￾", "￿"])
def test_check_chars_rejects_illegal(char: str) -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.check_chars(f"a{char}b", "w", source="s")
    assert info.value.code == "xml.illegal_char"
    assert info.value.params == {"where": "w", "codepoint": f"{ord(char):04X}"}
    assert info.value.source == "s" and info.value.line is None


@pytest.mark.parametrize("char", ["\t", "\n", "\r", " ", "퟿", "", "�", "\U00010000", "\U0010ffff"])
def test_check_chars_accepts_legal_boundaries(char: str) -> None:
    xmltree.check_chars(char, "w")


@pytest.mark.parametrize("key", ["a", "k.v-1", f"{{{NS_A}}}k", "xé"])
def test_check_attribute_key_accepts(key: str) -> None:
    xmltree.check_attribute_key(key, "w")


@pytest.mark.parametrize(
    "key",
    [
        "",
        "a b",
        "a:b",
        "1a",
        "xmlns",
        "xmlns:a",
        "xmlnsfoo",
        "{}k",
        f"{{{NS_XMLNS}}}k",
        f"{{{NS_A}}}",
        f"{{{NS_A}}}a b",
    ],
)
def test_check_attribute_key_rejects(key: str) -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.check_attribute_key(key, "w")
    assert info.value.code == "xml.write_bad_name"


@pytest.mark.parametrize(
    "namespaces",
    [
        {"xml": NS_A},
        {"xmlns": NS_A},
        {"1a": NS_A},
        {"a b": NS_A},
        {"a:b": NS_A},
        {"a": ""},
        {"a": NS_XML},
        {"a": NS_XMLNS},
    ],
)
def test_check_namespaces_rejects(namespaces: dict[str, str]) -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.check_namespaces(namespaces)
    assert info.value.code == "xml.write_bad_namespace"


def test_check_namespaces_accepts_and_ignores_default() -> None:
    xmltree.check_namespaces({"": "", "a": NS_A, "tb": NS_B})


def test_check_namespaces_illegal_char() -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.check_namespaces({"a": "urn:\x01"})
    assert info.value.code == "xml.illegal_char"


# ---------------------------------------------------------------- prefixes
def test_assign_prefixes_rules() -> None:
    result = xmltree.assign_prefixes(
        {"": NS_UI, "zz": NS_A, "aa": NS_A, "ns1": "urn:taken"},
        [NS_A, "urn:new1", NS_XML, NS_TB, "urn:new2", NS_A],
    )
    assert result == {
        NS_A: "aa",  # smallest declared prefix
        "urn:new1": "ns2",  # ns1 is taken by the namespaces map
        NS_XML: "xml",
        NS_TB: "tb",  # known prefix, free
        "urn:new2": "ns3",
    }


def test_assign_prefixes_a_known_prefix_bound_elsewhere_is_reclaimed() -> None:
    """H30 (QA-17a-03, ADR-002 Addendum B): tb always means ttkbootstrap on write."""
    assert xmltree.assign_prefixes({"tb": "urn:other"}, [NS_TB, "urn:other"]) == {
        NS_TB: "tb",
        "urn:other": "ns1",
    }
    assert xmltree.effective_namespaces({"tb": "urn:other", "a": "urn:a"}) == {"a": "urn:a"}


def test_assign_prefixes_ui_attribute_namespace_needs_a_prefix() -> None:
    assert xmltree.assign_prefixes({}, [NS_UI]) == {NS_UI: "ns1"}


def test_effective_namespaces_drops_what_the_reader_cannot_hoist() -> None:
    result = xmltree.effective_namespaces(
        {"": NS_UI, "zz": NS_A, "ui": NS_UI, "aa": NS_A, "tb": NS_TB, "b": "urn:b"}
    )
    assert list(result.items()) == [("aa", NS_A), ("b", "urn:b"), ("tb", NS_TB)]


def test_assign_prefixes_ignores_ui_bound_and_losing_prefixes() -> None:
    # "ns1" is bound to NS_UI and "ns2" loses to "a": both are free for generation.
    namespaces = {"ns1": NS_UI, "a": NS_A, "ns2": NS_A}
    assert xmltree.assign_prefixes(namespaces, [NS_UI, "urn:new", NS_A]) == {
        NS_UI: "ns1",
        "urn:new": "ns2",
        NS_A: "a",
    }


# ---------------------------------------------------------------- serialiser
def test_serialise_document_envelope_and_indentation() -> None:
    root = _el(f"{{{NS_UI}}}pyguibud-ui", schema_version="1.0")
    window = ET.SubElement(root, f"{{{NS_UI}}}window", {"id": "w"})
    ET.SubElement(window, f"{{{NS_UI}}}separator")
    out = xmltree.serialise(root, namespaces={}, known={root: 1})
    assert out == (
        b'<?xml version="1.0" encoding="UTF-8"?>\n'
        b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">\n'
        b'  <window id="w">\n    <separator/>\n  </window>\n</pyguibud-ui>\n'
    )


def test_serialise_childless_text_is_exact() -> None:
    assert ">  a\n b  </r>" in _ser(_el(f"{{{NS_UI}}}r", "  a\n b  "))
    assert "> \n </r>" in _ser(_el(f"{{{NS_UI}}}r", " \n "))
    assert '"/>' in _ser(_el(f"{{{NS_UI}}}r", ""))
    assert '"/>' in _ser(_el(f"{{{NS_UI}}}r", None))


def test_serialise_element_only_drops_whitespace_but_nbsp_is_content() -> None:
    root = _el(f"{{{NS_UI}}}r", " \n\t")
    child = ET.SubElement(root, f"{{{NS_UI}}}c")
    child.tail = "\r\n"
    assert ">\n  <c/>\n</r>" in _ser(root)
    mixed = _el(f"{{{NS_UI}}}r", "\u00a0")
    ET.SubElement(mixed, f"{{{NS_UI}}}c")
    assert ">\u00a0<c/></r>" in _ser(mixed)


def test_serialise_mixed_content_is_inline_and_verbatim() -> None:
    root = _el("{u}r", "a ")
    child = ET.SubElement(root, "{u}c", {"k": "v"})
    child.text = "x"
    child.tail = " b"
    ET.SubElement(child, "{u}d").tail = "\n"
    outer = _el(f"{{{NS_UI}}}pyguibud-ui")
    outer.append(root)
    out = xmltree.serialise(outer, namespaces={}, known={}).decode()
    assert '<ns1:r>a <ns1:c k="v">x<ns1:d/>\n</ns1:c> b</ns1:r>' in out


def test_serialise_escaping() -> None:
    root = _el(f"{{{NS_UI}}}r", 'a & b < c > d ]]> "q" \r', v="& < > \" \n \t \r '")
    out = _ser(root)
    assert ' v="&amp; &lt; &gt; &quot; &#10; &#9; &#13; \'">' in out
    assert 'a &amp; b &lt; c &gt; d ]]&gt; "q" &#13;</r>' in out
    assert "CDATA" not in out


def test_serialise_attribute_order_known_then_sorted() -> None:
    root = _el(f"{{{NS_UI}}}r", z="1", b="2", a="3")
    root.set(f"{{{NS_A}}}k", "4")
    # known = 1: only the first attribute keeps its schema position
    out = xmltree.serialise(root, namespaces={"a": NS_A}, known={root: 1}).decode()
    assert '<r z="1" xmlns="urn:pyguibud:ui:1" xmlns:a="urn:a" a="3" b="2" a:k="4"/>' in out


def test_serialise_declares_unused_namespaces_sorted_and_generates_prefixes() -> None:
    root = _el(f"{{{NS_UI}}}r")
    ET.SubElement(root, "{urn:new}x")
    out = xmltree.serialise(root, namespaces={"b": NS_B, "a": NS_A}, known={}).decode()
    assert (
        '<r xmlns="urn:pyguibud:ui:1" xmlns:a="urn:a" xmlns:b="urn:b" xmlns:ns1="urn:new">' in out
    )


def test_serialise_never_declares_xml_namespace() -> None:
    root = _el(f"{{{NS_UI}}}r")
    root.set(f"{{{NS_XML}}}lang", "de")
    out = _ser(root)
    assert 'xml:lang="de"' in out and "xmlns:xml" not in out


def test_serialise_refuses_bad_namespaces() -> None:
    with pytest.raises(XmlIoError) as info:
        xmltree.serialise(_el(f"{{{NS_UI}}}r"), namespaces={"xml": NS_A}, known={}, source="s")
    assert info.value.code == "xml.write_bad_namespace" and info.value.source == "s"


def test_serialise_fragment_declares_what_it_uses() -> None:
    root = _el("{urn:b}x")
    root.set("{urn:a}k", "1")
    ET.SubElement(root, f"{{{NS_UI}}}unknown")
    text = xmltree.serialise_fragment(root, namespaces={"q": NS_A})
    assert text == (
        f'<ns1:x xmlns="{NS_UI}" xmlns:ns1="urn:b" xmlns:q="urn:a" q:k="1"><unknown/></ns1:x>'
    )
    assert xmltree.parse_fragment(text).tag == "{urn:b}x"


def test_serialise_fragment_without_ui_elements_has_no_default_declaration() -> None:
    text = xmltree.serialise_fragment(_el("{urn:b}x"), namespaces={})
    assert text == '<ns1:x xmlns:ns1="urn:b"/>'


def test_serialise_fragment_is_compact() -> None:
    root = _el("{urn:b}x", "\n  ")
    ET.SubElement(root, "{urn:b}y").tail = "\n"
    assert "\n" not in xmltree.serialise_fragment(root, namespaces={})


# ---------------------------------------------------------------- XSD
def test_xsd_is_well_formed_and_declares_the_namespace() -> None:
    text = schema.xsd_text()
    tree = xmltree.parse(text.encode(), source="xsd", check_declared_encoding=True)
    assert tree.root.get("targetNamespace") == NS_UI
    assert 'targetNamespace="urn:pyguibud:ui:1"' in text
    assert schema.XSD_FILENAME == "pyguibud-ui-1.0.xsd"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.0", (1, 0)),
        ("0.0", (0, 0)),
        ("1.12", (1, 12)),
        ("123456789.987654321", (123456789, 987654321)),
        ("1", None),
        ("1.0.0", None),
        ("01.0", None),
        ("1.00", None),
        (" 1.0", None),
        ("1.0 ", None),
        ("1.0\n", None),
        ("abc", None),
        ("", None),
        ("-1.0", None),
        ("1.٣", None),
        ("1234567890.0", None),
    ],
)
def test_parse_version(text: str, expected: tuple[int, int] | None) -> None:
    assert schema.parse_version(text) == expected


def test_lazy_message_translates_when_formatted() -> None:
    from pyguibud import i18n

    lazy = xmltree.LazyMessage("Elements are nested more than {limit} levels deep.", limit=3)
    assert str(lazy) == "Elements are nested more than 3 levels deep."
    assert "LazyMessage" in repr(lazy)
    i18n.set_language("en_XA")
    try:
        assert str(lazy) != "Elements are nested more than 3 levels deep." and "3" in str(lazy)
    finally:
        i18n.set_language("en_GB")


def test_damaged_raw_detail_is_translated_late() -> None:
    from pyguibud import i18n

    with pytest.raises(XmlIoError) as info:
        xmltree.parse_fragment('<a xmlns="urn:a"><!--c--></a>')
    english = info.value.message
    i18n.set_language("en_XA")
    try:
        assert info.value.message != english
    finally:
        i18n.set_language("en_GB")


def test_root_check_error_that_already_has_a_position_keeps_it() -> None:
    def refuse(tag: str) -> None:
        raise XmlIoError("custom.refused", "no", line=7, column=9)

    exc = _error("\n<r/>", root_check=refuse)
    assert (exc.line, exc.column, exc.source) == (7, 9, "t.ui")
