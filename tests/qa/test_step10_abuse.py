"""QA regressions of Step 10 (runtime loader): abuse cases that must be blocked gracefully.

Pure tests (no display). GUI regressions live in ``tests/runtime/test_qa_step10_gui.py``, which
shares the single session Tk root.
"""

from __future__ import annotations

import gettext
import os
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from pyguibud import i18n
from pyguibud.core import default_registry, read_ui_string
from pyguibud.core.keys import is_valid_key_sequence, tk_key_sequences, tk_shortcut
from pyguibud.core.validate import validate
from pyguibud_runtime import LoadedUi, UiError, load_ui
from pyguibud_runtime._texts import DocumentTexts, Texts

HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
    '<meta source_locale="en_GB"/>'
)


@pytest.fixture(autouse=True)
def _en_gb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")


# ---------------------------------------------------------------- QA-10-01: digit keys
# In Tk, a bare digit after the modifiers is a mouse button: <Control-1> is Ctrl+click.
@pytest.mark.parametrize("digit", "0123456789")
def test_digit_shortcut_binds_the_key_not_a_mouse_button(digit: str) -> None:
    assert tk_shortcut(f"Ctrl+{digit}").sequences == (f"<Control-Key-{digit}>",)
    assert tk_shortcut(f"Alt+Shift+{digit}", aqua=True).sequences == (
        f"<Option-Shift-Key-{digit}>",
    )
    assert tk_key_sequences(f"Ctrl+{digit}") == (f"<Control-Key-{digit}>",)


@pytest.mark.parametrize(
    ("native", "expected"),
    [
        ("<1>", "<Key-1>"),
        ("<Control-5>", "<Control-Key-5>"),
        ("<Alt-Shift-0>", "<Alt-Shift-Key-0>"),
        ("<Key-1>", "<Key-1>"),
        ("<Control-KeyPress-5>", "<Control-KeyPress-5>"),
        ("<Control-s>", "<Control-s>"),
        ("<F5>", "<F5>"),
    ],
)
def test_native_digit_sequence_is_a_key(native: str, expected: str) -> None:
    assert is_valid_key_sequence(native)
    assert tk_key_sequences(native) == (expected,)


# ---------------------------------------------------------------- QA-10-02: huge sizes
# Sizes in the tens of millions of pixels freeze the Tk event loop on the first update.
def _one_widget(class_name: str, props: str, layout: str = "") -> str:
    return (
        f'{HEADER}<window id="main" kind="main"><layout type="grid"/>'
        f'<widget class="{class_name}" id="w1">{props}<cell row="0" column="0"/>{layout}'
        "</widget></window></pyguibud-ui>"
    )


_GRID = '<layout type="grid"/>'
_SIZES = [
    ("Frame", "width", _GRID),
    ("Frame", "height", _GRID),
    ("LabelFrame", "width", _GRID),
    ("ScrolledFrame", "height", _GRID),
    ("Notebook", "width", ""),
    ("Label", "width", ""),
    ("Button", "width", ""),
    ("Entry", "width", ""),
    ("Combobox", "width", ""),
    ("Spinbox", "width", ""),
    ("Text", "height", ""),
    ("Canvas", "width", ""),
    ("Canvas", "height", ""),
    ("Scale", "length", ""),
    ("Progressbar", "length", ""),
    ("Listbox", "height", ""),
    ("Treeview", "height", ""),
]


@pytest.mark.parametrize(("class_name", "prop", "layout"), _SIZES)
def test_huge_size_property_is_refused(class_name: str, prop: str, layout: str) -> None:
    def errors(value: str) -> list[str]:
        text = _one_widget(class_name, f'<prop name="{prop}">{value}</prop>', layout)
        report = validate(read_ui_string(text).document, default_registry())
        return [finding.code for finding in report.errors]

    assert errors("10000") == []
    assert errors("30000000") != []


# ---------------------------------------------------------------- QA-10-03: devices
def test_read_ui_refuses_a_device_without_blocking(tmp_path: Path) -> None:
    # Windows: CON reads the console and blocks; POSIX: a FIFO blocks the same way.
    if sys.platform == "win32":
        target = "CON"
    else:
        target = str(tmp_path / "fifo.ui")
        os.mkfifo(target)
    code = textwrap.dedent(
        f"""
        from pyguibud.core import read_ui
        from pyguibud.core.errors import XmlIoError
        try:
            read_ui({target!r})
        except XmlIoError as exc:
            print(exc.code)
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        stdin=subprocess.PIPE,
        check=False,
    )
    assert result.stdout.strip() == "xml.not_a_file", result.stderr


# ---------------------------------------------------------------- QA-10-04: translator shape
class _NoPgettext:
    def gettext(self, message: str) -> str:
        return message


@pytest.mark.parametrize("bad", [object(), "de_DE", _NoPgettext()])
def test_load_ui_refuses_a_translator_without_the_protocol(tmp_path: Path, bad: object) -> None:
    path = tmp_path / "t.ui"
    path.write_text(
        f'{HEADER}<window id="main" kind="main"><layout type="grid"/></window></pyguibud-ui>',
        encoding="utf-8",
    )
    with pytest.raises(TypeError, match="translator"):
        load_ui(path, translator=bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------- QA-10-05: BCP 47 tags
def test_hyphenated_language_finds_the_underscore_catalogue(tmp_path: Path) -> None:
    folder = tmp_path / "locale" / "de_DE" / "LC_MESSAGES"
    folder.mkdir(parents=True)
    examples = Path(__file__).resolve().parents[2] / "examples" / "locale"
    (folder / "hello.mo").write_bytes(
        (examples / "de_DE" / "LC_MESSAGES" / "hello.mo").read_bytes()
    )
    texts = Texts({"k": DocumentTexts("hello", tmp_path / "locale", "en_GB")}, "de-DE", None)
    assert texts._by_doc["k"].gettext("Ready") == "Bereit"
    pseudo = Texts({"k": DocumentTexts("hello", tmp_path / "locale", "en_GB")}, "en-XA", None)
    assert pseudo._by_doc["k"].gettext("Ready") != "Ready"


# ---------------------------------------------------------------- QA-10-06: empty reasons
def test_build_failure_with_an_empty_message_still_names_the_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.backends import ttkbootstrap as tb_backend

    def fail(self: object, plan: object, master: object) -> object:
        raise RuntimeError()

    monkeypatch.setattr(tb_backend.TtkbootstrapBackend, "prepare", lambda self, master: None)
    monkeypatch.setattr(tb_backend.TtkbootstrapBackend, "build", fail)
    path = tmp_path / "t.ui"
    path.write_text(
        f'{HEADER}<window id="main" kind="main"><layout type="grid"/></window></pyguibud-ui>',
        encoding="utf-8",
    )
    with pytest.raises(UiError) as info:
        load_ui(path)
    assert info.value.code == "runtime.build_failed"
    assert str(info.value).endswith("failed: RuntimeError")


# ---------------------------------------------------------------- QA-10-08: example --lang
@pytest.mark.parametrize("lang", ["german", "../etc", "de_DE.UTF-8"])
def test_example_refuses_a_bad_language_without_a_traceback(lang: str) -> None:
    script = Path(__file__).resolve().parents[2] / "examples" / "run_hello.py"
    result = subprocess.run(
        [sys.executable, str(script), "--lang", lang],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "lang must be a language code" in result.stderr


# ---------------------------------------------------------------- QA-10-07: huge texts
# A one-line text of a few million characters stalls the Tk event loop for minutes.
def _text_codes(window_body: str, variables: str = "", props: str = "") -> list[str]:
    text = (
        f'{HEADER}{variables}<window id="main" kind="main">{props}{window_body}'
        "</window></pyguibud-ui>"
    )
    report = validate(read_ui_string(text).document, default_registry())
    return [finding.code for finding in report.errors]


_TEXT_PLACES = {
    "title": ('<layout type="grid"/>', "", '<prop name="title">{t}</prop>'),
    "label": (
        '<layout type="grid"/><widget class="Label" id="w1"><prop name="text">{t}</prop>'
        '<cell row="0" column="0"/></widget>',
        "",
        "",
    ),
    "page": (
        '<layout type="grid"/><widget class="Notebook" id="nbk"><cell row="0" column="0"/>'
        '<widget class="Frame" id="pg"><page><prop name="text">{t}</prop></page>'
        '<layout type="grid"/></widget></widget>',
        "",
        "",
    ),
    "menu": (
        '<menubar><menu id="mnu"><prop name="text">{t}</prop><action id="act">'
        '<prop name="text">{t}</prop></action></menu></menubar><layout type="grid"/>',
        "",
        "",
    ),
    "statusbar": (
        '<statusbar id="sts"><prop name="text">{t}</prop></statusbar><layout type="grid"/>',
        "",
        "",
    ),
    "default": (
        '<layout type="grid"/><widget class="Entry" id="ent" bind="v"><cell row="0" column="0"/>'
        "</widget>",
        '<variables><var id="v" type="string" default="{t}"/></variables>',
        "",
    ),
}


@pytest.mark.parametrize("place", sorted(_TEXT_PLACES))
def test_text_longer_than_the_limit_is_refused(place: str) -> None:
    from pyguibud.core.validate import MAX_DEFAULT_LENGTH, MAX_TEXT_LENGTH

    limit = MAX_DEFAULT_LENGTH if place == "default" else MAX_TEXT_LENGTH
    body, variables, props = _TEXT_PLACES[place]

    def codes(length: int) -> list[str]:
        t = "x" * length
        return _text_codes(body.format(t=t), variables.format(t=t), props.format(t=t))

    assert codes(limit) == []
    assert "validate.text_too_long" in codes(limit + 1)


# ---------------------------------------------------------------- QA-10-09 / QA-10-11 (fake)
class _Session:
    """A minimal session: records the applied texts; ``alive`` can be switched off."""

    def __init__(self) -> None:
        self.is_alive = True
        self.destroyed = 0
        self.applied: list[list[str]] = []
        self.slots: list[object] = []

    def alive(self) -> bool:
        return self.is_alive

    def apply_texts(self, text: object, runtime_text: object) -> None:
        shown = [text(slot) for slot in self.slots]  # type: ignore[operator]
        self.applied.append(shown)

    def show(self, window_id: str) -> str | None:
        return None

    def run(self) -> None:
        return None

    def destroy(self) -> None:
        self.destroyed += 1


def _fake_ui() -> tuple[LoadedUi, _Session, Texts]:
    from pyguibud.backends.base import TextSlot
    from pyguibud.core.model import Prop

    ui = LoadedUi("t.ui")
    ui._windows["main"] = object()
    session = _Session()
    session.slots = [
        TextSlot("k", Prop(name="text", value=value, translatable=True))
        for value in ("File", "Ready")
    ]
    texts = Texts({"k": DocumentTexts("", Path("."), "en_GB")}, None, None)
    ui._session, ui._texts = session, texts
    return ui, session, texts


def test_closed_interface_reports_destroyed_and_cleans_up() -> None:
    # QA-10-09: closing the main window (X button) used to make show() raise a bare TclError.
    ui, session, _texts = _fake_ui()
    session.is_alive = False
    with pytest.raises(UiError) as info:
        ui.show("main")
    assert info.value.code == "runtime.destroyed"
    assert session.destroyed == 1  # what is left (e.g. the dialogs) is destroyed
    calls: tuple[Callable[[], object], ...] = (ui.retranslate, ui.run, lambda: ui.show("main"))
    for call in calls:
        with pytest.raises(UiError, match="destroyed"):
            call()
    assert session.destroyed == 1


class _Upper:
    def gettext(self, message: str) -> str:
        return message.upper()

    def pgettext(self, context: str, message: str) -> str:
        return message.upper()


class _BadResult(_Upper):
    def gettext(self, message: str) -> str:
        return 42 if message == "Ready" else message.upper()  # type: ignore[return-value]


def test_retranslate_with_a_non_text_translation_changes_nothing() -> None:
    # QA-10-11: a translator returning a non-str raised mid-way and stayed stored.
    ui, session, texts = _fake_ui()
    ui.retranslate(translator=_Upper())
    good = texts.translator
    with pytest.raises(TypeError, match="returned int, not str"):
        ui.retranslate(translator=_BadResult())
    assert texts.translator is good and texts.lang is None
    assert session.applied == [["FILE", "READY"]]  # nothing applied by the failed call
    ui.retranslate()
    assert session.applied[-1] == ["FILE", "READY"]
