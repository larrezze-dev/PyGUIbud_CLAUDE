"""The German literals of ``tools/verify_install.py`` still equal the shipped de_DE catalogue.

The install check compares real output with literals held in the script. If a translation is
reworded, this normal-suite test fails first, instead of the slow install check.
"""

from __future__ import annotations

import gettext
import importlib.util
import sys
from collections.abc import Callable
from types import ModuleType

import pytest
from babel.messages.pofile import read_po

from tests._paths import ROOT, RUNTIME_LOCALE

MSGID_NO_MAIN_WINDOW = "'{path}' has no main window; pass {argument} to load its dialogs."
DE_MESSAGES = RUNTIME_LOCALE / "de_DE" / "LC_MESSAGES"


@pytest.fixture(scope="module")
def script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_install", ROOT / "tools" / "verify_install.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def _check(script: ModuleType, translate: Callable[[str], str]) -> None:
    """``translate`` returns the raw de_DE msgstr; the message with parameters is formatted."""
    shown = translate(MSGID_NO_MAIN_WINDOW).format(path="dialog.ui", argument="master=")
    assert shown == script.GERMAN_NO_MAIN_WINDOW
    assert translate("_Cancel") == script.GERMAN_CANCEL
    assert translate("_OK") == script.GERMAN_OK


def test_the_literals_equal_the_po_msgstrs(script: ModuleType) -> None:
    with (DE_MESSAGES / "pyguibud.po").open("rb") as stream:
        catalogue = read_po(stream, locale="de_DE")

    def translate(msgid: str) -> str:
        message = catalogue[msgid]
        assert message is not None and isinstance(message.string, str), msgid
        return message.string

    _check(script, translate)


def test_the_literals_equal_the_compiled_catalogue(script: ModuleType) -> None:
    with (DE_MESSAGES / "pyguibud.mo").open("rb") as stream:
        translations = gettext.GNUTranslations(stream)
    _check(script, translations.gettext)
