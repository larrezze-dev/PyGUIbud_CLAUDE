"""The pure side of the preview (spec preview-export 4.1, 4.3, 9 "Pure")."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from pyguibud.core import default_registry, validate
from pyguibud.core.files import DiskFiles
from pyguibud.core.model import Include, Widget
from pyguibud.core.xml_io import dump_ui, read_ui, read_ui_bytes
from pyguibud.designer.files import FileStamp
from pyguibud.designer.preview import (
    R_COMPONENT,
    R_PSEUDO,
    R_SNAPSHOT,
    R_THEME,
    SNAPSHOT,
    PreparedPreview,
    PreviewRequest,
    PreviewState,
    Refusal,
    catalogue_note,
    child_argv,
    prepare_preview,
    preview_findings,
    read_ready,
    read_result,
    stderr_tail,
)
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.settings import Settings, parse_settings, save_settings
from tests.designer.conftest import best_of

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"


def _copy(tmp_path: Path, *names: str) -> Path:
    target = tmp_path / "doc"
    shutil.copytree(EXAMPLES, target, ignore=shutil.ignore_patterns("__pycache__", "*.py"))
    return target.joinpath(*names)


def _session(path: Path | None, data: bytes | None = None) -> DesignerSession:
    session = DesignerSession(default_registry())
    result = read_ui_bytes(data) if data is not None else read_ui(path or "")
    session.open_document(result, path=path)
    return session


def _prepare(
    session: DesignerSession,
    private: Path,
    *,
    window: str = "main",
    lang: str | None = None,
    theme: str | None = None,
    read_only: bool = False,
) -> PreparedPreview | Refusal:
    assert session.document is not None and session.stack is not None
    request = PreviewRequest(
        session.document, session.path, session.dirty, read_only, window,
        lang, theme, session.stamp,
    )  # fmt: skip
    findings = preview_findings(session.document, session.registry, session.path, private)
    return prepare_preview(request, private, findings)


@pytest.fixture
def private(tmp_path: Path) -> Path:
    folder = tmp_path / "private"
    folder.mkdir()
    return folder


def test_a_clean_saved_document_is_loaded_from_its_file(tmp_path: Path, private: Path) -> None:
    path = _copy(tmp_path, "hello.ui")
    prepared = _prepare(_session(path), private)
    assert isinstance(prepared, PreparedPreview)
    assert prepared.source == path and prepared.snapshot is None and prepared.localedir is None
    assert prepared.differences == ()


def test_a_changed_file_on_disk_gives_a_snapshot(tmp_path: Path, private: Path) -> None:
    path = _copy(tmp_path, "hello.ui")
    session = _session(path)
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    session.stamp = FileStamp(1, 1, "other")  # what the canvas shows is not on disk any more
    prepared = _prepare(session, private)
    assert isinstance(prepared, PreparedPreview) and prepared.snapshot is not None


def test_a_dirty_document_gives_a_rebased_snapshot_and_stays_unchanged(
    tmp_path: Path, private: Path
) -> None:
    path = _copy(tmp_path, "preview", "with_image.ui")
    session = _session(path)
    assert session.document is not None and session.stack is not None
    window = session.document.children[0]
    label = window.children[1]
    assert isinstance(label, Widget)
    from pyguibud.core.commands import SetProp
    from pyguibud.core.model import Prop

    assert session.stack.execute(SetProp(label, Prop(name="text", value="Changed"))).accepted
    before, children, depth = dump_ui(session.document), window.children, session.stack.undo_text
    prepared = _prepare(session, private)
    assert isinstance(prepared, PreparedPreview) and prepared.snapshot is not None
    assert prepared.source is None and prepared.localedir == path.parent / "locale"
    # the session's document is untouched: same bytes, same nodes, same undo step
    assert dump_ui(session.document) == before and window.children == children
    assert session.stack.undo_text == depth and session.dirty
    snapshot = private / SNAPSHOT
    snapshot.write_bytes(prepared.snapshot)
    result = read_ui(snapshot)
    image = result.document.resources["img_logo"]
    assert (snapshot.parent / image.src).resolve() == (path.parent / "logo.png").resolve()
    report = validate(result.document, default_registry(), files=DiskFiles(snapshot, result))
    assert report.errors == ()


def test_a_component_is_hosted_in_a_dialog_with_a_unique_id(tmp_path: Path, private: Path) -> None:
    source = (ROOT / "tests" / "codegen" / "data" / "includes.ui").read_text(encoding="utf-8")
    source = source.replace('id="dlg"', 'id="preview_host"', 1)
    path = tmp_path / "with_component.ui"
    path.write_text(source, encoding="utf-8")
    (tmp_path / "part.ui").write_bytes((ROOT / "tests/codegen/data/part.ui").read_bytes())
    session = _session(path)
    prepared = _prepare(session, private, window="local")
    assert isinstance(prepared, PreparedPreview) and prepared.snapshot is not None
    assert prepared.host_id == prepared.window_id == "preview_host_2"
    assert R_COMPONENT in prepared.differences and R_SNAPSHOT in prepared.differences
    snapshot = private / SNAPSHOT
    snapshot.write_bytes(prepared.snapshot)
    result = read_ui(snapshot)
    host = next(w for w in result.document.children if w.id == "preview_host_2")
    include = host.children[0]
    assert host.kind == "dialog" and isinstance(include, Include)
    assert (include.src, include.component) == ("#", "local")
    report = validate(result.document, default_registry(), files=DiskFiles(snapshot, result))
    assert report.errors == ()


def test_a_file_error_refuses_with_the_count_and_the_first_error(
    tmp_path: Path, private: Path
) -> None:
    path = _copy(tmp_path, "preview", "with_image.ui")
    (path.parent / "logo.png").rename(path.parent / "logo-renamed.png")
    session = _session(path)
    refusal = _prepare(session, private)
    assert isinstance(refusal, Refusal)
    assert refusal.message.startswith("The document has 1 error. Fix it to preview.")
    assert "logo.png" in refusal.message  # trim T2: no node selection


def test_an_untitled_document_with_relative_paths_must_be_saved_first(
    tmp_path: Path, private: Path
) -> None:
    data = (EXAMPLES / "preview" / "with_image.ui").read_bytes()
    refusal = _prepare(_session(None, data), private)
    assert isinstance(refusal, Refusal) and refusal.message.startswith("Save the document first")
    untitled = _prepare(_session(None, (EXAMPLES / "hello.ui").read_bytes()), private)
    assert isinstance(untitled, PreparedPreview) and untitled.localedir is None


def test_differences_from_the_exported_module(tmp_path: Path, private: Path) -> None:
    path = _copy(tmp_path, "hello.ui")
    prepared = _prepare(_session(path), private, lang="en_XA", theme="darkly")
    assert isinstance(prepared, PreparedPreview)
    assert prepared.differences == (R_PSEUDO, R_THEME)
    only = tmp_path / "only.ui"  # P9: a file with only components is previewed in its host
    only.write_bytes((ROOT / "tests/codegen/data/part.ui").read_bytes())
    component = _prepare(_session(only), private, window="part")
    assert isinstance(component, PreparedPreview) and component.host_id == "preview_host"


def test_prepare_is_fast_for_2000_widgets(tmp_path: Path, private: Path) -> None:
    labels = "".join(
        f'<widget class="Label" id="l{i}"><prop name="text">L{i}</prop><pack/></widget>'
        for i in range(2000)
    )
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n<pyguibud-ui schema_version="1.0" '
        'xmlns="urn:pyguibud:ui:1"><meta source_locale="en_GB"/><window id="main" kind="main">'
        f'<layout type="pack"/>{labels}</window></pyguibud-ui>\n'
    )
    path = tmp_path / "big.ui"
    path.write_text(text, encoding="utf-8")
    session = _session(path)
    session.stamp = None  # forces the snapshot path, the expensive one
    assert best_of(lambda: _prepare(session, private), repeat=3) < 0.6  # spec 150 ms; CI slack


# ---------------------------------------------------------------- state machine (4.3)
def _phase(state: PreviewState) -> str:
    return state.phase  # read through a call: no narrowing across steps


def test_state_transitions_and_a_storm_of_f5_presses() -> None:
    state = PreviewState()
    assert state.start() == "spawn" and _phase(state) == "starting"
    state.ready()
    assert _phase(state) == "running"
    actions = [state.start() for _ in range(10)]
    assert actions == ["quit"] + ["wait"] * 9 and state.pending
    assert state.exited() is True and _phase(state) == "starting"  # exactly one restart
    state.ready()
    assert state.stop() is True and _phase(state) == "stopping"
    assert state.exited() is False and _phase(state) == "idle"
    assert state.stop() is False


def test_shift_f5_cancels_a_pending_restart() -> None:
    state = PreviewState()
    state.start()
    state.start()
    assert state.pending
    state.stop()
    assert state.exited() is False and _phase(state) == "idle"


# ---------------------------------------------------------------- argv and child files
def test_child_argv_passes_odd_paths_after_double_dash(tmp_path: Path) -> None:
    odd = tmp_path / "-leading dash ü" / "my form.ui"
    prepared = PreparedPreview(odd, None, tmp_path / "loc ale", "dlg", None, ())
    argv = child_argv(prepared, tmp_path, ui_lang="de_DE", lang="fr_FR", theme="darkly")
    assert argv[:3] == [sys.executable, "-m", "pyguibud.preview"]
    assert argv[-2:] == ["--", str(odd)]
    pairs = dict(zip(argv[3:-2:2], argv[4:-2:2], strict=True))
    assert pairs == {
        "--ui-lang": "de_DE", "--backend": "ttkbootstrap", "--lang": "fr_FR",
        "--theme": "darkly", "--window": "dlg", "--localedir": str(tmp_path / "loc ale"),
    }  # fmt: skip
    snapshot = PreparedPreview(None, b"x", None, "main", None, ())
    plain = child_argv(snapshot, tmp_path, ui_lang="en_GB", lang=None, theme=None)
    assert plain[-1] == str(tmp_path / SNAPSHOT) and "--lang" not in plain


def test_read_result_treats_missing_malformed_and_huge_as_a_crash(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    assert read_result(path) == ("crash", "")
    for data in (b"{", b"[1]", b'{"code": 3}', b'{"code": "ok", "pad": "' + b"x" * 70_000 + b'"}'):
        path.write_bytes(data)
        assert read_result(path) == ("crash", ""), data[:20]
    path.write_text(json.dumps({"code": "ok", "message": 5}), "utf-8")
    assert read_result(path) == ("ok", "")


def test_read_ready_waits_for_a_complete_file(tmp_path: Path) -> None:
    path = tmp_path / "ready.json"
    assert read_ready(path) is None
    path.write_text('{"themes": ["a", ', encoding="utf-8")
    assert read_ready(path) is None
    path.write_text(json.dumps({"themes": ["flatly", 3, "darkly"]}), encoding="utf-8")
    assert read_ready(path) == ["flatly", "darkly"]


def test_stderr_tail_keeps_the_last_20_lines(tmp_path: Path) -> None:
    path = tmp_path / "stderr.txt"
    assert stderr_tail(path) == ""
    path.write_text("".join(f"line {i}\n" for i in range(5000)), encoding="utf-8")
    tail = stderr_tail(path).splitlines()
    assert len(tail) == 20 and tail[-1] == "line 4999"


def test_catalogue_note(tmp_path: Path) -> None:
    document = read_ui(EXAMPLES / "hello.ui").document
    locale = EXAMPLES / "locale"
    assert catalogue_note(document, locale, "de_DE") is None  # shipped
    assert catalogue_note(document, locale, None) is None
    assert catalogue_note(document, locale, "en_XA") is None
    assert catalogue_note(document, locale, "en_US") is None  # the source language
    note = catalogue_note(document, tmp_path, "fr_FR")
    assert note is not None and "fr_FR" in note and str(tmp_path) in note
    assert catalogue_note(document, None, "fr_FR") is None


def test_the_preview_language_is_remembered(tmp_path: Path) -> None:
    settings = Settings(preview_lang="de_DE")
    path = tmp_path / "settings.json"
    assert save_settings(settings, path=path)
    loaded = parse_settings(path.read_bytes())
    assert (
        loaded is not None and loaded.preview_lang == "de_DE" and "preview_lang" not in loaded.extra
    )
    for value in ("en_XA", "xx_YY", 5):
        parsed = parse_settings(json.dumps({"preview_lang": value}).encode())
        assert parsed is not None and parsed.preview_lang == ("en_XA" if value == "en_XA" else None)
    assert "preview_lang" not in json.loads(_written(tmp_path, Settings()))


def _written(tmp_path: Path, settings: Settings) -> str:
    path = tmp_path / "plain.json"
    assert save_settings(settings, path=path)
    return path.read_text(encoding="utf-8")


def test_qa15a_01_a_bad_preview_lang_type_falls_back(tmp_path: Path) -> None:
    values: tuple[object, ...] = ([], {}, ["de_DE"], 3.5, None)
    for value in values:
        parsed = parse_settings(json.dumps({"preview_lang": value, "language": "de_DE"}).encode())
        assert parsed is not None and parsed.preview_lang is None and parsed.language == "de_DE"
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"preview_lang": {}}), encoding="utf-8")
    assert save_settings(Settings(preview_lang="fr_FR"), path=path)  # the merge read
    assert json.loads(path.read_text(encoding="utf-8"))["preview_lang"] == "fr_FR"


def test_qa15a_02_prepare_refuses_an_unknown_window(tmp_path: Path, private: Path) -> None:
    refusal = _prepare(_session(_copy(tmp_path, "hello.ui")), private, window="gone")
    assert (
        isinstance(refusal, Refusal) and refusal.message == "The document has no window to preview."
    )
