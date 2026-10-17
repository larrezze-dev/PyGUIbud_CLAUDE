"""Status-bar texts (pure): the selection path and the validator summary."""

from __future__ import annotations

from pyguibud.core import Document, ValidationReport
from pyguibud.core.diagnostics import node_path
from pyguibud.designer.present import clip
from pyguibud.designer.present.canvas import window_of
from pyguibud.i18n import N_, _, ngettext

__all__ = ["findings_summary", "selection_path"]

_M_NO_FINDINGS = N_("No problems found")
_M_SUMMARY = N_("{errors}, {warnings}")


def selection_path(node: object | None, document: Document | None) -> str:
    """The untranslated path of the selected node ("" when nothing is selected)."""
    if node is None or node is document:
        return ""
    return clip(node_path(node, window=window_of(node, document)), 200)


def findings_summary(report: ValidationReport) -> str:
    """ "2 errors, 1 warning" in the current language, or "No problems found"."""
    errors = len(report.errors)
    warnings = len(report.warnings)
    if not errors and not warnings:
        return _(_M_NO_FINDINGS)
    return _(_M_SUMMARY).format(
        # Translators: part of the problem summary; {count} is a number of errors.
        errors=ngettext("{count} error", "{count} errors", errors).format(count=errors),
        # Translators: part of the problem summary; {count} is a number of warnings.
        warnings=ngettext("{count} warning", "{count} warnings", warnings).format(count=warnings),
    )
