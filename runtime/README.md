# pyguibud-runtime

The run-time half of [PyGUIbud](https://github.com/larrezze-dev/PyGUIbud_CLAUDE). It loads the
`.ui` files saved by the PyGUIbud designer and builds them with **ttkbootstrap** (default),
**tkinter** or **PySide6**. Applications need only this package, not the designer.

## Install
Python 3.10–3.13. On Linux, install Tk first (`sudo apt install python3-tk`).

```bash
pip install pyguibud-runtime
pip install "pyguibud-runtime[pyside]"   # adds the PySide6 back-end
```

More options (uv, TestPyPI, troubleshooting) are in the
[install guide](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/install.md).

## Use
```python
from pyguibud_runtime import load_ui


class Handlers:
    def on_quit(self) -> None:
        ui.destroy()


ui = load_ui("form.ui", Handlers())  # backend="tkinter" or "pyside6" also work
ui.run()
```

`load_ui` validates the file first and raises `pyguibud_runtime.UiError` with a readable reason
when it cannot be built. Its own messages and standard button texts come in the 8 PyGUIbud
languages (for example `lang="de_DE"`).

## Links
- Designer, source and issues: <https://github.com/larrezze-dev/PyGUIbud_CLAUDE>
- Licence: MIT, see [LICENSE](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/LICENSE).
  The name and logo are covered by
  [NOTICE.md](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/NOTICE.md).

Created by Luciano Arrezze and programmed with the support of Claude Code.
