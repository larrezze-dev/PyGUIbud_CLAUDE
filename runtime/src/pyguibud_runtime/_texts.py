"""Translators of the application's ``.ui`` texts (spec 6.1); separate from pyguibud's own state."""

from __future__ import annotations

import gettext
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TypeAlias

from pyguibud.backends.base import TextSlot
from pyguibud.core.errors import format_message
from pyguibud.i18n import (
    LANGUAGE_CODE_RE,
    LOCALE_DIR,
    N_,
    PSEUDO_LANGUAGE,
    PseudoTranslations,
    UnusableCatalogue,
    load_catalogue,
)
from pyguibud.i18n import M_CATALOGUE as _M_CATALOGUE

__all__ = ["DocumentTexts", "Texts", "Translator", "check_lang", "check_translator", "log"]

logger = logging.getLogger("pyguibud_runtime")
# Translators: {value} is the rejected argument as Python shows it; {example} is a language
# code that is never translated.
_M_LANG = N_("lang must be a language code such as '{example}', not {value}")


class Translator(Protocol):
    """What ``load_ui`` needs from a translation; ``gettext.NullTranslations`` fits."""

    def gettext(self, message: str, /) -> str: ...
    def pgettext(self, context: str, message: str, /) -> str: ...


def log(msgid: str, **params: object) -> None:
    """Log a runtime warning in the current pyguibud language."""
    logger.warning("%s", format_message(msgid, params))


def check_lang(lang: str | None) -> str | None:
    """Reject anything but a language code (blocks path traversal through ``languages=``)."""
    if lang is not None and (not isinstance(lang, str) or not LANGUAGE_CODE_RE.fullmatch(lang)):
        raise ValueError(format_message(_M_LANG, {"value": repr(lang), "example": "de_DE"}))
    return lang


def check_translator(translator: object) -> None:
    """Reject a ``translator`` without callable ``gettext`` and ``pgettext`` (API misuse)."""
    if translator is not None and not all(
        callable(getattr(translator, name, None)) for name in ("gettext", "pgettext")
    ):
        raise TypeError(
            f"translator must have gettext() and pgettext(), not {type(translator).__name__}"
        )


#: Everything ``Texts.rebuild`` replaces: lang, translator, code, per-document and runtime ones.
Snapshot: TypeAlias = tuple[
    str | None, Translator | None, str | None, dict[str, Translator], Translator
]


@dataclass(frozen=True, slots=True)
class DocumentTexts:
    """Where the translations of one ``.ui`` file live."""

    domain: str
    directory: Path
    source_locale: str


class Texts:
    """Per-document translators plus the runtime's own (dialog button) catalogue."""

    def __init__(
        self, documents: dict[str, DocumentTexts], lang: str | None, translator: Translator | None
    ) -> None:
        self._documents = documents
        self.lang = lang
        self.translator = translator
        self._by_doc: dict[str, Translator] = {}
        self._runtime: Translator = gettext.NullTranslations()
        self._code: str | None = None
        self.rebuild(lang, translator)

    def rebuild(self, lang: str | None, translator: Translator | None) -> None:
        """Build the translators for ``lang`` (or use ``translator`` for every document)."""
        self.lang, self.translator = lang, translator
        # gettext folders use underscores: a BCP 47 tag such as "de-DE" means de_DE.
        self._code = lang.replace("-", "_") if lang else None
        cache: dict[tuple[str, Path], Translator] = {}
        self._by_doc = {
            key: translator or self._load(cache, doc) for key, doc in self._documents.items()
        }
        if self._code == PSEUDO_LANGUAGE:
            self._runtime = PseudoTranslations()
        else:
            # A damaged pyguibud .mo shows the English button labels, never an error (QA-18-01).
            self._runtime = load_catalogue("pyguibud", LOCALE_DIR, self._code)
            if isinstance(self._runtime, UnusableCatalogue):
                log(_M_CATALOGUE, **self._runtime.params)

    def snapshot(self) -> Snapshot:
        """The current translators, so that a failed ``retranslate`` can put them back."""
        return self.lang, self.translator, self._code, self._by_doc, self._runtime

    def restore(self, state: Snapshot) -> None:
        """Put back the translators of :meth:`snapshot`."""
        self.lang, self.translator, self._code, self._by_doc, self._runtime = state

    def _load(self, cache: dict[tuple[str, Path], Translator], doc: DocumentTexts) -> Translator:
        lang = self._code
        if lang == PSEUDO_LANGUAGE:
            return PseudoTranslations()
        if not doc.domain:
            return gettext.NullTranslations()
        found = cache.get((doc.domain, doc.directory))
        if found is not None:
            return found
        # Read the .mo files directly: gettext.translation() caches them for the whole process,
        # so retranslate() could never pick up recompiled catalogues.
        paths = gettext.find(doc.domain, doc.directory, [lang] if lang else None, all=True)
        result, corrupt = gettext.NullTranslations(), False
        try:
            for path in reversed(paths):
                with open(path, "rb") as stream:
                    loaded = gettext.GNUTranslations(stream)
                loaded.add_fallback(result)
                result = loaded
        except Exception:  # a corrupt .mo file must not stop the interface
            result, corrupt = gettext.NullTranslations(), True
        source = doc.source_locale.split("_")[0].lower()
        foreign = bool(lang) and str(lang).split("_")[0].lower() != source
        if corrupt or (not paths and foreign):
            log(_M_CATALOGUE, domain=doc.domain, lang=self.lang, directory=str(doc.directory))
        cache[(doc.domain, doc.directory)] = result
        return result

    def text(self, slot: TextSlot) -> str:
        """The display text of a slot (an empty value never reaches gettext)."""
        prop = slot.prop
        if not prop.translatable or not prop.value:
            return prop.value
        translator = self._by_doc[slot.document]
        if prop.name == "columns" and isinstance(translator, PseudoTranslations):
            # Headings are shown one by one: pseudo-localise each, not the joined text (QA-17b-05).
            return ";".join(translator.gettext(heading) for heading in prop.value.split(";"))
        if prop.context:
            result = translator.pgettext(prop.context, prop.value)
        else:
            result = translator.gettext(prop.value)
        if not isinstance(result, str):  # an application translator, not a gettext catalogue
            raise TypeError(
                f"the translator returned {type(result).__name__}, not str, for {prop.value[:40]!r}"
            )
        return result

    def runtime_text(self, msgid: str) -> str:
        """A runtime-owned msgid (dialog button labels) in the application's language."""
        return self._runtime.gettext(msgid)
