"""Shared Tk builder: turns a :class:`BuildPlan` into Tk windows (reused by the Step 16 backend).

No toolkit import at module level (ADR-007): the backend passes the ``tkinter`` module and its
class table in. No string from a ``.ui`` file reaches Tk as a script, a variable name, a widget
path or an unvalidated bind sequence: only Python callables and option values are passed.
"""

from __future__ import annotations

import contextlib
import warnings
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import Any, TypeAlias

from pyguibud.backends._tkmap import (
    _BOOTSTYLE,
    _BOOTSTYLE_RE,
    _M_BOOTSTYLE,
    _M_FALLBACK,
    _MNEMONIC,
    _OPTION,
    _PADDED,
    _TK_BASED,
    _TRACE_VAR,
    _VAR_OPTION,
    clip_text,
    event_wiring,
    split_headings,
)
from pyguibud.backends.base import BuildPlan, Instance, TextSlot
from pyguibud.core.keys import parse_chord, split_mnemonic, tk_key_sequences, tk_shortcut
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
    PropertyDef,
    Widget,
    WidgetSpec,
    Window,
)
from pyguibud.core.registry import FactoryStage
from pyguibud.core.validate import MAX_TEXT_LENGTH
from pyguibud.i18n import N_, NP_

__all__ = ["Embed", "TkSession", "apply_slots", "event_wiring"]

#: A toolkit object; typed loosely because ``tkinter`` is never imported here.
Tk: TypeAlias = Any

# The pure tables live in ``_tkmap`` (shared with the code generator, ADR-008).
# Translators: a keyboard shortcut appears twice in one window.
_M_SHORTCUT = N_("The shortcut '{shortcut}' of '{id}' is already used in this window.")
# Translators: {count} is a number of widgets whose style was not applied; {package} is the
# package name ttkbootstrap and {attribute} the name of the .ui attribute (both inserted as they
# are); {toolkit} is the name of the toolkit.
_M_IGNORED_STYLES = NP_(
    "{count} {package} style ({attribute}) is ignored by the {toolkit} toolkit.",
    "{count} {package} styles ({attribute}) are ignored by the {toolkit} toolkit.",
)
# Translators: a text (usually a translation) is too long to display; {length} and {limit} are
# numbers of characters.
_M_CLIPPED = N_("The text of '{id}' has {length} characters; only the first {limit} are shown.")
# Translators: a plugin's widget could not be created (runtime.plugin_failed).
_M_PLUGIN_FAILED = N_(
    "The widget class '{name}' failed to build; its fallback '{fallback}' is shown."
)
# Translators: a plugin's widget raised an error when its text was set again (for example
# after a language change); {name} is its widget class.
_M_TEXT_FAILED = N_("The widget class '{name}' could not show the new text of '{id}'.")
# Translators: a widget does not accept the handler of an event (runtime.event_unsupported).
_M_EVENT_UNSUPPORTED = N_("The event '{event}' of '{id}' is not supported by '{name}'.")


def _raw(definition: PropertyDef, prop: Prop | None) -> str | None:
    """A property's value as written (or its default); an image's resource id."""
    if definition.type == "image":
        return prop.ref if prop is not None else None
    return definition.default if prop is None else prop.value


def _paths(widget: Tk) -> set[str]:
    """The path of every widget of the interpreter (each Tk widget is a ``.``-command)."""
    return set(widget.tk.splitlist(widget.tk.call("info", "commands", ".*")))


def _sweep(parent: Tk, before: set[str]) -> None:
    """Destroy every widget created since ``before`` (:func:`_paths`), wherever it is (H60).

    Only those: an existing widget a factory returns is never destroyed (H61), and neither
    are the parent and its ancestors. ``parent`` may itself be destroyed.
    """
    new: list[str] = []
    for path in sorted(_paths(parent) - before):  # an ancestor sorts before its descendants
        if not any(path.startswith(f"{top}.") for top in new):
            new.append(path)
    for path in new:
        try:
            parent.nametowidget(path).destroy()
        except Exception:  # not made by tkinter (no Python object), or already gone
            with contextlib.suppress(Exception):
                parent.tk.call("destroy", path)


def _call(fn: Callable[[], object], result: str | None = None) -> Callable[..., str | None]:
    """A Tk callback that calls the handler with no arguments (spec 4.1)."""

    def callback(*_args: object) -> str | None:
        fn()
        return result

    return callback


@dataclass(frozen=True, slots=True)
class Embed:
    """Designer canvas mode (ADR-010): each window is a frame in ``host``, never a toplevel."""

    host: Any
    on_node: Callable[[object, Any, Any], None]  # (model node, outer widget, inner widget)
    on_title: Callable[[Window, str], None]  # the title slot's setter
    placeholder: Callable[[Include, Any], Any]  # an unexpanded include -> a widget in parent
    #: (node, parent, reason) -> a card shown instead of a failed non-container plugin widget
    failed: Callable[[Widget, Any, str], Any] | None = None


@dataclass(frozen=True, slots=True)
class _Slot:
    key: TextSlot
    set: Callable[[str, int], object]  # (display text, underline index)
    mnemonic: bool
    label: str  # the id named in the log when the text is clipped
    #: A plugin widget's slot: a later set that raises is reported here, never raised (H49).
    failed: Callable[[BaseException], object] | None = None


def apply_slots(
    slots: Iterable[_Slot],
    text: Callable[[TextSlot], str],
    log: Callable[..., None],
    clipped: set[int],
) -> None:
    """Compute (split, clip) every slot's text first, then set them all: all-or-nothing.

    Shared with the Qt session. ``clipped`` holds the ``id()`` of the slots already logged.
    """
    slots = list(slots)
    shown: list[tuple[str, int]] = []
    for slot in slots:
        raw = text(slot.key)
        value, underline = split_mnemonic(raw) if slot.mnemonic else (raw, -1)
        cut = clip_text(value, underline)
        if cut is not None:
            if id(slot) not in clipped:
                clipped.add(id(slot))
                log(_M_CLIPPED, id=slot.label, length=len(value), limit=MAX_TEXT_LENGTH)
            value, underline = cut
        shown.append((value, underline))
    for slot, (value, underline) in zip(slots, shown, strict=True):
        if slot.failed is None:
            slot.set(value, underline)
            continue
        try:
            slot.set(value, underline)
        except (Exception, SystemExit) as exc:  # isolation point (D7): the others still apply
            slot.failed(exc)


class TkSession:
    """Builds and then owns the Tk objects of one ``load_ui`` call."""

    def __init__(
        self,
        plan: BuildPlan,
        master: Tk,
        *,
        tk: Tk,
        classes: Mapping[str, Any],
        make_root: Callable[[], Any],
        apply_theme: Callable[[Any, bool], None],
        backend: str,
        bootstyle: bool,
        embed: Embed | None = None,
    ) -> None:
        self._backend, self._embed = backend, embed
        self._plan, self._master, self._tk, self._classes = plan, master, tk, classes
        self._make_root, self._apply_theme, self._bootstyle = make_root, apply_theme, bootstyle
        self._root: Any = None
        self._created: list[Any] = []  # toplevels created here (destroyed in reverse)
        self._windows: dict[str, tuple[Any, Window]] = {}
        self._slots: list[_Slot] = []
        self._images: dict[tuple[str, str], Any] = {}
        self._keep: list[Any] = []  # private variables
        self._traces: list[tuple[Any, str]] = []  # (variable, trace name): removed on destroy
        self._logged: set[str] = set()
        self._clipped: set[int] = set()  # id() of the slots already logged as clipped
        self._armed = False
        self._after: str | None = None
        self._aqua = False
        self._ignored = 0  # tb:bootstyle attributes met with ``bootstyle=False`` (D5)

    # ------------------------------------------------------------ build
    def build(self) -> TkSession:
        """Build every window; on any exception destroy what was created, then re-raise."""
        try:
            self._build()
        except BaseException:
            self.destroy()
            raise
        return self

    def _build(self) -> None:
        plan = self._plan
        if self._master is None:
            self._root = self._make_root()
            self._created.append(self._root)
            self._root.withdraw()
        else:
            self._root = self._master.winfo_toplevel()
        self._aqua = self._root.tk.call("tk", "windowingsystem") == "aqua"
        if self._embed is None:  # designer themes are chrome-only (ADR-009 D4)
            self._apply_theme(self._root, self._master is None)
        self._make_vars(plan.top)
        for key, path in plan.images.items():
            self._images[key] = self._tk.PhotoImage(master=self._root, file=str(path))
        main: Any = None
        for window in plan.top.windows:
            top = self._window(plan.top, window, main)
            main = main if window.kind != "main" else top
        self.apply_texts(plan.text, plan.runtime_text)
        self._after = self._root.after_idle(self._arm)
        if self._ignored:
            plan.log(
                _M_IGNORED_STYLES,
                count=self._ignored,
                package="ttkbootstrap",
                attribute="tb:bootstyle",
                toolkit=self._backend,
            )
        if main is not None and self._embed is None:
            main.deiconify()

    def _arm(self) -> None:
        self._armed, self._after = True, None

    def _make_vars(self, inst: Instance) -> None:
        kinds = {
            "string": "StringVar",
            "int": "IntVar",
            "double": "DoubleVar",
            "bool": "BooleanVar",
        }
        parse: dict[str, Callable[[str], object]] = {
            "string": str,
            "int": lambda v: int(v or 0),
            "double": lambda v: float(v or 0),
            "bool": lambda v: v == "true",
        }
        for var in inst.doc.document.variables.values():
            value = parse[var.type](var.default)
            obj = getattr(self._tk, kinds[var.type])(master=self._root, value=value)
            inst.vars[var.id] = obj
            inst.scope._attach_var(var.id, obj)

    def _slot(
        self,
        doc: str,
        label: str,
        prop: Prop | None,
        setter: Callable[[str, int], object],
        mnemonic: bool,
    ) -> None:
        if prop is not None:
            self._slots.append(_Slot(TextSlot(doc, prop), setter, mnemonic, label))

    def _window(self, inst: Instance, window: Window, main: Tk) -> Tk:
        embed = self._embed
        if embed is not None:
            top = self._classes["Frame"](embed.host)
            self._created.append(top)
        elif window.kind == "main" and self._master is None:
            top = self._root
        else:
            top = self._classes["Toplevel"](master=self._root)
            self._created.append(top)
            top.withdraw()
        doc = inst.doc.key
        self._windows[window.id] = (top, window)
        inst.scope._attach(window.id, top, window=True)
        title = self._title(top, window)
        self._slot(doc, window.id, window.props.get("title"), title, False)
        if (window.min_width or window.min_height) and embed is None:
            top.minsize(window.min_width or 0, window.min_height or 0)
        if window.kind == "dialog" and embed is None:
            top.transient(main if main is not None else self._root)
            # Trim 1 (spec 0): the button bar and modality arrive in Step 14.
            top.protocol("WM_DELETE_WINDOW", top.withdraw)
        top.columnconfigure(0, weight=1)
        top.rowconfigure(0, weight=1)
        layout = window.layout
        body = self._classes["Frame"](top, padding=layout.padding if layout else 0)
        body.grid(row=0, column=0, sticky="nsew")
        if embed is not None:
            embed.on_node(window, top, body)
        if window.menubar is not None:
            bar = self._classes["Menu"](top, tearoff=False)
            if embed is None:  # embedded: built but not attached (the canvas draws a strip)
                top.configure(menu=bar)
            seen: set[object] = set()
            for menu in window.menubar.children:
                self._menu(inst, top, bar, menu, seen)
        if window.statusbar is not None:
            frame = self._classes["Frame"](top)
            frame.grid(row=2, column=0, sticky="ew")
            self._classes["Separator"](frame).pack(fill="x")
            label = self._classes["Label"](frame, padding=(6, 2), anchor="w")
            label.pack(fill="x")
            setter = self._set_text(label, underline=False)
            statusbar = window.statusbar
            self._slot(doc, statusbar.id, statusbar.props.get("text"), setter, False)
            inst.scope._attach(window.statusbar.id, label)
            if embed is not None:
                embed.on_node(statusbar, frame, label)
        self._container(inst, body, layout, "Frame", window.children)
        return top

    # ------------------------------------------------------------ menus
    def _menu(
        self,
        inst: Instance,
        top: Tk,
        parent: Tk,
        node: Menu,
        seen: set[object],
    ) -> None:
        sub = self._classes["Menu"](parent, tearoff=False)
        parent.add_cascade(label="", menu=sub)
        index = parent.index("end")
        self._slot(
            inst.doc.key,
            node.id,
            node.props.get("text"),
            lambda t, u: parent.entryconfigure(index, label=t, underline=u),
            True,
        )
        inst.scope._attach(node.id, sub)
        for child in node.children:
            if isinstance(child, MenuSeparator):
                sub.add_separator()
            elif isinstance(child, Menu):
                self._menu(inst, top, sub, child, seen)
            else:
                self._action(inst, top, sub, child, seen)

    def _action(self, inst: Instance, top: Tk, menu: Tk, node: Action, seen: set[object]) -> None:
        options: dict[str, Any] = {"label": ""}
        handler = self._plan.handlers.get(node.handler or "")
        if handler is not None:
            options["command"] = handler
        image = node.props.get("image")
        if image is not None and image.ref:
            options.update(image=self._image(inst, image.ref), compound="left")
        if "state" in node.props:
            options["state"] = node.props["state"].value
        shortcut = tk_shortcut(node.shortcut, aqua=self._aqua) if node.shortcut else None
        if shortcut is not None:
            options["accelerator"] = shortcut.accelerator
        menu.add_command(**options)
        index = menu.index("end")
        inst.scope._attach(node.id, index)
        self._slot(
            inst.doc.key,
            node.id,
            node.props.get("text"),
            lambda t, u: menu.entryconfigure(index, label=t, underline=u),
            True,
        )
        chord = parse_chord(node.shortcut) if node.shortcut else None
        if shortcut is None or chord is None or self._embed is not None:  # design runs no handler
            return
        if chord.identity in seen:
            self._plan.log(_M_SHORTCUT, shortcut=shortcut.accelerator, id=node.id)
            return
        seen.add(chord.identity)
        for sequence in shortcut.sequences:
            top.bind(sequence, lambda _e, m=menu, i=index: (m.invoke(i), "break")[1], add="+")

    # ------------------------------------------------------------ widget tree
    def _container(
        self,
        inst: Instance,
        parent: Tk,
        layout: Layout | None,
        class_name: str,
        children: Iterable[Widget | Include],
    ) -> None:
        if layout is not None and layout.type == "grid":
            for line, configure in (
                (layout.columns, parent.columnconfigure),
                (layout.rows, parent.rowconfigure),
            ):
                for entry in line:
                    configure(entry.index, weight=entry.weight, minsize=entry.minsize)
        packed = 0
        for child in children:
            outer = (
                self._include(inst, child, parent)
                if isinstance(child, Include)
                else self._widget(inst, child, parent)
            )
            place = child.placement
            if isinstance(place, PagePlacement):
                self._page(inst, parent, class_name, outer, place, child.id)
            elif isinstance(place, GridCell) and layout is not None:
                lead_x = layout.gap if place.column > 0 else 0
                lead_y = layout.gap if place.row > 0 else 0
                outer.grid(
                    row=place.row,
                    column=place.column,
                    rowspan=place.rowspan,
                    columnspan=place.columnspan,
                    sticky=place.sticky,
                    padx=(lead_x + place.padx, place.padx),
                    pady=(lead_y + place.pady, place.pady),
                )
            elif isinstance(place, PackPlacement) and layout is not None:
                lead = layout.gap if packed else 0
                packed += 1
                across = layout.orient == "horizontal"
                outer.pack(
                    side="left" if across else "top",
                    fill=place.fill,
                    expand=place.expand,
                    padx=(lead + place.padx, place.padx) if across else place.padx,
                    pady=place.pady if across else (lead + place.pady, place.pady),
                )
        if class_name == "Notebook" and self._embed is None:
            # ttk::notebook::enableTraversal binds on [winfo toplevel]: the designer root.
            parent.enable_traversal()

    def _page(
        self,
        inst: Instance,
        notebook: Tk,
        class_name: str,
        child: Tk,
        place: PagePlacement,
        label: str,
    ) -> None:
        if class_name != "Notebook":
            notebook.add(child, weight=place.weight)
            return
        options: dict[str, Any] = {"text": ""}
        image = self._image(inst, place.image) if place.image else None
        if image is not None:  # ttk's tab options do not skip None
            options.update(image=image, compound="left")
        notebook.add(child, **options)
        setter = lambda t, u: notebook.tab(child, text=t, underline=u)  # noqa: E731
        self._slot(inst.doc.key, label, place.text, setter, True)

    def _include(self, inst: Instance, node: Include, parent: Tk) -> Tk:
        if self._embed is not None and id(node) not in inst.includes:
            frame = self._embed.placeholder(node, parent)
            self._embed.on_node(node, frame, frame)
            return frame
        child = inst.include(node)
        component = child.windows[0]
        if child.host is None:
            self._make_vars(child)
        else:
            for name, var in self._owner(child).vars.items():
                child.scope._attach_var(name, var)
        layout = component.layout
        frame = self._classes["Frame"](parent, padding=layout.padding if layout else 0)
        child.scope._attach(component.id, frame)
        self._container(child, frame, layout, "Frame", component.children)
        inst.scope._attach(node.id, child.scope)
        if self._embed is not None:
            self._embed.on_node(node, frame, frame)
        return frame

    def _title(self, top: Tk, window: Window) -> Callable[[str, int], object]:
        embed = self._embed
        if embed is None:
            return lambda t, _u: top.title(t)
        return lambda t, _u: embed.on_title(window, t)

    def _image(self, inst: Instance, ref: str) -> Tk:
        """The image ``ref``; embedded (documents may be invalid): None, i.e. no option."""
        if self._embed is not None and (inst.doc.key, ref) not in self._images:
            return None
        return self._images[(inst.doc.key, ref)]

    @staticmethod
    def _owner(inst: Instance) -> Instance:
        while inst.host is not None:
            inst = inst.host
        return inst

    def _widget(self, inst: Instance, node: Widget, parent: Tk) -> Tk:
        plan = self._plan
        resolved = plan.registry.resolve(node.class_name, self._backend, node.fallback)
        spec = resolved.spec
        if spec.is_extension:
            made = self._extension(inst, node, parent, spec)
            if made is not None:
                return made
            spec = plan.registry.require(spec.fallback or "")  # exactly as registry.no_factory
        name = spec.name
        if resolved.is_fallback and node.class_name not in self._logged:
            self._logged.add(node.class_name)
            plan.log(_M_FALLBACK, name=node.class_name, fallback=name)
        options: dict[str, Any] = {}
        # Only the properties the built class defines are read: any other (an unknown name, or
        # one of an extension shown as its fallback) is kept in the model but ignored here.
        defined = {definition.name for definition in spec.properties}
        for definition in spec.properties:
            prop = node.props.get(definition.name)
            raw = _raw(definition, prop)
            if (
                raw is None
                or definition.name in ("text", "state")
                or (name, definition.name) == ("Radiobutton", "value")
            ):
                continue
            converted = self._convert(inst, definition.type, raw)
            options[_OPTION.get((name, definition.name), definition.name)] = converted
        var = self._variable(inst, node, name)
        if var is not None and name in _VAR_OPTION:
            options[_VAR_OPTION[name]] = var
        if name == "Radiobutton":
            value = node.props["value"].value if "value" in node.props else ""
            declared = self._owner(inst).doc.document.variables
            is_int = (
                node.bind is not None
                and (self._embed is None or node.bind in declared)
                and declared[node.bind].type == "int"
                and (self._embed is None or value.lstrip("-").isdigit())
            )
            options["value"] = int(value) if is_int else value
        if name in _PADDED and node.layout is not None:
            options["padding"] = node.layout.padding
        text = node.props.get("text") if "text" in defined else None
        if "image" in options and text is not None:
            options["compound"] = "left"
        widget = self._create(name, parent, options, node)
        if "state" in defined and "state" in node.props:
            widget.configure(state=node.props["state"].value)
        if text is not None and not (name == "Label" and node.bind):
            mnemonic = name in _MNEMONIC
            self._slot(inst.doc.key, node.id, text, self._set_text(widget, mnemonic), mnemonic)
        self._events(node, name, widget, var)
        inst.scope._attach(node.id, widget)
        if spec.container:
            self._container(inst, widget, node.layout, name, node.children)
        outer = widget.container if name == "ScrolledFrame" else widget
        if self._embed is not None:
            self._embed.on_node(node, outer, widget)
        return outer

    def _convert(self, inst: Instance, kind: str, raw: str) -> object:
        if kind == "image":
            return self._image(inst, raw)
        converters: dict[str, Callable[[str], object]] = {
            "int": int,
            "float": float,
            "bool": lambda v: v == "true",
        }
        return converters.get(kind, str)(raw)

    def _variable(self, inst: Instance, node: Widget, name: str) -> Tk:
        """The bound variable, or a private one when ``change`` needs a trace (else None)."""
        known = self._owner(inst).vars
        if node.bind and (self._embed is None or node.bind in known):
            return known[node.bind]
        if name in _TRACE_VAR and any(e.name == "change" for e in node.events):
            kind = {"string": "StringVar", "bool": "BooleanVar", "double": "DoubleVar"}[
                _TRACE_VAR[name]
            ]
            var = getattr(self._tk, kind)(master=self._root)
            self._keep.append(var)
            return var
        return None

    def _style(self, node: Widget, name: str) -> str | None:
        """The node's bootstyle if this backend applies it and it is usable (else logged)."""
        style = node.extra_attrs.get(_BOOTSTYLE) if self._bootstyle else None
        self._ignored += not self._bootstyle and _BOOTSTYLE in node.extra_attrs
        if style is not None and (
            name in _TK_BASED or len(style) > 64 or not _BOOTSTYLE_RE.fullmatch(style)
        ):
            self._plan.log(_M_BOOTSTYLE, value=style, id=node.id)
            return None
        return style

    def _extension(self, inst: Instance, node: Widget, parent: Tk, spec: WidgetSpec) -> Tk:
        """Build ``node`` with its plugin factory (spec plugins 4.2); None: use the fallback.

        Any exception from the factory, the checks or the first text and state settings destroys
        what the factory made, is reported to the registry and logged once per class.
        """
        registry, plan = self._plan.registry, self._plan
        fallback = registry.require(spec.fallback or "")
        factory = registry.load_factory(spec, self._backend)
        if factory is None:  # the import failed (reported by the registry)
            return self._failed(node, parent, fallback.name, "import", spec.container)
        props: dict[str, Any] = {}
        texts: dict[str, str] = {}  # the factory may consume ``props``
        for definition in spec.properties:
            prop = node.props.get(definition.name)
            raw = _raw(definition, prop)
            if raw is not None and definition.translatable and prop is not None:
                raw = texts[definition.name] = plan.text(TextSlot(inst.doc.key, prop))
            if raw is not None:
                props[definition.name] = self._convert(inst, definition.type, raw)
        var = self._variable(inst, node, fallback.name)
        style = self._style(node, fallback.name)
        before = {str(child) for child in parent.winfo_children()}
        existing = _paths(parent)
        outer: Any = None
        inner: Any = None
        stage: FactoryStage = "create"
        slots: list[_Slot] = []
        try:
            rejected = False
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                try:
                    made = factory(parent, dict(props), var, style)
                except (self._tk.TclError, TypeError, ValueError):
                    if style is None:
                        raise
                    _sweep(parent, existing)  # then again without the style, as _create
                    made, rejected = factory(parent, dict(props), var, None), True
            if style is not None and (rejected or caught):  # ttkbootstrap warns on bad tokens
                plan.log(_M_BOOTSTYLE, value=style, id=node.id)
            stage = "check"
            outer, inner = made if isinstance(made, tuple) and len(made) == 2 else (made, made)
            new = {str(child) for child in parent.winfo_children()} - before
            misc = self._tk.Misc
            if not (
                isinstance(outer, misc)
                and isinstance(inner, misc)
                and outer.master is parent
                and new == {str(outer)}
                and (inner is outer or str(inner).startswith(f"{outer}."))
            ):
                raise TypeError(f"the factory of {spec.name} returned {made!r}")
            if "state" in node.props and spec.property("state") is not None:
                inner.configure(state=node.props["state"].value)
            for definition in spec.properties:
                prop = node.props.get(definition.name)
                if not definition.translatable or prop is None:
                    continue
                mnemonic = definition.name == "text" and fallback.name in _MNEMONIC
                setter = self._ext_setter(spec.name, definition.name, outer, inner, mnemonic)
                setter(texts[definition.name], -1)  # inside the guard; retexted later
                failed = partial(self._text_failed, node)
                slots.append(_Slot(TextSlot(inst.doc.key, prop), setter, mnemonic, node.id, failed))
        except (Exception, SystemExit) as exc:  # isolation point (D7): fall back, never crash
            registry.report_failure(spec.name, self._backend, stage, exc)  # before the sweep
            _sweep(parent, existing)
            return self._failed(node, parent, fallback.name, repr(exc), spec.container)
        self._slots += slots
        self._events(node, fallback.name, inner, var)
        inst.scope._attach(node.id, inner)
        if spec.container:
            self._container(inst, inner, node.layout, fallback.name, node.children)
        if self._embed is not None:
            self._embed.on_node(node, outer, inner)
        return outer

    @staticmethod
    def _ext_setter(
        class_name: str, prop: str, outer: Tk, inner: Tk, mnemonic: bool
    ) -> Callable[[str, int], object]:
        if prop == "text":
            return TkSession._set_text(inner, mnemonic)
        if (class_name, prop) == ("tb:Tableview", "columns"):

            def headings(text: str, _underline: int) -> None:
                columns = outer.tablecolumns  # sorting restores these texts
                for column, heading in zip(
                    columns, split_headings(text, len(columns)), strict=True
                ):
                    column.configure(text=heading)

            return headings
        return lambda t, _u: outer.configure(**{prop: t})

    def _failed(
        self, node: Widget, parent: Tk, fallback: str, reason: str, container: bool = False
    ) -> Tk:
        """Log a failed plugin widget once per class; the design canvas may show a card."""
        key = "\0" + node.class_name
        # H62: with a destroyed parent the fallback cannot be shown and the build aborts.
        if key not in self._logged and parent.winfo_exists():
            self._logged.add(key)
            self._plan.log(_M_PLUGIN_FAILED, name=node.class_name, fallback=fallback)
        embed = self._embed
        if embed is None or embed.failed is None or container:
            return None
        card = embed.failed(node, parent, reason)
        embed.on_node(node, card, card)
        return card

    def _create(self, name: str, parent: Tk, options: dict[str, Any], node: Widget) -> Tk:
        factory = self._classes[name]
        style = self._style(node, name)
        if style is None:
            return factory(parent, **options)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                widget = factory(parent, bootstyle=style, **options)
                rejected = bool(caught)  # ttkbootstrap warns about unknown tokens
            except (self._tk.TclError, TypeError, ValueError):
                widget, rejected = factory(parent, **options), True
        if rejected:
            self._plan.log(_M_BOOTSTYLE, value=style, id=node.id)
        return widget

    def _events(self, node: Widget, name: str, widget: Tk, var: Tk) -> None:
        for event in node.events:
            fn = self._plan.handlers.get(event.handler)
            if fn is None:
                continue
            kind, details = event_wiring(name, event.name)
            if kind == "command":
                try:
                    widget.configure(command=_call(fn))
                except (Exception, SystemExit) as exc:  # a plugin widget without ``command``
                    self._unsupported(node, event.name, exc)
            elif kind == "trace":
                self._traces.append((var, var.trace_add("write", _call(fn))))
            elif kind == "modified":
                widget.bind("<<Modified>>", self._modified(widget, fn), add="+")
            elif kind == "virtual":
                widget.bind(details[0], self._armed_call(fn), add="+")
            else:
                result = "break" if event.name == "activate" else None
                sequences = (
                    tk_key_sequences(details[0], aqua=self._aqua) if kind == "key" else details
                )
                for sequence in sequences:
                    widget.bind(sequence, _call(fn, result), add="+")

    def _text_failed(self, node: Widget, exc: BaseException) -> None:
        """Log (once per class) and report a plugin text setter raising after the build."""
        key = "text:" + node.class_name
        if key not in self._logged:
            self._logged.add(key)
            self._plan.log(_M_TEXT_FAILED, name=node.class_name, id=node.id)
        self._plan.registry.report_failure(node.class_name, self._backend, "wire", exc)

    def _unsupported(self, node: Widget, event: str, exc: BaseException) -> None:
        """Log (once per class and event) and report an event a plugin widget refuses."""
        key = f"{node.class_name}{event}"
        if key not in self._logged:
            self._logged.add(key)
            self._plan.log(_M_EVENT_UNSUPPORTED, event=event, id=node.id, name=node.class_name)
        self._plan.registry.report_failure(node.class_name, self._backend, "wire", exc)

    @staticmethod
    def _modified(widget: Tk, fn: Callable[[], object]) -> Callable[..., None]:
        def callback(*_args: object) -> None:
            # Resetting the flag fires <<Modified>> again; the flag check stops the echo.
            if widget.edit_modified():
                fn()
                widget.edit_modified(False)

        return callback

    def _armed_call(self, fn: Callable[[], object]) -> Callable[..., None]:
        def callback(*_args: object) -> None:
            if self._armed:
                fn()

        return callback

    # ------------------------------------------------------------ texts and mnemonics
    @staticmethod
    def _set_text(widget: Tk, underline: bool = True) -> Callable[[str, int], object]:
        if underline:
            return lambda t, u: widget.configure(text=t, underline=u)
        return lambda t, _u: widget.configure(text=t)

    def apply_texts(
        self, text: Callable[[TextSlot], str], runtime_text: Callable[[str], str]
    ) -> None:
        """(Re)apply every text slot, splitting the mnemonics (spec 6.1, 6.2).

        Every text is computed (and clipped) before the first one is set, so a failing ``text``
        changes nothing. ``runtime_text`` serves the dialog button bar, which arrives in Step 14
        (trim 1).
        """
        apply_slots(self._slots, text, self._plan.log, self._clipped)

    # ------------------------------------------------------------ session
    def alive(self) -> bool:
        """True while the root and every window still exist (the user may close one)."""
        try:
            return bool(self._root.winfo_exists()) and all(
                top.winfo_exists() for top, _window in self._windows.values()
            )
        except self._tk.TclError:  # the Tcl interpreter itself is gone
            return False

    def show(self, window_id: str) -> str | None:
        """Show a window. Modality and the button result arrive in Step 14 (trim 1)."""
        if self._embed is not None:  # an embedded window is always shown on its canvas
            return None
        self._windows[window_id][0].deiconify()
        return None

    def run(self) -> None:
        """Run the Tk main loop of the root."""
        self._root.mainloop()

    def destroy(self) -> None:
        """Destroy every toplevel this session created (idempotent)."""
        if self._after is not None:
            with contextlib.suppress(self._tk.TclError):  # the root is already gone
                self._root.after_cancel(self._after)
            self._after = None
        for var, name in self._traces:  # H56: a dead session's handlers never fire again
            with contextlib.suppress(self._tk.TclError):  # the interpreter is gone
                var.trace_remove("write", name)
        self._traces.clear()
        for top in reversed(self._created):
            with contextlib.suppress(self._tk.TclError):  # already destroyed elsewhere
                top.destroy()
        self._created.clear()
        self._images.clear()
        self._keep.clear()
