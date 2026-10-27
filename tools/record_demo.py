"""Record the README demo GIF "drag -> save -> run" from the real designer (dev tool).

Usage: ``uv run python tools/record_demo.py [--out docs/images/demo.gif] [--fps 8]``.

The script starts the real ``DesignerApp`` in this process (en-GB, SAPE light theme, a fixed
1100 x 700 window kept on top), drives it through the same paths a user takes (a palette ->
canvas drag-and-drop with press/motion/release events, inspector edits, the Events tab) and
grabs the window region with ``PIL.ImageGrab`` on an ``after()`` timer. The save is done with
the app's own save path straight to a known file, because a native file dialog can be neither
captured nor driven. "Run" builds the saved ``hello.ui`` with ``pyguibud_runtime.load_ui`` in a
Toplevel of the same process: the live preview is a separate process whose window position and
start-up time cannot be controlled, and the topmost designer would cover it.

Settings, recent files and recovery data go to a fresh temporary folder (see
``isolate_settings``), set before any designer module is imported, so that the user's real
profile is never read or written. Next to the GIF it writes ``designer.png`` (one still frame).
The desktop must stay untouched while it records (about 20 s).

Only stdlib and Pillow (which ttkbootstrap already depends on) are used.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import sys
import tempfile
import time
import traceback
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "docs" / "images" / "demo.gif"
STILL_NAME = "designer.png"
WINDOW = (1100, 700)  # client size of the designer
POSITION = (40, 40)  # top-left corner on the primary screen
WATCHDOG_MS = 90_000
SIZE_LIMIT = 3 * 1024 * 1024
#: Environment variables that point the designer's profile folders elsewhere.
PROFILE_VARS = ("PYGUIBUD_CONFIG_DIR", "PYGUIBUD_STATE_DIR")

Step = tuple[int, Callable[[], None]]  # (delay before it in ms, action)


def isolate_settings() -> Path:
    """Point settings and recovery data at a fresh temporary folder and return that folder.

    Must run before any ``pyguibud.designer`` import: the designer reads these variables.
    """
    base = Path(tempfile.mkdtemp(prefix="pyguibud-demo-"))
    os.environ["PYGUIBUD_CONFIG_DIR"] = str(base / "config")
    os.environ["PYGUIBUD_STATE_DIR"] = str(base / "state")
    os.environ["PYGUIBUD_LANG"] = "en_GB"
    return base


class DemoError(RuntimeError):
    """A scripted step did not leave the designer in the expected state."""


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise DemoError(message)


def _window_rect(root: Any) -> tuple[int, int, int, int]:  # noqa: ANN401 - a Tk root
    """The visible outer rectangle of the window (title bar and menubar included), in pixels."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        rect = wintypes.RECT()
        hwnd = int(root.wm_frame(), 16)
        dwm_extended_frame_bounds = 9  # without the invisible resize borders
        result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
            wintypes.HWND(hwnd), dwm_extended_frame_bounds, ctypes.byref(rect), ctypes.sizeof(rect)
        )
        if result == 0:
            return rect.left, rect.top, rect.right, rect.bottom
    x, y = root.winfo_rootx(), root.winfo_rooty()
    return x, y, x + root.winfo_width(), y + root.winfo_height()


class Recorder:
    """Runs the scripted steps and the frame grabber, both on the Tk event loop."""

    def __init__(self, root: Any, app: Any, folder: Path, fps: int) -> None:  # noqa: ANN401
        from PIL import ImageGrab

        self.root, self.app, self.folder = root, app, folder
        # GIF stores durations in 10 ms units: a multiple of 10 keeps the real-time pace.
        self.interval = max(10, round(1000 / fps / 10) * 10)
        self.frames: list[Any] = []  # PIL images (RGB)
        self.durations: list[int] = []
        self.still: Any = None
        self.error: BaseException | None = None
        self.pointer: tuple[int, int] | None = None  # synthetic pointer, Tk screen coordinates
        self.steps: Iterator[Step] = iter(())
        self.done = False
        self.ui: Any = None
        self._grab = ImageGrab.grab
        self._prev: Any = None
        self.bbox = _window_rect(root)
        # Tk may work in logical pixels while the grab works in physical ones.
        self.scale = ImageGrab.grab().size[0] / max(1, root.winfo_screenwidth())

    # ------------------------------------------------------------ loop plumbing
    def fail(self, exc: BaseException) -> None:
        if self.error is None:
            self.error = exc
        self.root.quit()

    def run(self, steps: list[Step]) -> None:
        self.steps = iter(steps)
        self.root.report_callback_exception = lambda _t, exc, _tb: self.fail(exc)
        self.root.after(WATCHDOG_MS, lambda: self.fail(DemoError("the demo timed out")))
        self.root.after(0, self._capture)
        self._next()
        self.root.mainloop()
        if self.error is not None:
            raise self.error

    def _next(self) -> None:
        step = next(self.steps, None)
        if step is None:
            self.done = True
            self.root.quit()
            return
        delay, action = step

        def fire() -> None:
            try:
                action()
            except BaseException as exc:
                self.fail(exc)
                return
            self._next()

        self.root.after(delay, fire)

    def _capture(self) -> None:
        if self.done or self.error is not None:
            return
        try:
            self.frames_add(self.grab())
        except BaseException as exc:
            self.fail(exc)
            return
        self.root.after(self.interval, self._capture)

    def grab(self) -> Any:  # noqa: ANN401 - a PIL image
        from PIL import ImageDraw

        image = self._grab(bbox=self.bbox, all_screens=True).convert("RGB")
        if self.pointer is not None:  # the OS cursor is not captured: draw a stand-in
            px = round(self.pointer[0] * self.scale) - self.bbox[0]
            py = round(self.pointer[1] * self.scale) - self.bbox[1]
            arrow = [(0, 0), (0, 17), (4, 13), (7, 20), (10, 19), (7, 12), (12, 12)]
            ImageDraw.Draw(image).polygon(
                [(px + dx, py + dy) for dx, dy in arrow], fill="white", outline="black"
            )
        return image

    def frames_add(self, image: Any) -> None:  # noqa: ANN401 - a PIL image
        from PIL import ImageChops

        if self._prev is not None and ImageChops.difference(self._prev, image).getbbox() is None:
            self.durations[-1] += self.interval  # a duplicate: show the previous one longer
            return
        self.frames.append(image)
        self.durations.append(self.interval)
        self._prev = image

    # ------------------------------------------------------------ scripted gestures
    def settle(self) -> None:
        for _ in range(3):
            self.root.update_idletasks()

    def drag(
        self, name: str, target: Callable[[], tuple[int, int]], *, elbow: bool = False
    ) -> list[Step]:
        """A palette -> canvas drag of ``name`` with visible motion, a rest on the target and
        a drop; the same events the designer tests generate (``tests/designer/test_drag.py``).

        ``elbow``: go down inside the palette first, then across at the target's height, so the
        pointer never rests on an occupied cell on its way (that would show a denial).
        """
        tree = self.app.shell.palette.tree
        state: dict[str, Any] = {}

        def press() -> None:
            tree.see(f"w:{name}")
            self.settle()
            x, y, _w, h = (int(v) for v in tree.bbox(f"w:{name}"))
            sx, sy = tree.winfo_rootx() + x + 12, tree.winfo_rooty() + y + h // 2
            state["start"], state["end"] = (sx, sy), target()
            self.pointer = (sx, sy)
            tree.selection_set(f"w:{name}")
            tree.event_generate("<ButtonPress-1>", x=x + 12, y=y + h // 2, rootx=sx, rooty=sy)

        def motion(fraction: float) -> Callable[[], None]:
            def move() -> None:
                (sx, sy), (tx, ty) = state["start"], state["end"]
                if elbow and fraction <= 0.5:
                    px, py = sx, round(sy + (ty - sy) * fraction * 2)
                elif elbow:
                    px, py = round(sx + (tx - sx) * (fraction - 0.5) * 2), ty
                else:
                    px, py = round(sx + (tx - sx) * fraction), round(sy + (ty - sy) * fraction)
                if fraction < 0.1:  # past the drag threshold first, as a hand would
                    px, py = sx + 12 + round(200 * fraction), sy
                self.pointer = (px, py)
                tree.event_generate(
                    "<B1-Motion>", x=px - tree.winfo_rootx(), y=py - tree.winfo_rooty(),
                    rootx=px, rooty=py, state=0x100,
                )  # fmt: skip

            return move

        def release() -> None:
            tx, ty = state["end"]
            tree.event_generate(
                "<ButtonRelease-1>", x=tx - tree.winfo_rootx(), y=ty - tree.winfo_rooty(),
                rootx=tx, rooty=ty, state=0x100,
            )  # fmt: skip

        fractions = [0.02, 0.06] + [k / 14 for k in range(2, 15)]
        steps: list[Step] = [(500, press)]
        steps += [(60, motion(f)) for f in fractions]
        steps += [(700, motion(1.0)), (100, release)]
        return steps

    def type_text(self, key: str, text: str, *, events: bool = False) -> list[Step]:
        """Type ``text`` into the inspector field ``key`` one character per tick, then commit."""
        inspector = self.app.shell.inspector

        def editor() -> Any:  # noqa: ANN401 - an inspector editor
            found = (
                next((b for b in inspector.events.boxes if b.field.key == key), None)
                if events
                else inspector._editors.get(key)
            )
            _check(found is not None, f"the inspector has no field {key!r}")
            return found

        def begin() -> None:
            box = editor()
            widget = getattr(box, "widget", None)
            if widget is not None:
                self.pointer = (
                    widget.winfo_rootx() + widget.winfo_width() // 2,
                    widget.winfo_rooty() + widget.winfo_height() // 2,
                )
                widget.focus_set()
            box.var.set("")

        def typed(count: int) -> Callable[[], None]:
            return lambda: editor().var.set(text[:count])

        def commit() -> None:
            box = editor()
            if events:
                _check(box.commit_pending(), f"the handler {text!r} was refused")
            else:
                box._enter()

        steps: list[Step] = [(500, begin)]
        steps += [(90, typed(n)) for n in range(1, len(text) + 1)]
        steps.append((400, commit))
        return steps


def build_steps(rec: Recorder, target: Path) -> list[Step]:
    """The demo: new main window, drag a Label and a Button, edit them, save, run."""
    app, root = rec.app, rec.root

    def window() -> Any:  # noqa: ANN401 - the document's window node
        document = app.session.document
        _check(document is not None, "no document is open")
        return document.children[0]

    def body() -> Any:  # noqa: ANN401 - the canvas widget of the window body (rebuilt per edit)
        view = app.shell.canvas.stages[0].view
        _check(view is not None, "the canvas shows no window")
        return view.inner[id(window())]

    def label_point() -> tuple[int, int]:
        b = body()
        return b.winfo_rootx() + b.winfo_width() // 2, b.winfo_rooty() + 40

    def button_point() -> tuple[int, int]:
        b = body()
        return b.winfo_rootx() + b.winfo_width() // 2, b.winfo_rooty() + b.winfo_height() - 14

    def node(node_id: str) -> Any:  # noqa: ANN401 - a model widget
        found = next((c for c in window().children if getattr(c, "id", "") == node_id), None)
        _check(found is not None, f"{node_id!r} was not inserted")
        return found

    def new_window() -> None:
        _check(app.new_from_template("main_window"), "the main window template did not open")

    def dropped(node_id: str) -> Callable[[], None]:
        def check() -> None:
            selected = app.session.selection.node
            _check(selected is node(node_id), f"{node_id!r} is not selected after the drop")
            rec.pointer = None

        return check

    def text_is(node_id: str, text: str) -> Callable[[], None]:
        def check() -> None:
            prop = node(node_id).props.get("text")
            _check(prop is not None and prop.value == text, f"{node_id!r} text is not {text!r}")

        return check

    def show_events() -> None:
        inspector = app.shell.inspector
        inspector.notebook.select(str(inspector.events.frame))

    def handler_set() -> None:
        events = [(e.name, e.handler) for e in node("button1").events]
        _check(events == [("command", "on_hello")], f"unexpected events {events!r}")
        rec.pointer = None

    def save() -> None:
        errors = app.session.report().errors
        _check(not errors, f"the document has validation errors: {errors!r}")
        app._save_to(target, None)  # File > Save without the native dialog
        _check(app.session.path == target and target.is_file(), "hello.ui was not saved")
        _check(not app.session.dirty, "the document is still dirty after saving")

    def unfocus() -> None:
        rec.pointer = None
        app.shell.palette.tree.focus_force()  # no text caret in the inspector field

    def still() -> None:
        rec.settle()
        rec.still = rec.grab()

    def run_ui() -> None:
        from pyguibud_runtime import load_ui

        def on_hello() -> None:
            rec.ui.label1.configure(text="Hello from PyGUIbud!")

        rec.ui = load_ui(target, {"on_hello": on_hello, "on_quit": lambda: None}, master=root)
        rec.ui.show("main")
        top = rec.ui.windows["main"]
        b = body()
        x, y = b.winfo_rootx() + 30, b.winfo_rooty() - 60
        top.geometry(f"420x240+{x}+{y}")
        top.attributes("-topmost", True)
        top.lift()

    def point_at_button() -> None:
        button = rec.ui.button1
        rec.pointer = (
            button.winfo_rootx() + button.winfo_width() // 2,
            button.winfo_rooty() + button.winfo_height() // 2,
        )

    def press_button() -> None:
        rec.ui.button1.state(["pressed"])

    def click_button() -> None:
        rec.ui.button1.state(["!pressed"])
        rec.ui.button1.invoke()
        _check(str(rec.ui.label1.cget("text")) == "Hello from PyGUIbud!", "on_hello did not run")

    def close_ui() -> None:
        rec.ui.destroy()
        rec.ui, rec.pointer = None, None

    label_text, button_text = "Click the button", "Say hello"
    return [
        (1200, new_window),
        *rec.drag("Label", label_point),
        (300, dropped("label1")),
        *rec.type_text("prop:text", label_text),
        (200, text_is("label1", label_text)),
        *rec.drag("Button", button_point, elbow=True),
        (300, dropped("button1")),
        *rec.type_text("prop:text", button_text),
        (200, text_is("button1", button_text)),
        (500, unfocus),
        (300, still),
        (300, show_events),
        *rec.type_text("event:command", "on_hello", events=True),
        (200, handler_set),
        (900, save),
        (1600, run_ui),
        (900, point_at_button),
        (700, press_button),
        (180, click_button),
        (2200, close_ui),
        (900, lambda: None),  # a last look at the designer before the loop restarts
    ]


def write_gif(frames: list[Any], durations: list[int], out: Path) -> None:
    """One adaptive palette shared by every frame (no flicker, small deltas), looping forever."""
    from PIL import Image

    count = min(6, len(frames))
    picks = [frames[round(i * (len(frames) - 1) / max(1, count - 1))] for i in range(count)]
    width, height = frames[0].size
    sheet = Image.new("RGB", (width, height * len(picks)))
    for i, frame in enumerate(picks):
        sheet.paste(frame, (0, i * height))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    images = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    out.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="the GIF to write")
    parser.add_argument("--fps", type=int, default=8, help="frames per second (default 8)")
    args = parser.parse_args(argv)
    out: Path = args.out.resolve()
    fps = max(1, min(int(args.fps), 25))

    base = isolate_settings()  # before ANY pyguibud.designer import
    root: Any = None
    app: Any = None
    rec: Recorder | None = None
    try:
        import ttkbootstrap

        from pyguibud.designer.app import DesignerApp
        from pyguibud.i18n import set_language

        set_language("en_GB")
        root = ttkbootstrap.App(title="PyGUIbud")
        app = DesignerApp(root, role="light")
        app.set_theme("light")
        app.flush_theme()
        root.geometry(f"{WINDOW[0]}x{WINDOW[1]}+{POSITION[0]}+{POSITION[1]}")
        root.attributes("-topmost", True)
        root.deiconify()
        root.lift()
        for _ in range(5):
            root.update()
        time.sleep(0.3)  # let the compositor show the window before the first grab
        root.update()
        rec = Recorder(root, app, base, fps)
        target = base / "hello.ui"
        rec.run(build_steps(rec, target))
        _check(len(rec.frames) > 10, f"only {len(rec.frames)} frames were captured")
        write_gif(rec.frames, rec.durations, out)
        still = rec.still if rec.still is not None else rec.frames[len(rec.frames) // 2]
        still.save(out.with_name(STILL_NAME), optimize=True)
    except BaseException as exc:
        print(f"record_demo: FAILED: {exc}", file=sys.stderr)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
        return 1
    finally:
        if rec is not None and rec.ui is not None:
            with contextlib.suppress(Exception):
                rec.ui.destroy()
        if app is not None:
            with contextlib.suppress(Exception):
                app.dispose()
        if root is not None:
            with contextlib.suppress(Exception):
                root.destroy()
        for var in PROFILE_VARS:
            os.environ.pop(var, None)
        shutil.rmtree(base, ignore_errors=True)
        if base.exists():
            print(f"record_demo: warning: could not remove {base}", file=sys.stderr)
    size = out.stat().st_size
    total = sum(rec.durations) / 1000 if rec is not None else 0.0
    count = len(rec.frames) if rec is not None else 0
    print(f"Wrote {out} ({size / 1024:.0f} KiB, {count} frames, {total:.1f} s)")
    print(f"Wrote {out.with_name(STILL_NAME)}")
    if size > SIZE_LIMIT:
        print("record_demo: warning: the GIF is larger than 3 MB", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
