# Reddit r/Python

**DRAFT — not posted.**

## Rules status

I could not fetch the current r/Python rules: reddit.com is blocked for the tools available to me,
and no search result gave a current copy. What I found is only indirect:

- A 2020 moderator announcement made post flair mandatory, with an "I Made This" flair for
  projects (now called "Showcase", which I could not confirm). Source:
  <https://redlib.hackliberty.org/r/Python/comments/euprlf/changes_to_rpython/ffrd1cy/?context=3>
  (mirror of the original thread, 2020).
- The three-section template ("What My Project Does", "Target Audience", "Comparison") is used in
  showcase posts, but I found no source that makes it mandatory today. I follow it as you asked.

**Before posting, you must read the live rules** at <https://www.reddit.com/r/Python/about/rules>
(or the sidebar) and check: the exact flair name, whether the template headings are required,
rules on AI-assisted projects and posts, and any limit on self-promotion frequency. Adjust this
draft if anything differs.

## Post

- Flair: **Showcase**
- Title: see below (79 characters).

**Title:**

```text
PyGUIbud 0.1.0: a drag-and-drop GUI designer for ttkbootstrap, saving .ui files
```

(79 characters, hand-counted.)

**Body:**

---

I have released the first public version of PyGUIbud, a drag-and-drop GUI designer for
ttkbootstrap that saves portable `.ui` files. Repo: https://github.com/larrezze-dev/PyGUIbud_CLAUDE

![PyGUIbud: drag widgets onto the canvas, save a .ui file, run it](https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master/docs/images/demo.gif?raw=true)

(If the image does not render on Reddit, upload `demo.gif` to Reddit directly or link it as a
text link. Reddit does not always render images from Markdown links.)

## What My Project Does

PyGUIbud lets you build a window by dragging widgets from a palette onto a canvas. You move,
resize and reparent them on the canvas or in the object tree, edit their properties with typed
editors, and use grid or pack layouts, a menu editor, event handlers and variables bound to
widgets. There is multi-select, copy/paste between files, undo/redo, keyboard-only operation,
autosave with crash recovery, and a live preview in a separate process with a live theme and
language switch.

You save a versioned, validated XML `.ui` file. There are two ways to use it:

```python
from pyguibud_runtime import load_ui


class Handlers:
    def on_quit(self) -> None:
        ui.destroy()


ui = load_ui("form.ui", Handlers())
ui.run()
```

or generate a plain Python module with `pyguibud-uic form.ui`. The generated code does not import
PyGUIbud. `pyguibud-uic --check` validates a file, and `--extract` produces a `.pot` catalogue for
translators. The `backend` argument of `load_ui` accepts `"ttkbootstrap"` (the reference),
`"tkinter"` or `"pyside6"` (optional `[pyside]` extra).

A `.ui` file holds no code. Saving is atomic and keeps a backup, and corrupt, oversized or
newer-schema files are refused. Widgets can be added through plugins; a crashing plugin shows as
a placeholder instead of taking the designer down. The designer is available in British English,
Spanish, Portuguese (Portugal and Brazil), German, Italian, Dutch and French.

```bash
pip install pyguibud          # Python 3.10-3.13; on Linux install python3-tk first
uv tool install pyguibud
uvx pyguibud
```

Not in 0.1.0: the font editor, which is deferred until after v1.

## Target Audience

People who write Python desktop tools with tkinter or ttkbootstrap and would rather lay out a
window visually than in code, and who want the layout stored in a file that can be reviewed in
Git. It is a first release (0.1.0), so I would call it usable for small to medium tools and ask
for bug reports rather than recommend it for critical production work. Applications that only
load `.ui` files need just the small `pyguibud-runtime` package.

## Comparison

These are tools I know of; please correct me if I have misdescribed any of them.

- **PAGE** (Python Automatic GUI Generator) is a drag-and-drop builder for Tk and ttk widgets.
  It generates Python modules that need only Python 3 with ttk to run. It is written in Tcl/Tk.
  PyGUIbud differs by targeting ttkbootstrap first, storing the design in an XML file that can
  also be loaded at run time, and offering other back-ends.
- **pygubu-designer** is a GUI designer for tkinter that saves XML `.ui` files, which an
  application can load at run time with the pygubu builder, or it can generate Python code. It is
  the closest tool to PyGUIbud in approach. As far as I know it targets tkinter and ttk; PyGUIbud
  makes ttkbootstrap the reference back-end and adds an optional PySide6 back-end. I am less sure
  about its current ttkbootstrap support, so check its documentation.
- **Qt Designer** is the designer for Qt Widgets, and it also saves `.ui` XML files, used from
  Python with PySide6 or PyQt. It is a mature tool for Qt. PyGUIbud's `.ui` files are its own
  format, not Qt Designer files, and its PySide6 back-end loads them into PySide6 widgets. If you
  are building a Qt application, Qt Designer is the natural choice.

PyGUIbud builds on ttkbootstrap, tkinter and PySide6, and I am grateful to their authors.
Licence: MIT.

## AI-use disclosure

Created by me and programmed with the support of Claude Code.

Feedback, bug reports and questions are very welcome here or in the issue tracker.

---

## Notes for the author

- Remove the "(If the image does not render ...)" paragraph and this section before posting.
- Title length: the title above has been counted by hand at 79 characters; r/Python allows up to
  300, so it is fine.
- Reply to comments yourself, in your own words, and be factual when comparing with other tools.
- Comparison claims about PAGE and pygubu-designer are from their own pages (checked 2026-10-27):
  <https://page.sourceforge.net/> and <https://github.com/alejandroautalan/pygubu-designer>.
  The Qt Designer description is from <https://doc.qt.io/qt-6/qtdesigner-manual.html>; the `.ui`
  XML and PySide6 usage is from general knowledge of Qt tooling and was not on that page.
  Re-check all three the day you post.
- You may want to add a sentence on how you reviewed and tested the AI-assisted code. I left it
  out because the README does not describe it and I will not invent it.

Created by Luciano Arrezze and programmed with the support of Claude Code.
