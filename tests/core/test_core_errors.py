"""Tests for ``pyguibud.core.errors``."""

from __future__ import annotations

import pytest

from pyguibud import i18n
from pyguibud.core import ModelError, PyGUIbudError, RegistryError, format_message


def test_hierarchy() -> None:
    assert issubclass(ModelError, PyGUIbudError)
    assert issubclass(RegistryError, PyGUIbudError)
    assert issubclass(PyGUIbudError, Exception)


def test_code_msgid_params_and_message() -> None:
    err = ModelError("model.x", "Hello {who}, {n} items", who="Ann", n=3)
    assert err.code == "model.x"
    assert err.msgid == "Hello {who}, {n} items"
    assert err.params == {"who": "Ann", "n": 3}
    assert err.message == "Hello Ann, 3 items"
    assert str(err) == err.message
    assert err.args == ("model.x", "Hello {who}, {n} items")


def test_params_are_copied() -> None:
    err = RegistryError("r.x", "{a}", a="1")
    err.params["a"] = "2"
    assert err.message == "2"


def test_message_is_lazy_and_follows_language_switch() -> None:
    err = ModelError("model.x", "Unknown backend '{name}'.", name="qt")
    assert err.message == "Unknown backend 'qt'."
    i18n.set_language("en_XA")
    switched = err.message
    assert switched != "Unknown backend 'qt'."
    assert switched.startswith("[")
    assert "'qt'" in switched  # placeholder value survives pseudo-translation
    i18n.set_language("en_GB")
    assert err.message == "Unknown backend 'qt'."


def test_message_can_be_caught_and_displayed() -> None:
    with pytest.raises(PyGUIbudError, match="oops 1"):
        raise ModelError("c", "oops {n}", n=1)


@pytest.mark.parametrize(
    ("msgid", "params"),
    [
        ("needs {missing}", {}),
        ("needs {0}", {}),
        ("bad {", {"a": 1}),
        ("bad }", {}),
        ("{a.b}", {"a": 1}),
        ("{a[0]}", {"a": 1}),
        ("{a:d}", {"a": "text"}),
        ("{a.b.c}", {"a": None}),
        ("", {}),
    ],
)
def test_format_message_never_raises(msgid: str, params: dict[str, object]) -> None:
    result = format_message(msgid, params)
    assert isinstance(result, str)


def test_format_message_falls_back_to_msgid() -> None:
    assert format_message("needs {missing}", {}) == "needs {missing}"
    assert format_message("bad {", {}) == "bad {"


def test_format_message_extra_params_ignored() -> None:
    assert format_message("hi {a}", {"a": 1, "b": 2}) == "hi 1"


def test_error_with_missing_param_does_not_raise() -> None:
    err = ModelError("c", "needs {missing}")
    assert err.message == "needs {missing}"
    assert str(err) == "needs {missing}"


def test_format_message_translation_breaks_format(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pyguibud.core.errors._", lambda msgid: "broken {nope}")
    assert format_message("ok {a}", {"a": 1}) == "ok 1"


def test_format_message_both_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("pyguibud.core.errors._", lambda msgid: "{x")
    assert format_message("{y", {}) == "{y"
