"""Internationalisation infrastructure (stdlib only).

Looks up the *current* gettext translation on every call, so the language can be switched at
runtime. ``gettext.install()`` and builtins are deliberately not used.

Designer wiring (Step 12): widgets keep their *msgids* (never the translated text) and expose a
``retranslate()`` method that re-applies ``_()`` to every label. Each panel registers a bound
method (taking the new code) with :func:`add_language_listener`; bound methods are held weakly,
so destroyed Tk widgets drop out silently. Tk calls must stay on the main thread: call
:func:`set_language` from the main thread only.
"""

from __future__ import annotations

import contextlib
import gettext as _gettext_module
import inspect
import locale
import logging
import math
import os
import re
import weakref
from collections.abc import Callable, Iterator
from pathlib import Path

__all__ = [
    "DOMAIN",
    "LANGUAGES",
    "LANGUAGE_CODE_RE",
    "LOCALE_DIR",
    "NP_",
    "N_",
    "PSEUDO_LANGUAGE",
    "SOURCE_LANGUAGE",
    "PseudoTranslations",
    "_",
    "add_language_listener",
    "detect_language",
    "get_language",
    "gettext",
    "language_listener",
    "ngettext",
    "normalise_language",
    "pgettext",
    "plural_of",
    "remove_language_listener",
    "set_language",
]

_log = logging.getLogger(__name__)

DOMAIN = "pyguibud"
LOCALE_DIR = Path(__file__).parent / "locale"
SOURCE_LANGUAGE = "en_GB"
PSEUDO_LANGUAGE = "en_XA"
#: The grammar of a language code (``en_GB``, ``pt-BR``, ``de``): the validator's R81, the
#: ``--lang`` options and the runtime's ``lang`` check. The support code of generated modules
#: keeps a copy (a test keeps the copies in step).
LANGUAGE_CODE_RE = re.compile(r"[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})*")

# Native autonyms; order is the display order. The pseudo-locale is intentionally absent.
LANGUAGES: dict[str, str] = {
    "en_GB": "English (United Kingdom)",
    "es_ES": "Español (España)",
    "pt_PT": "Português (Portugal)",
    "pt_BR": "Português (Brasil)",
    "de_DE": "Deutsch (Deutschland)",
    "it_IT": "Italiano (Italia)",
    "nl_NL": "Nederlands (Nederland)",
    "fr_FR": "Français (France)",
}

# Windows locale names (as returned by locale.getlocale()) and bare languages.
_WINDOWS_NAMES: dict[str, str] = {
    "english_united kingdom": "en_GB",
    "english": "en_GB",
    "spanish_spain": "es_ES",
    "spanish": "es_ES",
    "portuguese_portugal": "pt_PT",
    "portuguese_brazil": "pt_BR",
    "portuguese": "pt_PT",
    "german_germany": "de_DE",
    "german": "de_DE",
    "italian_italy": "it_IT",
    "italian": "it_IT",
    "dutch_netherlands": "nl_NL",
    "dutch": "nl_NL",
    "french_france": "fr_FR",
    "french": "fr_FR",
}
_BARE: dict[str, str] = {}
for _code in LANGUAGES:
    _BARE.setdefault(_code.split("_")[0], _code)
_BY_LOWER = {c.lower(): c for c in (*LANGUAGES, PSEUDO_LANGUAGE)}


def normalise_language(code: str | None) -> str | None:
    """Map a locale-like string to a supported code, or return None. Never raises."""
    try:
        if not code:
            return None
        text = code.strip().split(".")[0].split("@")[0].replace("-", "_").lower()
        if not text:
            return None
        if text in _BY_LOWER:
            return _BY_LOWER[text]
        if text in _WINDOWS_NAMES:
            return _WINDOWS_NAMES[text]
        lang = text.split("_")[0]
        return _BARE.get(lang) or _WINDOWS_NAMES.get(lang)
    except Exception:  # contract: never raise
        return None


def detect_language() -> str:
    """Detect the preferred language from the environment; falls back to en_GB."""
    try:
        candidates: list[str] = []
        candidates.append(os.environ.get("PYGUIBUD_LANG", ""))
        candidates.extend(os.environ.get("LANGUAGE", "").split(":"))
        for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
            candidates.append(os.environ.get(var, ""))
        with contextlib.suppress(ValueError, TypeError, OSError):
            candidates.append(locale.getlocale()[0] or "")
        for candidate in candidates:
            found = normalise_language(candidate)
            if found:
                return found
    except Exception:  # contract: never raise
        _log.debug("Language detection failed", exc_info=True)
    return SOURCE_LANGUAGE


# ---------------------------------------------------------------- pseudo-locale
_ACCENTS = str.maketrans(
    {
        "a": "á",
        "e": "é",
        "i": "í",
        "o": "ó",
        "u": "ú",
        "n": "ñ",
        "c": "ç",
        "y": "ý",
        "A": "Á",
        "E": "É",
        "I": "Í",
        "O": "Ó",
        "U": "Ú",
        "N": "Ñ",
        "C": "Ç",
        "Y": "Ý",
    }
)
# Tokens that must survive untouched: {{ }}, {name}, {0}, %(name)s, %s, %d, %%.
_PRINTF = r"[#0\- +]*\d*(?:\.\d+)?[a-zA-Z]"
_PROTECTED = re.compile(rf"\{{\{{|\}}\}}|\{{[^{{}}]*\}}|%%|%\([^)]*\){_PRINTF}|%{_PRINTF}")


def _pseudo(message: str) -> str:
    if not message:
        return message
    out: list[str] = []
    pos = 0
    for match in _PROTECTED.finditer(message):
        out.append(message[pos : match.start()].translate(_ACCENTS))
        out.append(match.group())
        pos = match.end()
    out.append(message[pos:].translate(_ACCENTS))
    pad = math.ceil(len(message) * 0.4)
    return "[" + "".join(out) + " " + "·" * pad + "]"


class PseudoTranslations(_gettext_module.NullTranslations):
    """Pseudo-locale (en_XA): accented, bracketed, ~40 % longer, Latin-1 only."""

    def gettext(self, message: str) -> str:
        return _pseudo(message)

    def ngettext(self, msgid1: str, msgid2: str, n: int) -> str:
        return _pseudo(msgid1 if n == 1 else msgid2)

    def pgettext(self, context: str, message: str) -> str:
        return _pseudo(message)

    def npgettext(self, context: str, msgid1: str, msgid2: str, n: int) -> str:
        return _pseudo(msgid1 if n == 1 else msgid2)


# ---------------------------------------------------------------- state
_translation: _gettext_module.NullTranslations = _gettext_module.NullTranslations()
_language: str = SOURCE_LANGUAGE
# Each entry resolves to its callback, or None once a weakly held bound method is collected.
_listeners: list[Callable[[], Callable[[str], None] | None]] = []


def get_language() -> str:
    """Return the active language code."""
    return _language


def set_language(code: str, *, force: bool = False) -> str:
    """Activate a language and notify listeners.

    The translation is always (re)installed, which is cheap. Listeners are notified only when
    the language code actually changes, or when ``force`` is true (e.g. after reloading
    catalogues).

    Raises:
        ValueError: if the code is not a supported language.
    """
    resolved = normalise_language(code)
    if resolved is None:
        raise ValueError(
            gettext("Unknown language '{code}'. Valid codes: {valid}.").format(
                code=code, valid=", ".join((*LANGUAGES, PSEUDO_LANGUAGE))
            )
        )
    global _translation, _language
    changed = resolved != _language
    if resolved == PSEUDO_LANGUAGE:
        _translation = PseudoTranslations()
    else:
        _translation = _gettext_module.translation(
            DOMAIN, localedir=str(LOCALE_DIR), languages=[resolved], fallback=True
        )
    _language = resolved
    if changed or force:
        # Snapshot so listeners may add or remove listeners while being notified.
        for listener in _live_listeners():
            try:
                listener(resolved)
            except Exception:
                _log.exception("Language listener %r failed", listener)
    return resolved


def _live_listeners() -> list[Callable[[str], None]]:
    """Return live callbacks in registration order, pruning dead weak references."""
    live: list[Callable[[str], None]] = []
    alive: list[Callable[[], Callable[[str], None] | None]] = []
    for getter in _listeners:
        callback = getter()
        if callback is not None:
            live.append(callback)
            alive.append(getter)
    if len(alive) != len(_listeners):
        _listeners[:] = alive
    return live


def add_language_listener(callback: Callable[[str], None]) -> None:
    """Register a callback invoked with the new code after each language change.

    Bound methods are held *weakly* (``weakref.WeakMethod``) so a destroyed widget never keeps
    its listener alive or gets called; plain functions, lambdas and other callables are held
    strongly. Registering an already registered callback is a no-op.
    """
    if callback in _live_listeners():
        return
    if inspect.ismethod(callback):
        _listeners.append(weakref.WeakMethod(callback))
    else:
        _listeners.append(lambda: callback)


def remove_language_listener(callback: Callable[[str], None]) -> None:
    """Unregister a callback; unknown callbacks are ignored."""
    for getter in list(_listeners):
        if getter() == callback:
            _listeners.remove(getter)
            return


@contextlib.contextmanager
def language_listener(callback: Callable[[str], None]) -> Iterator[None]:
    """Register ``callback`` for the duration of a ``with`` block."""
    add_language_listener(callback)
    try:
        yield
    finally:
        remove_language_listener(callback)


def gettext(message: str) -> str:
    """Translate ``message`` with the current language."""
    return _translation.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    """Translate a plural form with the current language."""
    return _translation.ngettext(singular, plural, n)


def pgettext(context: str, message: str) -> str:
    """Translate ``message`` disambiguated by ``context``."""
    return _translation.pgettext(context, message)


_ = gettext


def N_(message: str) -> str:  # noqa: N802 - conventional gettext marker name
    """Mark ``message`` for extraction without translating it (translate later with ``_()``).

    Use it for msgids stored at import time, such as widget display names, which must be
    translated only when read so that a runtime language switch takes effect.
    """
    return message


# Singular msgid -> plural msgid, filled by ``NP_`` at import time of the defining module.
_plurals: dict[str, str] = {}


def NP_(singular: str, plural: str) -> str:  # noqa: N802 - conventional gettext marker name
    """Mark a plural message for extraction (keyword ``NP_:1,2``) and return the singular.

    The singular is the msgid to store; :func:`plural_of` finds the plural again, so a deferred
    message (for example a validator finding) can be translated with :func:`ngettext` when it is
    read. By convention the number that selects the form is the placeholder ``{count}``.
    """
    _plurals[singular] = plural
    return singular


def plural_of(singular: str) -> str | None:
    """Return the plural msgid registered with :func:`NP_` for ``singular``, or None."""
    return _plurals.get(singular)
