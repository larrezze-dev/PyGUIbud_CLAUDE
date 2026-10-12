# ADR-013 — Preview child process and export pipeline

- **Status:** Accepted (user, 2026-10-11: D1–D14 all defaults) · **Date:** 2026-10-11 · **Step:** 15 · **Spec:** `docs/specs/preview-export.md` (D1–D14)

## Context
ADR-009 and designer-shell D4 (Accepted) already require an out-of-process preview: one `Style` and one Tk root per process, so `load_ui(master=None)` raises `runtime.root_exists` inside the designer. Step 16 adds PySide6, and Qt and Tk event loops must not share a process. Still open: what the child may import, how it gets an unsaved document, how it is controlled and how it dies, and where the CLI's output-safety checks live once the designer exports too. Those checks are private functions in `uic.py` today.

## Decision
- **Child entry `python -m pyguibud.preview`** (package `src/pyguibud/preview/`). It may import `pyguibud_runtime`, `pyguibud.core`, `pyguibud.i18n` and `pyguibud.backends`. It must **never** import `pyguibud.designer`, `pyguibud.cli`, `pyguibud.uic` or `pyguibud.codegen`. `tests/runtime/test_import_boundary.py` gains this case.
- **Handoff:**
  - a clean, saved document: the child loads `session.path` itself, so paths and `<dir>/locale` resolve exactly as at runtime;
  - otherwise: a snapshot written with `dump_ui` into a private `tempfile.mkdtemp(prefix="pyguibud-preview-")` folder, with paths rebased (`files.rebase_paths` on a copy) and `localedir=<.ui dir>/locale`.
- **Control:** argv only (`shell=False`), `cwd` = the private folder, `CREATE_NO_WINDOW` on Windows.
  - stdin carries a line protocol (`theme NAME`, `lang CODE`, `raise`, `quit`). **stdin EOF ends the child**, so a crashed designer never leaves an orphan.
  - The child writes `ready.json` and `result.json` into the private folder. stderr goes to a file there (no pipe that can fill up). The designer polls with `after()`, never with `select`.
- **One live preview per designer.** F5 respawns it, with no in-process reload.
- **Backend-neutral host:** the child talks to the toolkit only through a `PreviewHost` (schedule, theme, show-only, close). Step 15 ships the ttkbootstrap host. Step 16 adds `tkinter` and `pyside6` hosts behind `--backend NAME`.
- **Export = `codegen.generate_python` on the saved file.** The output guards move from `uic.py` to a public `pyguibud.codegen.output` module. They are shared by the CLI and the designer, so both produce **byte-identical** modules.

## Consequences
- ➕ Crash isolation, the document's real theme, and the same `load_ui` path that users ship. The CLI and the dialog share one code path for refusals.
- ➖ Start-up costs about 0.5–1.5 s per preview, and there is no instant hot reload. Mitigation: F5 respawns at the last position, and theme and language switch live over stdin.
- ➖ A dirty snapshot uses one `localedir` for every document, so an external include with its own catalogue in another folder shows source texts. Documented. Saving removes it.
- Affected: Steps 16 (hosts, `--backend`), 17 (plugin widgets in the child), 19 (abuse list), 20 (the child ships in the `pyguibud` wheel, not in the runtime).
