---
name: scoreboard
description: How the PyGUIbud SCORER builds and refreshes the progress dashboard (SCOREBOARD.md + scoreboard.html) from the development plan, tests and coverage. Use when reporting project progress or updating the dashboard.
---

# Scoreboard

## Sources (read-only)
- `DEVELOPMENT_PLAN.md` §4 table: step number, name, lead and status emoji (✅ done · 🧪 awaiting UAT · 🔄 in progress · ⏳ pending).
- `uv run pytest -q --junitxml=.scorer/junit.xml --cov --cov-report=json:.scorer/coverage.json` (once code exists).
- `uv run ruff check . --statistics`, `uv run mypy src/pyguibud/core` (error counts).
- i18n: `pybabel compile --statistics` (translated % per locale).
- `git log --oneline` (read-only) for the timeline.

## Outputs (`tools/scorer.py`, from Step 05)
- `SCOREBOARD.md`: steps done/total, the current step, tests passed/failed, coverage %, lint/type errors, translation % per locale, last updated.
- `scoreboard.html`: a self-contained page (inline CSS/JS, no CDN) using SAPÉ colours, with light/dark support, a progress bar, step timeline, test/coverage tiles and a locale table.
- `.scorer/` is gitignored; the two outputs are committed by the user.

## Rules
- Deterministic and fast (< 10 s without tests). Never modify the plan or the code; only report.
- Show stale data honestly ("tests not run").
- Report only deltas to the orchestrator, e.g. "Step 07 → 🧪; tests 142/142; coverage 93 %".
