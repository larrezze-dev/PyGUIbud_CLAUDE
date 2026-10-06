"""The hand-made ``hello`` catalogue covers every translatable text of ``hello.ui``."""

from __future__ import annotations

import gettext
import re

from babel.messages.pofile import read_po

from pyguibud.core import Menu, Prop, Widget, read_ui
from pyguibud.core.model import Action, PagePlacement
from tests.runtime.conftest import EXAMPLES

MESSAGES = EXAMPLES / "locale" / "de_DE" / "LC_MESSAGES"


def _ui_props() -> list[Prop]:
    document = read_ui(EXAMPLES / "hello.ui").document
    props: list[Prop] = []
    for window in document.children:
        props.extend(window.props.values())
        if window.statusbar is not None:
            props.extend(window.statusbar.props.values())
        nodes = [*window.walk(), *(window.menubar.walk() if window.menubar else ())]
        for node in nodes:
            if isinstance(node, (Widget, Menu, Action)):
                props.extend(node.props.values())
            page = node.placement if isinstance(node, Widget) else None
            if isinstance(page, PagePlacement) and page.text is not None:
                props.append(page.text)
    return [p for p in props if p.translatable]


def test_po_covers_hello_ui_and_mo_is_fresh() -> None:
    with (MESSAGES / "hello.po").open("rb") as stream:
        catalogue = read_po(stream)
    with (MESSAGES / "hello.mo").open("rb") as stream:
        compiled = gettext.GNUTranslations(stream)
    keys = {(prop.context, prop.value) for prop in _ui_props()}
    assert len(keys) == 9
    for context, msgid in keys:
        message = catalogue.get(msgid, context=context)
        assert message is not None, (context, msgid)
        assert message.string and not message.fuzzy
    placeholder = re.compile(r"\{[^{}]*\}")
    for message in catalogue:
        if not message.id:
            continue
        assert isinstance(message.id, str) and isinstance(message.string, str)
        assert placeholder.findall(message.id) == placeholder.findall(message.string)
        if message.context:
            assert compiled.pgettext(message.context, message.id) == message.string
        else:
            assert compiled.gettext(message.id) == message.string
