"""Layout semantics (spec backends §4.2) and the static menus of 16b (§14) with PySide6."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from PySide6 import QtCore, QtTest, QtWidgets
from PySide6.QtCore import Qt

from pyguibud_runtime import LoadedUi, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

pytestmark = pytest.mark.qt

DATA = Path(__file__).resolve().parents[1] / "codegen" / "data"
GIF = (
    b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
    b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
)
PPM = b"P6\n1 1\n255\n\x00\x00\x00"
A = Qt.AlignmentFlag


@pytest.fixture
def loaded(qapp: Any) -> Iterator[list[LoadedUi]]:
    """Collects the interfaces of a test and destroys them afterwards."""
    uis: list[LoadedUi] = []
    yield uis
    for ui in uis:
        ui.destroy()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)


def _load(path: Path, uis: list[LoadedUi], **options: Any) -> LoadedUi:
    ui = load_ui(path, None, strict=False, backend="pyside6", **options)
    uis.append(ui)
    return ui


def _resized(ui: LoadedUi, width: int = 800, height: int = 600) -> None:
    ui.main.resize(width, height)
    QtTest.QTest.qWait(30)
    ui.main.centralWidget().layout().activate()


def _item(item: Any) -> Any:
    """A layout item that must exist (``itemAt`` is typed Optional)."""
    assert item is not None
    return item


# ---------------------------------------------------------------- grid
def _grid_ui(tmp_path: Path, weights: str) -> Path:
    return write_ui(
        tmp_path / "grid.ui",
        f'<window id="main"><layout type="grid">{weights}</layout>'
        '<widget class="Entry" id="ent"><cell row="0" column="0" sticky="nsew"/></widget>'
        "</window>",
    )


def test_a_grid_without_weights_leaves_extra_space_unused(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    ui = _load(_grid_ui(tmp_path, ""), loaded)  # an Expanding entry that fills its cell
    _resized(ui)
    hint = ui.ent.sizeHint()
    assert ui.ent.width() == hint.width() and ui.ent.height() == hint.height()
    assert ui.ent.width() < 400


def test_a_grid_with_weights_stretches_its_cells(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    weights = '<column index="0" weight="1"/><row index="0" weight="1"/>'
    ui = _load(_grid_ui(tmp_path, weights), loaded)
    _resized(ui)
    body = ui.main.centralWidget()
    assert ui.ent.width() == body.width() and ui.ent.height() == body.height()
    assert ui.ent.width() > 700


def test_grid_sticky_becomes_cell_alignment(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    cells = {"w": (0, 0), "ne": (0, 1), "nsew": (1, 0), "": (1, 1), "ns": (2, 0), "s": (2, 1)}
    widgets = "".join(
        f'<widget class="Button" id="b{row}{col}"><prop name="text">B</prop>'
        f'<cell row="{row}" column="{col}"{f" sticky={chr(34)}{s}{chr(34)}" if s else ""}/>'
        "</widget>"
        for s, (row, col) in cells.items()
    )
    path = write_ui(
        tmp_path / "sticky.ui",
        f'<window id="main"><layout type="grid" padding="3" gap="2"/>{widgets}</window>',
    )
    ui = _load(path, loaded)
    grid = ui.main.centralWidget().layout()
    assert isinstance(grid, QtWidgets.QGridLayout)
    assert grid.contentsMargins().left() == 3 and grid.horizontalSpacing() == 2
    expected = {
        "w": A.AlignLeft | A.AlignVCenter,
        "ne": A.AlignRight | A.AlignTop,
        "nsew": A(0),
        "": A.AlignHCenter | A.AlignVCenter,
        "ns": A.AlignHCenter,
        "s": A.AlignHCenter | A.AlignBottom,
    }
    for sticky, (row, col) in cells.items():
        item = _item(grid.itemAtPosition(row, col))
        assert item.widget() is getattr(ui, f"b{row}{col}"), sticky
        assert item.alignment() == expected[sticky], sticky
    # A button filling "ns" may grow vertically (its Fixed policy becomes Preferred).
    vertical = ui.b20.sizePolicy().verticalPolicy()
    assert vertical == QtWidgets.QSizePolicy.Policy.Preferred
    assert ui.b21.sizePolicy().verticalPolicy() == QtWidgets.QSizePolicy.Policy.Fixed


# ---------------------------------------------------------------- pack
def test_pack_expand_and_fill(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    path = write_ui(
        tmp_path / "pack.ui",
        '<window id="main"><layout type="pack" gap="5"/>'
        '<widget class="Entry" id="top"><pack fill="x"/></widget>'
        '<widget class="Text" id="mid"><pack fill="both" expand="true"/></widget>'
        '<widget class="Button" id="low"><prop name="text">B</prop><pack/></widget>'
        "</window>",
    )
    ui = _load(path, loaded)
    _resized(ui)
    box = ui.main.centralWidget().layout()
    assert isinstance(box, QtWidgets.QVBoxLayout) and box.spacing() == 5
    assert [box.stretch(i) for i in range(3)] == [0, 1, 0]
    assert box.count() == 3  # a child expands: no trailing stretch
    assert _item(box.itemAt(0)).alignment() == A(0) and _item(box.itemAt(1)).alignment() == A(0)
    assert _item(box.itemAt(2)).alignment() == A.AlignHCenter
    body = ui.main.centralWidget()
    assert ui.top.width() == body.width() and ui.mid.width() == body.width()
    assert ui.mid.height() > 400  # it takes the extra height
    assert ui.low.width() < body.width() // 2  # neither filled nor expanded: centred, own size


def test_horizontal_pack_without_expand_gets_a_trailing_stretch(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(
        tmp_path / "hpack.ui",
        '<window id="main"><layout type="pack" orient="horizontal"/>'
        '<widget class="Button" id="one"><prop name="text">1</prop><pack fill="y"/></widget>'
        '<widget class="Button" id="two"><prop name="text">2</prop><pack/></widget></window>',
    )
    ui = _load(path, loaded)
    box = ui.main.centralWidget().layout()
    assert isinstance(box, QtWidgets.QHBoxLayout) and box.count() == 3
    assert _item(box.itemAt(2)).spacerItem() is not None and box.stretch(2) == 1
    assert (
        _item(box.itemAt(0)).alignment() == A(0)
        and _item(box.itemAt(1)).alignment() == A.AlignVCenter
    )


# ---------------------------------------------------------------- pages
def test_notebook_tab_texts_carry_the_mnemonic_and_literal_ampersands(
    tmp_path: Path, loaded: list[LoadedUi]
) -> None:
    path = write_ui(
        tmp_path / "tabs.ui",
        '<window id="main"><layout type="pack"/>'
        '<widget class="Notebook" id="nbk"><pack fill="both" expand="true"/>'
        '<widget class="Frame" id="one"><page><prop name="text">Save &amp; _load</prop></page>'
        '<layout type="pack"/></widget>'
        '<widget class="Frame" id="two"><page><prop name="text">Plain</prop></page>'
        '<layout type="pack"/></widget></widget></window>',
    )
    ui = _load(path, loaded)
    assert [ui.nbk.tabText(i) for i in range(2)] == ["Save && &load", "Plain"]
    assert ui.nbk.widget(0) is ui.one and ui.nbk.widget(1) is ui.two


@pytest.mark.parametrize(
    ("orient", "expected"),
    [("horizontal", Qt.Orientation.Horizontal), (None, Qt.Orientation.Vertical)],  # Tk default
)
def test_splitter_orientation_and_weights(
    tmp_path: Path, loaded: list[LoadedUi], orient: str | None, expected: Any
) -> None:
    prop = f'<prop name="orient">{orient}</prop>' if orient else ""
    path = write_ui(
        tmp_path / "split.ui",
        '<window id="main"><layout type="pack"/>'
        f'<widget class="PanedWindow" id="pnd">{prop}<pack fill="both" expand="true"/>'
        '<widget class="Frame" id="a"><page weight="3"/><layout type="pack"/></widget>'
        '<widget class="Frame" id="b"><page/><layout type="pack"/></widget></widget></window>',
    )
    ui = _load(path, loaded)
    assert isinstance(ui.pnd, QtWidgets.QSplitter) and ui.pnd.orientation() == expected
    assert ui.pnd.count() == 2 and ui.pnd.widget(0) is ui.a
    vertical = expected == Qt.Orientation.Vertical

    def stretch(widget: Any) -> int:
        policy = widget.sizePolicy()
        return int(policy.verticalStretch() if vertical else policy.horizontalStretch())

    assert (stretch(ui.a), stretch(ui.b)) == (3, 0)


# ---------------------------------------------------------------- static menus (16b, §14)
def _tree(menu: Any) -> list[Any]:
    """(text, enabled, icon) per action, "---" per separator, (title, children) per sub-menu."""
    items: list[Any] = []
    for action in menu.actions():
        if action.isSeparator():
            items.append("---")
        elif action.menu() is not None:
            items.append((action.menu().title(), _tree(action.menu())))
        else:
            items.append((action.text(), action.isEnabled(), not action.icon().isNull()))
    return items


def _menubar(ui: LoadedUi) -> list[Any]:
    return [(action.menu().title(), _tree(action.menu())) for action in ui.main.menuBar().actions()]


def test_the_menu_tree_of_rich_ui(tmp_path: Path, loaded: list[LoadedUi]) -> None:
    shutil.copy(DATA / "rich.ui", tmp_path / "rich.ui")
    (tmp_path / "pic.gif").write_bytes(GIF)
    (tmp_path / "pic.ppm").write_bytes(PPM)
    ui = _load(tmp_path / "rich.ui", loaded)
    assert _menubar(ui) == [
        ("&Edit", [("&Open", False, True), "---", ("&More", [("Again", True, False)])])
    ]
    assert ui.mnu_sub.menuAction().parent() is not None


def test_the_menu_tree_of_hello_ui_and_its_translation(loaded: list[LoadedUi]) -> None:
    ui = _load(EXAMPLES / "hello.ui", loaded)
    assert _menubar(ui) == [("&File", [("&Quit", True, False)])]
    ui.retranslate("de_DE")
    assert _menubar(ui) == [("&Datei", [("&Beenden", True, False)])]
    ui.retranslate("en_GB")
    assert _menubar(ui) == [("&File", [("&Quit", True, False)])]


class _FailsOnQuit:
    """A translator whose ``_Quit`` is not a str: the whole retranslation must be refused."""

    def gettext(self, message: str) -> object:
        return None if message == "_Quit" else message.upper()

    def pgettext(self, context: str, message: str) -> object:
        return message.upper()


def test_a_failed_retranslate_changes_no_menu_text(loaded: list[LoadedUi]) -> None:
    ui = _load(EXAMPLES / "hello.ui", loaded, lang="de_DE")
    before = (_menubar(ui), ui.main.windowTitle(), ui.btn_greet.text())
    assert before[0] == [("&Datei", [("&Beenden", True, False)])]
    with pytest.raises(TypeError):
        ui.retranslate(translator=_FailsOnQuit())  # type: ignore[arg-type]
    assert (_menubar(ui), ui.main.windowTitle(), ui.btn_greet.text()) == before
