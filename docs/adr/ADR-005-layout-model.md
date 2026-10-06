# ADR-005 — Layout model: grid + restricted pack

- **Status:** Accepted (Step 02 UAT) · **Date:** 2026-10-05 · **Step:** 02

## Context
Layouts must work in tkinter/ttkbootstrap and map cleanly to Qt. tkinter's `place` and fully general `pack` (mixed sides) have no clean Qt equivalent and produce fragile, non-resizable UIs.

## Decision
- Supported: **grid** (row, column, rowspan, columnspan, sticky, padx/pady; column/row weights and minsize) → `QGridLayout`; and **pack with one `orient` per container** (vertical/horizontal, fill, expand, padding) → `QVBoxLayout`/`QHBoxLayout`.
- `place`/absolute layout: **Won't v1**.
- Each container declares exactly one layout; mixing is blocked by the validator (it also crashes Tk at runtime).
- Drag-and-drop UX: the canvas shows insertion targets (grid cells / pack slots) instead of free pixel positions; grid collisions are blocked.

## Consequences
- ➕ Resizable, portable layouts; simpler drag-and-drop hit-testing.
- ➖ Users wanting pixel placement must nest frames; documented with templates.

## Addendum A — page containers (Step 07, approved by the user 2026-10-05)
- Containers are of two kinds (`WidgetSpec.children`): **layout** containers (Frame, LabelFrame, ScrolledFrame, windows…) have exactly one `<layout>` (grid or pack), as above. **Page** containers (Notebook, PanedWindow) have **no** `<layout>`. Each of their direct children carries a page placement instead of a grid cell or pack slot: tab text/image for Notebook, pane weight for PanedWindow.
- No extra Tab/Pane classes. A page that needs several widgets uses a Frame child with its own layout.
- The XML spelling of the page placement is settled in Step 08 (ADR-002/schema). The validator (Step 09) blocks `<layout>` on page containers and grid/pack placements on their children.
- Spec: `docs/specs/core-model.md` §6–7.
