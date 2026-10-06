---
name: gui-testing
description: PyGUIbud testing strategy - pytest layout, hypothesis property tests, headless Tk/Qt tests, golden files, coverage, and real-desktop/browser control for end-to-end checks. Use when writing, running or fixing tests.
---

# Testing strategy

## Layout and commands
`tests/core/`, `tests/runtime/`, `tests/codegen/`, `tests/backends/`, `tests/designer/`, `tests/i18n/`, `tests/qa/`.
`uv run pytest -q` · `uv run pytest --cov=pyguibud --cov=pyguibud_runtime --cov-report=term-missing` · marker `@pytest.mark.gui` for tests that need a display; `@pytest.mark.slow` for long runs.
Coverage target: ≥ 90 % for core/runtime/codegen; the designer is covered through its presenters.

## Techniques
- **Property tests (hypothesis):** random valid models → serialise → parse → equal (round-trip); random mutations must either be applied or be rejected by the validator, never corrupt the model; undo(do(x)) == x.
- **Golden files:** `tests/data/*.ui` → expected `*_ui.py`. Run the generated code in a subprocess **without PyGUIbud on `sys.path`** to prove it is standalone.
- **Backends:** one parametrised mapping test per core widget per backend. Tk: create a `tk.Tk()` (withdrawn), call `update_idletasks()`, assert on widget class/options, then `destroy()` in a fixture. Qt: `QApplication` fixture with `QT_QPA_PLATFORM=offscreen`; skip if PySide6 is missing.
- **Designer presenters:** test without a display. For a real window, use the `gui` marker; Linux CI uses `pytest-xvfb`.
- **i18n:** catalogue completeness and placeholder tests per locale (see the i18n-catalogue skill).

## End-to-end and visual checks
When automated tests are not enough, drive the real app:
- Launch with `uv run pyguibud --lang <code>` in the background and take screenshots (Pillow `ImageGrab` on Windows/macOS) into `tests/artifacts/` (gitignored). Compare them or inspect them visually.
- Use any computer-use or browser tools available in the session (e.g. `mcp__claude-in-chrome__*` for the HTML scoreboard and docs site) to click, type and capture GIFs of flows.
- Always close spawned windows/processes afterwards.

## Reporting
Return the exact command, the pass/fail counts and the failing test ids with a short traceback excerpt. Don't modify production code to make a test pass; hand failures to the debugger with a reproduction.
