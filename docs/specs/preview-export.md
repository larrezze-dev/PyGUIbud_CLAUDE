# Spec — Step 15: preview and export

- **Status:** Accepted (user, 2026-10-11: D1–D14 all defaults; §13 resolved) · **ADR:** ADR-013 (Accepted); it builds on ADR-003/008 (codegen), ADR-007 (boundary), ADR-009 D4 (subprocess preview, Accepted) and ADR-011 (lifecycle)
- **Owner:** FRONTEND (designer side) + BACKEND (the child process, the `codegen.output` move) · **Reviewer:** SOFTWARE-ARCHITECT
- **Budget:** ≈ 1,100 production lines over two halves, caps 800 + 560 (§0)
- **Plan row 15:** live preview window and the Export `.py` dialog. UAT: "Preview matches the exported `.py` when run".

## 0. Scope fence, budget and split
**In:**
- **A, preview:** run the open document (saved or not) in a separate process, with the document's own theme and a chosen language. F5 restarts it. Theme and language switch live while it runs (FEATURES M10, S3).
- **B, export:** a dialog that writes the `.py` module exactly as `pyguibud-uic` would, optionally writes a `.pot`, and optionally runs the result.

**Out:**
- Other toolkits. Step 16 adds the `tkinter` and `pyside6` preview hosts; §7 shows where they plug in.
- Codegen for toolkits other than ttkbootstrap (not in the plan).
- Hot reload inside a running preview.
- Connecting the user's real handler code.
- A screenshot export (FEATURES S5).
- Batch or project export (FEATURES C2).
- Changing the generated module's shape. **No change to `codegen/_emit.py`, `_plan.py` or `_support.py`.**

**Hard constraints:**
- **No `.ui` format change and no schema bump.** No change to `core/` or `pyguibud_runtime/`.
- The one refactor is moving the output guards from `uic.py` to `codegen/output.py` (§6.1), with the behaviour unchanged. The existing `tests/test_uic*.py` and `tests/codegen/test_cli_generate.py` stay green with no edits apart from imports.
- Opening or previewing never runs user code. The child calls `load_ui` with no-op handlers. "Run after export" runs only the file this dialog has just written.

**Split (D13):**

| Half | Contents | Estimate | Cap |
|---|---|---|---|
| **15a "Preview"** | the child package, `designer/preview.py` (pure), `designer/preview_tk.py` (runner), actions, settings, icons | ≈ 650 | 800 |
| **15b "Export"** | `codegen/output.py` (move + about 30 new lines), `designer/export.py` (pure), `designer/dialogs/export.py`, run after export, actions | ≈ 450 | 560 |

The estimates include about 30 % overshoot. Trims are applied in order when a half's running count projects past its cap:

| Trim | Half | Dropped | Lines |
|---|---|---|---|
| T1 | 15a | reopen the preview at its last position | −25 |
| T2 | 15a | the findings dialog that selects the first error (the status bar names the count and the first error instead) | −30 |
| T3 | 15a | the "Export will refuse this" hint (§4.5) | −25 |
| T4 | 15a | live theme switch over stdin (a theme change restarts the child with `--theme`) | −60 |
| T5 | 15b | the `.pot` option | −50 |
| T6 | 15b | remembering the export path per `.ui` | −20 |
| T7 | 15b | run after export | −35 |

Not counted: tests (≈ 800), `.po` updates, icons (SVG data).

## 1. Decisions — recommended default in **bold** — **resolved 2026-10-11: all defaults (a)**
| ID | Question | Options |
|---|---|---|
| D1 | Preview process model | **(a) a separate process, `python -m pyguibud.preview`, which runs `pyguibud_runtime.load_ui`. Already decided by ADR-009 and designer-shell D4; ADR-013 defines the boundary.** Reasons: crash and hang isolation; the document's own theme (one `Style` per process); no `root_exists`; Step 16's Qt loop cannot share the designer's Tk process. · (b) an in-process `Toplevel`: the designer theme only, a crash takes the designer down, no PySide6. Contradicts ADR-009. |
| D2 | What the child runs | **(a) `load_ui` (the runtime). It supports `--backend` (Step 16) and `en_XA`, and parity with the generated module is test-gated (§9).** · (b) generate a temporary `.py` and run it: identical to the export by construction, but ttkbootstrap only (blocks Step 16), no `en_XA`, and no preview for documents with only components or newer MINOR files. |
| D3 | Unsaved or dirty document | **(a) clean, saved and `FileStamp` unchanged → the child loads `session.path` directly (exact runtime paths and catalogues). Dirty or untitled → a `dump_ui` snapshot in a private temporary folder, with paths rebased on a copy and `localedir=<.ui dir>/locale`.** · (b) always require a save first · (c) always a snapshot, even when clean (catalogues of external includes in other folders are lost, ADR-013 ➖) |
| D4 | Refresh | **(a) manual: F5 restarts the single preview (old child told to quit, killed after 2 s), reopening at the last position (T1).** · (b) auto-restart 1 s after each change (flicker, focus theft, a process per edit burst) · (c) reload inside the child (a second root after `destroy` in one process is fragile with ttkbootstrap's `Style` singleton) |
| D5 | Which window | **(a) the window on the canvas tab. Main → the whole interface, as the export runs it. Dialog → that dialog alone (main withdrawn; closing the dialog ends the preview). Component → hosted in a synthetic dialog `preview_host` (snapshot only). Documents without a main window → a hidden root, with the theme applied before `load_ui(master=root)`, as the generated `_preview_dialog` does.** · (b) always the main window, or the first dialog (exactly what `python out.py` shows; components cannot be previewed) |
| D6 | Preview language | **(a) Preview ▸ Language: "Document language" (the source, the default) + the 8 locales + `en_XA`. Remembered in settings (`preview_lang`). Live switch through `ui.retranslate`. A missing catalogue → the status bar says so and the source texts are shown.** · (b) follow the designer UI language · (c) only catalogues found on disk |
| D7 | Preview theme | **(a) the document's `meta/@theme` by default. Preview ▸ Theme lists the themes the child reports (`ready.json`) as a preview-only override, switched live (T4). Plus Preview ▸ Use this theme in the document → `SetField(meta, "theme", name)`, one undo step. Today no editor sets `meta/@theme`; this is the only one.** · (b) document theme only, no override (M10's "live theme switch" unmet) · (c) override only, no "use in document" |
| D8 | Handlers at design time | **(a) no-op callables for every handler name (so no `handler_missing` warning noise). The status bar notes once: `Preview: handlers are not connected, so buttons and menus do nothing.`** · (b) each call is echoed to the designer status bar (`Preview: 'on_save' was called.`) over a stdout reader thread (+40 lines) |
| D9 | Validation errors | **(a) Preview and Export are blocked while the document has errors (the session report plus the file rules with `files=`). Message: count + first error; the findings dialog lists up to 10 and selects the first node (T2). Warnings never block the preview.** · (b) preview anyway and let the child fail (worse messages, no node selection) |
| D10 | Export source | **(a) the saved file only. If dirty or untitled → `Save and export` / `Cancel` (Save As flow for untitled). If the file changed on disk (`FileStamp.changed`) → refused: save or reopen first. Output is byte-identical to `pyguibud-uic FILE -o OUT`.** · (b) export the in-memory model (the `.py` header names a `.ui` whose content differs, and the CLI cannot reproduce it) |
| D11 | Export dialog contents | **(a) Output file (entry + Browse…, default the remembered path, else `default_output()`); class name read-only (`Ui_<MainId>`, hint: rename the main window to change it); `[ ] Also write a translation template (.pot)` + path (default `<.ui dir>/locale/<domain or stem>.pot`); `[ ] Allow images and included files outside the .ui folder` (shown only when codegen reports such paths, listing them); `[ ] Run the module after export`; Export / Cancel.** · (b) also an editable class name (codegen API + CLI `--class`, breaks CLI identity) · (c) a plain Save dialog with no options |
| D12 | Overwriting | **(a) never overwrite a file that `pyguibud-uic` did not write (the marker check), and never a `.pot`/`.po` with translations. No override in the GUI: choose another name. Regenerating a generated file → silent replace.** · (b) a "Replace anyway" confirmation (= `--force`), with a `.bak` copy |
| D13 | Split | **(a) two halves, 15a "Preview" and 15b "Export", each with its own UAT** · (b) one session |
| D14 | Budget | **(a) ≈ 1,100 lines, caps 800 + 560, trims T1–T7 in order** · (b) raise the caps by 20 % instead of trimming |

**What "matches" means (for the UAT and the tests):** with D2 = a, the preview and `python out.py` match for the same saved file, in the document theme, in any of the 8 locales. These are excluded and shown as such:
- `en_XA`: the generated code treats it as an ordinary code (codegen §3.6 C5);
- a theme override (the export bakes `_THEME`);
- a component in its synthetic host;
- a dirty snapshot that includes external documents with their own catalogues (ADR-013 ➖).

Whenever one of these applies, the status bar adds: `This preview differs from the exported module: {reason}.`

## 2. Module layout
| File | New/changed | Half | Notes |
|---|---|---|---|
| `src/pyguibud/preview/__init__.py`, `__main__.py` | new | a | the child: argv, `run(args) -> int`, the stdin reader thread → `queue` → `host.schedule` |
| `src/pyguibud/preview/_host.py` | new | a | the `PreviewHost` protocol + `TtkbootstrapHost` (root, hidden-root path, `theme_use` with `install_legacy_themes`, `show_only(window)`, `transient("")`, `WM_DELETE_WINDOW` → quit, geometry) |
| `src/pyguibud/preview/_describe.py` | new | a | `describe(ui) -> dict`: a canonical widget tree (the `test_parity.py` fields + window title, `minsize`, `theme_use()`). Used by `--describe` and by the tests on the generated module |
| `src/pyguibud/designer/preview.py` | new, **pure** | a | `PreviewRequest`, `prepare_preview()`, `child_argv()`, `PreviewState` (state machine), `read_result()`, the refusal and difference texts |
| `src/pyguibud/designer/preview_tk.py` | new | a | `PreviewRunner`: `Popen`, `after()` polling, stdin writes, terminate/kill, deleting the private folder |
| `src/pyguibud/codegen/output.py` | new (moved from `uic.py`) | b | `check_output`, `replaceable`, `holds_translations`, `write_atomic`, `protected_ui_files`, `same_file`; the `M_*` msgids stay in `_errors.py` |
| `src/pyguibud/uic.py` | imports from `codegen.output` | b | no behaviour change |
| `src/pyguibud/designer/export.py` | new, **pure** (apart from stat/read) | b | `ExportRequest`, `export_plan()`, `run_export()` |
| `src/pyguibud/designer/dialogs/export.py` | new | b | `ExportDialog(ModalDialog)` |
| `designer/standard_actions.py`, `app.py`, `settings.py`, `icons/icons.json` | changed | a, b | §3 wiring; `Settings.preview_lang`, `Settings.exports` (path key → output, at most 50 entries); icons `preview`, `export` (ADR-012 pipeline) |

`PURE_MODULES` gains `preview` and `export`. The import-boundary test gains: importing `pyguibud.preview` loads no `pyguibud.designer*`, `pyguibud.cli`, `pyguibud.uic` or `pyguibud.codegen*`. Toolkits are loaded only inside `run()`.

## 3. Menus, shortcuts, toolbar (en-GB msgids through `N_()`/`_()`)
New top-level menu **`_Preview`** (between Document and View; the id `preview`):

| Action id | Label | Chord | Enabled when |
|---|---|---|---|
| `preview.run` | `_Preview` (toolbar icon `preview`) | **F5** | a document is open |
| `preview.close` | `_Close preview` | **Shift+F5** | a preview is running |
| `preview.language.*` | sub-menu `_Language`: `Document language`, the 8 autonyms, `Pseudo-locale (layout test)` (radio, `checked`) | — | always (applied live, or at the next start) |
| `preview.theme.*` | sub-menu `_Theme`: `Document theme` + the reported names (radio) | — | a preview is running |
| `preview.use_theme` | `_Use this theme in the document` | — | an override is active and the document is editable |
| `file.export` | `_Export Python code…` (toolbar icon `export`; in **File**, after Save as) | **Ctrl+E** | a document is open |

- F5 and Ctrl+E are free today (checked against `standard_actions.py`). The cheat sheet lists all of them.
- **Ctrl+E is application-wide, but Entry/Text class bindings run first.** Tk binds `<Control-e>` (end of line) on some platforms. With the focus in an inspector field, the field behaves as Tk does, the same way the editor fields handle Ctrl+Z/Y (`panels/editors.py:312`). The menu and the toolbar still reach Export. The implementer confirms the behaviour on win32 and documents it in the cheat sheet. If the field swallows the chord, that is accepted, not a bug.
- **Mnemonics** are checked by the existing all-locale collision test.
- Every action is keyboard-reachable. The export dialog has a full tab order, Enter = Export and Esc = Cancel.

## 4. Preview (15a)
### 4.1 `prepare_preview` (pure)
```python
@dataclass(frozen=True, slots=True)
class PreviewRequest:
    document: Document; path: Path | None; dirty: bool; read_only: bool
    window_id: str; lang: str | None; theme: str | None; backend: str = "ttkbootstrap"

@dataclass(frozen=True, slots=True)
class PreparedPreview:
    source: Path | None          # load this file directly (clean and saved), or None
    snapshot: bytes | None       # else write this to <private>/preview.ui
    localedir: Path | None       # <.ui dir>/locale for a snapshot of a saved document
    window_id: str; host_id: str | None
    differences: tuple[str, ...] # msgids of section 1 "matches" exclusions
    export_refusal: str | None   # §4.5

def prepare_preview(req: PreviewRequest, private: Path, findings: Sequence[Finding]) -> PreparedPreview | Refusal
```
1. **Errors (D9).** `findings` (the session report plus include and image rules with `DiskFiles`, as for the canvas resolver, cached) contain an error → `Refusal(M_ERRORS, count, first)`.
2. **Clean and saved, `FileStamp` unchanged (the disk holds what the canvas shows), and not a component window** → `source=path`, no snapshot.
3. **Otherwise** → `copy.deepcopy(document)`.
   - Apply `files.rebase_paths(copy, path.parent or None, private)` by executing its macro on the copy (never on the session stack).
   - For a component window, add a host dialog: id `preview_host`, suffixed `_2`, `_3`… if taken; a grid layout 1×1, weights 1; `<include src="#" component=ID>` at cell 0,0 with sticky `nsew`.
   - `dump_ui(copy)`; a `DumpError` → `Refusal(M_UNSAVEABLE)`.
4. **Untitled** with relative image or include paths: the file rules already produce errors, so this is a refusal at step 1, reworded: `Save the document first: its images or included files are given relative to a folder it does not have yet.`

The cost is ≤ 150 ms for 2,000 widgets on the main thread. It is measured, and a busy cursor is shown.

### 4.2 The child: `python -m pyguibud.preview`
`argv: [--ui-lang CODE] [--lang CODE] [--theme NAME] [--window ID] [--localedir DIR] [--backend NAME] [--geometry WxH+X+Y] [--describe] FILE`
- **`--ui-lang`** is the language of the child's own messages: the designer's current language, through `pyguibud.i18n`. **`--lang`** is the language of the document texts, passed to `load_ui`.
- **Steps:**
  1. `read_ui` only to collect the handler names (actions and events); no-op callables for them (D8).
  2. If the file has a main window: `load_ui(FILE, handlers, strict=False, lang=…, localedir=…, backend=…)`.
  3. Otherwise: the host creates a hidden root and applies the document theme, then `load_ui(..., master=root)`.
  4. `--window` names a dialog (or the host): `host.show_only(id)`, which withdraws the main window, shows the dialog, and ends the preview when the dialog closes.
- Runtime log records (logger `pyguibud_runtime`) are collected.
- **`ready.json`** (written once the windows are mapped): `{"themes": [...], "theme": "...", "warnings": [{"code","message"} ≤ 20], "pid": N}`.
- **`result.json`** (at exit): `{"code": "ok"|UiError.code|"crash", "message": str ≤ 2,000 chars, "geometry": "WxH+X+Y"}`.
- **Exit codes:** 0 = closed by the user or `quit`; 1 = a `UiError` (with the translated message); 2 = usage; anything else = a crash (the designer shows the last 20 lines, ≤ 8 KiB, of `stderr.txt` under Details).
- **stdin:** one command per line, ≤ 256 bytes, unknown lines ignored: `theme NAME` · `lang CODE|-` · `raise` · `quit`. **EOF → quit.**
- **`--describe`** builds the interface, prints `describe(ui)` as JSON to stdout, destroys it and exits 0 (tests only; not listed in `--help`).

### 4.3 Runner and state (`preview_tk.PreviewRunner`, `preview.PreviewState`)
- **States:** `idle → starting → running → stopping → idle`, with a single `pending` flag.
  - F5 while `starting` or `running` → `quit`, then a restart once the old process ends. **Ten F5 presses = one restart.**
  - Shift+F5 → `quit`, then `terminate()` after 2 s and `kill()` after 4 s.
- **Launch:** `subprocess.Popen([sys.executable, "-m", "pyguibud.preview", ...], cwd=private, stdin=PIPE, stdout=DEVNULL (or a file with --describe), stderr=open(private/"stderr.txt","wb"), creationflags=CREATE_NO_WINDOW on Windows, close_fds=True)`.
  - Never `shell=True`. The environment is inherited, with `PYTHONIOENCODING=utf-8` added.
- **Polling:** `after(200)` checks `ready.json` and `poll()`.
  - No `ready.json` within 20 s → terminate: `The preview did not start within 20 seconds.`
- **Ending:**
  - At exit, `result.json` is read (≤ 64 KiB; malformed → treated as a crash) and reported (§8).
  - The private folder is then deleted.
  - At start-up, folders `pyguibud-preview-*` in the temp dir older than 24 h whose `ready.json` pid is not alive are removed.
- **Designer close or Quit:** close stdin, terminate if needed (no wait longer than 1 s on the main thread), delete the folder.
  - If the document is closed or another file is opened, the preview is closed too.
- **Live switches:**
  - A Language change while running → `lang CODE`.
  - A Theme override → `theme NAME`.
  - Both are remembered for the next F5.

### 4.4 Status-bar feedback
`Starting the preview…` · `Preview of '{window}' open.` (+ the D8 note once per run, + `This preview differs from the exported module: {reason}.` when §1 exclusions apply) · `Preview closed.` · `No translation catalogue for {lang} in {folder}: the texts are shown in the document language.` (from the `catalogue_missing` warning) · the refusal and failure texts of §8.

### 4.5 Export-refusal hint (T3)
After a preview starts, if export would refuse the same document, the status bar adds `Export will refuse this document: {reason}.` This covers:
- read-only (newer MINOR);
- only components;
- outside paths (the warnings `validate.absolute_path` and `validate.path_escapes`);
- dirty (`Save it first.`).

## 5. Window selection details (D5)
| Canvas tab | Child shows | Closing it |
|---|---|---|
| main | everything `load_ui` shows (main mapped, dialogs withdrawn) | closing the main ends the preview |
| dialog, file has a main | the dialog; main withdrawn; `transient("")` so it is not hidden with the root | ends the preview |
| dialog, no main | hidden root (theme applied first), the dialog | ends the preview |
| component | `preview_host` dialog with the include, titled with the component id (snapshot only; a §1 exclusion) | ends the preview |

## 6. Export (15b)
### 6.1 `codegen/output.py` (moved, public)
`same_file(a, b)`, `protected_ui_files(path, result) -> list[str]`, `check_output(output, protected, written) -> str | None` (`M_SAME_FILE`/`M_ALREADY_WRITTEN`/`M_NOT_REGULAR`), `replaceable(output, *, extracting) -> bool`, `holds_translations(output) -> bool`, `write_atomic(output, text)`. The bodies are moved verbatim from `uic.py`. `uic.py` keeps thin private aliases if tests reference them.

### 6.2 `export_plan` and `run_export` (pure apart from file stat/read)
```python
@dataclass(frozen=True, slots=True)
class ExportRequest:
    ui_path: Path; output: Path; pot: Path | None; allow_outside: bool; run_after: bool

def export_plan(session_state, req: ExportRequest) -> ExportPlan | Refusal   # all checks, no writes
def run_export(plan: ExportPlan) -> ExportOutcome                             # writes .py then .pot
```
Checks run in this order; the first failure is the reason shown in the dialog. The Export button stays enabled, and pressing it re-checks.
1. **No document, dirty or untitled** → the D10 prompt. **Read-only (newer MINOR)** → `M_READ_ONLY`. **The file changed on disk** → `The file changed on disk since it was opened. Save or reopen it first.`
2. **Output path:**
   - empty → `Choose a file name.`
   - an existing folder, or a name ending in a separator → `'{output}' is a folder. Choose a file name.`
   - a network or device path (`is_network_or_device_path`) → R82 text
   - no suffix → `.py` is appended
   - any other suffix → `The file name must end in .py.`
3. **Module name:** a stem that is a stdlib module (`sys.stdlib_module_names`), or `ttkbootstrap`, `PIL` or `pyguibud*`, would shadow an import of the generated module → `A file named '{name}' would hide the Python module of the same name. Choose another name.`
   - A stem that is not an identifier is a warning only: `'{name}' cannot be imported with import; it can still be run.`
4. `check_output(output, protected_ui_files(...), [])` → the moved refusals, so the output is never the `.ui` or any file it includes, a folder or a device. Then `codegen.generate_python(read_ui(ui_path), ui_path, output=..., allow_outside=req.allow_outside)` → a `CodegenError` gives its message plus up to 10 findings. Then `module.sources` (`M_SAME_FILE`). Then `replaceable(output)` → `M_NOT_GENERATED` (D12: no override).
5. **The folder is not writable** (`os.access` as a hint; the real test is the write) → `The folder '{folder}' cannot be written to.`
6. **`.pot`:** the same output checks with `extracting=True`, plus `holds_translations` → `M_TRANSLATIONS`. It must not equal the `.py`. Its folder is created if missing (`locale/` only, one level).
- **Writes:** `write_atomic(.py)`, then `write_atomic(.pot)`. If the `.pot` fails, the `.py` stays and the message says which one failed.
- On success, the designer remembers `exports[path_key(ui)] = output` (T6) and posts `Exported {output}.` (+ ` and {pot}`).
- **Huge documents:** generation runs on the main thread with a busy cursor. It is ≤ 1.5 s for 10,000 widgets (the validator limits) and is measured. A thread is not used, because `generate_python` is not cancellable and Tk is single-threaded.

### 6.3 Dialog (`ExportDialog`)
- **Rows:**
  - Output file [entry][Browse…] (`asksaveasfilename`, filter "Python files (*.py)");
  - Class name: `Ui_Main` (read-only label + hint);
  - [ ] Also write a translation template (.pot): [entry][Browse…], enabled only when ticked;
  - [ ] Allow images and included files outside the .ui folder, visible only when the document has such paths, with the paths listed in a read-only text (≤ 5 lines, then `… and {count} more`);
  - [ ] Run the module after export (T7);
  - a message area (the reason or warnings, `wraplength`);
  - [Export] [Cancel].
- **Run after export:** the same runner class as the preview (a second instance, also single) runs `[sys.executable, OUTPUT]` with `--lang` = the preview language, except for `en_XA` and "Document language": then no `--lang`, and the status bar notes `The exported module cannot show the pseudo-locale.`
  - `cwd` = the output folder (as a user would run it).
  - It runs only if the bytes on disk equal the text just written (a hash check right before the launch).
- The dialog is modal (the existing `ModalDialog`). Ctrl+E while it is open does nothing. Its geometry follows `fit_geometry`.

### 6.4 As built (15b, 2026-10-12)
QA checks against this behaviour where it differs from 6.2/6.3:
1. `export_plan(source, req)`: `ExportSource(path, dirty, stamp)` + `ExportRequest(output: str, pot: str | None, allow_outside, run_after)`; the paths are the typed text (so empty names and trailing separators can be judged), relative names resolve against the `.ui` folder.
2. The string-only network/device test (R82) runs before any disk access, so `\\?\`-prefixed outputs get the R82 text, not `M_SAME_FILE`; `hello.ui` as output gets `The file name must end in .py.`; a hard-link alias of the `.ui` or of an included `.ui` gets `M_SAME_FILE`.
3. Refusals never mention CLI options: the designer has its own texts for "outside the folder" (tick the check box), "not written by PyGUIbud", "holds translations" and "template = module" (E3, E7, E8, E11). `M_SAME_FILE`, `M_NOT_REGULAR`, `M_READ_ONLY`, `M_WRITE_FAILED` and the other codegen errors are shown as the CLI words them (no option names in them).
4. `.pot` checks: "holds translations" runs before "not written by PyGUIbud", so a translated `de.po` gets the translations reason.
5. Status texts are two full msgids, `Exported {output}.` and `Exported {output} and {pot}.`, not a joined fragment.
6. The dialog sizes to its content and is centred and kept on the desktop by `ModalDialog` (not `fit_geometry`); no elision or tooltip, en_XA and de_DE fit (screenshots).
7. The class name is read with codegen's private `_class_name` (codegen unchanged). Export sits in the toolbar group of Preview.
8. Enter on a focused Cancel or Browse… button presses that button; anywhere else Enter exports. Ctrl+E is not swallowed by a text field on win32 (noted in the cheat sheet). "Run after export" uses `PreviewRunner.start(..., cwd=OUT folder, wait_ready=False)`; only its private stderr folder is deleted, and quitting the designer ends the run.

## 7. Step 16 hook (backend choice later, not implemented now)
- The child already takes `--backend NAME` and selects a `PreviewHost` from a dict `{"ttkbootstrap": TtkbootstrapHost}`. Step 16 adds `tkinter` and `pyside6` hosts (a Qt `QTimer` for `schedule`). Hosts without themes report `"themes": []`, and the Theme menu greys out.
- `PreviewRequest.backend` and `Settings.preview_backend` exist from 15a, fixed to `"ttkbootstrap"`. Step 16 adds the Preview ▸ Toolkit sub-menu from the `pyguibud.backends` entry points. A missing toolkit → the child's `runtime.backend_unavailable` message.
- Export stays ttkbootstrap. The dialog shows no toolkit choice, because codegen has one target (ADR-008).

## 8. Error and abuse cases (idiot-proof; each is blocked with a translated reason, nothing is lost)
| # | Abuse | Required behaviour |
|---|---|---|
| P1 | F5 with document errors. The command guards (ADR-006) block new model errors at edit time, so the reachable ones are **file-rule** errors: an image or included file renamed on disk (R49/R75), or a hand-broken file opened from a fixture | refused (D9): the status bar names the count and the first error; no findings dialog and no node selection (T2 applied in 15a) |
| P2 | F5 ×20 quickly; F5 while starting | one child at a time; one restart |
| P3 | Close the designer, or kill it from Task Manager, while a preview runs | the child gets stdin EOF and quits; the private folder is removed now or at the next start (24 h rule) |
| P4 | The preview hangs (the child is busy) | Shift+F5 terminates, then kills; the designer never blocks for more than 1 s |
| P5 | The child crashes (a plugin `SystemExit`, a segfault) | `The preview stopped unexpectedly (exit code {code}).` + Details (the stderr tail); the designer is unaffected |
| P6 | No display (SSH or CI) | the child's `runtime.no_display` text |
| P7 | Untitled document with relative images | the reworded save-first refusal (§4.1 step 4) |
| P8 | Read-only (newer MINOR) document | the preview of a clean saved main window or dialog works; a component or a file changed on disk needs a snapshot, which `dump_ui` refuses for a newer MINOR (shown as the reason). Export is refused (`M_READ_ONLY`, 15b); no hint at preview time (T3 applied in 15a) |
| P9 | Document with only components | the preview hosts the component; export → `codegen.nothing_to_generate` |
| P10 | 10,000 widgets | the preview starts (≤ 5 s, marked `slow`); the designer stays responsive (`after` polling) |
| P11 | Temp folder not writable or full | `The preview needs a temporary folder: {reason}.` |
| P12 | `sys.executable` missing (frozen build) | `The preview cannot start: no Python interpreter was found.` (frozen builds are out of scope) |
| E1 | Export to the `.ui` itself, or to an included `.ui` (by alias, `\\?\` prefix or hard link) | `M_SAME_FILE` |
| E2 | Export to a folder, `CON`, `nul.py`, `\\server\share\x.py` | folder / device / R82 refusal; never opened |
| E3 | Export over a hand-written `app.py` (or `.pot` over a file PyGUIbud did not write) | the designer's own wording, `'{output}' was not written by PyGUIbud, so it is not replaced. Choose another name.` (never mentions `--force`); no override (D12) |
| E4 | Export as `tkinter.py`, `gettext.py`, `ttkbootstrap.py` | the shadowing refusal (§6.2 step 3) |
| E5 | Export as `form.txt` | `The file name must end in .py.` |
| E6 | Read-only folder, or a read-only existing generated file | the OS reason (`M_WRITE_FAILED`); no temporary file left behind |
| E7 | `.pot` path = an existing translated `de.po` | the designer's own wording, `'{output}' holds translations, so it is not replaced. Choose another name.` |
| E8 | `.pot` path = the `.py` path | `'{output}' is the Python file of this export. Choose another name for the template.` (the CLI's `M_ALREADY_WRITTEN` mentions `-o`) |
| E9 | Dirty document → Export | `Save and export` / `Cancel`; a failed save → no export |
| E10 | The `.ui` edited in another program after opening | the changed-on-disk refusal |
| E11 | Images outside the folder | the checkbox appears with the paths; unticked → `M_OUTSIDE` |
| E12 | Run after export, then F5 | two separate processes (preview + run); each single |
| E13 | `en_XA` and `de_DE` designer UI | the dialog rows and the status texts fit (elided with a tooltip) |

## 9. Test plan (`tests/preview/`, `tests/designer/`, `tests/codegen/`)
**Pure (fast):**
- `prepare_preview`:
  - clean → `source` only;
  - dirty → the snapshot round-trips through `read_ui`, rebased paths resolve to the same files, `localedir` is set;
  - component → host id is unique, and the snapshot validates;
  - errors → refusal;
  - untitled with relative paths → the save-first refusal;
  - the session stack and document are **unchanged** (identity + `dump_ui` bytes before and after).
- `PreviewState`: every transition; F5 storms; a quit timeout → terminate → kill.
- `child_argv`: no shell metacharacter handling is needed (argv list); paths with spaces, non-ASCII and leading `-` are passed after `--`.
- `read_result`: malformed, oversized and missing → crash text.
- `export_plan`: every row of E1–E11 (with `tmp_path`, hard links where the OS allows them, `\\?\` on Windows).
- Shadowing names; `.py` suffix logic; `exports` capped at 50.

**Child (subprocess, `gui`):**
- `--describe` on `examples/hello.ui` gives JSON;
- `quit` on stdin → exit 0 and `result.json` ok;
- stdin closed → exit 0 within 2 s;
- an invalid file → exit 1 with `runtime.invalid_document`;
- `--window` dialog → only the dialog is mapped;
- dialogs-only file → the document theme is applied (`theme_use() == meta.theme`, no `theme_ignored` warning);
- `lang de_DE` over stdin → the texts change.

**Parity — the "matches" proof (`gui`, subprocess):** for each of `tests/codegen/data/{hello,includes,dialogs,events,images}.ui` and `examples/hello.ui`, in `None` and `de_DE`:
- `python -m pyguibud.preview --describe FILE` equals a harness that runs `generate_python` → a `tmp_path` module → `describe(ui)`. The harness follows the `_preview` path exactly:
  - with a main window: `Ui_X().setup_ui(None, H, strict=False, lang=…)`;
  - without one: the `_preview_dialog` path (a hidden `App` root, `_apply_theme()` first, then `setup_ui(root, H, …)`).
- **`H` is the same no-op handler mapping the child passes (D8).** Both `_tk.py` (`_events`, action commands) and `_support.py` (`_action`, `self._fns.get`) bind commands, keys and menu commands **only for resolved handlers**. With `handlers=None` on one side, the `bind()` lists would differ. Bindings are invisible, so `python out.py` (which passes `None`) still looks identical to the preview.
- The comparison covers: window class, title and `minsize`; `theme_use()`; the `test_parity.py` per-id fields; menus; tabs.
- Plus the snapshot path: the same document, dirty, gives the same describe as clean, apart from the `localedir` note.

**Export:**
- the dialog's `run_export` bytes == `pyguibud.uic.main([ui, "-o", out])` bytes;
- `.pot` == `--extract -o` bytes;
- regeneration replaces silently;
- E3 leaves the file untouched (mtime + bytes);
- a write failure leaves no `.pyguibud-*.tmp`.

**Boundary:** importing `pyguibud.preview` loads none of the forbidden modules (ADR-013).

**Tk designer (`gui`, shared root):**
- F5/Shift+F5/Ctrl+E bindings and enabled states;
- the dialog's tab order, Enter and Esc;
- the checkbox for outside paths appears only when needed;
- a fake runner (injected) receives the right argv and stdin lines for language and theme switches;
- Quit with a fake running child → terminate is called and the folder is deleted.

**Leaks:** 20 preview start/stop cycles with a fake runner → no `after` ids left, and no temp folders.

**Budgets:** prepare ≤ 150 ms for 2,000 widgets; export ≤ 1.5 s for 10,000 widgets (`slow`); designer Tk tests added ≤ 6 s per half.

## 10. i18n
- **Gates:** every string through `_()`/`N_()`/`ngettext` with named placeholders, all 8 locales and the `en_XA` truncation check. The child translates its own messages with `--ui-lang`.
- **New msgids:** the §3 labels and the §4.4, §6 and §8 texts, plus `Export Python code`, `Output file`, `Class name`, `Rename the main window to change the class name.`, `Also write a translation template (.pot)`, `Allow images and included files outside the .ui folder`, `Run the module after export`, `Export`, `Save and export`, `Document language`, `Document theme`, `Python files`, `Translation templates`.
- **Plurals:** `The document has {count} error. Fix it to preview.` / `… {count} errors. Fix them to preview.`; `… and {count} more`.

## 11. UAT (for the user)
**15a "Preview"** (`uv run pyguibud examples/hello.ui`). As built, trims T1–T4 applied (see §0):
1. Press F5: a separate window opens in the document's theme (flatly), not the designer theme. Click a button: nothing happens, and the status bar says handlers are not connected.
2. Preview ▸ Language ▸ Deutsch: the preview switches to German live, without restarting.
3. Preview ▸ Theme (filled once a preview has reported its themes) ▸ another theme: the preview restarts with that theme (T4: no live repaint), and the status bar says the preview differs from the export. Use this theme in the document → Ctrl+Z undoes it, and the "differs" note comes back. Opening another document forgets the override.
4. Change a label in the designer (do not save), then press F5: the preview restarts showing the change. The window position is not kept (T1).
5. Add a dialog first if the file has none (Document ▸ Add dialog). Switch to the dialog tab and press F5: only the dialog shows. Close it: the preview ends.
6. Open `examples/preview/with_image.ui` (provided by the step) and rename its `logo.png` on disk, then press F5. It is refused; the status bar shows the count and the "image missing" reason (T2: no node selection). Rename the file back. (The designer already refuses in-model errors at edit time, so file errors are what F5 can meet.)
7. Press F5 ten times quickly: one preview. Press Shift+F5: it closes. With a preview open, close the designer: the preview disappears too.

**15b "Export"**: first copy `examples/hello.ui` and `examples/locale/` into a scratch folder, e.g. `%TEMP%\uat15`. Do every step there: the committed `examples/hello_ui.py` is checked by `test_examples.py` and must not change.
1. Open the copy, make a change, then press Ctrl+E: "Save and export". Save; the dialog proposes `hello_ui.py` next to the copy, and the class is `Ui_Main`.
2. Tick "Run the module after export" and press Export. Compare it side by side with F5 (same language and theme): **identical**. Repeat both in German.
3. Export again over the same file: replaced silently. Copy `examples/run_hello.py` into the scratch folder and try to export onto it: refused (not generated by PyGUIbud). Try `hello.ui`: refused. Try `tkinter.py`: refused. Try a folder: refused.
4. Tick the `.pot` option: `locale/hello.pot` is written in the scratch folder. Point it at a `.po` with translations: refused.
5. Run `uv run pyguibud-uic %TEMP%\uat15\hello.ui -o %TEMP%\uat15\x.py` and compare it with the dialog's file: the same bytes (`fc /b`). Delete the scratch folder afterwards.
6. Repeat 1 and 3 with `--lang en_XA`: no clipped texts in the dialog.

## 12. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | Child start-up time feels slow (≈ 1 s) | "Starting the preview…" text; the reused position; live language and theme switches avoid restarts |
| R2 | `load_ui` and the generated module drift | the `--describe` parity tests run in CI on every fixture and locale |
| R3 | ttkbootstrap's theme listing API differs between 2.x versions | the child reports `theme_names()` after `install_legacy_themes`; nothing is hard-coded |
| R4 | Antivirus or Windows console flashes on `Popen` | `CREATE_NO_WINDOW`; `pythonw` is not used (stderr must work) |
| R5 | Snapshot `localedir` is wrong for external includes in other folders | documented exclusion; clean, saved documents avoid it (D3) |
| R6 | Plugins (Step 17) run in the child too | the same trust model as the designer (entry points); a crash is P5 |

## 13. Open questions — resolved by the user, 2026-10-11
1. D7: **yes**, 15a includes "Use this theme in the document" (undoable).
2. D12: **no override in the GUI**; the CLI keeps `--force`.
3. D5: **yes**, a component is previewed inside a synthetic host dialog.

## 14. Follow-ups after acceptance (applied 2026-10-11)
- ADR-013 → Accepted. `FEATURES.md` M10/S3 → "Step 15".
- `DEVELOPMENT_PLAN.md` row 15 → halves 15a and 15b with these UATs.
- `designer-shell.md` §1 table: point row 15 at this spec.
