# Spec — Step 09: validator and command stack

- **Status:** Ready for implementation. Decisions D1–D6 were made by the user on 2026-10-05 (§13) · **Date:** 2026-10-05 · **Owner:** BACKEND · **Sources:** FEATURES.md §4, ADR-001..005 (+ Addenda), ADR-006 (Accepted), `docs/specs/core-model.md`, `docs/specs/xml-io.md`, `ui-schema-rules` skill, DEVELOPMENT_PLAN §5 notes.
- Implement verbatim. Anything not listed here is out of scope (§12). "Model" means `pyguibud.core.model` as built in Steps 07–08.

## 1. Modules
| File | Contents |
|---|---|
| `src/pyguibud/core/diagnostics.py` | **new.** `Severity`, `Finding`, `SourceMap`, `node_path()` (§3). |
| `src/pyguibud/core/validate.py` | **new.** `validate()`, `validate_read()`, `ValidationReport`, `WidgetLookup`, rule data (`BIND_TYPES`, limits) (§4–5). |
| `src/pyguibud/core/commands.py` | **new.** `Command` and its subclasses, `Macro`, `CommandStack`, `Outcome`, `StackEvent`, helpers (§6). |
| `src/pyguibud/core/xml_io.py` | `XmlWarning = Finding` (alias). The `_Reader` records positions, and `ReadResult` gains `positions` (D1, D2). |
| `src/pyguibud/core/xmltree.py` | **+** `first_illegal_char(text: str) -> str \| None`. `check_chars` is rewritten on top of it (single source for §5 R54). |
| `src/pyguibud/core/registry.py` | **+** `registry.bad_display_name` (§7). |
| `src/pyguibud/uic.py` | `--check` also runs the validator (§8). |
| `examples/validator_demo.py` | UAT demo (§9). |

- **Import graph (no cycles):** `diagnostics → errors`; `xml_io → diagnostics`; `validate → model, diagnostics, xmltree, i18n` (it types the registry through the `WidgetLookup` Protocol and does not import `registry`); `commands → model, validate, diagnostics, errors, schema, i18n`; `uic → validate, registry, xml_io`.
- Stdlib only, no toolkit import, mypy strict (add `pyguibud.core.validate`/`commands`/`diagnostics` to the strict override list if it is per-module).
- **Re-exports from `pyguibud.core`** (add to `__all__`): `Finding`, `Severity`, `SourceMap`, `ValidationReport`, `WidgetLookup`, `validate`, `validate_read`, `CommandStack`, `Outcome`, `StackEvent`. Command classes stay in `pyguibud.core.commands`. `XmlWarning` stays exported.
- **Naming:** `pyguibud.core.Diagnostic` already exists (plugin loading, `registry.py`) and is unchanged. The new type is called `Finding` to avoid the clash.

## 2. Principles
- **One source of truth:** the validator is the only place where semantic rules live. Command guards run the validator; they never re-implement a rule (§6.3).
- **Never fail fast:** `validate()` returns every finding (up to a cap), in a deterministic order.
- **No recursion:** the validator and guards traverse with an explicit stack. They never call `walk()`, `iter_ids()` or `find()`, which use nested `yield from` (Step 19 builds 10 MiB / deeply nested documents).
- **Registry passed explicitly:** the reader stays registry-free; `validate(document, registry)` gets it as an argument.
- **Commands wrap the Step 07 primitives** (`insert_child`, `remove_child`, `move_child`, `set_prop`, `remove_prop`) and plain assignment of whitelisted fields. No command re-implements tree surgery.

## 3. Findings and positions (`diagnostics.py`)
```python
Severity = Literal["error", "warning"]

@dataclass(frozen=True, slots=True, kw_only=True)
class Finding:                       # XmlWarning's fields first, unchanged order and defaults
    code: str; msgid: str; params: Mapping[str, object]   # read-only proxy, hash=False
    source: str; line: int | None = None; column: int | None = None
    severity: Severity = "warning"                         # new
    path: str = ""                                         # new, untranslated node path (§3.2)
    anchor: object | None = field(default=None, compare=False, hash=False, repr=False)  # new
    part: str = ""                                         # new, sub-element of the anchor (§3.2)
    message -> str     # property, format_message(msgid, params); never raises
    location -> str    # property, unchanged: "source:line:column" (parts omitted when None)
    is_error -> bool   # property, severity == "error"
    __str__ -> f"{location}: {message}"   # unchanged
```
- **D1 (user, 2026-10-05):** `xml_io.XmlWarning` becomes an alias, `XmlWarning = Finding` (kept in `__all__`). Every reader warning keeps `severity="warning"` and `path=""`, so existing construction, equality and output stay identical.
- `anchor` is the model node the finding is about (the designer selects it in Step 14). It is excluded from equality, so golden tests compare plain data.

### 3.1 Positions (D2, user 2026-10-05: option a)
The reader's `element → (line, col)` map is dropped after parsing, and model nodes carry no position.

| Option | Verdict |
|---|---|
| **(a) Side table on `ReadResult`, keyed by `(anchor, part)`** | **Recommended.** No model change. Tree nodes are `eq=False`, so they hash by identity (Menubar, Statusbar and Meta too). Value objects (Prop, Event, GridCell, Variable…) hash by value and would collide, so they are addressed through `part` on their owner. |
| (b) Keyed by node path string | Rejected. Paths are built from ids, and duplicate ids are exactly what the validator reports. They also break on rename. |
| (c) A `source_pos` field on every node | Rejected. Model change, not round-trip data, and it goes stale after edits. |

```python
class SourceMap:                      # immutable after construction
    def __init__(self, entries: Mapping[tuple[object, str], tuple[int, int]] = {}) -> None
    def get(self, anchor: object, part: str = "") -> tuple[int, int] | None
        # exact (anchor, part); else (anchor, part before the first "/"); else (anchor, ""); else None
    def __len__(self) -> int
EMPTY_SOURCE_MAP: Final = SourceMap()
```
- `ReadResult` gains `positions: SourceMap = EMPTY_SOURCE_MAP` (last field). The `_Reader` records an entry each time it builds something, using the element's position from `ParsedTree.positions`:
  - `(node, "")` for Document (root), Window, Widget, Include, Menubar, Menu, Action, MenuSeparator, Statusbar;
  - `(owner, "prop[<name>]")`, `(widget, "event[<index>]")`, `(owner, "cell"|"pack"|"page")`, `(owner, "page/prop[text]")`, `(owner, "layout")`, `(owner, "layout/column[<list index>]")`, `(owner, "layout/row[<list index>]")`;
  - `(document, "resources/image[<id>]")`, `(document, "variables/var[<id>]")`, `(document, "meta")`.
- Elements created by a migration have no position and get no entry.
- **Validity:** positions describe the document **as read**. `uic` and `validate_read` pass them. The command stack never does, so findings from guards have no line. Edited nodes keep their load-time entry, and that is documented as harmless.

### 3.2 Node path (`node_path(anchor, part="") -> str`)
- Untranslated and slash-separated, using the existing `{where}` grammar of xml-io §8: `window[main]/menubar/menu[mnu_file]/action[act_quit]`, `window[main]/widget[nbk_main]/widget[frm_greeting]/layout/column[0]`, `variables/var[user_name]`, `resources/image[img]`, `meta`.
- Segments: `window[id]`, `menubar`, `menu[id]`, `action[id]`, `separator[<index in parent>]`, `statusbar[id]`, `widget[id]`, `include[id]`. An empty id becomes `#<index in parent>`, for example `widget[#2]`.
- The path is built by following `parent` (iterative). A detached node gets the path of its own subtree root.

## 4. Validator API (`validate.py`)
```python
MAX_FINDINGS: Final = 1000
MAX_GRID_INDEX: Final = 9998          # Tk 8.6 grids rows/columns 0..9998 (row + span <= 9999; QA-14a1-01)
MAX_PIXELS: Final = 10_000            # padding, gap, padx/pady, minsize, min_width/min_height
MAX_WEIGHT: Final = 10_000            # grid line weight, page weight
MAX_ID_LENGTH: Final = 64
MAX_TEXT_LENGTH: Final = 100_000      # string property values (R79); the runtime clips translations to it
MAX_DEFAULT_LENGTH: Final = 10_000    # variable defaults (R80): Tk entries lay text out in quadratic time
MAX_NESTING: Final = MAX_DEPTH - 2    # max XML element depth of a node element (§5 R23)

class WidgetLookup(Protocol):
    def get(self, name: str) -> WidgetSpec | None: ...      # Registry satisfies it

@dataclass(frozen=True, slots=True)
class ValidationReport:
    findings: tuple[Finding, ...]
    truncated: bool
    errors -> tuple[Finding, ...]; warnings -> tuple[Finding, ...]; ok -> bool  # no errors

def validate(document: Document, registry: WidgetLookup, *, source: str = "<memory>",
             positions: SourceMap | None = None, limit: int | None = MAX_FINDINGS,
             files: FileAccess | None = None) -> ValidationReport
    # limit=None: unbounded (used by command guards); otherwise an int >= 1 (not a bool),
    # else ValueError (QA Step 09: 0 used to be raised silently to 1)
def validate_read(result: ReadResult, registry: WidgetLookup, *,
                  files: FileAccess | None = None) -> ValidationReport
    # = validate(result.document, registry, source=result.source, positions=result.positions, files=files)

RESERVED_IDS: Final = frozenset({"vars", "widgets", "windows", "setup_ui", "retranslate", "show", "run", "destroy"})

class FileAccess(Protocol):            # §5.2; core/files.py::DiskFiles implements it
    @property
    def root(self) -> str: ...                                  # key of the validated document
    def resolve(self, including: str, src: str) -> str: ...     # "#" -> including; raises OSError
    def read(self, key: str) -> ReadResult: ...                 # cached; raises OSError or XmlIoError
    def probe_image(self, including: str, src: str) -> ImageProbe: ...
```
- Pure function. It never mutates the document and never raises for any document shape the model types allow. A value of the wrong Python type (a hand-built model) is reported as R31/R09, not as a `TypeError`.
- **Traversal order (deterministic):**
  1. the document (R06);
  2. `resources` in dict order;
  3. `variables` in dict order;
  4. each window in child order: the window, then its menubar subtree pre-order, then its statusbar, then its widget/include tree pre-order (explicit stack, children in order).
- **Rule order per node:** the order of the §5 table. Props are visited **sorted by name** (the writer's canonical order); events and grid lines in list order. Findings are emitted in visit order, and no sorting is done afterwards.
- **Single pass:** global rules are emitted at the node where they become visible. A duplicate id is reported at the second and later occurrences, with `{first}` = the path of the first. A second main window is reported at that window. Because resources and variables come first, a widget reusing a variable id is reported at the widget.
- **Cap:** after `limit` findings, no more findings are stored (rules keep running only to count). The last finding is `validate.truncated` (R55), whose severity is that of the worst finding dropped, and `truncated=True`. `ok` is still exact, because error counting continues to the end.
- **Effective spec of a widget:**
  - the registered spec (`registry.get(class_name)`);
  - else, for an extension with a core `fallback`, the fallback's spec ("fallback mode");
  - else none (R24/R25): the widget's own structural checks are skipped, and its children are validated with placement checks skipped.

## 5. Rule inventory
Codes are stable. Params in `{}`. "E" = error, "W" = warning. Ids, paths, class names and attribute names inside messages are untranslated values. Every msgid is wrapped in `N_()` at module level, with a `# Translators:` comment wherever a placeholder is not obvious.

| # | Code | Sev | msgid (en-GB) | What / where (anchor) |
|---|---|---|---|---|
| **Ids** — one flat namespace per file: windows, widgets, includes, menus, actions, statusbars, image resources and variables (FEATURES §4 "unique per file"; codegen exposes `ui.<id>` and `ui.vars.<id>`, and a shared namespace avoids future clashes) |
| R01 | `validate.duplicate_id` | E | "The id '{id}' is used more than once; the first use is {first}." | second and later occurrences in traversal order |
| R02 | `validate.empty_id` | E | "This element has no id; every element needs a unique id." | node with `id == ""` |
| R03 | `validate.bad_id` | E | "'{id}' is not a valid id: use up to {limit} letters (a–z, A–Z), digits and underscores, starting with a letter." | regex `^[A-Za-z][A-Za-z0-9_]{0,63}$` fails (this also covers a leading `_`, Unicode, spaces) (D3) |
| R04 | `validate.keyword_id` | E | "'{id}' is a Python keyword and cannot be used as an id." | `keyword.iskeyword(id)`. Soft keywords (`match`, `type`…) are allowed. |
| **Windows** |
| R05 | `validate.multiple_main` | E | "Only one window can be the main window; {first} already is." | each `kind="main"` window after the first |
| R06 | `validate.no_windows` | W | "The document has no windows." | document |
| R07 | `validate.component_chrome` | E | "The component window '{id}' cannot have a menu bar or a status bar." | component window with `menubar` or `statusbar` |
| R08 | `validate.dialog_only` | W | "'{attribute}' only applies to dialog windows and is ignored on '{id}'." | `modal=True` or `buttons is not None` on a non-dialog |
| **Ranges** (int fields; the writer already limits them to 9 digits) |
| R09 | `validate.out_of_range` | E | "{field} must be between {minimum} and {maximum}, not {value}." · variants "{field} must be at least {minimum}, not {value}." / "{field} must be at most {maximum}, not {value}." | `min_width`/`min_height` 0..MAX_PIXELS; layout `padding`/`gap` 0..MAX_PIXELS; grid line `index` 0..MAX_GRID_INDEX, `weight` 0..MAX_WEIGHT, `minsize` 0..MAX_PIXELS; cell `row`/`column` 0..MAX_GRID_INDEX, `rowspan`/`columnspan` ≥ 1 with `row+rowspan`/`column+columnspan` ≤ MAX_GRID_INDEX+1; `padx`/`pady` 0..MAX_PIXELS; page `weight` 0..MAX_WEIGHT; int/float props vs `PropertyDef.minimum/maximum`. `{field}` is the attribute or prop name. |
| **Containers, layouts, placements** (ADR-005 + Addendum A) |
| R10 | `validate.not_a_container` | E | "'{parent}' ({class_name}) cannot contain other widgets; move '{id}' into a container." | each child (widget or include) of a widget whose effective spec has `children` ≠ `layout`/`pages` |
| R11 | `validate.layout_not_allowed` | E | "'{id}' ({class_name}) is not a container and cannot have a layout." | `layout` on a `children="none"/"menu"` widget |
| R12 | `validate.layout_on_pages` | E | "'{id}' ({class_name}) shows its children as pages and cannot have a layout." | `layout` on a `children="pages"` widget (Notebook, PanedWindow) |
| R13 | `validate.layout_missing` | E | "'{id}' has no layout; add a grid or a pack layout." | every window and every `children="layout"` widget (including fallback mode) with `layout is None`, **even when empty** (D6, FEATURES §4). Page containers are the exception: they must have none (R12). |
| R14 | `validate.placement_missing` | E | "'{id}' needs a {expected} placement inside '{parent}'." | child without `placement`, where the parent kind is known: `<cell>` (grid), `<pack>` (pack), `<page>` (pages) |
| R15 | `validate.placement_mismatch` | E | "'{id}' has a {found} placement, but '{parent}' expects {expected}." | wrong placement type. This covers "mixed grid/pack" and "`<page>` only on page-container children". `{found}`/`{expected}` are the literal tags `<cell>`, `<pack>`, `<page>`. |
| R16 | `validate.grid_collision` | E | "'{id}' overlaps '{other}' in the grid at row {row}, column {column}." | later child of two overlapping cells (spans included). Algorithm: sort the children's rectangles by `(row, column)` and sweep, O(n log n + k); at most one finding per child. |
| R17 | `validate.bad_sticky` | E | "'{value}' is not a valid sticky value; use any of n, s, e and w, each at most once." | `sticky` not matching `^(?!.*(.).*\1)[nsew]{0,4}$` |
| R18 | `validate.grid_lines_on_pack` | E | "A pack layout cannot configure grid columns or rows." | pack layout with non-empty `columns`/`rows` |
| R19 | `validate.duplicate_grid_line` | E | "Grid column {index} is configured more than once." / "Grid row {index} is configured more than once." | repeated `GridLine.index` inside `columns` (or `rows`) |
| R20 | `validate.orient_ignored` | W | "'orient' only applies to pack layouts and is ignored here." | grid layout with `orient="horizontal"` (the model stores one `orient` per layout, so "mixed pack orientation" cannot be represented and needs no rule) |
| R21 | `validate.page_attr_ignored` | W | "'{attribute}' of a page is ignored by {class_name}." | `weight` ≠ 0 under Notebook; `text`/`image` under PanedWindow |
| R22 | `validate.structural_class` | E | "'{class_name}' is a menu or window element and cannot be used as a widget." | `<widget class="Menubar\|Menu\|Action\|Statusbar">`, or a registered spec with `children="menu"` |
| R23 | `validate.too_deep` | E | "'{id}' is nested too deeply; a .ui file allows at most {limit} levels." | node whose XML element depth (root = 1, window = 2, +1 per widget/menu level) exceeds `MAX_NESTING`; reported once per subtree root. Keeps the writer from emitting `xml.too_deep`. |
| **Classes and plugins** (ADR-001/004) |
| R24 | `validate.unknown_class` | E | "Unknown widget class '{class_name}'." | unprefixed class not registered |
| R25 | `validate.missing_fallback` | E | "The extension widget '{id}' ({class_name}) needs a fallback core class." | extension with `fallback is None`, **even if the plugin is installed** (the file must open everywhere) |
| R26 | `validate.bad_fallback` | E | "'{fallback}' is not a core widget class and cannot be the fallback of '{id}'." | `fallback` not in `CORE_CLASS_NAMES`, or structural (R22 set) |
| R27 | `validate.fallback_mismatch` | E | "The fallback '{fallback}' of '{id}' does not match {class_name}: one is a container and the other is not." | registered extension whose spec `.container` ≠ fallback spec `.container` |
| R28 | `validate.plugin_missing` | W | "'{class_name}' is not installed, so '{fallback}' is shown instead; install it with: pip install {plugin}" · variant without plugin: "'{class_name}' is not installed, so '{fallback}' is shown instead." | unregistered extension with a valid fallback |
| R29 | `validate.extension_attr_ignored` | W | "'{attribute}' only applies to extension widgets and is ignored on '{id}'." | `fallback`/`plugin` set on a core widget |
| **Properties** (vs the effective spec's `PropertyDef`s; window props vs the validator's built-in `WINDOW_PROPERTIES = (PropertyDef(name="title", type="string", translatable=True),)`; Menu/Action/Statusbar props vs their registry specs; not checked in fallback mode or for unknown classes) |
| R30 | `validate.unknown_prop` | W | "{class_name} has no property '{name}'; it is kept but ignored." | prop name not in the spec |
| R31 | `validate.bad_prop_value` | E | int: "The property '{name}' must be a whole number, not '{value}'." · float: "…must be a number, not '{value}'." · bool: "…must be true or false, not '{value}'." · enum: "…must be one of {choices}, not '{value}'." · colour: "…must be a colour such as #1a2b3c or a colour name, not '{value}'." | grammar: int `^-?[0-9]{1,9}$`; float `^-?(?:[0-9]{1,15}(?:\.[0-9]{1,15})?\|\.[0-9]{1,15})$`; bool `true\|false`; enum exact member; colour `^#(?:[0-9a-fA-F]{3}){1,2}$\|^#[0-9a-fA-F]{12}$\|^[A-Za-z][A-Za-z0-9 ]{0,39}$`. An empty value is invalid for these types (unset = remove the prop). Range → R09; the widget size props `width`, `height` (Frame, LabelFrame, ScrolledFrame, Notebook, Label, Button, Entry, Combobox, Spinbox, Text, Canvas, Listbox, Treeview) and `length` (Scale, Progressbar) have `maximum` 10 000 (`widgets._MAX_SIZE`, QA-10-02: tens of millions of pixels freeze Tk), so a larger value is R09. A `string` value longer than 100 000 characters → R79. |
| R32 | `validate.not_translatable` | E | "The property '{name}' cannot be translatable." | `Prop.translatable` on a def with `translatable=False` |
| R33 | `validate.image_needs_ref` | E | "The image property '{name}' must refer to an image resource (and have no text)." | `type="image"` with `ref` None/empty or `value` ≠ "" |
| R34 | `validate.ref_not_allowed` | E | "The property '{name}' is not an image and cannot refer to a resource." | `ref` set on a non-image def |
| R35 | `validate.unknown_resource` | E | "'{ref}' is not a declared image resource." | `Prop.ref` (any owner, including unknown props) and `PagePlacement.image` not in `document.resources` |
| **Events, handlers, binding** (ADR-003) |
| R36 | `validate.bad_event` | E | "'{name}' is not a valid event; use command, change, select, activate, focus_in, focus_out or key:<sequence>." | `not is_valid_event(name)` |
| R37 | `validate.unsupported_event` | E | "{class_name} does not support the event '{name}'." | an abstract event not in `spec.events`; `key:` without `focus_in` in `spec.events`. Skipped in fallback mode. |
| R38 | `validate.duplicate_event` | E | "The event '{name}' is handled more than once on '{id}'." | repeated `Event.name` on one widget |
| R39 | `validate.bad_handler` | E | "'{handler}' is not a valid handler name: use letters, digits and underscores, starting with a letter, and no Python keyword." | `Event.handler`, `Action.handler` (when not None) failing the R03/R04 identifier rule (the handler is passed to `getattr`, so `__init__`-style names are blocked) |
| R40 | `validate.bad_bind` | E | "'{bind}' is not a valid variable name." | `bind` (not None) failing the identifier rule |
| R41 | `validate.unknown_variable` | E | "'{bind}' is not a declared variable." | `bind` not in `document.variables` |
| R42 | `validate.bind_not_supported` | E | "{class_name} cannot be bound to a variable." | `bind` on a class whose `BIND_TYPES` row is empty |
| R43 | `validate.bind_type_mismatch` | E | "{class_name} cannot be bound to the {type} variable '{bind}'; use one of: {allowed}." | variable type not in the row |
| R44 | `validate.bad_variable_default` | E | "The default '{default}' of the variable '{id}' is not a valid {type} value." | non-empty default not matching: int (R31 int), double (R31 float), bool (`true\|false`); a string default is valid up to 10 000 characters (longer → R80) |
| **Resources, includes, paths** |
| R45 | `validate.empty_path` | E | "'{id}' has no file path." | `ImageResource.src == ""`, `Include.src == ""` |
| R46 | `validate.absolute_path` | W | "The path '{path}' is absolute; use a path relative to the .ui file." | `PurePosixPath(p).is_absolute()` or `PureWindowsPath(p).anchor` non-empty (`C:`, `/`); UNC and device paths are R82 errors instead (Step 11) |
| R47 | `validate.path_escapes` | W | "The path '{path}' points outside the folder of the .ui file." | after splitting on `/` and `\`, a `..` segment takes the depth below 0 |
| R48 | `validate.bad_component` | E | "'{component}' is not a valid component id." | `Include.component` failing the identifier rule |
| R49 | `validate.include_missing` | E | "The included file '{src}' does not exist or cannot be read." | `files=` only: `resolve`/`read` raised `OSError` (missing file, directory, permission) |
| R50 | `validate.include_invalid` | E | `NP_` "The included file '{src}' has {count} error." / "…has {count} errors."; read failure: "The included file '{src}' cannot be read: {reason}" | `files=` only: `XmlIoError`, or validator errors (or image errors, R75/R76) in that file. The file is not followed further. |
| R51 | `validate.include_not_component` | E | "'{src}' has no component window '{component}'." / "The window '{component}' in '{src}' is not a component." | `files=` only: id absent / `kind != "component"` |
| R52 | `validate.include_cycle` | E | "Including '{component}' from '{src}' creates a cycle: {chain}." | `files=` only: DFS over `(file, component)`; `{chain}` = `a.ui#x → b.ui#y → a.ui#x`; reported once, at the closing include |
| R53 | `validate.include_limit` | E | three msgids: "Including '{src}' nests includes deeper than {limit} levels." / "…reads more than {limit} files." / "…creates more than {limit} widgets." | `files=` only: `MAX_INCLUDE_DEPTH = 8`, `MAX_INCLUDE_FILES = 32` (root included), `MAX_EXPANDED_NODES = 10_000` widgets and includes instantiated through includes. Once a limit is hit, nothing more is followed. |
| **General** |
| R54 | `validate.illegal_char` | E | "{where} contains the character U+{codepoint}, which a .ui file cannot store." | any visited model string (prop value/context/comment, src, handler, shortcut, buttons, var default, page text, meta fields) where `xmltree.first_illegal_char` finds one. Keeps the guard in line with the writer contract. |
| R55 | `validate.truncated` | worst dropped | "{count} more problems were found but not listed." | last finding when the cap is hit |
| **Writer contract (R56–R64): values `dump_ui` refuses and the reader would reject; added so that every state the command stack accepts is serialisable** |
| R56 | `validate.bad_window_kind` | E | "{field} must be one of {choices}, not '{value}'." | `Window.kind` not in `main, dialog, component` |
| R57 | `validate.bad_layout_type` | E | same msgid as R56 | `Layout.type` not in `grid, pack` |
| R58 | `validate.bad_orient` | E | same msgid as R56 | `Layout.orient` not in `vertical, horizontal` |
| R59 | `validate.bad_fill` | E | same msgid as R56 | `PackPlacement.fill` not in `none, x, y, both` |
| R60 | `validate.bad_variable_type` | E | same msgid as R56 | `Variable.type` not in `string, int, double, bool` |
| R61 | `validate.bad_class_name` | E | "'{name}' is not a valid widget class name." | an extension (`:` in the name) failing `split_class_name` (`tb:meter`, `a:b:c`). Core names are covered by R24. |
| R62 | `validate.not_text` | E | "{where} must be text, not '{value}'." | any string field of R54 (and `Prop.name`, page image) holding a non-`str`, non-None value. `None` is reported too where the writer has no way to omit the value: `Prop.name`, `Prop.value` (page text included), `Meta.source_locale` and extra attribute values. |
| R63 | `validate.not_flag` | E | "{field} must be true or false, not '{value}'." | `Window.modal`, `PackPlacement.expand`, `Prop.translatable` that are not a real `bool` |
| R64 | `validate.bad_page_text` | E | "The text of a page must be a property named 'text'." | `PagePlacement.text` that is not a `Prop` named `text` |
| **Preserved content and shapes (R65–R68, QA Step 09): more of the writer contract, for content a command can reach** |
| R65 | `validate.bad_attribute_name` | E | "'{name}' is not a valid extra attribute name for {where}." | an `extra_attrs` key of any node or value object (Prop, Event, Variable, ImageResource, GridCell, PackPlacement, PagePlacement, Layout, GridLine, Meta, Document, the `<resources>`/`<variables>` extras) that is not a string, not an XML NCName or `{uri}NCName`, starts with `xmlns`, or is one of the element's own known attributes (`schema.KNOWN_ATTRIBUTES`, shared with the writer). Its values follow R54/R62. |
| R66 | `validate.bad_raw_xml` | E | "The preserved XML content of {where} is damaged and cannot be saved." | `extra_children` that is not a list/tuple, or holds an entry that is not a `RawXml`, has `RawXml.extra_attrs`, does not parse as exactly one element (`xmltree.parse_fragment`), or is an element of the `.ui` vocabulary. One finding per owner. Parsing is cached by text. The depth of a `RawXml` subtree is left to the writer (safety net, §6.3). |
| R67 | `validate.bad_item` | E | "{where} contains '{value}', which is not a {expected}." | a collection entry of the wrong model type in a hand-built model: `Widget.events` (not a list, or an item that is not an `Event`), `Layout.columns`/`rows` (not a tuple, or an item that is not a `GridLine`), a `props` value that is not a `Prop`, a `resources`/`variables` value of the wrong type. `{expected}` is the untranslated type name. |
| R68 | `validate.bad_schema_version` | E | "The schema version '{version}' cannot be saved; it must be {current}." | `Document.schema_version` that is not a string, does not parse as `MAJOR.MINOR`, or is older than `CURRENT_SCHEMA_VERSION` (a read document is always migrated, so only a hand-set value gets here). A **newer** version is not an error: it is read-only (§6.6), and `uic --check` still exits 0 for it. |
| **Step 10 (runtime, `docs/specs/runtime.md` §9): ids that clash with `ui.<id>`, dialog buttons, shortcuts and keys, images, radio values, domain** |
| R69 | `validate.reserved_id` | E | "'{id}' is reserved by the generated interface and cannot be used as an id." | any id owner (resources and variables included) with an id in `RESERVED_IDS` = `vars widgets windows setup_ui retranslate show run destroy`; checked after R03/R04, so a keyword or malformed id gets only that finding |
| R70 | `validate.bad_buttons` | E | "'{value}' is not a valid button list; use a comma-separated list of {choices} without repeats." | **dialog windows only** (others keep R08's "ignored" warning): `^T(,T)*$`, `T = ok\|cancel\|yes\|no\|close`, no duplicates, no spaces |
| R71 | `validate.bad_shortcut` | E | "'{value}' is not a valid shortcut, for example Ctrl+S or Ctrl+Shift+F5." / "The shortcut '{value}' needs Ctrl or Alt unless it is a function key (F1–F24)." | `Action.shortcut` not a chord (`core/keys.py`), or a chord without Ctrl/Alt that is not F1–F24. `""` is an error; `None` is fine. |
| R72 | `validate.bad_key_sequence` | E | "'{value}' is not a valid key, for example key:Ctrl+S or key:<Control-s>." | `key:` event whose non-empty sequence is neither a chord nor the Tk-native `<(Mod-)*(Key-)?keysym>` form (R36 still covers an empty sequence and whitespace) |
| R73 | `validate.duplicate_shortcut` | W | "The shortcut '{shortcut}' is used more than once in '{window}'; only the first one works." | same canonical chord twice among one window's actions (`Enter` = `Return`) |
| R74 | `validate.image_format` | E | "'{src}' is not a supported image; use PNG, GIF, PPM or PGM." | resource `src` suffix (case-insensitive) not `.png .gif .ppm .pgm` (no Pillow, decision U6) |
| R75 | `validate.image_missing` | E | "The image file '{src}' does not exist." | `files=` only: the file is not there |
| R76 | `validate.image_invalid` | E | "The image file '{src}' cannot be used: {reason}" | `files=` only: not a regular file, over 16 MiB, content not matching the suffix, damaged or zero-size header, or a side over 4096 px (only the header is read: the first 64 bytes, and for a GIF also the blocks up to its first image descriptor, whose size must be 1..4096 px too (QA-10-10); `{reason}` is a lazily translated msgid) |
| R77 | `validate.bad_radio_value` | E | "The value '{value}' of '{id}' must be a whole number, because it is bound to the int variable '{bind}'." | Radiobutton (or an extension falling back to it) bound to an `int` variable whose `value` prop is absent or not an int |
| R78 | `validate.bad_i18n_domain` | E | "'{value}' is not a valid translation domain; use letters, digits, '_', '-' or '.'." | non-empty `meta.i18n_domain` not matching `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$`, or containing `..` (it becomes a file name) |
| R79 | `validate.text_too_long` | E | "The property '{name}' has {length} characters; at most {limit} are allowed." | a `string` property value (text, title, page text, menu/action/statusbar text, Entry `show`, Radiobutton `value`) longer than `MAX_TEXT_LENGTH` (100 000). The runtime clips translations to the same constant (runtime.md §6.1). |
| R80 | `validate.text_too_long` | E | "The default of the variable '{id}' has {length} characters; at most {limit} are allowed." | a variable `default` longer than `MAX_DEFAULT_LENGTH` (10 000): a bound Entry/Combobox/Spinbox shows it, and Tk lays entry text out in quadratic time |
| R81 | `validate.bad_source_locale` | E | "'{value}' is not a valid language code for the source texts; use a code such as en_GB." | `meta.source_locale` not matching `i18n.LANGUAGE_CODE_RE` (`^[A-Za-z]{2,3}([_-][A-Za-z0-9]{2,8})*$`); generated modules compare it with the requested language (QA-11-11, Step 11) |
| R82 | `validate.network_path` | E | "The path '{path}' points to a network share or a device, which is never opened; use a path relative to the .ui file." | image or include `src` that is UNC or a Win32 namespace (`//host/share`, `\\host\share`, `\\?\`, `\\.\`, `\??\`) or has a Win32 device segment (`CON`, `nul.png`, `COM1 .gif`, any case and extension): `core.files.is_network_or_device_path`, a pure string test run before any file access; R46/R47 are then not reported, and the file rules skip the path (QA-11-03, Step 11, user decision "Block UNC") |

R56–R68 cannot occur in a file (the reader refuses the values), so their golden case is built in memory: `tests/core/data/validate/r56_r64_model_only.findings.txt`. `tests/core/test_commands_roundtrip.py` pushes invalid values through every `SetField` field and the variable, resource, property and event commands and asserts that what the stack accepts always passes `dump_ui` → `read_ui_bytes`. Not covered by a rule: the 10 MiB output limit (`xml.too_large`), which depends on the total document size; the depth of a `RawXml` subtree; and a `props` key that differs from its `Prop.name` (only a hand-built subtree inserted with `InsertNode` can have one). The guard's safety net (§6.3) rejects them. Regression tests for the QA findings: `tests/core/test_qa_step09.py`.

R49–R53 and R75/R76 run only when `files=` is given (§5.2); R69–R74 and R77–R82 are pure and also run in the command guards (R73 is a warning and never blocks). R69–R80 are specified in `docs/specs/runtime.md` §9.

### 5.1 `BIND_TYPES` (data in `validate.py`, keyed by core class; an extension uses its fallback's row)
| Class | Allowed variable types |
|---|---|
| Entry, Spinbox | string, int, double |
| Combobox | string |
| Label | string, int, double (display only) |
| Scale, Progressbar | double, int |
| Checkbutton | bool, int |
| Radiobutton | string, int |
| all others (containers, Button, Text, Separator, Listbox, Treeview, Scrollbar, Canvas) | none → R42 |
- A `WidgetSpec.bind_types` field would change the plugin API. It is noted for Step 17, not added here.

### 5.2 Includes and image files (D4; amended by Step 10, decision U1)
- **Step 09** checks only what one file can tell: R45 (`src` empty), R46/R47 (path form), R48 (`component` identifier), the id rules and placement (an include is a child like a widget).
- **Step 10** adds the rules that need the disk (R49–R53 includes, R75/R76 image files) through an injected `files: FileAccess | None = None` (`validate()` and `validate_read()`). `core/files.py::DiskFiles` implements it (real path + `normcase` keys, one read per file, cached failures); the runtime reuses the same instance for the build. `files=None` (the default, **and always for the command guards**, so the 100 ms edit budget never meets I/O) skips them; every other rule is pure. Every rule still lives in `validate()` (ADR-006).
- **Include pass:** runs after the single-document pass with an explicit stack. It checks every include of every window of the root file, and of each included file only the target component's subtree. A newly read file is validated once (`files=None`, plus its image probes), and its findings follow the root's with their own `source`. Memoised per `(file, component)` (depth and size), so a fan-out bomb costs one visit per component. Same-file spelling: `src="#"` (decision U5).
- Rejected alternative (Step 09): a `base_path` argument with the validator loading files itself. The injected protocol keeps the validator free of I/O decisions and testable with an in-memory `FileAccess`.
- **Not checked** (later): unused variables or resources, and the `tb:` extra attributes (Step 17).

## 6. Command stack (`commands.py`)
### 6.1 Commands
```python
class Command(abc.ABC):
    label: str                                   # msgid (N_), e.g. N_("Set property")
    def text(self) -> str                        # _(label)
    def targets(self) -> tuple[object, ...]      # objects that must belong to the stack's document
    def is_noop(self) -> bool                    # evaluated before applying; default False
    @abc.abstractmethod
    def apply(self) -> None                      # calls primitives; captures undo state at apply time
    @abc.abstractmethod
    def revert(self) -> None                     # exact inverse of the last apply
    def merge(self, newer: Command) -> bool      # default False (§6.4)
```
- `apply`/`revert` are for the stack and for `Macro` only. Applying twice without a revert, or reverting while not applied, raises `RuntimeError` (a programming error).
- **Constructors check their direct arguments** and raise `TypeError` before anything is applied: the node, parent and owner classes, the `SetField` field and value class, a child `index` that is not an int (a bool too), and a `SetEvents` item that is not an `Event`. What is **inside** a value object or a subtree (a `Layout` with `columns=None`, a `GridCell` with a bad `extra_children`, a `Prop(name=None)`) is not checked there: the validator reports it (R62, R65–R67) and the command is rejected with an `Outcome`, like any other invalid value.
- **Model primitives are exception-safe:** `insert_child` and `move_child` check (and clamp) the index before they touch the list, so a failure never drops a node (QA B1).
- **Bars are attached as copies (QA Step 09 M2, orchestrator decision: option b).** A `Menubar`/`Statusbar` has no parent pointer, so the stack cannot tell whether a bar still belongs to another window or document. `SetField(window, "menubar"|"statusbar", bar)` therefore makes a deep copy of `bar` when it is constructed (`SetField.given` is the caller's object, `SetField.value` the copy), and `InsertNode(document, window)` copies the window's bars and attaches the copies on apply (the window's original bars come back on revert). Menus, actions and separators are rebuilt with fresh parent pointers; props, extra attributes and preserved children get fresh containers, and the immutable values inside are shared. The command keeps its copy, so undo/redo restore the very same object. The caller's object is never aliased, so edits cannot leak between documents. The ids inside the copy go through the ordinary guard: a bar copied from another window of the same document is rejected by R01. `SetField` with the bar a window already has is a no-op.
- `explain(errors)` (default: unchanged) rewords the reasons of a rejection (§6.3).

| Command | Primitive used | Undo | No-op when |
|---|---|---|---|
| `InsertNode(parent, node, index=None)` (`None` = append; otherwise an int, clamped like `list.insert`). Parents: Document (Window), Window/Widget (Widget, Include), Menubar (Menu), Menu (Menu, Action, MenuSeparator). | `parent.insert_child` | `parent.remove_child` | never |
| `RemoveNode(node)` (node with a `parent` field) | `node.parent.remove_child` (index kept) | `insert_child(index)` | never |
| `MoveNode(node, new_parent, index)` (`index`: any int, clamped like `list.insert`, so `10**30` appends) | same parent: `move_child`; otherwise `remove_child` + `insert_child` (put back on any failure) | inverse, back to the old parent and index | same parent and same final index |
| `SetProp(owner, prop)` (Window, Widget, Menu, Action, Statusbar) | `owner.set_prop` → previous | `set_prop(previous)`, or `remove_prop` | `owner.props.get(name) == prop` |
| `RemoveProp(owner, name)` | `remove_prop` | `set_prop(removed)` | prop not set |
| `SetField(target, name, value)` | `setattr` on a whitelisted field (below) | `setattr(old)` | `old is value or old == value` |
| `SetEvents(widget, events: Sequence[Event])` (every item must be an `Event`) | `widget.events = list(events)` | restores the previous list object | equal lists |
| `SetVariable(document, variable)` / `RemoveVariable(document, id)` | dict set (a replace keeps the position; an add appends) / `del` | restores a shallow snapshot **in place** (`clear()` + `update()`), so the insertion order, which the writer emits, is exact | equal value / id absent |
| `SetResource(document, image)` / `RemoveResource(document, id)` | same as variables | same | same |
| `Macro(label, commands)` | applies its children in order | reverts them in reverse order | all children are no-ops |

- **`SetField` whitelist** (`EDITABLE_FIELDS`, with the expected Python type per field; a wrong type or field raises `TypeError`, a programming error):
  - Window: `id kind layout menubar statusbar min_width min_height modal buttons`;
  - Widget: `id class_name bind fallback plugin placement layout`;
  - Include: `id src component placement`;
  - Menu: `id`; Action: `id handler shortcut`; Statusbar: `id`;
  - Meta: `generator source_locale i18n_domain theme`.
  - Not editable: `parent`, `_children`, `props`, `events`, `extra_*`, `Document.schema_version`/`namespaces`. Menubar and Statusbar are set or removed through `SetField(window, "menubar"|"statusbar", …)`.
- **Helpers** (each returns a `Macro`, because the intermediate states are invalid):
  - `reparent(node, new_parent, index, placement)` = `MoveNode` + `SetField(node, "placement", placement)`;
  - `change_layout(container, layout: Layout, placements: Mapping[node, Placement])` = `SetField(container, "layout", layout)` + one `SetField(child, "placement", …)` per entry.
    - `layout=None`, or a container that is not a window or a `children="layout"` widget → `TypeError`/`ValueError` (a programming error). It replaces a layout and never removes one (D6).
    - Every current child must have an entry; a missing one → `ValueError`.
- **`DEFAULT_LAYOUT: Final = Layout(type="grid")`** (exported): the layout the designer palette (Step 13) and the demo give every new window or layout container.
- **D6 consequences** (no layout is ever invented by a command; the guard enforces R13):
  - `InsertNode` of a Window or of a `children="layout"` widget whose `layout is None` → rejected (R13), with the reason "'{id}' has no layout…". The caller builds the node with `DEFAULT_LAYOUT` (or another layout) first. A page container inserted **with** a layout → rejected (R12).
  - `SetField(container, "layout", None)` on a window or layout container → rejected (R13). Removing a layout is only allowed where it is itself an error: a page container (R12) or a `children="none"` widget (R11).
  - `SetField(widget, "class_name", …)` that turns a non-container into a layout container must come in a `Macro` together with `SetField(widget, "layout", …)`.
  - Read files with layout-less containers keep R13 as a pre-existing error and stay editable (§6.3).
- **Atomic macros:** if child *k* raises `ModelError`, children *k−1…0* are reverted and the macro is rejected. Any other exception is a bug: the macro reverts best-effort and then re-raises.

### 6.2 `CommandStack`
```python
class CommandStack:
    def __init__(self, document: Document, registry: WidgetLookup, *, source: str = "<memory>",
                 limit: int = 1000) -> None
    document -> Document; read_only -> bool; limit -> int            # properties
    def execute(self, command: Command) -> Outcome
    def check(self, command: Command) -> Outcome      # dry run: apply → guard → always revert; never pushes
    def undo(self) -> bool;  def redo(self) -> bool   # False when there is nothing to do
    can_undo -> bool; can_redo -> bool; undo_text -> str | None; redo_text -> str | None  # translated on read
    is_dirty -> bool
    def mark_saved(self) -> None;  def break_merge(self) -> None;  def clear(self) -> None
    def report(self) -> ValidationReport             # full validation of the current state (cached)
    def subscribe(self, callback: Callable[[StackEvent], None]) -> Callable[[], None]  # returns unsubscribe

@dataclass(frozen=True, slots=True)
class Outcome:
    accepted: bool; changed: bool; merged: bool = False
    findings: tuple[Finding, ...] = ()   # rejected: the new errors (the reasons); accepted: new warnings
    message -> str                        # first finding's message, "" if none
    __bool__ -> accepted

@dataclass(frozen=True, slots=True)
class StackEvent:
    kind: Literal["execute", "merge", "undo", "redo", "saved", "clear"]
    command: Command | None; dirty: bool
```
**`execute(command)`:**
1. **Read-only** → rejected with `command.read_only` (§6.6).
2. **Foreign target:** every `targets()` object must belong to `document` (iterative climb to the root; Menubar/Statusbar/Meta are found through their window or the document). Otherwise it is rejected with `command.foreign_node`: "This element does not belong to the open document."
3. `is_noop()` → `Outcome(accepted=True, changed=False)`. Nothing is pushed, there is no event, and the merge state does not change.
4. `apply()`. A `ModelError` (`model.cycle`, `model.already_parented`, `model.bad_child`, `model.not_a_child`) → the partial state is reverted (Macro) and the command is rejected with a `Finding` built from the error (`code`, `msgid` and `params` copied, severity error).
5. **Guard** (§6.3). New errors → `revert()`, rejected.
6. Merge into the top (§6.4) or push. Truncate the redo tail; enforce `limit` (§6.5); notify; `Outcome(accepted=True, changed=True, merged=…)`.

- **Order of the checks:** read-only → foreign target → no-op → apply → guard (§6.3) → safety net (§6.3).
- **Rejection = return value, not an exception.** This is the decision. The designer shows `outcome.message` in the status bar or on the drop target, and `check()` gives drag-and-drop hover feedback with the same code path. Exceptions are reserved for programming errors (`TypeError`, `RuntimeError`, non-model exceptions from a command).
- **Invariant (I1):** a rejected **or failing** command leaves the document (`dump_ui` and `structure()` equal) and the stack (history, indices, saved mark, merge state) untouched, and it emits no event.
- **`limit`** must be an int (not a bool) of at least 1; anything else (`0`, `1.5`, `True`, `nan`) raises `ValueError`.
- **`undo`/`redo`** run no guard: they restore states that were already accepted, or that already existed when the document was loaded.
- **Re-entrancy:** calling `execute`/`undo`/`redo`/`clear` from a listener raises `RuntimeError`.
- **Listeners** are held strongly, in subscription order. An exception in a listener is logged (`logging.getLogger(__name__).exception`) and swallowed. Events are fired after the state change.

### 6.3 Guards (apply → validate → serialise → keep or roll back)
- **No cached "before" (QA Step 09):** the guard validates the current state before every `apply()`. A cache cannot see an edit made behind the stack's back (a plain attribute assignment), and a stale "before" lets new errors through or blocks clean edits; no cheap revision counter can see a plain `setattr` either. `report()` is not cached for the same reason: it returns a fresh, capped report on each call.
- After `apply()` the guard runs the full `validate(document, registry, source=source, limit=None)` (`None` = unbounded; no positions). The cap applies only to `report()` display and `uic`, so a new error is never hidden behind 1000 existing ones.
- **Guard keys:** errors are compared as multisets of keys. `validate.truncated` never counts.
  - **Order-independent** keys for the symmetric rules, so reordering an already-broken document is not blocked:
    - R01 → `(code, id value)`;
    - R05 → `(code,)`;
    - R16 → `(code, frozenset({node, other}))`.
  - Every other rule → `(code, anchor identity, part)`.
- Any key whose count increased is a **new error**. The command is then rejected with the findings carrying those keys, in validation order.
- **Safety net (I2):** when the guard finds no new error, the stack serialises the document with `dump_ui`. If the writer refuses it (any exception), the command is reverted and rejected with `command.unsaveable`: "This change would make the document impossible to save, so it was not applied: {detail}" (`{detail}` is the writer's reason, translated on read). It covers what has no rule (§5: the 10 MiB limit, `RawXml` depth, a props key mismatch). **Only new problems block:** if the document could not be saved before the command either (only a hand-built document can be in that state), the stack re-applies the command and accepts it, so such a document stays editable and can be repaired, like one with pre-existing errors. `check()` runs the safety net too.
- **Failure policy (I3), decided:** a malformed command either raises `TypeError` from its constructor (direct arguments, §6.1) or is rejected with a translated `Outcome` (everything the validator or the safety net can judge). Any other exception that escapes `apply()`, the validator or the writer is a programming error: the stack reverts the command first (for any `BaseException`, `KeyboardInterrupt` included), then lets the exception through. The document and the stack are byte-identical to before, and the next command works. A `ModelError` from `apply()` stays a rejection (§6.2 step 4). The stack never reverts a command it did not apply in this call: re-executing a command that is still applied in the history raises `RuntimeError` and changes nothing.
- **Reasons in the terms of the command:** `explain()` rewords R41 caused by `RemoveVariable` as `command.variable_in_use` ("The variable '{id}' is still used by '{user}'; unbind it first.") and R35 caused by `RemoveResource` as `command.resource_in_use` ("The image resource '{id}' is still used by '{user}'; remove that use first."), one finding per element and anchored like the validator finding. The validator stays the only judge.
- Warnings never block. New warnings are returned in `Outcome.findings` of an accepted command.
- **Consequences, by design:**
  - A document read with existing errors stays editable: edits that fix errors, or leave them alone, are accepted. Only edits that add errors are blocked.
  - Deleting a variable or resource that is still referenced is blocked (R41/R35 become new errors). The designer has to unbind first; a "remove and unbind" macro belongs to Step 14.
  - Moving a child between a grid and a pack container needs `reparent(…, placement)`. A bare `MoveNode` is rejected (R14/R15).
  - Adding a Frame (or a window) needs its layout in the same command: the node passed to `InsertNode` already carries `layout` (`DEFAULT_LAYOUT`). Otherwise R13 rejects it (D6, §6.1).
- **Cost:** two full validations and one `dump_ui` per command. Measured on the 2,000-widget budget document (Windows 11, Python 3.12): validation ≈ 15 ms, `dump_ui` ≈ 37 ms, `execute(SetProp)` median ≈ 70–80 ms (≈ 14 ms before, with one cached validation and no safety net). Budget gate (§10): a 2,000-widget document executes a `SetProp` in under 100 ms. Scoped or incremental validation is a later optimisation (Step 19) and must produce findings identical to the full pass (property test).

### 6.4 Merge of consecutive edits
`newer` merges into the top command `top` iff **all** of these hold:
- `type(newer) is type(top)` and the type is `SetProp` (same owner identity and same `prop.name`) or `SetField` (same target identity and same field);
- `top` was pushed by the immediately preceding accepted change (the merge flag is open);
- the redo tail is empty;
- the saved mark is not at the top (`saved_index != index`).

**What breaks a merge** (closes the flag): any other accepted command, `undo`, `redo`, `mark_saved`, `clear`, `break_merge()`.
**What does not break it:** a rejected command, a no-op, `check()`.

- There is **no time window** in the core (deterministic and testable). The designer calls `break_merge()` when an editor commits (Enter, focus-out) or the selection changes.
- The merged command keeps `top`'s undo state (the oldest value) and takes `newer`'s new value. A merge that ends at the original value stays on the stack as a no-op step (documented; it keeps the dirty logic simple).
- The absorbed `newer` is left **not applied**, so it can be executed or checked again later (it used to raise `RuntimeError`).
- `Macro` never merges.

### 6.5 Clean/dirty and limit
- `index` = number of applied commands. `saved_index: int | None`, initially `0` (a freshly opened or created document is clean). `is_dirty = saved_index != index`.
- `mark_saved()` sets `saved_index = index`, closes the merge flag and emits `saved`. The caller calls it **after** `write_ui` succeeds.
- Undoing back to the save point gives clean. Undoing past it and then executing a new command truncates the redo tail that contained the save point: `saved_index = None`, and the document stays dirty until the next `mark_saved()`.
- **Limit** (default 1000, minimum 1): when the history exceeds it, the oldest command is dropped and `index` and `saved_index` shift down by one. A `saved_index` that falls below 0 becomes `None` (permanently dirty).
- `clear()` drops the history. `saved_index = 0` if the document was clean, else `None`.

### 6.6 Read-only documents (D5, user 2026-10-05: edits blocked)
- `read_only` is True when `parse_version(document.schema_version)` is newer than `CURRENT_SCHEMA_VERSION` (the same test the writer uses).
- **Decided:** edits are blocked. Every `execute`/`check` is rejected with `command.read_only`: "This document was opened read-only (schema version {version}); it cannot be changed." The writer refuses that document forever and "save a copy" is out of scope, so any edit would be lost work.
- Rejected alternative: allow editing without saving. It invites lost work.

## 7. Empty `display_name` in plugin specs
- **File:** `src/pyguibud/core/registry.py`, `Registry._register`, after the reserved-name check and before the duplicate check.
- **Check:** `not isinstance(spec.display_name, str) or not spec.display_name.strip()` → diagnostic `registry.bad_display_name` (severity error), and the spec is not registered: "The widget '{name}' from '{distribution}' has no display name and was ignored." It applies to every spec; the built-ins pass.
- **Not** in `WidgetSpec.__post_init__`: raising there would fail the whole entry point (`registry.load_failed`), its valid siblings included, and hide the specific reason.

## 8. `pyguibud-uic --check`
- Per file: `read_ui` → on `XmlIoError`, the Step 08 behaviour is unchanged.
- Otherwise `report = validate_read(result, default_registry(), files=DiskFiles(path, result))` (Step 10, decision U3: include and image errors exit 1, consistent with `load_ui`). Output on stderr:
  1. the reader warnings, then
  2. the validator findings in report order,

  each as `{location}: {severity}: {message}`. `{severity}` is the fixed English token `error` or `warning`. If a finding has no line and a non-empty `path`, the line is `{source}: {severity}: {path}: {message}`.
- Stdout `"{path}: no errors found"` only when the file was read and `report.ok`.
- **Exit codes:** 0 if every file was read and has no error findings (warnings and read-only files included); 1 if any file failed to read **or** has a validator error; 2 for a usage error. No new flag (there is no existing warnings-as-errors flag).
- **Trust note** (in `--help` epilog and docs): `default_registry()` loads installed `pyguibud.widgets` plugins, which runs their code (ADR-004 trust boundary). Plugin load diagnostics are not printed; a missing plugin surfaces as R28.
- `examples/hello.ui` must give exit 0 with no findings.
- **Exit-code change:** BACKEND audits the existing `tests/test_uic.py` cases and the `tests/core/data/xml_io` fixtures that expect exit 0. Any of them that now trip validator errors (unknown classes, missing layouts, duplicate ids…) is updated deliberately (the fixture is fixed, or the expectation changes, with a comment), never silently.

## 9. `examples/validator_demo.py` (UAT)
- Run it with `uv run python examples/validator_demo.py [--lang CODE]`. `--lang` reuses `pyguibud.cli._language_arg` + `set_language`. Output is en-GB by default, plain text on stdout, deterministic, and the script exits 0. It is importable, with `main(argv: list[str] | None = None) -> int`.
- It loads `hello.ui` next to the script (`Path(__file__).with_name("hello.ui")`), creates `CommandStack(document, default_registry())`, and prints numbered sections. Each attempt prints `OK` or `BLOCKED: <translated reason>`:
  1. **Accepted:** rename `lbl_name` → `lbl_user`; set `btn_greet` text; `dirty: True`.
  2. **Blocked, with reasons:**
     - rename to `class` (R04), to `btn_greet` (R01) and to `_x` (R03);
     - insert a Label into `lbl_about` (R10);
     - insert a widget with a `<pack>` placement into the grid frame (R15);
     - a cell overlapping `lbl_user` at row 0, column 0 (R16);
     - set `width="-5"` (R09) and `state="maybe"` (R31);
     - event `key:` (R36) and handler `1abc` (R39);
     - insert a Checkbutton bound to the string variable `user_name` (R43);
     - a layout on `nbk_main` (R12);
     - a second main window that carries `DEFAULT_LAYOUT`, so that R05 is the only reason;
     - an empty Frame without a layout (R13);
     - remove the bound variable `user_name` (R41).
     It then shows that the document is unchanged (`dump_ui` equal before and after the blocked block).
  3. **Merge:** three consecutive text edits of `lbl_user` → one undo step (prints the undo depth and `undo_text`).
  4. **Undo/redo and dirty:** `mark_saved` → edit → `dirty: True` → undo → `dirty: False` → redo → `dirty: True`; undo past the save point plus a new edit → dirty even after undoing to the old depth.
  5. **Validation of a broken document:** `read_ui_string` of an embedded document with ≥ 6 different errors and 1 warning. It prints `validate_read` findings with `line:column`, severity and message, then `ok: False`.
  6. **Read-only:** the same document with `schema_version="1.1"` → every edit is BLOCKED with `command.read_only`.

## 10. Test plan (TESTING agent) and gates
- **Layout:** `tests/core/test_diagnostics.py`, `test_validate.py` (one test per rule: positive + negative, asserting `code`, `severity`, `path` and, for file input, `line`/`column`), `test_validate_golden.py`, `test_commands.py`, `test_commands_props.py` (hypothesis), `tests/test_uic.py` (extended), `tests/test_validator_demo.py`, `tests/core/test_registry.py` (+ `bad_display_name`). Inputs go in `tests/core/data/validate/<case>.ui`; golden outputs are `<case>.findings.txt` (one `line:col: severity: code: path` per finding, untranslated and stable).
- **Validator:**
  - every R-code, including R13 on an empty Frame and an empty window, no R13 on an empty Notebook, the D6 command cases of §6.1, the R09 variants, every R31 type and the R28 variant without a plugin;
  - `examples/*.ui` → no findings;
  - deterministic order (two runs, and a model built in a different construction order but with identical structure, give equal findings);
  - the cap (`limit=5` → 5 findings, the last one `truncated`, `ok` exact);
  - fallback mode and unknown classes (no crash, children still checked);
  - a hand-built model with wrong Python types does not raise;
  - `validate()` does not mutate (`dump_ui` before == after);
  - registry passed as a fake `WidgetLookup` (dict-backed) as well as a real `Registry`.
- **Scale and abuse:**
  - a 1,000-level nested widget chain (built in code), validated without `RecursionError`, gives R23 once;
  - 20,000 siblings in one grid with collisions finish in < 2 s (sweep, not O(n²));
  - an id of 10,000 characters → R03.
- **Positions:** each recorded part maps to the right line (hello.ui plus a dedicated file); a migrated element has no entry; `XmlWarning is Finding`; the reader warnings' equality and `str()` are unchanged (the existing Step 08 tests stay green untouched).
- **Commands (unit):**
  - each command: apply, undo, redo and its no-op case;
  - every `ModelError` path → rejected, document untouched;
  - foreign node;
  - `SetField` with a non-whitelisted field or a wrong type → `TypeError`;
  - macro atomicity (failure at the 3rd child → the first 2 reverted);
  - `reparent` grid → pack accepted, bare `MoveNode` rejected;
  - dict order restored for variables and resources;
  - merge: every breaker of §6.4 and every non-breaker;
  - dirty: all transitions of §6.5, including the limit trimming the saved point;
  - read-only;
  - `check()` leaves everything untouched;
  - listener order, a listener exception is swallowed, re-entrancy raises;
  - `undo_text` follows `set_language("en_XA")`.
- **Property tests (hypothesis):** strategy = random sequences (≤ 40) of commands over `hello.ui` and a generated small document (ids drawn from a pool that includes duplicates, keywords and bad names; placements of every kind; legal XML strings only). Invariants:
  - a rejected command leaves `dump_ui(doc)` and `structure(doc)` equal to before, with the stack indices unchanged;
  - after the sequence, undo-all → `dump_ui == original` **and** `structure == original` (parent pointers intact);
  - redo-all → `dump_ui == final`;
  - every accepted state that started from a valid document is still error-free (`report().ok`);
  - one-way dirty check: `not is_dirty ⇒ dump_ui(doc) == saved_bytes`;
  - **parent pointers** (`structure()` skips `parent`): after every step, an iterative walk requires `child.parent is node` for every child, and the root's windows have `parent is document`.
- **Guard keys:** a document with a pre-existing duplicate pair A, B → moving B above A is accepted; a capped document (> 1000 errors) still rejects a new error.
- **Guard budget:** a 2,000-widget document, median of 20 `execute(SetProp)` < 100 ms (marked `slow`, run in CI).
- **uic:**
  - hello.ui → 0;
  - a file with only validator errors → 1 with `path:line:col: error:`;
  - warnings only (R28, R30) → 0 plus "no errors found";
  - read-only + validator warning → 0;
  - mixed files → 1;
  - `--lang en_XA` translates messages but not the tokens.
- **Demo:** `main([])` returns 0, stdout equals the golden `tests/data/validator_demo.en_GB.txt`, and `main(["--lang", "en_XA"])` differs from it but still has every section header number.
- **i18n:**
  - every msgid of §5/§6/§7 is a literal inside `N_()`/`_()` (a test greps the `.pot` after extraction for each `validate.*` and `command.*` msgid);
  - no f-string or concatenation builds a message;
  - `Finding.message` is translated on read (switch the language after `validate()`).
- **Isolation:** the subprocess test also imports `pyguibud.core.validate` and `pyguibud.core.commands` with no toolkit loaded.

**Gates (each run, with its result, in the report):**
- `uv sync`
- `uv run pytest tests/core --cov=pyguibud.core --cov-report=term-missing --cov-fail-under=90`
- `uv run pytest tests/test_uic.py tests/test_validator_demo.py`
- `uv run mypy src/pyguibud/core src/pyguibud/uic.py`
- `uv run ruff check src tests examples`
- `uv run pyguibud-uic --check examples/hello.ui` → exit 0, no findings
- `uv run python examples/validator_demo.py` → exit 0
- `.pot` re-extracted with `-k N_`, then `pybabel update` + `compile` (docs/i18n/README.md), with no fuzzy entries for `en_GB`
- `uv run python tools/scorer.py`

## 11. Documentation updates (done 2026-10-05) and fixture impact
- **Docs updated:**
  - ADR-006 → Accepted;
  - FEATURES §4: id grammar (D3), layout always required (D6), include checks in Step 10 (D4);
  - the `ui-schema-rules` skill;
  - DEVELOPMENT_PLAN §5 notes;
  - `docs/specs/xml-io.md` §12.
- **Fixture impact** (expected validator result; computed by hand, BACKEND confirms):
  - `examples/hello.ui` → no findings.
  - The `test_uic.py` inputs are all derived from `hello.ui`: the warning variant and the `1.5` read-only variant add no validator findings, and the corruptions fail at read time. **No uic test change is expected.**
  - `tests/core/data/xml_io/*.in.ui` are byte-level I/O fixtures that no Step 08 test validates. **Do not edit them** (their goldens would change). If a Step 09 test validates them, use these expectations:

| Fixture | Errors | Warnings |
|---|---|---|
| `minimal.in.ui` | none | R06 |
| `full.in.ui` | R13 (`dlg`, `cmp`), R34 (title `ref`), R42 (`b1` Button bind), R14 (`nb` has no cell) | R08 (`modal`/`buttons` on main), R20, R21 ×2 (page `weight` under Notebook) |
| `reordered.in.ui` | R13 (`dlg`) | R30 ×2 (`anchor`, `geometry`) |
| `special_chars.in.ui` | R13 (`main`) | R30 ×8 (`a`…`h` on Text) |
| `foreign.in.ui` | R13 (`main`), R37 (Label `change`) | R28 (`tb:Meter`) |

- Validator test inputs live in `tests/core/data/validate/` (§10), never in `xml_io/`.

## 12. Out of scope
- **Done in Step 10:** include resolution (R49–R53), image files (R74–R76), the `buttons` grammar (R70), the Action `shortcut` grammar (R71, R73) and the attribute-vs-property overlap (the attribute wins; the Action spec no longer lists a `shortcut` property, so a stray `<prop name="shortcut">` gets the R30 warning).
- **Done in Step 10 (R69):** reserved ids that clash with generated code or the runtime scope (`vars`, `setup_ui`, …).
- **Step 13/14:** designer wiring (status-bar reasons, DnD hover via `check()`, `break_merge()` on commit), "remove and unbind" and "rename variable" macros, copy/paste, autosave.
- **Step 17:** `tb:` attribute validation (`tb:bootstyle` values), `SetExtraAttr`, `WidgetSpec.bind_types`, the plugin diagnostics panel.
- **Step 19:** scoped or incremental validation, the depth of `RawXml` subtrees (the writer and the guard's safety net already refuse them), a `--strict`/warnings-as-errors flag.
- **Closed (QA Step 09 M2):** shared menu bars and status bars. Option (b) was chosen, deep copy on attach (§6.1), with no model change. The alternatives were an owner pointer on the bars (a model change) and a registry of live stacks (global state).
- Unused variables or resources, and style lints.

## 13. Decisions (user, 2026-10-05)
| # | Topic | Decision |
|---|---|---|
| D1 | Finding type | `Finding` in `core/diagnostics.py`; `XmlWarning = Finding` alias. |
| D2 | Positions | `ReadResult.positions: SourceMap`, keyed by `(node identity, part)`; no model change. |
| D3 | Id grammar | ASCII `^[A-Za-z][A-Za-z0-9_]{0,63}$` and not a Python keyword, also for handlers, bind and component. It avoids NFKC look-alike collisions and is Tk/Qt-name safe. |
| D4 | Includes | Step 09 checks syntax and path form only. **Amended in Step 10 (user, 2026-10-06, U1/U3/U5):** existence, component kind, cycles and limits are R49–R53, run through an injected `files=` (never in the command guards); same-file spelling is `src="#"`; `pyguibud-uic --check` runs them. |
| D5 | Read-only documents | All edits blocked (`command.read_only`). |
| D6 | Container without a layout | **Always an error**, even when empty (FEATURES §4; the user chose the alternative to the "warning if empty" proposal). Page containers must have no layout. Consequences: §6.1. |
