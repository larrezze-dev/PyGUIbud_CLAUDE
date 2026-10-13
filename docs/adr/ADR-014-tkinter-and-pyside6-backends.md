# ADR-014 — tkinter and PySide6 backends

- **Status:** Accepted (user, 2026-10-12: D1–D20 all defaults) · **Date:** 2026-10-12 · **Step:** 16 · **Spec:** `docs/specs/backends.md` (D1–D20)

## Context
ADR-001 promises that one `.ui` runs on ttkbootstrap, tkinter and PySide6, and ADR-013 left a `PreviewHost` slot for the other two. `_tk.py` already takes its class table, root factory and theme hook as parameters. Qt is different in four ways:
- it has no Tk variables and no per-cell padding;
- its sliders are integer-only;
- its labels render HTML;
- without a display it aborts the process instead of raising.

PySide6 is an optional extra. Rejected options: a backend-aware validator (it would change the core API), Qt-idiomatic variables, and a single Step 16 session.

## Decision
- **tkinter = `TkSession` reused:** a `tkinter`/`ttk` class table, `tkinter.Tk()` and `bootstyle=False`, plus a canvas-based ScrolledFrame shim. It never imports ttkbootstrap.
- **PySide6 = its own `QtSession`** (`backends/_qt.py`, imported only in `build()`). Its tables live in the pure `backends/_qtmap.py`.
  - Labels are PlainText, and `&` is escaped.
  - A display guard runs before `QApplication`.
  - The window semantics mirror Tk (spec §4).
- **Portable `ui.vars`:** pure `backends/_vars.py` classes with the tkinter subset (`get`, `set`, `trace_add`, `trace_remove`).
- **Degradations are runtime warnings** through `plan.log`, once per message and class. `validate()` stays backend-agnostic.
- **Preview:**
  - the built-in hosts, or a backend's optional `preview_host()`;
  - Preview ▸ Toolkit lists `registry.backends()`;
  - themes exist only for ttkbootstrap;
  - export stays ttkbootstrap (ADR-008).
- **"Same `.ui` in three toolkits"** = `portable_describe` equality over the fixtures, plus one shared event matrix.
- **Tests and CI:** the Qt tests run offscreen under the `qt` marker, in their own CI job; without PySide6 they are skipped and mypy ignores the imports. There is no `.ui`, core or runtime change.

## Consequences
- ➕ A fork adds a toolkit with one entry point (plus an optional preview host). Handler code that uses `ui.vars` is portable.
- ➖ The windows are not pixel-identical, and some Qt items degrade. Mitigation: logged warnings and a documented differences list. The Qt session is large. Mitigation: three parts with caps and trims.
- Affected:
  - Step 17: factories plug into `_create` and the Qt adapter table, and `WidgetSpec.bind_types` is needed;
  - Step 19: the B1–B16 abuse cases;
  - Step 20: the runtime distribution needs a `[pyside]` extra.
