# Spec — Step 13: canvas engine, drag-and-drop and selection

- **Status:** Accepted (user, 2026-10-06: all defaults, see §16) · **ADRs:** 003, 005, 006, 008, 009, **010** (Accepted)
- **UAT (plan row 13):** build a small form by dragging; move and resize widgets (§15).
- **Grounding:** `backends/_tk.py` (read in full), `backends/ttkbootstrap.py`, `pyguibud_runtime/_load.py:61-216`, `core/commands.py` (`InsertNode`, `MoveNode`, `reparent`, `check`, `_Busy`), `designer/session.py`, `panels/{canvas,palette,tree}.py`, `themes/sape.json`, `tests/codegen/test_parity.py`.
- **Decisions:** D1–D10 resolved by the user on 2026-10-06 — **all recommended defaults** (§16). Step 13 is split into **13a** and **13b**, each with its own UAT (§15).

## 0. Scope fence and budget
**In Step 13:**
- the canvas engine (`_tk.py` embed mode, design mode, overlay);
- the parity tests for embed mode;
- palette → canvas drag-and-drop with insertion targets and `check()` feedback;
- keyboard insertion (D7);
- selection: single, multi (D4), rubber band (D5), synced with the tree, inspector and status bar;
- move, reorder and reparent, plus grid span resize (D2), cell and slot snapping (D3);
- Edit ▸ Undo/Redo/Delete (D6);
- the QA-12-13 palette hint;
- the object-tree highlight;
- the mypy clean-up in `tests/` (plan §5).

**Not in Step 13:**
| Feature | Step |
|---|---|
| Property editors, events/variables panels, menu editor, copy/paste, open/save, settings store | 14 |
| Rendering external `<include>` files (they need a document path) | 14 |
| Document theme, translated preview | 15 (subprocess) |
| `tb:` attribute editing, plugin diagnostics | 17 |
| Subtree-only rebuild, scoped validation for faster hover | 19 (only if §13 budgets fail) |

**Budget:** ≤ 1,800 lines of production code, tests excluded. **Raised to ≤ 3,200 by the user at 13b kickoff (2026-10-07)**, so 13b ships in full, left/top handles included; the trim order below applies only beyond 3,200.
- `_tk.py` grows by ≤ 60 lines; every new line sits in an `if embed` branch or in a hook call.
- **Trim order if over budget:** (1) rubber band; (2) left/top resize handles (keep right/bottom/corner); (3) the cell-grid overlay during a drag; (4) multi-selection moves (keep multi-select delete).

**Sub-steps (D1 = B recommended):**
- **13a — "see and insert":** §§2–6, 9, 10, 11, with single selection. UAT 13a.
- **13b — "rearrange":** §§7–8, covering multi-select, rubber band, move and resize. UAT 13b.

## 1. Module layout and dependency rules
```
src/pyguibud/backends/_tk.py          + Embed hooks, embed branches (§2.1)           # no toolkit import (ADR-007)
src/pyguibud/backends/ttkbootstrap.py + TtkbootstrapBackend.build_embedded(plan, embed)
src/pyguibud_runtime/_load.py         load_ui P1-P7 split into private _prepare() (behaviour unchanged; ADR-007 boundary kept)
src/pyguibud/designer/
  render_plan.py   PURE  design_plan(document, window, registry) -> BuildPlan; RecordingScope
  geometry.py      PURE  Rect, ChildBox, ContainerBox, Snapshot; contains/intersects; grid line math
  targets.py       PURE  Payload, Target, hit_test(snapshot, x, y, payload) -> Target | None; keyboard_target()
  editing.py       PURE  unique_id, new_node, insert/move/resize/nudge/delete command builders, move_index
  session.py       PURE  Selection gains nodes/primary; select_many; prune on stack events
  present/status.py PURE + hint/selection-count/target texts
  theme.py         PURE  + selection_colours(spec)
  canvas/          Tk (new package)
    engine.py      CanvasEngine: one TkSession per window, node<->widget maps, rebuild, snapshot()
    design.py      apply_design_mode(widgets): design bindtag, takefocus; DESIGN_TAG handlers
    overlay.py     Overlay: selection outlines, handles, insertion indicator, rubber band, cell grid
    drag.py        DragController: palette drag, canvas move/resize/band state machine
  panels/canvas.py   Notebook tabs keep; tab body = scrollable stage (replaces the summary card)
  panels/palette.py  drag source, Enter/double-click insertion, click hint
  panels/tree.py     extended selection, keyboard reorder, Designer.Treeview style
  standard_actions.py + Edit menu (§11); actions.py + ActionDef.scope (§7.4)
```
- **Pure modules.** `render_plan`, `geometry`, `targets` and `editing` are pure. They join `PURE_MODULES` in `tests/designer/test_session.py` (subprocess, `tkinter` absent from `sys.modules`).
  - `render_plan` imports only `pyguibud.backends.base` (dataclasses and protocols, no toolkit) besides `core` and `i18n`.
- **Tk modules.** `canvas/*` and `panels/*` are Tk modules and are imported only from `DesignerApp`.
- **Boundaries.** `core`, `codegen` and `pyguibud_runtime` never import `designer` (the boundary test is unchanged). The designer imports `backends.ttkbootstrap` (allowed). The designer **never calls `load_ui`**: it is strict, needs handlers and paths, and refuses component-only files.

## 2. Canvas engine
### 2.1 Embed mode in `backends/_tk.py`
`TkSession(..., embed: Embed | None = None)`. With `embed=None` the behaviour is byte-for-byte what it is today: the existing parity tests guard it.
```python
@dataclass(frozen=True, slots=True)
class Embed:
    host: Any  # every window frame is created in it
    on_node: Callable[[object, Any, Any], None]  # (model node, outer widget, inner widget)
    on_title: Callable[[Window, str], None]  # the title slot's setter in embed mode
    placeholder: Callable[[Include, Any], Any]  # unexpanded include -> a widget in parent
```
| Runtime behaviour (`_tk.py`) | Embed mode |
|---|---|
| `_window`: `Toplevel(master=root)`, `withdraw()` (`:178-180`) | `classes["Frame"](embed.host)`, appended to `_created` (destroyed by `destroy()`) |
| title slot → `top.title(t)` (`:184`) | title slot → `embed.on_title(window, t)` (the canvas caption, §2.5) |
| `minsize`, `transient`, `protocol` (`:185-190`) | skipped (the stage shows `min_width`/`min_height`, §2.5) |
| `menubar`: `Menu(top)` + `top.configure(menu=bar)` (`:196-201`) | same `Menu(top)` tree **without** `configure(menu=)`; its entries feed the menubar strip (§2.5) |
| shortcut `top.bind(...)` (`:274`) | skipped (design mode never runs handlers) |
| `_apply_theme(root, owns)` (`:128`) | skipped (designer themes are chrome-only, ADR-009 D4; avoids `_M_THEME_IGNORED` on every rebuild) |
| `Notebook.enable_traversal()` (`:326`) | skipped: it binds Ctrl+Tab on `[winfo toplevel]`, i.e. the **designer root**, and would pile up on every rebuild (**verify** in `ttk/notebook.tcl` when implementing) |
| `main.deiconify()` (`:139`) | skipped (a Frame has none) |
| `show(id)` | no-op returning `None` |
| `_include` → `inst.include(node)` (`:348`) | if `id(node)` is not in `inst.includes` → `embed.placeholder(node, parent)` |
| every built node | `embed.on_node(node, outer, inner)`: windows (frame, body), widgets (`outer`=`widget.container` for ScrolledFrame, `inner`=widget), includes (frame, frame), statusbar (status frame, label) |

- **Lenient lookups.** These are embed-only and exist because the designer may show documents with errors (Step 14 opens files). The validated runtime never reaches them:
  - `self._images[(doc, ref)]` (`:131,250,342,392`) → missing key: no image option;
  - `vars[node.bind]` (`:398`) → missing: no variable;
  - `int(value)` for an int-bound Radiobutton (`:413`) → `ValueError`: keep the string.

  Any other exception aborts that window's build (§2.7).
- `TtkbootstrapBackend.build_embedded(plan, embed) -> TkSession` reuses the class table of `build()`. `make_root` raises (never called), and `apply_theme` is a no-op. The `Backend` protocol is unchanged; embedding is an optional capability, so `hasattr(backend, "build_embedded")` is the gate for future backends.
- **Codegen is untouched.** Embed mode exists only in `_tk.py`, and `_support.py` and generated modules do not change.

### 2.2 The design plan (`render_plan.py`, pure)
`design_plan(document, window, registry, *, log) -> BuildPlan`. It builds **one plan per window**, so one broken window never takes down the canvas, and an edit rebuilds only its window.
- `top = Instance(DocumentPlan(key="<designer>", path=Path(), document=document), windows=(window,), scope=RecordingScope())`. Every window kind is supported, components included.
- `handlers = {}`, so no user callable is ever wired and opening a `.ui` never executes code.
- `images = {}` in Step 13. Untitled documents have no folder; the lenient lookup draws no image. Step 14 fills the map from `DiskFiles` once documents have a path.
- `text = lambda slot: slot.prop.value` shows the source text. Translated preview is Step 15.
- `runtime_text = str`, `theme = ""`, and `log` goes to the designer logger (clipping, fallback and bootstyle notes).
- **Includes are left unexpanded** (`includes = {}`), so the placeholder is drawn. That is a `ttk.Labelframe` with `_("Included: {component}")` and a fixed 120 × 48 px minimum.
- `RecordingScope` implements `Scope` with no-ops. Identity mapping comes from `on_node`, never from ids: ids may be duplicate or empty in an invalid document.

### 2.3 Live widgets ↔ model nodes
`CanvasEngine` keeps, per window session:
- `outer: dict[int, Any]` — `id(node)` → the gridded or packed widget (for overlay geometry);
- `inner: dict[int, Any]` — `id(node)` → the widget that holds children (for drop coordinates);
- `owner: dict[str, object]` — `str(widget)` (Tk path) → node, for `outer` widgets and all their descendants up to the next registered node. Internal sub-widgets (ScrolledText parts, ScrolledFrame canvas) therefore map to their node;
- `node_of(widget) -> object | None` walks `winfo_parent` until a registered path or the stage.

The maps are rebuilt with the session. The keys are `id()` of live model nodes, and the session's selection holds the nodes themselves, so ids are never reused while they are referenced.

### 2.4 Design mode: widgets never react to input
`design.apply_design_mode(widget_paths)` runs after each build, over every descendant of the window frame. It is not in `_tk.py`, so parity below the body holds.
- `bindtags((DESIGN_TAG, "all"))`, with `DESIGN_TAG = "PyguibudDesign"`. This drops the class tag (ttk/Tk behaviour: pressing, typing, toggling, Combobox popdown, sash drag) and the instance tag (any binding `_tk.py` made). `<Configure>`/`<Map>` geometry is done by Tk itself, not by bindings.
  - **Verify:** ScrolledFrame relies on an instance `<Configure>` binding to size its inner frame. If it does, keep the instance tag on the ScrolledFrame's internal canvas only, and add a test.
- `takefocus=0` where the option exists, so Tab never enters the canvas widgets.
- `root.bind_class(DESIGN_TAG, seq, handler)` is called **once per app**, for `<ButtonPress-1>`, `<B1-Motion>`, `<ButtonRelease-1>`, `<Double-Button-1>`, `<ButtonPress-3>` (context menu: no-op in 13), `<Motion>`, `<MouseWheel>`/`<Button-4/5>` (forwarded to the stage scroll) and `<KeyPress>` (ignored). Every handler returns `"break"`.
- **Notebook tabs:** a click on a tab label of a canvas Notebook selects the tab via `nb.index(f"@{x},{y}")` and then selects the Notebook node. That is the only "live" behaviour.
- **Focus:** keyboard focus stays on the canvas panel's focus proxy (§7.4). Canvas widgets never take focus.

### 2.5 Stage and window chrome (`panels/canvas.py`)
Each Notebook tab body (one per window, unchanged from Step 12) is a scrollable stage:
```
tab ─ tk.Canvas (scroll host, xview/yview + ttk scrollbars)
       └ create_window → stage (ttk.Frame, origin 0,0)
            ├ caption   (ttk.Label: title from on_title, else id; + kind label)      [chrome]
            ├ menustrip (ttk.Frame of ttk.Labels, one per top-level menu entry)       [chrome]
            ├ window frame (from embed; contains body / status bar)                  [document]
            └ overlay strips and handles (place()-d, stacked at creation)           [chrome, §3]
```
- The window frame is gridded at `minsize = (min_width, min_height)` using `stage.grid_columnconfigure/rowconfigure(minsize=…)`. Otherwise it gets its natural requested size; windows never stretch to the tab.
- The **menubar strip** shows each entry `label` with its `underline` (from the hidden `Menu` tree). Clicking a strip label selects that `Menu` node; the menus never open.
- The status bar is the real embedded status frame, so a click selects the `Statusbar` node.
- **Chrome strings** go through `_()` and are retranslated on a language switch. **Document texts** are shown verbatim.

### 2.6 Rebuild strategy (recommended; not a user decision)
- **What triggers a rebuild:** a `StackEvent`, or `document_changed`. The window that is rebuilt is the one the command touches: `window_of(t)` for each `t` in `command.targets()`, else all windows. That window is marked stale.
- **Listeners only schedule.** A listener runs inside `_Busy` (`commands.py:1196`), so calling the stack from it raises `RuntimeError`. A rebuild is therefore one `after_idle` per burst, and the visible stale tab is rebuilt. Hidden stale tabs are rebuilt when they are shown.
- **Build off-screen, then swap.** The new window frame is built ungridded, then `update_idletasks()`, then gridded, then the old session's `destroy()` runs, then the design mode and the overlay are applied. This means no flicker.
- **Full window rebuild** is the v1 strategy. Subtree rebuild needs per-command knowledge in `_tk.py` and is deferred to Step 19, and only if the §13 budget fails.
- **The selection survives** because nodes are mutated in place. The session prunes detached nodes (§7.1).

### 2.7 Failure handling
A build exception for one window shows an error card in its tab instead: `_("This window cannot be drawn on the canvas: {reason}")`, plus the error count. The exception is logged with its traceback. The tree, inspector and other tabs keep working. The partially built frame is destroyed by `TkSession.build()`.

## 3. Overlay (`canvas/overlay.py`)
**Technique (recommended, ADR-010):** `place()`-d `tk.Frame` strips and handles, children of the **stage**, above the window frame in the stacking order.
- **Stacking (amended 14a.2, 2026-10-08):** a strip's stacking order is set once, when it is created: it goes just below the lowest strip of the layers above it (bottom to top: empty outlines, cell grid, selection, insertion target, handles, rubber band), and within a layer a later strip is above an earlier one. A redraw never restacks. After a rebuild, the new window frame (created on top) is lowered beneath every strip with one `lower()` (`Overlay.sink`). Raising every strip on every redraw was quadratic, because a Tk raise walks the sibling list. A redraw sends only the strips whose rect, colour or cursor changed to Tk.
- A child of the stage with a higher stacking order covers the whole subtree of the window frame, which is its sibling.
- Coordinates are `widget.winfo_rootx() - stage.winfo_rootx()` (and the same for y), read after `update_idletasks()`.

**Alternatives rejected:**
| Alternative | Why rejected |
|---|---|
| Canvas items on the scroll host | Tk draws embedded window items above every other canvas item, so the rectangles would be hidden |
| A transparent overlay `Toplevel` | `-transparentcolor` is Windows only, `-transparent` is macOS only, and X11 needs a compositor; focus and z-order also misbehave |
| A screenshot into an image | Needs Pillow or a screen grab |

**Elements:**
- **Selection outline:** 4 strips of 2 px (scaled) in `focus` around each selected node's `outer` rect, with a 1 px inner strip in `bg`. This two-tone outline is visible on any widget colour.
  - **Cap (amended 14a.2, 2026-10-08):** the primary is always outlined, plus the first `SELECTION_CAP` (16) other selected nodes in selection order. Each outline is 8 native windows, and mapping or hiding one costs about 1 ms on Windows, growing with the number of siblings. When more nodes are selected, the status bar says `{count} elements selected; only {shown} are outlined.` (ngettext). The selection itself, and every action on it, still covers every node.
- **Handles:** shown for the primary selection under grid only (D2). Up to 8 squares of 7 px (scaled), filled with `primary` and with a 1 px `bg` border. Cursors: `sb_h_double_arrow`, `sb_v_double_arrow`, `sizing`.
- **Insertion indicator:**
  - grid: a cell outline;
  - pack and pages: a 3 px bar across the container between two children;
  - container: an outline of the whole container.

  An **allowed** target is drawn in `primary`. A **denied** target is drawn in `danger` with a dashed look (alternating 6 px segments), plus the `X_cursor` cursor, plus the status-bar reason. Colour is never the only cue.
- **Cell grid (D3):** during a drag over a grid container, 1 px strips in `border` mark the column and row boundaries. They come from `grid_bbox`.
- **Rubber band:** 4 strips of 1 px in `focus`.

**Behaviour:**
- **Event isolation:** overlay frames are never in the `DESIGN_TAG` hit path. Hit-testing (§5) uses the pure snapshot, never `winfo_containing`, which would return the strips.
- **Updates:** the overlay is re-placed after a rebuild, on stage `<Configure>`, on selection change and on a theme change (colours re-read from the spec). Each update costs ≤ 5 ms.

## 4. Mandatory parity tests (`tests/codegen/test_parity.py`)
**Seam:** `pyguibud_runtime._load` splits P1–P7 of `load_ui` into a private `_prepare(path, handlers, *, strict, lang, localedir, translator) -> tuple[LoadedUi, BuildPlan]`. `load_ui` calls it, so its behaviour is unchanged. This is test-only use of a private name, the same pattern as `_tkmap`.

**New tests:**
| Test | Asserts |
|---|---|
| `test_embedded_build_matches_runtime[name]` (all 5 `NAMES`) | Builds `plan = _prepare(ui, Recorder)` with `build_embedded(plan, Embed(host=frame, …))` in the shared root. `_scope(embedded_ui)` equals `_scope(load_ui(...))` **exactly**: classes, options, geometry, tabs, panes, images and **widget bindings** (the same `Recorder` handlers). Includes are expanded here because the plan comes from `_prepare`. |
| `test_embedded_windows_match_runtime[name]` | Per window: the captured title (`on_title`) = `top.title()`; menubar entries `_menu(bar)` are equal; `descendants` is equal. Only the window-level keys in `EMBED_DEVIATIONS = ("minsize", "resizable", "bindings")` are excluded, and the test pins this tuple. |
| `test_embedded_retranslate_matches_runtime` | `hello` in `de_DE` after `retranslate`, compared as in `test_hello_after_retranslate_to_german` |
| `test_embed_creates_no_toplevel` | `root.winfo_children()` changes only under `host`. No `Toplevel` exists. `root.title()`, `root.cget("menu")` and `root.bind()` are unchanged, and so are `bind_class` of `TNotebook` and the root's bindtag sequences (catches `enable_traversal`). |
| `test_embed_rebuild_leaks_nothing` | 100 build/destroy cycles of `rich`: `root.winfo_children()`, `len(root.tk.call("image", "names"))` and `root.bind()` are unchanged |
| `test_embed_none_is_unchanged` | the existing `test_the_built_interfaces_are_equal` still passes (it runs `embed=None`) |

**Designer-side tests** (`tests/designer/test_canvas_engine.py`):
- After `apply_design_mode`, `_scope` descriptions differ from the embed-only build **only** in `takefocus`. `widget.bind()` lists a widget's own bindings whichever bindtags are active, so it does not change. A separate assertion checks `widget.bindtags() == (DESIGN_TAG, "all")` for every descendant.
  - `"all"` is kept only if it is needed. If the implementation finds no `all`-tag binding the canvas relies on, drop it: `(DESIGN_TAG,)`. That is safer, because the designer's own `bind_all` shortcuts then never fire from a canvas widget, which never has focus anyway.
- Synthetic `event_generate("<ButtonPress-1>")` / `<KeyPress-a>` on an Entry, Checkbutton, Combobox and Button inside the canvas changes no variable or text, posts no popdown and calls nothing.

**Rule (ADR-010):** any change to `_tk.py` embed branches or `Embed` must keep these tests green, and a new embed deviation needs an ADR addendum.

## 5. Insertion targets and hit-testing (pure: `geometry.py`, `targets.py`)
### 5.1 Snapshot
`CanvasEngine.snapshot() -> Snapshot` is taken after `update_idletasks()`. It is cached until the next rebuild, stage `<Configure>` or scroll.
```python
@dataclass(frozen=True, slots=True) class Rect: x: int; y: int; w: int; h: int     # stage coords
@dataclass(frozen=True, slots=True) class ChildBox: node: object; rect: Rect; placement: object
@dataclass(frozen=True, slots=True) class ContainerBox:
    node: object; rect: Rect; inner: Rect; kind: Literal["grid", "pack", "pages", "window"]
    orient: str; children: tuple[ChildBox, ...]; depth: int
    columns: tuple[int, ...]; rows: tuple[int, ...]      # grid boundary x / y (from grid_bbox), len = n+1
    tabs: tuple[Rect, ...]                               # Notebook tab label rects (identify/bbox)
@dataclass(frozen=True, slots=True) class Snapshot: containers: tuple[ContainerBox, ...]; leaves: tuple[ChildBox, ...]
```
**Empty grids:** a grid with no children has `columns = (x0, x1)` and `rows = (y0, y1)`. That is one virtual cell, (0,0), covering `inner`.

**Visibility (mandatory):**
- **Viewable boxes only.** A box enters the snapshot only if `winfo_viewable()` is true. Unmapped Notebook pages still report root coordinates, so a hidden tab's grid would otherwise win "deepest container".
- **Clipping.** Each `rect`/`inner` is intersected with the viewport of every ancestor ScrolledFrame; an empty intersection drops the box. Selection outlines follow the same rules, so unviewable or clipped-out nodes get no outline.
- **Pointer inside the visible canvas.** `hit_test` gets the scroll host's visible rect, in stage coordinates. A pointer outside it gives `None` (for example over the tree panel while the stage is wider than the view).
- **Hidden pages.** When the tree (or Tab) selects a node on a non-current Notebook page, the engine selects that page in the *rendered* Notebook. This is chrome state, not a model change.

### 5.2 `hit_test(snapshot, x, y, payload) -> Target | None`
```python
Payload = NewWidget(spec_name) | Moving(nodes: tuple[object, ...])
Target  = GridTarget(container, row, column) | SlotTarget(container, index) | PageTarget(container, index)
        | BarTarget(window, kind="menubar"|"statusbar")
```
1. **Pick the container.** Take the deepest `ContainerBox` whose `inner` contains (x, y).
   - **Edge band:** within 6 px (scaled) of a container's `rect` edge, its parent container is picked instead. This lets the user drop beside a nested frame.
   - **When moving:** the moving nodes and their descendants are never containers for the drop, so a node is never dropped into itself.
2. **Grid.**
   - `column` = the index *i* with `columns[i] ≤ x < columns[i+1]`.
   - Beyond the last boundary is the **append** column `n`, and the same holds for rows. The maximum is 9,998 (Tk's limit, `MAX_GRID_INDEX`).
   - An occupied cell (any child's span covers it) gives a `GridTarget` anyway: `check()` denies it with the validator's collision reason.
   - Exception: the cell is occupied only by the moving node itself. That is allowed (a no-op, or a span-preserving shift).
3. **Pack:** `index` = the number of children whose rect midpoint (x when `horizontal`, else y) is less than the pointer coordinate.
4. **Pages:**
   - Notebook: over the tab strip, `index` = the tab under or before the pointer; elsewhere in the body, the append index.
   - PanedWindow: as for pack, along its orient.
5. **Bars:**
   - A `Statusbar` payload gives a `BarTarget` on the window under the pointer.
   - A `Menubar` payload gives a `BarTarget` only on the menubar strip or the window.
   - `Menu`/`Action` payloads give `None`, with the reason `_M_MENU_EDITOR` (menus are edited in the menu editor).
6. **Nothing under the pointer.** Off-stage, caption or scrollbars → `None`, which means no target (neutral cursor, and the status bar says "Release to cancel").

**Gap index → `MoveNode` index (same parent):** `move_index(old, gap) = gap if gap <= old else gap - 1`. This matches `list.insert` after removal (`commands.py:411`). A hypothesis property checks it against a list model.

### 5.3 Turning a target into a command (`editing.py`, pure)
| Gesture | Command |
|---|---|
| new widget → `GridTarget`/`SlotTarget`/`PageTarget` | `InsertNode(container, node, index)`. `node.placement` is preset: `GridCell(row=, column=)`, `PackPlacement()`, or `PagePlacement(text=Prop("text", node.id, translatable=True))` (Notebook) / `PagePlacement()` (PanedWindow) |
| new Statusbar/Menubar → `BarTarget` | `SetField(window, "statusbar", Statusbar(id=…))` / `SetField(window, "menubar", Menubar())`; denied when one exists (reason `_M_BAR_EXISTS`) |
| move, same container, grid | `SetField(node, "placement", replace(cell, row=, column=))`, keeping the spans, sticky and padding |
| move, same container, pack/pages | `MoveNode(node, container, move_index(old, gap))` |
| move, other container | `reparent(node, container, index, placement)`. The placement is converted: grid→grid keeps sticky/pad and spans clipped to 1 if they collide; anything else gets the target kind's default placement |
| multi-move (D4) | `Macro(N_("Move elements"), [...])`. Grid applies the pointer's cell delta to every node; pack inserts the nodes contiguously in their current order |
| resize (D2) | `SetField(node, "placement", replace(cell, row, column, rowspan, columnspan))` |
| delete (D6) | `RemoveNode(node)` / `Macro(N_("Delete elements"), [...])`, in reverse document order |

**`new_node(spec, document) -> Widget`:**
- `class_name = spec.name`, with `fallback` and `plugin` taken from the spec for extensions.
- `id = unique_id(document, stem)`.
- If the spec has a translatable `text` property: `Prop("text", spec.display_name, translatable=True)`. That is the English msgid, untranslated: it is user content in `source_locale` en-GB.
- Layout containers get `layout = DEFAULT_LAYOUT` (`commands.py:86`), and page containers get none.

**`unique_id(document, stem) -> str`:**
- `stem` is the class local name in snake case (`labelframe`, `scrolled_frame`); for an extension, the prefix is dropped (`tb:Meter` → `meter`).
- Returns `f"{stem}{n}"` for the smallest *n* ≥ 1 that is not used anywhere in the one id namespace: windows, widgets, includes, menus, actions, statusbars, variables and resources.
- The result is guaranteed to match `^[A-Za-z][A-Za-z0-9_]{0,63}$`, to be outside `RESERVED_IDS`, and not to be a keyword. The stem is truncated to 58 chars.
- One `walk()` builds a set, so the cost is O(n).

**A drag reuses one `node` object.** Every hover check builds a fresh `InsertNode` around the same detached widget, which works because `revert()` detaches it. The id is computed once at drag start.

### 5.4 Reachable targets (Step 13a addendum; QA-13a-02/03/04)
This is an implementation clarification within **D3** (snap to cells and pack slots, no pixel grid), not a new decision. It changes neither the `.ui` nor codegen, runtime, `_tk.py` or `targets.py`. Everything here happens in `CanvasEngine` (`designer/canvas/engine.py`) **after** `build_embedded()` returns. The parity tests call `build_embedded()` directly (`tests/codegen/test_parity.py`), so they never see it. ADR-010 Addendum 2 pins the list.

**Rule R-A: minimum size of an empty container.**
- **Applies to:** every rendered `Window` or `Widget` with **no children** that is a layout container (`layout is not None`) or a page container (spec `children == "pages"`: Notebook, PanedWindow).
- **What it does:** the engine calls `inner.configure(width=scale(120), height=scale(64))`, where `inner` is the widget reported by `on_node`. For a Window, that is the body frame.
- **Errors:** a `TclError` is suppressed, as it is today.
- **Removal:** a Frame's children decide its size, so the minimum is gone once the first child arrives. A ttk Notebook or Panedwindow would keep honouring `width`/`height`, but every change rebuilds the whole window (§2.6), and the rebuilt container has children, so R-A no longer applies to it.

**Rule R-B: trailing append zone of a non-empty layout container.**
- **Applies to:** every rendered `Window` or `Widget` with `layout is not None` (grid **or** pack) and at least one child. Page containers are excluded.
- **What it does:** the engine adds `P = scale(20)` px to the **right and bottom** padding of `inner`:
  - read `cget("padding")` and normalise it to `(left, top, right, bottom)` (Tcl may return `''`, `'12'`, a 2-tuple or a 4-tuple);
  - then `configure(padding=(l, t, r + P, b + P))`.
- **Once per build, never cumulative:** each build starts from the plan's own padding, so building the same window twice gives the same rects.
- **Why padding and not an extra `minsize` row/column:** a configured empty row or column counts in `grid_size()`. It would add a boundary in `_grid_lines`, and the slack beyond it would map to column *n*+1, leaving an empty gap column.
- **Why it works without changes to `targets.py`:** points in the padding lie beyond the last grid boundary, so §5.2's existing rule yields the append column *n* / row *n*. In a pack container they lie past the last child's midpoint, so they yield the append gap.
- **Invariant P ≥ band + 12:** a nested container's outer 6 px band still belongs to its parent (§5.2), so at least 14 px (scaled) of the zone always pick the container itself.

**Rule R-C: append pane of a non-empty PanedWindow (QA-13a-03 reopened; ADR-010 Addendum 2, `paned-append-pane`).** A ttk Panedwindow has no `padding` and hands any extra size to its last pane, so instead of R-B the engine adds a trailing empty `ttk.Frame` pane of `P` px along the orient axis (`weight=0`; the last real pane gets `weight=1` when all real weights are 0, so it keeps the slack as at runtime), and `_map_owners` runs after it so a press on it selects the PanedWindow.

**Rule R-D: design-only outline of an empty container (QA-13a-14; user decision at 13b kickoff, 2026-10-07).**
- **Applies to:** the same nodes as R-A (empty layout or page containers, windows excluded), while they are **not** selected.
- **What it does:** the overlay draws a 1 px dashed rectangle (the theme's `border` colour when it reaches at least 3:1 against `bg` in all three themes per `theme.contrast()`, otherwise `fg`; drawn with the overlay's existing dashed-strip pool). Window bodies are excluded: the window chrome already frames them. `"empty-container-outline"` is appended to `DESIGN_AFFORDANCES` and its pin test is updated around the container's rect. It is redrawn with the other overlay items after every build and scroll.
- **Never** written to `.ui`, never seen by codegen, runtime, `_tk.py`, `targets.py` or the parity tests. It does not take hits: the overlay items stay non-interactive.
- **Acceptance:** an empty Frame dropped into a grid cell has a visible outline; it disappears once the Frame gets a child, and is replaced by the selection outline while selected.

**What is not added:**
- no pixel grid;
- no extra overlay drawing: the normal hover indicator (cell rect or slot bar) shows the zone;
- no change to selection outlines.

**Visible effect (acknowledged at UAT 13a):** non-empty containers and windows look up to 20 px larger on the canvas than at runtime. The Step 15 preview shows the true size.

**Acceptance (all `@pytest.mark.gui`, in `tests/designer/`):**
1. The QA xfails become plain passing tests, with the `xfail` marks removed:
   - `test_a_dropped_empty_container_can_be_dragged_into[Notebook]` and `[PanedWindow]`;
   - `test_a_frame_with_one_child_still_offers_a_free_cell_to_the_mouse`;
   - `test_the_empty_component_template_is_a_usable_drop_target`.
2. `main_window` with one child in the body: a point 10 px inside the body's right zone, at the child's row, gives (0, 1). A point in the bottom zone gives (1, 0). No point gives a column > *n* or a row > *n*.
3. A pack Frame whose only child is a Frame (fill both) offers the append slot (`index == 1`) to the mouse.
4. Building the same window twice gives identical snapshot rects (R-B is not cumulative).
5. After the first page is inserted into a Notebook, its pane follows the page's requested size, not 120×64.
6. `tests/codegen/test_parity.py` stays green, and there is no diff in `backends/_tk.py` or `designer/targets.py`.
7. 13b reuse: a `Moving` payload over a frame's zone gives the same append targets (no special case).

**Budget:** about 15–25 production lines, all in `engine.py` (`_reachable` widened, plus a padding helper).

## 6. Drag from the palette and drop feedback (`canvas/drag.py`)
**State machine** (pure transitions in `targets.py`, timers in Tk):
```
idle --press on palette widget item--> armed --motion > 4 px (scaled)--> dragging --release--> drop | cancel
dragging --Esc / focus out / release off-stage / document_changed--> cancel (nothing changes)
```
**Tracking the pointer:**
- The palette `Treeview` keeps the implicit pointer grab, so `<B1-Motion>` and `<ButtonRelease-1>` arrive there with `x_root`/`y_root`. These are converted to stage coordinates (`- stage.winfo_rootx()`) and then go to `hit_test`.
- Over the canvas tab the cursor is `plus`. Over a denied target it is `X_cursor`.
- There is no drag ghost window in Step 13.

**Hover checks (`check()`):**
- A target key is `(id(container), kind, row, column | index)`. The key is checked only when it changes **and** the pointer has rested on it for 60 ms (`after`, cancelled on the next change).
- **Results are cached per drag** in a dict keyed by target. The document cannot change during a drag; a `document_changed` signal cancels the drag.
- **While a check is pending**, the indicator is drawn neutral (`border` colour).
- **Accepted:** primary indicator. The status bar shows `_("Release to insert '{widget}' into '{container}'.")` (or the move/resize variant), plus the first new warning's message when there is one.
- **Rejected:** danger indicator plus `X_cursor`. The status bar shows `outcome.message`, the validator's translated reason. That covers occupied cells, a child in a non-container, a menu class, and read-only documents (`command.read_only`).
- **Cost:** a check costs about 75–80 ms on 2,000 widgets (plan §5, Step 09 notes), so only about one check per new target is run.
- **Calling context:** `check()` is never called from inside a stack listener (§2.6).

**Drop:**
- `outcome = stack.execute(command)` is a fresh run; the cached check result is never trusted.
- Accepted: the new or moved node is selected (`origin="canvas"`) and the status bar shows `_("Inserted '{id}'.")`. The rebuild follows via the `StackEvent`.
  - **Bars:** `SetField` attaches a **deep copy** of a menubar or statusbar (ADR-006). After a bar drop, select `window.statusbar` / `window.menubar`, never the constructed object, which `session.select()` would reject as foreign.
- Rejected: the reason is shown and nothing changes.
- **One gesture = one command = one undo step:** `stack.break_merge()` runs before the execute, so `SetField` merging never glues two drags together.

## 7. Selection
### 7.1 Model (`session.py`)
```python
@dataclass(frozen=True, slots=True)
class Selection:
    nodes: tuple[object, ...]        # document order is NOT implied; insertion order of the gesture
    origin: str                      # "tree" | "canvas" | "inspector" | "palette" | "session"
    @property
    def node(self) -> object | None: # compatibility: the primary (last added) node, or None
        return self.nodes[-1] if self.nodes else None
def select(self, node: object | None, *, origin: str) -> None          # unchanged signature
def select_many(self, nodes: Iterable[object], *, origin: str) -> None  # foreign nodes dropped; one walk
```
- **Constructor change.** Existing call sites that build `Selection(node, origin)` change to `Selection(() if node is None else (node,), origin)`. Always write `is None`, never truthiness: model nodes are objects whose truthiness must not matter. `__post_init__` raises `TypeError` when `nodes` is not a tuple, which catches old positional calls. The consumers are `panels/tree.py`, `panels/canvas.py`, `panels/inspector.py`, `shell.py` (status) and `tests/designer/*`. They keep reading `.node`.
- **Membership** is checked with **one** `walk()` that builds an identity set, capped at `_MAX_SELECT_WALK`. Today `_contains` walks once per node, which would be O(n·k).
- **Selection rules:**
  - multi-select holds only `Widget`/`Include` nodes of **one window**;
  - adding a node from another window, or a window or bar node, replaces the selection.
- **Pruning (new).** `_on_stack_event` drops selected nodes that are no longer in the document, which happens after undoing an insert or after a delete. If the selection changed, `selection_changed` is emitted (`origin="session"`). Today stale nodes stay selected.

### 7.2 Gestures
**Canvas:**
| Gesture | Effect |
|---|---|
| click | select one |
| Ctrl+click (Cmd on aqua) | toggle in the selection |
| Shift+click | add to the selection |
| click on empty stage | select the window |

**Rubber band (D5):** a press on a container's empty area followed by a drag of more than 4 px selects the **direct children of that container** whose rect lies **fully inside** the band. With Ctrl held, the band adds to the selection. A press-drag inside a container that is already selected moves the container; a band starts when the press is on a container that was not selected, on a window body (windows never move), or with Ctrl (Cmd on aqua) or Shift held (ruling QA-13b-06).

**Tree:** `selectmode="extended"`, with native Ctrl/Shift range selection. `<<TreeviewSelect>>` goes to `select_many`. Rows of another window, or window and bar rows, follow the rules of §7.1. The tree then re-renders its selection from the session, so it never disagrees with it.

**Sync:**
- **Status bar:** the path for one node; `ngettext("{count} element selected", "{count} elements selected", n)` for several.
- **Inspector:** the primary node, with a header line `_("{count} elements selected; showing '{id}'.")` when *n* > 1. Multi-edit is Step 14.
- **Canvas:** outlines for all selected nodes, and handles only for the primary.

### 7.3 Keyboard (the canvas focus proxy; D10)
The canvas panel's focusable widget is the scroll-host `tk.Canvas` (`takefocus=1`, F6 target). The focus ring stays the shell's FocusFrame.

| Key | Action |
|---|---|
| Tab / Shift+Tab | select the next / previous widget in document pre-order within the window (wraps), and scroll it into view |
| Enter | select the first child of a selected container |
| Esc | cancel the drag or band; else select the parent (window → stays) |
| Arrow keys | **move** the selection: grid cell ±1 (clamped at 0; collisions denied with the reason); pack/pages index ±1 along the orient (the cross-axis arrows do nothing and say why) |
| Shift+Arrow | grid only, primary node: rowspan/columnspan ±1 (min 1) |
| Delete | Edit ▸ Delete (§11) |
| Ctrl+A | select all children of the primary node's parent container |

- **Grid bound:** a keyboard move or span change may reach at most **one** row/column past the highest row/column used by the other children of that grid parent (the append cell, as the §5.4 append zone); beyond it the key is denied with the reason in the status bar, like the clamp at 0, and nothing is recorded (ruling QA-13b-02).
- **One key press = one command** (`break_merge()` first). Auto-repeat runs as separate commands, each validated, and a denial stops the motion with its reason.
- **Tree:** Alt+Up and Alt+Down reorder the selected node (`MoveNode`, same parent) with the same builders (D8).

### 7.4 Scoped shortcuts (`actions.py`)
The keys in §7.3 would clash with `Treeview` navigation if they were bound with `bind_all`. This amends the ADR-009 registry contract (recorded in ADR-010). `ActionDef` gains three fields.

**`scope: tuple[str, ...] = ()`**
- `()` keeps today's `bind_all` behaviour.
- `("canvas", "tree")` binds the chord only on those panels' focus widgets. Delete, for example, lives on both.
- Duplicate-chord detection is per scope: a scoped chord may not collide with a global one or with another action in the same scope.

**`alt_shortcuts: tuple[str, ...] = ()`**
- These are extra chords, such as Ctrl+Shift+Z for Redo, bound like `shortcut` and listed in the cheat-sheet.
- The menu accelerator shows only `shortcut`.

**`dynamic_label: Callable[[], str] | None = None`**
- It returns a **msgid with a mnemonic and named placeholders, plus its params**. For example `(N_("_Undo {action}"), {"action": stack.undo_text})` falls back to `N_("_Undo")` when there is nothing to undo.
- The menus refresh it in `postcommand` and on stack events.
- The mnemonic-uniqueness test checks the static fallback msgid. The placeholder is never in front of the mnemonic, so the underline index is computed from the msgid.

**Display and handling.** The cheat-sheet shows the scope, for example `_("Delete (canvas, object tree)")`. Menu items still show the accelerator, and the action handler acts on the session selection whichever panel has the focus.

**Leaving the canvas.** Tab walks the selection inside the canvas, so the documented exit is **F6 / Shift+F6** (WCAG 2.1.2, no keyboard trap). The canvas focus hint `_("Tab selects the next widget; F6 moves to the next panel.")` is shown in the status bar when the canvas gains focus, and the cheat-sheet lists it.

**Auto-repeat.** While a rebuild is pending (`after_idle` scheduled), further arrow and Shift+Arrow key repeats are dropped. A held key therefore moves at rebuild speed and never queues edits.

## 8. Move, resize and snapping
**Meaning of "move" per container kind** (ADR-005 has no free position):
| Container | Move means | Snapping |
|---|---|---|
| grid | the cell (row, column) changes; spans are kept | to cells, via the boundaries from `grid_bbox`, plus an append row/column |
| pack | the index among siblings changes (reorder) | to slots between children |
| pages | the tab/pane order changes | to tab/pane slots |
| any → other container | reparent with placement conversion (§5.3) | that of the target |

- **Drag-move:** a press on a selected widget followed by more than 4 px of motion is a `Moving` payload. It then follows the same target, check and execute path as §6.
- **Resize (D2 = A):** grid children only, through the handles.
  - Right, bottom and corner handles change `columnspan`/`rowspan`. Left and top handles change `column`/`row` and the span together, keeping the far edge.
  - The handle snaps to cell boundaries, with a minimum span of 1. Collisions are denied with the reason (live `check()`, as in §6).
  - Pack and page children show no handles. Their size is `fill`/`expand` and `width`/`height`, which are edited in the Step 14 inspector.
- **Snapping (D3 = A):** cell and slot snapping is inherent. There is no pixel grid size and no alignment guides, because there is no `place` (ADR-005). The cell-grid overlay (§3) shows the snap lines during a drag.

**Multi-move (D4 clarification; orchestrator ruling at 13b, refines the §5.3 "pointer's cell delta" row).**
- All moved nodes share one parent (otherwise the builder denies with `Only elements of the same container can be moved together.`); the primary node is the **anchor**.
- **Grid → grid:** every node keeps its row/column offset from the anchor, and the anchor lands on the target cell. If any node would land on a negative cell (or beyond 9,998), the **whole** move is denied with the reason; a collision with a cell that is not being moved is denied by `check()` with the validator's reason.
- **Pack/pages:** the nodes move as one contiguous block, in their current sibling order, to the target slot.
- **Reparent of several:** the same rules, applied in the target container. Grid→grid keeps sticky/padding and spans; a span that would cover a taken cell is clipped to 1. From pack/pages into a grid, the block is laid out in one row, in sibling order, with the anchor on the target cell.
- Always **one** compound command (`Macro`, `Move elements`), all or nothing. Dropping on the current place is denied (`'{id}' is already there.`) and never recorded.

## 9. Palette: hint and keyboard insertion (QA-12-13, D7)
**Hint.** Selecting a widget item by mouse or keyboard shows a transient status message (5 s, existing `show_message`):
- `_("Drag '{widget}' onto the canvas, or press Enter to insert it into the selected container.")`;
- Menu/Action items show `_M_MENU_EDITOR` instead.

**Insertion.** `Enter` / `KP_Enter` / double-click on a widget item calls `keyboard_target(document, selection, spec)`, which is pure:
1. **Pick the container.**
   - The primary selection is a layout or page container (window included): use it.
   - It is a leaf: use its parent, inserting after it.
   - Nothing is selected: use the current tab's window.
2. **Pick the position.**
   - grid: the first free cell in row-major order inside the current bounds, else `(max_row + 1, 0)`; a leaf as anchor means the next free cell after it;
   - pack/pages: the anchor's index + 1, or append.
3. **Execute.** The same `InsertNode` path runs. On success the new node is selected, the status bar says `_("Inserted '{id}' into '{container}'.")`, and **the focus stays on the palette**, so repeated Enter builds a column of fields. F6 moves to the canvas.

## 10. Object tree: stronger selected-row highlight
**Measured with the WCAG formula** (implementer: re-check with `theme.contrast()` in a test). `selectbg` against `inputbg` fails 3:1 in every SAPÉ theme:
| Theme | Ratio |
|---|---|
| light `#EEF3FF`/`#FFFFFF` | ≈ 1.1 |
| HC `#DCE6FF`/`#FFFFFF` | ≈ 1.25 |
| dark `#071044`/`#15181D` | ≈ 1.0 |

**Fix (D9 = A):** a pure `theme.selection_colours(spec) -> (fill, text)`.
- `fill` is the first candidate of `(colors["selectbg"], colors["primary"], focus)` with `contrast(fill, inputbg) ≥ 3.0`. In practice that is `primary`; light `#1C3FF0` on white is ≈ 7.0.
- `text` is `selectfg` if it reaches ≥ 4.5 on `fill`, else `readable(...)` toward white or black.
- `tag_colours()` gains the selected-row variants, so the error/muted tags stay ≥ 4.5 on `fill`.

**How it is applied.** A **namespaced** style `Designer.Treeview` is used by the palette, tree and inspector, with `style.map(..., background=[("selected", fill)], foreground=[("selected", text)])`. It is re-applied in `restyle()` on a theme change.
- `selectbg` itself is **not** changed, because ttkbootstrap uses it for troughs.
- The global `Treeview` style is **not** changed either, so user Treeviews on the canvas keep the runtime look (parity of `style`).

**Gate:** the contrast tests cover all 6 specs, SAPÉ and neutral: `fill/inputbg ≥ 3.0`, `text/fill ≥ 4.5`, and the tags on `fill` ≥ 4.5.

## 11. Edit actions (D6 = A)
| Menu | Action | Shortcut | Scope | Enabled when |
|---|---|---|---|---|
| _Edit | _Undo {label} | Ctrl+Z | global | `stack.can_undo`; label from `undo_text` |
| _Edit | _Redo {label} | Ctrl+Y, Ctrl+Shift+Z | global | `stack.can_redo` |
| _Edit | _Delete | Delete | canvas, tree | the selection has `Widget`/`Include` nodes |
| _Edit | Select _parent | Esc | canvas | the primary node has a parent |
| _Edit | Select _all in container | Ctrl+A | canvas | something is selected |

- **Delete:**
  - **Confirmation:** a selection containing a container with children asks for confirmation through the `ModalDialog` base (designer-ui rule), with `_("Delete '{id}' and its {count} elements?")` (`ngettext`).
  - **After the delete**, the parent becomes the selection.
  - **Guards:** windows, menubars and statusbars are not deleted in Step 13; their removal belongs to the Step 14 editors.
  - **Once per press (QA-13b-04):** the Delete key acts at most once per physical key press, in every scope. Auto-repeat presses are swallowed until the KeyRelease or a focus change, so a held key never cascades onto the parent it has just selected. Menu clicks are unaffected. Any future destructive key joins the same rule (`shell._ONCE_PER_PRESS`).
- **Undo/Redo** go through the stack. Undo/redo inside a text editor is Step 14's concern, since there are no editors yet.
- **Ctrl+Y on aqua:** the Ctrl+Y chord stays and Cmd+Shift+Z is added, via `core.keys` `aqua` handling.

## 12. i18n strings (en-GB msgids; all via `_()`/`N_()`/`ngettext`; named placeholders)
- **Palette:**
  - `Drag '{widget}' onto the canvas, or press Enter to insert it into the selected container.`
  - `Menus and actions are edited in the menu editor.` (`_M_MENU_EDITOR`)
- **Drag and drop:**
  - `Release to insert '{widget}' into '{container}'.`
  - `Release to move '{id}' into '{container}'.`
  - `Release to move {count} elements.` (plural)
  - `Release to resize '{id}' to {columns} × {rows} cells.`
  - `Release to cancel.`
  - `Drag cancelled.`
- **Result and refusal:**
  - `Inserted '{id}'.`
  - `Inserted '{id}' into '{container}'.`
  - `This window already has a status bar.` / `This window already has a menu bar.` (`_M_BAR_EXISTS`)
  - `A widget cannot be dropped into itself.`
- **Keyboard** (two full msgids, never composed from `{orient}`):
  - `This container arranges its children side by side; use Left and Right.`
  - `This container arranges its children top to bottom; use Up and Down.`
- **Selection:**
  - `{count} element selected` / `{count} elements selected`
  - `{count} elements selected; showing '{id}'.`
- **Canvas:**
  - `Included: {component}`
  - `This window cannot be drawn on the canvas: {reason}`
  - `Main window` / `Dialog` / `Component` (already exist in `present/canvas.py`; reuse them)
- **Edit menu:**
  - `_Edit`, `_Undo`, `_Undo {action}`, `_Redo`, `_Redo {action}`, `_Delete`, `Select _parent`, `Select _all in container`
  - `Delete '{id}' and its {count} element?` / `Delete '{id}' and its {count} elements?`
  - `Delete`, `Cancel`
- **New macro labels** (`N_()` in `designer/editing.py`; `Macro` takes the label, so `core` is unchanged):
  - `Move elements`
  - `Delete elements`
  - `Resize element`
- **Canvas focus hint:** `Tab selects the next widget; F6 moves to the next panel.`
- **Text rules:**
  - every new mnemonic is unique per menu in the source and in `en_XA` (existing test);
  - 40 % slack, no fixed widths;
  - catalogue sync per sub-step (`docs/i18n/README.md`), with D6-of-Step-12 still in force: no translations until Step 18.

## 13. Test plan and performance budget
**Pure tests (fast, no Tk):**
- `geometry`/`targets`:
  - hypothesis over random grids (≤ 20×20, random spans without collisions) and pack lists (≤ 50). `hit_test` always returns a target inside the bounds or `None`, and the result is monotonic in x and y;
  - the pack index is stable when the pointer moves within a child half;
  - edge band → parent;
  - a moving node and its descendants are never the target;
  - `move_index` matches the list model.
- `editing`:
  - `unique_id` against duplicates, reserved ids, keywords and 64-char stems (hypothesis on stems);
  - `new_node` for every core spec plus a fake extension spec. The node validates clean once inserted into a template window; `check()` accepts.
- `keyboard_target`: grid first-free-cell, leaf anchor, empty window and a page container.
- `session`:
  - `select_many` drops foreign nodes and mixed windows;
  - pruning after undo of an insert and after delete;
  - `.node` compatibility.
- `theme.selection_colours`: the contrast gate on all 6 specs.
- `PURE_MODULES` gains `render_plan`, `geometry`, `targets` and `editing`.

**Tk tests (`@pytest.mark.gui`, package-scoped shared root; reuse `tests/designer/conftest.py`):**
- Engine:
  - every template renders;
  - `node_of(widget)` round-trips for every node;
  - a window with a deliberately failing factory shows the error card while the other tabs still render;
  - the off-screen swap leaves exactly one window frame.
- Design mode: §4 designer-side tests.
- Overlay:
  - outline rects equal the `outer` widget rects (±1 px);
  - handles only under grid;
  - the denied indicator uses the dashed variant.
- Drag:
  - synthetic palette drag via `event_generate` with `x_root`/`y_root` (warp not needed) → drop into the `main_window` template grid → one `InsertNode`, the new node selected, undo restores;
  - occupied cell → denied, the status bar shows the validator message, the document is unchanged;
  - Esc mid-drag cancels.
- Keyboard: Tab order, arrow move (one undo step each), Shift+Arrow span, Delete with confirmation, Enter in the palette inserts.
- Sync: tree extended selection ↔ canvas outlines ↔ status count ↔ inspector header.
- Leaks: 50 rebuilds leave `root.winfo_children()`, `image names` and `bind_class(DESIGN_TAG)` unchanged.

**Performance budget** (measured in the tests with generous CI factors: ×3 under coverage):
| Operation | Budget |
|---|---|
| render of a 200-widget window | ≤ 250 ms |
| render of a 2,000-widget window | ≤ 2.0 s (marked `slow`; if over budget → Step 19 subtree rebuild) |
| `snapshot()` (200 widgets) | ≤ 30 ms |
| `hit_test` | ≤ 1 ms |
| overlay update | ≤ 5 ms |
| hover `check()` | ≤ 100 ms on 2,000 widgets (it inherits the Step 09 guard cost); 1 call per target change, after a 60 ms rest |
| designer Tk tests added | ≤ 6 s |

## 14. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | Embed and runtime drift below the window body | §4 tests compare the full widget description (bindings included); embed code is limited to `if embed` branches; ADR-010 rule |
| R2 | ttk Notebook `enable_traversal` or other `[winfo toplevel]` bindings leak into the designer root | Skipped in embed; `test_embed_creates_no_toplevel` checks `bind_class`/`root.bind()` |
| R3 | Dropping the instance bindtag breaks internal ScrolledFrame/ScrolledText sizing | **Verify** ttkbootstrap 2.2.3 `ScrolledFrame` (`<Configure>` on its canvas); keep that one tag if needed; a test renders `settings.ui` and a ScrolledFrame with children |
| R4 | `check()` at about 80 ms makes the hover sluggish on large documents | Key-change + 60 ms debounce + per-drag cache; Step 19 scoped validation |
| R5 | A stack listener calling the stack raises `RuntimeError` (`_Busy`) | Listeners only schedule `after_idle` (§2.6); a test executes from inside a listener path |
| R6 | Full rebuilds flicker or are slow | Off-screen build then swap; budget in §13; subtree rebuild deferred |
| R7 | The implicit grab on the palette Treeview is lost on some platforms (focus-follows-mouse WMs) | Cancel on `<FocusOut>`/`<Leave>` of the app; release off-stage = cancel |
| R8 | One `Style` means canvas widgets show the designer theme, not the document's | Accepted (ADR-009 D4); Step 15 subprocess preview |
| R9 | HiDPI: fixed pixel sizes for handles and bands | All sizes go through `theme_tk.scaled()` |
| R10 | The `Selection` constructor change breaks Step 12 tests | Mechanical update, listed in §7.1; `.node` property kept |

## 15. UAT (for the user)
**13a:**
1. `uv run pyguibud`: the canvas tab shows the real `main_window` template, with its caption, menubar strip and status bar.
2. Clicking a Button on the canvas selects it and does **not** press it. Typing goes nowhere.
3. Click a palette item: the status bar shows the drag hint. Drag a Label into an empty grid cell: the blue indicator follows the cells, release inserts it, and it becomes selected in the tree and the inspector.
4. Drag onto an occupied cell: a red dashed indicator, the cross cursor and the reason in the status bar; release changes nothing.
5. Ctrl+Z / Ctrl+Y undo and redo the insert. With an Entry selected in the palette, Enter inserts it into the selected container; keyboard-only.
6. Light, dark and HC themes: the selected rows in the tree, palette and inspector are clearly visible.

**13b:**
1. Drag a widget to another cell or into a Frame; reorder pack children; drag a grid widget's right/bottom handle to span 2 columns.
2. Ctrl/Shift-click and a rubber band select several widgets; move them together; Delete asks before removing a container with children.
3. Arrow keys move, and Shift+Arrow resizes the span; each step undoes separately.
4. Everything again with `--lang en_XA`: no truncated labels or hints.

## 16. Decisions (recommended default in bold)

**Resolved by the user on 2026-10-06: all defaults** — D1 = B, D2 = A, D3 = A, D4 = A, D5 = A, D6 = A, D7 = A, D8 = A, D9 = A, D10 = A.

- **D1 — Split Step 13?**
  - **B (recommended): two sub-steps with two UATs.** 13a covers the engine, design mode, palette insertion (drag + Enter), single selection, undo/redo and the tree highlight. 13b covers move, reorder, reparent, span resize, multi-select and the rubber band. This means smaller sessions, and the parity-critical engine is approved before the gestures land on it.
  - A: one step, one UAT. That is a larger session with a higher risk of crossing the context limit.
  - C: three sub-steps (engine / insert / rearrange). That means extra UAT overhead.
- **D2 — Resize semantics** (ADR-005 has no pixel position).
  - **A (recommended): grid spans only** (handles change `rowspan`/`columnspan`, and the left/top handles also change `row`/`column`). There are no handles for pack or page children; their sizes go to the Step 14 inspector.
  - B: A plus a drag on pack children that writes their `width`/`height` properties. The units are characters for Button/Entry/Label and pixels for others, so the result is inconsistent and confusing.
  - C: no resize in Step 13.
- **D3 — Snapping** (the plan mentions "grid size, guides").
  - **A (recommended): snap to cells and pack slots only, with a cell-grid overlay drawn during drags.** There is no pixel grid size and there are no guides.
  - B: amend ADR-005 to add `place`/absolute layout, which would give pixel grids and guides. This is a **scope change** (Won't v1): there is no clean Qt mapping, and it touches the validator, runtime, codegen and parity.
  - C: A plus dragging the edge of a widget to set `padx`/`pady` in 4 px steps. This adds complexity for little gain.
- **D4 — Multi-select scope.**
  - **A (recommended): select, delete and move as a block within the same parent container** (a grid delta or a contiguous pack insert).
  - B: select and delete only.
  - C: everything, including cross-container multi-moves and align/distribute commands. That needs more commands and has little value with grid/pack.
- **D5 — Rubber-band selection.**
  - **A (recommended): yes in Step 13.** It works inside the container where the band starts and selects the direct children that lie fully inside the band; Ctrl adds.
  - B: yes, selecting by intersection instead of full containment. This is easier to hit, but it catches neighbours by accident.
  - C: defer it to Step 19 polish (trim item 1 anyway).
- **D6 — Undo/Redo and Delete in Step 13** (the plan places them in Step 14).
  - **A (recommended): Edit ▸ Undo/Redo (Ctrl+Z, Ctrl+Y / Ctrl+Shift+Z) and Delete (with confirmation for non-empty containers) now.** Without undo, a bad drop during the UAT cannot be recovered.
  - B: Undo/Redo now, Delete in Step 14.
  - C: both in Step 14, as planned.
- **D7 — Keyboard insertion** (accessibility, M13).
  - **A (recommended): Enter or double-click on a palette item inserts it into the selected container (after a selected leaf) at the first free cell or at the end; the focus stays on the palette.**
  - B: as A, but the focus moves to the canvas with the new widget selected. That is better for immediate arrow moves, but worse for repeated insertion.
  - C: drag only. This **fails** the keyboard-only requirement.
- **D8 — Drag-and-drop in the object tree** (FEATURES M1 lists "reorder and reparent … in the object tree").
  - **A (recommended): keyboard reorder in the tree now (Alt+Up/Down), with tree drag-and-drop in Step 14.**
  - B: full tree drag-and-drop (reorder and reparent) in Step 13. That adds about 250 lines and a second drop-target model.
  - C: no tree reordering before Step 19.
- **D9 — Selected-row highlight style** (all 3 themes currently fail 3:1).
  - **A (recommended): a solid `primary` fill with readable on-colour text** (≥ 3:1 for the fill, ≥ 4.5 for the text). It is the strongest and matches the SAPÉ action colour.
  - B: the lightest tint of `primary` that reaches 3:1, keeping dark text. It is softer, and the tint is computed.
  - C: keep `selectbg` and add a "▶" marker plus bold text on the selected row. That is not a contrast fix for the row itself.
- **D10 — Meaning of the arrow keys on the canvas.**
  - **A (recommended): the arrow keys move the selected widget** (to the next cell or slot), and Tab/Shift+Tab walk the selection. This is the Qt Designer/WinForms convention.
  - B: the arrow keys move the *selection* spatially, and Alt+Arrow moves the widget. This is closer to list navigation, but spatial "next" is ambiguous with spans and nested containers.
