"""``UiError``: every failure of ``load_ui`` that is not API misuse (spec 2.4)."""

from __future__ import annotations

from pyguibud.core.diagnostics import Finding
from pyguibud.core.errors import PyGUIbudError, format_message
from pyguibud.core.text import printable
from pyguibud.i18n import NP_

__all__ = ["UiError"]

_SHOWN = 20
# Translators: closes a list of problems that was cut after 20 lines.
_MORE = NP_("… and {count} more problem.", "… and {count} more problems.")


class UiError(PyGUIbudError):
    """A ``.ui`` file, its environment or the handlers prevent building the interface.

    ``path`` is the ``.ui`` file, ``findings`` the validator errors and ``names`` the missing
    handler names, when they apply.
    """

    def __init__(
        self,
        code: str,
        message: str,
        /,
        *,
        path: str = "",
        findings: tuple[Finding, ...] = (),
        names: tuple[str, ...] = (),
        **params: object,
    ) -> None:
        super().__init__(code, message, path=path, **params)
        if names:
            self.params.setdefault("names", ", ".join(names))
        self.path = path
        self.findings = findings
        self.names = names

    def __str__(self) -> str:
        lines = [printable(self.message), *(str(finding) for finding in self.findings[:_SHOWN])]
        hidden = len(self.findings) - _SHOWN
        if hidden > 0:
            lines.append(format_message(_MORE, {"count": hidden}))
        return "\n".join(lines)
