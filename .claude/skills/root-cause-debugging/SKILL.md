---
name: root-cause-debugging
description: Systematic root-cause debugging procedure for PyGUIbud (reproduce, isolate, explain, minimal fix, regression test). Use when a test fails, a crash or wrong behaviour is reported, or QA files a bug.
---

# Root-cause debugging

1. **Reproduce:** get a deterministic failing command (`uv run pytest tests/...::test_x -x -vv` or a minimal script). Record the exact error and the environment (OS, Python, toolkit versions).
2. **Isolate:** shrink the input (hypothesis `@example`, minimal `.ui`). Bisect by code path and, if needed, read git history (`git log -p`; read-only). Add temporary logging and remove it afterwards.
3. **Explain:** state the root cause in one or two sentences (*why*, not *where*), with evidence: a stack trace, a variable value, a doc reference. If you cannot explain it, you are not done. Never guess-patch.
4. **Fix minimally** at the cause, not the symptom. Do not loosen the validator, catch-and-ignore, or skip/xfail a test to get green.
5. **Regression test** that fails before the fix and passes after it.
6. **Widen:** search for the same pattern elsewhere (`Grep`) and report siblings.
7. **Verify:** run the full suite and ruff/mypy, then report.

Tk pitfalls: mixing `grid` and `pack` in one master hangs or raises; `Tk()` created twice; variables garbage-collected without a master reference; `after()` callbacks after `destroy()`; DPI scaling on Windows.
Qt pitfalls: objects deleted by parent ownership; a missing `QApplication`; signals connected to lambdas capturing loop variables.

Report: root cause, fix (files), regression test id, verification output, related risks.
