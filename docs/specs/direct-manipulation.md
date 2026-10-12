# Spec — Step 14b: direct-manipulation sizing and structure

- **Status:** Accepted (user, 2026-10-10: D1–D10 all defaults) · **Date:** 2026-10-10 · **ADR:** ADR-010 Addendum 4 (Accepted)
- **Owner:** FRONTEND (+ BACKEND review of the include resolver) · **Reviewer:** SOFTWARE-ARCHITECT
- **Budget:** ≈ 1,000 production lines, cap 1,250 over two halves (§0)
- **Origin:** 14a.2 UAT (2026-10-09): "still not possible to select and change a component's size". User decisions: widget size by dragging **and** window/component-window size on the canvas; plus the B1-trimmed 14a items (tree drag-and-drop, external `<include>` rendering).

## 0. Scope fence, budget and split
**In:**
- **A:** widget size by dragging handles (`width`/`height`/`length`). This amends Step 13 D2 "grid spans only".
- **B:** window and component-window size by dragging the plate edge (`min_width`/`min_height`).
- **C:** keyboard size steps and the status-bar feedback for A and B.
- **D:** object-tree drag-and-drop (FEATURES M1 remainder; base spec `properties-save-load.md` §13.1).
- **E:** rendering of `<include>` on the canvas, same-file (`src="#"`) and external (base spec §13.2).

**Out:** free pixel positions or `place` (ADR-005 stands); an initial-size attribute for windows (a format change, D3 option b); opening an included file from the canvas; resizing several selected nodes at once (the primary only); grid row/column `minsize` by dragging (the inspector already edits it); subtree rebuilds (Step 19).

**Hard constraints:**
- **No `.ui` format change and no `schema_version` bump** with the recommended defaults. Every value written already exists: `width`/`height`/`length` props and the `min_width`/`min_height` window attributes.
- **No change to `core/`, `backends/_tk.py`, `pyguibud_runtime/` or `codegen/`** with the recommended defaults. The only core exposure is reading: `core.files.DiskFiles`, `core.validate.validate(files=…)`, `core.xml_io.read_ui` and the `Instance` type from `backends.base`. `_tk._include` already expands an include whenever `id(node) in inst.includes`, so include rendering is designer-only (`render_plan.py`), with no parity risk.
- Options D2(b), D3(b) and D4(b) would touch core, runtime or codegen; they are marked as such.
- Opening a `.ui`, or a file it includes, never executes code: `handlers={}`, the hardened `read_ui`, no imports.

**Split (recommended, D9):** two halves, each one chat session with its own UAT (§13).

| Half | Contents | Estimate | Cap |
|---|---|---|---|
| **14b.1 "Resize"** | A + B + C, ADR-010 Addendum 4 (D2 and R-A parts) | ≈ 600 | 750 |
| **14b.2 "Structure"** | D + E, ADR-010 Addendum 4 (include parts) | ≈ 400 | 500 |

The estimates already include about 30 % of overshoot (recent steps ran 25–35 % over). The trim lists below are pre-agreed. They are applied in order as soon as a half's running count projects past its cap.

| Trim | Half | What is dropped | Lines |
|---|---|---|---|
| T1 | 14b.1 | double-click a handle to reset (the inspector's reset stays) | −25 |
| T2 | 14b.1 | the sticky/fill "stretched" hint text (the handle behaviour of §2.4 stays) | −20 |
| T3 | 14b.1 | keyboard steps for the window size (keyboard steps for widgets stay) | −20 |
| T4 | 14b.1 | the ghost snaps to unit multiples (it follows the pointer; the status bar shows the value) | −20 |
| T5 | 14b.2 | menu rows in tree drag-and-drop (Alt+Up/Down stays) | −40 |
| T6 | 14b.2 | auto-expand of a collapsed row on hover | −20 |
| T7 | 14b.2 | tree auto-scroll near the edges | −20 |
| T8 | 14b.2 | View ▸ Reload included files (the focus-in refresh stays) | −20 |

Not counted: tests (≈ 900 across both halves), `.po` updates.

## 1. Module layout (ownership)
| File | Change | Half |
|---|---|---|
| `designer/sizing.py` (new, **pure**) | `SIZE_AXES` table, `size_axes()`, `drag_size()`, `size_command()`, `reset_size_command()`, `window_size_command()`, unit labels | 1 |
| `designer/editing.py` | unchanged API; `resize_command` keeps the span path | — |
| `designer/canvas/overlay.py` | size/span handle variants, window plate handles, the ghost outline, the include outline (R-E) | 1, 2 |
| `designer/canvas/drag.py` | `press_size()`, `press_window_size()`; the existing `press_resize()` stays for spans | 1 |
| `designer/canvas/engine.py` | R-A precedence (§2.6); a node filter for included subtrees (§6.3); `metrics(node)` → unit pitch | 1, 2 |
| `designer/panels/canvas.py` | handle semantics per node, window selection handles, placeholder reasons | 1, 2 |
| `designer/edit.py` + `standard_actions.py` | keyboard size actions (§4) | 1 |
| `designer/panels/tree.py` (+ `designer/tree_dnd.py`, pure targets) | drag-and-drop (§5) | 2 |
| `designer/render_plan.py` | include resolver (§6) | 2 |

`PURE_MODULES` gains `sizing` and `tree_dnd`. The boundary test is unchanged.

## 2. Widget size by dragging (A)
### 2.1 Which classes and axes (`sizing.SIZE_AXES`, from `core/widgets.py`)
| Class | Horizontal axis | Vertical axis | Unit |
|---|---|---|---|
| Frame, LabelFrame | `width` | `height` | px (**only while empty**, §2.5) |
| Notebook | `width` | `height` | px (the pane area) |
| ScrolledFrame | — | `height` | px |
| Canvas | `width` | `height` | px |
| Scale, Progressbar | `length` if `orient` = horizontal | `length` if `orient` = vertical | px |
| Label, Button, Entry, Combobox, Spinbox | `width` | — | characters |
| Text | `width` | `height` | characters × lines |
| Listbox, Treeview | — | `height` | rows |
| Checkbutton, Radiobutton, Separator, Scrollbar, PanedWindow, Include | — | — | no size handles |

- **Extension classes (`tb:` and plugins)** get no size handles in 14b. Their sizes stay editable in the inspector. A unit hint in `PropertyDef` is D8.
- `size_axes(node, spec) -> tuple[Axis | None, Axis | None]`, where `Axis = (prop, unit)` and unit is `"px" | "chars" | "lines" | "rows"`. Only properties that the node's registry spec actually declares count.

### 2.2 Handles: size and span coexist (D1)
**Recommended (D1 = a):** the 8 handles of the primary selection mean **size** wherever an axis has a size property.
- **Size handles** are filled squares, as today.
- **Span handles** (grid children only) are hollow squares: a 2 px `primary` ring on a `bg` fill. A grid child's handle is a span handle when its axis has no size property. Example: the top and bottom handles of a Button. **Ctrl** held at the press turns any handle of a grid child into a span handle for that drag.
- **Shape plus cursor plus status text**, so colour is never the only cue. Hovering a handle (`<Enter>`) shows the status text:
  - `Drag to change the width. Hold Ctrl to change the cells it spans.`
  - `Drag to change the cells it spans.`
- Left and top size handles change the same property as the right and bottom ones. A widget has no position, so dragging the left edge to the left makes it wider. Under grid with Ctrl, the left/top span semantics are unchanged (13b §8).
- **Corners:** a corner is a size handle only when both of its axes are size axes. Otherwise it is a span corner under grid (13b behaviour), and it is hidden for a pack child. A corner gesture never mixes a property and a placement edit.
- **Stretched axes under grid** (§2.4) behave like axes without a size property: hollow span handles, so the 13b span handles never disappear.
- A pack child shows size handles only. A page child shows none (D6). A node with no size axis and no grid cell shows none.

### 2.3 Units, measuring and rounding (honest about Tk)
- **Pixels.** A Tk integer size is screen pixels, so the designer writes what it measures. **`scaled()` is never applied to user values**; it is only for chrome. Pixel values snap to multiples of 4 px; holding Shift during the drag gives 1 px.
- **Characters, lines and rows** come from the canvas widget's real font metrics:
  - characters: `tkinter.font.Font(font=…).measure("0")`;
  - lines: `metrics("linespace")`;
  - Treeview rows: `ttk.Style().lookup("Treeview", "rowheight")`, falling back to the line space.

  The font comes from `cget("font")` for tk widgets, otherwise from the style lookup, otherwise `TkDefaultFont`. `engine.metrics(node) -> (x_pitch, y_pitch)` provides them.
- **Pure arithmetic:** `drag_size(start_value, start_px, pointer_delta, pitch, *, snap, minimum=1, maximum=10_000) -> int`. The result is `start_value + round(delta / pitch)` for units, or the snapped pixel size, clamped to the range. The property's `PropertyDef.minimum` and `maximum` stay the authority (the guard re-checks them).
- **Start value.**
  - If the property is set, it is the start value.
  - If it is unset (natural size), the start is an **estimate**: `round(current_px / pitch)` for units, or the current pixels. The first drag can land one or two units away from what the eye expects (ttk adds padding, and TButton has a theme minimum of about 11 characters). The status bar shows the exact value that will be written before release, and the rebuild after release shows the truth.
- **Back to natural size.** Dragging back to, or past, the press position by more than half a unit, when the property was unset, writes nothing (`'{id}' keeps its natural size.`). Double-click on a size handle → `RemoveProp` for that axis (`Reset width`). A drag never writes `0`.
- **Text clipping is the runtime's behaviour:** a ttk Label narrower than its text is clipped. The canvas shows exactly that. It is not blocked.

### 2.4 Layout-manager interactions
| Parent layout | Effect of the size property | Designer rule |
|---|---|---|
| grid, sticky does not span both sides of the axis | the widget gets the requested size inside its cell | handle shown |
| grid, sticky has both `e`+`w` (or `n`+`s`) | the cell stretches the widget; the property is only a minimum | that axis gets **span** handles (hollow), because the cells are what size a stretched widget. Hover hint: `'{id}' fills its cell horizontally (Sticky): drag to change the cells it spans.` (T2) |
| pack, `fill` covers the axis | the same | that axis's size handle is hidden. Hint: `'{id}' fills its space (Fill), so its width follows the container.` |
| pack, `fill` = none | requested size | shown |
| pages (Notebook tab, PanedWindow pane) | the page container decides | no handles (D6) |
| `place` | does not exist (ADR-005) | — |

The designer never edits sticky or fill as a side effect of a size drag.

### 2.5 Containers with children (D2)
Tk geometry propagation makes a Frame or LabelFrame **with managed children** ignore `width`/`height` (`src/` never calls `*_propagate(False)`). Dragging would write a dead value, so:
- **Recommended (D2 = a):** such a container shows no size handles. Hover hint: `A frame with contents takes the size of its contents. Use the column and row weights, Sticky or Fill to make it larger.`
- ScrolledFrame, Notebook and Canvas honour their sizes with children, so they keep their handles.
- **D2 (b)** would add a core property ("Keep size", `propagate=false`): registry + runtime + codegen + parity, and `schema_version` 1.1 under ADR-002 (older readers open such files read-only).

### 2.6 The R-A design affordance (ADR-010 Addendum 4)
Today the engine sets 120×64 px on every empty container (`engine.py:177`), which overrides a user's `width`/`height`. **New precedence, per axis:** a set size property wins. The engine configures `max(value, 16 px scaled)`, a design-only geometry floor that keeps tiny containers hittable; it is never written to the document. R-A applies only to an axis whose property is unset.

### 2.7 The gesture and its command
- **Press** on a size handle: `break_merge()`, measure the metrics, freeze the start rect.
- **Motion:** the overlay ghost (the rubber-band layer, 1 px `focus` strips) shows the new rect snapped to whole units. The status bar shows `Release to set the width of '{id}' to {value}.` The value is formatted with `ngettext` per unit (§9). A size drag runs **no `execute` and no `check()` during motion**, so there is no rebuild per pixel. A span drag (hollow handle or Ctrl) keeps 13b's live `check()` for collisions.
- **Release:** one `Macro(_("Resize"), [SetProp(node, prop, str(value)), …])`, with one or two axes for a corner. It goes through `CommandStack.execute`. A guard rejection posts its reason, and nothing changes. A release with no change records nothing.
- **Esc** or a release off the stage cancels (`Drag cancelled.`), as in 13b.
- **One gesture = one undo step.**

## 3. Window and component-window size (B)
- **Selecting the window** (click on the plate, the title bar or the empty body; existing) shows **3 handles**: right edge, bottom edge and the bottom-right corner of the plate. There is no left or top handle, because a window has no position on the canvas.
- **What is written (D3 = a):** `min_width` and `min_height`, the existing window attributes. At runtime they are `Toplevel.minsize()`, so the window opens at least that large and cannot be made smaller. **They set a floor, not a fixed size**, and the window still grows to fit its contents. The canvas already honours them (`panels/canvas.py:465–466`: stage column 0 and row 2 `minsize`, i.e. excluding the title bar and the menu strip; the same convention is kept).
- **Below the contents (D5 = a):** releasing at or below the window's natural content size on an axis clears that attribute (`None` = automatic): `'{id}' is as small as its contents allow; the minimum width was cleared.` Otherwise the value is the pointer extent snapped to 4 px (Shift: 1 px), clamped to `MAX_PIXELS` (10,000).
- **Command:** one `Macro(_("Resize window"), [SetField(window, "min_width", v), SetField(window, "min_height", h)])`, with only the changed fields. One gesture = one undo step. Double-click a window handle → clear that axis (T1).
- **Component windows (D4 = a):** the same handles and attributes. The runtime and codegen expand a component into a `Frame` (`_tk.py:384`), where `min_width`/`min_height` have no effect. In a component they are therefore a **design-time preview size**:
  - the inspector labels them `Preview width` and `Preview height` for `kind="component"`;
  - the status bar says once per gesture: `A component takes its size from the window that includes it; this size is for the canvas only.`

  No validator rule is added, because the attributes are already valid on every kind.
- Dialogs and main windows behave identically.

## 4. Keyboard access (C)
| Keys (canvas scope) | Action id | Effect |
|---|---|---|
| Shift+Arrows | existing `wider`/`narrower`/`taller`/`shorter` | grid span ±1 (unchanged) |
| Ctrl+Shift+Right / Left | `size_wider` / `size_narrower` | width ±1 unit (1 character, or 4 px for pixel sizes) |
| Ctrl+Shift+Down / Up | `size_taller` / `size_shorter` | height ±1 unit |

- With a window selected, the same keys change `min_width`/`min_height` by 8 px, starting from the shown size (T3).
- A key step uses a bare `SetProp`/`SetField`, so consecutive steps on the same owner and property **merge into one undo step**: `SetProp.merge` (`commands.py:483`) matches the owner and the property name. The canvas must call `break_merge()` on every selection change and before every gesture, so that unrelated steps never merge. The implementer verifies `SetField.merge` (`:579`) for the window attributes. If it does not merge per field, each window key step is its own undo step, as 13b arrow moves are.
- A step from unset uses the start estimate (§2.3). A step that would cross 1 unit downwards is refused: `'{id}' cannot be narrower.`
- If the axis is hidden (§2.4/§2.5) or has no size property, the status bar gives the same reason as the hover hint. Nothing changes.
- The cheat sheet lists the new actions with their scope. Labels: `Increase width`, `Decrease width`, `Increase height`, `Decrease height`.

## 5. Object-tree drag-and-drop (D)
**Base:** `properties-save-load.md` §13.1 stays normative (drop zones of 25 % / 50 % / 25 %, `drop-target`/`drop-denied` tags, Esc and outside release cancel, the moved nodes stay selected). Refinements:
- **The same path as the canvas.** `tree_dnd.target(document, row_node, zone, payload) -> Target | str` (pure) produces the same `Target` values that `targets.hit_test` produces. The drop then calls the same `editing.move_command` (with reparent and placement conversion), `check()` on target change (60 ms rest, cached per drag) and `execute` on release. There is no tree-only command builder.
  - **into** a grid container → the `keyboard_target` first free cell;
  - **before/after** a grid sibling → *orchestrator ruling 2026-10-10 (QA-14b2-12), replacing the "first free cell, else a new row" fallback:* the dropped node takes the sibling's cell ("before") or the next cell past the sibling in reading order over the columns in use ("after"); the block's top-left corner goes there. Children in the way move down one row at a time, nearest first and spans whole, each stopping at the first free rows (the cell the moved node left counts as free), so in a one-column grid "c before b" lands above b and "b before a" lands at the top. A block that already sits just before the sibling is "already there". The node also moves next to the sibling in the tree order (the Alt+Up/Down reorder). Everything is one `Macro`, one undo step. A push past the last grid row (`MAX_GRID_INDEX`) is the only refusal: `That would put an element outside the grid.` Signalled by a grid `Target` with an `index` (the sibling gap); the canvas never sets one.
- **Payload:** the tree selection. Multi-node drags follow 13b §8 (same parent; the anchor is the primary). One `Macro`, all or nothing. *Orchestrator ruling 2026-10-10 (QA-14b2-05):* on a tree drop into a grid, the **top-left corner of the selected block** goes to the target's free cell (grid sources keep their relative offsets; pack/page sources are offset by rank), so no node lands on a negative cell.
- **Refused drops (with a reason, no change):**
  - onto itself or a descendant;
  - **into** a leaf or an Include row (before/after it is allowed);
  - a widget into a menu, or a menu/action into a widget container;
  - a window row as a payload (windows are not reordered in 14b);
  - **across windows** (D7 = a): `Elements cannot be dragged to another window. Use Cut and Paste.`
- **Keyboard equivalent:** Alt+Up/Down (existing) reorders; reparenting by keyboard uses Cut and Paste. Nothing new.
- Auto-expand of a collapsed container after a 700 ms hover (T6); auto-scroll in a 16 px (scaled) band at the top and bottom edges (T7); menu rows (T5).

## 6. Include rendering (E)
### 6.1 Resolver (`render_plan.py`, designer-only)
`design_plan(..., path: Path | None)` populates `top.includes[id(include)]` with child `Instance`s, mirroring the runtime's `_expand` (`_load.py:226`) without importing it (ADR-007 boundary, R9 of the 14a spec).
- **`src="#"`** resolves to the open document, whose component window is used directly. This works for untitled documents too.
- **External `src`:**
  1. `DiskFiles(session.path, root_result)`, where `root_result` wraps the **current** session document, never the `ReadResult` from opening. `DiskFiles.read(root)` returns it, so a cycle back to this file by path sees the edited tree. Then `resolve(key, src)` and `read(key)`. Relative paths resolve against the **including** file's folder (nested includes against theirs).
  2. Before expanding, the include rules run: `validate(document, registry, files=DiskFiles)`, filtered to the R49–R53 and R82 findings anchored on include nodes. Any finding for an include → a placeholder with that finding's translated text.
  3. Defence in depth, even after validation: a depth counter (`MAX_INCLUDE_DEPTH`), a visited set per path (cycles), and a node budget (`MAX_EXPANDED_NODES`). Exceeding one → placeholder.
- **Placeholder cases (the existing card, now with a reason line):**

| Case | Reason shown |
|---|---|
| untitled document with an external `src` | `Save the document to show included files.` |
| missing, unreadable or not a file; UNC/device path (R82); newer MAJOR, oversized (> 10 MiB), too deep or invalid `.ui` (`XmlIoError`) | the validator's or reader's translated message |
| not a component (R51), cycle (R52), limits (R53) | the validator message |
| a factory exception while building | the existing error card |

- **A newer MINOR included file** renders. `read_ui` returns it read-only, as the runtime uses it (parity). Its outline caption adds `(newer format)`.
- **Images** inside an included document resolve against the included file (`probe_image(including_key, src)`), as at runtime.

### 6.2 Caching and refresh
- Parsed results are cached by `(realpath, mtime_ns, size)`. The include findings are cached by the open document's stack revision plus that set of stamps, so a rebuild with nothing changed does not re-validate (the ≈ 80 ms guard cost on large documents).
- **Refresh:**
  - on application `<FocusIn>`, the stamps are re-read and only windows whose includes changed are rebuilt;
  - after Save As (the base folder changed) and after an untitled document is first saved;
  - View ▸ Reload included files (T8).

### 6.3 Read-only display and selection
- **Node filter.** The engine records `on_node` only for nodes in the window's own `walk()` (plus its menubar and status bar), by identity. With `src="#"`, the included widgets are the **same objects** as the component tab's nodes. Without the filter, the identity map would collide and the included widgets would become selectable.
- Included widgets keep the design bindtags. Hit-testing resolves them to the nearest recorded ancestor, the `Include` node, which behaves as a **leaf**: it can be selected, moved, deleted and pasted, but nothing can be dropped into it.
- **R-E `include-outline` (new design affordance):** a 1 px dashed outline in `border`. It is a drawing, like R-D, with no geometry change.
- **Status bar on selection:** `'{id}' shows '{component}' from {file} (read-only). Edit that file to change it.` For `src="#"`, `{file}` is `this document`.
- The tree shows the include as one row (unchanged). Its children are not listed.

## 7. Status-bar feedback (summary)
| Moment | Message |
|---|---|
| hover a handle | §2.2 texts; hidden-axis hints §2.4/§2.5 |
| during a size drag | `Release to set the width of '{id}' to {value}.` / `… height …` / `Release to set the size of '{id}' to {width} × {height}.` |
| during a window drag | `Release to set the minimum size of '{id}' to {width} × {height} px.` |
| after release | `Resized '{id}'.` / the guard's reason / `'{id}' keeps its natural size.` |
| tree drag | the 13b `Release to move …` texts / the refusal reason |

## 8. Performance budgets
| Operation | Budget |
|---|---|
| handle motion (ghost + status) | ≤ 5 ms per event, with no Tk rebuild |
| size release → rebuilt window, 200 widgets | ≤ 250 ms (the existing render budget) |
| tree hover target + cached `check()` | ≤ 100 ms on 2,000 widgets, 1 call per target change |
| include resolve, cache hit | ≤ 2 ms per include |
| include resolve, cold, 10 files / 1,000 widgets | ≤ 400 ms (marked `slow`) |
| focus-in stamp check, 32 files | ≤ 10 ms |
| designer Tk tests added per half | ≤ 6 s |

## 9. i18n (en-GB msgids; `_()`/`N_()`/`ngettext`; named placeholders; no concatenation)
- **Units**, one plural form per unit with `{count}`: `{count} pixel`/`{count} pixels`, `{count} character`/`{count} characters`, `{count} line`/`{count} lines`, `{count} row`/`{count} rows`. The `{value}` of §7 is one of these formatted strings.
- **Commands and actions:** `Resize`, `Resize window`, `Reset width`, `Reset height`, `Increase width`, `Decrease width`, `Increase height`, `Decrease height`, `Reload included files`.
- **Labels:** `Preview width`, `Preview height`.
- **Messages:** every message in §§2–7, plus `'{id}' cannot be narrower.` / `'{id}' cannot be shorter.`, `Elements cannot be dragged to another window. Use Cut and Paste.`, `Save the document to show included files.`, `(newer format)`, `this document`.
- **Gates:** all 8 locales; `en_XA` truncation check on the status bar and the cheat sheet. Translator comments name the placeholders.

## 10. Test strategy
**Pure (fast, hypothesis):**
- `sizing.drag_size`: monotonic in the delta; clamped to [1, 10,000]; units round half away from the press; pixel snap 4/1.
- `size_axes`: the full §2.1 table against the registry. Extensions → none. Scale/Progressbar follow `orient`.
- The stretched-axis rule for every sticky and fill combination.
- `window_size_command`: clear below natural; only the changed fields; clamping.
- `tree_dnd.target`: zone → `Target` equals what `hit_test` gives for the same intent; descendants, cross-window and leaf "into" refused.
- **Resolver:** `src="#"`, external, nested (2 levels), cycle, missing, untitled, UNC, newer MAJOR, newer MINOR, the node budget. Cache hits and misses by stamp.

**Tk (`@pytest.mark.gui`, shared root):**
- **Drag:**
  - a Button's right handle moved by `3 × pitch` → `width` = start + 3, in one undo step;
  - an empty Frame's corner → `width` and `height` set, and R-A no longer overrides them;
  - a Frame with a child → no size handles;
  - sticky `ew` → hollow e/w span handles;
  - a Button corner under grid → span corner;
  - Ctrl+drag on a grid child → span;
  - double-click → `RemoveProp`.
- **Existing 13b handle tests** press without Ctrl on Buttons, Labels or Entries, so under D1 (a) they would now write `width`. They are updated mechanically: add the Ctrl state, or use a class with no size axis such as Checkbutton.
- **Window:** the corner drag writes both attributes in one undo step; dragging inside the content clears them; a component window shows the `Preview` labels.
- **Keyboard:** Ctrl+Shift+Right ×3 = one merged undo step; Shift+Right is still span.
- **Tree:** synthetic press/motion/release on rows; reorder, reparent into a Frame, denied into a Button (tag + status reason), Esc cancels.
- **Includes:** the external include renders its widgets; clicking an included widget selects the Include node; the outline is present; touching the file plus a focus-in rebuilds; a placeholder for each failure case shows its reason.
- **Parity:** an example with an external include — `build_embedded(design_plan(...))` vs `load_ui` give the same widget description inside the include frame (§4 of the 13 spec).
- **Leaks:** 50 resize/rebuild cycles leave `winfo_children`, `image names` and `bind_class` unchanged.

## 11. QA abuse list (must be blocked gracefully)
| # | Abuse | Required behaviour |
|---|---|---|
| Q1 | Drag a size handle far off-screen or to a negative size | Clamped to 1 unit / 10,000; never `0`; status shows the value |
| Q2 | Drag a handle while the document is read-only | No handles in read-only (`command.read_only` is the safety net) |
| Q3 | Resize, then Esc mid-drag; resize, then lose focus (Alt+Tab) | Cancelled, nothing recorded |
| Q4 | Ctrl+drag on a pack child | Size semantics (no span exists); no crash |
| Q5 | Hold Ctrl+Shift+Right for 5 s | Clamped at 10,000; one undo step; no rebuild storm (rebuilds coalesced `after_idle`) |
| Q6 | Window corner dragged to 50,000 px | Clamped to 10,000 |
| Q7 | Include of itself by path, of a sibling that includes back, 9 levels deep, 33 files | Placeholders with the R52/R53 reasons; designer responsive |
| Q8 | Include of a 50 MiB file, a binary file, a `.ui` with `schema_version="9.0"`, `\\server\share\x.ui` | Placeholder, never opened over the network |
| Q9 | Included file replaced while the designer is open; deleted; made unreadable | Focus-in → re-render or placeholder; no traceback |
| Q10 | Drag a tree row into its own child; a menu into a Frame; a widget into another window | Refused with a reason |
| Q11 | Drop an Include into an Include; select an included inner widget and press Delete | Refused / deletes the whole Include (one undo step) |
| Q12 | Resize while a palette drag is active (two pointers via a touchpad) | The second gesture is ignored until the first ends |
| Q13 | `en_XA` and `de_DE` | Hover hints and drag texts fit the status bar (elided with the full text on hover, as today) |

## 12. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | The unit estimate from natural size feels off by one or two units | Exact value in the status bar before release; rebuild shows the truth; test tolerance ±2 |
| R2 | One `Style` means the canvas measures character pitch in the designer theme, not the document theme | Accepted (ADR-009 D4); Step 15 preview shows the real theme |
| R3 | Ctrl+click on macOS is a right click | Accept Command (`Mod1`) as the span modifier on macOS as well |
| R4 | Validating with `files=` on every rebuild is slow | Cached by revision + stamps (§6.2); only windows with external includes |
| R5 | `src="#"` identity collisions in the node map | The `walk()` identity filter (§6.3) plus a test that selects an included widget |
| R6 | Users expect a window minimum to be an exact size | Status text and docs say "minimum"; D3 (b) is recorded as the future option |
| R7 | Span-only (grid sticky) or hidden (pack fill) size axes look like "it still can't be resized" | Hollow vs filled handles; the hover hint names Sticky/Fill and where to change it; the defaults (`sticky=""`, `fill="none"`) never stretch |

## 13. UAT (for the user)
**14b.1 "Resize"** (`uv run pyguibud src/pyguibud/designer/templates/main_window.ui`):
1. Select a Button: its left/right handles are filled squares and top/bottom are hollow. Drag the right handle: the status bar shows "… to 14 characters"; release; Ctrl+Z restores it in one step.
2. Insert an empty Frame and drag its corner: it grows in both directions. Add a Label into it: its size handles disappear, and hovering explains why.
3. Ctrl+drag a grid widget's right handle: it spans one more column (as in 13b).
4. Set a widget's Sticky to `ew` in the inspector: its left/right handles become hollow (cells), and the hover hint names Sticky.
5. Select the window (click its title bar) and drag its bottom-right corner larger; then drag it smaller than its contents: the minimum is cleared. Each is one undo step.
6. Document ▸ Add component; resize it on its tab; the inspector shows Preview width/height.
7. Ctrl+Shift+Right three times on a Label, then Ctrl+Z once: all three are undone.
8. Save, close, reopen: identical sizes. Repeat steps 1 and 5 with `--lang en_XA`: no clipped hints.

**14b.2 "Structure":**
1. In the object tree, drag a row above a sibling (reorder), then into a Frame (reparent); drag a Frame into its own child: refused, with the reason in the status bar. Esc mid-drag cancels.
2. Ctrl+Z undoes each drop in one step.
3. Open `examples/…/with_include.ui` (provided by the step): the included component's widgets appear inside a dashed outline. Clicking any of them selects the whole include, and the status bar names the file.
4. Edit the included file in another designer instance, save it and come back: the canvas updates.
5. Rename the included file on disk and come back: a placeholder with a reason, no error dialog.
6. Save → reopen: identical.

## 14. Decisions (recommended default in **bold**) — **resolved 2026-10-10: all defaults (a)**
| ID | Question | Options |
|---|---|---|
| D1 | How size handles and grid-span handles coexist | **(a) size by default (filled squares); hollow = span where an axis has no size; Ctrl forces span** · (b) span by default, Ctrl = size (keeps 13b muscle memory) · (c) a toolbar mode toggle Size/Cells |
| D2 | Frame/LabelFrame **with children** (Tk ignores their width/height) | **(a) no size handles + hint; no core change** · (b) new core property "Keep size" (`propagate=false`): core + runtime + codegen, `schema_version` 1.1 |
| D3 | What the window drag writes | **(a) `min_width`/`min_height` (existing; a floor)** · (b) new `width`/`height` initial-size attributes (format change, schema 1.1; older versions open such files read-only) |
| D4 | Component-window size | **(a) the same attributes as a design-time preview size, labelled "Preview"; ignored at runtime** · (b) also applied at runtime to the include frame (runtime + codegen + parity) · (c) no component resize |
| D5 | Dragging a window smaller than its contents | **(a) clears the minimum (automatic)** · (b) clamps to the content size and keeps the value |
| D6 | Children of a Notebook or PanedWindow | **(a) no size handles (size the Notebook)** · (b) width/height handles on page Frames |
| D7 | Tree drag across windows | **(a) refused; use Cut and Paste** · (b) allowed as a cross-window reparent |
| D8 | Where units (px/chars/lines/rows) are defined | **(a) a designer-side table for core classes now; extensions get no size handles until Step 17** · (b) an optional `PropertyDef.unit` field now (plugin API, ADR-004 amendment) |
| D9 | Split | **(a) two halves, 14b.1 "Resize" then 14b.2 "Structure", each with its own UAT** · (b) one session |
| D10 | Budget | **(a) ≈ 1,000 lines, caps 750 + 500 with trims T1–T8 in order** · (b) raise the caps by 20 % instead of trimming |

## 15. Follow-ups after acceptance (orchestrator)
- `dnd-selection.md` §3/§8: point D2 to this spec.
- `FEATURES.md`: M1 tree drag-and-drop → 14b.2; size handles.
- `DEVELOPMENT_PLAN.md` row 14b: halves and UATs.
- `properties-save-load.md` §13: mark it as "delivered by 14b.2".
