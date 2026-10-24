"""QA regressions of Step 11 (``pyguibud-uic``): abuse that must be blocked gracefully.

Each test names its QA-11-NN finding; all of them are fixed (``docs/specs/codegen.md`` 12.2), so
these are regression tests. The ``CON`` hang (QA-11-05) itself depends on the console, so it is
covered through ``os.devnull`` and the Win32 device-name check instead.
"""

from __future__ import annotations

import ast
import gettext
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from pyguibud import i18n
from pyguibud.codegen import CodegenError, extract_pot, generate_python
from pyguibud.core.xml_io import read_ui
from pyguibud.uic import main
from tests.codegen.conftest import png, write_ui

WINDOW = (
    '<window id="main" kind="main"><prop name="title" translatable="true">T</prop>'
    '<layout type="pack"/>{body}</window>'
)
LABEL = (
    '<widget class="Label" id="lbl"><prop name="text" translatable="true">Hi</prop><pack/></widget>'
)
IMAGE_LABEL = (
    '<widget class="Label" id="lbl"><prop name="image" ref="pic"/>'
    '<prop name="text">Hi</prop><pack/></widget>'
)


@pytest.fixture(autouse=True)
def _en_gb(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(i18n, "_translation", gettext.NullTranslations())
    monkeypatch.setattr(i18n, "_language", "en_GB")


def _ui(path: Path, body: str = LABEL, **parts: str) -> Path:
    return write_ui(path, WINDOW.format(body=body), **parts)


# ---------------------------------------------------------------- QA-11-01: --extract overwrites
def test_extract_refuses_to_overwrite_its_input(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    before = source.read_bytes()
    code = main(["--extract", str(source), "-o", str(source)])
    assert source.read_bytes() == before
    assert code == 1


def test_extract_refuses_to_overwrite_a_file_that_is_not_a_template(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    notes = tmp_path / "notes.txt"
    notes.write_text("important\n", encoding="utf-8")
    code = main(["--extract", str(source), "-o", str(notes)])
    assert notes.read_text(encoding="utf-8") == "important\n"
    assert code == 1


def test_extract_still_replaces_its_own_template(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    pot = tmp_path / "form.pot"
    assert main(["--extract", str(source), "-o", str(pot)]) == 0
    assert main(["--extract", str(source), "-o", str(pot)]) == 0
    assert 'msgid "Hi"' in pot.read_text(encoding="utf-8")


# ---------------------------------------------------------------- QA-11-02: aliased folders
@pytest.mark.skipif(sys.platform != "win32", reason="NTFS junction")
def test_module_written_through_a_junction_finds_its_catalogue(tmp_path: Path) -> None:
    if sys.platform == "win32":  # a literal check, so mypy skips the body on linux/darwin
        import _winapi  # CPython on Windows

        from babel.messages.catalog import Catalog
        from babel.messages.mofile import write_mo

        folder = tmp_path / "ui" / "locale" / "de_DE" / "LC_MESSAGES"
        folder.mkdir(parents=True)
        catalogue = Catalog(locale="de_DE", domain="form")
        catalogue.add("Hi", "Hallo")
        with (folder / "form.mo").open("wb") as stream:
            write_mo(stream, catalogue)
        source = _ui(tmp_path / "ui" / "form.ui", meta='i18n_domain="form"')
        real = tmp_path / "out"
        real.mkdir()
        (tmp_path / "a" / "b").mkdir(parents=True)
        link = tmp_path / "a" / "b" / "link"
        _winapi.CreateJunction(str(real), str(link))
        output = link / "form_ui.py"
        text = generate_python(read_ui(str(source)), str(source), output=str(output)).text
        output.write_text(text, encoding="utf-8")
        # Import the module through the junction and ask its own support code for the catalogue.
        script = (
            "import importlib.util, sys\n"
            "spec = importlib.util.spec_from_file_location('form_ui', sys.argv[1])\n"
            "module = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(module)\n"
            "print(module._translators(module._DOCS, 'de_DE', None, None)[0].gettext('Hi'))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(output)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.stdout.strip() == "Hallo", result.stderr


# ---------------------------------------------------------------- QA-11-04: output collisions
def test_inputs_with_the_same_default_output_are_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    first = _ui(tmp_path / "my-form.ui")
    second = _ui(tmp_path / "my_form.ui", body=LABEL.replace(">Hi<", ">Second<"))
    code = main([str(first), str(second)])
    err = capsys.readouterr().err
    assert code == 1
    assert "my_form_ui.py" in err


# ---------------------------------------------------------------- QA-11-06/07: images Tk refuses
@pytest.mark.parametrize(
    ("name", "data"),
    [
        pytest.param("plain.ppm", b"P3\n1 1\n255\n255 0 0\n", id="QA-11-07-P3"),
        pytest.param("plain.pgm", b"P2\n1 1\n255\n128\n", id="QA-11-07-P2"),
        pytest.param("cut.png", png()[:40], id="QA-11-06-cut-png"),
        pytest.param("short.ppm", b"P6\n2 2\n255\n" + bytes(11), id="QA-11-06-short-ppm"),
    ],
)
def test_images_tk_cannot_load_fail_the_check(tmp_path: Path, name: str, data: bytes) -> None:
    (tmp_path / name).write_bytes(data)
    source = _ui(
        tmp_path / "form.ui", body=IMAGE_LABEL, resources=f'<image id="pic" src="{name}"/>'
    )
    assert main(["--check", str(source)]) == 1


# ---------------------------------------------------------------- QA-11-08: preview tracebacks
def test_preview_with_a_bad_language_exits_without_a_traceback(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    module = tmp_path / "form_ui.py"
    text = generate_python(read_ui(str(source)), str(source), output=str(module)).text
    module.write_text(text, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(module), "--lang", "bad!"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert "Traceback" not in result.stderr
    assert result.returncode == 2


# ---------------------------------------------------------------- QA-11-09/10: .pot
def test_pot_keeps_the_reference_of_a_path_with_spaces(tmp_path: Path) -> None:
    from babel.messages.pofile import read_po

    # gettext >= 0.22 writes such a name between U+2068 and U+2069; Babel reads it back.
    source = _ui(tmp_path / "my form.ui")
    text = extract_pot([(read_ui(str(source)), str(source))], base_dir=str(tmp_path))
    catalogue = read_po(io.BytesIO(text.encode("utf-8")))
    hi = catalogue.get("Hi")
    assert hi is not None
    assert [name for name, _line in hi.locations] == ["my form.ui"]
    # A name that cannot be written on one "#:" line is dropped, never split into fields.
    text = extract_pot([(read_ui(str(source)), str(tmp_path / "a\nb.ui"))], base_dir=str(tmp_path))
    assert "#:" not in text


def test_pot_header_escapes_the_file_name(tmp_path: Path) -> None:
    from babel.messages.pofile import read_po

    source = _ui(tmp_path / "form.ui")
    result = read_ui(str(source))
    text = extract_pot([(result, '/tmp/evil"\nmsgid "pwn.ui')], base_dir=str(tmp_path))
    catalogue = read_po(io.BytesIO(text.encode("utf-8")))
    assert [m.id for m in catalogue if m.id] == ["T", "Hi"]
    assert '\nmsgid "pwn' not in text


# ---------------------------------------------------------------- QA-11-11: source_locale
def test_a_garbage_source_locale_is_refused(tmp_path: Path) -> None:
    source = write_ui(tmp_path / "form.ui", WINDOW.format(body=LABEL))
    text = source.read_text(encoding="utf-8").replace(
        'source_locale="en_GB"', 'source_locale="x\'); import os #"'
    )
    source.write_text(text, encoding="utf-8")
    with pytest.raises(CodegenError):
        generate_python(read_ui(str(source)), str(source), output=str(tmp_path / "f_ui.py"))


# ---------------------------------------------------------------- guards (passing)
@pytest.mark.skipif(sys.platform != "win32", reason="Win32 path aliases")
@pytest.mark.parametrize(
    "alias", ["form.ui.", "form.ui ", "form.ui::$DATA", "FORM.UI", "./form.ui"]
)
def test_windows_aliases_of_the_input_are_refused_even_with_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, alias: str
) -> None:
    monkeypatch.chdir(tmp_path)
    source = _ui(tmp_path / "form.ui")
    before = source.read_bytes()
    assert main(["form.ui", "-o", alias, "--force"]) == 1
    assert source.read_bytes() == before


@pytest.mark.skipif(sys.platform != "win32", reason="Windows sharing semantics")
def test_a_locked_output_fails_cleanly_without_a_temporary_file(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    assert main([str(source)]) == 0
    output = tmp_path / "form_ui.py"
    with output.open("rb"):  # no FILE_SHARE_DELETE: os.replace must fail
        assert main([str(source)]) == 1
    assert not [p for p in tmp_path.iterdir() if p.name.startswith("~pgb")]


@pytest.mark.parametrize(
    "attribute",
    ["theme", "source_locale", "{urn:pyguibud:ext:ttkbootstrap:1}bootstyle"],
)
@pytest.mark.parametrize(
    "payload",
    ["x'); import os; os.system('x') #", '"""\nimport os\n"""', "\u202e\u2028\x85", "a" * 5000],
)
def test_hostile_meta_and_style_values_change_only_constants(
    tmp_path: Path, attribute: str, payload: str
) -> None:
    def shape(text: str) -> str:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant):
                node.value = None
        return ast.dump(tree)

    base = _ui(
        tmp_path / "base.ui",
        body=LABEL.replace('id="lbl"', 'id="lbl" tb:bootstyle="info"'),
        meta='theme="flatly"',
    )
    reference = shape(
        generate_python(read_ui(str(base)), str(base), output=str(tmp_path / "o.py")).text
    )
    result = read_ui(str(base))
    if attribute == "theme":
        result.document.meta.theme = payload
    elif attribute == "source_locale":
        result.document.meta.source_locale = payload
    else:
        result.document.children[0].children[0].extra_attrs[attribute] = payload
    try:
        text = generate_python(result, str(base), output=str(tmp_path / "o.py")).text
    except CodegenError:
        return
    assert shape(text) == reference


def test_a_complete_png_passes_the_check(tmp_path: Path) -> None:
    (tmp_path / "ok.png").write_bytes(png())
    source = _ui(tmp_path / "form.ui", body=IMAGE_LABEL, resources='<image id="pic" src="ok.png"/>')
    assert main(["--check", str(source)]) == 0


# ---------------------------------------------------------------- fixes of the QA-11 pass
def test_extract_never_replaces_an_included_file_even_with_force(tmp_path: Path) -> None:
    part = write_ui(
        tmp_path / "part.ui",
        '<window id="part" kind="component"><layout type="pack"/></window>',
    )
    host = _ui(
        tmp_path / "host.ui",
        body='<include id="inc" src="part.ui" component="part"><pack/></include>',
    )
    before = part.read_bytes()
    assert main(["--extract", str(host), "-o", str(part), "--force"]) == 1  # QA-11-01
    assert part.read_bytes() == before


def test_extract_refuses_a_generated_module_and_a_po_file_without_force(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    assert main([str(source)]) == 0
    module = tmp_path / "form_ui.py"
    po = tmp_path / "de.po"
    po.write_text('msgid ""\nmsgstr ""\n"Language: de\n"\n\nmsgid "Hi"\nmsgstr "Hallo"\n', "utf-8")
    for target in (module, po):
        before = target.read_bytes()
        assert main(["--extract", str(source), "-o", str(target)]) == 1
        assert target.read_bytes() == before
    assert main(["--extract", str(source), "-o", str(po), "--force"]) == 0


def test_an_output_that_is_another_input_of_the_run_is_refused(tmp_path: Path) -> None:
    first = _ui(tmp_path / "form.ui")
    second = _ui(tmp_path / "form_ui.py")  # a .ui file named like the first one's output
    before = second.read_bytes()
    assert main([str(first), str(second), "--force"]) == 1  # QA-11-04, widened
    assert second.read_bytes() == before


@pytest.mark.parametrize("extract", [False, True])
def test_a_device_or_folder_output_is_refused_without_opening_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extract: bool
) -> None:
    # QA-11-05: -o CON used to read the console; os.devnull is the device every OS has.
    source = _ui(tmp_path / "form.ui")
    mode = ["--extract"] if extract else []
    for output in (os.devnull, str(tmp_path)):
        assert main([*mode, str(source), "-o", output, "--force"]) == 1
        assert "a folder, a device or a reserved device name" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 device names")
@pytest.mark.parametrize("name", ["CON", "con.py", "NUL.txt", "COM1 .py", "lpt9", "CONIN$"])
def test_reserved_device_names_are_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.chdir(tmp_path)
    source = _ui(tmp_path / "form.ui")
    assert main([str(source), "-o", name]) == 1
    assert main(["--extract", str(source), "-o", name]) == 1


@pytest.mark.parametrize("value", ["de_DE/../../x", "en_XA;rm", "de DE"])
def test_cli_lang_must_be_a_language_code(value: str) -> None:
    # QA-11-12: used to be cut down to a known language.
    with pytest.raises(SystemExit) as info:
        main(["--lang", value, "--check", "x.ui"])
    assert info.value.code == 2


@pytest.mark.parametrize("stem", ["__", "\u65e5\u672c", "-"])
def test_a_class_name_from_a_stem_without_letters_is_ui_form(tmp_path: Path, stem: str) -> None:
    dialog = '<window id="dlg" kind="dialog"><layout type="pack"/>' + LABEL + "</window>"
    source = write_ui(tmp_path / f"{stem}.ui", dialog)
    result = generate_python(read_ui(str(source)), str(source), output=str(tmp_path / "o.py"))
    assert result.class_name == "Ui_Form"


@pytest.mark.gui
def test_preview_of_a_file_with_dialogs_only_shows_the_first_and_ends_with_it(
    tmp_path: Path,
) -> None:
    from tests.codegen.conftest import _display, run_generated

    if _display() is not None:
        pytest.skip("needs a Tk display")
    dialogs = "".join(
        f'<window id="{name}" kind="dialog"><layout type="pack"/>'
        + LABEL.replace("lbl", name + "_l")
        + "</window>"
        for name in ("first", "second")
    )
    source = write_ui(tmp_path / "dlg.ui", dialogs)
    module = tmp_path / "dlg_ui.py"
    module.write_text(
        generate_python(read_ui(str(source)), str(source), output=str(module)).text, "utf-8"
    )
    out = run_generated(
        module,
        """
seen = {}
original = g["_Ui"].run
def run(self):
    def check():
        top = self.windows["first"]
        seen["viewable"] = bool(top.winfo_viewable())
        seen["second"] = bool(self.windows["second"].winfo_viewable())
        top.tk.call(top.wm_protocol("WM_DELETE_WINDOW"))  # the user closes the dialog
    self._root.after(300, check)
    original(self)
g["_Ui"].run = run
sys.argv = ["dlg_ui.py"]
g["_preview"](g["Ui_dlg"])
out.update(seen)
""",
    )
    assert out["viewable"] is True and out["second"] is False


# ---------------------------------------------------------------- QA-11-03: outside resources
def _unc(*parts: str) -> str:
    return "\\\\" + "\\".join(parts)


UNC_SOURCES = [
    _unc("host", "share", "logo.png"),
    "//host/share/logo.png",
    _unc("?", "UNC", "host", "share", "logo.png"),
    _unc(".", "pipe", "x.png"),
    "/??/UNC/host/share/logo.png",
    "\\".join(["", "??", "UNC", "host", "share", "logo.png"]),  # the NT prefix
    "icons/CON.png",
    "nul.gif",
]


@pytest.mark.parametrize("src", UNC_SOURCES)
def test_network_and_device_paths_are_errors_and_never_opened(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, src: str
) -> None:
    from pyguibud.core.files import DiskFiles
    from pyguibud.core.registry import default_registry
    from pyguibud.core.validate import validate_read

    include = src.replace("logo.png", "part.ui").replace(".png", ".ui").replace(".gif", ".ui")
    body = IMAGE_LABEL + f'<include id="inc" src="{include}" component="part"><pack/></include>'
    source = _ui(tmp_path / "form.ui", body=body, resources=f'<image id="pic" src="{src}"/>')
    result = read_ui(str(source))
    files = DiskFiles(str(source), result)
    registry = default_registry()
    registry.get("Label")  # loaded first (it is lazy): the entry points are files too

    def touched(*args: object, **kwargs: object) -> None:
        raise AssertionError(f"file access: {args!r}")

    for name in ("stat", "lstat", "open", "scandir", "listdir"):
        monkeypatch.setattr(os, name, touched)
    monkeypatch.setattr(os.path, "realpath", touched)
    monkeypatch.setattr("builtins.open", touched)
    report = validate_read(result, registry, files=files)
    codes = [f.code for f in report.errors]
    assert codes.count("validate.network_path") == 2, report.findings
    assert set(codes) == {"validate.network_path"}, codes  # no missing/invalid on top
    with pytest.raises(OSError):
        files.resolve(files.root, src)  # the file access itself refuses it too


def test_network_paths_fail_the_check_and_generation_even_with_force(tmp_path: Path) -> None:
    source = _ui(
        tmp_path / "form.ui",
        body=IMAGE_LABEL,
        resources=f'<image id="pic" src="{_unc("host", "share", "logo.png")}"/>',
    )
    assert main(["--check", str(source)]) == 1
    assert main([str(source), "--force"]) == 1
    assert not (tmp_path / "form_ui.py").exists()


@pytest.mark.parametrize("where", ["image", "include"])
def test_outside_paths_are_warnings_but_codegen_needs_force(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], where: str
) -> None:
    (tmp_path / "up.png").write_bytes(png())
    write_ui(
        tmp_path / "part.ui", '<window id="part" kind="component"><layout type="pack"/></window>'
    )
    (tmp_path / "sub").mkdir()
    if where == "image":
        source = _ui(
            tmp_path / "sub" / "form.ui",
            body=IMAGE_LABEL,
            resources='<image id="pic" src="../up.png"/>',
        )
    else:
        source = _ui(
            tmp_path / "sub" / "form.ui",
            body='<include id="inc" src="../part.ui" component="part"><pack/></include>',
        )
    assert main(["--check", str(source)]) == 0  # still a warning for --check (and load_ui)
    capsys.readouterr()
    assert main([str(source)]) == 1
    err = capsys.readouterr().err
    assert "warning:" in err and "--force" in err and "'../" in err
    assert not (tmp_path / "sub" / "form_ui.py").exists()
    with pytest.raises(CodegenError) as info:
        generate_python(read_ui(str(source)), str(source), output=str(tmp_path / "o.py"))
    assert info.value.code == "codegen.outside_path"
    assert main([str(source), "--force"]) == 0
    assert (tmp_path / "sub" / "form_ui.py").exists()


# ---------------------------------------------------------------- QA re-verification (fixed)
@pytest.mark.skipif(sys.platform != "win32", reason="Win32 long-path prefix")
@pytest.mark.parametrize("mode", ["generate", "extract"])
@pytest.mark.parametrize("prefix", [r"\\?" + "\\", "//?/"], ids=["backslash", "slash"])
def test_long_path_alias_of_the_input_is_refused_even_with_force(
    tmp_path: Path, mode: str, prefix: str
) -> None:
    source = _ui(tmp_path / "form.ui")
    before = source.read_bytes()
    alias = prefix + str(source.resolve()).replace("\\", "/" if prefix == "//?/" else "\\")
    args = [str(source), "-o", alias, "--force"]
    code = main(["--extract", *args] if mode == "extract" else args)
    assert source.read_bytes() == before  # the .ui file must never be replaced
    assert code == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Win32 long-path prefix")
def test_long_path_alias_of_an_include_is_refused_even_with_force(tmp_path: Path) -> None:
    part = write_ui(
        tmp_path / "part.ui",
        '<window id="part" kind="component"><layout type="pack"/></window>',
    )
    host = _ui(
        tmp_path / "host.ui",
        body='<include id="inc" src="part.ui" component="part"><pack/></include>',
    )
    before = part.read_bytes()
    alias = "\\\\?\\" + str(part.resolve())
    for mode in ([], ["--extract"]):
        assert main([*mode, str(host), "-o", alias, "--force"]) == 1
    assert part.read_bytes() == before


def test_a_hard_link_of_the_input_is_refused_even_with_force(tmp_path: Path) -> None:
    source = _ui(tmp_path / "form.ui")
    link = tmp_path / "link.ui"
    try:
        os.link(source, link)
    except OSError:
        pytest.skip("no hard links on this file system")
    before = source.read_bytes()
    for mode in ([], ["--extract"]):
        assert main([*mode, str(source), "-o", str(link), "--force"]) == 1
    assert source.read_bytes() == before


def test_extract_never_replaces_a_translated_copy_of_the_template_without_force(
    tmp_path: Path,
) -> None:
    source = _ui(tmp_path / "form.ui")
    template = tmp_path / "form.pot"
    assert main(["--extract", str(source), "-o", str(template)]) == 0
    po = tmp_path / "de.po"  # the "cp form.pot de.po" workflow, then translated by hand
    po.write_text(
        template.read_text("utf-8").replace('msgid "Hi"\nmsgstr ""', 'msgid "Hi"\nmsgstr "Hallo"'),
        "utf-8",
    )
    before = po.read_bytes()
    assert b'msgstr "Hallo"' in before
    code = main(["--extract", str(source), "-o", str(po)])
    assert po.read_bytes() == before  # the translations must survive
    assert code == 1


def _png_with(ihdr: tuple[int, int, int, int, int], idat: bytes, plte: bool = False) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    width, height, depth, colour, interlace = ihdr
    head = struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", head)
        + (chunk(b"PLTE", b"\x00\x00\x00") if plte else b"")
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _raw_rgb() -> bytes:
    import zlib

    return zlib.compress(b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(3)))


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(_png_with((2, 3, 8, 2, 0), b""), id="empty-idat"),
        pytest.param(_png_with((2, 3, 8, 2, 0), b"notzlib!!"), id="garbage-zlib"),
        pytest.param(_png_with((2, 3, 8, 2, 0), _raw_rgb()[:-6]), id="truncated-zlib"),
        pytest.param(_png_with((2, 3, 8, 5, 0), _raw_rgb()), id="bad-colour-type"),
        pytest.param(_png_with((2, 3, 3, 2, 0), _raw_rgb()), id="bad-bit-depth"),
        pytest.param(_png_with((2, 3, 8, 2, 7), _raw_rgb()), id="bad-interlace"),
        pytest.param(_png_with((2, 3, 8, 3, 0), _raw_rgb()), id="palette-without-plte"),
    ],
)
def test_crc_valid_pngs_tk_cannot_decode_fail_the_check(tmp_path: Path, data: bytes) -> None:
    (tmp_path / "pic.png").write_bytes(data)
    source = _ui(
        tmp_path / "form.ui", body=IMAGE_LABEL, resources='<image id="pic" src="pic.png"/>'
    )
    assert main(["--check", str(source)]) == 1


@pytest.mark.parametrize(
    ("text", "translated"),
    [
        ('msgid ""\nmsgstr ""\n"Project-Id-Version: x\n"\n\nmsgid "Hi"\nmsgstr ""\n', False),
        ('msgid ""\nmsgstr ""\n"a\n"\n\nmsgid ""\n"multi\n"\n"line"\nmsgstr ""\n', False),
        ('msgid ""\nmsgstr ""\n\nmsgctxt "c"\nmsgid ""\nmsgstr ""\n"x"\n', True),
        ('msgid "Hi"\nmsgstr ""\n"Hallo"\n', True),
        ('msgid "a"\nmsgid_plural "b"\nmsgstr[0] ""\nmsgstr[1] "Bs"\n', True),
        ('msgid "Hi"\nmsgstr ""\n\n#~ msgid "Old"\n#~ msgstr "Alt"\n', True),
    ],
)
def test_po_translation_detection(text: str, translated: bool) -> None:
    from pyguibud.uic import _has_translations

    assert _has_translations(text) is translated


def test_extract_refuses_a_translated_template_whatever_its_name(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _ui(tmp_path / "form.ui")
    template = tmp_path / "form.pot"
    assert main(["--extract", str(source), "-o", str(template)]) == 0
    text = (
        template.read_text("utf-8")
        .replace('msgstr ""\n', 'msgstr "x"\n')
        .replace('msgid ""\nmsgstr "x"', 'msgid ""\nmsgstr ""')
    )
    template.write_text(text, "utf-8")
    capsys.readouterr()
    assert main(["--extract", str(source), "-o", str(template)]) == 1
    assert "is a translation catalogue" in capsys.readouterr().err
    assert template.read_text("utf-8") == text
    assert main(["--extract", str(source), "-o", str(template), "--force"]) == 0
    empty = tmp_path / "new.po"  # a .po target is refused even when it does not exist yet
    assert main(["--extract", str(source), "-o", str(empty)]) == 1
    assert not empty.exists()


def _png_chunks(ihdr: bytes, *chunks: tuple[bytes, bytes]) -> bytes:
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    body = b"".join(chunk(kind, data) for kind, data in chunks)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + body + chunk(b"IEND", b"")


def _ihdr(width: int, height: int, depth: int, colour: int, interlace: int = 0) -> bytes:
    import struct

    return struct.pack(">IIBBBBB", width, height, depth, colour, 0, 0, interlace)


def _valid_pngs() -> dict[str, bytes]:
    import zlib

    data = zlib.compress(b"".join(b"\x00" + b"\xff\x00\x00" * 2 for _ in range(3)))
    # Adam7 of 3 x 3, 8-bit grey; (filter byte + pixels) per row of each pass: pass 1 = 2,
    # passes 2 and 3 are empty, pass 4 = 2, pass 5 = 3, pass 6 = 2 x 2, pass 7 = 4: 15 bytes.
    adam7 = zlib.compress(bytes(15))
    return {
        "rgb-two-idat": _png_chunks(
            _ihdr(2, 3, 8, 2), (b"IDAT", data[:5]), (b"tEXt", b"a\x00b"), (b"IDAT", data[5:])
        ),
        "palette-1bit": _png_chunks(
            _ihdr(9, 2, 1, 3), (b"PLTE", b"\x00\x00\x00"), (b"IDAT", zlib.compress(bytes(6)))
        ),
        "grey-16bit": _png_chunks(_ihdr(1, 1, 16, 0), (b"IDAT", zlib.compress(bytes(3)))),
        "adam7": _png_chunks(_ihdr(3, 3, 8, 0, 1), (b"IDAT", adam7)),
    }


def _rgb_png(idat: bytes, *extra: tuple[bytes, bytes]) -> bytes:
    return _png_chunks(_ihdr(2, 3, 8, 2), (b"IDAT", idat), *extra)


def _probe_cases() -> dict[str, tuple[bytes, bool]]:
    """PNGs and whether Tk 8.6 decodes them (measured); the probe must agree."""
    import zlib

    full = zlib.compress(bytes(21))  # 3 rows x (filter byte + 2 x RGB)
    cases = {name: (data, True) for name, data in _valid_pngs().items()}
    cases.update(
        {
            "short-data": (_rgb_png(zlib.compress(bytes(1))), True),  # Tk fills the rest
            "bytes-after-stream": (_rgb_png(full + b"xx"), True),
            "too-much-data": (_rgb_png(zlib.compress(bytes(22))), False),
            "idat-after-stream": (_rgb_png(full, (b"IDAT", b"zz")), False),
            "cut-stream": (_rgb_png(full[:-4]), False),
        }
    )
    return cases


@pytest.mark.gui
@pytest.mark.parametrize("name", list(_probe_cases()))
def test_the_png_probe_agrees_with_tk(name: str) -> None:
    import base64

    from pyguibud.core.files import probe_bytes
    from tests.codegen.conftest import _display

    if _display() is not None:
        pytest.skip("needs a Tk display")
    data, decodes = _probe_cases()[name]
    assert (probe_bytes(data, ".png").status == "ok") is decodes
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, tkinter; r = tkinter.Tk(); r.withdraw();"
            "tkinter.PhotoImage(master=r, data=sys.argv[1], format='png'); r.destroy()",
            base64.b64encode(data).decode(),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert (result.returncode == 0) is decodes, result.stderr


def test_a_png_zip_bomb_is_refused_without_inflating_it_all() -> None:
    import zlib

    from pyguibud.core.files import probe_bytes

    # 1 x 1 announced, 64 MiB of zeros inflated: refused as soon as the count passes 2 bytes.
    bomb = _png_chunks(_ihdr(1, 1, 8, 0), (b"IDAT", zlib.compress(bytes(64 << 20), 9)))
    assert probe_bytes(bomb, ".png").reason == "its data is incomplete or damaged"


def test_python_m_pyguibud_uic_runs_the_command(tmp_path: Path) -> None:
    # QA-11-16: the module had no __main__ block, so it exited 0 and did nothing.
    source = _ui(tmp_path / "form.ui")
    result = subprocess.run(
        [sys.executable, "-m", "pyguibud.uic", str(source)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "form_ui.py").exists()
    bad = subprocess.run(
        [sys.executable, "-m", "pyguibud.uic", "--check", str(tmp_path / "missing.ui")],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert bad.returncode == 1
