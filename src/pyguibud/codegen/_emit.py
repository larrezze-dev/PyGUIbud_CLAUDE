"""The Python writer (spec ``docs/specs/codegen.md`` 5-6): literal and identifier gates, build code.

Injection safety: every ``.ui`` string reaches the output only through :func:`lit` (``repr``);
ids reach it as code only through :func:`ident` and only in attribute position (``s.<id>``);
handler names only as literals. Every other piece of code is fixed text in this module. Tk
mapping decisions are taken here, from ``_tkmap`` and ``core.keys``, and emitted as literals.
"""

from __future__ import annotations

import base64
import keyword
import math
from collections.abc import Iterable

from pyguibud.backends._tkmap import (
    _BOOTSTYLE,
    _BOOTSTYLE_RE,
    _CLASSES,
    _M_BOOTSTYLE,
    _M_FALLBACK,
    _MNEMONIC,
    _OPTION,
    _PADDED,
    _RENAMED,
    _TK_BASED,
    _TRACE_VAR,
    _VAR_OPTION,
    event_wiring,
)
from pyguibud.codegen._errors import M_UNSAFE, CodegenError
from pyguibud.codegen._plan import DocInfo, Plan
from pyguibud.core.diagnostics import Finding, node_path
from pyguibud.core.keys import parse_chord, tk_key_sequences, tk_shortcut
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
    Window,
)
from pyguibud.core.registry import Registry
from pyguibud.core.validate import _ID_RE, RESERVED_IDS

__all__ = ["Emitter", "Literal_", "ident", "image_constant", "lit"]

Literal_ = str | int | bool | float | None | tuple["Literal_", ...]

_INDENT = "        "
_TB = {name: "ttkbootstrap." + _RENAMED.get(name, name) for name in _CLASSES}
_VAR_CLASS = {
    "string": "tkinter.StringVar",
    "int": "tkinter.IntVar",
    "double": "tkinter.DoubleVar",
    "bool": "tkinter.BooleanVar",
}
_CHUNK = 76


def lit(value: object) -> str:
    """``repr(value)`` for plain data only; anything else is a bug, so ``TypeError``."""
    if value is None or isinstance(value, (str, bool, int)):
        return repr(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError(f"not a finite float: {value!r}")
        return repr(value)
    if isinstance(value, tuple):
        for item in value:
            lit(item)
        return repr(value)
    raise TypeError(f"not a literal: {type(value).__name__}")


def _safe(name: object) -> str:
    """``name`` if it is an id-grammar, non-keyword name (explicit checks: ``-O`` keeps them)."""
    if not isinstance(name, str) or not _ID_RE.fullmatch(name) or keyword.iskeyword(name):
        raise CodegenError("codegen.unsafe_name", M_UNSAFE, name=str(name))
    return name


def ident(name: object) -> str:
    """An id usable as an attribute name: id grammar, not a keyword, not reserved."""
    checked = _safe(name)
    if checked in RESERVED_IDS:
        raise CodegenError("codegen.unsafe_name", M_UNSAFE, name=checked)
    return checked


def handler(name: object) -> str:
    """A handler name as a string literal (never as a bare name)."""
    return lit(_safe(name))


def _dict(items: Iterable[tuple[str, str]]) -> str:
    """A dict display from ``(key, code)`` pairs; keys always go through :func:`lit`."""
    return "{" + ", ".join(f"{lit(key)}: {code}" for key, code in items) + "}"


def image_constant(number: int, data: bytes) -> list[str]:
    """``_IMG_<n> = (...)``: base64 text in 76-character chunks."""
    text = base64.b64encode(data).decode("ascii")
    chunks = [text[i : i + _CHUNK] for i in range(0, len(text), _CHUNK)] or [""]
    return [f"_IMG_{number} = (", *(f"    {lit(chunk)}" for chunk in chunks), ")"]


def _var_value(kind: str, default: str) -> object:
    if kind == "int":
        return int(default or 0)
    if kind == "double":
        return float(default or 0)
    if kind == "bool":
        return default == "true"
    return default


class Emitter:
    """Writes ``_build`` and the ``_component_<n>`` methods of one generated class."""

    def __init__(self, plan: Plan, registry: Registry) -> None:
        self.plan = plan
        self.registry = registry
        self.handlers: set[str] = set()
        self.methods: dict[int, list[str]] = {}
        self._logged: set[str] = set()
        self._out: list[str] = []
        self._seen: set[object] = set()  # chord identities bound in the current window

    # ------------------------------------------------------------ output
    def _line(self, text: str) -> None:
        self._out.append(_INDENT + text)

    def build(self, windows: Iterable[Window]) -> list[str]:
        """The body of ``_build`` (images first, after the variables)."""
        doc = self.plan.top
        self._out = ["    def _build(self) -> None:", _INDENT + "s = self"]
        self._vars(doc, "s")
        images_at = len(self._out)
        for window in windows:
            self._window(doc, window)
        body = self._out
        images = [
            _INDENT + f"self._img.append(_image(self._root, _IMG_{image.number}, {lit(image.fmt)}))"
            for image in self.plan.images
        ]
        return body[:images_at] + images + body[images_at:]

    def _vars(self, doc: DocInfo, scope: str) -> None:
        for var in doc.document.variables.values():
            value = lit(_var_value(var.type, var.default))
            self._line(
                f"{scope}.vars.{ident(var.id)} = {_VAR_CLASS[var.type]}"
                f"(master=self._root, value={value})"
            )

    def _slot(
        self,
        doc: DocInfo,
        prop: Prop | None,
        mnemonic: bool,
        label: str,
        kind: str,
        target: str,
        extra: str = "None",
    ) -> None:
        if prop is None:
            return
        index = lit(doc.index) if prop.translatable else "None"
        self._line(
            f"self._slot({index}, {lit(prop.context)}, {lit(prop.value)}, {lit(mnemonic)}, "
            f"{lit(label)}, {lit(kind)}, {target}, {extra})"
        )

    # ------------------------------------------------------------ windows and menus
    def _window(self, doc: DocInfo, window: Window) -> None:
        layout = window.layout
        self._line(
            f"top, body = self._window(s, {lit(ident(window.id))}, {lit(window.kind)}, "
            f"{lit(window.min_width or 0)}, {lit(window.min_height or 0)}, "
            f"{lit(layout.padding if layout else 0)})"
        )
        self._slot(doc, window.props.get("title"), False, window.id, "title", "top")
        if window.menubar is not None:
            self._line("bar = self._menubar(top)")
            self._seen = set()
            for menu in window.menubar.children:
                self._menu(doc, "bar", menu)
        if window.statusbar is not None:
            bar_id = ident(window.statusbar.id)
            self._line("w = self._statusbar(top)")
            self._slot(doc, window.statusbar.props.get("text"), False, bar_id, "text", "w")
            self._line(f"_attach(s, {lit(bar_id)}, w)")
        self._container(doc, "body", layout, "Frame", window.children)

    def _menu(self, doc: DocInfo, parent: str, node: Menu) -> None:
        name = ident(node.id)
        self._line(f"menu, i = self._cascade({parent})")
        self._slot(doc, node.props.get("text"), True, name, "entry", parent, "i")
        self._line(f"_attach(s, {lit(name)}, menu)")
        for child in node.children:
            if isinstance(child, MenuSeparator):
                self._line(f"s.{name}.add_separator()")
            elif isinstance(child, Menu):
                self._menu(doc, f"s.{name}", child)
            else:
                self._action(doc, f"s.{name}", child)

    def _action(self, doc: DocInfo, menu: str, node: Action) -> None:
        name = ident(node.id)
        options: list[tuple[str, str]] = []
        image = node.props.get("image")
        if image is not None and image.ref:
            number = self.plan.image(doc, image.ref)
            options += [("image", f"self._img[{number}]"), ("compound", lit("left"))]
        if "state" in node.props:
            options.append(("state", lit(node.props["state"].value)))
        shortcut = tk_shortcut(node.shortcut) if node.shortcut else None
        if shortcut is not None:
            options.append(("accelerator", lit(shortcut.accelerator)))
        name_code = lit("")
        if node.handler:
            name_code = handler(node.handler)
            self.handlers.add(node.handler)
        self._line(f"i = self._action({menu}, {name_code}, {_dict(options)})")
        self._line(f"_attach(s, {lit(name)}, i)")
        self._slot(doc, node.props.get("text"), True, name, "entry", menu, "i")
        chord = parse_chord(node.shortcut) if node.shortcut else None
        if shortcut is None or chord is None or node.shortcut is None:
            return
        if chord.identity in self._seen:
            self._line(
                f"_warn('shortcut_duplicate', shortcut={lit(shortcut.accelerator)}, id={lit(name)})"
            )
            return
        self._seen.add(chord.identity)
        aqua = tk_shortcut(node.shortcut, aqua=True).sequences
        self._line(f"self._shortcut(top, {menu}, i, {lit(shortcut.sequences)}, {lit(aqua)})")

    # ------------------------------------------------------------ widget tree
    def _container(
        self,
        doc: DocInfo,
        parent: str,
        layout: Layout | None,
        class_name: str,
        children: Iterable[Widget | Include],
    ) -> None:
        if layout is not None and layout.type == "grid":
            for method, lines in (
                ("columnconfigure", layout.columns),
                ("rowconfigure", layout.rows),
            ):
                for entry in lines:
                    self._line(
                        f"{parent}.{method}({lit(entry.index)}, weight={lit(entry.weight)}, "
                        f"minsize={lit(entry.minsize)})"
                    )
        packed = 0
        for child in children:
            outer = (
                self._include(doc, child, parent)
                if isinstance(child, Include)
                else self._widget(doc, child, parent)
            )
            place = child.placement
            if isinstance(place, PagePlacement):
                self._page(doc, parent, class_name, outer, place, ident(child.id))
            elif isinstance(place, GridCell) and layout is not None:
                lead_x = layout.gap if place.column > 0 else 0
                lead_y = layout.gap if place.row > 0 else 0
                self._line(
                    f"{outer}.grid(row={lit(place.row)}, column={lit(place.column)}, "
                    f"rowspan={lit(place.rowspan)}, columnspan={lit(place.columnspan)}, "
                    f"sticky={lit(place.sticky)}, padx={lit((lead_x + place.padx, place.padx))}, "
                    f"pady={lit((lead_y + place.pady, place.pady))})"
                )
            elif isinstance(place, PackPlacement) and layout is not None:
                lead = layout.gap if packed else 0
                packed += 1
                across = layout.orient == "horizontal"
                padx = (lead + place.padx, place.padx) if across else place.padx
                pady = place.pady if across else (lead + place.pady, place.pady)
                self._line(
                    f"{outer}.pack(side={lit('left' if across else 'top')}, "
                    f"fill={lit(place.fill)}, expand={lit(place.expand)}, padx={lit(padx)}, "
                    f"pady={lit(pady)})"
                )
        if class_name == "Notebook":
            self._line(f"{parent}.enable_traversal()")

    def _page(
        self,
        doc: DocInfo,
        notebook: str,
        class_name: str,
        child: str,
        place: PagePlacement,
        label: str,
    ) -> None:
        if class_name != "Notebook":
            self._line(f"{notebook}.add({child}, weight={lit(place.weight)})")
            return
        options = [("text", lit(""))]
        if place.image:
            number = self.plan.image(doc, place.image)
            options += [("image", f"self._img[{number}]"), ("compound", lit("left"))]
        self._line(f"{notebook}.add({child}, **{_dict(options)})")
        self._slot(doc, place.text, True, label, "tab", notebook, child)

    def _include(self, doc: DocInfo, node: Include, parent: str) -> str:
        name = ident(node.id)
        target, component, shared = self.plan.include(doc, node)
        if shared:
            self._line("sub = _Scope(s)")
        else:
            self._line("sub = _Scope()")
            self._vars(target, "sub")
        number, new = self.plan.component(target, component)
        self._line(f"frame = self._component_{number}(sub, {parent})")
        self._line(f"_attach(s, {lit(name)}, sub)")
        if new:
            saved, saved_seen = self._out, self._seen
            self._out = [
                f"    def _component_{number}(self, s: _Scope, parent: Any) -> Any:",
            ]
            layout = component.layout
            self._line(
                f"body = ttkbootstrap.Frame(parent, padding={lit(layout.padding if layout else 0)})"
            )
            self._line(f"_attach(s, {lit(ident(component.id))}, body)")
            self._container(target, "body", layout, "Frame", component.children)
            self._line("return body")
            self.methods[number] = self._out
            self._out, self._seen = saved, saved_seen
        return "frame"

    def _resolve(self, node: Widget) -> tuple[str, list[tuple[str, object, str]], set[str]]:
        """The core class to build, its options ``(name, raw, type)`` and its property names.

        Any other property of the node (an unknown name, or one of an extension shown as its
        fallback) is kept in the model but ignored, exactly as the Tk builder does (parity).
        """
        resolved = self.registry.resolve(node.class_name, "ttkbootstrap", node.fallback)
        spec = resolved.spec
        is_fallback = resolved.is_fallback
        if spec.name not in _TB:  # an extension with its own factory: v0 renders its fallback
            spec, is_fallback = self.registry.require(spec.fallback or ""), True
        if is_fallback and node.class_name not in self._logged:
            self._logged.add(node.class_name)
            self._warn(
                node,
                "codegen.extension_fallback",
                _M_FALLBACK,
                name=node.class_name,
                fallback=spec.name,
            )
        props: list[tuple[str, object, str]] = []
        for definition in spec.properties:
            prop = node.props.get(definition.name)
            raw: str | None = definition.default if prop is None else prop.value
            if definition.type == "image":
                raw = prop.ref if prop is not None else None
            if (
                raw is None
                or definition.name in ("text", "state")
                or (spec.name, definition.name) == ("Radiobutton", "value")
            ):
                continue
            props.append((definition.name, raw, definition.type))
        return spec.name, props, {definition.name for definition in spec.properties}

    def _warn(self, node: Widget, code: str, msgid: str, **params: object) -> None:
        self.plan.warnings.append(
            Finding(
                code=code, msgid=msgid, params=params, source="", path=node_path(node), anchor=node
            )
        )

    def _widget(self, doc: DocInfo, node: Widget, parent: str) -> str:
        name_id = ident(node.id)
        name, props, defined = self._resolve(node)
        options: list[tuple[str, str]] = []
        for prop_name, raw, kind in props:
            text = str(raw)
            if kind == "int":
                code = lit(int(text))
            elif kind == "float":
                code = lit(float(text))
            elif kind == "bool":
                code = lit(text == "true")
            elif kind == "image":
                code = f"self._img[{self.plan.image(doc, text)}]"
            else:
                code = lit(text)
            options.append((_OPTION.get((name, prop_name), prop_name), code))
        var = False
        if node.bind:
            self._line(f"v = s.vars.{ident(node.bind)}")
            var = True
        elif name in _TRACE_VAR and any(e.name == "change" for e in node.events):
            kind_name = {"string": "StringVar", "bool": "BooleanVar", "double": "DoubleVar"}
            self._line(f"v = self._private(tkinter.{kind_name[_TRACE_VAR[name]]})")
            var = True
        if var and name in _VAR_OPTION:
            options.append((_VAR_OPTION[name], "v"))
        if name == "Radiobutton":
            value = node.props["value"].value if "value" in node.props else ""
            variable = doc.document.variables.get(node.bind) if node.bind else None
            is_int = variable is not None and variable.type == "int"
            options.append(("value", lit(int(value) if is_int else value)))
        if name in _PADDED and node.layout is not None:
            options.append(("padding", lit(node.layout.padding)))
        text_prop = node.props.get("text") if "text" in defined else None
        if any(key == "image" for key, _code in options) and text_prop is not None:
            options.append(("compound", lit("left")))
        style = node.extra_attrs.get(_BOOTSTYLE)
        if style is not None and (
            name in _TK_BASED or len(style) > 64 or not _BOOTSTYLE_RE.fullmatch(style)
        ):
            self._warn(node, "codegen.bootstyle_ignored", _M_BOOTSTYLE, value=style, id=node.id)
            style = None
        self._line(
            f"w = self._create({_TB[name]}, {parent}, {_dict(options)}, {lit(style)}, "
            f"{lit(name_id)})"
        )
        if "state" in defined and "state" in node.props:
            self._line(f"w.configure(state={lit(node.props['state'].value)})")
        if text_prop is not None and not (name == "Label" and node.bind):
            mnemonic = name in _MNEMONIC
            kind = "text_u" if mnemonic else "text"
            self._slot(doc, text_prop, mnemonic, name_id, kind, "w")
        self._events(node, name, var)
        self._line(f"_attach(s, {lit(name_id)}, w)")
        if self.registry.require(name).container:
            self._container(doc, f"s.{name_id}", node.layout, name, node.children)
        return f"s.{name_id}.container" if name == "ScrolledFrame" else f"s.{name_id}"

    def _events(self, node: Widget, name: str, var: bool) -> None:
        for event in node.events:
            fn = handler(event.handler)
            self.handlers.add(event.handler)
            kind, details = event_wiring(name, event.name)
            if kind == "command":
                self._line(f"self._command(w, {fn})")
            elif kind == "trace":
                if var:  # the validator allows ``change`` only where a variable exists
                    self._line(f"self._trace(v, {fn})")
            elif kind == "modified":
                self._line(f"self._modified(w, {fn})")
            elif kind == "virtual":
                self._line(f"self._virtual(w, {lit(details[0])}, {fn})")
            else:
                result = lit("break" if event.name == "activate" else None)
                if kind == "key":
                    plain = tk_key_sequences(details[0])
                    aqua = tk_key_sequences(details[0], aqua=True)
                else:
                    plain = aqua = details
                self._line(f"self._bind(w, {lit(plain)}, {lit(aqua)}, {fn}, {result})")
