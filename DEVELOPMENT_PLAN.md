# PyGUIbud — Development Plan

Each step = **one chat session**. Rules (from CLAUDE.md): watch context continuously, wrap up at **60–65 %**, start no new feature after **55 %**. Every session ends with `pytest` green (once code exists) and the **Session Handover Briefing**.

Status legend: ✅ done · 🔄 in progress · ⏳ pending

| # | Step | Lead agent(s) | Key deliverables | Done when | Status |
|---|------|---------------|------------------|-----------|--------|
| 01 | Concept, stack, license, agents | ORCH + ARCHITECT | `project.md`, this plan, `assets/brand/` | User approves stack/license/agent table | 🔄 |
| 02 | Feature spec (conversation with user) | ARCHITECT | `FEATURES.md` (MoSCoW), widget list v1, `.ui` schema draft, ADR-001..003 | Features signed off | ⏳ |
| 03 | Agent definitions & skills | ORCH | `.claude/agents/*.md` (10 agents, models per §4 of project.md), skills, `LICENSE`, `CONTRIBUTING.md` | Each agent invocable; dry-run delegation works | ⏳ |
| 04 | Repo scaffold | DEPLOYER + BACKEND | `pyproject.toml` (hatchling, extras), `uv.lock`, ruff/mypy/pre-commit, GH Actions matrix, `src/pyguibud/`, `src/pyguibud_runtime/` | `uv run pytest` green on smoke test; `pip install -e .` works | ⏳ |
| 05 | Core widget model | BACKEND | `core/model.py` (Widget, Property, Layout), `core/registry.py` (entry points) | ≥90 % coverage on model | ⏳ |
| 06 | `.ui` XML schema + I/O | BACKEND | `core/schema/` (XSD/JSON-Schema), `core/xml_io.py`, versioning/migration hook | Round-trip tests + invalid-file rejection | ⏳ |
| 07 | Validator & command stack | BACKEND | `core/validate.py` (rules), `core/commands.py` (undo/redo, guards) | Hypothesis fuzz: no invalid model reachable | ⏳ |
| 08 | Runtime loader + ttkbootstrap backend | BACKEND | `pyguibud_runtime.load_ui()`, `backends/ttkbootstrap.py` | Example `.ui` opens a real window (headless test) | ⏳ |
| 09 | Codegen (`pyguibud-uic`) | BACKEND | `codegen/` → standalone `.py`, CLI | Generated code runs + `ruff check` clean, no pyguibud import | ⏳ |
| 10 | Designer shell | FRONTEND | Main window: palette, canvas, inspector, object tree, SAPÉ theme | App launches, screenshots in `docs/` | ⏳ |
| 11 | Drag-and-drop & selection | FRONTEND (opus) | DnD from palette, move/resize, multi-select, snapping | TESTING drives it via computer control | ⏳ |
| 12 | Property editing, undo/redo, save/load | FRONTEND + BACKEND | Inspector editors, keyboard shortcuts, dirty-state guard | Edit → save → reload identical | ⏳ |
| 13 | Preview & export | FRONTEND | Live preview window, Export `.py` dialog | Preview == runtime output | ⏳ |
| 14 | tkinter + PySide6 backends | BACKEND | `backends/tkinter.py`, `backends/pyside6.py` (extra `[pyside]`) | Same `.ui` renders in 3 toolkits | ⏳ |
| 15 | QA hardening ("idiot-proof") | QA + DEBUGGER | Abuse-case suite: corrupt files, absurd values, cyclic parents, unsaved-quit, read-only paths | All abuse cases blocked gracefully | ⏳ |
| 16 | SCORER dashboard | SCORER | `SCOREBOARD.md` + HTML dashboard (progress, coverage, open bugs) | Auto-updates from plan + pytest/coverage | ⏳ |
| 17 | Packaging & release | DEPLOYER | Build wheels/sdist, TestPyPI, `pip install` + `uv add` + `uvx pyguibud` verified | Clean-venv install on 3 OSes in CI | ⏳ |
| 18 | Docs & launch | LAME-CULOS | README with GIFs, docs site, release notes, announcement drafts | User approves and publishes | ⏳ |

## Next session kickoff (Step 02)
> *"Resume PyGUIbud development at Step 02: Feature spec. Inspect DEVELOPMENT_PLAN.md and project.md in D:\Coding\SAPE\PyGUIbud_CLAUDE. Interview me to define v1 features (MoSCoW), the v1 widget list and the `.ui` schema draft; write FEATURES.md and ADRs."*
