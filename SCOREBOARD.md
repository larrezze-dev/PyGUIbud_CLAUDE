# PyGUIbud scoreboard

_Last updated: 2026-10-15 19:10:58 UTC+0200_

- **Steps done:** 18/23
- **Current step:** 17 Widget plugin API + ttkbootstrap extensions (🧪)
- **Tests:** 5287/5300 passed (gate figures 2026-10-15, pytest not run by scorer)
- **Coverage:** 91.1 %
- **Test detail:** 5300 collected, 0 failed, 0 errors, 13 skipped, 0.00 s

## Quality gates

| Check | Result |
| --- | --- |
| Lint (ruff) | passed: ruff check + ruff format clean (gate 2026-10-15) |
| Types (mypy) | passed: mypy clean, 287 files (gate 2026-10-15) |
| i18n coverage | 123/779 ≈ 15 % per locale (estimate, gate 2026-10-15) |

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
| 17 | Widget plugin API + ttkbootstrap extensions | ARCHITECT + BACKEND (opus) + FRONTEND | 🧪 awaiting UAT |
| 18 | Translations (7 languages) | TRANSLATOR + QA | ⏳ pending |
| 19 | QA hardening ("idiot-proof") | QA + DEBUGGER | ⏳ pending |
| 20 | Packaging & release candidate | DEPLOYER | ⏳ pending |
| 21 | Documentation & launch | LAME-CULOS | ⏳ pending |

## Recent commits

- `e6ae6b7 010`
- `dfee602 009`
- `f5f5af9 008`
- `2621983 007`
- `ff016eb 006`
