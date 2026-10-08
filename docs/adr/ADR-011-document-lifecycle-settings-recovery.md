# ADR-011 — Document lifecycle, settings store, recovery and clipboard

- **Status:** Accepted · **Date:** 2026-10-08 · **Step:** 14a · **Spec:** `docs/specs/properties-save-load.md` (D1–D12: all recommended defaults, user 2026-10-08)

## Context
Step 14a turns the designer from a template viewer into an editor of real files: open/save, an unsaved-changes guard, crash recovery, persisted preferences (Step 12 D7) and copy/paste between files. The constraints:
- one ttkbootstrap root per process (ADR-009) and every edit through `CommandStack` (ADR-006);
- the hardened, round-trip-safe reader (ADR-002);
- no new dependency, and pure headless-testable logic.

Rejected options: a bare-fragment or in-process clipboard; `platformdirs` or INI settings; recovery files next to the user's file; a single-instance process with IPC.

## Decision
- **One document per process.** "Multi-window" means the windows of one `.ui` as canvas tabs. Several files means several processes.
- **File lifecycle** (pure `designer/files.py`):
  - `FileStamp` (size, mtime_ns, sha256) for a conflict check before save;
  - `write_ui` atomic + `.bak` (unchanged);
  - undoable relative-path rebasing on Save As;
  - R82 refusal of network and device paths;
  - recent files (≤ 10);
  - the CLI positional `.ui` via the keyword-only `launch(lang, theme, *, path=None)`.
- **Asynchronous guard.** `app.guard(then)` with Save / Don't save / Cancel replaces the synchronous `can_discard()`. SIGINT never prompts; it writes a recovery snapshot.
- **Settings.** `settings.json` (schema v1) in a per-OS config dir computed with the stdlib, with a `PYGUIBUD_CONFIG_DIR` override.
  - Tolerant reading: a size cap, a `.corrupt` rename, per-key defaults; unknown keys are kept for forks.
  - Precedence: CLI > environment > settings > locale.
- **Recovery.**
  - Each process has a folder `state_dir()/recovery/<uuid>/` with an OS-locked `owner.lock` (`msvcrt`/`fcntl`), `document.ui` (`dump_ui`) and `info.json`.
  - A folder that can be locked and holds a snapshot is an orphan. Orphans are offered at start-up (Restore / Discard / Later).
  - Snapshots are written every 60 s while dirty, and on SIGINT. The folder is removed at process exit.
- **Clipboard.** A complete `.ui` text marked by foreign-namespace root attributes `clip:mode`/`clip:origin` (`urn:pyguibud:clipboard:1`, kept in `Document.extra_attrs`). It is read back with the hardened reader plus `validate_read`, ids are remapped, and it is inserted as one `Macro`.
  - The chords are scoped to the canvas and the tree (ADR-010).
  - No schema change.
- **The only core API change:** `CommandStack(..., dirty: bool = False)`, so a restored document opens dirty. External includes are expanded for the canvas by designer code mirroring the runtime's `_expand`, which stays in the runtime (it depends on `UiScope`/`Instance`, ADR-007).

## Consequences
- ➕ **No lost work:** atomic saves, conflict detection and recovery cover crashes, logoff and Ctrl+C. Two instances never touch each other's recovery data.
- ➕ **Paste is as hardened as Open**, with no second grammar.
- ➖ **The X11 clipboard empties when the source process exits.** Accepted and documented.
- ➖ **OS lock semantics differ** (NFS homes). Mitigation: a lock error counts as "live", so the folder is never deleted.
- ➖ **The include resolver is duplicated.** Mitigation: an embed-versus-`load_ui` parity test.
- ➖ **No font editor** (no `font` PropertyType). If D8 = A, `FEATURES.md` M3 needs amending; that is a scope change for the user to approve.
- **Affected:**
  - 14p (styling the new panels), 15 (preview uses `session.path`), 17 (`tb:` editors on `properties.Field`), 18 (msgids), 19 (abuse cases A1–A20, image-resource management);
  - `tools/scorer.py` (plan rows 14a/14p).
