"""The toolkit-free variables of the Qt backend (spec backends D12, §7 pure part)."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.backends._vars import BooleanVar, DoubleVar, IntVar, StringVar


def test_defaults_names_and_types() -> None:
    assert StringVar().get() == "" and IntVar().get() == 0
    assert DoubleVar().get() == 0.0 and BooleanVar().get() is False
    assert str(IntVar(5, "count")) == "count" and str(StringVar()).startswith("PY_VAR")
    assert IntVar("3.7").get() == 3 and IntVar(True).get() == 1
    assert DoubleVar("2.5").get() == 2.5 and StringVar(4).get() == "4"
    assert BooleanVar("Yes").get() is True and BooleanVar("off").get() is False
    assert BooleanVar(1).get() is True


@pytest.mark.parametrize(
    ("var", "bad"),
    [
        (IntVar(), "abc"),
        (IntVar(), "inf"),
        (IntVar(), None),
        (DoubleVar(), "x"),
        (BooleanVar(), "maybe"),
    ],
)
def test_a_value_that_does_not_convert_changes_nothing(var: IntVar, bad: object) -> None:
    calls: list[tuple[str, str, str]] = []
    var.trace_add("write", lambda *a: calls.append(a))
    before = var.get()
    with pytest.raises((ValueError, TypeError, OverflowError)):
        var.set(bad)
    assert var.get() == before and calls == []


def test_set_notifies_every_time_with_tkinter_arguments() -> None:
    var = StringVar("a", "name")
    calls: list[tuple[str, str, str]] = []
    token = var.trace_add("write", lambda *a: calls.append(a))
    var.set("a")  # an equal value still notifies, as a Tk trace
    var.set("b")
    assert calls == [("name", "", "write")] * 2 and var.get() == "b"
    var.trace_remove("write", token)
    var.trace_remove("write", token)  # unknown token: ignored
    var.set("c")
    assert len(calls) == 2


def test_only_the_write_mode_is_supported() -> None:
    with pytest.raises(ValueError, match="write"):
        IntVar().trace_add("read", lambda *_: None)
    with pytest.raises(ValueError, match="write"):
        IntVar().trace_remove("unset", "x")


def test_a_raising_trace_is_reported_and_the_others_still_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reported: list[object] = []
    monkeypatch.setattr("sys.excepthook", lambda *info: reported.append(info[1]))
    var = IntVar()
    calls: list[int] = []

    def boom(*_: object) -> None:
        raise RuntimeError("boom")

    var.trace_add("write", boom)
    var.trace_add("write", lambda *_: calls.append(var.get()))
    var.set(7)
    assert calls == [7] and isinstance(reported[0], RuntimeError)


@given(st.integers(min_value=-(10**9), max_value=10**9))
def test_int_round_trip(value: int) -> None:
    var = IntVar()
    var.set(value)
    assert var.get() == value
    var.set(str(value))
    assert var.get() == value


@given(st.text(max_size=50))
def test_string_round_trip(value: str) -> None:
    var = StringVar()
    var.set(value)
    assert var.get() == value
