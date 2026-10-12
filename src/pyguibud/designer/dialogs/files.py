"""The only callers of the native file and colour choosers (a seam the tests replace).

Native dialogs block the Tk event loop until they close (risk R7 of spec 14a); tests swap these
functions for fakes instead of opening them.
"""

from __future__ import annotations

import os
import tkinter
from tkinter import colorchooser, filedialog
from typing import Any

from pyguibud.i18n import N_, _

__all__ = ["ask_colour", "ask_export", "ask_image", "ask_open", "ask_save"]

_M_COLOUR = N_("Choose a colour")
_M_IMAGE = N_("Choose an image")
_M_IMAGES = N_("Images")
_M_ALL = N_("All files")
_M_UI_FILES = N_("PyGUIbud UI files")
# Translators: the titles of the native Open and Save As file dialogs.
_M_OPEN = N_("Open a UI file")
_M_SAVE_AS = N_("Save the UI file as")
_M_PYTHON = N_("Python files")
_M_TEMPLATES = N_("Translation templates")


def _chosen(path: object) -> str | None:
    """A native dialog returns "" or an empty tuple when cancelled."""
    return path if isinstance(path, str) and path else None


def _ui_types() -> list[tuple[str, str]]:
    return [(_(_M_UI_FILES), "*.ui"), (_(_M_ALL), "*")]


def ask_open(root: Any, folder: str | None = None) -> str | None:  # noqa: ANN401 - the app root
    """The ``.ui`` file the user picked to open, or None when cancelled."""
    path = filedialog.askopenfilename(
        parent=root, title=_(_M_OPEN), filetypes=_ui_types(), initialdir=folder or None
    )
    return _chosen(path)


def ask_save(root: Any, name: str, folder: str | None = None) -> str | None:  # noqa: ANN401
    """The file the user picked to save as (``.ui`` added when missing), or None."""
    path = filedialog.asksaveasfilename(
        parent=root,
        title=_(_M_SAVE_AS),
        filetypes=_ui_types(),
        defaultextension=".ui",
        initialfile=name,
        initialdir=folder or None,
    )
    return _chosen(path)


def ask_export(root: Any, path: str, *, pot: bool = False) -> str | None:  # noqa: ANN401
    """The Python module (or with ``pot`` the ``.pot`` template) to export to, or None."""
    kind, pattern = (_M_TEMPLATES, ".pot") if pot else (_M_PYTHON, ".py")
    folder, name = os.path.split(path)
    chosen = filedialog.asksaveasfilename(
        parent=root,
        filetypes=[(_(kind), f"*{pattern}"), (_(_M_ALL), "*")],
        defaultextension=pattern,
        confirmoverwrite=False,  # the export checks the file itself (D12)
        initialfile=name,
        initialdir=folder or None,
    )
    return _chosen(chosen)


def ask_colour(root: Any, initial: str) -> str | None:  # noqa: ANN401 - the app root
    """The colour the user picked as ``#rrggbb``, or None when cancelled."""
    try:
        _rgb, chosen = colorchooser.askcolor(initial or None, parent=root, title=_(_M_COLOUR))
    except tkinter.TclError:  # an initial value Tk rejects: open the chooser without it
        _rgb, chosen = colorchooser.askcolor(parent=root, title=_(_M_COLOUR))
    return str(chosen) if chosen else None


def ask_image(root: Any) -> str | None:  # noqa: ANN401 - the app root
    """The path of the image file the user picked, or None when cancelled."""
    path = filedialog.askopenfilename(
        parent=root,
        title=_(_M_IMAGE),
        filetypes=[(_(_M_IMAGES), "*.png *.gif *.ppm *.pgm"), (_(_M_ALL), "*")],
    )
    return _chosen(path)
