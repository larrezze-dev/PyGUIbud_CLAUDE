"""The author credit shown by ``--help``, ``--version`` and Help ▸ About (CLAUDE.md rule)."""

from __future__ import annotations

from .i18n import N_, _

AUTHOR = "Luciano Arrezze"
TOOL = "Claude Code"
# Translators: {author} is a person's name and {tool} a product name; both are never translated.
_M_CREDIT = N_("Created by {author} and programmed with the support of {tool}")


def credit() -> str:
    """The credit line in the interface language."""
    return _(_M_CREDIT).format(author=AUTHOR, tool=TOOL)
