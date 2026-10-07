"""The action registry (pure): one list of actions drives menus, toolbar, keys and cheat-sheet.

Labels are msgids (with an ``_`` mnemonic mark) and are translated when read, so a language
switch needs no rebuild of the registry. Shortcuts use the ``core.keys`` chord grammar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from pyguibud.core.keys import format_chord, parse_chord, split_mnemonic
from pyguibud.designer.signals import Signal
from pyguibud.i18n import N_, _, pgettext

__all__ = [
    "ActionDef",
    "ActionRegistry",
    "CheatRow",
    "MenuDef",
    "Separator",
    "label_of",
]

_log = logging.getLogger(__name__)
_M_FAILED = N_("The action could not be completed: {reason}")
# Translators: {label} is an action ("Delete"); {scope} lists the panels where its key works.
_M_SCOPED = N_("{label} ({scope})")
SCOPE_LABELS = {"canvas": N_("canvas"), "tree": N_("object tree")}


def _always() -> bool:
    return True


@dataclass(frozen=True, slots=True)
class ActionDef:
    """One user action. ``label`` is a msgid with an optional ``_`` mnemonic mark."""

    id: str  # unique, dotted: "file.new"
    menu: str  # a MenuDef id
    label: str
    handler: Callable[[], None]
    shortcut: str | None = None
    enabled: Callable[[], bool] = _always
    checked: Callable[[], bool] | None = None  # radio items (theme, language)
    toolbar: bool = False
    translate: bool = True  # False for literal labels such as language autonyms
    context: str | None = None  # pgettext context
    #: Panels (``"canvas"``, ``"tree"``) whose focus widget owns the chord; () = every widget.
    scope: tuple[str, ...] = ()
    alt_shortcuts: tuple[str, ...] = ()  # extra chords; the menu shows only ``shortcut``
    #: ``(msgid, params)`` of the live menu label, or None for the static ``label`` (fallback).
    dynamic_label: Callable[[], tuple[str, Mapping[str, str]] | None] | None = None
    #: Why the shortcut does nothing while the action is disabled (a translated status-bar
    #: text), or None to stay silent.
    refusal: Callable[[], str | None] | None = None

    @property
    def chords(self) -> tuple[str, ...]:
        """Every chord of the action, the displayed one first."""
        return (*(() if self.shortcut is None else (self.shortcut,)), *self.alt_shortcuts)


@dataclass(frozen=True, slots=True)
class MenuDef:
    """A menu, or a sub-menu when ``parent`` names another menu."""

    id: str
    label: str
    parent: str | None = None


@dataclass(frozen=True, slots=True)
class Separator:
    """A separator line between two groups of menu items."""


@dataclass(frozen=True, slots=True)
class CheatRow:
    """One line of the shortcut cheat-sheet, in the current language."""

    menu: str
    label: str
    accelerator: str


def label_of(action: ActionDef, *, live: bool = True) -> str:
    """The action's label in the current language (mnemonic mark still in).

    ``live=False`` ignores ``dynamic_label``: the cheat-sheet lists the static label.
    """
    if live and action.dynamic_label is not None:
        dynamic = action.dynamic_label()
        if dynamic is not None:
            # A literal "_" in a parameter must not become a mnemonic mark.
            params = {k: v.replace("_", "__") for k, v in dynamic[1].items()}
            return _(dynamic[0]).format(**params)
    if not action.translate:
        return action.label
    if action.context is not None:
        return pgettext(action.context, action.label)
    return _(action.label)


@dataclass(slots=True)
class ActionRegistry:
    """Menus, actions and separators, in the order they were added."""

    message: Signal[str] = field(default_factory=Signal, init=False)  # status-bar text for failures
    _menus: dict[str, MenuDef] = field(default_factory=dict, init=False)
    _items: dict[str, list[ActionDef | MenuDef | Separator]] = field(
        default_factory=dict, init=False
    )
    _actions: dict[str, ActionDef] = field(default_factory=dict, init=False)
    _chords: dict[tuple[frozenset[str], str], list[tuple[frozenset[str], str]]] = field(
        default_factory=dict, init=False
    )

    def add_menu(self, menu: MenuDef) -> None:
        """Register a menu; a sub-menu is also listed as an item of its parent.

        Raises:
            ValueError: duplicate id or unknown parent.
        """
        if menu.id in self._menus:
            raise ValueError(f"duplicate menu id {menu.id!r}")
        if menu.parent is not None and menu.parent not in self._menus:
            raise ValueError(f"unknown parent menu {menu.parent!r}")
        self._menus[menu.id] = menu
        self._items[menu.id] = []
        if menu.parent is not None:
            self._items[menu.parent].append(menu)

    def add(self, action: ActionDef) -> None:
        """Register an action.

        Raises:
            ValueError: duplicate id, unknown menu, bad chord or a chord used twice.
        """
        if action.id in self._actions:
            raise ValueError(f"duplicate action id {action.id!r}")
        if action.menu not in self._menus:
            raise ValueError(f"unknown menu {action.menu!r}")
        scope = frozenset(action.scope)
        claimed = []
        for text in action.chords:
            chord = parse_chord(text)
            if chord is None:
                raise ValueError(f"bad shortcut {text!r} for {action.id!r}")
            for other, owner in self._chords.get(chord.identity, ()):
                if not scope or not other or scope & other:  # a global chord clashes with any
                    raise ValueError(f"shortcut {text!r} is used by {owner!r} and {action.id!r}")
            claimed.append(chord.identity)
        for identity in claimed:
            self._chords.setdefault(identity, []).append((scope, action.id))
        self._actions[action.id] = action
        self._items[action.menu].append(action)

    def add_separator(self, menu_id: str) -> None:
        """Append a separator to a menu."""
        self._items[menu_id].append(Separator())

    def menu(self, menu_id: str) -> MenuDef:
        """The menu called ``menu_id`` (KeyError if unknown)."""
        return self._menus[menu_id]

    def menu_ids(self) -> tuple[str, ...]:
        """Every menu id, in registration order."""
        return tuple(self._menus)

    def menu_items(self, menu_id: str) -> tuple[ActionDef | MenuDef | Separator, ...]:
        """The items of a menu, in order (sub-menus appear where they were added)."""
        return tuple(self._items[menu_id])

    def actions(self) -> tuple[ActionDef, ...]:
        """Every action, in registration order."""
        return tuple(self._actions.values())

    def get(self, action_id: str) -> ActionDef | None:
        """The action with ``action_id``, or None."""
        return self._actions.get(action_id)

    def invoke(self, action_id: str) -> bool:
        """Run an action. Returns False when it is unknown or disabled.

        A failing handler is logged and reported through :attr:`message`; it never propagates.
        """
        action = self._actions.get(action_id)
        if action is None or not self._is_enabled(action):
            return False
        try:
            action.handler()
        except Exception as exc:
            _log.exception("Action %s failed", action_id)
            self.message.emit(_(_M_FAILED).format(reason=exc))
        return True

    @staticmethod
    def _is_enabled(action: ActionDef) -> bool:
        try:
            return bool(action.enabled())
        except Exception:
            _log.exception("enabled() of %s failed", action.id)
            return False

    def is_enabled(self, action: ActionDef) -> bool:
        """Whether ``action`` may run now (a failing ``enabled()`` counts as disabled)."""
        return self._is_enabled(action)

    @staticmethod
    def is_checked(action: ActionDef) -> bool:
        """Whether a radio action is the selected one (False without ``checked``)."""
        if action.checked is None:
            return False
        try:
            return bool(action.checked())
        except Exception:
            _log.exception("checked() of %s failed", action.id)
            return False

    def cheat_sheet(self) -> list[CheatRow]:
        """Every action that has a shortcut: ``(menu, label, accelerator)``, current language."""
        rows: list[CheatRow] = []
        for action in self._actions.values():
            chords = [parse_chord(text) for text in action.chords]
            if not chords or None in chords:  # cannot happen: add() validated them
                continue
            menu = self._menus[action.menu]
            label = split_mnemonic(label_of(action, live=False))[0]
            if action.scope:  # e.g. "Delete (canvas, object tree)"
                scope = ", ".join(_(SCOPE_LABELS[s]) for s in action.scope)
                label = _(_M_SCOPED).format(label=label, scope=scope)
            rows.append(
                CheatRow(
                    menu=split_mnemonic(_(menu.label))[0],
                    label=label,
                    accelerator=", ".join(format_chord(c) for c in chords if c is not None),
                )
            )
        return rows
