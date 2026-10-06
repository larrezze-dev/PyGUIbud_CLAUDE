"""Tests for the ``pyguibud-uic`` command line tool."""

from __future__ import annotations

import gettext
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

import pyguibud
from pyguibud import i18n, uic
from pyguibud.core import Finding
from pyguibud.uic import main

ROOT = Path(__file__).parents[1]
HELLO = ROOT / "examples" / "hello.ui"
GOOD = HELLO.read_text("utf-8")
LOCATION = re.compile(r"^(?P<path>.+?):(?P<line>\d+):(?P<col>\d+): (?P<kind>error|warning): ")


@pytest.fixture(autouse=True)
def clean_i18n(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for var in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")
    monkeypatch.setattr(i18n, "_listeners", [])
    monkeypatch.setattr("locale.getlocale", lambda *a, **k: (None, None))
    yield


@pytest.fixture
def write(tmp_path: Path) -> Callable[[str, str | bytes], str]:
    def make(name: str, content: str | bytes) -> str:
        path = tmp_path / name
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return str(path)

    return make


def run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, str, str]:
    code = main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# The seven "honest UAT corruptions": each must exit 1 with ``path:line:col: error:``.
def _delete_a_gt(text: str) -> str:
    return text.replace(
        '<var id="user_name" type="string"/>', '<var id="user_name" type="string"/', 1
    )


CORRUPTIONS: dict[str, Callable[[str], str]] = {
    "delete-gt": _delete_a_gt,
    "bad-int": lambda t: t.replace(
        'row="0" column="0" sticky="w"', 'row="x" column="0" sticky="w"'
    ),
    "duplicate-prop": lambda t: t.replace(
        '<prop name="text" translatable="true">Say hello</prop>',
        '<prop name="text" translatable="true">Say hello</prop>\n'
        '      <prop name="text">twice</prop>',
    ),
    "no-class": lambda t: t.replace(' class="Label" id="lbl_name"', ' id="lbl_name"'),
    "newer-major": lambda t: t.replace('schema_version="1.0"', 'schema_version="2.0"'),
    "doctype": lambda t: t.replace("<pyguibud-ui", "<!DOCTYPE x>\n<pyguibud-ui", 1),
    "no-xmlns": lambda t: t.replace(' xmlns="urn:pyguibud:ui:1"', "", 1),
}


#: Where each corruption of examples/hello.ui is reported (line, column).
POSITIONS = {
    "delete-gt": (5, 39),
    "bad-int": (35, 11),
    "duplicate-prop": (43, 7),
    "no-class": (33, 9),
    "newer-major": (2, 1),
    "doctype": (2, 12),
    "no-xmlns": (2, 1),
}


# --------------------------------------------------------------------------------------
# Success paths
# --------------------------------------------------------------------------------------
def test_valid_file_exits_0_with_a_success_line(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, "--check", str(HELLO))
    assert code == 0 and err == ""
    assert out == f"{HELLO}: no errors found\n"


def test_path_is_reported_exactly_as_typed(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    code, out, _ = run(capsys, "--check", "./examples/hello.ui")
    assert code == 0 and out == "./examples/hello.ui: no errors found\n"


def test_warnings_do_not_fail_the_run(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    text = GOOD.replace('<window id="main"', '<window id="main" oddity="1"').replace(
        "  </window>", "    <bogus/>\n    <!-- note -->\n  </window>"
    )
    path = write("warn.ui", text)
    code, out, err = run(capsys, "--check", path)
    assert code == 0 and out == f"{path}: no errors found\n"
    lines = err.splitlines()
    assert len(lines) == 3
    parsed = [LOCATION.match(line) for line in lines[:2]]
    assert all(m and m["kind"] == "warning" for m in parsed)
    assert [m["path"] for m in parsed if m] == [path, path]
    assert "oddity" in lines[0] and "<bogus>" in lines[1]
    assert lines[2].startswith(f"{path}: warning: ") and "(1)" in lines[2]  # no line/column


def test_read_only_newer_minor_still_exits_0(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("new.ui", GOOD.replace('schema_version="1.0"', 'schema_version="1.5"'))
    code, out, err = run(capsys, "--check", path)
    assert code == 0 and "no errors found" in out
    assert re.match(rf"{re.escape(path)}:2:1: warning: .*1\.5", err)


# --------------------------------------------------------------------------------------
# Failure paths
# --------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", sorted(CORRUPTIONS))
def test_each_honest_corruption_exits_1_with_a_location(
    name: str, capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    corrupted = CORRUPTIONS[name](GOOD)
    assert corrupted != GOOD, "the corruption must change the file"
    path = write(f"{name}.ui", corrupted)
    code, out, err = run(capsys, "--check", path)
    assert code == 1 and out == ""
    match = LOCATION.match(err.strip())
    assert match and match["kind"] == "error" and match["path"] == path, err
    assert int(match["line"]) >= 1 and int(match["col"]) >= 1


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("newer-major", "schema version 2.0"),
        ("no-xmlns", "not a PyGUIbud .ui file"),
        ("doctype", "DOCTYPE"),
        ("delete-gt", "not well-formed"),
        ("bad-int", "'row' of <cell> must be a whole number, not 'x'"),
        ("no-class", "needs the attribute 'class'"),
        ("duplicate-prop", "'text' is set more than once"),
    ],
)
def test_corruption_lines_and_messages(
    name: str,
    text: str,
    capsys: pytest.CaptureFixture[str],
    write: Callable[[str, str], str],
) -> None:
    corrupted = CORRUPTIONS[name](GOOD)
    _, _, err = run(capsys, "--check", write(f"{name}.ui", corrupted))
    match = LOCATION.match(err)
    assert match and text in err
    assert (int(match["line"]), int(match["col"])) == POSITIONS[name]


def test_mixed_files_report_every_file_and_exit_1(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    good1 = write("a.ui", GOOD)
    bad1 = write("b.ui", CORRUPTIONS["newer-major"](GOOD))
    good2 = write("c.ui", GOOD)
    bad2 = write("d.ui", CORRUPTIONS["bad-int"](GOOD))
    code, out, err = run(capsys, "--check", good1, bad1, good2, bad2)
    assert code == 1
    assert out.splitlines() == [f"{good1}: no errors found", f"{good2}: no errors found"]
    errors = err.splitlines()
    assert len(errors) == 2 and errors[0].startswith(bad1) and errors[1].startswith(bad2)


def test_a_failure_does_not_stop_later_files(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str], tmp_path: Path
) -> None:
    good = write("ok.ui", GOOD)
    code, out, err = run(capsys, "--check", str(tmp_path / "missing.ui"), good)
    assert code == 1 and "ok.ui: no errors found" in out and "missing.ui" in err


def test_missing_file(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    path = str(tmp_path / "nope.ui")
    code, out, err = run(capsys, "--check", path)
    assert code == 1 and out == ""
    assert err == f"{path}: error: The file does not exist.\n"


def test_directory(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    code, out, err = run(capsys, "--check", str(tmp_path))
    assert code == 1 and out == ""
    assert err == f"{tmp_path}: error: This is a folder, not a .ui file.\n"


def test_non_utf8_bytes(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, bytes], str]
) -> None:
    path = write("latin.ui", GOOD.encode().replace(b"Hello", b"H\xe9llo"))
    code, out, err = run(capsys, "--check", path)
    assert code == 1 and out == ""
    match = LOCATION.match(err)
    assert match and match["kind"] == "error" and "UTF-8" in err
    assert (match["line"], match["col"]) == ("8", "68")


def test_empty_file(capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]) -> None:
    code, _, err = run(capsys, "--check", write("empty.ui", ""))
    assert code == 1 and "not well-formed" in err


def test_unreadable_file_is_reported_not_raised(
    capsys: pytest.CaptureFixture[str],
    write: Callable[[str, str], str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pyguibud.core import xml_io

    def refuse(*args: object, **kwargs: object) -> object:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(xml_io, "open", refuse, raising=False)
    code, _, err = run(capsys, "--check", write("locked.ui", GOOD))
    assert code == 1 and "Permission denied" in err and err.count("\n") == 1


def test_bugs_are_not_swallowed(
    write: Callable[[str, str], str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(path: str) -> object:
        raise RuntimeError("a real bug")

    monkeypatch.setattr(uic, "read_ui", explode)
    with pytest.raises(RuntimeError, match="a real bug"):
        main(["--check", write("x.ui", GOOD)])


# --------------------------------------------------------------------------------------
# Glob expansion
# --------------------------------------------------------------------------------------
def test_glob_without_match(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    pattern = str(tmp_path / "*.nothing")
    code, out, err = run(capsys, "--check", pattern)
    assert code == 1 and out == ""
    assert err == f"{pattern}: error: no file matches this pattern\n"


def test_glob_expands_sorted_when_the_shell_does_not(
    capsys: pytest.CaptureFixture[str],
    write: Callable[[str, str], str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("b.ui", "a.ui", "c.txt"):
        write(name, GOOD)
    monkeypatch.chdir(tmp_path)
    code, out, _ = run(capsys, "--check", "*.ui")
    assert code == 0
    assert out.splitlines() == ["a.ui: no errors found", "b.ui: no errors found"]
    code, out, _ = run(capsys, "--check", "?.ui", "[ab].ui")
    assert code == 0 and out.count("no errors found") == 4


def test_glob_reports_errors_of_the_expanded_files(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str], tmp_path: Path
) -> None:
    write("one.ui", GOOD)
    bad = write("two.ui", CORRUPTIONS["newer-major"](GOOD))
    code, out, err = run(capsys, "--check", str(tmp_path / "*.ui"))
    assert code == 1 and "one.ui: no errors found" in out and err.startswith(bad)


def test_existing_file_with_glob_characters_is_taken_literally(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("w[1].ui", GOOD)
    write("w1.ui", CORRUPTIONS["newer-major"](GOOD))
    code, out, err = run(capsys, "--check", path)
    assert code == 0 and out == f"{path}: no errors found\n" and err == ""


# --------------------------------------------------------------------------------------
# Usage and options
# --------------------------------------------------------------------------------------
def test_no_arguments_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main([])
    assert info.value.code == 2
    assert "usage: pyguibud-uic" in capsys.readouterr().err


def test_check_without_files_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--check"])
    assert info.value.code == 2
    assert "FILE" in capsys.readouterr().err


def test_file_without_check_exits_2_and_explains(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = run(capsys, str(HELLO))
    assert code == 2 and out == ""
    assert "later development step" in err and "--check" in err and "Traceback" not in err


def test_unknown_option_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as info:
        main(["--bogus", "x.ui"])
    assert info.value.code == 2


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert capsys.readouterr().out == f"pyguibud-uic {pyguibud.__version__}\n"


def test_help_lists_the_options(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0
    out = capsys.readouterr().out
    assert "--check" in out and "--lang" in out and "FILE" in out


def test_invalid_language_is_a_usage_error(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as info:
        main(["--lang", "xx_YY", "--check", str(HELLO)])
    assert info.value.code == 2
    assert "xx_YY" in capsys.readouterr().err


def test_lang_changes_the_message_but_not_the_error_token(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("bad.ui", CORRUPTIONS["newer-major"](GOOD))
    _, _, english = run(capsys, "--check", path)
    code, _, pseudo = run(capsys, "--lang", "en_XA", "--check", path)
    assert code == 1
    assert pseudo != english
    en_match, xa_match = LOCATION.match(english), LOCATION.match(pseudo)
    assert en_match and xa_match
    assert xa_match["kind"] == en_match["kind"] == "error"
    assert (xa_match["path"], xa_match["line"], xa_match["col"]) == (
        en_match["path"],
        en_match["line"],
        en_match["col"],
    )
    assert pseudo.startswith(f"{path}:2:1: error: ")


def test_lang_changes_the_success_and_warning_text_but_not_the_tokens(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("warn.ui", GOOD.replace('<window id="main"', '<window id="main" oddity="1"'))
    _, english_out, english_err = run(capsys, "--check", path)
    _, pseudo_out, pseudo_err = run(capsys, "--lang", "en_XA", "--check", path)
    assert pseudo_out != english_out and pseudo_err != english_err
    assert ": warning: " in pseudo_err and "no errors found" not in pseudo_out


def test_lang_via_environment(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PYGUIBUD_LANG", "en_XA")
    _, _, err = run(capsys, "--check", str(tmp_path / "missing.ui"))
    assert ": error: " in err and "The file does not exist." not in err


# --------------------------------------------------------------------------------------
# The installed script
# --------------------------------------------------------------------------------------
def _script() -> str | None:
    scripts = Path(sys.executable).parent
    return shutil.which("pyguibud-uic", path=str(scripts)) or shutil.which("pyguibud-uic")


def test_installed_script_exit_codes(tmp_path: Path) -> None:
    script = _script()
    if script is None:
        pytest.skip("pyguibud-uic is not installed in this environment (run uv sync)")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    bad = tmp_path / "bad.ui"
    bad.write_text(CORRUPTIONS["newer-major"](GOOD), "utf-8")

    def call(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [script, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            timeout=60,
            check=False,
            cwd=ROOT,
        )

    ok = call("--check", "examples/hello.ui")
    assert ok.returncode == 0 and ok.stdout == "examples/hello.ui: no errors found\n"
    assert ok.stderr == ""
    failed = call("--check", "examples/hello.ui", str(bad))
    assert failed.returncode == 1 and "no errors found" in failed.stdout
    assert re.match(rf"{re.escape(str(bad))}:2:1: error: ", failed.stderr)
    assert call("examples/hello.ui").returncode == 2
    assert call().returncode == 2
    version = call("--version")
    assert version.returncode == 0 and version.stdout == f"pyguibud-uic {pyguibud.__version__}\n"
    assert "Traceback" not in ok.stderr + failed.stderr


# --------------------------------------------------------------------------------------
# The validator (Step 09)
# --------------------------------------------------------------------------------------
def _bad_width(text: str) -> str:
    return text.replace(
        '<prop name="text" translatable="true" context="greeting form">Your name:</prop>',
        '<prop name="width">-1</prop>',
    )


def _unknown_prop(text: str) -> str:
    return text.replace(
        '<prop name="text" translatable="true" context="greeting form">Your name:</prop>',
        '<prop name="mystery">1</prop>',
    )


def test_a_validator_error_exits_1_with_a_location_and_no_success_line(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("width.ui", _bad_width(GOOD))
    code, out, err = run(capsys, "--check", path)
    assert code == 1 and out == ""
    match = LOCATION.match(err)
    assert match and match["kind"] == "error" and match["path"] == path
    assert (int(match["line"]), int(match["col"])) == (34, 11)
    assert err.endswith("width must be between 0 and 10000, not -1.\n")


def test_validator_warnings_alone_still_succeed(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("prop.ui", _unknown_prop(GOOD))
    code, out, err = run(capsys, "--check", path)
    assert code == 0 and out == f"{path}: no errors found\n"
    match = LOCATION.match(err)
    assert match and match["kind"] == "warning" and "Label has no property 'mystery'" in err


def test_read_only_file_with_a_validator_warning_exits_0(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    text = _unknown_prop(GOOD).replace('schema_version="1.0"', 'schema_version="1.5"')
    path = write("new.ui", text)
    code, out, err = run(capsys, "--check", path)
    assert code == 0 and "no errors found" in out
    lines = err.splitlines()
    assert len(lines) == 2 and "1.5" in lines[0] and "mystery" in lines[1]  # reader first


def test_reader_warnings_come_before_validator_findings(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    text = _bad_width(GOOD).replace('<window id="main"', '<window id="main" oddity="1"')
    code, _, err = run(capsys, "--check", write("both.ui", text))
    kinds = [m["kind"] for m in map(LOCATION.match, err.splitlines()) if m]
    assert code == 1 and kinds == ["warning", "error"]


def test_mixed_files_with_a_validator_error_exit_1(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    good = write("a.ui", GOOD)
    invalid = write("b.ui", _bad_width(GOOD))
    warn = write("c.ui", _unknown_prop(GOOD))
    code, out, err = run(capsys, "--check", good, invalid, warn)
    assert code == 1
    assert out.splitlines() == [f"{good}: no errors found", f"{warn}: no errors found"]
    assert err.count(": error: ") == 1 and err.count(": warning: ") == 1


def test_lang_translates_validator_messages_but_not_the_tokens(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str], str]
) -> None:
    path = write("width.ui", _bad_width(GOOD))
    _, _, english = run(capsys, "--check", path)
    code, _, pseudo = run(capsys, "--lang", "en_XA", "--check", path)
    assert code == 1 and pseudo != english
    assert pseudo.startswith(f"{path}:34:11: error: ")


def test_a_finding_without_a_line_prints_its_path(capsys: pytest.CaptureFixture[str]) -> None:
    finding = Finding(
        code="x",
        msgid="Something {what}.",
        params={"what": "odd"},
        source="f.ui",
        severity="warning",
        path="window[main]/widget[a]",
    )
    uic._report(finding)
    assert capsys.readouterr().err == "f.ui: warning: window[main]/widget[a]: Something odd.\n"
    uic._report(Finding(code="x", msgid="Plain.", source="f.ui", severity="error"))
    assert capsys.readouterr().err == "f.ui: error: Plain.\n"


def test_help_carries_the_plugin_trust_note(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "runs their code" in out and "pyguibud.widgets" in out


def test_installed_script_runs_the_validator(tmp_path: Path) -> None:
    script = _script()
    if script is None:
        pytest.skip("pyguibud-uic is not installed in this environment (run uv sync)")
    bad = tmp_path / "bad.ui"
    bad.write_text(_bad_width(GOOD), "utf-8")
    result = subprocess.run(
        [script, "--check", str(bad)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
        check=False,
    )
    assert result.returncode == 1 and ":34:11: error: " in result.stderr


# --------------------------------------------------------------------------------------
# File rules (decision U3): includes and image files are checked too
# --------------------------------------------------------------------------------------
_PART = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">\n'
    '<meta source_locale="en_GB"/>\n'
    '<window id="part" kind="component"><layout type="grid"/></window>\n'
    "</pyguibud-ui>\n"
)


def _with_include(src: str, component: str = "part") -> str:
    return GOOD.replace(
        "  </window>",
        f'    <include id="inc_x" src="{src}" component="{component}"><cell row="9" column="0"/>'
        "</include>\n  </window>",
        1,
    )


def test_check_follows_includes(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str | bytes], str]
) -> None:
    write("part.ui", _PART)
    good = write("good.ui", _with_include("part.ui"))
    assert run(capsys, "--check", good)[0] == 0
    code, _out, err = run(capsys, "--check", write("gone.ui", _with_include("missing.ui")))
    assert code == 1 and "error: The included file 'missing.ui' does not exist" in err
    code, _out, err = run(capsys, "--check", write("nc.ui", _with_include("part.ui", "nope")))
    assert code == 1 and "has no component window 'nope'" in err


def test_check_probes_image_files(
    capsys: pytest.CaptureFixture[str], write: Callable[[str, str | bytes], str]
) -> None:
    resources = '  <resources><image id="img" src="x.png"/></resources>\n'
    text = GOOD.replace("  <variables>", resources + "  <variables>", 1)
    path = write("img.ui", text)
    code, _out, err = run(capsys, "--check", path)
    assert code == 1 and "The image file 'x.png' does not exist." in err
    write("x.png", b"not a png")
    code, _out, err = run(capsys, "--check", path)
    assert code == 1 and "cannot be used: its content does not match its file type" in err
