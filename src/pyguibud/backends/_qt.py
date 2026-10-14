"""The Qt builder of the PySide6 backend: turns a :class:`BuildPlan` into Qt windows (spec §4).

Imported only by ``PySide6Backend.build`` (ADR-007). Every ``QLabel`` is PlainText and every
text a widget could interpret as a mnemonic goes through ``_qtmap.qt_text``, so no ``.ui`` or
translated string is ever read as markup (B4). Variables are ``_vars`` objects bound both ways;
every signal, trace and event filter is connected after the whole build, so building fires
nothing (Tk's ``_arm``). Trims T3-T5 (spec §0) are applied: per-item padding is ignored,
requested sizes are minimum sizes, and a Label with an image and a text shows the image only.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from functools import partial
from typing import Any, TypeAlias

import shiboken6
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from pyguibud.backends import _vars
from pyguibud.backends._qtmap import (
    SELECTMODE,
    SIGNALS,
    UNITS,
    alignment,
    decimals,
    escape_title,
    pack_item,
    qt_key_sequences,
    qt_shortcut,
    qt_text,
    scaled_range,
)
from pyguibud.backends._tk import (
    _M_IGNORED_STYLES,
    _M_PLUGIN_FAILED,
    _M_SHORTCUT,
    _raw,
    _Slot,
    apply_slots,
)
from pyguibud.backends._tkmap import _BOOTSTYLE, _M_FALLBACK
from pyguibud.backends.base import BuildPlan, Instance, TextSlot
from pyguibud.core.keys import format_chord, parse_chord
from pyguibud.core.model import (
    Action,
    GridCell,
    Include,
    Layout,
    Menu,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    Prop,
    Widget,
    WidgetSpec,
    Window,
)
from pyguibud.core.registry import FactoryStage
from pyguibud.i18n import N_

__all__ = ["QtSession"]

#: A Qt object; typed loosely so that strict mypy passes with and without the PySide6 stubs.
Q: TypeAlias = Any
Setter = Callable[[str, int], object]
Value = Callable[[str], "str | None"]
Made = tuple[Q, Q]  # (outer: placed in the layout, inner: ``ui.<id>``)

# Translators: a program shows both Tk (tkinter) and Qt windows.
_M_MIXED = N_("Tk and Qt windows in one process: only one toolkit's windows respond at a time.")
# Translators: an image file of the .ui could not be decoded by Qt; it is not shown.
_M_IMAGE = N_("The image '{image}' cannot be displayed by Qt; it is left out.")
# Translators: {name} is a colour name from a .ui file, such as SeaGreen3.
_M_COLOUR = N_("The colour '{name}' of '{id}' is not known to Qt; the default colour is used.")
_M_RANGE = N_("The minimum of '{id}' is greater than its maximum; Qt uses them swapped.")
# Translators: padx and pady are .ui attribute names; keep them unchanged.
_M_PADDING = N_("The padding (padx, pady) of '{id}' is ignored by Qt.")
_M_LABEL_IMAGE = N_("The label '{id}' has an image and a text; Qt shows the image only.")
# Translators: a spin box is bound to a text variable whose value is not a number.
_M_SPIN_TEXT = N_("The spin box '{id}' cannot show a value that is not a number.")
#: A QLineEdit keeps 32767 characters by default and the next edit writes the cut text back to
#: its variable; a Tk Entry has no limit (QA-16c-03).
_MAX_LENGTH = 2**31 - 1
_VARS: dict[str, type[_vars.Var[Any]]] = {
    **{"string": _vars.StringVar, "int": _vars.IntVar},
    **{"double": _vars.DoubleVar, "bool": _vars.BooleanVar},
}
_PARSE: dict[str, Callable[[str], object]] = {  # the defaults, as ``_tk._make_vars``
    **{"string": str, "int": lambda v: int(v or 0)},
    **{"double": lambda v: float(v or 0), "bool": lambda v: v == "true"},
}
#: Sessions not destroyed yet. Strong references: Python owns the parentless windows, so a
#: dropped LoadedUi must not delete them (QA-16b-03); only the last live one quits (spec §14).
_LIVE: set[QtSession] = set()
#: The Qt class of each core class's inner widget: a plugin's ``inner`` must be one (D4).
_QT_CLASS = {
    **{"Frame": "QFrame", "LabelFrame": "QGroupBox", "Notebook": "QTabWidget"},
    **{"PanedWindow": "QSplitter", "ScrolledFrame": "QWidget", "Label": "QLabel"},
    **{"Button": "QPushButton", "Entry": "QLineEdit", "Text": "QPlainTextEdit"},
    **{"Checkbutton": "QCheckBox", "Radiobutton": "QRadioButton", "Combobox": "QComboBox"},
    **{"Spinbox": "QDoubleSpinBox", "Scale": "QSlider", "Progressbar": "QProgressBar"},
    **{"Separator": "QFrame", "Listbox": "QListWidget", "Treeview": "QTreeWidget"},
    **{"Scrollbar": "QScrollBar", "Canvas": "QGraphicsView"},
}
_AMP = frozenset({"Button", "Checkbutton", "Radiobutton", "LabelFrame"})  # & marks a mnemonic
_CONVERT: dict[str, Callable[[str], object]] = {"int": int, "float": float, "bool": "true".__eq__}


class _CloseWatch(QtCore.QObject):
    """Ends the session when the main window is closed (Tk parity, spec 4.1)."""

    def __init__(self, on_close: Callable[[], None]) -> None:
        super().__init__()
        self._on_close = on_close

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if event.type() == QtCore.QEvent.Type.Close:
            self._on_close()
        return False


class _Dialog(QtWidgets.QDialog):
    """A ``.ui`` dialog: Esc does not reject (hide) it and Enter clicks no default button,
    as in a Tk Toplevel (QA-16c-02 and QA-16c-06 rulings).

    A rejected QDialog hides without a Close event, so nothing would end the session; the
    title-bar X still closes it (``closeEvent`` calls ``reject``, which is not overridden).
    Widgets see both keys first (``returnPressed``, ``key:`` filters).
    """

    _SWALLOWED = (QtCore.Qt.Key.Key_Return, QtCore.Qt.Key.Key_Enter)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802
        if not (
            event.matches(QtGui.QKeySequence.StandardKey.Cancel) or event.key() in self._SWALLOWED
        ):
            super().keyPressEvent(event)


def _call(fn: Callable[[], object], *, checked: bool = False) -> Callable[..., None]:
    """Qt signal and trace arguments never reach user code (spec 4.3); ``checked``: only
    ``toggled(True)`` calls ``fn``."""

    def callback(*args: object) -> None:
        if not checked or args[0]:
            fn()

    return callback


class _Filter(QtCore.QObject):
    """D15: FocusIn, FocusOut and KeyPress handlers of one widget; never consumes the event."""

    def __init__(self, widget: Q) -> None:
        super().__init__(widget)  # parented: lives exactly as long as the widget
        self.calls: list[tuple[Q, Q, Callable[[], object]]] = []  # (event type, key or None, fn)

    def eventFilter(self, watched: Q, event: Q) -> bool:  # noqa: N802
        kind, pressed = event.type(), None
        if kind == QtCore.QEvent.Type.KeyPress:
            combo = event.keyCombination()
            modifiers = combo.keyboardModifiers() & ~Qt.KeyboardModifier.KeypadModifier
            pressed = QtGui.QKeySequence(QtCore.QKeyCombination(modifiers, combo.key()))
        for wanted, key, fn in list(self.calls):
            if wanted == kind and (key is None or key == pressed):
                fn()
        return False


def _align(names: Iterable[str]) -> Q:
    flags = Qt.AlignmentFlag(0)
    for name in names:
        flags |= getattr(Qt.AlignmentFlag, name)
    return flags


def _orient(value: str | None) -> Q:
    return Qt.Orientation.Vertical if value == "vertical" else Qt.Orientation.Horizontal


def _grow(widget: Q, horizontal: bool, vertical: bool) -> None:
    """A filled axis whose size policy is Fixed (a button's height) becomes Preferred."""
    policy = widget.sizePolicy()
    fixed, preferred = QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Preferred
    if horizontal and policy.horizontalPolicy() == fixed:
        policy.setHorizontalPolicy(preferred)
    if vertical and policy.verticalPolicy() == fixed:
        policy.setVerticalPolicy(preferred)
    widget.setSizePolicy(policy)


class QtSession:
    """Builds and then owns the Qt objects of one ``load_ui`` call."""

    def __init__(self, plan: BuildPlan, master: Q, *, app: Q, owns_app: bool) -> None:
        self._plan, self._master, self._app, self._owns = plan, master, app, owns_app
        self._created: list[Q] = []  # top-level windows (deleted in reverse)
        self._windows: dict[str, tuple[Q, Window]] = {}
        self._slots: list[_Slot] = []
        self._pixmaps: dict[tuple[str, str], Q] = {}
        self._logged: set[tuple[str, str]] = set()
        self._clipped: set[int] = set()
        self._closed = self._dead = False
        self._watch = _CloseWatch(self._main_closed)
        self._ignored = 0  # tb:bootstyle attributes (D5)
        self._wire: list[Callable[[], object]] = []  # connections made after the build
        self._groups: dict[int, Q] = {}  # id(variable) -> its exclusive QButtonGroup (D13)
        _LIVE.add(self)

    # ------------------------------------------------------------ build
    def build(self) -> QtSession:
        """Build every window; on any exception delete what was created, then re-raise."""
        try:
            self._build()
        except BaseException:
            self.destroy()
            raise
        return self

    def _build(self) -> None:
        plan = self._plan
        tk = sys.modules.get("tkinter")  # never imported here: only an existing root matters
        root = getattr(tk, "_default_root", None)
        if root is not None and _alive_tk(root):
            plan.log(_M_MIXED)
        for key, path in plan.images.items():
            pixmap = QtGui.QPixmap(str(path))
            if pixmap.isNull():
                plan.log(_M_IMAGE, image=key[1])
            self._pixmaps[key] = None if pixmap.isNull() else pixmap
        self._make_vars(plan.top)
        main: Q = None
        for window in sorted(plan.top.windows, key=lambda w: w.kind != "main"):
            top = self._window(plan.top, window, self._master if main is None else main)
            main = top if window.kind == "main" else main
        self.apply_texts(plan.text, plan.runtime_text)
        for connect in self._wire:  # building fired nothing; from now on handlers run
            connect()
        self._wire.clear()
        if self._ignored:
            plan.log(_M_IGNORED_STYLES, count=self._ignored, toolkit="pyside6")
        if main is not None:
            main.installEventFilter(self._watch)
            main.show()

    def _make_vars(self, inst: Instance) -> None:
        for var in inst.doc.document.variables.values():
            obj = _VARS[var.type](_PARSE[var.type](var.default or ""), var.id)
            inst.vars[var.id] = obj
            inst.scope._attach_var(var.id, obj)

    @staticmethod
    def _owner(inst: Instance) -> Instance:
        while inst.host is not None:
            inst = inst.host
        return inst

    def _once(self, message: str, key: str, **params: object) -> None:
        """A degradation warning, at most once per (message, class) per build (D6)."""
        if (message, key) not in self._logged:
            self._logged.add((message, key))
            self._plan.log(message, **params)

    def _slot(
        self, inst: Instance, label: str, prop: Prop | None, setter: Setter, split: bool
    ) -> None:
        if prop is not None:
            self._slots.append(_Slot(TextSlot(inst.doc.key, prop), setter, split, label))

    def _pixmap(self, inst: Instance, ref: str | None) -> Q:
        return None if ref is None else self._pixmaps.get((inst.doc.key, ref))

    def _image(self, inst: Instance, node: Widget | Action) -> Q:
        image = node.props.get("image")
        return self._pixmap(inst, None if image is None else image.ref)

    # ------------------------------------------------------------ windows
    def _window(self, inst: Instance, window: Window, parent: Q) -> Q:
        top: Q = (QtWidgets.QMainWindow if window.kind == "main" else _Dialog)(parent)
        if parent is not None:  # a child QMainWindow would otherwise embed itself in its parent
            top.setWindowFlag(Qt.WindowType.Window, True)
        self._created.append(top)
        self._windows[window.id] = (top, window)
        inst.scope._attach(window.id, top, window=True)
        title = window.props.get("title")
        self._slot(inst, window.id, title, lambda t, _u: top.setWindowTitle(escape_title(t)), False)
        if window.min_width or window.min_height:
            top.setMinimumSize(window.min_width or 0, window.min_height or 0)
        body = QtWidgets.QWidget(top)
        bar = status = None
        if window.menubar is not None:
            bar = QtWidgets.QMenuBar(top)
            seen: set[object] = set()
            for menu in window.menubar.children:
                self._menu(inst, top, bar, menu, seen)
        if window.statusbar is not None:
            status = QtWidgets.QStatusBar(top)
            label = self._label(status)
            status.addPermanentWidget(label, 1)
            node = window.statusbar
            self._slot(inst, node.id, node.props.get("text"), self._plain(label), False)
            inst.scope._attach(node.id, label)
        if window.kind == "main":
            top.setCentralWidget(body)
            if bar is not None:
                top.setMenuBar(bar)
            if status is not None:
                top.setStatusBar(status)
        else:
            outer = QtWidgets.QVBoxLayout(top)
            outer.setContentsMargins(0, 0, 0, 0)
            outer.setSpacing(0)
            if bar is not None:
                outer.setMenuBar(bar)
            outer.addWidget(body, 1)
            if status is not None:
                outer.addWidget(status)
        self._container(inst, body, window.layout, "Frame", window.children)
        return top

    # ------------------------------------------------------------ menus
    def _menu(self, inst: Instance, top: Q, parent: Q, node: Menu, seen: set[object]) -> None:
        sub = QtWidgets.QMenu(parent)
        parent.addMenu(sub)
        self._slot(inst, node.id, node.props.get("text"), self._amp(sub.setTitle), True)
        inst.scope._attach(node.id, sub)
        for child in node.children:
            if isinstance(child, MenuSeparator):
                sub.addSeparator()
            elif isinstance(child, Menu):
                self._menu(inst, top, sub, child, seen)
            else:
                self._action(inst, top, sub, child, seen)

    def _action(self, inst: Instance, top: Q, menu: Q, node: Action, seen: set[object]) -> None:
        action = QtGui.QAction(menu)
        pixmap = self._image(inst, node)
        if pixmap is not None:
            action.setIcon(QtGui.QIcon(pixmap))
        if "state" in node.props:
            action.setEnabled(node.props["state"].value != "disabled")
        menu.addAction(action)
        inst.scope._attach(node.id, action)
        self._slot(inst, node.id, node.props.get("text"), self._amp(action.setText), True)
        handler = self._plan.handlers.get(node.handler or "")
        if handler is not None:
            self._wire.append(lambda: action.triggered.connect(_call(handler)))
        chord = parse_chord(node.shortcut) if node.shortcut else None
        if chord is None:
            return
        if chord.identity in seen:  # only the first one is set, as in Tk
            self._plan.log(_M_SHORTCUT, shortcut=format_chord(chord), id=node.id)
            return
        seen.add(chord.identity)
        action.setShortcut(QtGui.QKeySequence(qt_shortcut(format_chord(chord))))
        # Also on the window itself, so the default WindowShortcut context matches without
        # walking a menu chain (a dialog's menu bar sits in a layout, spec 4.3).
        top.addAction(action)

    # ------------------------------------------------------------ layouts
    def _container(
        self,
        inst: Instance,
        parent: Q,
        layout: Layout | None,
        class_name: str,
        children: Iterable[Widget | Include],
    ) -> None:
        if class_name in ("Notebook", "PanedWindow"):
            for child in children:
                outer = self._child(inst, child, parent)
                if isinstance(child.placement, PagePlacement):
                    self._page(inst, parent, class_name, outer, child.placement, child.id)
        elif layout is not None and layout.type == "grid":
            self._grid(inst, parent, layout, children)
        elif layout is not None:
            self._pack(inst, parent, layout, children)

    def _grid(
        self, inst: Instance, parent: Q, layout: Layout, children: Iterable[Widget | Include]
    ) -> None:
        grid = QtWidgets.QGridLayout(parent)
        pad = layout.padding
        grid.setContentsMargins(pad, pad, pad, pad)
        grid.setHorizontalSpacing(layout.gap)
        grid.setVerticalSpacing(layout.gap)
        for entry in layout.columns:
            grid.setColumnStretch(entry.index, entry.weight)
            grid.setColumnMinimumWidth(entry.index, entry.minsize)
        for entry in layout.rows:
            grid.setRowStretch(entry.index, entry.weight)
            grid.setRowMinimumHeight(entry.index, entry.minsize)
        last_column = max((e.index + 1 for e in layout.columns), default=0)
        last_row = max((e.index + 1 for e in layout.rows), default=0)
        for child in children:
            place = child.placement
            if not isinstance(place, GridCell):
                continue
            outer = self._child(inst, child, parent)
            sticky = place.sticky
            _grow(outer, "w" in sticky and "e" in sticky, "n" in sticky and "s" in sticky)
            self._no_padding(child.id, place.padx, place.pady)
            span = (place.row, place.column, place.rowspan, place.columnspan)
            grid.addWidget(outer, *span, _align(alignment(sticky)))
            last_column = max(last_column, place.column + place.columnspan)
            last_row = max(last_row, place.row + place.rowspan)
        # Tk leaves extra space unused unless a line has a weight: an empty stretch line takes it.
        if not any(e.weight > 0 for e in layout.columns):
            grid.setColumnStretch(last_column, 1)
        if not any(e.weight > 0 for e in layout.rows):
            grid.setRowStretch(last_row, 1)

    def _pack(
        self, inst: Instance, parent: Q, layout: Layout, children: Iterable[Widget | Include]
    ) -> None:
        horizontal = layout.orient == "horizontal"
        box = QtWidgets.QHBoxLayout(parent) if horizontal else QtWidgets.QVBoxLayout(parent)
        pad = layout.padding
        box.setContentsMargins(pad, pad, pad, pad)
        box.setSpacing(layout.gap)
        expands = False
        for child in children:
            place = child.placement
            if not isinstance(place, PackPlacement):
                continue
            outer = self._child(inst, child, parent)
            stretch, names = pack_item(layout.orient, place.fill, place.expand)
            _grow(outer, place.fill in ("x", "both"), place.fill in ("y", "both"))
            self._no_padding(child.id, place.padx, place.pady)
            box.addWidget(outer, stretch, _align(names))
            expands = expands or place.expand
        if not expands:
            box.addStretch(1)

    def _no_padding(self, node_id: str, padx: int, pady: int) -> None:
        if padx or pady:  # trim T3 (D9 b): Qt layouts have no per-item padding
            self._once(_M_PADDING, "", id=node_id)

    def _page(
        self, inst: Instance, book: Q, class_name: str, child: Q, place: PagePlacement, label: str
    ) -> None:
        if class_name == "PanedWindow":
            book.addWidget(child)
            book.setStretchFactor(book.indexOf(child), place.weight)
            return
        pixmap = self._pixmap(inst, place.image)
        book.addTab(child, QtGui.QIcon() if pixmap is None else QtGui.QIcon(pixmap), "")
        setter = self._amp(lambda t: book.setTabText(book.indexOf(child), t))
        self._slot(inst, label, place.text, setter, True)

    def _child(self, inst: Instance, child: Widget | Include, parent: Q) -> Q:
        if isinstance(child, Include):
            return self._include(inst, child, parent)
        return self._widget(inst, child, parent)

    def _include(self, inst: Instance, node: Include, parent: Q) -> Q:
        child = inst.include(node)
        component = child.windows[0]
        if child.host is None:
            self._make_vars(child)
        else:  # shared with the host, as in Tk
            for name, var in self._owner(child).vars.items():
                child.scope._attach_var(name, var)
        frame = QtWidgets.QWidget(parent)
        child.scope._attach(component.id, frame)
        self._container(child, frame, component.layout, "Frame", component.children)
        inst.scope._attach(node.id, child.scope)
        return frame

    # ------------------------------------------------------------ widgets (spec 4.3)
    def _widget(self, inst: Instance, node: Widget, parent: Q) -> Q:
        plan = self._plan
        resolved = plan.registry.resolve(node.class_name, "pyside6", node.fallback)
        spec = resolved.spec
        made = self._extension(inst, node, parent, spec) if spec.is_extension else None
        if spec.is_extension:  # built by the factory or not, it behaves as its fallback
            spec = plan.registry.require(spec.fallback or "")
        name = spec.name
        if resolved.is_fallback:
            self._once(_M_FALLBACK, node.class_name, name=node.class_name, fallback=name)
        self._ignored += _BOOTSTYLE in node.extra_attrs
        # Only the properties the built class defines are read (as in Tk).
        defined = {definition.name: definition for definition in spec.properties}

        def value(prop: str) -> str | None:
            definition = defined.get(prop)
            if definition is None:
                return None
            given = node.props.get(prop)
            return definition.default if given is None else given.value

        make: Callable[[Instance, Widget, Q, Value], Made] = getattr(self, f"_make_{name.lower()}")
        outer, inner = made or make(inst, node, parent, value)
        state = value("state")
        if state == "disabled" and name == "Text":
            inner.setReadOnly(True)
        elif state == "disabled":
            inner.setEnabled(False)
        elif state == "readonly" and name in ("Entry", "Spinbox"):
            inner.setReadOnly(True)
        self._sizes(name, node, outer, inner, value)
        var = self._owner(inst).vars.get(node.bind) if node.bind else None
        if var is not None:
            self._bind(name, node, inner, var, value)
        self._events(name, node, inner, var)
        inst.scope._attach(node.id, inner)
        if spec.container:
            self._container(inst, inner, node.layout, name, node.children)
        return outer

    def _extension(self, inst: Instance, node: Widget, parent: Q, spec: WidgetSpec) -> Made | None:
        """The plugin factory path (spec plugins 4.1-4.2); None: build the fallback instead."""
        registry = self._plan.registry
        fallback = registry.require(spec.fallback or "").name
        factory = registry.load_factory(spec, "pyside6")
        props: dict[str, Any] = {}
        text: str | None = None
        for definition in spec.properties:
            prop = node.props.get(definition.name)
            raw = _raw(definition, prop)
            if raw is not None and definition.translatable and prop is not None:
                raw = self._plan.text(TextSlot(inst.doc.key, prop))
                text = raw if definition.name == "text" else text
            if raw is not None and definition.type == "image":
                props[definition.name] = self._pixmap(inst, raw)
            elif raw is not None:
                props[definition.name] = _CONVERT.get(definition.type, str)(raw)
        before = [c for c in parent.children() if c.isWidgetType()]
        outer: Q = None
        stage: FactoryStage = "create"
        try:
            if factory is None:  # the import failed (reported by the registry)
                raise LookupError(spec.name)  # never reported twice: report_failure dedupes
            made = factory(parent, props)
            stage = "check"
            outer, inner = made if isinstance(made, tuple) and len(made) == 2 else (made, made)
            new = [c for c in parent.children() if c.isWidgetType() and c not in before]
            if not (
                isinstance(outer, QtWidgets.QWidget)
                and isinstance(inner, getattr(QtWidgets, _QT_CLASS[fallback]))
                and outer.parent() == parent
                and new == [outer]
            ):
                raise TypeError(f"the factory of {spec.name} returned {made!r}")
            if text is not None:
                method = inner.setTitle if fallback == "LabelFrame" else inner.setText
                setter = self._amp(method) if fallback in _AMP else self._plain(inner)
                setter(text, -1)  # inside the guard; the slot sets it again
                self._slot(inst, node.id, node.props.get("text"), setter, fallback in _AMP)
        except (Exception, SystemExit) as exc:  # isolation point (D7): fall back, never crash
            if factory is not None:  # before the sweep, which may meet a deleted parent
                registry.report_failure(spec.name, "pyside6", stage, exc)
            kids = parent.children() if shiboken6.isValid(parent) else []
            strays = [c for c in kids if c.isWidgetType() and c not in before]
            for widget in {
                id(w): w
                for w in (outer, *strays)
                if isinstance(w, QtCore.QObject) and shiboken6.isValid(w)
            }.values():
                widget.setParent(None)
                widget.deleteLater()
            self._once(_M_PLUGIN_FAILED, node.class_name, name=node.class_name, fallback=fallback)
            return None
        return outer, inner

    @staticmethod
    def _sizes(name: str, node: Widget, outer: Q, inner: Q, value: Value) -> None:
        """Requested sizes in Tk units (D10) as minimum sizes (trim T4, D10 b)."""
        metrics = inner.fontMetrics()
        scale = {"chars": metrics.horizontalAdvance("0"), "lines": metrics.lineSpacing(), "px": 1}
        for (class_name, prop), unit in UNITS.items():
            raw = value(prop) if class_name == name else None
            if raw is None or (name in ("Frame", "LabelFrame") and node.children):
                continue  # a container with children sizes to them (Tk propagation)
            size = int(raw) * scale[unit]
            vertical = prop == "height" or (prop == "length" and value("orient") == "vertical")
            (outer.setMinimumHeight if vertical else outer.setMinimumWidth)(size)

    def _make_frame(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        frame = QtWidgets.QFrame(parent)
        return frame, frame

    def _make_labelframe(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        box = QtWidgets.QGroupBox(parent)
        self._slot(inst, node.id, node.props.get("text"), self._amp(box.setTitle), False)
        return box, box

    def _make_notebook(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        book = QtWidgets.QTabWidget(parent)
        return book, book

    def _make_panedwindow(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        splitter = QtWidgets.QSplitter(_orient(value("orient")), parent)
        return splitter, splitter

    def _make_scrolledframe(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        area = QtWidgets.QScrollArea(parent)
        area.setWidgetResizable(True)
        bars = Qt.ScrollBarPolicy
        area.setHorizontalScrollBarPolicy(bars.ScrollBarAlwaysOff)  # Tk's scrolls vertically only
        auto = value("autohide") == "true"
        area.setVerticalScrollBarPolicy(bars.ScrollBarAsNeeded if auto else bars.ScrollBarAlwaysOn)
        inner = QtWidgets.QWidget()
        area.setWidget(inner)
        return area, inner

    def _make_label(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        label = self._label(parent)
        pixmap = self._image(inst, node)
        text = node.props.get("text")
        if pixmap is not None:
            label.setPixmap(pixmap)
            if text is not None:  # trim T5 (D14 b)
                self._once(_M_LABEL_IMAGE, "Label", id=node.id)
        elif node.bind is None:  # a bound label shows its variable, as in Tk
            self._slot(inst, node.id, text, self._plain(label), False)
        return label, label

    def _make_button(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        button = QtWidgets.QPushButton(parent)
        button.setAutoDefault(False)  # Enter on a focused button does nothing, as in Tk
        pixmap = self._image(inst, node)
        if pixmap is not None:
            button.setIcon(QtGui.QIcon(pixmap))
            button.setIconSize(pixmap.size())
        self._slot(inst, node.id, node.props.get("text"), self._amp(button.setText), True)
        return button, button

    def _make_entry(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        entry = QtWidgets.QLineEdit(parent)
        entry.setMaxLength(_MAX_LENGTH)
        if value("show"):  # the mask character is the platform's
            entry.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        return entry, entry

    def _make_text(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        text = QtWidgets.QPlainTextEdit(parent)
        wrap = value("wrap")
        if wrap == "none":
            text.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        elif wrap == "char":
            text.setWordWrapMode(QtGui.QTextOption.WrapMode.WrapAnywhere)
        return text, text

    def _make_checkbutton(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        check = QtWidgets.QCheckBox(parent)
        self._slot(inst, node.id, node.props.get("text"), self._amp(check.setText), True)
        return check, check

    def _make_radiobutton(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        radio = QtWidgets.QRadioButton(parent)  # unbound: Qt's per-parent exclusivity (D13)
        self._slot(inst, node.id, node.props.get("text"), self._amp(radio.setText), True)
        return radio, radio

    def _make_combobox(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        combo = QtWidgets.QComboBox(parent)
        combo.setEditable(value("state") != "readonly")
        if (line := combo.lineEdit()) is not None:  # editable
            line.setMaxLength(_MAX_LENGTH)
        return combo, combo

    def _make_spinbox(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        spin = QtWidgets.QDoubleSpinBox(parent)
        low, high, step = (float(value(p) or 0) for p in ("minimum", "maximum", "increment"))
        if low > high:  # B13: sorted, logged
            self._once(_M_RANGE, node.id, id=node.id)
            low, high = high, low
        spin.setDecimals(decimals(low, high, step))
        spin.setRange(low, high)
        spin.setSingleStep(step)
        return spin, spin

    def _make_scale(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        orient = _orient(value("orient"))
        slider = QtWidgets.QSlider(orient, parent)
        minimum = float(value("minimum") or 0)
        scaled = scaled_range(minimum, float(value("maximum") or 0))
        slider.setRange(scaled.low, scaled.high)
        # Tk draws ``minimum`` at the top of a vertical scale; Qt draws its low end at the bottom.
        slider.setInvertedAppearance(scaled.inverted != (orient == Qt.Orientation.Vertical))
        slider.setValue(scaled.index(minimum))
        return slider, slider

    def _make_progressbar(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        bar = QtWidgets.QProgressBar(parent)
        bar.setTextVisible(False)
        bar.setOrientation(_orient(value("orient")))
        if value("mode") == "indeterminate":
            bar.setRange(0, 0)
        else:
            scaled = scaled_range(0.0, float(value("maximum") or 0))
            bar.setRange(scaled.low, scaled.high)
            bar.setInvertedAppearance(scaled.inverted)
            bar.setValue(scaled.index(float(value("value") or 0)))
        return bar, bar

    def _make_separator(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        line = QtWidgets.QFrame(parent)
        shape = QtWidgets.QFrame.Shape
        line.setFrameShape(shape.VLine if value("orient") == "vertical" else shape.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
        return line, line

    def _make_listbox(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        items = QtWidgets.QListWidget(parent)
        self._select(items, "Listbox", value)
        return items, items

    def _make_treeview(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        tree = QtWidgets.QTreeWidget(parent)
        show = value("show")
        tree.setHeaderHidden(show == "tree")
        tree.setRootIsDecorated(show != "headings")
        self._select(tree, "Treeview", value)
        return tree, tree

    @staticmethod
    def _select(view: Q, class_name: str, value: Value) -> None:
        mode = SELECTMODE[(class_name, value("selectmode") or "")]
        view.setSelectionMode(getattr(QtWidgets.QAbstractItemView.SelectionMode, mode))

    def _make_scrollbar(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        bar = QtWidgets.QScrollBar(_orient(value("orient")), parent)
        return bar, bar

    def _make_canvas(self, inst: Instance, node: Widget, parent: Q, value: Value) -> Made:
        view = QtWidgets.QGraphicsView(parent)
        view.setScene(QtWidgets.QGraphicsScene(view))
        colour = value("background")
        if colour and QtGui.QColor.isValidColorName(colour):
            view.setBackgroundBrush(QtGui.QColor(colour))
        elif colour:  # B7: a Tk colour name Qt does not know
            self._once(_M_COLOUR, colour, name=colour, id=node.id)
        return view, view

    # ------------------------------------------------------------ variables and events
    def _bind(self, name: str, node: Widget, w: Q, var: Q, value: Value) -> None:
        """Two-way sync of ``w`` and ``var`` (spec 4.4); a per-binding guard stops the echo."""
        signal: Q = None
        read: Callable[[], object] = lambda: w.text()  # noqa: E731
        write: Callable[[Any], object] = lambda v: w.setText(str(v))  # noqa: E731
        if name == "Entry":
            signal = w.textChanged
        elif name == "Combobox":
            signal, read = w.currentTextChanged, w.currentText
            write = lambda v: w.setCurrentText(str(v))  # noqa: E731
        elif name == "Checkbutton":
            signal, read, write = w.toggled, w.isChecked, lambda v: w.setChecked(bool(v))
        elif name == "Spinbox":
            signal, write = w.valueChanged, lambda v: self._spin(node, w, v)
            text = isinstance(var, _vars.StringVar)
            read = lambda: f"{w.value():.{w.decimals()}f}" if text else w.value()  # noqa: E731
        elif name in ("Scale", "Progressbar"):
            low = float(value("minimum") or 0) if name == "Scale" else 0.0
            scaled = scaled_range(low, float(value("maximum") or 0))
            signal = w.valueChanged if name == "Scale" else None
            read = lambda: scaled.value(w.value())  # noqa: E731
            write = lambda v: w.setValue(scaled.index(float(v)))  # noqa: E731
        elif name == "Radiobutton":
            signal, read, write = self._radio(w, var, value("value") or "")
        busy = [False]
        w.setProperty("pyguibud_bind", node.bind)  # read by the portable view (_describe_qt)

        def guarded(step: Callable[[], object]) -> None:
            if busy[0] or not shiboken6.isValid(w):  # a destroyed widget: silent, as Tk
                return
            busy[0] = True
            try:
                step()
            except (ValueError, TypeError, OverflowError):
                pass  # B12: the variable keeps its last value and nothing fires
            finally:
                busy[0] = False

        guarded(lambda: write(var.get()))
        var.trace_add("write", lambda *_: guarded(lambda: write(var.get())))
        if signal is not None:
            signal.connect(lambda *_: guarded(lambda: var.set(read())))

    def _radio(self, w: Q, var: Q, raw: str) -> tuple[Q, Callable[[], object], Callable[..., None]]:
        """D13: one exclusive group per variable object (across parents)."""
        mine: object = (
            int(raw) if isinstance(var, _vars.IntVar) and raw.lstrip("-").isdigit() else raw
        )
        group = self._groups.get(id(var))
        if group is None:
            group = self._groups[id(var)] = QtWidgets.QButtonGroup(self._app)
        group.addButton(w)

        def read() -> object:
            if not w.isChecked():
                raise ValueError(raw)  # only the newly checked radio writes the variable
            return mine

        def write(current: object) -> None:
            if current == mine:
                w.setChecked(True)
            elif w.isChecked():  # an exclusive group never unchecks its last button
                group.setExclusive(False)
                w.setChecked(False)
                group.setExclusive(True)

        return w.toggled, read, write

    def _spin(self, node: Widget, spin: Q, v: object) -> None:
        try:
            spin.setValue(float(v))  # type: ignore[arg-type]
        except ValueError:
            if v != "":
                self._once(_M_SPIN_TEXT, node.id, id=node.id)

    def _events(self, name: str, node: Widget, w: Q, var: Q) -> None:
        """Wire every handler, connected after the build (spec 4.1 step 3, 4.3, D15)."""
        flt: _Filter | None = None
        types = QtCore.QEvent.Type
        for event in node.events:
            fn = self._plan.handlers.get(event.handler)
            if fn is None:
                continue
            call, pair = _call(fn), (name, event.name)
            if event.name == "change" and var is not None:
                self._wire.append(partial(var.trace_add, "write", call))
            elif pair == ("Radiobutton", "change"):
                self._wire.append(partial(w.toggled.connect, _call(fn, checked=True)))
            elif pair in SIGNALS:
                self._wire.append(partial(getattr(w, SIGNALS[pair]).connect, call))
            else:  # focus_in, focus_out, key:<sequence>
                if flt is None:
                    flt = _Filter(w)
                    self._wire.append(partial(w.installEventFilter, flt))
                if event.name.startswith("key:"):
                    for text in qt_key_sequences(event.name[4:], mac=sys.platform == "darwin"):
                        flt.calls.append((types.KeyPress, QtGui.QKeySequence(text), fn))
                else:
                    kind = types.FocusIn if event.name == "focus_in" else types.FocusOut
                    flt.calls.append((kind, None, fn))

    # ------------------------------------------------------------ texts
    @staticmethod
    def _label(parent: Q) -> Q:
        """A ``QLabel`` that never interprets rich text (B4)."""
        label = QtWidgets.QLabel(parent)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    @staticmethod
    def _plain(label: Q) -> Setter:
        return lambda t, _u: label.setText(t)

    @staticmethod
    def _amp(setter: Callable[[str], object]) -> Setter:
        """A setter for a widget that reads ``&`` as a mnemonic marker (spec 4.5)."""
        return lambda t, u: setter(qt_text(t, u, True))

    def apply_texts(
        self, text: Callable[[TextSlot], str], runtime_text: Callable[[str], str]
    ) -> None:
        """(Re)apply every text slot: all are computed (and clipped) before the first is set."""
        apply_slots(self._slots, text, self._plan.log, self._clipped)

    # ------------------------------------------------------------ session
    def _main_closed(self) -> None:
        self._closed = True
        QtCore.QTimer.singleShot(0, self.destroy)  # never delete inside the close event

    def alive(self) -> bool:
        """True until the main window is closed or any window (or ``master``) is deleted."""
        if self._closed or self._dead:
            return False
        tops = [top for top, _window in self._windows.values()]
        if self._master is not None:
            tops.append(self._master)
        return all(shiboken6.isValid(top) for top in tops)

    def show(self, window_id: str) -> str | None:
        """Show and raise a window; dialogs stay non-modal, as in Tk (spec 0)."""
        top = self._windows[window_id][0]
        top.show()
        top.raise_()
        top.activateWindow()
        return None

    def run(self) -> None:
        """Run the Qt event loop unless one already runs in this thread (whoever made the app)."""
        if not self._dead and QtCore.QThread.currentThread().loopLevel() == 0:
            self._app.exec()

    def destroy(self) -> None:
        """Hide and delete every window this session created (idempotent)."""
        if self._dead:
            return
        self._dead = self._closed = True
        for top in reversed(self._created):
            if shiboken6.isValid(top):
                top.removeEventFilter(self._watch)
                top.hide()
                top.deleteLater()
        self._created.clear()
        self._pixmaps.clear()
        for group in self._groups.values():
            group.deleteLater()
        self._groups.clear()
        self._app.processEvents()
        _LIVE.discard(self)
        if self._owns and not any(session.alive() for session in _LIVE):
            self._app.quit()  # Qt 6 quit() closes every window: only the last session quits


def _alive_tk(root: Q) -> bool:
    try:
        return bool(root.winfo_exists())
    except Exception:  # a destroyed Tcl interpreter raises TclError
        return False
