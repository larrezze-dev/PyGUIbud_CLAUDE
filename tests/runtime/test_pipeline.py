"""The pre-Tk pipeline of ``load_ui`` with a fake backend: no display needed."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

import pyguibud_runtime._load as load_module
from pyguibud.backends import BUILTIN_BACKENDS, load_backend
from pyguibud.backends.base import BuildPlan, NoDisplayError, RootExistsError, TextSlot
from pyguibud.core import Registry
from pyguibud.core.diagnostics import Finding
from pyguibud.core.model import Prop
from pyguibud_runtime import LoadedUi, UiError, load_ui
from tests.runtime.conftest import EXAMPLES, write_ui

HELLO = EXAMPLES / "hello.ui"
MAIN = '<window id="main" kind="main"><layout type="grid"/>{body}</window>'


class FakeSession:
    def __init__(self, plan: BuildPlan) -> None:
        self.plan = plan
        self.texts: list[tuple[Callable[[TextSlot], str], Callable[[str], str]]] = []
        self.shown: list[str] = []
        self.ran = 0
        self.destroyed = 0
        self.is_alive = True

    def alive(self) -> bool:
        return self.is_alive

    def apply_texts(self, text: Callable[[TextSlot], str], runtime: Callable[[str], str]) -> None:
        self.texts.append((text, runtime))

    def show(self, window_id: str) -> str | None:
        self.shown.append(window_id)
        return None

    def run(self) -> None:
        self.ran += 1

    def destroy(self) -> None:
        self.destroyed += 1


class FakeBackend:
    name: ClassVar[str] = "fake"
    calls: ClassVar[list[str]] = []
    fail_prepare: ClassVar[BaseException | None] = None
    fail_build: ClassVar[BaseException | None] = None
    session: ClassVar[FakeSession | None] = None

    def prepare(self, master: object | None) -> None:
        FakeBackend.calls.append("prepare")
        if FakeBackend.fail_prepare is not None:
            raise FakeBackend.fail_prepare

    def build(self, plan: BuildPlan, master: object | None) -> FakeSession:
        FakeBackend.calls.append("build")
        if FakeBackend.fail_build is not None:
            raise FakeBackend.fail_build
        FakeBackend.session = FakeSession(plan)
        return FakeBackend.session


@pytest.fixture(autouse=True)
def fake_backend(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    FakeBackend.calls = []
    FakeBackend.fail_prepare = FakeBackend.fail_build = None
    FakeBackend.session = None
    monkeypatch.setattr(load_module, "load_backend", lambda name, registry: FakeBackend)
    yield


class Hello:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def on_greet(self) -> None:
        self.calls.append("greet")

    def on_quit(self) -> None:
        self.calls.append("quit")


def _plan() -> BuildPlan:
    assert FakeBackend.session is not None
    return FakeBackend.session.plan


def _slot(plan: BuildPlan, prop: Prop) -> str:
    return plan.text(TextSlot(plan.top.doc.key, prop))


# ---------------------------------------------------------------- P1 arguments
@pytest.mark.parametrize(
    ("kwargs", "error"),
    [
        ({"path": 3}, TypeError),
        ({"path": b"x.ui"}, TypeError),
        ({"strict": 1}, TypeError),
        ({"backend": None}, TypeError),
        ({"localedir": 5}, TypeError),
        ({"lang": "../../x"}, ValueError),
        ({"lang": "de/DE"}, ValueError),
        ({"lang": 7}, ValueError),
    ],
)
def test_api_misuse_raises_plain_errors(kwargs: dict[str, Any], error: type[Exception]) -> None:
    arguments: dict[str, Any] = {"path": HELLO, **kwargs}
    with pytest.raises(error):
        load_ui(**arguments)
    assert FakeBackend.calls == []


def test_bytes_pathlike_is_rejected() -> None:
    class BytesPath(os.PathLike[bytes]):
        def __fspath__(self) -> bytes:
            return b"x.ui"

    with pytest.raises(TypeError):
        load_ui(BytesPath())  # type: ignore[arg-type]


# ---------------------------------------------------------------- P2-P4 file checks
def test_unreadable_file(tmp_path: Path) -> None:
    with pytest.raises(UiError) as info:
        load_ui(tmp_path / "missing.ui")
    assert info.value.code == "runtime.unreadable"
    assert info.value.path.endswith("missing.ui")
    assert FakeBackend.calls == []


def test_invalid_document_lists_findings(tmp_path: Path) -> None:
    body = '<widget class="Button" id="run"><cell row="0" column="0"/></widget>'
    path = write_ui(tmp_path / "bad.ui", MAIN.format(body=body))
    with pytest.raises(UiError) as info:
        load_ui(path, Hello())
    error = info.value
    assert error.code == "runtime.invalid_document"
    assert [f.code for f in error.findings] == ["validate.reserved_id"]
    assert "1 error prevents loading" in str(error)
    assert "reserved" in str(error).splitlines()[1]
    assert FakeBackend.calls == []


@pytest.mark.parametrize(
    ("windows", "meta", "code"),
    [
        (
            MAIN.format(body="") + '<window id="part" kind="component"><layout type="pack"/>'
            '<include id="me" src="#" component="part"><pack/></include></window>',
            "",
            "validate.include_cycle",
        ),
        ("", 'i18n_domain="../x"', "validate.bad_i18n_domain"),
        (
            '<window id="w"><menubar><menu id="m"><action id="a" shortcut="Q"/></menu></menubar>'
            '<layout type="grid"/></window>',
            "",
            "validate.bad_shortcut",
        ),
        (
            MAIN.format(
                body='<widget class="Button" id="b"><event name="key:&lt;Button-1&gt;" '
                'handler="on_x"/><cell row="0" column="0"/></widget>'
            ),
            "",
            "validate.bad_key_sequence",
        ),
    ],
)
def test_abuse_is_refused_before_the_backend(
    tmp_path: Path, windows: str, meta: str, code: str
) -> None:
    path = write_ui(tmp_path / "abuse.ui", windows, meta=meta)
    with pytest.raises(UiError) as info:
        load_ui(path, {"on_x": lambda: None})
    assert info.value.code == "runtime.invalid_document"
    assert code in {f.code for f in info.value.findings}
    assert FakeBackend.calls == []


def test_error_message_is_capped_at_twenty_findings() -> None:
    findings = tuple(
        Finding(code="validate.x", msgid=f"problem {n}", source="a.ui", severity="error")
        for n in range(1003)
    )
    lines = str(UiError("runtime.invalid_document", "head", findings=findings)).splitlines()
    assert len(lines) == 22
    assert lines[-1] == "… and 983 more problems."


def test_validator_warnings_are_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    body = '<prop name="colour">red</prop>'
    path = write_ui(tmp_path / "warn.ui", MAIN.format(body=body))
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        load_ui(path)
    assert any("colour" in record.getMessage() for record in caplog.records)
    assert FakeBackend.calls == ["prepare", "build"]


@pytest.mark.parametrize(
    ("windows", "master", "code"),
    [
        ('<window id="d" kind="dialog"><layout type="grid"/></window>', None, "no_main_window"),
        ('<window id="c" kind="component"><layout type="grid"/></window>', None, "nothing_to_load"),
        ('<window id="c" kind="component"><layout type="grid"/></window>', 1, "nothing_to_load"),
        ("", None, "no_main_window"),
    ],
)
def test_window_checks(tmp_path: Path, windows: str, master: object, code: str) -> None:
    path = write_ui(tmp_path / "w.ui", windows)
    with pytest.raises(UiError) as info:
        load_ui(path, master=master)
    assert info.value.code == f"runtime.{code}"
    assert FakeBackend.calls == []


def test_dialogs_alone_load_into_a_master(tmp_path: Path) -> None:
    path = write_ui(
        tmp_path / "d.ui", '<window id="d" kind="dialog"><layout type="grid"/></window>'
    )
    load_ui(path, master=object())
    assert [w.id for w in _plan().top.windows] == ["d"]


# ---------------------------------------------------------------- P6 handlers
def test_missing_handlers_are_aggregated_and_sorted() -> None:
    with pytest.raises(UiError) as info:
        load_ui(HELLO, object())
    error = info.value
    assert error.code == "runtime.missing_handlers"
    assert error.names == ("on_greet", "on_quit")
    assert "2 handlers are missing or not callable on object: on_greet, on_quit." in str(error)
    assert FakeBackend.calls == []


def test_none_handlers_are_all_missing() -> None:
    with pytest.raises(UiError) as info:
        load_ui(HELLO)
    assert info.value.names == ("on_greet", "on_quit")


def test_mapping_handlers_and_bad_values() -> None:
    def greet() -> None:
        pass

    with pytest.raises(UiError) as info:
        load_ui(HELLO, {"on_greet": greet, "on_quit": "not callable"})
    assert info.value.names == ("on_quit",)
    load_ui(HELLO, {"on_greet": greet, "on_quit": greet})
    assert set(_plan().handlers) == {"on_greet", "on_quit"}


def test_a_raising_property_counts_as_missing() -> None:
    class Raising(Hello):
        @property
        def on_quit(self) -> Callable[[], None]:
            raise RuntimeError("boom")

    with pytest.raises(UiError) as info:
        load_ui(HELLO, Raising())
    assert info.value.names == ("on_quit",)


def test_non_strict_logs_and_leaves_unbound(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        load_ui(HELLO, {}, strict=False)
    messages = [record.getMessage() for record in caplog.records]
    assert sum("is missing or not callable" in m for m in messages) == 2
    assert _plan().handlers == {}


# ---------------------------------------------------------------- P8-P9 and build
@pytest.mark.parametrize(
    ("stage", "exc", "code"),
    [
        ("prepare", ImportError("no ttkbootstrap"), "backend_unavailable"),
        ("prepare", TypeError("master must be a live Tk widget"), "backend_unavailable"),
        ("prepare", RootExistsError("root"), "root_exists"),
        ("build", NoDisplayError("no $DISPLAY"), "no_display"),
        ("build", RuntimeError("bad"), "build_failed"),
    ],
)
def test_backend_failures_are_wrapped(stage: str, exc: BaseException, code: str) -> None:
    setattr(FakeBackend, f"fail_{stage}", exc)
    with pytest.raises(UiError) as info:
        load_ui(HELLO, Hello())
    assert info.value.code == f"runtime.{code}"
    assert info.value.__cause__ is exc
    assert FakeBackend.calls == (["prepare"] if stage == "prepare" else ["prepare", "build"])


def test_unknown_backend_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(load_module, "load_backend", load_backend)
    with pytest.raises(UiError) as info:
        load_ui(HELLO, Hello(), backend="nope")
    assert info.value.code == "runtime.backend_unavailable"
    assert "nope" in str(info.value)


def test_load_backend_safety_net_and_errors() -> None:
    empty = Registry(entry_points=lambda group: ())
    backend = load_backend("ttkbootstrap", empty)
    assert backend.__name__ == "TtkbootstrapBackend"
    assert BUILTIN_BACKENDS["ttkbootstrap"].endswith(":TtkbootstrapBackend")


def test_load_backend_rejects_a_non_class(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = Registry(entry_points=lambda group: ())
    monkeypatch.setattr(registry, "load_backend", lambda name: object())
    with pytest.raises(TypeError):
        load_backend("odd", registry)


# ---------------------------------------------------------------- LoadedUi and texts
def test_loaded_ui_delegates_and_destroys_once() -> None:
    ui = load_ui(HELLO, Hello(), lang="de_DE")
    session = FakeBackend.session
    assert isinstance(ui, LoadedUi) and session is not None
    plan = session.plan
    assert plan.theme == "flatly"
    title = plan.top.windows[0].props["title"]
    assert _slot(plan, title) == "Hallo PyGUIbud"
    ui._attach("main", "top", window=True)
    assert ui.show("main") is None and session.shown == ["main"]
    ui.run()
    ui.retranslate()
    ui.retranslate("en_GB")
    assert session.texts[-1][0](TextSlot(plan.top.doc.key, title)) == "Hello PyGUIbud"
    ui.retranslate(translator=Upper())
    assert session.texts[-1][0](TextSlot(plan.top.doc.key, title)) == "HELLO PYGUIBUD"
    ui.retranslate()  # keeps the translator
    assert session.texts[-1][0](TextSlot(plan.top.doc.key, title)) == "HELLO PYGUIBUD"
    with pytest.raises(ValueError):
        ui.retranslate("../x")
    with pytest.raises(UiError) as info:
        ui.show("nbk_main")
    assert info.value.code == "runtime.unknown_window"
    for wrong in ([], None, 1):  # QA-11-12: not a bare TypeError for an unhashable id
        with pytest.raises(UiError) as info:
            ui.show(wrong)  # type: ignore[arg-type]
        assert info.value.code == "runtime.unknown_window"
    ui.destroy()
    ui.destroy()
    assert session.destroyed == 1 and session.ran == 1
    calls: tuple[Callable[[], object], ...] = (ui.retranslate, ui.run, lambda: ui.show("main"))
    for call in calls:
        with pytest.raises(UiError) as info:
            call()
        assert info.value.code == "runtime.destroyed"


class Upper:
    def gettext(self, message: str, /) -> str:
        return message.upper()

    def pgettext(self, context: str, message: str, /) -> str:
        return message.upper()


def test_text_rules() -> None:
    load_ui(HELLO, Hello(), lang="en_XA")
    plan = _plan()
    pseudo = _slot(plan, Prop(name="text", value="Ready", translatable=True))
    assert pseudo.startswith("[") and "Ready" not in pseudo
    assert _slot(plan, Prop(name="text", value="", translatable=True)) == ""
    assert _slot(plan, Prop(name="text", value="Ready")) == "Ready"
    assert plan.runtime_text("_OK").startswith("[")


def test_unknown_language_logs_and_keeps_source(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        load_ui(HELLO, Hello(), lang="xx_XX")
    assert any("'hello' for 'xx_XX'" in r.getMessage() for r in caplog.records)
    plan = _plan()
    assert _slot(plan, plan.top.windows[0].props["title"]) == "Hello PyGUIbud"
    assert plan.runtime_text("_OK") == "_OK"


def test_source_language_without_catalogue_is_silent(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        load_ui(HELLO, Hello(), lang="en_US")
    assert not caplog.records


def test_corrupt_catalogue_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    messages = tmp_path / "locale" / "de_DE" / "LC_MESSAGES"
    messages.mkdir(parents=True)
    (messages / "app.mo").write_bytes(b"\xde\x12\x04\x95 garbage")
    title = '<prop name="title" translatable="true">Hi</prop>'
    path = write_ui(tmp_path / "a.ui", MAIN.format(body=title), meta='i18n_domain="app"')
    with caplog.at_level(logging.WARNING, logger="pyguibud_runtime"):
        load_ui(path, lang="de_DE")
    assert any("'app' for 'de_DE'" in r.getMessage() for r in caplog.records)
    assert _slot(_plan(), _plan().top.windows[0].props["title"]) == "Hi"


def test_localedir_and_no_domain(tmp_path: Path) -> None:
    load_ui(HELLO, Hello(), lang="de_DE", localedir=tmp_path)
    plan = _plan()
    assert _slot(plan, plan.top.windows[0].props["title"]) == "Hello PyGUIbud"
    path = write_ui(tmp_path / "plain.ui", MAIN.format(body=""))
    load_ui(path, lang="de_DE")
    assert _slot(_plan(), Prop(name="t", value="Ready", translatable=True)) == "Ready"


# ---------------------------------------------------------------- P5 includes and images
def test_includes_expand_into_scopes(tmp_path: Path) -> None:
    # A 1x1 GIF: screen descriptor, then one image descriptor and its data.
    (tmp_path / "img.gif").write_bytes(
        b"GIF89a\x01\x00\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
    )
    part = (
        '<window id="part" kind="component"><layout type="pack"/>'
        '<widget class="Button" id="btn"><event name="command" handler="on_part"/>'
        "<pack/></widget></window>"
    )
    write_ui(tmp_path / "part.ui", part, resources='<image id="pic" src="img.gif"/>')
    body = (
        '<include id="one" src="part.ui" component="part"><cell row="0" column="0"/></include>'
        '<include id="two" src="part.ui" component="part"><cell row="1" column="0"/></include>'
        '<include id="same" src="#" component="local"><cell row="2" column="0"/></include>'
    )
    local = '<window id="local" kind="component"><layout type="grid"/></window>'
    path = write_ui(
        tmp_path / "main.ui",
        MAIN.format(body=body) + local,
        variables='<var id="v" type="int"/>',
    )
    load_ui(path, {"on_part": lambda: None})
    top = _plan().top
    children = list(top.includes.values())
    assert len(children) == 3
    assert children[0].doc is children[1].doc and children[0].scope is not children[1].scope
    assert children[0].host is None and children[2].host is top
    assert [w.id for w in children[0].windows] == ["part"]
    images = _plan().images
    assert [key[1] for key in images] == ["pic"]
    assert next(iter(images.values())).name == "img.gif"
