"""The desktop that windows and dialogs are kept on (Tk; spec properties-save-load 12, A10)."""

from __future__ import annotations

import ctypes
import logging
import sys
import tkinter

__all__ = ["border_width", "desktop_bounds", "title_height", "work_area"]

_log = logging.getLogger(__name__)


def desktop_bounds(root: tkinter.Misc) -> tuple[int, int, int, int]:
    """``(width, height, left, top)`` of the desktop that ``fit_geometry`` clamps to.

    On Windows this is the virtual screen (every monitor): Tk's virtual root is the primary
    monitor only, so a window closed on a second monitor would come back at the default place.
    Elsewhere, or when the query fails, it is Tk's virtual root.
    """
    if sys.platform == "win32":
        try:
            metrics = ctypes.windll.user32.GetSystemMetrics
            # SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN, SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN
            width, height, left, top = (int(metrics(index)) for index in (78, 79, 76, 77))
            if width > 0 and height > 0:
                return width, height, left, top
        except (AttributeError, OSError):
            _log.debug("The virtual screen could not be read", exc_info=True)
    return root.winfo_vrootwidth(), root.winfo_vrootheight(), 0, 0


def work_area(root: tkinter.Misc) -> tuple[int, int, int, int]:
    """``(width, height, left, top)`` of the work area (the screen less the taskbar) of the
    monitor showing ``root``; elsewhere than on Windows, or when the query fails, the desktop.
    Tk's ``wm maxsize`` is the whole screen, taskbar included (QA-19f-03)."""
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            class Info(ctypes.Structure):  # MONITORINFO
                _fields_ = (("size", wintypes.DWORD), ("monitor", wintypes.RECT),
                            ("work", wintypes.RECT), ("flags", wintypes.DWORD))  # fmt: skip

            user32 = ctypes.WinDLL("user32")
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            user32.MonitorFromWindow.argtypes = (ctypes.c_void_p, wintypes.DWORD)
            user32.GetMonitorInfoW.argtypes = (ctypes.c_void_p, ctypes.POINTER(Info))
            info = Info(size=ctypes.sizeof(Info))
            monitor = user32.MonitorFromWindow(root.winfo_id(), 2)  # MONITOR_DEFAULTTONEAREST
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                work = info.work
                if work.right > work.left and work.bottom > work.top:
                    return work.right - work.left, work.bottom - work.top, work.left, work.top
        except (AttributeError, OSError, ctypes.ArgumentError, tkinter.TclError):
            _log.debug("The work area could not be read", exc_info=True)
    return desktop_bounds(root)


def border_width(root: tkinter.Misc) -> int:
    """The frame border the window manager puts left and right of ``root`` (Windows; else 0,
    as for :func:`title_height`)."""
    win32 = sys.platform == "win32"
    return max(0, min(root.winfo_rootx() - root.winfo_x(), 50)) if win32 else 0


def title_height(root: tkinter.Misc) -> int:
    """The title bar and top border the window manager puts above ``root`` (Windows; else 0,
    as X11's ``winfo_y`` of a reparented window is no frame offset)."""
    win32 = sys.platform == "win32"  # an expression: no unreachable branch on any platform
    return max(0, min(root.winfo_rooty() - root.winfo_y(), 100)) if win32 else 0
