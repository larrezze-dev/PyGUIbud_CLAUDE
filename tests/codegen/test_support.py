"""``_support.py`` equals the core functions it copies, and obeys its own rules (spec 4.2)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from hypothesis import given
from hypothesis import strategies as st

from pyguibud.backends._tkmap import clip_text
from pyguibud.codegen import _support, support_text
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.validate import MAX_TEXT_LENGTH, RESERVED_IDS
from pyguibud.i18n import LANGUAGE_CODE_RE

SUPPORT = Path(_support.__file__)
_MNEMONIC_TEXT = st.text(alphabet=st.sampled_from("a_ Bx_é"), max_size=12)


@given(_MNEMONIC_TEXT)
def test_split_mnemonic_is_the_core_one(text: str) -> None:
    assert _support._split_mnemonic(text) == split_mnemonic(text)


@given(st.integers(min_value=-1, max_value=MAX_TEXT_LENGTH + 5), st.integers(0, 3))
def test_clip_is_the_tkmap_one(underline: int, extra: int) -> None:
    text = "x" * (MAX_TEXT_LENGTH - 1 + extra)
    assert _support._clip(text, underline) == clip_text(text, underline)


def test_constants_match_the_core() -> None:
    assert _support._MAX_TEXT == MAX_TEXT_LENGTH
    # One language-code grammar: R81, --lang, load_ui and the generated modules.
    assert _support._LANG_RE.pattern == LANGUAGE_CODE_RE.pattern


def test_support_region_is_copied_without_markers() -> None:
    region = support_text()
    assert "BEGIN SUPPORT" not in region and "END SUPPORT" not in region
    assert region.startswith("import base64")
    assert region in SUPPORT.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_support_region_has_no_gettext_literal_calls_and_no_dynamic_code() -> None:
    tree = ast.parse(support_text())
    markers = {"_", "N_", "NP_", "gettext", "pgettext", "ngettext"}
    banned = {"eval", "exec", "compile", "__import__"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        assert not (isinstance(func, ast.Name) and name in banned), name
        assert name != "system", name
        if name in markers:
            assert not any(isinstance(arg, ast.Constant) for arg in node.args), ast.unparse(node)
    for module in ("importlib", "pickle", "subprocess", "pyguibud"):
        assert not re.search(rf"^\s*(import|from) {module}\b", support_text(), re.M), module


def test_public_members_are_exactly_the_reserved_ids() -> None:
    class Ui_Probe(_support._Ui):  # noqa: N801 - the generated class naming
        pass

    assert {n for n in dir(Ui_Probe()) if not n.startswith("_")} == RESERVED_IDS
    assert {n for n in dir(_support._Scope()) if not n.startswith("_")} == {
        "vars",
        "widgets",
        "windows",
    }


def test_resolve_follows_the_runtime_rules() -> None:
    class Raising:
        @property
        def on_x(self) -> object:
            raise RuntimeError

    def fn() -> None:
        return None

    assert _support._resolve({"on_x": fn}, "on_x") is fn
    assert _support._resolve({"on_x": 1}, "on_x") is None
    assert _support._resolve(Raising(), "on_x") is None
    assert _support._resolve(None, "on_x") is None


def test_setup_ui_checks_arguments_before_tk() -> None:
    import pytest

    ui = _support._Ui()
    for kwargs, error in (
        ({"strict": 1}, TypeError),
        ({"lang": "../x"}, ValueError),
        ({"translator": object()}, TypeError),
        ({"localedir": 3}, TypeError),
    ):
        with pytest.raises(error):
            ui.setup_ui(**kwargs)
    with pytest.raises(TypeError):
        ui.setup_ui(master=object())
    with pytest.raises(_support.UiError) as info:
        ui.show("main")
    assert info.value.code == "runtime.destroyed"
