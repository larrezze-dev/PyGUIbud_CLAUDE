---
name: pyguibud-ground-rules
description: Non-negotiable PyGUIbud project rules (git rules, en-GB, 8 locales, brand copying, context limits, reporting chain, document map). Use at the start of any PyGUIbud task by any agent.
---

# PyGUIbud ground rules

## Hard rules
1. **Git (CLAUDE.md, changed by the user 2026-10-24):** only the ORCHESTRATOR runs history-changing git. It commits each step on a `step-<id>` branch, pushes it and opens a PR to `master`. **Never push a `v*` tag**, because that publishes through `release.yml`; the user tags releases. Sub-agents use read-only git only (`status`, `diff`, `log`) and never `reset`/`rebase`/`push`.
2. **Language:** code, identifiers, comments, UI strings and docs in **British English (en-GB)**: colour, behaviour, licence (noun), initialise, serialise, centre, grey, catalogue.
3. **Multilingual:** every user-facing string goes through `_()`. Mandatory locales besides `en_GB`: `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`. Pseudo-locale `en_XA` is used for layout testing.
4. **Brand:** SAPÉ identity files are **copied** into `assets/brand/`. Never reference, edit or delete the source folder `G:\Mi unidad\Trabalho\Sape\UI-Design\corporate-identity\03-corporate-image`.
5. **Step discipline:** work only on the current step of `DEVELOPMENT_PLAN.md`. Each step ends with a user UAT, and the next step starts only after "UAT passed".
6. **Reporting:** only the ORCHESTRATOR talks to the user. Sub-agents return a concise report to their caller: what changed (paths), how it was verified (exact command + result), and open issues. Never claim a test passed without running it.
7. **Context budget:** keep reads targeted (no full dumps of large files). The main session wraps up at 60–65 % context; no new feature after 55 % unless it can be finished within 5 %.
8. **Safety:** opening a `.ui` never executes code; the core never imports a GUI toolkit; PySide6 stays an optional extra.

## Document map
| File | Contents |
| --- | --- |
| `CLAUDE.md` | User's rules (authoritative) |
| `DEVELOPMENT_PLAN.md` | Stack, licence, agents/models, steps + UAT, status |
| `project.md` | Concept + Mermaid diagrams |
| `FEATURES.md` | v1 MoSCoW, widget list, `.ui` schema draft |
| `docs/adr/ADR-00x-*.md` | Architecture decisions |
| `CONTRIBUTING.md`, `NOTICE.md`, `LICENSE` | Contribution rules, name/brand carve-out, MIT |

## Layout (from Step 04)
`src/pyguibud/` (designer, core, codegen, backends, locale) · `src/pyguibud_runtime/` (tiny loader) · `tests/` · `examples/` · `tools/` · `assets/brand/`.
