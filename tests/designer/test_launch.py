"""``designer.launch``: the no-display path (pure) and a real, short-lived window (gui)."""

from __future__ import annotations

import subprocess
import sys
import tkinter
from typing import Any

import pytest

from pyguibud import designer
from pyguibud.designer.app import CLI_THEMES, DesignerApp


def test_no_display_exits_1_with_translated_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import ttkbootstrap

    def no_display(*_args: object, **_kwargs: object) -> None:
        raise tkinter.TclError("no display name and no $DISPLAY environment variable")

    monkeypatch.setattr(ttkbootstrap, "App", no_display)
    assert designer.launch("en_GB", "light") == 1
    err = capsys.readouterr().err
    assert "cannot be opened" in err
    assert "no display name" in err
    assert "Traceback" not in err


def test_no_display_message_is_translated(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from pyguibud import i18n

    i18n.set_language("en_XA")
    assert designer.report_cannot_open("boom", tk_missing=True) == 1
    err = capsys.readouterr().err.splitlines()
    assert len(err) == 2
    assert all(line.startswith("[") for line in err)  # the pseudo-locale marks translations


def test_missing_tkinter_exits_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setitem(sys.modules, "pyguibud.designer.app", None)  # import raises ImportError
    assert designer.launch("en_GB", "light") == 1
    err = capsys.readouterr().err
    assert "cannot be opened" in err
    assert "Install Tk" in err
    assert "Traceback" not in err


def test_cli_theme_names_map_to_roles() -> None:
    assert CLI_THEMES == {"light": "light", "dark": "dark", "high-contrast": "high_contrast"}


@pytest.mark.gui
def test_shell_builds_with_title_and_minsize(shell: DesignerApp) -> None:
    root: Any = shell.root
    assert root.title() == "PyGUIbud designer"
    assert root.minsize()[0] >= 800


@pytest.mark.gui
def test_title_follows_language(shell: DesignerApp) -> None:
    from pyguibud import i18n

    i18n.set_language("en_XA")
    assert shell.root.title().startswith("[")
    i18n.set_language("en_GB")
    assert shell.root.title() == "PyGUIbud designer"


@pytest.mark.gui
@pytest.mark.parametrize("theme", ["light", "dark", "high-contrast"])
def test_launch_opens_and_closes_a_real_window(theme: str) -> None:
    """A separate process (the shared root must stay alone): window opens, closes, exit 0."""
    script = (
        "import sys, ttkbootstrap\n"
        "orig = ttkbootstrap.App.mainloop\n"
        "def short(self, n=0):\n"
        "    self.update()\n"
        "    self.after(400, self.destroy)\n"
        "    orig(self, n)\n"
        "ttkbootstrap.App.mainloop = short\n"
        "from pyguibud.designer import launch\n"
        f"sys.exit(launch('en_GB', {theme!r}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60, check=False
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
