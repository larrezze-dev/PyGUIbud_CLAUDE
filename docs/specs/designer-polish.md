# Spec — Step 14p: designer visual polish

- **Status:** Accepted (user approved all defaults D1–D14, 2026-10-09) · **Date:** 2026-10-09 · **ADR:** ADR-012 (Accepted)
- **Owner:** FRONTEND · **Reviewer:** SOFTWARE-ARCHITECT · **Budget:** ≈ 800 production lines, cap 900 (§8)

## 0. Scope fence
**In:**
- SAPÉ tokens applied consistently to the canvas stage, the embedded window chrome, the selection colours and the drop indicators.
- Panel headers, padding and a type scale.
- Inspector rows, sections and editor states.
- A small, consistent icon set for the toolbar, the palette, the object tree and the canvas tabs.
- QA-14a1-17: the path column of the recovery dialog.

**Out (Step 14b):** pixel resize by dragging, window or component resize on the canvas, tree drag-and-drop and external include rendering. The resize **handles keep their current geometry and behaviour** (D7).

**Hard constraints:**
- No changes to the model, the `.ui` format, the validator, the runtime or codegen. No task touches `core/`, `backends/`, `pyguibud_runtime/`, `codegen/`, `uic.py` or `cli.py`.
- The parity tests must stay green: `tests/codegen/test_parity.py` and `tests/designer/test_canvas_engine.py`.
- **Rule S (the real risk).** ttkbootstrap has one `Style` per process, and the canvas renders the user's widgets in the designer theme (designer-shell §4.2, D4). Configuring a base style (`TButton`, `TLabel`, `TFrame`, `TEntry`, `Treeview`, …) or a Tk named font (`TkDefaultFont`, `TkHeadingFont`, `TkTextFont`, `TkFixedFont`) therefore restyles the user's widgets, and the parity tests would **not** notice, because both sides build under the same style. So:
  - polish styles only **designer-owned names**, `Designer.*` (the `Designer.Treeview` precedent, `theme_tk.py:96`);
  - fonts are **designer-owned named fonts** (`PyGUIbud*`);
  - no new `option_add` globs.
  - Two existing leaks are kept, not extended: `option_add("*Listbox/*Text/*Menu…")` (`theme_tk.py:69-78`) and `Fonts.set_global_family` (`theme_tk.py:116`).
- **Style-name rule:** a designer style name must not contain a ttkbootstrap bootstyle keyword (`primary`, `secondary`, `success`, `info`, `warning`, `danger`, `light`, `dark`, `inverse`, `outline`, `link`, `ghost`, `round`, `square`, `striped`, `toolbutton`). ttkbootstrap parses style strings, and such a keyword would trigger its builder.

## 1. Current-state audit (what looks primitive)
| # | Where | Finding |
|---|---|---|
| A1 | `shell.py:317-330` | The toolbar is 3 plain text `ttk.Button`s (New/Open/Save) with `padx=2`. It has no icons, no grouping, no Undo/Redo or clipboard buttons, no tooltips and no separator from the panes. |
| A2 | `shell.py:166-173` | The status bar is a bare frame with `padding=(6, 2)`. It has no divider, and the findings summary has no severity cue except its text. |
| A3 | `panels/base.py:44-45` | The panel heading is a plain `TLabel`, the same weight and colour as the content. It has no header band or divider, and its padding is ad hoc (`padx=6, pady=(4, 2)`). |
| A4 | `panels/focus.py:20-32`, `base.py:84` | An unfocused panel border is painted in `bg`, so it is invisible and the panes run into each other. Only the focused panel shows an edge. |
| A5 | `panels/canvas.py:421, 434, 622` | The stage and the scroll host use `bg`, and so does the embedded window frame (user `TFrame`). The window has no visible edge and floats on the same colour as the stage. |
| A6 | `panels/canvas.py:436-441` | The caption is a bold `TkHeadingFont` label plus a kind label, `sticky="w"`. It does not read as a title bar and has no kind icon. The menu strip (`:506-529`) has no bar background and no divider. |
| A7 | `panels/canvas.py:492-501` | The "cannot draw" card is two bare labels with no error colour or icon. The empty state (`:96`) is a bare centred label. |
| A8 | `canvas/overlay.py:186-195, 300` | Denied targets use raw `danger`. For neutral-dark `#B3261E` on `#14171C` this is ≈ 2.8:1, **below the 3:1 non-text minimum** (verify with `contrast()`). The pack/page insertion bar is a bare 3 px bar with no end caps. |
| A9 | `panels/inspector.py:163-165, 225` | Section headers are only bold text (`Section.TLabel`), with no band or divider. Rows use `pady=1` and the label column has no minimum width, so the editors do not line up between sections. |
| A10 | `panels/inspector.py:429-431` | The `Invalid.*` foreground and border use raw `danger`. On SAPÉ-dark `inputbg #15181D` this is ≈ 3.4:1, **below AA 4.5:1** for text (verify with `contrast()`). Invalid is shown by **colour only** (ACCESSIBILITY.md: never colour alone). |
| A11 | `panels/editors.py:102-105` | The read-only state is `disabled`: text cannot be selected or copied, and it looks the same as "not applicable". There is no visible read-only cue in the rows (only the header text, `inspector.py:208-213`). |
| A12 | `panels/inspector.py:179, 199-202` | `(mixed)` is a muted label in column 9 next to the editor. That is acceptable, but it is not styled as a state. |
| A13 | `panels/inspector.py:182` | The reset button is a `↺` glyph in `Reset.TButton`. Its rendering depends on the font, and it has no icon. |
| A14 | `panels/palette.py:112-121`, `panels/tree.py:151-159` | The rows are text only. There are no class or node-kind icons, and category rows look like items. |
| A15 | `panels/canvas.py:396` | The canvas tabs show the window id only, with no kind cue. |
| A16 | `dialogs/recovery.py:51-54` | **QA-14a1-17:** `show="tree"`, so the `path` and `time` columns have **no headings**. The path column has a fixed `2.6i` width with no stretch and no eliding, so a long path loses its file name at the clipped end, and an unsaved entry shows an empty cell. |
| A17 | all panels | There are no shared spacing or type tokens: paddings are literals (`6, 4, 2, 12`), and only `_STAGE_PAD` is scaled. |
| A18 | whole designer | No icons exist (only the app icon, `app.py:804`). |

## 2. Design tokens (`theme.py`, pure)
**D1 = (a), recommended:** derive everything from the existing 16 `Colors` + `focus`, using `_mix` and `readable`. `sape.json`, its schema and `gen_themes.py` stay unchanged, and forks need nothing. **(b)** would add an optional `"ui": {…}` block to `sape.json`, emitted from `color.border.subtle`, `color.surface.raised` and `color.text.secondary`, with derivation as the fallback (a regenerated file plus an updated drift test). It gives higher brand fidelity for about 40 more lines.

`readable()` gains `minimum: float = TEXT_CONTRAST`, so non-text uses 3.0.

| Token | Rule (role-independent unless noted) | SAPÉ source it stands for | Gate (test, all 6 specs) |
|---|---|---|---|
| `stage` | `_mix(bg, fg, k)`, k = 0.06 light / 0.10 dark / 0.0 hc | — (workspace backdrop) | `border` vs `stage` ≥ 3.0 |
| `plate_border` | `border` | `color.border.control` | ≥ 3.0 vs `stage` |
| `titlebar` | `_mix(bg, primary, 0.08)`; hc: `bg` | tint of `color.action.primary` | `titlebar_fg` on it ≥ 4.5 |
| `titlebar_fg` | `fg` | `color.text.primary` | (as above) |
| `header` | `light` | `color.background.subtle` | `fg` on it ≥ 4.5 |
| `divider` | `_mix(bg, border, 0.45)`; hc: `border` | ≈ `color.border.subtle` | none: decorative, never the only cue |
| `muted` | `readable(secondary, TEXT_SURFACES, inputfg)`. `tag_colours()` is left unchanged for the tree tags. | `color.text.secondary` | ≥ 4.5 on each of `TEXT_SURFACES` |
| `error_text` | `readable(danger, TEXT_SURFACES, fg)` | `color.semantic.error.text` | ≥ 4.5 on each |
| `error_border` | `readable(danger, (inputbg, bg, stage), fg, minimum=3.0)` | `color.border.error` | ≥ 3.0 on each |
| `readonly_bg` | `light` | `color.background.subtle` | `inputfg` on it ≥ 4.5 |
| `icon` | `fg` | `color.text.primary` | ≥ 4.5 on `bg`, `header` |
| `icon_disabled` | `_mix(fg, bg, 0.55)` | `color.border.disabled` | none (disabled is exempt; the state is also shown by `disabled`) |
| `target_allowed` | `readable(primary, (bg, stage, titlebar), fg, minimum=3.0)` | `color.action.primary` | ≥ 3.0 on each. Neutral-dark raw `primary` vs a 10 % stage is ≈ 2.5:1, so the derivation is required (verify with `contrast()`). |
| `target_denied` | `error_border` | `color.border.error` | ≥ 3.0 vs `bg`, `stage` (+ dashed + `X_cursor`) |
| `ring` | `readable(focus, (bg, stage, titlebar, selectbg), fg, minimum=3.0)` | `color.border.focus` | ≥ 3.0 on each. It is used by the overlay selection, the rubber band and `FocusFrame`. |

`TEXT_SURFACES = (bg, inputbg, selectbg, header, titlebar, readonly_bg)`, every surface a designer label is painted on. Every text token is derived with `readable()` against all of them, so a gate can never fail without a fallback. Test 1 (§9) also iterates the *configured* `Designer.*` styles, so the table cannot drift from what is painted.

`SPACE = {"xs": 2, "s": 4, "m": 8, "l": 12, "xl": 16}` is in px at 96 dpi (`spacing.1`–`.4`, plus a 2 px hairline). Every use goes through `theme_tk.scaled()`.

**Type scale (D6 = relative, recommended).** Named fonts are derived from `TkDefaultFont.actual()` in **points**, so Tk scaling handles HiDPI. Tk has only normal and bold, so the brand's "medium" maps to bold.

| Named font | Size | Weight | Used by |
|---|---|---|---|
| `PyGUIbudTitle` | base + 2 pt | bold | canvas title bar |
| `PyGUIbudHeader` | base | bold | panel headers, inspector sections, palette categories |
| `PyGUIbudBody` | base | normal | rows (alias of base; it exists so a later change touches one place) |
| `PyGUIbudCaption` | base − 1 pt (min 7) | normal | kind label, status summary, `(mixed)`, recovery location line |

The fonts are re-derived after `apply_fonts()` on every theme switch. The brand sizes (label 14 px, body 16 px) are web density. This designer is a dense desktop tool, so the deviation is deliberate (D6 (b) would use the brand px sizes).

## 3. Styling layer (`theme_tk.py`)
`apply_designer_styles(root, spec)` is called by `use_theme()` after `apply_theme()`, on **every** switch, because `style.configure` applies to the current theme only. It configures:

| Style | Settings |
|---|---|
| `Designer.Header.TFrame` / `.TLabel` | background `header`; label fg `fg`, font `PyGUIbudHeader`, padding (`l`, `s`) |
| `Designer.Divider.TFrame` | background `divider` (1 px rows/columns) |
| `Designer.Stage.TFrame` | background `stage` |
| `Designer.Titlebar.TFrame` / `.TLabel` | background `titlebar`, fg `titlebar_fg`, font `PyGUIbudTitle` |
| `Designer.Caption.TLabel` | background `titlebar`, fg `muted`, font `PyGUIbudCaption` |
| `Designer.Strip.TLabel` | background `bg`, fg `fg`, padding (`m`, `xs`) |
| `Designer.Section.TLabel` | background `header`, font `PyGUIbudHeader`, padding (`s`, `xs`) |
| `Designer.Muted.TLabel` | fg `muted`, font `PyGUIbudCaption` |
| `Designer.Error.TLabel` | fg `error_text` |
| `Designer.TEntry` / `Designer.TSpinbox` | map `fieldbackground` `[("readonly", readonly_bg)]`. The editors switch to these, and the user's `TEntry` is untouched. **Not** the combobox: `_Choice` uses `state="readonly"` as its *normal* state (`editors.py:201`, also `variables.py:92`), so a read-only combobox is `disabled` instead. |
| `Designer.Invalid.TEntry` / `.TSpinbox` / `.TCombobox` / `.TLabel` | fg `error_text`, bordercolor `error_border`; the same readonly map is repeated. ttk resolves `Designer.Invalid.TEntry` → `Invalid.TEntry` → `TEntry`, **never** via `Designer.TEntry`. |
| `Designer.Treeview` | `rowheight = icon px + scaled(6)` (exists; extended) |

- The existing `Section.TLabel`, `Muted.TLabel` and `Reset.TButton` are renamed into `Designer.*`, and `editors.INVALID` becomes `"Designer.Invalid"` (D14). The users of the old names are:
  - `inspector.py:68-69, 429-431`;
  - `dialogs/text.py:69` and `dialogs/rename.py:43` (`Invalid.TLabel`);
  - the tests `tests/designer/test_inspector_gui.py:97,103` and `test_qa12_abuse.py:62`.

  All of these belong to Task B.
- **Editors keep their own normal style:** `Editor.style` is set to `"Designer.TEntry"` or `"Designer.TSpinbox"` at creation. `set_invalid()` toggles between `f"{INVALID}.{base}"` and `self.style`, never back to `winfo_class()` (today `editors.py:99-100` restores the bare `TEntry`).
- The toolbar uses ttkbootstrap's **`ghost` button builder** (`builders/button.py:295`), which is not reconfigured. It is the builder's own output, identical for a user `tb:bootstyle="ghost"`.

## 4. Component targets
**Toolbar (`shell.py`)**
- Groups: New · Open · Save | Undo · Redo | Cut · Copy · Paste · Delete (D4). Add `toolbar=True` and `icon="…"` to these `ActionDef`s, with `ActionDef.icon: str = ""` as a new field. Groups follow the menu groups (a new group = a `ttk.Separator(orient="vertical")`).
- Buttons are **icon-only** ghost buttons (D3). A disabled image is mapped with `image=(normal, "disabled", grey)`.
- Each button has a `ToolTip` (`ttkbootstrap.widgets.tooltip`) showing "Save (Ctrl+S)". The text comes from the **new msgid** `N_("{action} ({shortcut})")` (Translators: {action} is a menu label, {shortcut} a key such as Ctrl+S), never from concatenation. Without a shortcut, the tooltip is the bare label. It is refreshed in `retranslate_toolbar()`.
- Keyboard focus also posts the label to the status bar (the existing reset-button pattern, `inspector.py:186`).
- A 1 px `Designer.Divider` sits under the bar.

**Status bar:** a 1 px divider on top, padding (`m`, `xs`). The summary gets a severity icon: error, else warning, else ok (`compound="left"`), and the text stays.

**Panels (`panels/base.py`, `focus.py`):**
- The heading becomes a `Designer.Header.TFrame` band holding a `Designer.Header.TLabel`, with a 1 px divider below. The same band is used for every panel (palette, tree, variables, inspector).
- `FocusFrame` `plain` = `divider` (D10). Panes get a subtle edge, and focus stays a 2 px `focus` ring, so it differs by both thickness and colour.

**Canvas stage (`panels/canvas.py`)** (D5)
- The scroll host and the stage use `stage` / `Designer.Stage.TFrame`.
- New **plate**: a `tk.Frame` that is a **direct child of `stage`**, gridded at rows 0–2 (`rowspan=3`, `sticky="nsew"`), with `highlightthickness=1` in `plate_border` and background `titlebar`.
  - It is created **first** in `_new_stage`, so the caption, strip and card start above it.
  - The canvas calls `plate.lower()` after `stage.overlay.sink(view.frame)` and again after `_show_card`. The plate is then beneath the window frame and every overlay strip, which keeps the §3 stacking invariant of `dnd-selection.md`.
  - It is bound like the other chrome (`_selector(window)` and `<MouseWheel>`, `canvas.py:448-450`), so a click on its edge selects the window.
  - `Overlay` and `engine.build(host=stage)` are unchanged.
- Caption → title bar: a `Designer.Titlebar.TFrame` with `sticky="ew"`, holding the kind icon, the title (`PyGUIbudTitle`) and the kind (`Designer.Caption.TLabel`), with padding (`m`, `s`).
- The menu strip uses `Designer.Strip.TLabel` labels on a `bg` bar spanning the width, with a 1 px divider below.
- The window frame is gridded with `padx=1, pady=(0, 1)` inside the plate edge. **Its content is untouched.**
- Error card: an error icon plus `Designer.Error.TLabel` reason and a muted count, on `header` with a 1 px `error_border` edge.
- Empty state (`self.empty`): the app icon (if present) plus "New (Ctrl+N)" and "Open (Ctrl+O)" hints, using the same `{action} ({shortcut})` msgid, in `Designer.Muted`.
- The notebook tabs get a window-kind icon (`compound="left"`).

**Overlay (`canvas/overlay.py`)**
- Colours come from `design_tokens()`: denied → `target_denied`; allowed → `target_allowed`; selection outer ring, rubber band and `FocusFrame` ring → `ring`; grid lines and empty outlines → `border` (unchanged, 3:1 pinned).
- The pack/page insertion bar gets end caps: two perpendicular strips, 1 px × `scaled(9)`, so a bar is never mistaken for a selection edge.
- **The handles are unchanged (D7):** 14b owns them.

**Inspector (`panels/inspector.py`, `editors.py`)**
- Sections: a full-width `Designer.Section.TLabel` band, `pady=(m, xs)` above. The first section has no top gap.
- Rows: `pady=xs`. The label column has `minsize` = the max measured label width of the rendered rows (`tkfont.measure`), capped at 45 % of the form width. It is never a fixed char count (`en_XA` +40 %). Labels are left-aligned.
- Editor states:

| State | Look | Non-colour cue |
|---|---|---|
| normal | `Designer.TEntry` etc. (= theme look) | — |
| focus | the ttkbootstrap focus border plus the panel ring | ring |
| invalid | `Designer.Invalid.*` (`error_text` / `error_border`) | an **alert icon** in the editor frame (column 8) and the reason in the status bar (exists) |
| mixed | `(mixed)` in `Designer.Muted` (caption font) next to the empty editor | text |
| default | label in `Designer.Muted`; reset disabled | reset state |
| read-only | `state=["readonly"]` for entries and spinboxes (text selectable and copyable, `readonly_bg`); combobox, checkbutton and buttons `disabled`; header banner with a **lock icon** (D9) | banner + icon |
| disabled | ttk `disabled` (theme grey) | state |

- The reset button gets the `reset` icon instead of `↺`. Its tooltip uses the existing msgid "Reset to default".
- Findings: the existing "Error: …" text lines, each with its severity icon (`compound="left"`).

**Palette and tree (`palette.py`, `tree.py`, `variables.py`)**
- Item `image=` comes from `present/icons.py` (pure): `class_icon(name, registry)` and `node_icon(node)`. A plugin widget gets its `fallback` class icon, else `puzzle`.
- Category rows use tag `category` → font `PyGUIbudHeader`, with no icon.
- The tree keeps its severity text column. Error rows keep `error_text`.

**Recovery dialog (QA-14a1-17; D11 states the assumed meaning)**
- `show="tree headings"`. Headings: "Name", "Location" and "Saved" (3 new msgids, 8 locales).
- The path column has `stretch=True`. The shown text is `elide_middle(path, n)` (pure, `present/`), which keeps the drive and the file name. An unsaved entry shows "(not saved)" (new msgid) in muted.
- A `Designer.Muted` caption line under the list shows the full path of the selected entry, `N_("Location: {path}")` with `wraplength`, so nothing is lost to eliding.
- **New msgids in this step (6):** "Name", "Location", "Saved", "(not saved)", "{action} ({shortcut})" and "Location: {path}". All 8 locales are needed, plus `en_XA`.

## 5. Icons (ADR-012)
**D2 = (a), recommended: Tabler Icons (MIT, © Paweł Kuna).**
- Rasterised **at dev time** by `tools/gen_icons.py` into 8-bit **alpha masks** at 16/20/24/32 px. It uses a dev-only SVG rasteriser; the candidate is a resvg binding. Task A must verify its PyPI name, licence and Windows wheels before adding it to the dev group. A rasteriser that needs a system DLL (e.g. cairo) is rejected.
- Stored in `src/pyguibud/designer/icons/icons.json`: `{"_licence", "sizes", "icons": {name: {size: base64(zlib(alpha))}}}`, about 40 KB. A `--check` drift test is skipped when the tool or SVGs are absent.
- **At runtime,** pure `icons.py` encodes a mask plus the tint colour into PNG bytes (zlib, filter 0, built row by row; no per-pixel Tk calls).
- `icons_tk.py` turns the bytes into `tkinter.PhotoImage(data=…)`, which Tk 8.6 supports natively. There is no new runtime dependency.
- `NOTICE.md` §4 gains the Tabler MIT notice, and `icons/LICENSE-tabler.txt` is copied in.
- Alternatives:
  - (b) an own geometry set (lines, rects and circles on a 16-unit grid) rasterised at runtime with 4× supersampling. It has no third-party content and gives exact any-scale output, but costs +≈ 130 runtime lines and gives lower fidelity, which is the very complaint this step answers.
  - (c) Lucide (ISC), same pipeline as (a).

Pure `designer/icons.py` (no Tk), budget ≈ 60:
- `ICON_SIZES = (16, 20, 24, 32)`.
- `pick_size(base_px, factor) -> int`: the nearest size ≥ `base_px * factor`, else the largest.
- `load_masks() -> Mapping[str, Mapping[int, bytes]]`: validated with ≤ 256 KiB, known sizes and `len == size²`. A defect is logged once, `{}` is returned, and the designer shows text only (as `theme.py` does).
- `tinted_png(mask, size, colour) -> bytes`.

Tk `designer/icons_tk.py`, budget ≈ 50:
- One `IconCache` per root (`icons(root)`, stored on the root and kept alive).
- `get(name, disabled=False) -> PhotoImage | None` creates each image **once** per (name, state). Missing → `None`, and the caller shows text.
- `retint(spec)` on a theme switch and `rescale()` on a scaling change use `image.configure(data=…)`, so the image names and widget references stay. The count from `image names` **never grows**: there are no images per canvas rebuild.
- Dark mode uses the same masks with a different tint (`icon` / `icon_disabled`).

Icon list (Tabler names are confirmed at copy time; the mapping lives in `gen_icons.py`):

| Group | Our name → Tabler |
|---|---|
| Toolbar (9) | `new`→file-plus, `open`→folder-open, `save`→device-floppy, `undo`→arrow-back-up, `redo`→arrow-forward-up, `cut`→scissors, `copy`→copy, `paste`→clipboard, `delete`→trash |
| Containers (5) | Frame→square, LabelFrame→box-margin, Notebook→layout-navbar, PanedWindow→layout-columns, ScrolledFrame→layout-sidebar-right |
| Widgets (15) | Label→letter-t, Button→click, Entry→forms, Text→align-left, Checkbutton→checkbox, Radiobutton→circle-dot, Combobox→selector, Spinbox→arrows-up-down, Scale→adjustments-horizontal, Progressbar→progress, Separator→separator-horizontal, Listbox→list, Treeview→list-tree, Scrollbar→arrows-vertical, Canvas→brush |
| Menus (5) | Menubar→menu-2, Menu→menu, Action→point, separator→separator, Statusbar→layout-bottombar |
| tb extensions (3) | Meter→gauge, Floodgauge→battery-2, DateEntry→calendar |
| Windows, other (5) | `window_main`→app-window, `window_dialog`→message-square, `window_component`→components, `include`→link, `puzzle`→puzzle |
| States (6) | `error`→alert-circle, `warning`→alert-triangle, `info`→info-circle, `ok`→circle-check, `lock`→lock, `reset`→restore |

That is 48 icons. HiDPI: `pick_size(16, factor)` for rows and the toolbar (20 for the toolbar at ≥ 1.25×). The `Designer.Treeview` row height follows.

## 6. Frozen API (coded against from day one)
```python
# theme.py (pure)
@dataclass(frozen=True, slots=True)
class DesignTokens: stage: str; plate_border: str; titlebar: str; titlebar_fg: str; header: str
    divider: str; muted: str; error_text: str; error_border: str; readonly_bg: str
    icon: str; icon_disabled: str; target_allowed: str; target_denied: str; ring: str
def design_tokens(spec: ThemeSpec) -> DesignTokens
def readable(colour, backgrounds, toward, minimum: float = TEXT_CONTRAST) -> str
SPACE: Final[Mapping[str, int]]
# theme_tk.py
STYLE_HEADER, STYLE_HEADER_LABEL, STYLE_DIVIDER, STYLE_STAGE, STYLE_TITLEBAR, STYLE_TITLE_LABEL,
STYLE_CAPTION, STYLE_STRIP, STYLE_SECTION, STYLE_MUTED, STYLE_ERROR, INVALID_PREFIX: Final[str]
FONT_TITLE, FONT_HEADER, FONT_BODY, FONT_CAPTION: Final[str]       # "PyGUIbudTitle", …
def apply_designer_styles(root: tkinter.Misc, spec: ThemeSpec) -> None
def space(root: tkinter.Misc, key: str) -> int                    # scaled(SPACE[key])
# icons.py (pure) / icons_tk.py
ICON_SIZES; def pick_size(base_px: int, factor: float) -> int; def load_masks(); def tinted_png(...)
def icons(root: tkinter.Misc) -> IconCache; IconCache.get(name, *, disabled=False) -> PhotoImage | None
# present/icons.py (pure)
def class_icon(class_name: str, registry: Registry) -> str; def node_icon(node: object) -> str
```

## 7. Implementation split (file ownership, no overlaps)
| Task | Owns | Content | Lines |
|---|---|---|---|
| **A: Foundation and shell** (runs first; it publishes the §6 API, stubs first) | `theme.py`, `theme_tk.py`, `icons.py`, `icons_tk.py`, `icons/` data, `actions.py`, `standard_actions.py`, `shell.py`, `tools/gen_icons.py` (dev), `NOTICE.md` §4 | tokens + gates, styles + fonts, icon pipeline, toolbar, status bar | ≈ 360 |
| **B: Panels and inspector** | `panels/base.py`, `focus.py`, `inspector.py`, `editors.py`, `events.py`, `palette.py`, `tree.py`, `variables.py`, `present/icons.py`, `present/` elide helper, `dialogs/recovery.py`, `dialogs/text.py`, `dialogs/rename.py`, `.po`/`.pot`, tests asserting the old style names | headers, rows/states, icons in lists, the D14 rename, QA-14a1-17 | ≈ 300 |
| **C: Canvas** | `panels/canvas.py`, `canvas/overlay.py` | stage, plate, title bar, strip, card, empty state, tab icons, indicator colours and caps | ≈ 140 |

- Two developers: dev 1 = A then C, dev 2 = B (starts against the §6 stubs).
- Integration order: A → B ∥ C.
- Nobody touches `core/`, `backends/`, `pyguibud_runtime/`, `codegen/`, `canvas/engine.py`, `render_plan.py` or `geometry.py`.

## 8. Budget
- **Estimate:** ≈ 800 production lines (A 360 + B 300 + C 140). **Expected with the recent ≈ 30 % overshoot:** ≈ 1,040. Cap **900** (D13).
- The trim list is pre-agreed and applied in order as soon as the running count projects past 900. It recovers ≈ 225.

| Trim | What is dropped | Lines |
|---|---|---|
| T1 | notebook tab icons | −15 |
| T2 | findings severity icons | −20 |
| T3 | insertion-bar end caps | −15 |
| T4 | empty-state hints | −20 |
| T5 | tooltips → status-bar label only | −20 |
| T6 | D9 read-only mode → keep `disabled` + lock banner | −30 |
| T7 | recovery full-path line (headings + elision stay) | −15 |
| T8 | status-bar severity icon | −15 |
| T9 | palette category font | −5 |
| T10 | D5 plate → flat stage colours only | −70 |

- Not counted: `tools/gen_icons.py` (≈ 90, dev), `icons.json` (data) and tests (≈ 500).

## 9. Test plan (headless unless noted)
1. **Token gates:**
   - pure (`test_theme.py`): every §2 gate for all 6 specs (SAPÉ ×3 + neutral ×3), and `readable(minimum=3.0)`;
   - Tk (`test_theme_tk.py`): under each theme, iterate every configured `Designer.*` style and assert `contrast(foreground, background) ≥ 4.5` wherever both are set (an inherited background counts as `bg`).
2. **Rule S** (`test_theme_tk.py`). On the shared root:
   - (i) baseline: install the themes; for each theme run `use_theme`'s base part (`apply_theme`, `apply_fonts`) and snapshot `style.configure(n)` and `style.map(n)` for every name in `DESIGNER_STYLES` plus `"ghost.TButton"`, and `nametofont(f).actual()` for `TkDefaultFont`, `TkHeadingFont`, `TkTextFont` and `TkFixedFont`;
   - (ii) build the full `Shell`, cycle all 3 themes twice (this runs every panel's `restyle()`) and snapshot again per theme;
   - assert (i) == (ii).
3. **Style-name rule:** no `STYLE_*` / `Designer.*` name contains a bootstyle keyword (§0).
4. **No hard-coded colours** (AST): scan `src/pyguibud/designer/**/*.py` for string constants that fullmatch `#[0-9A-Fa-f]{3}|#[0-9A-Fa-f]{6}` or a Tk colour name (`white`, `black`, `red`, `grey`/`gray`, …). Exempt `theme.py`, `themes/` and the arguments of `_()`/`N_()`/`NP_()` (the msgids at `properties.py:73-74`).
5. **Icons:**
   - `load_masks()` is valid, and every name used by `present/icons.py`, the toolbar `ActionDef.icon`s and the §5 state icons exists;
   - `pick_size` for factors 1.0/1.25/1.5/2.0;
   - `tinted_png` decodes with `PhotoImage` at every size, with the correct width and height;
   - a defective or missing file gives text-only and one log line;
   - a theme switch ×3 leaves `len(image names)` unchanged;
   - 100 canvas rebuilds leave it unchanged;
   - `Designer.Treeview` rowheight ≥ icon px + 4.
6. **Shell/panels:**
   - every toolbar button has an image and a tooltip equal to the translated label, and `retranslate` updates it;
   - the disabled image is mapped;
   - each panel header uses `STYLE_HEADER`;
   - `FocusFrame` plain = `divider`.
7. **Inspector:**
   - invalid → `Designer.Invalid.*` and the alert icon is visible;
   - read-only → entry state `readonly`, `selection_range` works, combobox `disabled`, lock banner;
   - mixed label shown;
   - label column `minsize` ≥ the widest label measured in `en_XA`.
8. **Canvas:**
   - the plate is a child of `stage` and below `view.frame` and all strips in `winfo_children` stacking order;
   - the overlay still hit-tests nothing (existing tests);
   - denied target colour = `target_denied`.
9. **Recovery:** headings are shown; `elide_middle` keeps the basename and drive (pure, property test); "(not saved)" appears for `path=None`; the full path label follows the selection.
10. **Parity/fences:**
    - `uv run pytest tests/codegen/test_parity.py tests/designer/test_canvas_engine.py -q` is green;
    - the orchestrator checks that `git diff --stat` is empty for `src/pyguibud/{core,backends,codegen}` and `src/pyguibud_runtime`;
    - full `uv run pytest -q`, `mypy` and `ruff` are clean;
    - `tools/gen_themes.py --check` is unchanged (D1 (a)).
11. **i18n:** the 6 new msgids (§4) are in the `.pot` and the 8 `.po` files, and the tooltip uses the `{action} ({shortcut})` msgid, not concatenation. The `en_XA` smoke test opens the designer with every panel, and no header or toolbar text is clipped (manual; the label-column test above covers the inspector).

## 10. UAT checklist (user)
Run `uv run pyguibud examples/…` (any multi-window file) and, separately, `uv run pyguibud --lang en_XA`. For **each** of View ▸ Theme ▸ Light / Dark / High contrast:
1. **Toolbar:** grouped icons; hovering shows "Save (Ctrl+S)"; Save and Undo grey out when unavailable; Tab reaches each button and the status bar names it.
2. **Panels:** each has a header band; the panes have visible thin edges; the focused panel has a clear 2 px ring.
3. **Canvas:** the window sits on a slightly different backdrop with a 1 px frame, a title bar (icon, title, kind) and the menu strip; the tabs show kind icons. **Your widgets look exactly as before.**
4. **Drag and drop:** drag a Button over a grid, a pack container and a full cell. Allowed is blue; denied is red, dashed, with the X cursor and a reason; pack bars have end caps.
5. **Palette and tree:** every widget and node has an icon; the category rows stand out; nothing is blurry at your display scaling.
6. **Inspector:**
   - sections are banded and the editors line up;
   - type an invalid width → red text and border, an alert icon, and the reason;
   - multi-select two Labels → `(mixed)`;
   - open a read-only file → lock banner, and you can still select and copy a value.
7. **Recovery:** create recovery data (spec 14a UAT), restart. The list has Name, Location and Saved headings; a long path keeps its file name; selecting a row shows the full path.
8. **`en_XA`:** no header, toolbar tooltip, inspector label or dialog heading is cut off.
9. Verdict: is the look acceptable in all 3 themes?

## 11. Decisions (recommended default in **bold**)
| # | Question | Options |
|---|---|---|
| D1 | Source of the extra tokens | **(a) derived from the 16 colours + focus, no `sape.json` change** · (b) optional `"ui"` block generated from the brand tokens |
| D2 | Icon set (includes approving the `NOTICE.md` §4 attribution) | **(a) Tabler Icons (MIT), dev-time masks, runtime tint** · (b) own geometry set rasterised at runtime · (c) Lucide (ISC) |
| D3 | Toolbar buttons | **icon-only + tooltip + status label on focus** (no `en_XA` overflow) · icon + text |
| D4 | Toolbar content | **9 actions in 3 groups** · keep New/Open/Save only |
| D5 | Canvas stage | **tinted backdrop + framed plate with title bar** · flat (colours only) |
| D6 | Type scale | **relative to `TkDefaultFont` in points (desktop density)** · brand px sizes (label 14, body 16) |
| D7 | Resize handles | **unchanged in 14p (14b redesigns them)** · restyle now |
| D8 | Invalid cue | **colour + border + alert icon + status reason** · colour + reason only |
| D9 | Read-only editors | **`readonly` (copyable) + lock banner** · keep `disabled` |
| D10 | Unfocused panel edge | **1 px `divider`** · invisible (current) |
| D11 | QA-14a1-17 meaning (assumed: no headings, clipped path, empty unsaved cell) | **headings + middle elision + full-path line + "(not saved)"** · headings only |
| D12 | ADR-012 | **accept as written** · amend |
| D13 | Budget (estimate 800, expected ≈ 1,040 with overshoot) | **cap 900 with trim list T1–T10 applied in order** · raise the cap to ≈ 1,050 |
| D14 | Rename existing `Section/Muted/Reset/Invalid` styles into `Designer.*` | **yes (one namespace; 4 one-line edits)** · leave |

## 12. Risks
- **R1:** ttkbootstrap `ghost` buttons may render differently across 2.x minors. Mitigation: a pinned ttkbootstrap range already exists; the Rule S test covers base styles only.
- **R2:** In SAPÉ-dark the selection fill is the light `primary`, so `fg`-tinted tree icons on a selected row are low-contrast. This is accepted: the icons are decorative and the row text carries the meaning (it meets 4.5:1 via `selection_colours`). No gate.
- **R3:** If the plate stacking is wrong, it hides the window or the strips. This is covered by test 8 and the UAT; fallback = flat stage (D5 (b)).
- **R4:** The Tabler names or licence must be verified at copy time; the licence file is copied verbatim.
- **R5:** The 30 % overshoot history: trim list §8.
- **R6:** The QA-14a1-17 meaning is inferred (only the plan line exists). D11 asks the user.
