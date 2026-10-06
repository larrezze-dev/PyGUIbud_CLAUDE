"""Tests for ``pyguibud.core.model``."""

from __future__ import annotations

import string
from collections.abc import Callable
from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud import i18n
from pyguibud.core import (
    ABSTRACT_EVENTS,
    KNOWN_NAMESPACES,
    NS_TB,
    NS_UI,
    WIDGET_API_VERSION,
    Action,
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
    ModelError,
    PackPlacement,
    PagePlacement,
    Prop,
    PropertyDef,
    RawXml,
    Statusbar,
    Variable,
    Widget,
    WidgetSpec,
    Window,
    is_extension,
    is_valid_event,
    qualify,
    split_class_name,
)


def _w(wid: str, cls: str = "Frame") -> Widget:
    return Widget(class_name=cls, id=wid)


# ------------------------------------------------------------------ constants
def test_constants() -> None:
    assert NS_UI == "urn:pyguibud:ui:1"
    assert KNOWN_NAMESPACES == {"tb": NS_TB}
    assert WIDGET_API_VERSION == 1
    assert {"command", "change", "select", "activate", "focus_in", "focus_out"} == ABSTRACT_EVENTS
    with pytest.raises(TypeError):
        KNOWN_NAMESPACES["x"] = "y"  # type: ignore[index]


# ------------------------------------------------------------------ value objects
_VALUE_OBJECTS: list[Callable[[], Any]] = [
    lambda: RawXml(xml="<a/>"),
    lambda: Prop(name="text", value="x"),
    lambda: Event(name="command", handler="on_x"),
    lambda: GridCell(row=0, column=0),
    lambda: PackPlacement(),
    lambda: PagePlacement(),
    lambda: GridLine(index=0),
    lambda: Layout(type="grid"),
    lambda: Variable(id="v", type="int"),
    lambda: ImageResource(id="i", src="a.png"),
]


@pytest.mark.parametrize("factory", _VALUE_OBJECTS)
def test_value_objects_frozen_and_extra_attrs_readonly(factory: Callable[[], Any]) -> None:
    obj = factory()
    with pytest.raises(FrozenInstanceError):
        obj.extra_attrs = {}
    with pytest.raises(TypeError):
        obj.extra_attrs["k"] = "v"


def test_value_object_field_assignment_blocked() -> None:
    prop = Prop(name="text", value="x")
    with pytest.raises(FrozenInstanceError):
        prop.value = "y"  # type: ignore[misc]


def test_value_objects_hashable_and_equal() -> None:
    a = Prop(name="text", value="x", extra_attrs={"q": "1"})
    b = Prop(name="text", value="x", extra_attrs={"q": "1"})
    assert a == b
    assert hash(a) == hash(b)
    assert Prop(name="text", value="y") != a
    assert len({GridCell(row=1, column=2), GridCell(row=1, column=2)}) == 1
    assert isinstance(hash(Layout(type="pack", columns=(GridLine(index=0),))), int)


def test_extra_attrs_copied_from_input() -> None:
    src = {"a": "1"}
    prop = Prop(name="n", extra_attrs=src)
    src["a"] = "2"
    assert prop.extra_attrs["a"] == "1"


def test_value_defaults() -> None:
    assert GridCell(row=0, column=1).rowspan == 1
    assert PackPlacement().fill == "none"
    assert PackPlacement().expand is False
    assert Layout(type="pack").orient == "vertical"
    assert Prop(name="n").translatable is False
    assert Prop(name="n").ref is None
    page = PagePlacement(text=Prop(name="text", value="Tab", translatable=True), weight=2)
    assert page.text is not None
    assert page.text.value == "Tab"
    assert page.weight == 2
    assert page.image is None


# ------------------------------------------------------------------ class names
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Button", (None, "Button")),
        ("tb:Meter", ("tb", "Meter")),
        ("my-co:Fancy_Box2", ("my-co", "Fancy_Box2")),
        ("a1_b:X", ("a1_b", "X")),
    ],
)
def test_split_class_name_valid(name: str, expected: tuple[str | None, str]) -> None:
    assert split_class_name(name) == expected


@pytest.mark.parametrize(
    "name",
    [
        "",
        "button",
        "1Button",
        "tb:",
        ":Meter",
        "tb:meter",
        "a:b:C",
        "TB:Meter",
        "tb :Meter",
        "tb:Me ter",
        "Bu-tton",
        "tb:Me-ter",
        "1b:Meter",
        "Button\n",
        "tb:Meter\n",
    ],
)
def test_split_class_name_invalid(name: str) -> None:
    with pytest.raises(ModelError) as info:
        split_class_name(name)
    assert info.value.code == "model.bad_class_name"
    assert info.value.params["name"] == name


def test_bad_class_name_message_translates() -> None:
    with pytest.raises(ModelError) as info:
        split_class_name("x")
    assert info.value.message == "'x' is not a valid widget class name."
    i18n.set_language("en_XA")
    assert info.value.message.startswith("[")


def test_qualify() -> None:
    assert qualify(None, "Button") == "Button"
    assert qualify("tb", "Meter") == "tb:Meter"
    for prefix, local in [("TB", "Meter"), ("tb", "meter"), (None, "x"), ("tb", "")]:
        with pytest.raises(ModelError) as info:
            qualify(prefix, local)
        assert info.value.code == "model.bad_class_name"


def test_is_extension() -> None:
    assert is_extension("tb:Meter")
    assert not is_extension("Button")
    assert is_extension("not valid:")
    assert not is_extension("")


_prefixes = st.from_regex(r"[a-z][a-z0-9_-]{0,8}", fullmatch=True)
_locals = st.from_regex(r"[A-Z][A-Za-z0-9_]{0,10}", fullmatch=True)


@given(prefix=st.one_of(st.none(), _prefixes), local=_locals)
def test_class_name_round_trip(prefix: str | None, local: str) -> None:
    name = qualify(prefix, local)
    assert split_class_name(name) == (prefix, local)
    assert is_extension(name) is (prefix is not None)


@given(st.text(alphabet=string.printable + "éß", max_size=20))
def test_split_class_name_total(name: str) -> None:
    """Either a clean split that re-qualifies to the same name, or a ModelError."""
    try:
        prefix, local = split_class_name(name)
    except ModelError as exc:
        assert exc.code == "model.bad_class_name"
    else:
        assert qualify(prefix, local) == name


# ------------------------------------------------------------------ events
@pytest.mark.parametrize(
    "name", [*sorted(ABSTRACT_EVENTS), "key:Return", "key:<Control-s>", "key:F5"]
)
def test_valid_events(name: str) -> None:
    assert is_valid_event(name)


@pytest.mark.parametrize(
    "name",
    [
        "",
        "click",
        "Command",
        "key:",
        "key",
        "key:Control s",
        "key:\t",
        "key:a\x00",
        "key: Return",
        "key:Return\n",
    ],
)
def test_invalid_events(name: str) -> None:
    assert not is_valid_event(name)


# ------------------------------------------------------------------ tree
def _tree() -> tuple[Document, Window, Widget, Widget, Widget]:
    doc = Document()
    win = Window(id="main")
    doc.add_window(win)
    frame, label, button = _w("frame"), _w("label", "Label"), _w("button", "Button")
    win.append_child(frame)
    frame.append_child(label)
    frame.append_child(button)
    return doc, win, frame, label, button


def test_parent_back_references() -> None:
    doc, win, frame, label, _button = _tree()
    assert win.parent is doc
    assert frame.parent is win
    assert label.parent is frame
    assert list(label.ancestors()) == [frame, win, doc]
    assert label.window is win
    assert frame.window is win
    assert win.document is doc
    assert doc.main_window is win


def test_detached_nodes() -> None:
    assert _w("x").window is None
    assert Window(id="w").document is None
    assert Document().main_window is None
    assert list(_w("x").ancestors()) == []


def test_main_window_picks_first_main() -> None:
    doc = Document()
    doc.add_window(Window(id="d", kind="dialog"))
    m1, m2 = Window(id="m1"), Window(id="m2")
    doc.add_window(m1)
    doc.add_window(m2)
    assert doc.main_window is m1


def test_children_is_read_only_snapshot() -> None:
    _doc, _win, frame, label, button = _tree()
    assert frame.children == (label, button)
    assert isinstance(frame.children, tuple)


def test_insert_index_move_remove() -> None:
    _doc, _win, frame, label, button = _tree()
    extra = _w("extra")
    frame.insert_child(0, extra)
    assert frame.children == (extra, label, button)
    assert frame.index_of(button) == 2
    assert frame.move_child(button, 0) == 2
    assert frame.children == (button, extra, label)
    assert frame.remove_child(extra) == 1
    assert extra.parent is None
    assert list(frame.children) == [button, label]
    with pytest.raises(ModelError) as info:
        frame.index_of(extra)
    assert info.value.code == "model.not_a_child"
    with pytest.raises(ModelError):
        frame.remove_child(extra)
    with pytest.raises(ModelError):
        frame.move_child(extra, 0)


def test_index_of_uses_identity_not_equality() -> None:
    _doc, _win, frame, label, _button = _tree()
    twin = Widget(class_name="Label", id="label")
    with pytest.raises(ModelError):
        frame.index_of(twin)
    assert frame.index_of(label) == 0


def test_reparenting_requires_remove_first() -> None:
    _doc, win, frame, label, _button = _tree()
    other = _w("other")
    win.append_child(other)
    with pytest.raises(ModelError) as info:
        other.append_child(label)
    assert info.value.code == "model.already_parented"
    assert label.parent is frame
    assert frame.children[0] is label
    frame.remove_child(label)
    other.append_child(label)
    assert label.parent is other
    assert label.window is win
    assert label not in list(frame.walk())


def test_cycle_rejected() -> None:
    a, b, c = _w("a"), _w("b"), _w("c")
    a.append_child(b)
    b.append_child(c)
    with pytest.raises(ModelError) as info:
        c.append_child(a)
    assert info.value.code == "model.cycle"
    assert a.parent is None


def test_self_insert_cycle_code() -> None:
    a = _w("a")
    with pytest.raises(ModelError) as info:
        a.append_child(a)
    assert info.value.code == "model.cycle"


def test_bad_child_types() -> None:
    doc, win, _frame, _label, _button = _tree()
    cases: list[tuple[Any, Any]] = [
        (doc, _w("w")),
        (win, Window(id="w2")),
        (win, Menu(id="m")),
        (_w("p"), Action(id="a")),
        (Menubar(), _w("w")),
        (Menu(id="m"), _w("w")),
    ]
    for parent, child in cases:
        with pytest.raises(ModelError) as info:
            parent.append_child(child)
        assert info.value.code == "model.bad_child"
        assert getattr(child, "parent", None) is None


def test_failed_insert_leaves_tree_intact() -> None:
    _doc, win, frame, _l, _b = _tree()
    before = win.children
    with pytest.raises(ModelError):
        win.append_child(Menu(id="m"))  # type: ignore[arg-type]
    assert win.children == before
    assert frame.parent is win


def test_walk_order_preorder() -> None:
    doc, win, frame, label, button = _tree()
    inc = Include(id="inc", src="c.ui", component="c")
    win.append_child(inc)
    assert list(doc.walk()) == [doc, win, frame, label, button, inc]
    assert list(frame.walk()) == [frame, label, button]
    assert inc.parent is win


def test_window_walk_includes_menubar_and_statusbar() -> None:
    doc = Document()
    win = Window(id="main", menubar=Menubar(), statusbar=Statusbar(id="sb"))
    doc.add_window(win)
    assert win.menubar is not None
    file_menu = Menu(id="file")
    win.menubar.append_child(file_menu)
    sub = Menu(id="recent")
    file_menu.append_child(sub)
    action = Action(id="open", handler="on_open", shortcut="Ctrl+O")
    file_menu.append_child(action)
    sep = MenuSeparator()
    file_menu.append_child(sep)
    body = _w("body")
    win.append_child(body)
    nodes = list(doc.walk())
    assert nodes[:2] == [doc, win]
    assert nodes[2] is win.menubar
    assert nodes[3:7] == [file_menu, sub, action, sep]
    assert nodes[7] is win.statusbar
    assert nodes[8] is body
    assert action.parent is file_menu
    assert sub.parent is file_menu
    assert file_menu.parent is win.menubar
    assert list(action.ancestors())[:2] == [file_menu, win.menubar]
    assert sep.parent is file_menu


def test_menubar_and_statusbar_have_no_parent_attribute() -> None:
    assert not hasattr(Menubar(), "parent")
    assert not hasattr(Statusbar(id="s"), "parent")


def test_find_and_iter_ids() -> None:
    doc, win, frame, _label, button = _tree()
    doc.resources["img"] = ImageResource(id="img", src="a.png")
    doc.variables["v"] = Variable(id="v", type="string")
    assert doc.find("button") is button
    assert doc.find("main") is win
    assert doc.find("missing") is None
    ids = [i for i, _o in doc.iter_ids()]
    assert ids == ["main", "frame", "label", "button", "img", "v"]
    owners = dict(doc.iter_ids())
    assert owners["frame"] is frame
    assert isinstance(owners["img"], ImageResource)
    assert isinstance(owners["v"], Variable)


def test_iter_ids_keeps_duplicates() -> None:
    doc, win, _f, _l, _b = _tree()
    win.append_child(_w("button"))
    doc.variables["button"] = Variable(id="button", type="int")
    assert [i for i, _ in doc.iter_ids()].count("button") == 3


def test_find_covers_menus_and_statusbar() -> None:
    win = Window(id="w", menubar=Menubar(), statusbar=Statusbar(id="sb"))
    doc = Document()
    doc.add_window(win)
    assert win.menubar is not None
    win.menubar.append_child(Menu(id="m1"))
    assert isinstance(doc.find("m1"), Menu)
    assert isinstance(doc.find("sb"), Statusbar)


@given(st.lists(st.from_regex(r"[a-z][a-z0-9_]{0,6}", fullmatch=True), max_size=15))
def test_iter_ids_matches_walk(names: list[str]) -> None:
    doc = Document()
    win = Window(id="main")
    doc.add_window(win)
    parent: Widget | Window = win
    for index, name in enumerate(names):
        node = _w(name)
        parent.append_child(node)
        if index % 3 == 0:
            parent = node
    expected = ["main", *[n.id for n in win.walk() if isinstance(n, Widget)]]
    assert [i for i, _ in doc.iter_ids()] == expected
    for name in names:
        found = doc.find(name)
        assert found is not None
        assert getattr(found, "id", None) == name


@given(st.lists(st.integers(0, 5), max_size=12))
def test_random_mutations_keep_back_references_consistent(ops: list[int]) -> None:
    win = Window(id="w")
    pool = [_w(f"n{i}") for i in range(6)]
    for op in ops:
        node = pool[op]
        target = pool[(op + 1) % 6]
        try:
            if node.parent is None:
                (target if op % 2 else win).append_child(node)
            else:
                node.parent.remove_child(node)
        except ModelError:
            pass
    for n in win.walk():
        for child in getattr(n, "children", ()):
            assert child.parent is n
    seen = [id(n) for n in win.walk()]
    assert len(seen) == len(set(seen))


def test_document_window_helpers() -> None:
    doc = Document()
    a, b = Window(id="a"), Window(id="b")
    doc.add_window(a)
    doc.insert_window(0, b)
    assert doc.children == (b, a)
    assert doc.remove_window(b) == 0
    assert b.parent is None
    assert list(doc.children) == [a]


# ------------------------------------------------------------------ props
def test_set_and_remove_prop() -> None:
    w = _w("x")
    first = Prop(name="text", value="a")
    assert w.set_prop(first) is None
    assert w.set_prop(Prop(name="text", value="b")) == first
    assert w.props["text"].value == "b"
    assert w.remove_prop("text") == Prop(name="text", value="b")
    assert w.remove_prop("text") is None
    assert Menu(id="m").set_prop(first) is None
    assert Statusbar(id="s").set_prop(first) is None


# ------------------------------------------------------------------ extras preserved
def test_extra_attrs_and_raw_xml_kept_verbatim() -> None:
    raw = RawXml(xml='<x:y xmlns:x="urn:z" a="1"><k/></x:y>', extra_attrs={"a": "1"})
    w = Widget(
        class_name="tb:Meter",
        id="m",
        fallback="Progressbar",
        plugin="acme",
        extra_attrs={"x:flag": "1"},
        extra_children=[raw],
        layout=Layout(type="pack", extra_children=(raw,), extra_attrs={"z": "9"}),
    )
    assert w.extra_attrs == {"x:flag": "1"}
    assert w.extra_children[0].xml == raw.xml
    assert w.layout is not None
    assert w.layout.extra_children == (raw,)
    assert w.layout.extra_attrs["z"] == "9"
    doc = Document(extra_attrs={"q": "1"}, extra_children=[raw], meta=Meta(extra_attrs={"m": "2"}))
    assert doc.extra_attrs["q"] == "1"
    assert doc.meta.extra_attrs["m"] == "2"
    assert doc.namespaces == {"": NS_UI, "tb": NS_TB}
    doc.namespaces["x"] = "urn:z"
    assert "x" not in Document().namespaces  # defaults are not shared between documents


def test_nodes_compare_by_identity() -> None:
    assert _w("a") != _w("a")
    node = _w("a")
    assert node == node


def test_page_and_layout_placements() -> None:
    nb = _w("nb", "Notebook")
    page = _w("p1")
    page.placement = PagePlacement(text=Prop(name="text", value="One", translatable=True))
    nb.append_child(page)
    pane = _w("pane")
    pane.placement = PagePlacement(weight=3)
    ph = _w("ph", "PanedWindow")
    ph.append_child(pane)
    assert isinstance(nb.children[0].placement, PagePlacement)
    assert ph.children[0].placement == PagePlacement(weight=3)
    grid = _w("g")
    grid.placement = GridCell(row=1, column=2, sticky="nsew")
    pack = _w("k")
    pack.placement = PackPlacement(fill="both", expand=True)
    assert isinstance(grid.placement, GridCell)
    assert grid.placement.column == 2
    assert isinstance(pack.placement, PackPlacement)
    assert pack.placement.expand


# ------------------------------------------------------------------ PropertyDef / WidgetSpec
@pytest.mark.parametrize(
    "kwargs",
    [
        {"type": "enum"},
        {"type": "enum", "choices": ("a",), "default": "b"},
        {"type": "int", "choices": ("a",)},
        {"type": "int", "translatable": True},
    ],
)
def test_property_def_rejects_inconsistent(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ModelError) as info:
        PropertyDef(name="p", **kwargs)
    assert info.value.code == "model.bad_property_def"
    assert "'p'" in info.value.message


def test_property_def_valid_and_label() -> None:
    d = PropertyDef(
        name="state", type="enum", choices=("a", "b"), default="a", display_name="State"
    )
    assert d.label() == "State"
    assert PropertyDef(name="raw", type="string").label() == "raw"
    assert PropertyDef(name="e", type="enum", choices=("a",)).default is None
    assert PropertyDef(name="t", type="string", translatable=True).translatable
    i18n.set_language("en_XA")
    assert d.label() != "State"
    assert PropertyDef(name="raw", type="string").label() == "raw"


def _spec(**kw: Any) -> WidgetSpec:
    base: dict[str, Any] = {
        "name": "Frame",
        "display_name": "Frame",
        "category": "Containers",
        "api_version": 1,
    }
    base.update(kw)
    return WidgetSpec(**base)


def test_widget_spec_flags() -> None:
    assert _spec(children="layout").container
    assert _spec(children="pages").container
    assert not _spec(children="menu").container
    assert not _spec().container
    assert not _spec().is_extension
    assert _spec(name="tb:Meter").is_extension
    with pytest.raises(FrozenInstanceError):
        _spec().name = "x"  # type: ignore[misc]


def test_widget_spec_factories_readonly_and_ignored_in_eq() -> None:
    f = {"ttkbootstrap": lambda: 1}
    spec = _spec(factories=f)
    f["qt"] = lambda: 2
    assert "qt" not in spec.factories
    with pytest.raises(TypeError):
        spec.factories["qt"] = lambda: 3  # type: ignore[index]
    assert spec == _spec(factories={"other": lambda: 0})
    assert isinstance(hash(spec), int)


def test_widget_spec_label_and_category() -> None:
    spec = _spec(display_name="Label frame", category="Containers")
    assert spec.label() == "Label frame"
    assert spec.category_label() == "Containers"
    assert _spec(display_name="").label() == "Frame"
    assert _spec(category="").category_label() == ""
    i18n.set_language("en_XA")
    assert spec.label().startswith("[")
    assert spec.category_label().startswith("[")
    assert _spec(display_name="").label() == "Frame"
    assert _spec(category="").category_label() == ""


def test_widget_spec_property_lookup() -> None:
    d = PropertyDef(name="text", type="string")
    spec = _spec(properties=(d,))
    assert spec.property("text") is d
    assert spec.property("nope") is None
