"""Tk side of the designer icons: one ``PhotoImage`` per icon and state, per root.

A theme switch re-tints and a scaling change resizes the images in place
(``image.configure(data=...)``), so image names and widget references stay valid and the
number of Tk images never grows with canvas rebuilds or theme switches.
"""

from __future__ import annotations

import base64
import logging
import tkinter
from typing import Final

from pyguibud.designer.icons import load_masks, pick_size, tinted_png
from pyguibud.designer.theme import ThemeSpec, design_tokens, load_theme_specs

__all__ = ["BASE_PX", "IconCache", "icons"]

_log = logging.getLogger(__name__)

#: The icon size at 96 dpi (rows, toolbar); larger displays pick the next mask size.
BASE_PX: Final = 16
_ATTRIBUTE: Final = "_pyguibud_icons"


class IconCache:
    """The icons of one root; :func:`icons` returns the root's single instance."""

    def __init__(self, root: tkinter.Misc) -> None:
        self.root = root
        self._images: dict[tuple[str, bool], tkinter.PhotoImage] = {}
        self._tints = self._tints_of(load_theme_specs()[0])  # until the first theme switch
        self.size = self._wanted_size()

    def _wanted_size(self) -> int:
        try:
            factor = float(self.root.tk.call("tk", "scaling")) / (96 / 72)
        except tkinter.TclError:
            factor = 1.0
        return pick_size(BASE_PX, factor)

    def _data(self, name: str, disabled: bool) -> str | None:
        sizes = load_masks().get(name)
        if not sizes:
            return None
        size = self.size if self.size in sizes else max(sizes)
        png = tinted_png(sizes[size], size, self._tints[disabled])
        return base64.b64encode(png).decode("ascii")

    def get(self, name: str, *, disabled: bool = False) -> tkinter.PhotoImage | None:
        """The image of ``name`` (created once), or None when it is unknown: show text."""
        key = (name, disabled)
        image = self._images.get(key)
        if image is None:
            data = self._data(name, disabled)
            if data is None:
                return None
            try:
                image = tkinter.PhotoImage(master=self.root, data=data)
            except tkinter.TclError:
                _log.warning("Could not create the icon %s", name, exc_info=True)
                return None
            self._images[key] = image
        return image

    def _reload(self) -> None:
        for (name, disabled), image in self._images.items():
            data = self._data(name, disabled)
            if data is not None:
                image.blank()
                image.configure(width=0, height=0, data=data)

    @staticmethod
    def _tints_of(spec: ThemeSpec) -> tuple[str, str]:
        tokens = design_tokens(spec)
        return tokens.icon, tokens.icon_disabled

    def retint(self, spec: ThemeSpec) -> None:
        """Recolour every image for ``spec`` (same masks, the theme's icon colours)."""
        tints = self._tints_of(spec)
        if tints != self._tints:
            self._tints = tints
            self._reload()

    def rescale(self) -> None:
        """Re-pick the mask size after a Tk scaling change and reload the images."""
        size = self._wanted_size()
        if size != self.size:
            self.size = size
            self._reload()


def icons(root: tkinter.Misc) -> IconCache:
    """The icon cache of the application root of ``root`` (created on first use, kept on the
    root, shared by dialogs, so a theme switch re-tints every icon)."""
    top = root.nametowidget(".")
    cache = getattr(top, _ATTRIBUTE, None)
    if not isinstance(cache, IconCache):
        cache = IconCache(top)
        setattr(top, _ATTRIBUTE, cache)
    return cache
