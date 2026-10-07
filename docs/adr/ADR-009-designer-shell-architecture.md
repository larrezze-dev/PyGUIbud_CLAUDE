# ADR-009 — Designer shell architecture and theme provision

- **Status:** Accepted (user, 2026-10-06: D2 = A, D4 designer-only) · **Date:** 2026-10-06 · **Step:** 12 · **Spec:** `docs/specs/designer-shell.md`

## Context
The designer must stay testable headless, extensible by forks without core patches, and live-switchable for language and theme. ttkbootstrap 2.2 has three relevant traits:
- `Style` is a single process-wide singleton (`engine.py:61`), and a second live root raises (`window.py:69`).
- `Theme` families only produce `-light`/`-dark` names and re-ramp the anchor colours (`theme.py:752,884`).
- The `_tk.py` backend builds windows as `Toplevel`s when given a master, so it cannot render a document into a frame.

Brand tokens are all rights reserved (NOTICE §2).

## Decision
- **The views are thin Tk modules** (`designer/panels`, `shell`, `dialogs`). Logic lives in pure modules (`session`, `signals`, `actions`, `theme`, `present/*`) that never import Tk. The two sides communicate through `Signal` observers. Every model change goes through `CommandStack`; Step 12 only replaces documents.
- **One `ActionRegistry`** (id, label msgid with mnemonic, `core.keys` chord, handler, `enabled`/`checked` predicates) drives the menus, the toolbar, the key bindings and the cheat-sheet.
- **One i18n listener per app** retranslates the menus, then each panel's `retranslate()`, isolating failures.
- **Themes** are `ThemeDefinition` objects with exact `Colors`, registered on each root with `Style.register_theme`. The menu exposes *roles* (light/dark/high contrast). SAPÉ data comes from a generated `themes/sape.json` when present, else from built-in MIT neutral themes (`pyguibud-*`). Designer themes are chrome-only and are never written into `.ui`.
- **The canvas is a placeholder** until the Step 13 engine. The Step 15 preview runs out of process, which respects the single root.

## Consequences
- ➕ Presenters and actions are tested without a display. Forks drop the brand data with no code change. The focus ring and contrast are test-gated.
- ➖ `sape.json` (derived brand data) ships in the MIT wheel/sdist (user decision D2 = A). Mitigation: NOTICE §2 lists it as all rights reserved; neutral fallback for forks.
- ➖ The document theme cannot be shown inside the designer process. Mitigation: the Step 15 subprocess preview.
- Affected: Steps 13 (canvas body, DnD actions), 14 (settings store, file actions, `can_discard`), 15 (preview), 17 (diagnostics panel), 18 (all-locale mnemonic test).
