"""Copy, cut, paste and duplicate (pure; spec properties-save-load 8, 14 A4-A6, 17)."""

from __future__ import annotations

import keyword
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.core import (
    CommandStack,
    Document,
    Include,
    Widget,
    Window,
    default_registry,
    dump_ui,
    read_ui_string,
    validate,
)
from pyguibud.core.model import GridCell, PackPlacement, PagePlacement
from pyguibud.core.validate import RESERVED_IDS
from pyguibud.core.xml_io import MAX_UI_BYTES
from pyguibud.designer import clipboard
from pyguibud.designer.clipboard import (
    Copied,
    Pasted,
    copy_text,
    cut_command,
    duplicate_command,
    paste_command,
    pasted_message,
)

SOURCE = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <resources><image id="logo" src="icons/logo.png"/><image id="unused" src="x.png"/></resources>
  <variables><var id="name" type="string"/><var id="spare" type="int"/></variables>
  <window id="main" kind="main">
    <menubar><menu id="file_menu"><action id="act_quit"/></menu></menubar>
    <layout type="grid"/>
    <widget class="Label" id="lbl"><prop name="image" ref="logo"/>
      <cell row="2" column="1"/></widget>
    <widget class="Entry" id="ent" bind="name"><cell row="3" column="1"/></widget>
    <widget class="Frame" id="frm"><cell row="4" column="1"/><layout type="pack"/>
      <widget class="Button" id="btn_ok"><pack/></widget>
    </widget>
    <widget class="Notebook" id="nb"><cell row="5" column="0"/>
      <widget class="Frame" id="tab1"><page><prop name="text">One</prop></page>
        <layout type="grid"/></widget>
    </widget>
    <include id="inc" src="#" component="comp"><cell row="6" column="0"/></include>
  </window>
  <window id="comp" kind="component"><layout type="pack"/>
    <widget class="Label" id="clbl"><pack/></widget>
  </window>
</pyguibud-ui>
"""

EMPTY = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  {extra}
  <window id="other" kind="dialog"><layout type="{layout}"/></window>
</pyguibud-ui>
"""

REG = default_registry()


def load(text: str) -> tuple[Document, CommandStack]:
    document = read_ui_string(text).document
    assert validate(document, REG).ok
    return document, CommandStack(document, REG)


def empty(extra: str = "", layout: str = "grid") -> tuple[Document, CommandStack]:
    return load(EMPTY.format(extra=extra, layout=layout))


def node(document: Document, node_id: str) -> object:
    found = document.find(node_id)
    assert found is not None, node_id
    return found


def copied(document: Document, *ids: str, origin: Path | None = None) -> str:
    result = copy_text(document, [node(document, i) for i in ids], origin)
    assert isinstance(result, Copied), result
    return result.text


def paste_ok(stack: CommandStack, selected: object, text: str, base: Path | None = None) -> Pasted:
    """Paste, execute, and check that undo restores identical bytes (then redo)."""
    before = dump_ui(stack.document)
    pasted = paste_command(stack.document, selected, text, REG, base)
    assert isinstance(pasted, Pasted), pasted
    outcome = stack.execute(pasted.command)
    assert outcome.accepted, outcome.message
    assert stack.undo() and dump_ui(stack.document) == before
    assert stack.redo()
    return pasted


# ---------------------------------------------------------------- copy
def test_copy_text_is_a_marked_ui_with_only_what_is_referenced() -> None:
    document, _stack = load(SOURCE)
    text = copied(document, "lbl", "ent", origin=Path("C:/work/form.ui"))
    assert 'xmlns:clip="urn:pyguibud:clipboard:1"' in text and 'clip:mode="widgets"' in text
    assert "clip:origin=" in text and "form.ui" in text
    clip = read_ui_string(text).document
    assert set(clip.resources) == {"logo"} and set(clip.variables) == {"name"}
    (wrapper,) = clip.children
    assert wrapper.kind == "component" and wrapper.layout is not None
    assert wrapper.layout.type == "grid"
    cells = [w.placement for w in wrapper.children]
    assert cells == [GridCell(row=0, column=0), GridCell(row=1, column=0)]
    assert validate(clip, REG).ok


def test_copy_of_a_child_and_its_parent_copies_the_parent_once() -> None:
    document, _stack = load(SOURCE)
    clip = read_ui_string(copied(document, "btn_ok", "frm")).document
    assert [n.id for n in clip.children[0].children] == ["frm"]


def test_copy_refuses_menus_and_bars() -> None:
    document, _stack = load(SOURCE)
    menu = node(document, "file_menu")
    assert copy_text(document, [menu], None) == "Menus and actions cannot be copied yet."


def test_copy_from_a_notebook_pastes_back_as_pages() -> None:
    document, stack = load(SOURCE)
    text = copied(document, "tab1")
    wrapper = read_ui_string(text).document.children[0]
    assert wrapper.layout is not None and wrapper.layout.type == "pack"
    pasted = paste_ok(stack, node(document, "nb"), text)
    (page,) = pasted.nodes
    assert isinstance(page, Widget) and page.id == "tab2"
    assert isinstance(page.placement, PagePlacement) and page.placement.text is not None
    assert page.placement.text.value == "tab2"


# ---------------------------------------------------------------- paste
def test_paste_into_the_same_document_remaps_and_reuses() -> None:
    document, stack = load(SOURCE)
    text = copied(document, "lbl", "ent")
    pasted = paste_ok(stack, node(document, "main"), text)
    first, second = pasted.nodes
    assert isinstance(first, Widget) and isinstance(second, Widget)
    assert (first.id, second.id) == ("lbl1", "ent1")
    assert second.bind == "name" and set(document.variables) == {"name", "spare"}
    assert first.props["image"].ref == "logo" and set(document.resources) == {"logo", "unused"}
    # below the used rows (inc ends at row 7), at column 0, relative cells kept
    assert first.placement == GridCell(row=7, column=0)
    assert second.placement == GridCell(row=8, column=0)
    assert stack.document is document and validate(document, REG).ok


def test_paste_into_another_document_brings_variables_and_images(tmp_path: Path) -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "lbl", "ent", origin=tmp_path / "a" / "form.ui")
    target, stack = empty()
    pasted = paste_ok(stack, target.children[0], text, base=tmp_path / "b")
    assert [n.id for n in pasted.nodes if isinstance(n, Widget)] == ["lbl", "ent"]
    assert set(target.variables) == {"name"}
    assert target.resources["logo"].src == "../a/icons/logo.png"


def test_paste_into_an_untitled_document_makes_paths_absolute(tmp_path: Path) -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "lbl", origin=tmp_path / "form.ui")
    target, stack = empty()
    paste_ok(stack, target.children[0], text)
    assert Path(target.resources["logo"].src) == tmp_path / "icons" / "logo.png"


def test_variable_of_another_type_is_a_renamed_copy_and_binds_follow() -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "ent")
    target, stack = empty('<variables><var id="name" type="int"/></variables>')
    (entry,) = paste_ok(stack, target.children[0], text).nodes
    assert isinstance(entry, Widget) and entry.bind == "name1"
    assert target.variables["name1"].type == "string" and target.variables["name"].type == "int"


def test_variable_of_the_same_type_is_reused() -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "ent")
    target, stack = empty('<variables><var id="name" type="string" default="x"/></variables>')
    (entry,) = paste_ok(stack, target.children[0], text).nodes
    assert isinstance(entry, Widget) and entry.bind == "name" and len(target.variables) == 1


def test_image_with_another_path_is_a_renamed_copy_and_refs_follow() -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "lbl")
    target, stack = empty('<resources><image id="logo" src="other.png"/></resources>')
    (label,) = paste_ok(stack, target.children[0], text).nodes
    assert isinstance(label, Widget) and label.props["image"].ref == "logo1"
    assert target.resources["logo1"].src == "icons/logo.png"


def test_paste_after_a_selected_leaf_in_pack_order() -> None:
    document, stack = load(SOURCE)
    text = copied(document, "lbl")
    pasted = paste_ok(stack, node(document, "btn_ok"), text)
    frame = node(document, "frm")
    assert isinstance(frame, Widget)
    assert [c.id for c in frame.children] == ["btn_ok", "lbl1"]
    assert isinstance(pasted.nodes[0], Widget)
    assert isinstance(pasted.nodes[0].placement, PackPlacement)  # grid -> pack


def test_a5_paste_into_a_menu_is_refused_by_the_guard() -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    pasted = paste_command(
        document, node(document, "file_menu"), copied(document, "lbl"), REG, None
    )
    assert isinstance(pasted, Pasted)
    outcome = stack.execute(pasted.command)
    assert not outcome.accepted and outcome.message
    assert dump_ui(document) == before


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        "",
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        SOURCE,  # a valid .ui without the clip:mode marker
    ],
)
def test_a6_foreign_text_is_no_pyguibud_elements(text: str) -> None:
    document, _stack = load(SOURCE)
    assert paste_command(document, document.children[0], text, REG, None) == (
        "The clipboard holds no PyGUIbud elements."
    )


def test_a4_huge_text_is_refused_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    document, _stack = load(SOURCE)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("parsed")

    monkeypatch.setattr(clipboard, "read_ui_string", boom)
    for text in ("x" * (MAX_UI_BYTES + 1), "é" * (MAX_UI_BYTES // 2 + 1)):
        result = paste_command(document, document.children[0], text, REG, None)
        assert result == "The clipboard content is too large to paste."


def test_a4_too_many_widgets_is_refused() -> None:
    document, _stack = load(SOURCE)
    widgets = "".join(f'<widget class="Label" id="w{k}"><pack/></widget>' for k in range(2001))
    text = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" '
        'xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="widgets">'
        f'<window id="c" kind="component"><layout type="pack"/>{widgets}</window></pyguibud-ui>'
    )
    result = paste_command(document, document.children[0], text, REG, None)
    assert result == "Paste refused: more than 2000 widgets."


def test_invalid_clipboard_content_gives_the_first_reason() -> None:
    document, _stack = load(SOURCE)
    text = copied(document, "lbl").replace('id="lbl"', 'id="lbl" bind="nowhere"')
    result = paste_command(document, document.children[0], text, REG, None)
    assert isinstance(result, str) and result.startswith("The clipboard content is not valid: ")


def test_same_file_include_needs_its_component_in_the_target() -> None:
    source, stack = load(SOURCE)
    text = copied(source, "inc")
    target, _other = empty()
    assert paste_command(target, target.children[0], text, REG, None) == (
        "'inc' includes a component of its original file; paste that component first."
    )
    (include,) = paste_ok(stack, source.children[0], text).nodes
    assert isinstance(include, Include) and include.component == "comp"


def test_windows_mode_pastes_new_windows_with_bar_ids_remapped() -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "main", "comp")
    assert 'clip:mode="windows"' in text
    target, stack = empty('<variables><var id="file_menu" type="int"/></variables>', "pack")
    windows = paste_ok(stack, target.children[0], text).nodes
    main, comp = windows
    assert isinstance(main, Window) and isinstance(comp, Window)
    assert main.menubar is not None and main.menubar.children[0].id == "file_menu1"
    assert target.children[1].menubar is not None
    assert target.children[1].menubar.children[0].id == "file_menu1"
    assert validate(target, REG).ok


def test_windows_mode_renames_a_component_and_its_same_file_includes() -> None:
    source, _stack = load(SOURCE)
    text = copied(source, "main", "comp")
    target, stack = empty()
    target.children[0].id = "comp"  # the component id is taken in the target
    paste_ok(stack, target.children[0], text)
    include = node(target, "inc")
    assert isinstance(include, Include) and include.component == "comp1"


def test_a_second_main_window_is_pasted_as_a_dialog() -> None:
    document, stack = load(SOURCE)
    (window,) = paste_ok(stack, None, copied(document, "main")).nodes
    assert isinstance(window, Window) and window.kind == "dialog" and window.id == "main1"
    assert window.menubar is not None and validate(document, REG).ok
    result = duplicate_command(document, [node(document, "main")], REG)
    assert isinstance(result, Pasted) and stack.execute(result.command).accepted
    (duplicate,) = result.nodes
    assert isinstance(duplicate, Window) and duplicate.kind == "dialog"
    assert document.children[1] is duplicate  # right after the original
    assert [w.kind for w in document.children].count("main") == 1


def test_a_main_window_stays_main_where_there_is_none() -> None:
    source, _stack = load(SOURCE)
    _target, stack = empty()  # a lone dialog
    windows = paste_ok(stack, None, copied(source, "main", "comp")).nodes
    assert [w.kind for w in windows if isinstance(w, Window)] == ["main", "component"]


def test_remapped_ids_keep_their_case() -> None:
    text = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<window id="win" kind="main"><layout type="pack"/>'
        '<widget class="Button" id="OkBtn"><pack/></widget>'
        '<widget class="Button" id="Cancel_2"><pack/></widget></window></pyguibud-ui>'
    )
    document, stack = load(text)
    pasted = paste_ok(stack, document.children[0], copied(document, "OkBtn", "Cancel_2"))
    assert [n.id for n in pasted.nodes if isinstance(n, Widget)] == ["OkBtn1", "Cancel1"]


# ---------------------------------------------------------------- cut, duplicate
def test_cut_copies_then_deletes_in_one_step() -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    result = cut_command(document, [node(document, "lbl"), node(document, "ent")], None)
    assert not isinstance(result, str)
    clip, command = result
    assert clip.count == 2 and command.text() == "Cut"
    assert stack.execute(command).accepted and document.find("lbl") is None
    assert stack.undo() and dump_ui(document) == before


def test_cut_refuses_the_last_window_and_an_included_component() -> None:
    document, _stack = load(SOURCE)
    windows = list(document.children)
    assert cut_command(document, windows, None) == "A document needs at least one window."
    assert cut_command(document, [windows[1]], None) == "'comp' is still included by 'main'."


def test_duplicate_goes_after_the_original() -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    result = duplicate_command(document, [node(document, "btn_ok")], REG)
    assert isinstance(result, Pasted) and result.command.text() == "Duplicate"
    assert stack.execute(result.command).accepted
    frame = node(document, "frm")
    assert isinstance(frame, Widget) and [c.id for c in frame.children] == ["btn_ok", "btn_ok1"]
    assert stack.undo() and dump_ui(document) == before


def test_duplicate_of_a_container_is_a_sibling_not_a_child() -> None:
    document, stack = load(SOURCE)
    result = duplicate_command(document, [node(document, "frm")], REG)
    assert isinstance(result, Pasted) and stack.execute(result.command).accepted
    (copy,) = result.nodes
    assert copy.parent is document.children[0] and isinstance(copy, Widget)
    assert [c.id for c in copy.children] == ["btn_ok1"]


def test_duplicate_of_a_component_window_is_a_new_window() -> None:
    document, stack = load(SOURCE)
    result = duplicate_command(document, [node(document, "comp")], REG)
    assert isinstance(result, Pasted) and stack.execute(result.command).accepted
    assert [w.id for w in document.children] == ["main", "comp", "comp1"]


def test_pasted_message_is_plural_aware() -> None:
    assert pasted_message(1) == "Pasted 1 element."
    assert pasted_message(3) == "Pasted 3 elements."


# ---------------------------------------------------------------- remap property
_IDS = st.from_regex(r"[a-z][a-z0-9_]{0,8}", fullmatch=True).filter(
    lambda i: not keyword.iskeyword(i) and i not in RESERVED_IDS and i != "win"
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ids=st.lists(_IDS, min_size=1, max_size=6, unique=True), times=st.integers(1, 3))
def test_repeated_pastes_never_clash_and_undo_restores(ids: list[str], times: int) -> None:
    labels = "".join(f'<widget class="Label" id="{i}"><pack/></widget>' for i in ids)
    text = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        f'<window id="win" kind="main"><layout type="pack"/>{labels}</window></pyguibud-ui>'
    )
    document, stack = load(text)
    before = dump_ui(document)
    clip = copied(document, *ids)
    for _ in range(times):
        pasted = paste_command(document, document.children[0], clip, REG, None)
        assert isinstance(pasted, Pasted)
        assert stack.execute(pasted.command).accepted
    all_ids = [i for i, _owner in document.iter_ids()]
    assert len(all_ids) == len(set(all_ids)) == 1 + len(ids) * (times + 1)
    while stack.undo():
        pass
    assert dump_ui(document) == before


def test_a_differing_layout_keeps_the_reading_order() -> None:
    grid = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<window id="g" kind="main"><layout type="grid"/>'
        '<widget class="Label" id="second"><cell row="1" column="0"/></widget>'
        '<widget class="Label" id="first"><cell row="0" column="1"/></widget>'
        "</window></pyguibud-ui>"
    )
    source, _stack = load(grid)
    text = copied(source, "second", "first")
    target, stack = empty(layout="pack")
    pasted = paste_ok(stack, target.children[0], text)
    assert [n.id for n in pasted.nodes if isinstance(n, Widget)] == ["first", "second"]
    assert [c.id for c in target.children[0].children] == ["first", "second"]
    # pack -> grid: consecutive rows at column 0 below the used rows
    source, stack = load(SOURCE)
    pack_text = copied(source, "clbl", "btn_ok")  # two pack parents: a vertical pack wrapper
    pasted = paste_ok(stack, source.children[0], pack_text)
    cells = [n.placement for n in pasted.nodes if isinstance(n, Widget)]
    assert cells == [GridCell(row=7, column=0), GridCell(row=8, column=0)]


# ---------------------------------------------------------------- QA 14a.2 (debugger)
_CLIP = (
    '<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1" '
    'xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="widgets">'
    '<window id="w" kind="component"><layout type="pack"/>{body}</window></pyguibud-ui>'
)
_TWO_COMPONENTS = SOURCE.replace(
    '<window id="comp" kind="component"><layout type="pack"/>',
    '<window id="inner" kind="component"><layout type="pack"/>'
    '<widget class="Label" id="ilbl"><pack/></widget></window>\n'
    '  <window id="comp" kind="component"><layout type="pack"/>'
    '<include id="uses_inner" src="#" component="inner"><pack/></include>',
)


def _guard_refuses(stack: CommandStack, selected: object, text: str) -> str:
    """Paste ``text`` at ``selected``: the stack's guard refuses it and nothing changes."""
    before = dump_ui(stack.document)
    pasted = paste_command(stack.document, selected, text, REG, None)
    assert isinstance(pasted, Pasted), pasted
    outcome = stack.execute(pasted.command)
    assert not outcome.accepted and dump_ui(stack.document) == before
    return outcome.message


def test_qa01_a_pasted_include_that_closes_a_cycle_is_refused_by_the_guard() -> None:
    """QA-14a2-01/10: the guard follows same-file includes (ADR-006 amendment)."""
    document, stack = load(SOURCE)
    text = copied(document, "inc")  # main shows comp; pasted inside comp it would show itself
    assert _guard_refuses(stack, node(document, "clbl"), text) == (
        "Including 'comp' from '#' creates a cycle: #comp → #comp."
    )
    paste_ok(stack, node(document, "frm"), text)  # in main it is fine
    document, stack = load(_TWO_COMPONENTS)  # comp -> inner; inner -> comp closes a loop
    text = copied(document, "uses_inner").replace('component="inner"', 'component="comp"')
    message = _guard_refuses(stack, node(document, "ilbl"), text)
    assert message.startswith("Including '") and "#inner" in message and "#comp" in message


def test_qa01_a_pasted_include_of_a_window_that_is_no_component_is_refused() -> None:
    document, stack = load(SOURCE)
    body = '<include id="i" src="#" component="main"><pack/></include>'
    text = _CLIP.format(version="1.0", body=body)
    assert _guard_refuses(stack, node(document, "clbl"), text) == (
        "The window 'main' in '#' is not a component."
    )


def test_qa01_a_pasted_window_that_includes_itself_is_refused() -> None:
    _document, stack = load(SOURCE)
    text = (
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" '
        'xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="windows">'
        '<window id="loop" kind="component"><layout type="pack"/>'
        '<include id="me" src="#" component="loop"><pack/></include></window></pyguibud-ui>'
    )
    assert _guard_refuses(stack, None, text) == (
        "Including 'loop' from '#' creates a cycle: #loop → #loop."
    )


def test_n2_a_paste_counts_the_warnings_of_the_clipboard_content() -> None:
    document, stack = load(SOURCE)
    body = '<widget class="Label" id="x" future="1"><pack/></widget>'
    pasted = paste_command(
        document, node(document, "frm"), _CLIP.format(version="1.0", body=body), REG, None
    )
    assert isinstance(pasted, Pasted) and pasted.warnings >= 1
    assert stack.execute(pasted.command).accepted
    assert pasted_message(1, 2) == "Pasted 1 element. The clipboard content had 2 warnings."
    assert pasted_message(1) == "Pasted 1 element."
    clean = paste_command(document, node(document, "frm"), copied(document, "lbl"), REG, None)
    assert isinstance(clean, Pasted) and clean.warnings == 0


def test_qa06_a_clipboard_of_a_newer_schema_is_refused_with_its_version() -> None:
    document, _stack = load(SOURCE)
    body = '<widget class="Label" id="x"><pack/></widget>'
    for version in ("1.7", "2.0"):
        text = _CLIP.format(version=version, body=body)
        assert paste_command(document, node(document, "frm"), text, REG, None) == (
            f"The clipboard content uses schema version {version}, newer than 1.0; it cannot "
            "be pasted."
        )


def test_qa05_copy_works_on_a_read_only_document_and_leaves_it_untouched() -> None:
    document, stack = load(SOURCE.replace('schema_version="1.0"', 'schema_version="1.7"'))
    assert stack.read_only
    text = copied(document, "lbl")  # the writer refuses a newer schema: a copy only reads
    assert document.schema_version == "1.7"
    target, target_stack = load(SOURCE)
    paste_ok(target_stack, node(target, "frm"), text)


def test_qa07_duplicate_over_the_widget_cap_says_duplicate() -> None:
    labels = "".join(f'<widget class="Label" id="w{k}"><pack/></widget>' for k in range(2001))
    document, _stack = load(
        SOURCE.replace(
            '<widget class="Button" id="btn_ok"><pack/></widget>',
            '<widget class="Frame" id="big"><pack/><layout type="pack"/>' + labels + "</widget>",
        )
    )
    result = duplicate_command(document, [node(document, "big")], REG)
    assert result == "Duplicate refused: more than 2000 widgets."


def test_qa08_a_component_is_cut_with_the_window_that_includes_it() -> None:
    document, stack = load(
        SOURCE.replace(
            '<window id="comp"',
            '<window id="dlg" kind="dialog"><layout type="pack"/></window>\n  <window id="comp"',
        )
    )
    built = cut_command(document, [node(document, "main"), node(document, "comp")], None)
    assert not isinstance(built, str), built
    assert stack.execute(built[1]).accepted
    assert [w.id for w in document.children] == ["dlg"]
    assert stack.undo() and [w.id for w in document.children] == ["main", "dlg", "comp"]
    # alone, the component is still refused while main shows it
    assert cut_command(document, [node(document, "comp")], None) == (
        "'comp' is still included by 'main'."
    )
