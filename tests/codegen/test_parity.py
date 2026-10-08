"""Parity: a generated module builds the same interface as ``load_ui`` on the same ``.ui`` file.

Both are built into one hidden ttkbootstrap root. Each interface is described (widget classes,
the options that matter, geometry, tabs, menu entries, accelerators, variables, window state, key
bindings), and the two descriptions must be equal: after the build, after ``retranslate`` to
``de_DE``, with a fake translator and with a 150,000-character text. Liveness and error codes
are compared too. Spec ``codegen.md`` 10 (``test_parity.py``) and 13 (parity drift).
"""

from __future__ import annotations

import importlib.util
import itertools
import logging
import re
import shutil
import tkinter
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from pyguibud.codegen import generate_python
from pyguibud.core.xml_io import read_ui
from pyguibud_runtime import UiError as RuntimeUiError
from pyguibud_runtime import load_ui
from tests.codegen.conftest import EXAMPLES
from tests.prop_sweep import sweep_ui

pytestmark = pytest.mark.gui

OPTIONS = (
    *("text", "underline", "compound", "state", "padding", "style", "orient", "from", "to"),
    *("wrap", "show", "value", "width", "height", "length", "maximum", "mode", "increment"),
    *("selectmode", "background", "values", "weight", "justify", "anchor", "takefocus"),
)
ENTRY_OPTIONS = ("label", "underline", "accelerator", "state", "compound")
HANDLERS = ("on_cmd", "on_focus", "on_key", "on_change", "on_act", "on_select")
_counter = itertools.count()


@pytest.fixture(scope="module")
def tk_root() -> Iterator[Any]:
    """The one ttkbootstrap root of this module (ttkbootstrap allows a single root)."""
    import ttkbootstrap

    root = ttkbootstrap.App(title="parity")
    root.withdraw()
    yield root
    root.destroy()


class Recorder(dict[str, Callable[[], None]]):
    """A handlers mapping that records the calls of each name."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__()
        self.calls: list[str] = []
        for name in names:
            self[name] = lambda name=name: self.calls.append(name)  # type: ignore[misc]


def _source(name: str, tmp_path: Path, data_copy: Path) -> Path:
    if name != "hello":  # hello is the example itself, with its catalogue
        return data_copy / f"{name}.ui"
    target = tmp_path / "examples"
    shutil.copytree(EXAMPLES, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target / "hello.ui"


def _generate(ui: Path) -> ModuleType:
    module_path = ui.with_name(ui.stem + "_gen_ui.py")
    generated = generate_python(read_ui(str(ui)), str(ui), output=str(module_path))
    module_path.write_text(generated.text, encoding="utf-8", newline="\n")
    spec = importlib.util.spec_from_file_location(f"_parity_{next(_counter)}", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dynamic: Any = module  # the generated module gets one attribute from the harness
    dynamic.class_name = generated.class_name
    return module


def _text(value: Any) -> str:
    text = " ".join(str(part) for part in value) if isinstance(value, tuple) else str(value)
    return re.sub(r"PY_VAR\d+", "<variable>", text)  # variable names are numbered per process


def _image_size(widget: Any, option: str = "image", index: Any = None) -> Any:
    try:
        value = widget.cget(option) if index is None else widget.tab(index, option)
    except tkinter.TclError:
        return None
    name = value[0] if isinstance(value, tuple) and value else value
    if not name:
        return None
    return (
        int(widget.tk.call("image", "width", name)),
        int(widget.tk.call("image", "height", name)),
    )


def _geometry(widget: Any) -> dict[str, str]:
    manager = widget.winfo_manager()
    if manager not in {"grid", "pack"}:
        return {"manager": manager}
    try:
        info = {"grid": widget.grid_info, "pack": widget.pack_info}[manager]()
    except (KeyError, tkinter.TclError):
        return {"manager": manager}
    info.pop("in", None)
    return {"manager": manager, **{key: _text(value) for key, value in sorted(info.items())}}


def _menu(menu: Any) -> list[dict[str, str]]:
    last = menu.index("end")
    entries: list[dict[str, str]] = []
    for index in range(0 if last is None else last + 1):
        entry = {"type": str(menu.type(index))}
        if entry["type"] != "separator":
            for option in ENTRY_OPTIONS:
                try:
                    entry[option] = _text(menu.entrycget(index, option))
                except tkinter.TclError:
                    entry[option] = "<none>"
            entry["image"] = str(bool(menu.entrycget(index, "image")))
        entries.append(entry)
    return entries


def _widget(widget: Any) -> dict[str, Any]:
    info: dict[str, Any] = {"class": widget.winfo_class(), "geometry": _geometry(widget)}
    if isinstance(widget, tkinter.Menu):
        info["entries"] = _menu(widget)
        return info
    for option in OPTIONS:
        try:
            info[option] = _text(widget.cget(option))
        except tkinter.TclError:
            continue
    info["image"] = _image_size(widget)
    if info["class"] == "TNotebook":
        info["tabs"] = [
            {
                **{k: _text(widget.tab(t, k)) for k in ("text", "underline", "compound", "sticky")},
                "image": _image_size(widget, "image", t),
            }
            for t in widget.tabs()
        ]
    if info["class"] in {"TPanedwindow", "Panedwindow"}:
        info["panes"] = [_text(widget.pane(p, "weight")) for p in widget.panes()]
    info["bindings"] = sorted(widget.bind())
    return info


def _descendants(widget: Any) -> int:
    return sum(1 + _descendants(child) for child in widget.winfo_children())


def _scope(ui: Any, prefix: str = "") -> dict[str, Any]:
    described: dict[str, Any] = {}
    for key, obj in ui.widgets.items():
        if isinstance(obj, tkinter.Misc):
            described[prefix + key] = _widget(obj)
        elif isinstance(obj, int):
            described[prefix + key] = "<menu entry>"
        else:  # an include's scope
            described[prefix + key] = f"<scope {sorted(obj.widgets)}>"
            described.update(_scope(obj, f"{prefix}{key}/"))
    return described


def describe(ui: Any, variables: list[tuple[str, str]]) -> dict[str, Any]:
    windows: dict[str, Any] = {}
    for key, top in ui.windows.items():
        bar = top.cget("menu")
        windows[key] = {
            "title": top.title(),
            "minsize": top.minsize(),
            "resizable": top.resizable(),
            "bindings": sorted(top.bind()),
            "menubar": _menu(top.nametowidget(bar)) if bar else None,
            "descendants": _descendants(top),
        }
    return {
        "windows": windows,
        "widgets": _scope(ui),
        "vars": {
            name: (type(getattr(ui.vars, name)).__name__, getattr(ui.vars, name).get())
            for name, _kind in variables
        },
        "var_names": sorted(vars(ui.vars)),
    }


def _variables(ui: Path) -> list[tuple[str, str]]:
    return [(v.id, v.type) for v in read_ui(str(ui)).document.variables.values()]


class Pair:
    """The same ``.ui`` built by ``load_ui`` and by its generated module, side by side."""

    def __init__(self, ui: Path, root: Any, lang: str | None) -> None:
        self.root, self.ui = root, ui
        self.module = _generate(ui)
        self.variables = _variables(ui)
        self.before = set(root.winfo_children())
        names = tuple(self.module.__dict__[self.module.class_name]._handler_names)
        self.loaded_calls, self.generated_calls = Recorder(names), Recorder(names)
        self.loaded = load_ui(ui, self.loaded_calls, master=root, lang=lang)
        self.generated = self.module.__dict__[self.module.class_name]()
        self.generated.setup_ui(root, self.generated_calls, lang=lang)

    def both(self) -> tuple[dict[str, Any], dict[str, Any]]:
        return describe(self.loaded, self.variables), describe(self.generated, self.variables)

    def close(self) -> None:
        self.loaded.destroy()
        self.generated.destroy()
        self.root.update()
        assert set(self.root.winfo_children()) == self.before


@pytest.fixture
def make_pair(
    tk_root: Any, tmp_path: Path, data_copy: Path, caplog: pytest.LogCaptureFixture
) -> Iterator[Callable[..., Pair]]:
    pairs: list[Pair] = []

    def make(name: str, lang: str | None = None) -> Pair:
        with caplog.at_level(logging.WARNING):
            pair = Pair(_source(name, tmp_path, data_copy), tk_root, lang)
        pairs.append(pair)
        return pair

    yield make
    for pair in pairs:
        pair.close()


NAMES = ("hello", "rich", "includes", "images", "dialogs")


@pytest.mark.parametrize("name", NAMES)
def test_the_built_interfaces_are_equal(make_pair: Callable[..., Pair], name: str) -> None:
    pair = make_pair(name)
    loaded, generated = pair.both()
    assert diff(loaded, generated) == []
    assert len(generated["widgets"]) >= 2


def test_hello_after_retranslate_to_german(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("hello")
    for ui in (pair.loaded, pair.generated):
        ui.retranslate("de_DE")
    loaded, generated = pair.both()
    assert diff(loaded, generated) == []
    assert generated["widgets"]["btn_greet"]["text"] == "Hallo sagen"
    assert generated["widgets"]["mnu_file"]["entries"][0]["label"] == "Beenden"
    assert generated["widgets"]["nbk_main"]["tabs"][0]["text"] == "Begrüßung"
    for ui in (pair.loaded, pair.generated):
        ui.retranslate("en_GB")
    loaded, generated = pair.both()
    assert (
        diff(loaded, generated) == [] and generated["widgets"]["btn_greet"]["text"] == "Say hello"
    )


def test_hello_built_in_german(make_pair: Callable[..., Pair]) -> None:
    loaded, generated = make_pair("hello", "de_DE").both()
    assert (
        diff(loaded, generated) == [] and generated["windows"]["main"]["title"] == "Hallo PyGUIbud"
    )


class Shout:
    """A translator that decorates every text."""

    def gettext(self, message: str) -> str:
        return f"<{message}>"

    def pgettext(self, context: str, message: str) -> str:
        return f"<{context}|{message}>"


class Long:
    """A translator whose texts exceed the 100,000-character limit."""

    def gettext(self, message: str) -> str:
        return "Ab" * 75_000

    def pgettext(self, context: str, message: str) -> str:
        return "Ab" * 75_000


class Broken:
    """A translator that fails half way through."""

    def __init__(self) -> None:
        self.count = 0

    def gettext(self, message: str) -> str:
        self.count += 1
        if self.count > 3:
            raise RuntimeError("boom")
        return message.upper()

    pgettext: Any = None  # deliberately not callable


@pytest.mark.parametrize("name", ("hello", "rich"))
def test_a_custom_translator_gives_equal_texts(make_pair: Callable[..., Pair], name: str) -> None:
    pair = make_pair(name)
    for ui in (pair.loaded, pair.generated):
        ui.retranslate(translator=Shout())
    loaded, generated = pair.both()
    assert diff(loaded, generated) == []
    texts = [w.get("text", "") for w in generated["widgets"].values() if isinstance(w, dict)]
    assert any(t.startswith("<") for t in texts)


def test_a_huge_translated_text_is_clipped_alike(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("hello")
    for ui in (pair.loaded, pair.generated):
        ui.retranslate(translator=Long())
    loaded, generated = pair.both()
    assert diff(loaded, generated) == []
    assert len(generated["widgets"]["lbl_name"]["text"]) < 150_000


def test_a_failing_translator_changes_nothing_in_either(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("hello")
    before = pair.both()
    errors = []
    for ui in (pair.loaded, pair.generated):
        with pytest.raises((TypeError, RuntimeError)) as caught:
            ui.retranslate(translator=Broken())
        errors.append(type(caught.value))
    assert errors[0] is errors[1]
    assert diff(before[0], pair.both()[0]) == [] and diff(before[1], pair.both()[1]) == []


def test_handlers_are_called_the_same_way(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("rich")
    for ui in (pair.loaded, pair.generated):
        ui.btn.configure(state="normal")  # the fixture disables it
        ui.btn.invoke()
        ui.chk.invoke()
        ui.rad_s.invoke()
        ui.vars.name.set("changed")
    pair.root.update()
    assert pair.generated_calls.calls == pair.loaded_calls.calls
    assert "on_cmd" in pair.loaded_calls.calls and "on_change" in pair.loaded_calls.calls
    loaded, generated = pair.both()
    assert diff(loaded, generated) == []


def test_hello_widgets_follow_the_variable(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("hello")
    for ui in (pair.loaded, pair.generated):
        ui.vars.user_name.set("Ada")
        assert ui.ent_name.get() == "Ada"


def test_error_codes_before_and_after_destroy_are_equal(make_pair: Callable[..., Pair]) -> None:
    pair = make_pair("hello")
    codes: dict[str, list[str]] = {"unknown": [], "destroyed": [], "retranslate": []}
    generated_error = pair.module.UiError
    for ui in (pair.loaded, pair.generated):
        with pytest.raises((RuntimeUiError, generated_error)) as unknown:
            ui.show("nope")
        codes["unknown"].append(unknown.value.code)
    for ui in (pair.loaded, pair.generated):
        ui.destroy()
        ui.destroy()  # idempotent
        with pytest.raises((RuntimeUiError, generated_error)) as shown:
            ui.show("main")
        with pytest.raises((RuntimeUiError, generated_error)) as translated:
            ui.retranslate("de_DE")
        codes["destroyed"].append(shown.value.code)
        codes["retranslate"].append(translated.value.code)
    assert codes == {
        "unknown": ["runtime.unknown_window"] * 2,
        "destroyed": ["runtime.destroyed"] * 2,
        "retranslate": ["runtime.destroyed"] * 2,
    }


def diff(a: Any, b: Any, path: str = "") -> list[str]:
    """The paths where two descriptions differ (the readable form of a failed ``==``)."""
    if isinstance(a, dict) and isinstance(b, dict):
        found = [f"{path}/{k}: only in one" for k in a.keys() ^ b.keys()]
        for key in a.keys() & b.keys():
            found += diff(a[key], b[key], f"{path}/{key}")
        return found
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [
            d for i, (x, y) in enumerate(zip(a, b, strict=True)) for d in diff(x, y, f"{path}[{i}]")
        ]
    return [] if a == b else [f"{path}: {a!r} != {b!r}"]


# ---------------------------------------------------------------- embed mode (spec dnd-selection 4)
#: The window-level keys an embedded window may not reproduce (a frame has no WM state and no
#: window-level shortcut bindings). Pinned: a new deviation needs an ADR-010 addendum.
EMBED_DEVIATIONS = ("minsize", "resizable", "bindings")


class Embedded:
    """``.ui`` built from the ``load_ui`` plan in embed mode, inside a frame of the shared root."""

    def __init__(self, ui: Path, root: Any, lang: str | None = None) -> None:
        from tkinter import ttk

        from pyguibud.backends._tk import Embed
        from pyguibud.backends.ttkbootstrap import TtkbootstrapBackend
        from pyguibud.core.model import Window
        from pyguibud_runtime._load import _handler_names, _prepare

        self.host = ttk.Frame(root)
        self.frames: dict[str, Any] = {}
        self.titles: dict[str, str] = {}
        self.nodes: list[tuple[object, Any, Any]] = []

        def on_node(node: object, outer: Any, inner: Any) -> None:
            self.nodes.append((node, outer, inner))
            if isinstance(node, Window):
                self.frames[node.id] = outer

        def placeholder(node: object, parent: Any) -> Any:
            raise AssertionError("a _prepare plan expands every include")

        probe = _prepare(ui, None, strict=False, master=root)[1]
        self.calls = Recorder(tuple(sorted(_handler_names(probe.top))))
        self.ui, plan = _prepare(ui, self.calls, strict=True, master=root, lang=lang)
        embed = Embed(
            host=self.host,
            on_node=on_node,
            on_title=lambda window, text: self.titles.__setitem__(window.id, text),
            placeholder=placeholder,
        )
        self.ui._session = TtkbootstrapBackend().build_embedded(plan, embed)

    def windows(self) -> dict[str, Any]:
        described: dict[str, Any] = {}
        for key, frame in self.frames.items():
            bars = [c for c in frame.winfo_children() if isinstance(c, tkinter.Menu)]
            described[key] = {
                "title": self.titles.get(key, UNTITLED),
                "menubar": _menu(bars[0]) if bars else None,
                "descendants": _descendants(frame),
            }
        return described

    def close(self) -> None:
        self.ui.destroy()
        self.host.destroy()


#: A window without a ``title`` property has no title slot: the toolkit's default title of a
#: Toplevel is not document content, so both sides show this marker instead.
UNTITLED = "<no title property>"


def _runtime_windows(described: dict[str, Any], built: Embedded) -> dict[str, Any]:
    windows = {
        key: {k: v for k, v in window.items() if k not in EMBED_DEVIATIONS}
        for key, window in described["windows"].items()
    }
    for key, window in windows.items():
        if key not in built.titles:
            window["title"] = UNTITLED
    return windows


def _widgets(described: dict[str, Any], ui: Any) -> dict[str, Any]:
    """The widget descriptions without the windows themselves (a Toplevel is not a Frame)."""
    return {k: v for k, v in described["widgets"].items() if k not in ui.windows}


@pytest.fixture
def embedded(
    tk_root: Any, tmp_path: Path, data_copy: Path, caplog: pytest.LogCaptureFixture
) -> Iterator[Callable[..., tuple[Embedded, Any, Path]]]:
    made: list[Any] = []

    def make(name: str, lang: str | None = None) -> tuple[Embedded, Any, Path]:
        ui = _source(name, tmp_path, data_copy)
        with caplog.at_level(logging.WARNING):
            built = Embedded(ui, tk_root, lang)
            loaded = load_ui(ui, built.calls, master=tk_root, lang=lang)
        made.extend((built, loaded))
        return built, loaded, ui

    yield make
    for item in made:
        item.close() if isinstance(item, Embedded) else item.destroy()


def test_embed_deviations_are_pinned() -> None:
    assert EMBED_DEVIATIONS == ("minsize", "resizable", "bindings")


@pytest.mark.parametrize("name", NAMES)
def test_embedded_build_matches_runtime(embedded: Callable[..., Any], name: str) -> None:
    built, loaded, ui = embedded(name)
    variables = _variables(ui)
    runtime, embed = describe(loaded, variables), describe_scope(built.ui, variables)
    assert diff(_widgets(runtime, loaded), _widgets(embed, built.ui)) == []
    assert runtime["vars"] == embed["vars"] and runtime["var_names"] == embed["var_names"]
    assert len(_widgets(embed, built.ui)) >= 2


@pytest.mark.parametrize("name", NAMES)
def test_embedded_windows_match_runtime(embedded: Callable[..., Any], name: str) -> None:
    built, loaded, ui = embedded(name)
    runtime = _runtime_windows(describe(loaded, _variables(ui)), built)
    assert diff(runtime, built.windows()) == []
    assert set(built.frames) == set(loaded.windows)


def test_embedded_retranslate_matches_runtime(embedded: Callable[..., Any]) -> None:
    built, loaded, ui = embedded("hello")
    for scope in (built.ui, loaded):
        scope.retranslate("de_DE")
    variables = _variables(ui)
    runtime, embed = describe(loaded, variables), describe_scope(built.ui, variables)
    assert diff(_widgets(runtime, loaded), _widgets(embed, built.ui)) == []
    assert diff(_runtime_windows(runtime, built), built.windows()) == []
    assert embed["widgets"]["btn_greet"]["text"] == "Hallo sagen"
    assert built.titles["main"] == "Hallo PyGUIbud"


def describe_scope(ui: Any, variables: list[tuple[str, str]]) -> dict[str, Any]:
    """``describe`` without the window-level part (embedded windows are frames)."""
    return {
        "widgets": _scope(ui),
        "vars": {
            name: (type(getattr(ui.vars, name)).__name__, getattr(ui.vars, name).get())
            for name, _kind in variables
        },
        "var_names": sorted(vars(ui.vars)),
    }


def _root_state(root: Any) -> dict[str, Any]:
    return {
        "children": set(root.winfo_children()),
        "toplevels": [w for w in root.winfo_children() if isinstance(w, tkinter.Toplevel)],
        "title": root.title(),
        "menu": str(root.cget("menu")),
        "bind": sorted(root.bind()),
        "bindtags": root.bindtags(),
        "notebook": sorted(root.bind_class("TNotebook")),
        "all": sorted(root.bind_class("all")),
    }


@pytest.mark.parametrize("name", NAMES)
def test_embed_creates_no_toplevel(
    tk_root: Any, tmp_path: Path, data_copy: Path, caplog: pytest.LogCaptureFixture, name: str
) -> None:
    ui = _source(name, tmp_path, data_copy)
    with caplog.at_level(logging.WARNING):
        warm = Embedded(ui, tk_root)  # ttkbootstrap creates some styles lazily on first use
        warm.close()
        before = _root_state(tk_root)
        built = Embedded(ui, tk_root)
    try:
        after = _root_state(tk_root)
        assert after["children"] - before["children"] == {built.host}
        assert after == {**before, "children": after["children"]}
        assert not after["toplevels"]
        assert all(frame.master is built.host for frame in built.frames.values())
    finally:
        built.close()
    assert _root_state(tk_root) == before


def test_embed_rebuild_leaks_nothing(
    tk_root: Any, tmp_path: Path, data_copy: Path, caplog: pytest.LogCaptureFixture
) -> None:
    ui = _source("rich", tmp_path, data_copy)

    def state() -> tuple[Any, ...]:
        tk_root.update_idletasks()
        return (
            set(tk_root.winfo_children()),
            len(tk_root.tk.call("image", "names")),
            sorted(tk_root.bind()),
        )

    with caplog.at_level(logging.WARNING):
        Embedded(ui, tk_root).close()  # warm-up: lazily created styles and images
        before = state()
        for _round in range(100):
            Embedded(ui, tk_root).close()
    assert state() == before


def test_embed_none_is_unchanged(make_pair: Callable[..., Pair]) -> None:
    """The runtime path (``embed=None``) still matches the generated module exactly."""
    loaded, generated = make_pair("rich").both()
    assert diff(loaded, generated) == []


def test_every_class_ignores_the_properties_it_does_not_define(
    tk_root: Any, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Every core class with every defined property plus foreign ``text``/``state``/``value``/
    ``image``/``show``: the validator only warns ("kept but ignored"), so ``load_ui``, the
    generated module and the designer's embedded build must all build it (a Notebook with a
    ``text`` property raised ``unknown option "-text"``) and stay equal.
    """
    from pyguibud.core import default_registry
    from tests.prop_sweep import widget_classes

    registry = default_registry()
    ui = sweep_ui(tmp_path, registry)
    with caplog.at_level(logging.WARNING):
        pair = Pair(ui, tk_root, None)
        built = Embedded(ui, tk_root)
    try:
        loaded, generated = pair.both()
        assert diff(loaded, generated) == []
        variables = _variables(ui)
        embed = describe_scope(built.ui, variables)
        assert diff(_widgets(loaded, pair.loaded), _widgets(embed, built.ui)) == []
        widgets = loaded["widgets"]
        assert {f"w_{name.lower()}" for name in widget_classes(registry)} <= set(widgets)
        # The defined properties still apply: the foreign ones changed nothing else.
        button = widgets["w_button"]
        assert button["text"] == "Sample" and button["state"] == "disabled"
        assert widgets["w_label"]["text"] == "Sample"
        assert widgets["w_label"]["state"] == "normal"  # a ttk Label would take the foreign one
    finally:
        built.close()
        pair.close()
