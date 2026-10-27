# Demo script (60-90 s video, and the GIF)

**DRAFT — not posted.**

Goal: show drag, save, run, and the generated code, using only features listed in the README.
Record at 1920x1080, no voice-over required; captions carry the message. Use a throwaway config
directory so your own designer settings do not appear (set `PYGUIBUD_CONFIG_DIR` and
`PYGUIBUD_STATE_DIR` to temporary folders before launching the designer).

Target length: about 75 s. The silent GIF (`docs/images/demo.gif`) is scenes 2 to 5, looped.

## Scenes

| # | Time | Action on screen | Caption (en-GB) |
| --- | --- | --- | --- |
| 1 | 0-5 s | Terminal: type `pip install pyguibud`, then `pyguibud`. The designer opens. | Install with pip or uv, then run `pyguibud`. |
| 2 | 5-25 s | Drag a Label, an Entry and a Button from the palette onto the canvas. Resize one widget; show it in the object tree. | Drag widgets from the palette onto the canvas. |
| 3 | 25-35 s | In the property inspector, change the button text. Use the grid layout so the widgets line up. Press undo, then redo. | Edit properties; every change can be undone. |
| 4 | 35-45 s | Open the live preview. Switch the theme, then the language. | Live preview, with a live theme and language switch. |
| 5 | 45-55 s | Save as `form.ui`. Show the first lines of the XML in an editor. | Save a portable, versioned `.ui` file. |
| 6 | 55-70 s | Terminal: run the 4-line loader (below). The window opens. | Load it at run time with `load_ui`... |
| 7 | 70-80 s | Terminal: `pyguibud-uic form.ui`, then open `form_ui.py`. | ...or generate plain Python with `pyguibud-uic`. |
| 8 | 80-85 s | Title card with the repository URL. | github.com/larrezze-dev/PyGUIbud_CLAUDE. MIT licence. |

Scene 6 code to type or paste (ruff-format clean):

```python
from pyguibud_runtime import load_ui

ui = load_ui("form.ui")
ui.run()
```

Optional end card, small print: "Built on ttkbootstrap, tkinter and PySide6. Created by Luciano
Arrezze and programmed with the support of Claude Code."

## Recording notes

- Keep the mouse movement slow; pause one second after each action.
- Use a plain colour theme and avoid personal files, paths and usernames in the frame.
- Use the SAPÉ logo only as NOTICE.md allows; the safest choice is not to show it.
- Keep captions in sans-serif, at least 32 px, with high contrast; they are the only text track.
- Export a video (MP4) and a silent GIF no larger than about 10 MB so GitHub renders it. Check
  the real size.
- Add captions as a subtitle file as well, so the video is accessible without sound.
- Scenes 2 to 5 must show what the build really does; if a feature behaves differently when
  recording, change the caption, not the facts.

## Alt text for `demo.gif` (en-GB)

Short (used in the README, the release and social posts):

```text
Screen recording of the PyGUIbud designer: widgets are dragged onto the canvas, the form is saved as a .ui file, and the saved form is run as a window.
```

Long description (for the repository documentation, if wanted):

```text
A silent recording of the PyGUIbud designer. A Label, an Entry and a Button are dragged from the
palette onto the canvas and arranged in a grid. The form is saved as a .ui file and then run as a
Python window. Captions describe each step.
```

Adjust both to match what the final recording actually shows.

Created by Luciano Arrezze and programmed with the support of Claude Code.
