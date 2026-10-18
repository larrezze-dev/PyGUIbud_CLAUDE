"""Step 19e (designer part): menu paths in sentences (H77), contexts (H78), key names as
placeholders (H79), escaped user text in messages (H81), "Opened with N errors" (H82), About."""

from __future__ import annotations

import ast
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.__about__ import __version__
from pyguibud.core.keys import split_mnemonic
from pyguibud.core.model import Widget
from pyguibud.credits import credit
from pyguibud.designer import export as ex
from pyguibud.designer.actions import M_DELETE_WINDOW, M_DOCUMENT, label_of, window_delete_hint
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.clipboard import paste_command
from pyguibud.designer.dialogs.about import AboutDialog
from pyguibud.designer.standard_actions import _M_PREVIEW_MENU, _M_PREVIEW_RUN
from tests.designer.test_clipboard import REG, SOURCE, copied, load

TARGETS = ("es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR")
ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "data" / "hardening" / "bidi_id.ui"
FORGED = "a\nb\u202ec"
ESCAPED = "a\\nb\\u202ec"


@pytest.mark.parametrize("code", (*TARGETS, "en_XA"))
def test_h77_the_cited_path_is_the_real_menu_path(code: str) -> None:
    i18n.set_language(code)
    menu, item = (split_mnemonic(i18n._(m))[0] for m in (M_DOCUMENT, M_DELETE_WINDOW))
    hint = window_delete_hint()
    assert f"{menu} ▸ {item}" in hint and ">" not in hint and "{" not in hint
    sentence = i18n._("Windows are deleted with {path}.")  # the catalogue's own wording
    assert "{path}" in sentence


def test_h78_the_preview_menu_and_action_have_their_own_contexts() -> None:
    assert _M_PREVIEW_MENU != _M_PREVIEW_RUN
    assert i18n._(_M_PREVIEW_MENU) == i18n._(_M_PREVIEW_RUN) == "_Preview"
    i18n.set_language("en_XA")
    assert i18n._(_M_PREVIEW_MENU).startswith("[") and i18n._(_M_PREVIEW_RUN).startswith("[")


_KEYS = re.compile(r"\b(Ctrl|Control|Alt|Shift|Esc|Escape|Enter|Tab|PageUp|PageDown|F\d{1,2})\b")
_MARKERS = {"N_", "_", "NC_", "NP_", "ngettext", "pgettext", "gettext"}


def _literals(node: ast.AST) -> Iterator[ast.Constant]:
    return (n for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))


def test_h79_no_literal_key_names_inside_designer_msgids() -> None:
    found = []
    for path in (ROOT / "src" / "pyguibud" / "designer").rglob("*.py"):
        for call in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name in _MARKERS:
                found += [
                    f"{path.name}:{c.lineno} {c.value!r}"
                    for arg in call.args
                    for c in _literals(arg)
                    if isinstance(c.value, str) and _KEYS.search(c.value)
                ]
    assert not found, found


# ------------------------------------------------------------------ H81
def test_h81_export_messages_escape_user_text() -> None:
    refusal = ex.Refusal(ex.M_BAD_CHARS, {"name": FORGED})
    assert ESCAPED in refusal.text() and "\u202e" not in refusal.text()
    assert "\n" not in refusal.text()  # only the one line: nothing was forged
    plan = ex.ExportPlan("o.py", "", None, None, False, notes=(refusal,))
    outcome = ex.ExportOutcome(plan, (FORGED,), refusal)
    assert (
        ESCAPED in outcome.text() and "\n" not in outcome.text() and "\u202e" not in outcome.text()
    )


def test_h81_clipboard_messages_escape_user_text_but_not_the_payload() -> None:
    document, _stack = load(SOURCE)
    text = copied(document, "lbl")
    assert "\u202e" not in text
    bad = text.replace('id="lbl"', f'id="lbl" bind="{FORGED}"')
    result = paste_command(document, document.children[0], bad, REG, None)
    assert isinstance(result, str) and "\u202e" not in result and "\n" not in result, result


@pytest.mark.gui
def test_h81_the_status_bar_escapes_messages_and_selected_ids(
    shell: DesignerApp, tmp_path: Path
) -> None:
    shell.shell.show_message(FORGED)
    assert shell.shell._message == ESCAPED
    copy = tmp_path / "bidi_id.ui"
    shutil.copyfile(FIXTURE, copy)
    assert shell.open_path(copy)
    assert shell.session.document is not None
    button = next(n for n in shell.session.document.walk() if isinstance(n, Widget))
    assert "\u202e" in button.id
    shell.shell.clear_message()
    shell.session.select(button, origin="tree")
    shell.shell.root.update()
    shown = str(shell.shell._status.cget("text"))
    assert "\\u202e" in shown and "\u202e" not in shown


# ------------------------------------------------------------------ H82
@pytest.mark.gui
def test_h82_a_file_with_errors_says_errors_not_warnings(
    shell: DesignerApp, tmp_path: Path
) -> None:
    copy = tmp_path / "bidi_id.ui"
    shutil.copyfile(FIXTURE, copy)
    messages: list[str] = []
    shell.message.connect(messages.append)
    assert shell.open_path(copy)
    assert any(m.startswith("Opened with ") and " error" in m for m in messages), messages
    assert not any("warning" in m for m in messages)
    assert shell.session.report().errors


# ------------------------------------------------------------------ About
@pytest.mark.gui
def test_help_about_shows_the_version_licence_and_credit(shell: DesignerApp) -> None:
    action = next(a for a in shell.registry.actions() if a.id == "help.about")
    assert split_mnemonic(label_of(action))[0] == "About PyGUIbud…"
    shell.open_about()
    dialog: Any = shell._live_dialogs()[0]
    assert isinstance(dialog, AboutDialog)
    details = str(dialog.details.cget("text"))
    assert __version__ in details and "MIT" in details
    assert str(dialog.credit.cget("text")) == credit()
    assert "Luciano Arrezze" in credit() and "Claude Code" in credit()
    dialog.window.event_generate("<Escape>")
    dialog.close()
    assert dialog.closed
