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
Recorded by the orchestrator from the 13a engine delegation; pending user acknowledgement at UAT 13a.
- **Pinned `EMBED_DEVIATIONS`** = `("minsize", "resizable", "bindings")`: window-level only (a `Frame` has no WM state and no window-level shortcut bindings). Guarded by `test_embed_deviations_are_pinned`.
- **Parity comparison reading:** window ids are compared at window level only, not as widget descriptions, because a `Toplevel` can never describe the same as a `TFrame`. A window without a `title` property is compared as the marker `"<no title property>"` on both sides, because the Toplevel otherwise reports the toolkit default title, which is not document content.
- **Design-mode bindtags** are `("PyguibudDesign",)` **without `"all"`**, not `(PyguibudDesign, "all")`. Exception: the ScrolledFrame content frame and its viewport canvas keep their instance tag, because they need their `<Configure>` bindings to size themselves (spec risk R3, checked against ttkbootstrap 2.2.3). Global shortcuts must therefore keep working while focus is on a canvas widget (canvas widgets have `takefocus=0`, and the focus proxy owns keyboard input); a test guards Ctrl+Z after a canvas click.
- **ttkbootstrap ScrolledFrame leak:** its mouse-wheel handler is bound with `bind_class`, and Tk never deletes that callback, so a destroyed ScrolledFrame keeps its subtree alive (`load_ui` is affected too). `WindowView.destroy()` deletes these callbacks. This is the designer's only use of ttkbootstrap internals; candidate for an upstream report.

## Addendum 2 (Step 13a, QA-13a-02/03/04, 2026-10-07)
Proposed by the architect. It is an implementation clarification within D3, not a new decision, and is pending user acknowledgement at UAT 13a. Spec: `docs/specs/dnd-selection.md` §5.4.
- **Pinned `DESIGN_AFFORDANCES`:** three design-only geometry deviations from the runtime output. `CanvasEngine` applies them after `build_embedded()` returns, never in `_tk.py`, codegen or the runtime, and they never touch the `.ui`. The parity tests (`build_embedded` vs `load_ui`) cannot see them. Adding another needs an addendum to this ADR.
  - **R-A:** an empty layout or page container, or an empty window body, gets `width`/`height` = 120×64 px (scaled).
  - **R-B:** a non-empty grid or pack container gets 20 px (scaled) of extra right and bottom padding. That space is its append zone, and the existing "beyond the last boundary" and "past the last midpoint" rules in `hit_test` resolve it unchanged.
  - **R-C (QA-13a-03 reopened, third entry `paned-append-pane`):** a ttk Panedwindow has no padding and gives any extra size to its last pane, so a non-empty PanedWindow gets a trailing empty design-only pane of 20 px (scaled) along its orient axis instead, which the "past the last midpoint" rule resolves to the append slot; when every real pane weight is 0, the last real pane gets weight 1 so it keeps the slack, as at runtime.
- ➕ Every container is reachable by the mouse (13a insertion and 13b move alike), with no change to `targets.py`.
- ➖ The canvas is no longer pixel-identical to the runtime: containers can look up to 20 px larger. Mitigation: the Step 15 preview shows the true size, and the list above is pinned.
