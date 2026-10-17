# ADR-002 — `.ui` file format

- **Status:** Accepted (Step 02 UAT) · **Date:** 2026-10-05 · **Step:** 02

## Context
The format must be human-readable, diff-friendly, validatable, translatable, forward compatible and parsable with the standard library only (the runtime must stay tiny).

## Decision
- **XML**, root `<pyguibud-ui>`, default namespace `urn:pyguibud:ui:1`, attribute `schema_version="MAJOR.MINOR"`.
- Parsed with stdlib `xml.etree.ElementTree`, hardened against entity expansion (no DTDs, size limit). Validated by PyGUIbud's own rule validator. An XSD is published for external tools but is not required at runtime.
- **Versioning:** newer MAJOR → refuse; newer MINOR → read-only with a warning; older → chain of migration functions (`migrations/1_0_to_1_1.py`…).
- **Structure:** `meta`, `resources`, `variables`, then one or more `window` elements (`kind = main | dialog | component`, at most one `main`). `<include>` embeds `component` windows from the same or another file; cycles are rejected.
- **Properties:** `<prop name=…>` elements; text values may carry `translatable`, `context` and `comment` for gettext extraction.
- **Assets:** images are referenced by **paths relative to the `.ui` file** and declared once in `<resources>`. Absolute paths and paths escaping the project via `..` trigger a warning.
- **Theme:** `meta/@theme` stores a ttkbootstrap theme name. Other backends may map it or ignore it.
- **Saving:** deterministic attribute/element order and 2-space indentation, for clean diffs. Atomic write (write temp file → rename) with a `.bak` of the previous version.

## Consequences
- ➕ Familiar to Qt Designer users, easy to review in Git, zero runtime dependencies.
- ➖ XML is more verbose than YAML/JSON (accepted for the tooling ecosystem and namespaces).

## Addendum A — Step 08 details (Accepted by the user 2026-10-05: model additions approved; comments and processing instructions are warned about and dropped on save)
- **Page placement:** each child of a page container (Notebook, PanedWindow; see ADR-005 Addendum A) carries `<page image="res_id" weight="1">`. The tab text is a nested `<prop name="text" translatable="true" context="…" comment="…">…</prop>`, so it is extracted for translation like any other property.
- **Parser:** `pyexpat` is driven directly into `ElementTree.Element` trees. DOCTYPE and entity declarations are rejected, and the limits are 10 MiB and 100 levels of nesting. Input must be UTF-8 (a BOM and CRLF are accepted). Errors are reported as `file:line:col: message` (`XmlIoError`, codes `xml.*`). The reader raises on the first error and does no semantic validation (that is Step 09).
- **Read API:** `read_ui()` returns `ReadResult(document, warnings, read_only, source_version, source)`.
- **Versioning:**
  - The root namespace `urn:pyguibud:ui:N` encodes the MAJOR version, so a 2.x file reports "newer", not "not a .ui file".
  - **Newer MINOR:** the file opens read-only and the document keeps its version, which makes the writer refuse it.
  - A MINOR bump may only *add* optional elements and attributes, or allow existing elements in new places. New enum values or changed meaning require a MAJOR bump.
  - **Migrations** run on the element tree before the model is built, keyed by from-version. They live in `core/migrations/m1_0_to_1_1.py`, because the earlier `1_0_to_1_1.py` is not an importable name.
- **Preservation:**
  - Foreign-namespace attributes and elements are kept (`extra_attrs` / self-contained `RawXml`) and re-emitted after the known children.
  - Unknown names in the PyGUIbud namespace are kept with a warning (likely typos). Known elements in the wrong place are errors.
  - `<prop>` is text-only, and its text is preserved exactly.
  - **Comments and processing instructions are dropped**, with a warning.
  - All namespace declarations are hoisted to the root (original prefixes kept, `ns1…` generated for conflicts).
- **Canonical output:**
  - UTF-8 with an XML declaration, `\n` only, 2-space indent and a final newline;
  - a fixed attribute order per element, then extras sorted by key;
  - default values omitted (except `kind`, `type`, `source_locale`), props sorted by name, `<x/>` for empty elements;
  - characters XML cannot store are refused before writing;
  - the writer never stamps `meta/@generator`.
- **Save:** temp file in the same folder, then fsync, a copy to `<name>.bak`, and `os.replace` (retried on Windows locks).
- **Model additions (Step 07 model):** `extra_children` on the leaf value objects, and `Document.resources_extra`/`variables_extra` (`ContainerExtras`).
- **Spec:** `docs/specs/xml-io.md`.

## Addendum B — the `tb` prefix always means ttkbootstrap (Step 19b, hardening D9 (a), accepted by the user 2026-10-17)
- **Problem (QA-17a-03):** `xmlns:tb="urn:evil"` made `tb:bootstyle="primary;x"` look like an invalid ttkbootstrap attribute although it belongs to a foreign namespace; it checked clean, and after a real bootstyle was added the file read `tb:bootstyle="primary;x" ns1:bootstyle="info"`. No data was lost; only the text misled.
- **Writer:** a known prefix (`KNOWN_NAMESPACES`, today only `tb`) bound in `Document.namespaces` to another URI is ignored (`xmltree.effective_namespaces`). That URI gets a generated prefix (`ns1`, …) and `tb` is bound to `urn:pyguibud:ext:ttkbootstrap:1`. A second save is byte-identical.
- **Reader:** a file binding a known prefix to another URI loads, with one warning per prefix: `xml.foreign_prefix` ("The prefix '{prefix}' is bound to the foreign namespace '{uri}'; …"). Only the first binding of a prefix is examined (the reader keeps one binding per prefix).
- **No schema change:** namespace prefixes are not part of the format; the data is identical, only the prefix in the text changes.
