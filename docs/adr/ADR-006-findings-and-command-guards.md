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

## Amendment — same-file includes in the guards (2026-10-09, Step 14a.2)
- **Status:** Accepted (user, 2026-10-09). This reverses part of validate-commands §13 D4 ("never in the command guards"); the user confirmed it.
- **Context:** QA-14a2-10 (MAJOR). The guards validate with `files=None`, so the `src="#"` checks (R51, R52 and R53) never ran. The inspector's window Id, window Kind and include Component fields could then save files that `pyguibud-uic` and `load_ui` refuse. Only paste was patched, through `clipboard._include_problem`.
- **Decision:**
  - `validate()` always runs the include pass. With `files=None` it follows only `src="#"` (same file, no disk access). External includes are still checked only with `files=`.
  - The pass reuses the existing codes and msgids: R51 `validate.include_not_component` (component missing or not `kind="component"`), R52 `validate.include_cycle` and R53 `validate.include_limit` (depth and widgets). There are no new msgids.
  - With `files=` the result is unchanged: `"#"` already resolves to the same document, and each problem is reported once.
  - The R52 guard key is order-independent: `(code, frozenset of the loop's (file, component) pairs)`, carried in `Finding.related`. This keeps an already-cyclic document editable when its windows are reordered or a valid include is added.
  - Designer: the inspector's window **Id** goes through `rename_window`, so same-file includes follow. **Kind** and include **Component** edits are plain commands that the guard refuses, with the validator's reason.
- **Consequences:**
  - ➕ One rule source. Every edit path, current and future, is covered. Paste no longer needs its own copy of the checks.
  - ➖ An external file whose own `"#"` includes are broken now counts as invalid (R50, "has N errors") and is not followed.
  - ➖ In-memory tests with dangling `"#"` includes get new R51 errors.
  - ➖ R53 anchors on same-file chains depend on traversal order. This is accepted because those files are refused anyway.
