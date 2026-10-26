"""Regressions (CI 20b.1): Tk 9 answers "" for ``index end`` of an empty menu and for an unset
``underline``.

uv's Python 3.10 for Linux and macOS ships Tk 9.0, and Python 3.10's ``Menu.index`` (and so
``Menu.delete``) only knows Tk 8.6's "none" (CPython GH-103685): ``int("")`` raised
``TclError: expected integer but got ""`` while the designer built its empty tree menu, so the
designer did not start there. The fakes answer as Tk 9 does and fail as Python 3.10 does.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud.designer.theme_tk import clear_menu, menu_end, underline_of
from pyguibud.preview._describe import _menu_end, _mnemonic


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


# ------------------------------------------------------------------ an unset ``underline``
#: Regression (CI 20b.1, qt job under xvfb): Tk 9 answers "" for an unset ``underline`` where
#: Tk 8.6 answered -1, so ``int(...)`` crashed the preview child (``_describe._mnemonic``) and
#: would crash the tree menu's access keys and the canvas menubar strip.
@pytest.mark.parametrize(
    ("value", "index"),
    [("", -1), (" ", -1), (None, -1), ("-1", -1), (-1, -1), ("0", 0), (3, 3), ("12", 12)],
)
def test_an_unset_underline_reads_as_none(value: object, index: int) -> None:
    assert underline_of(value) == index
    assert _mnemonic(value) == (index if index >= 0 else None)


class _Entries:
    """A filled menu under Tk 9: entries made without ``underline`` answer ""."""

    def __init__(self, entries: list[tuple[str, object]]) -> None:
        self.tk = _Tcl(str(len(entries) - 1))
        self.entries = [{"label": label, "underline": underline} for label, underline in entries]

    def __str__(self) -> str:
        return ".menu"

    def type(self, index: int) -> str:
        return "command"

    def entrycget(self, index: int, option: str) -> object:
        return self.entries[index][option]

    def entryconfigure(self, index: int, **options: object) -> None:
        self.entries[index].update(options)


def test_the_tree_menu_access_keys_survive_entries_without_an_underline() -> None:
    from pyguibud.designer.shell import Shell

    menu: Any = _Entries([("Cut", 0), ("Copy", ""), ("Paste", "")])
    Shell._unique_access_keys(menu)
    assert [e["underline"] for e in menu.entries] == [0, 1, 0]  # C, o, P
