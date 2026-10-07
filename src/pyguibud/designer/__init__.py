"""The PyGUIbud designer application (ttkbootstrap).

``launch`` is the only entry used by the command line. Importing this package loads no Tk:
the Tk modules (``app``, ``theme_tk``, ...) are imported inside :func:`launch`.
"""

from __future__ import annotations

import sys

from pyguibud.i18n import N_, _

__all__ = ["launch", "report_cannot_open"]

_M_CANNOT_OPEN = N_("The designer window cannot be opened: {reason}")
_M_INSTALL_TK = N_("Install Tk for your Python (for example the python3-tk package).")


def report_cannot_open(reason: object, *, tk_missing: bool) -> int:
    """Print the translated "cannot open" message to stderr (no traceback) and return 1."""
    print(_(_M_CANNOT_OPEN).format(reason=reason), file=sys.stderr)
    if tk_missing:
        print(_(_M_INSTALL_TK), file=sys.stderr)
    return 1


def launch(lang: str, theme: str) -> int:
    """Open the designer window and run it until it is closed.

    Args:
        lang: Interface language code (already active in :mod:`pyguibud.i18n`).
        theme: ``"light"``, ``"dark"`` or ``"high-contrast"``.

    Returns:
        The process exit code: 0 after a normal close, 1 when no window can be opened,
        130 after Ctrl+C.
    """
    try:
        from pyguibud.designer.app import run
    except ImportError as exc:  # tkinter or ttkbootstrap is not installed
        return report_cannot_open(exc, tk_missing=True)
    return run(lang, theme)
