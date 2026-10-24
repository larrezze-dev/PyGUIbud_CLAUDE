# ADR-016 — `pyguibud-runtime` distribution split (namespace portions)

- **Status:** Accepted (user, 2026-10-24) · **Date:** 2026-10-24 · **Step:** 20 · Settles the open question of ADR-007 (its import rules stay in force)

## Context
`load_ui` needs `pyguibud.core`, `pyguibud.i18n`, `pyguibud.backends` and the catalogues, but `pyguibud_runtime` ships inside the `pyguibud` wheel today. Two distributions cannot both own `pyguibud/__init__.py`, which holds nothing but `__version__`. Options (spec `docs/specs/packaging.md` D1):
- (a) Move the shared code into `pyguibud_runtime._core`, with shims or rewritten imports in about 860 lines across 260 files. Shims split module identity and break monkeypatching.
- (b) A third `pyguibud-core` distribution: the same churn as (a), plus a third project to publish.
- (c) Make `pyguibud` a PEP 420 namespace package and ship it in two portions: no import changes.

## Decision
- Adopt (c). Delete `src/pyguibud/__init__.py`. **`pyguibud-runtime`** (uv workspace member `runtime/`) ships the following, as unchanged module names:
  - `pyguibud/__about__.py`, `pyguibud/i18n.py`, `pyguibud/core/` (with `schema/`), `pyguibud/backends/` and `pyguibud/locale/*.mo`;
  - `pyguibud_runtime/`.
- **`pyguibud`** ships `pyguibud/{__main__,cli,uic,_argparse,credits}.py` and `pyguibud/{codegen,designer,preview}/`, and depends on `pyguibud-runtime==<same version>`. No file is in both wheels; a build check enforces this.
- The `pyguibud.widgets`/`pyguibud.backends` entry points are declared **only** by `pyguibud-runtime`. The group names and values are unchanged. Built-in means the distribution `pyguibud-runtime` plus the existing value prefix. Any entry point from a distribution named `pyguibud` or `pyguibud-runtime` that is not built-in is treated as a fork (H66 rule).
- The catalogue keeps one gettext domain, `pyguibud`, owned by the runtime. Both wheels ship `.mo` only.
- `ttkbootstrap` is a runtime dependency, because the default backend of `load_ui` is `ttkbootstrap`. `PySide6` stays the `[pyside]` extra on both distributions.

## Consequences
- ➕ No import, entry-point or test-import churn. Generated code (no PyGUIbud import, ADR-003) and plugins that import `pyguibud.core` keep working.
- ➖ `pyguibud.__version__` is gone; use `pyguibud.__about__`. Nothing has been published yet, so no external user breaks. mypy needs `explicit_package_bases` and both source roots. PEP 561 `py.typed` goes in each subpackage, so the top-level modules (`pyguibud.i18n`) are untyped for consumers. The runtime wheel carries the designer msgids (≈ 500); a domain split is possible after v1.
