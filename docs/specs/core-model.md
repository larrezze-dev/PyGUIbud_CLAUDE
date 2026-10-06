# Spec — Step 07: core widget model and entry-point registry

- **Status:** Ready for implementation · **Date:** 2026-10-05 · **Owner:** BACKEND · **Sources:** ADR-001..005, FEATURES.md §3–4
- Implement verbatim. Anything not listed here is out of scope (§10).

## 1. Modules and entry points
| File | Contents |
|---|---|
| `src/pyguibud/core/__init__.py` | Re-exports the public names of `errors`, `model`, `registry` (explicit `__all__`). Must **not** import `widgets` or trigger registry loading. |
| `core/errors.py` | `PyGUIbudError`, `ModelError`, `RegistryError` (§8). |
| `core/model.py` | Namespace constants, name helpers, value objects, tree nodes, `WidgetSpec`, `PropertyDef` (§3–6). |
| `core/registry.py` | `Registry`, `Diagnostic`, `Resolved`, default-registry accessors (§9). |
| `core/widgets.py` | `core_widgets() -> tuple[WidgetSpec, ...]`: the 24 built-in specs (§6), pure data. |

`pyproject.toml` (dogfooding, ADR-004), added verbatim:
```toml
[project.entry-points."pyguibud.widgets"]
core = "pyguibud.core.widgets:core_widgets"
```
- **No `pyguibud.backends` entry yet** (nothing to point at until Step 10). The registry supports the group; an empty result is normal.
- **`tb:` specs are deferred to Step 17**: DEVELOPMENT_PLAN row 17 owns them, and they belong next to the ttkbootstrap factories. Step 07 tests fallback resolution with fake plugin specs.
- After editing `pyproject.toml`, run `uv sync` so the editable install's metadata exposes the entry point. Otherwise the default-registry tests fail.

## 2. Dependency rules
- **Import graph (no cycles):** `errors → i18n`; `model → errors, i18n`; `widgets → model, i18n`; `registry → model, errors, i18n` (plus `widgets`, imported **lazily inside** the core-fallback path only). `WIDGET_API_VERSION` lives in `model.py` so `widgets` can use it; `registry` re-exports it.
- **Stdlib only.** Never import `tkinter`, `ttkbootstrap`, `PySide6` or `xml.etree` in `core` (XML arrives in Step 08). `pyguibud/__init__.py` stays toolkit-free, as it is today.
- `from __future__ import annotations` everywhere; mypy `--strict` clean.
- **Open question (Step 20, not solved here):** `pyguibud-runtime` must not depend on `pyguibud`, yet `core` imports `pyguibud.i18n`. Decide later whether the runtime vendors a tiny i18n shim or the model moves into the runtime.

## 3. Model: value objects and tree nodes (`model.py`)
**Value objects:** `@dataclass(frozen=True, slots=True, kw_only=True)`, no inheritance between them.
- Sequence fields are `tuple[...]`.
- Mapping fields use `field(default_factory=dict, hash=False)` and are wrapped in `types.MappingProxyType` in `__post_init__` (via `object.__setattr__`).
- Every value object has `extra_attrs: Mapping[str, str]` (§4).

| Class | Fields (defaults) |
|---|---|
| `RawXml` | `xml: str`: one complete serialised element, its namespace declarations included (§4) |
| `Prop` | `name: str`, `value: str = ""` (raw text, never coerced), `ref: str \| None = None` (resource id), `translatable: bool = False`, `context: str \| None = None`, `comment: str \| None = None` |
| `Event` | `name: str`, `handler: str` |
| `GridCell` | `row: int`, `column: int`, `rowspan: int = 1`, `columnspan: int = 1`, `sticky: str = ""`, `padx: int = 0`, `pady: int = 0` |
| `PackPlacement` | `fill: Literal["none","x","y","both"] = "none"`, `expand: bool = False`, `padx: int = 0`, `pady: int = 0` |
| `PagePlacement` | `text: Prop \| None = None`, `image: str \| None = None` (resource id), `weight: int = 0`. Used for Notebook tabs and PanedWindow panes (§6). |
| `GridLine` | `index: int`, `weight: int = 0`, `minsize: int = 0` |
| `Layout` | `type: Literal["grid","pack"]`, `orient: Literal["vertical","horizontal"] = "vertical"` (pack only), `padding: int = 0`, `gap: int = 0`, `columns: tuple[GridLine, ...] = ()`, `rows: tuple[GridLine, ...] = ()`, `extra_children: tuple[RawXml, ...] = ()` |
| `Variable` | `id: str`, `type: Literal["string","int","double","bool"]` (ADR-003; **not** the property types), `default: str = ""` |
| `ImageResource` | `id: str`, `src: str` (relative path, stored verbatim) |

- `Placement = GridCell | PackPlacement | PagePlacement`.
- **Amended by `docs/specs/xml-io.md` §2 (Step 08, pending approval):** the leaf value objects gain `extra_children`, and `Document` gains `resources_extra`/`variables_extra` (`ContainerExtras`).
- Range and identifier checks belong to the validator (Step 09). Value objects do no checking, except `PropertyDef` (§6).

**Tree nodes:** `@dataclass(eq=False, slots=True, kw_only=True)`. Every `dict`/`list` field (here and in §6/§9) uses `field(default_factory=...)`; `Document.meta` uses `default_factory=Meta`.
- Equality is by identity, so `remove`/`index` hit the right node of two lookalikes.
- `parent` is `field(default=None, init=False, repr=False, compare=False)`, a plain strong reference (`weakref_slot` would need Python 3.11).
- Children live in `_children: list` (`init=False, repr=False`) and are exposed read-only as `children -> tuple`.
- Every node has `extra_attrs: dict[str, str]` and `extra_children: list[RawXml]`.

| Node | Fields |
|---|---|
| `Meta` | `generator: str = ""`, `source_locale: str = "en_GB"`, `i18n_domain: str = ""`, `theme: str = ""` |
| `Document` | `schema_version: str = "1.0"`, `namespaces: dict[str, str]` (prefix → URI as declared in the file; seeded with `{"": NS_UI, "tb": NS_TB}`), `meta: Meta`, `resources: dict[str, ImageResource]`, `variables: dict[str, Variable]` (both keyed by id, insertion-ordered), windows (children) |
| `Window` | `id: str`, `kind: Literal["main","dialog","component"] = "main"`, `props: dict[str, Prop]`, `layout: Layout \| None = None`, `menubar: Menubar \| None = None`, `statusbar: Statusbar \| None = None`, `min_width: int \| None = None`, `min_height: int \| None = None`, `modal: bool = False`, `buttons: str \| None = None`; children: `Widget \| Include` |
| `Widget` | `class_name: str`, `id: str`, `props: dict[str, Prop]`, `events: list[Event]`, `bind: str \| None = None`, `fallback: str \| None = None`, `plugin: str \| None = None`, `placement: Placement \| None = None`, `layout: Layout \| None = None`; children: `Widget \| Include` |
| `Include` | `id: str`, `src: str`, `component: str`, `placement: Placement \| None = None` (leaf) |
| `Menubar` | children: `Menu` |
| `Menu` | `id: str`, `props: dict[str, Prop]`; children: `Menu \| Action \| MenuSeparator` |
| `Action` | `id: str`, `props: dict[str, Prop]`, `handler: str \| None = None`, `shortcut: str \| None = None` (leaf) |
| `MenuSeparator` | no fields beyond `extra_*` (leaf) |
| `Statusbar` | `id: str`, `props: dict[str, Prop]` (leaf) |

**Tree helpers** (on every node that has children; mutation primitives for Step 09, with no validation of container-ness or ids):
- `insert_child(index: int, node)` and `append_child(node)`. Both set `node.parent`.
  - `ModelError("model.already_parented")` if `node.parent is not None`.
  - `ModelError("model.cycle")` if `node` is `self` or one of its ancestors.
  - `ModelError("model.bad_child")` if the child type is not allowed by the table above.
- `remove_child(node) -> int` returns the former index and clears `parent`; `ModelError("model.not_a_child")`.
- `index_of(node) -> int`. `move_child(node, new_index) -> int` returns the old index.
- `walk() -> Iterator[node]`: pre-order and depth-first over `self` and its descendants (Window also yields its menubar, its menus/actions/separators and its statusbar first). `ancestors() -> Iterator[node]`.
- `Widget.window -> Window | None`. `Window.document -> Document | None`.
- `set_prop(prop) -> Prop | None` returns the previous value. `remove_prop(name) -> Prop | None`.
- **`Document` helpers:**
  - `add_window` / `insert_window` / `remove_window -> int`.
  - `main_window -> Window | None`: the first `kind == "main"`.
  - `walk()`.
  - `find(id) -> node | None`: the first match over windows, widgets, includes, menus, actions and the statusbar.
  - `iter_ids() -> Iterator[tuple[str, object]]`: every id-bearing node, plus resources and variables. It is **not** de-duplicated; the validator uses it.

## 4. Round-trip storage (ADR-001/002)
- **Constants:** `NS_UI = "urn:pyguibud:ui:1"`, `NS_TB = "urn:pyguibud:ext:ttkbootstrap:1"`, `KNOWN_NAMESPACES: Mapping[str, str] = {"tb": NS_TB}` (read-only).
- **`extra_attrs`** holds every XML attribute the model has no field for:
  - namespaced attributes in Clark notation (`"{urn:pyguibud:ext:ttkbootstrap:1}bootstyle"`);
  - unknown plain attributes under their local name.
- **Unknown child elements** are kept as `RawXml` strings, so the model never holds ElementTree types. Step 08 re-emits them **after** the known children of the same parent. Their original position is not kept, which ADR-002's deterministic output allows.
- `Document.namespaces` lets Step 08 write the original prefixes back instead of `ns0:`.

## 5. Class names
- **Core names** are plain (`Button`). **Extension names** are `prefix:Local` (`tb:Meter`, `acme:ColourPicker`).
- The prefix is an **opaque registry key**, not an XML QName. Step 08 never resolves it through `xmlns`.
- **Grammar:**
  - prefix `^[a-z][a-z0-9_-]*$`;
  - local `^[A-Z][A-Za-z0-9_]*$`;
  - at most one colon.
- **Helpers in `model.py`:**
  - `split_class_name(name) -> tuple[str | None, str]` (`ModelError("model.bad_class_name")`).
  - `qualify(prefix: str | None, local: str) -> str`.
  - `is_extension(name) -> bool`.
  - `CORE_CLASS_NAMES: frozenset[str]`: the 24 names in §6.
- **`Widget` fields:** `fallback` is a core class name, required on extension widgets (the validator enforces it). `plugin` is the distribution name, used for the actionable "pip install" message.

## 6. Core vocabulary, `PropertyDef`, `WidgetSpec` (`model.py`, data in `widgets.py`)
- `ABSTRACT_EVENTS = frozenset({"command","change","select","activate","focus_in","focus_out"})`.
- `is_valid_event(name) -> bool`: true for `ABSTRACT_EVENTS`, or `key:<Sequence>` with a non-empty sequence of printable characters and no whitespace.
- `key:` events are allowed on any spec that lists `focus_in`.

**`PropertyDef`** (frozen value object):
- **Fields:** `name: str`, `type: Literal["string","int","float","bool","enum","image","colour"]`, `default: str | None = None` (raw string), `translatable: bool = False`, `choices: tuple[str, ...] = ()`, `minimum: float | None = None`, `maximum: float | None = None`, `display_name: str | None = None` (msgid).
- `__post_init__` raises `ModelError("model.bad_property_def")` when:
  - an enum has no choices, or its non-None default is not among them;
  - a non-enum has choices;
  - `translatable` is set on a non-string property.
- `label() -> str` returns `_(display_name)`, or `name` if there is none.

**`WidgetSpec`** (frozen value object, `kw_only=True`; `api_version` has **no default** so plugins must declare it):
- **Fields:**
  - `name: str`, `display_name: str` (msgid), `category: str` (msgid), `api_version: int`;
  - `children: Literal["none","layout","pages","menu"] = "none"`;
  - `properties: tuple[PropertyDef, ...] = ()`, `events: tuple[str, ...] = ()`;
  - `fallback: str | None = None`, `icon: str | None = None` (`"package:relative/path"`, resolved by the designer later);
  - `factories: Mapping[str, Callable[..., object]] = field(default_factory=dict, compare=False, hash=False)` (keys: `ttkbootstrap`, `tkinter`, `pyside6`; `compare=False, hash=False`, read-only proxy; factories must import their toolkit lazily);
  - `plugin: str | None = None`.
- **Derived:** `container -> bool` is `children in ("layout", "pages")`. This keeps ADR-004's flag and cannot contradict `children`.
- **Methods:** `label() -> str` (`_(display_name)`), `category_label() -> str`, `property(name) -> PropertyDef | None`, `is_extension -> bool`.
- **i18n trap:** `display_name`, `category` and `PropertyDef.display_name` hold **msgids**, wrapped at definition time in `N_()`. They are translated only on read. Never call `_()` at import time.
- **New marker:** add `def N_(message: str) -> str: return message` to `pyguibud/i18n.py` (and its `__all__`).
- **Extraction:** the extract command in `docs/i18n/README.md` gains `-k N_`. `babel.cfg` (`[python: **.py]`) already covers `core/`.

**Built-in specs.** Category msgids: Containers, Controls, Display, Menus. Shared property definitions:
- `text` = string, translatable;
- `image` = image;
- `state` = enum normal|disabled (default normal); `state3` = enum normal|disabled|readonly;
- `width`/`height`/`length` = int, min 0, default None;
- `orient` = enum horizontal|vertical.

Abbreviation in the table: `focus` = `focus_in, focus_out`.

| Class | children | Properties | Events |
|---|---|---|---|
| Frame | layout | width, height | — |
| LabelFrame | layout | text, width, height | — |
| Notebook | pages | width, height | select |
| PanedWindow | pages | orient (vertical) | — |
| ScrolledFrame | layout | height, autohide bool "true" | — |
| Label | none | text, image, width | — |
| Button | none | text, image, state, width | command, focus |
| Entry | none | width, state3, show string | change, activate, focus |
| Text | none | width, height, state, wrap enum none\|char\|word ("word") | change, focus |
| Checkbutton | none | text, state | command, change, focus |
| Radiobutton | none | text, value string, state | command, change, focus |
| Combobox | none | width, state3 | change, select, focus |
| Spinbox | none | minimum float "0", maximum float "100", increment float "1", width, state3 | change, focus |
| Scale | none | minimum float "0", maximum float "100", orient (horizontal), length | change |
| Progressbar | none | maximum float "100", value float "0", mode enum determinate\|indeterminate, orient (horizontal), length | — |
| Separator | none | orient (horizontal) | — |
| Listbox | none | height (default "10"), selectmode enum browse\|single\|multiple\|extended | select, activate, focus |
| Treeview | none | height, show enum tree\|headings\|tree headings, selectmode enum browse\|extended\|none | select, activate, focus |
| Scrollbar | none | orient (vertical) | change |
| Canvas | none | width, height, background colour | focus |
| Menubar | menu | — | — |
| Menu | menu | text | — |
| Action | none | text, image, state (the shortcut is the node's `shortcut` attribute, validated by R71; a `shortcut` property was removed in Step 10) | command |
| Statusbar | none | text | — |

- Every spec here has `api_version=WIDGET_API_VERSION`, `fallback=None` and no factories.
- **Notebook and PanedWindow** children are placed with `PagePlacement`, not a `<layout>`. **Menus** are structural nodes (§3).
- **Combobox, Listbox and Treeview** item and column models are deliberately absent. They grow in Step 08 and later.

## 7. Page containers (approved — see ADR-005 Addendum A)
- **Schema conflict:** `children="pages"` and `PagePlacement` conflict with the wording of ADR-005 and FEATURES §4 ("a container has exactly one `<layout>`").
- **Recommendation:** amend the rule to "every `children="layout"` container has exactly one layout; `pages` containers have none, and their children carry `<page>`". The XML spelling is settled in Step 08.
- **Delivery:** add an ADR-005 addendum, or a new ADR, once the user approves.

## 8. Errors (`errors.py`)
**`PyGUIbudError(Exception)`:**
- **Constructor:** `__init__(self, code: str, message: str, /, **params: object)`. `code` is a dotted, lowercase machine code (`"registry.load_failed"`). `message` is a msgid that call sites pass as `N_("…{name}…")`. The attributes `code`, `msgid` and `params` are stored.
- **`.message`** (property, lazy): `_(msgid).format(**params)`. On `KeyError`, `IndexError` or `ValueError` (a broken translation) it falls back to `msgid.format(**params)`; if that also fails it returns the raw msgid. It never raises.
- **`__str__`** returns `.message`.
- **Subclasses:** `ModelError` and `RegistryError`, with no extra fields.
- **Rules:** no bare `except:`. The only broad catch is `except Exception` in the registry isolation points (§9).

## 9. Registry (`registry.py`)
**Constants and types:**
- `WIDGET_API_VERSION: Final = 1`, defined in `model.py` and re-exported here (provisional until 1.0; compatible means `==`).
- `WIDGETS_GROUP = "pyguibud.widgets"`, `BACKENDS_GROUP = "pyguibud.backends"`.
- `EntryPointLike` (Protocol): `name`, `value`, `group: str`, `dist: <has .name> | None`, `load() -> object`.
- `EntryPointSource = Callable[[str], Iterable[EntryPointLike]]`. The default is `lambda g: importlib.metadata.entry_points(group=g)`.
- `Diagnostic` (frozen): `group`, `entry_point`, `distribution` (`"unknown"` if `dist` is None), `code`, `msgid`, `params: Mapping[str, str]` (read-only Mapping rule of §3), `severity: Literal["error","warning"]`, `exception: str | None` (`repr(exc)`), `traceback: str | None` (formatted). Lazy `.message`, same rules as errors.
- `Resolved` (frozen): `spec: WidgetSpec`, `requested: str`, `is_fallback: bool`, `code: str | None` (`"registry.plugin_missing"` or `"registry.no_factory"`).
- `BackendInfo` (frozen): `name`, `value`, `distribution`.

**`Registry(entry_points: EntryPointSource | None = None)`.** The constructor does no I/O. Lookups call `load()` once, lazily. `load()` clears and rebuilds all state.

**Loading `pyguibud.widgets`:**
1. **Order:** the entry point whose `value` starts with `"pyguibud.core.widgets:"` loads first (the "built-in"). The rest follow, sorted by `(distribution, name)`.
2. **Shape:** `obj = ep.load()`, then checked in this order:
   - a `WidgetSpec` → `[obj]`;
   - callable → call it with no arguments and apply the same check to the result (one level only);
   - a non-`str` iterable → its items;
   - anything else → diagnostic `registry.bad_entry_point`.

   Items that are not a `WidgetSpec` get `registry.bad_spec`. Valid siblings are still registered.
3. **Isolation:** any `Exception` from `load()`, the call or iteration becomes an error diagnostic `registry.load_failed`. Loading continues; `load()` never raises.
4. **Per spec, rejected with a diagnostic** (not registered):
   - `api_version != WIDGET_API_VERSION` → `registry.incompatible_api` (warning);
   - invalid name → `registry.bad_name`;
   - an unqualified name from a non-built-in entry point → `registry.reserved_name` (core names cannot be overridden);
   - a duplicate name → `registry.duplicate` (warning; the first one wins).

   A non-built-in spec with `plugin=None` gets `dataclasses.replace(spec, plugin=<distribution>)`.
5. **After all loading, extension specs are checked again:**
   - `fallback` must be a registered core name → otherwise `registry.bad_fallback` (removed);
   - `container` must equal the fallback's → otherwise `registry.fallback_mismatch` (removed).
6. **Core safety net:** if any `CORE_CLASS_NAMES` is missing (missing metadata or a broken install), register the missing specs from `widgets.core_widgets()` directly, plus a warning `registry.core_fallback`.

**Loading `pyguibud.backends`:**
- Entries are only **listed** as `BackendInfo` and never `.load()`ed during `load()`, because that would import a toolkit.
- `load_backend(name) -> object` loads on demand, cached.
- Unknown names raise `RegistryError("registry.unknown_backend")`. A failing load records a diagnostic and raises `RegistryError("registry.backend_failed") from exc`. The object's contract is defined in Step 10.

**Lookup API:**
- `get(name) -> WidgetSpec | None`.
- `require(name) -> WidgetSpec` (`RegistryError("registry.unknown_class")`).
- `specs() -> tuple[WidgetSpec, ...]` in registration order.
- `is_container(name) -> bool` (via `require`).
- `diagnostics() -> tuple[Diagnostic, ...]`. `backends() -> tuple[BackendInfo, ...]`.
- `resolve(class_name, backend: str, fallback: str | None = None) -> Resolved`:
  - a core name → itself, `is_fallback=False`, because backends map all core classes (ADR-001);
  - a registered extension with a factory for `backend` → itself;
  - a registered extension without one → its spec's fallback (`registry.no_factory`);
  - an unregistered extension with `fallback` → that core spec (`registry.plugin_missing`);
  - otherwise → `RegistryError("registry.unknown_class")`.

  It never returns None.

**Default registry:** `default_registry() -> Registry` (lazy, cached in a module global; main thread only) and `reset_default_registry() -> None` for tests.

## 10. Out of scope
- XML parsing/serialising, schema versions and migrations (Step 08).
- The validator, command stack and undo/redo (Step 09).
- Backends, `load_ui` and factories (Step 10+).
- The designer palette and icons (Step 11+).
- `tb:` specs, the placeholder widget, the diagnostics panel and the sample plugin (Step 17).

## 11. Test plan (TESTING agent)
**Layout and model:**
- **Layout:** `tests/core/__init__.py`, plus `tests/__init__.py` so packages resolve as `tests.core.*` (no top-level `core` package, no basename clashes).
- **Value objects:** frozen (`FrozenInstanceError`), hashable, `extra_attrs` read-only, and `PropertyDef` invariants (each error code).
- **Tree:** insert, append, remove (returns the index), move, index and walk order. Identity equality with two identical widgets. The `already_parented`, `cycle`, `bad_child` and `not_a_child` errors. `find`, `iter_ids` (duplicates kept), `main_window`, and `repr` that does not recurse.
- **Names:** `split_class_name`/`qualify` table tests, including bad inputs (`"a:b:C"`, `":X"`, `"tb:"`, `"button"`). Hypothesis round-trip `qualify(*split(n)) == n`.

**i18n:**
- `set_language("en_XA")` changes `spec.label()`, `PropertyDef.label()`, `error.message` and `diag.message` without re-importing. Importing `core.widgets` performs no translation (spy on `i18n._translation`).
- A broken translation placeholder falls back to the msgid.
- `N_` is the identity.

**Registry:**
- **Setup:** use fake `EntryPointLike` objects through `Registry(entry_points=…)`.
- **Entry-point shapes:** spec, iterable, callable, generator, bad object, bad item.
- **Failure cases:**
  - `load()` raises, the callable raises, iteration raises → diagnostics, no exception;
  - `KeyboardInterrupt` propagates;
  - incompatible API;
  - reserved name;
  - duplicate (first wins, independent of input order);
  - bad fallback and fallback mismatch;
  - core safety net (empty source → 24 core specs + `core_fallback`).
- **Resolution:** all four `resolve` branches plus `unknown_class`.
- **Backends:** backends listed but not loaded (a fake `load` that would fail is never called), plus `load_backend` success, failure and unknown.
- **Default registry:** `default_registry()` is cached, `reset_default_registry()` rebuilds it, and the real metadata yields the `core` entry point with no diagnostics (after `uv sync`).

**Isolation and gates:**
- **Toolkit isolation (subprocess):** `python -c "import pyguibud.core, sys; from pyguibud.core.registry import default_registry; default_registry().specs(); assert not {'tkinter','ttkbootstrap','PySide6'} & set(sys.modules)"`.
- **Gates:**
  - `uv run pytest tests/core --cov=pyguibud.core --cov-report=term-missing --cov-fail-under=90`
  - `uv run mypy src/pyguibud/core` (strict)
  - `uv run ruff check src/pyguibud/core tests/core`
