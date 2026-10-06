---
name: orchestration
description: How the PyGUIbud ORCHESTRATOR delegates to the 10 sub-agents, weighs the model per task, runs the UAT gate and writes the session handover. Use when planning or delegating PyGUIbud work.
---

# Orchestration

## Pipeline per step
1. Verify state: read the current step in `DEVELOPMENT_PLAN.md`; run `uv run pytest -q` once code exists.
2. **software-architect**: spec/ADR for anything not already decided (skip for pure execution steps).
3. **backend-developer** / **frontend-developer** (+ **translator**) implement it. Run them in parallel when they touch disjoint files.
4. **testing** writes and runs tests. Failures go to **debugger**, then back to testing, until green.
5. **qa** runs abuse and locale checks when the step has user-facing behaviour. Bugs go to debugger.
6. **scorer** refreshes the dashboard (from Step 05).
7. Report to the user: summary, UAT instructions, proposed commit message, handover block. **Never commit.**
8. Release steps only: **deployer**, then **lame-culos**. Nothing goes public without the user's explicit approval.

## Model weighting
Pass `model` in the Agent call to override the agent's default. Choose by risk and complexity, not by habit.

| Agent | Default | Raise to opus when… | Lower to haiku when… |
| --- | --- | --- | --- |
| software-architect | opus | n/a | never |
| backend-developer | sonnet | schema, codegen, plugin API, migration design | boilerplate, renames, docstrings |
| frontend-developer | sonnet | DnD/canvas engine, selection, hit-testing | styling, menu wiring, labels |
| translator | sonnet | n/a | catalogue sync, fuzzy cleanup |
| debugger | opus | n/a | never |
| testing | sonnet | flaky/GUI/concurrency tests | trivial test scaffolding |
| qa | opus | n/a | never |
| scorer | haiku | (sonnet) building or redesigning the dashboard | n/a |
| deployer | sonnet | n/a | n/a |
| lame-culos | sonnet | n/a | n/a |

Rules: don't waste tokens, and don't save them at the cost of quality. If a sub-agent's output fails review twice, re-run it one model tier up.

## Delegation brief (always include)
Step id and goal · files in scope (and out of scope) · acceptance criteria · exact verification command · "do not commit". Sub-agents start cold: give paths, not the whole history.

## UAT gate
A step is ✅ only after the user writes "UAT passed". Until then it is 🧪. Update the status column in `DEVELOPMENT_PLAN.md`.

## Context monitoring
Check context use at each delegation. At 55 %, start no new feature. At 60–65 %, wrap up: finish the current atomic edit → run `pytest` → handover → tell the user to open a new chat.

## Handover format (end of every session)
```
📋 Session Handover Briefing
- Step Completed: Step NN: <name>
- Deliverables Created/Modified: <paths>
- Verification Status: <command> -> <result>
- Current Git / Working State: <uncommitted files; user to commit>
- Next Step to Execute: Step NN: <name>

## 🚀 Next Session Kickoff Prompt
> "Resume PyGUIbud development at Step NN: <name>. Inspect DEVELOPMENT_PLAN.md and project.md. Verify current state with `pytest` before starting."
```
Also update §5 *Next session kickoff* in `DEVELOPMENT_PLAN.md`.
