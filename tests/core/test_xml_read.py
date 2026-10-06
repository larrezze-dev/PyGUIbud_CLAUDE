"""Reader tests: inputs, errors with positions, warnings, hardening and versioning."""

from __future__ import annotations

import builtins
import errno
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import (
    CURRENT_SCHEMA_VERSION,
    MAX_DEPTH,
    NS_UI,
    Action,
    Document,
    GridCell,
    Include,
    Layout,
    Menu,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    ReadResult,
    Widget,
    Window,
    XmlIoError,
    XmlWarning,
    dump_ui,
    read_ui,
    read_ui_bytes,
    read_ui_string,
    xml_io,
)

from .xml_helpers import DATA, HEAD, HELLO, doc, read_error, structure

# --------------------------------------------------------------------------------------
# Helpers: put one element into a nested context and know on which line it lands.
# --------------------------------------------------------------------------------------
_CONTEXTS: dict[str, list[str]] = {
    "root": [],
    "resources": ["<resources>"],
    "variables": ["<variables>"],
    "window": ['<window id="w">'],
    "menubar": ['<window id="w">', "<menubar>"],
    "menu": ['<window id="w">', "<menubar>", '<menu id="m">'],
    "layout": ['<window id="w">', '<layout type="grid">'],
    "widget": ['<window id="w">', '<widget class="Frame" id="f">'],
    "cell": ['<window id="w">', '<widget class="Frame" id="f">', '<cell row="0" column="0">'],
    "page": ['<window id="w">', '<widget class="Frame" id="f">', "<page>"],
    "action": ['<window id="w">', "<menubar>", '<menu id="m">', '<action id="a">'],
    "statusbar": ['<window id="w">', '<statusbar id="s">'],
}


def _closing(opening: str) -> str:
    return "</" + opening[1:].split()[0].rstrip(">") + ">"


def inside(context: str, element: str, *, version: str = "1.0") -> tuple[bytes, int]:
    """Return the document and the line (column is always 1) where ``element`` starts."""
    opens = _CONTEXTS[context]
    body = "\n".join([*opens, element, *(_closing(o) for o in reversed(opens))])
    return doc(body, version=version), 3 + len(opens)


def attrs_of(base: dict[str, str], **changes: str | None) -> str:
    merged = {**base, **changes}
    return " ".join(f'{k}="{v}"' for k, v in merged.items() if v is not None)


def expect(
    data: bytes, code: str, line: int | None, column: int | None = 1, **params: object
) -> XmlIoError:
    exc = read_error(data)
    assert exc.code == code, f"{exc.code}: {exc.message}"
    assert (exc.line, exc.column) == (line, column), exc.location
    assert exc.source == "t.ui"
    for key, value in params.items():
        assert exc.params[key] == value
    return exc


def codes(result: ReadResult) -> list[str]:
    return [w.code for w in result.warnings]


# --------------------------------------------------------------------------------------
# Happy path and canonical inputs
# --------------------------------------------------------------------------------------
def test_hello_reads_into_the_expected_model() -> None:
    result = read_ui(HELLO)
    assert result.warnings == () and not result.read_only
    assert result.source_version == "1.0" and result.source == str(HELLO)
    document = result.document
    assert document.schema_version == CURRENT_SCHEMA_VERSION
    assert document.meta.generator == "pyguibud" and document.meta.theme == "flatly"
    assert document.namespaces["tb"] == "urn:pyguibud:ext:ttkbootstrap:1"
    assert list(document.variables) == ["user_name"]
    window = document.children[0]
    assert (window.id, window.kind, window.min_width, window.min_height) == (
        "main",
        "main",
        480,
        320,
    )
    assert window.props["title"].translatable and window.props["title"].context == "window title"
    assert isinstance(window.layout, Layout) and window.layout.type == "grid"
    assert [(c.index, c.weight) for c in window.layout.columns] == [(0, 1)]
    notebook = window.children[0]
    assert isinstance(notebook, Widget) and notebook.class_name == "Notebook"
    assert notebook.placement == GridCell(row=0, column=0, sticky="nsew")
    greeting, about = notebook.children
    assert isinstance(greeting, Widget) and isinstance(greeting.placement, PagePlacement)
    assert greeting.placement.text is not None and greeting.placement.text.value == "Greeting"
    button = greeting.children[2]
    assert isinstance(button, Widget)
    assert button.extra_attrs == {"{urn:pyguibud:ext:ttkbootstrap:1}bootstyle": "primary"}
    assert [(e.name, e.handler) for e in button.events] == [("command", "on_greet")]
    assert isinstance(about, Widget) and about.children[0].placement == PackPlacement(fill="x")
    menu = window.menubar.children[0] if window.menubar else None
    assert isinstance(menu, Menu) and isinstance(menu.children[0], Action)
    assert menu.children[0].shortcut == "Ctrl+Q"


def test_full_golden_maps_every_element_kind() -> None:
    document = read_ui(DATA / "full.in.ui").document
    assert list(document.resources) == ["logo", "icon"]
    assert [v.type for v in document.variables.values()] == ["int", "double", "bool", "string"]
    main, dialog, component = document.children
    assert (main.kind, main.modal, main.buttons) == ("main", True, "ok")
    assert (dialog.kind, component.kind) == ("dialog", "component")
    assert main.menubar is not None
    file_menu = main.menubar.children[0]
    kinds = [type(child) for child in file_menu.children]
    assert kinds == [Action, MenuSeparator, Menu, Action]
    assert main.layout is not None
    assert [c.index for c in main.layout.columns] == [0, 2]
    assert [r.index for r in main.layout.rows] == [1, 0]
    frame = main.children[0]
    assert isinstance(frame, Widget) and isinstance(frame.children[1], Include)
    assert frame.children[1].placement == PackPlacement()
    nb = main.children[1]
    assert isinstance(nb, Widget)
    assert nb.children[1].placement == PagePlacement()
    assert nb.children[2].placement == PagePlacement(weight=2)


def test_source_is_the_path_as_given_and_accepts_pathlike(tmp_path: Path) -> None:
    target = tmp_path / "a.ui"
    target.write_bytes(HELLO.read_bytes())
    assert read_ui(target).source == str(target)
    assert read_ui(str(target)).source == str(target)
    assert read_ui_bytes(HELLO.read_bytes()).source == "<bytes>"
    assert read_ui_string(HELLO.read_text("utf-8")).source == "<string>"
    assert read_ui_bytes(HELLO.read_bytes(), source="mem").source == "mem"


def test_crlf_and_bom_read_like_lf() -> None:
    data = HELLO.read_bytes()
    expected = structure(read_ui_bytes(data).document)
    for variant in (
        data.replace(b"\n", b"\r\n"),
        b"\xef\xbb\xbf" + data,
        b"\xef\xbb\xbf" + data.replace(b"\n", b"\r\n"),
        data.replace(b"\n", b"\r"),
    ):
        assert structure(read_ui_bytes(variant).document) == expected
        assert dump_ui(read_ui_bytes(variant).document) == data


def test_crlf_inside_prop_text_is_normalised_but_char_ref_cr_is_kept() -> None:
    data = doc('<window id="w">\n<prop name="a">x\r\ny&#13;z</prop>\n</window>')
    value = read_ui_bytes(data).document.children[0].props["a"].value
    assert value == "x\ny\rz"


def test_read_ui_string_rules() -> None:
    text = HELLO.read_text("utf-8")
    assert dump_ui(read_ui_string("﻿" + text).document) == HELLO.read_bytes()
    # the declared encoding is not checked for text that is already decoded
    latin = text.replace('encoding="UTF-8"', 'encoding="ISO-8859-1"')
    assert read_ui_string(latin).document.children
    with pytest.raises(XmlIoError) as info:
        read_ui_string(text.replace("Hello", "Hello\ud800"), source="s")
    assert info.value.code == "xml.bad_encoding" and info.value.source == "s"


def test_prop_text_is_preserved_exactly() -> None:
    value = "  lead\n\ttab  \n  "
    data = doc(f'<window id="w">\n<prop name="a">{value}</prop>\n<prop name="b"/>\n</window>')
    props = read_ui_bytes(data).document.children[0].props
    assert props["a"].value == value and props["b"].value == ""


def test_children_are_accepted_in_any_order_and_order_is_kept() -> None:
    body = (
        '<window id="w">\n<widget class="Label" id="b"/>\n<prop name="p"/>\n<layout type="pack"/>\n'
        '<include id="i" src="x.ui" component="C"/>\n<statusbar id="s"/>\n<menubar/>\n'
        '<widget class="Label" id="a"/>\n</window>\n<window id="v"/>\n<meta/>\n<variables/>'
    )
    document = read_ui_bytes(doc(body)).document
    assert [w.id for w in document.children] == ["w", "v"]
    assert [c.id for c in document.children[0].children] == ["b", "i", "a"]


def test_page_text_prop_goes_to_the_placement() -> None:
    body = (
        '<window id="w">\n<widget class="Frame" id="f">\n<page weight="3" image="i">\n'
        '<prop name="text" context="c">T</prop>\n</page>\n</widget>\n</window>'
    )
    placement = read_ui_bytes(doc(body)).document.children[0].children[0].placement
    assert isinstance(placement, PagePlacement)
    assert placement.text is not None and placement.text.context == "c"
    assert (placement.image, placement.weight) == ("i", 3)


@pytest.mark.parametrize(
    ("value", "expected"), [("0", 0), ("-5", -5), ("007", 7), ("-0", 0), ("999999999", 999999999)]
)
def test_int_values_accepted(value: str, expected: int) -> None:
    data = doc(f'<window id="w" min_width="{value}"/>')
    assert read_ui_bytes(data).document.children[0].min_width == expected


@pytest.mark.parametrize(("value", "expected"), [("true", True), ("false", False)])
def test_bool_values_accepted(value: str, expected: bool) -> None:
    data = doc(f'<window id="w" modal="{value}"/>')
    assert read_ui_bytes(data).document.children[0].modal is expected


def test_empty_required_attributes_are_accepted() -> None:
    # The validator (Step 09) judges empty ids; the reader only demands presence.
    result = read_ui_bytes(doc('<window id="">\n<widget class="Label" id=""/>\n</window>'))
    assert result.document.children[0].id == ""


def test_empty_resources_and_variables_elements_are_read() -> None:
    document = read_ui_bytes(doc("<resources/>\n<variables/>")).document
    assert document.resources == {} and document.variables == {}


# --------------------------------------------------------------------------------------
# File access
# --------------------------------------------------------------------------------------
def test_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "nope.ui"
    with pytest.raises(XmlIoError) as info:
        read_ui(path)
    assert info.value.code == "xml.file_not_found"
    assert info.value.source == str(path) and info.value.line is None
    assert isinstance(info.value.__cause__, FileNotFoundError)
    assert str(info.value).startswith(str(path))


def test_directory(tmp_path: Path) -> None:
    with pytest.raises(XmlIoError) as info:
        read_ui(tmp_path)
    assert info.value.code == "xml.is_directory" and info.value.source == str(tmp_path)


def test_other_os_error_becomes_read_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "locked.ui"
    target.write_bytes(HELLO.read_bytes())

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(errno.EACCES, "Permission denied")

    monkeypatch.setattr(xml_io, "open", refuse, raising=False)
    with pytest.raises(XmlIoError) as info:
        read_ui(target)
    assert info.value.code == "xml.read_failed"
    assert info.value.params["reason"] == "Permission denied"
    assert "Permission denied" in info.value.message
    assert isinstance(info.value.__cause__, PermissionError)


def test_os_error_without_strerror_uses_str(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "x.ui"
    target.write_bytes(b"")

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise OSError("odd failure")

    monkeypatch.setattr(xml_io, "open", refuse, raising=False)
    with pytest.raises(XmlIoError) as info:
        read_ui(target)
    assert info.value.params["reason"] == "odd failure"


def test_file_read_goes_through_the_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "big.ui"
    target.write_bytes(HELLO.read_bytes())
    monkeypatch.setattr(xml_io, "MAX_UI_BYTES", 100)
    reads: list[int] = []
    real_open = builtins.open

    def spy(*args: Any, **kwargs: Any) -> Any:
        stream = real_open(*args, **kwargs)
        original = stream.read

        def read(size: int = -1) -> bytes:
            reads.append(size)
            return original(size)  # type: ignore[no-any-return]

        stream.read = read
        return stream

    monkeypatch.setattr(xml_io, "open", spy, raising=False)
    with pytest.raises(XmlIoError) as info:
        read_ui(target)
    assert info.value.code == "xml.too_large" and info.value.source == str(target)
    assert reads == [101], "the reader must never load more than the limit plus one byte"


def test_too_large_boundary_and_limit_parameter() -> None:
    limit = xml_io.MAX_UI_BYTES
    assert limit == 10 * 1024 * 1024
    padding = limit - len(doc(""))
    at_limit = doc("").replace(
        b"<pyguibud-ui", b"<!--" + b"x" * (padding - 4 - 3) + b"--><pyguibud-ui", 1
    )
    assert len(at_limit) <= limit
    assert read_ui_bytes(at_limit, source="t.ui").document.children == ()
    exc = expect(b" " * (limit + 1), "xml.too_large", None, None, limit=10)
    assert "10 MiB" in exc.message


def test_too_large_string_input() -> None:
    with pytest.raises(XmlIoError) as info:
        read_ui_string(" " * (xml_io.MAX_UI_BYTES + 1))
    assert info.value.code == "xml.too_large"


# --------------------------------------------------------------------------------------
# Encoding
# --------------------------------------------------------------------------------------
def test_latin1_bytes_report_line_and_column() -> None:
    data = doc('<window id="w">\n<prop name="a">caf\xe9</prop>\n</window>'.replace("\xe9", ""))
    data = data.replace(b'name="a">', b'name="a">caf\xe9')
    exc = expect(data, "xml.bad_encoding", 4, 19)
    assert "UTF-8" in exc.message


def test_invalid_byte_on_first_line_and_after_bom() -> None:
    expect(b"\xff<a/>", "xml.bad_encoding", 1, 1)
    expect(b"\xef\xbb\xbf\xff", "xml.bad_encoding", 1, 1)


def test_truncated_multibyte_sequence() -> None:
    expect(doc("") + b"\xe2\x82", "xml.bad_encoding", 5, 1)


@pytest.mark.parametrize(
    "encoding", ["utf-16", "utf-32", "utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"]
)
def test_utf16_and_utf32_are_refused(encoding: str) -> None:
    # BOM-less UTF-16 is valid UTF-8 byte-wise (ASCII + NUL) and expat would sniff it as UTF-16.
    data = HELLO.read_text("utf-8").encode(encoding)
    assert read_error(data).code == "xml.bad_encoding"


@pytest.mark.parametrize(
    ("data", "line", "column"),
    [
        (b"<\0?\0", 1, 2),
        (b"\0<\0?", 1, 1),
        (b"\n\0<\0", 2, 1),
        (b"\xef\xbb\xbf<\0?\0", 1, 2),  # the UTF-8 BOM is stripped first
    ],
)
def test_leading_nul_bytes_are_a_bad_encoding_with_position(
    data: bytes, line: int, column: int
) -> None:
    expect(data, "xml.bad_encoding", line, column)


def test_bomless_utf16_string_input_is_refused() -> None:
    text = HELLO.read_text("utf-8").encode("utf-16-le").decode("latin-1")
    with pytest.raises(XmlIoError) as info:
        read_ui_string(text)
    assert info.value.code == "xml.bad_encoding"


def test_nul_byte_after_the_start_stays_malformed_xml() -> None:
    data = doc('<window id="w"/>').replace(b'id="w"/>', b'id="w"/>\0')
    assert read_error(data).code == "xml.malformed"


@pytest.mark.parametrize("encoding", ["ISO-8859-1", "windows-1252", "ascii", "UTF-16"])
def test_declared_encoding_other_than_utf8(encoding: str) -> None:
    data = doc("").replace(b"UTF-8", encoding.encode())
    exc = expect(data, "xml.bad_encoding", 1, 1, encoding=encoding)
    assert encoding in exc.message


@pytest.mark.parametrize("encoding", [b"utf-8", b"UTF-8", b"utf8", b"UTF8"])
def test_declared_utf8_spellings(encoding: bytes) -> None:
    assert read_ui_bytes(doc("").replace(b"UTF-8", encoding)).document.children == ()


def test_no_declaration_is_fine() -> None:
    data = doc("").split(b"\n", 1)[1]
    assert read_ui_bytes(data).document.children == ()


# --------------------------------------------------------------------------------------
# Hardening
# --------------------------------------------------------------------------------------
def test_doctype_is_refused_with_position() -> None:
    data = (
        HEAD.encode()
        + f'<!DOCTYPE a>\n<pyguibud-ui schema_version="1.0" xmlns="{NS_UI}"/>'.encode()
    )
    exc = read_error(data)
    assert exc.code == "xml.doctype_forbidden" and exc.line == 2 and exc.column is not None


def test_billion_laughs_is_refused_quickly() -> None:
    entities = '<!ENTITY a0 "lol">' + "".join(
        f'<!ENTITY a{i} "{f"&a{i - 1};" * 10}">' for i in range(1, 9)
    )
    data = (
        f'{HEAD}<!DOCTYPE b [{entities}]>\n<pyguibud-ui schema_version="1.0" xmlns="{NS_UI}">'
        '<window id="&a8;"/></pyguibud-ui>'
    ).encode()
    assert read_error(data).code == "xml.doctype_forbidden"


def test_external_entity_is_refused_and_never_fetched(tmp_path: Path) -> None:
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET", "utf-8")
    data = (
        f'{HEAD}<!DOCTYPE b [<!ENTITY x SYSTEM "{secret.as_uri()}">]>\n'
        f'<pyguibud-ui schema_version="1.0" xmlns="{NS_UI}"><window id="w">'
        '<prop name="a">&x;</prop></window></pyguibud-ui>'
    ).encode()
    exc = read_error(data)
    assert exc.code == "xml.doctype_forbidden" and "SECRET" not in str(exc)


def test_external_dtd_subset_and_parameter_entities_are_refused(tmp_path: Path) -> None:
    for subset in (
        f'<!DOCTYPE b SYSTEM "{(tmp_path / "x.dtd").as_uri()}">',
        '<!DOCTYPE b [<!ENTITY % pe SYSTEM "x.dtd"> %pe;]>',
    ):
        data = f'{HEAD}{subset}\n<pyguibud-ui schema_version="1.0" xmlns="{NS_UI}"/>'.encode()
        assert read_error(data).code == "xml.doctype_forbidden"


def test_depth_bomb() -> None:
    levels = MAX_DEPTH  # root + (MAX_DEPTH - 1) unknown elements is the deepest legal file
    ok = doc("<e>" * (levels - 1) + "</e>" * (levels - 1))
    assert codes(read_ui_bytes(ok)) == ["xml.unknown_element"]
    bad = doc("<e>" * levels + "</e>" * levels)
    exc = read_error(bad)
    assert exc.code == "xml.too_deep" and exc.params["limit"] == MAX_DEPTH
    assert exc.line == 3  # all the elements are on one line; the limit is crossed there
    # a million-deep bomb is refused without recursion trouble
    assert read_error(doc("<e>" * 100_000)).code == "xml.too_deep"


def test_undefined_entity_has_line_and_column() -> None:
    data = doc('<window id="w">\n<prop name="a">&bogus;</prop>\n</window>')
    expect(data, "xml.malformed", 4, 16, detail="undefined entity")


def test_truncated_file_is_malformed_with_position() -> None:
    data = HELLO.read_bytes()[:300]
    exc = read_error(data)
    assert exc.code == "xml.malformed" and exc.line is not None and exc.column is not None
    assert "not well-formed" in exc.message


@pytest.mark.parametrize(
    "data",
    [b"", b"\n", b"not xml at all", doc("<a></b>"), doc("").replace(b"</pyguibud-ui>", b"")],
)
def test_malformed_files(data: bytes) -> None:
    assert read_error(data).code == "xml.malformed"


def test_no_namespace_element_names_the_element() -> None:
    data = doc('<window id="w">\n<foo xmlns=""/>\n</window>')
    exc = expect(data, "xml.no_namespace_element", 4, 1, element="foo")
    assert "<foo>" in exc.message


def test_no_namespace_element_nested_in_foreign_content() -> None:
    data = doc('<x:y xmlns:x="urn:x">\n<z xmlns=""/>\n</x:y>')
    expect(data, "xml.no_namespace_element", 4, 1, element="z")


# --------------------------------------------------------------------------------------
# Root and version
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "data",
    [
        b"<pyguibud-ui/>",
        b'<pyguibud-ui xmlns="urn:other"/>',
        b'<other xmlns="urn:pyguibud:ui:1"/>',
        b'<x:pyguibud-ui xmlns:x="urn:other"/>',
        b'<pyguibud-ui xmlns="urn:pyguibud:ui:0"/>',
        b'<pyguibud-ui xmlns="urn:pyguibud:ui:01"/>',
        b'<pyguibud-ui xmlns="urn:pyguibud:ui:1x"/>',
        b'<pyguibud-ui xmlns="urn:pyguibud:ui:1234567890"/>',
        b'<pyguibud-ui xmlns="URN:pyguibud:ui:1"/>',
    ],
)
def test_bad_root(data: bytes) -> None:
    exc = read_error(data)
    assert exc.code == "xml.bad_root" and exc.params["namespace"] == NS_UI
    assert (exc.line, exc.column) == (1, 1)


def test_root_without_xmlns_reports_bad_root_not_no_namespace() -> None:
    data = (HEAD + '<pyguibud-ui schema_version="1.0">\n<window id="w"/>\n</pyguibud-ui>').encode()
    expect(data, "xml.bad_root", 2, 1)


def test_root_after_comment_reports_its_own_line() -> None:
    expect(HEAD.encode() + b"<!-- c -->\n\n<wrong/>", "xml.bad_root", 4, 1)


def test_missing_schema_version() -> None:
    data = (HEAD + f'<pyguibud-ui xmlns="{NS_UI}"/>').encode()
    expect(data, "xml.missing_attribute", 2, 1, element="pyguibud-ui", attribute="schema_version")


@pytest.mark.parametrize(
    "version",
    [
        "abc",
        "1",
        "1.0.0",
        "01.0",
        " 1.0",
        "1.0 ",
        "1.",
        ".0",
        "",
        "-1.0",
        "1,0",
        "v1.0",
        "1.00",
        "1.٣",
    ],
)
def test_bad_version(version: str) -> None:
    exc = expect(doc("", version=version), "xml.bad_version", 2, 1, version=version)
    assert "MAJOR.MINOR" in exc.message


@pytest.mark.parametrize("version", ["2.0", "2.5", "10.0", "999999999.0"])
def test_newer_major_by_attribute(version: str) -> None:
    exc = expect(doc("", version=version), "xml.newer_major", 2, 1, version=version, current="1.0")
    assert version in exc.message


def test_newer_major_by_namespace_wins_over_everything_else() -> None:
    # a future file must say "newer", not "wrong root" or "bad content"
    body = '<totally-new-thing foo="bar"/>\n<window id="w" modal="maybe"/>'
    data = doc(body, ns="urn:pyguibud:ui:2")
    expect(data, "xml.newer_major", 2, 1, version="1.0")
    expect(doc("", ns="urn:pyguibud:ui:12", version="12.3"), "xml.newer_major", 2, 1)


def test_newer_major_namespace_with_missing_version_asks_for_the_version() -> None:
    data = (HEAD + '<pyguibud-ui xmlns="urn:pyguibud:ui:2"/>').encode()
    assert read_error(data).code == "xml.missing_attribute"


def test_newer_minor_is_read_only_with_warning_and_keeps_its_version() -> None:
    result = read_ui_bytes(doc('<window id="w"/>', version="1.7"), source="t.ui")
    assert result.read_only and result.source_version == "1.7"
    assert result.document.schema_version == "1.7"
    assert codes(result) == ["xml.newer_minor"]
    warning = result.warnings[0]
    assert (warning.line, warning.column) == (2, 1)
    assert warning.params == {"version": "1.7", "current": "1.0"}
    assert "1.7" in warning.message and "read-only" in warning.message
    for save in (dump_ui,):
        with pytest.raises(XmlIoError) as info:
            save(result.document)
        assert info.value.code == "xml.read_only"
        assert info.value.params == {"version": "1.7", "current": "1.0"}


def test_newer_minor_keeps_misplaced_known_elements_with_warnings() -> None:
    data, line = inside("window", '<cell row="0" column="0"/>', version="1.1")
    result = read_ui_bytes(data, source="t.ui")
    assert codes(result) == ["xml.newer_minor", "xml.misplaced_kept"]
    kept = result.warnings[1]
    assert (kept.line, kept.column) == (line, 1)
    assert kept.params == {"element": "cell", "parent": "window"}
    assert len(result.document.children[0].extra_children) == 1


def test_newer_minor_unknown_attributes_do_not_warn() -> None:
    data = doc('<window id="w" future="1"/>', version="1.4")
    result = read_ui_bytes(data)
    assert codes(result) == ["xml.newer_minor"]
    assert result.document.children[0].extra_attrs == {"future": "1"}


def test_newer_minor_still_fails_on_real_errors() -> None:
    assert read_error(doc('<window id="w" modal="maybe"/>', version="1.4")).code == "xml.bad_bool"


def test_equal_version_has_no_migration_warning() -> None:
    result = read_ui_bytes(doc(""))
    assert result.warnings == () and not result.read_only


@pytest.mark.parametrize("version", ["0.9", "0.0", "0.99"])
def test_older_version_without_migration_path(version: str) -> None:
    exc = expect(doc("", version=version), "xml.no_migration", None, None, version=version)
    assert exc.params["current"] == "1.0" and version in exc.message


# --------------------------------------------------------------------------------------
# Reader errors: singletons, placement, structure
# --------------------------------------------------------------------------------------
_SINGLETONS = [
    ("root", "<meta/>", "meta", "pyguibud-ui"),
    ("root", "<resources/>", "resources", "pyguibud-ui"),
    ("root", "<variables/>", "variables", "pyguibud-ui"),
    ("window", "<menubar/>", "menubar", "window"),
    ("window", '<statusbar id="s"/>', "statusbar", "window"),
    ("window", '<layout type="grid"/>', "layout", "window"),
    ("widget", '<layout type="pack"/>', "layout", "widget"),
]


@pytest.mark.parametrize(("context", "element", "name", "parent"), _SINGLETONS)
def test_duplicate_singletons(context: str, element: str, name: str, parent: str) -> None:
    opens = _CONTEXTS[context]
    body = "\n".join([*opens, element, element, *(_closing(o) for o in reversed(opens))])
    exc = expect(
        doc(body), "xml.duplicate_element", 3 + len(opens) + 1, 1, element=name, parent=parent
    )
    assert f"<{name}>" in exc.message and f"<{parent}>" in exc.message


@pytest.mark.parametrize("first", ['<cell row="0" column="0"/>', "<pack/>", "<page/>"])
@pytest.mark.parametrize("second", ['<cell row="1" column="1"/>', "<pack/>", "<page/>"])
@pytest.mark.parametrize("owner", ["widget", "include"])
def test_duplicate_placement(first: str, second: str, owner: str) -> None:
    if owner == "widget":
        element = f'<widget class="Label" id="x">\n{first}\n{second}\n</widget>'
        name = "widget"
    else:
        element = f'<include id="x" src="a.ui" component="C">\n{first}\n{second}\n</include>'
        name = "include"
    data, line = inside("window", element)
    # The error names the owner but points at the second (offending) placement.
    exc = expect(data, "xml.duplicate_placement", line + 2, 1, element=name)
    assert f"<{name}> has more than one placement" in exc.message


@pytest.mark.parametrize(
    ("context", "owner"),
    [
        ("window", '<window id="w2">'),
        ("widget", None),
        ("menu", None),
        ("action", None),
        ("statusbar", None),
    ],
)
def test_duplicate_prop(context: str, owner: str | None) -> None:
    opens = _CONTEXTS[context]
    body = "\n".join(
        [
            *opens,
            '<prop name="text"/>',
            '<prop name="text">again</prop>',
            *(_closing(o) for o in reversed(opens)),
        ]
    )
    line = 3 + len(opens) + 1
    exc = expect(doc(body), "xml.duplicate_prop", line, 1, name="text")
    assert "'text'" in exc.message


def test_duplicate_prop_in_page() -> None:
    data, line = inside("page", '<prop name="text"/>\n<prop name="text"/>')
    expect(data, "xml.duplicate_prop", line + 1, 1, name="text", element="page")


def test_same_prop_name_on_different_owners_is_fine() -> None:
    body = (
        '<window id="w">\n<prop name="a"/>\n<widget class="Label" id="x">\n<prop name="a"/>\n'
        "</widget>\n</window>"
    )
    read_ui_bytes(doc(body))


def test_bad_page_prop() -> None:
    data, line = inside("page", '<prop name="title"/>')
    expect(data, "xml.bad_page_prop", line, 1, name="title")


def test_page_rejects_other_children() -> None:
    data, line = inside("page", '<widget class="Label" id="x"/>')
    expect(data, "xml.misplaced_element", line, 1, element="widget", parent="page")


def test_duplicate_resource_and_variable() -> None:
    first = '<image id="a" src="1.png"/>'
    data, line = inside("resources", f'{first}\n<image id="a" src="2.png"/>')
    expect(data, "xml.duplicate_resource", line + 1, 1, id="a")
    data, line = inside("variables", '<var id="v" type="int"/>\n<var id="v" type="bool"/>')
    expect(data, "xml.duplicate_variable", line + 1, 1, id="v")


# --------------------------------------------------------------------------------------
# Reader errors: misplaced elements, text, props
# --------------------------------------------------------------------------------------
_MISPLACED = [
    ("window", '<cell row="0" column="0"/>', "cell", "window"),
    ("window", "<pack/>", "pack", "window"),
    ("window", "<page/>", "page", "window"),
    ("window", '<menu id="m"/>', "menu", "window"),
    ("window", '<action id="a"/>', "action", "window"),
    ("window", '<event name="a" handler="b"/>', "event", "window"),
    ("window", '<window id="n"/>', "window", "window"),
    ("window", "<meta/>", "meta", "window"),
    ("root", '<widget class="Label" id="x"/>', "widget", "pyguibud-ui"),
    ("root", '<prop name="a"/>', "prop", "pyguibud-ui"),
    ("root", '<cell row="0" column="0"/>', "cell", "pyguibud-ui"),
    ("root", "<menubar/>", "menubar", "pyguibud-ui"),
    ("root", "<pyguibud-ui/>", "pyguibud-ui", "pyguibud-ui"),
    ("menubar", '<prop name="a"/>', "prop", "menubar"),
    ("menubar", '<action id="a"/>', "action", "menubar"),
    ("menubar", "<separator/>", "separator", "menubar"),
    ("menu", '<widget class="Label" id="x"/>', "widget", "menu"),
    ("menu", '<statusbar id="s"/>', "statusbar", "menu"),
    ("action", '<menu id="m"/>', "menu", "action"),
    ("action", '<action id="a"/>', "action", "action"),
    ("widget", '<column index="0"/>', "column", "widget"),
    ("widget", "<menubar/>", "menubar", "widget"),
    ("widget", '<window id="n"/>', "window", "widget"),
    ("statusbar", '<widget class="Label" id="x"/>', "widget", "statusbar"),
    ("layout", '<widget class="Label" id="x"/>', "widget", "layout"),
    ("layout", '<prop name="a"/>', "prop", "layout"),
    ("resources", '<var id="a" type="int"/>', "var", "resources"),
    ("variables", '<image id="a" src="b"/>', "image", "variables"),
    ("cell", '<widget class="Label" id="x"/>', "widget", "cell"),
    ("cell", '<prop name="a"/>', "prop", "cell"),
]


@pytest.mark.parametrize(("context", "element", "name", "parent"), _MISPLACED)
def test_misplaced_element(context: str, element: str, name: str, parent: str) -> None:
    data, line = inside(context, element)
    exc = expect(data, "xml.misplaced_element", line, 1, element=name, parent=parent)
    assert f"<{name}> is not allowed inside <{parent}>." == exc.message


@pytest.mark.parametrize(("context", "element", "name", "parent"), _MISPLACED)
def test_misplaced_element_is_kept_in_newer_minor(
    context: str, element: str, name: str, parent: str
) -> None:
    data, line = inside(context, element, version="1.2")
    result = read_ui_bytes(data, source="t.ui")
    kept = [w for w in result.warnings if w.code == "xml.misplaced_kept"]
    assert len(kept) == 1 and (kept[0].line, kept[0].column) == (line, 1)
    assert kept[0].params == {"element": name, "parent": parent}


@pytest.mark.parametrize(
    ("context", "element", "owner"),
    [
        ("root", "junk", "pyguibud-ui"),
        ("window", "junk", "window"),
        ("menu", "junk", "menu"),
        ("widget", "junk", "widget"),
        ("layout", "junk", "layout"),
        ("window", '<widget class="Label" id="x">t</widget>', "widget"),
        ("window", "<menubar>t</menubar>", "menubar"),
        ("window", '<statusbar id="s">t</statusbar>', "statusbar"),
        ("widget", '<cell row="0" column="0">t</cell>', "cell"),
        ("widget", "<pack>t</pack>", "pack"),
        ("widget", '<event name="a" handler="b">t</event>', "event"),
        ("widget", "<page>t</page>", "page"),
        ("window", '<layout type="grid">t</layout>', "layout"),
        ("layout", '<column index="0">t</column>', "column"),
        ("resources", '<image id="a" src="b">t</image>', "image"),
        ("variables", '<var id="a" type="int">t</var>', "var"),
        ("root", "<meta>t</meta>", "meta"),
        ("menu", "<separator>t</separator>", "separator"),
    ],
)
def test_unexpected_text(context: str, element: str, owner: str) -> None:
    data, line = inside(context, element)
    exc = read_error(data)
    assert exc.code == "xml.unexpected_text" and exc.params["element"] == owner
    # the error points at the element that contains the text
    expected_line = line - 1 if element == "junk" else line
    if element == "junk" and context == "root":
        expected_line = 2
    assert exc.line == expected_line


def test_unexpected_tail_points_at_the_containing_element() -> None:
    body = '<window id="w">\n<widget class="Label" id="x"/>junk\n</window>'
    expect(doc(body), "xml.unexpected_text", 3, 1, element="window")
    body = '<window id="w">\n<widget class="Frame" id="x">\n<pack/>tail\n</widget>\n</window>'
    expect(doc(body), "xml.unexpected_text", 4, 1, element="widget")


def test_whitespace_only_text_is_ignored_in_structural_elements() -> None:
    body = '<window id="w"> \n\t <widget class="Label" id="x"> \r\n </widget>\t\n</window>'
    assert read_ui_bytes(doc(body)).document.children[0].children


def test_non_breaking_space_is_text_not_whitespace() -> None:
    body = '<window id="w">\u00a0<widget class="Label" id="x"/></window>'
    expect(doc(body), "xml.unexpected_text", 3, 1, element="window")


@pytest.mark.parametrize(
    "prop",
    [
        '<prop name="a"><b/></prop>',
        '<prop name="a">x<b/>y</prop>',
        f'<prop name="a"><b xmlns="{NS_UI}"/></prop>',
        '<prop name="a"><x:b xmlns:x="urn:x"/></prop>',
        '<prop name="a"><prop name="b"/></prop>',
    ],
)
def test_prop_with_element_children(prop: str) -> None:
    data, line = inside("window", prop)
    exc = expect(data, "xml.prop_has_children", line, 1, name="a")
    assert "plain text" in exc.message


def test_prop_children_in_page_and_menu() -> None:
    data, line = inside("page", '<prop name="text"><b/></prop>')
    expect(data, "xml.prop_has_children", line, 1)
    data, line = inside("menu", '<prop name="text"><b/></prop>')
    expect(data, "xml.prop_has_children", line, 1)


# --------------------------------------------------------------------------------------
# Reader errors: required attributes and value grammar
# --------------------------------------------------------------------------------------
_REQUIRED: list[tuple[str, str, dict[str, str]]] = [
    ("resources", "image", {"id": "a", "src": "b"}),
    ("variables", "var", {"id": "a", "type": "int"}),
    ("root", "window", {"id": "a"}),
    ("menubar", "menu", {"id": "a"}),
    ("menu", "action", {"id": "a"}),
    ("window", "statusbar", {"id": "a"}),
    ("window", "layout", {"type": "grid"}),
    ("layout", "column", {"index": "0"}),
    ("layout", "row", {"index": "0"}),
    ("window", "widget", {"class": "Label", "id": "a"}),
    ("window", "include", {"id": "a", "src": "b", "component": "c"}),
    ("window", "prop", {"name": "a"}),
    ("widget", "event", {"name": "a", "handler": "b"}),
    ("widget", "cell", {"row": "0", "column": "0"}),
]


def _required_cases() -> list[tuple[str, str, dict[str, str], str]]:
    return [(ctx, el, base, attr) for ctx, el, base in _REQUIRED for attr in base]


@pytest.mark.parametrize(
    ("context", "element", "base", "missing"),
    _required_cases(),
    ids=[f"{el}-{attr}" for _c, el, _b, attr in _required_cases()],
)
def test_missing_required_attribute(
    context: str, element: str, base: dict[str, str], missing: str
) -> None:
    data, line = inside(context, f"<{element} {attrs_of(base, **{missing: None})}/>")
    exc = expect(data, "xml.missing_attribute", line, 1, element=element, attribute=missing)
    assert f"<{element}>" in exc.message and f"'{missing}'" in exc.message


def test_required_attributes_may_be_present_in_any_order() -> None:
    data, _ = inside("window", '<widget id="a" class="Label"/>')
    read_ui_bytes(data)


_INT_FIELDS: list[tuple[str, str, dict[str, str], str]] = [
    ("root", "window", {"id": "a"}, "min_width"),
    ("root", "window", {"id": "a"}, "min_height"),
    ("window", "layout", {"type": "grid"}, "padding"),
    ("window", "layout", {"type": "grid"}, "gap"),
    ("layout", "column", {"index": "0"}, "index"),
    ("layout", "column", {"index": "0"}, "weight"),
    ("layout", "column", {"index": "0"}, "minsize"),
    ("layout", "row", {"index": "0"}, "index"),
    ("layout", "row", {"index": "0"}, "weight"),
    ("layout", "row", {"index": "0"}, "minsize"),
    ("widget", "cell", {"row": "0", "column": "0"}, "row"),
    ("widget", "cell", {"row": "0", "column": "0"}, "column"),
    ("widget", "cell", {"row": "0", "column": "0"}, "rowspan"),
    ("widget", "cell", {"row": "0", "column": "0"}, "columnspan"),
    ("widget", "cell", {"row": "0", "column": "0"}, "padx"),
    ("widget", "cell", {"row": "0", "column": "0"}, "pady"),
    ("widget", "pack", {}, "padx"),
    ("widget", "pack", {}, "pady"),
    ("widget", "page", {}, "weight"),
    ("window", "include", {"id": "a", "src": "b", "component": "c"}, "dummy-none"),
]
_BAD_INTS = [
    "+1",
    "1_0",
    " 1",
    "1 ",
    "٣",
    "1.5",
    "",
    "-",
    "x",
    "1234567890",
    "--1",
    "0x1",
    "1e3",
    "\u0661",
]


@pytest.mark.parametrize("value", _BAD_INTS)
@pytest.mark.parametrize(
    ("context", "element", "base", "attribute"),
    [case for case in _INT_FIELDS if case[3] != "dummy-none"],
    ids=lambda v: v if isinstance(v, str) else "",
)
def test_bad_int(
    context: str, element: str, base: dict[str, str], attribute: str, value: str
) -> None:
    data, line = inside(context, f"<{element} {attrs_of(base, **{attribute: value})}/>")
    exc = expect(data, "xml.bad_int", line, 1, element=element, attribute=attribute, value=value)
    assert "whole number" in exc.message


_BOOL_FIELDS = [
    ("root", "window", {"id": "a"}, "modal"),
    ("window", "prop", {"name": "a"}, "translatable"),
    ("widget", "pack", {}, "expand"),
]


@pytest.mark.parametrize("value", ["True", "TRUE", "1", "0", "yes", "", "true ", " false", "on"])
@pytest.mark.parametrize(("context", "element", "base", "attribute"), _BOOL_FIELDS)
def test_bad_bool(
    context: str, element: str, base: dict[str, str], attribute: str, value: str
) -> None:
    data, line = inside(context, f"<{element} {attrs_of(base, **{attribute: value})}/>")
    exc = expect(data, "xml.bad_bool", line, 1, element=element, attribute=attribute, value=value)
    assert "true or false" in exc.message


_ENUM_FIELDS = [
    ("root", "window", {"id": "a"}, "kind", "main, dialog, component"),
    ("variables", "var", {"id": "a", "type": "int"}, "type", "string, int, double, bool"),
    ("window", "layout", {"type": "grid"}, "type", "grid, pack"),
    ("window", "layout", {"type": "grid"}, "orient", "vertical, horizontal"),
    ("widget", "pack", {}, "fill", "none, x, y, both"),
]


@pytest.mark.parametrize(
    "value", ["Main", "MAIN", "", "dialogs", "main ", "Grid", "X", "all", "float"]
)
@pytest.mark.parametrize(("context", "element", "base", "attribute", "choices"), _ENUM_FIELDS)
def test_bad_enum(
    context: str, element: str, base: dict[str, str], attribute: str, choices: str, value: str
) -> None:
    if value in choices.split(", "):
        pytest.skip("valid for this field")
    data, line = inside(context, f"<{element} {attrs_of(base, **{attribute: value})}/>")
    exc = expect(data, "xml.bad_enum", line, 1, element=element, attribute=attribute, value=value)
    assert exc.params["choices"] == choices and choices in exc.message


@pytest.mark.parametrize(
    "name",
    [
        "button",
        "a:b:C",
        "",
        "Button ",
        "1X",
        "tb:meter",
        "TB:Meter",
        "tb:",
        ":M",
        "A-B",
        "A B",
        "É",
    ],
)
def test_bad_class_name(name: str) -> None:
    data, line = inside("window", f'<widget class="{name}" id="x"/>')
    exc = expect(data, "xml.bad_class_name", line, 1, name=name)
    assert f"'{name}'" in exc.message


@pytest.mark.parametrize("name", ["Button", "tb:Meter", "acme:My_Widget1", "A", "ttk:Frame"])
def test_good_class_names(name: str) -> None:
    data, _ = inside("window", f'<widget class="{name}" id="x"/>')
    assert read_ui_bytes(data).document.children[0].children[0].class_name == name  # type: ignore[union-attr]


def test_first_error_wins_in_document_order() -> None:
    body = '<window id="w" modal="x"/>\n<window min_width="y"/>'
    expect(doc(body), "xml.bad_bool", 3, 1)


# --------------------------------------------------------------------------------------
# Warnings and preserved content
# --------------------------------------------------------------------------------------
def test_unknown_element_warns_and_is_kept() -> None:
    data, line = inside("widget", '<bogus a="1"/>')
    result = read_ui_bytes(data, source="t.ui")
    assert codes(result) == ["xml.unknown_element"]
    warning = result.warnings[0]
    assert (warning.line, warning.column) == (line, 1)
    assert warning.params == {"element": "bogus", "parent": "widget"}
    assert warning.location == f"t.ui:{line}:1"
    assert str(warning) == f"t.ui:{line}:1: {warning.message}"
    assert "<bogus" in warning.message and "check its spelling" in warning.message
    assert b'<bogus a="1"/>' in dump_ui(result.document)


@pytest.mark.parametrize(
    ("attr", "expected_key"),
    [('mystery="1"', "mystery"), (f'xmlns:q="{NS_UI}" q:odd="1"', f"{{{NS_UI}}}odd")],
)
def test_unknown_attribute_warns_and_is_kept(attr: str, expected_key: str) -> None:
    result = read_ui_bytes(doc(f'<window id="w" {attr}/>'), source="t.ui")
    assert codes(result) == ["xml.unknown_attribute"]
    warning = result.warnings[0]
    assert (warning.line, warning.column) == (3, 1)
    assert warning.params["element"] == "window" and "check its spelling" in warning.message
    assert result.document.children[0].extra_attrs == {expected_key: "1"}


def test_foreign_attributes_and_elements_are_silent() -> None:
    body = (
        '<window id="w" x:k="1" xmlns:x="urn:x">\n'
        '<x:thing>hello <b xmlns="urn:y">there</b></x:thing>\n'
        '<widget class="Label" id="l" xml:lang="de"/>\n</window>'
    )
    result = read_ui_bytes(doc(body))
    assert result.warnings == ()
    window = result.document.children[0]
    assert window.extra_attrs == {"{urn:x}k": "1"}
    assert len(window.extra_children) == 1
    assert window.children[0].extra_attrs == {"{http://www.w3.org/XML/1998/namespace}lang": "de"}


def test_foreign_children_land_in_the_owners_slot() -> None:
    foreign = '<x:f xmlns:x="urn:x"/>'
    cases: list[tuple[str, str, Callable[[Any], Any]]] = [
        ("root", foreign, lambda d: d.extra_children),
        ("window", foreign, lambda d: d.children[0].extra_children),
        ("widget", foreign, lambda d: d.children[0].children[0].extra_children),
        ("menubar", foreign, lambda d: d.children[0].menubar.extra_children),
        ("menu", foreign, lambda d: d.children[0].menubar.children[0].extra_children),
        ("action", foreign, lambda d: d.children[0].menubar.children[0].children[0].extra_children),
        ("statusbar", foreign, lambda d: d.children[0].statusbar.extra_children),
        ("layout", foreign, lambda d: d.children[0].layout.extra_children),
        ("cell", foreign, lambda d: d.children[0].children[0].placement.extra_children),
        ("page", foreign, lambda d: d.children[0].children[0].placement.extra_children),
        ("resources", foreign, lambda d: d.resources_extra.extra_children),
        ("variables", foreign, lambda d: d.variables_extra.extra_children),
    ]
    for context, element, getter in cases:
        data, _ = inside(context, element)
        document = read_ui_bytes(data).document
        if context in {"resources", "variables", "root"}:
            assert len(getter(document)) == 1, context
            continue
        assert len(getter(document)) == 1, context


def test_foreign_children_in_leaf_elements() -> None:
    foreign = '<x:f xmlns:x="urn:x"/>'
    for context, element in [
        ("widget", f'<event name="a" handler="b">{foreign}</event>'),
        ("layout", f'<column index="0">{foreign}</column>'),
        ("resources", f'<image id="a" src="b">{foreign}</image>'),
        ("variables", f'<var id="a" type="int">{foreign}</var>'),
        ("widget", f"<pack>{foreign}</pack>"),
        ("menu", f"<separator>{foreign}</separator>"),
    ]:
        data, _ = inside(context, element)
        result = read_ui_bytes(data)
        assert result.warnings == ()
        assert dump_ui(read_ui_bytes(dump_ui(result.document)).document) == dump_ui(result.document)


def test_foreign_namespace_on_container_attributes() -> None:
    body = '<resources x:k="1"/>\n<variables x:v="2"/>'
    document = read_ui_bytes(doc(body, ' xmlns:x="urn:x"')).document
    assert document.resources_extra.extra_attrs == {"{urn:x}k": "1"}
    assert document.variables_extra.extra_attrs == {"{urn:x}v": "2"}


def test_comments_and_pis_warn_once_without_position() -> None:
    body = '<!-- a -->\n<window id="w">\n<!-- b -->\n<?pi data?>\n</window>\n<!-- c -->'
    result = read_ui_bytes(doc(body), source="t.ui")
    assert codes(result) == ["xml.discarded_content"]
    warning = result.warnings[0]
    assert warning.params == {"count": 3 + 1} and (warning.line, warning.column) == (None, None)
    assert warning.location == "t.ui"
    assert "(4)" in warning.message
    assert b"<!--" not in dump_ui(result.document)


def test_warnings_come_in_document_order_discarded_last() -> None:
    body = '<!--c-->\n<window id="w" odd="1">\n<bogus/>\n</window>\n<other/>'
    assert codes(read_ui_bytes(doc(body))) == [
        "xml.unknown_attribute",
        "xml.unknown_element",
        "xml.unknown_element",
        "xml.discarded_content",
    ]


def test_mixed_content_foreign_element_is_preserved_verbatim() -> None:
    body = '<window id="w">\n<x:p xmlns:x="urn:x">a <x:b>b</x:b>\n c <x:i/>  </x:p>\n</window>'
    first = dump_ui(read_ui_bytes(doc(body)).document)
    assert b"<x:p>a <x:b>b</x:b>\n c <x:i/>  </x:p>" in first
    assert dump_ui(read_ui_bytes(first).document) == first


def test_hoisting_declares_each_foreign_namespace_once_on_the_root() -> None:
    body = (
        '<window id="w">\n<a:x xmlns:a="urn:a"/>\n<a:y xmlns:a="urn:a"/>\n'
        '<q:z xmlns:q="urn:a"/>\n</window>'
    )
    document = read_ui_bytes(doc(body)).document
    assert document.namespaces == {"": NS_UI, "a": "urn:a"}
    out = dump_ui(document)
    assert out.count(b"xmlns:a=") == 1 and b"xmlns:q" not in out and b"<a:z/>" in out


def test_local_prefix_conflict_gets_a_generated_prefix() -> None:
    body = '<window id="w" xmlns:a="urn:a">\n<a:x/>\n<a:y xmlns:a="urn:b"/>\n</window>'
    out = dump_ui(read_ui_bytes(doc(body)).document)
    assert b'xmlns:a="urn:a"' in out and b'xmlns:ns1="urn:b"' in out
    assert b"<a:x/>" in out and b"<ns1:y/>" in out
    assert dump_ui(read_ui_bytes(out).document) == out


def test_unused_tb_is_not_invented_by_the_reader() -> None:
    document = read_ui_bytes(doc('<window id="w"/>')).document
    assert document.namespaces == {"": NS_UI}
    assert b"xmlns:tb" not in dump_ui(document)


def test_default_namespace_foreign_element_is_kept() -> None:
    body = '<window id="w">\n<thing xmlns="urn:other">t</thing>\n</window>'
    result = read_ui_bytes(doc(body))
    assert result.warnings == ()
    assert b"<ns1:thing>t</ns1:thing>" in dump_ui(result.document)


# --------------------------------------------------------------------------------------
# Result objects, structure and i18n
# --------------------------------------------------------------------------------------
def test_read_result_and_warning_shapes() -> None:
    result = read_ui_bytes(doc(""))
    assert isinstance(result, ReadResult) and isinstance(result.document, Document)
    assert isinstance(result.warnings, tuple)
    assert result == result and result != read_ui_bytes(doc(""))  # eq=False: identity
    with pytest.raises(AttributeError):
        result.read_only = True  # type: ignore[misc]
    warning = XmlWarning(code="c", msgid="m {x}", params={"x": 1}, source="s")
    assert warning.message == "m 1" and warning.location == "s" and str(warning) == "s: m 1"
    with pytest.raises(TypeError):
        warning.params["y"] = 2  # type: ignore[index]
    assert XmlWarning(code="c", msgid="{broken", source="s", line=3).message == "{broken"
    assert XmlWarning(code="c", msgid="m", source="s", line=3).location == "s:3"
    assert hash(warning) == hash(warning)


def test_error_message_follows_the_active_language() -> None:
    exc = read_error(doc("", version="zzz"))
    english = exc.message
    assert english.startswith("'zzz' is not a valid schema version")
    assert str(exc) == f"t.ui:2:1: {english}"
    i18n.set_language("en_XA")
    try:
        pseudo = exc.message
        assert pseudo != english and "zzz" in pseudo
        assert str(exc).startswith("t.ui:2:1: ")
        assert read_error(doc("", version="zzz")).code == "xml.bad_version"
        warning = read_ui_bytes(doc('<window id="w" odd="1"/>')).warnings[0]
        assert (
            warning.message
            != "Unknown attribute 'odd' on <window> is kept as it is; check its spelling."
        )
    finally:
        i18n.set_language("en_GB")


def test_error_code_is_stable_across_languages() -> None:
    i18n.set_language("en_XA")
    try:
        assert read_error(doc("", version="2.0")).code == "xml.newer_major"
    finally:
        i18n.set_language("en_GB")


def test_reader_does_not_mutate_or_share_module_state() -> None:
    data = HELLO.read_bytes()
    first = structure(read_ui_bytes(data).document)
    second = structure(read_ui_bytes(data).document)
    assert first == second
    assert Window(id="x") is not None  # model classes stay usable after reads


def test_visible_helper_signature_types() -> None:
    reader: Callable[..., ReadResult] = read_ui_bytes
    assert reader(doc("")).document.main_window is None
