"""Tests of the schema upgrade chain (``pyguibud.core.migrations``)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Mapping

import pytest

from pyguibud.core import NS_UI, XmlIoError, dump_ui, migrations, read_ui_bytes, xml_io

from .xml_helpers import doc, read_error

UI = f"{{{NS_UI}}}"


def step_to(target: str) -> migrations.Migration:
    """A migration that only changes the version."""

    def step(root: ET.Element) -> tuple[ET.Element, str]:
        return root, target

    return step


def bump_with_window(target: str, window_id: str) -> migrations.Migration:
    """A migration that adds a window, to prove it runs before the model is built."""

    def step(root: ET.Element) -> tuple[ET.Element, str]:
        ET.SubElement(root, f"{UI}window", {"id": window_id})
        return root, target

    return step


def old_doc(version: str, body: str = "") -> bytes:
    return doc(body, version=version)


def migrate_error(registry: Mapping[str, migrations.Migration], version: str) -> XmlIoError:
    with pytest.raises(XmlIoError) as info:
        migrations.migrate(ET.Element("r"), version, source="t.ui", registry=registry)
    return info.value


def test_shipped_registry_is_empty_and_read_only() -> None:
    assert dict(migrations.MIGRATIONS) == {}
    with pytest.raises(TypeError):
        migrations.MIGRATIONS["0.9"] = step_to("1.0")  # type: ignore[index]


def test_current_version_needs_no_step() -> None:
    root = ET.Element("r")
    assert migrations.migrate(root, "1.0", source="s", registry={}) == (root, "1.0", ())


def test_chain_runs_in_order_and_reports_the_versions_passed() -> None:
    order: list[str] = []

    def make(frm: str, to: str) -> migrations.Migration:
        def step(root: ET.Element) -> tuple[ET.Element, str]:
            order.append(frm)
            return root, to

        return step

    registry = {"0.7": make("0.7", "0.8"), "0.8": make("0.8", "0.9"), "0.9": make("0.9", "1.0")}
    root = ET.Element("r")
    assert migrations.migrate(root, "0.7", source="s", registry=registry) == (
        root,
        "1.0",
        ("0.7", "0.8", "0.9"),
    )
    assert order == ["0.7", "0.8", "0.9"]


def test_a_step_may_skip_versions() -> None:
    root = ET.Element("r")
    result = migrations.migrate(root, "0.5", source="s", registry={"0.5": step_to("1.0")})
    assert result == (root, "1.0", ("0.5",))


def test_a_step_may_return_a_new_root() -> None:
    replacement = ET.Element("new")

    def step(root: ET.Element) -> tuple[ET.Element, str]:
        return replacement, "1.0"

    root, version, passed = migrations.migrate(
        ET.Element("old"), "0.9", source="s", registry={"0.9": step}
    )
    assert root is replacement and version == "1.0" and passed == ("0.9",)


def test_missing_link_is_no_migration_and_names_the_missing_version() -> None:
    exc = migrate_error({"0.7": step_to("0.8")}, "0.7")
    assert exc.code == "xml.no_migration" and exc.params == {"version": "0.8", "current": "1.0"}
    assert exc.source == "t.ui" and exc.line is None
    assert "0.8" in exc.message and "1.0" in exc.message
    assert migrate_error({}, "0.1").params["version"] == "0.1"


@pytest.mark.parametrize(
    "result",
    ["0.9", "0.8", "0.0", "1.1", "2.0", "1.0.0", "abc", "", "01.0", " 1.0"],
)
def test_bad_step_results_are_refused(result: str) -> None:
    exc = migrate_error({"0.9": step_to(result)}, "0.9")
    assert exc.code == "xml.bad_migration"
    assert exc.params == {"version": "0.9", "result": result}
    assert f"'{result}'" in exc.message and "0.9" in exc.message


def test_a_loop_is_refused_instead_of_hanging() -> None:
    exc = migrate_error({"0.8": step_to("0.9"), "0.9": step_to("0.8")}, "0.8")
    assert exc.code == "xml.bad_migration" and exc.params["version"] == "0.9"


def test_step_that_stays_on_the_same_version_is_refused() -> None:
    assert migrate_error({"0.8": step_to("0.8")}, "0.8").code == "xml.bad_migration"


def test_overshooting_current_is_refused_even_if_a_later_step_exists() -> None:
    exc = migrate_error({"0.9": step_to("1.1"), "1.1": step_to("1.0")}, "0.9")
    assert exc.code == "xml.bad_migration" and exc.params["result"] == "1.1"


def test_other_exceptions_from_a_step_propagate_unchanged() -> None:
    def broken(root: ET.Element) -> tuple[ET.Element, str]:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        migrations.migrate(ET.Element("r"), "0.9", source="s", registry={"0.9": broken})


def test_xml_io_errors_from_a_step_propagate_unchanged() -> None:
    def refusing(root: ET.Element) -> tuple[ET.Element, str]:
        raise XmlIoError("custom.stop", "stop", source="s")

    with pytest.raises(XmlIoError) as info:
        migrations.migrate(ET.Element("r"), "0.9", source="s", registry={"0.9": refusing})
    assert info.value.code == "custom.stop"


def test_registry_none_reads_the_module_global_at_call_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = ET.Element("r")
    with pytest.raises(XmlIoError) as info:
        migrations.migrate(root, "0.9", source="s")
    assert info.value.code == "xml.no_migration"
    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": step_to("1.0")})
    assert migrations.migrate(root, "0.9", source="s")[1] == "1.0"


def test_reader_applies_the_chain_before_mapping_and_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        migrations,
        "MIGRATIONS",
        {"0.8": step_to("0.9"), "0.9": bump_with_window("1.0", "from_migration")},
    )
    result = read_ui_bytes(old_doc("0.8", '<window id="orig"/>'), source="t.ui")
    assert [w.id for w in result.document.children] == ["orig", "from_migration"]
    assert result.document.schema_version == "1.0" and result.source_version == "0.8"
    assert not result.read_only
    assert [w.code for w in result.warnings] == ["xml.migrated"]
    warning = result.warnings[0]
    assert warning.params == {"version": "0.8", "current": "1.0"}
    assert (warning.line, warning.column) == (2, 1)
    assert "0.8" in warning.message and "saving writes the new version" in warning.message
    # the upgraded document is a normal, savable one
    assert b'schema_version="1.0"' in dump_ui(result.document)
    assert b"from_migration" in dump_ui(result.document)


def test_migrated_document_is_stable_when_saved_again(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": step_to("1.0")})
    first = dump_ui(read_ui_bytes(old_doc("0.9", '<window id="w"/>')).document)
    second_read = read_ui_bytes(first)
    assert second_read.warnings == ()
    assert dump_ui(second_read.document) == first


def test_elements_created_by_a_step_carry_no_position(monkeypatch: pytest.MonkeyPatch) -> None:
    def bad_step(root: ET.Element) -> tuple[ET.Element, str]:
        ET.SubElement(root, f"{UI}window")  # no id: a missing required attribute
        return root, "1.0"

    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": bad_step})
    exc = read_error(old_doc("0.9"))
    assert exc.code == "xml.missing_attribute" and (exc.line, exc.column) == (None, None)
    assert exc.source == "t.ui"


def test_step_that_replaces_the_root_loses_its_position_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def replace(root: ET.Element) -> tuple[ET.Element, str]:
        new = ET.Element(root.tag, {"schema_version": "1.0"})
        ET.SubElement(new, f"{UI}window", {"id": "w", "modal": "maybe"})
        return new, "1.0"

    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": replace})
    exc = read_error(old_doc("0.9"))
    assert exc.code == "xml.bad_bool" and exc.line is None


def test_bad_step_through_the_reader_reports_bad_migration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.9": step_to("0.9")})
    exc = read_error(old_doc("0.9"))
    assert exc.code == "xml.bad_migration" and exc.source == "t.ui"


def test_missing_link_through_the_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrations, "MIGRATIONS", {"0.8": step_to("0.9")})
    exc = read_error(old_doc("0.8"))
    assert exc.code == "xml.no_migration" and exc.params["version"] == "0.9"


def test_newer_and_malformed_versions_never_reach_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called: list[str] = []

    def spy(root: ET.Element) -> tuple[ET.Element, str]:
        called.append("x")
        return root, "1.0"

    monkeypatch.setattr(migrations, "MIGRATIONS", {"1.1": spy, "abc": spy, "2.0": spy})
    assert read_ui_bytes(old_doc("1.1")).read_only
    assert read_error(old_doc("abc")).code == "xml.bad_version"
    assert read_error(old_doc("2.0")).code == "xml.newer_major"
    assert called == []


def test_xml_io_uses_the_same_registry_module() -> None:
    assert xml_io.migrations is migrations  # type: ignore[attr-defined]
