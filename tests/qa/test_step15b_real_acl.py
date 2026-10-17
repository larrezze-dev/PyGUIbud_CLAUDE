"""QA 15b pass 2: the QA-15b-01/02 fixes against a real Windows ACL (not a fake ``os.open``).

A scratch folder gets an ``icacls`` deny entry for "create files / create folders" for the
current user, exactly what a standard user meets in ``C:\\Program Files``. Every writer must
refuse at once with the operating system's reason and leave nothing behind. The deny entry is
always removed again, so pytest can delete the folder.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyguibud.codegen.output import write_atomic as write_module
from pyguibud.core import XmlIoError, read_ui, write_ui
from pyguibud.designer import export as ex
from pyguibud.designer.files import FileStamp
from pyguibud.designer.files import write_atomic as write_store
from pyguibud.designer.settings import Settings, save_settings
from pyguibud.uic import main as uic_main

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows ACLs (icacls)")

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
_FAST = 1.0  # seconds


def _user() -> str:
    """The current user as ``*SID`` (works for local, domain and Microsoft accounts)."""
    out = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"], check=True, capture_output=True, text=True
    ).stdout
    return "*" + out.strip().rsplit(",", 1)[-1].strip('"')


def _icacls(*args: object) -> None:
    subprocess.run(["icacls", *map(str, args)], check=True, capture_output=True)


@pytest.fixture
def denied(tmp_path: Path) -> Iterator[Path]:
    folder = tmp_path / "denied"
    folder.mkdir()
    user = _user()
    _icacls(folder, "/deny", f"{user}:(WD,AD)")
    try:
        yield folder
    finally:
        _icacls(folder, "/remove:d", user)


def _refuses_fast(folder: Path, action: Callable[[], object]) -> object:
    start = time.monotonic()
    result = action()
    assert time.monotonic() - start < _FAST
    assert list(folder.iterdir()) == []  # no temporary file left behind
    return result


def _raises(kind: type[BaseException], action: Callable[[], object]) -> Callable[[], str]:
    def run() -> str:
        with pytest.raises(kind) as info:
            action()
        return str(info.value)

    return run


def test_module_writer_refuses_a_real_denied_folder(denied: Path) -> None:
    _refuses_fast(denied, _raises(PermissionError, lambda: write_module(str(denied / "x.py"), "")))


def test_store_writer_refuses_a_real_denied_folder(denied: Path) -> None:
    _refuses_fast(denied, _raises(PermissionError, lambda: write_store(denied / "s.ui", b"x")))


def test_save_refuses_a_real_denied_folder(denied: Path) -> None:
    document = read_ui(EXAMPLES / "hello.ui").document
    _refuses_fast(denied, _raises(XmlIoError, lambda: write_ui(document, denied / "hello.ui")))


def test_save_of_an_existing_file_refuses_when_its_folder_denies_new_files(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "w"
    folder.mkdir()
    target = folder / "hello.ui"
    shutil.copy(EXAMPLES / "hello.ui", target)
    before = target.read_bytes()
    document = read_ui(target).document
    user = _user()
    _icacls(folder, "/deny", f"{user}:(WD,AD)")
    try:
        start = time.monotonic()
        with pytest.raises(XmlIoError):
            write_ui(document, target)
        assert time.monotonic() - start < _FAST
        assert sorted(p.name for p in folder.iterdir()) == ["hello.ui"]
    finally:
        _icacls(folder, "/remove:d", user)
    assert target.read_bytes() == before


def test_settings_refuse_a_real_denied_folder(denied: Path) -> None:
    assert _refuses_fast(denied, lambda: save_settings(Settings(), path=denied / "s.json")) is False


def test_export_reports_a_real_denied_folder(tmp_path: Path, denied: Path) -> None:
    ui = tmp_path / "hello.ui"
    shutil.copy(EXAMPLES / "hello.ui", ui)
    plan = ex.export_plan(
        ex.ExportSource(ui, False, FileStamp.of(ui)),
        ex.ExportRequest(str(denied / "hello_ui.py"), str(denied / "hello.pot")),
    )
    assert isinstance(plan, ex.ExportPlan)
    outcome = _refuses_fast(denied, lambda: ex.run_export(plan))
    assert isinstance(outcome, ex.ExportOutcome)
    assert outcome.written == () and outcome.failure is not None


def test_uic_reports_a_real_denied_folder(
    tmp_path: Path, denied: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ui = tmp_path / "hello.ui"
    shutil.copy(EXAMPLES / "hello.ui", ui)
    for extra in ([], ["--extract"]):
        start = time.monotonic()
        assert uic_main([str(ui), *extra, "-o", str(denied / "out.txt")]) == 1
        assert time.monotonic() - start < 5 * _FAST  # includes generation
        assert "cannot be written" in capsys.readouterr().err
        assert list(denied.iterdir()) == []


def test_qa15b_12_a_long_but_valid_file_name_can_be_saved(tmp_path: Path) -> None:
    target = tmp_path / ("a" * 247 + ".ui")  # 250 characters: valid on NTFS
    shutil.copy(EXAMPLES / "hello.ui", target)
    write_ui(read_ui(target).document, target)
