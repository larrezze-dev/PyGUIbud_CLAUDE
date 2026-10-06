"""PyGUIbud runtime: load a ``.ui`` file and build it with a toolkit backend.

``load_ui`` validates the file (with the same validator as the designer), checks the handlers,
then builds the interface. Per ADR-007 this package depends on ``pyguibud.core``,
``pyguibud.i18n`` and ``pyguibud.backends``, never on the designer, the CLI or codegen, and
importing it loads no GUI toolkit (the backend imports it while building). Generated code
(``pyguibud-uic``) needs neither this package nor ``pyguibud``.
"""

from __future__ import annotations

from pyguibud_runtime._load import load_ui
from pyguibud_runtime._texts import Translator
from pyguibud_runtime._ui import LoadedUi, UiScope
from pyguibud_runtime.errors import UiError

__version__ = "0.1.0.dev0"

__all__ = ["LoadedUi", "Translator", "UiError", "UiScope", "__version__", "load_ui"]
