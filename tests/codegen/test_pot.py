"""``extract_pot`` merging and ``GeneratedModule.sources`` (spec ``codegen.md`` 8, 12.1)."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from pyguibud.codegen import extract_pot, generate_python
from pyguibud.core.xml_io import read_ui
from tests.codegen.conftest import write_ui


def _ui(path: Path, *texts: tuple[str, str, str]) -> Path:
    """A main window whose labels are ``(text, context, comment)`` (empty = absent)."""
    widgets = ""
    for row, (text, context, comment) in enumerate(texts):
        attrs = (f' context="{context}"' if context else "") + (
            f' comment="{comment}"' if comment else ""
        )
        widgets += (
            f'<widget class="Label" id="l{row}"><prop name="text" translatable="true"{attrs}>'
            f'{text}</prop><cell row="{row}" column="0"/></widget>'
        )
    return write_ui(path, f'<window id="main" kind="main"><layout type="grid"/>{widgets}</window>')


def _pot(folder: Path, *names: str) -> str:
    return extract_pot(
        [(read_ui(str(folder / n)), str(folder / n)) for n in names], base_dir=str(folder)
    )


def _entries(text: str) -> list[tuple[str | None, str]]:
    return [(m.context, str(m.id)) for m in read_po(io.StringIO(text)) if m.id]


def test_merge_keeps_input_order_then_traversal_order(tmp_path: Path) -> None:
    _ui(tmp_path / "a.ui", ("zeta", "", ""), ("alpha", "", ""))
    _ui(tmp_path / "b.ui", ("mid", "", ""), ("alpha", "", ""), ("beta", "", ""))
    assert [i for _, i in _entries(_pot(tmp_path, "a.ui", "b.ui"))] == [
        "zeta",
        "alpha",
        "mid",
        "beta",
    ]
    assert [i for _, i in _entries(_pot(tmp_path, "b.ui", "a.ui"))] == [
        "mid",
        "alpha",
        "beta",
        "zeta",
    ]


def test_a_shared_message_merges_references_and_comments_once(tmp_path: Path) -> None:
    _ui(tmp_path / "a.ui", ("same", "", "from a"), ("same", "", "from a"))
    _ui(tmp_path / "b.ui", ("same", "", "from b"), ("same", "", "from a"))
    text = _pot(tmp_path, "a.ui", "b.ui")
    assert text.count('msgid "same"') == 1
    assert text.count("#. from a\n") == 1 and text.count("#. from b\n") == 1
    assert text.index("#. from a") < text.index("#. from b")
    refs = [line for line in text.splitlines() if line.startswith("#: ")]
    assert len(refs) == 1
    locations = refs[0][3:].split(" ")
    assert locations == sorted(set(locations), key=locations.index)  # no duplicates, in order
    assert {loc.split(":")[0] for loc in locations} == {"a.ui", "b.ui"}


def test_the_same_text_with_another_context_is_another_entry(tmp_path: Path) -> None:
    _ui(tmp_path / "a.ui", ("Open", "verb", ""), ("Open", "adjective", ""), ("Open", "", ""))
    assert _entries(_pot(tmp_path, "a.ui")) == [
        ("verb", "Open"),
        ("adjective", "Open"),
        (None, "Open"),
    ]


def test_the_header_names_the_first_input_and_nothing_is_dated(tmp_path: Path) -> None:
    _ui(tmp_path / "a.ui", ("x", "", ""))
    write_ui(
        tmp_path / "named.ui",
        '<window id="main" kind="main"><layout type="pack"/></window>',
        meta='i18n_domain="named"',
    )
    first = _pot(tmp_path, "named.ui", "a.ui")
    assert (
        first.startswith("# Translations template for named.\n")
        and "POT-Creation-Date" not in first
    )
    assert _pot(tmp_path, "a.ui", "named.ui").startswith("# Translations template for a.\n")


def test_no_translatable_text_gives_a_header_only_template(tmp_path: Path) -> None:
    write_ui(tmp_path / "n.ui", '<window id="main" kind="main"><layout type="pack"/></window>')
    assert _entries(_pot(tmp_path, "n.ui")) == []
    empty = extract_pot([], base_dir=str(tmp_path))
    assert empty.endswith(f'"Generated-By: pyguibud-uic {_version()}\\n"\n')


def _version() -> str:
    from pyguibud.__about__ import __version__

    return __version__


def test_references_avoid_unsafe_paths(tmp_path: Path) -> None:
    folder = tmp_path / "with space"
    folder.mkdir()
    _ui(folder / "a.ui", ("x", "", ""))
    text = extract_pot(
        [(read_ui(str(folder / "a.ui")), str(folder / "a.ui"))], base_dir=str(tmp_path)
    )
    # QA-11-09: a name with whitespace is isolated (U+2068 ... U+2069), as gettext 0.22 does,
    # so that it is not split in two on read; a line break cannot be written at all.
    assert "#: \u2068with space/a.ui\u2069:" in text
    text = extract_pot(
        [(read_ui(str(folder / "a.ui")), str(folder / "a\rb.ui"))], base_dir=str(tmp_path)
    )
    assert "#:" not in text


# ---------------------------------------------------------------------- GeneratedModule.sources
def test_sources_lists_the_input_and_every_included_file(tmp_path: Path) -> None:
    write_ui(
        tmp_path / "part.ui",
        '<window id="part" kind="component"><layout type="pack"/></window>',
    )
    write_ui(
        tmp_path / "deep.ui",
        '<window id="deep" kind="component"><layout type="pack"/>'
        '<include id="p" src="part.ui" component="part"><pack/></include></window>',
    )
    host = write_ui(
        tmp_path / "host.ui",
        '<window id="main" kind="main"><layout type="pack"/>'
        '<include id="a" src="deep.ui" component="deep"><pack/></include>'
        '<include id="b" src="part.ui" component="part"><pack/></include>'
        '<include id="c" src="#" component="local"><pack/></include></window>'
        '<window id="local" kind="component"><layout type="pack"/></window>',
    )
    generated = generate_python(read_ui(str(host)), str(host), output=str(tmp_path / "x.py"))
    names = [os.path.basename(s) for s in generated.sources]
    assert names[0] == "host.ui" and sorted(names) == ["deep.ui", "host.ui", "part.ui"]
    assert len(set(generated.sources)) == 3 and all(os.path.isabs(s) for s in generated.sources)
    assert all(os.path.exists(s) for s in generated.sources)


def test_a_single_file_module_has_one_source(tmp_path: Path) -> None:
    ui = _ui(tmp_path / "a.ui", ("x", "", ""))
    generated = generate_python(read_ui(str(ui)), str(ui), output=str(tmp_path / "a_ui.py"))
    assert [os.path.basename(s) for s in generated.sources] == ["a.ui"]
    assert generated.class_name == "Ui_Main" and generated.warnings == ()


@pytest.mark.parametrize("name", ["hello", "rich"])
def test_every_translatable_text_of_the_goldens_is_extracted(data_copy: Path, name: str) -> None:
    result = read_ui(str(data_copy / f"{name}.ui"))
    text = extract_pot([(result, str(data_copy / f"{name}.ui"))], base_dir=str(data_copy))
    assert all(m.locations for m in read_po(io.StringIO(text)) if m.id)
