"""QA abuse tests of Step 17a "Plugin API (headless)" (spec docs/specs/plugins.md §0-§14a).

What a careless or hostile user does with the five ``tb:`` widgets before their factories exist
(17b): hostile ``tb:bootstyle`` values, format-string tricks, ';' column lists, date formats,
wrong fallbacks, prefix games, the clipboard, the inspector, the real CLI, codegen, ``load_ui``
on three backends and the designer (palette drag, undo/redo storm, Save as, reopen).

Passing tests pin behaviour QA verified. Strict xfails are the open findings QA-17a-NN; each
says what is expected. Tk, Qt and designer scenarios run in a fresh interpreter with a hard
timeout (ttkbootstrap allows one root per process), marked ``gui``.
"""

# ruff: noqa: E501 - long literal .ui documents and subprocess scripts
from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import NS_TB, WIDGETS_GROUP, Registry, Widget, dump_ui, read_ui
from pyguibud.core.commands import CommandStack, SetExtraAttr
from pyguibud.core.errors import XmlIoError
from pyguibud.core.validate import validate

ROOT = Path(__file__).resolve().parents[2]
ACME_DEMO = ROOT / "examples" / "acme_demo.ui"
BOOTSTYLE = f"{{{NS_TB}}}bootstyle"
HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "QT_QPA_PLATFORM": "offscreen"}
for _name in ("PYGUIBUD_LANG", "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
    ENV.pop(_name, None)
ENV["PYGUIBUD_LANG"] = "en_GB"  # children must not follow the host locale
UIC = [sys.executable, "-m", "pyguibud.uic"]
LOCALES = ["en_GB", "es_ES", "pt_PT", "pt_BR", "de_DE", "it_IT", "nl_NL", "fr_FR", "en_XA"]


def _acme_installed() -> bool:
    try:
        importlib.metadata.distribution("acme-pyguibud")
    except importlib.metadata.PackageNotFoundError:
        return False
    return True


# ------------------------------------------------------------------ document builders
_HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" {ns}>
  <meta source_locale="en_GB"/>
  <variables><var id="v_s" type="string"/><var id="v_d" type="double"/><var id="v_b" type="bool"/><var id="v_i" type="int"/></variables>
  <window id="main" kind="main">
    <layout type="grid"/>
{body}  </window>
</pyguibud-ui>
"""
_TB_NS = f'xmlns:tb="{NS_TB}"'


def _doc(body: str, ns: str = _TB_NS) -> str:
    return _HEAD.format(ns=ns, body=body)


def _w(cls: str, fallback: str | None, props: str = "", attrs: str = "", events: str = "") -> str:
    fb = f' fallback="{fallback}"' if fallback else ""
    return (
        f'    <widget class="{cls}" id="w1"{fb}{attrs}>\n{props}{events}'
        '      <cell row="0" column="0"/>\n    </widget>\n'
    )


def _p(name: str, value: str) -> str:
    return f'      <prop name="{name}">{value}</prop>\n'


def _meter(props: str = "", attrs: str = "") -> str:
    return _w("tb:Meter", "Progressbar", props, attrs)


def _table(columns: str) -> str:
    return _w("tb:Tableview", "Treeview", _p("columns", columns))


def _date(name: str, value: str) -> str:
    return _w("tb:DateEntry", "Entry", _p(name, value))


def _registry() -> Registry:
    """Core + tb: through the safety net, independent of installed plugins."""
    return Registry(entry_points=lambda group: ())


def _findings(
    tmp_path: Path, text: str, name: str = "case.ui"
) -> tuple[set[str], set[str], list[Any]]:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    result = read_ui(str(path))
    report = validate(result.document, _registry())
    errors = {f.code for f in report.errors}
    warnings = {f.code for f in report.warnings} | {w.code for w in result.warnings}
    return errors, warnings, [*report.errors, *report.warnings]


# ------------------------------------------------------------------ the hostile corpus
REFUSED: dict[str, tuple[str, str]] = {
    # tb:bootstyle (R83): huge, unicode, control characters, ';' lists, empty, upper case
    "bootstyle_100k": (
        _meter(attrs=' tb:bootstyle="' + "a" * 100_000 + '"'),
        "validate.bad_bootstyle",
    ),
    "bootstyle_65": (_meter(attrs=' tb:bootstyle="' + "a" * 65 + '"'), "validate.bad_bootstyle"),
    "bootstyle_unicode": (_meter(attrs=' tb:bootstyle="primàry"'), "validate.bad_bootstyle"),
    "bootstyle_newline": (_meter(attrs=' tb:bootstyle="primary&#10;"'), "validate.bad_bootstyle"),
    "bootstyle_tab": (_meter(attrs=' tb:bootstyle="primary&#9;info"'), "validate.bad_bootstyle"),
    "bootstyle_semicolon": (
        _w("tb:ToggleButton", "Checkbutton", attrs=' tb:bootstyle="primary;x"'),
        "validate.bad_bootstyle",
    ),
    "bootstyle_empty": (_meter(attrs=' tb:bootstyle=""'), "validate.bad_bootstyle"),
    "bootstyle_double_space": (
        _meter(attrs=' tb:bootstyle="primary  info"'),
        "validate.bad_bootstyle",
    ),
    "bootstyle_upper": (_meter(attrs=' tb:bootstyle="PRIMARY"'), "validate.bad_bootstyle"),
    "bootstyle_on_unregistered": (
        _w("tb:Nonsense", "Label", attrs=' tb:bootstyle="a;b"'),
        "validate.bad_bootstyle",
    ),
    # Meter amount_format / Floodgauge mask (R89/R90): attribute walks and huge widths
    "format_attribute_walk": (_meter(_p("amount_format", "{0.__class__}")), "validate.bad_pattern"),
    "format_huge_width": (_meter(_p("amount_format", "{:>999999999}")), "validate.bad_pattern"),
    "format_two_fields": (_meter(_p("amount_format", "{}{}")), "validate.bad_pattern"),
    "format_7_decimals": (_meter(_p("amount_format", "{:.7f}")), "validate.bad_pattern"),
    "format_empty": (_meter(_p("amount_format", "")), "validate.bad_pattern"),
    "format_no_field": (_meter(_p("amount_format", "abc")), "validate.bad_pattern"),
    "format_33_chars": (_meter(_p("amount_format", "{}" + "x" * 31)), "validate.value_too_long"),
    "mask_globals": (
        _w("tb:Floodgauge", "Progressbar", _p("mask", "{.__init__.__globals__}")),
        "validate.bad_pattern",
    ),
    # Tableview columns (R89): ';' edge cases
    "columns_empty_item": (_table("a;;b"), "validate.bad_pattern"),
    "columns_trailing": (_table("a;b;"), "validate.bad_pattern"),
    "columns_only_semicolon": (_table(";"), "validate.bad_pattern"),
    "columns_empty": (_table(""), "validate.bad_pattern"),
    "columns_65": (_table(";".join(["c"] * 65)), "validate.bad_pattern"),
    "columns_heading_65": (_table("x" * 65), "validate.bad_pattern"),
    # DateEntry (R89/R90 and ranges)
    "date_format_dash": (_date("date_format", "%-d"), "validate.bad_pattern"),
    "date_format_brace": (_date("date_format", "{}"), "validate.bad_pattern"),
    "date_format_zone": (_date("date_format", "%Z"), "validate.bad_pattern"),
    "date_format_trailing_percent": (_date("date_format", "%Y%"), "validate.bad_pattern"),
    "date_value_arabic_digits": (_date("value", "٢٠٢٦-١٠-١٤"), "validate.bad_pattern"),  # noqa: RUF001
    "date_value_11_chars": (_date("value", "2026-10-141"), "validate.value_too_long"),
    "date_value_newline": (_date("value", "2026-10-14&#10;"), "validate.value_too_long"),
    # QA-17b-01/03: years 1900-9998 only (%y on Windows, the picker's month grid)
    "date_value_year_0001": (_date("value", "0001-01-01"), "validate.bad_pattern"),
    "date_value_year_1899": (_date("value", "1899-12-31"), "validate.bad_pattern"),
    "date_value_year_9999": (_date("value", "9999-12-31"), "validate.bad_pattern"),
    # bind_types (R40-R42 with the extension row) and events
    "meter_bound_to_bool": (_meter(attrs=' bind="v_b"'), "validate.bind_type"),
    "meter_bound_to_string": (_meter(attrs=' bind="v_s"'), "validate.bind_type"),
    "toggle_bound_to_double": (
        _w("tb:ToggleButton", "Checkbutton", attrs=' bind="v_d"'),
        "validate.bind_type",
    ),
    "date_bound_to_int": (_w("tb:DateEntry", "Entry", attrs=' bind="v_i"'), "validate.bind_type"),
    "toggle_select_event": (
        _w("tb:ToggleButton", "Checkbutton", events='      <event name="select" handler="h"/>\n'),
        "validate.bad_event",
    ),
    # fallbacks
    "container_fallback": (
        _meter().replace('fallback="Progressbar"', 'fallback="Frame"'),
        "validate.fallback_container",
    ),
    "no_fallback": (_w("tb:Meter", None), "validate.no_fallback"),
}

ACCEPTED: dict[str, tuple[str, set[str]]] = {
    "format_32_chars": (_meter(_p("amount_format", "{}" + "x" * 30)), set()),
    "format_percent_text": (_meter(_p("amount_format", "%s{:.6f}%d")), set()),
    "bootstyle_64": (_meter(attrs=' tb:bootstyle="' + "-".join(["info"] * 13) + '"'), set()),
    "unknown_tb_attribute": (
        _meter(attrs=' tb:style="x" tb:bootstyle="info"'),
        {"validate.unknown_extension_attr"},
    ),
    "bootstyle_on_text": (
        _w("Text", None, attrs=' tb:bootstyle="danger"'),
        {"validate.bootstyle_ignored"},
    ),
    "bootstyle_unknown_word": (
        _meter(attrs=' tb:bootstyle="zzz-qqq"'),
        {"validate.bootstyle_ignored"},
    ),
    "hostile_plugin_name": (_meter(attrs=' plugin="evil; rm -rf /"'), {"validate.bad_plugin_name"}),
    "columns_duplicates_and_blank": (_table("a;a; "), set()),  # tb.Tableview builds these
    "date_calendar_invalid": (
        _date("value", "2026-13-45"),
        set(),
    ),  # by design: checked at build (§5)
    "meter_maximum_zero": (_meter(_p("maximum", "0")), set()),  # ttkbootstrap 2.2 guards range 0
}


def _codes_of(errors: set[str], warnings: set[str]) -> set[str]:
    return errors | warnings


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_hostile_tb_values_are_errors_with_their_rule(tmp_path: Path, case: str) -> None:
    body, code = REFUSED[case]
    errors, _warnings, findings = _findings(tmp_path, _doc(body))
    if code in (
        "validate.bind_type",
        "validate.bad_event",
        "validate.fallback_container",
        "validate.no_fallback",
    ):
        assert errors, case  # the exact code of these older rules is not 17a's business
    else:
        assert code in errors, (case, errors)
    for finding in findings:  # every message is formatted and short, even for a 100 kB value
        assert "{" + "id}" not in finding.message and len(finding.message) < 400


@pytest.mark.parametrize("case", sorted(ACCEPTED))
def test_tolerated_tb_values_load_without_errors(tmp_path: Path, case: str) -> None:
    body, expected = ACCEPTED[case]
    errors, warnings, _ = _findings(tmp_path, _doc(body))
    assert not errors, (case, errors)
    assert expected <= warnings, (case, warnings)


def test_a_translatable_flag_cannot_smuggle_a_format_past_r89(tmp_path: Path) -> None:
    """A .mo could otherwise swap in '{0.__class__}' after the check."""
    for cls, fallback, name, value in (
        ("tb:Meter", "Progressbar", "amount_format", "{}"),
        ("tb:Floodgauge", "Progressbar", "mask", "{}%"),
        ("tb:DateEntry", "Entry", "date_format", "%Y-%m-%d"),
        ("tb:DateEntry", "Entry", "value", "2026-01-01"),
    ):
        prop = f'      <prop name="{name}" translatable="true">{value}</prop>\n'
        errors, _, _ = _findings(tmp_path, _doc(_w(cls, fallback, prop)))
        assert errors, name


def test_a_second_prop_cannot_override_the_checked_one(tmp_path: Path) -> None:
    props = _p("amount_format", "{}") + _p("amount_format", "{0.__class__}")
    with pytest.raises(XmlIoError, match="more than once"):  # refused by the reader itself
        _findings(tmp_path, _doc(_meter(props)))


def test_a_registered_tb_widget_ignores_a_wrong_fallback_everywhere(tmp_path: Path) -> None:
    """R91 was trimmed (T4): fallback="Label" on tb:Meter is silent; everything uses the spec."""
    errors, warnings, _f = _findings(tmp_path, _doc(_meter().replace("Progressbar", "Label")))
    assert not errors and not warnings
    # Step 17b: ttkbootstrap builds tb:Meter itself; the other backends show the spec fallback.
    assert _registry().resolve("tb:Meter", "ttkbootstrap", "Label").spec.name == "tb:Meter"
    assert _registry().resolve("tb:Meter", "tkinter", "Label").spec.name == "Progressbar"


# ------------------------------------------------------------------ findings (fixed and open)
@pytest.mark.parametrize(
    "value",
    [
        *("", "hello", "%d", "%%%A", "%Y-%m-%d-%d", "%Y%Y-%m-%d"),
        *("%%d-%m-%Y", "%d-%m-%Y %d", "%d %b %B %b %Y", "%d-%m-%Y-%U", "%x", "%d\t%m-%Y"),
    ],
)
def test_qa17a_01_date_formats_that_break_dateentry_are_refused(tmp_path: Path, value: str) -> None:
    """MAJOR, fixed. ttkbootstrap 2.2.3 ``DateEntry(date_format=...)`` raises ValueError for a
    format without year, month and day ('', 'hello', '%d', '%%%A'), and a repeated directive
    builds but makes ``_coerce_date`` raise ``re.error`` (not a ValueError) on every focus-out,
    inside a Tk callback outside any build guard. R89 now needs one day, one month and one
    year code, each code at most once, '%%' read as a literal percent sign."""
    errors, _, _ = _findings(tmp_path, _doc(_date("date_format", value)))
    assert "validate.bad_pattern" in errors


#: Formats R89 accepts; each one must build and round-trip in the real DateEntry.
DATE_FORMATS_ACCEPTED = [
    *("%Y-%m-%d", "%d/%m/%y", "%d %b %Y", "%A, %d %B %Y", "%a %d.%m.%Y (%j)", "%Y%y%m%d"),
    *("%d%%%m%Y", "%%%d-%m-%Y", "%d-%m-%Y %%%%", "%d·%m·%Y", "%d %b %m %Y", "%j: %d %m %Y"),
]


@pytest.mark.parametrize("value", DATE_FORMATS_ACCEPTED)
def test_qa17a_01_sane_date_formats_still_pass(tmp_path: Path, value: str) -> None:
    errors, _, _ = _findings(tmp_path, _doc(_date("date_format", value)))
    assert not errors, (value, errors)


@pytest.mark.gui
def test_qa17a_01_evidence_every_accepted_format_round_trips_in_dateentry() -> None:
    """Build a real DateEntry per accepted format, fire focus-out, and parse the text back."""
    script = textwrap.dedent(
        """
        import json, sys, datetime, ttkbootstrap as tb
        app = tb.App(); app.withdraw(); out = {}; day = datetime.datetime(2026, 2, 9)
        for fmt in json.loads(sys.argv[1]):
            try:
                entry = tb.DateEntry(app, date_format=fmt, start_date=day)
                entry._on_entry_blur()
                parsed = entry._coerce_date(entry.entry.get())
                out[fmt] = "ok" if parsed == day else f"parsed:{parsed}"
            except Exception as exc:
                out[fmt] = "raised:" + type(exc).__name__
        app.destroy(); print(json.dumps(out))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(DATE_FORMATS_ACCEPTED)],
        capture_output=True,
        text=True,
        timeout=60,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-800:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out == dict.fromkeys(DATE_FORMATS_ACCEPTED, "ok")


@pytest.mark.gui
def test_qa17a_01_evidence_ttkbootstrap_dateentry_rejects_what_r89_lets_through(
    tmp_path: Path,
) -> None:
    """The real toolkit behaviour behind QA-17a-01 (passes while the toolkit behaves so)."""
    script = textwrap.dedent(
        """
        import json, ttkbootstrap as tb
        app = tb.App(); app.withdraw(); out = {}
        for fmt in ["", "hello", "%d", "%%%A", "%Y-%m-%d-%d"]:
            try:
                entry = tb.DateEntry(app, date_format=fmt)
            except Exception as exc:
                out[fmt] = "ctor:" + type(exc).__name__; continue
            try:
                entry._coerce_date(entry.entry.get()); out[fmt] = "ok"
            except Exception as exc:
                out[fmt] = "parse:" + type(exc).__name__
        app.destroy(); print(json.dumps(out))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
        env=ENV,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-800:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out[""] == out["hello"] == out["%d"] == out["%%%A"] == "ctor:ValueError"
    assert out["%Y-%m-%d-%d"] == "parse:error"  # re.error escapes DateEntry's except clause


@pytest.mark.parametrize(
    "attrs",
    [
        ' tb:bootstyle="x&#10;forged.ui: no errors found&#10;"',
        ' plugin="a&#10;forged.ui: no errors found&#10;"',
        ' plugin="&#x202E;acme"',
        ' plugin="a&#x85;forged.ui: no errors found&#x2066;"',
    ],
)
def test_qa17a_02_cli_output_does_not_echo_control_characters(tmp_path: Path, attrs: str) -> None:
    """MINOR, fixed at the CLI output layer (orchestrator ruling). A value went into the
    GCC-style line unescaped, so a .ui could forge an 'x.ui: no errors found' line (R86 is
    only a warning, the file still checks clean) or flip the text direction. pyguibud-uic
    now prints control and bidi characters escaped (\\n, \\x85, \\u202e), for every rule."""
    path = tmp_path / "case.ui"
    path.write_text(_doc(_meter(attrs=attrs)), encoding="utf-8")
    result = _uic("--check", str(path))
    assert "Traceback" not in result.stderr and "case.ui" in result.stderr
    for line in result.stderr.split("\n"):
        assert not re.search("[\x00-\x1f\x7f-\x9f‪-‮⁦-⁩]", line), line
        assert not line.startswith("forged.ui"), line
    for line in result.stdout.split("\n"):
        assert "no errors found" not in line or line.startswith(str(path)), line


def test_qa17a_03_tb_prefix_bound_to_a_foreign_namespace(tmp_path: Path) -> None:
    """MINOR. xmlns:tb="urn:evil" makes tb:bootstyle="primary;x" look like an invalid
    bootstyle that checks clean; after a real bootstyle is added the file reads
    tb:bootstyle="primary;x" ns1:bootstyle="info". Data is kept (verified), only the text
    misleads. Expected: the writer binds tb to the ttkbootstrap namespace (renaming the
    foreign prefix), or the reader warns."""
    body = _meter(attrs=' tb:bootstyle="primary;x"')
    path = tmp_path / "evil.ui"
    path.write_text(_doc(body, ns='xmlns:tb="urn:evil"'), encoding="utf-8")
    result = read_ui(str(path))
    widget = next(n for n in result.document.walk() if isinstance(n, Widget))
    stack = CommandStack(result.document, _registry())
    assert stack.execute(SetExtraAttr(widget, BOOTSTYLE, "info"))
    assert f'xmlns:tb="{NS_TB}"' in dump_ui(result.document).decode("utf-8")


@dataclass
class _Dist:
    name: str


@dataclass
class _EP:
    name: str
    value: str
    dist: _Dist | None
    group: str = WIDGETS_GROUP
    loads: int = 0

    def load(self) -> object:
        self.loads += 1
        return list


def test_qa17a_04_a_bare_string_disabled_list_is_not_split_into_letters() -> None:
    """MINOR, fixed. ``Registry(disabled="acme-pyguibud")`` built frozenset('a','c','m',...),
    so the plugin still loaded and a distribution called 'a' would be disabled. 17c feeds this
    from a hand-editable settings.json. A bare string is now one name."""
    ep = _EP("acme", "acme_pyguibud:widgets", _Dist("acme-pyguibud"))
    try:
        registry = Registry(
            entry_points=lambda g: [ep] if g == WIDGETS_GROUP else [], disabled="acme-pyguibud"
        )
    except TypeError:
        return
    registry.load()
    assert ep.loads == 0 and "acme-pyguibud" in registry.disabled_distributions()


# ------------------------------------------------------------------ command and clipboard abuse
@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("{urn:x}a", "\x00", "validate.illegal_char"),
        ("{urn:x}a", "\ud800", "validate.illegal_char"),
        ("{urn:x}a", "x" * (11 * 1024 * 1024), "command.unsaveable"),
        (BOOTSTYLE, "primary\n", "validate.bad_bootstyle"),
        (BOOTSTYLE, "  ", "validate.bad_bootstyle"),
    ],
    ids=["nul", "lone_surrogate", "11_mib", "bootstyle_newline", "bootstyle_blank"],
)
def test_set_extra_attr_refuses_hostile_values_and_changes_nothing(
    key: str, value: str, code: str
) -> None:
    document = read_ui(str(ACME_DEMO)).document
    before = dump_ui(document)
    widget = next(n for n in document.walk() if isinstance(n, Widget) and n.id == "tbl_items")
    outcome = CommandStack(document, _registry()).execute(SetExtraAttr(widget, key, value))
    assert not outcome and code in {f.code for f in outcome.findings} | {
        getattr(outcome, "code", "")
    }
    assert outcome.message and dump_ui(document) == before


def test_set_extra_attr_refuses_the_xmlns_namespace() -> None:
    document = read_ui(str(ACME_DEMO)).document
    widget = next(n for n in document.walk() if isinstance(n, Widget))
    with pytest.raises(TypeError):
        SetExtraAttr(widget, "{http://www.w3.org/2000/xmlns/}evil", "urn:x")


@pytest.mark.parametrize(
    "key",
    [
        "{http://www.w3.org/XML/1998/namespace}lang",
        "{urn:pyguibud:ui:2}x",
        "{ns0}x",
        f"{{{NS_TB}}}zzz",
    ],
)
def test_odd_but_legal_extension_keys_round_trip(tmp_path: Path, key: str) -> None:
    document = read_ui(str(ACME_DEMO)).document
    widget = next(n for n in document.walk() if isinstance(n, Widget) and n.id == "tbl_items")
    assert CommandStack(document, _registry()).execute(SetExtraAttr(widget, key, "v"))
    data = dump_ui(document)
    (tmp_path / "o.ui").write_bytes(data)
    again = read_ui(str(tmp_path / "o.ui")).document
    assert dump_ui(again) == data


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("{:.0f}%", "{0.__class__}"),
        ('tb:bootstyle="primary"', 'tb:bootstyle="x;y"'),
        ("Name;Colour;Amount", ";;"),
    ],
)
def test_pasting_hostile_tb_widgets_is_refused_with_the_reason(old: str, new: str) -> None:
    from pyguibud.designer.clipboard import copy_text, paste_command

    source = read_ui(str(ACME_DEMO)).document
    nodes = [n for n in source.walk() if isinstance(n, Widget) and n.class_name.startswith("tb:")]
    copied = copy_text(source, nodes, None)
    assert not isinstance(copied, str)
    target = read_ui(str(ROOT / "examples" / "hello.ui")).document
    good = paste_command(target, target.children[0], copied.text, _registry(), None)
    assert not isinstance(good, str)
    refused = paste_command(
        target, target.children[0], copied.text.replace(old, new), _registry(), None
    )
    assert isinstance(refused, str) and "not valid" in refused


# ------------------------------------------------------------------ the real CLI (UAT 1 and 2)
def _uic(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*UIC, *args], capture_output=True, text=True, encoding="utf-8",
        timeout=120, env=ENV, cwd=cwd, check=False,
    )  # fmt: skip


def test_uat1_acme_demo_checks_with_one_pip_hint_and_no_tb_warning() -> None:
    if _acme_installed():
        pytest.skip("acme-pyguibud is installed; the pip hint does not apply")
    result = _uic("--check", str(ACME_DEMO))
    assert result.returncode == 0, result.stderr
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1 and "acme-pyguibud" in lines[0] and "pip install" in lines[0]
    assert "tb:" not in result.stderr and "no errors found" in result.stdout


def test_uat2_bad_bootstyle_and_format_walk_fail_the_check_and_codegen(tmp_path: Path) -> None:
    text = ACME_DEMO.read_text(encoding="utf-8")
    text = text.replace(
        'fallback="Checkbutton" tb:bootstyle="primary"',
        'fallback="Checkbutton" tb:bootstyle="primary;x"',
    )
    text = text.replace("{:.0f}%", "{0.__class__}")
    path = tmp_path / "uat2.ui"
    path.write_text(text, encoding="utf-8")
    check = _uic("--check", str(path))
    assert check.returncode == 1 and "Traceback" not in check.stderr
    assert "'primary;x'" in check.stderr and "'amount_format'" in check.stderr
    generate = _uic(str(path), "-o", str(tmp_path / "uat2_ui.py"))
    assert generate.returncode == 1 and not (tmp_path / "uat2_ui.py").exists()


@pytest.mark.parametrize("lang", LOCALES)
def test_new_messages_render_in_every_locale_without_a_traceback(tmp_path: Path, lang: str) -> None:
    body = (
        _w(
            "tb:ToggleButton",
            "Checkbutton",
            attrs=' tb:bootstyle="primary;x" tb:zzz="1" plugin="a b"',
        )
        .replace('id="w1"', 'id="w2"')
        .replace('row="0"', 'row="1"')
        + _meter(_p("amount_format", "{0.__class__}") + _p("subtext", "s"), ' bind="v_b"')
        + _table("x" * 5000).replace('id="w1"', 'id="w3"').replace('row="0"', 'row="2"')
        + _w("Text", None, attrs=' tb:bootstyle="danger"')
        .replace('id="w1"', 'id="w4"')
        .replace('row="0"', 'row="3"')
    )
    path = tmp_path / "all_codes.ui"
    path.write_text(_doc(body), encoding="utf-8")
    result = _uic("--lang", lang, "--check", str(path))
    assert result.returncode == 1 and "Traceback" not in result.stderr
    lines = [
        line for line in result.stderr.splitlines() if ": error: " in line or ": warning: " in line
    ]
    assert len(lines) >= 6
    for line in lines:
        assert not re.search(
            r"\{(id|value|prop|hint|limit|name|plugin|class_name|token)\}", line
        ), line
        if lang == "en_XA":
            assert "[" in line  # bracketed pseudo-translation


# ------------------------------------------------------------------ codegen and runtime (fallbacks)
ALL5 = """<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">
  <meta source_locale="en_GB"/>
  <variables>
    <var id="lvl" type="int" default="7"/>
    <var id="on" type="int" default="1"/>
    <var id="day" type="string" default="1999-02-31"/>
  </variables>
  <window id="main" kind="main" tb:bootstyle="x;x;x">
    <layout type="grid"/>
    <widget class="tb:Meter" id="m" bind="lvl" fallback="Label" tb:bootstyle="danger striped">
      <prop name="amount_format">x{:.6f}y</prop>
      <prop name="interactive">true</prop>
      <prop name="maximum">0</prop>
      <prop name="meter_size">1000</prop>
      <prop name="meter_type">semi</prop>
      <prop name="subtext" translatable="true">&#x202E;evil&#x200B;</prop>
      <prop name="value">-1</prop>
      <cell row="0" column="0"/>
    </widget>
    <widget class="tb:Floodgauge" id="f" bind="lvl" fallback="Progressbar" tb:bootstyle="info">
      <prop name="length">10000</prop>
      <prop name="mask">{}%</prop>
      <prop name="mode">indeterminate</prop>
      <prop name="orient">vertical</prop>
      <cell row="0" column="1"/>
    </widget>
    <widget class="tb:DateEntry" id="d" bind="day" fallback="Entry" tb:bootstyle="warning">
      <prop name="date_format">%Y/%m/%d</prop>
      <prop name="first_weekday">6</prop>
      <prop name="state">readonly</prop>
      <prop name="value">2026-02-30</prop>
      <event name="change" handler="on_c"/>
      <cell row="1" column="0"/>
    </widget>
    <widget class="tb:Tableview" id="t" fallback="Treeview" tb:bootstyle="primary">
      <prop name="columns" translatable="true">a b; ;&lt;x&gt;&amp;</prop>
      <prop name="pagesize">1000</prop>
      <prop name="paginated">true</prop>
      <prop name="selectmode">none</prop>
      <event name="select" handler="on_s"/>
      <cell row="1" column="1"/>
    </widget>
    <widget class="tb:ToggleButton" id="g" bind="on" fallback="Checkbutton" tb:bootstyle="success-square-toggle">
      <prop name="shape">square</prop>
      <prop name="state">disabled</prop>
      <prop name="text" translatable="true">_Go</prop>
      <event name="command" handler="on_g"/>
      <cell row="2" column="0"/>
    </widget>
  </window>
</pyguibud-ui>
"""
#: Step 17b: ``ui.<id>`` is the widget that behaves as the fallback (DateEntry and Tableview
#: own an inner Entry and Treeview).
NATIVE = {"m": "Meter", "f": "Floodgauge", "d": "Entry", "t": "Treeview", "g": "Checkbutton"}


@pytest.mark.gui
def test_codegen_of_all_five_runs_standalone_with_the_spec_fallbacks(tmp_path: Path) -> None:
    ui = tmp_path / "all5.ui"
    ui.write_text(ALL5, encoding="utf-8")
    check = _uic("--check", str(ui))
    assert check.returncode == 0, check.stderr  # window bootstyle: unchecked by design (§14a)
    out = tmp_path / "all5_ui.py"
    assert _uic(str(ui), "-o", str(out)).returncode == 0
    code = out.read_text(encoding="utf-8")
    assert "ttkbootstrap.Label, body" not in code  # fallback="Label" is ignored
    assert "ttkbootstrap.Meter, body" in code  # Step 17b: native tb: widgets (D13)
    runner = textwrap.dedent(
        """
        import importlib.util, json, sys, tkinter
        spec = importlib.util.spec_from_file_location("m", sys.argv[1])
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        class H:
            def __getattr__(self, name): return lambda *a, **k: None
        ui = module.Ui_Main(); ui.setup_ui(handlers=H())
        root = tkinter._default_root; root.update_idletasks()
        out = {k: type(ui.widgets[k]).__name__ for k in "mfdtg"}
        out["pyguibud"] = any(m.split(".")[0] in ("pyguibud", "pyguibud_runtime") for m in sys.modules)
        root.destroy(); print(json.dumps(out))
        """
    )
    shutil.copy(out, tmp_path / "gen.py")
    result = subprocess.run(
        [sys.executable, "-I", "-c", runner, str(tmp_path / "gen.py")],
        capture_output=True, text=True, timeout=120, env=ENV, cwd=tmp_path, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-1500:]
    out_json = json.loads(result.stdout.strip().splitlines()[-1])
    assert out_json.pop("pyguibud") is False
    assert out_json == NATIVE


@pytest.mark.gui
@pytest.mark.parametrize(
    "backend", ["ttkbootstrap", "tkinter", pytest.param("pyside6", marks=pytest.mark.qt)]
)
def test_load_ui_never_reaches_a_tb_factory_on_any_backend(tmp_path: Path, backend: str) -> None:
    """Spec §0 sequencing rule: no KeyError for tb: names, on every backend (and after 17b)."""
    if backend == "pyside6" and not HAS_PYSIDE6:
        pytest.skip("PySide6 is not installed")
    ui = tmp_path / "all5.ui"
    ui.write_text(ALL5, encoding="utf-8")
    bad = tmp_path / "bad.ui"
    bad.write_text(_doc(_meter(_p("amount_format", "{:>999999999}"))), encoding="utf-8")
    script = textwrap.dedent(
        f"""
        import json, sys
        from pyguibud_runtime import load_ui
        out = {{}}
        for path in sys.argv[1:3]:
            ui = load_ui(path, backend={backend!r}, strict=False)
            out[path] = {{k: type(ui.widgets[k]).__name__ for k in ("m", "f", "d", "t", "g") if k in ui.widgets}}
            ui.destroy()
        try:
            load_ui(sys.argv[3], backend={backend!r})
        except Exception as exc:
            out["bad"] = getattr(exc, "code", type(exc).__name__)
        print(json.dumps(out))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(ui), str(ACME_DEMO), str(bad)],
        capture_output=True, text=True, timeout=180, env=ENV, cwd=ROOT, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-1500:]
    assert "KeyError" not in result.stderr and "Traceback" not in result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["bad"] == "runtime.invalid_document"
    names = {k: v.removeprefix("Q").replace("ProgressBar", "Progressbar").replace("LineEdit", "Entry")
             .replace("CheckBox", "Checkbutton").replace("TreeWidget", "Treeview")
             for k, v in out[str(ui)].items()}  # fmt: skip
    # Step 17b: ttkbootstrap builds the real widgets (a bad bootstyle is retried without it).
    native = backend == "ttkbootstrap"
    assert names["m"] == ("Meter" if native else "Progressbar") and names["g"] == "Checkbutton"


# ------------------------------------------------------------------ the designer (UAT walk)
_DESIGNER = r"""
import json, os, sys, tempfile
from pathlib import Path
from typing import Any
sys.path.insert(0, os.getcwd())
from ttkbootstrap import App
from pyguibud.core import NS_TB, Widget, dump_ui, read_ui
from pyguibud.core.commands import SetExtraAttr
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.settings import Settings
from tests.designer.test_drag import _centre, _drag, _with_frame

out = {}
work = Path(sys.argv[2])
root = App(title="qa17a"); root.withdraw()
app = DesignerApp(root, settings=Settings())
demo = work / "acme_demo.ui"
demo.write_bytes(Path(sys.argv[1]).read_bytes())
out["open"] = app.open_path(demo)
root.update()
out["open_status"] = app.shell._message
out["open_byte_identical"] = dump_ui(app.session.document) == demo.read_bytes()
view = app.shell.canvas.stages[0].view
out["canvas_classes"] = sorted({type(v).__name__ for v in view.inner.values()})

# hostile inspector edits: refused with the reason, model unchanged
doc = app.session.document
before = dump_ui(doc)
nodes = {n.id: n for n in doc.walk() if isinstance(n, Widget)}
ins = app.shell.inspector
refusals = []
for wid, key, value in [
    ("mtr_level", "prop:amount_format", "{0.__class__}"),
    ("mtr_level", "prop:amount_format", "{:>999999999}"),
    ("mtr_level", "prop:amount_format", "{}" + "x" * 40),
    ("tbl_items", "prop:columns", "a;;b"),
    ("ent_day", "prop:date_format", "%-d"),
    ("ent_day", "prop:value", "2026-1-1"),
]:
    app.session.select(nodes[wid], origin="tree"); root.update()
    ok = ins.commit(ins._editors[key], value)
    refusals.append([ok, app.shell._message])
out["refusals"] = refusals
out["unchanged_after_refusals"] = dump_ui(doc) == before

# drag the five tb: widgets from the palette, storm undo/redo, Save as, reopen
dropped = {}
for name in ["tb:Meter", "tb:Floodgauge", "tb:DateEntry", "tb:Tableview", "tb:ToggleButton"]:
    frame = _with_frame(app, root)
    stage = app.shell.canvas.stages[0]
    _drag(app, root, name, _centre(stage.view.inner[id(frame)]))
    root.update()
    kids = list(frame.children)
    stack = app.session.stack
    assert stack.execute(SetExtraAttr(kids[0], "{%s}bootstyle" % NS_TB, "info outline")).accepted
    full = dump_ui(app.session.document)
    for _ in range(60):
        stack.undo()
    for _ in range(60):
        stack.redo()
    root.update()
    dropped[name] = [kids[0].class_name, kids[0].fallback, dump_ui(app.session.document) == full]
    target = work / (name[3:] + ".ui")
    file_dialogs.ask_save = lambda *a, **k: str(target)
    app.registry.invoke("file.save_as")
    saved = target.read_bytes()
    app.registry.invoke("file.close")
    app.open_path(target); root.update()
    again = dump_ui(app.session.document)
    reread = dump_ui(read_ui(str(target)).document)
    dropped[name] += [saved == full, again == saved, reread == saved]
out["dropped"] = dropped
app.dispose(); root.destroy()
print(json.dumps(out))
"""


@pytest.mark.gui
def test_designer_walk_with_the_five_tb_widgets(tmp_path: Path) -> None:
    env = {
        **ENV,
        "PYGUIBUD_CONFIG_DIR": str(tmp_path / "c"),
        "PYGUIBUD_STATE_DIR": str(tmp_path / "s"),
    }
    result = subprocess.run(
        [sys.executable, "-c", _DESIGNER, str(ACME_DEMO), str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, env=env, cwd=ROOT, check=False,
    )  # fmt: skip
    assert result.returncode == 0, result.stderr[-2000:]
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["open"] and out["open_byte_identical"]
    assert {"Meter", "Floodgauge", "Checkbutton", "Entry", "Treeview", "Label"} <= set(
        out["canvas_classes"]
    )  # Step 17b: the canvas builds the real tb: widgets
    for ok, message in out["refusals"]:
        assert not ok and message  # refused, with a reason in the status bar
    assert out["unchanged_after_refusals"]
    assert set(out["dropped"]) == {
        "tb:Meter",
        "tb:Floodgauge",
        "tb:DateEntry",
        "tb:Tableview",
        "tb:ToggleButton",
    }
    for name, (cls, fallback, storm_ok, saved_ok, reopened_ok, reread_ok) in out["dropped"].items():
        assert cls == name and fallback, name
        assert storm_ok and saved_ok and reopened_ok and reread_ok, (name, out["dropped"][name])
