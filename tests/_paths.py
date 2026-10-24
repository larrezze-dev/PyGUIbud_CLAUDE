"""Source roots of the two distributions (ADR-016): the `pyguibud` namespace package is split
between the designer portion (``src``) and the runtime portion (``runtime/src``)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: The `pyguibud` distribution: designer, codegen, preview and the CLIs.
DESIGNER_SRC = ROOT / "src"
#: The `pyguibud-runtime` distribution: core, backends, i18n, locale and pyguibud_runtime.
RUNTIME_SRC = ROOT / "runtime" / "src"
RUNTIME_LOCALE = RUNTIME_SRC / "pyguibud" / "locale"
