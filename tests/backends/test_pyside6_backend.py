"""PySide6 backend checks that need no Qt display (spec backends D8, B1, B2)."""

from __future__ import annotations

import sys

import pytest

from pyguibud.backends import BUILTIN_BACKENDS, load_backend
from pyguibud.backends.pyside6 import PySide6Backend, display_problem
from pyguibud.core.registry import default_registry
from pyguibud_runtime import UiError, load_ui
from tests.runtime.conftest import EXAMPLES


@pytest.mark.parametrize("platform", ["linux", "freebsd14", "openbsd7", "netbsd"])
def test_no_display_is_detected_on_x11_platforms(platform: str) -> None:
    assert display_problem(platform, {}) is not None
    assert display_problem(platform, {"DISPLAY": ""}) is not None
    for variable in ("DISPLAY", "WAYLAND_DISPLAY", "QT_QPA_PLATFORM"):
        assert display_problem(platform, {variable: "x"}) is None


@pytest.mark.parametrize("platform", ["win32", "darwin", "cygwin"])
def test_other_platforms_always_have_a_display(platform: str) -> None:
    assert display_problem(platform, {}) is None


_PLUGINS = ("qwindows.dll", "qoffscreen.dll", "libqxcb.so", "libqwayland-generic.so")


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_qa16b_01_a_platform_plugin_that_is_not_installed_is_refused(platform: str) -> None:
    """Qt aborts (and hangs on Windows) for an unknown QT_QPA_PLATFORM: refused before."""
    reason = display_problem(platform, {"QT_QPA_PLATFORM": "bogus"}, _PLUGINS)
    assert reason == "The Qt platform plugin 'bogus' (QT_QPA_PLATFORM) is not installed."
    many = {"QT_QPA_PLATFORM": "bogus;" + "x" * 500}
    assert len(display_problem(platform, many, _PLUGINS) or "") < 200  # the value is clipped


@pytest.mark.parametrize("platform", ["win32", "linux"])
@pytest.mark.parametrize("value", ["   ", ";", ":", " ; ", " XCB ", "offscreen "])
def test_qa19d_09_a_value_naming_no_plugin_is_refused(platform: str, value: str) -> None:
    """Qt 6 skips empty ';'/':' parts but strips nothing, then hangs: refused, even unlisted."""
    assert display_problem(platform, {"QT_QPA_PLATFORM": value}, _PLUGINS) is not None
    if not value.strip(";:"):  # no name at all: refused even with unknown plugin folders
        assert display_problem(platform, {"QT_QPA_PLATFORM": value}, ()) is not None


@pytest.mark.parametrize(
    "value", ["offscreen", "windows:darkmode=2", "wayland", "bogus;xcb", "XCB", ":xcb;;", ""]
)
def test_an_installed_platform_plugin_passes(value: str) -> None:
    assert display_problem("win32", {"QT_QPA_PLATFORM": value}, _PLUGINS) is None


def test_unknown_plugin_folders_never_refuse() -> None:
    assert display_problem("win32", {"QT_QPA_PLATFORM": "bogus"}, ()) is None


def test_the_backend_is_registered() -> None:
    assert BUILTIN_BACKENDS["pyside6"] == "pyguibud.backends.pyside6:PySide6Backend"
    assert load_backend("pyside6", default_registry()) is PySide6Backend


def test_missing_pyside6_gives_the_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "shiboken6", None)  # import -> ImportError
    with pytest.raises(UiError) as caught:
        load_ui(EXAMPLES / "hello.ui", None, strict=False, backend="pyside6")
    assert caught.value.code == "runtime.backend_unavailable"
    assert 'pip install "pyguibud[pyside]"' in str(caught.value)
