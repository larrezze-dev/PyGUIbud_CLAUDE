"""The Qt reader of ``portable_describe`` (spec backends 7): the Tk reader's view, read from the
built PySide6 objects. Imported only for ``pyside6`` (ADR-013: the preview loads no toolkit)."""

from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from pyguibud.backends._qtmap import split_qt_text
from pyguibud.preview._describe import min_size, pack_fill, portable_shortcut

__all__ = ["qt_portable_describe"]

W = QtWidgets
_A = QtCore.Qt.AlignmentFlag
_LINES = (W.QFrame.Shape.HLine, W.QFrame.Shape.VLine)
_CLASSES = (  # most specific first: QLabel and the scroll areas are QFrames too
    *((W.QLabel, "Label"), (W.QPushButton, "Button"), (W.QCheckBox, "Checkbutton")),
    *((W.QRadioButton, "Radiobutton"), (W.QLineEdit, "Entry"), (W.QPlainTextEdit, "Text")),
    *((W.QComboBox, "Combobox"), (W.QDoubleSpinBox, "Spinbox"), (W.QSlider, "Scale")),
    *((W.QProgressBar, "Progressbar"), (W.QScrollBar, "Scrollbar"), (W.QListWidget, "Listbox")),
    *((W.QTreeWidget, "Treeview"), (W.QGraphicsView, "Canvas"), (W.QTabWidget, "Notebook")),
    *((W.QSplitter, "PanedWindow"), (W.QGroupBox, "LabelFrame")),
)
#: The classes whose Tk widget has a ``state`` option (the Tk reader reports only those).
_STATEFUL = {"Label", "Button", "Entry", "Checkbutton", "Radiobutton", "Combobox", "Spinbox"}
_STATEFUL |= {"Scale", "Text", "Listbox", "Canvas"}
_KEEP_TEXT = {"Checkbutton", "Radiobutton", "Scale", "Progressbar"}  # Tk ``variable``, not text


def _wh(size: Any) -> tuple[int, int]:  # noqa: ANN401 - a QSize
    return size.width(), size.height()


def _mnemonic(index: int) -> int | None:
    return index if index >= 0 else None


def _area(widget: Any) -> Any:  # noqa: ANN401 - Qt objects
    """The ``QScrollArea`` showing ``widget`` (a ScrolledFrame's inner widget), or None."""
    viewport = widget.parentWidget()
    area = viewport.parentWidget() if viewport is not None else None
    return area if isinstance(area, W.QScrollArea) and area.widget() is widget else None


def _class(widget: Any) -> str:  # noqa: ANN401 - a QWidget
    for qt_class, name in _CLASSES:
        if isinstance(widget, qt_class):
            return name
    if isinstance(widget, W.QFrame) and widget.frameShape() in _LINES:
        return "Separator"
    return "ScrolledFrame" if _area(widget) is not None else "Frame"  # an include is a QWidget


def _menu(actions: Any) -> list[dict[str, Any]]:  # noqa: ANN401 - QActions
    items: list[dict[str, Any]] = []
    for action in actions:
        if action.isSeparator():
            items.append({"separator": True})
            continue
        text, mnemonic = split_qt_text(action.text())
        shortcut = action.shortcut().toString(QtGui.QKeySequence.SequenceFormat.PortableText)
        item: dict[str, Any] = {
            "text": text,
            "mnemonic": _mnemonic(mnemonic),
            "shortcut": portable_shortcut(shortcut),
            "enabled": action.isEnabled(),
            "image": not action.icon().isNull(),
        }
        if action.menu() is not None:
            item["items"] = _menu(action.menu().actions())
        items.append(item)
    return items


def _sides(flags: Any, low: Any, high: Any, centre: Any, names: str) -> str:  # noqa: ANN401
    """One axis of ``sticky`` from a layout item's alignment (no flag: both sides)."""
    if flags & low:
        return names[0]
    if flags & high:
        return names[1]
    return "" if flags & centre else names


def _placement(outer: Any) -> dict[str, Any]:  # noqa: ANN401 - a QWidget
    parent = outer.parentWidget()
    book = parent.parentWidget() if isinstance(parent, W.QStackedWidget) else None
    if isinstance(book, W.QTabWidget):
        index = book.indexOf(outer)
        text, mnemonic = split_qt_text(book.tabText(index))
        image = not book.tabIcon(index).isNull()
        return {"page": index, "text": text, "mnemonic": _mnemonic(mnemonic), "image": image}
    if isinstance(parent, W.QSplitter):
        return {"page": parent.indexOf(outer)}
    layout = parent.layout()
    index = layout.indexOf(outer)
    flags = layout.itemAt(index).alignment()
    if isinstance(layout, W.QGridLayout):
        position: Any = layout.getItemPosition(index)  # (row, column, rows, columns)
        row, column, rows, columns = position
        sticky = _sides(flags, _A.AlignLeft, _A.AlignRight, _A.AlignHCenter, "we")
        sticky += _sides(flags, _A.AlignTop, _A.AlignBottom, _A.AlignVCenter, "ns")
        return {"cell": [row, column], "span": [rows, columns], "sticky": "".join(sorted(sticky))}
    vertical = isinstance(layout, W.QVBoxLayout)  # _qt packs into QHBox/QVBox layouts
    expand = layout.stretch(index) > 0
    h_free, v_free = not flags & _A.AlignHCenter, not flags & _A.AlignVCenter
    fill_x, fill_y = (h_free, expand and v_free) if vertical else (expand and h_free, v_free)
    count = sum(layout.itemAt(i).widget() is not None for i in range(index))
    return {"pack": count, "fill": pack_fill(fill_x, fill_y, vertical, expand), "expand": expand}


def _parent_id(outer: Any, ids: dict[int, str]) -> str | None:  # noqa: ANN401 - a QWidget
    parent = outer.parentWidget()
    while parent is not None and id(parent) not in ids:
        parent = parent.parentWidget()
    return None if parent is None else ids[id(parent)]


def _state(widget: Any, name: str) -> str:  # noqa: ANN401 - a QWidget
    """The ``.ui`` state: a disabled Text is read-only in Qt (spec 4.3)."""
    if not widget.isEnabled() or (name == "Text" and widget.isReadOnly()):
        return "disabled"
    if name == "Combobox" and not widget.isEditable():
        return "readonly"
    return "readonly" if name in ("Entry", "Spinbox") and widget.isReadOnly() else "normal"


def _widget(widget: Any, scope: Any, ids: dict[int, str]) -> dict[str, Any]:  # noqa: ANN401
    name = _class(widget)
    outer = _area(widget) if name == "ScrolledFrame" else widget
    pixmap = widget.pixmap() if isinstance(widget, W.QLabel) else None
    icon = widget.icon() if isinstance(widget, W.QAbstractButton) else None
    info: dict[str, Any] = {
        "class": name,
        "parent": _parent_id(outer, ids),
        "place": _placement(outer),
        "image": (pixmap is not None and not pixmap.isNull())
        or (icon is not None and not icon.isNull()),
    }
    if name == "Label":
        info["text"] = widget.text()
    elif name in ("Button", "Checkbutton", "Radiobutton", "LabelFrame"):
        raw = widget.title() if name == "LabelFrame" else widget.text()
        info["text"], mnemonic = split_qt_text(raw)
        if mnemonic >= 0:
            info["mnemonic"] = mnemonic
    if name in _STATEFUL:
        info["state"] = _state(widget, name)
    if bound := widget.property("pyguibud_bind"):
        info["value"] = getattr(scope.vars, str(bound)).get()
        if name not in _KEEP_TEXT:
            info.pop("text", None)
    return info


def _flat(scope: Any, prefix: str = "") -> dict[str, tuple[Any, Any]]:  # noqa: ANN401
    """Every object of ``scope`` and its include scopes by (prefixed) id, with its scope."""
    found: dict[str, tuple[Any, Any]] = {}
    for key, obj in scope.widgets.items():
        if isinstance(obj, QtCore.QObject):
            found[prefix + key] = (obj, scope)
        else:
            found.update(_flat(obj, f"{prefix}{key}/"))
    return found


def qt_portable_describe(ui: Any) -> dict[str, Any]:  # noqa: ANN401 - a LoadedUi
    """``portable_describe(ui, "pyside6")``: the same schema as the Tk reader."""
    windows: dict[str, Any] = {}
    for key, top in ui.windows.items():
        main = isinstance(top, W.QMainWindow)
        bar = top.menuWidget() if main else top.layout().menuBar()  # menuBar() would create one
        # A dimension the .ui leaves unset gets the layout's own minimum (QLayout::activate).
        size, auto = top.minimumSize(), top.layout().totalMinimumSize()
        width, height = (v if v != a else 0 for v, a in zip(_wh(size), _wh(auto), strict=True))
        windows[key] = {
            "kind": "main" if main else "dialog",
            "title": top.windowTitle().replace("[*][*]", "[*]"),  # undo _qtmap.escape_title
            "minsize": min_size(width, height),
            "menubar": None if bar is None else _menu(bar.actions()),
            "status": None,
        }
    found = _flat(ui)
    ids = {id(obj): key for key, (obj, _scope) in found.items()}
    widgets: dict[str, Any] = {}
    for key, (obj, scope) in found.items():
        if key in windows:
            continue
        if isinstance(obj, W.QMenu):
            widgets[key] = {"class": "Menu", "items": _menu(obj.actions())}
        elif not isinstance(obj, W.QWidget):  # a QAction
            widgets[key] = "<menu entry>"
        elif isinstance(obj.parentWidget(), W.QStatusBar):
            windows[ids[id(obj.window())]]["status"] = obj.property("text")
            widgets[key] = "<status bar>"
        else:
            widgets[key] = _widget(obj, scope, ids)
    return {"windows": windows, "widgets": widgets}
