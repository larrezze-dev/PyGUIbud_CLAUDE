"""The designer's settings store, without Tk (spec ``properties-save-load.md`` section 12).

``settings.json`` (schema v1) in a per-OS config folder computed with the stdlib. Reading is
tolerant: a size cap, a ``.corrupt`` rename for unreadable files, per-key defaults, unknown keys
kept for forks. JSON only, never executed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from pyguibud.backends import BACKEND_NAME  # anything else falls back (spec backends B14)
from pyguibud.core.model import canonical_distribution
from pyguibud.designer.files import MAX_RECENT, RecentFiles, path_key, write_atomic
from pyguibud.designer.theme import ROLES
from pyguibud.i18n import LANGUAGES, N_, PSEUDO_LANGUAGE, detect_language, normalise_language

__all__ = [
    "BACKEND_NAME",
    "MAX_SETTINGS_BYTES",
    "M_SETTINGS_RESET",
    "Settings",
    "config_dir",
    "load_settings",
    "merge_recent",
    "parse_disabled_plugins",
    "parse_settings",
    "remember_export",
    "resolve_language",
    "resolve_theme",
    "save_settings",
    "settings_path",
    "state_dir",
]

_log = logging.getLogger(__name__)

MAX_SETTINGS_BYTES = 256 * 1024
M_SETTINGS_RESET = N_("Your settings could not be read and were reset.")
_GEOMETRY = re.compile(r"[0-9]{1,5}x[0-9]{1,5}[+-]-?[0-9]{1,6}[+-]-?[0-9]{1,6}")
_SASH_KEY = re.compile(r"[a-z][a-z0-9_]{0,31}")
_CLI_THEMES = {"light": "light", "dark": "dark", "high-contrast": "high_contrast"}
_KNOWN = frozenset(
    {"version", "language", "theme", "window", "sashes", "recent_files", "autosave_seconds"}
    | {"preview_lang", "preview_backend", "exports", "disabled_plugins"}
)
_DEFAULT_AUTOSAVE = 60
#: What the user chooses (menus, settings); the window layout is state, not a preference.
_PREFERENCES = (
    "language", "theme", "autosave_seconds", "preview_lang", "preview_backend", "exports",
    "disabled_plugins",
)  # fmt: skip
DEFAULT_BACKEND = "ttkbootstrap"
MAX_EXPORTS = 50
#: Longer remembered export keys or paths are dropped on load: no real path is this long, and
#: a huge one froze the Export dialog's entry (QA-15b-03).
MAX_EXPORT_PATH = 4096
#: A PEP 508 distribution name (as R86); more disabled plugins than this are dropped on load.
_DISTRIBUTION = re.compile(r"[A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9._-]{0,98}[A-Za-z0-9]")
MAX_DISABLED_PLUGINS = 200


def _platform() -> str:
    """``sys.platform`` behind a seam (tests, and mypy's platform narrowing)."""
    return sys.platform


def _base(env: str, windows: str, linux_var: str, linux_default: str) -> Path:
    override = os.environ.get(env)
    if override:
        return Path(override)
    home, system = Path.home(), _platform()
    if system == "win32":
        root = os.environ.get(windows)
        return Path(root) / "PyGUIbud" if root else home / "AppData" / "PyGUIbud"
    if system == "darwin":
        return home / "Library" / "Application Support" / "PyGUIbud"
    root = os.environ.get(linux_var)
    return (Path(root) if root else home / linux_default) / "pyguibud"


def config_dir() -> Path:
    """Where ``settings.json`` lives (``PYGUIBUD_CONFIG_DIR`` overrides it)."""
    return _base("PYGUIBUD_CONFIG_DIR", "APPDATA", "XDG_CONFIG_HOME", ".config")


def state_dir() -> Path:
    """Where recovery data lives (``PYGUIBUD_STATE_DIR`` overrides it)."""
    return _base("PYGUIBUD_STATE_DIR", "LOCALAPPDATA", "XDG_STATE_HOME", ".local/state")


def settings_path() -> Path:
    """The settings file."""
    return config_dir() / "settings.json"


@dataclass(slots=True)
class Settings:
    """Every key is optional; None means "not stored" (the caller's default applies)."""

    language: str | None = None
    theme: str | None = None  # a role of ``designer.theme.ROLES``
    geometry: str | None = None  # Tk ``WxH+X+Y``; clamping to the screen is the Tk layer's job
    zoomed: bool = False
    sashes: dict[str, tuple[int, ...]] = field(default_factory=dict)
    recent_files: tuple[str, ...] = ()
    autosave_seconds: int = _DEFAULT_AUTOSAVE
    #: Preview > Language: a code of ``LANGUAGES`` or the pseudo-locale; None = the document's.
    preview_lang: str | None = None
    #: Preview > Toolkit: a backend name; malformed values load as ``ttkbootstrap``, while a
    #: well-formed name that is not listed or installed is kept but not used (spec §14).
    preview_backend: str = DEFAULT_BACKEND
    #: File > Export: the last output per ``.ui`` (``path_key`` -> path), oldest first, <= 50.
    exports: dict[str, str] = field(default_factory=dict)
    #: Help > Plugins: PEP 503-normalised distributions not loaded at the next start (D7).
    disabled_plugins: tuple[str, ...] = ()
    #: Unknown top-level keys, written back unchanged (forks).
    extra: dict[str, object] = field(default_factory=dict)
    #: Not stored: the file exists but could not be read at start-up (locked by another
    #: instance, a permission error). It is kept; a save merges into it (``save_settings``).
    unread: bool = False


def _whole(value: object, low: int, high: int) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and low <= value <= high:
        return value
    return None


def _sashes(value: object) -> dict[str, tuple[int, ...]]:
    found: dict[str, tuple[int, ...]] = {}
    if not isinstance(value, dict):
        return found
    for key, positions in list(value.items())[:16]:
        if not isinstance(key, str) or not _SASH_KEY.fullmatch(key):
            continue
        if not isinstance(positions, list) or len(positions) > 16:
            continue
        numbers = [_whole(p, 0, 100_000) for p in positions]
        if all(n is not None for n in numbers):
            found[key] = tuple(n for n in numbers if n is not None)
    return found


def _from_mapping(data: Mapping[str, object]) -> Settings:
    """Per-key tolerance: a bad value falls back to the default of that key only."""
    result = Settings(extra={k: v for k, v in data.items() if k not in _KNOWN})
    language = data.get("language")
    if isinstance(language, str) and language in LANGUAGES:
        result.language = language
    theme = data.get("theme")
    if isinstance(theme, str) and theme in ROLES:
        result.theme = theme
    window = data.get("window")
    if isinstance(window, dict):
        geometry = window.get("geometry")
        if isinstance(geometry, str) and _GEOMETRY.fullmatch(geometry):
            result.geometry = geometry
        result.zoomed = window.get("zoomed") is True
    result.sashes = _sashes(data.get("sashes"))
    recent = data.get("recent_files")
    if isinstance(recent, list):
        result.recent_files = RecentFiles(e for e in recent if isinstance(e, str)).entries
    preview_lang = data.get("preview_lang")
    if isinstance(preview_lang, str) and (
        preview_lang in LANGUAGES or preview_lang == PSEUDO_LANGUAGE
    ):
        result.preview_lang = preview_lang
    backend = data.get("preview_backend")
    if isinstance(backend, str) and BACKEND_NAME.fullmatch(backend):
        result.preview_backend = backend
    exports = data.get("exports")
    if isinstance(exports, dict):
        valid = [
            (k, v)
            for k, v in exports.items()
            if isinstance(k, str)
            and isinstance(v, str)
            and len(k) <= MAX_EXPORT_PATH
            and len(v) <= MAX_EXPORT_PATH
        ]
        result.exports = dict(valid[-MAX_EXPORTS:])
    result.disabled_plugins = parse_disabled_plugins(data.get("disabled_plugins"))
    seconds = _whole(data.get("autosave_seconds"), 15, 3600)
    result.autosave_seconds = _DEFAULT_AUTOSAVE if seconds is None else seconds
    return result


def parse_disabled_plugins(value: object) -> tuple[str, ...]:
    """The normalised, de-duplicated names of a stored list; anything else (even ``"all"``,
    which is never safe mode) is no list, and malformed entries are dropped."""
    if not isinstance(value, list):
        return ()
    names = (canonical_distribution(v) for v in value if isinstance(v, str))
    valid = [n for n in names if _DISTRIBUTION.fullmatch(n)]
    return tuple(dict.fromkeys(valid))[-MAX_DISABLED_PLUGINS:]  # the newest win (appended)


def parse_settings(data: bytes) -> Settings | None:
    """The settings in ``data``, or None when it is not a readable JSON object (pure)."""
    if len(data) > MAX_SETTINGS_BYTES:
        return None
    try:
        parsed = json.loads(data.decode("utf-8-sig"))  # a BOM from a hand edit is fine
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return _from_mapping(parsed) if isinstance(parsed, dict) else None


def load_settings(path: Path | None = None) -> tuple[Settings, str | None]:
    """Read the settings once at start-up; never raises.

    Returns the settings and, when the file was unreadable and has been reset, the msgid
    :data:`M_SETTINGS_RESET` for a single status message (translate it when showing it).
    """
    path = path or settings_path()
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError:
        return Settings(), None
    except OSError as exc:
        # A transient failure (another instance replacing the file, a lock) is not corruption:
        # defaults for this run, and the file stays as it is (QA-14a1-08).
        _log.warning("Settings %s unreadable: %s", path, exc)
        return Settings(unread=True), None
    parsed = parse_settings(data)
    if parsed is not None:
        return parsed, None
    try:
        os.replace(path, path.with_name(path.name + ".corrupt"))
    except OSError as exc:
        _log.warning("Corrupt settings %s could not be renamed: %s", path, exc)
    return Settings(), M_SETTINGS_RESET


def merge_recent(
    ours: Collection[str], on_disk: Collection[str], removed: Collection[str]
) -> tuple[str, ...]:
    """Our list first, then entries another instance added; ``removed`` (path keys) stay out."""
    gone = set(removed)
    merged = RecentFiles([*ours, *(e for e in on_disk if path_key(e) not in gone)])
    return merged.entries[:MAX_RECENT]


def _encode(settings: Settings, recent: tuple[str, ...]) -> bytes:
    data: dict[str, object] = dict(settings.extra)
    data["version"] = 1
    if settings.language is not None:
        data["language"] = settings.language
    if settings.theme is not None:
        data["theme"] = settings.theme
    window: dict[str, object] = {"zoomed": settings.zoomed}
    if settings.geometry is not None:
        window["geometry"] = settings.geometry
    data["window"] = window
    data["sashes"] = {key: list(value) for key, value in settings.sashes.items()}
    data["recent_files"] = list(recent)
    data["autosave_seconds"] = settings.autosave_seconds
    if settings.preview_lang is not None:
        data["preview_lang"] = settings.preview_lang
    if settings.preview_backend != DEFAULT_BACKEND and BACKEND_NAME.fullmatch(
        settings.preview_backend
    ):
        data["preview_backend"] = settings.preview_backend
    if settings.exports:
        data["exports"] = dict(settings.exports)
    if settings.disabled_plugins:
        data["disabled_plugins"] = list(settings.disabled_plugins)
    return (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def save_settings(
    settings: Settings, *, removed: Collection[str] = (), path: Path | None = None
) -> bool:
    """Write ``settings`` atomically after a read-merge of ``recent_files`` (two instances).

    ``removed`` are the path keys this process dropped (``RecentFiles.removed``). Settings are a
    convenience: a failure is logged and returns False, it never interrupts the user.
    """
    path = path or settings_path()
    current: Settings | None = None
    readable = True
    try:
        with path.open("rb") as stream:
            current = parse_settings(stream.read(MAX_SETTINGS_BYTES + 1))
    except FileNotFoundError:
        pass
    except OSError:
        readable = False
    on_disk = current.recent_files if current is not None else ()
    recent = merge_recent(settings.recent_files, on_disk, removed)
    target = settings
    if settings.unread:
        if not readable:
            return False  # still unreadable: never replace a file that was not read
        target = _merge_unread(settings, current)
        if current is not None and target == replace(current, recent_files=recent):
            return True  # nothing this run changed: the file stays as it is
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, _encode(target, recent))
    except (OSError, TypeError, ValueError) as exc:  # unserialisable extras of a fork
        _log.warning("Settings %s not saved: %s", path, exc)
        return False
    if target is not settings:
        _adopt(settings, target)
    settings.recent_files = recent
    return True


def _merge_unread(ours: Settings, on_disk: Settings | None) -> Settings:
    """The file's settings with only the preferences this run set on top (it started from
    defaults); the window layout of this run is not a preference and is not written."""
    if on_disk is None:  # the file is gone or corrupt now: ours is all there is
        return replace(ours, unread=False)
    defaults = Settings()
    merged = replace(on_disk, unread=False)
    for name in _PREFERENCES:
        value = getattr(ours, name)
        if value != getattr(defaults, name):
            setattr(merged, name, value)
    return merged


def _adopt(settings: Settings, merged: Settings) -> None:
    """Make ``settings`` the merged, now-written state (later saves are ordinary ones)."""
    for name in ("geometry", "zoomed", "sashes", *_PREFERENCES):
        setattr(settings, name, getattr(merged, name))
    settings.extra, settings.unread = dict(merged.extra), False


def remember_export(settings: Settings, key: str, output: str) -> None:
    """Remember ``output`` for the ``.ui`` with path key ``key``; the oldest of 50 goes."""
    settings.exports.pop(key, None)
    settings.exports[key] = output
    for old in list(settings.exports)[:-MAX_EXPORTS]:
        del settings.exports[old]


def resolve_language(cli: str | None, settings: Settings) -> str:
    """CLI flag > ``PYGUIBUD_LANG`` > settings > system locale > en_GB (section 12)."""
    if cli:
        return cli
    environment = normalise_language(os.environ.get("PYGUIBUD_LANG"))
    if environment:
        return environment
    return settings.language or detect_language()


def resolve_theme(cli: str | None, settings: Settings) -> str:
    """The theme role: CLI token (``high-contrast``) > settings > ``light``."""
    if cli in _CLI_THEMES:
        return _CLI_THEMES[cli]
    return settings.theme or "light"
