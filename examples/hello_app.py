"""Run the generated ``hello_ui.py``; it needs only ttkbootstrap (PyGUIbud is not imported).

    uv run python examples/hello_app.py [--lang de_DE]

Enter or "Say hello" greets in the status bar, Ctrl+Q quits, F2 switches English <-> German.
Regenerate the interface with ``pyguibud-uic examples/hello.ui``. The German texts come from
``examples/locale/de_DE/LC_MESSAGES/hello.mo`` (compiled from ``hello.po``; the ``.mo`` is
committed, so nothing needs compiling to try it).
"""

from __future__ import annotations

import argparse
import gettext
import logging
import sys
from pathlib import Path

from hello_ui import Ui_Main, UiError

LOCALE = Path(__file__).resolve().parent / "locale"


class HelloApp:
    """The handlers of ``hello.ui``: called by name, with no arguments."""

    def __init__(self, lang: str | None) -> None:
        self.ui = Ui_Main()
        self.set_language(lang)
        self.ui.setup_ui(None, self, lang=lang)
        self.ui.windows["main"].bind("<F2>", lambda _event: self.toggle_language())

    def set_language(self, lang: str | None) -> None:
        self.lang = lang or "en_GB"
        languages = [lang] if lang else None
        self._ = gettext.translation("hello", LOCALE, languages, fallback=True).gettext

    def on_greet(self) -> None:
        name = self.ui.vars.user_name.get().strip()
        text = (
            self._("Hello, {name}!").format(name=name)
            if name
            else self._("Please enter your name.")
        )
        self.ui.sts_main.configure(text=text)

    def on_quit(self) -> None:
        self.ui.destroy()

    def toggle_language(self) -> None:
        self.set_language("de_DE" if self.lang == "en_GB" else "en_GB")
        self.ui.retranslate(self.lang)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the PyGUIbud hello example.")
    parser.add_argument("--lang", help="interface language, for example de_DE")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        app = HelloApp(args.lang)
    except (UiError, ValueError) as exc:  # ValueError: --lang is not a language code
        print(exc, file=sys.stderr)
        return 1
    app.ui.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
