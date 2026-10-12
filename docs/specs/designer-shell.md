# Spec — Step 12: designer shell

- **Status:** Implemented (Step 12 UAT passed 2026-10-06) · **ADRs:** 001, 004, 006, 007, **009** (Accepted) · canvas superseded by `docs/specs/dnd-selection.md` (Step 13)
- **UAT (plan row 12):** `uv run pyguibud` launches; switch language and theme live (§10).
- **Grounding:** ttkbootstrap **2.2.3** (installed; `>=2.2,<3`). Every ttkbootstrap API cited below was read in `.venv/Lib/site-packages/ttkbootstrap/`.

## 0. Scope fence and budget
**In Step 12:** the main window (menubar · toolbar · palette · canvas · object tree + inspector · status bar), SAPÉ themes with a live switch, a language menu with a live switch, read-only panels with synchronised selection, an action registry (menus, toolbar, shortcuts, cheat-sheet), F6 panel cycling, focus ring, and "New from template".

**Not in Step 12** (no stubs and no disabled placeholder menu items for these):
| Feature | Step |
|---|---|
| DnD, move/resize, multi-select, canvas engine | 13 |
| Property editing, events/variables panels, menu editor, open/save/autosave/recent files, copy/paste, unsaved-changes guard, settings persistence | 14 |
| Live preview window, Export `.py` | 15 (spec `docs/specs/preview-export.md`, ADR-013) |
| Plugin diagnostics panel | 17 |

- **The model is never mutated in Step 12.** The only document change is *replacing* it ("New from template", §6). That creates a new `Document` and a new `CommandStack` through core APIs. It is not an undoable command.
- **Canvas (D1):** a **placeholder** `ttk.Notebook` with one tab per window. Each tab shows a summary card: title, kind, layout, widget count, and the path of the selected node. It is **not** a rendering.
  - Rendering through the backend is impossible without new work. In `backends/_tk.py:175-180`, with a `master` every window (main included) becomes a `Toplevel`, so a render would spawn real windows.
  - An embed mode means changing `_tk.py`/`_tkmap.py`. That triggers the mandatory parity tests and is canvas-engine work, which belongs to Step 13.
  - The Notebook and the `CanvasPanel` protocol (§2.3) stay; Step 13 replaces the tab body.

Budget: **≤ 1,400 lines** of production code (tests, templates and theme data excluded). Trim order if over: (1) toolbar; (2) inspector findings section; (3) cheat-sheet dialog (the menu accelerators remain).

## 1. Module layout and dependency rules
```
src/pyguibud/designer/
  __init__.py      launch(lang, theme) -> int        # the only entry used by cli.py (lazy Tk import inside)
  app.py           DesignerApp(root, session)        # Tk: builds the shell, owns the one i18n listener, dispose()
  signals.py       Signal[T]                          # pure
  session.py       DesignerSession, Selection         # pure: document, stack, selection, cached report
  actions.py       ActionDef, MenuDef, ActionRegistry, CheatRow   # pure
  theme.py         ThemeSpec, load_theme_specs(), contrast(), pick_family()   # pure
  theme_tk.py      install_themes(style, specs), apply_theme(root, spec), fonts   # Tk
  themes/          __init__.py (neutral specs, MIT) · sape.json (generated, see D2)
  present/         palette.py · tree.py · inspector.py · canvas.py           # pure presenters
  panels/          palette.py · tree.py · inspector.py · canvas.py · focus.py (FocusFrame)  # thin Tk views
  shell.py         menubar, toolbar and status bar built from ActionRegistry; F6 cycle   # Tk
  dialogs/         new_file.py (template wizard) · shortcuts.py (cheat-sheet)           # Tk
  templates/       __init__.py (TEMPLATES manifest) · main_window.ui · dialog.ui · login_form.ui · settings.ui · empty_component.ui
tools/gen_themes.py                                    # tokens -> themes/sape.json (dev only)
```
- **Pure modules** (`signals`, `session`, `actions`, `theme`, `present/*`, `templates/__init__`) import only the stdlib, `pyguibud.core` and `pyguibud.i18n`. They never import `tkinter`/`ttkbootstrap`. A subprocess test enforces this: after `import` of each pure module, `tkinter` is not in `sys.modules`.
- **Tk modules** import `tkinter`/`ttkbootstrap` at module top. They are imported only from `designer.launch()`. `pyguibud.cli` imports `pyguibud.designer` lazily, so `--version`, `--help` and `--list-languages` never load Tk.
- ADR-007 is unchanged. `pyguibud_runtime`, `codegen` and `core` never import `pyguibud.designer`; the existing boundary test gains that case.
- mypy strict: the global `strict = true` already covers `pyguibud.designer`. Views may use `Any` for Tk widgets; pure modules may not.

## 2. Contracts with core
### 2.1 Session (pure controller)
```python
class Signal(Generic[T]):
    def connect(self, slot: Callable[[T], None]) -> Callable[[], None]   # returns disconnect
    def emit(self, value: T) -> None   # slots in order; an exception is logged and the rest still run

@dataclass(frozen=True, slots=True)
class Selection:
    node: object | None    # a model node of the current document (identity), or None
    origin: str            # "tree" | "canvas" | "inspector" | "palette" | "session"

class DesignerSession:
    def __init__(self, registry: Registry) -> None
    document: Document | None; stack: CommandStack | None; name: str     # display name ("Untitled" msgid until Step 14)
    document_changed: Signal[DesignerSession]; selection_changed: Signal[Selection]
    report_changed: Signal[ValidationReport]
    def open_result(self, result: ReadResult, *, name: str) -> None      # new CommandStack(result.document, registry, source=name)
    def new_from_template(self, template_id: str) -> None                # §6; raises TemplateError (PyGUIbudError)
    def select(self, node: object | None, *, origin: str) -> None        # a foreign node or an unchanged node is ignored
    def report(self) -> ValidationReport                                 # cached
    def can_discard(self) -> bool                                        # True in Step 12; Step 14 adds the guard
```
- **Validator use:** the cache is refreshed only on `document_changed` and on the stack's `StackEvent` (`CommandStack.subscribe`). It is **never** refreshed on a selection change, because `report()` costs about 75 ms on 2,000 widgets (Step 09 notes).
- **Selection identity:** selection is by object identity. Ids may be duplicate or empty in a readable but invalid document. `select()` checks membership by walking `document.walk()` lazily (≤ 10,000 nodes).
- **Feedback loops:** each view ignores `selection_changed` events whose `origin` is itself.
- **Model changes:** every one goes through the `CommandStack` (Step 13+). Views never touch model attributes, except to read them.

### 2.2 Presenters (pure; return plain rows in the current language)
| Presenter | Input → output | Core APIs used |
|---|---|---|
| `present.palette.palette_groups(registry)` | → `[PaletteGroup(category_label, items=(PaletteItem(name, label, plugin)…))]`. Sorted by translated label with `name` as the tie-break. | `Registry.specs()`, `WidgetSpec.label()`/`category_label()`/`is_extension` |
| `present.tree.tree_rows(document, report)` | → `[TreeRow(key, parent_key, node, text, detail, severity)]`. Iterative pre-order covering windows → menubar/menus/actions/separators, statusbar, widgets/includes. `key` is synthetic (`"n0"`, `"n1"`…), **never a model id**. | `Document.windows`, `walk()`, `diagnostics.node_path`, `Finding.anchor`/`severity` |
| `present.inspector.inspector_rows(node, registry, report)` | → `[InspectorRow(section, label, value, is_default)]`. Sections: General (class, id, kind), Properties (every `PropertyDef`; the default is shown when unset), Placement, Findings of this node. | `Registry.get`, `WidgetSpec.properties`/`property()`, `PropertyDef.label()`, `validate.WINDOW_PROPERTIES`, report findings |
| `present.canvas.canvas_tabs(document)` · `window_of(node)` | → `[CanvasTab(window, text, kind_label, summary)]`. The tab text is the `title` prop, else the id. | `Window.props`, `layout`, `walk()` |

User values (ids, titles) are shown verbatim and clipped to 100 chars (`…`). Format strings use named placeholders, for example `_("{id} ({class_name})")`.

### 2.3 Panel views (thin)
```python
class Panel(Protocol):
    frame: Any                       # the outer FocusFrame (§3.3)
    def retranslate(self) -> None    # re-render from msgids; keeps selection, open state and scroll
    def focus_first(self) -> None
    def dispose(self) -> None        # disconnect signals, unbind
```
- **Palette:** a `Treeview` (categories → widgets), read-only. Enter/double-click does nothing in Step 12.
- **Tree:** a `Treeview` with a `key ↔ node` dict, and an icon or tag by severity (error/warning, never colour only).
- **Inspector:** a read-only `Treeview`. Columns: property, value. Defaults are shown with a muted tag and an "(default)" text.
- **Canvas:** a `Notebook`. Tree selection → `CanvasPanel.show_window(window_of(node))` + `highlight(node)` (the summary-card text). Selecting a tab → the window is selected.
- **Status bar:** the selection path (`node_path`), then `ngettext("{count} error", "{count} errors", n)` + warnings, plus transient messages (5 s).

## 3. Actions, menus and keyboard
### 3.1 Registry (pure)
```python
@dataclass(frozen=True, slots=True)
class ActionDef:
    id: str                      # unique, dotted: "file.new"
    menu: str                    # MenuDef id
    label: str                   # msgid with "_" mnemonic (core.keys.split_mnemonic); literal when translate=False
    handler: Callable[[], None]
    shortcut: str | None = None  # core.keys chord grammar: "Ctrl+N", "Shift+F6", "F1"
    enabled: Callable[[], bool] = _always
    checked: Callable[[], bool] | None = None   # radio items (theme, language)
    toolbar: bool = False; translate: bool = True; context: str | None = None   # pgettext
@dataclass(frozen=True, slots=True)
class MenuDef: id: str; label: str; parent: str | None = None
class ActionRegistry:
    def add_menu(self, menu: MenuDef) -> None
    def add(self, action: ActionDef) -> None       # ValueError: duplicate id, unknown menu, bad chord, duplicate chord
    def menu_items(self, menu_id: str) -> tuple[ActionDef | MenuDef, ...]
    def invoke(self, action_id: str) -> bool        # False if disabled; handler exceptions → logged + status bar
    def cheat_sheet(self) -> list[CheatRow]        # (menu label, label without mnemonic, accelerator), current language
```
- Chords are parsed by `core.keys.parse_chord`. Tk sequences and accelerator text come from `core.keys.tk_shortcut(…, aqua=…)` (one grammar, aqua handled). Mnemonics come from `split_mnemonic`.
- `shell.py` binds each sequence once on the root with `bind_all`. The handler returns `"break"`, and does nothing when `enabled()` is false. Menu `postcommand` refreshes `state` from `enabled()`.

### 3.2 Step 12 actions (only implemented ones — D11)
| Menu | Action | Shortcut | Toolbar |
|---|---|---|---|
| _File | _New from template… | Ctrl+N | yes |
| _File | _Quit | Ctrl+Q | — |
| _View ▸ _Theme | _Light · _Dark · _High contrast (radio) | — | — |
| _View ▸ _Language | 8 autonyms (`LANGUAGES`, `translate=False`) · separator · `en_XA` "Pseudo-locale (layout test)" (radio) | — | — |
| _View | Next _panel · Previous pa_nel | F6 · Shift+F6 | — |
| _Help | _Keyboard shortcuts… | F1 | — |

The window close button (`WM_DELETE_WINDOW`) and Quit both call `app.quit()`. That checks `session.can_discard()`, then `dispose()`, then `root.destroy()`.

### 3.3 Focus and panel cycling
- **Order:** palette → canvas → tree → inspector → (wrap). Shift+F6 goes in reverse. Each panel's `focus_first()` focuses its main widget and, for a `Treeview`, the selected (or first) item.
- **Focus ring:** each panel sits in a `FocusFrame` (a `tk.Frame` with `highlightthickness` = 2 px scaled). A `bind_all("<FocusIn>")` handler marks the panel that contains the focus. Its border is set to the theme's `focus` colour, and the others are set to `bg`. This is a *focus-within* ring drawn by the shell, so it does not depend on ttk's 1 px `focusthickness` (`style/builders/button.py:75`).
- Tab order inside a panel is the widget order. Menus are reachable with Alt/F10, which Tk does natively.

## 4. Theming
### 4.1 ttkbootstrap 2.2 facts used
- `Style` is a process-wide singleton (`style/engine.py:61`). `App.destroy()` sets `Style.instance = None` (`window.py:728`), so themes must be **re-registered for every root**. A second live root raises `RuntimeError` (`window.py:69 _require_single_root`).
- **Do not use `Theme` (family).** `Theme._definition` (`style/theme.py:884`) only produces the names `<name>-light`/`<name>-dark` (no `-hc`). It also re-ramps anchors: on light, primary uses ramp step 600 (`_SOLID_STOP`, `theme.py:752`), so `#1C3FF0` would not render as itself.
- **Use** `ThemeDefinition(name, colors=Colors(16 fields), mode="light"|"dark")` (`theme.py:685`, exported by `ttkbootstrap.style`), registered with `Style.register_theme(definition)` (`engine.py:239`). Switch with `Style.theme_use(name)` (`engine.py:279`), which repaints the live tree and runs `on_theme_change` callbacks (`engine.py:479`).
- **Start-up:** create `App(title=…)` withdrawn, `install_themes(style, specs)`, `style.theme_use(initial)`, then `deiconify()`. This uses public API only, at the cost of one extra default-theme build. (`ttkbootstrap.utils.config.defer` would avoid that build, but it is an internal seam.)
- **Fonts:** `ttkbootstrap.Fonts.set_global_family(family, mono_family=…)` (`utils/fonts.py:79`; exported at the top level).

### 4.2 Theme data and token mapping
`ThemeSpec(name, role: "light"|"dark"|"high_contrast", mode, colors: Mapping[str, str], focus: str, sans: tuple[str, ...], mono: tuple[str, ...])` is loaded by `load_theme_specs()`. It is pure and validated strictly: 16 keys, `#RRGGBB`, mode in light/dark. Any defect → the defect is logged and the **neutral** specs are used.

| `Colors` field | SAPÉ token (`sape.{light,dark,high-contrast}.tokens.json`) |
|---|---|
| primary | `color.action.primary.background` |
| secondary | `color.semantic.neutral.solid` |
| success · info · warning · danger | `color.semantic.{success,info,warning,error}.solid` |
| light · dark | `color.background.subtle` · `color.background.inverse` |
| bg · fg | `color.background.base` · `color.text.primary` |
| selectbg · selectfg | `color.surface.selected` · `color.text.primary` |
| border | `color.border.control` (functional; never `subtle`) |
| inputbg · inputfg | `color.surface.base` · `color.text.primary` |
| active | `color.surface.raised` |
| *(focus, shell ring)* | `color.border.focus` |
| *(fonts)* | `font.family.primary` + `system_sans` list; `font.family.mono` + `system_mono` list |

- **Names:** `sape-light`, `sape-dark`, `sape-hc` (HC has mode `light`). The neutral MIT fallback is `pyguibud-light`, `pyguibud-dark`, `pyguibud-hc`. These are hand-picked greys and blue, defined in `themes/__init__.py`, and pass the same contrast gate.
- The **View ▸ Theme** menu shows **roles** (Light / Dark / High contrast). It maps them to the SAPÉ family when its data is present, else to neutral. A fork that deletes `sape.json` gets neutral themes with no code change.
- **Contrast gate (pure test, ACCESSIBILITY.md, WCAG 2.2 AA):** for every spec:
  - `fg/bg`, `inputfg/inputbg` and `selectfg/selectbg` must be ≥ 4.5;
  - for every accent fill (`primary`, `success`, `info`, `warning`, `danger`, `secondary`), **the on-colour ttkbootstrap actually paints** must be ≥ 4.5 against that fill. That colour is `builder.on_color(fill)` (`builders/button.py:45`) → `_accent_on_color` (`theme.py:191`), which accepts white down to 3.0:1 and is not necessarily the token's text colour. The test imports this private helper (test-only) and also checks `color.action.primary.text` on `primary`;
  - `border/bg`, `focus/bg` and `focus/selectbg` must be ≥ 3.0.

  The mapping above is the initial one; if a pair fails, the generator picks the next token, and the test is the gate.
- **Caveat on `selectbg`:** ttkbootstrap reuses `selectbg` as the neutral trough and border surface (`theme.py:807-812`). A tinted `color.surface.selected` may tint every trough (scale, progress, scrollbar). The 12b visual check covers troughs as well as selection. If they are tinted, use `color.background.subtle` for `selectbg` and keep the selection highlight in the shell's own `Treeview` tag.
- **Fonts:** `pick_family(preferred, available)` (pure) chooses the first installed family from `sans` (IBM Plex Sans → Segoe UI → Aptos → Arial). If none is installed, the Tk default is left untouched. Font files are not bundled (NOTICE §2).
- **Designer themes are chrome-only (D4).** They are never written into `.ui` `meta/@theme`. Templates carry no theme. One `Style` per process means the Step 13 canvas renders in the designer theme. The document theme is honoured by the Step 15 preview, which runs in a subprocess because `load_ui(master=None)` raises `RootExistsError` inside the designer.

### 4.3 Live switch
- `app.set_theme(role)` coalesces requests: it stores the pending role and runs `after_idle` once, so the last request wins.
- It then runs `theme_use`, followed by `apply_theme` (an `on_theme_change` callback): the focus-ring colours, `tk.Menu`/`tk.Frame` colours, and tags for muted/error rows.
- An unknown role or theme → a status bar message, and nothing changes. Re-entrancy is guarded by ttkbootstrap (`engine.py:367`).

### 4.4 Packaging — **USER DECISION D2 (licensing)**
`NOTICE.md` §2 says brand tokens are **all rights reserved, not MIT**, and the sdist already excludes `/assets/brand`. The wheel ships `src/pyguibud` whole, so anything placed under `src/` ships in both the wheel and the sdist.

| Option | What ships | Licence effect | Effort |
|---|---|---|---|
| **A (recommended)** | Generated `src/pyguibud/designer/themes/sape.json`: about 50 hex values + font names, with an "All rights reserved — SAPÉ; not MIT; forks must delete" header. Plus `tools/gen_themes.py` and a drift test (skipped when `assets/brand/` is absent). | Derived brand data in the MIT distribution. `NOTICE.md` §2 must list the path (user edit/approval). Matches the NOTICE intent ("included only to theme the official designer"). | low |
| B | `hatch force-include` of the raw `assets/brand/tokens/*.json` into the wheel | The whole token set is shipped, and wheels built from the sdist break (the sdist excludes the tokens) | low, fragile |
| C | Nothing in distributions. SAPÉ is used only from a checkout, or from a separate all-rights-reserved distribution `pyguibud-brand-sape`. | Cleanest MIT. PyPI users see the neutral themes. | medium |

All options include the neutral fallback. **What forks see:** neutral themes. NOTICE already obliges forks to remove the brand data, and removal needs no code change.

## 5. i18n
- **One i18n listener:** `DesignerApp._on_language` (a bound method, held weakly by `i18n.add_language_listener`; the app object is kept alive by `launch()`). It retranslates, in order:
  1. menus (`entryconfigure(label, underline)` per stored `(menu, index, action)`);
  2. toolbar;
  3. each panel's `retranslate()`;
  4. the window title;
  5. the status bar;
  6. open dialogs.

  Each step is isolated (`try`/log), so one failing panel never blocks the rest.
- Views store **msgids**, never translated text. Presenters re-run in the new language.
- The language menu calls `set_language(code)` on the Tk main thread only. An unknown code cannot occur (the menu lists `LANGUAGES` + `PSEUDO_LANGUAGE`). `set_language` raising `ValueError` → status bar message.
- **`en_XA` (D5):** always listed, after a separator (S3).
- **No fixed widths:** no `width=` on labels or buttons; `Treeview` columns get `stretch=True` with min widths only; dialogs size to their content (`update_idletasks` + `minsize`).
- Mnemonics must be unique per menu in every locale. A test covers the source and `en_XA` now, and every locale once Step 18 fills the catalogues.
- **Catalogue sync (every sub-step that adds strings):** run the `pybabel extract` and `pybabel update` commands in `docs/i18n/README.md`, then `pybabel compile`. `tests/test_catalogues.py::test_pot_matches_fresh_extraction` must stay green. The removed CLI placeholder msgid disappears from the `.pot`.
- **D6 (user decision 2026-10-06: deferred):** the shell strings are **not** translated in Step 12; only the catalogue sync runs (new msgids land untranslated in the 7 `.po` files). The live switch is verified with `en_XA` and with the existing stub strings; full translation stays in Step 18.
- **D7 persistence:** deferred to the Step 14 settings store (alongside recent files). Step 12 resolves the start-up language as `--lang` → `PYGUIBUD_LANG`/locale → `en_GB`, and the theme as `--theme` → `light`.

## 6. Templates and the new-file wizard (M12)
- **Templates:** `designer/templates/*.ui` package data (shipped by the wheel's `packages` rule). They are canonical, en-GB, `source_locale="en_GB"`, with no `meta/@theme`, and the texts are `translatable="true"`. They are the user's content, so they are not localised by the designer (D10). Every window and container carries a `<layout>`.
  - `main_window` — `kind="main"`, grid, a menubar with _File ▸ _Quit (`on_quit`) and a statusbar;
  - `dialog` — `kind="dialog"`, `modal="true"`, `buttons="ok cancel"`;
  - `login_form` — string variables `username` and `password`; Entry `show="*"`; Button `command → on_login`;
  - `settings` — a Notebook with 2 pages;
  - `empty_component` — `kind="component"`, empty grid.
- **Manifest:** `TEMPLATES: tuple[TemplateInfo(id, file, title msgid, description msgid), …]`, read with `importlib.resources.files(...).joinpath(file).read_bytes()`.
- `session.new_from_template(id)`:
  1. `read_ui_bytes(data, source=f"template:{id}")`;
  2. `validate_read(result, registry, files=None)` → any error → `TemplateError("designer.bad_template")`;
  3. `open_result(result, name=_("Untitled"))`;
  4. select the first window.
- **Start-up document (D9):** `main_window`.
- **Wizard (`dialogs/new_file.py`):** a modal `Toplevel` with a template list (Treeview) and a description label. Enter = create, Esc = cancel. It calls `session.can_discard()` first.
- **Tests:**
  - each template has zero errors and zero warnings with `validate(..., files=DiskFiles(path, result))`;
  - `dump_ui(read_ui(path).document) == path.read_bytes()` (canonical);
  - ids are not in `RESERVED_IDS`;
  - `pyguibud.uic.main(["--check", path])` returns 0 for each.

## 7. CLI
- `main(argv=None, *, launch: Callable[[str, str], int] | None = None) -> int`. With no action flag, after language selection it calls `launch(get_language(), args.theme)`. The default `launch` is a lazy `from pyguibud.designer import launch`.
- **New option:** `--theme {light,dark,high-contrast}` (D8). The theme choices are fixed English tokens; the help text is translated. A positional `.ui` path is **not** added in Step 12 (Step 14 owns opening files).
- **Unchanged behaviour:** `--version`, `--help`, `--list-languages`, and the `--lang` validation (exit 2). They never import `tkinter` (subprocess test checks `sys.modules`).
- **No display or no Tk:** `designer.launch` catches `ImportError` (tkinter missing) and `tkinter.TclError` when creating `App`. It prints a translated stderr message and returns **exit 1**:
  - `_("The designer window cannot be opened: {reason}")`;
  - plus `_("Install Tk for your Python (for example the python3-tk package).")` when tkinter is missing.

  No traceback is shown. Ctrl+C in the console → exit 130 quietly.
- The placeholder message at `cli.py:135` and its msgid are removed.

## 8. Testing
- **`tests/designer/conftest.py`:**
  - the display gate (`gui` marker; copy `_display()` from `tests/runtime/conftest.py`, or hoist it into a new `tests/conftest.py`);
  - **one package-scoped root** (`scope="package"`): `ttkbootstrap.App(title="designer-tests")`, withdrawn. ttkbootstrap allows one live root (`window.py:69`). If `Style.get_instance()` already has a live `master` (for example `pytest tests/runtime tests/designer` keeps the runtime session root alive), the fixture **reuses that root** and does not destroy it;
  - a function-scoped `shell` fixture that builds `DesignerApp(root, session)` and then calls `dispose()`. That destroys the children, runs `unbind_all` on what it bound, restores the `en_GB` theme `light`, and clears the `i18n` listeners.

  **Never** `Tk()` per test. The suite is about 100 s; the designer's Tk tests budget is ≤ 8 s.
- `DesignerApp` **accepts an injected root**. `launch()` alone creates `App`.
- **Pure tests (no Tk):** `Signal` isolation; session selection (foreign node ignored, origin loop); presenters on `examples/hello.ui` and a 2,000-widget document (`tree_rows` ≤ 150 ms); `ActionRegistry` (duplicates, chords, cheat-sheet in `en_XA`); theme specs (schema, contrast gate, drift vs `tools/gen_themes.py`, corrupt JSON → neutral); `pick_family`; templates (§6); CLI with a fake `launch` (exit codes, arguments passed through, no-display path).
- **Tk tests (`@pytest.mark.gui`):**
  - shell builds;
  - every theme role switches and `Style.theme_use()` reports it;
  - a language switch updates the menu labels, panel headings and title (`en_XA` contains `[`);
  - F6 cycles focus through the 4 panels;
  - tree ↔ canvas ↔ inspector selection sync;
  - the shortcut cheat-sheet lists every action with a shortcut;
  - 50 alternating theme and language toggles leave one listener and no exception.
- `pytest` keeps `--capture=sys`. **Existing tests that must change:** `test_main_no_args`, `test_pseudo_no_args` and `test_subprocess_pseudo_utf8` assume no arguments prints a placeholder. Rewrite them with the `launch=` seam (the subprocess test uses `--lang en_XA --list-languages`, whose first line is the translated heading, so `startswith("[")` still holds).

## 9. QA abuse list (shell)
- **Window size:** shrink to minimum, maximise, and drag sashes to 0. The root `minsize` is 800×500 scaled, and no panel collapses below its heading. Also try a 4K/150 % DPI and a 1366×768 screen.
- **Rapid toggling:** hold a key on repeated theme/language toggles, or click radios fast. Requests are coalesced; no crash; the final state matches the last choice.
- **Missing or corrupt `sape.json`:** delete or truncate the file, or use bad hex. The designer starts on neutral themes and logs once.
- **Odd language environment:** unknown `PYGUIBUD_LANG`, a garbage `--lang`, or `LANG=C` gives `en_GB` or exit 2 (existing tests). `en_XA` with the 40 % slack truncates no labels in the menus, the wizard or the cheat-sheet.
- **No display / missing font:** with no display (`DISPLAY=` on Linux, or headless CI) → exit 1 with a message. With no IBM Plex installed, fallback fonts are used.
- **Wizard:** press Ctrl+N twice quickly, which opens one modal only. Press Esc during the wizard. Quit while the wizard is open.
- **Keyboard and focus:** F6 with the wizard open stays modal. Ctrl+Q works from every panel. Focus is visible in every theme, HC included.
- **Large documents:** the selection highlights for 10,000 widgets and depth 100 (iterative presenters, no `RecursionError`). Duplicate or empty ids in a document read by tests are displayed without a crash.
- **Two designers:** a second `pyguibud` process is independent (no shared state in Step 12).

## 10. Atomic sub-steps (ordered by the UAT)
Each sub-step ends green with `uv run python -m pytest -q`, `uv run ruff check .` and `uv run mypy src`, plus the catalogue sync when strings changed.
| # | Content | Files | Verification |
|---|---|---|---|
| 12a | CLI `launch=` seam, `--theme`, no-display exit 1; `designer.launch` opens an empty themed `App`; the 3 CLI tests rewritten; designer test fixtures | `cli.py`, `designer/__init__.py`, `designer/app.py`, `tests/test_cli.py`, `tests/designer/conftest.py`, `tests/designer/test_launch.py` | `pytest tests/test_cli.py tests/designer` · `uv run pyguibud` shows a window |
| 12b | Theme specs + neutral themes + `gen_themes.py` + `sape.json` (**only if D2 = A**) + install/switch + fonts + contrast gate | `designer/theme.py`, `theme_tk.py`, `themes/`, `tools/gen_themes.py`, `tests/designer/test_theme*.py`, `NOTICE.md` (user) | `pytest tests/designer -k theme` |
| 12c | `Signal`, `DesignerSession`, `ActionRegistry`, the `main_window` template | `signals.py`, `session.py`, `actions.py`, `templates/__init__.py`, `templates/main_window.ui`, tests | `pytest tests/designer -k "session or actions or template"` |
| 12d | Shell: menubar/toolbar/status bar from the registry, 4 `FocusFrame` panel slots, View ▸ Theme and View ▸ Language live, the `retranslate` chain — **UAT reachable here** | `shell.py`, `panels/focus.py`, `app.py`, tests | `uv run pyguibud --lang en_XA`; switch theme and language |
| 12e | Panels: palette, tree, read-only inspector, canvas placeholder; selection sync; status bar findings | `present/*`, `panels/*`, tests | `pytest tests/designer -m gui` |
| 12f | ~~Translate the shell strings ×7~~ — **dropped (D6 deferred to Step 18)**; catalogue sync only, done in each sub-step | `locale/*` | `pytest tests/test_catalogues.py` |
| 12g | Keyboard: F6/Shift+F6, focus-within ring, mnemonic-uniqueness test, cheat-sheet dialog (F1) | `shell.py`, `dialogs/shortcuts.py`, tests | keyboard-only walkthrough |
| 12h | Other 4 templates + New-file wizard (Ctrl+N) | `templates/*.ui`, `dialogs/new_file.py`, tests | `pytest tests/designer -k template` · Ctrl+N in `uv run pyguibud` |
| 12i | QA §9 + an `en_XA` pass in every dialog; scoreboard | — | QA report |

- **12b is not blocked while D2 is open.** Build the neutral themes and `gen_themes.py` first. `sape.json` and the NOTICE line land only once D2 = A.
- **12d** also updates the `i18n.py` module docstring, which describes per-panel listeners. The shell uses one app-level listener (§5).

**Can slip to a follow-up session without failing the UAT:** 12g's cheat-sheet dialog (the accelerators show in the menus), 12h (keep only the `main_window` start-up document), and 12i's DPI checks. 12a–12e are the minimum for the UAT.

## 11. Decisions (recommended default in bold; **[USER]** = needs the user's answer)
**User answers 2026-10-06:** D2 = **A** · D4 = **accepted (designer-only)** · D6 = **deferred to Step 18 (no translation in Step 12)** · D7 = **accepted (deferred to Step 14)**. The other decisions take the architect's defaults.
- D1 **The canvas is a placeholder Notebook** (a summary card per window). Rendering via the backend waits for Step 13 (it needs a `_tk.py` embed mode plus parity tests).
- D2 **[USER, licensing]** How brand theme data ships: **A, a generated `sape.json` in `src/` + NOTICE carve-out**. B is force-include; C is no brand data in distributions. The neutral fallback ships in every case, and forks see neutral.
- D3 **Exact-colour `ThemeDefinition`/`Colors`** via `Style.register_theme`, re-registered for every root, started withdrawn. Not `Theme` families; not `config.defer`.
- D4 **[USER]** **Designer themes are chrome-only.** They are never written to `.ui`. This narrows the FEATURES.md §1 "Theme" row, which says SAPÉ themes are "shipped as ttkbootstrap themes". The Step 13 canvas uses the designer theme, and the Step 15 preview runs in a subprocess with the document theme.
- D5 **`en_XA` is always in the Language menu**, after a separator (S3). *Superseded by QA-12-12: listed only when the designer starts in `en_XA` (`--lang en_XA`).*
- D6 **[USER]** ~~Translate the ~50 shell strings into all 7 locales in Step 12~~ — *user answer: deferred to Step 18* (the live switch is verified with `en_XA`).
- D7 **[USER]** **Language/theme persistence is deferred to the Step 14 settings store.** Step 12 has `--lang` and `--theme`.
- D8 **CLI:** no arguments → GUI. `--theme light|dark|high-contrast`. No positional `.ui` until Step 14. No display → exit 1 with a message. `launch=` seam.
- D9 **Start-up document:** the untitled `main_window` template.
- D10 **Templates are en-GB `.ui` package data**, validated and canonical; they are the user's content, so they are not localised.
- D11 **Only implemented actions appear** (no disabled placeholders for future steps).
- D12 **Shortcuts:** Ctrl+N, Ctrl+Q, F6/Shift+F6, F1. They use the `core.keys` grammar. Theme and language have no shortcuts.
- D13 **Tests:** one package-scoped root in `tests/designer/conftest.py`. Hoisting all roots into `tests/conftest.py` is a later clean-up.
- D14 **The pure/Tk split** is enforced by a subprocess `sys.modules` test.
- D15 **The focus ring is a shell-drawn focus-within border** in `color.border.focus` (2 px scaled).
- D16 **The `pyguibud` console script stays.** A no-console `gui-scripts` entry is a Step 20 question.
