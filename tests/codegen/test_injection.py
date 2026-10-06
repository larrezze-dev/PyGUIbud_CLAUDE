"""Injection fuzz: nothing a ``.ui`` file says may become code in the generated module (spec 4.2).

Every text, comment, context and variable default is XML-legal but otherwise arbitrary; ids and
handler names sit on the boundaries of the identifier, reserved-name and keyword gates. A
document is either refused (``CodegenError``) or generates a module whose AST, with every
constant blanked, is *identical* to the AST of a plain skeleton: ``.ui`` strings change only
constants, and ids only attribute names.
"""

from __future__ import annotations

import ast
import keyword
import tempfile
import unicodedata
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape, quoteattr

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud.codegen import CodegenError, generate_python
from pyguibud.core.errors import XmlIoError
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import run_generated, write_ui
from tests.codegen.test_smoke import ALLOWED_IMPORTS, _imports

END = "# --- end of support ---"
# The support block opens the .mo catalogue and uses getattr for handlers: both reviewed once.
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "system", "popen"}
FORBIDDEN_AFTER_SUPPORT = FORBIDDEN_CALLS | {"open", "getattr", "setattr", "delattr", "globals"}
BAD_CATEGORIES = {"Cc", "Cf", "Zl", "Zp", "Cs", "Co", "Cn"}
SETTINGS = settings(
    max_examples=120,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.function_scoped_fixture],
)

# XML 1.0 forbids these code points (tab, LF and CR are the only legal controls below U+0020).
_ILLEGAL = "".join(chr(c) for c in (*range(0, 9), 11, 12, *range(14, 32), 0xFFFE, 0xFFFF))
NASTY_TEXTS = (
    '"""',
    "'''",
    '"',
    "'",
    "\\",
    "\\n",
    "\\x00",
    "\\u0000",
    "#",
    "# comment",
    "{}",
    "{0}",
    "{name}",
    "%s",
    "\n",
    "\t",
    "\r",
    "\x85",
    "\u2028",
    "\u2029",
    "\u202e",
    "\u200b",
    "\x7f",
    "\U0001f600",
    "'); import os; os.system('x') #",
    '"""\nimport os\n"""',
    "__import__('os')",
    "\\\n",
    "\\N{DIGIT ONE}",
    "f'{1}'",
    "${x}",
)
legal_char = st.characters(blacklist_categories=("Cs",), blacklist_characters=_ILLEGAL)
texts = st.one_of(
    st.text(legal_char, min_size=1, max_size=40),
    st.sampled_from(NASTY_TEXTS),
    st.lists(st.sampled_from(NASTY_TEXTS), min_size=2, max_size=5).map("".join),
)

NASTY_IDS = (
    *keyword.kwlist,
    *("match", "case", "type", "self", "print", "Ui_Main", "Ui_", "s", "w", "v", "i", "top"),
    *("body", "bar", "menu", "object", "str", "int", "id", "input", "__", "_x", "x_", "a" * 64),
    *(
        "a" * 65,
        "a" * 63 + "-",
        "a-b",
        "a b",
        "1a",
        "\u00e9",
        "\uff41",
        "a\u0301",
        "",
        " ",
        "a.b",
        "a/b",
    ),
    *("vars", "widgets", "windows", "setup_ui", "retranslate", "show", "run", "destroy"),
    *("exec", "eval", "getattr", "open", "compile", "__import__", "__class__", "format"),
)
grammar_ids = st.from_regex(r"[A-Za-z][A-Za-z0-9_]{0,12}", fullmatch=True)
any_id = st.one_of(
    grammar_ids, grammar_ids, st.sampled_from(NASTY_IDS), st.text(legal_char, max_size=8)
)
DEFAULT_IDS = ("main", "lbl", "btn", "nbk", "pg", "mnu", "act", "sts", "var")


def _text(value: str) -> str:
    return escape(value).replace("\r", "&#13;")


def _attr(value: str) -> str:
    return quoteattr(value)


def skeleton(
    *,
    title: str = "Title",
    ctx: str = "ctx",
    comment: str = "note",
    label: str = "Label",
    button: str = "_Go",
    tab: str = "Tab",
    menu: str = "_Menu",
    action: str = "_Act",
    status: str = "Ready",
    default: str = "x",
    ids: tuple[str, ...] = DEFAULT_IDS,
    handler: str = "on_go",
) -> tuple[str, str]:
    """``(windows, variables)``: one main window using every kind of text-bearing node."""
    main, lbl, btn, nbk, pg, mnu, act, sts, var = ids
    window = (
        f'<window id={_attr(main)} kind="main">'
        f'<prop name="title" translatable="true" context={_attr(ctx)} comment={_attr(comment)}>'
        f"{_text(title)}</prop>"
        f"<menubar><menu id={_attr(mnu)}>"
        f'<prop name="text" translatable="true">{_text(menu)}</prop>'
        f'<action id={_attr(act)} handler={_attr(handler)} shortcut="Ctrl+K">'
        f'<prop name="text" translatable="true">{_text(action)}</prop></action>'
        f"</menu></menubar>"
        f'<statusbar id={_attr(sts)}><prop name="text" translatable="true">{_text(status)}'
        f"</prop></statusbar>"
        f'<layout type="grid"/>'
        f'<widget class="Label" id={_attr(lbl)} bind={_attr(var)}>'
        f'<prop name="text" translatable="true" context={_attr(ctx)}>{_text(label)}</prop>'
        f'<cell row="0" column="0"/></widget>'
        f'<widget class="Button" id={_attr(btn)}>'
        f'<prop name="text" translatable="true" comment={_attr(comment)}>{_text(button)}</prop>'
        f'<event name="command" handler={_attr(handler)}/><cell row="1" column="0"/></widget>'
        f'<widget class="Notebook" id={_attr(nbk)}><cell row="2" column="0"/>'
        f'<widget class="Frame" id={_attr(pg)}><page>'
        f'<prop name="text" translatable="true" context={_attr(ctx)}>{_text(tab)}</prop></page>'
        f'<layout type="pack"/></widget></widget></window>'
    )
    return window, f'<var id={_attr(var)} type="string" default={_attr(default)}/>'


@pytest.fixture(scope="module")
def workdir() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="pyguibud-fuzz-") as folder:
        yield Path(folder)


def generate_text(workdir: Path, **params: Any) -> str | None:
    """The generated module for a skeleton, or ``None`` when the document is refused."""
    window, variables = skeleton(**params)
    ui = write_ui(workdir / "fuzz.ui", window, variables=variables)
    try:
        return generate_python(read_ui(str(ui)), str(ui), output=str(workdir / "fuzz_ui.py")).text
    except (CodegenError, XmlIoError):  # refused: invalid document or not well-formed
        return None


class _Blank(ast.NodeTransformer):
    """Blank every constant; optionally rename the given attribute names and the class name."""

    def __init__(self, names: frozenset[str] = frozenset()) -> None:
        self.names = names

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        return ast.Constant(value=None)

    def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
        self.generic_visit(node)
        if node.attr in self.names:
            node.attr = "<id>"
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.AST:
        self.generic_visit(node)
        if node.name.startswith("Ui_"):
            node.name = "Ui_<main>"
        return node

    def visit_Name(self, node: ast.Name) -> ast.AST:
        if node.id.startswith("Ui_"):
            node.id = "Ui_<main>"
        return node


def shape(text: str, names: frozenset[str] = frozenset()) -> str:
    """The AST of everything after the support block, constants blanked."""
    tree = ast.parse(text.split(END, 1)[1])
    return ast.dump(_Blank(names).visit(tree), include_attributes=False)


def _called(node: ast.Call) -> str:
    """The called name: a bare builtin, or a method such as ``os.system`` (not ``re.compile``)."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    attr = getattr(func, "attr", "")
    return "" if attr == "compile" else str(attr)


def check_module(text: str) -> None:
    """The structural safety rules of spec 4.2 for any generated module."""
    tree = ast.parse(text)
    compile(tree, "generated.py", "exec")
    assert _imports(tree) <= ALLOWED_IMPORTS
    for ch in set(text) - {"\n"}:
        assert unicodedata.category(ch) not in BAD_CATEGORIES, repr(ch)
    assert text.endswith("\n") and len(text.splitlines()) == text.count("\n")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            assert _called(node) not in FORBIDDEN_CALLS, _called(node)
    # After the support block (fixed text, reviewed once) nothing may reflect, import or exec.
    for node in ast.walk(ast.parse(text.split(END, 1)[1])):
        if isinstance(node, ast.Call):
            assert _called(node) not in FORBIDDEN_AFTER_SUPPORT, _called(node)
        assert not isinstance(node, (ast.Import, ast.ImportFrom))


@pytest.fixture(scope="module")
def baseline(workdir: Path) -> str:
    text = generate_text(workdir)
    assert text is not None
    check_module(text)
    return shape(text, frozenset(DEFAULT_IDS))


@SETTINGS
@given(
    title=texts,
    ctx=texts,
    comment=texts,
    label=texts,
    button=texts,
    tab=texts,
    menu=texts,
    action=texts,
    status=texts,
    default=st.one_of(st.just(""), texts),
)
def test_texts_comments_and_contexts_change_only_constants(
    workdir: Path, baseline: str, **params: str
) -> None:
    text = generate_text(workdir, **params)
    if text is None:  # a refusal is allowed; silent corruption is not
        return
    check_module(text)
    assert shape(text, frozenset(DEFAULT_IDS)) == baseline


@SETTINGS
@given(
    swaps=st.lists(st.tuples(st.integers(0, 8), any_id), min_size=1, max_size=4),
    handler=st.one_of(any_id, st.sampled_from(("exec", "eval", "getattr", "open", "on_go"))),
)
def test_ids_and_handlers_at_the_gate_boundaries(
    workdir: Path, baseline: str, swaps: list[tuple[int, str]], handler: str
) -> None:
    ids = list(DEFAULT_IDS)
    for slot, name in swaps:  # a duplicate id is a valid way to be refused
        ids[slot] = name
    text = generate_text(workdir, ids=tuple(ids), handler=handler)
    if text is None:
        return
    # Accepted: every id and the handler obey the grammar and are not keywords.
    for name in (*ids, handler):
        assert name.isascii() and name.isidentifier() and not keyword.iskeyword(name), name
        assert len(name) <= 64 and not name.startswith("_"), name
    assert len(set(ids)) == len(ids)
    check_module(text)
    assert shape(text, frozenset(ids)) == baseline


def test_gate_boundary_names_are_decided_by_the_validator(workdir: Path) -> None:
    def accepts(name: str) -> bool:
        ids = ("main", name, "btn", "nbk", "pg", "mnu", "act", "sts", "v")
        return generate_text(workdir, ids=ids) is not None

    accepted = {name for name in NASTY_IDS if accepts(name)}
    assert {"match", "case", "type", "self", "print", "Ui_Main", "s", "w", "i", "top"} <= accepted
    assert {"body", "bar", "menu", "format", "exec", "x_", "a" * 64} <= accepted
    refused = set(NASTY_IDS) - accepted
    assert set(keyword.kwlist) <= refused
    assert {"a" * 65, "a-b", "\u00e9", "", "1a", "vars", "setup_ui", "__", "_x"} <= refused


@pytest.mark.gui
def test_awkward_but_valid_ids_build_and_attach(workdir: Path) -> None:
    names = ["case", "type", "self", "print", "s", "w", "v", "i", "top", "body", "bar"]
    names += ["menu", "object", "str", "int", "id", "input", "format", "exec", "eval", "open"]
    names += ["getattr", "x_", "a" * 64, "Ui_Main", "Ui_", "bind", "grid", "pack", "config"]
    widgets = "".join(
        f'<widget class="Label" id="{n}"><prop name="text">{n[:8]}</prop>'
        f'<cell row="{row}" column="0"/></widget>'
        for row, n in enumerate(names)
    )
    ui = write_ui(
        workdir / "ids.ui",
        f'<window id="match" kind="main"><layout type="grid"/>{widgets}</window>',
        variables='<var id="self_v" type="string"/>',
    )
    module = workdir / "ids_ui.py"
    generated = generate_python(read_ui(str(ui)), str(ui), output=str(module))
    module.write_text(generated.text, encoding="utf-8", newline="\n")
    assert generated.class_name == "Ui_Match"
    out = run_generated(
        module,
        """
ui = g["Ui_Match"]()
ui.setup_ui()
out["classes"] = {n: ui.widgets[n].winfo_class() for n in ui.widgets if n != "match"}
out["attached"] = {n: getattr(ui, n) is ui.widgets[n] for n in ui.widgets}
ui.destroy()
""",
    )
    assert out["attached"] and all(out["attached"].values())
    assert all(cls == "TLabel" for cls in out["classes"].values())
