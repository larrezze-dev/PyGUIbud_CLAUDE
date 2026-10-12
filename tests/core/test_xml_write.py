"""Writer tests: canonical output, every refusal, and the atomic save."""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import (
    MAX_DEPTH,
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
    PackPlacement,
    PagePlacement,
    Prop,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    Window,
    XmlIoError,
    dump_ui,
    read_ui,
    read_ui_bytes,
    write_ui,
    xml_io,
)

from .xml_helpers import HELLO, structure

NS_X = "urn:x"
HEAD = b'<?xml version="1.0" encoding="UTF-8"?>\n'


def window_doc(**kwargs: Any) -> Document:
    document = Document()
    window = Window(id="w")
    for key, value in kwargs.items():
        setattr(window, key, value)
    document.add_window(window)
    return document


def widget_doc(**kwargs: Any) -> Document:
    document = Document()
    window = Window(id="w")
    document.add_window(window)
    widget = Widget(class_name="Label", id="x")
    for key, value in kwargs.items():
        setattr(widget, key, value)
    window.append_child(widget)
    return document


def refusal(document: Document) -> XmlIoError:
    with pytest.raises(XmlIoError) as info:
        dump_ui(document)
    assert info.value.source == "<memory>" and info.value.line is None
    return info.value


# --------------------------------------------------------------------------------------
# Canonical output
# --------------------------------------------------------------------------------------
def test_empty_document_is_minimal_and_deterministic() -> None:
    expected = (
        HEAD + b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" '
        b'xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">\n  <meta source_locale="en_GB"/>\n'
        b"</pyguibud-ui>\n"
    )
    assert dump_ui(Document()) == expected
    assert dump_ui(Document()) == dump_ui(Document())


def test_output_is_utf8_lf_without_bom_and_ends_with_one_newline() -> None:
    document = window_doc(props={"a": Prop(name="a", value="Zażółć\r\n€")})
    data = dump_ui(document)
    assert not data.startswith(b"\xef\xbb\xbf") and data.endswith(b"</pyguibud-ui>\n")
    assert b"\r\n" not in data and b"&#13;" in data
    assert "Zażółć".encode() in data


def test_defaults_are_omitted_and_star_attributes_are_always_written() -> None:
    document = Document()
    window = Window(id="w")
    window.layout = Layout(type="grid")
    document.add_window(window)
    widget = Widget(class_name="Button", id="b")
    widget.placement = GridCell(row=0, column=0)
    widget.events.append(Event(name="command", handler="go"))
    window.append_child(widget)
    pack = Widget(class_name="Frame", id="f")
    pack.placement = PackPlacement()
    pack.layout = Layout(type="pack")
    window.append_child(pack)
    pack.append_child(Widget(class_name="Label", id="l", placement=PagePlacement()))
    document.variables["v"] = Variable(id="v", type="string")
    text = dump_ui(document).decode()
    assert '<window id="w" kind="main">' in text
    assert '<layout type="grid"/>' in text
    assert '<cell row="0" column="0"/>' in text
    assert "<pack/>" in text and "<page/>" in text
    assert '<layout type="pack"/>' in text
    assert '<var id="v" type="string"/>' in text
    assert '<meta source_locale="en_GB"/>' in text
    for omitted in ("modal", "min_width", "orient", "padding", "rowspan", "sticky", "expand"):
        assert omitted not in text


def test_non_default_values_are_written_in_schema_order() -> None:
    document = Document(meta=None)  # type: ignore[arg-type]
    document.meta = __import__("pyguibud.core", fromlist=["Meta"]).Meta(
        generator="g", source_locale="de_DE", i18n_domain="dom", theme="t"
    )
    window = Window(
        id="w", kind="dialog", min_width=0, min_height=-3, modal=True, buttons="ok,cancel"
    )
    window.layout = Layout(type="grid", orient="horizontal", padding=4, gap=2)
    window.layout = Layout(
        type="grid",
        orient="horizontal",
        padding=4,
        gap=2,
        columns=(GridLine(index=2, weight=1, minsize=5),),
        rows=(GridLine(index=0),),
    )
    document.add_window(window)
    cell = GridCell(row=1, column=2, rowspan=2, columnspan=3, sticky="ew", padx=1, pady=2)
    window.append_child(Widget(class_name="Label", id="l", placement=cell, bind="v"))
    text = dump_ui(document).decode()
    assert '<meta generator="g" source_locale="de_DE" i18n_domain="dom" theme="t"/>' in text
    assert (
        '<window id="w" kind="dialog" min_width="0" min_height="-3" modal="true" '
        'buttons="ok,cancel">'
    ) in text
    assert '<layout type="grid" orient="horizontal" padding="4" gap="2">' in text
    assert '<column index="2" weight="1" minsize="5"/>' in text
    assert '<row index="0"/>' in text
    assert (
        '<cell row="1" column="2" rowspan="2" columnspan="3" sticky="ew" padx="1" pady="2"/>'
    ) in text
    assert '<widget class="Label" id="l" bind="v">' in text


def test_empty_string_optionals_follow_the_none_vs_empty_rule() -> None:
    # ``str | None`` fields write "" (it differs from None); plain ``str`` defaults omit "".
    window = Window(id="w", buttons="")
    action = Action(id="a", handler="", shortcut="")
    document = Document()
    document.add_window(window)
    window.menubar = Menubar()
    menu = Menu(id="m")
    menu.append_child(action)
    window.menubar.append_child(menu)
    text = dump_ui(document).decode()
    assert 'buttons=""' in text and '<action id="a" handler="" shortcut=""/>' in text
    reread = read_ui_bytes(dump_ui(document)).document
    assert reread.children[0].buttons == ""
    none_doc = window_doc()
    assert "buttons" not in dump_ui(none_doc).decode()


def test_props_are_sorted_by_name_for_every_owner() -> None:
    props = {name: Prop(name=name) for name in ("zeta", "Alpha", "beta", "_u", "ä")}
    document = Document()
    window = Window(id="w", props=dict(props))
    window.statusbar = Statusbar(id="s", props=dict(props))
    window.menubar = Menubar()
    menu = Menu(id="m", props=dict(props))
    menu.append_child(Action(id="a", props=dict(props)))
    window.menubar.append_child(menu)
    window.append_child(Widget(class_name="Label", id="x", props=dict(props)))
    document.add_window(window)
    text = dump_ui(document).decode()
    names = [chunk.split('"')[0] for chunk in text.split('<prop name="')[1:]]
    expected = ["Alpha", "_u", "beta", "zeta", "ä"]
    assert names == expected * 5


def test_element_order_is_canonical_whatever_the_model_order() -> None:
    document = Document()
    window = Window(id="w", extra_children=[RawXml(xml=f'<x:e xmlns:x="{NS_X}"/>')])
    document.add_window(window)
    document.namespaces = {"": NS_UI, "x": NS_X}
    window.layout = Layout(type="pack")
    window.statusbar = Statusbar(id="s")
    window.menubar = Menubar()
    window.set_prop(Prop(name="p"))
    widget = Widget(class_name="Frame", id="f", layout=Layout(type="pack"))
    widget.placement = PackPlacement()
    widget.events.append(Event(name="change", handler="h"))
    widget.set_prop(Prop(name="p"))
    window.append_child(widget)
    window.append_child(Include(id="i", src="a.ui", component="C"))
    text = dump_ui(document).decode()
    order = [
        "<prop",
        "<menubar/>",
        "<statusbar",
        "<layout",
        "<widget",
        "<include",
        "<x:e/>",
    ]
    positions = [text.index(item) for item in order]
    assert positions == sorted(positions)
    inner = text[text.index("<widget") : text.index("<include")]
    assert [inner.index(t) for t in ("<prop", "<event", "<pack/>", "<layout")] == sorted(
        inner.index(t) for t in ("<prop", "<event", "<pack/>", "<layout")
    )


def test_resources_and_variables_written_iff_non_empty_or_have_extras() -> None:
    assert b"resources" not in dump_ui(Document()) and b"variables" not in dump_ui(Document())
    with_extras = Document(
        namespaces={"": NS_UI, "x": NS_X},
        resources_extra=ContainerExtras(extra_attrs={f"{{{NS_X}}}k": "v"}),
        variables_extra=ContainerExtras(extra_children=(RawXml(xml=f'<x:e xmlns:x="{NS_X}"/>'),)),
    )
    text = dump_ui(with_extras).decode()
    assert "<resources" in text and "<variables>" in text and "<x:e/>" in text
    again = read_ui_bytes(dump_ui(with_extras)).document
    assert again.resources_extra.extra_attrs == {f"{{{NS_X}}}k": "v"}
    assert len(again.variables_extra.extra_children) == 1


def test_menus_statusbar_and_include_pages() -> None:
    document = Document()
    window = Window(id="w")
    document.add_window(window)
    window.menubar = Menubar()
    top = Menu(id="top")
    sub = Menu(id="sub")
    top.append_child(MenuSeparator())
    top.append_child(sub)
    top.append_child(Action(id="act", handler="go", shortcut="Ctrl+G"))
    window.menubar.append_child(top)
    window.append_child(
        Include(id="inc", src="a.ui", component="C", placement=PagePlacement(weight=2, image="im"))
    )
    document.resources["im"] = ImageResource(id="im", src="im.png")
    text = dump_ui(document).decode()
    assert text.index("<separator/>") < text.index('<menu id="sub"/>') < text.index("<action")
    assert '<include id="inc" src="a.ui" component="C">' in text
    assert '<page image="im" weight="2"/>' in text
    assert read_ui_bytes(dump_ui(document)).document.children[0].menubar is not None


def test_page_text_is_written_as_a_prop_inside_the_page() -> None:
    page = PagePlacement(text=Prop(name="text", value="Tab", translatable=True, context="c"))
    text = dump_ui(widget_doc(placement=page)).decode()
    assert (
        '<page>\n        <prop name="text" translatable="true" context="c">Tab</prop>\n'
        "      </page>"
    ) in text


def test_dump_does_not_mutate_the_document() -> None:
    document = read_ui(HELLO).document
    document.children[0].props["zzz"] = Prop(name="zzz")
    document.children[0].props["aaa"] = Prop(name="aaa")
    before = structure(document)
    order = list(document.children[0].props)
    first = dump_ui(document)
    assert structure(document) == before and list(document.children[0].props) == order
    assert dump_ui(document) == first


def test_dump_stamps_the_current_version_and_leaves_generator_alone() -> None:
    document = Document()
    assert b'schema_version="1.0"' in dump_ui(document)
    assert b"generator" not in dump_ui(document)
    document.meta.generator = "mine"
    assert b'generator="mine"' in dump_ui(document)


def test_root_attribute_order_and_extras() -> None:
    document = Document(
        extra_attrs={f"{{{NS_X}}}k": "1", "plain": "2"}, namespaces={"": NS_UI, "x": NS_X}
    )
    root = dump_ui(document).split(b"\n")[1].decode()
    assert root == (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" xmlns:x="urn:x" '
        'plain="2" x:k="1">'
    )


# --------------------------------------------------------------------------------------
# Namespaces and preserved content
# --------------------------------------------------------------------------------------
def test_namespaces_declared_on_root_used_or_not_sorted_by_prefix() -> None:
    document = Document(namespaces={"": "ignored", "zz": "urn:z", "aa": "urn:a", "tb": "urn:tb"})
    root = dump_ui(document).split(b"\n")[1].decode()
    assert root.index('xmlns:aa="urn:a"') < root.index("xmlns:tb=") < root.index("xmlns:zz=")
    assert 'xmlns="urn:pyguibud:ui:1"' in root and "ignored" not in root


def test_missing_tb_is_declared_when_tb_content_exists() -> None:
    document = read_ui(HELLO).document
    document.namespaces = {"": NS_UI}
    data = dump_ui(document)
    assert (
        b'xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1"' in data and b'tb:bootstyle="primary"' in data
    )
    assert dump_ui(read_ui_bytes(data).document) == data


def test_ui_namespace_attributes_get_a_generated_prefix() -> None:
    document = window_doc(extra_attrs={f"{{{NS_UI}}}odd": "1"})
    data = dump_ui(document).decode()
    assert 'xmlns:ns1="urn:pyguibud:ui:1"' in data and 'ns1:odd="1"' in data
    again = dump_ui(read_ui_bytes(data.encode()).document)
    assert again == data.encode()


def test_prefix_bound_to_ui_namespace_is_byte_stable() -> None:
    document = window_doc(extra_attrs={f"{{{NS_UI}}}odd": "1"})
    document.namespaces = {"": NS_UI, "ui": NS_UI}
    first = dump_ui(document)
    # the reader never hoists a prefix bound to NS_UI, so the writer ignores it from the start
    assert "xmlns:ui=" not in first.decode() and 'ns1:odd="1"' in first.decode()
    assert dump_ui(read_ui_bytes(first).document) == first


def test_generated_prefixes_avoid_declared_ones_and_follow_first_use() -> None:
    document = window_doc(
        extra_attrs={"{urn:b}k": "1", "{urn:a}k": "2"},
        extra_children=[RawXml(xml='<q:e xmlns:q="urn:c"/>')],
    )
    document.namespaces = {"": NS_UI, "ns1": "urn:taken"}
    data = dump_ui(document).decode()
    # attributes are written sorted by key, so urn:a is met first; ns1 is taken
    assert 'xmlns:ns1="urn:taken"' in data
    assert (
        'xmlns:ns2="urn:a"' in data and 'xmlns:ns3="urn:b"' in data and 'xmlns:ns4="urn:c"' in data
    )
    assert "<ns4:e/>" in data


def test_xml_namespace_attribute_needs_no_declaration() -> None:
    data = dump_ui(window_doc(extra_attrs={"{http://www.w3.org/XML/1998/namespace}lang": "de"}))
    assert b'xml:lang="de"' in data and b"xmlns:xml" not in data


def test_raw_xml_is_spliced_after_known_children_in_list_order() -> None:
    document = window_doc(
        extra_children=[
            RawXml(xml=f'<x:b xmlns:x="{NS_X}"><x:c/></x:b>'),
            RawXml(xml=f'<x:a xmlns:x="{NS_X}"/>'),
            RawXml(xml=f'<unknown xmlns="{NS_UI}"/>'),
        ]
    )
    document.children[0].append_child(Widget(class_name="Label", id="x"))
    document.namespaces = {"": NS_UI, "x": NS_X}
    text = dump_ui(document).decode()
    assert (
        text.index("<widget")
        < text.index("<x:b>")
        < text.index("<x:a/>")
        < text.index("<unknown/>")
    )
    assert "    <x:b>\n      <x:c/>\n    </x:b>" in text
    assert dump_ui(read_ui_bytes(text.encode()).document) == text.encode()


def test_raw_xml_mixed_content_is_written_verbatim() -> None:
    raw = RawXml(xml=f'<x:p xmlns:x="{NS_X}">a <x:b> b </x:b>\n tail</x:p>')
    text = dump_ui(window_doc(extra_children=[raw])).decode()
    assert "<ns1:p>a <ns1:b> b </ns1:b>\n tail</ns1:p>" in text


def test_raw_xml_known_names_nested_in_foreign_content_are_allowed() -> None:
    raw = RawXml(
        xml=f'<x:wrap xmlns:x="{NS_X}" xmlns="{NS_UI}"><cell row="0" column="0"/></x:wrap>'
    )
    data = dump_ui(window_doc(extra_children=[raw]))
    assert b"<cell" in data
    assert read_ui_bytes(data).warnings == ()


@pytest.mark.parametrize(
    "name",
    sorted(xml_io._VOCABULARY),
)
def test_raw_xml_with_known_top_element_is_refused(name: str) -> None:
    exc = refusal(window_doc(extra_children=[RawXml(xml=f'<{name} xmlns="{NS_UI}"/>')]))
    assert exc.code == "xml.write_bad_raw" and exc.params["where"] == "window[w]"
    assert f"<{name}>" in exc.message


def test_raw_xml_unknown_ui_name_is_allowed_and_read_back_with_a_warning() -> None:
    data = dump_ui(window_doc(extra_children=[RawXml(xml=f'<Cell xmlns="{NS_UI}"/>')]))
    assert [w.code for w in read_ui_bytes(data).warnings] == ["xml.unknown_element"]


# --------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("char", "codepoint"),
    [
        ("\x01", "0001"),
        ("\x00", "0000"),
        ("\x1f", "001F"),
        ("￾", "FFFE"),
        ("￿", "FFFF"),
        ("\ud800", "D800"),
    ],
)
def test_illegal_characters_are_refused_everywhere(char: str, codepoint: str) -> None:
    candidates: list[tuple[Callable[[], Document], str]] = [
        (lambda: window_doc(props={"a": Prop(name="a", value=f"x{char}")}), "window[w]/prop[a]"),
        (
            lambda: window_doc(props={"a": Prop(name="a", comment=char)}),
            "window[w]/prop[a]@comment",
        ),
        (
            lambda: window_doc(props={"a": Prop(name="a", context=char)}),
            "window[w]/prop[a]@context",
        ),
        (lambda: window_doc(buttons=char), "window[w]@buttons"),
        (lambda: window_doc(extra_attrs={"k": char}), "window[w]@k"),
        (lambda: window_doc(extra_attrs={f"k{char}": "v"}), "window[w]@k"),
        (lambda: widget_doc(bind=char), "window[w]/widget[x]@bind"),
        (lambda: widget_doc(fallback=char), "window[w]/widget[x]@fallback"),
    ]
    for build, where in candidates:
        exc = refusal(build())
        assert exc.code == "xml.illegal_char", where
        assert exc.params["codepoint"] == codepoint
        assert str(exc.params["where"]).startswith(where.split("@")[0])
    meta_doc = Document()
    meta_doc.meta.theme = char
    assert refusal(meta_doc).params["where"] == "meta@theme"
    id_doc = window_doc()
    id_doc.children[0].id = f"i{char}"
    assert refusal(id_doc).code == "xml.illegal_char"
    ns_doc = Document(namespaces={"": NS_UI, "a": f"urn:{char}"})
    assert refusal(ns_doc).code == "xml.illegal_char"


def test_illegal_char_message_names_where_and_codepoint() -> None:
    exc = refusal(window_doc(props={"a": Prop(name="a", value="\x01")}))
    assert exc.message == "window[w]/prop[a] contains the character U+0001, which XML cannot store."


def test_legal_boundary_characters_are_written() -> None:
    value = "\t\n ퟿�\U00010000\U0010ffff"
    document = window_doc(props={"a": Prop(name="a", value=value)})
    data = dump_ui(document)
    assert read_ui_bytes(data).document.children[0].props["a"].value == value


_BAD_VALUES: list[tuple[str, Callable[[], Document], str]] = [
    ("bool-as-int", lambda: window_doc(min_width=True), "window[w]@min_width"),
    ("str-as-int", lambda: window_doc(min_height="5"), "window[w]@min_height"),
    ("float-as-int", lambda: window_doc(min_height=1.5), "window[w]@min_height"),
    ("int-too-large", lambda: window_doc(min_width=1_000_000_000), "window[w]@min_width"),
    ("int-too-small", lambda: window_doc(min_width=-1_000_000_000), "window[w]@min_width"),
    ("bad-kind", lambda: window_doc(kind="popup"), "window[w]@kind"),
    ("kind-none", lambda: window_doc(kind=None), "window[w]@kind"),
    ("modal-str", lambda: window_doc(modal="yes"), "window[w]@modal"),
    ("modal-int", lambda: window_doc(modal=1), "window[w]@modal"),
    ("modal-none", lambda: window_doc(modal=None), "window[w]@modal"),
    ("buttons-int", lambda: window_doc(buttons=3), "window[w]@buttons"),
    ("layout-type", lambda: window_doc(layout=Layout(type="place")), "window[w]/layout@type"),  # type: ignore[arg-type]
    (
        "layout-orient",
        lambda: window_doc(layout=Layout(type="pack", orient="diag")),  # type: ignore[arg-type]
        "window[w]/layout@orient",
    ),
    (
        "layout-padding",
        lambda: window_doc(layout=Layout(type="pack", padding=None)),  # type: ignore[arg-type]
        "window[w]/layout@padding",
    ),
    (
        "layout-gap",
        lambda: window_doc(layout=Layout(type="pack", gap=True)),
        "window[w]/layout@gap",
    ),
    (
        "gridline-index",
        lambda: window_doc(layout=Layout(type="grid", columns=(GridLine(index=None),))),  # type: ignore[arg-type]
        "column",
    ),
    (
        "gridline-weight",
        lambda: window_doc(layout=Layout(type="grid", rows=(GridLine(index=0, weight="1"),))),  # type: ignore[arg-type]
        "row",
    ),
    ("cell-row", lambda: widget_doc(placement=GridCell(row=True, column=0)), "cell@row"),
    ("cell-column", lambda: widget_doc(placement=GridCell(row=0, column=None)), "cell@column"),  # type: ignore[arg-type]
    (
        "cell-span",
        lambda: widget_doc(placement=GridCell(row=0, column=0, rowspan=None)),  # type: ignore[arg-type]
        "cell@rowspan",
    ),
    (
        "cell-sticky",
        lambda: widget_doc(placement=GridCell(row=0, column=0, sticky=5)),  # type: ignore[arg-type]
        "cell@sticky",
    ),
    ("pack-fill", lambda: widget_doc(placement=PackPlacement(fill="all")), "pack@fill"),  # type: ignore[arg-type]
    ("pack-expand", lambda: widget_doc(placement=PackPlacement(expand=1)), "pack@expand"),  # type: ignore[arg-type]
    ("pack-padx", lambda: widget_doc(placement=PackPlacement(padx=2.0)), "pack@padx"),  # type: ignore[arg-type]
    ("page-weight", lambda: widget_doc(placement=PagePlacement(weight=None)), "page@weight"),  # type: ignore[arg-type]
    ("page-image", lambda: widget_doc(placement=PagePlacement(image=4)), "page@image"),  # type: ignore[arg-type]
    (
        "page-text-name",
        lambda: widget_doc(placement=PagePlacement(text=Prop(name="title"))),
        "page/prop[text]@name",
    ),
    ("placement-object", lambda: widget_doc(placement=object()), "placement"),
    (
        "prop-value-none",
        lambda: window_doc(props={"a": Prop(name="a", value=None)}),  # type: ignore[arg-type]
        "window[w]/prop[a]",
    ),
    (
        "prop-translatable",
        lambda: window_doc(props={"a": Prop(name="a", translatable=1)}),  # type: ignore[arg-type]
        "prop[a]@translatable",
    ),
    ("prop-name-int", lambda: window_doc(props={7: Prop(name=7)}), "prop[7]@name"),  # type: ignore[arg-type]
    (
        "window-id-int",
        lambda: Document(children=None) if False else _doc_with_window_id(5),
        "window[5]@id",
    ),
    ("widget-id-none", lambda: widget_doc(id=None), "widget[None]@id"),
    (
        "event-handler",
        lambda: widget_doc(events=[Event(name="command", handler=None)]),  # type: ignore[arg-type]
        "event[command]@handler",
    ),
    ("var-type", lambda: _doc_with_var(Variable(id="v", type="float")), "var[v]@type"),  # type: ignore[arg-type]
    ("meta-locale-none", lambda: _doc_with_locale(None), "meta@source_locale"),
]


def _doc_with_window_id(value: object) -> Document:
    document = window_doc()
    document.children[0].id = value  # type: ignore[assignment]
    return document


def _doc_with_var(variable: Variable) -> Document:
    document = Document()
    document.variables[variable.id] = variable
    return document


def _doc_with_locale(value: object) -> Document:
    document = Document()
    document.meta.source_locale = value  # type: ignore[assignment]
    return document


@pytest.mark.parametrize(("name", "build", "where"), _BAD_VALUES, ids=[c[0] for c in _BAD_VALUES])
def test_bad_values_are_refused(name: str, build: Callable[[], Document], where: str) -> None:
    exc = refusal(build())
    assert exc.code == "xml.write_bad_value" or exc.code == "xml.write_bad_name"
    assert exc.code == "xml.write_bad_value", exc.message
    assert where in str(exc.params["where"])
    assert "which the .ui format cannot store" in exc.message


@pytest.mark.parametrize("value", [999_999_999, -999_999_999, 0])
def test_int_limits_are_inclusive(value: int) -> None:
    data = dump_ui(window_doc(min_width=value))
    assert read_ui_bytes(data).document.children[0].min_width == value


def test_bad_class_name_is_refused_by_the_writer() -> None:
    exc = refusal(widget_doc(class_name="button"))
    assert exc.code == "xml.bad_class_name" and exc.params["name"] == "button"


@pytest.mark.parametrize(
    "key",
    [
        "kind",
        "id",
        "a b",
        "xmlns",
        "xmlns:a",
        "xmlnsx",
        "",
        "{}k",
        "a:b",
        "1a",
        "{urn:x}",
        "{http://www.w3.org/2000/xmlns/}a",
    ],
)
def test_bad_attribute_names_are_refused(key: str) -> None:
    exc = refusal(window_doc(extra_attrs={key: "v"}))
    assert exc.code == "xml.write_bad_name" and exc.params["name"] == key
    assert exc.params["where"] == f"window[w]@{key}"
    assert f"'{key}'" in exc.message


@pytest.mark.parametrize(
    ("build", "key"),
    [
        (lambda: widget_doc(extra_attrs={"class": "x"}), "class"),
        (lambda: widget_doc(extra_attrs={"id": "x"}), "id"),
        (lambda: widget_doc(extra_attrs={"bind": "x"}), "bind"),
        (lambda: widget_doc(placement=GridCell(row=0, column=0, extra_attrs={"row": "1"})), "row"),
        (lambda: widget_doc(placement=PackPlacement(extra_attrs={"fill": "x"})), "fill"),
        (lambda: window_doc(props={"a": Prop(name="a", extra_attrs={"name": "b"})}), "name"),
        (
            lambda: window_doc(props={"a": Prop(name="a", extra_attrs={"translatable": "b"})}),
            "translatable",
        ),
        (lambda: window_doc(layout=Layout(type="pack", extra_attrs={"gap": "1"})), "gap"),
        (lambda: Document(extra_attrs={"schema_version": "9"}), "schema_version"),
    ],
)
def test_extra_attribute_clashing_with_a_known_one_is_refused(
    build: Callable[[], Document], key: str
) -> None:
    exc = refusal(build())
    assert exc.code == "xml.write_bad_name" and exc.params["name"] == key


def test_extra_attribute_names_are_checked_on_every_element_kind() -> None:
    document = Document()
    window = Window(id="w")
    window.menubar = Menubar(extra_attrs={"a b": "1"})
    document.add_window(window)
    assert refusal(document).code == "xml.write_bad_name"
    window.menubar = None
    window.statusbar = Statusbar(id="s", extra_attrs={"a b": "1"})
    assert refusal(document).code == "xml.write_bad_name"


@pytest.mark.parametrize(
    "namespaces",
    [
        {"xml": NS_X},
        {"xmlns": NS_X},
        {"1a": NS_X},
        {"a b": NS_X},
        {"a:b": NS_X},
        {"a": ""},
        {"a": "http://www.w3.org/XML/1998/namespace"},
        {"a": "http://www.w3.org/2000/xmlns/"},
    ],
)
def test_bad_namespace_declarations_are_refused(namespaces: dict[str, str]) -> None:
    exc = refusal(Document(namespaces=namespaces))
    assert exc.code == "xml.write_bad_namespace"
    assert exc.params["prefix"] == next(iter(namespaces))
    assert "is not valid" in exc.message


@pytest.mark.parametrize(
    "xml",
    [
        "<broken",
        "",
        "plain text",
        '<a xmlns="urn:x"/><b xmlns="urn:x"/>',
        '<a xmlns="urn:x"><!-- c --></a>',
        '<a xmlns="urn:x"><?pi?></a>',
        "<a/>",
        '<!DOCTYPE a><a xmlns="urn:x"/>',
        '<a xmlns="urn:x">&undefined;</a>',
        '<a xmlns="urn:x">\ud800</a>',
    ],
)
def test_damaged_raw_xml_is_refused(xml: str) -> None:
    exc = refusal(window_doc(extra_children=[RawXml(xml=xml)]))
    assert exc.code == "xml.write_bad_raw" and exc.params["where"] == "window[w]"
    assert "is damaged" in exc.message


def test_raw_xml_extra_attrs_are_refused() -> None:
    exc = refusal(
        window_doc(extra_children=[RawXml(xml='<a:b xmlns:a="u"/>', extra_attrs={"k": "v"})])
    )
    assert exc.code == "xml.write_bad_raw" and "extra_attrs" in exc.message


def test_raw_xml_names_its_owner_in_every_slot() -> None:
    raw = RawXml(xml="<broken")
    cases: list[tuple[Document, str]] = []
    document = Document()
    document.meta.extra_children.append(raw)
    cases.append((document, "meta"))
    document = Document(extra_children=[raw])
    cases.append((document, "pyguibud-ui"))
    document = Document(resources_extra=ContainerExtras(extra_children=(raw,)))
    cases.append((document, "resources"))
    document = Document(variables_extra=ContainerExtras(extra_children=(raw,)))
    cases.append((document, "variables"))
    cases.append((widget_doc(extra_children=[raw]), "window[w]/widget[x]"))
    cases.append(
        (
            widget_doc(placement=GridCell(row=0, column=0, extra_children=(raw,))),
            "window[w]/widget[x]/cell",
        )
    )
    cases.append(
        (
            widget_doc(events=[Event(name="change", handler="h", extra_children=(raw,))]),
            "window[w]/widget[x]/event[change]",
        )
    )
    cases.append(
        (window_doc(layout=Layout(type="grid", extra_children=(raw,))), "window[w]/layout")
    )
    for bad, where in cases:
        exc = refusal(bad)
        assert exc.code == "xml.write_bad_raw" and exc.params["where"] == where


@pytest.mark.parametrize(
    "build",
    [
        lambda: window_doc(props={"a": Prop(name="b")}),
        lambda: widget_doc(props={"a": Prop(name="b")}),
        lambda: Document(resources={"a": ImageResource(id="b", src="s")}),
        lambda: Document(variables={"a": Variable(id="b", type="int")}),
    ],
)
def test_key_mismatch_is_refused(build: Callable[[], Document]) -> None:
    exc = refusal(build())
    assert exc.code == "xml.write_key_mismatch"
    assert exc.params["key"] == "a" and exc.params["name"] == "b"
    assert "does not match" in exc.message


@pytest.mark.parametrize("version", ["1.1", "1.7", "2.0", "10.0"])
def test_newer_version_is_read_only(version: str) -> None:
    exc = refusal(Document(schema_version=version))
    assert exc.code == "xml.read_only" and exc.params == {"version": version, "current": "1.0"}


@pytest.mark.parametrize(
    "version", ["0.9", "0.0", "abc", "", "1", "1.0.0", "01.0", " 1.0", 1.0, None]
)
def test_other_versions_cannot_be_saved(version: object) -> None:
    exc = refusal(Document(schema_version=version))  # type: ignore[arg-type]
    assert exc.code == "xml.write_bad_version" and exc.params["current"] == "1.0"


def test_nesting_beyond_the_depth_limit_is_refused_and_the_limit_is_readable() -> None:
    def nested(count: int) -> Document:
        document = Document()
        window = Window(id="w")
        document.add_window(window)
        parent: Window | Widget = window
        for index in range(count):
            child = Widget(class_name="Frame", id=f"f{index}")
            parent.append_child(child)
            parent = child
        return document

    deepest = MAX_DEPTH - 2  # root=1, window=2
    data = dump_ui(nested(deepest))
    assert len(read_ui_bytes(data).document.children) == 1
    exc = refusal(nested(deepest + 1))
    assert exc.code == "xml.too_deep" and exc.params["limit"] == MAX_DEPTH


def test_raw_xml_depth_counts_towards_the_limit() -> None:
    levels = MAX_DEPTH - 2  # window is depth 2, so the fragment may use MAX_DEPTH - 2 levels
    ok = "<a:e xmlns:a='urn:x'>" + "<a:e>" * (levels - 1) + "</a:e>" * levels
    data = dump_ui(window_doc(extra_children=[RawXml(xml=ok)]))
    assert read_ui_bytes(data).warnings == ()
    bad = "<a:e xmlns:a='urn:x'>" + "<a:e>" * levels + "</a:e>" * (levels + 1)
    assert refusal(window_doc(extra_children=[RawXml(xml=bad)])).code == "xml.too_deep"


def test_output_larger_than_the_reader_limit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xml_io, "MAX_UI_BYTES", 200)
    exc = refusal(window_doc(props={"a": Prop(name="a", value="x" * 500)}))
    assert exc.code == "xml.too_large"


def test_error_messages_follow_the_language() -> None:
    from pyguibud import i18n

    exc = refusal(window_doc(kind="popup"))
    english = exc.message
    i18n.set_language("en_XA")
    try:
        assert exc.message != english and "popup" in exc.message
    finally:
        i18n.set_language("en_GB")


# --------------------------------------------------------------------------------------
# Atomic save
# --------------------------------------------------------------------------------------
@pytest.fixture
def hello_document() -> Document:
    return read_ui(HELLO).document


def listing(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def test_write_creates_the_file_with_canonical_bytes(
    tmp_path: Path, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    write_ui(hello_document, target)
    assert target.read_bytes() == HELLO.read_bytes() == dump_ui(hello_document)
    assert b"\r" not in target.read_bytes()
    assert listing(tmp_path) == ["hello.ui"]


def test_write_accepts_str_paths_and_relative_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    write_ui(hello_document, str(tmp_path / "a.ui"))
    monkeypatch.chdir(tmp_path)
    write_ui(hello_document, "b.ui")
    assert (tmp_path / "a.ui").read_bytes() == (tmp_path / "b.ui").read_bytes()
    assert listing(tmp_path) == ["a.ui", "b.ui"]


def test_second_save_keeps_the_previous_bytes_as_bak(
    tmp_path: Path, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"old content")
    write_ui(hello_document, target)
    assert (tmp_path / "hello.ui.bak").read_bytes() == b"old content"
    first = target.read_bytes()
    hello_document.meta.theme = "darkly"
    write_ui(hello_document, target)
    assert (tmp_path / "hello.ui.bak").read_bytes() == first != target.read_bytes()
    assert listing(tmp_path) == ["hello.ui", "hello.ui.bak"]


def test_first_save_makes_no_bak(tmp_path: Path, hello_document: Document) -> None:
    write_ui(hello_document, tmp_path / "new.ui")
    assert listing(tmp_path) == ["new.ui"]


def test_backup_false(tmp_path: Path, hello_document: Document) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"old")
    write_ui(hello_document, target, backup=False)
    assert listing(tmp_path) == ["hello.ui"] and target.read_bytes() == dump_ui(hello_document)


def test_a_save_roundtrips_through_the_reader(tmp_path: Path, hello_document: Document) -> None:
    write_ui(hello_document, tmp_path / "x.ui")
    assert structure(read_ui(tmp_path / "x.ui").document) == structure(hello_document)


def test_target_is_a_directory(tmp_path: Path, hello_document: Document) -> None:
    folder = tmp_path / "folder.ui"
    folder.mkdir()
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, folder)
    assert info.value.code == "xml.write_failed" and info.value.source == str(folder)
    assert info.value.params["reason"]
    assert listing(tmp_path) == ["folder.ui"] and list(folder.iterdir()) == []


def test_missing_parent_directory(tmp_path: Path, hello_document: Document) -> None:
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, tmp_path / "nope" / "x.ui")
    assert info.value.code == "xml.write_failed"
    assert isinstance(info.value.__cause__, OSError)
    assert listing(tmp_path) == []


def test_validation_failure_touches_nothing(tmp_path: Path) -> None:
    target = tmp_path / "keep.ui"
    target.write_bytes(b"original")
    bad = window_doc(props={"a": Prop(name="a", value="\x01")})
    with pytest.raises(XmlIoError) as info:
        write_ui(bad, target)
    assert info.value.code == "xml.illegal_char" and info.value.source == str(target)
    assert target.read_bytes() == b"original" and listing(tmp_path) == ["keep.ui"]


def test_read_only_document_cannot_be_saved(tmp_path: Path) -> None:
    result = read_ui_bytes(
        b'<?xml version="1.0"?>\n<pyguibud-ui schema_version="1.4" xmlns="urn:pyguibud:ui:1"/>'
    )
    target = tmp_path / "x.ui"
    with pytest.raises(XmlIoError) as info:
        write_ui(result.document, target)
    assert info.value.code == "xml.read_only" and listing(tmp_path) == []


def test_failure_at_replace_leaves_original_intact_and_no_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"precious")
    seen: list[str] = []

    def fail(src: Any, dst: Any) -> None:
        seen.append(os.fspath(src))
        assert os.path.exists(src), "the temporary file must exist before the replace"
        raise OSError(errno_value, "disk on fire")

    errno_value = 5
    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, target)
    exc = info.value
    assert exc.code == "xml.write_failed" and exc.source == str(target)
    assert exc.params["reason"] == "disk on fire" and "disk on fire" in exc.message
    assert isinstance(exc.__cause__, OSError)
    assert target.read_bytes() == b"precious"
    assert listing(tmp_path) == ["hello.ui", "hello.ui.bak"]  # no *.tmp left behind
    assert (tmp_path / "hello.ui.bak").read_bytes() == b"precious"
    name = Path(seen[0]).name
    assert name.startswith(".hello.ui.") and name.endswith(".tmp")
    assert Path(seen[0]).parent == tmp_path


def test_failure_while_writing_the_temp_file_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"precious")

    def fail(fd: int) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, target)
    assert info.value.code == "xml.write_failed" and "No space" in info.value.message
    assert target.read_bytes() == b"precious" and listing(tmp_path) == ["hello.ui"]


def test_failure_creating_the_temp_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"precious")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(xml_io, "create_temporary", fail)
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, target)
    assert info.value.code == "xml.write_failed" and "Permission denied" in info.value.message
    assert target.read_bytes() == b"precious" and listing(tmp_path) == ["hello.ui"]


def test_failure_making_the_backup_leaves_everything_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    target = tmp_path / "hello.ui"
    target.write_bytes(b"precious")
    (tmp_path / "hello.ui.bak").write_bytes(b"older backup")

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("shutil.copy2", fail)
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, target)
    assert info.value.code == "xml.write_failed"
    assert target.read_bytes() == b"precious"
    assert (tmp_path / "hello.ui.bak").read_bytes() == b"older backup"
    assert listing(tmp_path) == ["hello.ui", "hello.ui.bak"]


def test_replace_retries_on_permission_error_and_succeeds_on_the_third_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    real_replace = os.replace
    attempts: list[int] = []
    sleeps: list[float] = []

    def flaky(src: Any, dst: Any) -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError(13, "locked by the indexer")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky)
    monkeypatch.setattr(xml_io.time, "sleep", sleeps.append)  # type: ignore[attr-defined]
    target = tmp_path / "hello.ui"
    write_ui(hello_document, target)
    assert len(attempts) == 3 and len(sleeps) == 2 and all(0 < s <= 0.1 for s in sleeps)
    assert target.read_bytes() == dump_ui(hello_document) and listing(tmp_path) == ["hello.ui"]


def test_replace_gives_up_after_six_attempts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    attempts: list[int] = []

    def locked(src: Any, dst: Any) -> None:
        attempts.append(1)
        raise PermissionError(13, "locked")

    monkeypatch.setattr(os, "replace", locked)
    monkeypatch.setattr(xml_io.time, "sleep", lambda s: None)  # type: ignore[attr-defined]
    target = tmp_path / "hello.ui"
    target.write_bytes(b"precious")
    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, target)
    assert info.value.code == "xml.write_failed" and len(attempts) == 6
    assert target.read_bytes() == b"precious" and not [
        n for n in listing(tmp_path) if n.endswith(".tmp")
    ]


def test_non_permission_errors_are_not_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    attempts: list[int] = []

    def broken(src: Any, dst: Any) -> None:
        attempts.append(1)
        raise OSError(5, "I/O error")

    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(XmlIoError):
        write_ui(hello_document, tmp_path / "x.ui")
    assert len(attempts) == 1


def test_read_only_target_is_translated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hello_document: Document
) -> None:
    monkeypatch.setattr(xml_io.time, "sleep", lambda s: None)  # type: ignore[attr-defined]
    target = tmp_path / "locked.ui"
    target.write_bytes(b"precious")
    if sys.platform == "win32":
        os.chmod(target, stat.S_IREAD)  # Windows refuses to replace a read-only file
        folder: Path | None = None
    else:
        if os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        folder = tmp_path
        os.chmod(folder, stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(XmlIoError) as info:
            write_ui(hello_document, target)
        assert info.value.code == "xml.write_failed" and info.value.source == str(target)
        assert info.value.params["reason"]
        assert isinstance(info.value.__cause__, OSError)
        assert target.read_bytes() == b"precious"
    finally:
        os.chmod(target, stat.S_IREAD | stat.S_IWRITE)
        if folder is not None:
            os.chmod(folder, stat.S_IRWXU)
    assert not [n for n in listing(tmp_path) if n.endswith(".tmp")]


def test_write_failed_message_is_translated_but_code_is_not(
    tmp_path: Path, hello_document: Document
) -> None:
    from pyguibud import i18n

    with pytest.raises(XmlIoError) as info:
        write_ui(hello_document, tmp_path)
    english = info.value.message
    i18n.set_language("en_XA")
    try:
        assert info.value.message != english and info.value.code == "xml.write_failed"
    finally:
        i18n.set_language("en_GB")
