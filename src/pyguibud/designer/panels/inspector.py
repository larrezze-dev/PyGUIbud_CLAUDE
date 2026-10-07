"""The inspector: a read-only list of the selected node's data, properties and findings."""

from __future__ import annotations

from typing import Any

from pyguibud.core import ValidationReport
from pyguibud.designer.panels.base import PanelBase
from pyguibud.designer.present.inspector import display_value, inspector_rows
from pyguibud.designer.session import DesignerSession, Selection
from pyguibud.designer.theme import ThemeSpec, tag_colours
from pyguibud.i18n import N_

__all__ = ["InspectorPanel"]


class InspectorPanel(PanelBase):
    """Sections (General, Properties, ...) with property and value; defaults are muted."""

    name = "inspector"
    HEADING = N_("Inspector")

    def __init__(
        self,
        parent: Any,  # noqa: ANN401 - Tk parent
        session: DesignerSession,
        *,
        ring_px: int = 2,
    ) -> None:
        super().__init__(parent, session, ring_px=ring_px)
        self._new_tree(("value",))
        self._connect(session.selection_changed, self._on_selection)
        self._connect(session.report_changed, self._on_report)
        self._render()

    def _on_selection(self, _selection: Selection) -> None:
        self._render()

    def _on_report(self, _report: ValidationReport) -> None:
        self._render()

    def _render(self) -> None:
        tree = self.tree
        if tree is None:
            return
        scroll = self._scroll_state()
        tree.delete(*tree.get_children())
        rows = inspector_rows(
            self.session.selection.node, self.session.registry, self.session.report()
        )
        section_ids: dict[str, str] = {}
        for row in rows:
            parent = section_ids.get(row.section)
            if parent is None:
                parent = section_ids[row.section] = tree.insert(
                    "", "end", text=row.section, open=True
                )
            tree.insert(
                parent,
                "end",
                text=row.label,
                values=(display_value(row),),
                tags=("muted",) if row.is_default else (),
            )
        self._restore_scroll(scroll)

    def restyle(self, spec: ThemeSpec) -> None:
        super().restyle(spec)
        if self.tree is not None:
            self.tree.tag_configure("muted", foreground=tag_colours(spec)["muted"])
