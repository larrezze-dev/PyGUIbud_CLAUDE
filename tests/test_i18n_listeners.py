"""Tests for the language-change listener API."""

from __future__ import annotations

import gc
import gettext
import weakref
from collections.abc import Callable, Iterator

import pytest

from pyguibud import i18n
from pyguibud.i18n import (
    add_language_listener,
    language_listener,
    remove_language_listener,
    set_language,
)


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))
    yield


class Widget:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def retranslate(self, code: str) -> None:
        self.calls.append(code)


def test_weak_bound_method_is_pruned_after_collection() -> None:
    widget = Widget()
    add_language_listener(widget.retranslate)
    set_language("es_ES")
    assert widget.calls == ["es_ES"]
    calls = widget.calls
    del widget
    gc.collect()
    set_language("fr_FR")
    assert calls == ["es_ES"]
    assert i18n._listeners == []


def test_bound_method_does_not_keep_object_alive() -> None:
    widget = Widget()
    ref = weakref.ref(widget)
    add_language_listener(widget.retranslate)
    del widget
    gc.collect()
    assert ref() is None


def test_functions_are_held_strongly() -> None:
    seen: list[str] = []
    add_language_listener(lambda code: seen.append(code))
    gc.collect()
    set_language("de_DE")
    assert seen == ["de_DE"]


def test_duplicate_registration_is_noop() -> None:
    widget = Widget()
    seen: list[str] = []
    for _ in range(2):
        add_language_listener(widget.retranslate)
        add_language_listener(seen.append)
    set_language("it_IT")
    assert widget.calls == ["it_IT"]
    assert seen == ["it_IT"]
    assert len(i18n._listeners) == 2


def test_remove_unknown_is_noop_and_removes_bound_method() -> None:
    widget = Widget()
    remove_language_listener(widget.retranslate)
    add_language_listener(widget.retranslate)
    remove_language_listener(widget.retranslate)
    set_language("nl_NL")
    assert widget.calls == []


def test_notified_in_registration_order() -> None:
    order: list[int] = []

    def make(index: int) -> Callable[[str], None]:
        return lambda _code: order.append(index)

    for index in range(4):
        add_language_listener(make(index))
    set_language("pt_PT")
    assert order == [0, 1, 2, 3]


def test_mutation_during_notification_is_safe() -> None:
    seen: list[str] = []

    def late(code: str) -> None:
        seen.append(f"late:{code}")

    def first(code: str) -> None:
        seen.append(f"first:{code}")
        add_language_listener(late)
        remove_language_listener(second)

    def second(code: str) -> None:
        seen.append(f"second:{code}")

    add_language_listener(first)
    add_language_listener(second)
    set_language("pt_BR")
    # The snapshot still notifies `second`; `late` joins from the next change onwards.
    assert seen == ["first:pt_BR", "second:pt_BR"]
    set_language("fr_FR")
    assert seen[2:] == ["first:fr_FR", "late:fr_FR"]


def test_notify_only_on_change_unless_forced() -> None:
    seen: list[str] = []
    add_language_listener(seen.append)
    set_language("en_GB")
    assert seen == []
    set_language("es_ES")
    set_language("es-ES")
    assert seen == ["es_ES"]
    set_language("es_ES", force=True)
    assert seen == ["es_ES", "es_ES"]


def test_same_language_still_installs_translation(monkeypatch: pytest.MonkeyPatch) -> None:
    set_language("en_XA")
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    set_language("en_XA")
    assert i18n.gettext("Open") != "Open"


def test_failing_listener_does_not_stop_others() -> None:
    seen: list[str] = []

    def bad(_code: str) -> None:
        raise RuntimeError("boom")

    add_language_listener(bad)
    add_language_listener(seen.append)
    set_language("de_DE")
    assert seen == ["de_DE"]


def test_language_listener_context_manager() -> None:
    seen: list[str] = []
    with language_listener(seen.append):
        set_language("fr_FR")
    set_language("it_IT")
    assert seen == ["fr_FR"]
