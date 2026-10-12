"""Include rendering on the canvas (spec direct-manipulation 6, 10, 11 Q7-Q11)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from pyguibud.core import default_registry, read_ui
from pyguibud.core.model import Document, Include, Widget, Window
from pyguibud.designer.app import DesignerApp
from pyguibud.designer.canvas.engine import widget_rect
from pyguibud.designer.render_plan import IncludeResolver, design_plan
from tests.designer.test_qa13a_abuse import _settle, app, tk_errors  # noqa: F401

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "include" / "with_include.ui"
HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<pyguibud-ui schema_version="{v}" xmlns="urn:pyguibud:ui:1">'
)
REGISTRY = default_registry()


def _component(cid: str = "card", body: str = "") -> str:
    return (
        f'<window id="{cid}" kind="component"><layout type="grid"/>'
        f'<widget class="Label" id="lbl_{cid}"><cell row="0" column="0"/></widget>{body}</window>'
    )


def _inc(src: str, component: str = "card", iid: str = "inc", row: int = 1) -> str:
    return (
        f'<include id="{iid}" src="{src}" component="{component}">'
        f'<cell row="{row}" column="0"/></include>'
    )


def _file(path: Path, windows: str, version: str = "1.0") -> Path:
    path.write_text(HEAD.format(v=version) + windows + "</pyguibud-ui>", "utf-8")
    return path


def _main(path: Path, body: str) -> Path:
    return _file(path, f'<window id="main" kind="main"><layout type="grid"/>{body}</window>')


def _expand(path: Path | None, document: Document, resolver: IncludeResolver | None = None,
            revision: int = 0) -> tuple[Any, dict[int, str], IncludeResolver]:  # fmt: skip
    resolver = resolver or IncludeResolver(REGISTRY)
    window = document.children[0]
    assert isinstance(window, Window)
    plan = design_plan(document, window, REGISTRY, log=lambda *_a, **_k: None)
    return plan.top, resolver.expand(plan.top, path, revision), resolver


def _include(document: Document) -> Include:
    return next(n for n in document.children[0].walk() if isinstance(n, Include))


# ---------------------------------------------------------------- resolver (pure)
def test_an_external_and_a_nested_include_expand(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _file(tmp_path / "sub" / "leaf.ui", _component("leaf"))
    _file(tmp_path / "card.ui", _component("card", _inc("sub/leaf.ui", "leaf", "deep")))
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    top, reasons, resolver = _expand(main, document)
    assert reasons == {}
    child = top.include(_include(document))
    assert child.windows[0].id == "card" and child.host is None
    nested = next(iter(child.includes.values()))  # resolved against card.ui's folder
    assert nested.windows[0].id == "leaf"
    assert resolver.describe(_include(document)) == (
        "'inc' shows 'card' from card.ui (read-only). Edit that file to change it."
    )


def test_a_same_file_include_shares_the_host_even_untitled() -> None:
    from pyguibud.core import read_ui_string

    text = HEAD.format(v="1.0") + (
        f'<window id="main" kind="main"><layout type="grid"/>{_inc("#")}</window>'
        f"{_component()}</pyguibud-ui>"
    )
    document = read_ui_string(text).document
    top, reasons, resolver = _expand(None, document)
    child = top.include(_include(document))
    assert reasons == {} and child.host is top and child.windows[0] is document.children[1]
    assert "from this document (read-only)" in resolver.describe(_include(document))


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("missing", "The included file 'nope.ui' does not exist or cannot be read."),
        ("unc", "network share or a device, which is never opened"),
        ("major", "cannot be read"),
        ("binary", "cannot be read"),
        ("cycle", "creates a cycle"),
        ("self", "creates a cycle"),
        ("not_component", "not a component"),
    ],
)
def test_every_failure_is_a_placeholder_reason(tmp_path: Path, case: str, expected: str) -> None:
    """Q7/Q8: the validator's reason; nothing is ever executed or opened over the network."""
    src = {
        "missing": "nope.ui",
        "unc": "//server/share/x.ui",
        "self": "main.ui",
        "not_component": "main.ui",
    }.get(case, "card.ui")
    component = "main" if case in ("self", "not_component") else "card"
    if case == "major":
        _file(tmp_path / "card.ui", _component(), version="9.0")
    elif case == "binary":
        (tmp_path / "card.ui").write_bytes(bytes(range(256)) * 64)
    elif case == "cycle":
        _file(tmp_path / "card.ui", _component("card", _inc("main.ui", "back")))
    if case == "self":
        main = _file(
            tmp_path / "main.ui",
            '<window id="main" kind="main"><layout type="grid"/>'
            f"{_inc('#', 'back')}</window>{_component('back', _inc(src, 'back', 'loop'))}",
        )
    elif case == "cycle":
        main = _file(
            tmp_path / "main.ui",
            f'<window id="main" kind="main"><layout type="grid"/>{_inc(src)}</window>'
            f"{_component('back', _inc('card.ui', 'card', 'again'))}",
        )
    else:
        main = _main(tmp_path / "main.ui", _inc(src, component))
    document = read_ui(main).document
    _top, reasons, _resolver = _expand(main, document)
    assert reasons, case
    assert any(expected.lower() in r.lower() for r in reasons.values()), reasons


def test_an_unsaved_document_asks_to_save_first(tmp_path: Path) -> None:
    document = read_ui(_main(tmp_path / "main.ui", _inc("card.ui"))).document
    _top, reasons, _r = _expand(None, document)
    assert list(reasons.values()) == ["Save the document to show included files."]


def test_a_newer_minor_file_renders_and_says_so(tmp_path: Path) -> None:
    _file(tmp_path / "card.ui", _component(), version="1.9")
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    top, reasons, resolver = _expand(main, document)
    assert reasons == {} and _include(document) is not None
    assert top.include(_include(document)).doc.document.children[0].id == "card"
    assert "card.ui (newer format)" in resolver.describe(_include(document))


def test_the_node_budget_is_defence_in_depth(tmp_path: Path, monkeypatch: Any) -> None:
    import pyguibud.designer.render_plan as module

    _file(tmp_path / "card.ui", _component())
    main = _main(tmp_path / "main.ui", _inc("card.ui") + _inc("card.ui", iid="two", row=2))
    monkeypatch.setattr(module, "MAX_EXPANDED_NODES", 1)
    document = read_ui(main).document
    top, reasons, _r = _expand(main, document)
    assert len(top.includes) == 1 and len(reasons) == 1


def test_parsed_files_are_cached_by_stamp(tmp_path: Path, monkeypatch: Any) -> None:
    import pyguibud.designer.render_plan as module

    card = _file(tmp_path / "card.ui", _component())
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    document = read_ui(main).document
    reads: list[str] = []
    real = read_ui

    def counted(path: Any) -> Any:
        reads.append(str(path))
        return real(path)

    monkeypatch.setattr(module, "read_ui", counted)
    _t, _r, resolver = _expand(main, document)
    _expand(main, document, resolver, revision=1)
    assert len(reads) == 1 and not resolver.changed()  # a cache hit
    _file(
        card,
        _component("card", '<widget class="Label" id="more"><cell row="1" column="0"/></widget>'),
    )
    stat = card.stat()
    os.utime(card, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
    assert resolver.changed()
    top, reasons, _r2 = _expand(main, document, resolver, revision=1)
    assert len(reads) == 2 and reasons == {}
    assert len(top.include(_include(document)).windows[0].children) == 2
    card.unlink()  # Q9: deleted -> a placeholder, no traceback
    assert resolver.changed()
    _t, reasons, _r3 = _expand(main, document, resolver, revision=1)
    assert len(reasons) == 1


def test_the_example_is_clean_and_shows_its_whole_component() -> None:
    """The include instance holds the component of address_card.ui, widget for widget."""
    document = read_ui(EXAMPLE).document
    top, reasons, _r = _expand(EXAMPLE, document)
    assert reasons == {}
    child = top.include(_include(document))
    runtime = read_ui(EXAMPLE.parent / "address_card.ui").document.children[0]
    shown = [(n.class_name, n.id) for n in child.windows[0].walk() if isinstance(n, Widget)]
    assert shown == [(n.class_name, n.id) for n in runtime.walk() if isinstance(n, Widget)]


# ---------------------------------------------------------------- canvas (Tk)
def _open_example(app: DesignerApp, root: Any, path: Path = EXAMPLE) -> Any:  # noqa: F811
    app.session.open_document(read_ui(path), path=path)
    _settle(root)
    return app.shell.canvas.stages[0]


@pytest.mark.gui
def test_the_example_renders_read_only_and_selects_the_include(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tk_errors: list[BaseException],  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(app.shell, "_fit_status", shown.append)
    stage = _open_example(app, designer_root)
    view = stage.view
    include = _include(app.session.document)  # type: ignore[arg-type]
    assert view is not None and id(include) in view.included
    frame = view.outer[id(include)]
    labels = [w for w in frame.winfo_children() if w.winfo_class() == "TLabel"]
    assert [w.cget("text") for w in labels] == ["Street", "City"]
    assert all(view.node_of(w) is include for w in frame.winfo_children())  # R5: no inner node
    assert not any(getattr(n, "id", "") == "ent_city" for n in view.nodes.values())
    app.session.select(app.session.document.children[0], origin="tree")  # type: ignore[union-attr]
    _settle(designer_root)
    rect = widget_rect(frame, stage.stage)
    assert rect is not None and rect in stage.overlay._empty  # R-E: the dashed outline
    app.session.select(include, origin="canvas")
    _settle(designer_root)
    assert shown[-1].startswith("'inc_address' shows 'address_card' from")
    assert tk_errors == []


@pytest.mark.gui
def test_touching_the_file_and_a_focus_in_rebuild_the_canvas(
    app: DesignerApp,  # noqa: F811
    designer_root: Any,
    tmp_path: Path,
    tk_errors: list[BaseException],  # noqa: F811
) -> None:
    card = _file(tmp_path / "card.ui", _component())
    main = _main(tmp_path / "main.ui", _inc("card.ui"))
    stage = _open_example(app, designer_root, main)
    include = _include(app.session.document)  # type: ignore[arg-type]
    assert stage.view is not None and id(include) in stage.view.included
    card.rename(tmp_path / "gone.ui")  # UAT 5: renamed on disk
    app.shell.canvas.refresh_includes()  # what the shell's <FocusIn> calls
    _settle(designer_root)
    placeholder = stage.view.outer[id(include)]
    assert placeholder.winfo_class() == "TLabelframe"
    assert "does not exist" in placeholder.winfo_children()[0].cget("text")
    (tmp_path / "gone.ui").rename(card)
    app.shell.canvas.refresh_includes()
    _settle(designer_root)
    assert id(include) in stage.view.included
    assert tk_errors == []


def _describe(frame: Any) -> list[dict[str, Any]]:
    from tests.codegen.test_parity import _widget

    found = []
    for child in frame.winfo_children():
        info = _widget(child)
        info.pop("geometry", None)  # the canvas plate and a runtime toplevel differ in size
        found.append(info)
    return found


@pytest.mark.gui
def test_the_include_frame_matches_load_ui(designer_root: Any, monkeypatch: Any) -> None:
    """Parity (spec 10, ADR-010 Addendum 4): ``build_embedded(design_plan)`` + the resolver
    versus ``load_ui`` on an example with an external include."""
    from tkinter import ttk

    import pyguibud.designer.canvas.engine as engine_module
    from pyguibud.designer.canvas.engine import CanvasEngine
    from pyguibud_runtime import load_ui
    from tests.codegen.test_parity import diff

    monkeypatch.setattr(engine_module, "apply_design_mode", lambda _frame: None)
    document = read_ui(EXAMPLE).document
    window = document.children[0]
    assert isinstance(window, Window)
    host = ttk.Frame(designer_root)
    view = CanvasEngine(REGISTRY, source=lambda: (EXAMPLE, 0)).build(document, window, host)
    loaded = load_ui(EXAMPLE, {}, master=designer_root)
    try:
        designer_root.update_idletasks()
        canvas = _describe(view.outer[id(_include(document))])
        runtime = _describe(loaded.inc_address.address_card)
        assert len(canvas) == 4 and diff(canvas, runtime) == []
    finally:
        loaded.destroy()
        view.destroy()
        host.destroy()
