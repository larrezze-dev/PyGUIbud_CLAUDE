"""Copy, cut, paste and duplicate (pure; spec properties-save-load 8, D3/D4).

The clipboard holds a complete ``.ui`` text marked with the foreign ``clip:mode`` root
attribute, read back with the hardened reader and judged by the validator (no second grammar).
Pasting works on that throwaway document: ids are remapped, references follow, paths are
rebased and placements fitted to the target before one ``Macro`` inserts the nodes. Nothing
here touches the user's document; the stack's guard judges the returned command.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from pyguibud.core.commands import (
    Command,
    InsertNode,
    Macro,
    RemoveNode,
    SetResource,
    SetVariable,
)
from pyguibud.core.errors import PyGUIbudError
from pyguibud.core.files import is_network_or_device_path
from pyguibud.core.model import (
    Action,
    Document,
    GridCell,
    Include,
    Layout,
    Menu,
    Menubar,
    MenuSeparator,
    PackPlacement,
    PagePlacement,
    Placement,
    Prop,
    Statusbar,
    Widget,
    Window,
)
from pyguibud.core.registry import Registry
from pyguibud.core.schema import CURRENT_SCHEMA_VERSION, parse_version
from pyguibud.core.validate import validate_read
from pyguibud.core.xml_io import MAX_UI_BYTES, dump_ui, read_ui_bytes, read_ui_string
from pyguibud.designer.editing import (
    M_LAST_WINDOW,
    relayout_command,
    unique_id,
    window_delete_refusal,
)
from pyguibud.designer.files import rebase_paths
from pyguibud.i18n import N_, _, ngettext

__all__ = [
    "CLIP_NS",
    "MAX_PASTE_WIDGETS",
    "Copied",
    "Pasted",
    "copy_text",
    "cut_command",
    "duplicate_command",
    "paste_command",
    "pasted_message",
]

CLIP_NS = "urn:pyguibud:clipboard:1"
_MODE = f"{{{CLIP_NS}}}mode"
_ORIGIN = f"{{{CLIP_NS}}}origin"
_STEM_MAX = 58  # room for a 6-digit counter within the 64-character id limit
#: Most widgets (and includes) one paste may add (A4).
MAX_PASTE_WIDGETS = 2000

_M_MENUS = N_("Menus and actions cannot be copied yet.")
_M_TOO_LARGE = N_("The clipboard content is too large to paste.")
_M_NOTHING = N_("The clipboard holds no PyGUIbud elements.")
# Translators: {reason} is the first validation error of the clipboard content.
_M_INVALID = N_("The clipboard content is not valid: {reason}")
# Translators: {id} is a pasted include whose component exists only in the file it came from.
_M_FOREIGN_INCLUDE = N_(
    "'{id}' includes a component of its original file; paste that component first."
)
# Translators: {limit} is the largest number of widgets one paste may add.
_M_TOO_MANY = N_("Paste refused: more than {limit} widgets.")
# Translators: {limit} is the largest number of widgets one duplicate may add.
_M_TOO_MANY_DUPLICATE = N_("Duplicate refused: more than {limit} widgets.")
# Translators: {version} and {current} are schema versions such as 1.1 and 1.0.
_M_NEWER_CLIP = N_(
    "The clipboard content uses schema version {version}, newer than {current}; it cannot "
    "be pasted."
)
#: Include rules that only the target document can judge: a copied ``src="#"`` include shows
#: a component of the original file (``_remap`` and the stack's guard check it there).
_TARGET_RULES = frozenset(
    {"validate.include_not_component", "validate.include_cycle", "validate.include_limit"}
)
_M_PASTE = N_("Paste")
_M_CUT = N_("Cut")
_M_DUPLICATE = N_("Duplicate")

_Item = Widget | Include
_Pasteable = Window | Widget | Include
_Mode = Literal["widgets", "windows"]
_Named = Window | Widget | Include | Menu | Action | Statusbar
_MENU_NODES = (Menubar, Menu, Action, MenuSeparator, Statusbar)


@dataclass(frozen=True, slots=True)
class Copied:
    """The clipboard text of a copy and the number of top-level elements in it."""

    text: str
    count: int


@dataclass(frozen=True, slots=True)
class Pasted:
    """The command that pastes, the pasted top-level nodes (the new selection) and how many
    warnings the clipboard content had (unknown content is kept, as on Open)."""

    command: Command
    nodes: tuple[_Pasteable, ...]
    warnings: int = 0


def pasted_message(count: int, warnings: int = 0) -> str:
    """The status message after a paste (shown after the selection changes, rule C1)."""
    # Translators: {count} is the number of pasted top-level elements.
    text = ngettext("Pasted {count} element.", "Pasted {count} elements.", count).format(
        count=count
    )
    if not warnings:
        return text
    # Translators: after "Pasted N elements."; {count} is the number of warnings about the
    # pasted content (unknown content is kept, as when a file is opened).
    more = ngettext(
        "The clipboard content had {count} warning.",
        "The clipboard content had {count} warnings.",
        warnings,
    ).format(count=warnings)
    return f"{text} {more}"


# ---------------------------------------------------------------- copy
def _pick(document: Document, nodes: Iterable[object]) -> list[_Pasteable] | str:
    """The top-level nodes to copy in document order (windows win), or a refusal."""
    nodes = list(nodes)
    if any(isinstance(n, _MENU_NODES) for n in nodes):
        return _(_M_MENUS)
    windows: list[_Pasteable] = [n for n in nodes if isinstance(n, Window)]
    chosen = windows or [n for n in nodes if isinstance(n, _Item)]
    order = {id(n): k for k, n in enumerate(document.walk())}
    keys = {id(n) for n in chosen}
    top = [n for n in chosen if id(n) in order and not any(id(a) in keys for a in n.ancestors())]
    if not top:
        raise ValueError("nothing to copy: the selection holds no element of the document")
    return sorted(top, key=lambda n: order[id(n)])


def _path(node: object) -> list[int]:
    """Child indices from the document down to ``node``."""
    path: list[int] = []
    while (parent := getattr(node, "parent", None)) is not None:
        path.append(parent.index_of(node))
        node = parent
    return path[::-1]


def _locate(document: Document, path: Sequence[int]) -> _Pasteable:
    node: Any = document
    for index in path:
        node = node.children[index]
    assert isinstance(node, Window | Widget | Include)
    return node


def _references(nodes: Iterable[object]) -> tuple[set[str], set[str]]:
    """(variable ids, image ids) that ``nodes`` use."""
    variables: set[str] = set()
    images: set[str] = set()
    for node in nodes:
        if isinstance(node, Widget) and node.bind:
            variables.add(node.bind)
        images.update(p.ref for p in getattr(node, "props", {}).values() if p.ref)
        placement = getattr(node, "placement", None)
        if isinstance(placement, PagePlacement) and placement.image:
            images.add(placement.image)
    return variables, images


def _wrapper_layout(top: Sequence[_Pasteable]) -> Layout:
    """The source parent's layout type and orient; pack when the parents differ or have pages."""
    parent = top[0].parent
    if all(n.parent is parent for n in top) and isinstance(parent, Window | Widget):
        if parent.layout is not None:
            return Layout(type=parent.layout.type, orient=parent.layout.orient)
        return Layout(type="pack", orient="horizontal")  # pages: in tab order
    return Layout(type="pack")


def _clip_placement(placement: Placement | None, layout: Layout, top: int, left: int) -> Placement:
    if layout.type == "grid" and isinstance(placement, GridCell):
        return replace(placement, row=placement.row - top, column=placement.column - left)
    return placement if isinstance(placement, PackPlacement) else PackPlacement()


def _snapshot(document: Document) -> bytes:
    """``dump_ui`` of ``document`` for a copy, also of a read-only (newer MINOR) one.

    The writer refuses a newer schema version because *saving* would lose what this version
    does not know. A copy only reads: it is written at this version, and whatever cannot be
    represented in it is refused when it is pasted (the clipboard is validated like a file).
    """
    version = document.schema_version
    parsed = parse_version(version) if isinstance(version, str) else None
    current = parse_version(CURRENT_SCHEMA_VERSION)
    if parsed is None or current is None or parsed <= current:
        return dump_ui(document)
    document.schema_version = CURRENT_SCHEMA_VERSION  # restored below: no edit, no stack
    try:
        return dump_ui(document)
    finally:
        document.schema_version = version


def copy_text(document: Document, nodes: Iterable[object], origin: Path | None) -> Copied | str:
    """The clipboard text for ``nodes`` (spec 8.1), or the translated reason it is refused.

    Selected windows are copied whole (``windows`` mode); otherwise the widgets and includes,
    with their descendants, go into a wrapper component with grid cells starting at 0,0.
    ``origin`` is the document's file (None when untitled); it lets a paste rebase paths.
    """
    top = _pick(document, nodes)
    if isinstance(top, str):
        return top
    try:
        copy = read_ui_bytes(_snapshot(document), source="<copy>").document
    except PyGUIbudError as error:
        return error.message
    found = [_locate(copy, _path(n)) for n in top]
    clip = Document(namespaces={**copy.namespaces, "clip": CLIP_NS}, meta=copy.meta)
    clip.extra_attrs[_MODE] = "windows" if isinstance(top[0], Window) else "widgets"
    if origin is not None:
        clip.extra_attrs[_ORIGIN] = os.path.abspath(origin).replace(os.sep, "/")
    if isinstance(top[0], Window):
        for window in found:
            assert isinstance(window, Window)
            copy.remove_window(window)
            clip.add_window(window)
    else:
        layout = _wrapper_layout(top)
        wrapper = Window(id=unique_id(document, "clipboard"), kind="component", layout=layout)
        clip.add_window(wrapper)
        cells = [
            n.placement for n in found if isinstance(n, _Item) and isinstance(n.placement, GridCell)
        ]
        first_row = min((c.row for c in cells), default=0)
        first_column = min((c.column for c in cells), default=0)
        for node in found:
            assert isinstance(node, _Item) and node.parent is not None
            node.parent.remove_child(node)
            node.placement = _clip_placement(node.placement, layout, first_row, first_column)
            wrapper.append_child(node)
    variables, images = _references(clip.walk())
    clip.variables = {k: v for k, v in copy.variables.items() if k in variables}
    clip.resources = {k: v for k, v in copy.resources.items() if k in images}
    try:
        return Copied(dump_ui(clip).decode("utf-8"), len(found))
    except PyGUIbudError as error:
        return error.message


def cut_command(
    document: Document, nodes: Iterable[object], origin: Path | None
) -> tuple[Copied, Command] | str:
    """Copy ``nodes`` and the ``Cut`` macro that deletes them, or the reason it is refused."""
    nodes = list(nodes)
    copied = copy_text(document, nodes, origin)
    if isinstance(copied, str):
        return copied
    top = _pick(document, nodes)
    assert not isinstance(top, str)
    windows = [n for n in top if isinstance(n, Window)]
    if windows and len(windows) >= len(document.children):
        return _(M_LAST_WINDOW)
    for window in windows:  # an includer that is cut as well does not keep it (QA-14a2-08)
        if reason := window_delete_refusal(document, window, also=windows):
            return reason
    return copied, Macro(_M_CUT, [RemoveNode(n) for n in top])


# ---------------------------------------------------------------- paste
def _read_clip(
    text: str, registry: Registry, too_many: str = _M_TOO_MANY
) -> tuple[Document, _Mode, int] | str:
    """Steps 1-2: size, hardened read, marker, schema version, widget limit, validation."""
    if len(text) > MAX_UI_BYTES or len(text.encode("utf-8", "surrogatepass")) > MAX_UI_BYTES:
        return _(_M_TOO_LARGE)
    try:
        result = read_ui_string(text, source="<clipboard>")
    except PyGUIbudError as error:
        if error.code == "xml.newer_major":  # from a newer PyGUIbud: say so (QA-14a2-06)
            version = error.params.get("version", "")
            return _(_M_NEWER_CLIP).format(version=version, current=CURRENT_SCHEMA_VERSION)
        return _(_M_NOTHING)
    clip = result.document
    mode = clip.extra_attrs.get(_MODE)
    if mode not in ("widgets", "windows") or (mode == "widgets" and len(clip.children) != 1):
        return _(_M_NOTHING)
    if result.read_only:  # a newer MINOR: its content would be saved under this version
        return _(_M_NEWER_CLIP).format(version=clip.schema_version, current=CURRENT_SCHEMA_VERSION)
    if sum(isinstance(n, _Item) for n in clip.walk()) > MAX_PASTE_WIDGETS:
        return _(too_many).format(limit=MAX_PASTE_WIDGETS)
    report = validate_read(result, registry)
    errors = [e for e in report.errors if e.code not in _TARGET_RULES]
    if errors:
        return _(_M_INVALID).format(reason=errors[0].message)
    warnings = len(result.warnings) + len(report.warnings)
    return clip, "widgets" if mode == "widgets" else "windows", warnings


def _resolved(src: str, base: Path | None) -> str:
    """A string identity of an image path (no file-system access: it may be a network path)."""
    if base is not None and not os.path.isabs(src):
        src = os.path.join(base, src)
    return os.path.normcase(os.path.normpath(src))


def _rebase(clip: Document, base: Path | None) -> None:
    """Step 4: relative paths from ``clip:origin`` to ``base`` (absolute when untitled)."""
    origin = clip.extra_attrs.get(_ORIGIN, "")
    old = None
    if os.path.isabs(origin) and not is_network_or_device_path(origin):
        old = Path(origin).parent
    if base is not None:
        command = rebase_paths(clip, old, base)
        if command is not None:
            command.apply()  # the throwaway document: no stack involved
        return
    if old is None:
        return
    for key, image in clip.resources.items():
        if image.src and not os.path.isabs(image.src):
            clip.resources[key] = replace(image, src=_absolute(old, image.src))
    for node in clip.walk():
        if isinstance(node, Include) and node.src not in ("", "#") and not os.path.isabs(node.src):
            node.src = _absolute(old, node.src)


def _absolute(folder: Path, src: str) -> str:
    return os.path.normpath(os.path.join(folder, src)).replace(os.sep, "/")


def _fresh(old: str, taken: set[str]) -> str:
    """A free id from ``old`` by the project numbering (``OkBtn_2`` -> ``OkBtn1``), case kept.

    The stem is never re-stemmed (unlike a palette insert); the digit suffix keeps the result
    off the keyword and reserved lists. Recorded in ``taken``.
    """
    stem = (re.sub(r"_?\d+$", "", old) or old)[:_STEM_MAX]
    n = 1
    while (new := f"{stem}{n}") in taken:
        n += 1
    taken.add(new)
    return new


def _remap(
    document: Document, clip: Document, tops: Sequence[_Pasteable], base: Path | None
) -> list[Command] | str:
    """Step 3 on the throwaway ``clip``: rename clashing ids and make references follow.

    Returns the ``SetVariable``/``SetResource`` commands of the copies that are not reused.
    """
    target = {i for i, _owner in document.iter_ids()}
    nodes = [n for top in tops for n in ([top] if isinstance(top, Include) else top.walk())]
    own = [i for n in nodes if isinstance(i := getattr(n, "id", None), str)]
    taken = target | set(own) | set(clip.variables) | set(clip.resources)
    commands: list[Command] = []
    variables: dict[str, str] = {}
    for var in clip.variables.values():
        old = document.variables.get(var.id)
        if old is not None and old.type == var.type:
            continue  # reuse: the binds stay
        new_id = _fresh(var.id, taken) if var.id in target else var.id
        variables[var.id] = new_id
        commands.append(SetVariable(document, replace(var, id=new_id)))
    images: dict[str, str] = {}
    for image in clip.resources.values():
        known = document.resources.get(image.id)
        if known is not None and _resolved(known.src, base) == _resolved(image.src, base):
            continue
        new_id = _fresh(image.id, taken) if image.id in target else image.id
        images[image.id] = new_id
        commands.append(SetResource(document, replace(image, id=new_id)))
    renamed: dict[str, str] = {}
    for node in nodes:
        if isinstance(node, _Named) and node.id in target:
            renamed[node.id] = node.id = _fresh(node.id, taken)
    windows = {w.id for w in document.children} | {t.id for t in tops if isinstance(t, Window)}
    for node in nodes:
        if isinstance(node, Widget) and node.bind is not None:
            node.bind = variables.get(node.bind, node.bind)
        props: dict[str, Prop] | None = getattr(node, "props", None)
        for name, prop in list((props or {}).items()):
            if prop.ref in images:
                props[name] = replace(prop, ref=images[prop.ref])  # type: ignore[index]
        page = node.placement if isinstance(node, _Item) else None
        if isinstance(page, PagePlacement) and page.image in images:
            node.placement = replace(page, image=images[page.image])  # type: ignore[union-attr]
        if isinstance(node, Include) and node.src == "#":
            node.component = renamed.get(node.component, node.component)
            if node.component not in windows:
                return _(_M_FOREIGN_INCLUDE).format(id=node.id)
    return commands


def _is_pages(node: object, registry: Registry) -> bool:
    if not isinstance(node, Widget):
        return False
    spec = registry.get(node.class_name) or registry.get(node.fallback or "")
    return spec is not None and spec.children == "pages"


def _page(container: Widget, node_id: str) -> PagePlacement:
    """A notebook tab shows the pasted id as its text; a paned window has no page text."""
    if "Notebook" in (container.class_name, container.fallback):
        return PagePlacement(text=Prop(name="text", value=node_id, translatable=True))
    return PagePlacement()


def _fit(wrapper: Window, container: object, registry: Registry) -> list[_Item]:
    """Step 5: the wrapper's children, detached and placed for ``container`` in paste order."""
    if _is_pages(container, registry):
        assert isinstance(container, Widget)
        for node in wrapper.children:
            node.placement = _page(container, node.id)
    elif isinstance(container, Window | Widget):
        kind = container.layout.type if container.layout is not None else "pack"
        if wrapper.layout is not None and wrapper.layout.type != kind:
            relayout_command(wrapper, kind).apply()  # keeps the reading order
        if kind == "grid":
            used = [c.placement for c in container.children if isinstance(c.placement, GridCell)]
            below = max((c.row + max(c.rowspan, 1) for c in used), default=0)
            cells = [n.placement for n in wrapper.children if isinstance(n.placement, GridCell)]
            top = min((c.row for c in cells), default=0)
            left = min((c.column for c in cells), default=0)
            for node in wrapper.children:
                cell = node.placement
                if isinstance(cell, GridCell):
                    node.placement = replace(
                        cell, row=cell.row - top + below, column=cell.column - left
                    )
    nodes = list(wrapper.children)
    for node in nodes:
        wrapper.remove_child(node)
    return nodes


def _target(document: Document, selected: object, registry: Registry) -> tuple[object, int | None]:
    """Where widgets go: into a selected container or window, after a selected leaf."""
    if isinstance(selected, Statusbar):
        selected = next((w for w in document.children if w.statusbar is selected), selected)
    if isinstance(selected, Window | Menubar | Menu) or (
        isinstance(selected, Widget)
        and (selected.layout is not None or _is_pages(selected, registry))
    ):
        return selected, None
    parent = getattr(selected, "parent", None)
    if isinstance(selected, Widget | Include | Action | MenuSeparator) and parent is not None:
        return parent, parent.index_of(selected) + 1
    raise TypeError(f"cannot paste into {type(selected).__name__}")


def _paste(
    document: Document,
    clip: Document,
    mode: _Mode,
    where: tuple[object, int | None],
    registry: Registry,
    base: Path | None,
    label: str,
    warnings: int = 0,
) -> Pasted | str:
    _rebase(clip, base)
    tops: list[_Pasteable] = list(clip.children) if mode == "windows" else []
    if mode == "widgets":
        tops = list(clip.children[0].children)
    commands = _remap(document, clip, tops, base)
    if isinstance(commands, str):
        return commands
    parent, index = where
    if mode == "windows":
        has_main = document.main_window is not None
        for window in clip.children:
            clip.remove_window(window)
            if window.kind == "main" and has_main:
                window.kind = "dialog"  # one main per file: the copy becomes a dialog
    else:
        tops = list(_fit(clip.children[0], parent, registry))
    inserts = [
        InsertNode(parent, node, None if index is None else index + k)
        for k, node in enumerate(tops)
    ]
    return Pasted(Macro(label, [*commands, *inserts]), tuple(tops), warnings)


def paste_command(
    document: Document,
    selected: object,
    text: str,
    registry: Registry,
    base: Path | None,
) -> Pasted | str:
    """Paste the clipboard ``text`` at ``selected`` (spec 8.2), or the reason it is refused.

    ``selected`` is the selected node, or the current window when nothing is selected;
    ``base`` is the folder of the document's file (None when untitled). Windows are always
    added as new windows. The guard still judges the command (non-container, collisions).
    """
    read = _read_clip(text, registry)
    if isinstance(read, str):
        return read
    clip, mode, warnings = read
    where = (document, None) if mode == "windows" else _target(document, selected, registry)
    return _paste(document, clip, mode, where, registry, base, _M_PASTE, warnings)


def duplicate_command(
    document: Document, nodes: Iterable[object], registry: Registry
) -> Pasted | str:
    """Ctrl+D: the copy-paste round trip in memory, inserted after the last selected node."""
    nodes = list(nodes)
    copied = copy_text(document, nodes, None)
    if isinstance(copied, str):
        return copied
    read = _read_clip(copied.text, registry, _M_TOO_MANY_DUPLICATE)
    if isinstance(read, str):
        return read
    top = _pick(document, nodes)
    assert not isinstance(top, str)
    anchor = top[-1]
    parent = anchor.parent
    assert parent is not None
    where = (parent, parent.index_of(anchor) + 1)  # type: ignore[arg-type]
    clip, mode, warnings = read
    return _paste(document, clip, mode, where, registry, None, _M_DUPLICATE, warnings)
