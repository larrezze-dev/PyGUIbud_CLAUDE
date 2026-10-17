"""The PySide6 backend (spec backends D8, §4.1): Qt widgets built by ``_qt.QtSession``.

PySide6 is an optional extra (``pip install "pyguibud[pyside]"``). It is imported only inside
:meth:`PySide6Backend.prepare` and :meth:`PySide6Backend.build`, so importing this module loads
no toolkit (ADR-007).
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from pyguibud.backends.base import BuildPlan, NoDisplayError
from pyguibud.i18n import N_, _

if TYPE_CHECKING:
    from pyguibud.backends._qt import QtSession

__all__ = ["PySide6Backend", "application", "display_problem"]

# Translators: {extra} is the literal install command; keep it unchanged.
_M_INSTALL = N_("PySide6 is not installed. Install it with: {extra}")
_M_THREAD = N_("PySide6 interfaces must be loaded in the main thread.")
# Translators: the application already runs a Qt core application, which cannot show windows.
_M_NOT_GUI = N_("The running Qt application has no graphical interface (QCoreApplication).")
# Translators: {variables} is a comma-separated list of environment variable names; keep it
# unchanged.
_M_NO_DISPLAY = N_("No display is set ({variables}), so Qt cannot open windows.")
# Translators: {name} is the value of an environment variable and {variable} its name; keep
# {variable} unchanged.
_M_NO_PLUGIN = N_("The Qt platform plugin '{name}' ({variable}) is not installed.")
_PLATFORM_VARIABLE = "QT_QPA_PLATFORM"
_DISPLAY_VARIABLES = ("DISPLAY", "WAYLAND_DISPLAY")
#: The QApplication this backend created: later sessions reusing it still quit it (§4.1).
_created_app: Any = None


def display_problem(
    platform: str, environ: Mapping[str, str], plugins: Iterable[str] = ()
) -> str | None:
    """Why Qt cannot open a display on ``platform``, or None (pure; D8 guard, QA-16b-01).

    Qt aborts the whole process (qFatal; on Windows it hangs on a message box) when
    ``QT_QPA_PLATFORM`` names no installed plugin, or on Linux and the BSDs without a display,
    so both are checked before a ``QApplication`` exists. ``plugins`` are the file names of the
    platform plugins; none known (an unreadable folder) never refuses.
    """
    value = environ.get("QT_QPA_PLATFORM", "")
    names = [part.split(":")[0].strip().lower() for part in value.split(";") if part.strip()]
    keys = _plugin_keys(plugins)
    if names and keys and not keys.intersection(names):  # exact keys: "win" is not "windows"
        return _(_M_NO_PLUGIN).format(name=value[:64], variable=_PLATFORM_VARIABLE)
    if not platform.startswith(("linux", "freebsd", "openbsd", "netbsd", "dragonfly")):
        return None
    if not names:  # Qt picks xcb or wayland by itself
        return None if any(environ.get(name) for name in _DISPLAY_VARIABLES) else _no_display()
    for name in names:  # xcb and wayland need their display; offscreen, eglfs... need none
        need = (
            "DISPLAY" if name == "xcb" else "WAYLAND_DISPLAY" if name.startswith("wayland") else ""
        )
        if not need or environ.get(need):
            return None
    return _no_display()


def _no_display() -> str:
    """The no-display reason, naming the variables a user can set (names are not translated)."""
    variables = ", ".join((*_DISPLAY_VARIABLES, _PLATFORM_VARIABLE))
    return _(_M_NO_DISPLAY).format(variables=variables)


def _plugin_keys(files: Iterable[str]) -> set[str]:
    """The ``QT_QPA_PLATFORM`` keys the platform plugin files serve, by name (QA-16c-01).

    ``libqxcb.so`` -> xcb; ``libqwayland-egl.so`` -> wayland-egl and wayland (as its metadata).
    A Windows debug build adds ``d`` to every file (``qwindowsd.dll`` -> windows), so the ``d``
    is dropped only when all ``.dll`` keys end in it (``qdirect2d.dll`` keeps direct2d).
    Residual: a release folder holding only ``qdirect2d.dll`` would also accept direct2.
    """
    found: list[tuple[str, str]] = []
    for file in files:
        stem, dot, extension = file.lower().removeprefix("lib").rpartition(".")
        if dot and extension in ("dll", "so", "dylib") and stem.startswith("q") and stem[1:]:
            found.append((stem[1:], extension))
    dlls = [key for key, extension in found if extension == "dll"]
    debug = bool(dlls) and all(key.endswith("d") and len(key) > 1 for key in dlls)
    keys = {key[:-1] if debug and extension == "dll" else key for key, extension in found}
    return keys | {key.partition("-")[0] for key in keys}


def _platform_plugins() -> list[str]:
    """The file names in Qt's platform plugin folders (where Qt itself looks for them)."""
    from PySide6.QtCore import QLibraryInfo

    roots = [QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)]
    roots += os.environ.get("QT_PLUGIN_PATH", "").split(os.pathsep)
    folders = [Path(root) / "platforms" for root in roots if root]
    if executable := getattr(sys, "executable", ""):  # a frozen application's own plugins
        folders.append(Path(executable).parent / "platforms")
    if extra := os.environ.get("QT_QPA_PLATFORM_PLUGIN_PATH"):
        folders.append(Path(extra))
    names: list[str] = []
    for folder in folders:
        with contextlib.suppress(OSError):
            names += [path.name for path in folder.iterdir()]
    return names


def application() -> Any:  # noqa: ANN401 - a QApplication
    """The running ``QApplication``, else a new one this backend owns, made after the D8 guard.

    Raises:
        NoDisplayError: Qt would abort the process instead of opening a display.
    """
    from PySide6 import QtWidgets

    global _created_app  # one QApplication per process
    app: Any = QtWidgets.QApplication.instance()
    if app is None:
        reason = display_problem(sys.platform, os.environ, _platform_plugins())
        if reason is not None:
            raise NoDisplayError(reason)
        app = _created_app = QtWidgets.QApplication([sys.argv[0] if sys.argv else "pyguibud"])
    return app


class PySide6Backend:
    """Builds ``.ui`` documents with PySide6 (Qt 6) widgets."""

    name: ClassVar[str] = "pyside6"

    def prepare(self, master: object | None) -> None:
        """Import PySide6 and check the thread, a running application and ``master``.

        Raises:
            RuntimeError: PySide6 is missing, not the main thread, or a non-GUI application.
            TypeError: ``master`` is not a live ``QWidget``.
        """
        try:
            import shiboken6
            from PySide6 import QtCore, QtWidgets
        except ImportError as exc:
            raise RuntimeError(
                _(_M_INSTALL).format(extra='pip install "pyguibud[pyside]"')
            ) from exc
        app = QtCore.QCoreApplication.instance()
        if app is None:
            main = threading.current_thread() is threading.main_thread()
        else:
            main = app.thread() is QtCore.QThread.currentThread()
        if not main:
            raise RuntimeError(_(_M_THREAD))
        if app is not None and not isinstance(app, QtWidgets.QApplication):
            raise RuntimeError(_(_M_NOT_GUI))
        if master is not None and not (
            isinstance(master, QtWidgets.QWidget) and shiboken6.isValid(master)
        ):
            raise TypeError("master must be a live QWidget")

    def build(self, plan: BuildPlan, master: object | None) -> QtSession:
        """Build the plan (the main window is shown when this returns).

        Raises:
            NoDisplayError: no display, checked before Qt could abort the process.
        """
        from pyguibud.backends._qt import QtSession

        app = application()
        return QtSession(plan, master, app=app, owns_app=app is _created_app).build()
