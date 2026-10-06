---
name: i18n-catalogue
description: PyGUIbud internationalisation workflow - gettext/Babel catalogues, the 8 locales, glossary, placeholders, pseudo-locale and translation quality gates. Use when adding user-facing strings, translating .po files or testing locales.
---

# i18n and catalogues

## Locales
Source `en_GB`. Targets: `es_ES`, `pt_PT`, `pt_BR`, `de_DE`, `it_IT`, `nl_NL`, `fr_FR`. Pseudo: `en_XA` (accented, +40 % length, bracketed).
Domain `pyguibud`; files in `src/pyguibud/locale/<lang>/LC_MESSAGES/pyguibud.po` → compiled `.mo` at build time.

## Workflow (Babel)
```bash
uv run pybabel extract -F babel.cfg -o src/pyguibud/locale/pyguibud.pot src/
uv run pybabel update  -i src/pyguibud/locale/pyguibud.pot -d src/pyguibud/locale -D pyguibud
uv run pybabel compile -d src/pyguibud/locale -D pyguibud --statistics
```

## Writing source strings
- Full sentences with named placeholders: `_("Cannot place {widget} inside {parent}: it is not a container.")`. Never concatenate fragments.
- Use `ngettext` for plurals and `pgettext(context, msg)` for ambiguous short strings ("Open" verb vs adjective).
- Mnemonics: `_File` (underscore marks the access key). Translators choose their own key, unique within the menu.
- Add `# Translators:` comments for anything non-obvious.

## Translating
- Keep placeholders, markup and mnemonic underscores intact. Match the source's punctuation style and the locale's conventions (French spaces before `:;?!`; German nouns capitalised).
- `pt_PT` ≠ `pt_BR`: e.g. *ficheiro* vs *arquivo*, *ecrã* vs *tela*, *guardar* vs *salvar*. Never copy one into the other.
- Formal register: es-ES *usted* (avoid where possible with impersonal forms), de *Sie*, fr *vous*, it *Lei*/impersonal, nl *u*, pt-PT impersonal / *você* sparingly, pt-BR *você*.
- Glossary: `docs/i18n/glossary.csv` (term, context, each locale). Add new UI terms (widget, container, handler, variable, layout, canvas, palette, inspector) before translating.

## Quality gates (tests)
100 % translated for all 7 targets · no fuzzy entries in releases · placeholder sets identical to the source · mnemonic present if the source has one · `.po` compiles without warnings · pseudo-locale screenshots show no truncation.

## Generated GUIs
`.ui` text props carry `translatable`, `context`, `comment`. `pyguibud-uic --extract` → `.pot` for the user's domain (`meta/@i18n_domain`).
