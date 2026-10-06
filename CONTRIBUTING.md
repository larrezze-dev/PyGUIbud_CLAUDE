# Contributing to PyGUIbud

Thank you for helping. PyGUIbud is a drag-and-drop GUI designer for Python. It saves `.ui` files that can be loaded at runtime or exported as plain `.py`. Read [project.md](./project.md) and [FEATURES.md](./FEATURES.md) first; architecture decisions are in [`docs/adr/`](./docs/adr/).

By taking part you agree to the [Code of Conduct](./CODE_OF_CONDUCT.md).

## Licence of contributions
- Code is licensed under the [MIT Licence](./LICENSE). By submitting a pull request you agree that your contribution is released under the same licence (inbound = outbound). No CLA is required.

## Name, trademark and forks
Forks are welcome; the MIT Licence lets you fork, modify and redistribute the code. The licence does **not** cover the name or the brand (see [NOTICE.md](./NOTICE.md)):
- A fork may say it is "based on PyGUIbud", but it may not be distributed **as** "PyGUIbud" (PyPI name, app title, logo) without the creator's written consent.
- A fork must replace the SAPÉ brand assets in `assets/brand/`; they are not MIT-licensed.
- Preferred route before forking: extend PyGUIbud through **plugins** (below). If a plugin is not enough, open an issue; the change may belong in the core.

## Extending without patching the core
| You want to… | Use |
| --- | --- |
| Add a widget (icon, properties, live rendering) | Entry point group `pyguibud.widgets` → `WidgetSpec` ([ADR-004](./docs/adr/ADR-004-widget-plugins.md)) |
| Add a GUI toolkit (Kivy, wx…) | Entry point group `pyguibud.backends` |
| Add toolkit-specific widgets or attributes | Your own XML namespace with a `fallback` core class ([ADR-001](./docs/adr/ADR-001-abstract-vocabulary.md)) |

Never import a GUI toolkit inside `pyguibud.core`; the core stays toolkit-agnostic.

## Development set-up
Requires Python ≥ 3.10 and [uv](https://docs.astral.sh/uv/). The repository scaffold arrives in Step 04 of the [development plan](./DEVELOPMENT_PLAN.md).
```bash
uv sync --all-extras          # or: pip install -e ".[dev,pyside]"
uv run pre-commit install
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src/pyguibud/core
```

## Rules for every change
1. **Language:** code, identifiers, comments, UI strings and docs are written in **British English (en-GB)**: `colour`, `behaviour`, `licence` (noun), `initialise`, `serialise`.
2. **i18n:** every user-facing string goes through `_()`. Do not build sentences by concatenation; use named placeholders (`_("Saved {filename}").format(filename=…)`). Run `uv run pybabel extract` when you add strings.
3. **Translations:** catalogues live in `src/pyguibud/locale/<lang>/LC_MESSAGES/`. Mandatory locales: `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`. Translators may submit `.po` files only; follow the glossary in the translation docs and keep placeholders intact.
4. **Idiot-proofing:** any new editing operation must go through the command stack and the validator. Invalid actions are **blocked with a translated reason**, never applied silently ([FEATURES.md](./FEATURES.md) M23–M25).
5. **Tests:** new behaviour needs tests (pytest; hypothesis for parsers/validators). GUI tests must run headless (`pytest-xvfb` on Linux CI).
6. **Typing and style:** ruff clean, `mypy --strict` on `pyguibud.core`.
7. **`.ui` format:** changes to the schema need an ADR, a `schema_version` bump and a migration function.
8. **Security:** opening a `.ui` file must never execute code. Parse XML with the hardened loader only.

## Pull requests
- One topic per PR, linked to an issue. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `i18n:`…).
- CI must pass on Windows, macOS and Linux.
- Describe how a reviewer can test the change by hand (the project's UAT culture).

## AI-assisted contributions
AI tools are allowed; you are responsible for what you submit. The project's own agent definitions live in `.claude/agents/` and `.claude/skills/`. **Agents never commit or push**: a human reviews and commits every change.

## Optional dependencies
PySide6 is LGPL-3.0 and stays an optional extra (`[pyside]`), imported dynamically. Do not vendor or bundle it, and do not make the core depend on it.
