---
name: ui-schema-rules
description: Condensed PyGUIbud .ui XML format, validator rules and architecture decisions (ADR-001..007). Use when reading, writing, validating, loading, generating code from or testing .ui files.
---

# `.ui` format and validator rules
Full sources: `FEATURES.md` §3–4 and `docs/adr/`. If this summary conflicts with them, they win.

## Shape
Canonical element and attribute order shown (spec: `docs/specs/xml-io.md`; ADR-002 Addendum A). `?` = optional, `*` = repeated.
```xml
<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">
  <meta generator? source_locale="en_GB" i18n_domain? theme?/>
  <resources><image id src="icons/x.png"/>*</resources>?          <!-- relative paths -->
  <variables><var id type="string|int|double|bool" default?/>*</variables>?
  <window id kind="main|dialog|component" min_width? min_height? modal? buttons?>*
    <prop name ref? translatable? context? comment?>exact text</prop>*   <!-- sorted by name -->
    <menubar><menu id><prop/>* (<menu>|<action id handler? shortcut?>|<separator/>)*</menu>*</menubar>?
    <statusbar id><prop/>*</statusbar>?
    <layout type="grid|pack" orient? padding? gap?><column index weight? minsize?/>* <row …/>*</layout>?
    <widget class id bind? fallback? plugin? tb:bootstyle?>*        <!-- extras after known attrs, sorted -->
      <prop/>* <event name handler/>*
      <cell row column rowspan? columnspan? sticky? padx? pady?/> | <pack fill? expand? padx? pady?/> | <page image? weight?><prop name="text" …/>?</page>
      <layout/>? <widget/>* <include/>*
    </widget>
    <include id src component><cell/>|<pack/>|<page/></include>*
  </window>
</pyguibud-ui>
```
- **Values:** bool is exactly `true` or `false`; int is `-?[0-9]{1,9}`; defaults are omitted on write (except `kind`, `type` and `source_locale`).
- **Unknown content:** foreign-namespace content is preserved (and hoisted to the root). Unknown `NS_UI` names produce a warning. Misplaced known elements are an error. Comments are dropped, with a warning.
- **Read API:** `read_ui()` returns `ReadResult`. Newer MINOR → read-only (the writer refuses). Hardened expat parser, 10 MiB, depth 100.

## Decisions
- **ADR-001:** abstract core vocabulary (20 widgets + Menubar/Menu/Action/Statusbar). Toolkit extras are namespaced (`tb:`), and every extension widget has a `fallback`. Unknown namespaced content is **preserved on save**.
- **ADR-002:** stdlib `xml.etree`, hardened (no DTD/entities, size limit). Newer MAJOR → refuse; newer MINOR → read-only + warning; older → migration chain. Deterministic output with 2-space indent. Atomic save (temp → rename) + `.bak`.
- **ADR-003:** named handlers and variables only; **no inline code**. `load_ui(path, handlers=obj, translator=…, backend=…)` uses `strict=True` by default. Codegen uses composition (`class Ui_Main: def setup_ui(self, root, handlers)`), carries a "do not edit" header, has no PyGUIbud import and wraps strings in `_()`. `--stubs` never overwrites existing files.
- **ADR-004:** plugins via entry points `pyguibud.widgets` / `pyguibud.backends` → `WidgetSpec` (api_version, fallback, per-backend factories). A crashing plugin becomes a placeholder plus a diagnostics entry.
- **ADR-005:** layouts are **grid** or **pack (one orient per container)**. No `place`. One layout per container.

- **ADR-007:** runtime packaging boundary (Step 10, accepted; spec `docs/specs/runtime.md`). `pyguibud_runtime` may import `pyguibud.core`, `pyguibud.i18n`, `pyguibud.backends`; never the designer, cli, uic or codegen. Toolkits are imported only inside backend `prepare()`/`build()`. Validator additions: `validate(..., files=FileAccess|None)` (`core/files.py::DiskFiles`; `None` for command guards), `core/keys.py` (shortcut/key grammar, mnemonic split), R69–R80 (R79 `text_too_long` ≤ 100,000 chars, R80 string var default ≤ 10,000): `reserved_id` (`vars widgets windows setup_ui retranslate show run destroy`), `bad_buttons` (dialogs only), `bad_shortcut` (needs Ctrl/Alt unless F1–F24), `bad_key_sequence`, `duplicate_shortcut` (warning), `image_format` (PNG/GIF/PPM/PGM only), `image_missing`/`image_invalid` (16 MiB, 4096 px; PNG chunks walked to IEND with CRC, IHDR fields checked, PLTE required for palette images, IDAT one complete zlib stream (bounded decompression), binary P5/P6 only with full pixel data; files only), `bad_radio_value`, `bad_i18n_domain`. The Action `shortcut` is an attribute, not a property.
- **ADR-006:** findings, positions and command guards (Step 09, spec `docs/specs/validate-commands.md`). `Finding` (alias `XmlWarning`) has `severity`, `path`, `anchor` and `part`. `ReadResult.positions` maps `(node, part)` to `(line, col)`. `validate(document, registry)` is pure and iterative, returns every finding, and is the only home of the rules (codes `validate.*`, R01–R82 (R81 `bad_source_locale`, R82 `network_path` = UNC/device paths, an error everywhere and never opened; R49–R53 and R75–R76 need `files=`, see ADR-007/Step 10); R56–R68 are the writer-contract rules `bad_window_kind`, `bad_layout_type`, `bad_orient`, `bad_fill`, `bad_variable_type`, `bad_class_name`, `not_text` (also `None` for `Prop.name`/`value`, `source_locale`, extra attribute values), `not_flag`, `bad_page_text`, `bad_attribute_name` (extra attribute keys), `bad_raw_xml` (`extra_children`), `bad_item` (wrong entry types), `bad_schema_version`: anything `dump_ui` refuses must be a validator error). `CommandStack` guards: fresh validate → apply → uncapped validate → roll back if there are **new** errors → `dump_ui` safety net (`command.unsaveable`, only for newly unsaveable states); a rejection is an `Outcome`, not an exception. Constructors raise `TypeError` for bad direct arguments (indices, `SetEvents` items); any other exception is re-raised after the command is reverted (nothing changes). Other guard codes: `command.read_only`, `command.foreign_node`, `command.variable_in_use`, `command.resource_in_use`. `SetField` of a menubar/statusbar and `InsertNode` of a window attach deep copies of the bars (never the caller's object). Read-only documents block every edit. Plural deferred messages use `NP_(singular, plural)` with a `{count}` placeholder.

## Validator must block (with a translated reason)
- `id` (one namespace per file, resources and variables included): duplicate, empty, or not matching ASCII `^[A-Za-z][A-Za-z0-9_]{0,63}$`, or a Python keyword. The same grammar applies to `handler`, `bind` and `component`.
- More than one `kind="main"`. Includes: `src` empty or component not an id → error (Step 09); with `files=` (Step 10, R49–R53): missing/unreadable/invalid file, not a component, cycles, limits (depth 8, 32 files, 10,000 widgets). `src="#"` = this file.
- A child in a non-container. A window or layout container without a `<layout>`: **always an error, even when empty**. A `<layout>` on a page container (Notebook/PanedWindow) or on a non-container. Placement not matching the layout (`<cell>`/`<pack>`/`<page>`), including a missing one. Grid cell collisions. A `<widget>` using a menu class. Nesting deeper than the file depth limit allows. (Mixed pack orientation cannot be represented.)
- `handler`/`bind` not an identifier; `bind` to an undeclared variable, one of an incompatible type, or a class without binding (table in the spec, §5.1).
- Out-of-range values (Tk grid cells 0..9998 (`MAX_GRID_INDEX`), lines ≤ 9999; colours = hex or Tk names via `core/colours.py`, `System*` refused; pixels ≤ 10 000, spans ≥ 1, weights ≥ 0); invalid sticky; invalid property values vs `PropertyDef` (int/float/bool/enum/colour, min/max); translatable or `ref` on the wrong property type; unknown resource; invalid/unsupported/duplicate events; unknown core class; an extension without a core `fallback` (also when installed); illegal XML characters; closed-set values (window kind, layout type/orient, pack fill, variable type), extension class-name grammar, non-text/non-bool values.
- **Warnings only:** image/include paths that are absolute or escape via `..` (but `pyguibud-uic` generation refuses them unless `--force`; UNC/device paths are R82 errors); unknown props; a plugin not installed (its fallback is shown); attributes that are ignored; no windows.

Abstract events: `command`, `change`, `select`, `activate`, `focus_in`, `focus_out`, `key:<Sequence>`.
