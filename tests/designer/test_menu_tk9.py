"""Regression (CI 20b.1): Tk 9 answers "" for ``index end`` of an empty menu.

uv's Python 3.10 for Linux and macOS ships Tk 9.0, and Python 3.10's ``Menu.index`` (and so
``Menu.delete``) only knows Tk 8.6's "none" (CPython GH-103685): ``int("")`` raised
``TclError: expected integer but got ""`` while the designer built its empty tree menu, so the
designer did not start there. The fakes answer as Tk 9 does and fail as Python 3.10 does.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud.designer.theme_tk import clear_menu, menu_end
from pyguibud.preview._describe import _menu_end


class _Tcl:
    def __init__(self, end: str) -> None:
        self.end = end

    def call(self, *args: object) -> str:
        assert args[1:] == ("index", "end"), args
        return self.end

    def getint(self, value: str) -> int:
        return int(value)  # ValueError on "", as tkinter's getint raises TclError


class _Menu:
    """A menu as Python 3.10 sees it under Tk 9: ``index``/``delete`` fail when it is empty."""

    def __init__(self, end: str) -> None:
        self.tk = _Tcl(end)
        self.deleted: list[tuple[object, object]] = []

    def __str__(self) -> str:
        return ".menu"

    def index(self, index: str) -> int | None:
        value = self.tk.call(str(self), "index", index)
        return None if value == "none" else self.tk.getint(value)  # Python 3.10

    def delete(self, first: object, last: object) -> None:
        self.index("end")
        self.deleted.append((first, last))


def test_the_fake_fails_like_python_310_under_tk_9() -> None:
    with pytest.raises(ValueError):
        _Menu("").index("end")
    with pytest.raises(ValueError):
        _Menu("").delete(0, "end")


@pytest.mark.parametrize("end", ["", "none"])  # Tk 9, Tk 8.6
def test_an_empty_menu_has_no_last_entry(end: str) -> None:
    menu: Any = _Menu(end)
    assert menu_end(menu) is None and _menu_end(menu) is None
    clear_menu(menu)
    assert menu.deleted == []


def test_a_filled_menu_reports_and_clears_its_entries() -> None:
    menu: Any = _Menu("2")
    assert menu_end(menu) == _menu_end(menu) == 2
    clear_menu(menu)
    assert menu.deleted == [(0, "end")]
