# Spec — Step 16: tkinter and PySide6 backends

- **Status:** Accepted (user, 2026-10-12: D1–D20 all defaults (a); `examples/run_hello.py` stays ttkbootstrap-only, `examples/show_ui.py` added) · **ADR:** ADR-014 (Accepted). Builds on ADR-001 (vocabulary, fallbacks), ADR-004 (entry points), ADR-005 (grid + one-orient pack), ADR-007 (boundary), ADR-008 (codegen stays ttkbootstrap), ADR-013 (preview child, `PreviewHost`)
- **Owner:** BACKEND (backends, preview child) + FRONTEND (Toolkit menu) · **Reviewer:** SOFTWARE-ARCHITECT
- **Budget:** ≈ 1,770 production lines over three parts, caps 500 + 850 + 700 = 2,050 (§0, D1)
- **Plan row 16:** `backends/tkinter.py`, `backends/pyside6.py` (`[pyside]` extra, `PySide6>=6.6`). UAT: "Same `.ui` renders in the 3 toolkits".

## 0. Scope fence, budget and split
**In:**
- `load_ui(..., backend="tkinter" | "pyside6")` builds every core class, layout, menu, status bar, include, image, variable, event and translatable text of a valid `.ui`.
- The preview child runs any of the three toolkits. The designer gains a Preview ▸ Toolkit sub-menu (preview-export §7).
- A toolkit-neutral `portable_describe` that proves "same `.ui`" (§7).

**Out:**
- Codegen for tkinter or Qt (ADR-008: export stays ttkbootstrap).
- The designer canvas: it stays ttkbootstrap embed mode (ADR-010).
- Plugin factories and `tb:` widgets (Step 17; the seam is in §8).
- Dialog modality and button bars (still trimmed since Step 14 in `_tk.py`, so Qt mirrors Tk: non-modal, closing hides).
- Qt's own strings (context menus) in other languages (D18).
- The runtime distribution split (Step 20).

**Hard constraints:**
- **No `.ui` format change, no schema bump, no validator change.** `validate()` stays backend-agnostic.
- **No change to `pyguibud_runtime/`** apart from docstrings. ADR-007 already allows lazy `pyguibud.backends.<name>`.
- `pyguibud.core` gets no change. Qt key and unit tables live in the pure module `backends/_qtmap.py`.
- Importing `pyguibud.backends.tkinter`, `.pyside6`, `._qtmap`, `._vars` or `pyguibud.preview*` loads no toolkit. `backends/_qt.py` may import PySide6 at module level, and only `PySide6Backend.build()` imports it.
- The tkinter backend and the `--backend tkinter` child never import `ttkbootstrap`. This is tested in a subprocess. ttkbootstrap 2.2 subclasses the tkinter classes and does not patch them (checked in `.venv/.../ttkbootstrap/__init__.py`), so a plain `tkinter.Tk()` stays unthemed.

**Split (D1).** Each part has its own UAT (§12):

| Part | Contents | Estimate | Cap |
|---|---|---|---|
| **16a "tkinter + Toolkit menu"** | `backends/tkinter.py`, `_tkscrolled.py`, the `_tk.py` bootstyle note, entry points, `TkinterHost`, the host lookup, `describe(ui, backend)` + `portable_describe` (Tk reader), Preview ▸ Toolkit, `examples/show_ui.py` | ≈ 410 | 500 |
| **16b "Qt build"** | `_qtmap.py` (pure), `pyside6.py` (prepare/build, app ownership, no-display guard), `_qt.py` build: windows, layouts, widgets, units, images, texts and mnemonics, `alive/show/run/destroy` | ≈ 760 | 850 |
| **16c "Qt behaviour"** | `_vars.py` (pure `Var`), variable binding, events (signals + one event filter), menus/actions/shortcuts, `QtHost`, the Qt `portable_describe` reader, the cross-toolkit parity tests | ≈ 600 | 700 |

The estimates include about 30 % overshoot. Trims are applied in order when a part's running count projects past its cap:

| Trim | Part | Dropped (fallback behaviour) | Lines |
|---|---|---|---|
| T1 | 16a | "(not installed)" detection: every toolkit is listed, and the child reports `backend_unavailable` | −15 |
| T2 | 16a | `_tkscrolled` shim: ScrolledFrame is built as a Frame, with a log | −55 |
| T3 | 16b | `padx`/`pady` wrappers (D9 b: ignored, logged once) | −40 |
| T4 | 16b | size hints (D10 b: minimum sizes) | −30 |
| T5 | 16b | Label image + text composite (D14 b: image only, logged) | −25 |
| T6 | 16c | Tk-native `key:` sequences: only chord-form `key:` events are wired, the rest are logged | −30 |
| T7 | 16c | `Var.trace_remove` and `trace_info` (only `get`/`set`/`trace_add`) | −15 |

Not counted: tests (≈ 1,100), `.po` updates, `pyproject`/CI edits.

## 1. Decisions — recommended default in **bold** — **resolved 2026-10-12: all defaults (a)**
| ID | Question | Options |
|---|---|---|
| D1 | Split | **(a) three parts 16a/16b/16c (§0)**: the Qt session is at least the size of `_tk.py` (606 lines) plus variables, radio groups and the event filter, which is too much for one session (15a capped at 800) · (b) halves 16a/16b, with 16b capped at 1,300 and T3–T7 applied up front |
| D2 | tkinter backend | **(a) reuse `TkSession` as it is: a `tkinter`/`tkinter.ttk` class table (ttk for the ttk widgets; `tkinter` for Text, Listbox, Canvas, Menu and Toplevel), `tkinter.Tk()` root, `bootstyle=False`. About 70 lines** · (b) a separate builder (two sources of truth) |
| D3 | ScrolledFrame in tkinter | **(a) `_tkscrolled.ScrolledFrame`: Canvas + inner `ttk.Frame` + `ttk.Scrollbar`, with the ttkbootstrap surface `TkSession` already uses (`.container`, `auto_hide`, `height`, `padding`, mouse wheel). Imported only inside `build()`** · (b) a Frame + a log (T2) |
| D4 | `meta/@theme` in tkinter | **(a) applied only when it names a ttk theme of this Tk (`clam`, `alt`, `default`, `classic`, `vista`…), otherwise the platform default, silently (theme names belong to ttkbootstrap). The preview host reports `"themes": []`** · (b) always the platform default · (c) list the ttk themes in Preview ▸ Theme (preview-only, "Use this theme" disabled) |
| D5 | `tb:bootstyle` outside ttkbootstrap | **(a) one log per build: `NP_("{count} ttkbootstrap style (tb:bootstyle) is ignored by the {toolkit} toolkit.", "... styles ... are ignored ...")`** · (b) silent (FEATURES §3 "ignored"; but ADR-001 says "with a warning") · (c) one log per widget |
| D6 | Reporting a degradation (no equivalent) | **(a) a runtime warning through `plan.log`, at most once per (message, class) per build. The preview collects it into `ready.json` and the status bar shows it** · (b) backend-aware validator findings (`validate(..., backend=)`, a core API change) · (c) silent |
| D7 | Qt windows | **(a) main → `QMainWindow` (`setMenuBar`, `setStatusBar`, central body widget); dialog → `QDialog` with an outer `QVBoxLayout` (`setMenuBar`, body, status bar). Parent = the main window, else `master`. Non-modal, close = hide. Closing the main window ends the session, as a destroyed Tk root does** · (b) every window a `QMainWindow` with the `Qt.Dialog` flag |
| D8 | `QApplication` ownership | **(a) `master=None`: reuse a running `QApplication`, or create one that the session owns (`run()` = `exec()`; `destroy()` quits it). An existing non-GUI `QCoreApplication` → `backend_unavailable`. `master` must be a live `QWidget` (`shiboken6.isValid`). A call off the main thread → `backend_unavailable`. Linux/BSD with no `DISPLAY`, `WAYLAND_DISPLAY` or `QT_QPA_PLATFORM` → `NoDisplayError` before construction, because Qt aborts the process (qFatal) instead of raising** · (b) mirror Tk: an existing app + `master=None` → `root_exists` |
| D9 | Grid/pack `padx`/`pady` in Qt (no per-item padding) | **(a) only a widget with non-zero padding is wrapped in a margin `QWidget` (the outer); `ui.<id>` stays the widget** · (b) ignored, logged once (T3) |
| D10 | Requested sizes and Tk units | **(a) converted by `_qtmap.UNITS`: characters = `horizontalAdvance("0")` × n, lines/rows = `lineSpacing` × n, pixels as is. Applied as `sizeHint` through lazily created per-class subclasses, so the widget can still shrink and grow as in Tk** · (b) `setMinimumSize` (cannot shrink; T4) · (c) ignored |
| D11 | Float ranges (QSlider, QProgressBar and QSpinBox take integers) | **(a) Scale and Progressbar: an integer range of 10,000 steps mapped linearly to `[minimum, maximum]`, or 1:1 when the range is integral and ≤ 10,000 wide. Spinbox: always `QDoubleSpinBox`, with decimals from the increment, minimum and maximum (0 when all are integral). A reversed range (`minimum > maximum`) gives an inverted slider; a spin box sorts it and logs** · (b) round to integers |
| D12 | `ui.vars` in Qt | **(a) pure `backends/_vars.py` classes `StringVar`, `IntVar`, `DoubleVar`, `BooleanVar` with the tkinter subset `get()`, `set(v)`, `trace_add("write", cb) -> token`, `trace_remove("write", token)`. Callbacks get `(name, "", "write")`, as in tkinter. Two-way widget sync is loop-guarded. Handler code that reads `ui.vars.x.get()` runs on all three toolkits** · (b) a `QObject` with a Qt property and a `changed` signal (Qt-idiomatic, a different API) · (c) no variables in Qt (breaks ADR-001) |
| D13 | Radio groups | **(a) a `QButtonGroup` (exclusive) per bound variable. Unbound radios use Qt's per-parent auto-exclusivity (Tk shares one hidden global variable among them; a documented difference)** · (b) one group per window for unbound radios |
| D14 | Label with `image` and `text` (QLabel shows one or the other) | **(a) a composite: a `QWidget` with an icon `QLabel` and a text `QLabel` (`compound="left"`); `ui.<id>` = the text label** · (b) image only, logged (T5) · (c) a flat `QToolButton` |
| D15 | `focus_in`, `focus_out` and `key:` in Qt | **(a) one event-filter object per widget handles FocusIn, FocusOut and KeyPress against the mapped key list. It never consumes the key, as a Tk `bind` does not, except `activate` (`"break"`)** · (b) `QShortcut(WidgetShortcut)`: consumes the key from the widget |
| D16 | Preview hosts for forks | **(a) the built-in `HOSTS` for the three toolkits, plus an optional backend capability `preview_host() -> PreviewHost` (like `build_embedded`). `--backend` is checked against the id grammar, not `choices`, so an unknown name → exit 1 with `runtime.backend_unavailable`, not a usage error** · (b) only the three built-ins (a fork's backend needs a core patch to preview) |
| D17 | Preview ▸ Toolkit | **(a) a radio list of `registry.backends()` names (listed, never loaded in the designer). PySide6 is disabled as `PySide6 (not installed)` when `importlib.util.find_spec("PySide6")` is None. The choice is saved in `Settings.preview_backend` (unknown or malformed → `ttkbootstrap`). A saved toolkit that is not installed at start-up is kept in the settings but not used: the preview runs `ttkbootstrap`, and the status bar says so once (`{name} is not installed; the preview uses ttkbootstrap.`). A change restarts a running preview. Theme and "Use this theme in the document" are disabled when the toolkit is not ttkbootstrap, and `--theme` is not passed. A new "differs" reason: `the exported module uses ttkbootstrap`** · (b) a setting only, no menu |
| D18 | Qt style and Qt's own strings | **(a) the platform default `QStyle`; `meta/@theme` is ignored silently. Qt's built-in texts (context menus) are not translated in v1 (they would need `lang` in the `Session` contract)** · (b) always Fusion · (c) load `qtbase_<lang>.qm` (contract change: `apply_texts(..., lang)`) |
| D19 | Tests and CI | **(a) marker `qt`. `tests/qt/conftest.py` runs `importorskip("PySide6")`, sets `QT_QPA_PLATFORM=offscreen` and creates one session `QApplication`. CI: a new `qt` job per OS (Python 3.12, `uv sync --locked --extra pyside`) runs `pytest -m qt`, and the existing jobs run `-m "not qt"` (Tk and Qt never share a process on macOS). mypy gets `ignore_missing_imports` for `PySide6.*`/`shiboken6`, plus `disallow_subclassing_any = false` for `pyguibud.backends._qt`, `pyguibud.preview._host_qt`, `pyguibud.preview._describe_qt` and `tests.qt.*` (without the stubs, `QObject` is `Any`). So strict mypy passes with and without PySide6, and the `qt` job also runs mypy against the real stubs** · (b) PySide6 in the dev group for all 12 jobs (≈ 200 MB each; one process for both toolkits) |
| D20 | Module and entry-point names | **(a) as planned: `backends/tkinter.py`, `backends/pyside6.py`, entry points `tkinter` and `pyside6` (the ADR-004 factory keys), both also in `BUILTIN_BACKENDS`. A test checks that the backend's `tkinter` is the standard library's** · (b) `backends/tk_plain.py` (avoids the name echo) |

## 2. Module layout
| File | New/changed | Part | Notes |
|---|---|---|---|
| `src/pyguibud/backends/tkinter.py` | new | a | `TkinterBackend` (`name = "tkinter"`). `prepare`: `tkinter._default_root` alive → `RootExistsError`; `master` must be a live `tkinter.Misc`. `build`: the class table, `make_root=tkinter.Tk` (`TclError` → `NoDisplayError`), `apply_theme` per D4 |
| `src/pyguibud/backends/_tkscrolled.py` | new | a | D3 shim. Imports tkinter at module level and is imported only by `TkinterBackend.build` |
| `src/pyguibud/backends/_tk.py` | changed (≈ 10 lines) | a | D5: with `bootstyle=False`, count the `tb:bootstyle` attributes and log once at the end of `build`. Nothing else changes |
| `src/pyguibud/backends/__init__.py`, `pyproject.toml` | changed | a, b | `BUILTIN_BACKENDS` + `[project.entry-points."pyguibud.backends"]`: `tkinter` (a), `pyside6` (b); mypy override (D19) |
| `src/pyguibud/backends/_qtmap.py` | new, **pure** | b, c | `alignment(sticky)`, `pack_item(orient, fill, expand)`, `qt_text(text, underline, mnemonic)`, `escape_title`, `UNITS`, `SELECTMODE`, `scaled_range`, `qt_key_sequences(seq) -> tuple[str, ...]` (from `core.keys.key_bindings`), `qt_shortcut` |
| `src/pyguibud/backends/pyside6.py` | new | b | `PySide6Backend` (`name = "pyside6"`): `prepare`/`build` per D8; imports `_qt` inside `build` |
| `src/pyguibud/backends/_qt.py` | new | b, c | `QtSession` (the `Session` protocol), `_Filter(QObject)`, hinted subclasses, the class adapter table (§4.3) |
| `src/pyguibud/backends/_vars.py` | new, **pure** | c | D12 variable classes; no toolkit |
| `src/pyguibud/preview/_host.py` | changed | a, c | `_TkHost` base shared by `TtkbootstrapHost` and `TkinterHost` (no themes); `QtHost` (c) in `_host_qt.py`; `host_for(name) -> PreviewHost` (D16) |
| `src/pyguibud/preview/_describe.py` | changed | a, c | `describe(ui, backend="ttkbootstrap")` (the default keeps `test_parity_describe.py` and the generated-module harness unchanged; tkinter reads `ttk.Style().theme_use()`); `portable_describe(ui, backend)` (§7); the Qt reader in `_describe_qt.py` (c) |
| `src/pyguibud/preview/__init__.py` | changed | a | `--backend` id grammar (D16); `--theme` ignored when the host has no themes |
| `src/pyguibud/designer/preview.py`, `preview_tk.py`, `standard_actions.py`, `settings.py` | changed | a | D17: the Toolkit sub-menu, `R_TOOLKIT`, `Settings.preview_backend` validation, Theme items disabled |
| `examples/show_ui.py` | new | a | `python examples/show_ui.py FILE [--backend NAME] [--lang CODE]`: `load_ui` with no-op handlers, then `run()`. The 16a/16b UAT viewer |

## 3. tkinter backend (16a)
- **Class table:** `ttk.{Frame, Labelframe, Notebook, Panedwindow, Label, Button, Entry, Checkbutton, Radiobutton, Combobox, Spinbox, Scale, Progressbar, Separator, Treeview, Scrollbar}`, `tkinter.{Text, Listbox, Canvas, Menu, Toplevel}` and `_tkscrolled.ScrolledFrame`. It reuses `_tkmap._CLASSES`/`_RENAMED`.
- **Everything else is `TkSession`:** layouts, events, variables (real `tkinter` variables), mnemonics, clipping, images (`PhotoImage`), menus, shortcuts and includes. So parity with ttkbootstrap is structural by construction.
- **Differences from ttkbootstrap:** the look (ttk default theme); `tb:bootstyle` ignored (D5); the `tb:` extension widgets show their fallbacks (`registry.resolve(..., "tkinter", ...)` already logs `_M_FALLBACK`).

## 4. PySide6 backend (16b, 16c)
### 4.1 Application, windows, session
- **`prepare(master)`** imports `PySide6.QtWidgets` (`ImportError` → `backend_unavailable`). The `reason` is the translated `PySide6 is not installed. Install it with: pip install "pyguibud[pyside]"`. It then applies the D8 checks.
- **`build`:**
  1. The display guard, then the `QApplication` (owned or reused).
  2. A warning when a live Tk root exists in the process: `Tk and Qt windows in one process: only one toolkit's windows respond at a time.`
  3. Variables, pixmaps, windows (D7), texts. Signals are connected **after** the initial values are set, so building fires nothing (Tk's `_arm` equivalent).
- **Every `.ui` window is a top-level** (`Qt.Window` flag when it has a parent). `min_width`/`min_height` → `setMinimumSize`. The title goes through `escape_title` (a literal `[*]` stays visible).
- **Status bar:** a `QStatusBar` with a permanent `QLabel` (stretch 1). `ui.<statusbar id>` = that label, as in Tk.
- **Session:**
  - `alive()`: every window passes `shiboken6.isValid` and the main window was not closed.
  - `show(id)`: `show()` + `raise_()` + `activateWindow()`; returns None.
  - `run()`: `exec()` when the session owns the app and no loop is running (otherwise it returns at once).
  - `destroy()` (idempotent): `deleteLater` on what it created, `processEvents`, and `quit()` if owned.
  - Closing the main window → `destroy()` (Tk parity).

### 4.2 Layouts (ADR-005)
- **Grid:**
  - `QGridLayout`, `setContentsMargins(padding)`, `setHorizontalSpacing(gap)`/`setVerticalSpacing(gap)`. Qt's style-dependent defaults are always overwritten, so 0 means 0, as in Tk.
  - `setColumnStretch(i, weight)`, `setColumnMinimumWidth(i, minsize)` (rows alike).
  - `addWidget(outer, row, column, rowspan, columnspan, alignment(sticky))`. In `_qtmap.alignment`, an axis with both sides (`ew`/`ns`) gets no flag (fill), one side gets that Align flag, and none gets centre. A fill on an axis whose size policy is Fixed (e.g. a `QPushButton` vertically) switches that axis to Preferred.
  - When no column (row) has a weight > 0, a stretch-1 spacer column (row) is added after the last one, so extra space stays unused as in Tk.
- **Pack:**
  - `QVBoxLayout`/`QHBoxLayout`, margins = padding, spacing = gap.
  - `addWidget(outer, stretch=1 if expand else 0, alignment)`. Across the axis: fill → no flag, else centre. Along the axis: expand without fill → centred in its parcel.
  - When no child expands, `addStretch(1)` at the end.
- **Pages:**
  - Notebook → `QTabWidget.addTab(child, icon, qt_text(text, underline, True))`.
  - PanedWindow → `QSplitter(orient)`, `setStretchFactor(index, weight)`.
- **Padding (D9 a):** the outer margin widget carries `padx`/`pady` (both sides, as Tk's tuple). The grid lead gap stays on the layout spacing.
- **Includes:**
  - an `<include>` becomes a `QWidget` with the component window's layout, attached as `component.id` in the child scope and as the include id in the host scope;
  - it shares the host's variables, or makes its own, as `_tk._include` does;
  - the preview's synthetic `preview_host` dialog then needs nothing new.

### 4.3 Widget table (one adapter per class: create, props, text setter, variable binding, events)
| Core class | Qt | Properties | Events → signal | Degradations |
|---|---|---|---|---|
| Frame | `QFrame` | width/height px → hint only when it has no children (Tk propagation) | — | — |
| LabelFrame | `QGroupBox` | text (plain, `&` escaped) | — | — |
| Notebook | `QTabWidget` | width/height px | select → `currentChanged` | — |
| PanedWindow | `QSplitter` | orient | — | — |
| ScrolledFrame | `QScrollArea` (`widgetResizable`) + inner `QWidget` = `ui.<id>` | height px; autohide → `ScrollBarAsNeeded`/`AlwaysOn` | — | — |
| Label | `QLabel` (**PlainText**) | text, image (pixmap), width chars | — | image + text → D14 |
| Button | `QPushButton` | text (mnemonic), image (`setIconSize` = pixmap size), state, width chars | command → `clicked` | — |
| Entry | `QLineEdit` | width chars; state normal/disabled/readonly → `setEnabled`/`setReadOnly`; show → `Password` echo | change → var or `textChanged`; activate → `returnPressed` | the mask character is the platform's (silent) |
| Text | `QPlainTextEdit` | width chars, height lines; wrap none/char/word → `NoWrap`/`WrapAnywhere`/`WordWrap`; disabled → read-only | change → `textChanged` | — |
| Checkbutton | `QCheckBox` | text (mnemonic), state | command → `clicked`; change → var | — |
| Radiobutton | `QRadioButton` + D13 group | text (mnemonic), value, state | command → `clicked`; change → var (else `toggled(True)`) | — |
| Combobox | `QComboBox` (editable unless readonly) | width chars, state | select → `activated`; change → var | — |
| Spinbox | `QDoubleSpinBox` (D11) | minimum, maximum, increment, width chars, state | change → var or `valueChanged` | bound to a string variable: a non-numeric value cannot be shown (logged) |
| Scale | `QSlider` (D11) | minimum, maximum, orient, length px | change → var or `valueChanged` | resolution 1/10,000 of the range |
| Progressbar | `QProgressBar` (`textVisible=False`) | maximum, value, mode (indeterminate → range 0..0), orient, length px | — | — |
| Separator | `QFrame` `HLine`/`VLine`, `Sunken` | orient | — | — |
| Listbox | `QListWidget` | height lines; selectmode browse/single → Single, multiple → Multi, extended → Extended | select → `itemSelectionChanged`; activate → `itemActivated` | — |
| Treeview | `QTreeWidget` | height rows; show tree → header hidden, headings → `rootIsDecorated(False)`; selectmode → Single/Extended/No | select, activate as Listbox | — |
| Scrollbar | `QScrollBar` | orient | change → `actionTriggered` (user only, like Tk `command`) | — |
| Canvas | `QGraphicsView` + scene | width/height px; background → `QColor` | — | a Tk colour name Qt does not know (`SeaGreen3`, `gray57`): logged, default background |
| Menu / Action | `QMenu` / `QAction` (16c) | text (mnemonic), image (icon), state, `shortcut` → `qt_shortcut` (Ctrl = Command on macOS, as Tk aqua) | command → `triggered` | a duplicate shortcut in one window: the same `_M_SHORTCUT` log, and only the first is set |

`focus_in`/`focus_out`/`key:` (any class that lists them) use the D15 filter. Every handler is wrapped as `lambda *_: fn()`, so Qt signal arguments never reach user code. An exception in a handler is printed by PySide6 and the loop goes on (the same as Tk; tested).

### 4.4 Variables (16c, D12)
- The `_vars` classes hold typed values (int, float, bool, str; the defaults are parsed as in `_tk._make_vars`). `ui.vars.<id>` and `Instance.vars` get them. Includes share the host's variables as in Tk.
- **Binding:**
  - widget → var on the user/programmatic change signal;
  - var → widget on `set`;
  - a per-binding guard stops the echo;
  - `set` always notifies, even with an equal value, as a Tk trace does.
- **Conversion failure** (an `IntVar` bound to an Entry showing `abc`): the variable keeps its last value and nothing fires. Tk instead raises at `get()`; this is a documented difference.
- A `change` event on an unbound Entry, Combobox, Spinbox, Scale or Checkbutton connects to the widget signal directly (Tk's private trace variable, `_TRACE_VAR`).

### 4.5 Texts, mnemonics, i18n
- **`apply_texts`** keeps the `_tk.py` contract: compute and clip (`clip_text`, same log) every slot first, then set. All-or-nothing.
- **`_qtmap.qt_text`:**
  - for widgets that interpret `&` (buttons, checks, radios, group-box titles, tabs, menus, actions), it doubles every `&`, then inserts `&` before the `split_mnemonic` index;
  - `QLabel`, the status bar and window titles get the text verbatim, with `PlainText`.
  - Tested with texts holding `&`, `_`, `__` and `<b>`.
- `retranslate` therefore works unchanged through `LoadedUi`.

## 5. Preview child and designer
- **`host_for(name)`:** `HOSTS` = `{"ttkbootstrap", "tkinter", "pyside6"}`, else the backend class's optional `preview_host` (D16), else `runtime.backend_unavailable`.
- **`TkinterHost`:** `_TkHost` with `tkinter.Tk()`, `themes() = []`, `current_theme() = ""`, `set_theme() = False`.
- **`QtHost` (16c):**
  - `prepare`: no main window → a hidden parentless `QWidget` as `master`;
  - `attach`: show only the chosen window; an event filter on Close calls `on_close`;
  - `schedule` = `QTimer.singleShot`, `update` = `processEvents`, `run` = `exec`, `lift` = `raise_` + `activateWindow`, `close` closes all and `quit()`;
  - `themes() = []`.
- **`ready.json` and `result.json`** are unchanged. The stdin thread still only fills the queue.
- **Designer (D17):** `PreviewRequest.backend` comes from `Settings.preview_backend`. `prepare_preview` adds `R_TOOLKIT` when the toolkit is not ttkbootstrap and drops a theme override. Preview ▸ Toolkit is a radio group after Language; the labels are the toolkit names (proper nouns, untranslated) plus `{name} (not installed)`.

## 6. Error and abuse cases (each is blocked or reported with a translated reason; nothing crashes)
| # | Abuse | Required behaviour |
|---|---|---|
| B1 | `backend="pyside6"` without PySide6 (runtime or preview) | `runtime.backend_unavailable` with the install hint; the designer item is disabled (D17) |
| B2 | PySide6 on Linux with no display | `runtime.no_display`, never a process abort (D8 guard; tested with the environment cleared) |
| B3 | `load_ui(..., backend="pyside6")` from a worker thread | `runtime.backend_unavailable` (`must run in the main thread`) |
| B4 | A label, title or translation holding `<img src="file:///…">`, `<a href>`, `<b>` | shown literally (PlainText everywhere); no file or network access |
| B5 | `&`, `[*]`, 200,000 characters in texts | literal `&` and `[*]`; clipped with the existing log |
| B6 | `tb:bootstyle` on 500 widgets with tkinter or Qt | one log line (D5) |
| B7 | A Tk colour name Qt does not know | logged; default background |
| B8 | An image that passed the validator but Qt cannot decode | logged; no image; the build goes on |
| B9 | Tk and Qt interfaces in one process | both build; the mixed-toolkit warning (§4.1, build step 2) is logged once |
| B10 | `load_ui` twice with pyside6; `run()` while a loop runs | a shared `QApplication`; `run()` returns at once |
| B11 | Closing the main window while a dialog is shown | the whole session ends (Tk parity); `ui.<x>` use afterwards → `runtime.destroyed` |
| B12 | An `IntVar` Entry receives `abc` | no exception, no `change` call, the variable unchanged |
| B13 | `minimum > maximum` on Scale or Spinbox | inverted slider / sorted spin range + log; no crash |
| B14 | `settings.json` hand-edited: `preview_backend` = `"pyside6; rm -rf"`, `""` or 10 KB | id grammar + length check → `ttkbootstrap`; argv is a list anyway |
| B15 | A third-party backend crashes on load or has no host | `registry.backend_failed` / `backend_unavailable` in the status bar; the designer is unaffected (P5 rules) |
| B16 | 10,000 widgets with pyside6 | builds in ≤ 5 s (`slow`) |

## 7. Test plan
**Pure (every CI job, no toolkit):**
- `_qtmap`: alignment for all 16 sticky forms; pack items; `qt_text` (hypothesis: stripping the `&` markers gives back the display text, and the mnemonic index survives); `escape_title`; `scaled_range` round-trips; `qt_key_sequences` for every modifier (`Control Alt Shift Option Command Meta`) and every keysym of `core.keys` (letters case-sensitive: `<Control-S>` → `Ctrl+Shift+S`). On macOS, Tk `Command` → Qt `Ctrl` (⌘) and Tk `Control` → Qt `Meta`, and chords follow Tk aqua (Ctrl = ⌘). Elsewhere `Control` → `Ctrl` and `Option` → `Alt`; every `UNITS` row.
- `_vars`: `set`/`get`/`trace_add`/`trace_remove`, notify on an equal value, callback arguments.

**Boundary:** `test_import_boundary` gains `pyguibud.backends.tkinter, .pyside6, ._qtmap, ._vars` and `pyguibud.preview._host`. A subprocess builds `examples/hello.ui` with `--backend tkinter --describe` and asserts `ttkbootstrap not in sys.modules`.

**tkinter (`gui`):**
- ttkbootstrap 2.2 does not patch tkinter, so the structural tests run in-process with `master=tk_root`. Only the own-root case (`prepare(None)` against the session `App` → `RootExistsError`) and the no-ttkbootstrap check run in a subprocess.
- every class of the `rich` fixture builds;
- the `test_tk_build.py` event, retranslate and failed-build cases parametrised with `backend` in (`ttkbootstrap`, `tkinter`);
- ScrolledFrame shim scrolls; `tb:bootstyle` gives one log.

**Qt (`qt`, offscreen):**
- every class and layout;
- the **event matrix**: for each `(class, event)` pair of the core specs, trigger it (`QTest`/signal emit) and assert exactly one handler call; Tk has the same matrix through `event_generate`/`invoke`;
- variables both ways and B12;
- radio groups;
- mnemonics and PlainText (B4/B5);
- B2 (environment cleared, in a subprocess), B3, B10, B11;
- the handler exception keeps the loop running;
- `destroy` idempotent; 20 build/destroy cycles leak no top-levels.

**"Same `.ui` in 3 toolkits" (the UAT proof):**
- `portable_describe(ui, backend)` reads the **built toolkit objects**, not the model:
  - windows: kind, title, minimum size, status text, menu tree (text, mnemonic, shortcut, enabled, separator, image flag);
  - per id: core class, display text + mnemonic, `state` as the `.ui` value (`normal`/`disabled`/`readonly`, read per class: Qt `isEnabled`/`isReadOnly`, so a disabled Text that is read-only in Qt compares equal), image flag, parent id, placement (grid cell + spans + sticky / pack index + fill + expand / page index + text), the bound variable's value.
- For `examples/hello.ui` and `tests/codegen/data/{hello,includes,dialogs,events,images}.ui`, in `None` and `de_DE`, the three backends give **equal** results.
- An explicit allow-list covers the documented differences (D13 unbound radios, D11 resolution).
- The existing ttkbootstrap ↔ generated-module parity (preview-export §9) is unchanged.

**Designer (`gui`):**
- the Toolkit sub-menu reflects the setting;
- PySide6 is disabled with `find_spec` faked to None;
- a toolkit change restarts a fake runner with `--backend`;
- the Theme items are disabled for tkinter/pyside6; `R_TOOLKIT` appears; B14.

## 8. Step 17 seam (not built here)
- **The extension point:** `TkSession._create` and the Qt adapter lookup are the only places where a class becomes a toolkit object. Step 17 plugs `spec.factories[backend]` in there. The keys are exactly `ttkbootstrap`, `tkinter` and `pyside6`.
- **Proposed factory contracts:**
  - Tk: `factory(parent, options) -> widget`;
  - Qt: an adapter `(create(parent) -> (outer, inner), set_text, bind_var, signal(event))`.
- **`WidgetSpec.bind_types`** (validate-commands §5.1) is needed for plugin bindings.
- **FEATURES §3 mismatch:** it lists `QDateEdit`/`QTableWidget` as PySide6 *fallbacks*, but fallbacks are core classes (ADR-001), so these would be Qt factories of the `tb:` widgets. Step 17 decides.

## 9. i18n
- **Gates:** `_()`/`N_()`/`NP_()` with named placeholders, all 8 locales, and `en_XA` fit checks for the Toolkit menu.
- **New msgids:**
  - the D5 plural;
  - the D6 degradation texts: Label image + text, colour name, image decode, Spinbox string, reversed range, padding ignored, Tk-native key (T6);
  - B1–B3 and B9;
  - `R_TOOLKIT`;
  - `{name} (not installed)` and `{name} is not installed; the preview uses ttkbootstrap.`;
  - `_Toolkit`.
- Toolkit names stay untranslated.

## 10. Packaging
- No new dependency. `PySide6>=6.6` stays the `[pyside]` extra. `uv.lock` already pins PySide6 6.11.2; the 16b implementer confirms in the `qt` job that wheels exist for every CI Python (3.10–3.13).
- **Step 20 note:** the future `pyguibud-runtime` distribution needs its own `[pyside]` extra, and both backends ship with it (ADR-007 is unchanged).

## 11. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | Users expect pixel-identical windows; Qt and Tk metrics differ | "Same" is defined by `portable_describe` (§7) plus a documented differences list; D9/D10 keep the geometry intent |
| R2 | Headless and CI fragility: Qt aborts without a display, Tk + Qt in one process on macOS, PySide6 wheels per Python/OS, strict mypy without stubs | the D8 guard; the D19 separate `qt` job and invocation; `importorskip`; mypy override |
| R3 | Semantics drift between toolkits (when `change` fires, variable conversion, radio groups) | one shared event matrix and the variable tests run on all backends; differences listed in §4.4 and D13 |
| R4 | The 16b/16c size (the Qt session is the largest module of the step) | three parts (D1), caps, trims T3–T7 |
| R5 | `backends/tkinter.py` echoes the stdlib name | absolute imports only; a test asserts the stdlib module (D20) |

## 12. UAT (for the user)
**16a:**
1. `uv run python examples/show_ui.py examples/hello.ui --backend tkinter`: a plain-looking window with the same widgets, menu and status bar. Repeat with `--lang de_DE` and `--lang en_XA`. `show_ui.py tests/codegen/data/dialogs.ui --backend tkinter` shows the dialogs (hidden root).
2. In the designer, Preview ▸ Toolkit ▸ tkinter, then F5: the same window; the status bar says it differs from the export (toolkit); the Preview ▸ Theme entry and "Use this theme in the document" are greyed.
3. Alt+P: every Preview menu item has its own underlined letter (Tool**k**it, **T**heme).
4. Break it: switch Toolkit ten times quickly with a preview open → one preview, last choice. Close the designer, set `"preview_backend": "qt5"` in `%APPDATA%\pyguibud\settings.json`, restart, F5 → ttkbootstrap preview and one status note; restore the file. `show_ui.py examples/hello.ui --backend bogus` and `--lang ""` → a one-line reason, no traceback.
(The PySide6 "(not installed)" item moved to 16b, when the `pyside6` entry point exists — QA-16a-11.)

**16b:**
1. Without PySide6 (`uv sync`), Preview ▸ Toolkit shows PySide6 greyed "(not installed)". Then `uv sync --extra pyside`.
2. `show_ui.py` with `--backend pyside6` on `examples/hello.ui` and on `tests/codegen/data/dialogs.ui`: the same layout, texts and menus as with ttkbootstrap, side by side. Alt shows the mnemonics.
3. Resize the window: the same widgets stretch.

**16c:**
1. Preview ▸ Toolkit ▸ PySide6 + F5: type a name and use a menu shortcut; nothing crashes (handlers are no-ops). Language ▸ Deutsch switches live.
2. `uv run pytest -m qt` is green.
3. Break it: with PySide6 chosen, quit and run `uv sync` (no `--extra pyside`), then restart the designer. Preview ▸ Toolkit ▸ PySide6 is greyed "(not installed)", and F5 previews with ttkbootstrap; the status bar says so. Then `uv sync --extra pyside` again.

## 13. Open questions
1. D1: three parts instead of the plan's two halves. The plan row 16 needs the orchestrator's update.
2. FEATURES §3 rows to amend after acceptance: Spinbox → `QDoubleSpinBox` only; ScrolledFrame tkinter → the canvas shim; the PySide6 fallbacks note (§8).
3. Should `examples/run_hello.py` (it uses Tk-only `configure`/`bind`) gain a Qt branch, or is `show_ui.py` enough for v1?

## 14. QA rulings (16a, orchestrator, 2026-10-12)
- **D17 clarified (QA-16a-02):** a saved `preview_backend` that is well-formed but not usable now (not listed by the registry — a hand-edited `qt5`, an uninstalled fork — or `pyside6` without PySide6) is kept in the settings and not used: the preview runs ttkbootstrap and the status bar says so once. Only a malformed value loads as `ttkbootstrap`.
- **One backend-name rule (QA-16a-05):** `[a-z][a-z0-9_-]{0,31}`, a single constant shared by the designer and the child. A name outside it gives `backend_unavailable`, never an argparse usage error.
- **Access keys (QA-16a-01):** `Tool_kit` (K), so it no longer clashes with `_Theme`.
- **`show_ui.py` (QA-16a-08):** a dialog-only document gets a hidden root, so it doubles as the 16b viewer.
- **Theme greying (QA-16a-10):** the Preview ▸ Theme cascade entry itself is disabled for non-ttkbootstrap toolkits.
- **Deferred:** QA-16a-13 (`show_ui.py --backend ttkbootstrap` on a dialog-only document ignores `meta/@theme` because the hidden root is a plain `tkinter.Tk()`; use a `ttkbootstrap` root there) → 16b, with the Qt hidden root. QA-16a-11 → 16b UAT item 1; QA-16a-12 (the designer shows `ready.json` warnings such as the D5 bootstyle note in the status bar) → 16c, with the Qt degradation warnings of D6.
