"""QA 19b: files and I/O abuse, end to end (``docs/specs/hardening.md`` section 3, H12-H31).

Every M24 open case goes through the three doors a hostile file can knock on: the designer
(``open_document`` and ``DesignerApp.open_path``), ``pyguibud-uic --check`` and ``load_ui``.
Each must refuse with a translated reason in under a second, without a traceback and without
leaving anything behind. The save cases use a real lock (an open handle), a real deny ACL
(Windows), a simulated full disk and real external changes; the original file and its ``.bak``
must survive every failure. One ``slow`` test kills a real designer process and checks that the
next start offers the autosave. Open findings are strict xfails ``QA-19b-NN``.
"""

from __future__ import annotations

import errno
import functools
import os
import queue
import shutil
import string
import subprocess
import sys
import textwrap
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.codegen._errors import M_STREAM_NAME
from pyguibud.codegen.output import check_output
from pyguibud.core import XmlIoError, dump_ui, read_ui, read_ui_bytes, write_ui
from pyguibud.core.errors import PyGUIbudError
from pyguibud.designer import export as ex
from pyguibud.designer import preview_tk
from pyguibud.designer import settings as settings_module
from pyguibud.designer.files import open_document
from pyguibud.designer.settings import Settings, load_settings, save_settings
from pyguibud.uic import main as uic_main
from pyguibud_runtime import load_ui
from pyguibud_runtime.errors import UiError
from tests.conftest import BUDGET_FACTOR, reset_root, under_coverage

ROOT = Path(__file__).resolve().parents[2]
HELLO = ROOT / "examples" / "hello.ui"
FAST = 1.0  # seconds: the acceptance budget of every M24 case
TARGETS = ("es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR")
HEAD = b'<?xml version="1.0" encoding="UTF-8"?>\n'
WINDOWS = sys.platform == "win32"


@pytest.fixture(autouse=True)
def private_profile(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settings and recovery data go to temporary folders, never the real profile."""
    base = tmp_path_factory.mktemp("profile19b")
    monkeypatch.setenv("PYGUIBUD_CONFIG_DIR", str(base / "config"))
    monkeypatch.setenv("PYGUIBUD_STATE_DIR", str(base / "state"))


def residue(folder: Path) -> list[str]:
    """Temporary files a writer left behind."""
    return sorted(p.name for p in folder.iterdir() if p.name.startswith("~pgb") or ".tmp" in p.name)


def timed(action: Callable[[], object]) -> tuple[object, float]:
    started = time.perf_counter()
    result = action()
    return result, time.perf_counter() - started


# ================================================================ H12/H13: the open matrix
def _fifty_mb(path: Path) -> None:
    with path.open("wb") as stream:
        stream.write(HEAD + b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">')
        chunk = b"<a>" * (1 << 20)
        for _ in range(17):  # 51 MiB of <a>
            stream.write(chunk)
    # Real-time antivirus scans a fresh file on its first open (~2 s for 51 MiB on Windows),
    # inside the timed refusal. Open it once here so the budget measures PyGUIbud only.
    with path.open("rb") as stream:
        stream.read(1)


_HELLO = HELLO.read_bytes()
_BAD: dict[str, Callable[[Path], object]] = {
    "empty": lambda p: p.write_bytes(b""),
    "renamed-png": lambda p: p.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 40),
    "truncated": lambda p: p.write_bytes(_HELLO[: len(_HELLO) // 2]),
    "entity-bomb": lambda p: p.write_bytes(
        b'<?xml version="1.0"?><!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
        b'<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;"><!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>'
        b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">&c;</pyguibud-ui>'
    ),
    "external-dtd": lambda p: p.write_bytes(
        b'<?xml version="1.0"?><!DOCTYPE pyguibud-ui SYSTEM "http://127.0.0.1:9/x.dtd">'
        b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"/>'
    ),
    "external-entity": lambda p: p.write_bytes(
        b'<?xml version="1.0"?><!DOCTYPE p [<!ENTITY x SYSTEM "file:///C:/Windows/win.ini">]>'
        b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">&x;</pyguibud-ui>'
    ),
    "wrong-root": lambda p: p.write_bytes(HEAD + b'<html xmlns="urn:pyguibud:ui:1"/>'),
    "qt-designer-ui": lambda p: p.write_bytes(HEAD + b'<ui version="4.0"><class>Form</class></ui>'),
    "newer-major": lambda p: p.write_bytes(
        _HELLO.replace(b'schema_version="1.0"', b'schema_version="2.0"')
    ),
    "latin-1": lambda p: p.write_bytes(
        _HELLO.replace(b"Hello PyGUIbud", "Olá ção".encode("latin-1"))
    ),
    "utf-16": lambda p: p.write_bytes(_HELLO.decode("utf-8").encode("utf-16")),
    "fifty-mb-of-a": _fifty_mb,
    "deleted": lambda p: None,  # never created: deleted between the picker and the read
    "folder": lambda p: p.mkdir(),
}


@pytest.fixture(params=sorted(_BAD))
def hostile(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    name: str = request.param
    folder = tmp_path / ("Ação 😀 ü" if name in {"truncated", "empty"} else "plain")
    folder.mkdir()
    path = folder / f"{name} 😀.ui" if name == "truncated" else folder / f"{name}.ui"
    _BAD[name](path)
    return path


def test_m24_hostile_file_is_refused_by_every_door_with_a_translated_reason(
    hostile: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = sorted(hostile.parent.iterdir())
    budget = FAST * (BUDGET_FACTOR if hostile.name.startswith("fifty") else 1)

    # 1. the designer's reader
    def designer() -> PyGUIbudError:
        with pytest.raises(PyGUIbudError) as info:
            open_document(hostile)
        return info.value

    error, seconds = timed(designer)
    assert isinstance(error, PyGUIbudError) and seconds < budget, seconds
    english = str(error)
    assert english and "Traceback" not in english and "{" not in english

    # 2. pyguibud-uic --check
    code, seconds = timed(lambda: uic_main(["--check", str(hostile)]))
    out = capsys.readouterr()
    assert code == 1 and seconds < budget, (code, seconds)
    assert "error:" in out.err and "Traceback" not in out.err + out.out

    # 3. the runtime: refused before any toolkit is touched
    def runtime() -> UiError:
        with pytest.raises(UiError) as info:
            load_ui(hostile)
        return info.value

    ui_error, seconds = timed(runtime)
    assert isinstance(ui_error, UiError) and seconds < budget
    assert ui_error.code not in {"runtime.root_exists", "runtime.build_failed"}

    # nothing was written next to the file
    assert sorted(hostile.parent.iterdir()) == before

    # the reason is translated in every target language and in the pseudo-locale
    for language in TARGETS:
        i18n.set_language(language)
        assert str(error) != english, (language, english)
    i18n.set_language(i18n.PSEUDO_LANGUAGE)
    assert str(error) != english


def test_a_newer_minor_file_opens_read_only_everywhere(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "minor.ui"
    path.write_bytes(_HELLO.replace(b'schema_version="1.0"', b'schema_version="1.9"'))
    opened = open_document(path)
    assert opened.read_only_reason is not None
    assert uic_main(["--check", str(path)]) == 0
    assert "warning:" in capsys.readouterr().err


def test_uic_check_survives_a_cp1252_console_and_an_emoji_path(tmp_path: Path) -> None:
    folder = tmp_path / "Ação 😀"
    folder.mkdir()
    good, bad = folder / "góod 😀.ui", folder / "bäd 😀.ui"
    shutil.copyfile(HELLO, good)
    bad.write_bytes(b"")
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "PYGUIBUD_LANG": "de_DE"}
    for path, expected in ((good, 0), (bad, 1)):
        run = subprocess.run(
            [sys.executable, "-m", "pyguibud.uic", "--check", str(path)],
            capture_output=True, env=env, timeout=60, check=False,
        )  # fmt: skip
        assert run.returncode == expected, run.stderr
        assert b"Traceback" not in run.stderr + run.stdout


# ================================================================ designer fixtures (GUI)
@pytest.fixture
def app(tk_root: Any) -> Iterator[Any]:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.recovery import RecoverySession

    reset_root(tk_root)
    recovery = RecoverySession()
    recovery.start()
    designer = DesignerApp(tk_root, settings=Settings(), recovery=recovery)
    designer.exits = []  # type: ignore[attr-defined]
    designer.on_exit = lambda: designer.exits.append(True)  # type: ignore[attr-defined]
    yield designer
    tk_root.protocol("WM_DELETE_WINDOW", tk_root.destroy)
    designer.set_theme("light")
    designer.flush_theme()
    designer.dispose()
    recovery.close()
    reset_root(tk_root)


@pytest.fixture
def hello(tmp_path: Path) -> Path:
    folder = tmp_path / "work"
    folder.mkdir()
    copy = folder / "hello.ui"
    shutil.copyfile(HELLO, copy)
    (folder / "hello.ui.bak").write_bytes(b"EARLIER BACKUP")
    return copy


def edit(designer: Any, text: str = "Edited 19b") -> None:
    from pyguibud.core import Widget
    from pyguibud.core.commands import SetProp
    from pyguibud.core.model import Prop

    session = designer.session
    label = next(
        n for n in session.document.walk() if isinstance(n, Widget) and n.class_name == "Label"
    )
    assert session.stack.execute(SetProp(label, Prop(name="text", value=text))).accepted


def dialog(designer: Any) -> Any:
    live = designer._live_dialogs()
    assert live, "no dialog is open"
    return live[-1]


def dialog_text(designer: Any) -> str:
    return str(dialog(designer).label.cget("text"))


def close_dialogs(designer: Any) -> None:
    for box in designer._live_dialogs():
        box.close()


# ================================================================ H12: open in the designer
@pytest.mark.gui
def test_m24_designer_open_refuses_each_hostile_file_and_keeps_the_open_document(
    app: Any, hello: Path, tmp_path: Path
) -> None:
    assert app.open_path(hello)
    edit(app)
    for name, build in sorted(_BAD.items()):
        target = tmp_path / f"bad-{name}.ui"
        build(target)
        opened, seconds = timed(functools.partial(app.open_path, target))
        budget = FAST * (BUDGET_FACTOR if name.startswith("fifty") else 1)
        assert opened is False and seconds < budget, (name, seconds)
        text = dialog_text(app)
        assert text and "Traceback" not in text and "{" not in text, (name, text)
        close_dialogs(app)
        assert app.session.path == hello and app.session.dirty, name  # nothing lost


# ================================================================ H14: saving
@pytest.mark.gui
def test_m24_save_onto_a_file_held_open_by_another_program(
    app: Any, hello: Path, request: pytest.FixtureRequest
) -> None:
    """A real lock: an open handle without FILE_SHARE_DELETE makes the replace fail (Windows)."""
    if not WINDOWS:
        pytest.skip("an open handle locks a file only on Windows")
    original = hello.read_bytes()
    app.open_path(hello)
    edit(app)
    with hello.open("rb"):
        _, seconds = timed(app.save)
        text = dialog_text(app)
    assert seconds < FAST * (BUDGET_FACTOR if under_coverage(request.config) else 1), seconds
    assert "The file could not be saved: " in text and not text.endswith(": "), text
    assert "Traceback" not in text
    assert hello.read_bytes() == original
    assert (hello.parent / "hello.ui.bak").read_bytes() == original  # a whole copy, never half
    assert residue(hello.parent) == [] and app.session.dirty


@pytest.mark.gui
def test_m24_save_when_the_disk_fills_up_while_writing(
    app: Any, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = hello.read_bytes()
    app.open_path(hello)
    edit(app)

    def full(_fd: int) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    with monkeypatch.context() as patch:  # never undo the profile redirection
        patch.setattr(os, "fsync", full)  # the temporary file exists, half written
        _, seconds = timed(app.save)
    assert seconds < FAST
    assert "No space left on device" in dialog_text(app)
    assert hello.read_bytes() == original
    assert (hello.parent / "hello.ui.bak").read_bytes() == b"EARLIER BACKUP"  # not reached
    assert residue(hello.parent) == [] and app.session.dirty


@pytest.fixture
def denied_folder(tmp_path: Path) -> Iterator[Path]:
    """A folder whose ACL denies creating files and folders to the current user (Windows)."""
    if not WINDOWS:
        pytest.skip("Windows ACLs (icacls)")
    from tests.qa.test_step15b_real_acl import _icacls, _user

    folder = tmp_path / "denied"
    folder.mkdir()
    shutil.copyfile(HELLO, folder / "hello.ui")
    (folder / "hello.ui.bak").write_bytes(b"EARLIER BACKUP")
    user = _user()
    _icacls(folder, "/deny", f"{user}:(WD,AD)")
    try:
        yield folder / "hello.ui"
    finally:
        _icacls(folder, "/remove:d", user)


@pytest.mark.gui
def test_m24_save_into_a_read_only_folder(
    app: Any, denied_folder: Path, request: pytest.FixtureRequest
) -> None:
    original = denied_folder.read_bytes()
    app.open_path(denied_folder)
    edit(app)
    _, seconds = timed(app.save)
    assert seconds < FAST * (BUDGET_FACTOR if under_coverage(request.config) else 1), seconds
    text = dialog_text(app)
    assert "The file could not be saved: " in text, text
    assert denied_folder.read_bytes() == original
    assert (denied_folder.parent / "hello.ui.bak").read_bytes() == b"EARLIER BACKUP"
    assert residue(denied_folder.parent) == [] and app.session.dirty


@pytest.mark.gui
def test_m24_a_file_changed_externally_is_kept_in_the_bak_when_overwritten(
    app: Any, hello: Path
) -> None:
    app.open_path(hello)
    edit(app)
    theirs = hello.read_bytes().replace(b"Ready", b"Theirs")
    hello.write_bytes(theirs)
    app.save()
    assert "was changed by another program" in dialog_text(app)
    dialog(app).press(0)  # Overwrite
    assert b"Edited 19b" in hello.read_bytes()
    assert (hello.parent / "hello.ui.bak").read_bytes() == theirs  # their work is recoverable
    assert residue(hello.parent) == [] and not app.session.dirty


@pytest.mark.gui
def test_m24_a_file_deleted_while_open_asks_and_can_be_written_again(app: Any, hello: Path) -> None:
    app.open_path(hello)
    edit(app)
    hello.unlink()
    app.save()
    assert "was changed by another program" in dialog_text(app)
    dialog(app).press(0)  # Overwrite
    assert b"Edited 19b" in hello.read_bytes()
    assert residue(hello.parent) == [] and not app.session.dirty


@pytest.mark.gui
def test_m24_save_as_onto_a_folder_named_like_a_ui_file(
    app: Any, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pyguibud.designer.dialogs import files as file_dialogs

    folder = hello.parent / "trap.ui"
    folder.mkdir()
    app.open_path(hello)
    edit(app)
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(folder))
    app.save(as_new=True)
    text = dialog_text(app)
    assert "Traceback" not in text and text, text
    assert folder.is_dir() and list(folder.iterdir()) == []
    assert residue(hello.parent) == [] and app.session.dirty and app.session.path == hello


@pytest.mark.gui
def test_m24_save_twice_on_an_emoji_path_keeps_a_bak(app: Any, tmp_path: Path) -> None:
    folder = tmp_path / "Ação 😀 ü"
    folder.mkdir()
    path = folder / "olá 😀.ui"
    shutil.copyfile(HELLO, path)
    app.open_path(path)
    edit(app, "first")
    app.save()
    edit(app, "second")
    app.save()
    assert not app._live_dialogs() and not app.session.dirty
    assert b"second" in path.read_bytes() and b"first" in (folder / "olá 😀.ui.bak").read_bytes()
    assert residue(folder) == []


def _save_as_onto(app: Any, hello: Path, target: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    from pyguibud.designer.dialogs import files as file_dialogs

    app.open_path(hello)
    edit(app)
    monkeypatch.setattr(file_dialogs, "ask_save", lambda *_a: str(target))
    app.save(as_new=True)
    live = app._live_dialogs()
    return str(live[-1].label.cget("text")) if live else ""


_QT_FORM = b'<?xml version="1.0" encoding="UTF-8"?>\n<ui version="4.0"><class>Form</class></ui>\n'
_README = b'# Notes\n\n```xml\n<pyguibud-ui schema_version="1.0">\n```\nMy precious notes.\n'


@pytest.mark.gui
@pytest.mark.parametrize(
    ("name", "content"),
    [("form.ui", _QT_FORM), ("README.md", _README)],
    ids=["qt-designer-form", "readme-quoting-the-root"],
)
def test_qa19b_03_save_as_never_replaces_a_foreign_file(
    app: Any, hello: Path, monkeypatch: pytest.MonkeyPatch, name: str, content: bytes
) -> None:
    target = hello.parent / name
    target.write_bytes(content)
    text = _save_as_onto(app, hello, target, monkeypatch)
    assert target.read_bytes() == content, text


# ================================================================ residuals (fixed in 19b)
def test_qa19b_01_a_252_character_name_can_be_saved_twice(tmp_path: Path) -> None:
    # '<name>.bak' would be 256 characters: the backup's name is shortened, the file's is not.
    document = read_ui(HELLO).document
    path = tmp_path / ("a" * 249 + ".ui")
    assert len(path.name) == 252
    write_ui(document, path)
    try:
        write_ui(document, path)  # the second save needs the .bak
    finally:
        assert residue(tmp_path) == []
        assert path.read_bytes() == dump_ui(document)
    assert (tmp_path / ("a" * 249 + ".u.bak")).read_bytes() == dump_ui(document)


def test_qa19b_02_a_full_disk_while_copying_the_bak_keeps_a_whole_bak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, path)
    bak = tmp_path / "hello.ui.bak"
    bak.write_bytes(b"EARLIER BACKUP")
    original = path.read_bytes()

    def half_copy(src: Any, dst: Any, **_k: Any) -> None:  # what copyfile does on POSIX
        with open(src, "rb") as source, open(dst, "wb") as target:
            target.write(source.read(40))
            raise OSError(errno.ENOSPC, "No space left on device")

    document = read_ui(path).document
    with monkeypatch.context() as patch, pytest.raises(XmlIoError):
        patch.setattr(shutil, "copy2", half_copy)  # the module xml_io uses
        write_ui(document, path)
    assert path.read_bytes() == original and residue(tmp_path) == []
    assert bak.read_bytes() in {b"EARLIER BACKUP", original}, bak.read_bytes()[:60]


# ================================================================ H16/H25: quitting
@pytest.mark.gui
def test_quit_with_unsaved_work_and_failing_settings_never_loses_the_work(
    app: Any, hello: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.open_path(hello)
    app.bind_close()
    edit(app)

    def full(*_a: Any, **_k: Any) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(settings_module, "write_atomic", full)
    root = app.root
    root.tk.call(root.protocol("WM_DELETE_WINDOW"))  # the X button / Alt+F4
    assert "hello.ui" in dialog_text(app)
    dialog(app).press(1)  # Don't save
    assert "No space left on device" in dialog_text(app)
    dialog(app).press(1)  # Cancel: stay
    assert app.exits == [] and app.session.dirty and not app._live_dialogs()
    app.registry.invoke("file.quit")  # asks again, the work is still there
    assert "hello.ui" in dialog_text(app)
    dialog(app).press(0)  # Save: the document is written, then the settings fail again
    assert b"Edited 19b" in hello.read_bytes() and not app.session.dirty
    assert "No space left on device" in dialog_text(app)
    dialog(app).press(0)  # Quit anyway
    assert app.exits == [True]


@pytest.mark.gui
def test_qa19b_04_the_settings_failure_at_quit_reads_as_sentences(
    app: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app.start()

    def denied(*_a: Any, **_k: Any) -> None:
        raise PermissionError(errno.EACCES, "Access is denied")  # Windows: no full stop

    def unserialisable(*_a: Any, **_k: Any) -> None:
        raise TypeError("Object of type set is not JSON serializable")  # a fork's extras

    monkeypatch.setattr(settings_module, "write_atomic", denied)
    app.quit()
    text = dialog_text(app)
    close_dialogs(app)
    monkeypatch.setattr(settings_module, "write_atomic", unserialisable)
    app.quit()
    python = dialog_text(app)
    close_dialogs(app)
    assert "JSON" not in python and "cannot be read or written. Quit" in python, python
    # Settings that could not be read at start-up and still cannot (a folder cannot be opened
    # for reading): save_settings returns False without recording an OS reason.
    app.settings.unread = True
    monkeypatch.setattr(settings_module, "settings_path", lambda: tmp_path)
    app.quit()
    empty = dialog_text(app) if app._live_dialogs() else ""
    assert "Access is denied. Quit anyway?" in text, text
    assert ":  " not in empty and "cannot be read or written. Quit" in empty, empty


# ================================================================ H15: kill -> restart -> recovery
_CHILD = textwrap.dedent(
    """
    import sys
    from pathlib import Path
    from ttkbootstrap import App
    from pyguibud.core import Widget
    from pyguibud.core.commands import SetProp
    from pyguibud.core.model import Prop
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.recovery import RecoverySession
    from pyguibud.designer.settings import Settings

    root = App(title="qa19b")
    root.withdraw()
    recovery = RecoverySession()
    recovery.start()
    app = DesignerApp(root, settings=Settings(), recovery=recovery)
    if sys.argv[1] == "edit":
        app.open_path(Path(sys.argv[2]))
        label = next(n for n in app.session.document.walk()
                     if isinstance(n, Widget) and n.class_name == "Label")
        app.session.stack.execute(SetProp(label, Prop(name="text", value="Unsaved 19b work")))
        print("READY", recovery.autosave(app.session, force=True), flush=True)
        root.mainloop()  # until killed
    else:
        from pyguibud.designer.dialogs.recovery import RecoveryDialog
        app.start()
        offers = [d for d in app._live_dialogs() if isinstance(d, RecoveryDialog)]
        entries = [e for d in offers for e in d._entries.values()]
        print("OFFERS", len(offers))
        for entry in entries:
            snapshot = (entry.folder / "document.ui").read_bytes()
            print("ENTRY", entry.name, b"Unsaved 19b work" in snapshot, flush=True)
        app.dispose()
        recovery.close()
        root.destroy()
    """
)


def _readline(process: subprocess.Popen[str], seconds: float) -> str:
    lines: queue.Queue[str] = queue.Queue()
    stream = process.stdout
    assert stream is not None
    threading.Thread(target=lambda: lines.put(stream.readline()), daemon=True).start()
    try:
        return lines.get(timeout=seconds)
    except queue.Empty:
        return ""


@pytest.mark.slow
def test_m24_killing_the_designer_mid_edit_offers_the_autosave_at_the_next_start(
    tmp_path: Path,
) -> None:
    ui = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, ui)
    original = ui.read_bytes()
    env = {
        **os.environ,
        "PYGUIBUD_CONFIG_DIR": str(tmp_path / "config"),
        "PYGUIBUD_STATE_DIR": str(tmp_path / "state"),
        "PYTHONPATH": str(ROOT),
        "PYTHONIOENCODING": "utf-8",
    }
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    victim = subprocess.Popen(
        [sys.executable, str(script), "edit", str(ui)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )  # fmt: skip
    try:
        line = _readline(victim, 60)
        assert line.startswith("READY None"), (line, victim.poll())
    finally:
        victim.kill()  # TerminateProcess / SIGKILL: no clean-up runs
        victim.wait(10)
    assert ui.read_bytes() == original  # the kill never touched the user's file
    restart = subprocess.run(
        [sys.executable, str(script), "start"],
        capture_output=True, text=True, env=env, timeout=120, check=False,
    )  # fmt: skip
    assert restart.returncode == 0, restart.stderr[-2000:]
    assert "Traceback" not in restart.stderr
    assert "OFFERS 1" in restart.stdout, restart.stdout
    assert "ENTRY hello.ui True" in restart.stdout, restart.stdout


# ================================================================ breaking the new code
def test_sweep_stale_with_forged_names_live_pids_and_a_junction(tmp_path: Path) -> None:
    base = tmp_path / "temp"
    base.mkdir()
    old = time.time() - 3 * 86_400
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        keep = {
            f"pyguibud-preview-{os.getpid()}-deadbeef",  # ours
            f"pyguibud-preview-run-{child.pid}-deadbeef",  # a live designer
            "pyguibud-preview-0-deadbeef",  # no pid a designer writes
            "pyguibud-preview-4294967295-deadbeef",
        }
        gone = {
            "pyguibud-preview-abc_12xy",  # an old mkdtemp name
            "pyguibud-preview-99999999999-deadbeef",  # 11 digits
            "pyguibud-preview-12-DEADBEEF",  # not the hex we write
            "pyguibud-preview-1-deadbeef-extra",
        }
        for name in keep | gone:
            (base / name).mkdir()
            (base / name / "x.ui").write_text("x", encoding="utf-8")
            os.utime(base / name, (old, old))
        young = base / "pyguibud-preview-young"
        young.mkdir()
        outside = tmp_path / "precious"
        outside.mkdir()
        (outside / "keep.txt").write_text("mine", encoding="utf-8")
        os.utime(outside, (old, old))
        if WINDOWS:
            junction = base / "pyguibud-preview-junction"
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                check=True, capture_output=True,
            )  # fmt: skip
        _, seconds = timed(lambda: preview_tk.sweep_stale(base))
        left = {p.name for p in base.iterdir()}
        assert keep <= left, keep - left
        assert not (gone & left), gone & left
        assert young.name in left
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "mine"  # never followed
        assert seconds < FAST
    finally:
        child.kill()
        child.wait(10)
    preview_tk.sweep_stale(base)  # the designer is gone now
    assert f"pyguibud-preview-run-{child.pid}-deadbeef" not in {p.name for p in base.iterdir()}


def _two_instances() -> tuple[Settings, Settings]:
    return load_settings()[0], load_settings()[0]


def test_two_instances_keep_each_others_plugin_toggles_over_several_saves() -> None:
    first, second = _two_instances()
    second.disabled_plugins = ("acme",)
    assert save_settings(second)  # second disables acme
    assert save_settings(first)  # first: nothing toggled (opening a recent file)
    assert save_settings(first)  # ... and once more (Quit)
    assert load_settings()[0].disabled_plugins == ("acme",)
    third = load_settings()[0]
    third.disabled_plugins = ()  # a third designer enables it again
    assert save_settings(third)
    assert save_settings(second) and save_settings(first)
    assert load_settings()[0].disabled_plugins == ()


@pytest.mark.parametrize(
    "raw",
    [
        b'{"disabled_plugins": "acme"}',
        b'{"disabled_plugins": [1, 2]}',
        b'{"disabled_plugins": ["acme", 3]}',
        b'{"disabled_plugins": null}',
    ],
    ids=["a-string", "numbers", "a-mixed-list", "null"],
)
def test_qa19b_05_a_malformed_list_on_disk_never_re_enables_a_plugin(raw: bytes) -> None:
    mine = load_settings()[0]
    mine.disabled_plugins = ("acme",)
    assert save_settings(mine)  # acme disabled and on disk
    settings_module.settings_path().write_bytes(raw)  # a hand edit gone wrong
    assert save_settings(mine)
    assert load_settings()[0].disabled_plugins == ("acme",)


@pytest.mark.parametrize("raw", [b'{"disabled_plugins": ["acme"', b"\x00\x01", b"null", b"[]"])
def test_a_corrupt_settings_file_keeps_this_instances_disabled_plugins(raw: bytes) -> None:
    mine = load_settings()[0]
    mine.disabled_plugins = ("acme",)
    assert save_settings(mine)
    settings_module.settings_path().write_bytes(raw)
    assert save_settings(mine)
    assert load_settings()[0].disabled_plugins == ("acme",)


@pytest.mark.skipif(not WINDOWS, reason="NTFS alternate data streams")
@pytest.mark.parametrize(
    "output",
    [
        "\\\\?\\C:\\x\\a.py:evil",
        "\\\\?\\UNC\\srv\\share\\a.py:x",
        "\\\\srv\\share\\a.py:x",
        "\\\\.\\C:\\a.py:x",
        "//?/C:/x/a.py:evil",
        "C:/x/a.py:evil",
        "C:a.py:x",
        "a.py::$DATA",
        "a.py:",
    ],
)
def test_every_spelling_of_a_stream_name_is_refused(output: str) -> None:
    assert check_output(output, [], []) == M_STREAM_NAME


@pytest.mark.skipif(not WINDOWS, reason="NTFS alternate data streams")
def test_uic_names_the_stream_path_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ui = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, ui)
    target = tmp_path / "a.py:evil"
    assert uic_main([str(ui), "-o", str(target)]) == 1
    err = capsys.readouterr().err
    assert str(target) in err and "{output}" not in err and "Traceback" not in err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hello.ui"]


_UNC = ("\\\\198.51.100.7\\share\\x.ui", "//198.51.100.7/share/x.ui")


def _network(path: Any) -> bool:
    return str(os.fspath(path)).startswith(("\\\\", "//"))


@pytest.mark.parametrize("path", _UNC)
def test_the_designer_refuses_a_network_path_at_once(path: str) -> None:
    started = time.perf_counter()
    with pytest.raises(PyGUIbudError) as opened:
        open_document(path)
    assert opened.value.code == "files.network_path"
    assert time.perf_counter() - started < FAST


# QA-19b-08 (ruling): the CLI refuses network paths at once, like the designer. load_ui, the
# runtime library API, may load from a share on purpose (runtime.md section 16).
@pytest.mark.skipif(not WINDOWS, reason="SMB paths")
@pytest.mark.parametrize("path", _UNC)
def test_qa19b_08_uic_refuses_a_network_path_without_contacting_it(
    path: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import pyguibud.uic as uic_module

    touched: list[object] = []
    real_exists = os.path.exists

    def exists(candidate: Any) -> bool:
        if _network(candidate):
            touched.append(candidate)  # instead of a 42 s SMB time-out
            return False
        return real_exists(candidate)

    def read(candidate: Any, *_a: Any, **_k: Any) -> Any:
        assert not _network(candidate), "read_ui opened a network path"
        return read_ui(candidate)

    monkeypatch.setattr(os.path, "exists", exists)
    monkeypatch.setattr(uic_module, "read_ui", read)
    assert uic_main(["--check", path]) == 1
    assert not touched, touched
    assert "Network and device paths cannot be opened." in capsys.readouterr().err


def test_designer_export_refuses_a_stream_name_with_its_own_wording(tmp_path: Path) -> None:
    from pyguibud.designer.files import FileStamp

    ui = tmp_path / "hello.ui"
    shutil.copyfile(HELLO, ui)
    source = ex.ExportSource(ui, False, FileStamp.of(ui))
    for output in ("hello_ui.py:evil", str(tmp_path / "x.py:evil")):
        result = ex.export_plan(source, ex.ExportRequest(output, None))
        assert isinstance(result, ex.Refusal), output
        assert "{" not in result.text() and "Traceback" not in result.text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["hello.ui"]


_NS = '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" {decl}>{body}</pyguibud-ui>'
_TB = 'xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1"'


def _ns_doc(decl: str, body: str) -> bytes:
    return HEAD + _NS.format(decl=decl, body=body).encode()


def test_a_tb_prefix_rebound_anywhere_never_means_ttkbootstrap() -> None:
    cases = {
        "nested": _ns_doc(
            _TB,
            '<window id="main" kind="main" xmlns:tb="urn:evil" tb:x="1"><layout type="pack"/>'
            "</window>",
        ),
        "root-with-alias": _ns_doc(
            'xmlns:tb="urn:evil" xmlns:t2="urn:pyguibud:ext:ttkbootstrap:1"',
            '<window id="main" kind="main" tb:x="1"><layout type="pack"/>'
            '<widget class="Button" id="b" t2:bootstyle="danger"><pack/></widget></window>',
        ),
    }
    for name, data in cases.items():
        result = read_ui_bytes(data)
        saved = dump_ui(result.document)
        assert dump_ui(read_ui_bytes(saved).document) == saved, name  # byte-stable
        assert b'xmlns:tb="urn:evil"' not in saved, name
        assert b'tb:x="1"' not in saved, name  # the foreign attribute moved prefix
    # tb bound to an unusable value is plain malformed XML, refused with a reason
    for decl in ('xmlns:tb=""', 'xmlns:xml="urn:evil"'):
        with pytest.raises(XmlIoError) as info:
            read_ui_bytes(
                _ns_doc(decl, '<window id="main" kind="main"><layout type="pack"/></window>')
            )
        assert info.value.code == "xml.malformed"


def test_qa19b_06_a_nested_tb_rebinding_is_reported() -> None:
    data = _ns_doc(
        _TB,
        '<window id="main" kind="main" xmlns:tb="urn:evil" tb:x="1"><layout type="pack"/></window>',
    )
    assert "xml.foreign_prefix" in [w.code for w in read_ui_bytes(data).warnings]


# ================================================================ the new messages, every locale
def _new_messages() -> dict[str, dict[str, object]]:
    from pyguibud.designer import app as app_module
    from pyguibud.designer import files, recovery

    foreign = read_ui_bytes(
        _ns_doc(
            'xmlns:tb="urn:evil"', '<window id="main" kind="main"><layout type="pack"/></window>'
        )
    ).warnings
    prefix = next(w for w in foreign if w.code == "xml.foreign_prefix")
    return {
        files._M_NOT_UI: {"name": "notes.txt"},
        M_STREAM_NAME: {"output": "a.py:evil"},
        ex.M_NO_FOLDER: {"folder": "C:\\nowhere"},
        ex.M_BAD_CHARS: {"name": "a|b.py"},
        ex.M_POT_SUFFIX: {"name": "hello.txt"},
        app_module._M_SETTINGS_NOT_SAVED_AT_QUIT: {"reason": "Disk full."},
        app_module._M_QUIT: {},
        app_module._M_SETTINGS_FILE_FAILED: {},
        recovery._M_AUTOSAVE_RECOVERED: {},
        prefix.msgid: dict(prefix.params),
    }


def _fields(text: str) -> set[str]:
    return {f for _, f, _, _ in string.Formatter().parse(text) if f is not None}


def test_every_new_19b_message_is_translated_with_its_placeholders_in_every_locale() -> None:
    messages = _new_messages()
    for language in (*TARGETS, i18n.SOURCE_LANGUAGE, i18n.PSEUDO_LANGUAGE):
        i18n.set_language(language)
        for msgid, params in messages.items():
            text = i18n.gettext(msgid)
            assert _fields(text) == _fields(msgid), (language, msgid, text)
            assert text.format(**params)
            if language in TARGETS:  # a context key ("dialog\x04_Quit") falls back to "_Quit"
                assert text != msgid.rpartition("\x04")[2], (language, msgid)


def _mnemonic(msgid: str) -> str:
    text = i18n.gettext(msgid)
    return text.split("_", 1)[1][:1].lower() if "_" in text else ""


@pytest.mark.parametrize(
    "language",
    [
        # QA-19b-07: the button has its own msgid (context "dialog"), not the menu's "_Quit"
        # (Dutch '_Afsluiten' shared the key A with '_Annuleren').
        *TARGETS,
        i18n.SOURCE_LANGUAGE,
        i18n.PSEUDO_LANGUAGE,
    ],
)
def test_the_quit_anyway_buttons_have_distinct_access_keys(language: str) -> None:
    from pyguibud.designer import app as app_module

    i18n.set_language(language)
    keys = [_mnemonic(app_module._M_QUIT), _mnemonic(app_module._M_CANCEL)]
    assert all(keys) and keys[0] != keys[1], (language, keys)
