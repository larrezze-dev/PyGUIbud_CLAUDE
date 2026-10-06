# ADR-001 — Abstract widget vocabulary with namespaced toolkit extensions

- **Status:** Accepted (Step 02 UAT) · **Date:** 2026-10-05 · **Step:** 02

## Context
PyGUIbud targets ttkbootstrap, tkinter and PySide6. A `.ui` file tied to one toolkit's native names would be faithful but not portable. A strict common subset would be portable but would hide ttkbootstrap bootstyles and widgets such as Meter or DateEntry.

## Decision
- The `.ui` file uses a **toolkit-agnostic vocabulary** (Frame, Button, Entry…) defined in `pyguibud.core`. Every backend must map all core classes (see FEATURES.md §3).
- Toolkit-specific widgets and attributes live in **XML namespaces** (`tb:` = ttkbootstrap). Extension widgets must declare a `fallback` core class.
- A backend renders the elements it understands; for unknown extension widgets it renders the `fallback` and ignores unknown extension attributes, with a warning.
- Unknown namespaced content is **preserved on save** (round-trip safe).

## Consequences
- ➕ One file can run on any backend; forks can add namespaces (`qt:`, `acme:`) without touching the core.
- ➕ ttkbootstrap users keep bootstyles and extras.
- ➖ Each backend has to maintain a mapping table, and abstract properties must be defined carefully. Mapping tests are required for every backend.
