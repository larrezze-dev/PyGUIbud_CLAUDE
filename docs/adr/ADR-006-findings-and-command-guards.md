# ADR-006 — Findings, source positions and validator-backed command guards

- **Status:** Accepted (user, 2026-10-05) · **Date:** 2026-10-05 · **Step:** 09

## Context
The reader (Step 08) emits `XmlWarning`s and fails fast; it does no semantic checking. Step 09 adds a multi-finding validator and an undo stack that must block invalid edits with a translated reason. `pyguibud-uic --check` prints both kinds of finding. Model nodes carry no source positions. Options considered: a parallel validator type, a position field on nodes, and per-command precondition code.

## Decision
- One finding type, `Finding` (`core/diagnostics.py`), with `severity`, `path`, `anchor` and `part`; `XmlWarning` becomes an alias of it.
- Source positions live in a side table, `ReadResult.positions: SourceMap`, keyed by `(node identity, part)`. The model is unchanged. Positions are valid for the document as read.
- `validate(document, registry)` is pure and iterative, returns every finding in a deterministic order, and is the **only** home of semantic rules.
- Command guards run the validator after applying a command and roll it back if the command introduced **new** errors. The validation is uncapped, and errors are compared by per-rule keys: `(code, anchor, part)`, or order-independent keys for the duplicate-id, main-window and grid-collision rules. A rejection is a return value (`Outcome`), not an exception. Documents that already contain errors stay editable.
- Newer-MINOR (read-only) documents reject every command.
- Ids (and handler, bind and component names) match ASCII `^[A-Za-z][A-Za-z0-9_]{0,63}$` and are not Python keywords.
- Every window and layout container needs a layout, even when it is empty; page containers must have none. Commands never invent a layout; the designer supplies `DEFAULT_LAYOUT`.
- Include existence, kind and cycles are checked in Step 10.
- Spec: `docs/specs/validate-commands.md`.

## Consequences
- ➕ A single source of truth, so guards cannot drift from `--check`. No model or schema change. Forks add rules in one place.
- ➖ One full validation per command. A budget test covers it, and scoped validation is deferred to Step 19.
- ➖ Positions go stale after edits, so the stack never reports lines (documented).
