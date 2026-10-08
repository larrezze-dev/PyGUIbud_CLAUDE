"""designer.files: stamps, open, the save plan, path rebasing, recent files (spec section 9)."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyguibud.core import (
    MAX_UI_BYTES,
    CommandStack,
    Include,
    XmlIoError,
    default_registry,
    dump_ui,
    read_ui_string,
)
from pyguibud.designer import files
from pyguibud.designer.files import (
    MAX_RECENT,
    FileError,
    FileStamp,
    RecentFiles,
    open_document,
    rebase_paths,
    save_plan,
    write_atomic,
)

UI = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="{version}" xmlns="urn:pyguibud:ui:1">
  <meta source_locale="en_GB"/>
  <resources>
    <image id="img_logo" src="{image}"/>
  </resources>
  <window id="main" kind="main">
    <layout type="grid"/>
    <widget class="Label" id="lbl_a"><cell row="0" column="0"/></widget>
    <include id="inc_a" src="{include}" component="cmp"><cell row="1" column="0"/></include>
  </window>
</pyguibud-ui>
"""


def ui(image: str = "icons/logo.png", include: str = "parts/comp.ui", version: str = "1.0") -> str:
    return UI.format(image=image, include=include, version=version)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def include_of(document: object) -> Include:
    return next(n for n in document.walk() if isinstance(n, Include))  # type: ignore[attr-defined]


# ---------------------------------------------------------------- stamps and atomic writes
def test_stamp_of_missing_file_is_none(tmp_path: Path) -> None:
    assert FileStamp.of(tmp_path / "nope.ui") is None
    assert FileStamp.of(Path("//server/share/x.ui")) is None


def test_stamp_detects_content_changes_but_not_touches(tmp_path: Path) -> None:
    path = write(tmp_path / "a.ui", "one")
    stamp = FileStamp.of(path)
    assert stamp is not None and stamp.size == 3
    assert stamp.same_stat(path) and not stamp.changed(path)
    os.utime(path, ns=(stamp.mtime_ns + 5_000_000_000,) * 2)
    assert not stamp.same_stat(path)
    assert not stamp.changed(path)  # same bytes: a touch is no conflict
    path.write_text("two!", encoding="utf-8")
    assert stamp.changed(path)
    path.unlink()
    assert stamp.changed(path)


def test_stamp_skips_special_and_oversized_files(tmp_path: Path) -> None:
    assert FileStamp.of(tmp_path) is None
    big = tmp_path / "big.ui"
    with big.open("wb") as stream:
        stream.truncate(MAX_UI_BYTES + 1)  # sparse: cheap to create
    assert FileStamp.of(big) is None
    with pytest.raises(XmlIoError):
        open_document(big)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only")
def test_open_fifo_never_blocks(tmp_path: Path) -> None:  # pragma: no cover - POSIX only
    fifo = tmp_path / "pipe.ui"
    os.mkfifo(fifo)  # type: ignore[attr-defined,unused-ignore]
    assert FileStamp.of(fifo) is None
    with pytest.raises(XmlIoError):
        open_document(fifo)


def test_write_atomic_replaces_and_cleans_up(tmp_path: Path) -> None:
    target = tmp_path / "x.json"
    write_atomic(target, b"1")
    write_atomic(target, b"22")
    assert target.read_bytes() == b"22"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.json"]
    with pytest.raises(OSError):
        write_atomic(tmp_path / "missing" / "x.json", b"1")


# ---------------------------------------------------------------- open
def test_open_refuses_network_paths_before_any_access() -> None:
    with pytest.raises(FileError) as caught:
        open_document("//server/share/main.ui")
    assert caught.value.code == "files.network_path"
    with pytest.raises(FileError):
        open_document("C:/work/CON.ui")


def test_open_reports_reader_errors(tmp_path: Path) -> None:
    with pytest.raises(XmlIoError):
        open_document(tmp_path)  # a directory (A11)
    with pytest.raises(XmlIoError):
        open_document(write(tmp_path / "empty.ui", ""))
    with pytest.raises(XmlIoError):
        open_document(tmp_path / "missing.ui")


def test_open_returns_stamp_and_no_reason(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", ui())
    opened = open_document(path)
    assert opened.path == path.absolute()
    assert opened.stamp == FileStamp.of(path)
    assert opened.read_only_reason is None
    assert not opened.result.read_only


def test_open_newer_minor_is_read_only(tmp_path: Path) -> None:
    opened = open_document(write(tmp_path / "new.ui", ui(version="1.9")))
    assert opened.result.read_only
    assert opened.read_only_reason == files.M_NEWER


@pytest.mark.skipif(getattr(os, "geteuid", lambda: 1)() == 0, reason="root ignores modes")
def test_open_write_protected_file(tmp_path: Path) -> None:
    path = write(tmp_path / "ro.ui", ui())
    os.chmod(path, stat.S_IREAD)
    try:
        assert open_document(path).read_only_reason == files.M_WRITE_PROTECTED
        assert files.write_protected(path)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert not files.write_protected(path)
    assert files.write_protected(tmp_path / "missing" / "x.ui")


# ---------------------------------------------------------------- save plan
def plan_for(path: Path | None, **kwargs: object) -> files.SavePlan:
    document = read_ui_string(ui()).document
    options: dict[str, object] = {
        "path": path,
        "stamp": FileStamp.of(path) if path else None,
        "read_only": False,
        "write_protected": False,
        "error_count": 0,
    }
    options.update(kwargs)
    return save_plan(document, **options)  # type: ignore[arg-type]


def test_plan_untitled_and_write_protected_ask_for_a_target(tmp_path: Path) -> None:
    assert plan_for(None).ask_target
    path = write(tmp_path / "a.ui", ui())
    assert plan_for(path, write_protected=True).ask_target


def test_plan_read_only_is_refused_with_reason(tmp_path: Path) -> None:
    plan = plan_for(None, read_only=True)
    assert plan.refusal == files.M_READ_ONLY and plan.reason == files.M_NEWER
    text = plan.refusal_text()
    assert text is not None and "newer version" in text
    assert plan_for(None, read_only=True, target=tmp_path / "x.ui").refusal is not None
    assert plan_for(None).refusal_text() is None


def test_plan_plain_save_and_conflict(tmp_path: Path) -> None:
    path = write(tmp_path / "a.ui", ui())
    plan = plan_for(path, error_count=2)
    assert plan.target == path and plan.error_count == 2
    assert not plan.conflict and plan.rebase is None and not plan.ask_target
    stamp = FileStamp.of(path)
    path.write_text(ui(image="other.png"), encoding="utf-8")
    assert plan_for(path, stamp=stamp).conflict  # A3


def test_plan_save_as_refusals(tmp_path: Path) -> None:
    path = write(tmp_path / "a.ui", ui())
    assert plan_for(path, target=Path("//srv/share/a.ui")).refusal == files.M_NETWORK
    included = write(tmp_path / "parts" / "comp.ui", ui())
    refused = plan_for(path, target=included)
    assert refused.refusal is not None and refused.target is None  # A18
    alias = tmp_path / "parts" / ".." / "parts" / "COMP.ui"
    if os.path.normcase("A") == "a":
        assert plan_for(path, target=alias).refusal is not None
    backup = tmp_path / "a.ui.bak"
    assert plan_for(path, target=backup).refusal is None  # a normal target


def test_plan_save_as_elsewhere_rebases(tmp_path: Path) -> None:
    path = write(tmp_path / "a.ui", ui())
    plan = plan_for(path, target=tmp_path / "sub" / "b.ui")
    assert plan.target == tmp_path / "sub" / "b.ui"
    assert plan.rebase is not None and not plan.conflict
    assert plan_for(path, target=tmp_path / "c.ui").rebase is None
    assert plan_for(path, target=path).rebase is None


# ---------------------------------------------------------------- rebasing
def test_rebase_relative_paths_and_undo(tmp_path: Path) -> None:
    document = read_ui_string(ui()).document
    stack = CommandStack(document, default_registry())
    before = dump_ui(document)
    command = rebase_paths(document, tmp_path, tmp_path / "deep" / "er")
    assert command is not None and command.text() == "Update file paths"
    assert stack.execute(command).accepted
    assert document.resources["img_logo"].src == "../../icons/logo.png"
    assert include_of(document).src == "../../parts/comp.ui"
    assert stack.undo()
    assert dump_ui(document) == before


def test_rebase_absolute_under_new_base_becomes_relative(tmp_path: Path) -> None:
    image = (tmp_path / "proj" / "img" / "a.png").as_posix()
    outside = (tmp_path / "elsewhere" / "b.ui").as_posix()
    document = read_ui_string(ui(image=image, include=outside)).document
    command = rebase_paths(document, None, tmp_path / "proj")
    assert command is not None
    CommandStack(document, default_registry()).execute(command)
    assert document.resources["img_logo"].src == "img/a.png"
    assert include_of(document).src == outside  # not under the new base: stays absolute


def test_rebase_leaves_this_file_network_and_untitled_relative() -> None:
    document = read_ui_string(ui(image="//srv/x.png", include="#")).document
    assert rebase_paths(document, None, Path("/somewhere")) is None
    plain = read_ui_string(ui()).document
    assert rebase_paths(plain, None, Path("/somewhere")) is None  # untitled: cannot resolve
    assert rebase_paths(plain, Path("/a"), Path("/a")) is None
    dotted = read_ui_string(ui(image="./x.png", include=r"parts\comp.ui")).document
    assert rebase_paths(dotted, Path("/a"), Path("/a/.")) is None  # same folder: untouched


@pytest.mark.skipif(sys.platform != "win32", reason="drive letters are Windows-only")
def test_rebase_other_drive_keeps_absolute() -> None:
    document = read_ui_string(ui()).document
    command = rebase_paths(document, Path("D:/work"), Path("C:/other"))
    assert command is not None
    CommandStack(document, default_registry()).execute(command)
    assert document.resources["img_logo"].src == "D:/work/icons/logo.png"


_SEGMENT = st.sampled_from(["a", "b", "img", "..", "Δ"])


@given(
    src=st.lists(_SEGMENT, min_size=1, max_size=4),
    old=st.lists(_SEGMENT.filter(lambda s: s != ".."), max_size=3),
    new=st.lists(_SEGMENT.filter(lambda s: s != ".."), max_size=3),
)
def test_rebase_keeps_the_resolved_target(src: list[str], old: list[str], new: list[str]) -> None:
    root = os.path.abspath(os.sep + "root")
    old_base = Path(os.path.join(root, *old))
    new_base = Path(os.path.join(root, *new))
    relative = "/".join([*src, "f.png"])
    document = read_ui_string(ui(image=relative)).document
    command = rebase_paths(document, old_base, new_base)
    if command is not None:
        command.apply()
    rebased = document.resources["img_logo"].src
    expected = os.path.normpath(os.path.join(old_base, relative))
    assert os.path.normpath(os.path.join(new_base, rebased)) == expected


# ---------------------------------------------------------------- recent files
def test_recent_files_order_dedupe_and_cap(tmp_path: Path) -> None:
    recent = RecentFiles()
    for index in range(MAX_RECENT + 3):
        recent.add(tmp_path / f"f{index}.ui")
    assert len(recent.entries) == MAX_RECENT
    assert recent.entries[0] == str(tmp_path / f"f{MAX_RECENT + 2}.ui")
    recent.add(tmp_path / "f5.ui")
    assert recent.entries[0] == str(tmp_path / "f5.ui")
    assert len({os.path.normcase(e) for e in recent.entries}) == MAX_RECENT
    if os.path.normcase("A") == "a":
        recent.add(str(tmp_path / "F5.UI"))
        assert sum(os.path.normcase(e).endswith("f5.ui") for e in recent.entries) == 1


def test_recent_files_never_store_network_or_relative_paths(tmp_path: Path) -> None:
    recent = RecentFiles(["//srv/share/a.ui", "relative.ui", str(tmp_path / "ok.ui"), 7])  # type: ignore[list-item]
    assert recent.entries == (str(tmp_path / "ok.ui"),)
    recent.add("//srv/share/b.ui")
    recent.add("\\\\?\\C:\\x.ui")
    assert recent.entries == (str(tmp_path / "ok.ui"),)


def test_recent_files_remove_and_clear_remember_removals(tmp_path: Path) -> None:
    a, b = str(tmp_path / "a.ui"), str(tmp_path / "b.ui")
    recent = RecentFiles([a, b])
    recent.remove(a)
    assert list(recent.entries) == [b]
    assert files.path_key(a) in recent.removed
    recent.clear()
    assert len(recent.entries) == 0
    assert files.path_key(b) in recent.removed
    recent.add(a)
    assert files.path_key(a) not in recent.removed
    recent.remove("//srv/x.ui")  # harmless, never resolved
