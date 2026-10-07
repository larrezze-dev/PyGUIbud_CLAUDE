"""Signal, DesignerSession and the pure-module boundary (no Tk anywhere in here)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from pyguibud import i18n
from pyguibud.core import Widget, default_registry, read_ui, read_ui_string
from pyguibud.core.commands import SetProp
from pyguibud.core.model import Prop
from pyguibud.designer.session import UNTITLED, DesignerSession, Selection, TemplateError
from pyguibud.designer.signals import Signal
from tests.designer.conftest import best_of

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
PURE_MODULES = (
    "pyguibud.designer.signals",
    "pyguibud.designer.session",
    "pyguibud.designer.actions",
    "pyguibud.designer.theme",
    "pyguibud.designer.themes",
    "pyguibud.designer.templates",
    "pyguibud.designer.standard_actions",
    "pyguibud.designer.present",
    "pyguibud.designer.present.palette",
    "pyguibud.designer.present.tree",
    "pyguibud.designer.present.inspector",
    "pyguibud.designer.present.canvas",
    "pyguibud.designer.render_plan",
    "pyguibud.designer.geometry",
    "pyguibud.designer.targets",
    "pyguibud.designer.editing",
    "pyguibud.designer.edit",
    "pyguibud.designer.present.status",
    "pyguibud.designer.present.focus",
    "pyguibud.designer.present.new_file",
)


# ---------------------------------------------------------------- Signal
def test_signal_calls_slots_in_order() -> None:
    sig: Signal[int] = Signal()
    seen: list[str] = []
    sig.connect(lambda v: seen.append(f"a{v}"))
    sig.connect(lambda v: seen.append(f"b{v}"))
    sig.emit(1)
    assert seen == ["a1", "b1"]


def test_signal_failing_slot_is_isolated(caplog: pytest.LogCaptureFixture) -> None:
    sig: Signal[int] = Signal()
    seen: list[int] = []

    def bad(_v: int) -> None:
        raise RuntimeError("boom")

    sig.connect(bad)
    sig.connect(seen.append)
    sig.emit(7)
    assert seen == [7]
    assert any("boom" in (r.exc_text or "") for r in caplog.records)


def test_signal_disconnect_is_idempotent_and_safe_during_emit() -> None:
    sig: Signal[int] = Signal()
    seen: list[int] = []
    disconnect = sig.connect(seen.append)
    sig.connect(lambda _v: disconnect())
    sig.emit(1)
    disconnect()
    sig.emit(2)
    assert seen == [1]
    assert len(sig) == 1


# ---------------------------------------------------------------- session
@pytest.fixture
def session() -> DesignerSession:
    return DesignerSession(default_registry())


def _open_hello(session: DesignerSession) -> None:
    session.open_result(read_ui(EXAMPLES / "hello.ui"), name="hello.ui")


def test_new_session_is_empty(session: DesignerSession) -> None:
    assert session.document is None and session.stack is None
    assert session.report().findings == ()
    assert session.can_discard()
    assert session.selection == Selection((), "session")


def test_open_result_creates_stack_and_signals(session: DesignerSession) -> None:
    events: list[str] = []
    session.document_changed.connect(lambda _s: events.append("document"))
    session.selection_changed.connect(lambda _s: events.append("selection"))
    session.report_changed.connect(lambda _r: events.append("report"))
    _open_hello(session)
    assert events == ["document", "selection", "report"]
    assert session.stack is not None and session.stack.document is session.document
    assert session.display_name == "hello.ui"


def test_select_by_identity_and_origin(session: DesignerSession) -> None:
    _open_hello(session)
    assert session.document is not None
    widget = next(n for n in session.document.walk() if isinstance(n, Widget))
    seen: list[Selection] = []
    session.selection_changed.connect(seen.append)
    session.select(widget, origin="tree")
    assert seen == [Selection((widget,), "tree")]
    session.select(widget, origin="canvas")  # unchanged: ignored, no loop
    assert len(seen) == 1
    session.select(None, origin="tree")
    assert seen[-1] == Selection((), "tree")


def test_foreign_node_is_ignored(session: DesignerSession) -> None:
    _open_hello(session)
    other = read_ui(EXAMPLES / "hello.ui").document
    seen: list[Selection] = []
    session.selection_changed.connect(seen.append)
    foreign = next(n for n in other.walk() if isinstance(n, Widget))
    session.select(foreign, origin="tree")
    assert seen == [] and session.selection.node is None


def test_select_without_a_document_is_ignored(session: DesignerSession) -> None:
    session.select(object(), origin="tree")
    assert session.selection.node is None


def test_opening_another_document_clears_the_selection(session: DesignerSession) -> None:
    _open_hello(session)
    assert session.document is not None
    session.select(session.document.children[0], origin="tree")
    old_stack = session.stack
    _open_hello(session)
    assert session.selection.node is None
    assert session.stack is not old_stack


def test_report_is_cached_and_not_refreshed_by_selection(
    session: DesignerSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyguibud.designer.session as session_module

    module: Any = session_module  # `validate` is imported there, not re-exported
    _open_hello(session)
    calls: list[int] = []
    real = module.validate

    def counting_validate(*a: Any, **k: Any) -> Any:
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(module, "validate", counting_validate)
    first = session.report()
    session.select(session.document.children[0], origin="tree")  # type: ignore[union-attr]
    assert session.report() is first
    assert calls == []  # cached since open_result; selection never validates


def test_report_refreshes_on_stack_events(session: DesignerSession) -> None:
    _open_hello(session)
    assert session.stack is not None and session.document is not None
    reports: list[object] = []
    session.report_changed.connect(reports.append)
    label = next(n for n in session.document.walk() if isinstance(n, Widget) and n.id == "lbl_name")
    before = session.report()
    outcome = session.stack.execute(SetProp(label, Prop(name="text", value="Changed")))
    assert outcome.accepted
    assert len(reports) == 1
    assert session.report() is not before


def test_unsubscribes_from_the_old_stack(session: DesignerSession) -> None:
    _open_hello(session)
    old = session.stack
    assert old is not None and session.document is not None
    old_window = old.document.children[0]
    _open_hello(session)
    reports: list[object] = []
    session.report_changed.connect(reports.append)
    assert old.execute(SetProp(old_window, Prop(name="title", value="Changed"))).accepted
    assert reports == []  # the old stack no longer feeds the session


def test_invalid_document_with_duplicate_ids_is_readable(session: DesignerSession) -> None:
    text = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        '<meta source_locale="en_GB"/><window id="main" kind="main">'
        '<layout type="pack"/>'
        '<widget class="Label" id="x"><pack/></widget>'
        '<widget class="Label" id="x"><pack/></widget></window></pyguibud-ui>'
    )
    session.open_result(read_ui_string(text), name="dup")
    assert not session.report().ok
    assert session.document is not None
    labels = [n for n in session.document.walk() if isinstance(n, Widget)]
    session.select(labels[1], origin="tree")  # selected by identity, not by id
    assert session.selection.node is labels[1]


# ---------------------------------------------------------------- templates
def test_new_from_template_opens_and_selects_first_window(session: DesignerSession) -> None:
    session.new_from_template("main_window")
    assert session.document is not None
    assert session.report().findings == ()
    assert session.selection.node is session.document.children[0]
    assert session.selection.origin == "session"
    assert session.name == UNTITLED


def test_untitled_name_follows_the_language(session: DesignerSession) -> None:
    session.new_from_template("main_window")
    assert session.display_name == "Untitled"
    i18n.set_language("en_XA")
    assert session.display_name.startswith("[")


def test_unknown_template_raises_translated_error(session: DesignerSession) -> None:
    with pytest.raises(TemplateError) as err:
        session.new_from_template("../../etc/passwd")
    assert err.value.code == "designer.unknown_template"
    assert "../../etc/passwd" in str(err.value)
    assert session.document is None


def test_damaged_template_is_refused(
    session: DesignerSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyguibud.designer.session as module

    monkeypatch.setattr(module, "template_bytes", lambda _info: b"<not-ui/>")
    with pytest.raises(TemplateError) as err:
        session.new_from_template("main_window")
    assert err.value.code == "designer.bad_template"
    assert session.document is None


def test_template_with_validation_errors_is_refused(
    session: DesignerSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    import pyguibud.designer.session as module

    broken = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1">'
        b'<meta source_locale="en_GB"/><window id="main" kind="main"><layout type="pack"/>'
        b'<widget class="Nope" id="w"/></window></pyguibud-ui>'
    )
    monkeypatch.setattr(module, "template_bytes", lambda _info: broken)
    with pytest.raises(TemplateError):
        session.new_from_template("main_window")


# ---------------------------------------------------------------- D14: pure modules import no Tk
@pytest.mark.parametrize("module", PURE_MODULES)
def test_pure_module_does_not_import_tk(module: str) -> None:
    code = (
        f"import sys, {module};"
        "bad = sorted(m for m in sys.modules if m.split('.')[0] in ('tkinter', 'ttkbootstrap'));"
        "print(bad); sys.exit(1 if bad else 0)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_core_boundary_still_holds() -> None:
    code = (
        "import sys, pyguibud.core;"
        "print(sorted(m for m in sys.modules if m.startswith('pyguibud.designer')));"
        "sys.exit(1 if any(m.startswith('pyguibud.designer') for m in sys.modules) else 0)"
    )
    assert subprocess.run([sys.executable, "-c", code], capture_output=True).returncode == 0


def test_session_open_is_fast_enough() -> None:
    registry = default_registry()
    sessions = iter([DesignerSession(registry) for _ in range(3)])  # each open is a first one
    # The best of 3 opens with the GC paused: one gen-2 collection is not the code's cost.
    assert best_of(lambda: next(sessions).new_from_template("main_window"), repeat=3) < 1.0
