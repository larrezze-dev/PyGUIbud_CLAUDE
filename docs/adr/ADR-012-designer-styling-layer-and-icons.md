# ADR-012 — Designer styling layer and icon pipeline

- **Status:** Accepted (2026-10-09) · **Date:** 2026-10-09 · **Step:** 14p · **Spec:** `docs/specs/designer-polish.md` (D1, D2, D14)

## Context
ttkbootstrap has one `Style` per process, and the canvas renders the user's widgets in the designer theme (ADR-009). Restyling a base ttk style or a Tk named font for the chrome would therefore silently change the rendered user widgets, and the parity tests cannot see it. The polish pass also needs:
- more colour roles than the 16 `Colors` (stage, header, divider, error border);
- a type scale;
- icons that recolour per theme and scale for HiDPI.

All of this must come without new runtime dependencies and without forks having to patch anything.

## Decision
- **Namespace:**
  - designer chrome styles only `Designer.*` ttk style names, which contain no bootstyle keyword, and the named fonts `PyGUIbudTitle`, `PyGUIbudHeader`, `PyGUIbudBody` and `PyGUIbudCaption`;
  - base styles, Tk named fonts and new `option_add` globs are off limits;
  - a headless snapshot test is the guard.
- **Tokens:** pure `theme.design_tokens(spec) -> DesignTokens` is derived from the 16 colours + `focus` via `_mix`/`readable`, with contrast gates in tests. `sape.json` and its schema are unchanged. Forks and the neutral themes get the same rules.
- **Icons:**
  - MIT Tabler Icons are rasterised at dev time (`tools/gen_icons.py`, dev-only rasteriser) into alpha masks at 16/20/24/32 px, in `designer/icons/icons.json`;
  - pure `icons.py` tints a mask into PNG bytes;
  - `icons_tk.IconCache` creates one `PhotoImage` per icon and state per root, and on a theme or scaling change re-tints it in place (`configure(data=…)`);
  - a missing or defective file falls back to text only.

## Consequences
- ➕ The user widgets on the canvas are provably untouched. Themes, forks and HiDPI need no extra assets, and the runtime gains no dependency.
- ➖ The brand's subtle tokens are approximated, not copied (option D1 (b) is to add a `"ui"` block later). The dev tool needs a dev-only SVG rasteriser (a resvg binding; name and licence are verified before adding it, and system-DLL rasterisers are rejected). The drift test skips without it.
- ➖ Third-party icon data ships in the wheel. Mitigation: the MIT notice goes in `NOTICE.md` §4 plus a copied `LICENSE-tabler.txt`.
