"""File > Export Python code… (Ctrl+E): the dialog and its controller (spec preview-export 6.3).

The checks and writes are :mod:`pyguibud.designer.export` (pure); "Run the module after export"
uses a second :class:`~pyguibud.designer.preview_tk.PreviewRunner`, so at most one run lives.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import tkinter
from collections.abc import Callable
from pathlib import Path
from tkinter import ttk
from typing import Any

from pyguibud.codegen import CodegenError
from pyguibud.codegen import _class_name as class_name_for
from pyguibud.designer import export as ex
from pyguibud.designer.dialogs import files as file_dialogs
from pyguibud.designer.dialogs.base import ModalDialog
from pyguibud.designer.dialogs.message import Answer
from pyguibud.designer.files import path_key
from pyguibud.designer.preview_tk import PreviewRunner
from pyguibud.designer.session import DesignerSession
from pyguibud.designer.settings import Settings, remember_export
from pyguibud.designer.theme_tk import INVALID_PREFIX
from pyguibud.i18n import N_, PSEUDO_LANGUAGE, _

__all__ = ["ExportController", "ExportDialog"]

_M_TITLE = N_("Export Python code")
_M_OUTPUT = N_("Output file")
_M_CLASS = N_("Class name")
_M_CLASS_HINT = N_("Rename the main window to change the class name.")
_M_POT = N_("Also write a translation template (.pot)")
_M_OUTSIDE = N_("Allow images and included files outside the .ui folder")
_M_RUN = N_("Run the module after export")
# Translators: opens a file chooser; the dialog has two of these buttons, so no access key.
_M_BROWSE = N_("Browse…")
# Translators: the buttons of the Export dialog; _ marks the access key (Alt+letter).
_M_EXPORT = N_("_Export")
_M_CANCEL = N_("_Cancel")
# Translators: {name} is a file name such as "main.ui"; asked before the Export dialog opens.
_M_UNSAVED = N_("Export uses the saved file, and '{name}' has changes that are not saved.")
_M_SAVE_AND_EXPORT = N_("_Save and export")
_M_CHANGED_BEFORE_RUN = N_("'{output}' changed after it was written, so it was not run.")
_MAX_OUTSIDE_LINES = 5


class ExportDialog(ModalDialog):
    """The rows of spec 6.3. ``on_export`` exports (and returns None) or returns the refusal;
    a refusal keeps the dialog open with the reason, and Export re-checks."""

    TITLE = _M_TITLE

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the app root
        *,
        class_name: str,
        output: str,
        pot: str,
        outside: tuple[str, ...],
        on_export: Callable[[ex.ExportRequest], ex.Refusal | None],
    ) -> None:
        super().__init__(root)
        self.on_export = on_export
        self.reason: ex.Refusal | None = None
        body = self.body
        body.columnconfigure(1, weight=1)
        self.output = tkinter.StringVar(root, value=output)
        self.pot = tkinter.StringVar(root, value=pot)
        self.want_pot, self.allow, self.run_after = (tkinter.BooleanVar(root) for _i in range(3))
        self.output_label = ttk.Label(body)
        self.output_label.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.output_entry = ttk.Entry(body, textvariable=self.output, width=48)
        self.output_entry.grid(row=0, column=1, sticky="ew")
        self.output_browse = ttk.Button(body, command=lambda: self._browse(self.output, False))
        self.output_browse.grid(row=0, column=2, padx=(6, 0))
        self.class_label = ttk.Label(body)
        self.class_label.grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Label(body, text=class_name).grid(row=1, column=1, sticky="w", pady=(8, 0))
        wrap = root.winfo_fpixels("4.5i")
        self.class_hint = ttk.Label(body, wraplength=wrap, justify="left")
        self.class_hint.grid(row=2, column=1, columnspan=2, sticky="w")
        self.pot_check = ttk.Checkbutton(body, variable=self.want_pot, command=self._pot_state)
        self.pot_check.grid(row=3, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.pot_entry = ttk.Entry(body, textvariable=self.pot)
        self.pot_entry.grid(row=4, column=1, sticky="ew")
        self.pot_browse = ttk.Button(body, command=lambda: self._browse(self.pot, True))
        self.pot_browse.grid(row=4, column=2, padx=(6, 0))
        self.allow_check = ttk.Checkbutton(body, variable=self.allow)
        self.allow_check.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.paths = ttk.Label(body, justify="left", wraplength=wrap)
        self.paths.grid(row=6, column=1, columnspan=2, sticky="w")
        self.run_check = ttk.Checkbutton(body, variable=self.run_after)
        self.run_check.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.message = ttk.Label(body, style=f"{INVALID_PREFIX}.TLabel", justify="left",
                                 wraplength=wrap)  # fmt: skip
        self.message.grid(row=8, column=0, columnspan=3, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=9, column=0, columnspan=3, sticky="e", pady=(12, 0))
        self.export_button = ttk.Button(buttons, command=self.accept, default="active")
        self.cancel_button = ttk.Button(buttons, command=self.close)  # after Export: tab order
        self.cancel_button.pack(side="right", padx=(6, 0))
        self.export_button.pack(side="right")
        self.access_keys = [(self.export_button, _M_EXPORT), (self.cancel_button, _M_CANCEL)]
        self.window.bind("<Return>", self._on_return)
        self._show_outside(outside)
        self._pot_state()

    def initial_focus(self) -> Any:  # noqa: ANN401 - a Tk widget
        return self.output_entry

    def retranslate(self) -> None:
        for widget, msgid in (
            (self.output_label, _M_OUTPUT), (self.output_browse, _M_BROWSE),
            (self.class_label, _M_CLASS), (self.class_hint, _M_CLASS_HINT),
            (self.pot_check, _M_POT), (self.pot_browse, _M_BROWSE),
            (self.allow_check, _M_OUTSIDE), (self.run_check, _M_RUN),
        ):  # fmt: skip
            widget.configure(text=_(msgid))
        self.label_buttons()
        self._show_reason(self.reason)
        super().retranslate()

    def _pot_state(self) -> None:
        state = "normal" if self.want_pot.get() else "disabled"
        self.pot_entry.configure(state=state)
        self.pot_browse.configure(state=state)

    def _browse(self, variable: tkinter.StringVar, pot: bool) -> None:
        chosen = file_dialogs.ask_export(self.window, variable.get(), pot=pot)
        if chosen:
            variable.set(chosen)

    def _show_outside(self, paths: tuple[str, ...]) -> None:
        """The check box and the paths, only when the document has such paths (D11)."""
        if not paths:
            self.allow_check.grid_remove()
            self.paths.grid_remove()
            return
        lines = list(paths[:_MAX_OUTSIDE_LINES])
        if len(paths) > _MAX_OUTSIDE_LINES:
            lines.append(ex.more_text(len(paths) - _MAX_OUTSIDE_LINES))
        self.paths.configure(text="\n".join(lines))
        self.allow_check.grid()
        self.paths.grid()

    def _show_reason(self, reason: ex.Refusal | None) -> None:
        self.reason = reason
        if reason is None:
            self.message.grid_remove()
            return
        self.message.configure(text=reason.text())
        self.message.grid()

    def request(self) -> ex.ExportRequest:
        pot = self.pot.get() if self.want_pot.get() else None
        return ex.ExportRequest(self.output.get(), pot, self.allow.get(), self.run_after.get())

    def _on_return(self, event: Any) -> str:  # noqa: ANN401 - a Tk event
        """Enter presses a focused Cancel or Browse… button; anywhere else it exports."""
        widget = getattr(event, "widget", None)
        if widget in (self.cancel_button, self.output_browse, self.pot_browse):
            widget.invoke()
        else:
            self.accept()
        return "break"

    def accept(self) -> None:
        """Export now; a refusal stays in the dialog (and reveals the outside paths)."""
        refusal = self.on_export(self.request())
        if refusal is None:
            self.close()
            return
        if refusal.outside:
            self._show_outside(refusal.outside)
        self._show_reason(refusal)
        self.fit()
        self.output_entry.focus_set()


class ExportController:
    """File > Export: the D10 prompt, the dialog, the writes, the status text and the run."""

    def __init__(
        self,
        root: Any,  # noqa: ANN401 - the designer's Tk root
        session: DesignerSession,
        settings: Settings,
        *,
        post: Callable[[str], None],
        tell: Callable[[str], None],
        ask: Callable[[Callable[[], str], list[tuple[str, Answer]]], None],
        save: Callable[[Callable[[], object]], None],
        open_dialog: Callable[[Callable[[], ModalDialog]], object],
        save_settings: Callable[[], None],
        popen: Callable[..., Any] = subprocess.Popen,
    ) -> None:
        self.root, self.session, self.settings = root, session, settings
        self.post, self.tell, self.ask, self.save = post, tell, ask, save
        self.open_dialog, self.save_settings = open_dialog, save_settings
        self.runner = PreviewRunner(root, lambda _themes: None, self._exited, popen)

    def start(self) -> None:
        """Ctrl+E: a dirty or untitled document is saved first (D10), then the dialog opens."""
        session, document = self.session, self.session.document
        if document is None:
            return
        path = session.path
        if path is None or session.dirty:
            self.ask(
                lambda: _(_M_UNSAVED).format(name=session.display_name),
                [(_M_SAVE_AND_EXPORT, lambda: self.save(self.start)), (_M_CANCEL, None)],
            )
            return
        if session.stamp is None or session.stamp.changed(path):
            self.tell(_(ex.M_CHANGED))
            return
        mains = [w.id for w in document.children if w.kind == "main"]
        try:
            name = class_name_for(mains[0] if mains else None, str(path))
        except CodegenError:
            name = "—"
        remembered = self.settings.exports.get(path_key(path))
        output, pot = ex.default_paths(path, document.meta.i18n_domain, remembered)
        outside = ex.outside_paths(session.report().warnings)
        self.open_dialog(lambda: ExportDialog(self.root, class_name=name, output=output, pot=pot,
                                              outside=outside, on_export=self.export))  # fmt: skip

    def export(self, request: ex.ExportRequest) -> ex.Refusal | None:
        """Check, write, remember and report; run the module when asked (T7)."""
        session = self.session
        source = ex.ExportSource(session.path, session.dirty, session.stamp)
        self.root.configure(cursor="watch")  # generation runs here: <= 1.5 s for 10,000 widgets
        self.root.update_idletasks()
        try:
            plan = ex.export_plan(source, request)
            outcome = ex.run_export(plan) if isinstance(plan, ex.ExportPlan) else None
        finally:
            self.root.configure(cursor="")
        if not isinstance(plan, ex.ExportPlan) or outcome is None:
            return plan if isinstance(plan, ex.Refusal) else None
        if not outcome.written:
            return outcome.failure
        if session.path is not None:  # T6: proposed next time
            remember_export(self.settings, path_key(session.path), plan.output)
            self.save_settings()
        text = outcome.text()
        if plan.run_after:
            text = " ".join(t for t in (text, self._run(plan)) if t)
        self.post(text)
        return None

    def _run(self, plan: ex.ExportPlan) -> str:
        """Run what was just written, in its folder; the status note (or "")."""
        if not ex.intact(plan.output, plan.text):
            return _(_M_CHANGED_BEFORE_RUN).format(output=plan.output)
        lang = self.settings.preview_lang
        self.runner.dispose()  # one run at a time: the previous one ends (<= 1 s)
        try:
            folder = Path(tempfile.mkdtemp(prefix="pyguibud-preview-run-"))
        except OSError as exc:
            return exc.strerror or str(exc)
        try:
            argv = ex.run_argv(plan.output, lang)
            self.runner.start(argv, folder, cwd=Path(plan.output).parent, wait_ready=False)
        except OSError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            return exc.strerror or str(exc)
        return _(ex.M_RUN_PSEUDO) if lang == PSEUDO_LANGUAGE else ""

    def _exited(self, code: int, _result: tuple[str, str], tail: str, _timed_out: bool) -> None:
        if code != 0:
            self.tell("\n\n".join(t for t in (_(ex.M_RUN_FAILED).format(code=code), tail) if t))

    def dispose(self) -> None:
        self.runner.dispose()
