# PyGUIbud scoreboard

_Last updated: 2026-10-18 08:55:09 UTC+0200_

- **Steps done:** 20/23
- **Current step:** 19 QA hardening ("idiot-proof") (🔄)
- **Tests:** 6108/6118 passed (gate figures 2026-10-18, pytest not run by scorer)
- **Coverage:** not available
- **Test detail:** 6118 collected, 0 failed, 0 errors, 10 skipped, 0.00 s

## Quality gates

| Check | Result |
| --- | --- |
| Lint (ruff) | passed: ruff check + ruff format clean (gate 2026-10-18) |
| Types (mypy) | passed: mypy clean, 307 files (gate 2026-10-18) |
| i18n coverage | 799 msgids, 7 locales at 100 % (gate 2026-10-18) |

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
| 17 | Widget plugin API + ttkbootstrap extensions | ARCHITECT + BACKEND (opus) + FRONTEND | ✅ done |
| 18 | Translations (7 languages) | TRANSLATOR + QA | ✅ done |
| 19 | QA hardening ("idiot-proof") | QA + DEBUGGER | 🔄 in progress |
| 20 | Packaging & release candidate | DEPLOYER | ⏳ pending |
| 21 | Documentation & launch | LAME-CULOS | ⏳ pending |

## Recent commits

- `4449d7d 015`
- `26262ad 014`
- `67125cc 013`
- `067483d 012`
- `2da74d8 011`
