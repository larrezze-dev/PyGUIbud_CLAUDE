"""The unsaved-changes question: Save / Don't save / Cancel (Tk; spec 14a section 10)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyguibud.designer.dialogs.message import ChoiceDialog
from pyguibud.i18n import N_, _

__all__ = ["save_changes_dialog"]

# Translators: {name} is a file name such as "main.ui", or "Untitled".
_M_QUESTION = N_("Save the changes to '{name}' before closing?")
# Translators: the buttons of the unsaved-changes question; _ marks the access key.
_M_SAVE = N_("_Save")
_M_DONT_SAVE = N_("_Don't save")
_M_CANCEL = N_("_Cancel")


def save_changes_dialog(
    root: Any,  # noqa: ANN401 - the app root
    name: Callable[[], str],
    *,
    save: Callable[[], object],
    discard: Callable[[], object],
) -> ChoiceDialog:
    """Save is the default (Enter); Cancel and Esc change nothing."""
    return ChoiceDialog(
        root,
        lambda: _(_M_QUESTION).format(name=name()),
        [(_M_SAVE, save), (_M_DONT_SAVE, discard), (_M_CANCEL, None)],
    )
