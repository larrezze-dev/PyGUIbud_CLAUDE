"""Entry-point registry of widget specifications and backends (ADR-004).

Plugins are a trust boundary: loading one runs its code. Every failure while loading a widget
entry point is isolated into a :class:`Diagnostic` so that a broken plugin never prevents the
designer from starting. Backends are only *listed* during :meth:`Registry.load`, because loading
one imports a GUI toolkit; :meth:`Registry.load_backend` loads them on demand.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata
import traceback
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, Protocol

from pyguibud.core.errors import ModelError, RegistryError, format_message
from pyguibud.core.model import (
    CORE_CLASS_NAMES,
    WIDGET_API_VERSION,
    WidgetSpec,
    is_extension,
    split_class_name,
)
from pyguibud.i18n import N_

__all__ = [
    "BACKENDS_GROUP",
    "WIDGETS_GROUP",
    "WIDGET_API_VERSION",
    "BackendInfo",
    "Diagnostic",
    "EntryPointLike",
    "EntryPointSource",
    "Registry",
    "Resolved",
    "default_registry",
    "reset_default_registry",
]

WIDGETS_GROUP: Final = "pyguibud.widgets"
BACKENDS_GROUP: Final = "pyguibud.backends"

_BUILTIN_PREFIX = "pyguibud.core.widgets:"
_UNKNOWN_DISTRIBUTION = "unknown"


class _DistributionLike(Protocol):
    @property
    def name(self) -> str: ...


class EntryPointLike(Protocol):
    """The subset of :class:`importlib.metadata.EntryPoint` the registry uses."""

    @property
    def name(self) -> str: ...

    @property
    def value(self) -> str: ...

    @property
    def group(self) -> str: ...

    @property
    def dist(self) -> _DistributionLike | None: ...

    def load(self) -> object: ...


EntryPointSource = Callable[[str], Iterable[EntryPointLike]]


def _metadata_entry_points(group: str) -> Iterable[EntryPointLike]:
    return importlib.metadata.entry_points(group=group)


@dataclass(frozen=True, slots=True, kw_only=True)
class Diagnostic:
    """A problem found while loading plugins; ``message`` is translated on read."""

    group: str
    entry_point: str
    distribution: str
    code: str
    msgid: str
    params: Mapping[str, str] = field(default_factory=dict, hash=False)
    severity: Literal["error", "warning"] = "error"
    exception: str | None = None
    traceback: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))

    @property
    def message(self) -> str:
        """The message in the current language. Never raises."""
        return format_message(self.msgid, self.params)


@dataclass(frozen=True, slots=True, kw_only=True)
class Resolved:
    """Result of :meth:`Registry.resolve`: the spec to render for a requested class."""

    spec: WidgetSpec
    requested: str
    is_fallback: bool
    code: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class BackendInfo:
    """A backend entry point, listed but not loaded."""

    name: str
    value: str
    distribution: str


def _distribution(ep: EntryPointLike) -> str:
    dist = ep.dist
    return dist.name if dist is not None else _UNKNOWN_DISTRIBUTION


def _is_builtin(ep: EntryPointLike) -> bool:
    return ep.value.startswith(_BUILTIN_PREFIX)


class Registry:
    """Widget specifications and backends discovered through entry points.

    The constructor does no I/O; the first lookup calls :meth:`load` once.
    """

    def __init__(self, entry_points: EntryPointSource | None = None) -> None:
        self._source: EntryPointSource = entry_points or _metadata_entry_points
        self._loaded = False
        self._specs: dict[str, WidgetSpec] = {}
        # Entry point each spec came from; None for core specs added by the safety net.
        self._origins: dict[str, EntryPointLike | None] = {}
        self._diagnostics: list[Diagnostic] = []
        self._backend_eps: dict[str, EntryPointLike] = {}
        self._backends: list[BackendInfo] = []
        self._backend_cache: dict[str, object] = {}

    # ------------------------------------------------------------ loading
    def load(self) -> None:
        """(Re)discover every widget spec and backend. Never raises (except BaseException)."""
        self._specs.clear()
        self._origins.clear()
        self._diagnostics.clear()
        self._backend_eps.clear()
        self._backends.clear()
        self._backend_cache.clear()
        self._loaded = True
        for ep in self._sorted(WIDGETS_GROUP):
            self._load_widget_entry_point(ep)
        self._ensure_core()
        self._check_extensions()
        for ep in self._sorted(BACKENDS_GROUP):
            name = ep.name
            if name in self._backend_eps:
                self._diagnose(
                    ep,
                    "registry.duplicate",
                    N_("The backend '{name}' from '{distribution}' is already registered."),
                    severity="warning",
                    name=name,
                )
                continue
            self._backend_eps[name] = ep
            self._backends.append(
                BackendInfo(name=name, value=ep.value, distribution=_distribution(ep))
            )

    def _sorted(self, group: str) -> list[EntryPointLike]:
        """Entry points of ``group``: the built-in first, then by (distribution, name)."""
        try:
            eps = list(self._source(group))
        except Exception as exc:  # isolation point: broken metadata must not stop loading
            self._diagnostics.append(
                Diagnostic(
                    group=group,
                    entry_point="",
                    distribution=_UNKNOWN_DISTRIBUTION,
                    code="registry.load_failed",
                    msgid=N_("The entry points of group '{group}' could not be read: {error}"),
                    params={"group": group, "error": repr(exc)},
                    exception=repr(exc),
                    traceback=traceback.format_exc(),
                )
            )
            return []
        return sorted(eps, key=lambda ep: (not _is_builtin(ep), _distribution(ep), ep.name))

    def _diagnose(
        self,
        ep: EntryPointLike,
        code: str,
        msgid: str,
        *,
        severity: Literal["error", "warning"] = "error",
        exc: BaseException | None = None,
        **params: object,
    ) -> None:
        distribution = _distribution(ep)
        values = {"entry_point": ep.name, "distribution": distribution}
        values.update({key: str(value) for key, value in params.items()})
        self._diagnostics.append(
            Diagnostic(
                group=ep.group,
                entry_point=ep.name,
                distribution=distribution,
                code=code,
                msgid=msgid,
                params=values,
                severity=severity,
                exception=repr(exc) if exc is not None else None,
                traceback=(
                    "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                    if exc is not None
                    else None
                ),
            )
        )

    def _collect(self, ep: EntryPointLike) -> list[object] | None:
        """Turn what an entry point provides into a list of candidate items."""
        obj = ep.load()
        for may_call in (True, False):
            if isinstance(obj, WidgetSpec):
                return [obj]
            if may_call and callable(obj):
                obj = obj()
                continue
            if isinstance(obj, Iterable) and not isinstance(obj, str):
                return list(obj)
            break
        self._diagnose(
            ep,
            "registry.bad_entry_point",
            N_(
                "The entry point '{entry_point}' from '{distribution}' does not provide a widget "
                "specification, an iterable of them or a callable returning them."
            ),
        )
        return None

    def _load_widget_entry_point(self, ep: EntryPointLike) -> None:
        try:
            items = self._collect(ep)
        except Exception as exc:  # isolation point: a plugin must never crash the designer
            self._diagnose(
                ep,
                "registry.load_failed",
                N_("The entry point '{entry_point}' from '{distribution}' failed to load: {error}"),
                exc=exc,
                error=repr(exc),
            )
            return
        for item in items or ():
            if isinstance(item, WidgetSpec):
                self._register(ep, item)
            else:
                self._diagnose(
                    ep,
                    "registry.bad_spec",
                    N_(
                        "The entry point '{entry_point}' from '{distribution}' provided an item "
                        "that is not a widget specification: {item}"
                    ),
                    item=repr(item),
                )

    def _register(self, ep: EntryPointLike, spec: WidgetSpec) -> None:
        builtin = _is_builtin(ep)
        if spec.api_version != WIDGET_API_VERSION:
            self._diagnose(
                ep,
                "registry.incompatible_api",
                N_(
                    "The widget '{name}' from '{distribution}' targets widget API version "
                    "{version}, but this version of PyGUIbud requires version {required}."
                ),
                severity="warning",
                name=spec.name,
                version=spec.api_version,
                required=WIDGET_API_VERSION,
            )
            return
        try:
            prefix, _local = split_class_name(spec.name)
        except ModelError:
            self._diagnose(
                ep,
                "registry.bad_name",
                N_("The widget class name '{name}' from '{distribution}' is not valid."),
                name=spec.name,
            )
            return
        if prefix is None and not builtin:
            self._diagnose(
                ep,
                "registry.reserved_name",
                N_(
                    "The widget '{name}' from '{distribution}' has no prefix; plugin widgets "
                    "need a prefixed name such as 'acme:{name}' and cannot replace core widgets."
                ),
                name=spec.name,
            )
            return
        # Checked here, not in WidgetSpec.__post_init__: raising there would fail the whole entry
        # point (and its valid siblings) and hide the specific reason.
        if not isinstance(spec.display_name, str) or not spec.display_name.strip():
            self._diagnose(
                ep,
                "registry.bad_display_name",
                N_(
                    "The widget '{name}' from '{distribution}' has no display name and was ignored."
                ),
                name=spec.name,
            )
            return
        if spec.name in self._specs:
            self._diagnose(
                ep,
                "registry.duplicate",
                N_(
                    "The widget '{name}' from '{distribution}' is already registered by "
                    "'{first}' and was ignored."
                ),
                severity="warning",
                name=spec.name,
                first=self._origin_name(spec.name),
            )
            return
        if not builtin and spec.plugin is None:
            spec = dataclasses.replace(spec, plugin=_distribution(ep))
        self._specs[spec.name] = spec
        self._origins[spec.name] = ep

    def _ensure_core(self) -> None:
        """Safety net: register missing core specs directly (broken install or metadata)."""
        missing = CORE_CLASS_NAMES - self._specs.keys()
        if not missing:
            return
        try:
            # Lazy import keeps ``registry`` free of the widget data unless it is needed.
            from pyguibud.core import widgets

            for spec in widgets.core_widgets():
                if spec.name in missing:
                    self._specs[spec.name] = spec
                    self._origins[spec.name] = None
        except Exception as exc:  # isolation point: still never raise from load()
            self._diagnostics.append(
                Diagnostic(
                    group=WIDGETS_GROUP,
                    entry_point="",
                    distribution="pyguibud",
                    code="registry.load_failed",
                    msgid=N_("The built-in widgets could not be loaded: {error}"),
                    params={"error": repr(exc)},
                    exception=repr(exc),
                    traceback=traceback.format_exc(),
                )
            )
            return
        self._diagnostics.append(
            Diagnostic(
                group=WIDGETS_GROUP,
                entry_point="",
                distribution="pyguibud",
                code="registry.core_fallback",
                msgid=N_(
                    "Built-in widgets were missing from the installed package metadata and were "
                    "registered directly: {names}. Reinstalling PyGUIbud may fix this."
                ),
                params={"names": ", ".join(sorted(missing))},
                severity="warning",
            )
        )

    def _check_extensions(self) -> None:
        for name, spec in list(self._specs.items()):
            if not spec.is_extension:
                continue
            fallback = self._specs.get(spec.fallback or "")
            code: str | None = None
            msgid = ""
            if fallback is None or spec.fallback not in CORE_CLASS_NAMES:
                code = "registry.bad_fallback"
                msgid = N_(
                    "The widget '{name}' from '{distribution}' has no valid core fallback class "
                    "('{fallback}') and was ignored."
                )
            elif fallback.container != spec.container:
                code = "registry.fallback_mismatch"
                msgid = N_(
                    "The widget '{name}' from '{distribution}' and its fallback '{fallback}' "
                    "disagree on whether they are containers; the widget was ignored."
                )
            if code is not None:
                del self._specs[name]
                ep = self._origins.pop(name)
                # Extensions always come from an entry point; the safety net adds core names only.
                assert ep is not None
                self._diagnose(ep, code, msgid, name=name, fallback=spec.fallback or "")

    def _origin_name(self, name: str) -> str:
        ep = self._origins.get(name)
        return _distribution(ep) if ep is not None else "pyguibud"

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    # ------------------------------------------------------------ lookups
    def get(self, name: str) -> WidgetSpec | None:
        """Return the spec registered as ``name``, or None."""
        self._ensure_loaded()
        return self._specs.get(name)

    def require(self, name: str) -> WidgetSpec:
        """Return the spec registered as ``name``.

        Raises:
            RegistryError: ``registry.unknown_class``.
        """
        spec = self.get(name)
        if spec is None:
            raise _unknown_class(name)
        return spec

    def specs(self) -> tuple[WidgetSpec, ...]:
        """All registered specs, in registration order."""
        self._ensure_loaded()
        return tuple(self._specs.values())

    def is_container(self, name: str) -> bool:
        """True if ``name`` is a layout or page container (raises for unknown classes)."""
        return self.require(name).container

    def diagnostics(self) -> tuple[Diagnostic, ...]:
        """Problems found while loading, in the order they occurred."""
        self._ensure_loaded()
        return tuple(self._diagnostics)

    def backends(self) -> tuple[BackendInfo, ...]:
        """The listed (not loaded) backends."""
        self._ensure_loaded()
        return tuple(self._backends)

    def resolve(self, class_name: str, backend: str, fallback: str | None = None) -> Resolved:
        """Choose the spec to render ``class_name`` with ``backend``. Never returns None.

        Raises:
            RegistryError: ``registry.unknown_class`` if nothing can render the class.
        """
        spec = self.get(class_name)
        if spec is not None:
            if not spec.is_extension or backend in spec.factories:
                return Resolved(spec=spec, requested=class_name, is_fallback=False)
            # Registered extensions always have a registered core fallback (checked on load).
            return Resolved(
                spec=self.require(spec.fallback or ""),
                requested=class_name,
                is_fallback=True,
                code="registry.no_factory",
            )
        if is_extension(class_name) and fallback in CORE_CLASS_NAMES:
            core = self._specs.get(fallback or "")
            if core is not None:
                return Resolved(
                    spec=core,
                    requested=class_name,
                    is_fallback=True,
                    code="registry.plugin_missing",
                )
        raise _unknown_class(class_name)

    # ------------------------------------------------------------ backends
    def load_backend(self, name: str) -> object:
        """Load (once) and return the backend object registered as ``name``.

        Raises:
            RegistryError: ``registry.unknown_backend`` or ``registry.backend_failed``.
        """
        self._ensure_loaded()
        if name in self._backend_cache:
            return self._backend_cache[name]
        ep = self._backend_eps.get(name)
        if ep is None:
            raise RegistryError(
                "registry.unknown_backend", N_("Unknown backend '{name}'."), name=name
            )
        try:
            backend = ep.load()
        except Exception as exc:  # isolation point: report, then raise a domain error
            msgid = N_("The backend '{name}' from '{distribution}' failed to load: {error}")
            self._diagnose(
                ep, "registry.backend_failed", msgid, exc=exc, name=name, error=repr(exc)
            )
            raise RegistryError(
                "registry.backend_failed",
                msgid,
                name=name,
                distribution=_distribution(ep),
                error=repr(exc),
            ) from exc
        self._backend_cache[name] = backend
        return backend


def _unknown_class(name: str) -> RegistryError:
    return RegistryError("registry.unknown_class", N_("Unknown widget class '{name}'."), name=name)


# ---------------------------------------------------------------- default registry
_default: Registry | None = None


def default_registry() -> Registry:
    """The process-wide registry backed by the installed metadata (lazy; main thread only)."""
    global _default
    if _default is None:
        _default = Registry()
    return _default


def reset_default_registry() -> None:
    """Forget the default registry so the next call rebuilds it (for tests)."""
    global _default
    _default = None
