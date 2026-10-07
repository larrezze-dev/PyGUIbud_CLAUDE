"""Built-in document templates (``.ui`` package data) for "New from template".

Pure: the manifest only names the files; they are read with :mod:`importlib.resources`.
Templates are the user's content, so their texts are not localised by the designer.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources

from pyguibud.i18n import N_

__all__ = ["TEMPLATES", "TemplateInfo", "template_bytes", "template_info"]


@dataclass(frozen=True, slots=True)
class TemplateInfo:
    """One template: its id, file name and the msgids of its title and description."""

    id: str
    file: str
    title: str
    description: str


TEMPLATES: tuple[TemplateInfo, ...] = (
    TemplateInfo(
        id="main_window",
        file="main_window.ui",
        title=N_("Main window"),
        description=N_("An application window with a File menu and a status bar."),
    ),
    TemplateInfo(
        id="dialog",
        file="dialog.ui",
        title=N_("Dialog"),
        description=N_("A modal dialog with OK and Cancel buttons."),
    ),
    TemplateInfo(
        id="login_form",
        file="login_form.ui",
        title=N_("Login form"),
        description=N_("A user name and password form with a sign-in button."),
    ),
    TemplateInfo(
        id="settings",
        file="settings.ui",
        title=N_("Settings"),
        description=N_("A window with a tabbed notebook for settings pages."),
    ),
    TemplateInfo(
        id="empty_component",
        file="empty_component.ui",
        title=N_("Empty component"),
        description=N_("A reusable component with an empty grid layout."),
    ),
)


def template_info(template_id: str) -> TemplateInfo | None:
    """The manifest entry called ``template_id``, or None."""
    return next((info for info in TEMPLATES if info.id == template_id), None)


def template_bytes(info: TemplateInfo) -> bytes:
    """The raw bytes of a template file."""
    return resources.files(__package__).joinpath(info.file).read_bytes()
