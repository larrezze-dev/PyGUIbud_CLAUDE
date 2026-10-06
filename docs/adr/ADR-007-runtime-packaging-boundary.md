# ADR-007 — Runtime packaging boundary (v0)

- **Status:** Accepted (user, 2026-10-06) · **Date:** 2026-10-06 · **Step:** 10

## Context
The `pyguibud_runtime` docstring promises "no dependency on the designer". However, `load_ui` must run the `pyguibud.core` validator first, the backends live in `pyguibud/backends/` (plan rows 10 and 16), and `core` imports `pyguibud.i18n`. Options considered:
- (a) Duplicate the reader and validator inside the runtime: two sources of truth, which contradicts ADR-006.
- (b) Move `core` into the runtime now: churns Steps 07–09 before the split is designed.
- (c) Allow a narrow, tested dependency now, and decide the distribution split in Step 20.

## Decision
- Adopt (c). Allowed imports: `pyguibud_runtime` → `pyguibud.core`, `pyguibud.i18n`, `pyguibud.backends.base`, plus `pyguibud.backends.<name>`, loaded lazily by name. **Never** the designer, `pyguibud.cli`, `pyguibud.uic` or `pyguibud.codegen`.
- `tkinter`, `ttkbootstrap` and `PySide6` are imported only inside backend `prepare()`/`build()`. Importing `pyguibud_runtime`, `pyguibud.backends.*` or `pyguibud.core` never loads a toolkit. `pyguibud.core` stays stdlib-only.
- `pyguibud/__init__.py` stays designer-, cli- and toolkit-free, because importing `pyguibud.core` executes it first.
- Mandatory **import-boundary test**: a subprocess imports `pyguibud_runtime` and `pyguibud.backends.ttkbootstrap`, then asserts that `sys.modules` contains no `tkinter`, `ttkbootstrap`, `pyguibud.cli`, `pyguibud.uic`, `pyguibud.designer*` or `pyguibud.codegen*`.
- Generated code (Step 11) imports none of these (ADR-003). Only `load_ui` users depend on `pyguibud`.
- Open question for Step 20: does `pyguibud-runtime` ship `core` + `i18n` + `backends` (with `pyguibud` depending on it), or does it vendor them? The boundary above keeps both possible.

## Consequences
- ➕ One validator for the designer, `--check` and `load_ui`. Forks add backends through `pyguibud.backends` without patching anything.
- ➖ Until Step 20, `load_ui` users install the whole `pyguibud` wheel (the designer code is present but never imported). The boundary test stops this from growing.
