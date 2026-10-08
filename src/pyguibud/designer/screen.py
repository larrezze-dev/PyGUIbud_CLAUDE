"""The desktop that windows and dialogs are kept on (Tk; spec properties-save-load 12, A10)."""

from __future__ import annotations

import logging
import sys
import tkinter

__all__ = ["desktop_bounds"]

_log = logging.getLogger(__name__)


def desktop_bounds(root: tkinter.Misc) -> tuple[int, int, int, int]:
    """``(width, height, left, top)`` of the desktop that ``fit_geometry`` clamps to.

    On Windows this is the virtual screen (every monitor): Tk's virtual root is the primary
    monitor only, so a window closed on a second monitor would come back at the default place.
    Elsewhere, or when the query fails, it is Tk's virtual root.
    """
    if sys.platform == "win32":
        try:
            import ctypes

            metrics = ctypes.windll.user32.GetSystemMetrics
            # SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
            width, height, left, top = (int(metrics(index)) for index in (78, 79, 76, 77))
            if width > 0 and height > 0:
                return width, height, left, top
        except (AttributeError, OSError):
            _log.debug("The virtual screen could not be read", exc_info=True)
    return root.winfo_vrootwidth(), root.winfo_vrootheight(), 0, 0
