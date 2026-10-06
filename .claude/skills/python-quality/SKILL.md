---
name: python-quality
description: PyGUIbud Python coding standards (typing, structure, toolchain, packaging layout, dependency rules). Use when writing or reviewing any Python code in the PyGUIbud repository.
---

# Python quality standards

## Toolchain
Python ≥ 3.10 · `uv` (env + lock) · hatchling · ruff (lint + format) · mypy `--strict` on `pyguibud.core` and `pyguibud_runtime` · pytest + hypothesis · pre-commit.
Commands: `uv run ruff check . --fix` · `uv run ruff format .` · `uv run mypy src/pyguibud/core` · `uv run pytest -q`.

## Structure and dependencies
- `src/` layout. `pyguibud.core` = pure dataclasses + stdlib, **no GUI imports**. `pyguibud_runtime` = stdlib + the chosen toolkit only (it ships with users' apps, so keep it tiny).
- Backends and widgets register via entry points (`pyguibud.backends`, `pyguibud.widgets`), including the built-in ones (dogfooding).
- PySide6 is imported lazily inside its backend; a missing PySide6 produces a clear message telling the user to install the extra.

## Code style
- Full type hints; `from __future__ import annotations`; prefer `dataclass(slots=True, frozen=True)` for value objects; `Enum`/`Literal` for closed sets.
- Model mutations go **only** through the command stack (undo/redo) and the validator.
- Errors: domain exceptions (`PyGUIbudError` subclasses) carry a translatable message and a machine code. Never use a bare `except:`; never swallow errors silently.
- User-facing strings: `_()` with named placeholders. Log messages are not translated.
- File I/O: `pathlib`, explicit `encoding="utf-8"`, atomic writes for user files.
- Comments explain *why*, in en-GB. Public functions get concise docstrings.
- Keep functions small and side-effect-free where possible; this keeps tests cheap.
- Don't add dependencies without an ADR or orchestrator approval.

## Definition of done
ruff + mypy clean, tests added and passing, no new untranslated user-facing string, and the caller's verification command run with its output reported.
