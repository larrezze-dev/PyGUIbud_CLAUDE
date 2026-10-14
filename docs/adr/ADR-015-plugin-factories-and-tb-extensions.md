# ADR-015 — Plugin factories, isolation and the `tb:` extensions

- **Status:** Accepted (user, 2026-10-14: D1–D21 all recommended defaults: D6 a placeholder card, D11 core fallbacks in tkinter and Qt, D12 one `;`-separated translatable `columns` string, D13 native `tb:` export with third-party plugins exported as their fallback, D14 R83 error + R84 warning, D16 a modal Help ▸ Plugins… dialog; split 17a/17b/17c, caps 650/600/600, trims T1–T7) · **Date:** 2026-10-14 · **Step:** 17 · **Spec:** `docs/specs/plugins.md` (D1–D21). It amends ADR-004 (factory contract, isolation) and ADR-008 (native `tb:` emission); the accepted text of both stays as it is.

## Context
ADR-004 named per-backend factories but no contract. Today a factory is never called: `_tk.py` indexes a class table, `_qt.py` looks up `_make_<name>`, and codegen forces the fallback. Three more problems:
- a raising factory aborts the whole window build;
- `SystemExit` raised by a plugin import kills the designer;
- `pyguibud.core` must stay stdlib-only, yet built-in `tb:` specs need ttkbootstrap callables.

Options considered:
- a full adapter protocol per backend;
- probing plugins in a subprocess;
- `<column>` children for Tableview (a schema bump).

## Decision
- **References:** `WidgetSpec.factories` values are callables or lazy `"module:attr"` strings, resolved by `Registry.load_factory`. Keys follow `BACKEND_NAME` (moved to core). The built-in `tb:` specs come from a second built-in entry point (`pyguibud.core.widgets:tb_widgets`). "Built-in" means two things together: the distribution is `pyguibud` and the value prefix is `pyguibud.core.widgets:`. Their factories live in `pyguibud.backends._tbwidgets`, and the `tb` prefix is reserved.
- **Contract — "renders as itself, behaves as its fallback":**
  - Tk: `factory(parent, props, variable, bootstyle)`;
  - Qt: `factory(parent, props)`, where `inner` is an instance of the fallback's Qt class.
  The builder then wires text, state, variables and events as for the fallback.
- **Registration checks:** `events` ⊆ the fallback's events, `bind_types` ⊆ the fallback's row, and the same container kind. A file valid with a plugin stays valid without it.
- **Isolation:**
  - `Exception` and `SystemExit` are caught at import, at the spec callable, at factory resolution and around each factory call (checks included);
  - on a failure: clean-up, then `Registry.report_failure` (deduplicated, with `revision`), then the fallback (the design canvas shows a card for non-containers);
  - there are no in-process timeouts; instead, `pyguibud --no-plugins` and `Settings.disabled_plugins` filter before `ep.load()`. The designer passes both to the preview child.
- **Validator:**
  - `WidgetSpec.bind_types` (extensions);
  - generic `PropertyDef.pattern/max_length/hint` (R89/R90);
  - `tb:bootstyle` grammar (R83) and tokens (R84);
  - unknown `tb:` attributes (R85);
  - PEP 508 `plugin=` (R86);
  - failed or disabled plugins (R87/R88).
  `SetExtraAttr` edits extension attributes through the guard.
- **Rendering:** `tb:` widgets have ttkbootstrap factories only. tkinter and PySide6 render the core fallbacks (FEATURES §3 amended). Codegen emits `tb:` natively; third-party plugins export as their fallback.
- **Diagnostics:** a Help ▸ Plugins… dialog lists the status and tracebacks per distribution, and has a Disable toggle that takes effect on the next start. `WIDGET_API_VERSION` stays 1 (provisional).

## Consequences
- ➕ The plugin API is exercised by the built-in `tb:` widgets (dogfooding).
- ➕ A broken plugin degrades to its fallback and never crashes the designer.
- ➕ A `.ui` file never triggers an import.
- ➖ Plugins still run trusted code in-process, and a hang needs safe mode. Mitigation: a documented trust boundary, the disabled list and `--no-plugins`.
- ➖ The fallback-shaped contract limits plugin events and binding types. Mitigation: a later ADR can add an adapter protocol under API version 2.
- Affected: Step 18 (msgids), Step 19 (abuse cases), Step 20 (the runtime split carries `_tbwidgets`).
