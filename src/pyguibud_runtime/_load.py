"""``load_ui``: the fail-fast pipeline of spec section 3 (no Tk object before all checks pass)."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from pyguibud.backends import load_backend
from pyguibud.backends.base import (
    BuildPlan,
    DocumentPlan,
    Instance,
    NoDisplayError,
    RootExistsError,
    Session,
)
from pyguibud.core.errors import XmlIoError
from pyguibud.core.files import DiskFiles
from pyguibud.core.model import Action, Document, Include, Widget, Window
from pyguibud.core.registry import default_registry
from pyguibud.core.validate import validate
from pyguibud.core.xml_io import read_ui
from pyguibud.i18n import N_, NP_
from pyguibud_runtime._texts import (
    DocumentTexts,
    Texts,
    Translator,
    check_lang,
    check_translator,
    log,
    logger,
)
from pyguibud_runtime._ui import LoadedUi, UiScope
from pyguibud_runtime.errors import UiError

__all__ = ["load_ui"]

Handler = Callable[[], object]

_M_UNREADABLE = N_("The .ui file '{path}' cannot be loaded: {reason}")
# Translators: {count} is the number of validation errors, {path} the .ui file name.
_M_INVALID = NP_(
    "{count} error prevents loading '{path}'.", "{count} errors prevent loading '{path}'."
)
# Translators: {argument} is the name of a Python argument ("master="); keep it unchanged.
_M_NO_MAIN = N_("'{path}' has no main window; pass {argument} to load its dialogs.")
_M_ONLY_COMPONENTS = N_("'{path}' contains only components; include them from another .ui file.")
# Translators: {target} is the handlers object (its type name), {names} a comma-separated list.
_M_MISSING = NP_(
    "{count} handler is missing or not callable on {target}: {names}.",
    "{count} handlers are missing or not callable on {target}: {names}.",
)
_M_HANDLER = N_("The handler '{name}' is missing or not callable on {target}; it is not bound.")
_M_BACKEND = N_("The backend '{name}' is not available: {reason}")
# Translators: {argument} is the name of a Python argument ("master="); keep it unchanged.
_M_ROOT = N_(
    "A Tk root window already exists; pass it as {argument} to load another .ui file into it."
)
_M_DISPLAY = N_("No display is available, so no window can be opened: {reason}")
_M_BUILD = N_("Building the interface from '{path}' failed: {reason}")


def load_ui(
    path: str | os.PathLike[str],
    handlers: object | Mapping[str, Handler] | None = None,
    *,
    strict: bool = True,
    backend: str = "ttkbootstrap",
    master: object | None = None,
    lang: str | None = None,
    localedir: str | os.PathLike[str] | None = None,
    translator: Translator | None = None,
) -> LoadedUi:
    """Validate a ``.ui`` file and build it with ``backend``; main thread only.

    Handlers are looked up by name on ``handlers`` (attribute or mapping key) and called with no
    arguments. ``strict`` makes any missing handler an error listing all of them.

    Raises:
        TypeError, ValueError: API misuse (wrong argument types, a malformed ``lang``).
        UiError: the file, its includes, the handlers or the environment prevent loading.
    """
    ui, plan = _prepare(
        path,
        handlers,
        strict=strict,
        backend=backend,
        master=master,
        lang=lang,
        localedir=localedir,
        translator=translator,
    )
    shown = plan.path
    # P8-P9: backend (imports the toolkit; checks master and an existing root)
    try:
        chosen = load_backend(backend, plan.registry)()
        chosen.prepare(master)
    except RootExistsError as exc:
        raise UiError("runtime.root_exists", _M_ROOT, path=shown, argument="master=") from exc
    except Exception as exc:
        raise UiError(
            "runtime.backend_unavailable", _M_BACKEND, path=shown, name=backend, reason=_reason(exc)
        ) from exc
    try:
        session: Session = chosen.build(plan, master)
    except NoDisplayError as exc:
        raise UiError("runtime.no_display", _M_DISPLAY, path=shown, reason=_reason(exc)) from exc
    except Exception as exc:
        raise UiError("runtime.build_failed", _M_BUILD, path=shown, reason=_reason(exc)) from exc
    ui._session = session
    return ui


def _prepare(
    path: str | os.PathLike[str],
    handlers: object | Mapping[str, Handler] | None,
    *,
    strict: bool,
    backend: str = "ttkbootstrap",
    master: object | None = None,
    lang: str | None = None,
    localedir: str | os.PathLike[str] | None = None,
    translator: Translator | None = None,
) -> tuple[LoadedUi, BuildPlan]:
    """P1-P7 of ``load_ui``: every check, and the toolkit-free plan (no Tk object yet).

    The ``LoadedUi`` already holds its translators; ``load_ui`` adds the session. Private: the
    parity tests build the same plan in embed mode (spec dnd-selection 4).
    """
    # P1: arguments
    for name, value, kinds in (
        ("path", path, (str, os.PathLike)),
        ("strict", strict, (bool,)),
        ("backend", backend, (str,)),
        ("localedir", localedir, (str, os.PathLike, type(None))),
    ):
        if not isinstance(value, kinds):
            raise TypeError(f"{name} has the wrong type: {type(value).__name__}")
    check_lang(lang)
    check_translator(translator)
    shown = os.fspath(path)
    if not isinstance(shown, str):
        raise TypeError("path must be a text path")
    # P2-P3: read, validate the file with its includes and images
    try:
        result = read_ui(shown)
    except XmlIoError as exc:
        raise UiError("runtime.unreadable", _M_UNREADABLE, path=shown, reason=str(exc)) from exc
    registry = default_registry()
    files = DiskFiles(shown, result)
    report = validate(
        result.document, registry, source=result.source, positions=result.positions, files=files
    )
    for warning in report.warnings:
        logger.warning("%s", warning)
    errors = report.errors
    if errors:
        raise UiError(
            "runtime.invalid_document", _M_INVALID, path=shown, count=len(errors), findings=errors
        )
    # P4: something to show
    document = result.document
    windows = document.children
    mains = tuple(w for w in windows if w.kind == "main")
    dialogs = tuple(w for w in windows if w.kind == "dialog")
    if not mains and (master is None or not dialogs):
        if windows and all(w.kind == "component" for w in windows):
            raise UiError("runtime.nothing_to_load", _M_ONLY_COMPONENTS, path=shown)
        raise UiError("runtime.no_main_window", _M_NO_MAIN, path=shown, argument="master=")
    # P5: instance plan, expanded from the validated (cached) files
    ui = LoadedUi(shown)
    docs: dict[str, DocumentPlan] = {}
    top = _expand(files, files.root, document, mains + dialogs, ui, None, docs)
    # P6: handlers
    names = sorted(_handler_names(top))
    resolved = {name: fn for name in names if (fn := _resolve(handlers, name)) is not None}
    missing = tuple(name for name in names if name not in resolved)
    target = type(handlers).__name__
    if missing and strict:
        raise UiError(
            "runtime.missing_handlers",
            _M_MISSING,
            path=shown,
            names=missing,
            count=len(missing),
            target=target,
        )
    for name in missing:
        log(_M_HANDLER, name=name, target=target)
    # P7: translators
    texts = Texts(
        {
            key: DocumentTexts(
                plan.document.meta.i18n_domain,
                Path(localedir) if localedir is not None else plan.path.parent / "locale",
                plan.document.meta.source_locale,
            )
            for key, plan in docs.items()
        },
        lang,
        translator,
    )
    images = {
        (key, image.id): Path(files.path_of(files.resolve(key, image.src)))
        for key, plan in docs.items()
        for image in plan.document.resources.values()
    }
    plan = BuildPlan(
        path=shown,
        top=top,
        handlers=resolved,
        images=images,
        registry=registry,
        theme=document.meta.theme,
        text=texts.text,
        runtime_text=texts.runtime_text,
        log=log,
    )
    ui._texts = texts
    return ui, plan


def _reason(exc: BaseException) -> str:
    """The text of ``exc``, or its type name when it has none (e.g. a bare ``TclError()``)."""
    return str(exc) or type(exc).__name__


def _expand(
    files: DiskFiles,
    key: str,
    document: Document,
    windows: tuple[Window, ...],
    scope: UiScope,
    host: Instance | None,
    docs: dict[str, DocumentPlan],
) -> Instance:
    """Build the instance tree; bounded by the include limits the validator enforced (R53)."""
    plan = docs.setdefault(key, DocumentPlan(key, Path(files.path_of(key)), document))
    instance = Instance(plan, windows, scope, host)
    for window in windows:
        for node in window.walk():
            if isinstance(node, Include):
                target = files.resolve(key, node.src)
                included = files.read(target).document
                component = next(w for w in included.children if w.id == node.component)
                shares = instance if target == key else None
                child = _expand(files, target, included, (component,), UiScope(), shares, docs)
                instance.includes[id(node)] = child
    return instance


def _handler_names(instance: Instance) -> set[str]:
    names: set[str] = set()
    for window in instance.windows:
        nodes = list(window.walk())
        if window.kind != "component" and window.menubar is not None:
            nodes.extend(window.menubar.walk())
        for node in nodes:
            if isinstance(node, Widget):
                names.update(event.handler for event in node.events)
            elif isinstance(node, Action) and node.handler:
                names.add(node.handler)
    for child in instance.includes.values():
        names |= _handler_names(child)
    return names


def _resolve(handlers: object, name: str) -> Handler | None:
    if handlers is None:
        return None
    try:
        if isinstance(handlers, Mapping):
            found = handlers.get(name)
        else:
            found = getattr(handlers, name, None)
    except Exception:  # a raising property counts as missing
        return None
    return found if callable(found) else None
