# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - Unreleased

First public release.

### Added
- Designer: drag-and-drop canvas and palette, object tree, property inspector with typed editors,
  grid and pack layout editing, menu editor, event handlers, variables, templates, multi-select,
  copy/paste between files, undo/redo, keyboard-only operation, autosave with crash recovery, live
  preview in a separate process with live theme and language switch.
- `.ui` format: versioned and validated XML, with a schema-version migration hook.
- Runtime: `load_ui()` in `pyguibud-runtime`, returning the widgets, variables and windows.
- `pyguibud-uic`: `--check` to validate, code generation without any PyGUIbud import in the
  output, and `--extract` to produce a `.pot` catalogue.
- Back-ends: `ttkbootstrap` (reference), `tkinter` and `pyside6` (optional `[pyside]` extra).
- Plugins: widget plugin API through the `pyguibud.widgets` entry point, with an example plugin and
  failure isolation (a crashing plugin renders as a placeholder).
- Internationalisation: designer in en-GB, es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL and fr-FR,
  plus the `en_XA` pseudo-locale for layout testing.
- Safety and hardening: invalid actions blocked with a translated reason, atomic saves with
  backup, and refusal of corrupt, oversized or newer-schema files. A `.ui` file holds no code.
- Packaging: two distributions, `pyguibud` (designer and `pyguibud-uic`) and `pyguibud-runtime`,
  installable with pip and uv, for Python 3.10–3.13.

### Known limitations
- The font editor is deferred until after v1.
- GUI tests on Linux and macOS CI are non-blocking.

[Unreleased]: https://github.com/larrezze-dev/PyGUIbud_CLAUDE/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/larrezze-dev/PyGUIbud_CLAUDE/releases/tag/v0.1.0

Created by Luciano Arrezze and programmed with the support of Claude Code.
