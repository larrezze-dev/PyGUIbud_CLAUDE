"""Step 19f layout hardening (H85-H88, H92, H96): dialogs capped to the work area, the side
panels' width policy at the minimum size (D4, D5), a pasted 4,000-character export path, and
extreme window sizes plus double-click storms."""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from pyguibud.designer.dialogs.base import ModalDialog
from tests.conftest import reset_geometry
from tests.designer.test_qa18_abuse import _OPENERS, HELLO, _designer, _object_tree_cut, _settle
from tests.designer.test_qa18_abuse import _switch as _switch_language

pytestmark = pytest.mark.gui


@pytest.fixture
def app(designer_root: Any, tmp_path: Path) -> Iterator[Any]:
    """The designer at its minimum size on a copy of hello.ui (a storm may save it)."""
    shutil.copy(HELLO, tmp_path / "hello.ui")
    with _designer(designer_root, tmp_path / "hello.ui") as designer:
        yield designer


def _scaled(app: Any, pixels: int) -> int:
    from pyguibud.designer.theme_tk import scaled

    return scaled(app.root, pixels)


# ------------------------------------------------------------------ H85 (D6)
@pytest.mark.parametrize("lang", ["de_DE", "nl_NL"])
def test_the_shortcuts_sheet_scrolls_within_the_work_area_with_close_visible(
    app: Any, lang: str
) -> None:
    app.open_shortcuts()
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    _switch_language(app, lang)
    _settle(app.root)
    window = dialog.window
    _width, area = dialog.work_area()
    assert window.winfo_reqheight() <= area * 0.85 + 1
    bottom = dialog.close_button.winfo_rooty() + dialog.close_button.winfo_height()
    assert bottom <= window.winfo_rooty() + window.winfo_height()  # inside the dialog ...
    assert bottom <= window.winfo_screenheight()  # ... and on the screen
    canvas = dialog._scroll[0]
    if dialog.rows.winfo_reqheight() > canvas.winfo_height():  # it scrolls: keys and wheel
        dialog.close_button.event_generate("<Next>")
        assert canvas.yview()[0] > 0
        dialog.close_button.event_generate("<Home>")
        assert canvas.yview()[0] == 0
        dialog._on_wheel(SimpleNamespace(delta=-120, num=0))
        assert canvas.yview()[0] > 0


def test_the_work_area_is_the_monitor_less_the_taskbar_and_never_raises(designer_root: Any) -> None:
    """QA-19f-03: dialogs fit the work area of the main window's monitor (taskbar excluded),
    not Tk's ``wm maxsize`` (the whole screen); a failing query falls back to the desktop."""
    import ctypes
    import sys

    from pyguibud.designer import screen

    designer_root.geometry("400x300+50+50")  # on the primary monitor
    designer_root.update()
    width, height, left, top = screen.work_area(designer_root)
    if sys.platform == "win32":
        from ctypes import wintypes

        rect = wintypes.RECT()
        ctypes.windll.user32.SystemParametersInfoW(0x30, 0, ctypes.byref(rect), 0)
        assert (width, height, left, top) == (rect.right - rect.left, rect.bottom - rect.top,
                                              rect.left, rect.top)  # fmt: skip
        assert 0 < screen.title_height(designer_root) <= 100
    fake: Any = SimpleNamespace(winfo_vrootwidth=lambda: 640, winfo_vrootheight=lambda: 480)
    assert len(screen.work_area(fake)) == 4  # no window handle: the desktop, no exception
    reset_geometry(designer_root)


_ALL_OPENERS: dict[str, Callable[[Any], None]] = {**_OPENERS, "about": lambda app: app.open_about()}


@pytest.mark.parametrize("lang", ["de_DE", "nl_NL"])
@pytest.mark.parametrize("name", sorted(_ALL_OPENERS))
def test_every_dialog_fits_a_1366x768_screen(
    app: Any, lang: str, name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: (1366, 728))  # minus a taskbar
    _switch_language(app, lang)
    _ALL_OPENERS[name](app)
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    dialog.fit()
    assert dialog.window.winfo_reqwidth() <= 1366
    assert dialog.window.winfo_reqheight() <= 728


# ------------------------------------------------------------------ H86-H88 (D4, D5)
def _palette_tree(app: Any) -> Any:
    return app.shell.palette.tree


@pytest.mark.parametrize("lang", ["de_DE", "fr_FR", "pt_PT", "nl_NL", "en_XA"])
def test_at_the_minimum_size_the_canvas_keeps_its_floor_and_no_name_is_lost(
    app: Any, lang: str
) -> None:
    from pyguibud.designer.shell import CANVAS_FLOOR

    _switch_language(app, lang)
    shell = app.shell
    assert shell.canvas.frame.winfo_width() >= _scaled(app, CANVAS_FLOOR) - 1
    assert _object_tree_cut(app) == set()
    tree = shell.tree.tree
    assert tree.winfo_width() >= int(tree.column("#0", "width"))  # the name column is shown
    palette, rows = shell.palette, shell.palette._rows
    for iid, (full, _icon, _category) in rows.items():
        shown = str(_palette_tree(app).item(iid, "text"))
        assert shown == full or (shown.endswith("…") and full.startswith(shown[:-1].rstrip()))
        if shown != full:  # an elided name has its full name as the tooltip
            box = _palette_tree(app).bbox(iid)
            palette._on_motion(SimpleNamespace(y=box[1] + 1))
            assert palette._tip.text == full


def test_the_palette_gives_way_first_and_its_names_come_back(app: Any) -> None:
    """Below 800 px wide (a lowered minimum) the palette is first to give way: names elide."""
    root, palette, tree = app.root, app.shell.palette, _palette_tree(app)
    minimum = root.minsize()
    try:
        root.minsize(1, 1)
        root.geometry("700x500")
        _switch_language(app, "fr_FR")
        assert app.shell.canvas.frame.winfo_width() >= _scaled(app, 280) - 1
        assert palette.frame.winfo_width() < palette.fit_width()
        item = max(palette._rows, key=lambda iid: len(palette._rows[iid][0]))
        full = palette._rows[item][0]
        assert str(tree.item(item, "text")).endswith("…")
        tree.see(item)
        _settle(root)
        palette._on_motion(SimpleNamespace(y=tree.bbox(item)[1] + 1))
        assert palette._tip.text == full
        root.geometry("1400x700")
        _switch_language(app, "en_GB", "fr_FR")  # D4: wide again after the next switch
        assert str(tree.item(item, "text")) == full
        tree.see(item)
        _settle(root)
        palette._on_motion(SimpleNamespace(y=tree.bbox(item)[1] + 1))
        assert palette._tip.text == ""
    finally:
        root.minsize(*minimum)
        reset_geometry(root)


def test_d4_an_auto_grown_palette_shrinks_back_after_a_long_language(app: Any) -> None:
    app.root.geometry("1200x700")
    _settle(app.root)
    palette = app.shell.palette
    _switch_language(app, "en_GB")
    english = palette.frame.winfo_width()
    _switch_language(app, "fr_FR")
    assert palette.frame.winfo_width() >= palette.fit_width() - 1 > english
    _switch_language(app, "en_GB")
    assert abs(palette.frame.winfo_width() - english) <= 1


def test_d4_a_width_the_user_dragged_is_kept_on_a_switch(app: Any) -> None:
    app.root.geometry("1200x700")
    _settle(app.root)
    shell, body = app.shell, app.shell.body
    start = int(body.sashpos(0))
    shell._on_sash_press(SimpleNamespace(x=start + 2, y=20))
    assert shell._palette_drag
    body.sashpos(0, 330)
    shell._on_sash_release(None)
    _switch_language(app, "de_DE", "en_GB")
    assert abs(int(body.sashpos(0)) - 330) <= 1
    shell._on_sash_press(SimpleNamespace(x=5, y=20))  # a press beside the sash: not a drag
    assert not shell._palette_drag


def test_a_theme_switch_refits_the_palette(app: Any) -> None:
    app.root.geometry("1200x700")
    _switch_language(app, "fr_FR")
    app.shell.body.sashpos(0, 500)  # moved by the program, not the user: not kept
    app.set_theme("dark")
    app.flush_theme()
    _settle(app.root)
    assert abs(app.shell.palette.frame.winfo_width() - app.shell.palette.fit_width()) <= 1


# ------------------------------------------------------------------ H92
def test_a_4000_character_path_keeps_the_export_buttons_on_screen(app: Any) -> None:
    app.exporter.start()
    _settle(app.root)
    dialog = app._live_dialogs()[-1]
    long_path = "Z:/no-such-folder/" + "d" * 4000 + "/x.py"
    dialog.output.set(long_path)
    dialog.accept()
    _settle(app.root)
    window = dialog.window
    assert not dialog.closed and dialog.message.winfo_manager()
    assert len(str(dialog.message.cget("text"))) < 600  # the path is shown elided
    assert dialog.output.get() == long_path == dialog.request().output  # the value is whole
    assert window.winfo_reqheight() <= dialog.work_area()[1]
    for button in (dialog.export_button, dialog.cancel_button):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= window.winfo_screenheight()
    dialog.accept()  # Export again: refused again, the dialog stays the same height
    assert window.winfo_reqheight() <= dialog.work_area()[1]


# ------------------------------------------------------------------ H96
def test_tiny_and_8k_window_sizes_raise_nothing(app: Any) -> None:
    root = app.root
    minimum = root.minsize()
    try:
        root.minsize(1, 1)
        for size in ("1x1", "7680x4320", "1x1", "800x500"):
            root.geometry(size)
            _settle(root)
            app.shell.clamp_sashes()
            _settle(root)
        _switch_language(app, "de_DE")
        root.geometry("7680x4320")
        _settle(root)
        assert app.shell.canvas.frame.winfo_width() >= _scaled(app, 280) - 1
    finally:
        root.minsize(*minimum)
        reset_geometry(root)


_STORM = ("file.new", "file.export", "edit.undo", "edit.redo", "edit.copy", "edit.cut",
          "edit.paste", "edit.delete", "file.export", "file.new")  # fmt: skip


def test_a_double_click_storm_opens_at_most_one_dialog(app: Any) -> None:
    """Every button is stormed from a clean state; edits make the document dirty, so the later
    File > New and Export bursts also storm their "save first?" question."""
    buttons = {action.id: button for button, action in app.shell._buttons}
    app.session.select(app.session.document.children[0].children[0], origin="canvas")
    opened = 0
    for action_id in _STORM:
        button = buttons[action_id]
        for _click in range(4):
            if str(button.cget("state")) != "disabled":
                button.invoke()
        app.root.update_idletasks()
        live = app._live_dialogs()
        assert len(live) <= 1, action_id
        opened += len(live)
        for dialog in live:
            dialog.close()
            dialog.close()  # a second click on a closing dialog does nothing
    assert opened >= 3  # New, Export and the dirty questions really opened (one each)
    for _round in range(3):
        app.open_shortcuts()
        app.open_about()
        app.exporter.start()
    assert len(app._live_dialogs()) == 1


@pytest.mark.parametrize("lang", ["de_DE", "nl_NL"])
def test_message_dialogs_with_a_huge_text_keep_their_buttons_in_a_1366x768_screen(
    app: Any, lang: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ModalDialog, "work_area", lambda _self: (1366, 728))
    _switch_language(app, lang)
    huge = "Z:/" + "folder/" * 600 + "x.py"
    openers: tuple[Callable[[], None], ...] = (
        lambda: app._confirm(huge, lambda: None),
        lambda: app._ask(lambda: huge, [("_OK", None)]),
        lambda: app._ask_name("main", lambda _t: None, lambda _t: None),
        lambda: app._tell(lambda: huge),
    )
    for open_it in openers:
        open_it()
        _settle(app.root)
        dialog = app._live_dialogs()[-1]
        window = dialog.window
        assert window.winfo_reqwidth() <= 1366 and window.winfo_height() <= 728
        buttons = [w for w in _descendants(window) if w.winfo_class() == "TButton"]
        assert buttons
        for button in buttons:
            bottom = button.winfo_rooty() - window.winfo_rooty() + button.winfo_height()
            assert button.winfo_ismapped() and bottom <= window.winfo_height(), button
        dialog.close()


def test_a_dialog_is_made_transient_before_it_is_shown(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Windows Tk withdraws a shown window that is made transient while another application is
    in front (a Close from the taskbar, a test run in the background): the dialog then held the
    grab unseen and the designer looked frozen. ``open`` sets ``transient`` first (19f gate)."""
    from pyguibud.designer.dialogs.confirm import ConfirmDialog

    calls: list[str] = []
    dialog = ConfirmDialog(app.root, "?", lambda: None)
    window: Any = dialog.window

    def spy(name: str) -> Callable[..., Any]:
        real = getattr(window, name)

        def call(*args: Any) -> Any:
            calls.append(name)
            return real(*args)

        return call

    for name in ("transient", "deiconify"):
        monkeypatch.setattr(window, name, spy(name))
    app._open_dialog(lambda: dialog)
    _settle(app.root)
    assert calls[:2] == ["transient", "deiconify"]
    assert window.state() == "normal" and window.winfo_ismapped()
    dialog.close()


def _descendants(widget: Any) -> list[Any]:
    found = []
    for child in widget.winfo_children():
        found += [child, *_descendants(child)]
    return found


def test_restored_sashes_survive_the_start_up_refit(designer_root: Any) -> None:
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings

    designer = DesignerApp(designer_root, settings=Settings(sashes={"main": (300, 900)}))
    try:
        assert designer.open_path(HELLO)
        designer_root.deiconify()
        designer_root.geometry("1200x700+0+0")
        for _round in range(3):
            _settle(designer_root)
        body: Any = designer.shell.body
        assert abs(int(body.sashpos(0)) - 300) <= 1
    finally:
        designer.dispose()
        reset_geometry(designer_root)


@pytest.mark.parametrize("dragged", [True, False], ids=["dragged", "auto-grown"])
@pytest.mark.parametrize("wider", [True, False], ids=["wider", "narrower"])
def test_d4_only_a_saved_dragged_palette_width_counts_as_the_user_width(
    designer_root: Any, wider: bool, dragged: bool
) -> None:
    """A width the user dragged in an earlier session is kept across a restart and a language
    switch; a restored sash that only auto-grew is not a user width and shrinks back
    (QA-19f-01)."""
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings
    from pyguibud.i18n import set_language

    saved = 330 if wider else 100  # wider than the natural width / narrower than the en fit
    sashes = {"main": (saved, 900), **({"palette_user": (saved,)} if dragged else {})}
    designer = DesignerApp(designer_root, settings=Settings(sashes=sashes))
    try:
        assert designer.open_path(HELLO)
        designer_root.deiconify()
        designer_root.geometry("1200x700+0+0")
        for _round in range(3):
            _settle(designer_root)
        designer._apply_sashes()  # what the first real size does (``_restore_sashes``)
        _settle(designer_root)
        body: Any = designer.shell.body
        palette = designer.shell.palette
        natural = max(palette.frame.winfo_reqwidth(), palette.fit_width())
        user = saved if dragged else 0
        assert designer.shell.palette_user == user
        assert not wider or abs(int(body.sashpos(0)) - saved) <= 1  # the saved sash is restored
        set_language("de_DE")
        _settle(designer_root)
        _settle(designer_root)
        german = int(body.sashpos(0))
        assert abs(german - max(user, palette.frame.winfo_reqwidth(), palette.fit_width())) <= 1
        set_language("en_GB")
        _settle(designer_root)
        _settle(designer_root)
        expected = saved if wider and dragged else natural
        assert abs(int(body.sashpos(0)) - expected) <= 1
    finally:
        set_language("en_GB")
        designer.dispose()
        reset_geometry(designer_root)


@pytest.mark.parametrize("drag", [True, False], ids=["dragged", "never-dragged"])
def test_d4_quit_stores_the_dragged_palette_width_apart(
    designer_root: Any, tmp_path: Path, drag: bool
) -> None:
    """Quit stores the palette width only when the user dragged its sash; it survives a
    save and a load of the settings file (QA-19f-01)."""
    from pyguibud.designer.app import DesignerApp
    from pyguibud.designer.settings import Settings, load_settings, save_settings

    designer = DesignerApp(designer_root, settings=Settings())
    try:
        assert designer.open_path(HELLO)
        designer_root.deiconify()
        designer_root.geometry("1200x700+0+0")
        for _round in range(3):
            _settle(designer_root)
        shell = designer.shell
        body: Any = shell.body
        if drag:
            shell._on_sash_press(SimpleNamespace(x=int(body.sashpos(0)) + 2, y=20))
            body.sashpos(0, 330)
            shell._on_sash_release(None)
        designer._remember_window()
        path = tmp_path / "settings.json"
        assert save_settings(designer.settings, path=path)
        loaded, problem = load_settings(path)
        assert problem is None
        assert loaded.sashes.get("palette_user") == ((330,) if drag else None)
        assert len(loaded.sashes["main"]) == 2
    finally:
        designer.dispose()
        reset_geometry(designer_root)
