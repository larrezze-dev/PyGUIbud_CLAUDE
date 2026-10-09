# PyGUIbud — Project Proposal & Development Plan

> Open-source drag-and-drop GUI designer for Python. Design visually, save a `.ui` file, then **load it at runtime** or **export plain `.py`**.
> Targets: **ttkbootstrap** (first), **tkinter**, **PySide6** (optional extra). Multilingual from day one.
> Diagrams: see [project.md](./project.md) (Mermaid). Brand: `assets/brand/` (copied SAPÉ corporate identity).

---

## 0. Ground rules (from CLAUDE.md)

| Rule | How this plan applies it |
| --- | --- |
| **Step by step, every step tested by the user** | Each step has a **User Acceptance Test (UAT)**: concrete commands/actions the user runs. The next step does not start until the user reports *UAT passed*. |
| **One step = one chat session** | Steps are sized for one session; each ends with the *Session Handover Briefing* + kickoff prompt. |
| **Context limits** | Monitor continuously; wrap up at 60–65 %; no new feature after 55 %. |
| **Git: the AI never commits or pushes** | The agent only edits files. At the end of each step it proposes a commit message; **the user commits/pushes manually**. |
| **Multilingual** | Source language **British English (en-GB)** for code, UI, comments, identifiers and docs. Mandatory translations: **es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL, fr-FR**. |
| **Brand reference** | Files from the SAPÉ identity folder are **copied** into `assets/brand/`, never linked, edited or deleted at source. |

---

## 1. Stack

| Layer | Choice | Rationale |
| --- | --- | --- |
| Language | Python ≥ 3.10 | Modern typing and pattern matching; runs on Windows, macOS and Linux |
| Designer UI | **ttkbootstrap** (dogfooding) | Lightweight, pip-only, same toolkit we target first |
| Core model | Pure-Python dataclasses, **toolkit-agnostic** | Backends never leak into the model, which keeps forks cheap |
| `.ui` format | XML with `schema_version`, validated (XSD / JSON-Schema) | Diff-friendly, familiar to Qt users, stdlib `xml.etree` only |
| Extensibility | `importlib.metadata` **entry points**: `pyguibud.backends`, `pyguibud.widgets` | Forks/plugins add toolkits or widgets without touching the core |
| **i18n** | stdlib **`gettext`** + **Babel** (extract/compile `.po`→`.mo`), CLDR locale data | Standard, translator-friendly (Weblate/Crowdin/Poedit), no runtime dependency beyond stdlib |
| Packaging | `pyproject.toml` + **hatchling**, managed with **uv**; extras `[pyside]`, `[dev]` | Installs with both `pip install` and `uv add` / `uvx` |
| Quality | pytest (+ pytest-xvfb in CI), hypothesis, ruff, mypy `--strict` on core, pre-commit | Standard tools, so contributors already know them |
| CI/CD | GitHub Actions matrix (Win/macOS/Linux × py3.10–3.13), PyPI trusted publishing | No secrets in the repo |
| Theming | SAPÉ tokens → ttkbootstrap custom theme (light / dark / high-contrast) | Corporate look that can still be swapped |

**Distributions** (one repo):
- `pyguibud`: designer app + CLI (`pyguibud`, `pyguibud-uic`).
- `pyguibud-runtime`: tiny loader (stdlib + chosen toolkit). This is what end users ship.

### 1.1 Multilingual design
- **Designer**: every user-facing string goes through `_()`; catalogues live in `src/pyguibud/locale/<lang>/LC_MESSAGES/pyguibud.po`. Language selection: OS locale, then setting, then `--lang` flag, with a live switch from the menu.
- **Generated GUIs**: `.ui` text properties carry `translatable="true"` + optional `context`/`comment`. `pyguibud-uic` emits `_()` calls, and `load_ui(..., translator=gettext.translation(...))` translates at load time. `pyguibud-uic --extract` produces a `.pot` for the user's own app.
- **Locale codes**: `en_GB` (source), `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`.
- **Quality gates**: test that all 7 catalogues are 100 % translated and placeholders match; **pseudo-locale** (`en_XA`, +40 % length) to catch layouts that break with long German/Dutch strings; British spelling check (`colour`, `licence`, `behaviour`…) in code review.

---

## 2. Licence

**MIT** (accepted, Step 03). Name and SAPÉ brand assets are excluded, see `NOTICE.md`. Permissive and fork-friendly; generated `.ui`/`.py` files belong entirely to the user. "Acceptable forks" are handled by `CONTRIBUTING.md` + a short **name/trademark note**: forks may not be distributed as "PyGUIbud" without the creator's consent.
Alternative: **Apache-2.0** if an explicit patent grant is wanted.
PySide6 (LGPL) is imported dynamically from the user's environment, which is compatible with MIT.

---

## 3. Agents & models

Defined in `.claude/agents/*.md`, with shared skills in `.claude/skills/` (Step 03). The model shown is the **default**: the ORCHESTRATOR weighs each delegated task and moves the model up or down (Agent `model` override; rules in `.claude/skills/orchestration/`). A normal session already acts as the orchestrator via `CLAUDE.md`. `claude --agent orchestrator` is optional: it enforces the agent's rules but replaces Claude Code's default system prompt.

| Agent | Default | Up / down | Responsibilities |
| --- | --- | --- | --- |
| ORCHESTRATOR | user-selected | n/a | Delegates, integrates, **only agent that reports to the user**, runs the UAT gate |
| SOFTWARE-ARCHITECT | opus | n/a | Specs, ADRs, schema, review |
| BACKEND-DEVELOPER | sonnet | ↑ opus: schema/codegen design · ↓ haiku: boilerplate | Core, I/O, runtime, codegen |
| FRONTEND-DEVELOPER | sonnet | ↑ opus: DnD/canvas engine · ↓ haiku: styling | Designer UI, theming, i18n wiring |
| TRANSLATOR (sub-role of FRONTEND) | sonnet | ↓ haiku: catalogue sync | `.po` files for 7 languages, glossary |
| DEBUGGER | opus | never downgraded | Root-cause analysis, fixes |
| TESTING | sonnet | ↑ opus: flaky/GUI tests | pytest, hypothesis, computer/GUI control, screenshots |
| QA | opus | n/a | "Idiot-proof" abuse scenarios, every locale, accessibility, computer control |
| SCORER | haiku | ↑ sonnet: dashboard build | Progress dashboard from plan + tests + coverage |
| DEPLOYER | sonnet | n/a | Build, TestPyPI/PyPI, pip + uv verification |
| LAME-CULOS (promoter) | sonnet | n/a | README, release notes, announcements; **user approves before anything goes public** |

---

## 4. Development plan

Status: ✅ done (UAT passed) · 🧪 awaiting user UAT · 🔄 in progress · ⏳ pending

| # | Step | Lead | Deliverables | User Acceptance Test (UAT) | Status |
|---|------|------|--------------|-----------------------------|--------|
| 01 | Proposal: stack, licence, agents, i18n | ORCH + ARCHITECT | This file, `project.md`, `assets/brand/` | Read this file; check the Mermaid diagrams render in `project.md`; approve or change stack / licence / agents / languages | ✅ |
| 02 | Feature specification (interview) | ARCHITECT | `FEATURES.md` (MoSCoW), v1 widget list, `.ui` schema draft, ADR-001…005 (`docs/adr/`) | Review `FEATURES.md` + ADRs; tick the sign-off list | ✅ |
| 03 | Agents, skills, licence files | ORCH | `.claude/agents/*.md` (11), `.claude/skills/*/SKILL.md` (13), `LICENSE` (MIT), `NOTICE.md` (name + brand carve-out), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` | Restart Claude Code → `/agents` lists 11 project agents; ask for a dry-run delegation; read LICENSE/NOTICE/CONTRIBUTING | ✅ |
| 04 | Repository scaffold | DEPLOYER + BACKEND | `pyproject.toml`, `uv.lock`, ruff/mypy/pre-commit, CI workflow, `src/pyguibud/`, `src/pyguibud_runtime/` | `uv sync` · `uv run pytest` green · `uv run pyguibud --version` · `pip install -e .` in a clean venv | ✅ |
| 05 | SCORER dashboard (early, for tracking) | SCORER | `tools/scorer.py` → `SCOREBOARD.md` + `scoreboard.html` (steps, tests, coverage) | `uv run python tools/scorer.py`; open the HTML and see Steps 01–04 | ✅ |
| 06 | i18n infrastructure | FRONTEND + BACKEND | `pyguibud/i18n.py`, Babel config, `en_GB` catalogue, 7 locale stubs, pseudo-locale, catalogue tests | `uv run pyguibud --list-languages` shows 8 languages · `--lang en_XA` shows pseudo-strings | ✅ |
| 07 | Core widget model | BACKEND | `core/model.py`, `core/registry.py` (entry points) | `uv run pytest tests/core` green; coverage ≥ 90 % in report | ✅ |
| 08 | `.ui` XML schema + I/O | BACKEND | `core/schema/`, `core/xml_io.py`, translatable strings, migration hook | Open `examples/hello.ui` in an editor; corrupt it → `pyguibud-uic --check` rejects it with a clear message | ✅ |
| 09 | Validator & command stack | BACKEND | `core/validate.py`, `core/commands.py` (undo/redo, guards) | Run the provided demo script: invalid operations are blocked with reasons | ✅ |
| 10 | Runtime loader + ttkbootstrap backend | BACKEND | `pyguibud_runtime.load_ui()`, `backends/ttkbootstrap.py` | `uv run python examples/run_hello.py` opens a real window, also with `--lang de_DE` | ✅ |
| 11 | Code generator `pyguibud-uic` | BACKEND | `codegen/`, CLI, `--extract` `.pot` | `pyguibud-uic examples/hello.ui -o hello.py` → `python hello.py` works **without** pyguibud installed | ✅ |
| 12 | Designer shell | FRONTEND | Main window: palette, canvas, inspector, object tree, SAPÉ theme, language menu, templates wizard, keyboard navigation | `uv run pyguibud` launches; switch language and theme live | ✅ |
| 13 | Drag-and-drop & selection (13a + 13b) | FRONTEND (opus) | Spec `docs/specs/dnd-selection.md`, ADR-010 (Accepted). **13a Canvas engine & insertion:** `_tk.py` embed mode + parity tests, design mode, overlay, palette drag + Enter insertion, hover `check()`, single selection, Edit ▸ Undo/Redo/Delete, QA-12-13 hint, tree highlight, mypy clean. **13b Rearrange & multi-select:** move/reorder/reparent, grid-span resize, cell/slot snapping, multi-select, rubber band, keyboard move, tree Alt+Up/Down | Two UATs (spec §15): 13a build a small form by dragging + undo; 13b move/resize/multi-select widgets | ✅ (13a UAT 2026-10-07 · 13b UAT 2026-10-08) |
| 14a | Properties, undo/redo, save/load (functional) | FRONTEND + BACKEND | Spec `docs/specs/properties-save-load.md`, ADR-011 (Proposed). Inspector editors + multi-edit, events & variables panels (rename / remove-and-unbind macros), menu editor, multi-window management, copy/paste, open/save/recent + CLI `.ui`, autosave + crash recovery, unsaved-changes guard, settings store, tree drag-and-drop, external `<include>` rendering. Proposed as two halves 14a.1 "Files and properties" / 14a.2 "Structure" (spec D1) | Edit → save → close → reopen: identical; Ctrl+Z/Ctrl+Y work (spec §19, per half) | 🔄 14a.1 ✅ (UAT 2026-10-08) · 14a.2 ⏳ |
| 14p | Designer visual polish | FRONTEND | Canvas look, panels & spacing/typography, inspector look, iconography. A dedicated pass after the functional Step 14a (user feedback at 13b UAT: "the UI is still very primitive"): SAPÉ tokens applied consistently to the stage, window chrome, selection and drop indicators; panel headers, padding and type scale; inspector rows, sections and editor states; a small consistent icon set for toolbar, palette and tree. Spec written at the start of the step; no model or file-format changes | User judges the look in the 3 themes + `en_XA` | ⏳ |
| 15 | Preview & export | FRONTEND | Live preview window, Export `.py` dialog | Preview matches the exported `.py` when run | ⏳ |
| 16 | tkinter + PySide6 backends | BACKEND | `backends/tkinter.py`, `backends/pyside6.py` (`[pyside]`) | Same `.ui` renders in the 3 toolkits | ⏳ |
| 17 | Widget plugin API + ttkbootstrap extensions | ARCHITECT + BACKEND (opus) | `pyguibud.widgets` entry points, `WidgetSpec`, isolation/placeholder, diagnostics panel, `tb:` Meter/Floodgauge/DateEntry/Tableview/ToggleButton with fallbacks, sample plugin `examples/acme_plugin` | `pip install -e examples/acme_plugin` → widget appears in palette; break it on purpose → placeholder, designer keeps running; open the `.ui` with tkinter backend → fallbacks render | ⏳ |
| 18 | Translations (7 languages) | TRANSLATOR + QA | Complete `.po` for es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL, fr-FR; glossary | Switch through every language; spot-check the strings you know; no truncated labels | ⏳ |
| 19 | QA hardening ("idiot-proof") | QA + DEBUGGER | Abuse suite: corrupt files, absurd values, cyclic parents, quit unsaved, read-only paths, huge files | Try to break it yourself using the provided checklist; every bad action is blocked gracefully | ⏳ |
| 20 | Packaging & release candidate | DEPLOYER | Wheels/sdist, TestPyPI, install docs; split `pyguibud_runtime` into the standalone `pyguibud-runtime` distribution (until then it ships inside the `pyguibud` wheel; afterwards `pyguibud` depends on it and drops it from its own wheel) | In a clean venv: `pip install -i <TestPyPI> pyguibud` · `uv tool install` · `uvx pyguibud` | ⏳ |
| 21 | Documentation & launch | LAME-CULOS | README (en-GB + language links), GIFs, docs site, release notes, announcement drafts | Approve texts; **you** commit, tag and publish | ⏳ |

### Step lifecycle
1. Session starts from the kickoff prompt and verifies the current state (`pytest` once code exists).
2. Agents implement the step; TESTING runs automated tests.
3. ORCHESTRATOR hands over the **UAT** instructions + a **proposed commit message**.
4. **User** runs the UAT and commits manually. The next step starts only after the user reports *UAT passed*.

---

## 5. Next session kickoff (Step 14a.2: Structure — only after "14a.1 UAT passed")

> *"Resume PyGUIbud development in D:\Coding\SAPE\PyGUIbud_CLAUDE at Step 14a.2 "Structure" (spec `docs/specs/properties-save-load.md` §§6, 7, 8, 13; ADR-011 Accepted). Act as the orchestrator (load skills orchestration + pyguibud-ground-rules). Precondition met: "14a.1 UAT passed" (2026-10-08). **Ask the user for the B1 budget choice first (recommended: b) and STOP until answered.** Verify the baseline: `uv sync`, `uv run python -m pytest -q -p no:randomly` (expect 3544 passed, 1 skipped, 7 xfailed), `uv run mypy` (clean, 185 files), `uv run ruff check .`, `uv run ruff format --check .`, `uv run python tools/scorer.py`. Then delegate 14a.2: in-place menu editor (§6, D9), window management + Ctrl+PageUp/PageDown (§7), copy/cut/paste/duplicate with the `.ui`-text clipboard and id renaming (§8, D3/D4), object-tree drag-and-drop and external `<include>` rendering (§13), applying the budget decision B1. Then testing → QA → debugger → UAT 14a.2. Watch context: no new feature after 55 %, wrap up at 60–65 %. Never commit."*

**14a.1 UAT (2026-10-08):** user wrote "UAT passed"; **B1 = (b)** (2026-10-08): trim items 1–2 applied — §13.1 tree drag-and-drop (Alt+Up/Down kept) and §13.2 external `<include>` rendering (placeholder kept) leave 14a.2; Step 14 cap ≈ 4,050 → ≈ 750 lines for 14a.2 (menu 200, windows 150, clipboard 380). Destination step of the trimmed items: open (user to decide).

**If UAT 14a.1 reports failures:** fix them first (debugger → regression test → user re-check) before starting 14a.2. The user pastes the B1 choice together with "14a.1 UAT passed".

**Step 14a.1 session (2026-10-08):** baseline 3165/7 → **3544 passed, 1 skipped (POSIX FIFO), 7 xfailed**; mypy clean (185 files); ruff + format clean; coverage 93.3 %. User decisions: polish → new plan row **14p** (canvas look, panels & spacing, inspector, iconography); **D1–D12 all defaults** (spec §20; ADR-011 Accepted; FEATURES M3 amended: font editor after v1). Delivered: pure `settings.py`, `files.py`, `recovery.py`, `properties.py`, `screen.py`, `core/colours.py`; `CommandStack(dirty=)`; session path/stamp/read-only/dirty/title; inspector editors + multi-edit + Reset + `flush()`; Events tab; Variables tab (rename / remove-and-unbind macros); File menu (New/Open/Open recent/Save/Save As/Close/Recover…/Quit), CLI positional `.ui`, unsaved-changes guard, autosave 60 s + start-up recovery dialog, settings persistence (language, theme, sashes, geometry incl. multi-monitor, recent files). Debugger fixes: builders ignore properties a class does not define (Notebook `text` crash in canvas, runtime and codegen); autosave skips the flush while typing; multi-monitor geometry. QA: pass 1 REJECT (majors 01–06: Tk grid limit 9998, colour names, dark-start spinbox, Ctrl+Z in Variables/Events, restored-snapshot stamp, mixed "…" dialog), all fixed + minors 07–15; pass 2 **APPROVE**, its minors 18–22 fixed. Deferred: QA-14a1-16 (100k-char text re-render ≈ 11 s) → Step 19; QA-14a1-17 recovery dialog path column → 14p. Open risks: picking "(none)" in a mixed image/variable combobox does nothing; restore of a deleted file gives no status notice; real-key Ctrl+Tab not verified by automation (UAT). Incidents: QA sent OS-level keystrokes in two probes (possibly a stray Tab to the terminal; stopped) and one native Save As dialog may have flashed; two sub-agents hit the API usage limit and were resumed.
**B1 budget (answered (b), 2026-10-08):** 14a.1 ≈ 3,300 logical production lines vs its ≈ 2,490 share; ≈ 300 of the 3,600 cap remain for 14a.2, which needs ≈ 1,110. Options: (a) raise the Step 14 cap to ≈ 4,400; (b) apply trim items 1–2 (external include rendering, tree DnD) → cap ≈ 4,050; (c) (b) plus trim items 3–6.

**13b UAT (2026-10-08):** user reported the UAT tests passed; feedback "UI is still very primitive" (carried into Step 14 kickoff). Budget overshoot (≈3,350 vs 3,200) and loss of keyboard window-tab switching accepted by default (not objected to).

**Step 13b session (2026-10-07/08):** baseline 3047/7 → **3165 passed, 7 xfailed**; mypy clean (158 files); ruff + format clean; parity tests green, no diff in `backends/_tk.py` / `designer/targets.py`. Delivered (3 frontend/opus delegations): `editing.py` pure builders (`move_command`, `move_index`, `nudge_command`, `resize_command`, `resize_cell`, `span_rect`, `past_the_grid`, `delete_command(*nodes)`); `session.select_many` (last occurrence = primary); drag-move/reparent/multi-move through the shared target/check/execute path (`Moving` payload); grid-span resize handles on all 4 edges + cell-grid overlay; Ctrl/Shift-click, rubber band; canvas focus proxy = scroll-host canvas with scoped keys (Tab/Shift+Tab, Enter, Esc, arrows, Shift+arrows, Ctrl+A, Delete); Edit ▸ Move submenu; tree extended selection + Alt+Up/Down; multi-count status line + inspector header; multi-delete as one undo step; R-D empty-container outline (`DESIGN_AFFORDANCES` + "empty-container-outline", ADR-010 Addendum 3). 35 new msgids translated in 7 locales. Orchestrator rulings recorded in the spec: multi-move (§8, D4 clarification); page placement kept only between same-kind page containers; keyboard grid bound (§7.3, one cell past the other children — the mouse may still walk outward one append line per gesture, accepted); band-vs-move on a selected container (§7.2); Delete once per physical key press (§11). QA: pass 1 REJECT (majors 01–05), pass 2 REJECT (major 10), pass 3 **APPROVE**; all of 01–05, 09–12 fixed with regression tests in `tests/designer/test_qa13b_abuse.py`. **Open for the user:** (a) **Step 13 budget overshoot**: production code ≈ 3,350 lines vs the raised cap of 3,200 (+≈150; nothing trimmed — the trim order would drop the rubber band first) — accept or ask for a trim; (b) keyboard switching between canvas window tabs is gone (one tab stop; use the object tree); (c) X11 Shift+Tab (`ISO_Left_Tab`) falls back to normal traversal. Deferred: QA-13b-08 localised key names in accelerators → Step 18; faint-ish grid lines in light theme accepted (4.07:1); multi-select inspector header makes the tree jump 23 px (cosmetic); intermittent focus skip at `tests/designer/test_qa13a_abuse.py:207` in full runs (environmental) → Step 19; designer Tk tests over the §13 time budget → Step 19. Step-14 cautions from the debugger: any message posted on file open must come after the selection is set; non-action command paths must post `""` on success or go through `Shell._invoker`. Incidents: a testing sub-agent ran `git stash` + immediate `pop` (verified intact, stash list empty); sub-agent hit an API session limit and was resumed.

**Step 13b kickoff (2026-10-07):** user wrote "13a UAT passed"; ADR-010 Addenda 1–2 acknowledged; answers: (a) Step 13 budget **raised to ≤ 3,200** production lines (spec §0); (b) QA-13a-14 → **add** design-only dashed outline for empty unselected containers (spec §5.4 R-D, ADR-010 Addendum 3). Baseline re-verified: 3047 passed, 7 xfailed; mypy clean (151 files); ruff clean.

**Step 13a session (2026-10-07):** baseline 2863/7 → **3047 passed, 7 xfailed** (only the Step-18 catalogue xfails); `uv run mypy` clean (151 files); ruff + format clean. Delivered: `_tk.py` embed mode (+51 net lines, `embed=None` unchanged, codegen untouched) + `TtkbootstrapBackend.build_embedded`; `_load._prepare()` split; pure `render_plan`, `geometry`, `targets`, `editing`, `edit` (PURE_MODULES); `designer/canvas/{engine,design,overlay,drag}.py`; stage canvas panel; palette drag + Enter/double-click insertion; single selection synced canvas↔tree↔inspector↔status; Edit ▸ Undo/Redo/Delete (`ActionDef.scope/alt_shortcuts/dynamic_label/refusal`); QA-12-13 hint; `Designer.Treeview` max-contrast selected rows; 22+2 new msgids translated in 7 locales. Parity tests (§4) green for all 5 examples. ADR-010 **Addendum 1** (parity readings, bindtags without "all", ScrolledFrame `bind_class` leak) and **Addendum 2** (`DESIGN_AFFORDANCES`: empty-minimum-size, append-zone-padding, paned-append-pane; spec §5.4) — both pending user acknowledgement at UAT 13a. QA: pass 1 REJECT (blocker QA-13a-01 mid-drag re-render + unreachable targets 02–04), all fixed; pass 2 APPROVE, its 7 findings fixed. Also fixed: palette/tree idle jobs leaking past dispose, flaky timing tests (`tests/designer/conftest.best_of`), flaky `test_property_strategy_actually_exercises_the_interesting_cases` (derandomised). **Open for the user:** (a) Step 13 production budget exceeded (spec §0: ≤1,800; actual ≈2,150 so far) — raise it for 13b or apply the §0 trim order; (b) QA-13a-14 empty unselected Frame is invisible (no border) — add a design-only dashed outline in 13b (needs §5.4 change)?; (c) perf: real edit cycle 0.66 s at 200 widgets, ~2.1 s at 1,000 (render budgets per §13 deferred to Step 19). Incident: a testing sub-agent ran a broad `taskkill` on python.exe (believed to have matched nothing).

**Step 13 spec session (2026-10-06):** baseline 2863 passed / 7 xfailed; mypy carry-over cleared (`uv run mypy` → Success, 133 files; only `tests/` touched). Architect wrote `docs/specs/dnd-selection.md` and `docs/adr/ADR-010-canvas-engine-dnd.md`; corrected stale entries in `docs/specs/designer-shell.md`. **User decisions D1–D10: all defaults** (D1 = B split 13a/13b; D2 grid spans only; D3 snap to cells/pack slots, no pixel grid/guides — plan's "grid size, guides" dropped, ADR-005 unchanged; D4 multi-select = select/delete/move within one parent; D5 rubber band, full containment; D6 Undo/Redo + Delete brought forward from Step 14; D7 Enter/double-click on palette inserts, focus stays on palette; D8 tree Alt+Up/Down now, tree DnD → Step 14 (FEATURES M1 part); D9 solid primary fill for selected rows; D10 arrows move the widget, Tab walks the selection). Architect risks to honour (spec §14): `enable_traversal()` leak in embed mode, selection not pruned on stack events, listeners must not re-enter `CommandStack` (`_Busy`), builder assumes valid documents (lenient embed-only lookups), ScrolledFrame vs design-mode bindtags (check ttkbootstrap 2.2.3), selected-row contrast fails in **all 3** themes (confirm with `theme.contrast()`).

**Step 12 closed (2026-10-06):** final check passed (QA-12-09 Alt mnemonics in en_XA, QA-12-10 ellipsis + full text in status bar, QA-12-12 en_XA hidden from View ▸ Language; QA-12-11 covered by tests). User wrote "UAT passed". New minor **QA-12-14** (fix in Step 13): `tests/designer/test_theme.py:272` reads `sape.json` at import time, so a missing file aborts the whole collection (exit 2) instead of failing one test. **Fixed the same day** (test reads the file inside the test body).

**Brand application icon (2026-10-06, user request after Step 12 UAT):** `assets/brand/logo/pyguibud.png` (32 px) is copied by `tools/gen_themes.py` to `designer/themes/pyguibud.png` (drift-checked by `--check` and a test; NOTICE §2). Pure `theme.load_app_icon()` (missing/defective → None, logged once) + `app.apply_app_icon(root)`: `iconphoto(True, PhotoImage(data=…))` so every designer window and dialog uses it, image kept on the root, own Windows AppUserModelID `SAPE.PyGUIbud.Designer`. Fallback: ttkbootstrap's default icon. `scoreboard.html` gets it as an inline favicon (`tools/scorer.py`). Not applied to runtime/codegen windows (user apps, NOTICE §3). Console-script `.exe` launchers from pip/uv cannot carry an icon. Only 16/32 px sources exist → Alt-Tab/HiDPI look soft; a larger PNG (e.g. 256 px) in `assets/brand/logo` would fix that.

**Minor fixes (2026-10-06, frontend/sonnet; 2854 passed, ruff clean):** QA-12-09 `i18n._PROTECTED` keeps `__`/`_x` mnemonic unaccented; QA-12-10 pure `present.fit_text()` + `TreePanel(on_full_text=)` ellipsis re-fitted on `<Configure>`/render; QA-12-11 `theme._warn_once` (missing and defective each log once per process); QA-12-12 en_XA menu item only registered when the start language is en_XA (residual: stays until restart after switching away). Carry-over: `uv run mypy` → 23 errors, all in `tests/` (codegen, designer, runtime), `src/` clean.

**Step 12 UAT checklist (for the user):**
1. `uv run pyguibud` opens the designer (palette · canvas · inspector · object tree · status bar). View ▸ Theme: Light / Dark / High contrast switch live. View ▸ Language: en_XA (pseudo) switches live; other languages show mostly English (D6, translations in Step 18).
2. `uv run pyguibud --lang en_XA --theme high-contrast`: no truncated labels.
3. Click nodes in the object tree: canvas card, inspector and status bar follow.
4. Ctrl+N → the wizard: Up/Down + Enter creates a document from one of 5 templates; Esc cancels and returns focus.
5. F6 / Shift+F6 cycle the 4 panels with a visible blue ring in all 3 themes; F1 shows the shortcut sheet; Ctrl+Q quits.
6. Drag every sash to its limits: panel headings stay visible.
7. Dark theme → Ctrl+N ▸ Login form → select `ent_username`: inspector "(default)" rows readable.
8. Ctrl+C in the launching console closes the window within ~1 s.
9. `uv run pyguibud --lang xx`, `--theme purple`, `foo.ui` → usage error, exit 2, no window. `uv run pyguibud --version` and `--list-languages` still work.

**UAT results (2026-10-06):** items 1–9 all passed. User decisions: SAPÉ colour substitutions below **approved**; minors QA-12-09/10/11/12 fixed before closing Step 12; QA-12-13 → Step 13. New findings: **QA-12-12** en_XA pseudo-locale visible in View ▸ Language confuses users → hide it from the menu (still available via `--lang en_XA`); **QA-12-13** clicking a palette item gives no feedback → status-bar hint "Drag … onto the canvas" (Step 13); object-tree selected row highlight is faint in the light theme (Step 13 polish); sash positions / window geometry not persisted → Step 14 settings store (with D7).

**SAPÉ colour substitutions (approved 2026-10-06)** (`tools/gen_themes.py` falls back to the `.hover` token when the `.solid` one fails 4.5:1 against the white ttkbootstrap paints on buttons): light success `#178A5A`→`#117047`, light warning `#B86B00`→`#985700`, dark primary `#3F6DFF` (4.34:1) → its `.hover` token. Check `src/pyguibud/designer/themes/sape.json` for the exact dark/hc values taken.

**Notes carried from Step 12 (spec `docs/specs/designer-shell.md`, ADR-009 Accepted, user decisions 2026-10-06):**
- D2 = A: generated `designer/themes/sape.json` ships in wheel/sdist, listed as all rights reserved in NOTICE §2; neutral MIT themes `pyguibud-light/dark/hc` are the fallback; drift test vs `assets/brand` (`tools/gen_themes.py --check`). D4: designer themes are chrome-only, never written to `.ui` (FEATURES Theme row reworded); Step 15 preview must run in a subprocess (single ttkbootstrap root). D6: no translations until Step 18 (new msgids untranslated; catalogue sync done). D7: language/theme persistence → Step 14 settings store.
- CLI: no args → designer; `--theme light|dark|high-contrast`; `main(argv, *, launch=)` seam; no display/Tk → exit 1; no positional `.ui` until Step 14.
- Architecture: pure modules (`session`, `signals`, `actions`, `standard_actions`, `theme`, `present/*`) never import Tk (subprocess test `PURE_MODULES`); thin views in `shell.py`, `panels/*`, `dialogs/*`; one app-level i18n listener; theme switch coalesced via `after_idle` (`flush_theme()` for tests); `ModalDialog` base, one modal at a time.
- Canvas is a placeholder Notebook (D1). `backends/_tk.py:175-180` builds windows as Toplevels when given a master → Step 13 needs an embed mode (+ parity tests).
- Panel order for F6: palette → canvas → tree → inspector (spec §3.3).
- Tests: one package-scoped shared root in `tests/designer/conftest.py`; `tests/designer` takes ~18 s (over the §8 budget of 8 s; 3.7 s are two subprocess Ctrl+C tests) — trim in Step 19. Full suite ~110–120 s.
- Open minors: **QA-12-09** en_XA accents mnemonic letters (Alt+F, N fails in pseudo-locale; fix in `i18n.py` pseudo-translation); **QA-12-10** object-tree detail column clips long en_XA text (no ellipsis/h-scroll); **QA-12-11** deleted `sape.json` is not logged (spec §9 says "logs once"); Windows menubar stays light in dark theme (platform limit); real-console Ctrl+C not verified by automation.

**Notes carried from Step 11 (spec `docs/specs/codegen.md`, ADR-008 Accepted, decisions 2026-10-06):**
- C1–C8 accepted with defaults: support block copied from `codegen/_support.py` + straight-line build; Tk mapping shared via `backends/_tkmap.py` (parity tests `tests/codegen/test_parity.py` are mandatory for any `_tk.py`/`_tkmap.py` change); `setup_ui(self, master=None, handlers=None, *, strict, lang, localedir, translator)`; own `UiError(RuntimeError)` with runtime codes (en-GB); locale dir stored relative to the generated file (`realpath(__file__)`; cross-drive output → copy `locale/` or pass `localedir=`); no `en_XA` in generated code; version line normalised in goldens, no POT-Creation-Date; images embedded base64 (binary P5/P6 only); `--stubs` deferred to Step 15.
- Orchestrator decision: a dialogs-only file with `master=None` → `setup_ui` refuses (`runtime.no_main_window`) like `load_ui`; the module's `__main__` preview uses a hidden root instead.
- QA-11-03 (user decision): UNC/device paths are rule **R82 `validate.network_path`**, an error everywhere and never opened; absolute/`..` resources stay warnings for `--check`/`load_ui`, but generation refuses them unless `--force`. New **R81 `bad_source_locale`**. `--force` never allows writing over an input/included `.ui` (any alias, incl. `\\?\` and hard links) or a device; `--extract -o` refuses a `.po` or any translated catalogue unless `--force`.
- Image probe (shared by validator, `load_ui`, codegen): PNG chunks + CRC + IHDR fields + PLTE + one complete zlib IDAT stream (bounded); PPM/PGM P5/P6 with full pixel data; GIF header only (Tk loads truncated GIFs).
- Goldens: `tests/codegen/data/*.golden`, regenerate with `PYGUIBUD_REGEN_GOLDEN=1`; `examples/hello_ui.py` drift test (regenerate with `uv run pyguibud-uic examples/hello.ui -o examples/hello_ui.py --force`; excluded from ruff). Clean-venv test is `@pytest.mark.slow` and runs by default (needs uv + network on a cold cache).
- Open minors: GIF structure not validated; symlink→UNC untested (no privilege); POSIX FIFO/device branch untested on Windows; `.po` files carry one empty fuzzy plural entry (harmless); the full suite now takes ~100 s.
- New public surface to keep stable: `pyguibud.codegen` (`generate_python(allow_outside=)`, `extract_pot`, `default_output`, `GeneratedModule.sources`, `GENERATED_MARKER`, `FORMAT`, `support_text`), `i18n.LANGUAGE_CODE_RE`, `core.files.is_network_or_device_path`/`is_device_name`/`WINDOWS_DEVICE_NAMES`/`probe_bytes`.
**Notes carried from Step 10 (spec `docs/specs/runtime.md`, ADR-007 Accepted, decisions 2026-10-06):**
- U1–U6 accepted with the architect's defaults **(the orchestrator applied them during the unattended run, so the user must confirm or revert at UAT)**: `validate(..., files=FileAccess|None)` (command guards never pass it); reserved ids (R69) enforced now; `pyguibud-uic --check` runs the file rules; `ttkbootstrap>=2.2,<3` (legacy `flatly` theme kept); same-file include `src="#"`; images PNG/GIF/PPM/PGM only, no Pillow.
- New rules R49–R53 (includes), R69–R80; R79 `text_too_long` (`MAX_TEXT_LENGTH = 100_000`), R80 string var default ≤ 10,000; widget `width`/`height`/`length` ≤ 10,000; new read error `xml.not_a_file`.
- Accepted trims: no dialog button bar (`show()` only deiconifies, returns `None`); no Alt bindings for Button/Checkbutton/Radiobutton (underline shown only). Revisit in Step 14/15.
- Runtime clips display texts > 100,000 chars (`runtime.text_clipped`, logged once per slot); `retranslate` is atomic (snapshot/restore); `Session.alive()` → `runtime.destroyed` after the window is closed.
- pytest runs with `--capture=sys` (fd capture leaves stale Tcl std handles on Windows → random empty `TclError` on `image create photo -file`). Product risk: an app that `dup2`s fd 1/2 after Tk starts could hit the same; consider `PhotoImage(data=…)` in Step 11/16 (check Tk 8.6 `-data` for PPM/PGM).
- Open minors: `load_ui` with a non-str translator gives `runtime.build_failed` while `retranslate` gives `TypeError` (inconsistent); per-slot clipping only (a `.mo` could still produce many large slots); example prints `UiError` to a cp1252 pipe may raise `UnicodeEncodeError`.
- `tests/core/test_validate.py` perf test budget: 2.0 s, ×3 under coverage.
- `backends/ttkbootstrap.py` shows ~72 % line coverage because its own-root paths run in subprocess tests.

**Notes carried from Steps 07–08:**
- Core model spec: `docs/specs/core-model.md`; XML I/O spec: `docs/specs/xml-io.md`. `tb:` extension specs are deferred to Step 17. Built-in widgets come from the `pyguibud.widgets` entry point `core` (re-run `uv sync` after any entry-point or script change).
- Step 09 must reject an empty `display_name` in plugin specs.
- The XML reader is registry-free and does no semantic checks: duplicate ids across nodes, the main-window count, container/layout/page rules and bind/variable types all belong to the Step 09 validator. It does reject per-owner duplicates (props, resources, variables, placements) because the model would lose them.
- Comments and processing instructions in `.ui` files are dropped on save with the warning `xml.discarded_content` (user decision, 2026-10-05).
- A document read from a newer MINOR version keeps that `schema_version`, and the writer refuses to save it (read-only).
- `.gitattributes` forces `*.ui` to LF; golden files live in `tests/core/data/xml_io/`.
- Open question for Step 20: `pyguibud-runtime` must not depend on `pyguibud`, but `pyguibud.core` (now including the XML reader) imports `pyguibud.i18n`.

**Notes carried from Step 09 (spec `docs/specs/validate-commands.md`, ADR-006, decisions 2026-10-05):**
- **Step 10 owns the include checks:** file existence, "the target is a `kind="component"` window", the same-file spelling and cycles (codes `validate.include_*`, R49–R53 reserved). It also owns image file existence, the `buttons` value grammar, and the Action `shortcut` attribute-vs-property overlap.
- **Step 11:** reserved ids that clash with generated code (`vars`, `setup_ui`…).
- **Steps 13–14:** new windows and containers carry `DEFAULT_LAYOUT` (a layout is always required; commands never invent one); DnD hover uses `CommandStack.check()`; `break_merge()` on editor commit; "remove and unbind" and "rename variable" macros.
- **Step 17:** `WidgetSpec.bind_types` (until then extensions use their fallback's bind row), `tb:` attribute validation, `SetExtraAttr`.
- **Step 19:** scoped validation — since the QA fixes the guard runs validate (before + after) plus a `dump_ui` safety net (`command.unsaveable`): ~75–80 ms per edit on 2,000 widgets (budget 100 ms), and `check()` (DnD hover) pays the same. `undo`/`redo` have no revert-on-failure if a `revert()` raises halfway.
- Menubar/Statusbar passed to `SetField`/`InsertNode` are attached as deep copies (no cross-document aliasing).
