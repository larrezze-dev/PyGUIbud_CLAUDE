# PyGUIbud — v1 Feature Specification

> Status: **signed off (Step 02 UAT passed)** · Source of decisions: user interview, 2026-10-05 · Architecture decisions: [`docs/adr/`](./docs/adr/)

## 1. Decisions summary

| Topic | Decision | ADR |
| --- | --- | --- |
| Portability | One **abstract widget vocabulary** for every backend + **namespaced toolkit extensions** | [001](./docs/adr/ADR-001-abstract-vocabulary.md) |
| File format | XML, namespaced, `schema_version`, validated, migratable; images as **relative paths** | [002](./docs/adr/ADR-002-ui-file-format.md) |
| Behaviour | **Named handlers** + **named variables**; codegen by **composition** (pyuic style) | [003](./docs/adr/ADR-003-behaviour-binding-and-codegen.md) |
| Custom widgets | **Full plugin widgets** via entry points (icon, properties, live rendering) | [004](./docs/adr/ADR-004-widget-plugins.md) |
| Layouts | **grid + pack** (pack limited to one orientation per container); no `place` | [005](./docs/adr/ADR-005-layout-model.md) |
| Windows | Main window, Dialog, Reusable component; **multiple windows per `.ui`** | 002 |
| Theme | SAPÉ light / dark / high-contrast theme the designer itself; `.ui` files store any ttkbootstrap theme name (D4, Step 12) | 002 |
| Files | Single `.ui` files, recent files, autosave + crash recovery (no project folders in v1) | — |

## 2. MoSCoW

### Must
**Designer**
- M1 Palette → canvas drag-and-drop; move, reorder and reparent widgets in the canvas and the object tree.
- M2 Object tree (hierarchy) synchronised with the canvas selection; multi-select.
- M3 Property inspector: typed editors (text, number, bool, enum, colour, image, variable, handler), with defaults shown and resettable. *Font editor deferred until after v1 (Step 14 D8 = A, user 2026-10-08): no `font` property type exists yet.*
- M4 Undo/redo for **every** model change (command stack).
- M5 Layout editing: grid (rows/cols, span, sticky, weights, padding) and pack (orientation, fill, expand, padding).
- M6 Windows: main window (menubar, statusbar), dialogs (modal, standard buttons), reusable components (`<include>`); several windows per file.
- M7 Menubar/menu editor (actions with text, shortcut, icon, handler, separator, submenu).
- M8 Event panel: assign named handlers to abstract events.
- M9 Variables panel: declare `string/int/double/bool` variables and bind them to widgets.
- M10 Live preview in a real window, plus a live theme switch.
- M11 Copy / paste / duplicate, also between `.ui` files (clipboard carries XML).
- M12 Templates / new-file wizard: Main window, Dialog, Login form, Settings, Empty component.
- M13 Keyboard-only operation: every action reachable by keyboard; shortcut cheat-sheet.
- M14 Open/save single `.ui`, recent files, **autosave + crash recovery**, unsaved-changes guard on close.
- M15 Designer UI available in **en-GB, es-ES, pt-PT, pt-BR, de-DE, it-IT, nl-NL, fr-FR**; live language switch.

**Format, runtime & codegen**
- M16 `.ui` XML format, schema validation, `schema_version` + migration hook (ADR-002).
- M17 `pyguibud-runtime.load_ui(path, handlers=obj, translator=..., backend=...)` returns an object with `widgets`, `vars`, `windows`.
- M18 `pyguibud-uic file.ui -o file_ui.py`: standalone code (composition), handler stubs, `_()` calls; generated code has **no PyGUIbud import**.
- M19 `pyguibud-uic --extract` → `.pot` for the user's app; translatable flags/context/comments in `.ui`.
- M20 `pyguibud-uic --check` validates files (CI-friendly exit codes).
- M21 Backends: ttkbootstrap (reference), tkinter, PySide6 (`[pyside]` extra).
- M22 Widget plugin API (entry points) + live rendering in the designer (ADR-004).

**Idiot-proofing (QA gate)**
- M23 Invalid actions are **blocked with a translated reason**, never silently applied: child into a non-container, two mains per file, duplicate/invalid ids (must be Python identifiers, not keywords), cyclic includes, grid cell collisions, mixing grid and pack in one container, handler names that aren't identifiers, variables of the wrong type, out-of-range values.
- M24 Safe file handling: atomic save (write temp file → rename), backup of the previous version, refusal of corrupt/oversized/newer-schema files with a clear message, read-only paths detected before editing.
- M25 Plugin failures are isolated: a crashing plugin widget renders as a placeholder; the designer keeps running.

### Should
- S1 Alignment/distribution helpers for selected widgets in a grid.
- S2 Search/filter in the palette and the object tree.
- S3 Pseudo-locale preview (`en_XA`) in the designer to check text expansion.
- S4 Accessibility hints in the inspector (missing label for an entry, low contrast).
- S5 Export screenshot of the form (PNG) for docs.

### Could
- C1 Embed images as base64 (opt-in) for a single self-contained file.
- C2 Project folders (`pyguibud.toml`) with batch export.
- C3 Style editor for custom ttkbootstrap themes.
- C4 Import Qt Designer `.ui` (subset).

### Won't (v1)
- W1 `place` / absolute layout. W2 Inline Python code in `.ui`. W3 Parsing hand-edited `.py` back into `.ui`. W4 Right-to-left scripts. W5 Web/HTML targets. W6 Non-visual helpers such as ToastNotification placed on the canvas (they stay code-only).

## 3. v1 widget list

**Abstract core** (all backends). Names are PyGUIbud classes; columns show the mapping.

| # | PyGUIbud | ttkbootstrap / tkinter | PySide6 | Container |
|---|---|---|---|---|
| 1 | Frame | `ttk.Frame` | `QFrame` / `QWidget` | ✔ |
| 2 | LabelFrame | `ttk.Labelframe` | `QGroupBox` | ✔ |
| 3 | Notebook (+ Tab) | `ttk.Notebook` | `QTabWidget` | ✔ |
| 4 | PanedWindow (+ Pane) | `ttk.Panedwindow` | `QSplitter` | ✔ |
| 5 | ScrolledFrame | `ttkbootstrap.scrolled.ScrolledFrame` / canvas-based | `QScrollArea` | ✔ |
| 6 | Label | `ttk.Label` | `QLabel` | |
| 7 | Button | `ttk.Button` | `QPushButton` | |
| 8 | Entry | `ttk.Entry` | `QLineEdit` | |
| 9 | Text | `tk.Text` / `ScrolledText` | `QPlainTextEdit` | |
| 10 | Checkbutton | `ttk.Checkbutton` | `QCheckBox` | |
| 11 | Radiobutton | `ttk.Radiobutton` | `QRadioButton` (+ `QButtonGroup`) | |
| 12 | Combobox | `ttk.Combobox` | `QComboBox` | |
| 13 | Spinbox | `ttk.Spinbox` | `QSpinBox` / `QDoubleSpinBox` | |
| 14 | Scale | `ttk.Scale` | `QSlider` | |
| 15 | Progressbar | `ttk.Progressbar` | `QProgressBar` | |
| 16 | Separator | `ttk.Separator` | `QFrame` (HLine/VLine) | |
| 17 | Listbox | `tk.Listbox` | `QListWidget` | |
| 18 | Treeview | `ttk.Treeview` | `QTreeWidget` | |
| 19 | Scrollbar | `ttk.Scrollbar` | `QScrollBar` | |
| 20 | Canvas | `tk.Canvas` | `QGraphicsView` | |
| + | Menubar / Menu / Action | `tk.Menu` | `QMenuBar` / `QMenu` / `QAction` | |
| + | Statusbar | `ttk.Frame` + `Label` (convention) | `QStatusBar` | |

**ttkbootstrap extensions** (namespace `tb:`; each declares a `fallback` for other backends):

| Extension | Fallback (tkinter / PySide6) |
|---|---|
| `tb:Meter` | Progressbar |
| `tb:Floodgauge` | Progressbar |
| `tb:DateEntry` | Entry / `QDateEdit` |
| `tb:Tableview` | Treeview / `QTableWidget` |
| `tb:ToggleButton` (round/square toggle bootstyle) | Checkbutton |
| `tb:bootstyle` attribute on any core widget | ignored |

## 4. `.ui` schema draft (v1.0)

```xml
<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0"
             xmlns="urn:pyguibud:ui:1"
             xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">
  <meta generator="pyguibud 0.1.0" source_locale="en_GB" i18n_domain="myapp" theme="sape-light"/>

  <resources>
    <image id="img_save" src="icons/save.png"/>          <!-- relative to this .ui -->
  </resources>

  <variables>
    <var id="username" type="string" default=""/>
    <var id="remember" type="bool"   default="false"/>
  </variables>

  <window id="main" kind="main" min_width="480" min_height="320">
    <prop name="title" translatable="true">Sign in</prop>
    <menubar>
      <menu id="mnu_file"><prop name="text" translatable="true">_File</prop>
        <action id="act_quit" shortcut="Ctrl+Q" handler="on_quit">
          <prop name="text" translatable="true">_Quit</prop>
        </action>
      </menu>
    </menubar>

    <layout type="grid" padding="12" gap="6">
      <column index="1" weight="1"/>
    </layout>

    <widget class="Label" id="lbl_user">
      <prop name="text" translatable="true" context="login">User name</prop>
      <cell row="0" column="0" sticky="w"/>
    </widget>
    <widget class="Entry" id="ent_user" bind="username">
      <cell row="0" column="1" sticky="ew"/>
    </widget>
    <widget class="Checkbutton" id="chk_remember" bind="remember">
      <prop name="text" translatable="true">Remember me</prop>
      <cell row="1" column="1" sticky="w"/>
    </widget>
    <widget class="Button" id="btn_sign_in" tb:bootstyle="primary">
      <prop name="text" translatable="true">Sign in</prop>
      <prop name="image" ref="img_save"/>
      <event name="command" handler="on_sign_in"/>
      <cell row="2" column="1" sticky="e"/>
    </widget>
    <widget class="tb:Meter" id="mtr_strength" fallback="Progressbar">
      <cell row="3" column="0" columnspan="2"/>
    </widget>
    <include src="components/footer.ui" component="footer" id="footer">
      <cell row="4" column="0" columnspan="2" sticky="ew"/>
    </include>
  </window>

  <window id="dlg_about" kind="dialog" modal="true" buttons="ok">
    <layout type="pack" orient="vertical" padding="12"/>
    <widget class="Label" id="lbl_about">
      <prop name="text" translatable="true">About this app</prop>
      <pack fill="x"/>
    </widget>
  </window>

  <!-- third-party plugin widget (ADR-004) -->
  <!-- <widget class="acme:ColourPicker" plugin="acme-pyguibud" fallback="Frame" id="..."/> -->
</pyguibud-ui>
```

**Rules (enforced by the validator):**
- Root element `pyguibud-ui`; `schema_version` is `MAJOR.MINOR`. Newer MAJOR → refuse; newer MINOR → open read-only with a warning; older → migrate.
- `id` is unique per file, in one namespace shared by windows, widgets, includes, menus, actions, status bars, images and variables. It matches ASCII `^[A-Za-z][A-Za-z0-9_]{0,63}$` (so it never starts with `_`) and is not a Python keyword (Step 09).
- At most one `kind="main"` window; `kind="component"` windows can be `<include>`d (no cycles). Step 09 checks the include syntax and path form; Step 10 checks file existence, the component kind, cycles and limits (depth 8, 32 files, 10,000 widgets). `src="#"` includes a component of the same file; its component, kind, cycle and limit checks need no disk access and also run in the edit guards (Step 14a.2). Ids must not be one of `vars widgets windows setup_ui retranslate show run destroy`.
- `shortcut` (Action attribute) is a chord such as `Ctrl+S` or `Ctrl+Shift+F5` (modifiers `Ctrl`, `Alt`, `Shift`; keys A–Z, 0–9, F1–F24 and named keys); it needs Ctrl or Alt unless it is a function key. `key:<sequence>` events take a chord or a Tk-native sequence such as `<Control-s>`. Dialog `buttons` is a comma-separated list of `ok`, `cancel`, `yes`, `no`, `close`, without repeats.
- Image resources are PNG, GIF, PPM or PGM (decoded natively by the toolkit, no Pillow), at most 16 MiB and 4096 × 4096 px; paths are relative to the file that names them. `meta` `i18n_domain` is a plain name (letters, digits, `_`, `-`, `.`).
- Every window and layout container has exactly one `<layout>`, even when it is empty. Page containers (Notebook, PanedWindow) have none, and their children carry `<page>`. Children carry the matching placement (`<cell>` for grid, `<pack>` for pack).
- Pack uses one `orient` per container (maps to `QVBoxLayout`/`QHBoxLayout`).
- `handler` and `bind` must be identifiers; `bind` must reference a declared variable of a compatible type (table: `docs/specs/validate-commands.md` §5.1). Full rule list: that spec, §5.
- Abstract events: `command`, `change`, `select`, `activate` (double-click/Enter), `focus_in`, `focus_out`, `key:<Sequence>`.
- Unknown namespaced elements/attributes are preserved on save (forward compatibility) and ignored by backends that don't understand them.
- **Step 08 precision:** this draft is illustrative. The canonical spelling, attribute and element order, default omission and the `<page>` placement for Notebook and PanedWindow children are defined in ADR-002 Addendum A and `docs/specs/xml-io.md`. Comments like the ones above are dropped when the file is saved, and the reader issues a warning.

## 5. Plan impact
- New step **Widget plugin API + ttkbootstrap extensions** inserted after the backends step (see DEVELOPMENT_PLAN.md).
- Steps 12–15 (designer) now include: multi-window editor, menu editor, events/variables panels, templates, keyboard operation, autosave/crash recovery.

## 6. Sign-off (UAT for Step 02)
- [x] Decisions summary correct
- [x] MoSCoW lists correct (move anything you disagree with)
- [x] Widget list and mappings correct
- [x] Schema draft understood and acceptable
