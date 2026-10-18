# Spec — Step 17: Widget plugin API + ttkbootstrap extensions

- **Status:** Accepted (user, 2026-10-14: D1–D21 all recommended defaults (a), including the six ★ choices; split 17a/17b/17c with caps 650/600/600 and trims T1–T7) · **ADR:** ADR-015 (Accepted). It amends ADR-004 (the factory contract) and ADR-008 (native `tb:` emission). It builds on ADR-001 (fallbacks), ADR-006 (the validator is the only home of rules), ADR-007 (boundary) and ADR-014 (the backends and the §8 seam).
- **Owner:** BACKEND (core, registry, backends, codegen) + FRONTEND (designer) · **Reviewer:** SOFTWARE-ARCHITECT
- **Budget:** ≈ 1,590 production lines over three parts. The caps are 650 + 600 + 600 = 1,850 (§0).
- **Plan row 17:** `pyguibud.widgets` entry points, `WidgetSpec`, isolation/placeholder, a diagnostics panel, `tb:` Meter/Floodgauge/DateEntry/Tableview/ToggleButton with fallbacks, and the sample plugin `examples/acme_plugin`. UAT:
  - `pip install -e examples/acme_plugin` → the widget appears in the palette;
  - break it on purpose → a placeholder, and the designer keeps running;
  - open the `.ui` with the tkinter backend → the fallbacks render.

## 0. Scope fence, budget and split
**What exists already (as built):**
- `core/registry.py` discovers `pyguibud.widgets` and isolates `Exception` at load time into `Diagnostic`s. It checks the API version, the prefix, the display name, duplicates and that the fallback is a core class with the same container kind.
- `Registry.resolve()` returns the fallback when the backend has no factory (`registry.no_factory`) or when the plugin is missing (`registry.plugin_missing`).
- The validator's fallback mode (R25–R29) and `new_node` (`fallback=`, `plugin=`) work.
- **Gaps:**
  - `_tk.py::_create` indexes `self._classes[name]` (a KeyError for any extension that has a factory);
  - `_qt.py` calls `getattr(self, f"_make_{name}")`;
  - `codegen/_emit.py:352` forces the fallback;
  - a factory that raises takes down the whole window build: `engine.build` destroys the session and re-raises;
  - `SystemExit` raised by a plugin import kills the designer;
  - load failures are the only kind of diagnostic: nothing records failures after load;
  - the palette labels every extension "(plugin)", `tb:` included;
  - nothing shows the diagnostics.

**In:**
- the final `WidgetSpec`/`PropertyDef` shape;
- lazy factory references;
- per-widget isolation in the Tk, Qt and design builds;
- the five `tb:` widgets (ttkbootstrap factories, native codegen);
- `tb:` attribute validation and `SetExtraAttr`;
- the designer's Plugins dialog, safe mode and the disabled list;
- `examples/acme_plugin`.

**Out:**
- a schema bump (none is needed);
- Qt factories for `tb:` widgets (D11);
- importing plugin modules in generated code (D13);
- plugin palette icons (D21);
- a hot reload of plugins (a restart is needed after an install);
- translating ttkbootstrap's own strings (D18);
- the runtime distribution split (Step 20).

**Hard constraints:**
- `pyguibud.core` stays stdlib-only. Built-in factories are `"module:attr"` strings into `pyguibud.backends._tbwidgets`, which imports ttkbootstrap only inside its functions.
- Opening a `.ui` never imports anything the file names: `plugin=` is display text, never an import target.
- ADR-007: `pyguibud_runtime` may load plugin entry points (installed code = trusted). The import-boundary test gains the registry load (§10).
- Tests never depend on installed plugins: they inject `Registry(entry_points=...)`. An installed acme must not change the palette, golden or boundary tests.

**Split (D1).** Each part has its own UAT (§12). The estimates already include the 30–40 % overshoot seen in 16a–16c. The caps are firm, and the trims are applied in order when the running count projects past a part's cap.

| Part | Contents | Estimate | Cap |
|---|---|---|---|
| **17a "Plugin API (headless)"** | `WidgetSpec.bind_types`, `FactoryRef`, `PropertyDef.pattern/max_length/hint`, `BACKEND_NAME` moved to core; registry changes (built-in detection, reserved `tb`, the `disabled` filter, `SystemExit`, parity checks, `load_factory`, `report_failure`, `failed_distributions`, `revision`); the `tb_widgets()` data; validator R83–R91 and `bind_types`; `SetExtraAttr`; the `tb` entry point | ≈ 560 | 650 |
| **17b "Factories and codegen"** | the `_tk.py` extension path + guard + the Embed failure hook; `backends/_tbwidgets.py` (5 factories) + the pure `_tkmap.TB_EXT` table; the `_qt.py` factory path + guard; native `tb:` codegen + support helpers; `describe` for `tb:` classes | ≈ 510 | 600 |
| **17c "Designer and sample plugin"** | the Plugins dialog + presenter, the Help menu item, the start-up note; `Settings.disabled_plugins` + `pyguibud --no-plugins`; the palette plugin flag; the canvas failure card; the inspector Bootstyle row (`SetExtraAttr`); `examples/acme_plugin` | ≈ 520 | 600 |

| Trim | Part | Dropped (fallback behaviour) | Lines |
|---|---|---|---|
| T1 | 17b | Tableview factory: `tb:Tableview` is registered without factories, so it shows as Treeview everywhere and the heading helper goes too | −80 |
| T2 | 17b | the Qt factory path: plugin `pyside6` factories are ignored (`registry.no_factory`, fallback); acme drops its Qt factory | −75 |
| T3 | 17b | native `tb:` codegen: the export shows the fallbacks with `codegen.extension_fallback` (today's behaviour) | −110 |
| T4 | 17a | R91 `fallback_differs`, `registry.slow_plugin`, `registry.toolkit_imported` | −30 |
| T5 | 17c | the inspector Bootstyle row (`SetExtraAttr` stays, tested headless; bootstyle is edited in the XML) | −70 |
| T6 | 17c | the per-plugin Disable toggle in the dialog (`disabled_plugins` in `settings.json` and `--no-plugins` still work) | −50 |
| T7 | 17c | the canvas failure card: the canvas builds the fallback, and the status bar plus the dialog name the failure | −40 |

**Calibration:** the 16a–16c actuals ran 1.25–1.64× the raw estimates (653/410, 954/760, 985/600). The figures above are raw × ≈ 1.3, so expect T1–T3 to be needed. 1,850 is not comfortable headroom.

**Sequencing rule:**
- **17a** ships `tb_widgets()` with `factories={}`. Until 17b lands, `resolve()` returns the fallback (`registry.no_factory`), so the canvas, the preview and `load_ui` never reach `_create` with a `tb:` name (today that is a KeyError).
- **17b** adds the refs together with `_tbwidgets` and the builder path.
- **17a also** extends the `_ensure_core` safety net to `tb_widgets()`, so the widgets exist even before `uv sync` refreshes the entry points.

**Known 17a test churn.** 29 test references use `tb:Meter` as an *unregistered* extension stand-in:
- tests: `test_core_model`, `test_core_registry`, `test_validate`, `test_xml_*`, `test_commands_roundtrip`, `test_tk_build`, `test_qt_build`, `designer/test_sizing`, `test_targets`;
- goldens: `validate/r25`, `r26`, `r28_plugin_missing.ui`, `xml_io/foreign.*.ui`, `codegen/data/rich.ui`.

Where a test means "a plugin that is not installed", it switches to `zz:Gauge`. Where it means `tb:Meter`, the golden is regenerated: R28 disappears for `tb:Meter`, and `rich.ui` exports a native Meter in 17b.

Not counted: tests (≈ 1,200), `.po` updates, `pyproject`/CI edits and the acme `pyproject.toml`. The acme Python module **is** counted (≈ 110).

## 1. Decisions — recommended default in **bold**; ★ = was the user's choice — **resolved 2026-10-14: all defaults (a)**
| ID | Question | Options |
|---|---|---|
| D1 | Split | **(a) three parts 17a/17b/17c (§0)** · (b) two halves (registry + validator / everything else), with 17b capped at 1,100 |
| D2 | Where the `tb:` specs live | **(a) a second built-in entry point `tb = "pyguibud.core.widgets:tb_widgets"`. "Built-in" becomes "the distribution name normalises to `pyguibud` **and** the value starts with `pyguibud.core.widgets:`" (a value prefix alone is spoofable by a third-party `pyguibud.foo` module, and built-ins bypass safe mode and the disabled list). The `tb` prefix is reserved for built-ins (`registry.reserved_prefix`). Built-in specs keep `plugin=None`, so `new_node` writes no `plugin=` and the palette does not say "(plugin)"** · (b) inside `core_widgets()` (no dogfooding) · (c) a separate `pyguibud-tb` distribution |
| D3 | Factory references | **(a) `factories: Mapping[str, Callable \| str]`. A string is `"module.path:attr"`, checked against `^[A-Za-z_][\w.]*:[A-Za-z_]\w*$` at registration, imported by `Registry.load_factory(spec, backend)` only when a widget is built, cached, with failures isolated. Keys follow `BACKEND_NAME` (moved to `core.model`, re-exported by `backends`)** · (b) callables only (the core would have to import the backends, or the plugin module would import its toolkit eagerly) |
| D4 | Factory contract | **(a) "renders as itself, behaves as its fallback":<br>• Tk: `factory(parent, props, variable, bootstyle) -> widget \| (outer, inner)`;<br>• Qt: `factory(parent, props) -> QWidget \| (outer, inner)`, where `inner` must be an instance of the fallback's Qt class.<br>The builder then wires text, state, variable (Qt) and events on `inner` exactly as for the fallback class. Plain arguments only (§4.1), so generated code could call a factory without PyGUIbud** · (b) a full adapter protocol per backend (`create/set_text/bind_var/signal`): more power, ≈ +150 lines, two contracts to keep stable |
| D5 | Fallback parity, checked at registration | **(a) `events` ⊆ the fallback's events; `bind_types` ⊆ the fallback's `BIND_TYPES` row; the same container kind (already checked). A violation → diagnostic `registry.not_fallback_compatible`, and the spec is ignored. Reason: R25 "the file must open everywhere". A file valid with the plugin must stay valid without it (no R42 or R36 surprises)** · (b) no check (validation then depends on what is installed) |
| D6 ★ | What a failing factory shows | **(a) design canvas: a non-container shows a placeholder card (the include-card pattern, `engine.py:330`) "acme:Gauge — the plugin failed"; a container shows its fallback, so its children stay editable. Preview, `load_ui` and `show_ui`: the fallback is built + `plan.log` (`runtime.plugin_failed`). One registry diagnostic per (class, backend)** · (b) the fallback everywhere, flagged only in the status bar and the dialog (= T7) · (c) a card everywhere (breaks `ui.<id>` for handler code) |
| D7 | Isolation scope and hangs | **(a) catch `Exception` **and `SystemExit`** at `ep.load()`, at the spec callable, in `load_factory` and around each factory call (`KeyboardInterrupt` propagates). No in-process timeouts (a Python thread cannot be killed safely). Instead:<br>• safe mode `pyguibud --no-plugins` (every non-built-in entry point skipped);<br>• `Settings.disabled_plugins` (normalised distribution names, filtered **before** `ep.load()`; a change takes effect on restart);<br>• an import slower than 2 s → warning `registry.slow_plugin`.<br>The preview child keeps its existing ready timeout** · (b) load plugins in a probe subprocess at start-up (+1 s start, about 120 lines) |
| D8 | `bind_types` | **(a) `bind_types: tuple[VariableType, ...] \| None = None`, honoured for extensions only; `None` = the fallback's row. The core classes keep `validate.BIND_TYPES` (one table, no churn)** · (b) move `BIND_TYPES` into the core specs |
| D9 | Constrained string properties | **(a) generic `PropertyDef.pattern` (a regex, full match), `max_length` (default 256 when `pattern` is set) and `hint` (a msgid). `max_length` is checked before the regex (ReDoS guard). New rules R89/R90 (errors). The `tb:` format, date and column properties use them, so no per-widget rules are needed** · (b) one rule per `tb:` property |
| D10 | The five widgets | **(a) the property sets of §5. ToggleButton = `ttkbootstrap.Checkbutton` with `bootstyle="<colour>-round-toggle"` or `"-square-toggle"` (2.2 has no ToggleButton class; tokens from `style/builders/toggle.py`). Floodgauge = the 2.2 Canvas-based `Floodgauge` (not `FloodgaugeLegacy`). DateEntry stores ISO `YYYY-MM-DD`, never `%x`** · (b) a minimal set (value/maximum only) |
| D11 ★ | Qt rendering of `tb:` widgets (FEATURES §3 lists `QDateEdit`/`QTableWidget`) | **(a) no Qt factories: `tb:` widgets show their core fallbacks in tkinter and PySide6 (ADR-001: "tb:" = ttkbootstrap). FEATURES §3 is amended to "Entry", "Treeview"** · (b) Qt factories `QDateEdit` (DateEntry) and `QTableWidget` (Tableview). Under D4 (a) they need a widened contract, because a `QDateEdit` is not a `QLineEdit`: ≈ +120 lines |
| D12 ★ | Tableview columns (there is no list property type) | **(a) `columns`: a translatable string of `;`-separated headings, `pattern` ≤ 64 headings × 64 chars, with a translator comment. The runtime pads or truncates a translation with a wrong count and logs it** · (b) no columns in the `.ui` (headings come from handler code; the designer shows an empty table) · (c) `<column>` child elements (schema MINOR bump + migration; rejected for v1) |
| D13 ★ | Codegen of extension widgets | **(a) `tb:` widgets are emitted natively (`ttkbootstrap.Meter(...)`; ttkbootstrap is already imported); third-party plugins → fallback + `codegen.extension_fallback` (as today)** · (b) plugins with a string factory ref → a guarded `from mod import attr` in the generated module (the export then depends on the plugin distribution; ≈ +45 lines) |
| D14 ★ | `tb:bootstyle` validation strength | **(a) R83 **error** when the grammar fails (`_BOOTSTYLE_RE`, ≤ 64 chars); R84 warning for an unknown token or a class without bootstyle (Text, Listbox, Canvas). Risk: a hand-edited file with a malformed value (which is ignored today) now refuses `load_ui`; 2 test fixtures are affected (§14 R4)** · (b) both warnings (nothing breaks; the command guard cannot block junk) |
| D15 | `SetExtraAttr` | **(a) `SetExtraAttr(node, key, value \| None)` sets or removes one extra attribute. The key must be Clark-form `{ns}local` with a non-core namespace and an NCName local part (`TypeError` otherwise). It goes through the normal guard, so R83 blocks a bad bootstyle. Merges like `SetProp`** · (b) a `SetBootstyle` command only |
| D16 ★ | The diagnostics "panel" | **(a) a modal dialog Help ▸ Plugins…:<br>• a list of distribution / widgets / status (Loaded, Failed, Disabled, Incompatible, Built-in);<br>• a read-only details box (message + traceback);<br>• Copy details, Disable/Enable on next start, Close.<br>Live factory failures appear (`registry.revision`). A start-up status note when there are problems** · (b) a dockable panel beside Properties (≈ +80 lines, layout persistence) |
| D17 | Missing vs broken vs disabled | **(a) `plugin=` must match the PEP 508 name grammar, ≤ 100 chars (R86 warning; otherwise R28's nameless variant, never a `pip install` with junk). A distribution that is installed but failed → R87 (no pip hint, "see Help ▸ Plugins"). Disabled → R88. Names are compared PEP 503-normalised** · (b) keep R28 for all three |
| D18 | ttkbootstrap's own strings | **(a) our texts go through `_()` (the DateEntry popup title is a new msgid). The calendar's month and day names and the Tableview search/pager texts stay as ttkbootstrap provides them (as backends D18 for Qt)** · (b) patch ttkbootstrap's msgcat per language |
| D19 | `WIDGET_API_VERSION` | **(a) stays 1: the API is provisional (ADR-004), the new fields have defaults, and no factory ever worked before** · (b) bump to 2 |
| D20 | Sample plugin | **(a) `examples/acme_plugin` (distribution `acme-pyguibud`, package `acme_pyguibud`): `acme:ColourSwatch`, fallback Label, factories for `ttkbootstrap`, `tkinter`, `pyside6`. `ACME_PYGUIBUD_BREAK=import\|spec\|factory\|exit` makes it fail on purpose. Installed with `uv pip install -e examples/acme_plugin` (the venv has no pip.exe)** · (b) two widgets (one container) |
| D21 | Plugin palette icons | **(a) not loaded in v1: the palette and tree use the fallback's icon (as `present/icons.py` already does). `WidgetSpec.icon` is reserved** · (b) an `importlib.resources` PNG through the hardened image probe (≈ +50 lines) |

## 2. Module layout
| File | New/changed | Part | Notes |
|---|---|---|---|
| `src/pyguibud/core/model.py` | changed | a | `FactoryRef`, `WidgetSpec.bind_types`, `PropertyDef.pattern/max_length/hint` (checked in `__post_init__`: the regex compiles, `max_length` is 1..100,000), `BACKEND_NAME` |
| `src/pyguibud/core/registry.py` | changed | a | §3 |
| `src/pyguibud/core/widgets.py` | changed | a | `tb_widgets()`: the 5 specs (data, string refs) |
| `src/pyguibud/core/validate.py` | changed | a | `bind_types`, R83–R91 (§6) |
| `src/pyguibud/core/commands.py` | changed | a | `SetExtraAttr` (next to `SetProp`) |
| `pyproject.toml` | changed | a | `[project.entry-points."pyguibud.widgets"] tb = "pyguibud.core.widgets:tb_widgets"` |
| `src/pyguibud/backends/_tkmap.py` | changed (pure) | b | `TB_EXT`: class → (ttkbootstrap class path, prop → option renames, inner accessor, variable option); `split_headings` |
| `src/pyguibud/backends/_tbwidgets.py` | new | b | the 5 Tk factories; ttkbootstrap is imported inside each function |
| `src/pyguibud/backends/_tk.py`, `_qt.py`, `base.py` (`Embed.failed`) | changed | b | §4 |
| `src/pyguibud/codegen/_emit.py`, `_support.py` | changed | b | §7 |
| `src/pyguibud/preview/_describe.py` | changed | b | `tb:` classes described by their outer widget type |
| `src/pyguibud/designer/dialogs/plugins.py`, `present/plugins.py` | new | c | D16 |
| `designer/standard_actions.py`, `settings.py`, `cli.py`, `app.py`, `present/palette.py`, `canvas/engine.py`, `panels/inspector.py` | changed | c | menu item, `disabled_plugins`, `--no-plugins`, `PaletteItem.plugin = spec.plugin is not None`, failure card, Bootstyle row |
| `examples/acme_demo.ui` | new | a | used by the UAT of every part (data, not counted) |
| `examples/acme_plugin/` | new | c | `pyproject.toml` (hatchling), `src/acme_pyguibud/__init__.py` |

## 3. Registry (17a)
- **Built-in:** both conditions hold (D2):
  - the normalised distribution name is `pyguibud`;
  - `ep.value.startswith("pyguibud.core.widgets:")`.
  Built-ins sort first. A test proves that a fake third-party distribution exposing `pyguibud.core.widgets:x` is not built-in. A non-built-in spec with prefix `tb` → `registry.reserved_prefix` (error, ignored).
- **`Registry(entry_points=None, *, disabled: Collection[str] | Literal["all"] = ())`.** Disabled distributions are skipped before `ep.load()`. Each gets one warning `registry.disabled`. `"all"` = every non-built-in (safe mode). The runtime (`load_ui`) never reads designer settings, so it always passes `()`.
  - **The preview child** gets the designer's set through a hidden `--disable-plugins NAME,...` / `--no-plugins` flag (like `--portable`). Its default registry is then built with the same filter, so a disabled or hanging plugin is not loaded on F5 either.
- **Isolation:** `except (Exception, SystemExit)` at the three load points. The `SystemExit` code goes into the diagnostic text. An import > 2 s → `registry.slow_plugin` (T4).
- **Registration checks (new):**
  - `registry.bad_factory`: a key not matching `BACKEND_NAME`, or a string ref failing the D3 grammar, or a value that is neither callable nor str;
  - `registry.not_fallback_compatible` (D5);
  - `registry.reserved_prefix`.
  - `registry.toolkit_imported` (warning, T4): `tkinter`, `ttkbootstrap` or `PySide6` appeared in `sys.modules` after the entry point loaded ("plugins must import their toolkit inside the factory").
- **`load_factory(spec, backend) -> Callable | None`.** It resolves the ref once and caches it. A failure → `report_failure(...)` and `None`, and the caller uses the fallback.
- **`report_failure(class_name, backend, stage, exc)`:**
  - appends one `Diagnostic` per (class, backend, stage) with code `registry.factory_failed`, the traceback and the distribution;
  - bumps `revision: int`;
  - `stage` ∈ `import`, `create`, `check`, `wire`.
- **`failed_distributions()` / `disabled_distributions()`:** PEP 503-normalised `frozenset`s for R87/R88.
- `resolve()` gains code `registry.plugin_failed` when the class is unregistered but `plugin=` names a failed distribution.

## 4. Backends (17b)
### 4.1 Factory contract (D4)
- **`props`:** a fresh `dict` with every `PropertyDef` of the spec that has a value or a default, converted:
  - `int`, `float`, `bool`;
  - `image` → the session's `PhotoImage` / `QPixmap`;
  - others `str`;
  - translatable values already translated.
  The factory may consume it.
- **Tk:** `factory(parent, props, variable, bootstyle)`:
  - `variable` is the bound `tkinter` variable (or the trace variable that the builder creates for `change`, as for core classes), or `None`;
  - `bootstyle` is the `tb:bootstyle` value under ttkbootstrap only, else `None`;
  - it returns a widget or `(outer, inner)`.
- **Qt:** `factory(parent, props)` returns a `QWidget` or `(outer, inner)`. `inner` must be an instance of the fallback's Qt class. The builder binds the `_vars` variable and wires the signals on `inner` as for the fallback.
- **Checks** (stage `check`):
  - Tk: `outer` and `inner` are `tkinter.Misc`; `outer.master` is `parent`; `inner` is `outer` or a descendant of it.
  - Qt: `QWidget`s; `outer.parent()` is `parent`; the `isinstance` check above.

### 4.2 Builder path and the guard
- `_widget` resolves the class. When `resolved.spec.is_extension` and `load_factory` returns a callable, it runs a guarded section: factory → checks → text slot (`text` via `configure(text=)`, mnemonic per the fallback) → `state`.
- **Translatable properties other than `text`** become slots that call `outer.configure(**{name: value})`. Tableview `columns` uses `_tkmap.split_headings`.
- **Any exception in the guarded section:**
  1. `outer.destroy()` (Qt: `deleteLater()`), plus any widget the factory left under `parent` (a children snapshot taken before the call);
  2. `registry.report_failure(...)`;
  3. `plan.log(runtime.plugin_failed)` once per class;
  4. the fallback path, exactly as `registry.no_factory`.
- **Events** are wired after the guard succeeds, with the fallback's wiring (`event_wiring(fallback, event)`, Qt `SIGNALS[fallback]`). A `configure(command=)` that raises is logged once (`runtime.event_unsupported`) and does not abort the window.
- **Design build:** when `Embed.failed` is set and the extension is not a container, step 4 calls `embed.failed(node, parent, reason)` instead (the canvas card, D6). `on_node` still reports the card so selection works.
- **Design mode:** the existing bindtag replacement makes Meter `interactive` and the DateEntry button inert on the canvas (a test pins this). Theme switches already rebuild (canvas.py:731).

## 5. The five `tb:` widgets (17a data, 17b factories)
All have `category = N_("ttkbootstrap")` and `api_version = 1`. Properties shared with the fallback keep the fallback's names, so the fallback shows the same value.

| Class | Fallback | Properties (type, constraint) | Events | `bind_types` | ttkbootstrap factory |
|---|---|---|---|---|---|
| `tb:Meter` | Progressbar | `value` float 0; `maximum` float 100; `subtext` string translatable; `meter_type` enum full\|semi; `meter_size` int 50..1000 = 200; `meter_thickness` int 1..100 = 10; `amount_format` string pattern `[^{}]*\{(:\.[0-6]f)?\}[^{}]*` ≤ 32 = `{}`; `show_text` bool true; `interactive` bool false | — | double, int | `Meter(amount_total, amount_used, …)`, bound variable as its amount-used variable |
| `tb:Floodgauge` | Progressbar | `value`, `maximum`, `mode`, `orient`, `length` (as Progressbar); `text` translatable; `mask` string, same pattern as `amount_format`, ≤ 32 | — | double, int | `Floodgauge(...)` (Canvas-based); `variable` |
| `tb:DateEntry` | Entry | `width`, `state` (as Entry); `value` string pattern `YYYY-MM-DD`, years 1900–9998 only (QA-17b-01/03: Windows `%y` refuses years < 1900; the 2.2.3 picker grid overflows at 0001/9999; calendar validity checked at build, logged); `date_format` string ≤ 32 = `%Y-%m-%d`: codes `%d %m %Y %y %b %B %a %A %j %%` only, exactly one day (`%d`), one month (`%m/%b/%B`) and one year (`%Y/%y`), no code repeated, no `{}` or control characters (`_DATE_FORMAT_RE`, QA-17a-01); `first_weekday` int 0..6 = 0 | change, activate, focus_in, focus_out | string | `DateEntry(...)`, `inner = .entry`, `textvariable` on the inner entry; popup title `_("Select a date")` |
| `tb:Tableview` | Treeview | `height`, `selectmode` (as Treeview); `columns` translatable, pattern `[^;]{1,64}(;[^;]{1,64}){0,63}`; `paginated`, `searchable`, `yscrollbar`, `autofit` bool; `pagesize` int 1..1000 = 10 | select, activate, focus_in, focus_out | — | `Tableview(coldata=headings, rowdata=[])`, `inner = .view` (rows come from handler code) |
| `tb:ToggleButton` | Checkbutton | `text` translatable, `state` (as Checkbutton); `shape` enum round\|square = round | command, change, focus_in, focus_out | bool, int | `ttkbootstrap.Checkbutton(bootstyle=…)`: `"{colour}-{shape}-toggle"` when `tb:bootstyle` has a colour token (the first one), else `"{shape}-toggle"` |

- **tkinter backend:** no factories, so fallbacks are shown with `_M_FALLBACK` logged once.
- **PySide6 backend:** the same (D11).
- **When ttkbootstrap is missing:** it is a hard dependency of `pyguibud`, so this cannot happen in-tree. A ttkbootstrap whose API differs (a renamed keyword) fails in the guard → fallback + diagnostic. The tkinter and Qt backends never import `_tbwidgets` (boundary test).

## 6. Validator (17a) — new rules (codes stable; every msgid in `N_()`)
| # | Code | Sev | What |
|---|---|---|---|
| — | (existing R40–R42) | E | `bind`: a registered extension with `bind_types` uses them; otherwise the fallback's row |
| R83 | `validate.bad_bootstyle` | E (D14) | `tb:bootstyle` > 64 chars or not matching `_BOOTSTYLE_RE` (moved to `core`) |
| R84 | `validate.bootstyle_ignored` | W | an unknown token (closed list of ttkbootstrap 2.2 colours and types in `core`), or a class without bootstyle (Text, Listbox, Canvas) |
| R85 | `validate.unknown_extension_attr` | W | an attribute in `NS_TB` other than `bootstyle` (ignored, preserved). Foreign namespaces stay untouched |
| R86 | `validate.bad_plugin_name` | W | `plugin=` not PEP 508 (`^([A-Za-z0-9]\|[A-Za-z0-9][A-Za-z0-9._-]*[A-Za-z0-9])$`) or > 100 chars; R28 then uses its nameless text |
| R87 | `validate.plugin_failed` | W | an unregistered extension whose `plugin` is in `failed_distributions()`: "'{class_name}' comes from '{plugin}', which failed to load, so '{fallback}' is shown instead. See Help ▸ Plugins." (replaces R28 for that node) |
| R88 | `validate.plugin_disabled` | W | the same for disabled distributions |
| R89 | `validate.bad_pattern` | E | a string prop failing its `PropertyDef.pattern`: "The value of '{prop}' on '{id}' is not valid: {hint}" |
| R90 | `validate.value_too_long` | E | a string prop longer than its `max_length` |
| ~~R91~~ | `validate.fallback_differs` | dropped (T4, 17a) | a registered extension whose `fallback=` differs from `spec.fallback` (it renders differently where the plugin is missing) |

All of these are pure, so they also run in the command guards. R89/R90 are skipped in fallback mode (as every prop rule is).

## 7. Codegen (17b, D13)
- `_emit._resolve` uses `_tkmap.TB_EXT` for `tb:` classes. It emits `w = self._create(ttkbootstrap.Meter, parent, {renamed options}, style, ...)`. The inner accessor (`w.entry`, `w.view`) and the variable option come from the table.
- DateEntry `value` is emitted as `datetime.date(Y, M, D)`, and `datetime` joins the fixed import block.
- `_support.py` gains `_headings(view, text)` (≈ 8 lines) for Tableview retranslation.
- Third-party plugins: fallback + `codegen.extension_fallback` (unchanged).
- **Parity:** `tests/codegen/data/tb_widgets.ui` joins `test_parity.py` (generated module vs `load_ui`, ttkbootstrap).

## 8. Designer (17c)
- **Help ▸ Plugins…** (D16): `present/plugins.py` turns the registry diagnostics and specs into rows. It is pure and tested headless. Rows are grouped by distribution:
  - the status: Built-in / Loaded / Failed / Disabled / Incompatible;
  - the class names;
  - the first message.
- **The dialog:**
  - details box: every message for the row + its traceback; read-only, selectable;
  - **C**opy details;
  - **D**isable/**E**nable on next start (it writes `Settings.disabled_plugins`; built-ins cannot be disabled);
  - Close;
  - access keys, and Esc closes it.
  It refreshes when `registry.revision` changes.
- **Start-up note:** once, when there is an error diagnostic: `NP_("{count} plugin problem — see Help ▸ Plugins.", "{count} plugin problems — see Help ▸ Plugins.")`.
- **`pyguibud --no-plugins`** (D7) adds the note "Plugins are disabled (safe mode)."
- **Palette:** `PaletteItem.plugin = spec.plugin is not None`, so the `tb:` widgets sit under "ttkbootstrap" without "(plugin)".
- **Inspector:** a "Bootstyle" editable combobox row (colour tokens × type tokens) for widgets under ttkbootstrap. An edit = `SetExtraAttr`, and a rejection shows the guard's reason (T5).
- **Canvas:** the failure card (D6, T7).

## 9. Sample plugin `examples/acme_plugin` (17c, D20)
- **`pyproject.toml`:**
  - `name = "acme-pyguibud"`;
  - `dependencies = ["pyguibud"]`;
  - `[project.entry-points."pyguibud.widgets"] acme = "acme_pyguibud:widgets"`.
- **`acme_pyguibud/__init__.py`:**
  - `widgets()` returns one `WidgetSpec`: `acme:ColourSwatch`, fallback Label, `text` translatable, `colour` colour = `#2E86DE`, `bind_types=("string",)`;
  - `factories` = string refs to `acme_pyguibud:tk_swatch` (used for both `ttkbootstrap` and `tkinter`: a `tkinter.Label` with `bg`) and `acme_pyguibud:qt_swatch` (a `QLabel` with a style sheet);
  - toolkits are imported inside the factories only;
  - `ACME_PYGUIBUD_BREAK` = `import` (raise at module import), `spec` (raise in `widgets()`), `factory` (raise in the factory), `exit` (`sys.exit(3)` at import).
- **`examples/acme_demo.ui`:** a ColourSwatch with `plugin="acme-pyguibud"`, one Meter, one ToggleButton and one DateEntry.
- A README paragraph explains the trust boundary.

## 10. Security and boundary
- **Plugins run code** when the registry loads (designer, preview child, `load_ui`). ADR-004's trust note is repeated in the dialog's header text and the acme README.
- **A `.ui` cannot cause an import:**
  - `plugin=` and `fallback=` are text;
  - classes resolve only against installed entry points;
  - factory refs come from installed specs, never from the file;
  - the D3 grammar stops a malformed ref.
- **Format strings and dates** are constrained by R89/R90 before any widget sees them, so there is no `str.format` attribute walk, no huge-width padding and no Windows `strftime` crash.
- **Import-boundary test additions:**
  - in a subprocess, `Registry().load()` with the in-tree metadata, then `load_factory` of a `tb:` spec for `tkinter` (none), imports neither `tkinter`, `ttkbootstrap` nor `PySide6`;
  - `pyguibud.backends._tbwidgets` imports no toolkit at module level.

## 11. Test plan (all headless unless marked)
- **Registry (fake entry points):**
  - each `ACME_PYGUIBUD_BREAK` stage → one diagnostic, siblings still load, no exception;
  - `SystemExit` at import is caught;
  - `disabled` filters before `load()` (the fake `load` asserts it is never called);
  - `"all"`;
  - reserved `tb`;
  - D5 violations;
  - bad factory refs;
  - `report_failure` deduplicates and bumps `revision`;
  - `failed_distributions` normalisation.
- **Validator:** a golden case per R83–R91; `bind_types` accept/reject; fallback mode skips R89/R90; R87 vs R28 selection; a ReDoS-shaped long value is rejected by `max_length` in under 10 ms.
- **Commands:** `SetExtraAttr` set/remove/merge/undo; a guard rejection on R83; `TypeError` for a core-namespace key; read-only documents.
- **Backends (Tk):**
  - each `tb:` widget builds under ttkbootstrap;
  - tkinter shows the fallbacks and imports no `_tbwidgets`;
  - a raising factory, a factory returning `None`, a factory returning a widget of the wrong master and a factory leaving children → fallback, no stray widgets, one log and one diagnostic;
  - variables and events on the inner widgets (shared event matrix rows for ToggleButton and DateEntry).
- **Backends (`qt`):** the acme Qt factory; a factory whose `inner` is not a `QLabel` → fallback; `tb:` widgets → fallbacks.
- **Codegen:** golden `tb_widgets.ui`; parity with `load_ui`; the plugin widget → fallback + warning.
- **Designer:**
  - the presenter rows for every status;
  - the dialog opens, copies and toggles, and is keyboard-reachable;
  - the `--no-plugins` note;
  - the palette shows `tb:` without "(plugin)";
  - the canvas card for a failing non-container and the fallback for a failing container;
  - Meter and DateEntry are inert in design mode;
  - `en_XA` fit.
- **QA (abuse):** see §12 "Break it", plus 100 failing widgets in one window (one diagnostic per class, still responsive) and a factory that destroys its parent (caught at `check`).

## 12. UAT (for the user)
**17a:**
1. `uv sync --extra pyside` (it registers the new `tb` entry point). Then `uv run pyguibud-uic --check examples/acme_demo.ui` without acme installed: one warning names `acme-pyguibud` with a pip hint; the `tb:` widgets give no warning; no errors.
2. Edit a copy so its ToggleButton has `tb:bootstyle="primary;x"`: the check shows the R83 error. Give the Meter `<prop name="amount_format">{0.__class__}</prop>`: the R89 error.
3. `uv run pytest tests/core -q` is green.

**17b:**
1. `uv run python examples/show_ui.py examples/acme_demo.ui`: a ttkbootstrap window with a real Meter, ToggleButton and DateEntry. `--backend tkinter` and `--backend pyside6`: the fallbacks render (Progressbar, Checkbutton, Entry), with one note each, and no traceback.
2. Export `acme_demo.ui` from the designer and run the module: the same `tb:` widgets.

**17c:**
1. `uv pip install -e examples/acme_plugin` (not `pip`: the uv venv has none). **Note:** a later `uv sync` uninstalls it.
2. `uv run pyguibud examples/acme_demo.ui`: "Colour swatch" appears in the palette (category Acme); the swatch renders in colour; Help ▸ Plugins lists `acme-pyguibud` as Loaded.
3. Break it: quit, `$env:ACME_PYGUIBUD_BREAK="factory"`, restart. The swatch shows a placeholder card, the designer keeps working, Help ▸ Plugins shows Failed + traceback, and F5 previews with the Label fallback. Repeat with `import` and `exit`: the designer starts, the palette has no swatch, and the canvas shows the fallback with an R87 note. `Remove-Item Env:ACME_PYGUIBUD_BREAK`.
4. Help ▸ Plugins ▸ Disable acme, restart: listed Disabled, fallback shown. Enable again. `uv run pyguibud --no-plugins`: the safe-mode note.
5. Preview ▸ Toolkit ▸ tkinter, F5: the fallbacks render.

## 13. i18n
- **New msgids:**
  - registry: `disabled`, `slow_plugin`, `toolkit_imported`, `reserved_prefix`, `bad_factory`, `not_fallback_compatible`, `factory_failed` + its stages;
  - `runtime.plugin_failed`, `runtime.event_unsupported`;
  - R83–R91;
  - the 5 display names, the category "ttkbootstrap" (a proper name, translator note), the property display names, the `hint`s;
  - "Select a date";
  - the dialog (title, columns, statuses, buttons with access keys, the trust note);
  - the start-up plural, the safe-mode note, `--no-plugins` help, the "Bootstyle" row;
  - the acme strings stay in acme's own domain (an example of a plugin's i18n domain).
- **Gates:** all 8 locales, `en_XA` fit of the dialog, no concatenation, named placeholders. Class names, distribution names and tokens stay untranslated.

## 14. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | A plugin hangs at import (no timeout possible) | `--no-plugins`, the disabled list, the slow-import warning; the preview child's timeout |
| R2 | A plugin corrupts process state (monkeypatching, Tk grabs) | the documented trust boundary; not preventable in-process |
| R3 | ttkbootstrap API drift in Meter/DateEntry keywords | the guard falls back; `TB_EXT` is one table; a CI test pins the 2.2 keywords |
| R4 | D14 (a) refuses old files with a malformed bootstyle | such values only come from hand edits, and the message names the attribute; choose (b) if unacceptable. In-tree evidence: 2 of 16 fixture values fail the grammar (`"Not Valid!"` in `tests/runtime/test_tk_build.py:186` and `tests/codegen/data/rich.ui:61`); both exist to test the runtime `_M_BOOTSTYLE` log, and they would move to in-memory documents built with the validator skipped. The unknown-token case (`"nonsense"`) stays valid (R84 warning) |
| R5 | Budget overshoot (16a–16c ran 1.25–1.64× their estimates) | the estimates are raw × ≈ 1.3, so expect T1–T3; trims remove whole surfaces first |

## 14a. 17a as built (2026-10-14)
- **Budget:** 648 net production lines against cap 650 (688 gross). **T4 applied**: R91 `fallback_differs`, `registry.slow_plugin` and `registry.toolkit_imported` were dropped.
- **Deviations from this spec:**
  - R83–R85 are checked on `<widget>` only, not on windows or includes.
  - `failed_distributions()` counts any error-level diagnostic from a non-built-in distribution. An API-version mismatch is a warning, so a widget from such a plugin still gets the R28 pip hint, not R87.
  - The `_ensure_core` safety net also registers the `tb:` widgets, with `registry.core_fallback`, when the `tb` entry point is stale (no `uv sync` yet).
  - `SystemExit` is also caught in `load_backend`.
  - `Registry.resolve()` gained a keyword-only `plugin=`, which it uses for `registry.plugin_failed`.
  - `examples/acme_demo.ui` was added for the UAT.
- **Interim state until 17b/17c:**
  - the `tb:` widgets show "(plugin)" in the palette (the palette fix is 17c);
  - they render as their fallbacks (no factories until 17b);
  - R87's "Help ▸ Plugins" target does not exist yet (17c).

- **QA rulings (orchestrator, 2026-10-14):** QA pass APPROVE with 4 findings.
  - QA-17a-01 (MAJOR): the `date_format` pattern accepted formats that crash ttkbootstrap 2.2.3 `DateEntry` (ValueError at build; `re.error` on every focus-out for repeated codes). Fixed with a stricter pattern (§5 row above; `%U` dropped; new hint msgid). Every accepted test format is round-tripped through a real `DateEntry`.
  - QA-17a-02 (MINOR): `pyguibud-uic` now escapes C0/DEL/C1 and bidi controls (U+202A–202E, U+2066–2069) in printed messages, so a file cannot forge an output line. Designer status bar, `designer/export.py`, `designer/clipboard.py`, `Finding.__str__` and runtime strict-mode messages still print them raw → Step 19.
  - QA-17a-03 (MINOR): a file may bind the `tb` prefix to another URI (`xmlns:tb="urn:evil"`) and then checks clean → Step 19 (strict xfail).
  - QA-17a-04 (MINOR): `Registry(disabled="name")` is now one name, not letters.
  - Budget after fixes: ≈ 660 net production lines vs cap 650. **User ruling (UAT 17a passed, 2026-10-14):** overshoot accepted.

## 14b. 17b as built (2026-10-14)
- **Budget:** 560 net production lines against cap 600 (546 before the QA fixes). Measured as added − deleted for `src/**/*.py` from `git diff --numstat HEAD -- src`, plus the line count of the untracked `_tbwidgets.py`. **No trims:** T1–T3 were not needed, so Tableview has a factory, the Qt factory path exists and codegen is native.
- **Deviations from this spec:**
  - `Embed.failed` lives in `_tk.py`, where `Embed` is defined, not in `base.py`. It defaults to `None`; the canvas card UI is 17c.
  - **`ui.<id>` is the inner widget** (D4: "behaves as its fallback"). The outer widget is `ui.<id>.master` for DateEntry and `ui.<id>.master.master` for Tableview.
  - **Meter** has no variable keyword in ttkbootstrap 2.2.3. The bound variable is linked both ways to `amount_used_var` (`_tbwidgets.link`, `_support._link`), and the bound value wins at first.
  - **The factory path retries once without the bootstyle** on TclError, TypeError or ValueError, like the core `_create`. Runtime and export therefore agree for bootstyles ttkbootstrap rejects.
  - **The generated DateEntry popup title is the en-GB literal "Select a date".** Generated modules have no `_()` (codegen §4.2), and the frameless popup never shows the title. This follows the documented untranslated en-GB deviation (codegen §3.6).
  - **Two runtime messages are untranslated stdlib logging:** a calendar-invalid DateEntry value and a wrong Tableview heading count. At export, a calendar-invalid date is dropped without a Finding (→ Step 18 msgids / Step 19).
  - **The Qt factory path slots only `text`** (on `inner`). Tk slots every translatable property; Tableview headings go through `TableColumn.configure`, so sorting keeps them.
  - `runtime.event_unsupported` is logged once per (class, event) and is also reported to the registry with stage `wire`.
  - **A factory that destroys its parent** records the `check` diagnostic first, then the build ends in `UiError runtime.build_failed`; a design build re-raises to the canvas error card. An `inner` outside `outer` is destroyed, unless it is the parent or one of its ancestors.
- **Known limitation (to document for users):** rows that handler code adds with `ui.<id>.insert(...)` on the inner Treeview are shown but are not part of the Tableview's row model, so sort, search, paging and reset ignore them. Use the Tableview API (`insert_row(s)` + `load_table_data()`) on the outer widget instead.
- **Deferred → Step 19:**
  - the Qt check does not verify that `inner` lies inside `outer`;
  - the bootstyle-retry sweep cannot remove an `inner` created outside `parent`;
  - an existing widget elsewhere in the window that is returned as `inner` is destroyed;
  - the "fallback is shown" warning is logged before a destroyed-parent abort;
  - a DateEntry bound variable holds ISO text, not text in `date_format`;
  - a handle to reach the outer Tableview.
- **QA (2026-10-14): first REJECT (2 MAJOR), all fixed except QA-17b-05.**
  - **QA-17b-01** (MAJOR): a pre-1900 DateEntry value with `%y` crashed the exported module on Windows. **QA-17b-03** (MINOR): the 2.2.3 picker failed at 9999-12-31, or at 0001-01-01 with first weekday 6. Both fixed by narrowing `value` to 1900–9998 (R89, with a new hint msgid). Picking a December 1899 day from the grid by hand is ttkbootstrap's problem.
  - **QA-17b-02** (MAJOR): the Floodgauge was drawn at 1×1 on the design canvas. Fixed: `<<ThemeChanged>>` joins `_GEOMETRY` in `designer/canvas/design.py`. A test pins Meter and DateEntry inertness on the canvas.
  - **QA-17b-04** (MINOR): each Tableview build leaked the `_trace_pagesize` Tcl command. Fixed in `_tbwidgets.tableview` by wrapping the instance `destroy()`.
  - **QA-17b-05** (MINOR): `en_XA` pseudo-localised the whole heading string rather than each heading → fixed in Step 18a (`Texts.text` pseudo-localises each `;`-separated heading; the xfail is gone).
- **Test-order notes (→ Step 19, test isolation):**
  - Running `tests/runtime` before `tests/codegen` in one process raises 33 "single application root" errors. This predates 17b.
  - Running `tests/runtime` before `tests/designer` in one process hangs `test_13a_gaps.py::test_no_listener_reenters_the_stack_in_any_designer_flow` in Tk's `update_idletasks`. Not bisected, and not checked against pre-17b code (user ruling 2026-10-14).
  - Neither affects the default (alphabetical) order.

## 14c. 17c as built (2026-10-15)
- **Budget:** 549 net production lines against cap 600: 465 in `src/**/*.py` (155 net in tracked files from `git diff --numstat HEAD`, plus 310 in the new `designer/dialogs/plugins.py` and `designer/present/plugins.py`), plus the 84-line acme module. **No trims:** T5–T7 were not needed, so the Bootstyle row, the Disable toggle and the canvas card all shipped.
- **Deviations from this spec:**
  - `core.registry.configure_default_registry(disabled)` (new) replaces the process-wide default registry. The designer calls it in `run()` straight after `load_settings()`; the preview child calls it from `--no-plugins` / `--disable-plugins a,b` (hidden flags).
  - **A non-built-in spec's `plugin` is always its entry point's real distribution** (QA-17c-01). A self-declared name that differs after PEP 503 normalisation gives one warning per spec, `registry.plugin_name_mismatch`, and loading continues. `docs/specs/core-model.md` is updated.
  - The dialog has no "first message" column: the details box shows every message. Rows are one per distribution, the built-in first; status order is Disabled > Failed > Incompatible > Loaded, and Built-in for `pyguibud`.
  - In safe mode, rows read plain "Disabled" (no "on next start" suffix); the toggle still edits `disabled_plugins`.
  - `Settings.disabled_plugins` is PEP 503-normalised, de-duplicated and capped at the **newest** 200 entries. A stored `"all"` or a non-list reads as `()`, never as safe mode. A name the parser would drop cannot be toggled.
  - The preview child gets the filter the designer **started** with, not the setting as edited since.
  - The failure card shows "{name} — the plugin failed" without the reason (`_tk.py` passes the raw stage text).
  - The Bootstyle row shows for every widget whose class takes a bootstyle, whatever Preview toolkit is selected, and also on plugin widgets whose fallback takes one (e.g. acme's swatch, where the value is accepted and ignored).
  - acme keeps its Qt factory: 17b's Qt factory path calls plugin `pyside6` factories (`tests/qt/test_acme_qt.py`).
- **Testing:** 17c-BUG-1 (`child_argv` split a bare string into letters) and 17c-BUG-2 (a test read the machine's language) were fixed.
- **QA (2026-10-15): REJECT (1 MAJOR), all fixed except QA-17c-04.**
  - **QA-17c-01** (MAJOR): rows, Disable and `new_node` used the plugin's self-declared name. Fixed in the registry (above).
  - **QA-17c-02** (MINOR): a name the settings parser drops could be toggled. **QA-17c-03** (MINOR): the cap kept the oldest entries. **QA-17c-05** (MINOR): pt_PT/pt_BR Copy and Close both used Alt+C ("_Fechar"). **QA-17c-07** (MINOR): the status column clipped after a toggle (now sized to every possible status text, `stretch=False`). **QA-17c-08** (MINOR): the details box had no scrollbar. **QA-17c-09** (MINOR): two tests depended on acme being absent.
  - **QA-17c-04** (MINOR) → Step 19 (strict xfail): with two designers open, the last one to save its settings overwrites the other's `disabled_plugins`.
- **Deferred → Step 19:**
  - a non-built-in entry point whose real distribution is named `pyguibud` lands under the Built-in row;
  - `.ui` files saved before the QA-17c-01 fix may carry a misdeclared `plugin=`, so R87/R88 miss and R28 hints the wrong pip name;
  - the "cannot be drawn" card shows raw Tcl text when a factory destroys its parent (17b risk);
  - the Bootstyle value on a plugin widget that ignores it gives no R84.
- **→ Step 18:** `en_XA` and catalogue gaps noted by QA (older CLI help strings and "_Keyboard shortcuts…" untranslated); one translator comment missing on the start-up plural.

## 14d. Step 19d (2026-10-18)
- **Fixed:** H59 the Qt check requires `inner` inside `outer`; H60/H61 the sweeps destroy only widgets the factory created (Tk: a Tcl path snapshot; Qt: a widget-pointer snapshot), so an existing widget returned as `inner` survives and a stray made outside `parent` is removed; H62 no fallback warning before a destroyed-parent abort; H65 a calendar-invalid DateEntry date gives the `codegen.bad_date` Finding at export; H66 built-in needs the `pyguibud` distribution **and** a known group **and** the group's value prefix (`pyguibud.core.widgets:` / `pyguibud.backends.`), any other entry point of a `pyguibud` distribution is named after its module; H67 `Registry.plugin_for_prefix` gives R87/R88/R28 the real distribution behind a misdeclared `plugin=` (exact evidence first: a registered class or a diagnostic naming the class; the entry point named like the prefix fills in only when the file declares no `plugin=` or declares that entry point's name, so a correct declared name is never overridden, QA-19d-04); H68 the canvas card shows a translated reason only; H49 `ACME_PYGUIBUD_BREAK=setter`, and a plugin text setter that fails on retranslate is isolated (`_M_TEXT_FAILED`, registry stage `wire`).
- **Trim T4 (H69 dropped):** a `tb:bootstyle` on a plugin widget gives no R84. Factories receive `bootstyle` and may honour it, and `WidgetSpec` cannot declare whether they do, so a warning would be false for compliant plugins (pinned by `tests/core/test_hardening_19d.py`).
- **Documented (runtime.md §16):** H63 DateEntry ISO variable, H64 the outer Tableview handle.

## 15. Affected documents (applied 2026-10-14)
- ✔ FEATURES §3: the fallback column for DateEntry/Tableview = Entry/Treeview (D11); ToggleButton = a Checkbutton toggle bootstyle; tkinter and PySide6 show the core fallbacks.
- ✔ validate-commands §5 + §5.1: R83–R90 rows as built (17a), R91 marked dropped (T4), `bind_types`.
- ✔ codegen.md: a pointer to the native `tb:` export (§7).
- ✔ backends.md §8: points here.
- ✔ The DEVELOPMENT_PLAN row 17 split.
- ✔ ADR-015 (Accepted).
