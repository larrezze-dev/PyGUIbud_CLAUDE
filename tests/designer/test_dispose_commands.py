"""dispose() frees the Tcl commands of its class and ``all`` bindings (H11, QA-14p-13)."""

from __future__ import annotations

from typing import Any

import pytest

from pyguibud.designer.app import DesignerApp

pytestmark = pytest.mark.gui


def _commands(root: Any) -> int:
    return len(root.tk.splitlist(root.tk.call("info", "commands")))


def test_a_designer_rebuild_leaks_no_tcl_command(designer_root: Any) -> None:
    def cycle() -> None:
        app = DesignerApp(designer_root)
        designer_root.update()
        app.dispose()
        designer_root.update()

    cycle()  # warm-up: lazily created styles, images and fonts register once
    before = _commands(designer_root)
    cycle()
    cycle()
    assert _commands(designer_root) - before == 0  # was ~45 per rebuild
