"""Entry-point registry of widget specifications and backends (ADR-004).

Plugins are a trust boundary: loading one runs its code. Every failure while loading a widget
entry point is isolated into a :class:`Diagnostic` so that a broken plugin never prevents the
designer from starting. Backends are only *listed* during :meth:`Registry.load`, because loading
one imports a GUI toolkit; :meth:`Registry.load_backend` loads them on demand.
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.metadata
import re
import traceback
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Literal, Protocol

from pyguibud.core.errors import ModelError, RegistryError, format_message
from pyguibud.core.model import (
    BACKEND_NAME,
    CORE_CLASS_NAMES,
    FACTORY_REF,
    WIDGET_API_VERSION,
    WidgetSpec,
    canonical_distribution,
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
    "FactoryStage",
    "Registry",
    "Resolved",
    "configure_default_registry",
    "default_registry",
    "reset_default_registry",
]

WIDGETS_GROUP: Final = "pyguibud.widgets"
BACKENDS_GROUP: Final = "pyguibud.backends"

#: The distribution that declares PyGUIbud's own entry points (ADR-016).
_BUILTIN_DISTRIBUTION: Final = "pyguibud-runtime"
#: PyGUIbud's distribution names: any other entry point they declare is a fork (H66).
_RESERVED_DISTRIBUTIONS: Final = frozenset({"pyguibud", _BUILTIN_DISTRIBUTION})
#: The value prefix of PyGUIbud's own entry points, per group (H66: both must match).
_BUILTIN_PREFIXES: Final[Mapping[str, str]] = MappingProxyType(
    {WIDGETS_GROUP: "pyguibud.core.widgets:", BACKENDS_GROUP: "pyguibud.backends."}
)
_MODULE_NAME = re.compile(r"[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9_]{0,98}[A-Za-z0-9]")
_UNKNOWN_DISTRIBUTION = "unknown"
#: Class-name prefix only the built-in entry points may use (spec plugins D2).
_RESERVED_PREFIX = "tb"
#: Isolation: a plugin may raise anything, or call ``sys.exit``; KeyboardInterrupt propagates.
_PLUGIN_ERRORS = (Exception, SystemExit)
FactoryStage = Literal["import", "create", "check", "wire"]
_STAGE_MSGIDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "import": N_(
            "The factory of widget '{name}' from '{distribution}' for backend '{backend}' "
            "could not be imported: {error}"
        ),
        "create": N_(
            "The factory of widget '{name}' from '{distribution}' failed to create the widget "
            "with backend '{backend}': {error}"
        ),
        "check": N_(
            "The factory of widget '{name}' from '{distribution}' returned an unusable widget "
            "with backend '{backend}': {error}"
        ),
        "wire": N_(
            "The widget '{name}' from '{distribution}' could not be set up with backend "
            "'{backend}': {error}"
        ),
    }
)


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
    """The distribution name shown and filtered on. Another entry point of a distribution named
    ``pyguibud`` or ``pyguibud-runtime`` (a fork, a hand-edited or stale install) is named after
    its top-level module instead, so it never joins the Built-in row nor hides its errors from R87
    (H66)."""
    dist = ep.dist
    if dist is None:
        return _UNKNOWN_DISTRIBUTION
    if _is_builtin(ep):  # one spelling, whatever the metadata's (``pyguibud_runtime``)
        return _BUILTIN_DISTRIBUTION
    if canonical_distribution(dist.name) not in _RESERVED_DISTRIBUTIONS:
        return dist.name
    module = ep.value.partition(":")[0].partition(".")[0].strip()
    plain = (
        _MODULE_NAME.fullmatch(module)
        and canonical_distribution(module) not in _RESERVED_DISTRIBUTIONS
    )
    return module if plain else _UNKNOWN_DISTRIBUTION


def _is_builtin(ep: EntryPointLike) -> bool:
    """Distribution, group and value prefix: a prefix alone is spoofable by a third party (D2),
    and a distribution name alone by a fork or a hand-made ``pyguibud-runtime`` metadata folder
    (H66)."""
    dist, prefix = ep.dist, _BUILTIN_PREFIXES.get(ep.group)
    return (
        dist is not None
        and prefix is not None
        and canonical_distribution(dist.name) == _BUILTIN_DISTRIBUTION
        and ep.value.startswith(prefix)
    )


def _traceback(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def _factory_problem(spec: WidgetSpec) -> str | None:
    """The first invalid factory key or reference of ``spec`` (D3), or None."""
    for key, ref in spec.factories.items():
        value: object = ref  # object: a plugin may put anything here
        if not isinstance(key, str) or BACKEND_NAME.fullmatch(key) is None:
            return repr(key)
        if isinstance(value, str):
            if FACTORY_REF.fullmatch(value) is None:
                return f"{key}: {value!r}"
        elif not callable(value):
            return f"{key}: {type(value).__name__}"
    return None


class Registry:
    """Widget specifications and backends discovered through entry points.

    The constructor does no I/O; the first lookup calls :meth:`load` once. ``disabled`` names
    distributions whose widget entry points are skipped before they are loaded; ``"all"`` skips
    every non-built-in one (safe mode); any other bare string is one name, not its letters.
    """

    def __init__(
        self,
        entry_points: EntryPointSource | None = None,
        *,
        disabled: Collection[str] | Literal["all"] = (),
    ) -> None:
        self._source: EntryPointSource = entry_points or _metadata_entry_points
        names = [disabled] if isinstance(disabled, str) else disabled  # never split a str
        self._disabled_filter: frozenset[str] | None = (
            None if disabled == "all" else frozenset(map(canonical_distribution, names))
        )
        self._disabled: set[str] = set()
        self._factories: dict[tuple[str, str], Callable[..., object] | None] = {}
        self._failures: set[tuple[str, str, str]] = set()
        #: Bumped on every load and every new factory failure (the designer refreshes on it).
        self.revision = 0
        self._loaded = False
        self._specs: dict[str, WidgetSpec] = {}
        # Entry point each spec came from; None for core specs added by the safety net.
        self._origins: dict[str, EntryPointLike | None] = {}
        self._diagnostics: list[Diagnostic] = []
        self._backend_eps: dict[str, EntryPointLike] = {}
        self._backends: list[BackendInfo] = []
        self._backend_cache: dict[str, object] = {}
        #: Non-built-in widget entry point name -> its distribution (H67's last resort).
        self._entry_dists: dict[str, str] = {}

    # ------------------------------------------------------------ loading
    def load(self) -> None:
        """(Re)discover every widget spec and backend. Never raises (except BaseException)."""
        self._specs.clear()
        self._origins.clear()
        self._diagnostics.clear()
        self._backend_eps.clear()
        self._backends.clear()
        self._backend_cache.clear()
        self._disabled.clear()
        self._factories.clear()
        self._failures.clear()
        self._entry_dists.clear()
        self.revision += 1
        self._loaded = True
        for ep in self._sorted(WIDGETS_GROUP):
            if not _is_builtin(ep):
                self._entry_dists.setdefault(ep.name, _distribution(ep))
            if not self._skip_disabled(ep):
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

    def _skip_disabled(self, ep: EntryPointLike) -> bool:
        """True when ``ep`` is filtered out (before it is loaded); warns once per distribution."""
        name = canonical_distribution(_distribution(ep))
        wanted = self._disabled_filter
        if _is_builtin(ep) or (wanted is not None and name not in wanted):
            return False
        if name not in self._disabled:
            self._disabled.add(name)
            self._diagnose(
                ep,
                "registry.disabled",
                N_("The plugin '{distribution}' is disabled and was not loaded."),
                severity="warning",
            )
        return True

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
                traceback=_traceback(exc) if exc is not None else None,
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
        except _PLUGIN_ERRORS as exc:  # isolation point: a plugin must never crash the designer
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
        if prefix == _RESERVED_PREFIX and not builtin:
            self._diagnose(
                ep,
                "registry.reserved_prefix",
                N_(
                    "The widget '{name}' from '{distribution}' uses the prefix '{prefix}', which "
                    "is reserved for PyGUIbud's own widgets; it was ignored."
                ),
                name=spec.name,
                prefix=_RESERVED_PREFIX,
            )
            return
        if (problem := _factory_problem(spec)) is not None:
            self._diagnose(
                ep,
                "registry.bad_factory",
                N_(
                    "The widget '{name}' from '{distribution}' has an invalid factory "
                    "({factory}) and was ignored."
                ),
                name=spec.name,
                factory=problem,
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
        # The real distribution, never the self-declared name: Help > Plugins groups and disables
        # by it, and a third party must not pose as another plugin or as PyGUIbud (QA-17c-01).
        real = _distribution(ep)
        if not builtin and spec.plugin != real:
            if isinstance(spec.plugin, str) and (  # a plugin may put anything here
                canonical_distribution(spec.plugin) != canonical_distribution(real)
            ):
                self._diagnose(
                    ep,
                    "registry.plugin_name_mismatch",
                    # Translators: {declared} is the plugin name a widget claims; {distribution}
                    # is the package it really comes from, which PyGUIbud uses instead.
                    N_(
                        "The widget '{name}' from '{distribution}' declares the plugin "
                        "'{declared}'; '{distribution}' is used instead."
                    ),
                    severity="warning",
                    name=spec.name,
                    declared=spec.plugin,
                )
            spec = dataclasses.replace(spec, plugin=real)
        self._specs[spec.name] = spec
        self._origins[spec.name] = ep

    def _ensure_core(self) -> None:
        """Safety net: register missing built-in specs directly (broken install, stale metadata)."""
        missing: set[str] = set()
        try:
            # Lazy import keeps ``registry`` free of the widget data until it loads.
            from pyguibud.core import widgets

            for spec in (*widgets.core_widgets(), *widgets.tb_widgets()):
                if spec.name not in self._specs:
                    missing.add(spec.name)
                    self._specs[spec.name] = spec
                    self._origins[spec.name] = None
        except Exception as exc:  # isolation point: still never raise from load()
            self._diagnostics.append(
                Diagnostic(
                    group=WIDGETS_GROUP,
                    entry_point="",
                    distribution=_BUILTIN_DISTRIBUTION,
                    code="registry.load_failed",
                    msgid=N_("The built-in widgets could not be loaded: {error}"),
                    params={"error": repr(exc)},
                    exception=repr(exc),
                    traceback=traceback.format_exc(),
                )
            )
            return
        if not missing:
            return
        self._diagnostics.append(
            Diagnostic(
                group=WIDGETS_GROUP,
                entry_point="",
                distribution=_BUILTIN_DISTRIBUTION,
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
        # Lazy: ``validate`` imports this module's neighbours; the table is only read here.
        from pyguibud.core.validate import BIND_TYPES

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
            elif not set(spec.events) <= set(fallback.events) or not set(
                spec.bind_types or ()
            ) <= set(BIND_TYPES.get(fallback.name, ())):
                # D5: a file valid with the plugin must stay valid without it (R25).
                code = "registry.not_fallback_compatible"
                msgid = N_(
                    "The widget '{name}' from '{distribution}' supports events or variable "
                    "types that its fallback '{fallback}' does not; the widget was ignored."
                )
            if code is not None:
                del self._specs[name]
                ep = self._origins.pop(name)
                params = {"name": name, "fallback": spec.fallback or ""}
                if ep is not None:
                    self._diagnose(ep, code, msgid, name=name, fallback=params["fallback"])
                else:  # a built-in spec added by the safety net (a packaging bug)
                    self._diagnostics.append(
                        Diagnostic(
                            group=WIDGETS_GROUP,
                            entry_point="",
                            distribution=_BUILTIN_DISTRIBUTION,
                            code=code,
                            msgid=msgid,
                            params=params | {"distribution": _BUILTIN_DISTRIBUTION},
                        )
                    )

    def _origin_name(self, name: str) -> str:
        ep = self._origins.get(name)
        return _distribution(ep) if ep is not None else _BUILTIN_DISTRIBUTION

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

    def failed_distributions(self) -> frozenset[str]:
        """Normalised names of plugin distributions with a load or factory error (R87)."""
        self._ensure_loaded()
        return frozenset(
            canonical_distribution(d.distribution)
            for d in self._diagnostics
            if d.severity == "error"
            and d.group == WIDGETS_GROUP
            and d.distribution not in (_BUILTIN_DISTRIBUTION, _UNKNOWN_DISTRIBUTION)
        )

    def disabled_distributions(self) -> frozenset[str]:
        """Normalised names of the distributions skipped by the ``disabled`` filter (R88)."""
        self._ensure_loaded()
        return frozenset(self._disabled)

    def plugin_for_prefix(self, prefix: str, declared: str | None = None) -> str | None:
        """The real distribution behind the class prefix ``prefix``, or None (H67: a file saved
        before QA-17c-01 may name the plugin's self-declared name instead).

        Exact for a class the registry has seen (registered, or named by a diagnostic). Otherwise
        the distribution whose widget entry point is named like the prefix (acme's ``acme``): a
        heuristic for a plugin that is disabled or failed before naming its classes, used only
        when the file's ``declared`` name is absent or is that entry point name (QA-19d-04: an
        unrelated distribution must never replace a correct ``plugin=``).
        """
        self._ensure_loaded()
        if prefix == _RESERVED_PREFIX:  # PyGUIbud's own; a plugin claiming it was refused
            return None
        seen = [(spec.name, spec.plugin) for spec in self._specs.values()]
        seen += [
            (d.params.get("name", ""), d.distribution)
            for d in self._diagnostics
            if d.group == WIDGETS_GROUP
        ]
        for name, plugin in seen:
            if (
                name.startswith(f"{prefix}:")
                and plugin
                and plugin not in (_BUILTIN_DISTRIBUTION, _UNKNOWN_DISTRIBUTION)
            ):
                return plugin
        if declared and canonical_distribution(declared) != canonical_distribution(prefix):
            return None
        return self._entry_dists.get(prefix)

    def load_factory(self, spec: WidgetSpec, backend: str) -> Callable[..., object] | None:
        """The factory of ``spec`` for ``backend``, importing a string reference once.

        Returns None when there is none or it fails to import (then reported, see
        :meth:`report_failure`); the caller renders the fallback.
        """
        self._ensure_loaded()
        key = (spec.name, backend)
        if key in self._factories:
            return self._factories[key]
        ref = spec.factories.get(backend)
        factory: Callable[..., object] | None = None
        if callable(ref):
            factory = ref
        elif isinstance(ref, str):
            module, _sep, attribute = ref.partition(":")
            try:
                loaded = getattr(importlib.import_module(module), attribute)
                if not callable(loaded):
                    raise TypeError(f"{ref} is not callable")
                factory = loaded
            except _PLUGIN_ERRORS as exc:  # isolation point: fall back, never crash
                self.report_failure(spec.name, backend, "import", exc)
        self._factories[key] = factory
        return factory

    def report_failure(
        self, class_name: str, backend: str, stage: FactoryStage, exc: BaseException
    ) -> None:
        """Record a factory failure once per (class, backend, stage) and bump ``revision``."""
        self._ensure_loaded()  # a later first load would clear the record
        key = (class_name, backend, stage)
        if key in self._failures:
            return
        self._failures.add(key)
        distribution = self._origin_name(class_name)
        self._diagnostics.append(
            Diagnostic(
                group=WIDGETS_GROUP,
                entry_point=(ep.name if (ep := self._origins.get(class_name)) else ""),
                distribution=distribution,
                code="registry.factory_failed",
                msgid=_STAGE_MSGIDS[stage],
                params={
                    "name": class_name,
                    "distribution": distribution,
                    "backend": backend,
                    "stage": stage,
                    "error": repr(exc),
                },
                exception=repr(exc),
                traceback=_traceback(exc),
            )
        )
        self.revision += 1

    def resolve(
        self,
        class_name: str,
        backend: str,
        fallback: str | None = None,
        *,
        plugin: str | None = None,
    ) -> Resolved:
        """Choose the spec to render ``class_name`` with ``backend``. Never returns None.

        ``plugin`` (the ``plugin=`` text of the file) only picks the diagnostic code of a missing
        class: ``registry.plugin_failed`` when that distribution failed to load.

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
                failed_names = self.failed_distributions()
                if plugin is None or canonical_distribution(plugin) not in failed_names:
                    plugin = self.plugin_for_prefix(class_name.partition(":")[0], plugin) or plugin
                failed = plugin is not None and canonical_distribution(plugin) in failed_names
                return Resolved(
                    spec=core,
                    requested=class_name,
                    is_fallback=True,
                    code="registry.plugin_failed" if failed else "registry.plugin_missing",
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
        except _PLUGIN_ERRORS as exc:  # isolation point: report, then raise a domain error
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


def configure_default_registry(disabled: Collection[str] | Literal["all"] = ()) -> None:
    """Replace the default registry with one that skips ``disabled`` plugins (still lazy)."""
    global _default
    _default = Registry(disabled=disabled)


def reset_default_registry() -> None:
    """Forget the default registry so the next call rebuilds it (for tests)."""
    global _default
    _default = None
