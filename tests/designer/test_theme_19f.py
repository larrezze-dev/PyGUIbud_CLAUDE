"""Step 19f, theme and display items: H89 theme groups, H90 ring thickness, H91 error border,
and the 19e carry-overs (escaped display of model text that stays editable)."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import default_registry
from pyguibud.core.model import Widget
from pyguibud.core.text import printable
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.present.canvas import canvas_tabs
from pyguibud.designer.present.inspector import inspector_rows
from pyguibud.designer.preview_tk import group_themes
from pyguibud.designer.theme import (
    NON_TEXT_CONTRAST,
    contrast,
    design_tokens,
    load_theme_specs,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "data" / "hardening" / "bidi_id.ui"
SPECS = [*load_theme_specs(), *load_theme_specs(brand=False)]


def test_h89_themes_are_grouped_by_type() -> None:
    groups = group_themes(["flatly", "darkly", "sape-dark", "sape-light", "mystery", "cyborg"])
    assert groups == {
        "light": ["flatly", "sape-light"],
        "dark": ["darkly", "sape-dark", "cyborg"],
        "other": ["mystery"],
    }


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.name)
def test_h91_the_error_border_clears_every_surface_it_touches(spec) -> None:  # type: ignore[no-untyped-def]
    t, c = design_tokens(spec), spec.colors
    for surface in (c["inputbg"], c["bg"], t.stage, t.divider):  # the card sits on the plate
        assert contrast(t.error_border, surface) >= NON_TEXT_CONTRAST, surface


@pytest.mark.gui
def test_h90_the_focus_ring_is_thicker_as_well_as_coloured(shell: DesignerApp) -> None:
    frame = shell.shell.panels[0].frame
    frame.mark(False)
    idle, edge = int(frame.cget("highlightthickness")), int(frame.cget("borderwidth"))
    frame.mark(True)
    active = int(frame.cget("highlightthickness"))
    assert active > idle >= 1
    assert active + int(frame.cget("borderwidth")) == idle + edge  # the content never shifts


def _bidi(shell: DesignerApp, tmp_path: Path) -> Widget:
    copy = tmp_path / "bidi_id.ui"
    shutil.copyfile(FIXTURE, copy)
    assert shell.open_path(copy)
    assert shell.session.document is not None
    node = next(n for n in shell.session.document.walk() if isinstance(n, Widget))
    assert "‮" in node.id
    return node


@pytest.mark.gui
def test_carry_over_presenters_escape_but_the_id_editor_never_commits_them(
    shell: DesignerApp, tmp_path: Path
) -> None:
    node = _bidi(shell, tmp_path)
    original, stack = node.id, shell.session.stack
    assert stack is not None
    rows = inspector_rows(node, default_registry(), shell.session.report())
    assert all("‮" not in r.value for r in rows)
    assert any(r.value == printable(original) for r in rows)
    document = shell.session.document
    assert document is not None
    assert all("‮" not in t.text for t in canvas_tabs(document))
    shell.session.select(node, origin="tree")
    shell.shell.root.update()
    editor: Any = shell.shell.inspector._editors["field:id"]
    depth = stack.can_undo
    editor.widget.focus_force()
    editor.widget.event_generate("<FocusIn>")
    editor.commit_pending()  # focus-out
    editor._enter()  # Enter
    shell.shell.root.update()
    assert node.id == original and not editor.pending()
    assert stack.can_undo == depth and not shell.session.dirty
    assert editor.hint is not None and editor.hint.text == printable(original)
