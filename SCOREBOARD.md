# PyGUIbud scoreboard

_Last updated: 2026-10-14 23:36:00 UTC+0200_

- **Steps done:** 18/23
- **Current step:** 17 Widget plugin API + ttkbootstrap extensions (🔄)
- **Tests:** 5134/5146 passed (verified gate 2026-10-14, run by the orchestrator, not by the scorer: 5134 passed, 1 skipped, 11 xfailed in 711.63 s)
- **Coverage:** not available
- **Test detail:** 5146 collected, 0 failed, 0 errors, 12 skipped, 711.63 s

## Quality gates

| Check | Result |
| --- | --- |
| Lint (ruff) | passed: `ruff check .` all checks passed; `ruff format --check .` 325 files formatted |
| Types (mypy) | no issues in 278 source files |
| i18n coverage | n/a (later step) |

## Steps

| # | Step | Lead | Status |
| --- | --- | --- | --- |
| 01 | Proposal: stack, licence, agents, i18n | ORCH + ARCHITECT | ✅ done |
| 02 | Feature specification (interview) | ARCHITECT | ✅ done |
| 03 | Agents, skills, licence files | ORCH | ✅ done |
| 04 | Repository scaffold | DEPLOYER + BACKEND | ✅ done |
| 05 | SCORER dashboard (early, for tracking) | SCORER | ✅ done |
| 06 | i18n infrastructure | FRONTEND + BACKEND | ✅ done |
| 07 | Core widget model | BACKEND | ✅ done |
| 08 | .ui XML schema + I/O | BACKEND | ✅ done |
| 09 | Validator & command stack | BACKEND | ✅ done |
| 10 | Runtime loader + ttkbootstrap backend | BACKEND | ✅ done |
| 11 | Code generator pyguibud-uic | BACKEND | ✅ done |
| 12 | Designer shell | FRONTEND | ✅ done |
| 13 | Drag-and-drop & selection (13a + 13b) | FRONTEND (opus) | ✅ done |
| 14a | Properties, undo/redo, save/load (functional) | FRONTEND + BACKEND | ✅ done |
| 14p | Designer visual polish | FRONTEND | ✅ done |
| 14b | Direct-manipulation sizing & structure | FRONTEND + BACKEND | ✅ done |
| 15 | Preview & export | FRONTEND + BACKEND | ✅ done |
| 16 | tkinter + PySide6 backends | BACKEND + FRONTEND | ✅ done |
| 17 | Widget plugin API + ttkbootstrap extensions | ARCHITECT + BACKEND (opus) + FRONTEND | 🔄 in progress |
| 18 | Translations (7 languages) | TRANSLATOR + QA | ⏳ pending |
| 19 | QA hardening ("idiot-proof") | QA + DEBUGGER | ⏳ pending |
| 20 | Packaging & release candidate | DEPLOYER | ⏳ pending |
| 21 | Documentation & launch | LAME-CULOS | ⏳ pending |

## Recent commits

- `dfee602 009`
- `f5f5af9 008`
- `2621983 007`
- `ff016eb 006`
- `0685c94 005`
