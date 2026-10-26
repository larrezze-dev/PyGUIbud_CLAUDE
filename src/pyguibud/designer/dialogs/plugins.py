"""Help > Plugins…: what the registry loaded, what failed and why (Tk; spec plugins 8, D16)."""

from __future__ import annotations

import contextlib
import tkinter
from collections.abc import Callable
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any

from pyguibud.core.registry import Registry
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.present.plugins import PluginRow, plugin_rows, status_texts, toggled
from pyguibud.designer.settings import Settings
from pyguibud.designer.theme_tk import LIST_STYLE
from pyguibud.i18n import N_, _

__all__ = ["PluginsDialog"]

# Translators: the title of the Help > Plugins dialog (installed widget packages).
_M_TITLE = N_("Plugins")
# Translators: the header of Help > Plugins (ADR-004 trust boundary).
_M_TRUST = N_(
    "Plugins run their own code inside PyGUIbud and the preview: install only plugins you "
    "trust. Disabling or enabling a plugin takes effect when PyGUIbud starts again."
)
# Translators: the column headings of the plugin list.
_M_DISTRIBUTION = N_("Distribution")
# Translators: a column heading of Help > Plugins: the widget classes a plugin adds.
_M_WIDGETS = N_("Widgets")
# Translators: a column heading of Help > Plugins: Loaded, Failed, Disabled...
_M_STATUS = N_("Status")
# Translators: the buttons of Help > Plugins; _ marks the access key (Alt+letter).
_M_COPY = N_("_Copy details")
# Translators: a button of Help > Plugins; _ marks the access key.
_M_DISABLE = N_("_Disable on next start")
# Translators: a button of Help > Plugins; _ marks the access key.
_M_ENABLE = N_("_Enable on next start")
# Translators: a button of Help > Plugins; _ marks the access key.
_M_CLOSE = N_("C_lose")
_POLL_MS = 1000  # live factory failures bump ``registry.revision``


def _tk_safe(text: str) -> str:
    """``text`` with each NUL shown as the symbol for null: under Python 3.10, _tkinter ends a
    Text insert and the clipboard at U+0000, which hid a hostile name's details (CI 20b.1)."""
    return text.replace("\x00", "\N{SYMBOL FOR NULL}")


class PluginsDialog(ModalDialog):
    """The plugin list, a read-only details box, Copy details, the toggle and Close."""

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        registry: Registry,
        settings: Settings,
        *,
        copy: Callable[[str], None],
        save: Callable[[], None],
        safe_mode: bool = False,
    ) -> None:
        super().__init__(root)
        self.registry, self.settings, self._copy, self._save = registry, settings, copy, save
        self.safe_mode = safe_mode
        self.rows: list[PluginRow] = []
        self._revision = -1
        self._poll_id: str | None = None
        wrap = self.root.winfo_fpixels("5i")
        self.header = ttk.Label(self.body, justify="left", wraplength=wrap)
        self.header.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.tree = ttk.Treeview(self.body, columns=("widgets", "status"), height=6,
                                 selectmode="browse", style=LIST_STYLE)  # fmt: skip
        self.tree.grid(row=1, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show())
        box = ttk.Frame(self.body)
        box.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        self.details = tkinter.Text(box, width=72, height=10, wrap="word",
                                    state="disabled", takefocus=1)  # fmt: skip
        self.ring_on_focus(self.details)  # read-only, but the arrows and Page keys scroll it
        bar = ttk.Scrollbar(box, orient="vertical", command=self.details.yview, takefocus=0)
        self.details.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")  # packed first: it keeps its width when space is short
        self.details.pack(side="left", fill="both", expand=True)
        self.body.columnconfigure(0, weight=1)
        self.body.rowconfigure(2, weight=1)
        buttons = ttk.Frame(self.body)
        buttons.grid(row=3, column=0, sticky="e", pady=(12, 0))
        self.copy_button = ttk.Button(buttons, command=self.copy)
        self.toggle_button = ttk.Button(buttons, command=self.toggle)
        self.close_button = ttk.Button(buttons, command=self.close)
        for button in (self.copy_button, self.toggle_button, self.close_button):
            button.pack(side="left", padx=(6, 0))
        self._poll()

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        return self.tree

    def selected(self) -> PluginRow | None:
        chosen = self.tree.selection()
        return self.rows[int(chosen[0])] if chosen else None

    def retranslate(self) -> None:
        self.header.configure(text=_(_M_TRUST))
        self.tree.heading("#0", text=_(_M_DISTRIBUTION))
        self.tree.heading("widgets", text=_(_M_WIDGETS))
        self.tree.heading("status", text=_(_M_STATUS))
        # The status column fits every text it can show, so a toggle never clips it; fixed, as
        # Tk would otherwise re-stretch it to the mapped tree. The widget list may clip.
        name = str(ttk.Style(self.tree).lookup("Treeview", "font") or "TkDefaultFont")
        try:
            font = tkfont.nametofont(name)
        except tkinter.TclError:
            font = tkfont.nametofont("TkDefaultFont")
        width = max(font.measure(text) for text in (*status_texts(), _(_M_STATUS)))
        pad = int(self.root.winfo_fpixels("0.3i"))
        self.tree.column("status", width=width + pad, minwidth=width + pad, stretch=False)
        self.refresh()
        super().retranslate()

    def refresh(self) -> None:
        """Re-read the registry, keeping the selected distribution."""
        current = self.selected()
        self._revision = self.registry.revision
        self.rows = plugin_rows(self.registry)
        self.tree.delete(*self.tree.get_children())
        disabled_next, safe_mode = self.settings.disabled_plugins, self.safe_mode
        statuses = [row.status_text(disabled_next, safe_mode=safe_mode) for row in self.rows]
        for index, (row, status) in enumerate(zip(self.rows, statuses, strict=True)):
            self.tree.insert("", "end", iid=str(index), text=row.distribution,
                             values=(", ".join(row.classes), status))  # fmt: skip
        keys = [row.key for row in self.rows]
        index = keys.index(current.key) if current is not None and current.key in keys else 0
        if self.rows:
            self.tree.selection_set(str(index))
            self.tree.focus(str(index))
        self._show()

    def _show(self) -> None:
        row = self.selected()
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", _tk_safe(row.details()) if row is not None else "")
        self.details.configure(state="disabled")
        wanted = row is not None and row.key in self.settings.disabled_plugins
        self.access_keys = [(self.copy_button, _M_COPY),
                            (self.toggle_button, _M_ENABLE if wanted else _M_DISABLE),
                            (self.close_button, _M_CLOSE)]  # fmt: skip
        self.label_buttons()
        can_toggle = row is not None and row.can_toggle
        self.toggle_button.state(["!disabled" if can_toggle else "disabled"])
        self.copy_button.state(["!disabled" if row is not None else "disabled"])

    def copy(self) -> None:
        """Copy details: the selected distribution's messages and tracebacks."""
        row = self.selected()
        if row is not None:
            self._copy(_tk_safe(f"{row.distribution}\n\n{row.details()}"))

    def toggle(self) -> None:
        """Disable or enable the selected plugin from the next start (written at once)."""
        row = self.selected()
        if row is None or not row.can_toggle:
            return
        self.settings.disabled_plugins = toggled(self.settings.disabled_plugins, row.key)
        self._save()
        self.refresh()

    def _poll(self) -> None:
        if self.closed:
            return
        if self.registry.revision != self._revision and self._revision >= 0:
            self.refresh()
        self._poll_id = self.window.after(_POLL_MS, self._poll)

    def close(self) -> None:
        if self._poll_id is not None and not self.closed:
            with contextlib.suppress(tkinter.TclError):
                self.window.after_cancel(self._poll_id)
        super().close()
