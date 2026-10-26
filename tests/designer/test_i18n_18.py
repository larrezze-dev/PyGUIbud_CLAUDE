"""Step 18: the access keys of every dialog button set and of the tree's context menu are unique
in every locale now that the catalogues are filled.

The dialog check works on the msgid groups each dialog shows together (cheap and complete); the
context menu is checked on the real menu, since the shell de-duplicates its keys at run time.
"""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core.keys import split_mnemonic
from pyguibud.designer import app as app_module
from pyguibud.designer.dialogs import (
    confirm,
    export,
    message,
    new_file,
    plugins,
    recovery,
    rename,
    save_changes,
    shortcuts,
    text,
)
from pyguibud.designer.theme_tk import underline_of

ALL_LANGUAGES = (*i18n.LANGUAGES, i18n.PSEUDO_LANGUAGE)

#: The button labels that share one window (and so one set of Alt keys).
DIALOG_GROUPS: dict[str, tuple[str, ...]] = {
    "unsaved changes": (save_changes._M_SAVE, save_changes._M_DONT_SAVE, save_changes._M_CANCEL),
    "file changed on disk": (app_module._M_OVERWRITE, app_module._M_SAVE_AS, app_module._M_CANCEL),
    "write failed": (app_module._M_OK, app_module._M_SAVE_AS),
    "confirm delete": (confirm._M_DELETE, confirm._M_CANCEL),
    "confirm save with errors": (app_module._M_SAVE, confirm._M_CANCEL),
    "confirm discard": (app_module._M_DISCARD, confirm._M_CANCEL),
    "recovery": (recovery._M_RESTORE, recovery._M_DISCARD, recovery._M_LATER),
    "export": (export._M_EXPORT, export._M_CANCEL),
    "export of unsaved changes": (export._M_SAVE_AND_EXPORT, export._M_CANCEL),
    "template wizard": (new_file._M_CREATE, new_file._M_CANCEL),
    "plugins (disable)": (plugins._M_COPY, plugins._M_DISABLE, plugins._M_CLOSE),
    "plugins (enable)": (plugins._M_COPY, plugins._M_ENABLE, plugins._M_CLOSE),
    "rename window": (rename._M_OK, rename._M_CANCEL),
    "edit text": (text._M_OK, text._M_CANCEL),
    "message": (message._M_OK,),
    "keyboard shortcuts": (shortcuts._M_CLOSE,),
}


def _keys(msgids: tuple[str, ...]) -> list[str]:
    letters = []
    for msgid in msgids:
        shown, underline = split_mnemonic(i18n._(msgid))
        assert underline >= 0, (msgid, i18n._(msgid))
        letters.append(shown[underline].casefold())
    return letters


@pytest.mark.parametrize("lang", ALL_LANGUAGES)
@pytest.mark.parametrize("group", sorted(DIALOG_GROUPS))
def test_dialog_buttons_have_unique_access_keys(lang: str, group: str) -> None:
    assert i18n.set_language(lang) == lang
    letters = _keys(DIALOG_GROUPS[group])
    assert len(letters) == len(set(letters)), (lang, group, letters)


@pytest.mark.gui
@pytest.mark.parametrize("lang", ALL_LANGUAGES)
def test_tree_context_menu_has_unique_access_keys(shell: Any, lang: str) -> None:
    shell.set_language(lang)
    menu = shell.shell.tree_menu
    last = menu.index("end")
    assert last is not None
    letters = []
    for index in range(last + 1):
        if menu.type(index) == "separator":
            continue
        label = str(menu.entrycget(index, "label"))
        underline = underline_of(menu.entrycget(index, "underline"))
        assert 0 <= underline < len(label), (lang, label, underline)
        letters.append(label[underline].casefold())
    assert len(letters) >= 5
    assert len(letters) == len(set(letters)), (lang, letters)
