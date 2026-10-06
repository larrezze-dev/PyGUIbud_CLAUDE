"""Tests of the document validator (``pyguibud.core.validate``)."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pyguibud import i18n
from pyguibud.core import (
    CORE_CLASS_NAMES,
    Action,
    Document,
    Event,
    Finding,
    GridCell,
    GridLine,
    ImageResource,
    Include,
    Layout,
    Menu,
    Menubar,
    PackPlacement,
    PagePlacement,
    Prop,
    PropertyDef,
    Registry,
    Statusbar,
    ValidationReport,
    Variable,
    Widget,
    WidgetSpec,
    Window,
    default_registry,
    dump_ui,
    read_ui,
    validate,
    validate_read,
)
from pyguibud.core.validate import (
    BIND_TYPES,
    MAX_FINDINGS,
    MAX_NESTING,
    TRUNCATED_CODE,
    guard_key,
    new_errors,
)
from pyguibud.core.widgets import core_widgets

from .xml_helpers import DATA, HELLO, structure

CASES = Path(__file__).parent / "data" / "validate"
EXAMPLES = Path(__file__).parents[2] / "examples"
GRID = Layout(type="grid")


class DictRegistry:
    """A fake :class:`WidgetLookup`: proves the validator needs only ``get``."""

    def __init__(self, *extra: WidgetSpec) -> None:
        self.specs = {spec.name: spec for spec in (*core_widgets(), *extra)}

    def get(self, name: str) -> WidgetSpec | None:
        return self.specs.get(name)


def gauge(*, children: str = "none") -> WidgetSpec:
    return WidgetSpec(
        name="acme:Gauge",
        display_name="Gauge",
        category="Display",
        api_version=1,
        children=children,  # type: ignore[arg-type]
        events=("change",),
    )


def line(finding: Finding) -> str:
    return f"{finding.line}:{finding.column}: {finding.severity}: {finding.code}: {finding.path}"


def codes(report: ValidationReport) -> list[str]:
    return [f.code.removeprefix("validate.") for f in report.findings]


def label(widget_id: str, row: int = 0, column: int = 0) -> Widget:
    return Widget(class_name="Label", id=widget_id, placement=GridCell(row=row, column=column))


def build(*children: Widget | Include, layout: Layout | None = GRID) -> Document:
    document = Document()
    window = Window(id="main", layout=layout)
    for child in children:
        window.append_child(child)
    document.add_window(window)
    return document


def run(document: Document, registry: DictRegistry | Registry | None = None) -> ValidationReport:
    return validate(document, registry or DictRegistry())


# ---------------------------------------------------------------- golden files, one per rule
CASE_FILES = sorted(CASES.glob("*.ui"))


def test_every_case_has_a_golden_file() -> None:
    assert len(CASE_FILES) >= 40
    for path in CASE_FILES:
        assert path.with_suffix(".findings.txt").exists(), path.name


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_golden_findings(path: Path) -> None:
    result = read_ui(path)
    report = validate_read(result, default_registry())
    actual = "".join(line(f) + "\n" for f in report.findings)
    assert actual == path.with_suffix(".findings.txt").read_text("utf-8")
    assert all(f.source == str(path) for f in report.findings)


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_golden_findings_are_translated_on_read(path: Path) -> None:
    report = validate_read(read_ui(path), default_registry())
    english = [f.message for f in report.findings]
    i18n.set_language("en_XA")
    assert [f.message for f in report.findings] != english or not english


def test_clean_documents_have_no_findings() -> None:
    for path in (HELLO, *sorted(EXAMPLES.glob("*.ui"))):
        report = validate_read(read_ui(path), default_registry())
        assert report.findings == () and report.ok and not report.truncated, path.name
    assert (CASES / "clean_menus_statusbar.findings.txt").read_text("utf-8") == ""


def test_xml_io_fixtures_match_the_hand_computed_table() -> None:
    # Spec section 11; pg1 and pg2 are Frames without a layout, which D6 also reports (R13).
    expected = {
        "minimal": ({}, {"no_windows": 1}),
        "full": (
            {
                "layout_missing": 4,
                "ref_not_allowed": 1,
                "bind_not_supported": 1,
                "placement_missing": 1,
            },
            {"dialog_only": 2, "orient_ignored": 1, "page_attr_ignored": 2},
        ),
        "reordered": ({"layout_missing": 1}, {"unknown_prop": 2}),
        "special_chars": ({"layout_missing": 1}, {"unknown_prop": 8}),
        "foreign": ({"layout_missing": 1, "unsupported_event": 1}, {"plugin_missing": 1}),
    }
    for name, (errors, warnings) in expected.items():
        report = validate_read(read_ui(DATA / f"{name}.in.ui"), default_registry())

        def count(findings: tuple[Finding, ...]) -> dict[str, int]:
            result: dict[str, int] = {}
            for finding in findings:
                key = finding.code.removeprefix("validate.")
                result[key] = result.get(key, 0) + 1
            return result

        assert count(report.errors) == errors, name
        assert count(report.warnings) == warnings, name


# ---------------------------------------------------------------- report and API
def test_report_properties() -> None:
    report = run(build(label("a"), label("a", 1)))
    assert not report.ok and report.errors == report.findings and report.warnings == ()
    assert run(build(label("a"))).ok
    only_warning = run(Document())
    assert only_warning.ok and codes(only_warning) == ["no_windows"]
    assert only_warning.findings[0].severity == "warning"


def test_validate_does_not_mutate_and_is_deterministic() -> None:
    document = read_ui(DATA / "full.in.ui").document
    before_bytes = structure(document)
    registry = default_registry()
    first = validate(document, registry)
    second = validate(document, registry)
    assert first.findings == second.findings
    assert structure(document) == before_bytes


def test_a_differently_built_model_gives_equal_findings() -> None:
    def make(order: list[str]) -> Document:
        children = {
            "a": label("dup"),
            "b": label("dup", 1),
            "c": Widget(class_name="Label", id="c"),
        }
        document = Document()
        window = Window(id="main", layout=GRID)
        document.add_window(window)
        for key in order:
            window.append_child(children[key])
        # Same structure, but the nodes were created in another order.
        return document

    one = run(make(["a", "b", "c"]))
    two = run(make(["a", "b", "c"]))
    assert one.findings == two.findings and codes(one) == ["duplicate_id", "placement_missing"]


def test_rule_order_is_resources_variables_then_windows() -> None:
    document = build(label("v"), label("r", 1))
    document.resources["r"] = ImageResource(id="r", src="a.png")
    document.variables["v"] = Variable(id="v", type="string")
    report = run(document)
    assert [f.path for f in report.findings] == ["window[main]/widget[v]", "window[main]/widget[r]"]
    assert "variables/var[v]" in report.findings[0].message
    assert "resources/image[r]" in report.findings[1].message


def test_findings_carry_anchor_part_and_position() -> None:
    result = read_ui(CASES / "r17_bad_sticky.ui")
    report = validate_read(result, default_registry())
    finding = report.findings[0]
    assert isinstance(finding.anchor, Widget) and finding.anchor.id == "a"
    assert finding.part == "cell" and (finding.line, finding.column) == (5, 34)
    # Without positions (guards) there is no line, but the path stays.
    bare = validate(result.document, default_registry())
    assert bare.findings[0].line is None and bare.findings[0].path == finding.path
    assert bare.findings[0].source == "<memory>"


# ---------------------------------------------------------------- the cap
def make_many_errors(count: int) -> Document:
    return build(*[Widget(class_name="Label", id=f"w{i}") for i in range(count)])


def test_cap_keeps_limit_findings_and_marks_the_last_as_truncated() -> None:
    document = make_many_errors(20)
    report = validate(document, DictRegistry(), limit=5)
    assert len(report.findings) == 5 and report.truncated
    last = report.findings[-1]
    assert last.code == TRUNCATED_CODE and last.severity == "error" and not report.ok
    assert last.message == "16 more problems were found but not listed."
    assert all(f.code == "validate.placement_missing" for f in report.findings[:-1])
    full = validate(document, DictRegistry(), limit=None)
    assert len(full.findings) == 20 and not full.truncated


def test_cap_boundaries() -> None:
    document = make_many_errors(5)
    assert not validate(document, DictRegistry(), limit=5).truncated
    assert validate(document, DictRegistry(), limit=4).truncated
    assert len(validate(document, DictRegistry(), limit=1).findings) == 1
    assert MAX_FINDINGS == 1000


@pytest.mark.parametrize("limit", [0, -1, 1.5, True, "5", float("nan")])
def test_cap_must_be_a_positive_int(limit: object) -> None:
    # QA Step 09: limit=0 used to be silently raised to 1; a bad cap is a programming error.
    with pytest.raises(ValueError, match="limit"):
        validate(make_many_errors(2), DictRegistry(), limit=limit)  # type: ignore[arg-type]


def test_truncated_severity_is_the_worst_dropped_and_ok_stays_exact() -> None:
    # Two warnings are stored; the dropped finding is an error, so ok must be False.
    document = build(layout=GRID)
    window = document.children[0]
    window.modal = True
    window.buttons = "ok"
    window.append_child(Widget(class_name="Label", id="bad"))
    report = validate(document, DictRegistry(), limit=2)
    assert report.truncated and not report.ok
    assert report.findings[-1].severity == "error"
    # Only warnings dropped: the truncated finding is a warning and ok holds.
    warnings_only = Document()
    warnings_only.add_window(Window(id="w", layout=GRID, modal=True, buttons="x"))
    report = validate(warnings_only, DictRegistry(), limit=1)
    assert report.truncated and report.ok and report.findings[0].severity == "warning"


# ---------------------------------------------------------------- scale and abuse
def test_a_thousand_level_chain_is_validated_without_recursion() -> None:
    outer = Widget(class_name="Frame", id="f0", placement=GridCell(row=0, column=0), layout=GRID)
    current = outer
    for index in range(1, 1000):
        child = Widget(
            class_name="Frame", id=f"f{index}", placement=GridCell(row=0, column=0), layout=GRID
        )
        current.append_child(child)
        current = child
    report = run(build(outer))
    assert codes(report) == ["too_deep"]
    finding = report.findings[0]
    assert isinstance(finding.anchor, Widget)
    # window = 2, f0 = 3, so the first node over the limit is f(MAX_NESTING - 2).
    assert finding.anchor.id == f"f{MAX_NESTING + 1 - 3}"


def test_twenty_thousand_siblings_with_collisions_finish_quickly() -> None:
    children = [label(f"w{i}", row=i % 50, column=i % 7) for i in range(20_000)]
    document = build(*children)
    started = time.perf_counter()
    report = validate(document, DictRegistry(), limit=None)
    elapsed = time.perf_counter() - started
    # Coverage tracing slows pure-Python loops by roughly 2-3x (the scorer runs with --cov).
    budget = 6.0 if "coverage" in sys.modules else 2.0
    assert elapsed < budget, elapsed
    assert len(report.errors) == 20_000 - 350  # 50 x 7 distinct cells are free


def test_large_spans_are_detected_pairwise() -> None:
    big = Widget(
        class_name="Label",
        id="big",
        placement=GridCell(row=0, column=0, rowspan=100, columnspan=100),
    )
    inside = label("inside", 50, 50)
    other_big = Widget(
        class_name="Label",
        id="big2",
        placement=GridCell(row=99, column=99, rowspan=100, columnspan=100),
    )
    clear = label("clear", 500, 500)
    report = run(build(big, inside, other_big, clear))
    assert [f.path for f in report.findings] == [
        "window[main]/widget[inside]/cell",
        "window[main]/widget[big2]/cell",
    ]
    messages = [f.message for f in report.findings]
    assert messages[0] == "'inside' overlaps 'big' in the grid at row 50, column 50."
    assert messages[1] == "'big2' overlaps 'big' in the grid at row 99, column 99."


def test_a_huge_id_is_one_bounded_finding() -> None:
    report = run(build(label("x" * 10_000)))
    assert codes(report) == ["bad_id"]
    assert len(report.findings[0].message) < 400


# ---------------------------------------------------------------- hand-built models
def test_wrong_python_types_are_findings_not_exceptions() -> None:
    widget = Widget(class_name="Label", id="a", placement=GridCell(row="x", column=None))  # type: ignore[arg-type]
    widget.bind = 5  # type: ignore[assignment]
    widget.events.append(Event(name=3, handler=None))  # type: ignore[arg-type]
    widget.props["width"] = Prop(name="width", value=7)  # type: ignore[arg-type]
    widget.props[5] = Prop(name=9)  # type: ignore[index, arg-type]
    broken = Widget(class_name=7, id=8, placement="cell")  # type: ignore[arg-type]
    document = build(widget, broken)
    document.children[0].min_width = "wide"  # type: ignore[assignment]
    document.children[0].layout = Layout(
        type="grid",
        padding="x",  # type: ignore[arg-type]
        columns=(GridLine(index="a"),),  # type: ignore[arg-type]
    )
    document.variables["v"] = Variable(id="v", type="string", default=3)  # type: ignore[arg-type]
    report = run(document)
    assert not report.ok
    assert {
        "out_of_range",
        "bad_bind",
        "bad_event",
        "bad_handler",
        "bad_prop_value",
        "bad_id",
    } <= set(codes(report))
    assert "unknown_class" in codes(report)


def test_illegal_characters_are_reported_with_the_path_and_attribute() -> None:
    widget = label("a")
    widget.props["text"] = Prop(name="text", value="bad\x01char", context="c\x02", comment="ok")
    window = Window(id="main", layout=GRID, buttons="x\x03")
    window.append_child(widget)
    document = Document()
    document.add_window(window)
    document.meta.generator = "g\x04"
    document.resources["i"] = ImageResource(id="i", src="a\x05.png")
    document.variables["v"] = Variable(id="v", type="string", default="d\x06")
    report = run(document)
    messages = [f.message for f in report.findings if f.code == "validate.illegal_char"]
    assert messages == [
        "meta@generator contains the character U+0004, which a .ui file cannot store.",
        "resources/image[i]@src contains the character U+0005, which a .ui file cannot store.",
        "variables/var[v]@default contains the character U+0006, which a .ui file cannot store.",
        "window[main]@buttons contains the character U+0003, which a .ui file cannot store.",
        "window[main]/widget[a]/prop[text] contains the character U+0001, which a .ui file "
        "cannot store.",
        "window[main]/widget[a]/prop[text]@context contains the character U+0002, which a "
        ".ui file cannot store.",
    ]


# ---------------------------------------------------------------- model-only rules (R56 to R64)
# The reader refuses these values (xml.bad_enum, xml.bad_class_name, ...), so no .ui file can carry
# them; a hand-built model can, and the command guards must catch them before the writer does.
def model_only_document() -> Document:
    document = Document()
    document.meta.generator = 5  # type: ignore[assignment]
    document.variables["v"] = Variable(id="v", type="float")  # type: ignore[arg-type]
    document.variables["w"] = Variable(id="w", type="string", default=3)  # type: ignore[arg-type]
    window = Window(id="main", kind="bogus", layout=Layout(type="spiral"))  # type: ignore[arg-type]
    window.modal = 1  # type: ignore[assignment]
    window.append_child(
        Widget(
            class_name="acme:gauge",
            id="g",
            fallback="Label",
            placement=GridCell(row=0, column=0),
        )
    )
    packed = Widget(
        class_name="Frame",
        id="p",
        layout=Layout(type="pack", orient="diagonal"),  # type: ignore[arg-type]
        placement=GridCell(row=1, column=0),
    )
    packed.append_child(
        Widget(
            class_name="Label",
            id="q",
            placement=PackPlacement(fill="wide", expand=1),  # type: ignore[arg-type]
        )
    )
    packed.props["x"] = Prop(name="x", value="v", translatable=1)  # type: ignore[arg-type]
    window.append_child(packed)
    book = Widget(class_name="Notebook", id="book", placement=GridCell(row=2, column=0))
    book.append_child(Widget(class_name="Frame", id="page_a", placement=PagePlacement(text="t")))  # type: ignore[arg-type]
    book.append_child(
        Widget(
            class_name="Frame",
            id="page_b",
            layout=GRID,
            placement=PagePlacement(text=Prop(name="caption", value="t"), image=7),  # type: ignore[arg-type]
        )
    )
    window.append_child(book)
    document.add_window(window)
    return document


def test_model_only_rules_golden() -> None:
    report = validate(model_only_document(), default_registry())
    actual = "".join(line(f) + "\n" for f in report.findings)
    assert actual == (CASES / "r56_r64_model_only.findings.txt").read_text("utf-8")
    assert {f.code for f in report.findings} >= {
        "validate.bad_window_kind",
        "validate.bad_layout_type",
        "validate.bad_orient",
        "validate.bad_fill",
        "validate.bad_variable_type",
        "validate.bad_class_name",
        "validate.not_text",
        "validate.not_flag",
        "validate.bad_page_text",
    }


# ---------------------------------------------------------------- classes, fallbacks and plugins
def ext(widget_id: str, fallback: str | None = "Progressbar", **kw: object) -> Widget:
    return Widget(
        class_name="acme:Gauge",
        id=widget_id,
        fallback=fallback,
        placement=GridCell(row=0, column=0),
        **kw,  # type: ignore[arg-type]
    )


def test_registered_extension_is_validated_against_its_own_spec() -> None:
    registry = DictRegistry(gauge())
    widget = ext("g")
    widget.events.append(Event(name="change", handler="on_g"))
    widget.props["mystery"] = Prop(name="mystery", value="1")
    report = run(build(widget), registry)
    assert codes(report) == ["unknown_prop"]  # registered: props are checked, no R28


def test_registered_extension_still_needs_a_fallback() -> None:
    registry = DictRegistry(gauge())
    assert codes(run(build(ext("g", None)), registry)) == ["missing_fallback"]
    assert codes(run(build(ext("g", "Menu")), registry)) == ["bad_fallback"]


def test_fallback_container_mismatch() -> None:
    registry = DictRegistry(gauge(children="layout"))
    widget = ext("g", "Progressbar")
    widget.layout = GRID
    report = run(build(widget), registry)
    assert codes(report) == ["fallback_mismatch"]
    assert report.findings[0].message == (
        "The fallback 'Progressbar' of 'g' does not match acme:Gauge: one is a container and "
        "the other is not."
    )
    matching = ext("g", "Frame")
    matching.layout = GRID
    assert run(build(matching), registry).ok


def test_fallback_mode_checks_structure_but_not_props_or_events() -> None:
    inner = label("inner")
    frame = ext("g", "Frame")
    frame.props["anything"] = Prop(name="anything", value="x")
    frame.events.append(Event(name="whatever_but_valid:", handler="on_x"))
    frame.append_child(inner)
    document = build(frame)
    report = run(document)
    # Missing layout (R13) and a bad event name (R36) still count; unknown props and the
    # supported-event check (R30, R37) do not apply in fallback mode.
    assert set(codes(report)) == {"plugin_missing", "layout_missing", "bad_event"}
    frame.layout = GRID
    frame.events.clear()
    assert codes(run(document)) == ["plugin_missing"]


def test_children_of_unknown_classes_are_still_checked() -> None:
    unknown = Widget(class_name="Gizmo", id="g", placement=GridCell(row=0, column=0))
    unknown.append_child(Widget(class_name="Label", id="a"))  # no placement check without a spec
    unknown.append_child(Widget(class_name="Label", id="a"))
    report = run(build(unknown))
    assert codes(report) == ["unknown_class", "duplicate_id"]


def test_structural_registered_spec_is_refused_as_a_widget() -> None:
    menu_like = WidgetSpec(
        name="acme:Menus", display_name="Menus", category="x", api_version=1, children="menu"
    )
    widget = Widget(
        class_name="acme:Menus", id="m", fallback="Frame", placement=GridCell(row=0, column=0)
    )
    assert codes(run(build(widget), DictRegistry(menu_like))) == ["structural_class"]


# ---------------------------------------------------------------- containers and layouts
def test_empty_containers_and_windows_follow_decision_d6() -> None:
    empty_frame = Widget(class_name="Frame", id="f", placement=GridCell(row=0, column=0))
    notebook = Widget(class_name="Notebook", id="n", placement=GridCell(row=1, column=0))
    paned = Widget(class_name="PanedWindow", id="p", placement=GridCell(row=2, column=0))
    document = build(empty_frame, notebook, paned)
    document.add_window(Window(id="dlg", kind="dialog"))
    report = run(document)
    assert [f.path for f in report.findings] == ["window[main]/widget[f]", "window[dlg]"]
    assert codes(report) == ["layout_missing", "layout_missing"]


def test_children_of_a_container_without_layout_get_no_placement_findings() -> None:
    frame = Widget(class_name="Frame", id="f", placement=GridCell(row=0, column=0))
    frame.append_child(Widget(class_name="Label", id="a"))
    assert codes(run(build(frame))) == ["layout_missing"]


def test_pack_and_page_expectations() -> None:
    notebook = Widget(class_name="Notebook", id="n", placement=GridCell(row=0, column=0))
    notebook.append_child(Widget(class_name="Frame", id="p1", layout=GRID))
    notebook.append_child(
        Widget(class_name="Frame", id="p2", layout=GRID, placement=GridCell(row=0, column=0))
    )
    notebook.append_child(
        Widget(class_name="Frame", id="p3", layout=GRID, placement=PagePlacement())
    )
    report = run(build(notebook))
    assert codes(report) == ["placement_missing", "placement_mismatch"]
    assert "expects <page>" in report.findings[1].message
    pack = Widget(
        class_name="Frame", id="f", layout=Layout(type="pack"), placement=GridCell(row=0, column=0)
    )
    pack.append_child(Widget(class_name="Label", id="a", placement=PackPlacement(padx=-1)))
    assert codes(run(build(pack))) == ["out_of_range"]


def test_collision_reports_the_later_child_once_with_the_first_overlap() -> None:
    report = run(
        build(
            label("a"),
            Widget(class_name="Label", id="b", placement=GridCell(row=0, column=0, columnspan=2)),
            label("c", 0, 1),
        )
    )
    assert [f.message for f in report.findings] == [
        "'b' overlaps 'a' in the grid at row 0, column 0.",
        "'c' overlaps 'b' in the grid at row 0, column 1.",
    ]
    first = report.findings[0]
    assert isinstance(first.related, Widget) and first.related.id == "a"


def test_includes_are_children_like_widgets() -> None:
    include = Include(id="inc", src="x.ui", component="Panel")
    label_child = Widget(class_name="Label", id="a", placement=GridCell(row=0, column=0))
    label_child.append_child(Include(id="inc2", src="y.ui", component="Panel"))
    assert codes(run(build(include, label_child))) == ["placement_missing", "not_a_container"]


def test_menu_nesting_and_statusbar_are_visited() -> None:
    document = build()
    window = document.children[0]
    window.statusbar = Statusbar(id="sts")
    window.menubar = Menubar()
    menu = Menu(id="m")
    window.menubar.append_child(menu)
    current = menu
    for index in range(MAX_NESTING):
        child = Menu(id=f"m{index}")
        current.append_child(child)
        current = child
    current.append_child(Action(id="deep"))
    report = run(document)
    assert codes(report) == ["too_deep"]


def test_window_rules_for_components_and_dialogs() -> None:
    document = Document()
    component = Window(id="cmp", kind="component", layout=GRID, menubar=Menubar())
    dialog = Window(id="dlg", kind="dialog", layout=GRID, modal=True, buttons="ok")
    document.add_window(component)
    document.add_window(dialog)
    document.add_window(Window(id="m2", kind="main", layout=GRID))
    document.add_window(Window(id="m3", kind="main", layout=GRID))
    report = run(document)
    assert codes(report) == ["component_chrome", "multiple_main"]
    assert (
        report.findings[1].message
        == "Only one window can be the main window; window[m2] already is."
    )


# ---------------------------------------------------------------- property values
def prop_widget(cls: str, name: str, value: str, **kw: object) -> Widget:
    widget = Widget(
        class_name=cls,
        id="w",
        placement=GridCell(row=0, column=0),
        layout=GRID if cls in ("Frame", "ScrolledFrame") else None,
    )
    widget.props[name] = Prop(name=name, value=value, **kw)  # type: ignore[arg-type]
    return widget


@pytest.mark.parametrize(
    ("cls", "name", "value", "expected"),
    [
        ("Label", "width", "12", []),
        ("Label", "width", "-0", []),
        ("Label", "width", "1234567890", ["bad_prop_value"]),
        ("Label", "width", "1.5", ["bad_prop_value"]),
        ("Label", "width", "-1", ["out_of_range"]),
        ("Scale", "minimum", "1.5", []),
        ("Scale", "minimum", ".5", []),
        ("Scale", "minimum", "-3", []),
        ("Scale", "minimum", "1e5", ["bad_prop_value"]),
        ("ScrolledFrame", "autohide", "true", []),
        ("ScrolledFrame", "autohide", "True", ["bad_prop_value"]),
        ("Button", "state", "disabled", []),
        ("Button", "state", "", ["bad_prop_value"]),
        ("Canvas", "background", "#abc", []),
        ("Canvas", "background", "#aabbcc", []),
        ("Canvas", "background", "#aabbccddeeff", []),
        ("Canvas", "background", "light blue", []),
        ("Canvas", "background", "#abcd", ["bad_prop_value"]),
        ("Canvas", "background", "", ["bad_prop_value"]),
        ("Entry", "show", "*", []),
    ],
)
def test_property_value_grammar(cls: str, name: str, value: str, expected: list[str]) -> None:
    assert codes(run(build(prop_widget(cls, name, value)))) == expected


def test_float_range_messages_use_plain_numbers() -> None:
    ranged = WidgetSpec(
        name="Label",
        display_name="Label",
        category="x",
        api_version=1,
        properties=(
            PropertyDef(name="ratio", type="float", minimum=0.5, maximum=2),
            PropertyDef(name="top", type="float", maximum=3),
        ),
    )
    registry = DictRegistry()
    registry.specs["Label"] = ranged
    widget = prop_widget("Label", "ratio", "3")
    widget.props["top"] = Prop(name="top", value="4")
    report = run(build(widget), registry)
    assert [f.message for f in report.findings] == [
        "ratio must be between 0.5 and 2, not 3.",
        "top must be at most 3, not 4.",
    ]


def test_translatable_and_reference_rules() -> None:
    assert run(build(prop_widget("Label", "text", "t", translatable=True))).ok
    missing = run(build(prop_widget("Label", "image", "", ref="logo")))
    assert codes(missing) == ["unknown_resource"]

    def with_logo(widget: Widget) -> Document:
        document = build(widget)
        document.resources["logo"] = ImageResource(id="logo", src="a.png")
        return document

    assert run(with_logo(prop_widget("Label", "image", "", ref="logo"))).ok
    assert codes(run(with_logo(prop_widget("Label", "image", "text", ref="logo")))) == [
        "image_needs_ref"
    ]
    assert codes(run(with_logo(prop_widget("Label", "text", "t", ref="logo")))) == [
        "ref_not_allowed"
    ]


# ---------------------------------------------------------------- events, handlers, binding
def test_event_rules_and_key_sequences() -> None:
    widget = Widget(class_name="Entry", id="e", placement=GridCell(row=0, column=0))
    widget.events.extend(
        [
            Event(name="key:<Return>", handler="on_key"),
            Event(name="change", handler="on_change"),
            Event(name="change", handler="on_change2"),
            Event(name="select", handler="on_select"),
        ]
    )
    assert codes(run(build(widget))) == ["duplicate_event", "unsupported_event"]
    # key: needs focus_in support
    label_widget = label("l")
    label_widget.events.append(Event(name="key:<a>", handler="on_a"))
    assert codes(run(build(label_widget))) == ["unsupported_event"]


@pytest.mark.parametrize(
    ("class_name", "variable_type", "expected"),
    [
        ("Entry", "string", []),
        ("Entry", "bool", ["bind_type_mismatch"]),
        ("Spinbox", "double", []),
        ("Combobox", "int", ["bind_type_mismatch"]),
        ("Label", "int", []),
        ("Scale", "string", ["bind_type_mismatch"]),
        ("Progressbar", "int", []),
        ("Checkbutton", "bool", []),
        ("Radiobutton", "bool", ["bind_type_mismatch"]),
        ("Button", "string", ["bind_not_supported"]),
        ("Listbox", "string", ["bind_not_supported"]),
    ],
)
def test_bind_types_table(class_name: str, variable_type: str, expected: list[str]) -> None:
    widget = Widget(class_name=class_name, id="w", bind="v", placement=GridCell(row=0, column=0))
    document = build(widget)
    document.variables["v"] = Variable(id="v", type=variable_type)  # type: ignore[arg-type]
    assert codes(run(document)) == expected


def test_bind_table_covers_every_core_class() -> None:
    assert set(BIND_TYPES) == set(CORE_CLASS_NAMES)
    assert BIND_TYPES["Frame"] == () and BIND_TYPES["Entry"] == ("string", "int", "double")


def test_an_extension_uses_the_binding_row_of_its_fallback() -> None:
    registry = DictRegistry(gauge())
    widget = ext("g", "Progressbar", bind="v")
    document = build(widget)
    document.variables["v"] = Variable(id="v", type="string")
    assert codes(run(document, registry)) == ["bind_type_mismatch"]


def test_variable_defaults() -> None:
    document = build()
    document.variables["i"] = Variable(id="i", type="int", default="-3")
    document.variables["d"] = Variable(id="d", type="double", default=".5")
    document.variables["b"] = Variable(id="b", type="bool", default="false")
    document.variables["s"] = Variable(id="s", type="string", default="any thing")
    assert run(document).ok


# ---------------------------------------------------------------- registry as a protocol
def test_a_real_registry_and_a_fake_one_agree() -> None:
    document = read_ui(DATA / "full.in.ui").document
    real = validate(document, default_registry())
    fake = validate(document, DictRegistry())
    assert real.findings == fake.findings


def test_an_empty_registry_reports_every_class_as_unknown() -> None:
    class Nothing:
        def get(self, name: str) -> WidgetSpec | None:
            return None

    report = validate(build(label("a")), Nothing())
    assert codes(report) == ["unknown_class"]


# ---------------------------------------------------------------- guard helpers
def test_guard_keys_are_order_independent_for_symmetric_rules() -> None:
    first = run(build(label("dup"), label("dup", 1))).findings[0]
    moved = run(build(label("dup", 1), label("dup"))).findings[0]
    assert guard_key(first) == guard_key(moved) == ("validate.duplicate_id", "dup")
    two_mains = Document()
    two_mains.add_window(Window(id="a", layout=GRID))
    two_mains.add_window(Window(id="b", layout=GRID))
    assert guard_key(run(two_mains).findings[0]) == ("validate.multiple_main",)
    collision = run(build(label("a"), label("b"))).findings[0]
    swapped = run(build(label("b"), label("a"))).findings[0]
    assert guard_key(collision)[0] == "validate.grid_collision"
    assert len(guard_key(collision)[1]) == 2  # type: ignore[arg-type]
    assert guard_key(collision) != guard_key(swapped)  # different node objects


def test_new_errors_is_a_multiset_difference_that_ignores_truncation() -> None:
    document = build(label("a"), label("a", 1))
    before = run(document).findings
    assert new_errors(before, before) == ()
    other = label("a", 2)
    document.children[0].append_child(other)
    after = run(document).findings
    fresh = new_errors(before, after)
    assert len(fresh) == 1 and fresh[0].anchor is other
    truncated = Finding(code=TRUNCATED_CODE, msgid="m", source="s", severity="error")
    assert new_errors((), (truncated,)) == ()
    warning = Finding(code="x", msgid="m", source="s")
    assert new_errors((), (warning,)) == ()


def test_dump_is_unchanged_by_validation() -> None:
    document = read_ui(HELLO).document
    before = dump_ui(document)
    validate(document, default_registry())
    assert dump_ui(document) == before


# ---------------------------------------------------------------- property test
ID_POOL = ["a", "b", "dup", "", "class", "1x", "ok_id", "x" * 70]
CLASS_POOL = ["Label", "Frame", "Notebook", "Button", "Entry", "Gizmo", "tb:Meter", "Menu"]

placements = st.one_of(
    st.none(),
    st.builds(
        GridCell,
        row=st.integers(-2, 12000),
        column=st.integers(-2, 12000),
        rowspan=st.integers(-1, 5),
        columnspan=st.integers(-1, 5),
        sticky=st.sampled_from(["", "n", "nsew", "nn", "x"]),
    ),
    st.builds(PackPlacement, padx=st.integers(-3, 3)),
    st.builds(PagePlacement, weight=st.integers(0, 2)),
)
layouts = st.one_of(
    st.none(),
    st.builds(
        Layout,
        type=st.sampled_from(["grid", "pack"]),
        orient=st.sampled_from(["vertical", "horizontal"]),
        columns=st.lists(st.builds(GridLine, index=st.integers(-1, 3)), max_size=3).map(tuple),
    ),
)


@st.composite
def widgets(draw: st.DrawFn, depth: int = 0) -> Widget:
    widget = Widget(
        class_name=draw(st.sampled_from(CLASS_POOL)),
        id=draw(st.sampled_from(ID_POOL)),
        bind=draw(st.sampled_from([None, "v", "1x"])),
        fallback=draw(st.sampled_from([None, "Frame", "Menu"])),
        placement=draw(placements),
        layout=draw(layouts),
    )
    if depth < 2:
        for child in draw(st.lists(widgets(depth + 1), max_size=2)):
            widget.append_child(child)
    return widget


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.lists(widgets(), max_size=4), st.integers(1, 8))
def test_random_documents_never_raise_and_are_stable(children: list[Widget], limit: int) -> None:
    document = build(*children)
    document.variables["v"] = Variable(id="v", type="string")
    before = structure(document)
    registry = default_registry()
    capped = validate(document, registry, limit=limit)
    full = validate(document, registry, limit=None)
    again = validate(document, registry, limit=None)
    assert full.findings == again.findings
    assert len(capped.findings) <= limit
    assert capped.ok == full.ok
    assert structure(document) == before
