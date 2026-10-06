"""Golden output and scale checks for Step 09 (spec ``docs/specs/validate-commands.md`` §10)."""

from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

from pyguibud.core import (
    CommandStack,
    Document,
    GridCell,
    Layout,
    Prop,
    Widget,
    Window,
    default_registry,
    validate,
)
from pyguibud.core.commands import SetProp

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "examples" / "validator_demo.py"
GOLDEN = ROOT / "tests" / "data" / "validator_demo.en_GB.txt"


def _demo(*args: str) -> str:
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG", "PYTHONUTF8"):
        env.pop(var, None)
    result = subprocess.run(
        [sys.executable, str(DEMO), *args], capture_output=True, env=env, check=False, timeout=120
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    return result.stdout.decode("utf-8").replace("\r\n", "\n")


def test_demo_stdout_equals_the_en_gb_golden() -> None:
    expected = GOLDEN.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert _demo() == expected


def test_demo_pseudo_locale_differs_from_the_golden_but_keeps_headers() -> None:
    expected = GOLDEN.read_bytes().decode("utf-8").replace("\r\n", "\n")
    pseudo = _demo("--lang", "en_XA")
    assert pseudo != expected
    lines = pseudo.splitlines()
    for number in range(1, 7):
        assert any(line.startswith(f"{number}. ") for line in lines), number


def _big_document(count: int) -> Document:
    document = Document()
    layout = Layout(type="grid")
    window = Window(id="main", layout=layout)
    frame = Widget(
        class_name="Frame",
        id="frame",
        placement=GridCell(row=0, column=0),
        layout=Layout(type="grid"),
    )
    window.append_child(frame)
    for index in range(count):
        frame.append_child(
            Widget(
                class_name="Label",
                id=f"w{index}",
                placement=GridCell(row=index // 40, column=index % 40),
            )
        )
    document.add_window(window)
    return document


def test_deep_tree_of_five_thousand_levels_does_not_hit_the_recursion_limit() -> None:
    document = Document()
    window = Window(id="main", layout=Layout(type="grid"))
    current: Window | Widget = window
    for index in range(5_000):
        child = Widget(
            class_name="Frame",
            id=f"f{index}",
            placement=GridCell(row=0, column=0),
            layout=Layout(type="grid"),
        )
        current.append_child(child)
        current = child
    document.add_window(window)
    report = validate(document, default_registry(), limit=None)
    assert not report.ok
    assert [f.code for f in report.errors].count("validate.too_deep") >= 1


def test_guard_budget_with_two_thousand_widgets() -> None:
    document = _big_document(2_000)
    stack = CommandStack(document, default_registry())
    target = document.find("w1000")
    assert isinstance(target, Widget)
    timings: list[float] = []
    for index in range(20):
        started = time.perf_counter()
        outcome = stack.execute(SetProp(target, Prop(name="text", value=f"t{index}")))
        timings.append(time.perf_counter() - started)
        assert outcome.accepted
    # Spec target: median < 100 ms. A generous bound keeps slow CI runners green.
    assert statistics.median(timings) < 1.0, timings
