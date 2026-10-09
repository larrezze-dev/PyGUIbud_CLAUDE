"""Step 14a.2 gap tests (pure): properties, paste target rules, rebasing, abuse A4-A6/A13.

Written from spec properties-save-load 7, 8.2, 14 and 17; they add to (never repeat)
``test_clipboard.py`` and ``test_structure_builders.py``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, assume, event, given, settings
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
from pyguibud.core.xml_io import MAX_UI_BYTES
from pyguibud.designer.clipboard import (
    Copied,
    Pasted,
    copy_text,
    cut_command,
    duplicate_command,
    paste_command,
)
from pyguibud.designer.clipboard_actions import ClipboardActions
from pyguibud.designer.editing import rename_window
from pyguibud.designer.session import DesignerSession
from tests.designer.conftest import best_of
from tests.designer.test_clipboard import SOURCE, copied, empty, load, node, paste_ok

REG = default_registry()
NO_ELEMENTS = "The clipboard holds no PyGUIbud elements."
HEAD = '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
CLIP_HEAD = HEAD[:-1] + ' xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="{mode}">'
ORIGIN_A = Path("C:/proj/a/form.ui")


def _ui(body: str) -> str:
    return f"{HEAD}{body}</pyguibud-ui>"


def _ids(document: Document) -> list[str]:
    return [i for i, _owner in document.iter_ids()]


# ======================================================================================
# Random documents (hypothesis): an entropy stream drives a small, always valid builder
# ======================================================================================
_TYPES = ("string", "int", "bool")


class _Builder:
    """Builds a valid ``.ui`` text from a list of integers (shrinks towards the first choice)."""

    def __init__(self, entropy: list[int]) -> None:
        self.it = iter(entropy)
        self.n = 0
        self.variables: dict[str, str] = {}
        self.images: list[str] = []
        self.components: list[str] = []

    def pick(self, count: int) -> int:
        return next(self.it, 0) % count

    def fresh(self, stem: str = "n") -> str:
        self.n += 1
        return f"{stem}{self.n}"

    def place(self, parent: str, index: int) -> str:
        if parent == "grid":
            return f'<cell row="{index}" column="{self.pick(2)}"/>'
        if parent == "pages":
            return '<page><prop name="text">T</prop></page>' if self.pick(2) else "<page/>"
        return "<pack/>"

    def widget(self, parent: str, index: int, depth: int) -> str:
        kind = self.pick(8 if depth < 3 else 5)
        wid, where = self.fresh(), self.place(parent, index)
        if kind == 0:
            image = ""
            if self.images and self.pick(2):
                image = f'<prop name="image" ref="{self.images[self.pick(len(self.images))]}"/>'
            return f'<widget class="Label" id="{wid}">{image}{where}</widget>'
        if kind == 1:
            names = [v for v, t in self.variables.items() if t == "string"]
            bind = f' bind="{names[self.pick(len(names))]}"' if names and self.pick(2) else ""
            return f'<widget class="Entry" id="{wid}"{bind}>{where}</widget>'
        if kind == 2:
            names = [v for v, t in self.variables.items() if t == "bool"]
            bind = f' bind="{names[self.pick(len(names))]}"' if names and self.pick(2) else ""
            return f'<widget class="Checkbutton" id="{wid}"{bind}>{where}</widget>'
        if kind == 3:
            return f'<widget class="Button" id="{wid}">{where}</widget>'
        if kind == 4 and self.components and parent != "pages":
            comp = self.components[self.pick(len(self.components))]
            return f'<include id="{self.fresh("inc")}" src="#" component="{comp}">{where}</include>'
        if kind in (4, 5, 6):
            return self.frame(wid, where, depth)
        pages = "".join(self.widget("pages", k, depth + 1) for k in range(1 + self.pick(2)))
        cls = "Notebook" if self.pick(2) else "PanedWindow"
        if cls == "PanedWindow":
            pages = pages.replace('<page><prop name="text">T</prop></page>', "<page/>")
        return f'<widget class="{cls}" id="{wid}">{where}{pages}</widget>'

    def frame(self, wid: str, where: str, depth: int) -> str:
        layout = "grid" if self.pick(2) else "pack"
        orient = ' orient="horizontal"' if layout == "pack" and self.pick(2) else ""
        kids = "".join(self.widget(layout, k, depth + 1) for k in range(self.pick(4)))
        return (
            f'<widget class="Frame" id="{wid}">{where}'
            f'<layout type="{layout}"{orient}/>{kids}</widget>'
        )

    def window(self, wid: str, kind: str) -> str:
        layout = "grid" if self.pick(2) else "pack"
        bars = ""
        if kind != "component" and self.pick(2):
            bars = (
                f'<menubar><menu id="{self.fresh("m")}"><action id="{self.fresh("a")}"/></menu>'
                f"</menubar>"
            )
            if self.pick(2):
                bars += f'<statusbar id="{self.fresh("sb")}"/>'
        kids = "".join(self.widget(layout, k, 0) for k in range(self.pick(5)))
        return f'<window id="{wid}" kind="{kind}">{bars}<layout type="{layout}"/>{kids}</window>'

    def document(self) -> str:
        names = ["v1", "v2", "v3"][: 1 + self.pick(3)]
        self.variables = {v: _TYPES[self.pick(3)] for v in names}
        self.images = ["img1", "img2"][: self.pick(3)]
        head = ""
        if self.images:
            head += (
                "<resources>"
                + "".join(f'<image id="{i}" src="icons/{i}.png"/>' for i in self.images)
                + "</resources>"
            )
        head += (
            "<variables>"
            + "".join(f'<var id="{v}" type="{t}"/>' for v, t in self.variables.items())
            + "</variables>"
        )
        count = 1 + self.pick(3)
        kinds = ["main"] + [("dialog", "component")[self.pick(2)] for _ in range(count - 1)]
        ids = [f"w{k + 1}" for k in range(count)]
        self.components = [i for i, k in zip(ids, kinds, strict=True) if k == "component"]
        windows = "".join(self.window(i, k) for i, k in zip(ids, kinds, strict=True))
        self.n += 100  # keep window-body ids apart from window ids is not needed; just distinct
        return _ui(f'<meta source_locale="en_GB"/>{head}{windows}')


@st.composite
def documents(draw: st.DrawFn) -> tuple[Document, CommandStack]:
    entropy = draw(st.lists(st.integers(0, 10_000), min_size=20, max_size=160))
    text = _Builder(entropy).document()
    document = read_ui_string(text).document
    assume(validate(document, REG).ok)
    return document, CommandStack(document, REG)


def _movable(document: Document) -> list[Widget | Include]:
    return [n for n in document.walk() if isinstance(n, Widget | Include)]


_SETTINGS = settings(max_examples=120, deadline=None, suppress_health_check=list(HealthCheck))


# ---------------------------------------------------------------- rename then undo
@_SETTINGS
@given(
    pair=documents(),
    which=st.integers(0, 9),
    new=st.sampled_from(
        ["fresh", "w1", "w2", "w3", "n1", "n2", "class", "vars", "9x", "", "ok_1", "A" * 64, "a b"]
    ),
)
def test_rename_window_then_undo_is_identical(
    pair: tuple[Document, CommandStack], which: int, new: str
) -> None:
    document, stack = pair
    window = document.children[which % len(document.children)]
    assert isinstance(window, Window)
    before, old = dump_ui(document), window.id
    includes = [i for i in document.walk() if isinstance(i, Include) and i.component == old]
    outcome = stack.execute(rename_window(document, window, new))
    if not outcome.accepted:
        event("refused")
        assert dump_ui(document) == before and outcome.message
        return
    event("accepted")
    after = dump_ui(document)
    assert window.id == new
    if new == old:  # renaming to its own id changes nothing and records no step
        assert after == before and not stack.can_undo
        return
    assert all(i.component == new for i in includes)  # every same-file include followed
    assert validate(document, REG).ok
    assert stack.undo() and dump_ui(document) == before
    assert window.id == old and all(i.component == old for i in includes)
    assert stack.redo() and dump_ui(document) == after


# ---------------------------------------------------------------- copy -> paste property
def _check_resolves(document: Document) -> None:
    """Ids unique; binds, image refs and include components all resolve."""
    ids = _ids(document)
    assert len(ids) == len(set(ids))
    windows = {w.id for w in document.children}
    for n in document.walk():
        if isinstance(n, Widget) and n.bind:
            assert n.bind in document.variables
        for prop in getattr(n, "props", {}).values():
            if prop.ref:
                assert prop.ref in document.resources
        place = getattr(n, "placement", None)
        if isinstance(place, PagePlacement) and place.image:
            assert place.image in document.resources
        if isinstance(n, Include) and n.src == "#":
            assert n.component in windows


@_SETTINGS
@given(
    source=documents(),
    target=documents(),
    picks=st.lists(st.integers(0, 500), min_size=1, max_size=3),
    where=st.integers(0, 500),
    base=st.sampled_from([None, Path("C:/proj/b"), Path("C:/proj/a")]),
    origin=st.sampled_from([None, ORIGIN_A]),
    same=st.booleans(),
)
def test_copy_paste_into_random_targets_validates_and_undoes(
    source: tuple[Document, CommandStack],
    target: tuple[Document, CommandStack],
    picks: list[int],
    where: int,
    base: Path | None,
    origin: Path | None,
    same: bool,
) -> None:
    src_doc = source[0]
    dst_doc, dst_stack = source if same else target
    pool = _movable(src_doc)
    assume(pool)
    chosen = list({id(n): n for n in (pool[p % len(pool)] for p in picks)}.values())
    clip = copy_text(src_doc, chosen, origin)
    assert isinstance(clip, Copied), clip
    nodes = [n for n in dst_doc.walk() if isinstance(n, Window | Widget | Include)]
    selected = nodes[where % len(nodes)]
    before = dump_ui(dst_doc)
    pasted = paste_command(dst_doc, selected, clip.text, REG, base)
    assert dump_ui(dst_doc) == before  # building the command touches nothing
    if isinstance(pasted, str):
        event("refused-before")
        assert pasted
        return
    outcome = dst_stack.execute(pasted.command)
    if not outcome.accepted:
        event("refused-by-guard")
        assert dump_ui(dst_doc) == before and outcome.message
        # only includes may legitimately be refused (cycles / foreign components)
        assert any(
            isinstance(n, Include) for c in chosen for n in (c, *getattr(c, "walk", tuple)())
        )
        return
    event("accepted")
    after = dump_ui(dst_doc)
    assert not validate(dst_doc, REG).errors
    _check_resolves(dst_doc)
    assert all(n.parent is not None for n in pasted.nodes)
    assert dst_stack.undo() and dump_ui(dst_doc) == before
    assert dst_stack.redo() and dump_ui(dst_doc) == after


@_SETTINGS
@given(
    source=documents(),
    target=documents(),
    picks=st.lists(st.integers(0, 5), min_size=1, max_size=3),
    same=st.booleans(),
)
def test_windows_mode_paste_validates_and_undoes(
    source: tuple[Document, CommandStack],
    target: tuple[Document, CommandStack],
    picks: list[int],
    same: bool,
) -> None:
    src_doc = source[0]
    dst_doc, dst_stack = source if same else target
    chosen = list(
        {id(w): w for w in (src_doc.children[p % len(src_doc.children)] for p in picks)}.values()
    )
    clip = copy_text(src_doc, chosen, ORIGIN_A)
    assert isinstance(clip, Copied)
    before = dump_ui(dst_doc)
    pasted = paste_command(dst_doc, dst_doc.children[0], clip.text, REG, Path("C:/proj/b"))
    if isinstance(pasted, str):
        event("refused-before")
        assert dump_ui(dst_doc) == before
        return
    outcome = dst_stack.execute(pasted.command)
    if not outcome.accepted:
        event("refused-by-guard")
        assert dump_ui(dst_doc) == before
        return
    after = dump_ui(dst_doc)
    assert not validate(dst_doc, REG).errors
    _check_resolves(dst_doc)
    assert [w.kind for w in dst_doc.children].count("main") <= 1
    assert dst_stack.undo() and dump_ui(dst_doc) == before
    assert dst_stack.redo() and dump_ui(dst_doc) == after


def test_the_random_paste_property_is_not_vacuous() -> None:
    """A fixed sweep: every leaf of SOURCE pastes at every node and is accepted."""
    accepted = 0
    document, _stack = load(SOURCE)
    leaves = [n for n in _movable(document) if not isinstance(n, Include)]
    targets = [n for n in document.walk() if isinstance(n, Window | Widget | Include)]
    for leaf in leaves:
        text = copied(document, leaf.id)
        for target in targets:
            fresh, stack = load(SOURCE)
            result = paste_command(fresh, fresh.find(target.id), text, REG, None)
            assert isinstance(result, Pasted), (leaf.id, target.id, result)
            outcome = stack.execute(result.command)
            assert outcome.accepted, (leaf.id, target.id, outcome.message)
            assert not validate(fresh, REG).errors
            accepted += 1
    assert accepted >= 40


# ---------------------------------------------------------------- fuzz of the clipboard text
@settings(max_examples=120, deadline=None, suppress_health_check=list(HealthCheck))
@given(
    start=st.integers(0, 4000),
    length=st.integers(0, 80),
    junk=st.text(max_size=12),
    cut_tail=st.booleans(),
)
def test_a_mutated_clipboard_text_never_raises_or_corrupts(
    start: int, length: int, junk: str, cut_tail: bool
) -> None:
    document, stack = load(SOURCE)
    base = copied(document, "lbl", "ent", "frm", "nb")
    start %= len(base)
    text = base[:start] if cut_tail else base[:start] + junk + base[start + length :]
    before = dump_ui(document)
    result = paste_command(document, document.children[0], text, REG, None)
    if isinstance(result, str):
        assert dump_ui(document) == before
        return
    outcome = stack.execute(result.command)  # a guard refusal is fine; an exception is not
    if outcome.accepted:
        dump_ui(document)
        assert not validate(document, REG).errors
    else:
        assert dump_ui(document) == before


@settings(max_examples=100, deadline=None)
@given(text=st.text(max_size=300))
def test_any_text_is_refused_without_raising(text: str) -> None:
    document, _stack = load(SOURCE)
    assert paste_command(document, document.children[0], text, REG, None) == NO_ELEMENTS


# ======================================================================================
# Paste target rules (8.2 step 5)
# ======================================================================================
GRID_TARGET = _ui(
    '<window id="g" kind="main"><layout type="grid"/>'
    '<widget class="Label" id="tall"><cell row="0" column="3" rowspan="3"/></widget>'
    '<widget class="Label" id="low"><cell row="1" column="0"/></widget></window>'
)
BLOCK = _ui(
    '<window id="src" kind="main"><layout type="grid"/>'
    '<widget class="Label" id="p"><cell row="2" column="3"/></widget>'
    '<widget class="Label" id="q"><cell row="3" column="4" columnspan="2"/></widget></window>'
)


def test_grid_block_goes_below_rowspans_at_column_zero_keeping_relative_cells() -> None:
    source, _s = load(BLOCK)
    target, stack = load(GRID_TARGET)
    pasted = paste_ok(stack, target.children[0], copied(source, "p", "q"))
    p, q = pasted.nodes
    assert isinstance(p, Widget) and isinstance(q, Widget)
    assert p.placement == GridCell(row=3, column=0)  # tall ends at row 3
    assert q.placement == GridCell(row=4, column=1, columnspan=2)


def test_grid_block_into_an_empty_grid_starts_at_the_origin() -> None:
    source, _s = load(BLOCK)
    target, stack = empty(layout="grid")
    pasted = paste_ok(stack, target.children[0], copied(source, "p", "q"))
    assert [n.placement for n in pasted.nodes if isinstance(n, Widget)] == [
        GridCell(row=0, column=0),
        GridCell(row=1, column=1, columnspan=2),
    ]


def test_paste_after_a_grid_leaf_sits_after_it_in_order_but_below_the_used_rows() -> None:
    source, _s = load(BLOCK)
    target, stack = load(GRID_TARGET)
    pasted = paste_ok(stack, node(target, "tall"), copied(source, "p"))
    (p,) = pasted.nodes
    assert [c.id for c in target.children[0].children] == ["tall", "p", "low"]
    assert isinstance(p, Widget) and p.placement == GridCell(row=3, column=0)


PACK = _ui(
    '<window id="pk" kind="main"><layout type="pack"/>'
    '<widget class="Button" id="a"><pack/></widget>'
    '<widget class="Button" id="b"><pack/></widget>'
    '<widget class="Button" id="c"><pack/></widget></window>'
)
OTHER_PACK = _ui(
    '<window id="o" kind="main"><layout type="pack"/>'
    '<widget class="Label" id="x"><pack/></widget>'
    '<widget class="Label" id="y"><pack/></widget></window>'
)


def test_pack_leaf_target_inserts_the_block_in_order_after_it() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(PACK)
    pasted = paste_ok(stack, node(target, "a"), copied(source, "x", "y"))
    assert [c.id for c in target.children[0].children] == ["a", "x", "y", "b", "c"]
    assert all(
        isinstance(n.placement, PackPlacement) for n in pasted.nodes if isinstance(n, Widget)
    )


def test_pack_container_and_window_targets_append_to_the_end() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(PACK)
    paste_ok(stack, target.children[0], copied(source, "x"))  # a window: its body
    assert [c.id for c in target.children[0].children] == ["a", "b", "c", "x"]


def test_pack_order_is_the_document_order_of_the_selection() -> None:
    source, _s = load(OTHER_PACK)
    text = copied(source, "y", "x")  # selected in the opposite order
    target, stack = load(PACK)
    paste_ok(stack, node(target, "c"), text)
    assert [c.id for c in target.children[0].children][-2:] == ["x", "y"]


PAGES = _ui(
    '<window id="pg" kind="main"><layout type="pack"/>'
    '<widget class="Notebook" id="nb"><pack/></widget>'
    '<widget class="PanedWindow" id="pw"><pack/></widget></window>'
)


def test_several_widgets_into_a_notebook_become_pages_titled_with_their_ids() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(PAGES)
    pasted = paste_ok(stack, node(target, "nb"), copied(source, "x", "y"))
    texts = []
    for n in pasted.nodes:
        assert isinstance(n, Widget) and isinstance(n.placement, PagePlacement)
        assert n.placement.text is not None and n.placement.text.translatable
        texts.append(n.placement.text.value)
    assert texts == ["x", "y"] == [n.id for n in pasted.nodes if isinstance(n, Widget)]
    assert not validate(target, REG).errors


def test_a_remapped_id_is_the_page_text_of_a_notebook_page() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(PAGES)
    paste_ok(stack, node(target, "nb"), copied(source, "x"))
    pasted = paste_ok(stack, node(target, "nb"), copied(source, "x"))
    (page,) = pasted.nodes
    assert isinstance(page, Widget) and page.id == "x1"
    assert isinstance(page.placement, PagePlacement) and page.placement.text is not None
    assert page.placement.text.value == "x1"


def test_a_paned_window_gets_pages_without_text() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(PAGES)
    pasted = paste_ok(stack, node(target, "pw"), copied(source, "x", "y"))
    assert all(
        isinstance(n.placement, PagePlacement) and n.placement.text is None
        for n in pasted.nodes
        if isinstance(n, Widget)
    )
    assert not [f for f in validate(target, REG).findings if f.code == "validate.page_attr_ignored"]


def test_a_leaf_inside_a_notebook_pastes_after_it_as_a_page() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(
        _ui(
            '<window id="pg" kind="main"><layout type="pack"/>'
            '<widget class="Notebook" id="nb"><pack/>'
            '<widget class="Label" id="one"><page/></widget>'
            '<widget class="Label" id="two"><page/></widget></widget></window>'
        )
    )
    pasted = paste_ok(stack, node(target, "one"), copied(source, "x"))
    nb = node(target, "nb")
    assert isinstance(nb, Widget) and [c.id for c in nb.children] == ["one", "x", "two"]
    assert isinstance(pasted.nodes[0], Widget)
    assert isinstance(pasted.nodes[0].placement, PagePlacement)


def test_grid_to_pack_and_pack_to_grid_keep_the_reading_order_of_many_nodes() -> None:
    grid = _ui(
        '<window id="g" kind="main"><layout type="grid"/>'
        '<widget class="Label" id="c3"><cell row="1" column="1"/></widget>'
        '<widget class="Label" id="c1"><cell row="0" column="0"/></widget>'
        '<widget class="Label" id="c2"><cell row="0" column="1"/></widget></window>'
    )
    source, _s = load(grid)
    text = copied(source, "c1", "c2", "c3")
    target, stack = load(PACK)
    paste_ok(stack, node(target, "pk"), text)
    assert [c.id for c in target.children[0].children][-3:] == ["c1", "c2", "c3"]
    # and back: a pack source into the grid, rows in reading order at column 0
    pack_text = copied(target, "a", "b", "c")
    gtarget, gstack = load(grid)
    pasted = paste_ok(gstack, node(gtarget, "g"), pack_text)
    assert [n.placement for n in pasted.nodes if isinstance(n, Widget)] == [
        GridCell(row=2, column=0),
        GridCell(row=3, column=0),
        GridCell(row=4, column=0),
    ]


def test_a_statusbar_selection_pastes_into_its_window_body() -> None:
    source, _s = load(OTHER_PACK)
    target, stack = load(
        _ui(
            '<window id="s" kind="main"><statusbar id="sb"/><layout type="pack"/>'
            '<widget class="Button" id="a"><pack/></widget></window>'
        )
    )
    paste_ok(stack, node(target, "sb"), copied(source, "x"))
    assert [c.id for c in target.children[0].children] == ["a", "x"]


# ---------------------------------------------------------------- rebasing paths
IMAGES = _ui(
    '<resources><image id="logo" src="icons/logo.png"/></resources>'
    '<window id="w" kind="main"><layout type="pack"/>'
    '<widget class="Label" id="lbl"><prop name="image" ref="logo"/><pack/></widget></window>'
)
IMAGE_TARGET = _ui('<window id="t" kind="main"><layout type="pack"/></window>')


@pytest.mark.parametrize(
    ("base", "expected"),
    [
        (Path("C:/proj/a"), "icons/logo.png"),  # same folder: unchanged
        (Path("C:/proj/b"), "../a/icons/logo.png"),  # sibling folder
        (Path("C:/proj/a/sub"), "../icons/logo.png"),  # deeper
        (Path("C:/proj"), "a/icons/logo.png"),  # shallower
        (Path("C:/proj/a/icons"), "logo.png"),
    ],
)
def test_relative_image_src_is_rebased_between_folders(base: Path, expected: str) -> None:
    source, _s = load(IMAGES)
    text = copied(source, "lbl", origin=ORIGIN_A)
    target, stack = load(IMAGE_TARGET)
    paste_ok(stack, node(target, "t"), text, base=base)
    assert target.resources["logo"].src == expected


def test_a_clip_without_origin_keeps_the_relative_src_untouched() -> None:
    source, _s = load(IMAGES)
    target, stack = load(IMAGE_TARGET)
    paste_ok(stack, node(target, "t"), copied(source, "lbl"), base=Path("C:/proj/b"))
    assert target.resources["logo"].src == "icons/logo.png"
    target2, stack2 = load(IMAGE_TARGET)
    paste_ok(stack2, node(target2, "t"), copied(source, "lbl"), base=None)  # no origin, untitled
    assert target2.resources["logo"].src == "icons/logo.png"


def test_an_absolute_src_is_never_rebased() -> None:
    source, _s = load(IMAGES.replace("icons/logo.png", "C:/shared/logo.png"))
    target, stack = load(IMAGE_TARGET)
    paste_ok(stack, node(target, "t"), copied(source, "lbl", origin=ORIGIN_A), Path("C:/proj/b"))
    assert target.resources["logo"].src == "C:/shared/logo.png"


def test_the_same_image_by_resolved_path_is_reused_not_duplicated() -> None:
    source, _s = load(IMAGES)
    text = copied(source, "lbl", origin=ORIGIN_A)
    target, stack = load(
        _ui(
            '<resources><image id="logo" src="../a/icons/logo.png"/></resources>'
            '<window id="t" kind="main"><layout type="pack"/></window>'
        )
    )
    (label,) = paste_ok(stack, node(target, "t"), text, base=Path("C:/proj/b")).nodes
    assert isinstance(label, Widget) and label.props["image"].ref == "logo"
    assert list(target.resources) == ["logo"]


def test_an_external_include_src_is_rebased_with_the_images() -> None:
    source, _s = load(
        _ui(
            '<window id="w" kind="main"><layout type="pack"/>'
            '<include id="ext" src="parts/panel.ui" component="panel"><pack/></include></window>'
        )
    )
    target, stack = load(IMAGE_TARGET)
    (inc,) = paste_ok(
        stack, node(target, "t"), copied(source, "ext", origin=ORIGIN_A), Path("C:/proj/b")
    ).nodes
    assert isinstance(inc, Include) and inc.src == "../a/parts/panel.ui"
    untitled, ustack = load(IMAGE_TARGET)
    (inc2,) = paste_ok(ustack, node(untitled, "t"), copied(source, "ext", origin=ORIGIN_A)).nodes
    assert isinstance(inc2, Include) and Path(inc2.src) == Path("C:/proj/a/parts/panel.ui")


def test_a_network_origin_is_never_used_to_rebase() -> None:
    source, _s = load(IMAGES)
    text = copied(source, "lbl", origin=ORIGIN_A).replace(
        "C:/proj/a/form.ui", "//server/share/f.ui"
    )
    target, stack = load(IMAGE_TARGET)
    paste_ok(stack, node(target, "t"), text, base=Path("C:/proj/b"))
    assert target.resources["logo"].src == "icons/logo.png"


# ---------------------------------------------------------------- windows mode
BARS = _ui(
    '<variables><var id="flag" type="bool"/></variables>'
    '<window id="main" kind="main">'
    '<menubar><menu id="m"><action id="act"/><menu id="sub"><action id="deep"/></menu></menu>'
    "</menubar>"
    '<statusbar id="sb"/><layout type="pack"/>'
    '<widget class="Checkbutton" id="chk" bind="flag"><pack/></widget></window>'
)


def test_windows_mode_remaps_menu_action_and_statusbar_ids_and_variables() -> None:
    document, stack = load(BARS)
    (window,) = paste_ok(stack, document.children[0], copied(document, "main")).nodes
    assert isinstance(window, Window) and window.kind == "dialog" and window.id == "main1"
    assert window.menubar is not None and window.statusbar is not None
    menu: Any = window.menubar.children[0]
    assert (menu.id, menu.children[0].id, menu.children[1].children[0].id) == (
        "m1",
        "act1",
        "deep1",
    )
    assert window.statusbar.id == "sb1"
    assert [c.id for c in window.children] == ["chk1"]
    assert not validate(document, REG).errors and len(_ids(document)) == len(set(_ids(document)))


def test_windows_mode_into_another_file_keeps_free_ids_and_brings_variables() -> None:
    source, _s = load(BARS)
    target, stack = load(IMAGE_TARGET)
    (window,) = paste_ok(stack, target.children[0], copied(source, "main")).nodes
    assert isinstance(window, Window) and window.id == "main" and window.kind == "dialog"
    assert set(target.variables) == {"flag"} and window.menubar is not None
    assert [w.id for w in target.children] == ["t", "main"]


# ======================================================================================
# Abuse
# ======================================================================================
@pytest.mark.parametrize("size", [11 * 1024 * 1024, 100 * 1024 * 1024])
def test_a4_oversize_text_is_refused_at_once(size: int) -> None:
    document, _stack = load(SOURCE)
    text = "x" * size
    started = time.perf_counter()
    result = paste_command(document, document.children[0], text, REG, None)
    elapsed = time.perf_counter() - started
    assert result == "The clipboard content is too large to paste."
    assert elapsed < 0.5, f"{elapsed:.2f}s to refuse {size} characters"


def test_a4_multibyte_text_just_over_the_byte_limit_is_refused_quickly() -> None:
    document, _stack = load(SOURCE)
    text = "<" + "ß" * (MAX_UI_BYTES // 2)  # fewer characters than bytes: over the byte limit
    started = time.perf_counter()
    assert paste_command(document, document.children[0], text, REG, None) == (
        "The clipboard content is too large to paste."
    )
    assert time.perf_counter() - started < 0.5


def _labels(count: int, mode: str = "widgets") -> str:
    widgets = "".join(f'<widget class="Label" id="w{k}"><pack/></widget>' for k in range(count))
    return (
        f"{CLIP_HEAD.format(mode=mode)}"
        f'<window id="c" kind="component"><layout type="pack"/>{widgets}</window></pyguibud-ui>'
    )


def test_a4_exactly_the_widget_limit_is_accepted_and_fast() -> None:
    document, stack = load(SOURCE)
    started = time.perf_counter()
    pasted = paste_command(document, document.children[0], _labels(2000), REG, None)
    assert isinstance(pasted, Pasted) and len(pasted.nodes) == 2000
    assert stack.execute(pasted.command).accepted
    assert time.perf_counter() - started < 5.0


def test_a4_the_widget_limit_counts_nested_widgets_and_includes() -> None:
    document, _stack = load(SOURCE)
    inner = "".join(f'<widget class="Label" id="n{k}"><pack/></widget>' for k in range(1001))
    inc = "".join(
        f'<include id="i{k}" src="#" component="comp"><pack/></include>' for k in range(1000)
    )
    text = (
        f"{CLIP_HEAD.format(mode='widgets')}"
        '<window id="c" kind="component"><layout type="pack"/>'
        f'<widget class="Frame" id="f"><pack/><layout type="pack"/>{inner}</widget>{inc}'
        "</window></pyguibud-ui>"
    )
    assert paste_command(document, document.children[0], text, REG, None) == (
        "Paste refused: more than 2000 widgets."
    )


def test_a4_a_deeply_nested_clip_is_refused_without_recursion_errors() -> None:
    document, _stack = load(SOURCE)
    text = CLIP_HEAD.format(mode="widgets") + "<a>" * 5000 + "</a>" * 5000 + "</pyguibud-ui>"
    started = time.perf_counter()
    assert paste_command(document, document.children[0], text, REG, None) == NO_ELEMENTS
    assert time.perf_counter() - started < 2.0


BILLION = (
    '<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY a "aaaaaaaaaa">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
    '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">'
    '<!ENTITY d "&c;&c;&c;&c;&c;&c;&c;&c;&c;&c;">'
    '<!ENTITY e "&d;&d;&d;&d;&d;&d;&d;&d;&d;&d;">]>'
    '<pyguibud-ui xmlns="urn:pyguibud:ui:1" xmlns:clip="urn:pyguibud:clipboard:1"'
    ' clip:mode="widgets">&e;</pyguibud-ui>'
)
FOREIGN = [
    "",
    "   \n\t ",
    "hello world",
    "\x00\x01\x02",
    "\ud800",  # a lone surrogate
    "<html><body><p>hi</p></body></html>",
    '<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>',
    BILLION,
    '<?xml version="1.0"?><!DOCTYPE x SYSTEM "file:///etc/passwd"><x/>',
    '<!DOCTYPE pyguibud-ui [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]>'
    + CLIP_HEAD.format(mode="widgets")
    + "&x;</pyguibud-ui>",
    "\ufeff" + CLIP_HEAD.format(mode="nonsense") + "</pyguibud-ui>",  # an unknown mode
    CLIP_HEAD.format(mode="widgets") + "</pyguibud-ui>",  # no wrapper window
    CLIP_HEAD.format(mode="widgets")
    + '<window id="a" kind="component"><layout type="pack"/></window>'
    + '<window id="b" kind="component"><layout type="pack"/></window></pyguibud-ui>',
    CLIP_HEAD.format(mode="widgets") + "<window",  # truncated
    "{}",
    "[1, 2, 3]",
    "<pyguibud-ui/>",
]


@pytest.mark.parametrize("text", FOREIGN, ids=[f"foreign{k}" for k in range(len(FOREIGN))])
def test_a6_foreign_text_xml_bombs_and_dtds_are_refused_without_a_change(text: str) -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    started = time.perf_counter()
    result = paste_command(document, document.children[0], text, REG, None)
    assert time.perf_counter() - started < 1.0
    assert isinstance(result, str) and result  # a reason, never a command
    assert result == NO_ELEMENTS or result.startswith("The clipboard content is not valid: ")
    assert dump_ui(document) == before and not stack.can_undo


def test_a6_a_marked_clip_with_an_unknown_class_names_the_reason() -> None:
    document, _stack = load(SOURCE)
    text = _labels(1).replace("Label", "Nonexistent")
    result = paste_command(document, document.children[0], text, REG, None)
    assert isinstance(result, str) and result.startswith("The clipboard content is not valid: ")


def test_a6_windows_mode_with_no_windows_and_a_non_ui_root() -> None:
    document, _stack = load(SOURCE)
    empty_clip = CLIP_HEAD.format(mode="windows") + "</pyguibud-ui>"
    result = paste_command(document, document.children[0], empty_clip, REG, None)
    if isinstance(result, Pasted):  # nothing to insert is harmless; it must not change anything
        assert not result.nodes
    else:
        assert result == NO_ELEMENTS


# ---------------------------------------------------------------- A5
def _refused(document: Document, stack: CommandStack, selected: object, text: str) -> str:
    before = dump_ui(document)
    pasted = paste_command(document, selected, text, REG, None)
    if isinstance(pasted, str):
        assert dump_ui(document) == before
        return pasted
    outcome = stack.execute(pasted.command)
    assert not outcome.accepted and outcome.message
    assert dump_ui(document) == before and not stack.can_undo
    return outcome.message


@pytest.mark.parametrize("target", ["menubar", "file_menu", "act_quit"])
def test_a5_paste_into_menu_nodes_gives_a_reason_and_changes_nothing(target: str) -> None:
    document, stack = load(SOURCE)
    text = copied(document, "lbl", "ent")
    selected = document.children[0].menubar if target == "menubar" else node(document, target)
    assert _refused(document, stack, selected, text)


def test_a5_paste_after_a_menu_separator_is_refused() -> None:
    document, stack = load(
        _ui(
            '<window id="m" kind="main"><menubar><menu id="mm"><separator/></menu></menubar>'
            '<layout type="pack"/><widget class="Label" id="l"><pack/></widget></window>'
        )
    )
    separator = document.children[0].menubar.children[0].children[0]  # type: ignore[union-attr]
    assert _refused(document, stack, separator, copied(document, "l"))


def test_a5_grid_that_cannot_take_the_block_below_its_last_row_is_refused() -> None:
    document, stack = load(
        _ui(
            '<window id="g" kind="main"><layout type="grid"/>'
            '<widget class="Label" id="far"><cell row="9998" column="0"/></widget></window>'
        )
    )
    reason = _refused(document, stack, document.children[0], copied(document, "far"))
    assert reason  # the block would start at row 9999, outside the grid limits


def test_a5_a_block_whose_height_overflows_the_grid_is_refused() -> None:
    document, stack = load(
        _ui(
            '<window id="g" kind="main"><layout type="grid"/>'
            '<widget class="Label" id="top"><cell row="0" column="0"/></widget>'
            '<widget class="Label" id="low"><cell row="9000" column="0"/></widget></window>'
        )
    )
    text = copied(document, "top", "low")
    assert _refused(document, stack, document.children[0], text)


def test_a5_the_error_cases_leave_the_clipboard_text_usable() -> None:
    document, stack = load(SOURCE)
    text = copied(document, "lbl")
    assert _refused(document, stack, node(document, "act_quit"), text)
    pasted = paste_command(document, document.children[0], text, REG, None)  # same text, now fine
    assert isinstance(pasted, Pasted) and stack.execute(pasted.command).accepted


def test_a5_an_unpasteable_selection_type_raises_a_type_error_not_a_corruption() -> None:
    """The actions never pass a Document or None (they use the current window); pin the contract."""
    document, _stack = load(SOURCE)
    text = copied(document, "lbl")
    before = dump_ui(document)
    for bad in (document, None):
        with pytest.raises(TypeError):
            paste_command(document, bad, text, REG, None)
    assert dump_ui(document) == before


# ---------------------------------------------------------------- A13
THREE = _ui(
    '<window id="main" kind="main"><layout type="pack"/>'
    '<include id="uses" src="#" component="part"><pack/></include></window>'
    '<window id="part" kind="component"><layout type="pack"/></window>'
    '<window id="free" kind="dialog"><layout type="pack"/></window>'
)


def test_a13_cut_of_windows_refuses_the_last_and_the_included_and_allows_the_rest() -> None:
    document, stack = load(THREE)
    main, part, free = document.children
    before = dump_ui(document)
    assert cut_command(document, [part], None) == "'part' is still included by 'main'."
    assert (
        cut_command(document, [main, part, free], None) == "A document needs at least one window."
    )
    result = cut_command(document, [free], None)
    assert not isinstance(result, str)
    assert stack.execute(result[1]).accepted and [w.id for w in document.children] == [
        "main",
        "part",
    ]
    assert stack.undo() and dump_ui(document) == before


def test_a13_a_refused_cut_leaves_the_clipboard_and_the_document_alone() -> None:
    session = DesignerSession(REG)
    session.open_result(read_ui_string(THREE), name="t")
    store = {"text": "SENTINEL"}
    messages: list[str] = []
    actions = ClipboardActions(
        session,
        messages.append,
        lambda text: store.__setitem__("text", text),
        lambda: store["text"],
    )
    document = session.document
    assert document is not None
    part = node(document, "part")
    before = dump_ui(document)
    session.select(part, origin="tree")
    actions.cut()
    assert store["text"] == "SENTINEL" and messages == ["'part' is still included by 'main'."]
    assert dump_ui(document) == before and session.stack is not None and not session.stack.can_undo
    session.select_many(list(document.children), origin="tree")
    assert len(session.selection.nodes) == 1  # windows never form a multi-selection
    session.select(node(document, "main"), origin="tree")
    actions.cut()  # 'main' is the only window that includes 'part', not included itself: allowed
    assert "clip:mode" in store["text"] and store["text"] != "SENTINEL"
    store["text"] = "SENTINEL"
    session.stack.undo()
    assert dump_ui(document) == before
    # a menu node cannot be copied, so cutting it leaves the clipboard alone as well
    session.select(node(document, "free"), origin="tree")
    actions.cut()
    assert "clip:mode" in store["text"]


def test_cut_copy_paste_duplicate_through_the_actions_are_single_undo_steps() -> None:
    session = DesignerSession(REG)
    session.open_result(read_ui_string(SOURCE), name="t")
    store = {"text": ""}
    actions = ClipboardActions(
        session, lambda _m: None, lambda t: store.__setitem__("text", t), lambda: store["text"]
    )
    document, stack = session.document, session.stack
    assert document is not None and stack is not None
    for ids, run in (
        (["lbl", "ent"], actions.duplicate),
        (["btn_ok"], actions.cut),
    ):
        before, depth = dump_ui(document), stack.index
        session.select_many([node(document, i) for i in ids], origin="tree")
        run()
        assert stack.index == depth + 1 and dump_ui(document) != before
        assert stack.undo() and dump_ui(document) == before and stack.index == depth
        assert stack.redo()
    before, depth = dump_ui(document), stack.index
    session.select(node(document, "ent"), origin="tree")
    actions.copy()
    assert stack.index == depth  # copy changes nothing and records nothing
    session.select_many([node(document, "frm")], origin="tree")
    actions.paste()
    assert stack.index == depth + 1
    assert stack.undo() and dump_ui(document) == before


# ---------------------------------------------------------------- duplicate
def test_duplicate_of_several_nodes_keeps_their_order_and_stays_valid() -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    result = duplicate_command(document, [node(document, "ent"), node(document, "lbl")], REG)
    assert isinstance(result, Pasted) and stack.execute(result.command).accepted
    assert [n.id for n in result.nodes if isinstance(n, Widget)] == ["lbl1", "ent1"]
    assert not validate(document, REG).errors
    assert stack.undo() and dump_ui(document) == before


# ---------------------------------------------------------------- performance
def test_paste_of_500_widgets_stays_inside_its_budget() -> None:
    document, stack = load(SOURCE)
    text = _labels(500)
    target = document.children[0]

    def paste_and_undo() -> None:
        pasted = paste_command(document, target, text, REG, None)
        assert isinstance(pasted, Pasted)
        assert stack.execute(pasted.command).accepted
        assert stack.undo()

    best = best_of(paste_and_undo, repeat=3)
    assert best <= 1.5, f"paste of 500 widgets took {best:.2f}s (budget 1.5s)"


def test_the_500_widget_paste_is_one_undo_step() -> None:
    document, stack = load(SOURCE)
    before = dump_ui(document)
    pasted = paste_command(document, document.children[0], _labels(500), REG, None)
    assert isinstance(pasted, Pasted) and stack.execute(pasted.command).accepted
    assert stack.undo() and dump_ui(document) == before and not stack.can_undo
