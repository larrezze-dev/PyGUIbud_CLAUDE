# PyGUIbud

A drag-and-drop GUI designer for **ttkbootstrap** (with tkinter and PySide6 back-ends) that saves
portable `.ui` files. Load a `.ui` file at run time with `pyguibud-runtime`, or turn it into a
plain Python module with `pyguibud-uic`.

> **Status:** release candidate (`0.1.0rc1`), published on TestPyPI only.

## Install
Python 3.10–3.13. On Linux, install Tk first (`sudo apt install python3-tk`).

```bash
pip install "pyguibud==0.1.0rc1"          # pip
uv tool install "pyguibud==0.1.0rc1"      # uv: the pyguibud and pyguibud-uic commands
uvx --from "pyguibud==0.1.0rc1" pyguibud  # uv: run without installing
```

The exact version is needed while only release candidates exist. Add the `[pyside]` extra for the
PySide6 back-end. A full install guide (including installing a release candidate from TestPyPI)
follows in `docs/install.md`.

## Use
```bash
pyguibud                       # open the designer
pyguibud-uic --check form.ui   # validate a .ui file
pyguibud-uic form.ui           # generate the Python module form_ui.py
```

```python
from pyguibud_runtime import load_ui


class Handlers:
    def on_quit(self) -> None:
        ui.destroy()


ui = load_ui("form.ui", Handlers())
ui.run()
```

Applications that only load `.ui` files need just
[`pyguibud-runtime`](https://pypi.org/project/pyguibud-runtime/).

## Links
- Source and issues: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Licence: MIT, see [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  The name, logo and SAPÉ brand assets are covered by
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Created by Luciano Arrezze and programmed with the support of Claude Code.
