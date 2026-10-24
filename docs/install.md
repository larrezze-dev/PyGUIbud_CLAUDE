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
To add it to a uv project: `uv add "pyguibud==X"`.

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

PowerShell:
```powershell
mkdir rc
py -m pip download --no-deps -d rc -i https://test.pypi.org/simple/ pyguibud==X pyguibud-runtime==X
py -m venv v
.\v\Scripts\python -m pip install --find-links rc pyguibud==X
.\v\Scripts\pyguibud --version
```

bash:
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

Always give the exact version. pip and uv skip pre-releases unless the requirement names one, so
`pip install pyguibud` without a version finds nothing while only release candidates exist. (`--pre`
also works, but it allows pre-releases of every dependency.)

## Uninstall
```bash
pip uninstall pyguibud pyguibud-runtime
uv tool uninstall pyguibud
```
Remove both packages. If you remove only `pyguibud-runtime`, the designer stays installed but no
longer works; `pip check` reports it as a missing requirement. Reinstall the runtime, or remove
`pyguibud` too.

## Troubleshooting
- **"No matching distribution found" or "No solution found".** Only pre-releases exist so far:
  give the exact version (`pyguibud==X`), and for a release candidate use the TestPyPI recipe above.
- **`No module named tkinter` or `No module named '_tkinter'`.** Your Python was built without Tk.
  Install it as listed under Requirements, then start a new Python. Homebrew Python needs
  `python-tk` matching its version.
- **`pyguibud` is not found after `uv tool install`.** The tool folder is not on your PATH. Run
  `uv tool update-shell` once and open a new terminal.
- **A folder named `pyguibud/` in your project breaks imports.** `pyguibud` is a namespace package
  shared by the two distributions, so a folder of that name in the current directory can join it and
  hide the real modules. Rename the folder (name your own package differently). The installed
  commands are not affected, because they do not put the current directory on the import path, but
  `python -c` and `python -m` do.
- **"Requires a different Python: 3.9" or "requires-python >=3.10".** PyGUIbud needs Python 3.10 or
  newer. Use a newer interpreter (`uv tool install --python 3.12 "pyguibud==X"`, or create the
  venv with it).

Created by Luciano Arrezze and programmed with the support of Claude Code.
