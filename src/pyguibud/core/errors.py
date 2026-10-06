"""Domain exceptions of the PyGUIbud core.

Every exception carries a machine ``code`` and a translatable ``msgid``; the human-readable
message is produced lazily, in the language active when it is read, so an error raised before a
language switch still displays in the new language.
"""

from __future__ import annotations

from collections.abc import Mapping

from pyguibud.i18n import _, ngettext, plural_of

__all__ = ["ModelError", "PyGUIbudError", "RegistryError", "XmlIoError", "format_message"]

# A broken translation (wrong or missing placeholder, stray brace) must never turn an error
# report into a second error.
_FORMAT_ERRORS = (KeyError, IndexError, ValueError, AttributeError, TypeError)


def format_message(msgid: str, params: Mapping[str, object]) -> str:
    """Translate ``msgid`` and fill its named placeholders. Never raises.

    Falls back to the untranslated msgid when the translation is broken, and to the raw msgid
    when even that cannot be formatted.
    """
    plural = _plural(msgid, params)
    try:
        translated = _(msgid) if plural is None else ngettext(msgid, plural[0], plural[1])
        return translated.format(**params)
    except _FORMAT_ERRORS:
        pass
    source = msgid if plural is None or plural[1] == 1 else plural[0]
    try:
        return source.format(**params)
    except _FORMAT_ERRORS:
        return source


def _plural(msgid: str, params: Mapping[str, object]) -> tuple[str, int] | None:
    """The plural msgid and ``params["count"]`` of an ``NP_`` msgid, or None."""
    plural = plural_of(msgid)
    count = params.get("count")
    if plural is None or not isinstance(count, int) or isinstance(count, bool):
        return None
    return plural, count


class PyGUIbudError(Exception):
    """Base class of every PyGUIbud domain error.

    Args:
        code: dotted, lower-case machine code, e.g. ``"registry.load_failed"``.
        message: msgid marked with ``N_()`` at the call site, using named placeholders.
        **params: values for the placeholders.
    """

    def __init__(self, code: str, message: str, /, **params: object) -> None:
        super().__init__(code, message)
        self.code = code
        self.msgid = message
        self.params: dict[str, object] = dict(params)

    @property
    def message(self) -> str:
        """The message translated into the current language."""
        return format_message(self.msgid, self.params)

    def __str__(self) -> str:
        return self.message


class ModelError(PyGUIbudError):
    """Invalid operation on the document model."""


class RegistryError(PyGUIbudError):
    """Widget or backend registry failure."""


def _format_location(source: str, line: int | None, column: int | None) -> str:
    """Return ``source:line:column``; the line and column parts are omitted when None."""
    location = source
    if line is not None:
        location += f":{line}"
        if column is not None:
            location += f":{column}"
    return location


class XmlIoError(PyGUIbudError):
    """A ``.ui`` file could not be read or written.

    ``source``, ``line`` and ``column`` locate the problem; they are reserved names, so msgids
    must not use them as placeholders.
    """

    def __init__(
        self,
        code: str,
        message: str,
        /,
        *,
        source: str = "",
        line: int | None = None,
        column: int | None = None,
        **params: object,
    ) -> None:
        super().__init__(code, message, **params)
        self.source = source
        self.line = line
        self.column = column

    @property
    def location(self) -> str:
        """``source:line:column`` (parts omitted when unknown)."""
        return _format_location(self.source, self.line, self.column)

    def __str__(self) -> str:
        location = self.location
        return f"{location}: {self.message}" if location else self.message
