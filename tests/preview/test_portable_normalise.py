"""The normalisers both portable readers share (spec backends 7), and B1 for the Qt host."""

from __future__ import annotations

import sys
from typing import Any

import pytest

from pyguibud.preview._describe import min_size, pack_fill, portable_shortcut


@pytest.mark.parametrize(
    ("tk", "qt", "expected"),
    [
        ("Ctrl+Q", "Ctrl+Q", "Ctrl+Q"),
        ("Ctrl+Shift+S", "Ctrl+Shift+S", "Ctrl+Shift+S"),
        ("Ctrl+Return", "Ctrl+Return", "Ctrl+Enter"),
        ("Ctrl+Enter", "Ctrl+Return", "Ctrl+Enter"),
        ("Alt+Escape", "Alt+Esc", "Alt+Escape"),
        ("Ctrl+Delete", "Ctrl+Del", "Ctrl+Delete"),
        ("Ctrl+PageDown", "Ctrl+PgDown", "Ctrl+PageDown"),
        ("Ctrl+Plus", "Ctrl++", "Ctrl+Plus"),
        ("Ctrl+Minus", "Ctrl+-", "Ctrl+Minus"),
        ("F5", "F5", "F5"),
        ("", "", ""),
    ],
)
def test_tk_accelerators_and_qt_sequences_normalise_alike(tk: str, qt: str, expected: str) -> None:
    assert portable_shortcut(tk) == portable_shortcut(qt) == expected


def test_an_unparsable_shortcut_is_kept_verbatim() -> None:
    assert portable_shortcut("Meta+Q") == "Meta+Q"


def test_an_unset_minimum_size_reads_as_zero() -> None:
    assert min_size(1, 1) == min_size(0, 0) == [0, 0]
    assert min_size(480, 1) == [480, 0]


@pytest.mark.parametrize(
    ("fill", "vertical", "expand", "expected"),
    [
        ((True, True), True, True, "both"),
        ((True, True), True, False, "x"),  # along a vertical pack a fixed parcel: no y fill
        ((True, True), False, False, "y"),
        ((False, True), True, False, "none"),
        ((True, False), False, True, "x"),
        ((False, False), True, True, "none"),
    ],
)
def test_pack_fill_drops_the_along_axis_without_expand(
    fill: tuple[bool, bool], vertical: bool, expand: bool, expected: str
) -> None:
    assert pack_fill(*fill, vertical, expand) == expected


def test_b1_a_missing_pyside6_is_backend_unavailable_with_the_install_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.preview._host import host_for
    from pyguibud_runtime import UiError

    monkeypatch.setitem(sys.modules, "pyguibud.preview._host_qt", None)  # import fails
    with pytest.raises(UiError) as caught:
        host_for("pyside6")
    assert caught.value.code == "runtime.backend_unavailable"
    assert 'pip install "pyguibud[pyside]"' in str(caught.value)


def test_a_progressbar_has_no_portable_text_even_where_tk_9_gives_it_one(tk_root: Any) -> None:
    """Regression (CI 20b.1, Linux Tk 9): ttk::progressbar gained ``-text`` in Tk 9, so the
    tkinter fallback of a Meter reported ``text: ""`` where ttkbootstrap and Qt report none."""
    from tkinter import ttk

    from pyguibud.preview._describe import _portable_widget

    class Tk9Progressbar(ttk.Progressbar):
        def cget(self, key: str) -> object:
            return "" if key in ("text", "underline") else super().cget(key)

    bar = Tk9Progressbar(tk_root)
    try:
        bar.pack()
        info = _portable_widget(bar, {}, {})
        assert info["class"] == "Progressbar"
        assert "text" not in info and "mnemonic" not in info
    finally:
        bar.destroy()
