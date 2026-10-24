# Installing PyGUIbud

PyGUIbud ships as two packages:

- **`pyguibud`**: the designer and the `pyguibud` and `pyguibud-uic` commands. It needs
  `pyguibud-runtime` and installs it for you.
- **`pyguibud-runtime`**: the small loader that applications use to open `.ui` files.

Replace `X` below with the version you want, for example `0.1.0rc1`.

## Requirements
- Python 3.10, 3.11, 3.12 or 3.13.
- Tk (the library behind tkinter):
  - Windows: included with the python.org installer.
  - macOS: use the python.org installer, or `brew install python-tk` with Homebrew Python.
  - Linux: `sudo apt install python3-tk` (Debian, Ubuntu), `sudo dnf install python3-tkinter`
    (Fedora).

## Install with pip
```bash
pip install "pyguibud==X"
pyguibud --version
```
Use a virtual environment if you can (`python -m venv .venv`).

## Install with uv
```bash
uv tool install "pyguibud==X"    # installs the pyguibud and pyguibud-uic commands
uv tool update-shell             # once, if pyguibud is not found afterwards
pyguibud --version               # in a new terminal
```
To try it without installing anything:
```bash
uvx --from "pyguibud==X" pyguibud
uvx --from "pyguibud==X" pyguibud-uic --check form.ui
```
To add it to a uv project: `uv add "pyguibud==X"`. For a release candidate from the download
folder of the recipe below: `uv add --find-links rc "pyguibud==X"`.

## Runtime only
Applications that only load `.ui` files do not need the designer:
```bash
pip install "pyguibud-runtime==X"
```
It gives you `pyguibud_runtime.load_ui`, which builds a window from a `.ui` file with ttkbootstrap
(the default) or tkinter, and `ttkbootstrap` as a dependency. It does not give you the designer,
the `pyguibud` and `pyguibud-uic` commands, or the code generator.

## PySide6 back-end
PySide6 is optional. Add the extra to either package:
```bash
pip install "pyguibud[pyside]==X"
pip install "pyguibud-runtime[pyside]==X"
```

## Installing a release candidate from TestPyPI
Release candidates are published on TestPyPI only. TestPyPI does not carry current copies of
`ttkbootstrap`, and a package of the same name there could be planted by anyone. The safe recipe
therefore downloads only the two PyGUIbud wheels from TestPyPI and takes everything else from PyPI.

PowerShell (use `py -3.12`, or any 3.10+ version, instead of bare `py`: the launcher default may
be older):
```powershell
mkdir rc
py -3.12 -m pip download --no-deps -d rc -i https://test.pypi.org/simple/ pyguibud==X pyguibud-runtime==X
py -3.12 -m venv v
.\v\Scripts\python -m pip install --find-links rc pyguibud==X
.\v\Scripts\pyguibud --version
```

Linux/macOS (Git Bash on Windows: use `v/Scripts/` instead of `v/bin/`):
```bash
mkdir rc
python3 -m pip download --no-deps -d rc -i https://test.pypi.org/simple/ pyguibud==X pyguibud-runtime==X
python3 -m venv v
v/bin/python -m pip install --find-links rc pyguibud==X
v/bin/pyguibud --version
```

With uv, after the download step:
```bash
uv tool install --find-links rc pyguibud==X
uvx --find-links rc --from pyguibud==X pyguibud --version
```
For the runtime only, use `pyguibud-runtime==X` in the install line.

Always give the exact version. If a pre-release is the only candidate, pip and uv install it even
without a version (PEP 440), but the exact pin is safer: nobody can plant a different package under
the same name, and you stay on the release candidate once a final release exists. (`--pre` allows
pre-releases of every dependency, so avoid it.)

## Uninstall
```bash
pip uninstall pyguibud pyguibud-runtime
uv tool uninstall pyguibud
```
Remove both packages. If you remove only `pyguibud-runtime`, the designer stays installed but no
longer works; `pip check` reports it as a missing requirement. Reinstall the runtime, or remove
`pyguibud` too.

## Troubleshooting
- **"No matching distribution found for pyguibud" or "not found in the package registry".**
  The package is not on the index you are using. Release candidates are on TestPyPI only, so use the
  TestPyPI recipe above with the exact version (`pyguibud==X`). The same message appears before the
  first upload, when the names are not on PyPI yet.
- **"Ignored the following versions that require a different Python ... Requires-Python >=3.10",
  then "No matching distribution found for ttkbootstrap<3,>=2.2".** Your Python is too old (3.9 or
  earlier), so pip skips every newer `ttkbootstrap`. Use Python 3.10 or newer.
- **`No module named tkinter` or `No module named '_tkinter'`.** Your Python was built without Tk.
  Install it as listed under Requirements, then start a new Python. Homebrew Python needs
  `python-tk` matching its version.
- **`pyguibud` is not found after `uv tool install`.** The tool folder is not on your PATH. Run
  `uv tool update-shell` once and open a new terminal.
- **A folder named `pyguibud/` in your project breaks imports.** `pyguibud` is a namespace package
  shared by the two distributions, so a folder of that name in the current directory, or next to the
  script you run (Python puts the script's folder first on the import path), can join it and hide
  the real modules. Typical symptoms: `ModuleNotFoundError: No module named 'pyguibud.__about__'`
  or `ModuleNotFoundError: No module named 'pyguibud.core'`. Rename the folder (name your own
  package differently). The installed commands are not affected, because they do not put the
  current directory on the import path, but `python -c` and `python -m` do.
- **"Requires a different Python: 3.9" or "requires-python >=3.10".** PyGUIbud needs Python 3.10 or
  newer. Use a newer interpreter (`uv tool install --python 3.12 "pyguibud==X"`, or create the
  venv with `py -3.12 -m venv .venv` on Windows or `python3.12 -m venv .venv` elsewhere).

Created by Luciano Arrezze and programmed with the support of Claude Code.
