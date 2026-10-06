"""``extract_pot``: a deterministic ``.pot`` template from ``.ui`` files (spec ``codegen.md`` 8).

The output has no creation date and no width wrapping, and the entries come in traversal order,
so the same ``.ui`` files always give the same bytes.
"""

from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Iterator, Sequence

from pyguibud.__about__ import __version__
from pyguibud.core.model import Action, Include, Menu, PagePlacement, Prop, Widget, Window
from pyguibud.core.xml_io import ReadResult

__all__ = ["extract_pot"]

_ESCAPES = str.maketrans(
    {"\\": "\\\\", '"': '\\"', "\t": "\\t", "\r": "\\r", "\n": "\\n"},
)

# The template's name (header) comes from the domain or the file name: never a quote or newline.
_NOT_NAME = re.compile(r"[^A-Za-z0-9_.-]")
# gettext >= 0.22 (and Babel) isolate a file name with whitespace between FSI and PDI.
_FSI, _PDI = "\u2068", "\u2069"

# (owner node, position part, prop) for every translatable prop, in traversal order.
_Item = tuple[object, str, Prop]


def _wanted(prop: Prop | None) -> bool:
    return prop is not None and prop.translatable and prop.value != ""


def _props(owner: object, props: dict[str, Prop]) -> Iterator[_Item]:
    for prop in props.values():
        if _wanted(prop):
            yield owner, f"prop[{prop.name}]", prop


def _menus(menu: Menu) -> Iterator[_Item]:
    yield from _props(menu, menu.props)
    for child in menu.children:
        if isinstance(child, Menu):
            yield from _menus(child)
        elif isinstance(child, Action):
            yield from _props(child, child.props)


def _widgets(children: Sequence[Widget | Include]) -> Iterator[_Item]:
    stack: list[Widget | Include] = list(reversed(children))
    while stack:
        node = stack.pop()
        if isinstance(node, Widget):
            yield from _props(node, node.props)
        placement = node.placement
        page = placement.text if isinstance(placement, PagePlacement) else None
        if page is not None and _wanted(page):
            yield node, "page/prop[text]", page
        if isinstance(node, Widget):
            stack.extend(reversed(node.children))


def _items(window: Window) -> Iterator[_Item]:
    yield from _props(window, window.props)
    if window.menubar is not None:
        for menu in window.menubar.children:
            yield from _menus(menu)
    if window.statusbar is not None:
        yield from _props(window.statusbar, window.statusbar.props)
    yield from _widgets(window.children)


def _quote(text: str) -> list[str]:
    """The quoted PO lines of ``text``; a value with newlines uses the multi-line form."""
    if "\n" not in text:
        return ['"' + text.translate(_ESCAPES) + '"']
    parts = text.split("\n")
    segments = [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])
    return ['""', *('"' + segment.translate(_ESCAPES) + '"' for segment in segments)]


def _field(name: str, text: str) -> list[str]:
    first, *rest = _quote(text)
    return [f"{name} {first}", *rest]


def _reference(source: str, line: int, base_dir: str) -> str | None:
    try:
        shown = os.path.relpath(os.path.abspath(source), os.path.abspath(base_dir))
    except ValueError:  # another drive
        shown = os.path.basename(source)
    shown = shown.replace(os.sep, "/")
    if any(ch in (_FSI, _PDI) or unicodedata.category(ch) in ("Cc", "Zl", "Zp") for ch in shown):
        return None  # a line break or isolate inside the name cannot be written on a "#:" line
    if any(ch.isspace() for ch in shown):  # references are whitespace-separated (QA-11-09)
        shown = f"{_FSI}{shown}{_PDI}"
    return f"{shown}:{line}"


def extract_pot(results: Sequence[tuple[ReadResult, str]], *, base_dir: str) -> str:
    """Merge the translatable texts of ``results`` (each with its path) into one ``.pot`` text.

    ``base_dir`` is the folder the ``#:`` references are relative to. The text has LF newlines
    and ends with one newline.
    """
    entries: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    for result, path in results:
        for window in result.document.children:
            for owner, part, prop in _items(window):
                comments, references = entries.setdefault(
                    (prop.context or "", prop.value), ([], [])
                )
                for line in (prop.comment or "").splitlines():
                    if line not in comments:
                        comments.append(line)
                position = result.positions.get(owner, part)
                if position is not None:
                    ref = _reference(path, position[0], base_dir)
                    if ref is not None and ref not in references:
                        references.append(ref)
    name = ""
    if results:
        first, first_path = results[0]
        domain = first.document.meta.i18n_domain
        name = domain or os.path.splitext(os.path.basename(first_path))[0]
        name = _NOT_NAME.sub("_", name)  # QA-11-10: the name is written inside the header
    lines = [
        f"# Translations template for {name}.",
        "#, fuzzy",
        'msgid ""',
        'msgstr ""',
        f'"Project-Id-Version: {name}\\n"',
        '"MIME-Version: 1.0\\n"',
        '"Content-Type: text/plain; charset=UTF-8\\n"',
        '"Content-Transfer-Encoding: 8bit\\n"',
        f'"Generated-By: pyguibud-uic {__version__}\\n"',
    ]
    for (context, msgid), (comments, references) in entries.items():
        lines.append("")
        lines += [f"#. {line}" for line in comments]
        if references:
            lines.append("#: " + " ".join(references))
        if context:
            lines += _field("msgctxt", context)
        lines += _field("msgid", msgid)
        lines.append('msgstr ""')
    return "\n".join(lines) + "\n"
