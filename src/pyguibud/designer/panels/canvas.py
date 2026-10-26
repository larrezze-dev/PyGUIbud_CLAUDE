"""The canvas panel (spec dnd-selection 2.5-2.7): one tab per window, each a scrollable stage.

A stage shows the window's caption, its menu bar strip and the real window, built by the
runtime builder in embed mode (``canvas.engine``) and put in design mode. Stack listeners only
mark windows stale and schedule one ``after_idle`` rebuild (they run inside the stack's
``_Busy`` guard, so they must never call the stack). That rebuild never runs nested inside the
panel's own work: see :meth:`CanvasPanel._settled`.
"""

from __future__ import annotations

import contextlib
import logging
import tkinter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any

from pyguibud.core import StackEvent
from pyguibud.core.errors import PyGUIbudError, format_message
from pyguibud.core.model import Include, Widget, Window
from pyguibud.core.text import printable
from pyguibud.designer import sizing
from pyguibud.designer.canvas import design
from pyguibud.designer.canvas.engine import CanvasEngine, WindowView, reveal, widget_rect
from pyguibud.designer.canvas.overlay import SELECTION_CAP, Overlay
from pyguibud.designer.editing import Edge
from pyguibud.designer.geometry import Rect
from pyguibud.designer.icons_tk import icons
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present import clip
from pyguibud.designer.present.canvas import canvas_tabs, kind_label, window_of
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.signals import Signal
from pyguibud.designer.theme import ThemeSpec, design_tokens
from pyguibud.designer.theme_tk import (
    STYLE_CAPTION,
    STYLE_ERROR,
    STYLE_MUTED,
    STYLE_STAGE,
    STYLE_STRIP,
    STYLE_TITLE_LABEL,
    STYLE_TITLEBAR,
    menu_end,
    scaled,
    space,
)
from pyguibud.i18n import N_, _, ngettext

__all__ = ["CanvasPanel"]

_log = logging.getLogger(__name__)

# Translators: {new} and {open} are the shortcuts Ctrl+N and Ctrl+O, inserted as they are (key
# names are not translated, like the accelerators in the menus).
_M_EMPTY = N_("No document. Press {new} for a new one or {open} to open a file.")
_EMPTY_KEYS = {"new": "Ctrl+N", "open": "Ctrl+O"}
# Translators: the reason on the canvas card when a widget fails to build for an unforeseen
# cause; the technical detail is in the log file.
_M_UNEXPECTED = N_("an unexpected error occurred; see the log")
# Translators: shown on the canvas instead of a window that fails to render; {reason} is the
# technical cause (usually in English).
_M_CANNOT_DRAW = N_("This window cannot be drawn on the canvas: {reason}")
_STAGE_PAD = 12  # px at 96 dpi around the window on its stage
# Translators: shown in the status bar when the canvas gets the keyboard focus. {next} and
# {panel} are the keys Tab and F6, inserted as they are (key names are not translated).
FOCUS_HINT = N_("{next} selects the next widget; {panel} moves to the next panel.")
_FOCUS_KEYS = {"next": "Tab", "panel": "F6"}


def focus_hint() -> str:
    """The canvas focus hint in the interface language."""
    return format_message(FOCUS_HINT, _FOCUS_KEYS)


def _includes(window: Window, *, external: bool = False) -> bool:
    """True when ``window`` holds a same-file include (or, ``external``, one of another file)."""
    return any(isinstance(n, Include) and (n.src != "#") == external for n in window.walk())


def _nothing() -> None:
    return None


@dataclass(eq=False, slots=True)
class _Stage:
    """The tab of one window: scroll host, stage, chrome and the rendered view."""

    window: Window
    page: ttk.Frame
    scroll: tkinter.Canvas
    stage: ttk.Frame
    title: ttk.Label
    kind: ttk.Label
    strip: ttk.Frame
    card: tkinter.Frame
    overlay: Overlay
    plate: tkinter.Frame  # the window's framed backdrop: the lowest child of ``stage`` (R3)
    view: WindowView | None = None
    stale: bool = True
    error: PyGUIbudError | None = None  # why the last build failed (translated when shown)
    chrome: dict[int, Any] = field(default_factory=dict)  # id(menu bar / menu) -> strip widget


class CanvasPanel(PanelBase):
    """One stage per window; clicks select, the selection is outlined, edits rebuild."""

    name = "canvas"
    HEADING = N_("Canvas")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        # The focus proxy is each stage's scroll host (spec 7.3): one tab stop, the F6 target.
        self.notebook: Any = ttk.Notebook(self.frame, takefocus=False)
        self.notebook.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=2, pady=2)
        self.empty = ttk.Label(self.frame, anchor="center")
        self.engine = CanvasEngine(
            session.registry, scale=self._scaled, source=lambda: (session.path, session.revision)
        )
        self.stages: list[_Stage] = []
        #: Emitted just before every stage is destroyed (a re-render): whoever holds a stage
        #: (the drag controller) lets go of it while its widgets still exist.
        self.stages_closing: Signal[CanvasPanel] = Signal()
        self._spec: ThemeSpec | None = None
        self._idle: str | None = None
        self._depth = 0  # how deep the panel is in its own synchronous work (_settled)
        self._deferred = False  # a rebuild fired inside that work and waits for its end
        self._unsubscribe_stack: Callable[[], None] = _nothing
        # The tab that our own code selected: Tk reports that switch later, as an event, and it
        # must not be taken for a click of the user.
        self._expected = ""
        #: The shell's ``DragController``: a press on a selected widget can start a move.
        self.drag: Any = None
        self.status: Callable[[str], None] = lambda _text: None  # the shell's status bar
        self._keys: list[tuple[str, Callable[[Any], object]]] = []  # scoped chords (spec 7.4)
        self._aqua = str(self.frame.tk.call("tk", "windowingsystem")) == "aqua"
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab)
        design.install(
            self.frame,
            {
                "<ButtonPress-1>": self._on_press,
                "<Double-Button-1>": self._on_press,  # a quick 2nd press still selects/drags
                "<B1-Motion>": self._on_motion,
                "<ButtonRelease-1>": self._on_release,
                "<MouseWheel>": self._on_wheel,
                "<Button-4>": lambda e: self._scroll(e, -1),
                "<Button-5>": lambda e: self._scroll(e, 1),
            },
        )
        self._connect(session.document_changed, self._on_document)
        self._connect(session.selection_changed, self._on_selection)
        self._path = session.path  # a new folder (Save As) resolves the includes again
        self._connect(session.file_changed, lambda s: self.refresh_includes(s.path != self._path))
        self._render()

    def _scaled(self, pixels: int) -> int:
        return scaled(self.frame, pixels)

    # ------------------------------------------------------------ the CanvasPanel protocol
    def show_window(self, window: object) -> None:
        """Bring the tab of ``window`` to the front (rendering it if it is stale)."""
        with self._settled():
            for stage in tuple(self.stages):
                if stage.window is window:
                    if self.notebook.select() != str(stage.page):
                        self.notebook.select(stage.page)
                    if stage.stale:
                        self._build(stage)
            self._expected = str(self.notebook.select())

    def stage_of(self, window: object) -> _Stage | None:
        """The stage of ``window`` (tests and the later drag controller use it)."""
        return next((s for s in self.stages if s.window is window), None)

    @property
    def focus_widget(self) -> Any:  # noqa: ANN401 - a Tk widget
        """The keyboard focus proxy: the shown stage's scroll host (else the notebook)."""
        stage = self.current_stage()
        return stage.scroll if stage is not None else self.notebook

    @property
    def rebuild_pending(self) -> bool:
        """True while an ``after_idle`` rebuild is scheduled (arrow-key repeats are dropped)."""
        return self._idle is not None

    def bind_key(self, sequence: str, handler: Callable[[Any], object]) -> None:
        """Bind a canvas-scoped chord on every stage's focus proxy, now and after re-renders."""
        self._keys.append((sequence, handler))
        for stage in self.stages:
            stage.scroll.bind(sequence, handler, add="+")

    def refresh_includes(self, force: bool = False) -> None:
        """Rebuild the windows showing other files when one changed on disk (focus-in) or, with
        ``force``, when the document's folder changed (Save As; spec 6.2)."""
        self._path = self.session.path
        if not self.engine.includes.changed() and not force:
            return
        for stage in self.stages:
            # A same-file include may show a component that includes the changed file.
            stage.stale = stage.stale or any(isinstance(n, Include) for n in stage.window.walk())
        if self._idle is None:
            self._idle = self.frame.after_idle(self._flush)

    # ------------------------------------------------------------ signals
    def _on_document(self, _session: DesignerSession) -> None:
        self._path = self.session.path
        self._render()

    def _on_selection(self, selection: Selection) -> None:
        with self._settled():
            node = selection.node
            if node is not None and selection.origin != "canvas":
                self.show_window(window_of(node, self.session.document))
            self._outline_all(reveal_node=True)
        count = len(selection.nodes)
        if count > SELECTION_CAP + 1:  # the outlines are capped: say how many are selected
            # Translators: status bar after a large multi-selection; {count} is the number of
            # selected elements, {shown} how many of them the canvas outlines (fewer).
            text = ngettext(
                "{count} element selected; only {shown} are outlined.",
                "{count} elements selected; only {shown} are outlined.",
                count,
            )
            self.status(text.format(count=count, shown=SELECTION_CAP + 1))

    def _on_tab(self, _event: object) -> None:
        with self._settled():
            current = str(self.notebook.select())
            stage = next((s for s in self.stages if str(s.page) == current), None)
            if stage is not None and stage.stale:
                self._build(stage)
        if current == self._expected or stage is None:
            return
        self._expected = current
        owner = window_of(self.session.selection.node, self.session.document)
        if owner is not stage.window:  # a programmatic switch keeps a widget selection
            self.session.select(stage.window, origin="canvas")

    def _on_stack(self, event: StackEvent) -> None:
        """Mark the touched windows stale and schedule one rebuild (never calls the stack)."""
        if event.kind == "saved":
            return
        document = self.session.document
        targets = event.command.targets() if event.command is not None else ()
        owners = {id(w) for t in targets if (w := window_of(t, document)) is not None}
        for stage in self.stages:
            # A same-file include shows another window's nodes: any edit may change it.
            if not owners or id(stage.window) in owners or _includes(stage.window):
                stage.stale = True
        if self._idle is None:
            self._idle = self.frame.after_idle(self._flush)

    @contextlib.contextmanager
    def _settled(self) -> Iterator[None]:
        """Do the panel's own work without its scheduled rebuild re-entering it.

        ``_build`` and ``_outline`` call ``update_idletasks()`` (spec dnd-selection 2.6), which
        runs every idle handler, the pending ``_flush`` included. A re-render in there destroys
        the stage being built or outlined (deleting or cutting a window: a selection change
        right after the edit, ``bad window path name``). So the outermost call first runs the
        pending rebuild itself, and a rebuild that still fires inside waits until it ends.
        """
        outer = self._depth == 0
        if outer and self._idle is not None:
            self.frame.after_cancel(self._idle)
            self._flush()
        self._depth += 1
        try:
            yield
        finally:
            self._depth -= 1
        if outer and self._deferred:
            self._deferred = False
            self._flush()

    def _flush(self) -> None:
        self._idle = None
        if self._depth:  # inside the panel's own update_idletasks(): after it (_settled)
            self._deferred = True
            return
        with self._settled():
            self._rebuild_stale()

    def _rebuild_stale(self) -> None:
        document = self.session.document
        windows = [] if document is None else [id(w) for w in document.children]
        if windows != [id(s.window) for s in self.stages]:
            self._render()
            return
        if document is not None:
            for stage, tab in zip(self.stages, canvas_tabs(document), strict=True):
                self.notebook.tab(stage.page, text=tab.text)
        current = self.current_stage()
        built = current if current is not None and current.stale else None
        if built is not None:
            self._build(built)
        self._outline_all(reveal_node=False, done=built)

    # ------------------------------------------------------------ design-mode input
    def _stage_at(self, widget: Any) -> _Stage | None:  # noqa: ANN401 - a Tk widget
        path = str(widget)
        for stage in self.stages:
            root = str(stage.page)
            if path == root or path.startswith(root + "."):
                return stage
        return None

    def _on_press(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        """Click selects, Ctrl+click toggles, Shift+click adds (spec 7.2); a press on a
        container's empty area arms a rubber band, on a selected widget a move."""
        stage = self._stage_at(event.widget)
        if stage is None or stage.view is None:
            return
        held = isinstance(event.state, int) and bool(event.state & 0x100)  # Button-1 still down
        if self.drag is not None and self.drag.busy and held:
            return  # Q12 (H40): a second pointer never ends the running drag; a lost release does
        stage.scroll.focus_set()  # design widgets take no focus: the keys go to the proxy
        node = stage.view.node_of(event.widget)
        if node is None:
            return
        if isinstance(node, Widget) and event.widget is stage.view.inner.get(id(node)):
            self._select_tab(event)
        state = event.state if isinstance(event.state, int) else 0
        toggle = bool(state & (0x8 if self._aqua else 0x4))  # Cmd on aqua (0x8 = NumLock on Win)
        modified = toggle or bool(state & 0x1)
        selected = any(node is n for n in self.session.selection.nodes)
        band = modified or not selected or isinstance(node, Window)
        if self.drag is not None and self._container(node) and band:
            if not modified:
                self.session.select(node, origin="canvas")
            base = self.session.selection.nodes if modified else ()
            click = (lambda: self._click(node, toggle)) if modified else None
            self.drag.press_band(node, base, click, event.x_root, event.y_root)
        elif modified:
            self._click(node, toggle)
        elif not selected or isinstance(node, Window):
            self.session.select(node, origin="canvas")
        nodes = self.session.selection.nodes
        movable = isinstance(node, Widget | Include) and any(node is n for n in nodes)
        if not modified and self.drag is not None and movable and not self.drag.moving:
            self.drag.press_move(nodes, node, event.x_root, event.y_root, event.widget)

    def _container(self, node: object) -> bool:
        """A window body, or a layout or page container (where a rubber band can start)."""
        if isinstance(node, Window):
            return True
        spec = self.session.registry.get(node.class_name) if isinstance(node, Widget) else None
        pages = spec is not None and spec.children == "pages"
        return isinstance(node, Widget) and (node.layout is not None or pages)

    def _click(self, node: object, toggle: bool) -> None:
        """A Ctrl+click toggles ``node`` in the selection; a Shift+click adds it."""
        nodes = self.session.selection.nodes
        if toggle and any(node is n for n in nodes):
            rest = [n for n in nodes if n is not node]
            if rest:
                self.session.select_many(rest, origin="canvas")
            else:
                self.session.select(window_of(node, self.session.document), origin="canvas")
            return
        self.session.select_many([*nodes, node], origin="canvas")

    def _on_motion(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self.drag is not None:
            self.drag.motion(event.x_root, event.y_root)

    def _on_release(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        if self.drag is not None:
            self.drag.release(event.x_root, event.y_root)

    def _cancel_move(self, event: Any) -> str | None:  # noqa: ANN401 - a Tk event
        """Esc (or the focus leaving) cancels a canvas move; a palette drag is not ours.

        Only Esc is consumed: a focus loss still reaches the other FocusOut bindings.
        """
        if self.drag is None or not self.drag.moving:
            return None
        self.drag.cancel()
        return "break" if getattr(event, "keysym", "") == "Escape" else None

    def _on_handle(self, edge: Edge, phase: str, event: Any) -> str:  # noqa: ANN401 - a Tk event
        """A handle of the primary: hover, press, drag, release and double-click.

        A filled handle sizes (spec direct-manipulation 2.2), a hollow one or Ctrl (also
        Command on macOS, R3) changes a grid child's spans (dnd-selection 8).
        """
        node, stage, drag = self.session.selection.node, self.current_stage(), self.drag
        state = event.state if isinstance(event.state, int) else 0
        if drag is None or stage is None:
            return "break"
        kind = stage.overlay.kinds.get(edge)
        if phase == "enter" and kind is not None and not isinstance(node, Window):
            spec = self.session.registry.get(getattr(node, "class_name", ""))
            self.status(sizing.hover_text(node, spec, edge, kind))
        elif phase == "double" and kind == "size" and drag.state in ("idle", "armed"):  # Q12
            drag.reset_size(node, edge)
        elif phase == "press" and drag.state in ("idle", "armed"):  # Q12: one drag at a time
            self.focus_widget.focus_set()  # Esc reaches _cancel_move
            span = bool(state & 0x4) or (self._aqua and bool(state & 0x8))
            if kind == "span" or (span and sizing.grid_child(node)):
                drag.press_resize(node, edge, event.x_root, event.y_root, event.widget)
            elif kind == "size":
                drag.press_size(node, edge, event.x_root, event.y_root, event.widget)
        elif phase in ("motion", "release"):
            relay = drag.motion if phase == "motion" else drag.release
            relay(event.x_root, event.y_root, fine=bool(state & 0x1))
        return "break"

    def _handle_kinds(self, node: object) -> dict[Edge, sizing.HandleKind]:
        """The primary's handles: none while read-only (Q2); a window gets 3 (spec 3)."""
        if node is None or self.session.read_only_refusal() is not None:
            return {}
        if isinstance(node, Window):
            return dict.fromkeys(("e", "se", "s"), "size")
        return sizing.handle_kinds(node, self.session.registry.get(getattr(node, "class_name", "")))

    def window_box(self, stage: _Stage) -> tuple[Rect, tuple[int, int]] | None:
        """The window body (stage column 0, row 2, where ``min_width``/``min_height`` apply)
        in stage coordinates, and its contents' natural size (spec 3, D5)."""
        column, row, view = stage.stage.grid_bbox(0, 0), stage.stage.grid_bbox(0, 2), stage.view
        if view is None or not column or not row:
            return None
        bars = [w for w in (stage.title.master, stage.strip) if w.winfo_manager()]
        width = max(w.winfo_reqwidth() for w in (view.frame, *bars)) + 2  # the plate edge
        natural = (width, view.frame.winfo_reqheight() + 1)
        return Rect(column[0], row[1], column[2], row[3]), natural

    def measure(self, node: object) -> sizing.Measured | None:
        """What a size key step needs of ``node`` on the shown stage (spec 4)."""
        stage = self.current_stage()
        if stage is None or stage.view is None:
            return None
        if isinstance(node, Window):
            box = self.window_box(stage)
            return None if box is None else sizing.Measured((box[0].w, box[0].h), natural=box[1])
        outer = stage.view.outer.get(id(node))
        rect = widget_rect(outer, stage.stage) if outer is not None else None
        if rect is None:
            return None
        return sizing.Measured((rect.w, rect.h), self.engine.metrics(stage.view, node))

    @staticmethod
    def _select_tab(event: Any) -> None:  # noqa: ANN401 - a Tk event
        """A click on a tab label of a canvas Notebook shows that page (the only live input)."""
        if event.widget.winfo_class() != "TNotebook":
            return
        try:
            event.widget.select(event.widget.index(f"@{event.x},{event.y}"))
        except tkinter.TclError:  # not over a tab label
            return

    def _on_wheel(self, event: Any) -> None:  # noqa: ANN401 - a Tk event
        delta = int(getattr(event, "delta", 0))
        if delta:
            self._scroll(event, -1 if delta > 0 else 1)

    def _scroll(self, event: Any, units: int) -> None:  # noqa: ANN401 - a Tk event
        stage = self._stage_at(event.widget)
        if stage is not None:
            stage.scroll.yview_scroll(units, "units")

    # ------------------------------------------------------------ rendering
    def current_stage(self) -> _Stage | None:
        """The stage of the shown tab."""
        current = str(self.notebook.select())
        return next((s for s in self.stages if str(s.page) == current), None)

    def _render(self) -> None:
        """Recreate every tab (a new document, a window added or removed, a language switch)."""
        previous = self.current_stage()
        previous_window = previous.window if previous is not None else None
        if self._idle is not None:
            self.frame.after_cancel(self._idle)
            self._idle = None
        self._clear()
        document = self.session.document
        self._unsubscribe_stack()
        self._unsubscribe_stack = _nothing
        if document is None or self.session.stack is None:
            self.empty.configure(text=format_message(_M_EMPTY, _EMPTY_KEYS))
            self.empty.grid(row=1, column=0, columnspan=2)
            return
        self.empty.grid_remove()
        self._unsubscribe_stack = self.session.stack.subscribe(self._on_stack)
        for tab in canvas_tabs(document):
            stage = self._new_stage(tab.window)
            self.notebook.add(stage.page, text=tab.text)
            self.stages.append(stage)
        self._expected = str(self.notebook.select())
        node = self.session.selection.node
        target = window_of(node, document) if node is not None else previous_window
        self.show_window(target if self.stage_of(target) is not None else None)
        current = self.current_stage()
        if current is not None and current.stale:
            self._build(current)
        self._outline_all(reveal_node=True, done=current)  # _build outlined the shown tab

    def _clear(self) -> None:
        self.stages_closing.emit(self)
        for tab in self.notebook.tabs():
            self.notebook.forget(tab)
        for stage in self.stages:
            if stage.view is not None:
                stage.view.destroy()
            stage.page.destroy()
        self.stages.clear()

    def _new_stage(self, window: Window) -> _Stage:
        page = ttk.Frame(self.notebook)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        scroll = tkinter.Canvas(page, highlightthickness=0, borderwidth=0, takefocus=1)
        # Esc cancels a move or band first ("break"); only then is it Select parent.
        for sequence in ("<Escape>", "<FocusOut>"):
            scroll.bind(sequence, self._cancel_move, add="+")
        scroll.bind("<FocusIn>", lambda _e: self.status(focus_hint()), add="+")
        for sequence, handler in self._keys:
            scroll.bind(sequence, handler, add="+")
        vbar = ttk.Scrollbar(page, orient="vertical", command=scroll.yview)
        hbar = ttk.Scrollbar(page, orient="horizontal", command=scroll.xview)
        scroll.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        scroll.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        stage = ttk.Frame(scroll, style=STYLE_STAGE, padding=self._scaled(_STAGE_PAD))
        scroll.create_window(0, 0, anchor="nw", window=stage)
        # The plate is created first, so it starts beneath the caption, strip and card; after a
        # window build it is lowered again (R3). Its 1 px edge is the window's frame. It is
        # placed over the first column's rows (``_on_stage_configure``), not gridded: the stage
        # grid keeps exactly one child per cell.
        plate = tkinter.Frame(stage, borderwidth=0, highlightthickness=1, takefocus=0)
        caption = ttk.Frame(stage, style=STYLE_TITLEBAR)
        m, s = space(stage, "m"), space(stage, "s")
        mark = icons(stage).get(f"window_{window.kind}")
        glyph = ttk.Label(caption, style=STYLE_TITLE_LABEL, image=mark or "")
        title = ttk.Label(caption, style=STYLE_TITLE_LABEL, anchor="w")
        kind = ttk.Label(caption, style=STYLE_CAPTION, anchor="w")
        if mark is not None:
            glyph.grid(row=0, column=0, padx=(m, 0), pady=s)
        title.grid(row=0, column=1, sticky="w", padx=(m, 0), pady=s)
        kind.grid(row=0, column=2, sticky="w", padx=m, pady=s)
        caption.grid(row=0, column=0, sticky="ew", padx=1, pady=(1, 0))
        strip = ttk.Frame(stage)
        overlay = Overlay(stage, scale=self._scaled, on_handle=self._on_handle)
        card = tkinter.Frame(stage, borderwidth=0, highlightthickness=1, takefocus=0)
        built = _Stage(window, page, scroll, stage, title, kind, strip, card, overlay, plate)
        stage.bind("<Configure>", lambda _e: self._on_stage_configure(built))
        # The stage's own <Configure> comes before grid has laid out its rows (and, the first
        # time, before the stage padding applies: grid_bbox() is still (0, 0, ...)). The title
        # bar is moved or resized whenever that layout settles, so its <Configure> places the
        # plate again with the final box; a fixed min_height/min_width gives no second stage
        # <Configure> to do it (QA-14p-04).
        caption.bind("<Configure>", lambda _e: self._on_stage_configure(built), add="+")
        for widget in (scroll, stage, plate, caption, glyph, title, kind, strip):
            widget.bind("<ButtonPress-1>", self._selector(window))
            widget.bind("<MouseWheel>", self._on_wheel)
        title.configure(text=clip(printable(window.id)))
        kind.configure(text=kind_label(window))
        if self._spec is not None:
            self._restyle_stage(built, self._spec)
        return built

    def _on_stage_configure(self, stage: _Stage) -> None:
        box = stage.stage.grid_bbox(0, 0, 0, 2)
        if box is not None:
            stage.plate.place(x=box[0], y=box[1], width=box[2], height=box[3], bordermode="outside")
        stage.scroll.configure(scrollregion=stage.scroll.bbox("all"))
        self._outline(stage, reveal_node=False)

    def _build(self, stage: _Stage) -> None:
        """Rebuild ``stage``'s window off-screen, then swap it in (no flicker, spec 2.6)."""
        stage.stale = False
        document = self.session.document
        if document is None:
            return
        # A window drag or key step changes these: every rebuild applies them again.
        stage.stage.columnconfigure(0, minsize=stage.window.min_width or 0)
        stage.stage.rowconfigure(2, minsize=stage.window.min_height or 0)
        try:
            view = self.engine.build(document, stage.window, stage.stage)
        except Exception as exc:
            _log.exception("The window %r cannot be drawn on the canvas", stage.window.id)
            self._drop_view(stage)
            # H68: never raw Tcl/exception text on the card (it stays in the log above).
            stage.error = (
                exc
                if isinstance(exc, PyGUIbudError)
                else PyGUIbudError("canvas.build", _M_UNEXPECTED)
            )
            self._show_card(stage)
            return
        if stage.view is not None:  # a rebuild keeps the shown Notebook pages
            self.engine.restore_pages(view, self.engine.pages(stage.view))
        stage.stage.update_idletasks()
        view.frame.grid(
            row=2, column=0, sticky="nsew", padx=1, pady=(0, 1)
        )  # inside the plate edge
        stage.overlay.sink(view.frame)  # created above the strips: beneath them now
        stage.plate.lower()  # sink() put the window at the very bottom: the plate goes under it
        self._drop_view(stage)
        stage.view, stage.error = view, None
        stage.card.grid_remove()
        stage.title.configure(text=clip(printable(view.title or stage.window.id)))
        self._fill_strip(stage, view)
        self._outline(stage, reveal_node=True)

    def _drop_view(self, stage: _Stage) -> None:
        if stage.view is not None:
            stage.view.destroy()
            stage.view = None

    def _show_card(self, stage: _Stage) -> None:
        for child in stage.card.winfo_children():
            child.destroy()
        count, m = len(self.session.report().errors), space(stage.card, "m")
        wrap = self._scaled(480)
        # str() of the stored error translates lazily: a rebuilt card follows a language switch.
        reason = _(_M_CANNOT_DRAW).format(reason=stage.error)
        mark = icons(stage.card).get("error")
        message = ttk.Label(stage.card, style=STYLE_ERROR, text=reason, wraplength=wrap)
        message.grid(row=0, column=1, sticky="w", padx=(0, m), pady=(m, 0))
        # Translators: under the message of a widget that failed to build; {count} is the number
        # of errors.
        errors = ngettext("{count} error", "{count} errors", count).format(count=count)
        ttk.Label(stage.card, style=STYLE_MUTED, text=errors).grid(
            row=1, column=1, sticky="w", padx=(0, m), pady=(0, m)
        )
        # Created last: the reason and the count stay the card's first two children.
        glyph = ttk.Label(stage.card, style=STYLE_ERROR, image=mark or "")
        glyph.grid(row=0, column=0, rowspan=2, padx=m, pady=m)
        stage.card.grid(row=2, column=0, sticky="nw", padx=m, pady=m)
        stage.plate.lower()
        stage.strip.grid_remove()
        stage.overlay.show_selection(())
        stage.overlay.show_empty(())

    def _fill_strip(self, stage: _Stage, view: WindowView) -> None:
        """One label per top-level menu of the hidden menu bar; a click selects that menu."""
        for child in stage.strip.winfo_children():
            child.destroy()
        stage.chrome.clear()
        bar, model = view.menubar(), stage.window.menubar
        if bar is None or model is None:
            stage.strip.grid_remove()
            return
        stage.chrome[id(model)] = stage.strip
        last = menu_end(bar)
        menus, count = model.children, 0 if last is None else last + 1
        for index in range(count):
            label = ttk.Label(
                stage.strip,
                style=STYLE_STRIP,
                text=bar.entrycget(index, "label"),
                underline=int(bar.entrycget(index, "underline")),
            )
            label.grid(row=0, column=index)
            node: object = menus[index] if index < len(menus) else model
            stage.chrome[id(node)] = label
            label.bind("<ButtonPress-1>", self._selector(node))
        # A full-width bar: a spacer column takes the slack, and the 1 px gap below it shows the
        # plate (painted ``divider``), which is the bar's divider.
        stage.strip.columnconfigure(count, weight=1)
        stage.strip.grid(row=1, column=0, sticky="ew", padx=1, pady=(0, 1))

    def _selector(self, node: object) -> Callable[[object], None]:
        """A click handler of chrome: select ``node`` and take the keys, as a body click does."""

        def select(_event: object) -> None:
            self.focus_widget.focus_set()
            self.session.select(node, origin="canvas")

        return select

    # ------------------------------------------------------------ selection outline
    def _outline_all(self, *, reveal_node: bool, done: _Stage | None = None) -> None:
        """Outline the selection on every stage but ``done`` (just built and outlined).

        A stale stage is skipped too: its view is about to be replaced, and ``_build`` outlines
        the new one (an edit used to outline the shown tab four times, QA-13a-05).
        """
        for stage in tuple(self.stages):
            if stage is not done and not stage.stale:
                self._outline(stage, reveal_node=reveal_node)

    def _outline(self, stage: _Stage, *, reveal_node: bool) -> None:
        """Outline every selected node shown on ``stage``; only the primary's page is revealed."""
        primary, view = self.session.selection.node, stage.view
        if view is None:
            stage.overlay.show_selection(())
            stage.overlay.show_empty(())
            return
        if primary is not None and reveal_node and id(primary) in view.outer:
            reveal(view, primary)
            stage.stage.update_idletasks()
        chosen, empty = {id(n) for n in self.session.selection.nodes}, list[Rect]()
        for key, node in view.nodes.items():  # R-D: empty, unselected, never a window body
            if key in view.included and key not in chosen:  # R-E: an expanded include
                with contextlib.suppress(tkinter.TclError):
                    empty += [r] if (r := widget_rect(view.outer[key], stage.stage)) else []
            if key in chosen or not isinstance(node, Widget) or node.children:
                continue
            with contextlib.suppress(tkinter.TclError):  # the widget is being destroyed
                rect = widget_rect(view.outer[key], stage.stage) if self._container(node) else None
                empty += [rect] if rect is not None else []
        stage.overlay.show_empty(empty)
        rects, primary_rect, others = [], None, 0
        for node in self.session.selection.nodes:
            if node is not primary:  # the primary always; the others up to SELECTION_CAP
                if others >= SELECTION_CAP:
                    continue
                others += 1
            widget = stage.chrome.get(id(node), view.outer.get(id(node)))
            try:
                rect = widget_rect(widget, stage.stage) if widget is not None else None
            except tkinter.TclError:  # the widget is being destroyed
                rect = None
            if rect is not None:
                rects.append(rect)
                primary_rect = rect if node is primary else primary_rect
        handles = self._handle_kinds(primary)
        stage.overlay.show_selection(rects, primary=primary_rect, handles=handles)
        if reveal_node and primary_rect is not None and not isinstance(primary, Window):
            self._see(stage, primary_rect)

    @staticmethod
    def _see(stage: _Stage, rect: Rect) -> None:
        """Scroll an off-screen ``rect`` (stage coordinates) into view (Tab, spec 7.3).

        A partly visible one stays put: whatever the pointer picked never scrolls the stage
        (a jump under the pointer would also shift a rubber band that is starting).
        """
        canvas, body = stage.scroll, stage.stage
        left, top = int(canvas.canvasx(0)), int(canvas.canvasy(0))
        if Rect(left, top, canvas.winfo_width(), canvas.winfo_height()).intersects(rect):
            return
        for move, first, start, size, view, total in (
            (canvas.xview_moveto, canvas.canvasx(0), rect.x, rect.w, canvas.winfo_width(),
             body.winfo_width()),
            (canvas.yview_moveto, canvas.canvasy(0), rect.y, rect.h, canvas.winfo_height(),
             body.winfo_height()),
        ):  # fmt: skip
            if total > 1 and (start < first or start + size > first + view):
                target = start if start < first else min(start, start + size - view)
                move(max(0, target) / total)

    # ------------------------------------------------------------ Panel protocol
    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        self._spec = spec
        for stage in self.stages:
            self._restyle_stage(stage, spec)
            # Design mode drops instance <<ThemeChanged>> hooks (Meter, icons): rebuild instead.
            stage.stale = True
        if self.stages and self._idle is None:
            self._idle = self.frame.after_idle(self._flush)

    @staticmethod
    def _restyle_stage(stage: _Stage, spec: ThemeSpec) -> None:
        tokens = design_tokens(spec)
        stage.scroll.configure(background=tokens.stage)
        stage.plate.configure(background=tokens.divider, highlightbackground=tokens.plate_border)
        stage.card.configure(background=spec.colors["bg"], highlightbackground=tokens.error_border)
        stage.overlay.restyle(spec)

    def focus_first(self) -> None:
        self.focus_widget.focus_set()

    def dispose(self) -> None:
        if self._idle is not None:
            try:
                self.frame.after_cancel(self._idle)
            except tkinter.TclError:
                _log.debug("after_cancel failed", exc_info=True)
            self._idle = None
        self._unsubscribe_stack()
        self._unsubscribe_stack = _nothing
        try:
            design.uninstall(self.frame)
            for stage in self.stages:
                if stage.view is not None:
                    stage.view.destroy()
        except tkinter.TclError:  # the root is already gone
            _log.debug("The canvas was already destroyed", exc_info=True)
        self.stages.clear()
        super().dispose()
