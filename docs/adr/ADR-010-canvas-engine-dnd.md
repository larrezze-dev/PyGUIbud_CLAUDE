# ADR-010 — Canvas engine (embed mode) and drag-and-drop model

- **Status:** Accepted (user, 2026-10-06) · **Date:** 2026-10-06 · **Step:** 13 · **Spec:** `docs/specs/dnd-selection.md` (D1–D10 resolved: all defaults)

## Context
The canvas must show what the runtime builds, without a second builder. It must also never run user code or react to input, and it must stay inside the single ttkbootstrap root (ADR-009). Today `backends/_tk.py` turns every window into a `Toplevel` when it is given a master. ADR-005 rules out pixel placement. Each `CommandStack.check()` costs about 80 ms on 2,000 widgets, and stack listeners must not re-enter the stack. Two alternatives were rejected:
- a separate canvas renderer, because it would drift from the runtime;
- a transparent overlay `Toplevel`, because it is not portable.

## Decision
- **Embed mode:** `TkSession(..., embed=Embed(host, on_node, on_title, placeholder))`, reached through `TtkbootstrapBackend.build_embedded()`. In embed mode:
  - each window is a `Frame` in `host`, and the title goes to `on_title`;
  - the menubar `Menu` tree is built but not attached;
  - `minsize`, `transient`, `protocol`, shortcut binds, the theme, `enable_traversal` and `deiconify` are skipped;
  - lookups of images and variables are lenient;
  - `on_node(node, outer, inner)` reports every node by identity.

  `embed=None` is unchanged, and codegen is untouched.
- **Parity rule:** for all parity examples, embed mode must produce the same widget description as `load_ui` (bindings included). Only the pinned window-level `EMBED_DEVIATIONS` may differ. Adding a deviation needs an addendum to this ADR.
- **Design plan:** the designer builds its own `BuildPlan` with the pure `designer/render_plan.py`, one per window. It never calls `load_ui`. The plan has no handlers, shows the source texts, and draws unexpanded includes as placeholders (until Step 14).
- **Design mode:** after the build, every canvas widget gets bindtags `(PyguibudDesign, "all")` and `takefocus=0`. Handlers bound once with `bind_class` return `"break"`.
- **Overlay:** `place()`-d `tk.Frame` strips and handles, children of the stage, raised above the window frame. Colours come from theme tokens, and a denied target has a dashed look plus a cursor plus text.
- **Hit-testing** is pure: a geometry `Snapshot`, and `hit_test()` → grid cell, pack slot, page slot or bar. It never uses `winfo_containing`.
- **Commands:** each gesture is one command (`break_merge()` first). Hover calls `check()` only when the target changes and after a 60 ms rest, with the results cached per drag. A drop calls `execute()`. Stack listeners only schedule `after_idle` rebuilds, which rebuild the whole affected window off-screen and then swap it in.
- **Selection** holds `nodes: tuple` (`.node` is the primary). It is pruned on every stack event.
- **Amendment to the ADR-009 action registry:** `ActionDef` gains three fields:
  - `scope` (panel-local chords);
  - `alt_shortcuts`;
  - `dynamic_label` (for "Undo {action}").

  Unscoped actions keep `bind_all`.

## Consequences
- ➕ The canvas is the runtime's own output. Opening or editing a `.ui` never executes code. The geometry logic is testable headless with hypothesis.
- ➖ `_tk.py` gains embed branches (≤ 60 lines). Mitigation: the parity tests above, plus the no-Toplevel and leak tests.
- ➖ Full-window rebuilds and the hover guard cost scale with document size. Mitigation: the budgets in spec §13; subtree rebuild and scoped validation in Step 19.
- Affected: Steps 14 (include expansion, images, inspector multi-edit, tree drag-and-drop), 15 (preview), 16 (backends may offer `build_embedded`) and 19 (performance).

## Addendum 1 (Step 13a implementation, 2026-10-07)
Recorded by the orchestrator from the 13a engine delegation; acknowledged by the user at UAT 13a (2026-10-07).
- **Pinned `EMBED_DEVIATIONS`** = `("minsize", "resizable", "bindings")`: window-level only (a `Frame` has no WM state and no window-level shortcut bindings). Guarded by `test_embed_deviations_are_pinned`.
- **Parity comparison reading:** window ids are compared at window level only, not as widget descriptions, because a `Toplevel` can never describe the same as a `TFrame`. A window without a `title` property is compared as the marker `"<no title property>"` on both sides, because the Toplevel otherwise reports the toolkit default title, which is not document content.
- **Design-mode bindtags** are `("PyguibudDesign",)` **without `"all"`**, not `(PyguibudDesign, "all")`. Exception: the ScrolledFrame content frame and its viewport canvas keep their instance tag, because they need their `<Configure>` bindings to size themselves (spec risk R3, checked against ttkbootstrap 2.2.3). Global shortcuts must therefore keep working while focus is on a canvas widget (canvas widgets have `takefocus=0`, and the focus proxy owns keyboard input); a test guards Ctrl+Z after a canvas click.
- **ttkbootstrap ScrolledFrame leak:** its mouse-wheel handler is bound with `bind_class`, and Tk never deletes that callback, so a destroyed ScrolledFrame keeps its subtree alive (`load_ui` is affected too). `WindowView.destroy()` deletes these callbacks. This is the designer's only use of ttkbootstrap internals; candidate for an upstream report.

## Addendum 2 (Step 13a, QA-13a-02/03/04, 2026-10-07)
Proposed by the architect. It is an implementation clarification within D3, not a new decision, and was acknowledged by the user at UAT 13a (2026-10-07). Spec: `docs/specs/dnd-selection.md` §5.4.
- **Pinned `DESIGN_AFFORDANCES`:** three design-only geometry deviations from the runtime output. `CanvasEngine` applies them after `build_embedded()` returns, never in `_tk.py`, codegen or the runtime, and they never touch the `.ui`. The parity tests (`build_embedded` vs `load_ui`) cannot see them. Adding another needs an addendum to this ADR.
  - **R-A:** an empty layout or page container, or an empty window body, gets `width`/`height` = 120×64 px (scaled).
  - **R-B:** a non-empty grid or pack container gets 20 px (scaled) of extra right and bottom padding. That space is its append zone, and the existing "beyond the last boundary" and "past the last midpoint" rules in `hit_test` resolve it unchanged.
  - **R-C (QA-13a-03 reopened, third entry `paned-append-pane`):** a ttk Panedwindow has no padding and gives any extra size to its last pane, so a non-empty PanedWindow gets a trailing empty design-only pane of 20 px (scaled) along its orient axis instead, which the "past the last midpoint" rule resolves to the append slot; when every real pane weight is 0, the last real pane gets weight 1 so it keeps the slack, as at runtime.
- ➕ Every container is reachable by the mouse (13a insertion and 13b move alike), with no change to `targets.py`.
- ➖ The canvas is no longer pixel-identical to the runtime: containers can look up to 20 px larger. Mitigation: the Step 15 preview shows the true size, and the list above is pinned.

## Addendum 3 (Step 13b kickoff, QA-13a-14, 2026-10-07)
User decision. Spec: `docs/specs/dnd-selection.md` §5.4 rule R-D.
- **R-D (`empty-container-outline`):** an empty, unselected layout or page container gets a 1 px dashed design-only outline drawn by the overlay. It is a drawing, not a geometry change, so it does not alter any rect, hit test or parity reading. It is listed with the `DESIGN_AFFORDANCES` so that the list of every way the canvas differs from the runtime stays complete.

## Amendment (Step 14a.2, 2026-10-08): overlay stacking and selection-outline cap
Debugger fix with orchestrator approval. Spec: `docs/specs/dnd-selection.md` §3.
- **Stacking:** the overlay strips are no longer raised with `lift()` on every draw. A strip's stacking order is set once, when it is created (just below the lowest strip of the layers above it), and a rebuilt window frame is lowered beneath every strip with a single `lower()` (`Overlay.sink`). A redraw only sends changed strips to Tk. The decision (strips above the window frame, children of the stage) is unchanged. Only the way that order is kept has changed. Raising every strip on every redraw was quadratic: a paste of 500 widgets took about 48 s.
- **Selection-outline cap:** the primary plus at most `SELECTION_CAP` = 16 other selected nodes are outlined. A larger selection is reported in the status bar with its count. Reason: each outline is 8 native child windows, which take about 1 ms each to map on Windows and more as siblings grow (800 strips 0.57 s, 4000 strips 5.9 s to map and 14 s to hide in plain Tk).
- ➕ Paste of 500 widgets: 48.3 s → 1.21 s (budget 1.5 s). Select all of 500: 5.2 s → 0.55 s. Deselecting afterwards: about 0.2 s.
- ➖ In a selection larger than 17 nodes, not every selected node is outlined on the canvas. Mitigation: the status-bar count, and the object tree still highlights every selected row.

## Addendum 4 (Step 14b, 2026-10-10): size handles and include rendering
- **Status:** Accepted (user, 2026-10-10; D1–D10 all defaults, so no ADR-013). Spec: `docs/specs/direct-manipulation.md` (D1–D10). This is an addendum rather than a new ADR because it amends this ADR's own D2, the "placeholders until Step 14" clause and the R-A affordance. If D8 (b) is chosen (a `PropertyDef.unit` field = plugin-API scope), that part moves to a new ADR-013.
- **D2 amended (user, 14a.2 UAT):** the handles of the primary selection change the widget's **size properties** (`width`/`height`/`length`, in the unit Tk uses: px, characters, lines or rows; designer-side table) wherever an axis has one. Span semantics remain for grid children:
  - on axes without a size property (hollow handles);
  - on axes stretched by grid sticky (on both sides);
  - on mixed corners;
  - for the whole drag when Ctrl is held.

  Hidden size axes, so that a value with no runtime effect is never written:
  - pack `fill`;
  - page children;
  - Frame/LabelFrame with children (Tk propagation).
- **Window size:** the selected window's plate gets right, bottom and corner handles. They write `min_width`/`min_height` with `SetField`; dragging below the contents clears them. For `kind="component"` they are a design-time preview size (no runtime effect). No format change.
- **Gestures:** motion draws a ghost only. Release runs one `Macro` (`Resize`, `Resize window`) after `break_merge()`. Keyboard steps (Ctrl+Shift+Arrows) use mergeable bare `SetProp`/`SetField`.
- **R-A amended:** per axis, a set `width`/`height` property overrides the 120×64 design size, with a 16 px (scaled) design-only geometry floor that is never written.
- **R-E `include-outline` (new `DESIGN_AFFORDANCES` entry):** a 1 px dashed outline around an expanded include. It is a drawing, with no geometry change.
- **Include rendering:** `render_plan.design_plan` populates `Instance.includes`, mirroring the runtime's `_expand` without importing it (ADR-007). `_tk.py` is unchanged: `_include` already expands when the entry exists, so embed/runtime parity holds, and a parity test with an external include is added.
  - External files go through `core.files.DiskFiles` and the R49–R53/R82 findings.
  - Any finding, any reader error (newer MAJOR, more than 10 MiB, invalid), an untitled document, or a depth, cycle or node-budget breach → a placeholder with the reason.
  - A newer MINOR file renders read-only (as at runtime).
  - Cache by `(realpath, mtime_ns, size)`; refresh on focus-in.
  - The engine maps only nodes of the window's own `walk()`, by identity. Included widgets resolve to the `Include` node, which is a read-only leaf. This is required for `src="#"`, where included widgets are the component tab's own objects.
- ➕ Fixes the 14a.2 UAT complaint without a `.ui` format change, core change or runtime change (recommended defaults). Opening an included file never executes code.
- ➖ The canvas measures character pitch in the designer theme (ADR-009 D4), and first drags from a natural size are estimates (±1–2 units). Mitigation: the exact value shows in the status bar, and the rebuild shows the truth. A window minimum is a floor, not an exact size; an initial-size attribute is deferred (spec D3 b).
