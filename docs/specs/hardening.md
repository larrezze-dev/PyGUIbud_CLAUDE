# Spec — Step 19: QA hardening ("idiot-proof")

- **Status:** Accepted (user, 2026-10-17: "accept all defaults" — D1–D14 all at the recommended default). Budget baseline: HEAD `67125cc` (Step 18 committed). **Rulings after 19a (user, 2026-10-17):** `pytest-randomly` becomes a dev dependency (in 19b); the CLAUDE.md attribution rule ("Created by Luciano Arrezze and programmed with the support of Claude Code", translated) lands in the UI/About strings in 19e and in the docs in Step 21; the H03 livelock (a designer on a root mapped at its empty size, then withdrawn) is fixed in 19c. **Rulings in 19c (user/orchestrator, 2026-10-18):** H41 → the inspector shows a read-only clipped preview above 2,000 characters (↺ Reset clears it; the model and file keep everything); QA-19c-03 → H37 works by compensation, and when a failed undo/redo changed the document the history is cleared (`command.history_cleared`, document stays dirty); an int variable bound to a text Entry stays accepted; the H38 shift applies to "after" drops only. · **ADR:** none needed. Nothing here changes the `.ui` schema, the public API or the import boundary. If D9 (a) is chosen, ADR-002 gets an addendum about the writer's `tb` prefix.
- **Owner:** QA (opus) + DEBUGGER (opus), with TESTING, BACKEND, FRONTEND and TRANSLATOR per part (§3) · **Reviewer:** SOFTWARE-ARCHITECT
- **Budget:** ≈ 2,280 net production lines over seven parts. The caps total 2,920 (§3).
- **Plan row 19:** an abuse suite covering corrupt files, absurd values, cyclic parents, quitting with unsaved changes, read-only paths and huge files. UAT: "Try to break it yourself using the provided checklist; every bad action is blocked gracefully."

## 1. Scope and sources
This spec is the plan of record for Step 19. It lists every item that is deferred to, or assigned to, Step 19. Each item appears exactly once in §2.

| Code | Source | How it was collected |
|---|---|---|
| S1 | `DEVELOPMENT_PLAN.md` §4, row 19 | 6 themes |
| S2 | skill `abuse-testing`: Files M24, Editing M23, Plugins M25, Locales/accessibility | 14 bullets, one row each; sub-cases inline |
| S3 | `DEVELOPMENT_PLAN.md` §5 session notes for 16c, 17a, 17b, 17c and 18 | every "→ Step 19" / "Deferred → Step 19" |
| S4 | `DEVELOPMENT_PLAN.md` §5, the "18 UAT" note | 3 follow-ups |
| S3b | **Older §5 notes the kickoff list did not name:** Step 09, 12, 13a, 13b, 14a.1, 14p, 14b.1, 14b.2, 15a, 15b, 16b | the same grep. They carry real deferrals, so they are included |
| S5 | `docs/specs/*.md` §14/§14a/§14b/§14c and other "Step 19" mentions, plus ADR-006/010/014/015 | `grep "Step 19" docs/` (25 hits in 11 files) |
| S6 | `xfail(strict=True` in `tests/` | 8 decorated tests = **13 cases**. The parametrised ones are 18-04 (×3 argv), 18-13 (×2 tools) and 18-16 (×3 languages): 1+1+1+1+1+3+2+3 = 13 |

**Not items (excluded on purpose):**
- `dnd-selection.md:644` (D5-C) and `:656` (D8-C) are options the user rejected in Step 13. They are not deferrals.
- `validate-commands.md:26` only says that Step 19 builds 10 MiB / deeply nested documents. It is folded into H13.
- ADR-006:21, ADR-010:36 and `runtime.md:547` repeat H47/H48.

**Out of Step 19 (user ruling, Step 18):**
- localised accelerator key names ("Strg+Q");
- translated enum display names.

H79 only moves literal key names into placeholders; neither ruling is re-opened here.

**Budget baseline.** Step 18 is not committed yet.
- Measure a part as: (`git diff --numstat HEAD -- src` now) − (the same per file in the snapshot `C:\Users\larre\AppData\Local\Temp\claude\D--Coding-SAPE-PyGUIbud-CLAUDE\1ca3ec6e-2451-4f61-ad27-a8a5a11bad9d\scratchpad\step19_baseline_numstat.txt`). Count added − deleted for `src/**/*.py`.
- Add the full line count of any **new untracked** `src/**/*.py` (`step19_baseline_untracked.txt` in the same folder is empty, so every untracked module is new in Step 19).
- Once the user commits Step 18, measure against HEAD instead.
- Each part records its start numstat in its handover. The next part's figure is then a delta against that record.
- Not counted: tests, `.po`/`.mo`, docs, `tools/`.

## 2. Traceability (96 unique items)
Severity: B = blocker, M = major, m = minor, P = performance, D = documentation, T = test infrastructure. Where an item has several sources, the first one is primary; the others are listed after it.

### 19a — test-infrastructure stability (11)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H01 | S4 | Test helpers reset the shared root with `withdraw()`+`geometry("")`, which Windows ignores on a withdrawn root. Replace them with one shared conftest reset (resize while mapped, then withdraw) | T |
| H02 | S3 17b · S5 plugins §14b | Running `tests/runtime` before `tests/codegen` gives 33 "single application root" errors. Cause: the session-scoped root in `tests/runtime/conftest.py` vs the package-scoped root in `tests/designer/conftest.py` | T |
| H03 | S3 17b · S3b 16b · S5 plugins §14b | Running `tests/runtime` before `tests/designer` hangs in `update_idletasks` (`test_13a_gaps::test_no_listener_reenters…`, `canvas.py:576`) | T |
| H04 | S3 17a | `tests/qa` has no autouse i18n reset | T |
| H05 | S3b 15b | QA-15b-11: pytest "fixture not found" when the command line goes back to `tests/designer`; `test_export_gui.py` imports `FakeProcess` from another test module | T |
| H06 | S3b 15b | QA-15b-17: the budget tests fail under `--cov`; the scorer counts 🔶 as done | T |
| H07 | S3b 15a | QA-10-13: a Tcl `focus.tcl` handle flake (seen once) | T |
| H08 | S3b 13b | An intermittent focus skip at `test_qa13a_abuse.py:207` in full runs | T |
| H09 | S3b 13b · S3b Step 12 | `tests/designer` is over its time budget (≈ 18 s vs 8 s; §13 allows ≤ 6 s for new tests) | T |
| H10 | S3b 14p | QA-14p-12: the inspector render budget is flaky (≈ 48–50 ms vs 60) | T |
| H11 | S3b 14p | QA-14p-13: `dispose()` leaks ≈ 41 Tcl commands per rebuild (`unbind_class`) | m |

### 19b — files and I/O abuse (20)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H12 | S1 corrupt files · S2 M24 open | Opening hostile files: empty, binary, truncated, an entity bomb, an external DTD, the wrong root, a newer MAJOR/MINOR schema, the wrong encoding, a non-ASCII/emoji path, a file deleted while open. Partly pinned (`core/test_xml_read`, `designer/test_files`); 19b adds one end-to-end matrix | M |
| H13 | S1 huge files · S2 M24 (2 GB) · S5 validate-commands §26 | Huge files: a 2 GB file, a 10 MiB file, depth 100 and 10,000 widgets refuse fast, with no recursion and no freeze | M |
| H14 | S1 read-only paths · S2 M24 save | Saving: a read-only file or folder, a full disk (simulated), a file locked by another process, overwriting a non-`.ui` file, a file changed externally. Atomic write and `.bak` are checked | M |
| H15 | S2 M24 kill | Killing the process mid-edit → restart → recovery offers the autosave | M |
| H16 | S1 quit unsaved · S2 M24 close | Closing with unsaved changes through the window X, Alt+F4, menu Quit and the OS logout signal (`WM_SAVE_YOURSELF`/`WM_DELETE_WINDOW`) | M |
| H17 | S3b 15b | QA-15b-04: a locked generated file is reported as "not written by PyGUIbud" | m |
| H18 | S3b 15b | QA-15b-06: the `.pot` field of the Export dialog has no suffix rule | m |
| H19 | S3b 15b | QA-15b-07: the refusal wording for invalid characters and a missing folder | m |
| H20 | S3b 15b | QA-15b-08: NTFS stream names (`a.py:evil`) pass the output plan | m |
| H21 | S3b 15b | QA-15b-09: a lone surrogate in the settings silently blocks later saves | M |
| H22 | S3b 15b | QA-15b-10: re-exporting while a run is open blocks for ≈ 1 s | m |
| H23 | S3b 15b · S6 | QA-15b-12: a `.ui` name of 242–255 characters cannot be saved (the temporary name adds 14). Strict xfail `tests/qa/test_step15b_real_acl.py::test_qa15b_12_a_long_but_valid_file_name_can_be_saved` | m |
| H24 | S3b 15b | QA-15b-13: `tempfile.mkdtemp` in `preview_tk.py` and `dialogs/export.py` has the retry loop when `%TEMP%` becomes denied (use `core/atomic`) | M |
| H25 | S3b 15b | QA-15b-15: a settings-save failure at Quit shows no OS reason | m |
| H26 | S3b 15b | QA-15b-16: "Autosave failed" stays in the status bar after recovery | m |
| H27 | S3b 15a | QA-15a-06: `sweep_stale` checks the mtime only, not whether the pid is alive | m |
| H28 | S3b 14b.2 | A symlink to a network share would be contacted (R82 checks only the `src` string) | D |
| H29 | S3 17c · S5 plugins §14c · S6 | QA-17c-04: a second designer instance overwrites `disabled_plugins`. Strict xfail `tests/qa/test_step17c_abuse.py::test_qa17c_04_a_second_instance_keeps_the_disabled_plugin` | m |
| H30 | S3 17a · S5 plugins §14a · S6 | QA-17a-03: `xmlns:tb="urn:evil"` checks clean. Strict xfail `tests/qa/test_step17a_abuse.py::test_qa17a_03_tb_prefix_bound_to_a_foreign_namespace` | m |
| H31 | S5 validate-commands §539 | The depth of `RawXml` subtrees is unchecked (the writer and the safety net refuse them; the reader should cap them) | m |

### 19c — editing and model abuse (12)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H32 | S2 M23 ids | Ids: duplicate, `class`, `None`, `_private`, `1abc`, `a-b`, 10,000 characters, Unicode lookalikes. These go through the inspector, the tree rename and the Variables tab | M |
| H33 | S1 absurd values · S2 M23 grid | Grid collisions, negative or huge row/span/padding, mixed grid+pack, two main windows, a cyclic `<include>` | M |
| H34 | S1 cyclic parents · S2 M23 drop | Dropping into a non-container, a window into itself, a container into its own descendant (canvas, tree DnD, keyboard, paste) | M |
| H35 | S2 M23 handlers | Handler or variable names that are not identifiers; an int var bound to a text Entry; deleting a variable that is still bound | M |
| H36 | S2 M23 storms | 1,000 rapid Ctrl+Z/Ctrl+Y; pasting garbage XML or huge text from the clipboard; multi-select delete + undo | M |
| H37 | S3b Step 09 | `undo`/`redo` cannot recover when a `revert()` raises halfway (no revert-on-failure) | M |
| H38 | S3b 14b.2 · S6 | QA-14b2-14: a wide block dropped "after" a tall sibling lands above it. Strict xfail `tests/designer/test_qa14b2_abuse.py::test_qa_14b2_14_a_wide_block_dropped_after_a_tall_sibling_lands_above_it` | m |
| H39 | S3b 14b.2 | A span resize keeps stale grid lines if a rebuild happens mid-resize | m |
| H40 | S3b 14b.1 | Q12 races: palette Enter or double-click inserts during a resize; a canvas press ends a palette drag; the palette selection overwrites the size status | m |
| H41 | S3b 14a.1 | QA-14a1-16: re-rendering a 100,000-character text takes ≈ 11 s (a design-canvas display clip is needed, as in the runtime) | M |
| H42 | S5 properties-save-load §196 | `Prop.ref`/`PagePlacement.image` are not renamed when a resource id changes. Pin that the guard blocks orphaning (unknown resource) | m |
| H43 | S3b 14p (pre-existing, untagged) | Cut is enabled on a selected window (Delete is not) | m |

### Performance group — after v1 by default (D2) (5)
Every gate is met today, so the budgets stay as regression tests. If a gate fails during 19a–19g, the item comes back.
| Id | Source | Summary | Sev |
|---|---|---|---|
| H44 | S3b Step 09 · S5 validate-commands §379/§539, runtime §547, dnd R4, ADR-006, ADR-010 | Scoped or incremental validation (an edit takes ≈ 75–80 ms on 2,000 widgets; the budget is 100) | P |
| H45 | S3b 13a · S5 dnd §147/§585, direct-manipulation §16, ADR-010 | Subtree rebuild / render budgets (0.66 s per edit at 200 widgets, 2.1 s at 1,000) | P |
| H46 | S3b 14b.1 | The rebuild after a size release takes ≈ 480 ms at 200 widgets vs 250 ms | P |
| H47 | S3b 15a | QA-15a-07: a dirty prepare takes 197 ms vs a 150 ms budget at 2,000 widgets | P |
| H48 | S3b 14b.2 | An unreadable include costs ≈ 1.8 ms per focus change | P |

### 19d — plugins and backends (21)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H49 | S2 M25 · S5 ADR-015:44 | Plugin abuse: raises on import, render or in a property setter; hangs; incompatible `api_version`; missing. Mostly pinned (17a–17c); 19d fills the gaps (setter raise, hang) | M |
| H50 | S5 ADR-014:35, backends §6 | Re-run B1–B16 in the Step 19 suite. backends §7 plans tests for B2–B5, B10–B12 (`tests/qt`) and B14/B1 (designer); audit all 16 and add the missing ones (likely B6–B9, B13, B15, B16) | M |
| H51 | S3 16c · S5 backends §14 | A handler hiding a dialog leaves the loop running with no window | D |
| H52 | S3 16c · S5 backends §14 | `_Collect.emit` in the preview child has no `handleError` | m |
| H53 | S3 16c · S5 backends §14 | Leading-zero integers in `_vars` read as decimal (Tcl 9 behaviour) | D |
| H54 | S3 16c · S5 backends §14 | Qt `key:` matching is exact (`<Control-s>` does not fire on Ctrl+Alt+S) | m |
| H55 | S3 16c · S5 backends §14 | A bound Combobox whose items are added later overwrites the variable | m |
| H56 | S3 16c · S5 backends §14 | A destroyed session's traces stay on its variables | m |
| H57 | S3 16c · S5 backends §14 | QA-16b-01 residual: on Windows, a platform plugin that fails to initialise hangs until the ready timeout | m |
| H58 | S3 16c · S5 backends §14 | QA-16b-01 residual: a set but unreachable `DISPLAY` aborts (crash dialog) | D |
| H59 | S5 plugins §14b | The Qt check does not verify that `inner` lies inside `outer` | m |
| H60 | S5 plugins §14b | The bootstyle-retry sweep cannot remove an `inner` created outside `parent` | m |
| H61 | S5 plugins §14b | An existing widget elsewhere in the window that is returned as `inner` is destroyed | M |
| H62 | S5 plugins §14b | The "fallback is shown" warning is logged before a destroyed-parent abort | m |
| H63 | S5 plugins §14b | A DateEntry bound variable holds ISO text, not text in `date_format` | D |
| H64 | S5 plugins §14b | There is no handle to reach the outer Tableview | D |
| H65 | S5 plugins §14b (l. 355) | A calendar-invalid DateEntry date is dropped at export without a Finding | m |
| H66 | S5 plugins §14c | A non-built-in entry point whose distribution is named `pyguibud` lands under the Built-in row | M |
| H67 | S5 plugins §14c | `.ui` files saved before the QA-17c-01 fix may carry a misdeclared `plugin=` (R87/R88 miss; R28 hints the wrong pip name) | m |
| H68 | S5 plugins §14c | The "cannot be drawn" card shows raw Tcl text when a factory destroys its parent | m |
| H69 | S5 plugins §14c | A Bootstyle value on a plugin widget that ignores it gives no R84 | m |

### 19e — CLI, messages and catalogues (15)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H70 | S3 18 · S6 | QA-18-04: argparse's own errors stay English. Strict xfail `tests/qa/test_step18_abuse.py::test_qa18_04_argparse_errors_are_translated` ×3 (`--bogus`, `--theme hell`, `--lang`) | m |
| H71 | S3 18 · S6 | QA-18-13: the French help section titles lack the NBSP before ":". Strict xfail `tests/qa/test_step18_abuse.py::test_qa18_13_french_help_section_titles_space_their_colon` ×2 (`pyguibud`, `uic`) | m |
| H72 | S3 18 | `preview/__init__.py` uses plain argparse instead of `PyGUIbudParser` | m |
| H73 | S3 18 | The runtime `check_lang` ValueError is English-only | m |
| H74 | S3 18 | A valid but wrong `Plural-Forms` gives no warning | m |
| H75 | S3 18 | Obsolete `#~` entries are kept in the `.po` files | m |
| H76 | S3 18 | Terminology drift: fallback (es/pt_BR/it), include (de/nl), the span label vs its hint, the sticky label vs its error | m |
| H77 | S3 18 | "Document > Delete window" uses ">" instead of "▸" | m |
| H78 | S3 18 | `_Preview` is one msgid for both the menu and the action (`pgettext`) | m |
| H79 | S3 18 | Literal key names inside msgids (F6, "Hold Ctrl…", Ctrl+E, Enter, F1–F24 in `_M_SHORTCUT_MODIFIER`). Move them into placeholders only | m |
| H80 | S3 18 | pt_PT leaves the inspector labels Fill/Expand in English (`inspector.py:137`, ordinary msgids, not enum names, so the Step 18 ruling does not apply). Translate them. This row is split out of the H76 drift note | m |
| H81 | S3 17a · S5 plugins §14a | Raw C0/C1/bidi controls in the designer status bar, `designer/export.py`, `designer/clipboard.py`, `Finding.__str__` and runtime strict-mode messages (the uic escaping is not shared) | m |
| H82 | S3 17a | "Opened with N warning(s)" is shown when the file has errors | m |
| H83 | S3 17a | Codegen warnings have no file prefix | m |
| H84 | S5 validate-commands §539 | A `--strict` / warnings-as-errors flag for `pyguibud-uic` → **after v1 by default** (D12: a scope addition, not hardening) | — |

### 19f — layout, accessibility, locales (12)
| Id | Source | Summary | Sev |
|---|---|---|---|
| H85 | S3 18 · S6 | QA-18-09: the F1 dialog is ≈ 1,100 px tall, so Close is off a 1080p screen. Strict xfail `tests/designer/test_qa18_abuse.py::test_qa18_09_cheat_sheet_fits_a_full_hd_screen` | M |
| H86 | S3 18 · S6 | QA-18-16: object-tree names are cut at 800×500 in translated locales. Strict xfail `tests/designer/test_qa18_abuse.py::test_qa18_16_object_tree_names_that_fit_in_english_fit_in_every_language` ×3 (fr_FR, de_DE, pt_PT) | m |
| H87 | S4 | The palette does not shrink back after leaving a long language → D4 | m |
| H88 | S4 | The canvas is only ≈ 114 px wide at the 800×500 minimum → D5 | M |
| H89 | S3b 15a | QA-15a-09: the Theme menu is a flat list of 48 items | m |
| H90 | S3b 14p | QA-14p-09: the focus ring changes colour only | m |
| H91 | S3b 14p | QA-14p-10: the error-card border vs the plate is < 3:1 in some themes (`error_border` derivation) | m |
| H92 | S3b 15b | QA-15b-14: a ≈ 4,000-character pasted path pushes the Export dialog buttons off-screen | m |
| H93 | S2 locales | All 8 locales + `en_XA`: no truncated labels, no untranslated strings, mnemonics unique per menu (re-run the Step 18 gates + screenshots) | M |
| H94 | S2 a11y | A keyboard-only walk-through of the main flows | M |
| H95 | S2 a11y | The high-contrast theme meets `assets/brand/docs/ACCESSIBILITY.md` | M |
| H96 | S2 M23 last bullet | Rapid double-clicks on every button; resizing the window to 1×1 px and to 8K | M |

### Totals
- **By primary source** (unique items):
  - S1+S2 rows: 15. These are H12–H16, H32–H36, H49 and H93–H96. All 6 S1 themes and all 14 S2 bullets are mapped.
  - S3: 29. The 18 note gives 13: its 12 listed items, with pt_PT Fill/Expand (H80) split out of the drift item. Then 17c 1, 17b 2, 17a 5, 16c 8.
  - S4: 3 (H01, H87, H88).
  - S3b: 34. 15b 13, 15a 4, 14b.2 4, 14b.1 2, 14p 5, 14a.1 1, 13b 2, 13a 1, Step 09 2; the 16b hang and Step 12 are merged into H03 and H09.
  - S5-only: 15. B1–B16 1, plugins §14b 7, §14c 4, validate-commands 2, properties-save-load 1.
  - S6: 0 new.
  - **Total: 96.**
- **Merges:**
  - S3: the 17c note points to §14c and the 17b note points to §14b; their items are counted once, under S3 or S5.
  - S5: of the 25 grep hits, 2 are excluded (§1), and the rest are either S5-only items or extra sources of S3/S3b rows.
- **S6: all 8 strict-xfail tests / 13 cases are mapped:**
  - H23 (1), H29 (1), H30 (1), H38 (1);
  - H70 (3), H71 (2);
  - H85 (1), H86 (3).
- **By part:** 19a 11 · 19b 20 · 19c 12 · perf 5 (D2) · 19d 21 · 19e 15 · 19f 12.
- **If the defaults are accepted:**
  - **84 items are built** in 19a–19f.
  - **6 are documented only (D3):** H28, H51, H53, H58, H63, H64. They are still owned by their part, at ≈ 0 lines.
  - **6 are deferred after v1:**
    - H44–H48, under D2;
    - H84, under D12.
- **Rule:** a part closes only when every strict xfail it owns has either lost its mark (fixed) or been turned into a passing test that pins a ruled behaviour (D10 b, D7 b).

## 3. Parts
Each part fits one session and has its own UAT. Each starts from a green suite, after the user writes "UAT 19x passed".

**For every part:**
- Any new or changed msgid is translated into all 7 locales **in the same part**: the TRANSLATOR (sonnet) runs `tools/po_roundtrip.py` dump/load/check, and the catalogue gates in `tests/test_catalogues.py` stay green.
- The `.pot` is regenerated only with the extract command in `docs/i18n/README.md`.
- QA (opus) adds `tests/qa/test_step19x_abuse.py` or `tests/designer/test_qa19x_abuse.py`, with strict xfails for open findings, and returns APPROVE/REJECT.
- No Tk test runs while another agent runs Tk tests, and no full suite runs while agents are editing.

**Estimates** are raw figures × 1.3 (the 16–17 calibration).

| Part | Scope (one line) | Agents (model) | Est. | Cap |
|---|---|---|---|---|
| **19a** | One shared Tk root + reset fixture for the whole suite; order-independent runs; flakes and test-time budget | TESTING (opus), DEBUGGER (opus) | ≈ 60 | 120 |
| **19b** | Files and I/O abuse matrix (open/save/recover/quit), 15b/15a residuals, settings merge, `tb` prefix | BACKEND (sonnet; opus for H24/H30/H31), FRONTEND (sonnet), QA, DEBUGGER | ≈ 480 | 600 |
| **19c** | Editing and model abuse (ids, values, cycles, storms, undo safety), the 14b residuals, the 100k-text freeze | FRONTEND (opus, canvas/DnD), BACKEND (sonnet, commands), QA, DEBUGGER | ≈ 380 | 450 |
| **19d** | Plugin/backend abuse (M25, B1–B16), 16c/17b/17c residuals, documented limits | BACKEND (opus), QA, DEBUGGER | ≈ 480 | 600 |
| **19e** | CLI and argparse i18n, message escaping, catalogue hygiene, terminology | FRONTEND (sonnet), BACKEND (haiku for the uic prefix), TRANSLATOR (sonnet), QA | ≈ 380 | 450 |
| **19f** | Layout at minimum size and on 1080p, palette/tree widths, a11y and locale sweep | FRONTEND (opus), TESTING (opus, real desktop), TRANSLATOR (haiku), QA | ≈ 380 | 450 |
| **19g** | The final break-it sweep across all parts: the consolidated UAT checklist and a full gate. Fixes only | QA (opus), DEBUGGER (opus), SCORER (haiku) | ≈ 120 | 250 |

Total: est. ≈ 2,280, caps 2,920. 19a goes first because every later gate depends on a stable, order-independent suite. 19b–19f may swap order; 19g is always last.

### 19a — Test-infrastructure stability (H01–H11)
- **Scope:**
  - A top-level `tests/conftest.py` owns **one** session root for every Tk package. `tests/runtime` and `tests/designer` request it instead of creating their own.
  - It provides a `reset_root` helper/fixture: deiconify → `geometry("")`/set size → `update_idletasks` → withdraw; destroy stray toplevels; `option clear`; i18n reset.
  - The H01 helpers move onto it.
  - H02/H03 are bisected and fixed. H04: an autouse i18n reset in `tests/qa`. H05: `FakeProcess` moves into a shared helper module.
  - H06: budget tests skip under `--cov` (`sys.gettrace()`/`--cov` marker), and the scorer counts only ✅.
  - H07/H08: root-cause or quarantine with a reason. H09: trim or mark `slow`. H10: `best_of` + a factor. H11: a fix in `dispose()` if it stays under 20 lines, otherwise documented.
- **Acceptance:**
  - `pytest -p no:randomly tests/runtime tests/designer tests/codegen`, `tests/runtime tests/codegen` and `tests/designer tests/runtime` all finish green with no hang (add `pytest-timeout` per test = 120 s in CI only if already a dev dependency; otherwise a watchdog in the conftest);
  - one full run with `-p randomly` (seeded, seed recorded) is green;
  - the full suite gives ≥ 5,763 passed, 1 skipped, 13 xfailed;
  - `tests/designer` is ≤ 12 s.
- **UAT:**
  1. `uv run pytest tests/runtime tests/designer -q -p no:randomly` finishes.
  2. `uv run pytest tests/runtime tests/codegen -q -p no:randomly` is green.
  3. The full suite is green.
- **Cap 120.** **Trims:** T1 H11 is only documented · T2 H09 marks subprocess tests `slow` instead of speeding them up · T3 the H06 scorer fix moves to Step 20 · T4 H07 is quarantined with a reason.

### 19b — Files and I/O abuse (H12–H31)
- **Scope:**
  - An end-to-end matrix test (designer `open`/`save` + `pyguibud-uic --check` + `load_ui`) over H12–H16. Disk full and the external lock are simulated with monkeypatched `os.replace`/`open` raising `OSError(ENOSPC)`/`PermissionError(32)`. External change is detected by the stamp → "changed on disk" prompt (exists since 14a; verify).
  - Real-process kill → recovery (one subprocess test, `slow`).
  - Logout: `WM_SAVE_YOURSELF`, where the platform supports it, routes to the unsaved guard. Otherwise it is documented.
  - H17–H27: the minimal fixes. H23: the temporary name no longer grows with the target name (`~pgb<8 hex>.tmp` in the same folder).
  - H24: every `mkdtemp` goes through `core/atomic`. H28 and H31 per D3 / reader cap. H29 per D8. H30 per D9.
- **Acceptance:**
  - every M24 case is refused or handled with a translated reason in < 1 s, with no traceback, no `.tmp` left behind, and the original plus `.bak` intact;
  - the strict xfails H23, H29 and H30 are flipped.
- **UAT (break it):**
  1. Open an empty file, a renamed `.png`, a half-truncated `hello.ui` and a 50 MB file of `<a>` → each is refused with a reason.
  2. Make a `.ui` read-only, edit it, Ctrl+S → refused; Save As works.
  3. Edit, then kill the process in Task Manager → restart offers recovery.
  4. Edit, then try X, Alt+F4 and File ▸ Quit → each asks to save.
  5. Open two designers, disable acme in one, quit the other → acme stays disabled.
  6. Save a file whose name has 250 characters.
- **Cap 600.** **Trims:** T1 H22 accepted and documented · T2 H27 documented (keep the mtime check) · T3 H18 becomes a warning, not a rule · T4 H30 reader warning only (no writer rename) · T5 logout handling documented only.

### 19c — Editing and model abuse (H32–H43)
- **Scope:**
  - Property tests (hypothesis) that drive `CommandStack` with random command sequences, including the M23 values. Invariant: after every step, `dump_ui` succeeds, `validate` gives no new errors, and undo-all returns the start document byte-identically.
  - GUI tests for the ids, drop and paste paths. H36: a 1,000× undo/redo storm.
  - H37: `Macro.revert` and the stack become transactional. On an exception, each command compensates its own partial work and the stack reports `command.undo_failed`, which is a new msgid; if the document still differs from its form before the step, the history is cleared (`command.history_cleared`) and the document stays dirty (ruling 2026-10-18).
  - H38 per D10. H39/H40: the minimal guards (block palette insertion while a resize or drag is active). H41: clip display texts on the design canvas, as the runtime does (`runtime.text_clipped`). H42: a pin test. H43: Cut is disabled on a window.
- **Acceptance:**
  - 500 hypothesis examples with no invariant break;
  - the M23 matrix is green;
  - 100k text: re-render ≤ 1 s;
  - the strict xfail H38 is resolved.
- **UAT (break it):**
  1. Rename a widget to `class`, `1abc`, `a-b`, `ａｂｃ` (full-width) and a 10,000-character id → each is refused with a reason.
  2. Drag a Frame into its own child, and in the tree → refused.
  3. Paste a page of random text, then a broken `<widget>` XML, onto the canvas → refused, no change.
  4. Hold Ctrl+Z, then Ctrl+Y, for 10 s → no freeze, and the document matches.
  5. Delete a variable that is bound → refused (or remove-and-unbind).
  6. Paste 100,000 characters into a Label text → the canvas stays responsive.
- **Cap 450.** **Trims:** T1 H43 · T2 H39 (cosmetic) · T3 H40 keeps only the palette-insert block · T4 D10 → (b).

### 19d — Plugins and backends (H49–H69)
- **Scope:**
  - H49: tests for a fake plugin that raises in a property setter and one whose import sleeps. The latter is covered by safe mode + the D7 note; there is no timeout, as the Step 17 ruling says.
  - H50: an audit table that maps each of B1–B16 to a test; the missing ones are added.
  - Code fixes: H52, H55, H56, H57 (the preview ready timeout reports `runtime.no_display`-style text), H59–H62, H65 (a Finding at export), H66 (built-in = the value prefix **and** the entry-point group check), H67 (R87/R88 fall back to the registry's real distribution for the class prefix), H68 (a translated card reason), H69 (R84 for an ignoring plugin when its spec has no bootstyle). H54: Qt `key:` matches modifiers like Tk, if it stays under 40 lines.
  - Documented limits (D3), written into a new `docs/specs/runtime.md` §"Known limitations": H51, H53, H58, H63, H64.
- **Acceptance:**
  - every B case and every M25 case is pinned;
  - with `ACME_PYGUIBUD_BREAK=import|spec|factory|exit` and the new `setter`, the designer keeps running;
  - the parity tests are unchanged.
- **UAT (break it):**
  1. `uv pip install -e examples/acme_plugin`, then each `ACME_PYGUIBUD_BREAK` value → a placeholder, Help ▸ Plugins shows Failed, no crash.
  2. Preview ▸ Toolkit ▸ PySide6 with `QT_QPA_PLATFORM=bogus` → a translated reason within the timeout.
  3. Open `examples/acme_demo.ui` without acme → a warning only.
  4. `uv pip uninstall acme-pyguibud` afterwards.
- **Cap 600.** **Trims:** T1 H54 documented · T2 H59–H60 keep only H61 (data loss) · T3 H64 documented (`ui.<id>.master.master`) · T4 H69 dropped · T5 H57 documented.
- **As built (2026-10-18):** 253 / 600 net src lines (plus 18 in acme). Only **T4** applied (H69 dropped: plugin factories receive `bootstyle` and may honour it; pinned "no R84"). Fixed: H49 (`ACME_PYGUIBUD_BREAK=setter`; plugin text slots guarded on retranslate, `_M_TEXT_FAILED`), H52, H54, H55, H56, H57, H59–H62, H65–H68; the Qt eventFilter line was a raising `key:` handler (now `sys.excepthook`). H50 audit: `docs/specs/backends-audit-19d.md` (QA-19d-01: the mixed-toolkit warning once per Tk root). Documented in runtime.md §16: H51, H53, H58, H63, H64. QA REJECT (1 major) → QA-19d-02…09 fixed (fr NUL byte + new control-character catalogue gate; translator comments; H67 never overrides a correct declared `plugin=`; Qt Backtab; bound Combobox across `clear()`/removals; Qt sweep keeps stolen/pre-existing widgets; `QT_QPA_PLATFORM` parsed as Qt does). Details: plugins.md §14d, backends.md §14.

### 19e — CLI, messages and catalogues (H70–H84)
- **Scope:**
  - H70/H71 per D7. H72: the preview child uses `PyGUIbudParser`. H73: `check_lang` raises with a translated message (the ValueError text goes through `_()`).
  - H74: `tests/test_catalogues.py` compares each locale's `Plural-Forms` with a CLDR table for the 8 locales (test-only), and `i18n.load_catalogue` logs a mismatch.
  - H75 per D11. H76: a terminology pass over the glossary terms (TRANSLATOR; glossary updated). H77: "▸". H78 per D13. H79: placeholders.
  - H81: one shared `core.text.printable()` (the C0/C1/bidi escape already used by uic), used by the five outputs. H82: "Opened with N error(s)", with its own plural msgid. H83: a `{file}:` prefix.
- **Acceptance:**
  - the strict xfails H70 and H71 are resolved;
  - the catalogue gates are green in 8 locales;
  - `rg -n "Ctrl\+|F6|Enter" src --type py` shows no literal key names inside msgids (allow-list for comments);
  - the forged-line tests pass for the designer status bar, clipboard and export.
- **UAT (break it):**
  1. `$env:PYGUIBUD_LANG="de_DE"; uv run pyguibud --bogus` → a German error.
  2. With `fr_FR`, `uv run pyguibud --help` → "options :" with the NBSP.
  3. Open a `.ui` with an id holding U+202E (provided fixture) → the status bar shows it escaped.
  4. Open a file with errors → "Opened with … error(s)".
  5. Switch to each language and read Document ▸ Delete window and the Preview menu.
- **Cap 450.** **Trims:** T1 H78 (pgettext) · T2 H74 becomes a test-only check (no runtime log) · T3 H83 · T4 D7 → (b) for H70 (keep H71).
- **As built (2026-10-18):** 323 / 450 net src lines. Only **T2** applied (H74 is a test-only CLDR `Plural-Forms` table in `tests/test_catalogues.py`; all 7 headers matched). H84 stays after v1 (D12). H70/H71 per D7 (a): `pyguibud/_argparse.py` (new; shared by `cli`, `uic` and the preview child, which must not import `pyguibud.cli` — ADR-007/013 boundary) binds argparse's `_`/`ngettext` to ours while a `PyGUIbudParser` works (thread-safe swap, QA-19e-03); `_ARGPARSE_MSGIDS` marks the 3.10–3.13 union; a feature-tested `_Section` translates the hard-coded heading colon on interpreters before 3.11.9/3.12.3 (verified on a real 3.10.22, QA-19e-02); on the same interpreters `ArgumentError`'s "argument X: " prefix is re-translated in `PyGUIbudParser.error` (feature test). H72 the preview child pre-selects `--ui-lang` before building its parser (QA-19e-06). H73 `check_lang` translated. H75 `--ignore-obsolete` (434 `#~` entries purged; README updated). H76 terminology pass + glossary. H77 `Windows are deleted with {path}.` built from the real menu labels. H78 `NC_("menu"|"action", "_Preview")`. H79 key names in placeholders. H80 pt_PT Preencher/Expandir. H81 `core.text.printable()` (C0, DEL/C1, bidi embeddings/isolates, U+2028/9, LRM/RLM/ALM) used by uic, `Finding.__str__`, `UiError.__str__`, the status bar, export, clipboard messages, the object tree and inspector finding rows (display only, QA-19e-08). H82 `Opened with {count} error(s).` H83 `{file}:` prefix; codegen no longer logs the bad-date warning a second time (QA-19e-05). obs-2: a `TclError` in `runtime.build_failed` gets a generic translated reason (original as `__cause__`). Attribution ruling: `credits.credit()` in `--help` epilogs, `--version` (never wrapped, QA-19e-07) and the new Help ▸ About PyGUIbud dialog. QA REJECT (1 blocker: QA-19e-02) → QA-19e-01…08 fixed. UAT fixture `tests/data/hardening/bidi_id.ui`.

### 19f — Layout, accessibility, locales (H85–H96)
- **Scope:**
  - H85 per D6. H86–H88 per D4/D5: one width policy for the side panels at the minimum size. H89: the Theme menu grouped by light/dark (ttkbootstrap's `type`). H90: a focus ring with thickness + colour (2 px outline). H91: `error_border` derived to ≥ 3:1 against the plate. H92: elide the path in the dialog field display, with buttons in a fixed row.
  - H93–H95: the TESTING agent runs a real-desktop sweep (screenshots × 9 languages × 3 themes at 800×500 and 1920×1080) and a keyboard-only script.
  - H96: a 1×1 and an 8K geometry, plus a double-click storm on every toolbar/dialog button, with no crash and no duplicate dialogs.
- **Acceptance:**
  - the strict xfails H85 and H86 are resolved;
  - canvas ≥ the D5 floor at 800×500 in every locale;
  - every dialog fits 1366×768;
  - contrast gates are green in the 3 themes;
  - one modal at a time under a storm.
- **UAT (break it):**
  1. Shrink to the minimum in de_DE, fr_FR, pt_PT and en_XA → the canvas is usable and no palette or tree name is cut without a tooltip.
  2. Switch de_DE → en_GB → the palette shrinks back (D4).
  3. Press F1 on a 1080p screen → Close is visible.
  4. Unplug the mouse: create, edit, save and preview a form with the keyboard only.
  5. Use the high-contrast theme, with Tab focus visible everywhere.
  6. Double-click every toolbar button fast → one dialog at most.
- **Cap 450.** **Trims:** T1 H89 · T2 H90 · T3 H91 · T4 D4 → shrink applied at the next start only.

### 19g — Final sweep and gate
- **Scope:**
  - QA runs the whole S2 checklist again on the integrated build (real desktop, all locales), plus the B, P and M tables.
  - The DEBUGGER fixes any blockers.
  - The SCORER refreshes the dashboard.
  - The orchestrator merges the per-part UATs into one "try to break it" checklist (≤ 20 lines) for the row 19 UAT.
- **Acceptance:**
  - zero open blockers or majors;
  - every strict xfail is resolved (expected **0 xfailed** unless a ruling keeps one; the count of kept ones is stated);
  - full suite, mypy and ruff are green.
- **UAT:** the consolidated checklist.
- **Cap 250** (fixes only; the trim is to defer a minor to after v1 with the user's consent).

## 4. Decisions for the user (recommended default in **bold**)
| ID | Question | Options |
|---|---|---|
| D1 | Split and order | **(a) seven parts 19a–19g as in §3 (caps 120/600/450/600/450/450/250), 19a first, 19g last** · (b) fold 19g into 19f (saves a session, no integrated sweep) |
| D2 | Performance group H44–H48 (scoped validation, subtree rebuild, 480 ms / 197 ms / 1.8 ms) | **(a) after v1, unless a budget gate fails in 19a–19g. Every current gate is met (an edit is 75–80 ms vs 100); the budgets stay as regression tests** · (b) an extra part 19h "performance" (≈ 700 lines, its own UAT) |
| D3 | Platform limits that cannot be fixed cheaply: H28 symlink→UNC, H51 a hidden dialog keeps the loop, H53 leading zeros, H58 unreachable `DISPLAY`, H63 DateEntry ISO var, H64 the outer Tableview handle | **(a) document them in `docs/specs/runtime.md` "Known limitations" (later copied into the user docs in Step 21)** · (b) fix each (≈ +250 lines, mostly 19d) |
| D4 | Palette width after leaving a long language (H87) | **(a) recompute on every language/theme switch: width = max(fit width of the current language, the width the user set by dragging the sash). An auto-grown width therefore shrinks back, and a user-set width is kept** · (b) never shrink (today) · (c) shrink only at the next start |
| D5 | The canvas at the 800×500 minimum (H88, also fixes H86) | **(a) keep 800×500 and give the canvas a floor of 280 px. The side panels give way in the order palette (names elide, with a tooltip), inspector, tree; the tree name column keeps priority over its detail column** · (b) raise the minimum to 1024×600 (smaller laptops then cannot shrink the window) · (c) accept as is (remove the xfail; ids are cut) |
| D6 | The F1 shortcuts dialog on 1080p (H85) | **(a) cap the dialog at 85 % of the screen's work area; the body scrolls, and Close stays outside the scroll area** · (b) two columns (still too tall in de/nl) |
| D7 | argparse's own messages (H70, H71) | **(a) `PyGUIbudParser` translates them: argparse's msgids (≈ 20) join our catalogue, and its `_`/`ngettext` are bound to ours while parsing; section titles use a translated "{title}:" msgid (fr NBSP)** · (b) accept English argparse errors; the xfails become pinning tests and the limitation is documented |
| D8 | Two designers write `settings.json` (H29) | **(a) on save, re-read the file and apply this instance's `disabled_plugins` toggles as a delta (recent files are merged the same way)** · (b) file locking · (c) document "last one wins" |
| D9 | `xmlns:tb` bound to a foreign URI (H30) | **(a) the writer always binds `tb` to the ttkbootstrap namespace and renames a foreign `tb` prefix (`ns1`); the reader warns once (new msgid). No schema change; ADR-002 addendum** · (b) reader warning only |
| D10 | QA-14b2-14 (H38) | **(a) fix: "after" a tall sibling places the block below the sibling's whole area (one `_make_room` change)** · (b) keep it as accepted on 2026-10-11; the xfail becomes a passing test that pins the behaviour, plus a note in the spec |
| D11 | Obsolete `#~` entries (H75) | **(a) purge them now that all 7 locales are at 100 % (`pybabel update --ignore-obsolete`, then the round-trip check; the purge is reviewed in the diff before the user commits)** · (b) keep them |
| D12 | `--strict` flag for `pyguibud-uic` (H84) | **(a) after v1 (a scope addition, not hardening)** · (b) add it in 19e (≈ 30 lines + 2 msgids) |
| D13 | `_Preview` menu vs action (H78) | **(a) add `pgettext` (`i18n.pgettext`, the Babel keyword `pgettext:1c,2`, and the extract command in `docs/i18n/README.md`)** · (b) leave one msgid |
| D14 | Minor behaviour changes that the fixes bring (beyond D4/D5/D9/D10). Each is a refusal or wording change with no format change:<br>• H23 the temp-name scheme;<br>• H37 the `command.undo_failed` refusal;<br>• H41 canvas text clipping;<br>• H43 Cut disabled on a window;<br>• H65/H66/H67/H69 new or corrected findings and plugin rows;<br>• H81 escaped control characters in the status bar, clipboard and export;<br>• H82 "Opened with … error(s)" | **(a) accept them as a batch now; QA lists each one in its part report** · (b) rule on each at its part's UAT |

## 5. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | 19a changes fixture scope and breaks many tests at once | Land the shared root behind one fixture name and migrate package by package; run each package alone, then the pairs |
| R2 | The hypothesis command storms (19c) find guard holes beyond the cap | Strict xfail + a QA id; the DEBUGGER fixes blockers first; minors go to 19g or after v1 with the user's consent |
| R3 | Real-desktop sweeps (19f) interfere with the user's desktop | The rules from the 14a/15a incidents: a dedicated window, no OS-level keystrokes outside the designer, screenshots only |
| R4 | The D11 purge loses entries that exist only in the uncommitted tree | Purge only after the user commits Step 18 |
| R5 | The budget baseline is ambiguous while Step 18 is uncommitted | §1 rule; each handover records the numstat |
| R6 | D7 (a): argparse's msgids differ across Python versions (`requires-python >= 3.10`; e.g. "options" vs "optional arguments", and the error wording changed in later releases) | Catalogue the msgid union for 3.10–3.13; the H70/H71 tests read the msgids from the running `argparse` at test time; the CI matrix covers the lowest and highest versions |

## 6. Affected documents (on acceptance)
- `DEVELOPMENT_PLAN.md` row 19: the split 19a–19g with caps; §5 kickoff → 19a.
- `docs/specs/runtime.md`: "Known limitations" (D3).
- ADR-002: an addendum if D9 (a). `docs/i18n/README.md`: the extract command if D13 (a).
- `docs/specs/designer-shell.md`: the panel width policy (D4/D5).
- The specs that defer to Step 19 (validate-commands §539, dnd-selection §13, plugins §14b/§14c, backends §14) get "→ hardening.md Hxx" pointers in 19g.
