""" "Same ``.ui`` in 3 toolkits" (spec backends §7, the 16c UAT proof).

``portable_describe`` is run for ttkbootstrap, tkinter and pyside6, each backend in its **own**
process (Tk and Qt never share one): one process per (backend, language) describes every fixture
through the hidden ``--portable`` flag of the preview child, so the suite starts six processes.

* ttkbootstrap and tkinter must be **equal**, with no exception at all.
* Tk and Qt must be equal after one normalisation and an explicit allow-list:

  - **Normalised, not allow-listed: the Windows minimum track width.** A mapped Tk window on
    Windows reports the system minimum width (120 px at 100 % scaling, more at higher DPI) as its
    ``minsize`` when the ``.ui`` sets none; Qt reports 0. The Tk process measures that value on a
    bare root, and the comparison maps it to 0 only on win32 and only for windows whose ``.ui``
    declares no ``min_width``. A declared ``min_width`` is therefore still compared exactly.
  - ``_ALLOWED``: each entry names the fixture, the exact JSON path, the Tk value, the Qt value
    and the spec reason. An entry that no longer matches a difference fails the test (stale).
  - ``_NOT_OBSERVABLE``: documented differences the portable view cannot see, kept here so the
    reader knows why they have no entry.

``events.ui`` of the spec does not exist; the codegen fixture with events is ``rich.ui`` (as in
``tests/preview/test_parity_describe.py``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import _display, make_data_copy
from tests.preview.conftest import ENV
from tests.runtime.conftest import EXAMPLES

pytestmark = pytest.mark.qt

BACKENDS = ("ttkbootstrap", "tkinter", "pyside6")
LANGS = (None, "de_DE")
#: Fixture key -> path relative to the data copy (``examples/hello.ui`` is kept apart).
FIXTURES = {
    "examples/hello": "",
    "data/hello": "hello.ui",
    "data/includes": "includes.ui",
    "data/dialogs": "dialogs.ui",
    "data/images": "images.ui",
    "data/rich": "rich.ui",
}

# (fixture, JSON path, Tk value, Qt value) -> spec reason.
_T5 = "T5 (§14, 16b budget): a Label with image + text shows the image only in Qt"
_DUP = (
    "R73 validate.duplicate_shortcut (runtime spec; backends §14, 16c menus): "
    "Qt sets the shortcut on the first action only; "
    "Tk still shows the accelerator text on both entries"
)
_ALLOWED: dict[tuple[str, str, Any, Any], str] = {
    **{
        ("data/images", f"/widgets/lbl_{k}/text", "x", ""): _T5
        for k in ("gif", "pgm", "png", "ppm")
    },
    ("data/rich", "/widgets/lbl/text", "Pic", ""): _T5,
    ("data/rich", "/widgets/mnu/items[2]/items[0]/shortcut", "Ctrl+O", ""): _DUP,
    ("data/rich", "/widgets/mnu_sub/items[0]/shortcut", "Ctrl+O", ""): _DUP,
    ("data/rich", "/windows/main/menubar[0]/items[2]/items[0]/shortcut", "Ctrl+O", ""): _DUP,
}
#: Documented differences the portable view does not read, so they never show as a difference.
_NOT_OBSERVABLE = {
    "D13": "unbound radios: Tk shares one hidden variable, Qt uses per-parent auto-exclusivity; "
    "the view reports only the value of a *declared* variable, never a checked state",
    "D11": "Scale/Progressbar resolution (10,000 integer steps in Qt): the view reports the bound "
    "variable's value, not the widget's native range",
}

_SCRIPT = """
import contextlib, io, json, sys
import pyguibud.preview as p
backend, lang, *files = sys.argv[1:]
views = []
for name in files:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = p.run(["--describe", "--portable", "--backend", backend,
                      *(["--lang", lang] if lang else []), "--", name])
    assert code == 0, (name, code, out.getvalue())
    views.append(json.loads(out.getvalue().strip().splitlines()[-1]))
clamp = None
if backend != "pyside6":  # the minimum width Windows gives a mapped Tk window with no minsize
    import tkinter
    root = tkinter.Tk()
    root.update()
    clamp = root.minsize()[0]
    root.destroy()
print(json.dumps({"views": views, "clamp": clamp}))
"""


@pytest.fixture(scope="module")
def paths(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    data = make_data_copy(tmp_path_factory.mktemp("parity") / "data")
    return {key: (data / rel if rel else EXAMPLES / "hello.ui") for key, rel in FIXTURES.items()}


@pytest.fixture(scope="module")
def views(paths: dict[str, Path], tmp_path_factory: pytest.TempPathFactory) -> Any:
    """``(backend, lang) -> {"views": {fixture: view}, "clamp": int | None}``, computed lazily."""
    cache: dict[tuple[str, str | None], dict[str, Any]] = {}

    def get(backend: str, lang: str | None) -> dict[str, Any]:
        if (backend, lang) not in cache:
            if backend != "pyside6" and (reason := _display()) is not None:
                pytest.skip(f"needs a Tk display: {reason}")
            env = {**ENV, "QT_QPA_PLATFORM": "offscreen"} if backend == "pyside6" else ENV
            result = subprocess.run(
                [sys.executable, "-c", _SCRIPT, backend, lang or "", *map(str, paths.values())],
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=180,
                cwd=tmp_path_factory.mktemp(backend),
                env=env,
                check=False,
            )
            assert result.returncode == 0, result.stderr[-2000:]
            data = json.loads(result.stdout.strip().splitlines()[-1])
            cache[backend, lang] = {
                "views": dict(zip(paths, data["views"], strict=True)),
                "clamp": data["clamp"],
            }
        return cache[backend, lang]

    return get


def _diff(tk: Any, qt: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    """Every leaf where the two views differ, as (JSON path, Tk value, Qt value)."""
    if isinstance(tk, dict) and isinstance(qt, dict):
        return [
            d
            for key in sorted(tk.keys() | qt.keys())
            for d in _diff(tk.get(key, "<missing>"), qt.get(key, "<missing>"), f"{path}/{key}")
        ]
    if isinstance(tk, list) and isinstance(qt, list) and len(tk) == len(qt):
        return [
            d
            for i, (a, b) in enumerate(zip(tk, qt, strict=True))
            for d in _diff(a, b, f"{path}[{i}]")
        ]
    return [] if tk == qt else [(path, tk, qt)]


def _normalise_min_width(view: dict[str, Any], ui: Path, clamp: int | None) -> dict[str, Any]:
    """Map the Windows minimum track width to "none" for windows that declare no ``min_width``."""
    if sys.platform != "win32" or clamp is None:
        return view
    declared = {w.id for w in read_ui(ui).document.children if w.min_width is not None}
    view = json.loads(json.dumps(view))  # a copy
    for key, window in view["windows"].items():
        if key not in declared and window["minsize"][0] == clamp:
            window["minsize"][0] = 0
    return view


@pytest.mark.parametrize("lang", LANGS, ids=["source", "de_DE"])
def test_ttkbootstrap_and_tkinter_are_identical(views: Any, lang: str | None) -> None:
    tb, tk = views("ttkbootstrap", lang), views("tkinter", lang)
    for key in FIXTURES:
        assert _diff(tb["views"][key], tk["views"][key]) == [], key
    assert tb["clamp"] == tk["clamp"]


@pytest.mark.parametrize("lang", LANGS, ids=["source", "de_DE"])
def test_tk_and_qt_are_equal_up_to_the_allow_list(
    views: Any,
    paths: dict[str, Path],
    lang: str | None,
) -> None:
    tk, qt = views("tkinter", lang), views("pyside6", lang)
    used: set[tuple[str, str, Any, Any]] = set()
    unexpected: list[tuple[str, str, Any, Any]] = []
    for key, ui in paths.items():
        tk_view = _normalise_min_width(tk["views"][key], ui, tk["clamp"])
        for path, a, b in _diff(tk_view, qt["views"][key]):
            entry = (key, path, a, b)
            if entry in _ALLOWED:
                used.add(entry)
            else:
                unexpected.append(entry)
    assert unexpected == []
    assert used == set(_ALLOWED), f"stale allow-list entries: {set(_ALLOWED) - used}"


@pytest.mark.parametrize("lang", LANGS, ids=["source", "de_DE"])
def test_allow_listed_widgets_are_otherwise_equal(views: Any, lang: str | None) -> None:
    """T5 only drops the text (the image is shown on both); only the duplicate loses its key."""
    tk, qt = views("tkinter", lang), views("pyside6", lang)
    for key, ids in (
        ("data/images", ("lbl_gif", "lbl_pgm", "lbl_png", "lbl_ppm")),
        ("data/rich", ("lbl",)),
    ):
        for wid in ids:
            assert tk["views"][key]["widgets"][wid]["image"] is True
            assert qt["views"][key]["widgets"][wid]["image"] is True
    menus = [v["views"]["data/rich"]["windows"]["main"]["menubar"] for v in (tk, qt)]
    shortcuts = [
        [item.get("shortcut") for top in menu for item in top.get("items", [])] for menu in menus
    ]
    assert "Ctrl+O" in shortcuts[0] and shortcuts[0] == shortcuts[1]  # the first one is equal


def test_the_min_width_normalisation_keeps_declared_widths(
    views: Any,
    paths: dict[str, Path],
) -> None:
    tk, qt = views("tkinter", None), views("pyside6", None)
    assert tk["views"]["data/rich"]["windows"]["main"]["minsize"][0] == 200
    assert qt["views"]["data/rich"]["windows"]["main"]["minsize"][0] == 200
    assert tk["views"]["examples/hello"]["windows"]["main"]["minsize"] == [480, 320]
    if sys.platform == "win32":  # the clamp exists and is normalised for undeclared widths only
        assert tk["clamp"] and tk["clamp"] > 0
        raw = tk["views"]["data/includes"]["windows"]["main"]["minsize"][0]
        normalised = _normalise_min_width(
            tk["views"]["data/includes"], paths["data/includes"], tk["clamp"]
        )
        assert raw == tk["clamp"] and normalised["windows"]["main"]["minsize"][0] == 0


def test_translation_reaches_every_toolkit(views: Any) -> None:
    texts = {
        b: views(b, "de_DE")["views"]["examples/hello"]["widgets"]["btn_greet"]["text"]
        for b in BACKENDS
    }
    assert set(texts.values()) == {"Hallo sagen"}
    assert (
        views("pyside6", None)["views"]["examples/hello"]["widgets"]["btn_greet"]["text"]
        == "Say hello"
    )


def test_not_observable_differences_are_documented() -> None:
    assert set(_NOT_OBSERVABLE) == {"D11", "D13"} and all(_NOT_OBSERVABLE.values())
