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
| 11 | Code generator `pyguibud-uic` | BACKEND | `codegen/`, CLI, `--extract` `.pot` | `pyguibud-uic examples/hello.ui -o hello.py` → `python hello.py` works **without** pyguibud installed | 🔄 |
| 12 | Designer shell | FRONTEND | Main window: palette, canvas, inspector, object tree, SAPÉ theme, language menu, templates wizard, keyboard navigation | `uv run pyguibud` launches; switch language and theme live | ⏳ |
| 13 | Drag-and-drop & selection | FRONTEND (opus) | DnD from palette, move/resize, multi-select, snapping | Build a small form by dragging; move/resize widgets | ⏳ |
| 14 | Properties, undo/redo, save/load | FRONTEND + BACKEND | Inspector editors, events & variables panels, menu editor, multi-window, copy/paste, autosave + crash recovery, unsaved-changes guard | Edit → save → close → reopen: identical; Ctrl+Z/Ctrl+Y work | ⏳ |
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

## 5. Next session kickoff (after Step 10 UAT)

> *"Resume PyGUIbud development at Step 11: Code generator `pyguibud-uic` (`codegen/`, CLI, `--extract` `.pot`). Inspect DEVELOPMENT_PLAN.md §5 (kickoff + notes), project.md, docs/adr/ (ADR-001..007), docs/specs/runtime.md (§2 pinned `UiScope`/`LoadedUi` API that codegen must reproduce), validate-commands.md, xml-io.md, the `ui-schema-rules` skill and .claude/ in D:\Coding\SAPE\PyGUIbud_CLAUDE. Step 10 UAT passed. Verify the baseline with `uv sync`, `uv run python -m pytest` and `uv run python tools/scorer.py`. Act as the orchestrator: architect specifies the generated-module shape (same public surface as `load_ui`: one attribute per id, `.vars`, `.widgets`, `.windows`, `retranslate`/`show`/`run`/`destroy`; handlers called with no arguments; text clipping at `MAX_TEXT_LENGTH` and liveness → `runtime.destroyed`), the generated code depends only on tkinter/ttkbootstrap (NOT on pyguibud), deterministic output (golden files), `--extract` producing a `.pot` for a `.ui` (msgctxt, comments), and Step 11 reserved ids that clash with generated code; backend implements; testing adds golden + run-without-pyguibud tests (clean venv); QA abuse pass (code injection via ids/texts/handler names into generated Python!). UAT: `pyguibud-uic examples/hello.ui -o hello.py` → `python hello.py` works without pyguibud installed. Refresh the scoreboard at the end. Do not commit."*

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
