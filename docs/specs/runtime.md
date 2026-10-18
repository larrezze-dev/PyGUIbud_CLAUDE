# Spec — Step 10: runtime loader + ttkbootstrap backend

- **Status:** Proposed (architect, 2026-10-06) · **ADRs:** 001–006, **007** (packaging boundary)
- **UAT:** `uv run python examples/run_hello.py` opens a real window, also with `--lang de_DE`.
- **Reference toolkit:** ttkbootstrap **2.2.x** (installed: 2.2.3). Its API differs from 1.x: `App` (alias `Window`), `ScrolledFrame(auto_hide=)`, `LabelFrame` = ttk `Labelframe`, a single live root enforced by `RuntimeError`, and pre-2.0 theme names only after `install_legacy_themes()`. See decision U4.

## 0. Scope and budget
Target: **≤ 1,500 lines of production code** in `src/` (tests, `examples/` and the 10-line `uic.py` change excluded; the `src/` rows below add up to 1,500). The **must-ship path is `examples/hello.ui`**: menubar with mnemonics and a shortcut, statusbar, Notebook pages with `context`, grid and pack, `bind`, the `activate` and `command` events, `tb:bootstyle`, a legacy theme name, and `de_DE` plus a live language switch.

| Module | New/changed | Budget |
|---|---|---|
| `src/pyguibud/core/keys.py` | new: shortcut/key grammar, mnemonic split (pure) | 110 |
| `src/pyguibud/core/files.py` | new: `DiskFiles`, `ImageProbe`, limits (I/O, toolkit-free) | 150 |
| `src/pyguibud/core/validate.py` | +R49–R53, R69–R78; `files=` parameter | 230 |
| `src/pyguibud/core/widgets.py` | Action: drop the `shortcut` `PropertyDef` (§9.4) | −1 |
| `src/pyguibud_runtime/__init__.py`, `_load.py`, `_ui.py`, `errors.py` | `load_ui`, `UiScope`/`LoadedUi`, `UiError`, pre-Tk pipeline, translators | 380 |
| `src/pyguibud/backends/__init__.py`, `base.py` | `Backend`/`Session` protocols, `BuildPlan` | 70 |
| `src/pyguibud/backends/_tk.py` | shared Tk builder (reused by the Step 16 tkinter backend) | 470 |
| `src/pyguibud/backends/ttkbootstrap.py` | class table, theme, `bootstyle` | 90 |
| `src/pyguibud/uic.py` | `--check` passes `files=` (decision U3) | 10 |
| `examples/run_hello.py` + `examples/locale/de_DE/LC_MESSAGES/hello.{po,mo}` | UAT | 60 |

**Trim order if over budget:** (1) the dialog button bar and `show()` modality (§8.5): keep the `buttons` grammar rule, and render the bar in Step 14; (2) button Alt-mnemonics (§6.2): keep the underline display only.

## 1. Dependency rules (ADR-007)
- `pyguibud_runtime` imports `pyguibud.core`, `pyguibud.i18n` and `pyguibud.backends.base` only. It **never** imports the designer, `pyguibud.cli`, `pyguibud.uic` or `pyguibud.codegen`.
- `tkinter` and `ttkbootstrap` are imported **only inside** `Backend.prepare()`/`build()` (function-local imports; `TYPE_CHECKING` for types). Importing `pyguibud_runtime` or `pyguibud.backends.ttkbootstrap` must not put `tkinter` in `sys.modules`.
- `pyguibud.core` stays stdlib-only and toolkit-free (unchanged). Errors raised to the caller are `pyguibud_runtime.UiError` (§2.4); backends never raise it themselves, and the runtime wraps everything they raise.

## 2. Public API
### 2.1 `load_ui`
```python
def load_ui(
    path: str | os.PathLike[str],
    handlers: object | Mapping[str, Callable[[], object]] | None = None,
    *,
    strict: bool = True,
    backend: str = "ttkbootstrap",
    master: object | None = None,          # a live Tk widget; None → load_ui creates the root
    lang: str | None = None,               # e.g. "de_DE"; None → gettext environment lookup
    localedir: str | os.PathLike[str] | None = None,   # overrides <.ui dir>/locale for every document
    translator: Translator | None = None,  # overrides lang/localedir for every document
) -> LoadedUi

class Translator(Protocol):                # gettext.NullTranslations fits
    def gettext(self, message: str, /) -> str: ...
    def pgettext(self, context: str, message: str, /) -> str: ...
```
- **API misuse** raises a plain `TypeError` or `ValueError` with an English message, as `validate(limit=…)` does. Examples: `path` is not str/PathLike; `strict` is not a bool; `backend` is not a str; `lang` does not match `^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})*$`. Rejecting `/`, `\` and `..` blocks path traversal through `languages=`.
- **Everything else** (the file, the environment, the handlers) raises `UiError`.
- Main thread only (Tk rule); this is documented, not checked.

### 2.2 Returned object (pinned: Step 11 codegen reproduces it exactly)
```python
class UiScope:                             # one per document instance: the top document, and each <include>
    vars: types.SimpleNamespace            # ui.vars.<variable id> → tk Variable
    widgets: Mapping[str, object]          # read-only (MappingProxyType): every id-addressable object below
    windows: Mapping[str, object]          # instantiated windows (main + dialogs); {} in an include scope
    # + one attribute per id, see the table

class LoadedUi(UiScope):                   # returned by load_ui; codegen's Ui_<Name> after setup_ui()
    def retranslate(self, lang: str | None = None, *, translator: Translator | None = None) -> None
    def show(self, window_id: str) -> str | None
    def run(self) -> None
    def destroy(self) -> None
```

| Node with id | `ui.<id>` (ttkbootstrap backend) |
|---|---|
| main window | `ttkbootstrap.App`, the root (when `master is None`), or `ttkbootstrap.Toplevel(master)` |
| dialog window | `ttkbootstrap.Toplevel`, created **withdrawn**, `transient` to the main window (or master) |
| component window | not instantiated on its own. In an include scope, `scope.<component id>` is the include's frame |
| widget | the toolkit widget (§8.4). `ScrolledFrame` → the instance (its content frame) |
| menu | its `ttkbootstrap.Menu` dropdown |
| action | `int`: the entry index in its parent menu (`ui.mnu_file.entryconfigure(ui.act_quit, state="disabled")`) |
| statusbar | the `ttk.Label` that shows the text |
| include | a nested `UiScope` (§7.2) |
| variable | not an attribute: `ui.vars.<id>` |
| image resource | not exposed (references are held privately) |

- `retranslate(lang=None, translator=None)`:
  - With no arguments, it re-applies the current translators (for example after the catalogues were recompiled).
  - With `lang`, it rebuilds them for the new language; with `translator`, it uses that object.
  - It re-applies **every translatable text from the `.ui`**, including window titles, menu labels, page texts, the statusbar and dialog buttons, and redoes the mnemonics (§6). Text the application set itself on those slots is overwritten; this is documented.
  - **All-or-nothing** (QA-10-11): every text is computed before the first one is set. A translator returning anything but `str` raises `TypeError`; no text changes and the previous translators (language, `translator=`) are restored. The `translator=` and `lang` arguments are checked before anything changes.
- `show(window_id)`:
  - Deiconifies the main window or a dialog. For a dialog with `modal="true"`, it grabs and waits (`wait_variable`) until a button-bar button or the window-manager close, then returns the button token (`"ok"`, …), or `None` for a window-manager close.
  - Non-modal: returns `None` at once.
  - An unknown id or a component id raises `UiError("runtime.unknown_window")`.
- `run()` = `mainloop()` of the root. It is meant for the case where `load_ui` created the root.
- `destroy()` is idempotent. It destroys every toplevel that `load_ui` created, and the root if `load_ui` created it (`App.destroy` also resets the ttkbootstrap `Style` singleton). After `destroy()`, `retranslate`, `show` and `run` raise `UiError("runtime.destroyed")`.
- **Liveness** (QA-10-09): the same `runtime.destroyed` is raised when the interface was destroyed from outside, i.e. the user closed the main window with its close button (a `Toplevel` under `master=` is destroyed by the window manager) or the application destroyed `master` or any main/dialog window of the interface itself (a session is whole or dead: its slots span every window). `LoadedUi` asks `Session.alive()` (§10.1) first; when it is false, what is left of the session (e.g. the dialogs) is destroyed, then the error is raised. Never a raw `TclError`.
- Private state uses `_`-prefixed names only. Ids can never start with `_`, so they cannot clash.

### 2.3 Reserved ids (R69, enforced from Step 10: decision U2)
`RESERVED_IDS = frozenset({"vars", "widgets", "windows", "setup_ui", "retranslate", "show", "run", "destroy"})`, which is exactly the non-id members above plus codegen's `setup_ui` (ADR-003). Defined in `core/validate.py` and used by Step 11 unchanged. Adding a public member to `UiScope`/`LoadedUi` later is a **breaking change** that needs an ADR, because it makes existing ids invalid.

### 2.4 `UiError(PyGUIbudError)` (`pyguibud_runtime/errors.py`)
- Extra fields: `path: str`, `findings: tuple[Finding, ...] = ()`, `names: tuple[str, ...] = ()`.
- `__str__` = the message, then up to 20 `str(finding)` lines, then the `NP_("… and {count} more problem.", "… and {count} more problems.")` tail. Messages are in the **pyguibud** catalogue: developer-facing and lazily translated, like the core errors.

| Code | When | msgid (en-GB) |
|---|---|---|
| `runtime.unreadable` | `read_ui` failed (cause: `XmlIoError`) | "The .ui file '{path}' cannot be loaded: {reason}" |
| `runtime.invalid_document` | the validator found errors (all files) | `NP_` "{count} error prevents loading '{path}'." / "{count} errors prevent loading '{path}'." |
| `runtime.no_main_window` | no `main` window and `master is None` | "'{path}' has no main window; pass master= to load its dialogs." |
| `runtime.nothing_to_load` | only component windows | "'{path}' contains only components; include them from another .ui file." |
| `runtime.missing_handlers` | strict, at least one name unresolved | `NP_` "{count} handler is missing or not callable on {target}: {names}." / "{count} handlers are missing or not callable on {target}: {names}." |
| `runtime.backend_unavailable` | unknown backend, failed import, bad `master` | "The backend '{name}' is not available: {reason}" |
| `runtime.root_exists` | `master is None` but a live Tk root exists | "A Tk root window already exists; pass it as master= to load another .ui file into it." |
| `runtime.no_display` | `TclError` creating the root | "No display is available, so no window can be opened: {reason}" |
| `runtime.build_failed` | any exception during the build (cause chained) | "Building the interface from '{path}' failed: {reason}" |
| `runtime.unknown_window` | `show()` with a bad id | "'{id}' is not a main or dialog window of this interface." |
| `runtime.destroyed` | a method called after `destroy()` | "This interface has been destroyed." |

**Logged, not raised.** Logger `pyguibud_runtime`, level WARNING, message = `format_message(msgid, params)`:
- every validator **warning**;
- `runtime.handler_missing` (non-strict);
- `runtime.catalogue_missing`;
- `runtime.unknown_theme`;
- `runtime.theme_ignored` (master given);
- `runtime.extension_fallback` (once per class);
- `runtime.bootstyle_ignored`;
- `runtime.mnemonic_conflict`;
- `runtime.shortcut_duplicate`;
- `runtime.text_clipped` (once per text slot, also across `retranslate`; §6.1): "The text of '{id}' has {length} characters; only the first {limit} are shown."

## 3. Load pipeline
**Pre-Tk phase: no Tk object exists, and any failure raises before one does.**

| # | Step | Failure |
|---|---|---|
| P1 | Check the arguments (§2.1) | `TypeError`/`ValueError` |
| P2 | `result = read_ui(path)` | `runtime.unreadable` from the `XmlIoError` |
| P3 | `files = DiskFiles(path, result)` (§9.1); `report = validate(result.document, default_registry(), source=result.source, positions=result.positions, files=files)`. Including the includes and images of every file. | errors → `runtime.invalid_document` (with `findings`); log the warnings |
| P4 | Window check: main present, or `master` given with ≥ 1 dialog | `runtime.no_main_window` / `runtime.nothing_to_load` |
| P5 | **Instance plan**: expand the includes from `files`' cache (no re-read, so no time-of-check/time-of-use gap; bounded by R53) | — |
| P6 | **Handlers**: collect the unique names of every `<event>` and `Action.handler` across the plan, then resolve each (§4.1) | strict → one `runtime.missing_handlers` listing **all** names, sorted; non-strict → log each, leave it unbound |
| P7 | **Translators** per document (§6.1); a missing or corrupt `.mo` → log, identity | — |
| P8 | Resolve the backend (§10.2): `cls = registry.load_backend(name)` (built-in safety net for `"ttkbootstrap"`); `backend = cls(); backend.prepare(master)` imports the toolkit and checks `master` | `runtime.backend_unavailable` |
| P9 | `master is None` and a live root exists (`Style.get_instance()` whose master `winfo_exists()`, or `tkinter._default_root`) | `runtime.root_exists` |

**Build phase:** `session = backend.build(plan, master)`.
- `build` records every toplevel it creates. On **any** exception, it destroys them (and the root, if it created one) **before** the runtime raises `runtime.build_failed` (`TclError` on root creation → `runtime.no_display`).
- **Invariant, tested: after a failed `load_ui` there is no new Tk root, no new toplevel and no `Style` singleton.**

Build order:
1. Create the root, or use the master's toplevel. The main window stays **withdrawn** during the build.
2. Apply the theme (§8.2).
3. Create the variables with their **defaults set before any trace** (§5).
4. Create one `PhotoImage(master=root, file=str(abs_path))` per `(document, image id)`.
5. Build each window: body frame, menubar, statusbar, dialog button bar (§8.1).
6. Build the widget tree pre-order (§8.3–8.4).
7. Apply the texts (§6).
8. Bind the events and shortcuts (§4, §6.3).
9. Attach the ids to the scopes.
10. **Arm the virtual-event `select` wrappers** (`<<NotebookTabChanged>>`, `<<ComboboxSelected>>`, `<<ListboxSelect>>`, `<<TreeviewSelect>>`) with `root.after_idle(arm)`. Until then they are no-ops, so events queued during the build (for example the first `Notebook.add`) never reach a handler.
    - Every other wrapper (`command`, traces, `key:`, focus, `activate`, shortcuts, mnemonics) is live as soon as `load_ui` returns. `ui.btn_greet.invoke()` works immediately.
    - Nothing else can fire during the build: commands fire only when invoked, and traces are attached after the defaults are set.
11. Deiconify the main window.

## 4. Handlers and events
### 4.1 Resolution and security
- `handlers` is a `Mapping` → `handlers.get(name)`. Any other object → `getattr(handlers, name, None)`.
- An `Exception` raised by the lookup (for example a raising property) counts as unresolved. The value must be `callable()`. `handlers=None` with any handler name → all unresolved.
- Names are already identifiers (`_ID_RE`; they cannot start with `_`, so no dunder access) and validated (P3).
- **Tcl-injection rule:** no string from a `.ui` ever reaches Tk as:
  - a script-valued option (`command`, `*command`, `validatecommand`): only Python callables are passed;
  - a Tcl variable name (never `name=` on a Variable);
  - a widget path (never `name=` on a widget; Tk auto-names, and ids may start with an upper-case letter, which Tk paths forbid);
  - a bind sequence that the grammar of §6.3 has not validated.

  Texts and values are passed as option values (data). Nothing is ever `eval`/`exec`'d.
- **Call signature: `handler()`, with no arguments, for every event and backend** (portable to the Step 16 PySide6 signals; codegen is identical). Signatures are never introspected.
  - The return value is ignored, except that `activate` wrappers return `"break"` after calling the handler, so that Return in an entry does not also trigger a dialog's default button.
  - Exceptions inside a handler go to Tk's `report_callback_exception` (not caught).

### 4.2 Abstract event → Tk (from the built-in specs; an extension uses its fallback's row)
| Event | Classes | Tk wiring |
|---|---|---|
| `command` | Button, Checkbutton, Radiobutton | `command=` through the no-argument wrapper `_call(fn)` |
|  | Action | `add_command(command=)` on the menu entry |
| `change` | Entry, Combobox, Spinbox | `trace_add("write")` on the bound variable, or on a private `StringVar` set as `textvariable` when unbound |
|  | Checkbutton / Radiobutton | trace on the bound variable, or on a private `BooleanVar` / `StringVar` |
|  | Scale | trace on the bound variable, or on a private `DoubleVar` |
|  | Text | `<<Modified>>`; the wrapper calls `edit_modified(False)` afterwards |
|  | Scrollbar | `command=` through `_call(fn)`, which drops Tk's `("scroll", n, "units")` / `("moveto", f)` arguments (Step 16c fix) (the v1 schema has no scrollbar↔widget link; when one is added, the backend chains link first, then handler) |
| `select` | Notebook | `<<NotebookTabChanged>>` |
|  | Combobox | `<<ComboboxSelected>>` |
|  | Listbox | `<<ListboxSelect>>` |
|  | Treeview | `<<TreeviewSelect>>` |
| `activate` | Entry | `<Return>`, `<KP_Enter>` |
|  | Listbox, Treeview | `<Double-Button-1>`, `<Return>`, `<KP_Enter>` |
| `focus_in` / `focus_out` | all that support them | `<FocusIn>` / `<FocusOut>` |
| `key:<seq>` | the widget | `widget.bind(tk_seq)` for each Tk sequence of §6.3 |

Traces fire on programmatic writes too (documented). Bindings use `add="+"` so that ttkbootstrap's own class bindings survive.

## 5. Variables and `bind`
- `string|int|double|bool` → `StringVar|IntVar|DoubleVar|BooleanVar(master=root, value=…)`.
- Defaults are parsed with the validator's grammar (`int()`, `float()`, `"true"`/`"false"`). An empty default → `""`, `0`, `0.0`, `False`.
- Option per class:
  - Entry, Combobox, Spinbox, Label → `textvariable`. A bound Label gets **no** text slot: the variable owns the text.
  - Scale, Progressbar, Checkbutton, Radiobutton → `variable`.
  - Radiobutton also gets `value=` from its `value` prop: `int(value)` for an int variable (guaranteed by R77), otherwise the string.

## 6. Texts: translation, mnemonics, shortcuts
### 6.1 Translation (the app's catalogue, separate from pyguibud's)
- Every `Prop` with `translatable=True` is a **text slot**: `(document, prop, target, mnemonic: bool)`.
- Text = `t.pgettext(context, value)` if `context` is set, else `t.gettext(value)`. **An empty value is never passed to gettext**, because `""` returns the catalogue header.
- Translator per document, in this order:
  1. `translator=` (all documents);
  2. `lang == "en_XA"` → `pyguibud.i18n.PseudoTranslations()`;
  3. if `meta.i18n_domain` is empty → identity;
  4. otherwise `gettext.translation(domain, localedir or <that .ui's dir>/locale, languages=[lang] if lang else None, fallback=True)`, cached per `(domain, dir, lang)`.

  Any exception from gettext (a corrupt `.mo`) → identity + `runtime.catalogue_missing`. The same warning is logged when `lang` was given explicitly, no catalogue was found, and `lang`'s language differs from `meta.source_locale`'s.
- **Display limit** (QA-10-07): Tk lays a one-line text out in linear time (≈ 0.04 s per widget at 100 000 characters on Windows, Label/Button/Checkbutton/Radiobutton/Notebook tab; titles and menu labels are cheaper) but stalls for minutes near 4.5 million characters (a Notebook tab hung at 4.7 M). A `.ui` text is limited by R79, but a translation is never validated, so the backend clips every display text (titles, menu and action labels, page texts, widget texts, the statusbar) to `core.validate.MAX_TEXT_LENGTH` = 100 000 characters: the first 99 999 plus `…`. The mnemonic is split on the full text first; an `underline` in the removed part becomes `-1`. Each clipped slot logs `runtime.text_clipped` once. A `Text` widget has no `.ui` text, so nothing is clipped there. A bound variable's `default` is not clipped (it is application data); R80 limits it instead.
- Catalogue path: `<ui dir>/locale/<lang>/LC_MESSAGES/<i18n_domain>.mo` (standard gettext layout; stdlib lookup, so `de_DE` falls back to `de`).
- **Runtime-owned strings** (dialog buttons: `N_("_OK")`, `N_("_Cancel")`, `N_("_Yes")`, `N_("_No")`, `N_("_Close")`):
  - Translated with a **private** `gettext.translation("pyguibud", pyguibud.i18n.LOCALE_DIR, languages=[lang] …)`, so they follow the **app's** language.
  - The runtime never calls `pyguibud.i18n.set_language` and never touches the designer's global state.

### 6.2 Mnemonics (`core.keys.split_mnemonic(text) -> tuple[str, int]`)
- **Order:** translate the raw msgid (underscore included) first, then split. Codegen does the same.
- **Grammar:**
  - `__` → a literal `_`;
  - the first `_` followed by a character other than `_` or a space marks that character, which is removed from the display and whose index becomes `underline`;
  - later single underscores and a trailing `_` stay literal;
  - no mark → `-1`.
- **Applies to:** Menu (cascade label), Action (entry label), Button, Checkbutton, Radiobutton and Notebook page text.
- **Never applies to** (text shown literally): Label, LabelFrame, Statusbar and window titles.
- **Activation:**
  - menus: Tk native;
  - Notebook: `enable_traversal()`;
  - Button, Checkbutton, Radiobutton: bind `<Alt-KeyPress-x>` and `<Alt-KeyPress-X>` on the **owning toplevel**. The binding does `focus_set()` and `invoke()` if the widget is viewable and its state is not disabled, and returns `"break"`.
- **Conflicts:**
  - a letter already used by a top-level menu of that window → menu wins, logged as `runtime.mnemonic_conflict`;
  - two widgets with the same letter → the first in build order wins, logged.
- On `aqua` no Alt bindings are made (macOS has no access-key convention).
- `retranslate` unbinds and rebinds these Alt bindings (it tracks the funcids).

### 6.3 Shortcut and key grammar (`core/keys.py`, pure; shared by the validator and every backend)
```
chord    := (modifier "+")* key                    -- case-insensitive; each modifier at most once
modifier := Ctrl | Alt | Shift                     -- canonical order Ctrl, Alt, Shift
key      := A–Z | 0–9 | F1–F24 | Enter | Return | Escape | Tab | Space | Backspace | Delete | Insert
          | Home | End | PageUp | PageDown | Up | Down | Left | Right | Plus | Minus | Comma | Period | Slash
```
- `parse_chord(text) -> Chord | None`, where `Chord(modifiers: frozenset[str], key: str)` is canonical. `format_chord(chord) -> str` gives e.g. `"Ctrl+Shift+S"`.
- **Action `shortcut`** (the attribute, §9.4) must parse, and must contain Ctrl or Alt unless the key is F1–F24. Otherwise it would steal typing from entries, because it is bound on the toplevel.
- **`key:<seq>`** accepts either:
  - a chord (any key; for example `key:Return`, `key:F5`), or
  - the **Tk-native form** `<(Mod-)*(KeyPress-|Key-)?keysym>`, where `Mod ∈ {Control, Alt, Shift, Option, Command, Meta}` (each at most once) and `keysym` is one ASCII letter or digit, or one of `Return KP_Enter Escape Tab space BackSpace Delete Insert Home End Prior Next Up Down Left Right plus minus comma period slash F1`–`F24` (for example `key:<Control-s>`, `key:<Return>`). It is passed to Tk verbatim, **except** that `Key-` is inserted before a bare digit keysym (QA-10-01): Tk reads `<Control-1>` as Ctrl + mouse button 1, so `<1>` → `<Key-1>` and `<Control-5>` → `<Control-Key-5>`; a sequence that already says `Key-`/`KeyPress-` is unchanged. All six modifiers are names in Tk's static modifier table (`bind(n)`), so every platform accepts them (`Command`/`Option` alias `Mod1`/`Mod2` off macOS), and the validator never approves a sequence that Tk refuses at build time. Portability is reviewed in Step 16.
- **Chord → Tk** (backend, `_tk.py`):
  - modifiers: `Ctrl` → `Control` (`Command` on aqua), `Alt` → `Alt` (`Option` on aqua), `Shift` → `Shift`;
  - keys: letter → **both** `x` and `X` sequences; Enter/Return → `Return` and `KP_Enter`; Space → `space`; Backspace → `BackSpace`; PageUp/PageDown → `Prior`/`Next`; Plus/Minus/Comma/Period/Slash → `plus`/`minus`/`comma`/`period`/`slash`; others as named.
  - Example: `Ctrl+Q` → `<Control-q>`, `<Control-Q>`.
  - A digit key always gets `Key-`: `Ctrl+1` → `<Control-Key-1>` (QA-10-01; `<Control-1>` would be Ctrl + mouse button 1).
- **Menu shortcuts:**
  - `add_command(accelerator=format_chord(chord))`: the display is canonical and untranslated in v0, so "Strg" for German is Step 18.
  - Each Tk sequence is bound on the **owning window's toplevel** (never `bind_all`) to `menu.invoke(index)`, which respects a disabled entry.
  - Duplicate chords in one window (R73 warning): only the first is bound.

## 7. Resources and includes at runtime
### 7.1 Images
- `src` is resolved relative to **its own** `.ui` file's directory (an included file uses its own). R46/R47 absolute or escaping paths stay **warnings** (schema decision), and the runtime loads them; the code generator refuses them unless `--force` (Step 11, QA-11-03). UNC, Win32-namespace and device paths are R82 **errors** (Step 11) and are never opened. There is no sandbox: images are decoded by Tk only (documented).
- Formats: **PNG, GIF, PPM/PGM only**, decoded natively by Tk 8.6. No Pillow, for every backend and for codegen (decision U6).
- The file was probed in P3: it exists, its magic matches the suffix, it is ≤ 16 MiB and each side is ≤ 4096 px (R74–R76).
- One `PhotoImage` per `(document, id)`, held in `LoadedUi._images` for the life of the UI.
- With both `text` and `image` → `compound="left"`.

### 7.2 Includes
- **Spelling:** `src="#"` means **this file** (decision U5); `"./#"` would name a real file called `#`. A path that resolves (real path + `normcase`) to the including file is treated identically.
- **Instance:** each `<include>` becomes a `ttk.Frame`, placed by the include's placement in its parent. The component window's `<layout>` (padding, gap, grid lines) is applied to that frame, and the component window's props (title) are ignored. The component subtree is then built into it.
- **Scope:** `ui.<include id>` is a new `UiScope`:
  - attributes: the component's ids plus `scope.<component window id>` = the frame;
  - `windows == {}`;
  - nested includes nest scopes.

  Inner ids are reachable **only** through the scope, never as `ui.<inner id>`, because a component included twice would clash.
- **Variables:**
  - a same-file component **shares** the host document's `vars` (one file, one variable namespace);
  - an external component gets a **fresh instance** of its file's variables per include (`ui.<include id>.vars`).
- **Shared by all instances:** one handlers object. Translators and images are per document.

## 8. Windows, theme, layout, widgets (`_tk.py` + `ttkbootstrap.py`)
### 8.1 Window structure (one geometry manager per master)
- **Toplevel** (grid, column 0 weight 1):
  - row 0: **body** `ttk.Frame`, sticky `nsew`, row weight 1. The window's `<layout>` is applied to the body, never to the toplevel.
  - row 1: the dialog **button bar**, if `buttons` is set (§8.5);
  - last row: the **statusbar** `ttk.Frame` (sticky `ew`), containing a `ttk.Separator` (pack `fill="x"`) and a `ttk.Label` (pack `fill="x"`, `padding=(6, 2)`).
- **Menubar:** `ttkbootstrap.Menu(top, tearoff=False)`, then `top.configure(menu=…)`.
  - Menu → `add_cascade(label, underline, menu=Menu(parent, tearoff=False))`, nested likewise.
  - Separator → `add_separator()`.
  - Action → `add_command(label, underline, accelerator, command, image, compound="left", state)`.
- **Window settings:**
  - `title` → `top.title()` (translatable);
  - `min_width`/`min_height` → `minsize(w or 0, h or 0)`;
  - dialogs: `WM_DELETE_WINDOW` → withdraw + result `None`;
  - main: default (destroying the root ends the app).

### 8.2 Theme
- Only when `load_ui` created the root:
  1. `App(title=…)` **without** a theme argument: an unknown name passed to the constructor would raise after the root exists.
  2. If `meta.theme` is set and is not in `style.theme_names()`, call `install_legacy_themes(style)` once, inside `warnings.catch_warnings()` with `DeprecationWarning` ignored, then check again.
  3. Still unknown → `runtime.unknown_theme`, default theme kept; otherwise `style.theme_use(name)`.
- `hello.ui`'s `flatly` is a legacy name and works through this path.
- With `master` given, the theme is **not** changed (it is process-wide); `runtime.theme_ignored` is logged when `meta.theme` differs from the current theme.

### 8.3 Layout mapping (ADR-005; codegen emits the same numbers)
- **Container padding:** `padding` → ttk `padding=` on the body, Frame, LabelFrame, ScrolledFrame or include frame.
- **Grid:**
  - `columnconfigure(i, weight=, minsize=)` and `rowconfigure(…)` from `<column>`/`<row>`;
  - child: `grid(row, column, rowspan, columnspan, sticky, padx=(lead_x + padx, padx), pady=(lead_y + pady, pady))`, where `lead_x = gap if column > 0 else 0` and likewise for rows (gap = space *between* cells, as Qt spacing).
- **Pack:**
  - `side="top"` (vertical) or `"left"` (horizontal); `fill`, `expand`, `padx`, `pady`;
  - the 2nd and later children get a leading `gap` along the orientation.
- **Pages:**
  - Notebook → `add(child, text=, underline=, image=, compound=)`, then `enable_traversal()`;
  - PanedWindow → `add(child, weight=page.weight)`;
  - the PanedWindow `orient` prop is passed to the constructor (it cannot change later).

### 8.4 Widgets and props
| Class | ttkbootstrap class | Prop → option deviations |
|---|---|---|
| Frame, Label, Button, Entry, Checkbutton, Radiobutton, Combobox, Spinbox, Scale, Progressbar, Separator, Treeview, Scrollbar, Notebook | same name | Scale/Spinbox `minimum`→`from_`, `maximum`→`to`; Spinbox `increment` |
| LabelFrame | `Labelframe` | — |
| PanedWindow | `Panedwindow` | — |
| ScrolledFrame | `ScrolledFrame` | `autohide`→`auto_hide` |
| Text, Listbox, Canvas | `Text`, `Listbox`, `Canvas` (tk, autostyled) | Canvas `background` |
- **Effective value** = the prop value, else `PropertyDef.default` when not None, else the toolkit default. This is pinned because PyGUIbud defaults differ from Tk's (Text `wrap="word"`, Spinbox `to=100`, ScrolledFrame `auto_hide=True`).
- Values are converted by `PropertyDef.type`: int, float, bool; enum/colour/string as is. Image → `PhotoImage`.
- `state` → `configure(state=)`. Props unknown to the spec (already warned) are ignored.
- All construction-time options (`orient`, `mode`, `show`, …) go to the constructor.
- **Extensions:** `registry.resolve(class_name, "ttkbootstrap", fallback)`. In Step 10, every extension renders its **core fallback** (logged once as `runtime.extension_fallback`). Calling `WidgetSpec.factories` is Step 17.
- **`tb:bootstyle`** (`extra_attrs["{urn:pyguibud:ext:ttkbootstrap:1}bootstyle"]`):
  - passed as `bootstyle=` to ttk-based classes only;
  - the value must match `^[a-z]+(-[a-z]+)*( [a-z]+(-[a-z]+)*)*$` and be ≤ 64 characters;
  - if it does not, or the toolkit rejects it (construction is retried without it), or the class is tk-based → `runtime.bootstyle_ignored`.
- Other `tb:` attributes are ignored. `tb:` validation is Step 17. Other backends ignore `tb:` (FEATURES §3).

### 8.5 Dialog button bar (trim candidate 1)
- Tokens (R70) are rendered as buttons in the **written order**, right-aligned, with mnemonic labels from the runtime catalogue (§6.1).
- **Default button:** the first of `ok`/`yes` gets `default="active"`; Return on the dialog toplevel invokes it.
- **Escape** invokes `cancel`, else `no`, else `close`.
- Every token closes the dialog: withdraw, store the result, release the grab.
- `apply`/`help` (non-closing) are deferred: they need a handler contract.

## 9. Validator additions (code in `core/validate.py`; amends validate-commands.md §5.2, decision U1)
### 9.1 `files=`: injected file access, so every rule stays in `validate()`
```python
def validate(document, registry, *, source="<memory>", positions=None, limit=MAX_FINDINGS,
             files: FileAccess | None = None) -> ValidationReport
def validate_read(result, registry, *, files: FileAccess | None = None) -> ValidationReport

class FileAccess(Protocol):                      # core/validate.py
    @property
    def root(self) -> str: ...                   # key of the validated document
    def resolve(self, including: str, src: str) -> str: ...   # "#" → including; raises OSError
    def read(self, key: str) -> ReadResult: ...  # cached; raises OSError or XmlIoError
    def probe_image(self, including: str, src: str) -> ImageProbe: ...

@dataclass(frozen=True, slots=True)
class ImageProbe:                                # core/files.py
    status: Literal["ok", "missing", "invalid"]
    reason: str = ""                             # msgid key for R76's {reason}
    width: int = 0
    height: int = 0
```
- `files=None` (every existing caller, and **always the command guards**: I/O would break the 100 ms edit budget) skips R49–R53 and R75–R76. Every other new rule is pure and always runs. *Amended 2026-10-09 (ADR-006 amendment): R51–R53 still run for same-file `src="#"` includes, because they need no I/O.*
- **`DiskFiles(path, root_result)`** (`core/files.py`):
  - key = `os.path.normcase(os.path.realpath(p))`; `read(root)` returns `root_result`;
  - `read` requires a regular file (directories, devices → `OSError`), then `read_ui`, which applies the 10 MiB and depth limits;
  - `probe_image` checks: `stat` size ≤ `MAX_IMAGE_BYTES = 16 MiB`; ≤ 64 header bytes; magic vs suffix (PNG signature + IHDR, `GIF87a`/`GIF89a`, `P2`/`P3`/`P5`/`P6` + header dimensions); each side ≤ `MAX_IMAGE_SIDE = 4096`.
  - The runtime reuses the same instance for the build (P5).
- **Include pass:**
  - Runs after the single-document pass, with an explicit stack. It checks every include of **every window of the root file**, and of each included file only the **target component's subtree**.
  - Each newly read file is validated once (`files=None`) and its findings are appended verbatim after the root's (their own `source`). Its resources are probed (R75/R76).
  - **Limits:** `MAX_INCLUDE_DEPTH = 8`, `MAX_INCLUDE_FILES = 32` distinct files, `MAX_EXPANDED_NODES = 10_000` nodes instantiated *via includes* (memoised per `(key, component)`, so it is fan-out-bomb-proof). Once a limit is hit, no further include is followed.

### 9.2 New rules
All anchored at the node shown, with the usual `{}`-param msgids marked `N_`, plus `# Translators:` comments.

| # | Code | Sev | msgid (en-GB) | What |
|---|---|---|---|---|
| R49 | `validate.include_missing` | E | "The included file '{src}' does not exist or cannot be read." | `resolve`/`read` raised `OSError` (missing file, directory, permission) |
| R50 | `validate.include_invalid` | E | `NP_` "The included file '{src}' has {count} error." / "The included file '{src}' has {count} errors."; for a read failure, "The included file '{src}' cannot be read: {reason}" | `XmlIoError`, or validator errors in that file |
| R51 | `validate.include_not_component` | E | "'{src}' has no component window '{component}'." / "The window '{component}' in '{src}' is not a component." | id absent / `kind != "component"` |
| R52 | `validate.include_cycle` | E | "Including '{component}' from '{src}' creates a cycle: {chain}." | DFS over `(key, component)`; `{chain}` = `a.ui#x → b.ui#y → a.ui#x` |
| R53 | `validate.include_limit` | E | Three msgids (no concatenation): "Including '{src}' nests includes deeper than {limit} levels." / "Including '{src}' reads more than {limit} files." / "Including '{src}' creates more than {limit} widgets." | §9.1 limits |
| R69 | `validate.reserved_id` | E | "'{id}' is reserved by the generated interface and cannot be used as an id." | any id ∈ `RESERVED_IDS` (all id owners, resources and variables included) |
| R70 | `validate.bad_buttons` | E | "'{value}' is not a valid button list; use a comma-separated list of {choices} without repeats." | **dialog windows only** (on others R08 already says "ignored"): `^T(,T)*$` with `T = ok\|cancel\|yes\|no\|close`, no duplicates, no spaces |
| R71 | `validate.bad_shortcut` | E | "'{value}' is not a valid shortcut, for example Ctrl+S or Ctrl+Shift+F5." / "The shortcut '{value}' needs Ctrl or Alt unless it is a function key (F1–F24)." | Action `shortcut` attribute (§6.3) |
| R72 | `validate.bad_key_sequence` | E | "'{value}' is not a valid key, for example key:Ctrl+S or key:<Control-s>." | `key:` events with a non-empty sequence failing both forms (R36 still covers `key:` and whitespace) |
| R73 | `validate.duplicate_shortcut` | W | "The shortcut '{shortcut}' is used more than once in '{window}'; only the first one works." | same canonical chord twice among one window's actions |
| R74 | `validate.image_format` | E | "'{src}' is not a supported image; use PNG, GIF, PPM or PGM." | resource `src` suffix (case-insensitive) ∉ `.png .gif .ppm .pgm` |
| R75 | `validate.image_missing` | E | "The image file '{src}' does not exist." | probe `missing` (files only) |
| R76 | `validate.image_invalid` | E | "The image file '{src}' cannot be used: {reason}" | probe `invalid`: damaged header, content not matching suffix, over 16 MiB, side over 4096 px, plain-text P2/P3 (Tk cannot read them), a PNG whose chunks do not reach `IEND` intact (CRC, `IDAT`, no unknown critical chunk) or a PPM/PGM raster shorter than its header says (Step 11, QA-11-06/07). For a GIF both the logical screen and the **first image descriptor** (after the global colour table and any extension blocks; Tk allocates the frame from it) must be 1..4096 px; no image before the trailer or the end of the file = damaged (QA-10-10) |
| R77 | `validate.bad_radio_value` | E | "The value '{value}' of '{id}' must be a whole number, because it is bound to the int variable '{bind}'." | Radiobutton bound to an `int` variable with a `value` failing R31 int (absent = `""` fails) |
| R78 | `validate.bad_i18n_domain` | E | "'{value}' is not a valid translation domain; use letters, digits, '_', '-' or '.'." | non-empty `meta.i18n_domain` not matching `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$` or containing `..` (it becomes a file name) |
| R79 | `validate.text_too_long` | E | "The property '{name}' has {length} characters; at most {limit} are allowed." | a `string` property (text, title, page text, menu/action/statusbar text, Entry `show`, Radiobutton `value`) longer than `MAX_TEXT_LENGTH` = 100 000 (QA-10-07; the runtime clips translations to the same constant, §6.1) |
| R80 | `validate.text_too_long` | E | "The default of the variable '{id}' has {length} characters; at most {limit} are allowed." | a variable `default` longer than `MAX_DEFAULT_LENGTH` = 10 000: a bound Entry/Combobox/Spinbox shows it, and the Tk entry lays text out in quadratic time (≈ 0.1 s at 10 000, 6 s at 100 000) |
| R81 | `validate.bad_source_locale` | E | "'{value}' is not a valid language code for the source texts; use a code such as en_GB." | `meta.source_locale` not matching `i18n.LANGUAGE_CODE_RE` (`^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})*$`); generated modules compare it with the requested language (QA-11-11, Step 11) |
| R82 | `validate.network_path` | E | "The path '{path}' points to a network share or a device, which is never opened; use a path relative to the .ui file." | image or include `src` that is UNC or a Win32 namespace (`//host/share`, `\\host\share`, `\\?\`, `\\.\`, `\??\`) or has a Win32 device segment (`CON`, `nul.png`, `COM1 .gif`, any case and extension): `core.files.is_network_or_device_path`, a pure string test run before any file access; R46/R47 are then not reported, and the file rules skip the path (QA-11-03, Step 11, user decision "Block UNC") |

### 9.3 Guards and `--check`
- **Command guards:** R69–R74 and R77–R80 now participate, with the default guard key. So renaming an id to `run`, typing a bad shortcut or a bad `key:` sequence, and so on, is blocked. R73 never blocks (warning).
- **`pyguibud-uic --check`** passes `files=DiskFiles(path, result)` (decision U3). Include and image errors then exit 1, consistent with `load_ui`.

### 9.4 Action `shortcut`: attribute versus property
- **The attribute wins.** It is canonical in xml-io §9.2, `hello.ui`, FEATURES §4 and the Step 09 §6.1 command fields.
- Remove `PropertyDef(name="shortcut")` from the Action spec (`widgets.py`; core-model §6 table, line 171).
- A stray `<prop name="shortcut">` then gets the existing `validate.unknown_prop` warning (kept, ignored). No new code.

## 10. Backend contract (`pyguibud/backends/base.py`; provisional until 1.0, like `WidgetSpec`)
### 10.1 Protocols
```python
class Backend(Protocol):
    name: ClassVar[str]  # entry-point name, e.g. "ttkbootstrap"

    def prepare(
        self, master: object | None
    ) -> None: ...  # import the toolkit, check master; never creates a window
    def build(self, plan: BuildPlan, master: object | None) -> Session: ...


class Session(Protocol):
    def apply_texts(
        self, text: Callable[[TextSlot], str], runtime_text: Callable[[str], str]
    ) -> None: ...  # compute every text first, then set them (all-or-nothing)
    def alive(self) -> bool: ...  # False once a window or the root is gone; never raises
    def show(self, window_id: str) -> str | None: ...
    def run(self) -> None: ...
    def destroy(self) -> None: ...
```
- **`BuildPlan`** (frozen, toolkit-free): `path`, the instance tree from P5 (documents with base directory, scopes to fill, include targets), resolved `handlers: Mapping[str, Callable[[], object]]` (missing names absent), `images: Mapping[tuple[str, str], Path]`, `registry`, `theme`, `owns_root: bool`. The implementer finalises the private field types. Only the protocols above are public.
- `build` attaches ids through a private `UiScope._attach(id, obj)` and registers a `TextSlot` for each translatable prop. `LoadedUi` holds the session and delegates `retranslate` → `apply_texts`, plus `show`, `run` and `destroy`.
- `prepare` turns `ImportError` and a `master` of the wrong kind into an exception that the runtime wraps as `runtime.backend_unavailable`.

### 10.2 Registration
- `pyproject.toml`: `[project.entry-points."pyguibud.backends"] ttkbootstrap = "pyguibud.backends.ttkbootstrap:TtkbootstrapBackend"`, then `uv sync`. Orchestrator/DEPLOYER edit.
- `Registry.load_backend` returns the class; `load_ui` instantiates it once per call.
- **Safety net** (like the core widgets): if the registry lists no `ttkbootstrap`, import it directly.
- Forks and plugins register their own backend names; core needs no patch.
- **Step 16:** `backends/tkinter.py` reuses `_tk.TkBuilder` with a plain-ttk class table and no theme/`bootstyle`; `backends/pyside6.py` implements the protocols afresh.

## 11. UAT assets
- **`examples/locale/de_DE/LC_MESSAGES/hello.po`:**
  - **Hand-made** (Step 11's `--extract` is not available yet; Step 11 adds a test that its `.pot` has the same `(msgctxt, msgid)` set).
  - Header: `Language: de_DE`, UTF-8, `Plural-Forms: nplurals=2; plural=(n != 1);`.
  - Compile with `uv run pybabel compile -d examples/locale -D hello` and **commit the `.mo`** (the repository tracks `.mo` files).
  - `babel.cfg` extracts `src/` only, so the example strings never enter `pyguibud.pot`.

| msgctxt | msgid | msgstr |
|---|---|---|
| window title | Hello PyGUIbud | Hallo PyGUIbud |
| — | _File | _Datei |
| — | _Quit | _Beenden |
| — | Ready | Bereit |
| tab | Greeting | Begrüßung |
| greeting form | Your name: | Ihr Name: |
| — | Say hello | Hallo sagen |
| tab | About | Info |
| — | PyGUIbud example: one window, two tabs. | PyGUIbud-Beispiel: ein Fenster, zwei Reiter. |
| — | Hello, {name}! *(run_hello.py)* | Hallo, {name}! |
| — | Please enter your name. *(run_hello.py)* | Bitte geben Sie Ihren Namen ein. |

- **`examples/run_hello.py`** (about 60 lines):
  - `argparse --lang`;
  - `class HelloApp` with `on_greet` (reads `ui.vars.user_name`, writes the greeting through its own `gettext.translation("hello", examples/locale, [lang], fallback=True)` into `ui.sts_main`) and `on_quit` (`ui.destroy()`);
  - `F2` toggles `en_GB` ↔ `de_DE` via `ui.retranslate(lang)` (live switch);
  - `ui.run()`.
- **UAT checklist (for the orchestrator):**
  - the window opens with the theme;
  - type a name + Enter → status greeting; the button works too;
  - Alt+F opens File; Ctrl+Q quits;
  - `--lang de_DE` → German, `_Datei` underlined;
  - F2 switches live;
  - `--lang xx_XX` → English plus a log warning;
  - rename `on_greet` in the script → one clear error naming it, and no window appears.

## 12. Test plan (TESTING agent)
- **Layout:** `tests/runtime/`:
  - `test_keys.py` (pure);
  - `test_validate_step10.py` (pure rules + `DiskFiles` on `tmp_path`);
  - `test_pipeline.py` (pre-Tk, **no display needed**: a fake backend records `prepare`/`build` and the tests assert `build` is never called on failure);
  - `test_tk_build.py` (`gui`);
  - `test_own_root.py` (`gui`, subprocesses);
  - `test_import_boundary.py`;
  - `test_example_catalogue.py`.
- **Display gate:**
  - `conftest.py` probes once per session with a subprocess `python -c "import tkinter; tkinter.Tk().destroy()"` (timeout 10 s); marker `gui` → skip with a reason when the probe fails;
  - register `markers = ["gui: needs a Tk display"]` in `pyproject.toml` (`--strict-markers` is on).
- **ttkbootstrap single root:**
  - a session-scoped `tk_root` fixture (`ttkbootstrap.App()`, withdrawn); every in-process GUI test uses `master=tk_root`;
  - tests of the own-root path (theme, `destroy()` resets `Style`, a second `load_ui` → `runtime.root_exists`, `no_display`) run in a **subprocess** and print JSON results;
  - each test asserts that `tk_root.winfo_children()` is unchanged after `ui.destroy()`.
- **Golden behaviour (`hello.ui`):**
  - `de_DE`: titles and labels translated; `mnu_file` label `Datei`, underline 0; tab texts; accelerator `Ctrl+Q`;
  - `retranslate("en_GB")` restores; `en_XA` is pseudo;
  - `ui.vars.user_name.set("Ana")` → `ui.ent_name.get() == "Ana"`;
  - `ui.btn_greet.invoke()` → `on_greet` called once with no arguments;
  - `<Control-q>` and `<Control-Q>` bound on the main toplevel; `ui.act_quit == 0`;
  - **no `select` handler call caused by the build** (a Notebook with a `select` handler, then `update()` → 0 calls); `invoke()` straight after `load_ui` (no `update()`) → 1 call;
  - `bootstyle` applied to `btn_greet`;
  - `flatly` active (subprocess).
  - Event wiring is also tested purely: a table function maps `(class, event)` → Tk wiring without Tk.
- **Pipeline:**
  - each `UiError` code; the aggregated missing-handler list (sorted, unique, all names);
  - Mapping handlers; a raising property counts as missing; non-callable;
  - non-strict logs; a validator error → `findings` attached; warnings logged (`caplog`).
- **Import boundary** (subprocess): `import pyguibud_runtime, pyguibud.backends.ttkbootstrap` leaves `tkinter`, `ttkbootstrap`, `pyguibud.cli`, `pyguibud.uic` and any `pyguibud.designer`/`pyguibud.codegen` modules out of `sys.modules`; `import pyguibud.core` likewise (ADR-007).
- **Abuse (QA):**
  - include fan-out bomb (10 × 10 × 10 × 10 × 10) → R53;
  - A→B→A and the self-include `#` cycle → R52;
  - `src` naming a directory / an 11 MiB file / a binary file / `../../…`;
  - case-variant paths on Windows (same key);
  - PNG with an IHDR of 100000 × 100000; `.png` holding GIF data; a 0-byte image;
  - `i18n_domain="../x"` (R78); `lang="../../x"` (`ValueError`);
  - an id `run` (R69); `shortcut="Q"` (R71); `key:<Button-1>` (R72);
  - a handler that raises → the app keeps running;
  - `load_ui` twice without `master`; `retranslate` after `destroy`;
  - 1,000+ errors → message capped at 20 lines + tail.
- **Example catalogue:** every `(context, msgid)` of the translatable props in `hello.ui` is in `hello.po`, non-fuzzy and non-empty, with placeholders preserved; the `.mo` returns the `.po` msgstr for each (a stale `.mo` fails).
- **CI** (recommendation for `.github/workflows/ci.yml`, orchestrator/DEPLOYER edit): on `runner.os == 'Linux'`, add `sudo apt-get install -y xvfb` and run `xvfb-run -a uv run python -m pytest --cov`; Windows and macOS unchanged. The `gui` probe still skips cleanly if no display exists.
- **Gates:** ruff, mypy `--strict`; coverage ≥ 85 % for `pyguibud_runtime` + `pyguibud/backends` on a machine with a display, ≥ 90 % for `core/keys.py` and `core/files.py`.

## 13. Fixture and document impact
| Item | Impact |
|---|---|
| `tests/core/data/validate/r08_dialog_only.ui` (`buttons="ok_cancel"` on main) | unchanged: R70 runs on dialogs only |
| `test_validate.py:278` (`buttons="x"` on a main window, warnings only) / `:374` (`"x\x03"`) | unchanged (main window) |
| `xml_io/reordered.*` dialog `buttons="ok,cancel"`; `full.*` `shortcut="Ctrl+O"`, `key:<Control-s>` | valid under R70/R71/R72 |
| `test_core_model.py` key events `key:Return`, `key:F5`, `key:<Control-s>` | valid (R72) |
| `test_commands_roundtrip.py:117/141` `SetField` `buttons`/`shortcut` with `TEXTS` | `shortcut="fine"` and `""` are now rejected by the guard (R71); update the expectations if the test asserts acceptance |
| `validator_demo` golden output | unchanged unless it uses a reserved id/shortcut (verify) |
| `examples/hello.ui` | **unchanged** (byte-exact golden, xml-io §13; `flatly` via legacy themes) |
| Docs to update on approval | validate-commands §4 (`files=`), §5 (R49–R53, R69–R78), §5.2 and §13 D4 (amended), §12; core-model §6 Action row; FEATURES §4 (`src="#"`, key/shortcut grammar, image formats); `ui-schema-rules` skill summary (R-range, ADR-007); DEVELOPMENT_PLAN §5 notes |

## 14. Deferred
- **Step 11:** codegen emits this exact shape, with helpers (mnemonic split, chord → Tk, button bar) inlined dependency-free; `--extract` reproduces §11's msgid set. Superseded by `docs/specs/codegen.md` (ADR-008): runtime-owned button labels are not extracted until the button bar exists (Step 14).
- **Step 14:** `apply`/`help` dialog buttons (handler contract).
- **Step 16:** tkinter/PySide6 backends; portability of Tk-native `key:` sequences; Qt `Ctrl`↔`Meta` semantics.
- **Step 17:** `WidgetSpec.factories` calls, `tb:` attribute validation, extension placeholders.
- **Step 18:** localised accelerator text ("Strg+Q") and runtime button labels in seven locales.
- **Step 19:** scoped validation.
- **Step 20:** distribution split (ADR-007).

## 15. Decisions for the user (proposed default in bold)
| # | Question | Default |
|---|---|---|
| U1 | Include and image checks need file access. Inject it into `validate(…, files=FileAccess)`, which amends Step 09 D4's rejected alternative but keeps every rule in `validate()`? Or use a separate checker module? | **Inject**: `files=None` by default, never used by the command guards |
| U2 | Enforce the reserved ids (R69: `vars widgets windows setup_ui retranslate show run destroy`) now, because the runtime already exposes `ui.<id>`, rather than in Step 11? | **Now** |
| U3 | Should `pyguibud-uic --check` also run the file rules (include and image errors → exit 1)? | **Yes** |
| U4 | Pin `ttkbootstrap>=2.2,<3` (the code targets the 2.x API), and keep `hello.ui`'s `theme="flatly"` working through the legacy themes (no golden change)? | **Yes / yes** |
| U5 | Should the same-file include spelling be `src="#"`? | **Yes** |
| U6 | Limit images to Tk-native PNG, GIF, PPM and PGM (no Pillow) for every backend and for codegen? | **Yes** |

## 16. Known limitations
Platform limits that cannot be fixed cheaply (hardening spec, decision D3). They are copied into the user documentation in Step 21.

| Id | Limitation | Why it stays | What to do |
|---|---|---|---|
| H28 | A symbolic link or junction to a network share **is followed**. R82 (`validate.network_path`) checks only the `src` text (`\\host\share`, `//host/share`, device paths); a local-looking `icons/x.png` or `form.ui` that is itself a link to a share is opened, so the share is contacted (and may stall or ask for credentials). | Refusing it would mean resolving every path with `realpath` before every open (designer, `load_ui`, `pyguibud-uic`), with a race between the check and the open, and junctions and mount points differ per OS. | Keep `.ui` projects, their images and their includes on local disks; do not link them to network shares. |
| H51 | A handler that hides a dialog (Qt `hide()`/`accept()`/`reject()`, Tk `withdraw()`) leaves the event loop running with no visible window, so `run()` (or the preview) does not return. | Tk parity: a withdrawn Toplevel keeps `mainloop` running too, and the loader cannot tell a temporarily hidden dialog from a finished one. | Close the window (`ui.<window>.destroy()` / `close()`) when you are done with it, or call `ui.destroy()`; hide it only if you show it again. |
| H53 | With the PySide6 backend, an integer variable reads leading zeros as decimal: `"010"` is 10, not octal 8 (Tcl 9 behaviour; Tk 8.6 reads 8). | Following one Tcl version is the only consistent choice; octal integers in a form are almost always a typing mistake. | Do not rely on octal input; validate the text yourself if leading zeros matter. |
| H58 | On Linux/BSD, PySide6 with `DISPLAY` set to an unreachable X server aborts the process inside Qt (a crash dialog in the designer with the stderr tail). The guard only checks that the variable is set and that a platform plugin exists. | Reaching the server means opening an X connection before Qt does, which needs an X client library in the core; Qt's own abort cannot be caught in Python. | Unset `DISPLAY` or set `QT_QPA_PLATFORM=offscreen` on headless machines; with no display the guard refuses cleanly (`runtime.no_display`). |
| H63 | A variable bound to a `tb:DateEntry` holds the date as ISO text (`2026-10-18`), not in the widget's `date_format`. | The ISO form is what the `.ui` stores and what every backend can parse; the display format may be ambiguous (`%y`, `%d/%m`). | Parse the variable with `datetime.date.fromisoformat()`. |
| H64 | `ui.<id>` of a `tb:Tableview` is the inner `Treeview`; the outer Tableview has no handle of its own. | `ui.<id>` behaves as the fallback class (plugins spec D4), so code written for the core Treeview keeps working. | Reach the Tableview as `ui.<id>.master.master` (DateEntry: `ui.<id>.master`); add rows with its `insert_row(s)` + `load_table_data()`, not with `ui.<id>.insert(...)`. |
| QA-19b-08 | `load_ui(r"\\host\share\form.ui")` opens a top-level `.ui` on a network share: the share is contacted, and an unreachable host stalls the call (about 40 s on Windows) before it fails. The designer and `pyguibud-uic` refuse network and device paths at once ("Network and device paths cannot be opened."). Images and includes inside the file are still R82 errors. | `load_ui` is a library API: an application may load its forms from a share on purpose, and only the application knows whether the share is reachable. | Load forms from a local folder, or check the share yourself before calling `load_ui`. |
