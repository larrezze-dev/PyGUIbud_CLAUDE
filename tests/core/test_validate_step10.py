"""Tests of the Step 10 validator rules: R49 to R53 and R69 to R78 (``files=`` injection)."""

from __future__ import annotations

import os
import struct
import time
import zlib
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from pyguibud.core import (
    Action,
    Document,
    Event,
    Finding,
    ImageResource,
    Layout,
    Menu,
    Menubar,
    Prop,
    Statusbar,
    Variable,
    Widget,
    Window,
    default_registry,
    read_ui,
)
from pyguibud.core.errors import XmlIoError
from pyguibud.core.files import (
    MAX_EXPANDED_NODES,
    MAX_IMAGE_BYTES,
    MAX_INCLUDE_DEPTH,
    MAX_INCLUDE_FILES,
    DiskFiles,
    ImageProbe,
)
from pyguibud.core.validate import RESERVED_IDS, ValidationReport, validate, validate_read

HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">\n'
)


def ui_text(body: str, *, meta: str = "", resources: str = "", variables: str = "") -> str:
    return (
        HEAD
        + f'<meta source_locale="en_GB"{meta}/>\n'
        + (f"<resources>{resources}</resources>\n" if resources else "")
        + (f"<variables>{variables}</variables>\n" if variables else "")
        + body
        + "\n</pyguibud-ui>\n"
    )


def window(wid: str, kind: str = "component", body: str = "", extra: str = "") -> str:
    return f'<window id="{wid}" kind="{kind}"{extra}><layout type="grid"/>{body}</window>'


def label(wid: str, row: int = 0) -> str:
    return f'<widget class="Label" id="{wid}"><cell row="{row}" column="0"/></widget>'


def include(iid: str, src: str, component: str, row: int = 0) -> str:
    return (
        f'<include id="{iid}" src="{src}" component="{component}">'
        f'<cell row="{row}" column="0"/></include>'
    )


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def check(path: Path) -> ValidationReport:
    result = read_ui(path)
    return validate_read(result, default_registry(), files=DiskFiles(path, result))


def anchor_id(finding: Finding) -> str:
    return str(getattr(finding.anchor, "id", ""))


def codes(report: ValidationReport) -> list[str]:
    return [f.code for f in report.findings]


def doc_with(*windows: Window) -> Document:
    document = Document()
    for item in windows:
        document.add_window(item)
    return document


def pure(text: str) -> ValidationReport:
    from pyguibud.core import read_ui_string

    return validate_read(read_ui_string(text), default_registry())


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(width: int, height: int, *, ihdr: bool = True) -> bytes:
    """A complete black 8-bit grey PNG (IHDR, IDAT, IEND), as Tk needs (QA-11-06, QA-11-15).

    Oversized dimensions get a token IDAT: the probe refuses them before reading the data.
    """
    head = b"\x89PNG\r\n\x1a\n"
    kind = b"IHDR" if ihdr else b"IDAT"
    fits = 0 < width <= 4096 and 0 < height <= 4096
    raw = b"\x00" * (height * (1 + width)) if fits else b"\x00"
    return (
        head
        + chunk(kind, struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def gif(
    width: int,
    height: int,
    *,
    frame: tuple[int, int] | None = None,
    palette: bool = False,
    extensions: bytes = b"",
) -> bytes:
    """A GIF whose screen is ``width`` x ``height`` and whose first image is ``frame`` (same)."""
    frame_width, frame_height = frame or (width, height)
    flags = 0x81 if palette else 0x00  # 0x81: a global colour table of 4 entries (12 bytes)
    screen = b"GIF89a" + struct.pack("<HHBBB", width, height, flags, 0, 0)
    table = b"\x00\xff" * 6 if palette else b""
    image = b"," + struct.pack("<HHHHB", 0, 0, frame_width, frame_height, 0) + b"\x02\x02D\x01\x00"
    return screen + table + extensions + image + b";"


# ---------------------------------------------------------------- R69 reserved ids
@pytest.mark.parametrize("name", sorted(RESERVED_IDS))
@pytest.mark.parametrize(
    "where",
    ["window", "widget", "menu", "action", "statusbar", "include", "resource", "variable"],
)
def test_r69_reserved_id_everywhere(name: str, where: str) -> None:
    ids = {
        "window": "main_win",
        "widget": "lbl",
        "menu": "mnu",
        "action": "act",
        "statusbar": "sts",
        "include": "inc",
        "resource": "img",
        "variable": "var_a",
    }
    ids[where] = name
    body = window(
        ids["window"],
        "main",
        label(ids["widget"])
        + include(ids["include"], "x.ui", "comp", 1)
        + f'<menubar><menu id="{ids["menu"]}"><action id="{ids["action"]}"/></menu></menubar>'
        + f'<statusbar id="{ids["statusbar"]}"/>',
    )
    text = ui_text(
        body,
        resources=f'<image id="{ids["resource"]}" src="a.png"/>',
        variables=f'<var id="{ids["variable"]}" type="string"/>',
    )
    report = pure(text)
    found = [f for f in report.errors if f.code == "validate.reserved_id"]
    assert len(found) == 1
    assert found[0].params["id"] == name
    assert "reserved" in found[0].message


def test_r69_does_not_flag_similar_names() -> None:
    body = window("main", "main", label("runner") + label("show_all", 1) + label("Run", 2))
    assert "validate.reserved_id" not in codes(pure(ui_text(body)))


def test_r69_matches_the_runtime_spec_set() -> None:
    assert {
        "vars",
        "widgets",
        "windows",
        "setup_ui",
        "retranslate",
        "show",
        "run",
        "destroy",
    } == RESERVED_IDS


# ---------------------------------------------------------------- R70 buttons
@pytest.mark.parametrize(
    "value",
    ["ok", "ok,cancel", "yes,no,close", "close,ok", "ok,cancel,yes,no,close"],
)
def test_r70_valid_button_lists(value: str) -> None:
    body = window("dlg", "dialog", extra=f' buttons="{value}"')
    assert "validate.bad_buttons" not in codes(pure(ui_text(body)))


@pytest.mark.parametrize(
    "value",
    [
        "",
        "ok_cancel",
        "OK",
        "ok,ok",
        "ok, cancel",
        " ok",
        "ok,",
        ",ok",
        "ok,,cancel",
        "apply",
        "ok;no",
    ],
)
def test_r70_invalid_button_lists(value: str) -> None:
    body = window("dlg", "dialog", extra=f' buttons="{value}"')
    report = pure(ui_text(body))
    assert codes(report).count("validate.bad_buttons") == 1
    message = next(f.message for f in report.errors if f.code == "validate.bad_buttons")
    assert "ok, cancel, yes, no, close" in message


def test_r70_only_on_dialogs() -> None:
    for kind in ("main", "component"):
        report = pure(ui_text(window("w", kind, extra=' buttons="x"')))
        assert "validate.bad_buttons" not in codes(report)
        assert "validate.dialog_only" in codes(report)


def test_r70_non_text_value_is_not_text_error_only() -> None:
    document = doc_with(Window(id="d", kind="dialog", layout=Layout(type="grid")))
    document.children[0].buttons = 5  # type: ignore[assignment]
    found = codes(validate(document, default_registry()))
    assert "validate.not_text" in found and "validate.bad_buttons" not in found


# ---------------------------------------------------------------- R71 and R73 shortcuts
def action_ui(*shortcuts: str, windows: int = 1) -> str:
    out = ""
    for w in range(windows):
        actions = "".join(
            f'<action id="act_{w}_{i}" shortcut="{s}"/>' for i, s in enumerate(shortcuts)
        )
        kind = "main" if w == 0 else "dialog"
        out += window(f"win_{w}", kind, f'<menubar><menu id="mnu_{w}">{actions}</menu></menubar>')
    return ui_text(out)


@pytest.mark.parametrize(
    "value", ["Ctrl+S", "ctrl+shift+f5", "Alt+F4", "F1", "Shift+F24", "Ctrl+Enter"]
)
def test_r71_valid(value: str) -> None:
    assert "validate.bad_shortcut" not in codes(pure(action_ui(value)))


@pytest.mark.parametrize(
    ("value", "needle"),
    [
        ("fine", "not a valid shortcut"),
        ("Ctrl+", "not a valid shortcut"),
        ("Ctrl+Ctrl+S", "not a valid shortcut"),
        ("Ctrl+F25", "not a valid shortcut"),
        ("Strg+S", "not a valid shortcut"),
        ("Ctrl S", "not a valid shortcut"),
        ("Q", "needs Ctrl or Alt"),
        ("Shift+Q", "needs Ctrl or Alt"),
        ("Enter", "needs Ctrl or Alt"),
        ("Delete", "needs Ctrl or Alt"),
        ("Ctrl+" + "A" * 5000, "not a valid shortcut"),
    ],
)
def test_r71_invalid(value: str, needle: str) -> None:
    report = pure(action_ui(value))
    found = [f for f in report.errors if f.code == "validate.bad_shortcut"]
    assert len(found) == 1 and needle in found[0].message
    assert len(found[0].message) < 300  # absurd values are clipped


def _bar(action: Action) -> Menubar:
    menu = Menu(id="m")
    menu.append_child(action)
    bar = Menubar()
    bar.append_child(menu)
    return bar


def test_r71_empty_shortcut_is_an_error_and_none_is_fine() -> None:
    assert "validate.bad_shortcut" in codes(pure(action_ui("")))
    document = doc_with(
        Window(
            id="w",
            kind="main",
            layout=Layout(type="grid"),
            menubar=_bar(Action(id="a")),
        )
    )
    assert "validate.bad_shortcut" not in codes(validate(document, default_registry()))


def test_r71_non_text_shortcut() -> None:
    action = Action(id="a")
    action.shortcut = 7  # type: ignore[assignment]
    document = doc_with(
        Window(id="w", kind="main", layout=Layout(type="grid"), menubar=_bar(action))
    )
    found = codes(validate(document, default_registry()))
    assert "validate.not_text" in found and "validate.bad_shortcut" not in found


def test_r73_duplicate_shortcut_is_a_warning() -> None:
    report = pure(action_ui("Ctrl+S", "ctrl+s", "Ctrl+O", "Ctrl+Shift+P", "shift+ctrl+p"))
    dups = [f for f in report.warnings if f.code == "validate.duplicate_shortcut"]
    assert [d.params["shortcut"] for d in dups] == ["Ctrl+S", "Ctrl+Shift+P"]
    assert dups[0].params["window"] == "win_0"
    assert report.ok


def test_r73_enter_and_return_clash_but_windows_are_independent() -> None:
    dups = codes(pure(action_ui("Ctrl+Enter", "Ctrl+Return")))
    assert dups.count("validate.duplicate_shortcut") == 1
    assert "validate.duplicate_shortcut" not in codes(pure(action_ui("Ctrl+S", windows=2)))


def test_r73_invalid_shortcuts_do_not_count_as_duplicates() -> None:
    report = pure(action_ui("Q", "Q"))
    assert "validate.duplicate_shortcut" not in codes(report)


# ---------------------------------------------------------------- R72 key sequences
def key_ui(sequence: str) -> str:
    body = window(
        "main",
        "main",
        f'<widget class="Entry" id="ent"><event name="key:{escape(sequence)}" handler="on_key"/>'
        '<cell row="0" column="0"/></widget>',
    )
    return ui_text(body)


@pytest.mark.parametrize(
    "sequence", ["Return", "F5", "Ctrl+S", "<Control-s>", "<Return>", "<Key-F12>"]
)
def test_r72_valid(sequence: str) -> None:
    assert "validate.bad_key_sequence" not in codes(pure(key_ui(sequence)))


@pytest.mark.parametrize(
    "sequence",
    [
        "<Button-1>",
        "<Control-Control-s>",
        "nope",
        "Ctrl+Ctrl+S",
        "<Control-ss>",
        "<<Copy>>",
        "x" * 500,
    ],
)
def test_r72_invalid(sequence: str) -> None:
    report = pure(key_ui(sequence))
    found = [f for f in report.errors if f.code == "validate.bad_key_sequence"]
    assert len(found) == 1
    assert "key:<Control-s>" in found[0].message


def test_r72_empty_sequence_is_still_r36() -> None:
    found = codes(pure(key_ui("")))
    assert "validate.bad_event" in found and "validate.bad_key_sequence" not in found


# ---------------------------------------------------------------- R74 to R76 images
def image_ui(src: str) -> str:
    return ui_text(window("main", "main"), resources=f'<image id="img" src="{src}"/>')


@pytest.mark.parametrize(
    "src", ["a.jpg", "a.bmp", "a.svg", "a", "a.png.exe", "a.", ".ico", "dir/a.webp"]
)
def test_r74_unsupported_formats(src: str) -> None:
    report = pure(image_ui(src))
    assert "validate.image_format" in codes(report)


@pytest.mark.parametrize("src", ["a.png", "a.PNG", "a.Gif", "dir/a.ppm", "a.pgm", "../a.png"])
def test_r74_supported_formats(src: str) -> None:
    assert "validate.image_format" not in codes(pure(image_ui(src)))


def test_r74_pure_run_never_probes_the_disk() -> None:
    found = codes(pure(image_ui("missing.png")))
    assert "validate.image_missing" not in found and "validate.image_invalid" not in found


def probe(tmp_path: Path, name: str, data: bytes | None) -> list[str]:
    if data is not None:
        (tmp_path / name).write_bytes(data)
    path = write(tmp_path / "t.ui", image_ui(name))
    return codes(check(path))


def test_images_valid_headers(tmp_path: Path) -> None:
    ok = {
        "a.png": png(16, 16),
        "b.gif": gif(4096, 1),
        "c.ppm": b"P6\n# a comment\n10 20\n255\n" + b"\x00" * 600,
        "d.pgm": b"P5 3 4 255\n" + b"\x00" * 12,
        "e.pgm": b"P5\n1 1\n65535\n\x00\x00",  # 16-bit samples
        "f.ppm": b"P6\n1 1\n255\n\x00\x00\x00 trailing bytes are fine",
        "g.PNG": png(4096, 4096),
        # A colour table and extensions (graphic control, comment) before the first image.
        "h.gif": gif(
            8, 8, frame=(4096, 2), palette=True, extensions=b"!\xf9\x04\x01\x00\x00\x00\x00"
        ),
        "i.gif": gif(2, 2, extensions=b"!\xfe" + b"\xff" + b"c" * 255 + b"\x01x\x00"),
    }
    for name, data in ok.items():
        assert probe(tmp_path, name, data) == [], name


@pytest.mark.parametrize(
    ("name", "data", "reason"),
    [
        ("a.png", b"", "damaged"),
        ("a.png", b"\x89PNG\r\n\x1a\n", "damaged"),
        ("a.png", png(8, 8, ihdr=False), "damaged"),
        ("a.png", png(0, 8), "damaged"),
        ("a.png", png(100_000, 100_000), "4096"),
        ("a.png", png(4097, 1), "4096"),
        ("a.png", png(1, 4097), "4096"),
        ("a.png", gif(4, 4), "does not match"),
        ("a.png", b"not an image at all", "does not match"),
        ("a.png", b"\x00" * 100, "does not match"),
        ("a.gif", png(4, 4), "does not match"),
        ("a.gif", b"GIF89a\x01", "damaged"),
        ("a.gif", gif(0, 5), "damaged"),
        ("a.gif", gif(5000, 5), "4096"),
        # QA-10-10: Tk allocates the first frame from its own descriptor, not the screen size.
        ("a.gif", gif(1, 1, frame=(5000, 5000)), "4096"),
        ("a.gif", gif(1, 1, frame=(1, 4097), palette=True), "4096"),
        ("a.gif", gif(1, 1, frame=(5000, 1), extensions=b"!\xfe\x03abc\x02de\x00"), "4096"),
        ("a.gif", gif(1, 1, frame=(0, 1)), "damaged"),
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00;", "damaged"),  # no image at all
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00", "damaged"),  # ends after the screen
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00,\x00\x00", "damaged"),  # cut descriptor
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00\x00!\xfe\x05ab", "damaged"),  # cut extension
        ("a.gif", b"GIF89a\x01\x00\x01\x00\x00\x00", "damaged"),  # cut screen descriptor
        # QA-11-06: Tk refuses a PNG that ends early, has a bad CRC or misses IDAT/IEND.
        ("a.png", png(8, 8)[:40], "incomplete"),
        ("a.png", png(8, 8)[:-12], "incomplete"),  # no IEND
        ("a.png", png(8, 8)[:-1] + b"\x00", "incomplete"),  # IEND CRC
        ("a.png", png(8, 8)[:33] + chunk(b"IEND", b""), "incomplete"),  # no IDAT
        ("a.png", png(8, 8)[:33] + chunk(b"ABCD", b"") + png(8, 8)[33:], "incomplete"),
        ("a.png", png(8, 8)[:33] + b"\x7f\xff\xff\xffIDAT", "incomplete"),  # huge length
        # QA-11-07: plain-text netpbm, and a raster shorter than its header announces.
        ("a.pgm", b"P2\n2 2\n255\n0 0 0 0\n", "plain-text"),
        ("a.ppm", b"P3\n1 1\n255\n0 0 0\n", "plain-text"),
        ("a.ppm", b"P6\n2 2\n255\n" + b"\x00" * 11, "incomplete"),
        ("a.pgm", b"P5\n2 2\n256\n" + b"\x00" * 7, "incomplete"),
        ("a.ppm", b"P6\n1 1\n0\n\x00\x00\x00", "damaged"),
        ("a.ppm", b"P6\n1 1\n70000\n" + b"\x00" * 6, "damaged"),
        ("a.ppm", b"", "damaged"),
        ("a.ppm", b"P7\n1 1\n", "does not match"),
        ("a.ppm", b"P6", "damaged"),
        ("a.ppm", b"P6\n10", "damaged"),
        ("a.ppm", b"P6\n10 10", "damaged"),
        ("a.ppm", b"P6\n0 5\n255\n", "damaged"),
        ("a.ppm", b"P6\n99999 5\n255\n", "4096"),
        ("a.ppm", b"P610 10\n255\n", "damaged"),
        ("a.ppm", b"P6\n" + b"1" * 12 + b" 5\n255\n", "damaged"),
        ("a.ppm", b"P6\n#" + b"x" * 80 + b"\n5 5\n255\n", "damaged"),
        ("a.pgm", b"P6\nabc\n", "damaged"),
        ("a.ppm", b"P6\n" + b"#" * 10 + b"\n" + b"\n" * 5 + b"-5 5\n", "damaged"),
    ],
)
def test_images_invalid(tmp_path: Path, name: str, data: bytes, reason: str) -> None:
    (tmp_path / name).write_bytes(data)
    path = write(tmp_path / "t.ui", image_ui(name))
    report = check(path)
    found = [f for f in report.errors if f.code == "validate.image_invalid"]
    assert len(found) == 1, report.findings
    assert reason in found[0].message


def test_image_missing_directory_and_oversized(tmp_path: Path) -> None:
    assert probe(tmp_path, "nope.png", None) == ["validate.image_missing"]
    (tmp_path / "dir.png").mkdir()
    path = write(tmp_path / "t.ui", image_ui("dir.png"))
    report = check(path)
    assert codes(report) == ["validate.image_invalid"]
    assert "not a regular file" in report.errors[0].message
    big = tmp_path / "big.png"
    with big.open("wb") as stream:
        stream.write(png(8, 8))
        stream.truncate(MAX_IMAGE_BYTES + 1)
    path = write(tmp_path / "t.ui", image_ui("big.png"))
    assert "16 MiB" in check(path).errors[0].message
    just = tmp_path / "just.png"
    with just.open("wb") as stream:
        stream.write(png(8, 8))
        stream.truncate(MAX_IMAGE_BYTES)
    path = write(tmp_path / "t.ui", image_ui("just.png"))
    assert codes(check(path)) == []


def test_image_path_escape_and_absolute_stay_warnings(tmp_path: Path) -> None:
    (tmp_path / "up.png").write_bytes(png(2, 2))
    sub = tmp_path / "sub"
    sub.mkdir()
    path = write(sub / "t.ui", image_ui("../up.png"))
    report = check(path)
    assert report.ok and codes(report) == ["validate.path_escapes"]
    absolute = write(sub / "abs.ui", image_ui(str(tmp_path / "up.png").replace("\\", "/")))
    assert check(absolute).ok


def test_image_probe_uses_the_folder_of_its_own_file(tmp_path: Path) -> None:
    comp_dir = tmp_path / "parts"
    comp_dir.mkdir()
    (comp_dir / "icon.png").write_bytes(png(2, 2))
    write(
        comp_dir / "comp.ui",
        ui_text(window("comp"), resources='<image id="icn" src="icon.png"/>'),
    )
    main = write(
        tmp_path / "main.ui",
        ui_text(window("main", "main", include("inc", "parts/comp.ui", "comp"))),
    )
    assert codes(check(main)) == []
    (comp_dir / "icon.png").unlink()
    report = check(main)
    assert codes(report) == ["validate.include_invalid", "validate.image_missing"]
    assert report.findings[0].source.endswith("main.ui")
    assert report.findings[1].source.endswith("comp.ui")


# ---------------------------------------------------------------- R77 and R78
def radio_ui(var_type: str, value: str | None, bind: str = "v") -> str:
    prop = "" if value is None else f'<prop name="value">{value}</prop>'
    body = window(
        "main",
        "main",
        f'<widget class="Radiobutton" id="rad" bind="{bind}">{prop}<cell row="0" column="0"/></widget>',  # noqa: E501
    )
    return ui_text(body, variables=f'<var id="v" type="{var_type}"/>')


@pytest.mark.parametrize("value", ["1", "-5", "0", "123456789"])
def test_r77_valid_int_values(value: str) -> None:
    assert "validate.bad_radio_value" not in codes(pure(radio_ui("int", value)))


@pytest.mark.parametrize("value", [None, "", "x", "1.5", "1234567890", "1 2", "--1", "١"])  # noqa: RUF001
def test_r77_invalid_int_values(value: str | None) -> None:
    text = radio_ui("int", value)
    report = pure(text)
    assert codes(report).count("validate.bad_radio_value") == 1
    assert "whole number" in report.errors[0].message


def test_r77_string_variable_and_other_widgets_are_free() -> None:
    assert "validate.bad_radio_value" not in codes(pure(radio_ui("string", "anything")))
    assert "validate.bad_radio_value" not in codes(pure(radio_ui("string", None)))
    # an int variable bound to an Entry has no "value"
    body = window(
        "main", "main", '<widget class="Entry" id="e" bind="v"><cell row="0" column="0"/></widget>'
    )
    text = ui_text(body, variables='<var id="v" type="int"/>')
    assert "validate.bad_radio_value" not in codes(pure(text))


def test_r77_mismatched_type_reports_only_the_binding_error() -> None:
    found = codes(pure(radio_ui("bool", "x")))
    assert "validate.bind_type_mismatch" in found and "validate.bad_radio_value" not in found


@pytest.mark.parametrize("domain", ["hello", "my-app.v2", "A_b", "0x", "a" * 64])
def test_r78_valid_domains(domain: str) -> None:
    text = ui_text(window("main", "main"), meta=f' i18n_domain="{domain}"')
    assert "validate.bad_i18n_domain" not in codes(pure(text))


@pytest.mark.parametrize(
    "domain", ["../x", "a..b", "..", "a/b", "a\\b", "a b", "-x", ".x", "a" * 65, "café", "a:b"]
)
def test_r78_invalid_domains(domain: str) -> None:
    text = ui_text(window("main", "main"), meta=f' i18n_domain="{domain}"')
    report = pure(text)
    assert codes(report).count("validate.bad_i18n_domain") == 1


def test_r78_empty_domain_means_no_catalogue() -> None:
    assert "validate.bad_i18n_domain" not in codes(pure(ui_text(window("main", "main"))))


# ---------------------------------------------------------------- R81 source_locale (QA-11-11)
def locale_ui(value: str) -> str:
    return ui_text(window("main", "main")).replace(
        'source_locale="en_GB"', f'source_locale="{value}"'
    )


@pytest.mark.parametrize("value", ["en_GB", "pt-BR", "de", "en_XA", "sr_Latn_RS", "fil_PH"])
def test_r81_valid_source_locales(value: str) -> None:
    assert "validate.bad_source_locale" not in codes(pure(locale_ui(value)))


@pytest.mark.parametrize(
    "value", ["", "x", "en_", "de_DE/../x", "en_XA;rm", "x'); import os #", "de_DE.UTF-8", "ñu"]
)
def test_r81_invalid_source_locales(value: str) -> None:
    report = pure(locale_ui(value))
    assert codes(report).count("validate.bad_source_locale") == 1
    assert not report.ok


# ---------------------------------------------------------------- includes: R49 to R52
def project(tmp_path: Path, files: dict[str, str], root: str = "main.ui") -> ValidationReport:
    for name, text in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return check(tmp_path / root)


def main_with(*includes: str) -> str:
    return ui_text(window("main", "main", "".join(includes)))


def test_files_none_skips_the_file_rules(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with(include("inc", "gone.ui", "comp")))
    assert validate_read(read_ui(path), default_registry()).ok
    assert codes(check(path)) == ["validate.include_missing"]


def test_r49_missing_directory_and_garbage_paths(tmp_path: Path) -> None:
    (tmp_path / "adir").mkdir()
    for src in ("gone.ui", "adir", "sub/gone.ui", "../../../../gone.ui", "a|b.ui"):
        report = project(tmp_path, {"main.ui": main_with(include("inc", src, "comp"))})
        assert "validate.include_missing" in codes(report), src
        assert not report.ok
    msg = report.errors[0].message
    assert "does not exist or cannot be read" in msg


def test_r49_nul_and_whitespace_paths_do_not_crash(tmp_path: Path) -> None:
    from pyguibud.core import read_ui_string

    for src in ("a\x00b.ui", " ", "\t"):
        document = read_ui_string(main_with(include("inc", "x.ui", "comp"))).document
        inc = document.children[0].children[0]
        inc.src = src  # type: ignore[union-attr]
        main = write(tmp_path / "m.ui", main_with(include("inc", "x.ui", "comp")))
        result = read_ui(main)
        report = validate(document, default_registry(), files=DiskFiles(main, result))
        assert not report.ok


def test_r50_unreadable_and_invalid_included_files(tmp_path: Path) -> None:
    report = project(
        tmp_path,
        {
            "main.ui": main_with(
                include("inc", "bad.ui", "comp"), include("inc2", "xml.ui", "c", 1)
            ),
            "bad.ui": "<not-pyguibud/>",
            "xml.ui": "<unclosed",
        },
    )
    assert codes(report) == ["validate.include_invalid", "validate.include_invalid"]
    assert "cannot be read" in report.errors[0].message


def test_r50_includes_the_error_count_and_foreign_findings(tmp_path: Path) -> None:
    broken = ui_text(
        window("comp", "component", label("lbl_a") + label("lbl_a", 1) + label("class", 2))
    )
    report = project(
        tmp_path, {"main.ui": main_with(include("inc", "broken.ui", "comp")), "broken.ui": broken}
    )
    assert codes(report)[0] == "validate.include_invalid"
    first = report.findings[0]
    assert first.code == "validate.include_invalid" and first.source.endswith("main.ui")
    assert first.params["count"] == 2
    assert "has 2 errors" in first.message
    foreign = [f for f in report.findings if f.source.endswith("broken.ui")]
    assert {f.code for f in foreign} == {"validate.duplicate_id", "validate.keyword_id"}
    # one error is singular
    one = ui_text(window("comp", "component", label("lbl_a") + label("lbl_a", 1)))
    report = project(
        tmp_path, {"main.ui": main_with(include("inc", "broken.ui", "comp")), "broken.ui": one}
    )
    assert "has 1 error." in report.findings[0].message


def test_r51_missing_window_and_wrong_kind(tmp_path: Path) -> None:
    files = {
        "comp.ui": ui_text(window("comp") + window("other", "dialog")),
        "main.ui": main_with(
            include("inc_a", "comp.ui", "nope", 0),
            include("inc_b", "comp.ui", "other", 1),
            include("inc_c", "main.ui", "main", 2),
        ),
    }
    report = project(tmp_path, files)
    assert codes(report) == ["validate.include_not_component"] * 3
    assert "has no component window 'nope'" in report.errors[0].message
    assert "is not a component" in report.errors[1].message
    assert "is not a component" in report.errors[2].message


def test_valid_includes_same_file_and_nested(tmp_path: Path) -> None:
    files = {
        "main.ui": ui_text(
            window(
                "main",
                "main",
                include("inc_a", "#", "local", 0) + include("inc_b", "parts/a.ui", "part_a", 1),
            )
            + window("local", "component", label("lbl_local"))
        ),
        "parts/a.ui": ui_text(
            window("part_a", "component", include("inc_c", "b.ui", "part_b") + label("lbl_a", 1))
        ),
        "parts/b.ui": ui_text(window("part_b", "component", label("lbl_b"))),
    }
    assert codes(project(tmp_path, files)) == []


def test_same_file_include_also_by_real_path_and_hash_file_is_a_real_name(tmp_path: Path) -> None:
    files = {
        "main.ui": ui_text(
            window(
                "main",
                "main",
                include("inc_a", "main.ui", "local", 0) + include("inc_b", "./main.ui", "local", 1),
            )
            + window("local", "component", label("lbl_local"))
        )
    }
    assert codes(project(tmp_path, files)) == []
    files = {"main.ui": main_with(include("inc", "./#", "comp"))}
    assert codes(project(tmp_path, files)) == ["validate.include_missing"]


def test_r52_self_include_via_hash(tmp_path: Path) -> None:
    body = window("main", "main", include("inc_m", "#", "comp")) + window(
        "comp", "component", include("inc_self", "#", "comp")
    )
    report = project(tmp_path, {"main.ui": ui_text(body)})
    cycles = [f for f in report.errors if f.code == "validate.include_cycle"]
    assert len(cycles) == 1
    assert cycles[0].params["chain"] == "main.ui#comp → main.ui#comp"
    assert "creates a cycle" in cycles[0].message


def test_r52_two_file_cycle_reported_once(tmp_path: Path) -> None:
    files = {
        "main.ui": main_with(include("inc", "a.ui", "ca")),
        "a.ui": ui_text(window("ca", "component", include("inc_b", "b.ui", "cb"))),
        "b.ui": ui_text(window("cb", "component", include("inc_a", "a.ui", "ca"))),
    }
    report = project(tmp_path, files)
    found = [f for f in report.findings if f.code == "validate.include_cycle"]
    assert len(found) == 1
    assert found[0].params["chain"] == "a.ui#ca → b.ui#cb → a.ui#ca"
    assert found[0].source.endswith("b.ui")
    assert codes(report).count("validate.include_invalid") == 0  # nested include in b.ui is checked


def test_r52_cycle_between_root_components(tmp_path: Path) -> None:
    body = (
        window("main", "main")
        + window("ca", "component", include("i1", "#", "cb"))
        + window("cb", "component", include("i2", "#", "ca"))
    )
    report = project(tmp_path, {"main.ui": ui_text(body)})
    found = [f for f in report.findings if f.code == "validate.include_cycle"]
    assert len(found) == 1
    assert found[0].params["chain"] == "main.ui#ca → main.ui#cb → main.ui#ca"


def test_diamond_includes_are_not_cycles(tmp_path: Path) -> None:
    files = {
        "main.ui": main_with(include("i1", "a.ui", "ca", 0), include("i2", "b.ui", "cb", 1)),
        "a.ui": ui_text(window("ca", "component", include("ia", "leaf.ui", "leaf"))),
        "b.ui": ui_text(window("cb", "component", include("ib", "leaf.ui", "leaf"))),
        "leaf.ui": ui_text(window("leaf", "component", label("lbl"))),
    }
    assert codes(project(tmp_path, files)) == []


def test_case_variant_and_dot_paths_are_one_file(tmp_path: Path) -> None:
    files = {
        "main.ui": main_with(
            include("i1", "sub/../comp.ui", "comp", 0), include("i2", "./comp.ui", "comp", 1)
        ),
        "comp.ui": ui_text(window("comp", "component", label("lbl"))),
    }
    assert codes(project(tmp_path, files)) == []
    result = read_ui(tmp_path / "main.ui")
    disk = DiskFiles(tmp_path / "main.ui", result)
    key = disk.resolve(disk.root, "comp.ui")
    assert key == disk.resolve(disk.root, "sub/../comp.ui")
    if os.path.normcase("A") == "a":  # Windows: one key for case variants
        assert key == disk.resolve(disk.root, "COMP.ui")


# ---------------------------------------------------------------- includes: R53 limits
def test_r53_depth_bomb(tmp_path: Path) -> None:
    levels = MAX_INCLUDE_DEPTH + 2
    body = window("main", "main", include("inc", "#", "d0"))
    for i in range(levels):
        inner = include(f"inc_{i}", "#", f"d{i + 1}") if i + 1 < levels else label("lbl")
        body += window(f"d{i}", "component", inner)
    report = project(tmp_path, {"main.ui": ui_text(body)})
    found = [f for f in report.errors if f.code == "validate.include_limit"]
    assert len(found) == 1
    assert "deeper than 8 levels" in found[0].message
    assert codes(report) == ["validate.include_limit"]


def test_r53_exactly_the_maximum_depth_is_fine(tmp_path: Path) -> None:
    body = window("main", "main", include("inc", "#", "d0"))
    for i in range(MAX_INCLUDE_DEPTH):
        inner = include(f"inc_{i}", "#", f"d{i + 1}") if i + 1 < MAX_INCLUDE_DEPTH else label("lbl")
        body += window(f"d{i}", "component", inner)
    assert codes(project(tmp_path, {"main.ui": ui_text(body)})) == []


def test_r53_depth_found_through_a_memoised_component(tmp_path: Path) -> None:
    # Two roads to the same chain: a short one explored first, then a deep one.
    n = MAX_INCLUDE_DEPTH - 1
    body = window(
        "main", "main", include("i_short", "#", "d0", 0) + include("i_deep", "#", "pre0", 1)
    )
    for i in range(n):
        inner = include(f"i_{i}", "#", f"d{i + 1}") if i + 1 < n else label("lbl")
        body += window(f"d{i}", "component", inner)
    body += window("pre0", "component", include("p1", "#", "pre1"))
    body += window("pre1", "component", include("p2", "#", "d0"))
    report = project(tmp_path, {"main.ui": ui_text(body)})
    assert codes(report) == ["validate.include_limit"]
    assert anchor_id(report.errors[0]) == "p2"


def test_r53_file_limit(tmp_path: Path) -> None:
    count = MAX_INCLUDE_FILES + 5
    files = {"main.ui": main_with(*(include(f"inc_{i}", f"f{i}.ui", "c", i) for i in range(count)))}
    for i in range(count):
        files[f"f{i}.ui"] = ui_text(window("c", "component", label("lbl")))
    report = project(tmp_path, files)
    limits = [f for f in report.errors if f.code == "validate.include_limit"]
    assert len(limits) == 1 and "reads more than 32 files" in limits[0].message
    assert len(anchor_id(limits[0])) > 0
    assert codes(report) == ["validate.include_limit"]


def test_r53_exactly_the_maximum_number_of_files_is_fine(tmp_path: Path) -> None:
    count = MAX_INCLUDE_FILES - 1  # plus the root
    files = {"main.ui": main_with(*(include(f"inc_{i}", f"f{i}.ui", "c", i) for i in range(count)))}
    for i in range(count):
        files[f"f{i}.ui"] = ui_text(window("c", "component", label("lbl")))
    assert codes(project(tmp_path, files)) == []


@pytest.mark.budget
def test_r53_fan_out_bomb_is_cheap_and_reported(tmp_path: Path) -> None:
    body = window("main", "main", include("inc", "#", "l0"))
    for level in range(5):
        children = "".join(include(f"i_{level}_{k}", "#", f"l{level + 1}", k) for k in range(10))
        body += window(f"l{level}", "component", children)
    body += window("l5", "component", label("lbl"))
    started = time.perf_counter()
    report = project(tmp_path, {"main.ui": ui_text(body)})
    assert time.perf_counter() - started < 2.0
    limits = [f for f in report.errors if f.code == "validate.include_limit"]
    assert len(limits) == 1 and "more than 10000 widgets" in limits[0].message
    assert codes(report) == ["validate.include_limit"]


def test_r53_widget_limit_through_one_big_component(tmp_path: Path) -> None:
    many = "".join(label(f"lbl_{i}", i) for i in range(60))
    body = window("main", "main", "".join(include(f"i_{k}", "#", "big", k) for k in range(200)))
    body += window("big", "component", many)
    report = project(tmp_path, {"main.ui": ui_text(body)})
    limits = [f for f in report.errors if f.code == "validate.include_limit"]
    assert len(limits) == 1
    assert 60 * 166 <= MAX_EXPANDED_NODES < 60 * 167  # the 167th include is the first over
    assert anchor_id(limits[0]) == "i_166"


def test_r53_a_component_alone_may_be_large(tmp_path: Path) -> None:
    many = "".join(label(f"lbl_{i}", i) for i in range(MAX_EXPANDED_NODES + 5))
    body = window("main", "main") + window(
        "big", "component", many + include("inc", "#", "tiny", MAX_EXPANDED_NODES + 5)
    )
    body += window("tiny", "component", label("lbl_t"))
    assert "validate.include_limit" not in codes(project(tmp_path, {"main.ui": ui_text(body)}))


def test_limits_stop_following_further_includes(tmp_path: Path) -> None:
    body = window(
        "main",
        "main",
        include("i1", "#", "l0", 0) + include("i2", "gone.ui", "x", 1),
    )
    for i in range(MAX_INCLUDE_DEPTH + 1):
        inner = include(f"c{i}", "#", f"l{i + 1}") if i < MAX_INCLUDE_DEPTH else label("lbl")
        body += window(f"l{i}", "component", inner)
    report = project(tmp_path, {"main.ui": ui_text(body)})
    assert codes(report) == ["validate.include_limit"]  # i2 was never followed


# ---------------------------------------------------------------- DiskFiles
def test_diskfiles_root_and_caching(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with(include("inc", "comp.ui", "comp")))
    comp = write(tmp_path / "comp.ui", ui_text(window("comp")))
    result = read_ui(path)
    disk = DiskFiles(path, result)
    assert disk.read(disk.root) is result
    key = disk.resolve(disk.root, "comp.ui")
    first = disk.read(key)
    comp.write_text("<broken", encoding="utf-8")
    assert disk.read(key) is first  # cached: never read twice
    assert disk.resolve(key, "#") == key
    assert disk.path_of(key).endswith("comp.ui")


def test_diskfiles_errors_are_cached_and_typed(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with(include("inc", "bad.ui", "c")))
    write(tmp_path / "bad.ui", "<nope")
    (tmp_path / "adir").mkdir()
    disk = DiskFiles(path, read_ui(path))
    key = disk.resolve(disk.root, "bad.ui")
    with pytest.raises(XmlIoError) as first:
        disk.read(key)
    with pytest.raises(XmlIoError) as second:
        disk.read(key)
    assert first.value is second.value
    with pytest.raises(OSError):
        disk.read(disk.resolve(disk.root, "adir"))
    with pytest.raises(OSError):
        disk.read(disk.resolve(disk.root, "missing.ui"))
    with pytest.raises(OSError):
        disk.resolve(disk.root, "")
    with pytest.raises(OSError):
        disk.resolve(disk.root, "a\x00b")


def test_diskfiles_rejects_oversized_ui_files(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with(include("inc", "huge.ui", "c")))
    with (tmp_path / "huge.ui").open("wb") as stream:
        stream.write(b"<x/>")
        stream.truncate(11 * 1024 * 1024)
    report = check(path)
    assert codes(report) == ["validate.include_invalid"]
    assert "cannot be read" in report.errors[0].message


def test_probe_image_results(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with())
    (tmp_path / "ok.png").write_bytes(png(30, 20))
    disk = DiskFiles(path, read_ui(path))
    assert disk.probe_image(disk.root, "ok.png") == ImageProbe("ok", "", 30, 20)
    assert disk.probe_image(disk.root, "no.png").status == "missing"
    assert disk.probe_image(disk.root, "a\x00.png").status == "invalid"
    assert disk.probe_image(disk.root, "").status == "invalid"


# ---------------------------------------------------------------- custom FileAccess
class FakeFiles:
    """An in-memory FileAccess: the validator must not care where files live."""

    def __init__(self, files: dict[str, str], images: dict[str, ImageProbe]) -> None:
        from pyguibud.core import read_ui_string

        self._files = {k: read_ui_string(v, source=k) for k, v in files.items()}
        self._images = images
        self.reads: list[str] = []

    @property
    def root(self) -> str:
        return "root"

    def resolve(self, including: str, src: str) -> str:
        return including if src == "#" else src

    def read(self, key: str):  # type: ignore[no-untyped-def]
        self.reads.append(key)
        if key not in self._files:
            raise FileNotFoundError(key)
        return self._files[key]

    def probe_image(self, including: str, src: str) -> ImageProbe:
        return self._images.get(src, ImageProbe("missing"))


def test_validate_accepts_any_file_access() -> None:
    comp = ui_text(
        window("comp", "component", label("lbl")), resources='<image id="i" src="x.png"/>'
    )
    root = ui_text(
        window("main", "main", include("i1", "comp", "comp") + include("i2", "comp", "comp", 1))
    )
    fake = FakeFiles({"root": root, "comp": comp}, {"x.png": ImageProbe("ok", "", 1, 1)})
    report = validate(fake.read("root").document, default_registry(), files=fake)
    assert report.findings == ()
    assert fake.reads.count("comp") == 1  # read once for two includes
    bad = FakeFiles(
        {"root": root, "comp": comp}, {"x.png": ImageProbe("invalid", "its header is damaged")}
    )
    report = validate(bad.read("root").document, default_registry(), files=bad)
    assert codes(report) == ["validate.include_invalid"] * 2 + ["validate.image_invalid"]
    assert "its header is damaged" in report.findings[2].message


def test_validation_cap_applies_to_included_findings(tmp_path: Path) -> None:
    many = "".join(label(f"lbl_{i}") for i in range(50))  # 49 cell collisions + ... all errors
    files = {
        "main.ui": main_with(include("inc", "comp.ui", "comp")),
        "comp.ui": ui_text(window("comp", "component", many)),
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text, encoding="utf-8")
    result = read_ui(tmp_path / "main.ui")
    report = validate_read(
        result, default_registry(), files=DiskFiles(tmp_path / "main.ui", result)
    )
    assert len(report.findings) > 10
    capped = validate(
        result.document,
        default_registry(),
        source=result.source,
        files=DiskFiles(tmp_path / "main.ui", result),
        limit=5,
    )
    assert capped.truncated and len(capped.findings) == 5 and not capped.ok


# ---------------------------------------------------------------- hand-built models
def test_hand_built_model_with_files(tmp_path: Path) -> None:
    path = write(tmp_path / "main.ui", main_with())
    disk = DiskFiles(path, read_ui(path))
    document = doc_with(Window(id="w", kind="main", layout=Layout(type="grid")))
    document._children.append("not a window")  # type: ignore[arg-type]
    document.resources["img"] = ImageResource(id="img", src="x.png")
    document.variables["v"] = Variable(id="v", type="string")
    found = codes(validate(document, default_registry(), files=disk))
    assert "validate.image_missing" in found


def test_widget_include_in_widget_subtree_is_followed(tmp_path: Path) -> None:
    nested = (
        '<widget class="Frame" id="frm"><cell row="0" column="0"/><layout type="grid"/>'
        + include("inc", "gone.ui", "comp")
        + "</widget>"
    )
    path = write(tmp_path / "main.ui", ui_text(window("main", "main", nested)))
    assert codes(check(path)) == ["validate.include_missing"]


def test_guard_style_event_prop_helpers_still_importable() -> None:
    # Smoke: the names the command guards use are untouched by the new rules.
    assert Event(name="command", handler="h").name == "command"
    assert Prop(name="x", value="y").value == "y"
    assert Statusbar(id="s").id == "s"
    assert Widget(class_name="Label", id="l").id == "l"
