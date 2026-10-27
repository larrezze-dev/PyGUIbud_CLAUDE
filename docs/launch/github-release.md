# GitHub Release v0.1.0

**DRAFT — not posted.**

- Tag: `v0.1.0` (the user tags; no agent pushes tags)
- Title: `PyGUIbud 0.1.0`
- Pre-release box: unticked (first public release)
- Note: the GIF uses the `?raw=true` form of the URL. A plain `blob/` URL returns an HTML page and
  does not render inside a release body. Confirm in the release preview.

Paste everything between the rules as the release body.

---

## PyGUIbud 0.1.0

First public release.

PyGUIbud is a drag-and-drop GUI designer for **ttkbootstrap** (with tkinter and PySide6
back-ends) that saves portable `.ui` files. Load a `.ui` file at run time with `pyguibud-runtime`,
or turn it into a plain Python module with `pyguibud-uic`.

![PyGUIbud designer: dragging widgets onto the canvas, saving a .ui file and running it](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/images/demo.gif?raw=true)

### Install

Python 3.10–3.13. On Linux, install Tk first (`sudo apt install python3-tk`).

```bash
pip install pyguibud          # pip
uv tool install pyguibud      # uv: the pyguibud and pyguibud-uic commands
uvx pyguibud                  # uv: run the designer without installing
```

Add the `[pyside]` extra (`pip install "pyguibud[pyside]"`) for the PySide6 back-end. Applications
that only load `.ui` files need just
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/). See the
[full install guide](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

### Quick start

```bash
pyguibud                                 # open the designer
pyguibud-uic --check form.ui             # validate a .ui file
pyguibud-uic form.ui                     # generate the Python module form_ui.py
```

```python
from pyguibud_runtime import load_ui


class Handlers:
    def on_quit(self) -> None:
        ui.destroy()


ui = load_ui("form.ui", Handlers())
ui.run()
```

### Added

- **Designer:** drag-and-drop canvas and palette, object tree, property inspector with typed
  editors, grid and pack layout editing, menu editor, event handlers, variables, templates,
  multi-select, copy/paste between files, undo/redo, keyboard-only operation, autosave with crash
  recovery, and a live preview in a separate process with live theme and language switch.
- **`.ui` format:** versioned and validated XML, with a schema-version migration hook.
- **Runtime:** `load_ui()` in `pyguibud-runtime`, returning the widgets, variables and windows.
- **`pyguibud-uic`:** `--check` to validate, code generation without any PyGUIbud import in the
  output, and `--extract` to produce a `.pot` catalogue.
- **Back-ends:** `ttkbootstrap` (reference), `tkinter` and `pyside6` (optional `[pyside]` extra).
- **Plugins:** widget plugin API through the `pyguibud.widgets` entry point, with an example plugin
  and failure isolation (a crashing plugin renders as a placeholder).
- **Internationalisation:** designer in en-GB, es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL and fr-FR,
  plus the `en_XA` pseudo-locale for layout testing.
- **Safety and hardening:** invalid actions blocked with a translated reason, atomic saves with
  backup, and refusal of corrupt, oversized or newer-schema files. A `.ui` file holds no code.
- **Packaging:** two distributions, `pyguibud` (designer and `pyguibud-uic`) and
  `pyguibud-runtime`, installable with pip and uv, for Python 3.10–3.13.

### Known limitations

- The font editor is deferred until after v1.
- GUI tests on Linux and macOS CI are non-blocking.

### Documentation in other languages

[Español](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.es-ES.md) ·
[Português (Portugal)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-PT.md) ·
[Português (Brasil)](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.pt-BR.md) ·
[Deutsch](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.de-DE.md) ·
[Italiano](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.it-IT.md) ·
[Nederlands](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.nl-NL.md) ·
[Français](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/readme/README.fr-FR.md)

### Thanks

PyGUIbud depends on [ttkbootstrap](https://github.com/israel-dryer/ttkbootstrap) (MIT) and uses
tkinter from the Python standard library (PSF licence). PySide6 (LGPL-3.0) is never bundled: it is
imported from your environment only if you install the `[pyside]` extra. Thanks to the authors of
all three.

### Licence

MIT, see [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE). The name,
logo and SAPÉ brand assets are not covered by it; see
[NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Bug reports, feedback and contributions are welcome: see
[CONTRIBUTING.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CONTRIBUTING.md).

**Full changelog:**
[CHANGELOG.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/CHANGELOG.md)

Created by Luciano Arrezze and programmed with the support of Claude Code.

---

Created by Luciano Arrezze and programmed with the support of Claude Code.
