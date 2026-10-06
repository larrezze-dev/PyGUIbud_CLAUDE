"""Tests of findings, source positions and node paths (``pyguibud.core.diagnostics``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pyguibud import i18n
from pyguibud.core import (
    NS_UI,
    Action,
    Document,
    Finding,
    GridCell,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    SourceMap,
    Statusbar,
    Variable,
    Widget,
    Window,
    XmlWarning,
    migrations,
    read_ui,
    read_ui_bytes,
)
from pyguibud.core.diagnostics import EMPTY_SOURCE_MAP, node_path

from .xml_helpers import HELLO, doc

UI = f"{{{NS_UI}}}"


# ---------------------------------------------------------------- Finding
def test_xml_warning_is_finding_and_defaults_are_unchanged() -> None:
    assert XmlWarning is Finding
    finding = Finding(code="x.y", msgid="Hello {name}", params={"name": "you"}, source="a.ui")
    assert finding.severity == "warning" and finding.path == "" and finding.part == ""
    assert finding.anchor is None and finding.related is None
    assert not finding.is_error
    assert finding.message == "Hello you"
    assert finding.location == "a.ui"
    assert str(finding) == "a.ui: Hello you"
    located = Finding(code="x", msgid="m", source="a.ui", line=3, column=7, severity="error")
    assert located.location == "a.ui:3:7" and located.is_error
    assert Finding(code="x", msgid="m", source="a.ui", line=3).location == "a.ui:3"


def test_params_are_read_only_and_not_hashed() -> None:
    finding = Finding(code="x", msgid="m", params={"a": 1}, source="s")
    with pytest.raises(TypeError):
        finding.params["a"] = 2  # type: ignore[index]
    assert hash(finding) == hash(Finding(code="x", msgid="m", params={"b": 2}, source="s"))


def test_anchor_and_related_do_not_take_part_in_equality() -> None:
    one = Finding(code="x", msgid="m", source="s", anchor=Widget(class_name="Label", id="a"))
    two = Finding(code="x", msgid="m", source="s", anchor=Widget(class_name="Label", id="b"))
    assert one == two and "anchor" not in repr(one)


def test_message_is_translated_on_read_and_never_raises() -> None:
    finding = Finding(code="x", msgid="The id '{id}' is broken.", params={"id": "a"}, source="s")
    english = finding.message
    i18n.set_language("en_XA")
    assert finding.message != english
    # A placeholder missing from params must not turn a report into a second error.
    broken = Finding(code="x", msgid="Needs {missing}", source="s")
    assert broken.message == "Needs {missing}"


# ---------------------------------------------------------------- SourceMap
def test_source_map_lookup_falls_back_from_part_to_element() -> None:
    node = Widget(class_name="Label", id="a")
    other = Widget(class_name="Label", id="b")
    positions = SourceMap(
        {(node, ""): (3, 1), (node, "layout"): (4, 2), (node, "prop[text]"): (5, 3)}
    )
    assert len(positions) == 3
    assert positions.get(node) == (3, 1)
    assert positions.get(node, "prop[text]") == (5, 3)
    assert positions.get(node, "layout/column[0]") == (4, 2)  # before the first "/"
    assert positions.get(node, "event[7]") == (3, 1)  # unknown part: the element
    assert positions.get(other) is None
    assert len(EMPTY_SOURCE_MAP) == 0 and EMPTY_SOURCE_MAP.get(node) is None


def test_source_map_is_a_snapshot_and_survives_unhashable_anchors() -> None:
    node = Widget(class_name="Label", id="a")
    entries: dict[tuple[object, str], tuple[int, int]] = {(node, ""): (1, 1)}
    positions = SourceMap(entries)
    entries.clear()
    assert positions.get(node) == (1, 1)
    assert positions.get([1, 2]) is None


# ---------------------------------------------------------------- reader positions
def _hello_lines() -> list[str]:
    return HELLO.read_text("utf-8").splitlines()


def test_reader_records_a_position_for_every_node_and_part() -> None:
    result = read_ui_bytes(HELLO.read_bytes(), source="hello.ui")
    document = result.document
    lines = _hello_lines()
    positions = result.positions

    def line_of(anchor: object, part: str = "") -> str:
        position = positions.get(anchor, part)
        assert position is not None, (anchor, part)
        return lines[position[0] - 1].strip()

    assert line_of(document).startswith("<pyguibud-ui")
    assert line_of(document, "meta").startswith("<meta")
    assert line_of(document, "variables/var[user_name]").startswith('<var id="user_name"')
    window = document.children[0]
    assert line_of(window).startswith('<window id="main"')
    assert line_of(window, "prop[title]").startswith('<prop name="title"')
    assert window.menubar is not None and window.statusbar is not None
    assert line_of(window.menubar).startswith("<menubar")
    assert line_of(window.statusbar).startswith('<statusbar id="sts_main"')
    assert line_of(window.statusbar, "prop[text]").startswith('<prop name="text"')
    menu = window.menubar.children[0]
    assert line_of(menu).startswith('<menu id="mnu_file"')
    action = menu.children[0]
    assert isinstance(action, Action) and line_of(action).startswith('<action id="act_quit"')
    assert line_of(action, "prop[text]").startswith('<prop name="text"')
    assert window.layout is not None
    assert line_of(window, "layout").startswith('<layout type="grid"')
    assert line_of(window, "layout/column[0]").startswith('<column index="0"')
    assert line_of(window, "layout/row[0]").startswith('<row index="0"')
    notebook = window.children[0]
    assert isinstance(notebook, Widget)
    assert line_of(notebook, "cell").startswith('<cell row="0"')
    frame = notebook.children[0]
    assert isinstance(frame, Widget)
    assert line_of(frame, "page").startswith("<page>")
    assert line_of(frame, "page/prop[text]").startswith('<prop name="text"')
    button = frame.children[2]
    assert isinstance(button, Widget)
    assert line_of(button, "event[0]").startswith('<event name="command"')
    entry = frame.children[1]
    assert line_of(entry, "event[0]").startswith('<event name="activate"')
    about = notebook.children[1]
    assert isinstance(about, Widget)
    label = about.children[0]
    assert isinstance(label, Widget)
    assert line_of(label, "pack").startswith('<pack fill="x"')


def test_reader_records_resources_includes_and_separators() -> None:
    body = (
        '<resources><image id="logo" src="logo.png"/></resources>\n'
        '<window id="main"><layout type="grid"/>\n'
        '<menubar><menu id="m"><separator/></menu></menubar>\n'
        '<include id="inc" src="x.ui" component="Panel"><cell row="0" column="0"/></include>\n'
        "</window>"
    )
    result = read_ui_bytes(doc(body))
    document = result.document
    window = document.children[0]
    assert result.positions.get(document, "resources/image[logo]") == (3, 12)
    assert window.menubar is not None
    separator = window.menubar.children[0].children[0]
    assert isinstance(separator, MenuSeparator)
    assert result.positions.get(separator) == (5, 23)
    include = window.children[0]
    assert isinstance(include, Include)
    assert result.positions.get(include) == (6, 1)
    assert result.positions.get(include, "cell") == (6, 48)


def test_a_node_created_by_a_migration_has_no_position(monkeypatch: pytest.MonkeyPatch) -> None:
    def step(root: ET.Element) -> tuple[ET.Element, str]:
        ET.SubElement(root, f"{UI}window", {"id": "added"})
        return root, "1.0"

    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": step})
    result = read_ui_bytes(doc('<window id="old"/>', version="0.9"))
    old, added = result.document.children
    assert result.positions.get(old) is not None
    assert result.positions.get(added) is None


def test_read_result_has_empty_positions_by_default() -> None:
    result = read_ui(HELLO)
    assert len(result.positions) > 30
    assert all(w.line is not None for w in result.warnings if w.code != "xml.discarded_content")


# ---------------------------------------------------------------- node_path
def test_node_path_of_nested_nodes_and_parts() -> None:
    document = read_ui(HELLO).document
    window = document.children[0]
    notebook = window.children[0]
    assert isinstance(notebook, Widget)
    frame = notebook.children[0]
    assert isinstance(frame, Widget)
    assert node_path(document) == ""
    assert node_path(document, "variables/var[user_name]") == "variables/var[user_name]"
    assert node_path(window) == "window[main]"
    assert node_path(frame) == "window[main]/widget[nbk_main]/widget[frm_greeting]"
    assert (
        node_path(frame, "layout/column[0]")
        == "window[main]/widget[nbk_main]/widget[frm_greeting]/layout/column[0]"
    )


def test_node_path_of_menus_needs_the_window_for_the_prefix() -> None:
    window = read_ui(HELLO).document.children[0]
    assert window.menubar is not None and window.statusbar is not None
    menu = window.menubar.children[0]
    action = menu.children[0]
    assert node_path(action) == "menubar/menu[mnu_file]/action[act_quit]"
    assert (
        node_path(action, window=window) == "window[main]/menubar/menu[mnu_file]/action[act_quit]"
    )
    assert node_path(window.menubar, window=window) == "window[main]/menubar"
    assert node_path(window.statusbar, window=window) == "window[main]/statusbar[sts_main]"
    assert node_path(window.statusbar) == "statusbar[sts_main]"


def test_node_path_uses_the_index_for_empty_ids_and_separators() -> None:
    window = Window(id="main")
    window.append_child(Widget(class_name="Label", id="a"))
    anonymous = Widget(class_name="Label", id="")
    window.append_child(anonymous)
    include = Include(id="", src="x.ui", component="C")
    window.append_child(include)
    menu = Menu(id="m")
    menu.append_child(Action(id="act"))
    separator = MenuSeparator()
    menu.append_child(separator)
    assert node_path(anonymous) == "window[main]/widget[#1]"
    assert node_path(include) == "window[main]/include[#2]"
    assert node_path(separator) == "menu[m]/separator[1]"
    assert node_path(Statusbar(id="")) == "statusbar[#0]"
    assert node_path(Window(id="")) == "window[#0]"


def test_node_path_of_a_detached_subtree_and_unknown_objects() -> None:
    frame = Widget(class_name="Frame", id="f")
    child = Widget(class_name="Label", id="c")
    frame.append_child(child)
    assert node_path(child) == "widget[f]/widget[c]"
    assert node_path(object()) == ""
    assert node_path(Menubar()) == "menubar"


def test_node_path_is_iterative() -> None:
    root = Widget(class_name="Frame", id="w0")
    current = root
    for index in range(1, 1500):
        child = Widget(class_name="Frame", id=f"w{index}")
        current.append_child(child)
        current = child
    path = node_path(current)
    assert path.count("/") == 1499 and path.endswith("widget[w1499]")


def test_node_path_survives_a_cyclic_parent_chain() -> None:
    first = Widget(class_name="Frame", id="a")
    second = Widget(class_name="Frame", id="b")
    first.parent = second
    second.parent = first
    assert node_path(first).startswith("widget[b]")  # terminates thanks to the segment cap


def test_hand_built_pieces_have_stable_paths() -> None:
    document = Document()
    document.resources["logo"] = ImageResource(id="logo", src="a.png")
    document.variables["v"] = Variable(id="v", type="string")
    window = Window(id="main", layout=Layout(type="grid"))
    document.add_window(window)
    widget = Widget(class_name="Label", id="a", placement=GridCell(row=0, column=0))
    window.append_child(widget)
    assert node_path(widget, "cell") == "window[main]/widget[a]/cell"
