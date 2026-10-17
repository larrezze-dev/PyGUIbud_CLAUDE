# Spec — Step 08: `.ui` XML schema and I/O

- **Status:** Ready for implementation (**[approval]** items approved by the user 2026-10-05) · **Date:** 2026-10-05 · **Owner:** BACKEND · **Sources:** ADR-002 (+ Addendum A), ADR-001/003/005, `docs/specs/core-model.md`, FEATURES.md §4
- Implement verbatim. Anything not listed here is out of scope (§14). "Model" means `pyguibud.core.model` as built in Step 07.

## 1. Modules
| File | Contents |
|---|---|
| `src/pyguibud/core/errors.py` | **+** `XmlIoError` (§8). |
| `src/pyguibud/core/model.py` | **+** the model additions of §2 **[approval]**. |
| `src/pyguibud/core/schema/__init__.py` | `CURRENT_SCHEMA_VERSION: Final = "1.0"`, `XSD_FILENAME: Final = "pyguibud-ui-1.0.xsd"`, `parse_version(text: str) -> tuple[int, int] \| None` (regex `^(0\|[1-9][0-9]{0,8})\.(0\|[1-9][0-9]{0,8})$`, else None), `xsd_text() -> str` (via `importlib.resources.files(__name__)`). |
| `src/pyguibud/core/schema/pyguibud-ui-1.0.xsd` | Published XSD (§11). Documentation for external tools; never loaded at runtime. |
| `src/pyguibud/core/xmltree.py` | Hardened expat parser into `xml.etree.ElementTree.Element` trees, canonical serialiser, prefix assignment (§5–7). No model knowledge beyond `NS_UI`/`KNOWN_NAMESPACES`. |
| `src/pyguibud/core/migrations/__init__.py` | `Migration`, `MIGRATIONS` (empty), `migrate()` (§4). |
| `src/pyguibud/core/xml_io.py` | Public read/write API (§3), element ↔ model mapping (§9), atomic save (§10). |
| `src/pyguibud/core/atomic.py` | `create_temporary()`: the temporary file for every atomic write (§10 step 3; also `codegen.output.write_atomic` and the designer's settings/autosave). Stdlib only. Added in Step 15b (QA-15b-01). |
| `src/pyguibud/uic.py` | `pyguibud-uic` CLI (§12). |
| `examples/hello.ui` | §13, byte-exact. |

- **Import graph (no cycles):** `schema → (stdlib)`; `xmltree → errors, model, i18n`; `migrations → xmltree, schema, errors, i18n`; `atomic → (stdlib)`; `xml_io → model, errors, schema, xmltree, migrations, atomic, i18n`; `uic → core.xml_io, cli, i18n`.
- **Stdlib only.** `xmltree` imports `xml.parsers.expat` and `xml.etree.ElementTree` (for the `Element` type only: **never** `ET.parse`, `ET.fromstring`, `ET.XMLParser`, `ET.tostring`, `ET.indent` or `ET.register_namespace`). No `tkinter`, no `registry` import (the reader does not know the widget registry), nothing designer-only: `pyguibud_runtime` will reuse the reader (Step 10/20).
- **Re-exports from `pyguibud.core`** (add to `__all__`): `CURRENT_SCHEMA_VERSION`, `MAX_UI_BYTES`, `MAX_DEPTH`, `ReadResult`, `XmlWarning`, `XmlIoError`, `ContainerExtras`, `read_ui`, `read_ui_bytes`, `read_ui_string`, `dump_ui`, `write_ui`. `xmltree` and `migrations` are importable but not re-exported.
- `pyproject.toml`: add `pyguibud-uic = "pyguibud.uic:main"` under `[project.scripts]`; add `"pyguibud.uic"` to the strict mypy override list; add `"/examples"` to the sdist `include`. The wheel needs **no** change: hatchling ships every file under `src/pyguibud`, `.gitignore` does not exclude `*.xsd` (verify with the gate in §15). Run `uv sync` afterwards.

## 2. Model additions **[approval]** (minimal; no other model change)
| Change | Why |
|---|---|
| `Event`, `GridCell`, `PackPlacement`, `PagePlacement`, `GridLine`, `Variable`, `ImageResource` gain `extra_children: tuple[RawXml, ...] = ()` (last field). | A foreign child inside `<cell>`, `<event>`… has no slot today. Without it the reader would have to refuse such files, also in read-only mode for newer minors. `Layout` already has this field. |
| New frozen value object `ContainerExtras(extra_attrs: Mapping[str, str] = {}, extra_children: tuple[RawXml, ...] = ())` (same §3 rules: `MappingProxyType`, `hash=False`). `Document` gains `resources_extra: ContainerExtras = field(default_factory=ContainerExtras)` and `variables_extra: ContainerExtras` (same). | `<resources>`/`<variables>` are flattened into dicts, so their own attributes/foreign children had nowhere to go. Moving them to `Document.extra_*` would change their position and meaning. |
| **No** read-only flag. | A newer-minor document keeps its source `schema_version` (e.g. `"1.3"`), and the writer refuses anything ≠ `CURRENT_SCHEMA_VERSION` (§3). The state survives copies and has no hidden flag. |
| `RawXml.extra_attrs` stays but is unused. | The reader leaves it empty; the writer raises `xml.write_bad_raw` if it is not empty. |
- `Prop` gets **no** `extra_children`. `<prop>` is text-only, and an element child is a read error (`xml.prop_has_children`), because mixed content would break exact text preservation.

## 3. Public API (`xml_io.py`)
```python
MAX_UI_BYTES: Final = 10 * 1024 * 1024     # checked before parsing
MAX_DEPTH: Final = 100                     # element nesting; keeps every recursive walk far below the recursion limit

@dataclass(frozen=True, slots=True, kw_only=True)
class XmlWarning:
    code: str; msgid: str; params: Mapping[str, object]   # read-only proxy, hash=False
    source: str; line: int | None = None; column: int | None = None
    message -> str     # property, format_message(msgid, params); never raises
    location -> str    # property, "source:line:column" (parts omitted when None)
    __str__ -> f"{location}: {message}"

@dataclass(frozen=True, slots=True, kw_only=True, eq=False)
class ReadResult:
    document: Document
    warnings: tuple[XmlWarning, ...]
    read_only: bool           # True only for a newer MINOR
    source_version: str       # as written in the file, before migration
    source: str

def read_ui(path: str | os.PathLike[str]) -> ReadResult
def read_ui_bytes(data: bytes, *, source: str = "<bytes>") -> ReadResult
def read_ui_string(text: str, *, source: str = "<string>") -> ReadResult
def dump_ui(document: Document) -> bytes                    # canonical bytes; never mutates the document
def write_ui(document: Document, path: str | os.PathLike[str], *, backup: bool = True) -> None
```
- `source` = `os.fspath(path)` as given (not resolved). It is used in every `location`.
- `read_ui_string`: strip one leading `"﻿"` and encode as UTF-8 (`UnicodeEncodeError`, e.g. a lone surrogate → `xml.bad_encoding`). The declared encoding is **not** checked (the text is already decoded). Then continue as for bytes.
- **Read-only and saving:** `dump_ui`/`write_ui` first check `document.schema_version`:
  - newer than current (by `parse_version`) → `XmlIoError("xml.read_only")`;
  - otherwise ≠ `CURRENT_SCHEMA_VERSION` (older or malformed, only possible for hand-built documents) → `xml.write_bad_version`.
  - The writer stamps `CURRENT_SCHEMA_VERSION`. It **never** touches `meta/@generator`; the designer sets that (Step 12).
- **Writer contract: it never produces a file its reader rejects.** All checks of §8 "write" run while building the output, before any byte reaches disk.

## 4. Read pipeline and versioning
1. **Bytes** (`read_ui` only):
   - `os.path.isdir(path)` → `xml.is_directory`. Windows raises `PermissionError` when opening a folder, so this check comes first.
   - Open with `"rb"` and read `MAX_UI_BYTES + 1` bytes. `FileNotFoundError` → `xml.file_not_found`; any other `OSError` → `xml.read_failed` (`reason = exc.strerror or str(exc)`). All are raised `from exc`.
2. **Size:** `len(data) > MAX_UI_BYTES` → `xml.too_large` (the same check applies to `read_ui_bytes`/`_string` input).
3. **Encoding:** strip a UTF-8 BOM, then `data.decode("utf-8")` strictly. On `UnicodeDecodeError` → `xml.bad_encoding`, with line = count of `b"\n"` before `exc.start` + 1 and column = byte offset in that line + 1. Then a NUL byte in the first 4 bytes → `xml.bad_encoding` (same msgid, position of that byte): NUL is valid UTF-8, but expat sniffs a leading `<\0`/`\0<` as UTF-16 despite the UTF-8 override. (UTF-16 and UTF-32 files fail here, with or without BOM; a NUL further on is left to expat → `xml.malformed`.)
4. **Parse** (§5) → root `Element`, positions, hoisted namespaces, discarded count. The declared encoding is checked in `XmlDeclHandler` (bytes path): if not None and its lower-case form is not in `{"utf-8", "utf8"}` → `xml.bad_encoding` (msgid variant with `{encoding}`).
5. **Root and version** (in this order, so a future 2.x file says "newer", not "wrong root"):
   1. Root local name must be `pyguibud-ui` and its namespace must match `^urn:pyguibud:ui:([1-9][0-9]{0,8})$` → else `xml.bad_root`. Call the captured number N.
   2. `schema_version` missing → `xml.missing_attribute`; `parse_version` is None → `xml.bad_version`.
   3. N > 1, or major > current major → `xml.newer_major` (refuse).
   4. Same major, minor > current minor → warning `xml.newer_minor`, `read_only=True`, and the document keeps that `schema_version`. "Misplaced known element" becomes a kept-with-warning case (§9.4).
   5. Older → `migrations.migrate(root, version, source=…)` **on the element tree, before mapping**, then warning `xml.migrated`. The document gets `CURRENT_SCHEMA_VERSION`.
6. **Map** the tree to the model (§9). Warnings are collected in document order.

**Migrations (`core/migrations/__init__.py`)**
```python
Migration = Callable[[ET.Element], tuple[ET.Element, str]]   # (new_root, new_version)
MIGRATIONS: Final[Mapping[str, Migration]] = MappingProxyType({})   # keyed by from-version, e.g. "1.0"
def migrate(root: ET.Element, version: str, *, source: str,
            registry: Mapping[str, Migration] | None = None) -> tuple[ET.Element, str, tuple[str, ...]]
```
- `registry=None` reads the module global **at call time**, so tests can inject a chain without monkeypatching.
- Loop while `version != CURRENT_SCHEMA_VERSION`:
  - no entry → `xml.no_migration` (`version`);
  - the step's result must parse and satisfy `old < new ≤ current` → else `xml.bad_migration` (`version`, `result`). This prevents loops and overshoot.
- It returns the root, the final version and the versions passed through.
- Exceptions other than `XmlIoError` raised by a step are bugs and propagate.
- **Naming:** one module per step, `core/migrations/m1_0_to_1_1.py` exposing `migrate(root) -> (root, "1.1")` and registered in `MIGRATIONS`. ADR-002's `1_0_to_1_1.py` cannot be imported (Addendum A).
- Steps edit the tree in place or build a new one. Elements they create have no position, so errors on them carry no line/column.

## 5. Hardened parser (`xmltree.parse(data: bytes, *, source: str, check_declared_encoding: bool, root_check: Callable[[str], None] | None = None) -> ParsedTree`)
`ParsedTree` (frozen): `root: ET.Element`, `positions: Mapping[ET.Element, tuple[int, int]]` (identity-keyed dict), `namespaces: Mapping[str, str]` (hoisted, §7), `discarded: int`.

| Setting / handler | Behaviour |
|---|---|
| `expat.ParserCreate(encoding="UTF-8", namespace_separator="}")` | Names arrive as `uri}local` → stored as Clark `{uri}local`. A name without `}` is in no namespace: for an **element** → `xml.no_namespace_element`; for an attribute → plain name. |
| `buffer_text = True`, `ordered_attributes = False`, `specified_attributes = True` | Text may still arrive in several chunks: **append** to the current element's `.text` (no child yet) or to the last child's `.tail`. |
| `SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)` | |
| `StartDoctypeDeclHandler`, `EntityDeclHandler`, `UnparsedEntityDeclHandler`, `NotationDeclHandler`, `ExternalEntityRefHandler` | raise `xml.doctype_forbidden` (current position). Blocks the billion-laughs attack and XXE. |
| `StartElementHandler` | depth + 1 > `MAX_DEPTH` → `xml.too_deep`. Record `(CurrentLineNumber, CurrentColumnNumber + 1)` in `positions`. **At depth 1** call the `root_check(tag)` callable passed to `parse()` **before** the no-namespace test. `xml_io` passes the §4.5.1 check, so a file whose `xmlns` was deleted reports `xml.bad_root` at the root's line rather than `xml.no_namespace_element`. `parse_fragment` passes no check. |
| `StartNamespaceDeclHandler(prefix, uri)` | `prefix=None` → `""`. Feeds hoisting (§7). |
| `CommentHandler`, `ProcessingInstructionHandler` | `discarded += 1` (content dropped). |
| `XmlDeclHandler` | Encoding check (§4.4), only when `check_declared_encoding`. |
| `expat.ExpatError` | → `xml.malformed`, `detail = expat.ErrorString(e.code)` (English, from expat), line `e.lineno`, column `e.offset + 1`. |
- Exceptions raised inside handlers propagate out of `Parse()`. `Parse(data, True)` is called once.
- **CRLF** is normalised to `\n` by XML itself. BOM was stripped in §4.3.
- `xmltree.parse_fragment(xml: str) -> ET.Element` parses `RawXml.xml` with the same handlers and limits. It accepts exactly one element, with no comments or processing instructions (any `discarded > 0` → error). Failures → `xml.write_bad_raw`.

## 6. Canonical serialiser (`xmltree.serialise`)
- **Whitespace:** "whitespace" means only `" \t\n\r"` (never `str.isspace`, which accepts U+00A0).
- **Layout modes:** *pretty* uses a 2-space indent per depth and `"\n"`; *compact* uses neither.
  - **Childless element:** empty text → `<t a="…"/>`; otherwise `<t a="…">text</t>`, with the text written exactly (leading/trailing whitespace, inner newlines and whitespace-only text are all kept).
  - **Element-only content:** the element has children, and its text and every child tail are None or whitespace. That whitespace is dropped. Each child goes on its own line at depth + 1 (pretty) or directly adjacent (compact), and `</t>` follows at depth.
  - **Mixed content** (any non-whitespace text or tail): written **inline** with no added whitespace. The whole subtree is verbatim, text and tails exactly.
  - Known model elements are never mixed.
- **Text escaping:** `&`→`&amp;`, `<`→`&lt;`, `>`→`&gt;` (so `]]>` is safe), `\r`→`&#13;`. CDATA is never written.
- **Attribute escaping:** the text rules plus `"`→`&quot;`, `\n`→`&#10;`, `\t`→`&#9;`, `\r`→`&#13;`. Values are always double-quoted, all attributes on one line, separated by one space.
- **Legal characters:** every name and value must consist of XML 1.0 `Char` (`#x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]`). Otherwise → `xml.illegal_char` (`where`, `codepoint` as `0001`). Lone surrogates and U+FFFE/U+FFFF are therefore refused.
- **Names:** an attribute key is either a plain NCName (`^[^\W\d][\w.\-]*$`, no `:`) or Clark `{uri}NCName` with a non-empty uri. Keys starting with `xmlns`, or with uri `http://www.w3.org/2000/xmlns/`, are rejected. Otherwise → `xml.write_bad_name`. An extra key equal to one of the element's known attribute names (§9) → `xml.write_bad_name`.
- **Attribute order:**
  - known elements: the schema order of §9, then the extras sorted by key (code-point order, so plain names come before Clark names);
  - unknown or foreign elements: all attributes sorted by key;
  - root: `schema_version`, `xmlns`, `xmlns:p…` sorted by prefix, then the extras.
- **Document bytes:** `<?xml version="1.0" encoding="UTF-8"?>\n` + pretty(root, depth 0) + `\n`, encoded as UTF-8. No BOM; always `\n`, on every OS. Comments and processing instructions are never written.
- **`RawXml.xml` form** (made by the reader): the **compact** serialisation of the subtree, with no XML declaration. Its top element declares every namespace the subtree uses:
  - `xmlns="urn:pyguibud:ui:1"` if any element is in `NS_UI`;
  - then `xmlns:p="uri"` sorted by prefix, with prefixes from §7.
  - The `xml` namespace is never declared.
  - On that top element the declarations come **first** (`xmlns`, then `xmlns:p` sorted by prefix), followed by its attributes sorted by key.
- **Writer re-emission:** each `RawXml` is parsed with `parse_fragment` and spliced **after the known children** of its owner, in list order. It is then serialised in pretty mode at the owner's depth, with the root's prefix map and no declarations of its own. A second save is therefore byte-identical.
- **Guard:** a fragment whose **top** element is in `NS_UI` and has a known local name (§9.4 vocabulary) → `xml.write_bad_raw`. It would read back as a real model element or be misplaced, which breaks the writer contract. Unknown `NS_UI` names and foreign elements are allowed. Known names *nested inside* a foreign fragment are allowed, because the reader keeps the whole subtree raw.

## 7. Namespaces and prefixes
- **Hoisting (reader):**
  - Collect every `StartNamespaceDeclHandler` call in document order into `namespaces: dict[str, str]`.
  - Skip default declarations (`""`), any prefix bound to `NS_UI` or to the `xml` namespace, any prefix already present, and any URI that already has a prefix ("first wins").
  - `Document.namespaces = {"": NS_UI, **hoisted}`. A file that never mentions `tb` therefore has no `tb` entry.
- **Effective map (writer): `xmltree.effective_namespaces(namespaces)`** keeps only what the reader can hoist back: it drops `""` and every prefix bound to `NS_UI`, and keeps the smallest prefix (code-point order) for each URI. `check_namespaces` still validates the raw map. Everything below uses the effective map, so no prefix choice depends on an entry a re-read would lose (byte-stable second save).
- **Prefix map (writer and `RawXml` form): `xmltree.assign_prefixes(namespaces, uris_in_order) -> dict[uri, prefix]`**
  - `NS_UI` elements → `""`. `NS_UI` *attributes* need a prefix and follow the rules below (the effective map never binds `NS_UI`, so it is always generated). The XML namespace → `"xml"` (never declared).
  - Other URIs → the smallest non-empty prefix `p` (code-point order) with `namespaces[p] == uri`.
  - Otherwise → the `KNOWN_NAMESPACES` prefix for that URI if it is free.
  - Otherwise → the first free `ns1`, `ns2`…
  - "Free" means not a key of the effective map and not already generated.
  - Generation follows the order of first use in a pre-order walk of the output (element tag, then attributes in output order, then children).
- **Root declarations written:**
  - `xmlns="urn:pyguibud:ui:1"` (always; any `namespaces[""]` is ignored);
  - every entry of the effective map (one prefix per URI, never `NS_UI`), whether used or not;
  - the generated prefixes.
  - No other element carries declarations.
- **Writer checks on `namespaces`:** a prefix that is not an NCName, is `xml`/`xmlns`, or has an empty URI → `xml.write_bad_namespace`. Do not use `ET.register_namespace` (global state).
- **Limitation (documented):** QNames inside attribute *values* of foreign content (e.g. `xsi:type="acme:T"`) are not rewritten when a prefix changes.

## 8. Errors and warnings
`XmlIoError(PyGUIbudError)` in `errors.py`:
- `__init__(self, code, message, /, *, source: str = "", line: int | None = None, column: int | None = None, **params)`.
- `source`, `line` and `column` are reserved: msgids must not use those placeholders.
- `.location` works as for `XmlWarning`. `.message` carries no location. `__str__` = `f"{location}: {message}"` if there is a location, else the message.
- Add it to `__all__`.

All msgids are wrapped in `N_()` at the raise site. `{element}` is the local name for `NS_UI` elements and the Clark name otherwise. `{where}` is an untranslated model path such as `window[main]/widget[btn_ok]/prop[text]@context`.

| Code | Kind | msgid |
|---|---|---|
| `xml.file_not_found` | read | "The file does not exist." |
| `xml.is_directory` | read | "This is a folder, not a .ui file." |
| `xml.not_a_file` | read | "This is a device or another special file, not a .ui file." (it exists but is not a regular file: `CON`/`NUL` on Windows, a FIFO or device on POSIX, which would block or never end; checked before opening, QA-10-03) |
| `xml.read_failed` | read | "The file could not be read: {reason}" |
| `xml.too_large` | read | "The file is larger than the limit of {limit} MiB for .ui files." |
| `xml.bad_encoding` | read | "The file is not valid UTF-8 text; save it with UTF-8 encoding." / variant "The file declares the encoding '{encoding}'; only UTF-8 is supported." |
| `xml.malformed` | read | "The file is not well-formed XML: {detail}" |
| `xml.doctype_forbidden` | read | "DOCTYPE and entity declarations are not allowed in .ui files." |
| `xml.too_deep` | read | "Elements are nested more than {limit} levels deep." |
| `xml.no_namespace_element` | read | "The element <{element}> has no namespace; remove xmlns=\"\" from the file." |
| `xml.bad_root` | read | "This is not a PyGUIbud .ui file: the root element must be <pyguibud-ui> in the namespace {namespace}." |
| `xml.missing_attribute` | read | "The element <{element}> needs the attribute '{attribute}'." |
| `xml.bad_version` | read | "'{version}' is not a valid schema version; expected MAJOR.MINOR, for example 1.0." |
| `xml.newer_major` | read | "This file uses schema version {version}; it needs a newer PyGUIbud (this one supports {current})." |
| `xml.no_migration` | read | "Schema version {version} cannot be upgraded to {current}." |
| `xml.bad_migration` | read | "The upgrade from schema version {version} failed: it produced version '{result}'." |
| `xml.duplicate_element` | read | "<{element}> appears more than once inside <{parent}>." |
| `xml.duplicate_placement` | read | "<{element}> has more than one placement (<cell>, <pack> or <page>)." |
| `xml.misplaced_element` | read | "<{element}> is not allowed inside <{parent}>." |
| `xml.unexpected_text` | read | "Text is not allowed directly inside <{element}>." |
| `xml.prop_has_children` | read | "The property '{name}' must contain plain text only, not elements." |
| `xml.bad_int` | read | "The attribute '{attribute}' of <{element}> must be a whole number, not '{value}'." |
| `xml.bad_bool` | read | "The attribute '{attribute}' of <{element}> must be true or false, not '{value}'." |
| `xml.bad_enum` | read | "The attribute '{attribute}' of <{element}> must be one of {choices}, not '{value}'." |
| `xml.bad_class_name` | read | "'{name}' is not a valid widget class name." |
| `xml.duplicate_prop` | read | "The property '{name}' is set more than once on <{element}>." |
| `xml.duplicate_resource` | read | "The resource id '{id}' is declared more than once." |
| `xml.duplicate_variable` | read | "The variable id '{id}' is declared more than once." |
| `xml.bad_page_prop` | read | "A <page> can only hold the property 'text', not '{name}'." |
| `xml.newer_minor` | warning | "This file uses schema version {version}, newer than {current}; it is opened read-only so that nothing is lost." |
| `xml.migrated` | warning | "The file was upgraded from schema version {version} to {current}; saving writes the new version." |
| `xml.unknown_element` | warning | "Unknown element <{element}> inside <{parent}> is kept as it is; check its spelling." |
| `xml.misplaced_kept` | warning | "<{element}> inside <{parent}> belongs to a newer schema and is kept as it is." |
| `xml.unknown_attribute` | warning | "Unknown attribute '{attribute}' on <{element}> is kept as it is; check its spelling." |
| `xml.discarded_content` | warning | "Comments and processing instructions ({count}) are not kept when the file is saved." (once per file, no position) |
| `xml.read_only` | write | "This document uses schema version {version}, newer than {current}; it was opened read-only and cannot be saved." |
| `xml.write_bad_version` | write | "The document's schema version '{version}' cannot be saved; expected {current}." |
| `xml.illegal_char` | write | "{where} contains the character U+{codepoint}, which XML cannot store." |
| `xml.write_bad_value` | write | "{where} has the value '{value}', which the .ui format cannot store." |
| `xml.write_bad_name` | write | "'{name}' is not a valid attribute name here ({where})." |
| `xml.write_bad_namespace` | write | "The namespace declaration '{prefix}' = '{uri}' is not valid." |
| `xml.write_bad_raw` | write | "Preserved XML content of {where} is damaged: {detail}" |
| `xml.write_key_mismatch` | write | "{where}: the key '{key}' does not match the name '{name}'." |
| `xml.write_failed` | write | "The file could not be saved: {reason}" |

- **Position:** read errors and warnings carry the position of the offending element (attribute errors: their element; unexpected text or tail: the containing element). Write errors carry `source` (path, or `"<memory>"` for `dump_ui`) and no line.
- **Fail fast:** the reader raises on the **first** error; there is no recovery.

## 9. Element ↔ model mapping
### 9.1 Value grammar (reader; the writer emits exactly these forms)
| Type | Accepted | Written |
|---|---|---|
| int | `^-?[0-9]{1,9}$` (ASCII; no `+`, spaces, `_` or other Unicode digits) → `xml.bad_int` | `str(v)`; `bool` or non-`int` → `xml.write_bad_value` |
| bool | exactly `true` / `false` → `xml.bad_bool` | `true` / `false` |
| enum | exact, case-sensitive member → `xml.bad_enum` (`choices` = `"a, b, c"`) | value checked against the same set → `xml.write_bad_value` |
| str | any (attribute-normalised by XML) | escaped (§6) |
| class | `split_class_name` succeeds → else `xml.bad_class_name` | same check |
- **Required attributes:** a missing one → `xml.missing_attribute`; present but empty is accepted (the validator judges, Step 09).
- **Omission:** an optional attribute is omitted when its value equals the **omit-when** value below (None, `""`, 0, 1, `false` as listed). `str | None` fields write `""` (it differs from None). ★ = always written.

### 9.2 Elements (canonical attribute order = column order; R = required)
| Element | Parent(s) | Model | Attributes: name (type, omit-when) | Children in canonical order | Foreign/unknown children & attrs → |
|---|---|---|---|---|---|
| `pyguibud-ui` | root | `Document` | `schema_version` R ★ (written as current) | `meta`, `resources`, `variables`, `window`* | `Document.extra_*` |
| `meta` | root | `Document.meta` | `generator` (str, `""`), `source_locale` (str ★), `i18n_domain` (str, `""`), `theme` (str, `""`) | — | `Meta.extra_*` |
| `resources` | root | `Document.resources` | — | `image`* (dict order) | `Document.resources_extra` |
| `image` | resources | `ImageResource` (key = id) | `id` R, `src` R | — | own `extra_*` |
| `variables` | root | `Document.variables` | — | `var`* (dict order) | `Document.variables_extra` |
| `var` | variables | `Variable` (key = id) | `id` R, `type` R enum `string\|int\|double\|bool`, `default` (str, `""`) | — | own |
| `window` | root | `Window` | `id` R, `kind` (enum `main\|dialog\|component` ★), `min_width` (int, None), `min_height` (int, None), `modal` (bool, false), `buttons` (str, None) | `prop`*, `menubar`?, `statusbar`?, `layout`?, (`widget`\|`include`)* | own |
| `menubar` | window | `Menubar` | — | `menu`* | own |
| `menu` | menubar, menu | `Menu` | `id` R | `prop`*, (`menu`\|`action`\|`separator`)* | own |
| `action` | menu | `Action` | `id` R, `handler` (str, None), `shortcut` (str, None) | `prop`* | own |
| `separator` | menu | `MenuSeparator` | — | — | own |
| `statusbar` | window | `Statusbar` | `id` R | `prop`* | own |
| `layout` | window, widget | `Layout` | `type` R ★ enum `grid\|pack`, `orient` (enum `vertical\|horizontal`, `vertical`), `padding` (int, 0), `gap` (int, 0) | `column`*, `row`* (tuple order) | own (`extra_children` tuple) |
| `column`, `row` | layout | `GridLine` | `index` R int, `weight` (int, 0), `minsize` (int, 0) | — | own |
| `widget` | window, widget | `Widget` | `class` R (→ `class_name`), `id` R, `bind` (str, None), `fallback` (str, None), `plugin` (str, None) | `prop`*, `event`*, (`cell`\|`pack`\|`page`)?, `layout`?, (`widget`\|`include`)* | own |
| `include` | window, widget | `Include` | `id` R, `src` R, `component` R | (`cell`\|`pack`\|`page`)? | own |
| `prop` | window, widget, menu, action, statusbar, page | `Prop` | `name` R, `ref` (str, None), `translatable` (bool, false), `context` (str, None), `comment` (str, None); **text = `value`** | none (→ `xml.prop_has_children`) | `extra_attrs` only |
| `event` | widget | `Event` | `name` R, `handler` R | — | own |
| `cell` | widget, include | `GridCell` | `row` R int, `column` R int, `rowspan` (int, 1), `columnspan` (int, 1), `sticky` (str, `""`), `padx` (int, 0), `pady` (int, 0) | — | own |
| `pack` | widget, include | `PackPlacement` | `fill` (enum `none\|x\|y\|both`, `none`), `expand` (bool, false), `padx` (int, 0), `pady` (int, 0) | — | own |
| `page` | widget, include | `PagePlacement` | `image` (str resource id, None), `weight` (int, 0) | `prop`? with `name="text"` (→ `PagePlacement.text`) | own |

### 9.3 Ordering and singletons
- The reader accepts known children **in any order**. The relative order of windows, widgets/includes, menu entries, events, columns, rows, resources, variables and extras is kept.
- The writer emits the canonical order of the table. `prop` elements are written **sorted by name** (code-point order) for every owner. Extras always come last.
- **Singletons:**
  - a second `meta`/`resources`/`variables` (root), `menubar`/`statusbar`/`layout` (window) or `layout` (widget) → `xml.duplicate_element`;
  - a second placement of any kind → `xml.duplicate_placement`;
  - a second prop with the same name on one owner, or a second prop in one `page` → `xml.duplicate_prop`;
  - duplicate `image` id → `xml.duplicate_resource`; duplicate `var` id → `xml.duplicate_variable`.
- **Written iff:**
  - `meta` → always (because of ★);
  - `resources` / `variables` → the dict is non-empty or its `ContainerExtras` is non-empty;
  - `menubar` / `statusbar` / `layout` / placement → not None (an empty `Menubar` → `<menubar/>`);
  - `page` → `<page/>` when everything is default.
- **Page:** `PagePlacement.text` is written as `<prop name="text" …>` inside `<page>`. A `<prop>` in `<page>` with another name → `xml.bad_page_prop`. A model `text` whose `name != "text"` → `xml.write_bad_value`.
- **Key consistency (writer):** for each `props[key]`, `resources[key]` and `variables[key]`, the key must equal `prop.name` / `.id` → `xml.write_key_mismatch`.

### 9.4 Unknown content and text
| Case | Reader behaviour |
|---|---|
| Child element in a foreign namespace (e.g. `acme:`, `tb:`) | Becomes `RawXml` in the owner's `extra_children` slot (table above). No warning. |
| Child in `NS_UI` with an **unknown** local name (a typo) | Becomes `RawXml` in the same slot, plus a warning `xml.unknown_element`. |
| Child in `NS_UI` with a **known** local name in the wrong parent (e.g. `<cell>` in `<window>`, `<widget>` in `<cell>`) | `xml.misplaced_element`. In newer-minor mode it is kept as `RawXml` instead, plus a warning `xml.misplaced_kept`. |
| Attribute in a foreign namespace | Goes to `extra_attrs` under its Clark name. No warning. |
| Unknown plain attribute, or any attribute in `NS_UI`'s namespace | Goes to `extra_attrs` (local or Clark name), plus a warning `xml.unknown_attribute`. In newer-minor mode there is no warning. |
| Text or tail in known non-`prop` elements | Whitespace-only is ignored. Anything else → `xml.unexpected_text`. |
| `prop` text | Becomes `Prop.value` **exactly** (`None` → `""`), including leading/trailing whitespace and newlines. |
| Comments and processing instructions | Dropped, with **one** warning `xml.discarded_content` (count). Documented loss. |
- The known vocabulary (local names in `NS_UI`): `pyguibud-ui meta resources image variables var window menubar menu action separator statusbar layout column row widget include prop event cell pack page`.

## 10. Atomic save (`write_ui`)
1. `data = dump_ui(document)`. Every `XmlIoError` is raised here, before the file system is touched.
2. `target = Path(path)`. If `target.is_dir()` → `xml.write_failed`.
3. Create the temporary file with `core.atomic.create_temporary(target.parent or ".")` (name `~pgb<8 hex>.tmp`, never longer with the target, Step 19b H23; mode 0600, `O_EXCL`, at most 100 names; a `PermissionError` is raised at once). Not `tempfile.mkstemp`: on Windows it retries a refused folder up to `TMP_MAX` times because `os.access` ignores ACLs (QA-15b-01, Step 15b). Write the bytes, `flush`, `os.fsync`, close.
4. **POSIX:** `shutil.copymode(target, tmp)` if the target exists, else `os.chmod(tmp, 0o644)`. This undoes the 0600 of step 3.
5. If `backup` and the target exists: create a second temporary file as in step 3, close it, `shutil.copy2(target, tmp_bak)`, then `os.replace(tmp_bak, core.atomic.backup_path(target))` (retried as in step 6). Copy, never rename, so the target exists until step 6; a failed copy (a full disk) leaves the earlier `.bak` whole (QA-19b-02). `backup_path` is `<name>.bak` (`hello.ui` → `hello.ui.bak`); when that would exceed 255 UTF-16 units (Windows) or bytes (POSIX), the name before `.bak` is shortened until it fits, and the saved file keeps its full name (QA-19b-01).
6. `os.replace(tmp, target)`. On `PermissionError`, retry up to 5 times, 50 ms apart (Windows antivirus or indexer locks).
7. Best effort: `os.fsync` of the directory, POSIX only.
8. **Any `OSError` in steps 2–7:**
   - remove the temporary files (`contextlib.suppress(OSError)`);
   - raise `XmlIoError("xml.write_failed", …, source=str(path), reason=exc.strerror or str(exc)) from exc`.
   - The original file and any existing `.bak` from an earlier save stay intact. If the failure happens after step 5, the new `.bak` equals the original.
- Symlinks are replaced, not followed (documented).

## 11. XSD (`core/schema/pyguibud-ui-1.0.xsd`)
- `targetNamespace="urn:pyguibud:ui:1"`, `elementFormDefault="qualified"`, one global element `pyguibud-ui`.
- **Simple types:**
  - `Bool` (enumeration `true|false`; not `xs:boolean`, which accepts 1/0);
  - `Int` (`xs:string` pattern `-?[0-9]{1,9}`; not `xs:int`, which allows `+` and whitespace);
  - `Version` (pattern `(0|[1-9][0-9]{0,8})\.(0|[1-9][0-9]{0,8})`);
  - one enumeration per Literal field of §9.2.
- **Every complex type** has `<xs:anyAttribute namespace="##other" processContents="lax"/>`. Its content model is `<xs:choice minOccurs="0" maxOccurs="unbounded">` over the known children plus `<xs:any namespace="##other" processContents="lax"/>`.
  - `xs:choice` (not `xs:sequence`) avoids violating XSD's Unique Particle Attribution (UPA) rule and matches the reader's lenient order.
  - The XSD therefore cannot express singletons, and the reader is stricter. A comment in the XSD says so.
- **`prop`:** `xs:simpleContent` extending `xs:string`.
- **Consistency:** `##other` excludes both no-namespace and `NS_UI` content. That matches the reader: no-namespace elements are errors, and unknown `NS_UI` names and plain attributes are warnings (typos), so they are invalid per the XSD.
- **Shipping:** the gate in §15 lists the wheel and checks that the `.xsd` is inside it. A test also checks that `schema.xsd_text()` contains `targetNamespace="urn:pyguibud:ui:1"`.

## 12. `pyguibud-uic` (Step 08 scope)
- **Module:** `src/pyguibud/uic.py`, `main(argv: list[str] | None = None) -> int`. It reuses `_make_stdout_safe`, `_select_initial_language` and `_language_arg` from `pyguibud.cli` (an import, not a move).
- **Usage:** `pyguibud-uic [--lang CODE] [--version] [--check] FILE...`.
  - `--version` prints `pyguibud-uic <version>`.
  - `--lang` behaves exactly as in `pyguibud`.
- **Modes:**
  - no FILE → argparse usage error (exit 2);
  - FILE without `--check` → stderr `_("Generating Python code from .ui files arrives in a later development step; use --check to verify files.")`, exit 2.
- **`--check`:** each FILE is checked in order and processing continues after a failure.
  - **Glob expansion:** an argument that does not exist and contains `*`, `?` or `[` is expanded with `sorted(glob.glob(arg))`, because PowerShell does not expand globs. No match → `{arg}: error: ` + `_("no file matches this pattern")`.
  - **Output on stderr:** `{location}: error: {message}` and `{location}: warning: {message}`.
    - `location` is `path[:line[:column]]`, with the path exactly as typed.
    - The `error`/`warning` tokens are **fixed English**, so the output stays machine-parseable (GCC style); the messages are translated.
  - **On success:** stdout `_("{path}: no errors found")`.
  - **Exit codes:** 0 if every file was read (warnings and read-only files included); 1 if any file failed; 2 for a usage error.
  - Only `XmlIoError` is caught. Anything else is a bug and shows its traceback.
- **What `--check` proves in Step 08:**
  - **Caught:** well-formedness, encoding, size, depth, DOCTYPE/entities, root, version (newer/malformed/unmigratable), misplaced/duplicate singletons, duplicate props/resource ids/variable ids, missing required attributes, int/bool/enum syntax, class-name grammar, stray text, prop children.
  - **Not caught until Step 09** (the validator is added to `--check` then):
    - id uniqueness and identifier rules, and the count of `main` windows;
    - unknown core classes (`class="Buton"` passes the grammar), missing `fallback`;
    - container/layout/placement consistency and grid collisions;
    - event names, `handler`/`bind` identifiers and references, value ranges, image paths (see `docs/specs/validate-commands.md`).
  - **Not caught until Step 10:** include file existence, component kind and include cycles (user decision D4, 2026-10-05).
  - Unknown elements and attributes are **warnings** (exit 0).
- **Honest UAT corruptions (guaranteed exit 1):**
  - delete a `>`;
  - `row="x"`;
  - duplicate `<prop name="text">`;
  - remove `class=`;
  - `schema_version="2.0"`;
  - add `<!DOCTYPE x>`;
  - delete `xmlns="urn:pyguibud:ui:1"` from the root (→ `xml.bad_root` on line 2).

## 13. `examples/hello.ui` (byte-exact, LF, final newline; canonical: `dump_ui(read_ui(f).document) == f.read_bytes()`)
```xml
<?xml version="1.0" encoding="UTF-8"?>
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1" xmlns:tb="urn:pyguibud:ext:ttkbootstrap:1">
  <meta generator="pyguibud" source_locale="en_GB" i18n_domain="hello" theme="flatly"/>
  <variables>
    <var id="user_name" type="string"/>
  </variables>
  <window id="main" kind="main" min_width="480" min_height="320">
    <prop name="title" translatable="true" context="window title">Hello PyGUIbud</prop>
    <menubar>
      <menu id="mnu_file">
        <prop name="text" translatable="true" comment="The underscore marks the access key.">_File</prop>
        <action id="act_quit" handler="on_quit" shortcut="Ctrl+Q">
          <prop name="text" translatable="true">_Quit</prop>
        </action>
      </menu>
    </menubar>
    <statusbar id="sts_main">
      <prop name="text" translatable="true">Ready</prop>
    </statusbar>
    <layout type="grid" padding="12" gap="6">
      <column index="0" weight="1"/>
      <row index="0" weight="1"/>
    </layout>
    <widget class="Notebook" id="nbk_main">
      <cell row="0" column="0" sticky="nsew"/>
      <widget class="Frame" id="frm_greeting">
        <page>
          <prop name="text" translatable="true" context="tab" comment="Title of the first tab.">Greeting</prop>
        </page>
        <layout type="grid" padding="12" gap="6">
          <column index="1" weight="1"/>
        </layout>
        <widget class="Label" id="lbl_name">
          <prop name="text" translatable="true" context="greeting form">Your name:</prop>
          <cell row="0" column="0" sticky="w"/>
        </widget>
        <widget class="Entry" id="ent_name" bind="user_name">
          <event name="activate" handler="on_greet"/>
          <cell row="0" column="1" sticky="ew"/>
        </widget>
        <widget class="Button" id="btn_greet" tb:bootstyle="primary">
          <prop name="text" translatable="true">Say hello</prop>
          <event name="command" handler="on_greet"/>
          <cell row="1" column="1" sticky="e"/>
        </widget>
      </widget>
      <widget class="Frame" id="frm_about">
        <page>
          <prop name="text" translatable="true" context="tab">About</prop>
        </page>
        <layout type="pack" padding="12"/>
        <widget class="Label" id="lbl_about">
          <prop name="text" translatable="true" comment="Shown on the About tab.">PyGUIbud example: one window, two tabs.</prop>
          <pack fill="x"/>
        </widget>
      </widget>
    </widget>
  </window>
</pyguibud-ui>
```
- Core widgets only, plus one `tb:bootstyle` extra attribute. No images, no includes, no comments.
- The ids satisfy the Step 09 rules: unique identifiers, not keywords, no leading `_`.

## 14. Out of scope
- **Step 09:** the validator (the semantic rules in §12, except include resolution, which moves to Step 10) and the command stack.
- **Steps 10–11:** `load_ui`, backends and codegen (`pyguibud-uic FILE -o`, `--extract`, `--stubs`).
- **Later steps:**
  - item and column models for Combobox, Listbox and Treeview (a future MINOR schema bump);
  - designer UI for read-only and "save a copy";
  - an `xml:lang`-aware or QName-aware rewrite;
  - preserving comments;
  - multi-error recovery in the reader;
  - a standalone `pyguibud-runtime` distribution (Step 20; the reader is kept designer-free for it).
- **Translations:** new msgids are extracted with `-k N_` as usual. Translating them belongs to the i18n pass, not to this step.

## 15. Test plan (TESTING agent) and gates
**Layout:**
- `tests/core/test_xml_read.py`, `test_xml_write.py`, `test_xmltree.py`, `test_migrations.py`, `test_xml_roundtrip.py` (hypothesis), `tests/test_uic.py`.
- Golden pairs go in `tests/core/data/xml_io/<case>.in.ui` → `<case>.out.ui` (expected canonical bytes).
- The `.gitattributes` rule `*.ui text eol=lf` already exists (git `core.autocrlf=true` on this machine). Inputs with **CRLF or a BOM are therefore built as bytes inside the tests**, never stored as files.
- **Helper** `tests/core/xml_helpers.py: structure(obj) -> object`. It returns a recursive plain-data dump (type name, fields, children; `MappingProxyType` → dict) because nodes compare by identity (`eq=False`).

**Cases:**
- **Round trip:**
  - byte idempotence `dump(read(dump(read(x)))) == dump(read(x))` for every golden input;
  - `hello.ui` is canonical, and a test parametrised over all `examples/*.ui` checks they all are;
  - hypothesis: a random model (XML-legal strings via a `Char` filter, ids, props incl. whitespace/newline values, extras, `RawXml` built from small foreign trees) → `structure(read(dump(m))) == structure(m)`, and dump→read→dump is byte-equal.
    - Generate each `RawXml` already in the canonical compact form (§6) by passing it through `xmltree` once.
    - Restrict the top element of every generated `RawXml` to foreign namespaces or unknown `NS_UI` names (see the §6 guard).
    - Compare `Document.namespaces` separately: the reader adds the generated prefixes, so the read map must be a superset of the model's map.
    - Dict order does not matter (props are written sorted).
- **Inputs:**
  - CRLF and BOM (identical result to the LF/no-BOM version);
  - foreign prefix `xmlns:acme` on attributes and on elements, declared on the root and only locally (hoisted; a second save is byte-identical);
  - a conflicting local re-use of a prefix (→ `ns1`);
  - a document whose `namespaces` lacks `tb` while `tb:` content exists (→ `tb` declared);
  - `xml:lang` on a foreign element (no declaration written);
  - an unknown default-namespace element (kept + warning);
  - mixed-content foreign element preserved verbatim;
  - page with translatable text, context and comment;
  - `<page/>`;
  - whitespace-only and multi-line prop values, and attribute values containing `\n`, `\t` and `\r`;
  - `& < > ]]> "` in text and attributes;
  - comments → `xml.discarded_content` count.
- **Versions:**
  - `1.1` → read-only + warning, then `dump_ui` raises `xml.read_only`;
  - `2.0`, and the root namespace `urn:pyguibud:ui:2` → `xml.newer_major`;
  - `abc`, `1`, `1.0.0`, `01.0`, ` 1.0` → `xml.bad_version`;
  - `0.9` → `xml.no_migration`;
  - an injected chain `0.8→0.9→1.0` works and warns;
  - a non-advancing or overshooting step → `xml.bad_migration`.
- **Hardening:**
  - DOCTYPE, billion laughs and an external entity → `xml.doctype_forbidden`;
  - `MAX_UI_BYTES + 1` bytes → `xml.too_large`;
  - depth `MAX_DEPTH + 1` → `xml.too_deep`;
  - an undefined entity, or a truncated file → `xml.malformed` with line/column;
  - Latin-1 bytes, UTF-16 and a declared `ISO-8859-1` → `xml.bad_encoding`;
  - a non-root `xmlns=""` element → `xml.no_namespace_element`;
  - a root without `xmlns` → `xml.bad_root` (not `no_namespace_element`).
- **Reader errors:** one test per read code of §8 asserting `code`, `line` and `column`. Required coverage:
  - every singleton duplicate;
  - every int, bool and enum field (`+1`, `1_0`, ` 1`, `٣`, `True`, `1`);
  - every required attribute;
  - non-whitespace text in a widget;
  - an element inside a `prop`;
  - `class="button"` and `class="a:b:C"`;
  - a misplaced `<cell>` in a `<window>`.
- **Writer:**
  - every write code: a `\x01` in a prop value, U+FFFE, a lone surrogate, `extra_attrs={"class": …}`, `{"a b": …}`, bad namespace prefixes, a damaged `RawXml`, a `RawXml` whose top element is a known `NS_UI` name (`<cell>`), `RawXml.extra_attrs` set, a key mismatch, an enum outside the Literal, `True` in an int field;
  - default omission and ★ attributes;
  - props sorted;
  - `dump_ui` does not mutate the document.
- **Atomic save** (`tmp_path`):
  - creates the file; the second save creates `hello.ui.bak` equal to the previous bytes;
  - `backup=False`;
  - a target that is a directory;
  - a failure injected at `os.replace` via monkeypatch: the original is intact, no `.tmp` is left behind, and the error is `xml.write_failed`;
  - a `PermissionError` retry that succeeds on the third attempt.
- **XSD:** `xsd_text()` loads, is well-formed (parsed with `xmltree.parse`), and declares the target namespace.
- **CLI** (`tests/test_uic.py`, `main([...])` plus `capsys`):
  - a valid file → exit 0;
  - each of the seven UAT corruptions → exit 1 with `path:line:col: error:`;
  - several files mixed → exit 1, with every file reported;
  - a missing file, a directory, a non-UTF-8 file;
  - glob expansion with no match;
  - no arguments → 2; FILE without `--check` → 2;
  - `--lang en_XA` changes the message but not the `error:` token;
  - `--version`.
- **Isolation:** the subprocess test of Step 07 is extended with `import pyguibud.core.xml_io`. No toolkit module may be loaded.

**Gates (each run, with its result, in the report):**
- `uv sync`
- `uv run pytest tests/core --cov=pyguibud.core --cov-report=term-missing --cov-fail-under=90`
- `uv run pytest tests/test_uic.py`
- `uv run mypy src/pyguibud/core src/pyguibud/uic.py`
- `uv run ruff check src tests`
- `uv run pyguibud-uic --check examples/hello.ui` → exit 0
- `uv build --wheel`, plus `python -c "import zipfile,glob;z=zipfile.ZipFile(sorted(glob.glob('dist/*.whl'))[-1]);assert any(n.endswith('pyguibud-ui-1.0.xsd') for n in z.namelist())"`
