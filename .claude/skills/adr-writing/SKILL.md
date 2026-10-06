---
name: adr-writing
description: How to write and maintain PyGUIbud Architecture Decision Records and specs in docs/adr/. Use when a design decision, schema change, public API or trade-off needs to be recorded.
---

# ADR writing

- Location: `docs/adr/ADR-NNN-kebab-title.md`, numbered sequentially and never renumbered.
- Status: `Proposed` → `Accepted` (after user sign-off) → `Superseded by ADR-NNN` / `Deprecated`. Never delete an ADR; supersede it.
- Keep each ADR under about 25 lines. Template:

```markdown
# ADR-NNN — <Title>

- **Status:** Proposed · **Date:** YYYY-MM-DD · **Step:** NN

## Context
<forces, constraints, options considered — 2–5 lines>

## Decision
- <bullet per decision; concrete names, files, APIs>

## Consequences
- ➕ <benefit>
- ➖ <cost / risk and its mitigation>
```

## Checklist before proposing
- Is it toolkit-agnostic in the core? Can a fork or plugin extend it without patching the core?
- Does it preserve `.ui` round-trip and forward compatibility? Does it need a `schema_version` bump + migration?
- Is it i18n-ready (translatable strings, no concatenation)? Can the validator block abuse?
- Is it testable headless? What is the user's UAT for it?
- Update `FEATURES.md` / `DEVELOPMENT_PLAN.md` if scope or steps change, and list the affected steps.

Present options with a recommendation; the user decides, and the ORCHESTRATOR relays.
