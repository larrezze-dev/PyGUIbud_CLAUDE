---
name: designer-ui
description: Conventions for the PyGUIbud ttkbootstrap designer UI (shell layout, SAPÉ theming, drag-and-drop, keyboard access, i18n wiring). Use when building or changing anything in the designer application.
---

# Designer UI conventions

## Shell
Main window = menubar · toolbar · **palette** (left) · **canvas** (centre) · **inspector** + **object tree** (right, PanedWindow) · statusbar. Tabs for multiple windows per `.ui`; panels for events, variables, menu editor and plugin diagnostics.

## Theming
- SAPÉ tokens in `assets/brand/tokens/` (light, dark, high-contrast) → ttkbootstrap custom themes `sape-light`, `sape-dark`, `sape-hc`. Read tokens at build time; never hard-code hex values in widgets.
- Key colours: primary `#1C3FF0` (hover `#122AD2`, active `#1026A6`), background `#F8FAFC`, surface `#FFFFFF`, text `#212832`. Fonts: IBM Plex Sans (UI), JetBrains Mono (code), with OS fallbacks because font files are not bundled.
- Follow `assets/brand/docs/ACCESSIBILITY.md` for contrast and focus visibility. Themes switch live.

## Interaction
- Drag-and-drop shows **insertion targets** (grid cells / pack slots), not pixel positions (ADR-005). An invalid drop shows the validator's reason in the status bar or a tooltip, and nothing changes.
- Every model change goes through a command (undo/redo). The UI never mutates the model directly.
- **Keyboard-only:** every action has a menu entry and, where sensible, a shortcut; there is a visible focus ring; Tab order is logical; the shortcut cheat-sheet is generated from the action registry.
- Destructive actions (close unsaved, delete a container with children) ask for confirmation.

## i18n
- All labels, menus, tooltips and messages use `_()`. The live language switch rebuilds text via a `retranslate()` hook per widget/panel instead of restarting.
- Leave about 40 % slack for German/Dutch: no fixed-width labels; test with `--lang en_XA`.

## Code
Views are thin. Logic lives in controllers/presenters that are testable without a display. One module per panel under `src/pyguibud/designer/`.
