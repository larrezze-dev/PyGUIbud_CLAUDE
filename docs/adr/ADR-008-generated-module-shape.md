# ADR-008 — Generated module shape (amends ADR-003)

- **Status:** Accepted (user, 2026-10-06; C1–C8 defaults) · **Date:** 2026-10-06 · **Step:** 11 · **Spec:** `docs/specs/codegen.md`

## Context
ADR-003 fixed codegen as composition (`class Ui_Main: def setup_ui(self, root, handlers)`), with no PyGUIbud import, and ADR-007 confirmed the latter. Runtime §2.2 pins the public surface that codegen must reproduce: clipping, liveness, atomic retranslation, mnemonics, shortcuts and include scopes. Three options were considered:
- pure pyuic-style code, which repeats the logic inline;
- data tables plus a vendored mini-loader, which is a second `_tk.py`;
- a fixed support block plus straight-line build code.

## Decision
- Each generated module is made of:
  - a header;
  - a fixed import block (stdlib + `ttkbootstrap`);
  - a **support block** copied verbatim from the tested `pyguibud/codegen/_support.py`;
  - module constants;
  - `class Ui_<Name>(_Ui)` with a straight-line `_build`.
- Tk mapping decisions are made at **generation time** from `pyguibud/backends/_tkmap.py` (moved out of `_tk.py`) and `core.keys`, so there is one source of truth.
- `setup_ui(self, master=None, handlers=None, *, strict=True, lang=None, localedir=None, translator=None)`:
  - the positional order is ADR-003's;
  - `master` has `load_ui` semantics: `None` creates the themed `App`.
- The module defines its own `UiError(RuntimeError)`. Its `.code` values are runtime's, and its messages are en-GB, untranslated.
- Translations use stdlib gettext + `pgettext`. Each document's `<ui dir>/locale` is emitted as a path relative to the generated file, and `localedir=` overrides it. The pseudo-locale is not generated.
- Images are embedded as base64 `data=` (no `file=`).
- `RESERVED_IDS` is unchanged; every other member is `_`-prefixed, and a test pins this.
- `--stubs` (ADR-003) is deferred to Step 15. A file without the generated marker is never overwritten without `--force`. `--force` also lets codegen embed resources with absolute or `..`-escaping paths, which it otherwise refuses (QA-11-03, user decision 2026-10-06). It never allows writing over an input `.ui`, an included file or a device, and network (UNC) paths are always an error (R82).

## Consequences
- ➕ Readable, deterministic output that runs without PyGUIbud. The surface is the same as `load_ui`, and parity is test-enforced.
- ➖ About 300 lines of support code in every generated file. Mitigation: it is one copied block, golden-normalised.
- ➖ Fixes to `_tk.py` must be mirrored. Mitigation: `test_parity.py` and the shared `_tkmap`.
