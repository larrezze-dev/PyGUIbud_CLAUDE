"""Step 21a: the en-GB README links every translated README, and each translation carries the
credit line in its own language (taken from the designer's catalogue) and only absolute links."""

from __future__ import annotations

import re

import pytest
from babel.messages.pofile import read_po

from tests._paths import ROOT, RUNTIME_LOCALE

REPO = "https://github.com/larrezze-dev/PyGUIbud_CLAUDE/blob/master"
LOCALES = ["es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR"]
CREDIT_MSGID = "Created by {author} and programmed with the support of {tool}"


def _readme(locale: str) -> str:
    return f"docs/readme/README.{locale.replace('_', '-')}.md"


def _credit(locale: str) -> str:
    with (RUNTIME_LOCALE / locale / "LC_MESSAGES" / "pyguibud.po").open("rb") as po:
        message = read_po(po).get(CREDIT_MSGID)
    assert message is not None and message.string, locale
    return str(message.string).format(author="Luciano Arrezze", tool="Claude Code")


@pytest.mark.parametrize("locale", LOCALES)
def test_the_english_readme_links_each_translation(locale: str) -> None:
    assert f"]({REPO}/{_readme(locale)})" in (ROOT / "README.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("locale", LOCALES)
def test_each_translation_carries_its_credit_and_only_absolute_links(locale: str) -> None:
    text = (ROOT / _readme(locale)).read_text(encoding="utf-8")
    assert _credit(locale) in text
    assert re.findall(r"\]\((?!https://)([^)]*)\)", text) == []
    # Every translation links back to the English original.
    assert f"]({REPO}/README.md)" in text
