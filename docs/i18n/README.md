# PyGUIbud translations

Domain `pyguibud`; source language `en_GB` (British English).
Locales: `en_GB` (source, identity), `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`.
Catalogues are owned by `pyguibud-runtime` (ADR-016) and live in
`runtime/src/pyguibud/locale/<lang>/LC_MESSAGES/pyguibud.po` (+ compiled `.mo`, which are committed
on purpose so the runtime wheel ships them; wheels carry no `.po`/`.pot`). The template is
`runtime/src/pyguibud/locale/pyguibud.pot`. Extraction scans both source roots (`src` and
`runtime/src`) into the one `pyguibud` domain.

## Workflow (run from the repository root)

```bash
# 1. Extract source strings (`_`, `N_`, `NP_`, `NC_`, `ngettext`, `pgettext`, `npgettext`) into
#    the template. `NP_(singular, plural)` marks a deferred plural, translated on read with
#    ngettext and chosen by the `{count}` placeholder. `NC_(context, text)` marks a deferred
#    text with a context (msgctxt), translated on read with pgettext (a dialog button that must
#    not share the menu's translation).
uv run pybabel extract -F babel.cfg -o runtime/src/pyguibud/locale/pyguibud.pot \
  -k _ -k N_ -k "NP_:1,2" -k "NC_:1c,2" -k "ngettext:1,2" -k "pgettext:1c,2" \
  -k "npgettext:1c,2,3" \
  --add-comments=Translators: \
  --project=PyGUIbud --version=0.1.0 --copyright-holder="Luciano Arrezze" \
  --msgid-bugs-address=https://github.com/larrezze/PyGUIbud/issues --sort-by-file src runtime/src
# 2. Merge new/changed strings into every catalogue. --no-fuzzy-matching: a new msgid starts
#    empty instead of inheriting a similar string's translation as a (wrong) fuzzy guess.
#    --ignore-obsolete: drop `#~` entries of removed msgids instead of piling them up
uv run pybabel update --no-fuzzy-matching --ignore-obsolete -i runtime/src/pyguibud/locale/pyguibud.pot \
  -d runtime/src/pyguibud/locale -D pyguibud
# 3. Translate the .po files (resolve every fuzzy entry), then compile
uv run pybabel compile -d runtime/src/pyguibud/locale -D pyguibud --statistics
```

A new locale is created with `pybabel init -l <code> -D pyguibud -d runtime/src/pyguibud/locale -i <pot>`.
`tests/test_catalogues.py` fails when the `.pot` is stale or a catalogue drifts from it.

## Rules

- Keep placeholders (`{name}`, `%(name)s`), markup and mnemonic underscores intact.
- `pt_PT` and `pt_BR` are strictly separate; use the formal register of each language.
- Use the terms in `glossary.csv` (UTF-8, one column per locale) and add new terms before translating.

## Pseudo-locale

`en_XA` has no catalogue: it is generated at runtime (accented, about 40 % longer, bracketed) to
reveal truncation and untranslated strings. Try `pyguibud --lang en_XA`.

## Status

Since Step 18 the seven target catalogues are 100 % translated with no fuzzy entries;
`tests/test_catalogues.py` keeps them that way (placeholders, mnemonics, plural forms, stale `.mo`,
pt_PT/pt_BR variants). A damaged `.mo` falls back to the English source with one warning.

## Helper

`tools/po_roundtrip.py` fills a catalogue without hand-editing it:
`dump <locale> <file.json> [--all]` → edit the `msgstr` values → `load <locale> <file.json>`
(refuses placeholder or access-key mismatches) → `check <locale>`. Then compile (step 3).
