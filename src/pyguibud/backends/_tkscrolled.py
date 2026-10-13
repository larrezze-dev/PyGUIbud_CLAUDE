"""A vertical scrolled frame for the plain ``tkinter`` backend (spec backends D3).

It offers the surface of ttkbootstrap's ``ScrolledFrame`` that :class:`~pyguibud.backends._tk.
TkSession` relies on: children are created in the frame itself, ``container`` is what gets
placed, and ``auto_hide`` hides the scrollbar while the pointer is away. Imports ``tkinter`` at
module level, so only ``TkinterBackend.build`` imports this module.
"""

from __future__ import annotations

import contextlib
import tkinter
from tkinter import ttk
from typing import Any

__all__ = ["ScrolledFrame"]

_WHEEL = ("<MouseWheel>", "<Button-4>", "<Button-5>")


class _Container(ttk.Frame):
    """The outer frame; it records that it is being destroyed so the content does not recurse."""

    tearing_down = False

    def destroy(self) -> None:
        self.tearing_down = True
        super().destroy()


class ScrolledFrame(ttk.Frame):
    """Canvas viewport + vertical scrollbar; the frame itself is the scrolled content."""

    def __init__(
        self,
        master: tkinter.Misc,
        *,
        padding: int = 2,
        auto_hide: bool = False,
        height: int = 200,
        width: int = 300,
        **kwargs: Any,  # noqa: ANN401 - passed on to ttk.Frame
    ) -> None:
        self.container = _Container(master, width=width, height=height)
        self.container.propagate(False)
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)
        # Sized as ttkbootstrap's: the viewport asks for width x height (QA-16a-03).
        self._canvas = tkinter.Canvas(
            self.container, highlightthickness=0, borderwidth=0, width=width, height=height
        )
        self._canvas.grid(row=0, column=0, sticky="nsew")
        self._bar = ttk.Scrollbar(self.container, orient="vertical", command=self._canvas.yview)
        self._bar.grid(row=0, column=1, sticky="ns")
        self._canvas.configure(yscrollcommand=self._bar.set)
        super().__init__(self._canvas, padding=padding, **kwargs)
        self.auto_hide = auto_hide
        window = self._canvas.create_window(0, 0, anchor="nw", window=self)
        # Keep the content as wide as the viewport and the scroll region as tall as the content.
        self.bind(
            "<Configure>", lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        )
        self._canvas.bind(
            "<Configure>", lambda e: self._canvas.itemconfigure(window, width=e.width)
        )
        # The wheel scrolls through a bind tag of this instance, not bind_all: it never
        # replaces the application's own bindings or outlives the frame (QA-16a-04).
        self._tag = f"PyGUIbudScrolledFrame{id(self)}"
        for sequence in _WHEEL:
            self.bind_class(self._tag, sequence, self._wheel)
        self.container.bind("<Enter>", self._enter, add="+")
        self.container.bind("<Leave>", self._leave, add="+")
        if auto_hide:
            self._bar.grid_remove()
        for method in ("pack", "grid", "place"):  # placing "the frame" places the assembly
            setattr(self, method, getattr(self.container, method))

    def _tag_subtree(self, add: bool) -> None:
        """Add or remove the wheel tag on the viewport and the content (children come later)."""
        stack: list[tkinter.Misc] = [self._canvas, self]
        while stack:
            widget = stack.pop()
            stack.extend(widget.winfo_children())
            tags = [t for t in widget.bindtags() if t != self._tag]
            widget.bindtags((tags[0], self._tag, *tags[1:]) if add else tuple(tags))

    def _enter(self, _event: object) -> None:
        self._tag_subtree(add=True)
        if self.auto_hide:
            self._bar.grid()

    def _leave(self, event: tkinter.Event[tkinter.Misc]) -> None:
        under = self.container.winfo_containing(event.x_root, event.y_root)
        root = str(self.container)
        if (under is not None and str(under).startswith(root + ".")) or str(under) == root:
            return  # the pointer only moved onto a child
        self._tag_subtree(add=False)
        if self.auto_hide:
            self._bar.grid_remove()

    def _wheel(self, event: tkinter.Event[tkinter.Misc]) -> None:
        first, last = self._canvas.yview()
        if first > 0.0 or last < 1.0:  # content that fits is not scrolled
            step = -1 if event.num == 4 or event.delta > 0 else 1
            self._canvas.yview_scroll(step, "units")

    def destroy(self) -> None:
        """Destroy the whole assembly, whether called on the content or on the container."""
        if self.container.tearing_down:
            for sequence in _WHEEL:
                with contextlib.suppress(tkinter.TclError):  # the interpreter is already gone
                    self.unbind_class(self._tag, sequence)
            super().destroy()
        else:
            self.container.destroy()
