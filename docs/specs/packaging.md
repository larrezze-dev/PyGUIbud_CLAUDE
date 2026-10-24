# Spec — Step 20: Packaging & release candidate

- **Status:** Accepted (user, 2026-10-24: all defaults D1–D12; D8 decided "Accept as is"; O1 GitHub repo deferred to 20b; O2 branch stays `master`). **Date:** 2026-10-24. **ADR:** ADR-016 (Accepted). It settles ADR-007's open question; ADR-007's import rules stay as they are.
- **Owner:** DEPLOYER (sonnet). BACKEND (sonnet) does the 20a code edits. TESTING runs the clean-venv checks. **Reviewer:** SOFTWARE-ARCHITECT.
- **Plan row 20:** wheels/sdist, TestPyPI, install docs, and the split of `pyguibud_runtime` into the standalone `pyguibud-runtime` distribution. UAT: in a clean venv, `pip install -i <TestPyPI> pyguibud` · `uv tool install` · `uvx pyguibud`.
- **Baseline (2026-10-24):** 6999 passed / 1 skipped; mypy strict clean (328 files × win32/linux/darwin); ruff clean (380). `import pyguibud_runtime` loads 26 modules, with no toolkit and no designer.
- **Hard limits:** the DEPLOYER never tags, pushes or uploads. The user does every TestPyPI/PyPI publication through the release workflow.

## 1. Scope
**In scope:**
- the runtime split (ADR-016);
- a uv workspace;
- metadata, READMEs and URLs;
- RC versioning and a bump tool;
- CI on `master` with build, dist checks and install-smoke;
- a release workflow (OIDC trusted publishing);
- a local clean-venv verification script;
- `docs/install.md`.

**Out of scope:**
- README polish, GIFs, the docs site and translated docs (Step 21);
- Python 3.14 in classifiers or the matrix (after v1, unless the user asks);
- a gettext domain split (after v1, D3 b);
- code signing and standalone executables.

**Budget rule** (net `src/**/*.py` and `runtime/src/**/*.py` lines, as in Steps 16–19):
- A moved file is compared with its HEAD original (`git show HEAD:<old path>` against the new path, `git diff --no-index --numstat`). A pure move counts 0.
- Every part records its start numstat in its handover.
- Not counted: tests, `tools/`, workflows, TOML, docs, `.po`/`.mo`.

## 2. Target layout (D1 c + D2 a)
```
pyproject.toml            # pyguibud (designer + CLIs); workspace root
README.md  LICENSE  NOTICE.md
src/pyguibud/             # NO __init__.py (PEP 420 portion)
  __main__.py cli.py uic.py _argparse.py credits.py
  codegen/ designer/ preview/          (each with py.typed)
runtime/
  pyproject.toml          # pyguibud-runtime; workspace member
  README.md  LICENSE  NOTICE.md        # byte copies, checked by a test
  src/pyguibud/           # NO __init__.py
    __about__.py i18n.py
    core/ (schema/, migrations/)  backends/   (each with py.typed)
    locale/<8 locales>/LC_MESSAGES/pyguibud.{po,mo}  locale/pyguibud.pot
  src/pyguibud_runtime/   # unchanged package, py.typed
tests/  examples/  docs/  tools/       # unchanged places
```
- Each file is moved as it is, and no import line changes.
- `pyguibud_runtime.__version__` becomes `from pyguibud.__about__ import __version__`, which removes its duplicate literal.
- `src/pyguibud/__init__.py` is deleted. The 5 test sites of `pyguibud.__version__` use `pyguibud.__about__.__version__`.

## 3. Decisions for the user (recommended default in **bold**)
| ID | Question | Options |
|---|---|---|
| D1 | How to split the runtime | **(c) PEP 420 namespace portions (ADR-016): delete `pyguibud/__init__.py`. `pyguibud-runtime` ships `pyguibud/{__about__,i18n}.py`, `core/`, `backends/`, `locale/` and `pyguibud_runtime/`; `pyguibud` ships the rest. Churn: about 45 moved files (0 lines each), ≈ 30 net src lines, ≈ 60 test lines in ≈ 25 files, and config.** · (a) move the shared code into `pyguibud_runtime._core`/`_i18n`/`_backends`. Rewriting the imports touches 335 lines in 92 src files and 524 lines in 168 test files, plus 24 quoted module names in 13 tests. Shims through `from … import *` drop private names (`_metadata_entry_points`, `_BUILTIN_DISTRIBUTION`) and make monkeypatching hit the wrong module. Only `sys.modules` aliasing is safe, and mypy cannot follow it. The entry-point values, `_BUILTIN_PREFIXES` and `BUILTIN_BACKENDS` all change. · (b) a third distribution, `pyguibud-core`: the churn of (a), plus a third project and publisher pair, for no size gain |
| D2 | Repo layout | **(a) uv workspace: root `[tool.uv.workspace] members = ["runtime"]` + `[tool.uv.sources] pyguibud-runtime = { workspace = true }`; one `uv.lock`; `uv sync` installs both editable** · (b) two independent projects with a `path` source (two locks, more drift) |
| D3 | Catalogue ownership | **(a) one domain `pyguibud`, owned by `pyguibud-runtime` (`runtime/src/pyguibud/locale`). `_texts.py:103` and `i18n.DOMAIN` stay as they are. The ≈ 500 designer-only msgids ride along in the runtime `.mo` (one locale is loaded at a time). Wheels ship `.mo` only and sdists keep `.po`/`.pot`** · (b) split into domains: `pyguibud` (≈ 335 core/backends/runtime references) and `pyguibud_designer`, chained with `add_fallback`. This needs 8 `.po` splits, two extract runs and catalogue-test churn (≈ +25 src lines, a full TRANSLATOR pass) |
| D4 | Built-in detection (`registry.py:53`, `_is_builtin`, `_distribution`) | **(a) `_BUILTIN_DISTRIBUTION = "pyguibud-runtime"`, plus `_RESERVED_DISTRIBUTIONS = frozenset({"pyguibud", "pyguibud-runtime"})` for the H66 "fork → named after its module" rule. Built-in = the runtime distribution + the group's value prefix (unchanged). Entry points are declared only in `runtime/pyproject.toml`; `pyguibud` declares none. The `BUILTIN_BACKENDS` fallback stays. The 9 test files that fake a `"pyguibud"` dist are updated** · (b) a set of built-in distributions {`pyguibud`, `pyguibud-runtime`} (keeps a stale editable `pyguibud` 0.1.0.dev0 "built-in", which weakens H66) |
| D5 | Dependencies and extras | **(a) `pyguibud-runtime`: `ttkbootstrap>=2.2,<3` (`load_ui` defaults to `backend="ttkbootstrap"`), extra `[pyside] = PySide6>=6.6`. `pyguibud`: `pyguibud-runtime==X`, `ttkbootstrap>=2.2,<3` (the designer imports it directly), extras `[pyside] = pyguibud-runtime[pyside]==X` and `[dev]` (unchanged). `examples/acme_plugin` depends on `pyguibud-runtime`** · (b) ttkbootstrap as a runtime extra (a plain runtime install then fails at the default `load_ui`) |
| D6 | Version source and coupling | **(a) one literal, in `runtime/src/pyguibud/__about__.py`. The hatch version `path` of both projects points there (the root project reads `runtime/src/pyguibud/__about__.py`, which is included in its sdist). The exact pins in the root `pyproject.toml` are static. `tools/bump_version.py <ver>` rewrites the literal and both pins, regenerates `examples/hello_ui.py` and the codegen goldens (they embed the version in their header), and runs `uv lock`. `tests/test_version_sync.py` asserts that the literal, both pins, `pyguibud_runtime.__version__` and the `hello_ui.py` header agree** · (b) a hatch metadata hook (`hatch_build.py`) that pins dynamically, plus version-normalised goldens (more build magic) |
| D7 | Metadata | **(a) A minimal `README.md` per distribution: what it is, install, a 5-line example, links, and the credit line "Created by Luciano Arrezze and programmed with the support of Claude Code". Then `readme = "README.md"`; `[project.urls]` Homepage/Source/Issues/Changelog → the GitHub repo (open item O1); `Development Status :: 4 - Beta`; `Natural Language ::` × 8; runtime keywords. The root sdist keeps src/tests/docs/examples (for downstream packagers); the runtime sdist has `src`, README, LICENSE, NOTICE and pyproject only, no tests** · (b) the same, but tests are dropped from the root sdist too (≈ 555 → ≈ 300 files) |
| D8 | Run after export with a missing interpreter (19g) | **Decided (user, 2026-10-24): "Accept as is".** The message stays "The preview cannot start: no Python interpreter was found." and no new msgid is added. |
| D9 | RC versioning | **(a) `0.1.0rc1`, `rc2`, … on TestPyPI (TestPyPI never accepts a version twice, so every retry bumps rcN). `0.1.0` final on PyPI happens in Step 21. The release workflow sends pre-release tags (`a`/`b`/`rc`/`.dev`) to TestPyPI only** · (b) `0.1.0.devN` (pip/uv treat dev releases as pre-releases too, but the name says "unfinished", not "candidate") · (c) `0.1.0aN` |
| D10 | CI and release workflows | **(a) as §5: `ci.yml` on `master` + `workflow_dispatch`; jobs test/qt (as now) + `build` (both dists, twine check, `tools/check_dist.py`) + `install-smoke` (built artefacts, clean venv, ubuntu+windows × py3.10/3.13). A new `release.yml` on tag `v*`: build → TestPyPI (environment `testpypi`) → PyPI (environment `pypi`, required reviewer, final versions only), all through OIDC trusted publishing** · (b) a single workflow, with publishing behind `workflow_dispatch` only |
| D11 | Local verification | **(a) `tools/verify_install.py` (stdlib only). It builds both distributions, makes clean venvs in a temp folder, and runs the §6 checks along the pip path and the uv path (`uv tool install`, `uvx`). It also takes `--from-index testpypi --version X` for the UAT. A thin `tests/test_install.py` calls it, under a **new** marker `install`. The `slow` marker is already used by 10 tests in 9 files, so it is not reused. `addopts` adds `-m "not install"`, so neither the local full run nor the CI matrix runs it; only the `install-smoke` job runs the script directly** · (b) the script only, with no pytest wrapper |
| D12 | Install docs | **(a) `docs/install.md` (en-GB): requirements (Python 3.10–3.13; Linux `python3-tk`), pip / `uv tool install` / `uvx`, runtime-only, `[pyside]`, the RC-from-TestPyPI recipe (§7), PATH after `uv tool install` (`uv tool update-shell`), uninstall, troubleshooting (pre-release not found, `No module named tkinter`), and the credit line. The README links to it. Translations follow in Step 21** · (b) everything in the README |

## 4. Parts
For every part: start from a green suite after the user writes "UAT 20x passed". Use no history-changing git; keep the moves as plain file moves (git detects renames when the user stages them). Any script that builds a `DesignerApp` sets `PYGUIBUD_CONFIG_DIR`/`PYGUIBUD_STATE_DIR` to a temp folder. Estimates are raw figures × 1.3.

| Part | Scope (one line) | Agents (model) | Est. | Cap |
|---|---|---|---|---|
| **20a** | Runtime split: the workspace, the moves, registry D4, version D6, tool config, tests | DEPLOYER (sonnet), BACKEND (sonnet; opus for the registry), TESTING | ≈ 40 | 120 |
| **20b** | Metadata, READMEs, `check_dist`, CI fix + build/install-smoke, `release.yml` | DEPLOYER (sonnet), ARCHITECT review | ≈ 10 | 60 |
| **20c** | `verify_install.py` (local), `docs/install.md`, user-run TestPyPI RC + UAT | DEPLOYER (sonnet), TESTING (opus, real desktop), QA (opus) | ≈ 20 | 80 |

### 20a — Runtime split
**Scope:**
- Move the files to §2's layout. Delete `src/pyguibud/__init__.py` and the top-level `src/pyguibud/py.typed`; under PEP 420 the namespace root carries neither. Add `py.typed` to each runtime and designer subpackage, and to `pyguibud_runtime`.
- Write `runtime/pyproject.toml` (hatchling; `packages = ["src/pyguibud", "src/pyguibud_runtime"]`; wheel `exclude = ["*.po", "*.pot"]`; entry points moved here from the root).
- Root `pyproject.toml`:
  - wheel `packages = ["src/pyguibud"]`, with `.po`/`.pot` excluded;
  - the workspace keys (D2) and pins (D5/D6);
  - no `pyguibud.*` entry points.
- Tool configuration:
  - mypy: `mypy_path = ["src", "runtime/src"]`, `explicit_package_bases = true`, `files = ["src", "runtime/src", "tests"]`;
  - ruff: `src = ["src", "runtime/src", "tests"]`;
  - coverage: `source = ["src", "runtime/src"]` (directories, so namespace portions are found);
  - pytest `testpaths` stays as it is;
  - run `uv lock`.
- Code:
  - `registry.py` D4 (≈ +10);
  - `pyguibud_runtime/__init__.py` version import;
  - `examples/acme_plugin` depends on `pyguibud-runtime`.
- Paths: change the `src/pyguibud/{core,backends,locale}` paths in tests and tools (≈ 12 of the 23 files that build `src/pyguibud/...` paths) to a shared `tests/_paths.py` (`RUNTIME_SRC`, `DESIGNER_SRC`); point the extract/update/compile commands in `docs/i18n/README.md` and `tools/po_roundtrip.py` at `runtime/src/pyguibud/locale`, and the extract command at both roots.
- Add `tools/bump_version.py` and `tests/test_version_sync.py` (D6), and set the version to `0.1.0rc1`.
- Extend the ADR-007 boundary test so that `pyguibud_runtime` and every module it loads resolve under `runtime/src` and none under `src/`.

**Acceptance:**
- the full suite is green (≥ 6999 passed + the new tests, 1 skipped);
- mypy is clean on win32, linux and darwin, and `python -m pyguibud --version` works;
- `uv build --all-packages` gives 2 wheels and 2 sdists, with no file present in both wheels;
- `uv run python -c "import importlib.metadata as m; print(m.entry_points(group='pyguibud.backends'))"` shows `pyguibud-runtime` as the distribution;
- Help ▸ Plugins shows the built-in row as before.

**UAT (PowerShell, in the repo):**
1. `uv sync`, then `uv run pyguibud`: the designer opens. Help ▸ Plugins shows "Built-in" and acme behaves as in Step 17c.
2. `uv run pyguibud-uic --check examples/hello.ui` → OK. `uv run python examples/run_hello.py` → the window opens.
3. `uv build --all-packages`, then `dir dist` shows `pyguibud-0.1.0rc1-py3-none-any.whl`, `pyguibud_runtime-0.1.0rc1-py3-none-any.whl` and two `.tar.gz` files.
4. `uv run python -m pytest -q` is green (or the orchestrator's recorded run).

**Trims:** T1 skip the boundary-test extension (the CI runtime-only smoke covers it) · T2 drop `bump_version.py` and do the bumps by hand, with the sync test as the guard.

### 20b — Metadata, build and workflows
**Scope:**
- D7 metadata on both projects. Add `README.md` (root) and `runtime/README.md`, both minimal and carrying the credit line. Copy LICENSE and NOTICE.md into `runtime/` (a test checks the bytes are identical).
- `tools/check_dist.py` (stdlib `zipfile`/`tarfile`). It asserts the following:
  - the expected wheel trees, with no overlap between the two wheels, no `pyguibud/__init__.py` or top-level `pyguibud/py.typed`, and no `designer|codegen|preview|cli|uic` in the runtime wheel;
  - 8 `.mo` files, no `.po` in the wheels, the XSD and the `py.typed` files;
  - `Requires-Dist: pyguibud-runtime==X` matching the version;
  - README present in each METADATA;
  - the entry points only in the runtime's `entry_points.txt`.
- `ci.yml` and `release.yml` as described in §5.
- `twine check --strict`.

**Acceptance:**
- `uv build --all-packages && uvx twine check --strict dist/* && uv run python tools/check_dist.py dist` passes locally;
- `actionlint` is clean, if available (otherwise a YAML parse test);
- the user sees CI run green on `master` after they push.

**UAT:**
1. Run the acceptance command → "OK".
2. Open `dist/*.whl` as a zip (rename a copy) → the runtime wheel has no `designer` folder.
3. After your push, the GitHub Actions tab shows CI green, including `install-smoke`.
4. In GitHub, the repo settings show the two environments you created (§5.3).

**Trims:** T1 `install-smoke` on ubuntu only · T2 `check_dist` limited to overlap + Requires-Dist + `.mo`.

### 20c — Clean-venv verification, install docs, RC
**Scope:**
- `tools/verify_install.py` (D11): a pip path and a uv path, each running the §6 checks.
- `tests/test_install.py` (marker `install`).
- `docs/install.md` (D12).
- Fixes for whatever the clean venvs reveal (counted against the cap).
- A QA pass along the install paths: wrong Python (3.9), no Tk, an offline second run, `pip install pyguibud` without a version (→ installs the RC when it is the only candidate (PEP 440); "no matching distribution" only while the name is missing from the index in use; documented, QA-20c-01).
- The user tags `v0.1.0rc1` and approves the publish (§5.3); TESTING then verifies from TestPyPI.

**Acceptance:**
- `uv run python tools/verify_install.py` is green locally (pip + uv; py3.10 and 3.13, if both are installed);
- after the user's upload, `uv run python tools/verify_install.py --from-index testpypi --version 0.1.0rc1` is green.

**UAT (PowerShell, after you published rc1):** make a new empty folder, `cd` into it, and copy `hello.ui` there from the repo's `examples` folder. Then run the §7 commands.
1. pip: `pyguibud --version` prints the version and the credit line; `pyguibud` opens the designer.
2. `uv tool install`: `pyguibud` starts from a new terminal.
3. `uvx`: `pyguibud-uic --check hello.ui` → OK.
4. Runtime-only venv: `python -c "import pyguibud_runtime"` works, while `pyguibud` and `pyguibud-uic` are not found.
5. Read `docs/install.md` once and follow its uninstall step.

**Trims:** T1 the `install` pytest wrapper is dropped · T2 the uv path is checked by hand in UAT only.

## 5. Workflows
### 5.1 `ci.yml`
- **Triggers:** `push`/`pull_request` on `master`, plus `workflow_dispatch`.
- **`test` and `qt`:** as now. The `install` marker is excluded through `addopts`, which needs no workflow change.
- **`build`:**
  - `uv build --all-packages` (built through the sdist, which proves the sdists can build);
  - `uvx twine check --strict dist/*`;
  - `python tools/check_dist.py dist`;
  - `actions/upload-artifact` uploads `dist`.
- **`install-smoke`:** needs `build`. Matrix `ubuntu-latest`, `windows-latest` × `3.10`, `3.13`; xvfb on Linux.
  - Download `dist/`.
  - `python -m venv` in `$RUNNER_TEMP`, then `pip install --find-links dist "pyguibud[...]==<ver>"`. The runtime is not on any index, so `--find-links` is the source; ttkbootstrap comes from PyPI.
  - Run the §6 designer checks from a cwd outside the checkout, with `python -I`.
  - Make a second clean venv and run `pip install --find-links dist pyguibud-runtime==<ver>`, then the §6 runtime-only checks.
  - `uv tool install --find-links dist pyguibud==<ver>`, then `pyguibud --version`. `uvx --find-links dist --from pyguibud==<ver> pyguibud-uic --check examples/hello.ui`.
  - Read `<ver>` from `runtime/src/pyguibud/__about__.py`.

### 5.2 `release.yml` (tag `v*`)
- **`build`:**
  - the same commands as CI `build`;
  - a check that the tag equals `v` + `__about__.__version__`;
  - upload of the artefact.
- **`publish-testpypi`:**
  - `environment: testpypi`, `permissions: id-token: write`;
  - `pypa/gh-action-pypi-publish@release/v1` with `repository-url: https://test.pypi.org/legacy/`;
  - it uploads both distributions.
- **`publish-pypi`:**
  - needs `publish-testpypi`;
  - `if:` the version has no pre-release segment (D9);
  - `environment: pypi`, which has a required reviewer (the user), and `id-token: write`.
- There are no tokens or secrets in the repo.

### 5.3 What the user configures (once, by hand)
1. **GitHub** ▸ Settings ▸ Environments: create `testpypi` and `pypi`. On `pypi`, set Required reviewers = you, and Deployment tags = `v*`.
2. **test.pypi.org** ▸ Account ▸ Publishing ▸ "Add a new pending publisher" twice, for the projects `pyguibud` and `pyguibud-runtime`. Each one gets owner `<GitHub owner>`, repository `<repo name>`, workflow `release.yml` and environment `testpypi`.
3. **pypi.org**: the same two pending publishers, with environment `pypi`.
4. **Publishing an RC:** `git tag v0.1.0rc1`, `git push origin v0.1.0rc1`. Watch the workflow; the TestPyPI job runs without approval. A retry needs `tools/bump_version.py 0.1.0rc2`, a commit, and a new tag.

## 6. Smoke checks (shared by CI, `verify_install.py` and the UAT)
Every check runs in a temp folder outside the checkout, with absolute paths. The script first copies `examples/hello.ui` (and any file it references) into that folder.

**Designer venv:**
- (1) `pyguibud --version` → `pyguibud <ver>` + the credit line.
- (2) `pyguibud-uic --check examples/hello.ui` → exit 0.
- (3) Generate `hello.ui` into the temp folder with `pyguibud-uic`, then import the module there with `python -I`. Afterwards, no `sys.modules` key starts with `pyguibud` (ADR-003). Importability alone proves nothing here, because `pyguibud` is installed.
- (4) `load_ui("examples/hello.ui", handlers=<stub>)` builds the window, then destroys it without `mainloop`.
- (5) A headless `DesignerApp` builds, opens `hello.ui` and destroys itself, with `PYGUIBUD_CONFIG_DIR`/`PYGUIBUD_STATE_DIR` in a temp folder.
- (6) `pyguibud.core.__file__` and `pyguibud.designer.__file__` lie in the venv's site-packages, never in the checkout.
- (7) The German catalogue shipped. Run `pyguibud.i18n.set_language("de_DE")` (the runtime does not read `PYGUIBUD_LANG`), then `load_ui` on a dialog-only `.ui` without `master=`. `str(UiError)` must **equal** the de_DE msgstr of `runtime.no_main_window`; the script carries the expected German text as a literal. Also `Texts({}, "de_DE", None).runtime_text("_Cancel")` must equal "_Abbrechen" (the `_texts.py:103` path; the runtime builds no dialog button bar, so there is no button to read; amended in 20c). `tests/test_verify_install_literals.py` keeps the literals in step with the catalogue.

**Runtime-only venv:**
- (4) and (7) as above.
- `importlib.util.find_spec("pyguibud.designer") is None`.
- `importlib.metadata.distribution("pyguibud")` raises `PackageNotFoundError`.
- No `pyguibud`/`pyguibud-uic` script exists.
- After `import pyguibud_runtime`, `sys.modules` holds no `tkinter`/`ttkbootstrap`.

## 7. RC install commands (PowerShell, `X` = e.g. `0.1.0rc1`)
**Why exact pins:**
- pip and uv install a pre-release only when it is the sole candidate (PEP 440) or a specifier names one. The exact pin `pyguibud==X` (and the transitive `pyguibud-runtime==X`) is still recommended: it is squat-proof and stays on the RC once a final release exists. "No matching distribution" happens when the name is not on the index in use (e.g. before the first upload), not because only RCs exist.
- TestPyPI has only `ttkbootstrap` ≤ 1.7.2 (checked 2026-10-24). Under uv's default `first-index` strategy, `--index test.pypi` would stop there and fail. With `unsafe-best-match`, a squatted package on TestPyPI could win.
- So the recommended (squat-proof) recipe downloads only our two wheels from TestPyPI and takes everything else from PyPI.

```powershell
mkdir rc; py -m pip download --no-deps -d rc -i https://test.pypi.org/simple/ pyguibud==X pyguibud-runtime==X
# pip
py -m venv v; .\v\Scripts\python -m pip install --find-links rc pyguibud==X; .\v\Scripts\pyguibud --version
# uv tool (open a NEW terminal afterwards, or run `uv tool update-shell` once, so pyguibud is on PATH)
uv tool install --find-links rc pyguibud==X
pyguibud --version            # in the new terminal
# uvx (the plan row's `uvx pyguibud`)
uvx --find-links rc --from pyguibud==X pyguibud --version
uvx --find-links rc --from pyguibud==X pyguibud-uic --check hello.ui
# runtime only
py -m venv r; .\r\Scripts\python -m pip install --find-links rc pyguibud-runtime==X
```
- The plan-row form also works for pip, because both of our names 404 on PyPI today: `pip install -i https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ pyguibud==X`. pip picks the highest version across the indexes.
- For uv, the documented direct form is `--index https://test.pypi.org/simple/ --index-strategy unsafe-best-match`, accepting the squatting risk.

## 8. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | mypy reports "source file found twice under different module names", or a missing `pyguibud.designer` | `explicit_package_bases` + `mypy_path` in 20a, before any other change. Fallback: run mypy per root with `--namespace-packages` |
| R2 | A user folder named `pyguibud/` in the cwd joins the namespace | Documented in `install.md`. The CLIs run from installed scripts, so the cwd is not on `sys.path` for console scripts. Smoke (6) asserts that the real portions are used |
| R3 | Uninstalling only `pyguibud-runtime` leaves a broken designer | `pyguibud` pins it, and `pip check` reports the problem. Documented |
| R4 | A version bump breaks goldens, `uv.lock` (`--locked`) and the pins | `bump_version.py` + `test_version_sync.py` (D6) |
| R5 | A stale editable `pyguibud` 0.1.0.dev0 metadata folder leaves duplicate entry points | `uv sync` replaces it. D4 (a) treats the leftovers as forks, never as built-in |
| R6 | A wheel built straight from the tree differs from one built through the sdist | CI and release always use `uv build --all-packages` (sdist → wheel) and `check_dist.py` |
| R7 | The pending publishers' owner/repo/environment are mistyped → the upload fails with 403 | §5.3 lists the exact values. A failed TestPyPI job costs only one rcN bump |
| R8 | A pending publisher does **not** reserve a name (docs.pypi.org). If someone registers `pyguibud` or `pyguibud-runtime` first, the publisher is invalidated | Configure §5.3 only when 20b is green, then tag rc1 the same day. Both names were free on 2026-10-24 |

## 9. Open items (cannot be decided here)
- **O1 (decided, user 2026-10-24):** `https://github.com/larrezze-dev/PyGUIbud_CLAUDE` (owner `larrezze-dev`, repository `PyGUIbud_CLAUDE`), for `[project.urls]` and the trusted publishers.
- **O2 (decided, user 2026-10-24):** `master` stays the default branch.

## 10. Affected documents (on acceptance)
- `DEVELOPMENT_PLAN.md` row 20: parts 20a–20c with caps; §5 kickoff → 20a.
- ADR-016 → Accepted. ADR-007 gets a "Settled by ADR-016" line under its status.
- `docs/i18n/README.md`: catalogue paths. Skill `release-pip-uv`: the namespace layout, `uv build --all-packages`, and D5. The skill still calls ttkbootstrap an optional runtime extra. `FEATURES.md`: the install section, if one exists.

## As built
*(filled in per part)*

### 20a (2026-10-24, BACKEND)
- **Layout as §2.** Plain moves of `__about__.py`, `i18n.py`, `core/`, `backends/`, `locale/` and `pyguibud_runtime/` to `runtime/src/`; `src/pyguibud/__init__.py` and the top-level `py.typed` deleted; `py.typed` added to `core`, `backends`, `codegen`, `designer`, `preview`. Version `0.1.0rc1` (one literal); `pyguibud_runtime.__version__` imports it.
- **R1:** none. `mypy_path` + `explicit_package_bases` + `files` were clean on the first run (329 files × win32/linux/darwin); the fallback was not needed.
- **Registry D4** as specified. In addition, three leftover `"pyguibud"` literals in `registry.py` (the safety-net diagnostics and `_origin_name`) now use `_BUILTIN_DISTRIBUTION`, and `_distribution()` returns `_BUILTIN_DISTRIBUTION` for a built-in entry point whatever the metadata's spelling.
- **Deviation:** `designer/present/plugins.py` `_BUILTIN` became `"pyguibud-runtime"` (not in §4's list). The Help ▸ Plugins row stays "Built-in" and first, but its distribution column now reads `pyguibud-runtime`.
- **Deviation:** `runtime/pyproject.toml` has no `license-files` yet; LICENSE/NOTICE copies arrive in 20b, so the runtime wheel carries no licence file until then.
- **Goldens:** the codegen goldens are version-normalised (`normalise_version`), so `bump_version.py` regenerates only `examples/hello_ui.py`. `tests/test_version_sync.py` parses TOML with regexes (no `tomllib` on 3.10).
- **Also changed:** `CONTRIBUTING.md` (catalogue path, `uv run mypy`, the pip editable recipe now installs `./runtime` first). The `.pot` location comments still name the old paths until the next extract (the catalogue test compares msgids only).
- **Budget:** `src/**/*.py` + `runtime/src/**/*.py`: +20 / −24 (net −4; the deleted `__init__.py` is −11). Start numstat for 20b: run the same comparison against HEAD after the user commits 20a.
- **Venv note:** an empty `pyguibud-0.1.0.dev0.dist-info` (two 0-byte `.tmp` files from 2026-10-17) survived `uv sync` and made `metadata.version("pyguibud")` return `None`; it was removed by hand (R5).

### 20b (2026-10-24, ORCHESTRATOR)
- **Metadata (D7):** both projects have `readme`, `[project.urls]` (Homepage/Source/Issues/Changelog → `larrezze-dev/PyGUIbud_CLAUDE`), `Development Status :: 4 - Beta`, 8 × `Natural Language ::` and the 3.10–3.13 classifiers. The runtime adds keywords, `license-files` and byte copies of `LICENSE`/`NOTICE.md`. All 42 classifiers were checked against `trove-classifiers`. The READMEs are minimal, use absolute links only (PyPI) and end with the credit line.
- **Carried from 20a:** the runtime wheel now ships `licenses/LICENSE` + `licenses/NOTICE.md`. The root sdist adds `/runtime/src/pyguibud/locale` (the tests read the catalogues there), but no other runtime code. The runtime sdist is `src`, README, LICENSE, NOTICE and pyproject, with no tests.
- **`tools/check_dist.py`:** checks the wheel trees against the two source roots (minus caches and `.po`/`.pot`), plus overlap, the namespace `__init__`/`py.typed`, designer code in the runtime, 8 `.mo`, the XSD, `py.typed`, licence files, Markdown README + credit in METADATA, both exact runtime pins and the entry-point placement (`pyguibud.*` groups only in the runtime; console scripts only in `pyguibud`). It also checks the sdists (tests / no tests, `.po` sources, locale).
- **`ci.yml`:** triggers changed `main` → `master`, and `workflow_dispatch` added. `build` = `uv build --all-packages` + `twine check --strict` + `check_dist` + the artefact. `install-smoke` (ubuntu/windows × 3.10/3.13, bash, Xvfb on Linux):
  - the pip designer venv runs §6 checks (1), (2), (3), (4) and (6) plus `pip check`;
  - the runtime-only venv runs (4) and the runtime-only checks;
  - then `uv tool install` + `uvx … pyguibud-uic --check`.
  - **Deferred to 20c (`verify_install.py`):** checks (5), the headless `DesignerApp`, and (7), the German catalogue literals. The job will then call the script.
- **`release.yml`:** as §5.2; the build job outputs `version`/`prerelease`, and `publish-pypi` runs only when `prerelease == 'false'`.
- **Tests:** `tests/test_packaging_files.py` covers the licence byte copies, the README credit and absolute links, the metadata keys and the workflow invariants. `actionlint` (through `uvx --from actionlint-py`) is clean on both workflows.
- **Budget:** 0 / 60 net `src/**/*.py` + `runtime/src/**/*.py` lines (only TOML, tools, tests, workflows and docs changed). Start numstat for 20c: 0 against the 20b commit.
- **Git (user, 2026-10-24):** CLAUDE.md now allows autonomous git. 20b is committed on branch `step-20b` and pushed; the user opens the PR to `master` (`gh` is not installed). No `v*` tag is ever pushed by an agent, because a tag publishes.

### 20b.1 "CI green" (2026-10-26, ORCHESTRATOR + DEBUGGER; user ruling: blocking non-GUI everywhere, blocking GUI on Windows)
- **Why:** the first CI runs ever (the old trigger was `main`). Billing blocked the private repo; the user made it public. The first full run showed that the GUI suite had only ever been proven on the developer's Windows desktop.
- **CI layout (`ci.yml`):**
  - `UV_PYTHON_PREFERENCE: only-managed`, because the runner's system Python 3.12 has no tkinter.
  - `test`: 3 OS × py3.10–3.13, with lint, mypy and `-m "not qt and not gui"`. Blocking.
  - `gui`: `-m "gui and not qt"`. Blocking on Windows × 4 Pythons; non-blocking on ubuntu 3.10 (Tk 9), ubuntu 3.12 and macOS 3.12.
  - `qt`: blocking on ubuntu (now under xvfb) and Windows; non-blocking on macOS.
  - Xvfb runs a 1920x1200x24 screen.
  - `tests/conftest.py` auto-marks every test that uses `tk_root` as `gui`.
- **Product fixes (net +80 `src` lines, runtime 0):**
  - **Tk 9 + Python 3.10:** `Menu.index("end")` of an empty menu raised, so the designer did not start on uv's Linux/macOS CPython 3.10. Fixed with `theme_tk.menu_end`/`clear_menu`.
  - **Tk 9:** an unset `underline` reads `""`, which crashed the preview describe. Fixed with `theme_tk.underline_of`; Progressbar now has no portable text.
  - **Python 3.10:** a NUL truncates Text/clipboard, so Help ▸ Plugins now shows it as U+2400.
  - **POSIX:** a Windows-absolute image/include src is never rebased (`files.is_absolute_anywhere`).
  - **Dialogs:** a dialog pushed to the right edge now counts the Windows frame border (`screen.border_width`).
- **Test robustness:**
  - `reset_geometry` raises `wm maxsize` for small runner screens.
  - The event matrix fits 1024x700.
  - `.gitattributes` keeps `sape.json`/`icons.json` LF.
  - 3.13 changes handled: argparse deprecation msgids, the gettext plural rule, `re.PatternError`, the `winfo_children` menubar clone.
  - The export 10k test is now a `budget` test, so it is skipped under `--cov` and checked locally only.
- **Backlog "CI GUI parity" (after v1, non-blocking jobs):**
  - the ubuntu gui job dies with X `BadAlloc` in `test_qa14b1_abuse::test_q5_held_size_keys…`;
  - about 100 macOS gui failures (focus, clipboard, Ctrl/Cmd in Qt);
  - `tests/preview/test_child.py::test_closed_stdin…` errors on POSIX;
  - a huge plugin traceback row takes ≈ 5 s to select.
- **Gate:** CI run 5 (`d2dca13`) is green on every blocking job. Local full suite: 7047 passed, 2 failed (placement tests whose fake root lacked `winfo_x`), fixed in `030`; the affected files pass (74). mypy ×3 + ruff clean.

### 20c (2026-10-24, DEPLOYER + QA)
- **`tools/verify_install.py`** (stdlib): builds both distributions (or `--dist DIR`, or `--from-index testpypi --version X` = §7 download of our two wheels only), makes clean venvs in one temp folder outside the checkout, and runs every §6 check along the pip path (designer + runtime-only) and the uv path (`uv tool install` with `UV_TOOL_DIR`/`UV_TOOL_BIN_DIR` in the temp folder, `uvx`). Child processes get a cleaned environment (no `VIRTUAL_ENV`, `PYTHONPATH`, inherited `PYGUIBUD_*`; `PYGUIBUD_CONFIG_DIR`/`PYGUIBUD_STATE_DIR` always temp). `UV_CACHE_DIR` stays shared on purpose (content-addressed; faster, offline-capable uv path). Guards: `check_python` (≥ 3.10 up front), `check_artefacts` (folder exists, valid zip wheels, versions found), Ctrl+C → "interrupted", exit 130, stale `pyguibud-verify-*` folders older than 24 h swept, output safe on redirected Windows consoles. `install-smoke` now runs `python tools/verify_install.py --dist dist`.
- **§6 (7) amended:** the runtime builds no dialog button bar, so the button half reads `Texts({}, "de_DE", None).runtime_text("_Cancel")` == "_Abbrechen"; the UiError half uses a dialog-only `.ui` without `master=` (`runtime.no_main_window`). `tests/test_verify_install_literals.py` keeps the literals in step with the `.po`/`.mo`.
- **QA-20c-01 correction:** a pre-release that is the only candidate *is* installed by a bare `pip install pyguibud` (PEP 440); "no matching distribution" only means the name is missing from the index in use. The exact pin stays recommended (squat-proof; stays on the RC once a final exists). Fixed in §4, §7 and `docs/install.md`.
- **Tests:** `tests/test_install.py` (marker `install`, deselected through `addopts -m "not install"`), `tests/qa/test_step20c_install_abuse.py` (fast, no builds).
- **Verified:** Windows py3.12 and py3.10, 26 checks. **Not yet run:** Linux and py3.13 (first PR CI run), `--from-index testpypi` (needs the rc1 upload); macOS is not in the `install-smoke` matrix.
- **Budget:** 0 / 80 net src lines.
