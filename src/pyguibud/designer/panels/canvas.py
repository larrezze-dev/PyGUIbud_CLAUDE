"""The canvas panel (spec dnd-selection 2.5-2.7): one tab per window, each a scrollable stage.

A stage shows the window's caption, its menu bar strip and the real window, built by the
runtime builder in embed mode (``canvas.engine``) and put in design mode. Stack listeners only
mark windows stale and schedule one ``after_idle`` rebuild (they run inside the stack's
``_Busy`` guard, so they must never call the stack).
"""

from __future__ import annotations

import logging
import tkinter
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk
from typing import Any

from pyguibud.core import StackEvent
from pyguibud.core.model import Widget, Window
from pyguibud.designer.canvas import design
from pyguibud.designer.canvas.engine import CanvasEngine, WindowView, reveal, widget_rect
from pyguibud.designer.canvas.overlay import Overlay
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present.canvas import canvas_tabs, kind_label, window_of
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.signals import Signal
from pyguibud.designer.theme import ThemeSpec
from pyguibud.designer.theme_tk import scaled
from pyguibud.i18n import N_, _, ngettext

__all__ = ["CanvasPanel"]

_log = logging.getLogger(__name__)

_M_EMPTY = N_("No document is open.")
# Translators: shown on the canvas instead of a window that fails to render; {reason} is the
# technical cause (usually in English).
_M_CANNOT_DRAW = N_("This window cannot be drawn on the canvas: {reason}")
_STAGE_PAD = 12  # px at 96 dpi around the window on its stage


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
    card: ttk.Frame
    overlay: Overlay
    view: WindowView | None = None
    stale: bool = True
    error: str | None = None  # why the last build failed
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
        self.notebook: Any = ttk.Notebook(self.frame, takefocus=True)
        self.notebook.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=2, pady=2)
        self.empty = ttk.Label(self.frame, anchor="center")
        self.engine = CanvasEngine(session.registry, scale=self._scaled)
        self.stages: list[_Stage] = []
        #: Emitted just before every stage is destroyed (a re-render): whoever holds a stage
        #: (the drag controller) lets go of it while its widgets still exist.
        self.stages_closing: Signal[CanvasPanel] = Signal()
        self._spec: ThemeSpec | None = None
        self._idle: str | None = None
        self._unsubscribe_stack: Callable[[], None] = _nothing
        # The tab that our own code selected: Tk reports that switch later, as an event, and it
        # must not be taken for a click of the user.
        self._expected = ""
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab)
        design.install(
            self.frame,
            {
                "<ButtonPress-1>": self._on_press,
                "<MouseWheel>": self._on_wheel,
                "<Button-4>": lambda e: self._scroll(e, -1),
                "<Button-5>": lambda e: self._scroll(e, 1),
            },
        )
        self._connect(session.document_changed, self._on_document)
        self._connect(session.selection_changed, self._on_selection)
        self._render()

    def _scaled(self, pixels: int) -> int:
        return scaled(self.frame, pixels)

    # ------------------------------------------------------------ the CanvasPanel protocol
    def show_window(self, window: object) -> None:
        """Bring the tab of ``window`` to the front (rendering it if it is stale)."""
        for stage in self.stages:
            if stage.window is window:
                if self.notebook.select() != str(stage.page):
                    self.notebook.select(stage.page)
                if stage.stale:
                    self._build(stage)
        self._expected = str(self.notebook.select())

    def stage_of(self, window: object) -> _Stage | None:
        """The stage of ``window`` (tests and the later drag controller use it)."""
        return next((s for s in self.stages if s.window is window), None)

    # ------------------------------------------------------------ signals
    def _on_document(self, _session: DesignerSession) -> None:
        self._render()

    def _on_selection(self, selection: Selection) -> None:
        node = selection.node
        if node is not None and selection.origin != "canvas":
            self.show_window(window_of(node, self.session.document))
        self._outline_all(reveal_node=True)

    def _on_tab(self, _event: object) -> None:
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
            if not owners or id(stage.window) in owners:
                stage.stale = True
        if self._idle is None:
            self._idle = self.frame.after_idle(self._flush)

    def _flush(self) -> None:
        self._idle = None
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
        stage = self._stage_at(event.widget)
        if stage is None or stage.view is None:
            return
        self.notebook.focus_set()  # design widgets take no focus: the keys (Delete) go here
        node = stage.view.node_of(event.widget)
        if node is None:
            return
        if isinstance(node, Widget) and event.widget is stage.view.inner.get(id(node)):
            self._select_tab(event)
        self.session.select(node, origin="canvas")

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
            self.empty.configure(text=_(_M_EMPTY))
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
        scroll = tkinter.Canvas(page, highlightthickness=0, borderwidth=0, takefocus=0)
        vbar = ttk.Scrollbar(page, orient="vertical", command=scroll.yview)
        hbar = ttk.Scrollbar(page, orient="horizontal", command=scroll.xview)
        scroll.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        scroll.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        stage = ttk.Frame(scroll, padding=self._scaled(_STAGE_PAD))
        scroll.create_window(0, 0, anchor="nw", window=stage)
        caption = ttk.Frame(stage)
        title = ttk.Label(caption, font="TkHeadingFont", anchor="w")
        kind = ttk.Label(caption, anchor="w")
        title.grid(row=0, column=0, sticky="w")
        kind.grid(row=0, column=1, sticky="w", padx=(self._scaled(12), 0))
        caption.grid(row=0, column=0, sticky="w", pady=(0, self._scaled(6)))
        strip = ttk.Frame(stage)
        stage.columnconfigure(0, minsize=window.min_width or 0)
        stage.rowconfigure(2, minsize=window.min_height or 0)
        overlay = Overlay(stage, scale=self._scaled)
        built = _Stage(window, page, scroll, stage, title, kind, strip, ttk.Frame(stage), overlay)
        stage.bind("<Configure>", lambda _e: self._on_stage_configure(built))
        for widget in (scroll, stage, caption, title, kind, strip):
            widget.bind("<ButtonPress-1>", self._selector(window))
            widget.bind("<MouseWheel>", self._on_wheel)
        title.configure(text=window.id)
        kind.configure(text=kind_label(window))
        if self._spec is not None:
            self._restyle_stage(built, self._spec)
        return built

    def _on_stage_configure(self, stage: _Stage) -> None:
        stage.scroll.configure(scrollregion=stage.scroll.bbox("all"))
        self._outline(stage, reveal_node=False)

    def _build(self, stage: _Stage) -> None:
        """Rebuild ``stage``'s window off-screen, then swap it in (no flicker, spec 2.6)."""
        stage.stale = False
        document = self.session.document
        if document is None:
            return
        try:
            view = self.engine.build(document, stage.window, stage.stage)
        except Exception as exc:
            _log.exception("The window %r cannot be drawn on the canvas", stage.window.id)
            self._drop_view(stage)
            stage.error = str(exc) or type(exc).__name__
            self._show_card(stage)
            return
        if stage.view is not None:  # a rebuild keeps the shown Notebook pages
            self.engine.restore_pages(view, self.engine.pages(stage.view))
        stage.stage.update_idletasks()
        view.frame.grid(row=2, column=0, sticky="nsew")
        self._drop_view(stage)
        stage.view, stage.error = view, None
        stage.card.grid_remove()
        stage.title.configure(text=view.title or stage.window.id)
        self._fill_strip(stage, view)
        self._outline(stage, reveal_node=True)

    def _drop_view(self, stage: _Stage) -> None:
        if stage.view is not None:
            stage.view.destroy()
            stage.view = None

    def _show_card(self, stage: _Stage) -> None:
        for child in stage.card.winfo_children():
            child.destroy()
        count = len(self.session.report().errors)
        wrap = self._scaled(480)
        reason = _(_M_CANNOT_DRAW).format(reason=stage.error)
        ttk.Label(stage.card, text=reason, wraplength=wrap, anchor="w").grid(sticky="w")
        errors = ngettext("{count} error", "{count} errors", count).format(count=count)
        ttk.Label(stage.card, text=errors, anchor="w").grid(sticky="w")
        stage.card.grid(row=2, column=0, sticky="nw")
        stage.strip.grid_remove()
        stage.overlay.show_selection(None)

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
        last = bar.index("end")
        menus = model.children
        for index in range(0 if last is None else last + 1):
            label = ttk.Label(
                stage.strip,
                text=bar.entrycget(index, "label"),
                underline=int(bar.entrycget(index, "underline")),
                padding=(self._scaled(6), self._scaled(2)),
            )
            label.pack(side="left")
            node: object = menus[index] if index < len(menus) else model
            stage.chrome[id(node)] = label
            label.bind("<ButtonPress-1>", self._selector(node))
        stage.strip.grid(row=1, column=0, sticky="w")

    def _selector(self, node: object) -> Callable[[object], None]:
        """A click handler of chrome: select ``node`` and take the keys, as a body click does."""

        def select(_event: object) -> None:
            self.notebook.focus_set()
            self.session.select(node, origin="canvas")

        return select

    # ------------------------------------------------------------ selection outline
    def _outline_all(self, *, reveal_node: bool, done: _Stage | None = None) -> None:
        """Outline the selection on every stage but ``done`` (just built and outlined).

        A stale stage is skipped too: its view is about to be replaced, and ``_build`` outlines
        the new one (an edit used to outline the shown tab four times, QA-13a-05).
        """
        for stage in self.stages:
            if stage is not done and not stage.stale:
                self._outline(stage, reveal_node=reveal_node)

    def _outline(self, stage: _Stage, *, reveal_node: bool) -> None:
        node, view = self.session.selection.node, stage.view
        widget = None
        if node is not None and view is not None:
            widget = stage.chrome.get(id(node), view.outer.get(id(node)))
            if widget is not None and reveal_node:
                reveal(view, node)
                stage.stage.update_idletasks()
        try:
            rect = widget_rect(widget, stage.stage) if widget is not None else None
        except tkinter.TclError:  # the widget is being destroyed
            rect = None
        stage.overlay.show_selection(rect)

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
        stage.scroll.configure(background=spec.colors["bg"])
        stage.overlay.restyle(spec)

    def focus_first(self) -> None:
        self.notebook.focus_set()

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
