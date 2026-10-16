"""Help > Plugins rows (pure; spec plugins 8, D16): the registry's specs and diagnostics per
distribution, with a status, the widget classes and every message for the details box."""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Literal

from pyguibud.core.model import canonical_distribution
from pyguibud.core.registry import Diagnostic, Registry
from pyguibud.designer.settings import parse_disabled_plugins
from pyguibud.i18n import N_, NP_, _, ngettext, plural_of

__all__ = ["STATUS_LABELS", "PluginRow", "plugin_note", "plugin_rows", "status_texts", "toggled"]

Status = Literal["builtin", "loaded", "failed", "disabled", "incompatible"]
STATUS_LABELS: dict[Status, str] = {
    # Translators: a plugin status in Help > Plugins: part of PyGUIbud itself.
    "builtin": N_("Built-in"),
    # Translators: a plugin status in Help > Plugins: the plugin's widgets were loaded.
    "loaded": N_("Loaded"),
    # Translators: a plugin status in Help > Plugins: the plugin raised an error.
    "failed": N_("Failed"),
    # Translators: a plugin status in Help > Plugins: the user chose not to load it.
    "disabled": N_("Disabled"),
    # Translators: a plugin status in Help > Plugins: made for another PyGUIbud version.
    "incompatible": N_("Incompatible"),
}
# Translators: {status} is a plugin status such as "Loaded"; the change needs a restart.
_M_DISABLE_NEXT = N_("{status} (disabled on next start)")
# Translators: {status} is a plugin status such as "Disabled"; the change needs a restart.
_M_ENABLE_NEXT = N_("{status} (enabled on next start)")
_M_NO_PROBLEMS = N_("No problems were reported.")
M_PROBLEMS = NP_(
    "{count} plugin problem — see Help ▸ Plugins.", "{count} plugin problems — see Help ▸ Plugins."
)
M_SAFE_MODE = N_("Plugins are disabled (safe mode).")
_BUILTIN = "pyguibud"
_UNKNOWN = "unknown"  # the registry's name when the metadata gives no distribution


@dataclass(frozen=True, slots=True)
class PluginRow:
    """One distribution; ``key`` is its PEP 503 name (what ``disabled_plugins`` stores)."""

    key: str
    distribution: str
    status: Status
    classes: tuple[str, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def can_toggle(self) -> bool:
        """Built-ins, a nameless distribution and a name the settings would drop cannot be."""
        return (
            self.status != "builtin"
            and self.key != _UNKNOWN
            and (parse_disabled_plugins([self.key]) == (self.key,))
        )

    def status_text(self, disabled_next: Collection[str], *, safe_mode: bool = False) -> str:
        """The status, plus the change the next start makes (Disable/Enable on next start);
        none in safe mode, where every plugin stays disabled whatever the list says."""
        status = _(STATUS_LABELS[self.status])
        wanted = self.key in disabled_next
        if self.can_toggle and not safe_mode and wanted != (self.status == "disabled"):
            return _(_M_DISABLE_NEXT if wanted else _M_ENABLE_NEXT).format(status=status)
        return status

    def details(self) -> str:
        """Every message with its traceback, for the read-only details box (translated now)."""
        parts = [d.message + (f"\n\n{d.traceback.rstrip()}" if d.traceback else "")
                 for d in self.diagnostics]  # fmt: skip
        return "\n\n".join(parts) or _(_M_NO_PROBLEMS)


def _status(key: str, found: list[Diagnostic]) -> Status:
    codes = {d.code for d in found}
    if key == _BUILTIN:
        return "builtin"
    if "registry.disabled" in codes:
        return "disabled"
    if any(d.severity == "error" for d in found):  # as ``failed_distributions`` (R87)
        return "failed"
    return "incompatible" if "registry.incompatible_api" in codes else "loaded"


def plugin_rows(registry: Registry) -> list[PluginRow]:
    """One row per distribution: the built-in first, then by name."""
    names: dict[str, str] = {}
    classes: dict[str, list[str]] = {}
    found: dict[str, list[Diagnostic]] = {}
    for spec in registry.specs():
        name = spec.plugin or _BUILTIN
        names.setdefault(canonical_distribution(name), name)
        classes.setdefault(canonical_distribution(name), []).append(spec.name)
    for diagnostic in registry.diagnostics():
        key = canonical_distribution(diagnostic.distribution)
        names.setdefault(key, diagnostic.distribution)
        found.setdefault(key, []).append(diagnostic)
    return [
        PluginRow(
            key,
            names[key],
            _status(key, found.get(key, [])),
            tuple(classes.get(key, ())),
            tuple(found.get(key, ())),
        )
        for key in sorted(names, key=lambda k: (k != _BUILTIN, k))
    ]


def status_texts() -> list[str]:
    """Every status text a row can show (translated now), to size the column once."""
    labels = [_(label) for label in STATUS_LABELS.values()]
    nexts = (_(_M_DISABLE_NEXT), _(_M_ENABLE_NEXT))
    return [*labels, *(text.format(status=label) for text in nexts for label in labels)]


def plugin_note(registry: Registry, safe_mode: bool) -> str | None:
    """The start-up status note (translated now): safe mode, else the error count, else None."""
    if safe_mode:
        return _(M_SAFE_MODE)
    count = sum(d.severity == "error" for d in registry.diagnostics())
    if not count:
        return None
    return ngettext(M_PROBLEMS, plural_of(M_PROBLEMS) or M_PROBLEMS, count).format(count=count)


def toggled(disabled: Collection[str], key: str) -> tuple[str, ...]:
    """``disabled`` with ``key`` added, or removed when it is already there (order kept)."""
    if key in disabled:
        return tuple(name for name in disabled if name != key)
    return (*disabled, key)
