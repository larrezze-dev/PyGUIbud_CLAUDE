---
name: release-pip-uv
description: PyGUIbud packaging and release procedure compatible with pip and uv (hatchling, extras, two distributions, TestPyPI/PyPI trusted publishing, clean-venv verification). Use for scaffold packaging, CI workflows and release candidates.
---

# Packaging and release (pip + uv)

## Distributions
- `pyguibud`: designer + CLIs (`pyguibud`, `pyguibud-uic`). Extras: `[pyside]` (PySide6), `[dev]`.
- `pyguibud-runtime`: `load_ui()` only; depends on stdlib (+ ttkbootstrap optional extra).
- Build backend **hatchling**; `src/` layout; version from a single source (`__about__.py` or VCS tag via hatch-vcs).
- Include compiled `.mo` files and themes in the wheel (hatch build hook runs `pybabel compile`). Exclude `assets/brand/` sources not needed at runtime.

## pyproject essentials
`requires-python = ">=3.10"` · classifiers (OS Independent, Tk, Qt) · `license = "MIT"` + `license-files = ["LICENSE", "NOTICE.md"]` · `[project.scripts]` · `[project.entry-points."pyguibud.backends"]` / `"pyguibud.widgets"` · `[dependency-groups] dev` for uv.

## Verification matrix (all must pass before a release)
```bash
uv build                                    # sdist + wheel
uvx twine check dist/*
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
