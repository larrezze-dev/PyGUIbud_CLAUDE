# PyGUIbud translations

Domain `pyguibud`; source language `en_GB` (British English).
Locales: `en_GB` (source, identity), `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`.
Catalogues live in `src/pyguibud/locale/<lang>/LC_MESSAGES/pyguibud.po` (+ compiled `.mo`, which
are committed on purpose so the wheel ships them). The template is `src/pyguibud/locale/pyguibud.pot`.

## Workflow (run from the repository root)

```bash
# 1. Extract source strings (`_`, `N_`, `NP_`, `ngettext`, `pgettext`, `npgettext`) into the
#    template. `NP_(singular, plural)` marks a deferred plural, translated on read with ngettext
#    and chosen by the `{count}` placeholder.
uv run pybabel extract -F babel.cfg -o src/pyguibud/locale/pyguibud.pot \
  -k _ -k N_ -k "NP_:1,2" -k "ngettext:1,2" -k "pgettext:1c,2" -k "npgettext:1c,2,3" \
  --add-comments=Translators: \
  --project=PyGUIbud --version=0.1.0 --copyright-holder="Luciano Arrezze" \
  --msgid-bugs-address=https://github.com/larrezze/PyGUIbud/issues --sort-by-file src
# 2. Merge new/changed strings into every catalogue
uv run pybabel update -i src/pyguibud/locale/pyguibud.pot -d src/pyguibud/locale -D pyguibud
# 3. Translate the .po files (resolve every fuzzy entry), then compile
uv run pybabel compile -d src/pyguibud/locale -D pyguibud --statistics
```

A new locale is created with `pybabel init -l <code> -D pyguibud -d src/pyguibud/locale -i <pot>`.
`tests/test_catalogues.py` fails when the `.pot` is stale or a catalogue drifts from it.

## Rules

- Keep placeholders (`{name}`, `%(name)s`), markup and mnemonic underscores intact.
- `pt_PT` and `pt_BR` are strictly separate; use the formal register of each language.
- Use the terms in `glossary.csv` (UTF-8, one column per locale) and add new terms before translating.

## Pseudo-locale

`en_XA` has no catalogue: it is generated at runtime (accented, about 40 % longer, bracketed) to
reveal truncation and untranslated strings. Try `pyguibud --lang en_XA`.

## Status

The seven target catalogues are currently empty stubs (the runtime falls back to the English
source). Step 18 completes the translations (100 % per locale, no fuzzy entries).
