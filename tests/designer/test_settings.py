"""designer.settings: locations, tolerant reading (A9), merge, precedence (spec section 12)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.designer import settings as store
from pyguibud.designer.files import path_key
from pyguibud.designer.settings import (
    M_SETTINGS_RESET,
    MAX_SETTINGS_BYTES,
    Settings,
    load_settings,
    merge_recent,
    parse_settings,
    resolve_language,
    resolve_theme,
    save_settings,
)


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(tmp_path / "state"))
    return tmp_path / "config"


# ---------------------------------------------------------------- locations
def test_overrides(config: Path, tmp_path: Path) -> None:
    assert store.config_dir() == config
    assert store.state_dir() == tmp_path / "state"
    assert store.settings_path() == config / "settings.json"


@pytest.mark.parametrize(
    ("platform", "env", "config_tail", "state_tail"),
    [
        ("win32", {"APPDATA": "R", "LOCALAPPDATA": "L"}, ("R", "PyGUIbud"), ("L", "PyGUIbud")),
        ("darwin", {}, ("Library", "Application Support", "PyGUIbud"), None),
        (
            "linux",
            {"XDG_CONFIG_HOME": "C", "XDG_STATE_HOME": "S"},
            ("C", "pyguibud"),
            ("S", "pyguibud"),
        ),
        ("linux", {}, (".config", "pyguibud"), (".local", "state", "pyguibud")),
    ],
)
def test_platform_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    platform: str,
    env: dict[str, str],
    config_tail: tuple[str, ...],
    state_tail: tuple[str, ...] | None,
) -> None:
    for name in ("PYGUIBUD_CONFIG_DIR", "PYGUIBUD_STATE_DIR", "APPDATA", "LOCALAPPDATA"):
        monkeypatch.delenv(name, raising=False)
    for name in ("XDG_CONFIG_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, str(tmp_path / value))
    monkeypatch.setattr(store, "_platform", lambda: platform)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert store.config_dir().parts[-len(config_tail) :] == config_tail
    if state_tail is not None:
        assert store.state_dir().parts[-len(state_tail) :] == state_tail


# ---------------------------------------------------------------- reading
def test_missing_file_gives_defaults(config: Path) -> None:
    assert load_settings() == (Settings(), None)


def test_valid_file_round_trips_and_keeps_unknown_keys(config: Path, tmp_path: Path) -> None:
    recent = str(tmp_path / "app" / "main.ui")
    data = {
        "version": 1,
        "language": "de_DE",
        "theme": "dark",
        "window": {"geometry": "1280x800+-8+-8", "zoomed": True},
        "sashes": {"main": [240, 1040], "right": [420]},
        "recent_files": [recent],
        "autosave_seconds": 120,
        "fork_feature": {"x": [1, 2]},
    }
    config.mkdir(parents=True)
    (config / "settings.json").write_text(json.dumps(data), encoding="utf-8")
    loaded, message = load_settings()
    assert message is None
    assert loaded.language == "de_DE" and loaded.theme == "dark"
    assert loaded.geometry == "1280x800+-8+-8" and loaded.zoomed
    assert loaded.sashes == {"main": (240, 1040), "right": (420,)}
    assert loaded.recent_files == (recent,) and loaded.autosave_seconds == 120
    assert save_settings(loaded)
    written = json.loads((config / "settings.json").read_text(encoding="utf-8"))
    assert written == data


@pytest.mark.parametrize(
    "content",
    [
        b"garbage{",
        b"null",
        b"[1, 2]",
        b"\xff\xfe\x00",
        b"[" * 100_000,
        b" " * (MAX_SETTINGS_BYTES + 1),
    ],
    ids=["garbage", "null", "list", "not-utf8", "deep", "oversized"],
)
def test_corrupt_file_is_renamed_and_reported_once(config: Path, content: bytes) -> None:
    config.mkdir(parents=True)
    path = config / "settings.json"
    (config / "settings.json.corrupt").write_bytes(b"older copy")
    path.write_bytes(content)
    assert load_settings() == (Settings(), M_SETTINGS_RESET)
    assert not path.exists()
    assert (config / "settings.json.corrupt").read_bytes() == content  # one copy kept
    assert load_settings() == (Settings(), None)


def test_bad_values_fall_back_per_key(tmp_path: Path) -> None:
    data = {
        "language": "xx_YY",
        "theme": "neon",
        "window": {"geometry": "huge", "zoomed": 1},
        "sashes": {"main": [True, 3], "Bad Key": [1], "right": [5]},
        "recent_files": ["relative.ui", "//srv/share/a.ui", 5, str(tmp_path / "ok.ui")],
        "autosave_seconds": 5,
    }
    loaded = parse_settings(json.dumps(data).encode())
    assert loaded is not None
    assert loaded.language is None and loaded.theme is None
    assert loaded.geometry is None and not loaded.zoomed
    assert loaded.sashes == {"right": (5,)}
    assert loaded.recent_files == (str(tmp_path / "ok.ui"),)
    assert loaded.autosave_seconds == 60
    assert parse_settings(b'{"autosave_seconds": true, "window": []}') == Settings()


_JSON = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False) | st.text(max_size=20),
    lambda inner: (
        st.lists(inner, max_size=4) | st.dictionaries(st.text(max_size=12), inner, max_size=4)
    ),
    max_leaves=20,
)
_KEYS = st.sampled_from(
    ["language", "theme", "window", "sashes", "recent_files", "autosave_seconds", "x"]
)


@given(st.dictionaries(_KEYS, _JSON, max_size=7))
def test_fuzz_any_json_object_parses_to_valid_settings(data: dict[str, object]) -> None:
    loaded = parse_settings(json.dumps(data).encode())
    assert loaded is not None
    assert loaded.language is None or isinstance(loaded.language, str)
    assert 15 <= loaded.autosave_seconds <= 3600
    assert isinstance(loaded.zoomed, bool)
    assert all(isinstance(v, int) for values in loaded.sashes.values() for v in values)


@given(st.binary(max_size=200))
def test_fuzz_bytes_never_raise(data: bytes) -> None:
    result = parse_settings(data)
    assert result is None or isinstance(result, Settings)


# ---------------------------------------------------------------- writing and merging
def test_merge_recent_three_way(tmp_path: Path) -> None:
    a, b, c = (str(tmp_path / f"{n}.ui") for n in "abc")
    assert merge_recent([a], [b, a], ()) == (a, b)  # another instance added b
    assert merge_recent([a], [b, a], [path_key(b)]) == (a,)  # we removed b: it stays out
    assert merge_recent([], [c], [path_key(c)]) == ()  # Clear list


def test_save_merges_two_instances(config: Path, tmp_path: Path) -> None:
    a, b = str(tmp_path / "a.ui"), str(tmp_path / "b.ui")
    first, second = Settings(recent_files=(a,)), Settings(recent_files=(b,))
    assert save_settings(first)
    assert save_settings(second)
    assert second.recent_files == (b, a)
    assert load_settings()[0].recent_files == (b, a)


def test_save_failure_returns_false(tmp_path: Path) -> None:
    folder = tmp_path / "settings.json"
    folder.mkdir()
    assert not save_settings(Settings(), path=folder)
    assert not save_settings(Settings(extra={"bad": object()}), path=tmp_path / "s.json")


# ---------------------------------------------------------------- precedence
@pytest.mark.parametrize(
    ("cli", "env", "stored", "expected"),
    [
        ("fr_FR", "nl", "de_DE", "fr_FR"),
        (None, "nl", "de_DE", "nl_NL"),
        (None, "", "de_DE", "de_DE"),
        (None, "garbage", "de_DE", "de_DE"),
        (None, "", None, "it_IT"),
    ],
)
def test_language_precedence(
    monkeypatch: pytest.MonkeyPatch, cli: str | None, env: str, stored: str | None, expected: str
) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", env)
    monkeypatch.setattr(store, "detect_language", lambda: "it_IT")
    assert resolve_language(cli, Settings(language=stored)) == expected


def test_theme_precedence() -> None:
    assert resolve_theme("high-contrast", Settings(theme="dark")) == "high_contrast"
    assert resolve_theme(None, Settings(theme="dark")) == "dark"
    assert resolve_theme(None, Settings()) == "light"


# ---------------------------------------------------------------- Step 19b (H21, H29)
def test_a_lone_surrogate_no_longer_blocks_saving(tmp_path: Path) -> None:
    """H21 (QA-15b-09): a ``\\ud800`` from the file (or a Windows path) is kept, escaped."""
    path = tmp_path / "settings.json"
    path.write_text(
        '{"version": 1, "fork": "a\\ud800b", "recent_files": ["C:/x\\udc80.ui"]}',
        encoding="utf-8",
    )
    settings, message = store.load_settings(path)
    assert message is None and settings.extra["fork"] == "a\ud800b"
    settings.theme = "dark"
    assert store.save_settings(settings, path=path)
    again = store.load_settings(path)[0]
    assert again.theme == "dark" and again.extra["fork"] == "a\ud800b"
    again.theme = "light"
    assert store.save_settings(again, path=path)  # and every later save
    assert store.load_settings(path)[0].theme == "light"


def test_two_instances_merge_their_disabled_plugin_toggles(tmp_path: Path) -> None:
    """H29 (QA-17c-04, D8): each save applies its own toggles onto the file's list."""
    path = tmp_path / "settings.json"
    assert store.save_settings(Settings(disabled_plugins=("old",)), path=path)
    first, second = store.load_settings(path)[0], store.load_settings(path)[0]
    first.disabled_plugins = ("old", "acme")
    assert store.save_settings(first, path=path)
    second.disabled_plugins = tuple(n for n in second.disabled_plugins if n != "old")
    assert store.save_settings(second, path=path)
    assert second.disabled_plugins == ("acme",)
    assert store.load_settings(path)[0].disabled_plugins == ("acme",)
    assert store.save_settings(first, path=path)  # nothing new from the first: no stale delta
    assert store.load_settings(path)[0].disabled_plugins == ("acme",)


@given(
    ours=st.lists(st.sampled_from("abcde"), unique=True),
    base=st.lists(st.sampled_from("abcde"), unique=True),
    disk=st.lists(st.sampled_from("abcde"), unique=True),
)
def test_merge_disabled_applies_exactly_the_delta(
    ours: list[str], base: list[str], disk: list[str]
) -> None:
    merged = set(store.merge_disabled(ours, base, disk))
    assert merged == (set(disk) - (set(base) - set(ours))) | (set(ours) - set(base))
    assert store.merge_disabled(ours, ours, disk) == tuple(disk)
