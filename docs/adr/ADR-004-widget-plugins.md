# ADR-004 — Widget plugin API

- **Status:** Accepted (Step 02 UAT) · **Date:** 2026-10-05 · **Step:** 02

## Context
The user chose full plugin widgets for v1: third parties ship widgets with palette icons, property definitions and live rendering in the designer.

## Decision
- Discovery via the entry point group **`pyguibud.widgets`**. Each entry point returns a `WidgetSpec`: namespaced class name (`acme:ColourPicker`), display name (translatable), icon, category, `container: bool`, typed property schema, supported events, `fallback` core class, and per-backend factories (`ttkbootstrap`, `tkinter`, `pyside6`; each optional).
- Backends follow the same mechanism (`pyguibud.backends`); the core widgets are registered through it too (dogfooding).
- **Isolation:** plugin loading and rendering are wrapped. Any exception → placeholder widget + entry in a *Plugins* diagnostics panel; the designer never crashes. Plugins can be disabled from settings.
- **Versioning:** `WidgetSpec.api_version`; incompatible plugins are listed but not loaded.
- `.ui` records `plugin="<distribution name>"` so a missing plugin produces an actionable message (`pip install acme-pyguibud`), and the fallback is rendered.

## Consequences
- ➕ Ecosystem and forks extend PyGUIbud without patching the core.
- ➖ Plugins execute code when loaded, so this is documented as a trust boundary (only install plugins you trust). The API surface must stay stable, so it is marked *provisional* until 1.0.
