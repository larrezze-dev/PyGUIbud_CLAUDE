"""Round trips: golden files, byte idempotence and hypothesis properties."""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.core import (
    NS_TB,
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
    Prop,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    Window,
    dump_ui,
    read_ui,
    read_ui_bytes,
    write_ui,
    xmltree,
)

from .xml_helpers import DATA, HELLO, doc, structure

EXAMPLES = sorted((HELLO.parent).glob("*.ui"))
GOLDEN = sorted(DATA.glob("*.in.ui"))
NS_XML = "http://www.w3.org/XML/1998/namespace"


# --------------------------------------------------------------------------------------
# Golden files and byte idempotence
# --------------------------------------------------------------------------------------
def test_golden_pairs_exist() -> None:
    assert len(GOLDEN) >= 5
    for path in GOLDEN:
        assert path.with_name(path.name.replace(".in.ui", ".out.ui")).is_file(), path


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name.removesuffix(".in.ui"))
def test_golden_input_produces_the_expected_canonical_bytes(path: Any) -> None:
    expected = path.with_name(path.name.replace(".in.ui", ".out.ui")).read_bytes()
    assert dump_ui(read_ui(path).document) == expected
    assert b"\r" not in expected and expected.endswith(b"\n") and not expected.endswith(b"\n\n")


@pytest.mark.parametrize("path", GOLDEN, ids=lambda p: p.name.removesuffix(".in.ui"))
def test_golden_output_is_canonical(path: Any) -> None:
    out = path.with_name(path.name.replace(".in.ui", ".out.ui"))
    assert dump_ui(read_ui(out).document) == out.read_bytes()


@pytest.mark.parametrize("path", [*GOLDEN, *EXAMPLES], ids=lambda p: p.name)
def test_byte_idempotence(path: Any) -> None:
    first = dump_ui(read_ui(path).document)
    second = dump_ui(read_ui_bytes(first).document)
    third = dump_ui(read_ui_bytes(second).document)
    assert second == first == third


@pytest.mark.parametrize("path", [*GOLDEN, *EXAMPLES], ids=lambda p: p.name)
def test_model_is_stable_across_a_round_trip(path: Any) -> None:
    document = read_ui(path).document
    again = read_ui_bytes(dump_ui(document)).document
    first, second = structure(document), structure(again)
    assert isinstance(first, dict) and isinstance(second, dict)
    # the reader adds the prefixes the writer generated, so only compare the rest exactly
    first_ns, second_ns = first.pop("namespaces"), second.pop("namespaces")
    assert first == second
    assert first_ns.items() <= second_ns.items()


def test_hello_is_canonical() -> None:
    data = HELLO.read_bytes()
    assert dump_ui(read_ui(HELLO).document) == data
    assert b"\r" not in data and data.endswith(b"</pyguibud-ui>\n")


def test_every_example_is_canonical_and_warning_free() -> None:
    assert HELLO in EXAMPLES
    for path in EXAMPLES:
        result = read_ui(path)
        assert result.warnings == (), path
        assert dump_ui(result.document) == path.read_bytes(), path


def test_foreign_golden_only_has_the_two_expected_warnings() -> None:
    result = read_ui(DATA / "foreign.in.ui")
    assert [w.code for w in result.warnings] == ["xml.unknown_element", "xml.unknown_attribute"]
    assert [w.line for w in result.warnings] == [11, 12]


def test_special_characters_golden_values() -> None:
    props = read_ui(DATA / "special_chars.in.ui").document.children[0].children[0].props  # type: ignore[union-attr]
    assert props["a"].value == "  leading and trailing  "
    assert props["b"].value == "line one\nline two\n\ttabbed"
    assert props["c"].value == "   "
    assert props["d"].value == "& < > ]]> \"quoted\" 'single'"
    assert props["e"].value == "<raw & text>"
    assert props["f"].context == 'a\nb\tc\rd "q" <&' and props["f"].comment == "x > y"
    assert props["f"].value == "Zażółć ü ñ €"
    assert props["g"].value == props["h"].value == ""


def test_crlf_bom_and_lf_variants_converge_on_the_golden_output() -> None:
    source = (DATA / "full.in.ui").read_bytes()
    expected = (DATA / "full.out.ui").read_bytes()
    for variant in (
        source,
        source.replace(b"\n", b"\r\n"),
        b"\xef\xbb\xbf" + source,
        b"\xef\xbb\xbf" + source.replace(b"\n", b"\r\n"),
    ):
        assert dump_ui(read_ui_bytes(variant).document) == expected


def test_foreign_declared_only_locally_is_hoisted_and_then_stable() -> None:
    body = '<window id="w">\n<a:x xmlns:a="urn:a"/>\n<b:y xmlns:b="urn:b" b:k="1"/>\n</window>'
    first = dump_ui(read_ui_bytes(doc(body)).document)
    assert b'xmlns:a="urn:a"' in first and b'xmlns:b="urn:b"' in first
    assert dump_ui(read_ui_bytes(first).document) == first


def test_written_file_survives_a_disk_round_trip(tmp_path: Any) -> None:
    document = read_ui(DATA / "foreign.in.ui").document
    target = tmp_path / "foreign.ui"
    write_ui(document, target)
    assert target.read_bytes() == (DATA / "foreign.out.ui").read_bytes()
    write_ui(read_ui(target).document, target)
    assert target.read_bytes() == (DATA / "foreign.out.ui").read_bytes()
    assert (tmp_path / "foreign.ui.bak").read_bytes() == (DATA / "foreign.out.ui").read_bytes()


# --------------------------------------------------------------------------------------
# Duplicate-URI prefixes: the writer keeps the smallest prefix per URI (spec §7)
# --------------------------------------------------------------------------------------


def _duplicate_document(first: str, second: str) -> Document:
    return Document(
        namespaces={"": NS_UI, first: "urn:a", second: "urn:a"},
        extra_attrs={"{urn:a}k": "1"},
        extra_children=[
            RawXml(
                xml=(
                    f'<{first}:e xmlns:{first}="urn:a">'
                    f'<{second}:f xmlns:{second}="urn:a"/></{first}:e>'
                )
            )
        ],
    )


def test_duplicate_uri_prefixes_are_normalised_and_byte_stable() -> None:
    document = _duplicate_document("a", "b")
    first = dump_ui(document)
    text = first.decode()
    assert text.count('="urn:a"') == 1, "only one prefix may be declared for the URI"
    assert dump_ui(read_ui_bytes(first).document) == first
    assert dump_ui(read_ui_bytes(dump_ui(read_ui_bytes(first).document)).document) == first


def test_duplicate_uri_prefixes_use_one_prefix_for_every_use() -> None:
    text = dump_ui(_duplicate_document("a", "b")).decode()
    used = {chunk[:1] for chunk in text.replace("<", " ").split() if ":" in chunk[:3]}
    assert "a:k=" in text and "<a:e>" in text and "<a:f/>" in text
    assert "b:" not in text.replace("xmlns:b=", "")
    assert used


def test_duplicate_uri_winner_is_the_smallest_prefix() -> None:
    # "zz" is inserted first but sorts last: the winner is "aa" (code-point order, not insertion).
    text = dump_ui(_duplicate_document("zz", "aa")).decode()
    assert "<aa:e>" in text and "<aa:f/>" in text and "aa:k=" in text
    assert "zz:" not in text and text.count('="urn:a"') == 1
    again = dump_ui(read_ui_bytes(text.encode()).document).decode()
    assert again == text


def test_a_file_declaring_two_prefixes_for_one_uri_reads_and_saves(tmp_path: Any) -> None:
    body = '<a:x/>\n<b:y b:k="1"/>\n<window id="w" a:k="2"/>'
    data = doc(body, ' xmlns:a="urn:a" xmlns:b="urn:a"')
    result = read_ui_bytes(data)
    assert result.warnings == () and result.document.namespaces == {"": NS_UI, "a": "urn:a"}
    target = tmp_path / "dup.ui"
    write_ui(result.document, target)
    saved = target.read_bytes()
    assert (
        saved.count(b"urn:a") == 1
        and b"<a:x/>" in saved
        and b"<a:y" in saved
        and b'a:k="2"' in saved
    )
    assert dump_ui(read_ui(target).document) == saved


def test_prefix_bound_to_the_ui_namespace_is_byte_stable() -> None:
    document = Document(namespaces={"": NS_UI, "ui": NS_UI}, extra_attrs={f"{{{NS_UI}}}odd": "1"})
    first = dump_ui(document)
    assert dump_ui(read_ui_bytes(first).document) == first


@pytest.mark.parametrize(
    "namespaces",
    [
        # an ignored NS_UI prefix must not block the generated prefix it happens to look like
        {"": NS_UI, "ns1": NS_UI},
        # nor may a losing duplicate-URI prefix, which the reader never sees
        {"": NS_UI, "a": "urn:a", "ns1": "urn:a"},
        {"": NS_UI, "ns1": NS_UI, "ns2": "urn:a", "ns3": "urn:a", "zz": "urn:b"},
    ],
)
def test_ignored_prefixes_do_not_shift_generated_ones(namespaces: dict[str, str]) -> None:
    document = Document(
        namespaces=namespaces,
        extra_attrs={f"{{{NS_UI}}}odd": "1", "{urn:c}k": "2"},
        extra_children=[RawXml(xml='<q:e xmlns:q="urn:d"/>')],
    )
    first = dump_ui(document)
    assert dump_ui(read_ui_bytes(first).document) == first


# --------------------------------------------------------------------------------------
# Hypothesis
# --------------------------------------------------------------------------------------
_TEXT = st.text(
    alphabet=st.characters(
        blacklist_categories=("Cs",),  # type: ignore[arg-type]
        blacklist_characters=[
            chr(c) for c in (*range(0, 9), 11, 12, *range(14, 32), 0xFFFE, 0xFFFF)
        ],
    ),
    max_size=12,
)
_ODD_TEXT = st.sampled_from(
    [
        "",
        " ",
        "  ",
        "\n",
        "\r",
        "\r\n",
        "\t",
        "\u00a0",
        " x ",
        "a\nb",
        "&<>\"'",
        "]]>",
        "&#13;",
        "<![CDATA[x]]>",
    ]
)
_TEXTS = st.one_of(_TEXT, _ODD_TEXT)
_IDENT = st.from_regex(r"[a-z][a-z0-9_]{0,5}", fullmatch=True)
_CLASSES = st.sampled_from(
    ["Label", "Button", "Frame", "Entry", "tb:Meter", "acme:Gauge", "Notebook"]
)
_INT = st.integers(min_value=-999_999_999, max_value=999_999_999)
_SMALL = st.integers(min_value=0, max_value=50)
_URIS = ["urn:e1", "urn:e2", NS_TB, NS_XML]
_DECLARED = {"": NS_UI, "e1": "urn:e1", "e2": "urn:e2", "tb": NS_TB}
_PREFIX_POOL = {"e1": "urn:e1", "e2": "urn:e2", "tb": NS_TB, "q": "urn:q", "k": "urn:k"}


def _extra_attrs(uris: list[str]) -> st.SearchStrategy[dict[str, str]]:
    keys = st.one_of(
        _IDENT.map("x_{}".format),
        st.builds(lambda uri, name: f"{{{uri}}}{name}", st.sampled_from(uris), _IDENT),
    )
    return st.dictionaries(keys, _TEXTS, max_size=2)


@st.composite
def _fragment(draw: st.DrawFn, uris: list[str], namespaces: dict[str, str]) -> RawXml:
    """A canonical compact RawXml: foreign top element or an unknown NS_UI name."""

    def build(depth: int, top: bool) -> Any:
        import xml.etree.ElementTree as ET

        if top and draw(st.booleans()):
            tag = f"{{{NS_UI}}}zz{draw(_IDENT)}"
        else:
            tag = f"{{{draw(st.sampled_from(uris))}}}{draw(_IDENT)}"
        element = ET.Element(tag)
        for key, value in draw(_extra_attrs(uris)).items():
            element.set(key, value)
        children = (
            [build(depth + 1, False) for _ in range(draw(st.integers(0, 2)))] if depth < 2 else []
        )
        mode = draw(st.sampled_from(["empty", "text", "mixed"]))
        if not children:
            element.text = draw(_TEXTS) if mode != "empty" else None
        elif mode == "mixed":
            element.text = draw(_TEXTS)
            for child in children:
                child.tail = draw(_TEXTS)
        for child in children:
            element.append(child)
        return element

    element = build(0, True)
    canonical = xmltree.parse_fragment(xmltree.serialise_fragment(element, namespaces=namespaces))
    return RawXml(xml=xmltree.serialise_fragment(canonical, namespaces=namespaces))


@st.composite
def _documents(
    draw: st.DrawFn, *, undeclared: bool, namespaces: dict[str, str] | None = None
) -> Document:
    chosen = (
        dict(namespaces)
        if namespaces is not None
        else {
            "": NS_UI,
            **{p: u for p, u in _PREFIX_POOL.items() if draw(st.booleans())},
        }
    )
    declared_uris = [u for p, u in chosen.items() if p]
    pool = [*declared_uris, NS_XML]
    if undeclared:
        pool += ["urn:u1", "urn:u2", NS_UI]
    if not declared_uris:
        pool = [NS_XML] if not undeclared else pool
    uris = pool

    def extras() -> dict[str, str]:
        return draw(_extra_attrs(uris)) if draw(st.integers(0, 3)) == 0 else {}

    def raws() -> list[RawXml]:
        return (
            draw(st.lists(_fragment(uris, chosen), max_size=1))
            if draw(st.integers(0, 3)) == 0
            else []
        )

    def prop(name: str) -> Prop:
        return Prop(
            name=name,
            value=draw(_TEXTS),
            ref=draw(st.none() | _IDENT),
            translatable=draw(st.booleans()),
            context=draw(st.none() | _TEXTS),
            comment=draw(st.none() | _TEXTS),
            extra_attrs=extras(),
        )

    def props() -> dict[str, Prop]:
        names = draw(
            st.lists(
                st.sampled_from(["text", "title", "tip", "a", "Z", "_x"]), unique=True, max_size=3
            )
        )
        return {n: prop(n) for n in names}

    def line() -> GridLine:
        return GridLine(
            index=draw(_SMALL),
            weight=draw(_SMALL),
            minsize=draw(_SMALL),
            extra_attrs=extras(),
            extra_children=tuple(raws()),
        )

    def layout() -> Layout:
        return Layout(
            type=draw(st.sampled_from(["grid", "pack"])),
            orient=draw(st.sampled_from(["vertical", "horizontal"])),
            padding=draw(_SMALL),
            gap=draw(_SMALL),
            columns=tuple(line() for _ in range(draw(st.integers(0, 2)))),
            rows=tuple(line() for _ in range(draw(st.integers(0, 2)))),
            extra_children=tuple(raws()),
            extra_attrs=extras(),
        )

    def placement() -> Any:
        kind = draw(st.sampled_from(["none", "cell", "pack", "page"]))
        if kind == "cell":
            return GridCell(
                row=draw(_INT),
                column=draw(_SMALL),
                rowspan=draw(_SMALL),
                columnspan=draw(_SMALL),
                sticky=draw(st.sampled_from(["", "n", "nsew", "ew"])),
                padx=draw(_SMALL),
                pady=draw(_SMALL),
                extra_attrs=extras(),
                extra_children=tuple(raws()),
            )
        if kind == "pack":
            return PackPlacement(
                fill=draw(st.sampled_from(["none", "x", "y", "both"])),
                expand=draw(st.booleans()),
                padx=draw(_SMALL),
                pady=draw(_SMALL),
                extra_attrs=extras(),
                extra_children=tuple(raws()),
            )
        if kind == "page":
            text = prop("text") if draw(st.booleans()) else None
            return PagePlacement(
                text=text,
                image=draw(st.none() | _IDENT),
                weight=draw(_SMALL),
                extra_attrs=extras(),
                extra_children=tuple(raws()),
            )
        return None

    def widget(depth: int) -> Widget | Include:
        if draw(st.integers(0, 6)) == 0:
            return Include(
                id=draw(_IDENT),
                src=draw(_TEXTS),
                component=draw(_IDENT),
                placement=placement(),
                extra_attrs=extras(),
                extra_children=raws(),
            )
        node = Widget(
            class_name=draw(_CLASSES),
            id=draw(_IDENT),
            props=props(),
            events=[
                Event(
                    name=draw(st.sampled_from(["command", "change", "key:<Return>"])),
                    handler=draw(_IDENT),
                    extra_attrs=extras(),
                    extra_children=tuple(raws()),
                )
                for _ in range(draw(st.integers(0, 2)))
            ],
            bind=draw(st.none() | _IDENT),
            fallback=draw(st.none() | _IDENT),
            plugin=draw(st.none() | _IDENT),
            placement=placement(),
            layout=layout() if draw(st.booleans()) else None,
            extra_attrs=extras(),
            extra_children=raws(),
        )
        if depth < 2:
            for _ in range(draw(st.integers(0, 2))):
                node.append_child(widget(depth + 1))
        return node

    def menu(depth: int) -> Menu:
        node = Menu(id=draw(_IDENT), props=props(), extra_attrs=extras(), extra_children=raws())
        for _ in range(draw(st.integers(0, 3))):
            kind = (
                draw(st.sampled_from(["action", "separator", "menu"]))
                if depth < 2
                else draw(st.sampled_from(["action", "separator"]))
            )
            if kind == "action":
                node.append_child(
                    Action(
                        id=draw(_IDENT),
                        props=props(),
                        handler=draw(st.none() | _IDENT),
                        shortcut=draw(st.none() | _IDENT),
                        extra_attrs=extras(),
                        extra_children=raws(),
                    )
                )
            elif kind == "separator":
                node.append_child(MenuSeparator(extra_attrs=extras(), extra_children=raws()))
            else:
                node.append_child(menu(depth + 1))
        return node

    document = Document(
        namespaces=chosen,
        meta=Meta(
            generator=draw(_TEXTS),
            source_locale=draw(st.sampled_from(["en_GB", "de_DE", ""])),
            i18n_domain=draw(_TEXTS),
            theme=draw(_TEXTS),
            extra_attrs=extras(),
            extra_children=raws(),
        ),
        extra_attrs=extras(),
        extra_children=raws(),
    )
    for ident in draw(st.lists(_IDENT, unique=True, max_size=2)):
        document.resources[ident] = ImageResource(
            id=ident, src=draw(_TEXTS), extra_attrs=extras(), extra_children=tuple(raws())
        )
    for ident in draw(st.lists(_IDENT, unique=True, max_size=2)):
        document.variables[ident] = Variable(
            id=ident,
            type=draw(st.sampled_from(["string", "int", "double", "bool"])),
            default=draw(_TEXTS),
            extra_attrs=extras(),
            extra_children=tuple(raws()),
        )
    document.resources_extra = ContainerExtras(extra_attrs=extras(), extra_children=tuple(raws()))
    document.variables_extra = ContainerExtras(extra_attrs=extras(), extra_children=tuple(raws()))
    for _ in range(draw(st.integers(0, 3))):
        window = Window(
            id=draw(_IDENT),
            kind=draw(st.sampled_from(["main", "dialog", "component"])),
            props=props(),
            layout=layout() if draw(st.booleans()) else None,
            min_width=draw(st.none() | _INT),
            min_height=draw(st.none() | _SMALL),
            modal=draw(st.booleans()),
            buttons=draw(st.none() | _TEXTS),
            extra_attrs=extras(),
            extra_children=raws(),
        )
        if draw(st.booleans()):
            window.menubar = Menubar(extra_attrs=extras(), extra_children=raws())
            for _ in range(draw(st.integers(0, 2))):
                window.menubar.append_child(menu(0))
        if draw(st.booleans()):
            window.statusbar = Statusbar(
                id=draw(_IDENT), props=props(), extra_attrs=extras(), extra_children=raws()
            )
        for _ in range(draw(st.integers(0, 3))):
            window.append_child(widget(0))
        document.add_window(window)
    return document


_SETTINGS = settings(
    max_examples=60,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.data_too_large,
        HealthCheck.large_base_example,
    ],
)


def _check_stable(document: Document) -> bytes:
    first = dump_ui(document)
    second = dump_ui(read_ui_bytes(first).document)
    assert second == first
    return first


@_SETTINGS
@given(_documents(undeclared=False))
def test_property_model_dump_read_is_lossless_and_stable(document: Document) -> None:
    before = structure(document)
    first = _check_stable(document)
    assert structure(document) == before, "dump_ui must not mutate the document"
    reread = read_ui_bytes(first).document
    assert structure(reread.children) == structure(document.children)
    for field in (
        "meta",
        "resources",
        "variables",
        "extra_attrs",
        "extra_children",
        "resources_extra",
        "variables_extra",
    ):
        assert structure(getattr(reread, field)) == structure(getattr(document, field)), field
    # the reader adds generated prefixes, so its map is a superset of the model's
    assert document.namespaces.items() <= reread.namespaces.items() | {("", NS_UI)}


@_SETTINGS
@given(_documents(undeclared=True))
def test_property_undeclared_namespaces_are_byte_stable(document: Document) -> None:
    # URIs without a declared prefix get generated ones (ns1...), which the file then declares.
    _check_stable(document)


# Two prefixes for one URI, plus a prefix bound to NS_UI; "ns1" may be any of them, so an
# ignored entry would shift the generated prefixes (undeclared URIs and NS_UI attributes).
_DUP = st.permutations(["a", "ns1", "c", "zz"]).map(
    lambda p: {"": NS_UI, p[0]: "urn:dup", p[1]: "urn:dup", p[2]: "urn:x", p[3]: NS_UI}
)


@settings(parent=_SETTINGS, max_examples=50)
@given(
    _DUP.flatmap(
        lambda ns: _documents(undeclared=True, namespaces={**ns, "tb": NS_TB, "e1": "urn:e1"}).map(
            lambda d: (ns, d)
        )
    )
)
def test_property_duplicate_uri_prefixes_are_byte_stable(
    pair: tuple[dict[str, str], Document],
) -> None:
    _, document = pair
    _check_stable(document)


def test_property_strategy_actually_exercises_the_interesting_cases() -> None:
    # Guard against a strategy that silently degenerates into trivial documents.
    seen: dict[str, int] = {"windows": 0, "widgets": 0, "raws": 0, "pages": 0, "menus": 0}

    @settings(max_examples=40, deadline=None, suppress_health_check=list(HealthCheck))
    @given(_documents(undeclared=False))
    def run(document: Document) -> None:
        seen["windows"] += len(document.children)
        for node in document.walk():
            seen["widgets"] += isinstance(node, Widget)
            seen["menus"] += isinstance(node, Menu)
            seen["pages"] += isinstance(getattr(node, "placement", None), PagePlacement)
            seen["raws"] += len(getattr(node, "extra_children", ()))

    run()
    assert all(count >= 3 for count in seen.values()), seen
