"""File > Export, the pure part: every abuse row E1-E11 of spec preview-export 8, the byte
identity with ``pyguibud-uic`` and the remembered export paths (spec 9 "Export")."""

from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

import pytest

from pyguibud import uic
from pyguibud.codegen._errors import M_READ_ONLY, M_SAME_FILE, M_WRITE_FAILED
from pyguibud.core import write_ui
from pyguibud.core.model import Document, GridCell, Layout, Widget, Window
from pyguibud.designer import export as ex
from pyguibud.designer.files import M_NETWORK, FileStamp
from pyguibud.designer.settings import MAX_EXPORTS, Settings, parse_settings, remember_export

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "examples"
CODEGEN = ROOT / "tests" / "codegen" / "data"


@pytest.fixture
def ui(tmp_path: Path) -> Path:
    folder = tmp_path / "doc"
    folder.mkdir()
    shutil.copy(EXAMPLES / "hello.ui", folder)
    shutil.copytree(EXAMPLES / "locale", folder / "locale")
    return folder / "hello.ui"


def _source(path: Path, *, dirty: bool = False) -> ex.ExportSource:
    return ex.ExportSource(path, dirty, FileStamp.of(path))


def _plan(path: Path, output: str, **options: object) -> ex.ExportPlan | ex.Refusal:
    return ex.export_plan(_source(path), ex.ExportRequest(output, **options))  # type: ignore[arg-type]


def _refused(path: Path, output: str, msgid: str, **options: object) -> ex.Refusal:
    plan = _plan(path, output, **options)
    assert isinstance(plan, ex.Refusal), plan
    assert plan.msgid == msgid, plan.text()
    assert plan.text()  # renders
    return plan


def _export(path: Path, output: str, **options: object) -> ex.ExportOutcome:
    plan = _plan(path, output, **options)
    assert isinstance(plan, ex.ExportPlan), plan.text()
    return ex.run_export(plan)


# ---------------------------------------------------------------- byte identity (D10)
def test_module_bytes_equal_pyguibud_uic(ui: Path) -> None:
    out = ui.parent / "hello_ui.py"
    outcome = _export(ui, "hello_ui.py")
    assert outcome.failure is None and outcome.written == (str(out),)
    ours = out.read_bytes()
    out.unlink()
    assert uic.main([str(ui), "-o", str(out)]) == 0
    assert ours == out.read_bytes()
    assert "Exported" in outcome.text()


def test_template_bytes_equal_uic_extract(ui: Path) -> None:
    pot = ui.parent / "locale" / "hello.pot"
    outcome = _export(ui, "hello_ui.py", pot="locale/hello.pot")
    assert outcome.written == (str(ui.parent / "hello_ui.py"), str(pot))
    ours = pot.read_bytes()
    pot.unlink()
    assert uic.main(["--extract", str(ui), "-o", str(pot)]) == 0
    assert ours == pot.read_bytes()
    assert "hello.pot" in outcome.text()


def test_template_folder_is_created_one_level_only(ui: Path) -> None:
    shutil.rmtree(ui.parent / "locale")
    _export(ui, "hello_ui.py", pot="locale/hello.pot")
    assert (ui.parent / "locale" / "hello.pot").is_file()
    _refused(ui, "hello_ui.py", ex.M_NO_FOLDER, pot="a/b/x.pot")


def test_regeneration_replaces_silently(ui: Path) -> None:
    _export(ui, "hello_ui.py")
    assert _export(ui, "hello_ui.py").failure is None


def test_suffix_is_appended_and_relative_names_follow_the_ui_folder(ui: Path) -> None:
    plan = _plan(ui, "  form  ")
    assert isinstance(plan, ex.ExportPlan)
    assert plan.output == str(ui.parent / "form.py")
    assert not plan.notes


# ---------------------------------------------------------------- E1: the .ui and its includes
def test_e1_the_ui_itself_is_never_the_output(ui: Path) -> None:
    _refused(ui, "hello.ui", ex.M_SUFFIX)  # the suffix rule stops it first
    _refused(ui, "\\\\?\\" + str(ui.with_suffix(".py")), M_NETWORK)  # never opened (R82)
    link = ui.parent / "alias.py"
    try:
        os.link(ui, link)
    except OSError:
        pytest.skip("hard links are not available here")
    _refused(ui, "alias.py", M_SAME_FILE)
    assert link.read_bytes() == ui.read_bytes()


def test_e1_an_included_ui_is_never_the_output(tmp_path: Path) -> None:
    for name in ("includes.ui", "part.ui"):
        shutil.copy(CODEGEN / name, tmp_path)
    try:
        os.link(tmp_path / "part.ui", tmp_path / "part_alias.py")
    except OSError:
        pytest.skip("hard links are not available here")
    _refused(tmp_path / "includes.ui", "part_alias.py", M_SAME_FILE)


# ---------------------------------------------------------------- E2-E5: names
@pytest.mark.parametrize("name", ["", "   ", "sub/", "sub"])
def test_e2_empty_names_and_folders(ui: Path, name: str) -> None:
    (ui.parent / "sub").mkdir()
    _refused(ui, name, ex.M_NO_NAME if not name.strip() else ex.M_IS_FOLDER)


@pytest.mark.parametrize("name", ["CON", "nul.py", "\\\\server\\share\\x.py", "//host/s/x.py"])
def test_e2_devices_and_network_paths_are_never_opened(ui: Path, name: str) -> None:
    _refused(ui, name, M_NETWORK)


def test_e3_a_hand_written_file_is_left_untouched(ui: Path) -> None:
    app = ui.parent / "app.py"
    app.write_text("print('mine')\n", encoding="utf-8")
    before = (app.read_bytes(), app.stat().st_mtime_ns)
    _refused(ui, "app.py", ex.M_NOT_GENERATED)
    assert (app.read_bytes(), app.stat().st_mtime_ns) == before


@pytest.mark.parametrize(
    "name", ["tkinter.py", "gettext.py", "ttkbootstrap.py", "PIL.py", "pyguibud_runtime.py"]
)
def test_e4_names_that_would_hide_a_module(ui: Path, name: str) -> None:
    refusal = _refused(ui, name, ex.M_SHADOWS)
    assert name.removesuffix(".py") in refusal.text()


def test_e5_other_suffixes_are_refused(ui: Path) -> None:
    _refused(ui, "form.txt", ex.M_SUFFIX)


def test_a_name_that_cannot_be_imported_is_only_a_warning(ui: Path) -> None:
    outcome = _export(ui, "my-form.py")
    assert outcome.written and "my-form.py" in outcome.text()
    assert [n.msgid for n in outcome.plan.notes] == [ex.M_NOT_IMPORTABLE]


# ---------------------------------------------------------------- E6: write failures
def test_e6_a_failed_write_leaves_no_temporary_file(
    ui: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(ui, "hello_ui.py")
    assert isinstance(plan, ex.ExportPlan)

    def refuse(*_args: object) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "replace", refuse)
    outcome = ex.run_export(plan)
    assert outcome.written == () and outcome.failure is not None
    assert outcome.failure.msgid == M_WRITE_FAILED
    assert "Permission denied" in outcome.text()
    assert not list(ui.parent.glob("~pgb*.tmp"))
    assert not (ui.parent / "hello_ui.py").exists()


def test_e6_a_failed_template_keeps_the_module_and_says_which(
    ui: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = _plan(ui, "hello_ui.py", pot="locale/hello.pot")
    assert isinstance(plan, ex.ExportPlan)
    real = os.replace

    def refuse_pot(source: str, target: str) -> None:
        if target.endswith(".pot"):
            raise PermissionError(13, "Permission denied")
        real(source, target)

    monkeypatch.setattr(os, "replace", refuse_pot)
    outcome = ex.run_export(plan)
    assert outcome.written == (plan.output,)
    assert "hello.pot" in outcome.text() and "hello_ui.py" in outcome.text()
    assert not list((ui.parent / "locale").glob("~pgb*.tmp"))


def test_e6_a_missing_folder_is_refused_before_generation(ui: Path) -> None:
    _refused(ui, "missing/hello_ui.py", ex.M_NO_FOLDER)


# ---------------------------------------------------------------- E7, E8: the template
def test_e7_a_translated_catalogue_is_never_the_template(ui: Path) -> None:
    po = "locale/de_DE/LC_MESSAGES/hello.po"
    before = (ui.parent / po).read_bytes()
    _refused(ui, "hello_ui.py", ex.M_TRANSLATIONS, pot=po)
    assert (ui.parent / po).read_bytes() == before


def test_e8_the_template_is_not_the_module(ui: Path) -> None:
    _refused(ui, "hello_ui.py", ex.M_TEMPLATE_IS_MODULE, pot="hello_ui.py")


def test_the_template_is_not_the_ui(ui: Path) -> None:
    _refused(ui, "hello_ui.py", M_SAME_FILE, pot="hello.ui")


# ---------------------------------------------------------------- E9, E10, read-only
def test_e9_a_dirty_or_untitled_document_must_be_saved_first(ui: Path) -> None:
    request = ex.ExportRequest("hello_ui.py")
    for source in (_source(ui, dirty=True), ex.ExportSource(None, False, None)):
        refusal = ex.export_plan(source, request)
        assert isinstance(refusal, ex.Refusal) and refusal.msgid == ex.M_SAVE_FIRST


def test_e10_a_file_changed_on_disk_is_refused(ui: Path) -> None:
    source = _source(ui)
    ui.write_bytes(ui.read_bytes() + b"<!-- edited elsewhere -->\n")
    refusal = ex.export_plan(source, ex.ExportRequest("hello_ui.py"))
    assert isinstance(refusal, ex.Refusal) and refusal.msgid == ex.M_CHANGED
    assert not (ui.parent / "hello_ui.py").exists()


def test_a_newer_minor_file_is_refused(ui: Path) -> None:
    ui.write_bytes(ui.read_bytes().replace(b'schema_version="1.0"', b'schema_version="1.9"'))
    _refused(ui, "hello_ui.py", M_READ_ONLY)


# ---------------------------------------------------------------- E11: outside paths
def test_e11_outside_paths_need_the_check_box(tmp_path: Path) -> None:
    (tmp_path / "logo.ppm").write_bytes(b"P6 1 1 255\n\x00\x00\x00")
    folder = tmp_path / "doc"
    folder.mkdir()
    text = (EXAMPLES / "hello.ui").read_text(encoding="utf-8")
    text = text.replace("<window ", '<resources><image id="logo" src="../logo.ppm"/></resources>'
                        "<window ", 1)  # fmt: skip
    (folder / "hello.ui").write_text(text, encoding="utf-8")
    refusal = _refused(folder / "hello.ui", "hello_ui.py", ex.M_OUTSIDE)
    assert refusal.outside == ("../logo.ppm",)
    assert _export(folder / "hello.ui", "hello_ui.py", allow_outside=True).written


# ---------------------------------------------------------------- helpers
def test_default_paths(ui: Path) -> None:
    assert ex.default_paths(ui, "hello", None) == (
        str(ui.parent / "hello_ui.py"),
        str(ui.parent / "locale" / "hello.pot"),
    )
    assert ex.default_paths(ui, None, "x.py") == ("x.py", str(ui.parent / "locale" / "hello.pot"))


def test_run_argv_never_passes_the_pseudo_locale() -> None:
    assert ex.run_argv("o.py", None) == [sys.executable, "o.py"]
    assert ex.run_argv("o.py", "en_XA") == [sys.executable, "o.py"]
    assert ex.run_argv("o.py", "de_DE") == [sys.executable, "o.py", "--lang", "de_DE"]


def test_intact_compares_the_bytes_on_disk(tmp_path: Path) -> None:
    out = tmp_path / "o.py"
    out.write_bytes(b"x = 1\n")
    assert ex.intact(str(out), "x = 1\n")
    assert not ex.intact(str(out), "x = 2\n")
    assert not ex.intact(str(tmp_path / "missing.py"), "")


def test_exports_are_capped_at_fifty_newest_kept() -> None:
    settings = Settings()
    for index in range(MAX_EXPORTS + 5):
        remember_export(settings, f"k{index}", f"o{index}.py")
    remember_export(settings, "k10", "again.py")  # moves to the newest end
    assert len(settings.exports) == MAX_EXPORTS
    assert "k0" not in settings.exports and list(settings.exports)[-1] == "k10"


@pytest.mark.parametrize("value", ['"text"', "[1, 2]", '{"a": 1, "b": "ok", "1": null}', "null"])
def test_malformed_exports_in_settings_are_dropped(value: str) -> None:
    settings = parse_settings(f'{{"exports": {value}}}'.encode())
    assert settings is not None
    assert settings.exports == ({"b": "ok"} if value.startswith("{") else {})


def test_exports_survive_a_settings_round_trip(tmp_path: Path) -> None:
    from pyguibud.designer.settings import load_settings, save_settings

    settings = Settings()
    remember_export(settings, "key", "out.py")
    path = tmp_path / "settings.json"
    assert save_settings(settings, path=path)
    assert load_settings(path)[0].exports == {"key": "out.py"}


@pytest.mark.slow
def test_export_of_ten_thousand_widgets_is_fast(tmp_path: Path) -> None:
    document = Document()
    window = Window(id="main", layout=Layout(type="grid"))
    frame = Widget(class_name="Frame", id="frame", placement=GridCell(row=0, column=0),
                   layout=Layout(type="grid"))  # fmt: skip
    window.append_child(frame)
    for index in range(10_000):
        cell = GridCell(row=index // 40, column=index % 40)
        frame.append_child(Widget(class_name="Label", id=f"w{index}", placement=cell))
    document.add_window(window)
    path = tmp_path / "big.ui"
    write_ui(document, path)
    started = time.perf_counter()
    outcome = _export(path, "big_ui.py")
    elapsed = time.perf_counter() - started
    assert outcome.failure is None
    assert elapsed <= 1.5, elapsed


def test_refusals_never_name_command_line_options(ui: Path) -> None:
    app = ui.parent / "app.py"
    app.write_text("print('mine')\n", encoding="utf-8")
    po = "locale/de_DE/LC_MESSAGES/hello.po"
    refusals = [
        _refused(ui, "app.py", ex.M_NOT_GENERATED),
        _refused(ui, "hello_ui.py", ex.M_NOT_GENERATED, pot="app.py"),
        _refused(ui, "hello_ui.py", ex.M_TRANSLATIONS, pot=po),
        _refused(ui, "hello_ui.py", ex.M_TEMPLATE_IS_MODULE, pot="hello_ui.py"),
        _refused(ui, "hello_ui.py", M_SAME_FILE, pot="hello.ui"),
    ]
    for refusal in refusals:
        assert "--force" not in refusal.text() and " -o" not in refusal.text()
