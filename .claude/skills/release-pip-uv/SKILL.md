---
name: release-pip-uv
description: PyGUIbud packaging and release procedure compatible with pip and uv (hatchling, extras, two distributions, TestPyPI/PyPI trusted publishing, clean-venv verification). Use for scaffold packaging, CI workflows and release candidates.
---

# Packaging and release (pip + uv)

## Distributions
- `pyguibud` is a **PEP 420 namespace** split over two distributions (ADR-016): no `pyguibud/__init__.py`, no top-level `py.typed`.
- `pyguibud-runtime` (`runtime/`): `__about__`, `i18n`, `core/`, `backends/`, `locale/`, `pyguibud_runtime/`, all entry points. Depends on `ttkbootstrap>=2.2,<3` (hard dependency, spec packaging D5); extra `[pyside]`.
- `pyguibud` (root): designer, preview, codegen, CLIs (`pyguibud`, `pyguibud-uic`); pins `pyguibud-runtime==X` exactly. Extras `[pyside]`, `[dev]`.
- uv workspace (one `uv.lock`); build both with `uv build --all-packages`, then `tools/check_dist.py dist`.
- Build backend **hatchling**; one version literal in `runtime/src/pyguibud/__about__.py`, bumped with `tools/bump_version.py`.
- Compiled `.mo` files are committed; wheels ship `.mo` only, sdists keep `.po`/`.pot`. Exclude `assets/brand/` sources not needed at runtime.

## pyproject essentials
`requires-python = ">=3.10"` · classifiers (OS Independent, Tk, Qt) · `license = "MIT"` + `license-files = ["LICENSE", "NOTICE.md"]` · `[project.scripts]` · `[project.entry-points."pyguibud.backends"]` / `"pyguibud.widgets"` · `[dependency-groups] dev` for uv.

## Verification matrix (all must pass before a release)
```bash
uv build --all-packages                     # 2 sdists + 2 wheels (wheels built from the sdists)
uvx twine check --strict dist/*
uv run python tools/check_dist.py dist
# clean venv, pip
python -m venv /tmp/v && /tmp/v/bin/pip install dist/pyguibud-*.whl && /tmp/v/bin/pyguibud --version
# uv
uv tool install dist/pyguibud-*.whl && pyguibud --version
uvx --from dist/pyguibud-*.whl pyguibud-uic --help
# extras
pip install "dist/pyguibud-*.whl[pyside]"
```
On Windows use `.venv\Scripts\` paths. Test on py3.10 and the latest supported version.

## CI/CD (GitHub Actions)
Matrix Windows/macOS/Linux × py3.10–3.13: ruff, mypy, pytest (xvfb on Linux), build. Release workflow on tag `v*` → TestPyPI then PyPI with **trusted publishing** (OIDC, no tokens in the repo).

## Hard limits
The deployer **never** tags, pushes or uploads to PyPI/TestPyPI. It prepares everything, then gives the user the exact commands to run after approval.
