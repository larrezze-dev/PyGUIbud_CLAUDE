"""Run ``hello.ui`` with ``pyguibud_runtime.load_ui`` (Step 10 UAT).

    uv run python examples/run_hello.py [--lang de_DE]

Enter or "Say hello" greets in the status bar, Ctrl+Q quits, F2 switches English <-> German.
"""

from __future__ import annotations

import argparse
import gettext
import logging
import sys
from pathlib import Path

from pyguibud_runtime import LoadedUi, UiError, load_ui

HERE = Path(__file__).resolve().parent
LOCALE = HERE / "locale"


class HelloApp:
    """The handlers of ``hello.ui``: called by name, with no arguments."""

    def __init__(self, lang: str | None) -> None:
        self.ui: LoadedUi | None = None
        self.set_language(lang)

    def set_language(self, lang: str | None) -> None:
        self.lang = lang or "en_GB"
        languages = [lang.replace("-", "_")] if lang else None
        self._ = gettext.translation("hello", LOCALE, languages, fallback=True).gettext

    def on_greet(self) -> None:
        assert self.ui is not None
        name = self.ui.vars.user_name.get().strip()
        text = (
            self._("Hello, {name}!").format(name=name)
            if name
            else self._("Please enter your name.")
        )
        self.ui.sts_main.configure(text=text)

    def on_quit(self) -> None:
        assert self.ui is not None
        self.ui.destroy()

    def toggle_language(self) -> None:
        assert self.ui is not None
        self.set_language("de_DE" if self.lang == "en_GB" else "en_GB")
        self.ui.retranslate(self.lang)


def build(lang: str | None) -> tuple[HelloApp, LoadedUi]:
    """Load the interface; raises ``UiError`` when it cannot be built."""
    app = HelloApp(lang)
    app.ui = load_ui(HERE / "hello.ui", app, lang=lang)
    app.ui.main.bind("<F2>", lambda _event: app.toggle_language())
    return app, app.ui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PyGUIbud hello example.")
    parser.add_argument("--lang", help="interface language, for example de_DE")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        _app, ui = build(args.lang)
    except (UiError, ValueError) as exc:  # ValueError: --lang is not a language code
        print(exc, file=sys.stderr)
        return 1
    ui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
