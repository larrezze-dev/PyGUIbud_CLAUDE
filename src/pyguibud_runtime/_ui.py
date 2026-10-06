"""``UiScope`` and ``LoadedUi``: the object ``load_ui`` returns (spec 2.2, pinned for codegen)."""

from __future__ import annotations

import types
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from pyguibud.i18n import N_
from pyguibud_runtime._texts import check_lang, check_translator
from pyguibud_runtime.errors import UiError

if TYPE_CHECKING:
    from pyguibud.backends.base import Session
    from pyguibud_runtime._texts import Texts, Translator

__all__ = ["LoadedUi", "UiScope"]

_M_DESTROYED = N_("This interface has been destroyed.")
_M_UNKNOWN_WINDOW = N_("'{id}' is not a main or dialog window of this interface.")


class UiScope:
    """One document instance: ``ui.<id>`` for each id, plus ``vars``, ``widgets`` and ``windows``.

    Private state uses ``_`` names only; ids never start with ``_``, so they cannot clash.
    """

    vars: types.SimpleNamespace
    widgets: Mapping[str, object]
    windows: Mapping[str, object]

    def __init__(self) -> None:
        self.vars = types.SimpleNamespace()
        self._widgets: dict[str, object] = {}
        self._windows: dict[str, object] = {}
        self.widgets = types.MappingProxyType(self._widgets)
        self.windows = types.MappingProxyType(self._windows)

    def _attach(self, name: str, obj: object, *, window: bool = False) -> None:
        self._widgets[name] = obj
        if window:
            self._windows[name] = obj
        setattr(self, name, obj)

    def _attach_var(self, name: str, var: object) -> None:
        setattr(self.vars, name, var)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - ``ui.<id>`` is any toolkit object
        # Only reached for names that were never attached; typed Any for ``ui.<id>`` access.
        raise AttributeError(name)


class LoadedUi(UiScope):
    """The interface built by ``load_ui``. Main thread only (Tk rule)."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._path = path
        self._session: Session | None = None
        self._texts: Texts | None = None

    def _live(self) -> tuple[Session, Texts]:
        """The session, or ``runtime.destroyed`` once it (or a window of it) is gone.

        The user may close the main window, or the application destroy ``master``, without
        calling :meth:`destroy`; what is left of the session is then destroyed here.
        """
        session, texts = self._session, self._texts
        if session is not None and texts is not None and session.alive():
            return session, texts
        self.destroy()
        raise UiError("runtime.destroyed", _M_DESTROYED, path=self._path)

    def retranslate(self, lang: str | None = None, *, translator: Translator | None = None) -> None:
        """Re-apply every translatable text of the ``.ui`` files, and redo the mnemonics.

        With no argument the current translators are rebuilt (e.g. after recompiling the
        catalogues); ``lang`` switches the language, ``translator`` uses that object. Text the
        application set itself on these slots is overwritten.

        All-or-nothing: if a translator fails (for example it returns something other than
        ``str``, which raises ``TypeError``), no text changes and the previous translators stay.
        """
        session, texts = self._live()
        check_translator(translator)
        check_lang(lang)
        before = texts.snapshot()
        try:
            if translator is not None:
                texts.rebuild(texts.lang, translator)
            elif lang is not None:
                texts.rebuild(lang, None)
            else:
                texts.rebuild(texts.lang, texts.translator)
            session.apply_texts(texts.text, texts.runtime_text)
        except BaseException:
            texts.restore(before)
            raise

    def show(self, window_id: str) -> str | None:
        """Show the main window or a dialog; a modal dialog returns its button token or None."""
        session, _texts = self._live()
        if window_id not in self._windows:
            raise UiError(
                "runtime.unknown_window", _M_UNKNOWN_WINDOW, path=self._path, id=window_id
            )
        return session.show(window_id)

    def run(self) -> None:
        """Run the main loop (for the case where ``load_ui`` created the root)."""
        self._live()[0].run()

    def destroy(self) -> None:
        """Destroy every window ``load_ui`` created; idempotent."""
        session, self._session, self._texts = self._session, None, None
        if session is not None:
            session.destroy()
