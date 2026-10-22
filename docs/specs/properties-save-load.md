# Spec — Step 14a: properties, undo/redo, save/load

- **Status:** Proposed (awaiting the user's D1–D12) · **ADRs:** 003, 005, 006, 007, 009, 010, **011** (Proposed)
- **UAT (plan row 14a):** edit → save → close → reopen gives an identical file; Ctrl+Z/Ctrl+Y work everywhere (§19).
- **Grounding:** `core/commands.py` (`SetProp`/`RemoveProp`/`SetField`/`EDITABLE_FIELDS`/`SetEvents`/`SetVariable`/`RemoveVariable`/`SetResource`/`Macro`/`change_layout`/`CommandStack`), `core/xml_io.py` (`ReadResult`, `dump_ui`, `write_ui`), `core/model.py` (`Prop`, `PropertyDef`, `PropertyType`, `Document.extra_attrs`, `PagePlacement.image`), `core/validate.py` (`BIND_TYPES`, `WINDOW_PROPERTIES`), `pyguibud_runtime/_load.py` (`_expand`), `designer/{session,shell,app,standard_actions,editing,edit}.py`, `designer/panels/{inspector,tree}.py`, `designer/dialogs/{base,confirm}.py`, `cli.py`.
- **Plan naming:** the plan row is **14a** (functional). If D1 = B, it runs as two halves **14a.1** and **14a.2**, each with its own UAT, under the same row. **14p** (visual polish) is a separate row with its own spec, written later.

## 0. Scope fence and budget
**In Step 14a:**
- typed inspector editors with reset, multi-edit, and the layout, placement and window sections (§3);
- the events tab (§4);
- the variables panel with the rename and "remove and unbind" macros (§5);
- the in-place menu editor (§6);
- window management: add, rename, delete and tab switching (§7);
- copy, cut, paste and duplicate (§8);
- the file lifecycle and the CLI positional `.ui` (§9);
- the unsaved-changes guard (§10);
- autosave and crash recovery (§11);
- the settings store (§12);
- object-tree drag-and-drop (the D8 remainder, §13.1);
- external `<include>` rendering (§13.2).

**Not in Step 14a:**
| Feature | Step |
|---|---|
| Look and feel of the canvas, panels, inspector and icons | **14p** |
| Live preview, Export `.py`, `--stubs`, runtime dialog button bar and Alt bindings (Step 10 trims) | 15 |
| A `font` property type (if D8 = A) | after v1 (scope change, needs user approval) |
| Image-resource management (rename, delete unused) beyond "Add image…" | 19 |
| `tb:` attribute editors, the plugin diagnostics panel | 17 |
| Translated enum display names, localised key names in accelerators | 18 |
| A Preferences dialog (settings are captured implicitly) | after v1 |

**Budget (D2):** ≤ **3,600 lines of production code**, tests excluded.

| Area | Lines |
|---|---|
| Inspector editors, multi-edit, layout/placement/window sections | 900 |
| File lifecycle, CLI, guard, stamps, path rebasing | 520 |
| Autosave and recovery | 330 |
| Settings store and geometry/sash persistence | 280 |
| Clipboard (copy, cut, paste, duplicate) | 380 |
| Variables panel and macros | 300 |
| Events tab | 160 |
| Menu editor (insert actions) | 200 |
| Window management | 150 |
| Tree drag-and-drop | 220 |
| External include rendering | 160 |
| **Total** | **3,600** |

The include expansion for the canvas is designer code (§13.2). Core changes in 14a:
1. `CommandStack(dirty=)` (§11.4), at most 10 lines inside the total.
2. **Amended 2026-10-09 (Step 14a.2, QA-14a2-10; ADR-006 amendment, accepted by the user 2026-10-09):**
   - `validate()` always runs the same-file (`src="#"`) include checks (R51, R52 and R53), even without `files=`, so the command guards see them.
   - `guard_key` keys R52 by the loop's members instead of the anchor.
   - About 40 lines in `core/validate.py`.

**Trim order if over budget:**
1. external include rendering (keep the placeholder);
2. tree drag-and-drop (keep Alt+Up/Down);
3. the focus-in "changed on disk" notice (keep the check on save);
4. path rebasing on Save As (replace it with a warning that lists the broken paths);
5. multi-edit of placement fields (keep multi-edit of properties);
6. the colour chooser button (keep the hex entry and the swatch).

**Halves (D1 = B):**
- **14a.1 "Files and properties":** §§3, 4, 5, 9, 10, 11, 12. UAT 14a.1.
- **14a.2 "Structure":** §§6, 7, 8, 13. UAT 14a.2.

## 1. Module layout and dependency rules
```
src/pyguibud/core/commands.py        CommandStack(..., dirty=False)                       (§11.4)
src/pyguibud/designer/
  render_plan.py   PURE  + include sub-plans via core.files.DiskFiles (§13.2)
  settings.py      PURE  config_dir(), state_dir(), Settings, load_settings(), save_settings()
  files.py         PURE  FileStamp, DocumentFile, open_document(), save_plan(), rebase_paths(), RecentFiles
  recovery.py      PURE  RecoverySession (lock), snapshot(), scan_orphans(), RecoveryEntry
  clipboard.py     PURE  copy_text(nodes), parse_clipboard(text), paste_command(...)
  properties.py    PURE  Field, field_rows(nodes, registry), parse_value(), commit_commands()
  editing.py       PURE  + window/menu/variable builders and macros (§§5–7)
  session.py       PURE  + path, stamp, read_only_reason, open_document(), dirty
  panels/inspector.py   Tk: form of editors (replaces the read-only rows); Properties | Events tabs
  panels/editors.py     Tk: one editor class per Field kind
  panels/variables.py   Tk: Variables tab beside the object tree
  panels/tree.py        + drag-and-drop (§13.1)
  dialogs/save_changes.py  Save / Don't save / Cancel
  dialogs/recovery.py      the start-up recovery list
  dialogs/text.py          multi-line text + translatable/context/comment
  dialogs/message.py       error/information with one OK button
  dialogs/files.py         the only caller of tkinter.filedialog / colorchooser (a test seam)
```
- **Pure modules.** `settings`, `files`, `recovery`, `clipboard` and `properties` join `PURE_MODULES` (no `tkinter` in `sys.modules`). The OS lock in `recovery` uses `msvcrt`/`fcntl` (stdlib).
- **Boundaries.** `core` never imports `designer`. The designer still never calls `load_ui`. No new runtime dependency (`platformdirs` is not added; see D7).
- **Every model change goes through `CommandStack.execute()`.** Opening, closing and recovery only *replace* the document (as Step 12 does).
- **Debugger cautions (plan §5), now binding rules:**
  - **C1:** any message posted while a document opens comes **after** the first window is selected. Otherwise the selection change clears it.
  - **C2:** non-action command paths post `""` on success, or go through `Shell._invoker`. These are inspector commits, panel buttons, tree drops and recovery restore. Otherwise a stale refusal stays in the status bar.

## 2. Session model additions (`session.py`)
```python
class DesignerSession:
    path: Path | None                 # None = untitled
    stamp: FileStamp | None           # (size, mtime_ns, sha256) at open/save, for conflict checks
    read_only_reason: str | None      # msgid: newer schema, or path not writable (D11)
    def open_document(self, result: ReadResult, *, path: Path | None, dirty: bool = False) -> None
    def close_document(self) -> None   # document None: the panels show their empty hints
    @property
    def dirty(self) -> bool            # stack.is_dirty (False with no document)
```
- **Title:** `"{name}{star} — PyGUIbud"`, where `star` is `"*"` while dirty and `name` is the file name or `_("Untitled")`. A read-only document adds `_("(read-only)")`.
- **Empty state:** `document is None` is already handled by the tree and canvas panels (`tree.py:126`, `canvas.py:202/342/419`). The inspector, variables and events views add the same check. The canvas shows `_("No document. Press Ctrl+N for a new one or Ctrl+O to open a file.")`.

## 3. Inspector (`properties.py` pure + `panels/inspector.py`, `panels/editors.py`)
### 3.1 Field model (pure)
```python
@dataclass(frozen=True, slots=True)
class Field:
    key: str                 # "prop:text", "field:id", "place:row", "layout:orient", "line:col:2:weight"…
    section: str             # msgid: General | Properties | Layout | Placement | Window | Action
    label: str               # msgid (PropertyDef.display_name or a fixed one)
    kind: EditorKind         # see the table in 3.2
    value: str | None        # None = mixed across the selection (multi-edit)
    default: str | None
    is_default: bool
    choices: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    multi: bool = True       # False: shown only for a single selection
def field_rows(nodes: tuple[object, ...], registry: Registry, document: Document) -> tuple[Field, ...]
def parse_value(field: Field, text: str) -> str | Finding      # local grammar check, translated reason
def commit_commands(nodes, field: Field, value: str | None) -> Command   # None = reset
```
- **Validation authority.** `parse_value` only checks the grammar (int `-?[0-9]{1,9}`, float, colour, enum membership, min/max) so that the editor can say *why* at once. The command guard (`CommandStack.execute`) stays the final judge; its `Outcome.message` is shown as is.
- **Undo labels.** `commit_commands` returns a single `SetProp`/`RemoveProp`/`SetField` for one node, and a `Macro` with the label `N_("Set '{name}' on {count} elements")` (plural via `NP_`) for several.

### 3.2 Editors per kind
| Kind (source) | Editor | Commit | Command |
|---|---|---|---|
| `string` | `Entry` plus a "…" button that opens `dialogs/text.py` (multi-line text, **Translatable**, **Context**, **Comment**; the last three only when `PropertyDef.translatable`) | Enter, Tab or focus-out; dialog OK | `SetProp(Prop(name, value, translatable=…, context=…, comment=…))` |
| `int` / `float` | `Spinbox` (`from_`/`to` = min/max; no limit → ±10,000 as the validator allows) | Enter or focus-out; the arrows commit at once **and merge** (validate-commands §6.4) | `SetProp` |
| `bool` | `Checkbutton`; mixed → the ttk `alternate` state | click or Space | `SetProp` (`true`/`false`) |
| `enum` | read-only `Combobox` of `choices` (raw tokens; display names in Step 18) | `<<ComboboxSelected>>` | `SetProp` |
| `colour` | `Entry` + swatch + "Choose…" (`dialogs/files.ask_colour`) | Enter, focus-out, chooser OK | `SetProp` |
| `image` | read-only `Combobox`: `(none)` + resource ids + `Add image…` | selection | `SetProp(Prop(name, "", ref=id))`; "Add image…" → `Macro(SetResource(new), SetProp(ref))` |
| variable (`Widget.bind`) | read-only `Combobox` of declared variables whose type is in `BIND_TYPES[class]`, plus `(none)` and `New variable…` | selection | `SetField(w, "bind", id or None)`; "New…" → `Macro(SetVariable, SetField)` |
| id (`field:id`) | `Entry`, single selection only | Enter or focus-out | `SetField(node, "id", …)`; a window goes through `rename_window` (§7) |
| class | label (read-only) | — | — |
| handler (Action), shortcut (Action) | `Entry`; the shortcut is checked with `core.keys` | Enter or focus-out | `SetField(action, "handler"/"shortcut", …)` |
| window fields | kind (`Combobox` main/dialog/component), `min_width`/`min_height` (`Spinbox`), `modal` (`Checkbutton`), `buttons` (5 `Checkbutton`s; dialogs only; ticking a button appends it, unticking removes it, and the existing order of an opened file is kept), and the `WINDOW_PROPERTIES` props | as above | `SetField` / `SetProp` |
| layout (containers) | type (grid/pack; a new `editing.relayout_command` computes the placements in reading order (grid → pack row-major; pack → grid along the orient) and passes them to `change_layout`, which takes a placements mapping), orient, padding, gap | as above | `change_layout(...)` / `SetField(c, "layout", replace(...))` |
| placement | grid: row, column, rowspan, columnspan, sticky (4 `Checkbutton`s N/E/S/W), padx, pady, plus **weight and minsize of the occupied column and row**; pack: fill, expand, padx, pady; page: text (string kind), image, weight | as above | `SetField(w, "placement", replace(...))`; line weight → `SetField(parent, "layout", …)` |

- **Font:** no `font` PropertyType exists today (`model.py:712`), so it is **D8**.
- **Reset:** every row of a property or optional field has a focusable "Reset" button (`_("Reset to default")`, which is also its tooltip) that runs `RemoveProp` or `SetField(…, None)`. Defaults are shown as `"{value} (default)"`, as today.
- **Invalid input:** the editor gets the `danger` style, the reason goes to the status bar, and the typed text stays. Esc restores the model value. A refused command (`Outcome.accepted is False`) is shown the same way.
- **Read-only document:** every editor is disabled (`state="disabled"`), and the header shows `_("This document is read-only: {reason}")`.

### 3.3 Commit, merge and undo inside editors
- **Editor sessions.** Focus-in on an editor calls `stack.break_merge()`, and so does a commit. Spinbox arrows within one focus session merge into one undo step (as the plan §5 notes require: "`break_merge()` on editor commit").
- **Flush.** `Inspector.flush() -> bool` commits the focused editor's pending text. A refusal returns `False` and leaves the editor marked. It is called **before** Save, Save As, the guard (§10), Copy and any stack Undo/Redo. The autosave timer does **not** flush while the keyboard focus is in an inspector/variables editor (`Shell.typing()`, orchestrator decision 2026-10-08). A failed flush aborts Save and the guard, with the reason shown. Autosave skips the pending text and snapshots the model as it is.
- **Ctrl+Z / Ctrl+Y in an editor.** Undo and redo are `_TEXT_OWNED` today (`shell.py:39`), so a text widget keeps its own key. The rule:
  - when the editor text **differs** from the model value, Ctrl+Z restores the model value (a local revert);
  - when it is **unchanged**, Ctrl+Z goes to `stack.undo()`, and the editor then reloads from the model.

  Ctrl+Y is symmetric. Both go through `Shell._invoker` (C2).

### 3.4 Multi-edit (selection of n > 1)
- **Shown fields.** The fields shown are those whose key **and** `PropertyDef` (type, choices, minimum/maximum) are identical for every selected node. `multi=False` fields (id, class, bind, events) are hidden. The Step 13 header `"{count} elements selected; showing '{id}'."` is replaced by `_("{count} elements selected; editing shared properties.")`.
- **Mixed values.** Equal values are shown; different ones show the placeholder `_("(mixed)")` (bool → `alternate`).
- **Commits.** A commit creates one `Macro` (one undo step); Reset creates one `Macro` of `RemoveProp`s.
- **Placement fields** are shared only when every node has the same placement type and parent layout type; row and column are never multi-edited (collisions).

### 3.5 Layout
- **Placement.** The inspector sits in the right PanedWindow (Step 12). It becomes a `ttk.Notebook` with the tabs **Properties** and **Events** (D10). Inside a tab: a vertically scrolled grid of `label | editor | reset`, with sections as bold labels. There are no fixed widths, so 40 % slack applies.
- **Rebuilding.** The form is rebuilt on a **selection** change. On stack events only the values are refreshed (`after_idle`, R5 of Step 13).
- **Tab order:** editors top to bottom, then Reset, row by row. F6 enters the active tab's first editor.

## 4. Events tab (`panels/inspector.py`, single selection)
- **Rows.** One row per abstract event in `WidgetSpec.events` for the class: `command`, `change`, `select`, `activate`, `focus_in`, `focus_out`. Each row has a `Combobox` (editable) offering the handler names already used in the document (sorted). Empty means unbound.
- **Key events.** `key:<Sequence>` rows are listed below, with "Add key event…" (an `Entry` checked with `core.keys`) and a Remove button per row.
- **Commit.** Every change builds the full new event tuple and runs **one** `SetEvents(node, events)`. Invalid or duplicate events are refused by the guard with its reason.
- **Scope.** Actions show only their `handler` (§3.2). Windows, bars and multi-selections show `_("Select one widget to edit its events.")`.

## 5. Variables panel (`panels/variables.py`; a tab beside the object tree, D10)
- **List.** A `Treeview` with the columns id, type, default and "used by" (a count, with the ids in a tooltip).
- **Buttons** (each also has a context-menu item; the panel's own keys are Insert = add, F2 = rename, Delete = delete, all scoped to the panel):

| Button | Builder (`editing.py`) | Command |
|---|---|---|
| Add | `new_variable(document, type)` (`unique_id("var")`) | `SetVariable` |
| Rename (F2) | `rename_variable(document, old, new)` | `Macro(N_("Rename variable"), [RemoveVariable(old), SetVariable(new), SetField(w, "bind", new) for every user])` |
| Change type or default | inline edit (type `Combobox`, default `Entry`) | `SetVariable`; a type that breaks a binding or a radio value is refused by the guard (R41 / `bad_radio_value`) with its reason |
| Delete | `remove_and_unbind(document, id)` | unused → `RemoveVariable`; used → confirmation `_("'{id}' is bound to {count} widgets. Unbind them and delete it?")` (`ngettext`) → `Macro(N_("Remove and unbind variable"), [SetField(w, "bind", None)…, RemoveVariable])` |
| Bind to selection | — | `SetField(primary, "bind", id)` (or a `Macro` over a multi-selection) |

- **References.** Variables are referenced only by `Widget.bind`, so the macros cover every reference. Images (`Prop.ref`, `PagePlacement.image`) are not renamed in 14a (Step 19).

## 6. Menu editor (in place: tree + inspector, D9)
- **The tree already shows** Menubar › Menu › Action/Separator nodes. Selecting one shows its fields: Menu (id, text), Action (id, text, shortcut, handler, `icon` image prop), Separator (none).
- **New Edit ▸ Insert submenu** (canvas and tree scope; every item also sits in the tree's context menu):

| Action | Enabled when | Command |
|---|---|---|
| Insert ▸ _Menu bar | a window without a menubar is selected | `SetField(window, "menubar", Menubar())` |
| Insert ▸ M_enu | a menubar or menu is selected | `InsertNode(Menu(unique_id("menu")))` (a menu in a menu = a submenu) |
| Insert ▸ _Action | a menu or an item in it is selected | `InsertNode(Action(unique_id("act")))` after the item |
| Insert ▸ _Separator | as Action | `InsertNode(MenuSeparator())` |
| Insert ▸ Status _bar | a window without a statusbar is selected | `SetField(window, "statusbar", Statusbar(...))` |

- **Reorder:** Alt+Up/Down (existing) and tree drag-and-drop (§13.1). A `Menu`/`Action` never moves into a widget container; the guard refuses it.
- **Delete:** Delete on a menu, action, separator, menubar or statusbar node (lifting the Step 13 guard, `dnd-selection.md` §11). A menu with items asks for confirmation (the existing `ngettext` text).
- **Copy/paste** of menu nodes is not in 14a: `_("Menus and actions cannot be copied yet.")`.

## 7. Window management (canvas tabs; a new **Document** menu)
| Action | Shortcut | Builder | Notes |
|---|---|---|---|
| Add _main window / _dialog / _component | — | `new_window(document, kind)` with `DEFAULT_LAYOUT`, `unique_id` | a second main window → the guard reason (one main per file) |
| _Rename window… | F2 (canvas scope, a window selected) | `rename_window(document, window, new)` = `Macro([SetField(window, "id", new)] + [SetField(inc, "component", new) for every same-file include (src="#") of it])` | external files that include this component are **not** updated: a warning message says so. The inspector's window **Id** field uses the same builder (amended 2026-10-09) |
| _Delete window | — | `RemoveNode(window)` after confirmation | refused for the **last** window (`_("A document needs at least one window.")`) and for a component still included with `src="#"` (`_("'{id}' is still included by '{user}'.")`) |
| Next / previous window tab | Ctrl+PageDown / Ctrl+PageUp (global) | selection of the window | restores the keyboard tab switching lost in 13b |

## 8. Copy, cut, paste, duplicate (`clipboard.py`, D3/D4)
### 8.1 Clipboard format (D3 = A)
The clipboard holds a complete, valid `.ui` text, read back with the hardened reader. There is no second grammar.
```xml
<pyguibud-ui schema_version="1.0" xmlns="urn:pyguibud:ui:1"
             xmlns:clip="urn:pyguibud:clipboard:1" clip:mode="widgets" clip:origin="C:/…/form.ui">
  <meta source_locale="en_GB"/>
  <resources>…only the images the copied nodes reference…</resources>
  <variables>…only the variables they bind…</variables>
  <window id="{unique wrapper id}" kind="component">
    <layout type="grid|pack" orient?/>          <!-- the source parent's layout type and orient -->
    <widget …>…</widget>*                        <!-- grid cells normalised so the block starts at 0,0 -->
  </window>
</pyguibud-ui>
```
- **Marker.** The `clip:*` attributes are foreign-namespace root attributes, which the reader keeps in `Document.extra_attrs`. No schema change.
- **Modes.** `clip:mode` is `widgets` or `windows` (copying a window copies the whole window and pastes it as a new window). `clip:origin` is the source file's absolute path, or absent; it is used to rebase relative `src`. A pasted or duplicated `kind="main"` window becomes `kind="dialog"` when the target already has a main window (one main per file); otherwise it stays main.
- **Writing.** `dump_ui`. The text goes to the Tk clipboard (`clipboard_clear` + `clipboard_append`), so it can be pasted between two designer processes and into a text editor.

### 8.2 Paste
1. **Read.** `clipboard_get()`. More than 10 MiB once encoded as UTF-8 (the reader's byte limit) → refuse `_("The clipboard content is too large to paste.")`. Then `read_ui_string(text)`. Any failure, or no `clip:mode` marker → `_("The clipboard holds no PyGUIbud elements.")`.
2. **Check.** `validate_read(result, registry, files=None)`. Errors → `_("The clipboard content is not valid: {reason}")` (the first error). More than **2,000** widgets → refuse with a reason.
3. **Remap ids (D4 = A).** Every pasted id that clashes with the target document, or is reserved, gets a fresh id by the project's `unique_id` numbering: trailing digits are stripped and a counter appended, case kept (`btn_ok` → `btn_ok1`, `OkBtn` → `OkBtn1`). Variables: same id **and** same type → reuse the existing variable; otherwise a renamed copy, and the pasted `bind`s follow. Images: the same rule with an equal resolved path, and the `ref`/page `image` values follow.
4. **Rebase paths.** A relative image `src` is rebased from `clip:origin` to the target document (§9.4).
5. **Target.**
   - A selected container → append to it.
   - A selected leaf → after it in its parent.
   - A selected window → its body.
   - Grid targets: the block keeps its relative cells and is offset to the first row below the used rows, at column 0.
   - Pack targets: inserted in order.
   - Page containers: each top-level pasted widget becomes a page with its id as the page text.
   - A layout type that differs from the fragment's → the reading order is kept (as `change_layout` does).
6. **Execute.** `Macro(N_("Paste"), [SetVariable…, SetResource…, InsertNode…])`, one undo step. The pasted nodes become the selection, and the message `ngettext("Pasted {count} element.", "Pasted {count} elements.", n)` comes after the selection (C1). A guard refusal (paste into a non-container, a collision) → its reason, and nothing changes.
- **Cut** = Copy, then the Delete macro (`N_("Cut")`). **Duplicate** (Ctrl+D) = the same round-trip in memory, inserted after the original, without touching the system clipboard.
- **Same-file includes.** A pasted `<include src="#">` whose component does not exist in the target → a refused paste with `_("'{id}' includes a component of its original file; paste that component first.")`.
  - This check stays in `_remap`, because its wording is clearer than R51's.
  - **Amended 2026-10-09:** the guard itself now refuses a non-component target (R51) and a cycle (R52), as it does for every other edit path (ADR-006 amendment). `clipboard._include_problem` and its helpers are removed.
- **Scoping.** Ctrl+C/X/V/D are **scoped to the canvas and the tree** (the ADR-010 `scope`), so in an inspector `Entry` they keep their text meaning. The Edit menu items act on the selection from anywhere.

## 9. File lifecycle (`files.py` pure, `app.py` wiring)
### 9.1 Actions (File menu)
| Action | Shortcut | Behaviour |
|---|---|---|
| _New from template… | Ctrl+N | guard (§10) → wizard (exists) |
| _Open… | Ctrl+O | `dialogs/files.ask_open` (filter `*.ui`) → guard → §9.2 |
| Open _recent ▸ | — | up to 10 entries, mnemonics `_1`…`_9`, `1_0`; a missing file → message + removal from the list; "_Clear list" |
| _Save | Ctrl+S | untitled or a read-only path → Save As; else §9.3 |
| Save _as… | Ctrl+Shift+S | `ask_save` (default extension `.ui`) → rebase (§9.4) → §9.3 |
| _Close | Ctrl+W | guard → `close_document()` (empty state) |
| _Quit | Ctrl+Q | guard → quit (exists) |

### 9.2 Open
1. **Refuse unsafe paths.** `is_network_or_device_path(path)` (R82) → `_("Network and device paths cannot be opened.")`, and nothing is read.
2. **Read.** `read_ui(path)`. An `XmlIoError` (corrupt, oversized, newer MAJOR, not a file) → `dialogs/message` with the translated reason. The current document stays.
3. **Set the read-only reason** (D11):
   - `result.read_only` (newer MINOR) → fully read-only (the stack refuses every edit; the writer refuses Save and Save As);
   - the file or its directory is not writable (`os.access(W_OK)` on both, plus the Windows read-only attribute) → `read_only_reason = _("the file is write-protected")`. Editing is allowed, and Save becomes Save As.
   - a restored recovery snapshot whose original no longer exists → `read_only_reason = _("the file no longer exists")`. Nothing is locked and the title carries no `(read-only)` mark; Save becomes Save As (QA-14a1-19).
4. **Install the document.** `session.open_document(result, path=…)`, `stamp = FileStamp.of(path)`, push to the recent files, and select the first window.
5. **Report after selecting (C1).** The result's warnings (`xml.discarded_content`, unknown names) and the validation errors → `ngettext("Opened with {count} warning.", …)`; the details are in the inspector Findings section.
- **Files with validation errors** still open, so the user can repair them.
- **CLI.** `pyguibud [FILE]` passes `path` to `launch(lang, theme, *, path=None)`. The keyword-only argument keeps the test seam that injects `launch(lang, theme)` working.
  - Without a FILE, `main()` calls `launch(lang, theme)` with **no** `path=`, so the existing two-argument fakes keep working.
  - The path is opened after the window appears, through the same §9.2. A failure shows the dialog and leaves the empty state.
  - A path that does not exist → exit 2 with the usage error `_("The file '{path}' does not exist.")` before any window opens.
  - The CLI tests and Step 12 UAT item 9 (`foo.ui` → exit 2) keep exit 2 but get this new message, so their assertions need updating.

### 9.3 Save
1. `Inspector.flush()` (§3.3); a failure aborts.
2. **Validation errors** (only possible for files opened with errors) → confirm `ngettext("The document has {count} error. Save anyway?", …)` (D11).
3. **Conflict check.** If `FileStamp.of(path) != session.stamp` (the file changed on disk) → dialog `_("'{name}' was changed by another program since it was opened.")` with **Overwrite**, **Save as…** and **Cancel**.
4. **Write.** `write_ui(document, path, backup=True)` (atomic + `.bak`). On `XmlIoError` (disk full, permission, locked) → message with the OS reason. The document stays dirty, the recovery snapshot is kept, and Save as… is offered.
5. **After a success:** `stack.mark_saved()`, a new `stamp`, recent files updated, the recovery entry dropped, `name`/title updated, and the message `_("Saved '{name}'.")`.
- **Saving onto an included file.** Save As onto a file that this document includes (any alias, `os.path.samefile`) is refused, as `pyguibud-uic` does.
- **Focus-in notice.** When the root gets focus, the file is stat-checked (no read); a changed stamp shows a one-time status message `_("'{name}' was changed on disk.")` (trim item 3).

### 9.4 Path rebasing (`rebase_paths(document, old_base, new_base) -> Command | None`)
- **Which paths.** Relative image `src` and include `src` (not `#`) are resolved against `old_base` and re-expressed relative to `new_base` (forward slashes). A path that cannot be relative (another drive) stays absolute, and the validator warning tells the user.
- **Absolute paths** under `new_base` become relative.
- **When it runs.** For Save As to another directory, and for the first save of an untitled document, whose images were stored absolute by "Add image…".
- **How it runs.** A `Macro(N_("Update file paths"))` executed **before** the write, so it is undoable.
- **Recovery restore** keeps the original path as the base, never the recovery folder (§11.3).

## 10. Unsaved-changes guard
- **API.** `session.can_discard()` (synchronous) is replaced by `app.guard(then: Callable[[], None]) -> None`:
  - clean document → `then()` at once;
  - dirty document → `dialogs/save_changes` `_("Save the changes to '{name}' before closing?")` with **Save** (default), **Don't save** and **Cancel**. Save runs §9.3 (or Save As) and continues with `then` only on success. Don't save runs `then`. Cancel and Esc do nothing.
- **The snapshot is dropped only when the document is actually replaced or closed** (inside `open_document`/`close_document`), never at the Don't save click. A cancelled file picker or a failed open therefore keeps the snapshot.
- **Open and Open recent** run the file picker **first** and the guard second, so cancelling the picker never asks about saving.
- **Callers:**
  - `WM_DELETE_WINDOW`, Quit, Close, Open, Open recent, the New wizard (before it opens), and recovery restore (§11.3);
  - language and theme switches do not need it.
- **Ctrl+C in the console (SIGINT)** never opens a dialog. If the document is dirty, a recovery snapshot is written synchronously (the editor text is not flushed). Then the process exits with code 130 as today. The next start offers recovery.
- **OS logoff and crashes** are covered by autosave (§11).

## 11. Autosave and crash recovery (`recovery.py`, D5/D6)
### 11.1 Location and lock
- **Location.** `state_dir()/recovery/<session-uuid>/`:
  - Windows `%LOCALAPPDATA%\PyGUIbud`;
  - macOS `~/Library/Application Support/PyGUIbud`;
  - Linux `$XDG_STATE_HOME/pyguibud`, default `~/.local/state/pyguibud`.
  - `PYGUIBUD_STATE_DIR` overrides it (tests, portable installs). Recovery files never go next to the user's file.
- **The session folder holds:**
  - `owner.lock`, opened and held with an exclusive OS lock (`msvcrt.locking` / `fcntl.flock`) for the life of the process;
  - `document.ui`, the last snapshot;
  - `info.json` (`{"version": 1, "path": "…"|null, "name": "…", "saved_at": "ISO-8601", "pid": n}`).

  A folder whose lock **can** be taken **and** that holds a `document.ui` belongs to a dead process (an orphan). `scan_orphans` skips the process's own folder. A lockable folder without `document.ui` is removed silently, which also covers a crash between creating the folder and taking the lock. Two running instances never see each other's live sessions as orphans.

### 11.2 Snapshots
- **When.** A timer every **60 s** (D5) writes a snapshot when the stack changed since the last snapshot and the document is dirty. A snapshot is also written on SIGINT (§10).
- **How.** `dump_ui(document)` is written atomically (temp + `os.replace`), then `info.json`. A read-only document is never snapshotted.
- **Failures** (disk full, permission) → a single status message `_("Autosave failed: {reason}")` per failure streak. Editing is never blocked, and the next tick retries.
- **Clean-up.** On Windows, a folder that holds an open, locked file cannot be removed. So:
  - only `document.ui` and `info.json` are removed when the snapshot becomes obsolete (a successful save, or the document being replaced or closed);
  - the lock is released and the folder removed at process exit (a normal Quit, or SIGINT with a clean document).

### 11.3 Start-up recovery (D6 = A)
- **Scan.** At start-up, before the start-up document is opened, `scan_orphans()` lists the orphan folders. There are at most 20; anything older than 30 days is removed.
- **Prompt.** If any exist, `dialogs/recovery` lists them (name, original path, time) with the buttons **Restore**, **Discard** and **Later**:
  - **Restore** reads `document.ui` with `read_ui`. A failure (corrupt snapshot) marks the row `_("damaged")` and leaves only Discard. On success it calls `open_document(result, path=original path or None, dirty=True)` and adopts the folder into the live session. One document is restored at a time (one document per process). A second orphan stays for the next start, or for **File ▸ Recover…**, which opens the same dialog.
  - **Discard** deletes the folder after a confirmation.
  - **Later** keeps it.
- **CLI file.** With `pyguibud FILE`, the prompt comes first, and the CLI file opens only if nothing is restored.

### 11.4 Core change
`CommandStack(document, registry, *, source, limit, dirty: bool = False)`: `dirty=True` sets `saved_index = None`, so a restored document is dirty until it is saved. No other core API changes (ADR-011).

## 12. Settings store (`settings.py`, D7)
- **File.** `config_dir()/settings.json`:
  - Windows `%APPDATA%\PyGUIbud`;
  - macOS `~/Library/Application Support/PyGUIbud`;
  - Linux `$XDG_CONFIG_HOME/pyguibud`, default `~/.config/pyguibud`.
  - `PYGUIBUD_CONFIG_DIR` overrides it.
- **Schema v1** (every key optional; unknown keys are kept on write, for forks):
```json
{"version": 1, "language": "de_DE", "theme": "dark",
 "window": {"geometry": "1280x800+40+30", "zoomed": false},
 "sashes": {"main": [240, 1040], "right": [420]},
 "recent_files": ["C:/Users/me/app/main.ui"], "autosave_seconds": 60}
```
- **Tolerance:**
  - the file is read once at start (≤ 256 KiB; JSON only, never executed);
  - a missing file → defaults;
  - unreadable or invalid JSON → the file is renamed to `settings.json.corrupt` (one copy is kept), defaults are used, and the status message `_("Your settings could not be read and were reset.")` shows once;
  - a bad value → the default for **that key only** (language not in the catalogue list, theme not a role, geometry not `WxH+X+Y`, sashes not ints, recent entries not absolute existing-format paths or network paths, autosave outside 15–3600).
- **Precedence:** CLI flag > environment (`PYGUIBUD_LANG`) > settings > system locale > default. `cli.py` changes the `--theme` default to `None`, so that "not given" can be told apart.
- **Writing:** atomic. The settings are written when the language or theme changes, when recent files change, and once on Quit (geometry and sashes). Two instances: read–merge–write of `recent_files` (union, most recent first, at most 10). Otherwise the last writer wins.
- **Geometry restore:** clamped to the virtual desktop (`app.desktop_bounds()`: Windows `GetSystemMetrics` virtual screen, else `winfo_vrootwidth/height`); positions are always written as `+X+Y`. If less than 200×150 px would be visible → the default geometry. Sashes are restored after the first `<Configure>`, then pass through the existing `clamp_sashes()`. `sashes["palette_user"]` (Step 19f, D4) holds the palette width the user set by dragging sash 0, written only after a real drag; an auto-grown palette is never stored there, and a missing or bad value means none.

## 13. Tree drag-and-drop and include rendering
> Trimmed from 14a.2 (B1); **delivered by Step 14b.2**, spec `docs/specs/direct-manipulation.md` §5–§6.
### 13.1 Object-tree drag-and-drop (D8 of Step 13, remainder)
- **Drop positions.** A press-drag of more than 4 px on a row starts a drag; the payload is the tree selection. The row under the pointer gives the target:
  - the top 25 % → **before** it;
  - the bottom 25 % → **after** it;
  - the middle of a container or menu row → **into** it (append; grid → the `keyboard_target` first free cell).
- **Commands.** The targets map to the existing `editing.move_command`/`reparent` builders. Feedback comes from `check()` on target change (the Step 13 rules: debounce, cache). The target row gets the tag `drop-target` (theme colours) or `drop-denied`, and the reason goes to the status bar.
- **Ending a drag.** Esc or a release outside the tree cancels. A drop executes, posts `""` or the reason (C2), and keeps the moved nodes selected.
- **Menu rows** reorder and reparent within menubars and menus with the same mechanism.

### 13.2 External `<include>` rendering
- **Expansion.** The runtime's `_expand` (`_load.py:226`) is **not** reused. It depends on the runtime's `UiScope` and on `backends.base.Instance`, so moving it into `core` would make `core` import upward. It also assumes an already validated tree (`next()` on the component).
  - `render_plan` instead gains a designer-side resolver of about 40 lines that mirrors it. It uses `core.files.DiskFiles(root=session.path)` `resolve`/`read`, and its own `RecordingScope` per included document.
  - The resolver first runs the include rules (`validate(..., files=DiskFiles)`, R49–R53), and any finding → placeholder.
  - A parity test compares an included component's widget description with `load_ui` on an example that has an external include.
- **Display.** An include is drawn **read-only**: its widgets have no node mapping (the whole include selects as one node), a dashed outline is drawn, and the caption is `"Included: {component}"` (exists).
- **Fallbacks.**
  - Untitled document, missing file, cycle or limits (R49–R53) → today's placeholder with the reason.
  - `src="#"` renders from the open document.
- **Caching.** By `(realpath, mtime_ns, size)`; the cache is cleared on file focus-in.

## 14. Idiot-proofing (abuse cases → required behaviour)
| # | Abuse | Required behaviour (test) |
|---|---|---|
| A1 | Save to a read-only file or folder | Detected at open (D11) → Save becomes Save As; a forced write error → message, still dirty, snapshot kept |
| A2 | Disk full during save / autosave | `write_ui` keeps the original + `.bak`; message; autosave retries silently after one message |
| A3 | File changed on disk by another program | Overwrite/Save as/Cancel at save (§9.3); notice on focus-in |
| A4 | Huge paste (100 MiB text, 50k widgets) | Refused before parsing (> 10 MiB) or after reading (> 2,000 widgets); UI responsive |
| A5 | Paste into a non-container, a grid collision, a menu | Guard reason; document unchanged (I1) |
| A6 | Paste of foreign text, XML bombs, DTDs | Hardened reader refuses; "no PyGUIbud elements" |
| A7 | Corrupt / truncated autosave | Row marked damaged; only Discard; designer starts normally |
| A8 | Two instances, same file | Each has its own recovery folder and lock; conflict check at save (A3); recent-files merge |
| A9 | Corrupt `settings.json` (garbage, 10 MB, wrong types, `null`) | Size cap; renamed `.corrupt`; per-key defaults; one message |
| A10 | Window geometry off-screen (monitor removed) | Clamped / default (§12) |
| A11 | Open a UNC/device path, a directory, a 0-byte or a 200 MB file | R82 refuse / `xml.not_a_file` / reader errors; current document kept |
| A12 | Rename a variable to an existing id, a keyword, `vars` | Guard reason (R01/R04/R69); macro all-or-nothing |
| A13 | Delete the last window; delete a component still included | Refused with reason (§7) |
| A14 | Type `999999999999` / `abc` / `1e400` in an int/float field | Local reason at once; nothing executed |
| A15 | Close / Quit / Open / New while an editor has invalid pending text | Flush fails → the action is aborted and the reason shown |
| A16 | Ctrl+C in the console while dirty | Snapshot written; exit 130; recovery offered next start |
| A17 | Hold Ctrl+X / Ctrl+V / Ctrl+D | Once per physical press (`_ONCE_PER_PRESS` gains `edit.cut`, `edit.paste`, `edit.duplicate`): a held Ctrl+X must not cut the parent that the cut selects, up to the window |
| A18 | Save As onto a file the document includes, or onto the `.bak` | Refused (`samefile`) / allowed only as a normal target |
| A19 | Recent file now missing or on a network path | Message, removed from the list; network paths are never stored |
| A20 | Edit a newer-MINOR (read-only) document | All editors disabled; every command refused (`command.read_only`); Save/Save As refused with reason |
| A21 | Break a same-file include from the inspector. Examples: change an included component's **Kind** to dialog; set an include's **Component** to `main`, `ghost` or its own window; create a cycle. | Refused by the guard with the validator's reason (R51/R52). Nothing changes. **Id** of an included component → `rename_window`, so its same-file includes follow (same as Document ▸ Rename, with `M_EXTERNAL_INCLUDES` shown). (Added 2026-10-09, QA-14a2-10) |

## 15. i18n strings (en-GB msgids; `_()`/`N_()`/`ngettext`; named placeholders)
| Area | Msgids (new) |
|---|---|
| File menu | `_Open…`, `Open _recent`, `_Clear list`, `_Save`, `Save _as…`, `_Close`, `_Recover…`, `Saved '{name}'.`, `Opened with {count} warning.`/`…warnings.`, `The file '{path}' does not exist.`, `Network and device paths cannot be opened.`, `'{name}' was changed by another program since it was opened.`, `'{name}' was changed on disk.`, `Overwrite`, `The document has {count} error. Save anyway?`/plural, `(read-only)`, `This document is read-only: {reason}`, `the file is write-protected`, `No document. Press Ctrl+N for a new one or Ctrl+O to open a file.`, `PyGUIbud UI files`, `All files` |
| Guard | `Save the changes to '{name}' before closing?`, `Save`, `Don't save`, `Cancel` |
| Recovery | `Recover unsaved work`, `Restore`, `Discard`, `Later`, `damaged`, `Autosave failed: {reason}`, `Discard the recovered copy of '{name}'?` |
| Settings | `Your settings could not be read and were reset.` |
| Inspector | `Layout`, `Window`, `Action`, `Events`, `Reset to default`, `(mixed)`, `{count} elements selected; editing shared properties.`, `Set '{name}' on {count} element`/plural, `Translatable`, `Context`, `Comment`, `Edit text…`, `Add image…`, `New variable…`, `(none)`, `Choose…`, `Column weight`, `Row weight`, `Column minimum size`, `Row minimum size`, `Select one widget to edit its events.`, `Add key event…`, `Remove`, `Not a whole number.`, `Not a number.`, `Must be between {minimum} and {maximum}.`, `Not a colour such as #1C3FF0.`, sticky letters `N`, `E`, `S`, `W` (with translator comments) |
| Variables | `Variables`, `Used by`, `Add`, `Rename…`, `Delete`, `Bind to selection`, `Rename variable`, `Remove and unbind variable`, `'{id}' is bound to {count} widget. Unbind it and delete it?`/plural |
| Menu / windows | `_Insert`, `_Menu bar`, `M_enu`, `_Action`, `_Separator`, `Status _bar`, `_Document`, `Add _main window`, `Add _dialog`, `Add _component`, `_Rename window…`, `_Delete window`, `Next window`, `Previous window`, `A document needs at least one window.`, `'{id}' is still included by '{user}'.`, `Files that include this component from outside were not updated.`, `Menus and actions cannot be copied yet.` |
| Clipboard | `Cu_t`, `_Copy`, `_Paste`, `D_uplicate`, `Paste`, `Cut`, `Update file paths`, `Pasted {count} element.`/plural, `The clipboard holds no PyGUIbud elements.`, `The clipboard content is too large to paste.`, `The clipboard content is not valid: {reason}`, `'{id}' includes a component of its original file; paste that component first.`, `Paste refused: more than {limit} widgets.` |

- **Rules:** every mnemonic is unique per menu (also in `en_XA`); no concatenation; 40 % slack; translator comments on every placeholder; catalogue sync per half; translations in Step 18 (D6 of Step 12 still in force).

## 16. Keyboard access
| Chord | Action | Scope |
|---|---|---|
| Ctrl+O, Ctrl+S, Ctrl+Shift+S, Ctrl+W | Open, Save, Save As, Close | global |
| Ctrl+C, Ctrl+X, Ctrl+V, Ctrl+D | Copy, Cut, Paste, Duplicate | canvas, tree |
| Ctrl+PageUp/PageDown | previous/next window tab | global |
| F2 | rename (window in canvas, variable in variables panel) | canvas, variables |
| Insert, Delete | add/delete variable | variables |
| Enter / Esc in an editor | commit / revert | inspector |
| Alt+Up/Down | reorder (now also menus) | tree |

- **F6 order:** palette → canvas → tree/variables notebook → inspector notebook. Ctrl+Tab switches the tab inside the focused notebook. It uses scoped bindings on the two notebooks, **not** `ttk.Notebook.enable_traversal()`, which binds Ctrl+Tab and Alt mnemonics on the toplevel and would clash with the menubar (Step 13 R2).
- **The cheat-sheet** (F1) lists every new action from the registry.
- **Dialogs:** Enter = default, Esc = cancel, and Alt mnemonics on buttons. Every button of every dialog has a unique access key (`ModalDialog.access_keys`, also in `en_XA`). The `…` text dialog judges its text with the guard's own dry run (`CommandStack.check`) before it closes; a refusal keeps it open with the typed text and shows the reason (QA-14a1-20). Enter in an untouched editor, a `(mixed)` one above all, commits nothing: only typed text commits (QA-14a1-18).

## 17. Test plan and performance budget
**Pure tests (no Tk):**
- **`properties`:**
  - `field_rows` for every core spec × single/multi (hypothesis: random selections of 1–5 widgets; shared fields = the intersection);
  - `parse_value` grammar edges (A14);
  - `commit_commands` → executed on a template, round-trips through `dump_ui`/`read_ui`, and undo restores identical bytes.
- **`editing` macros:**
  - `rename_variable`/`remove_and_unbind`/`rename_window`/`new_window`, all-or-nothing on refusal (I1);
  - hypothesis: random documents, rename then undo → identical `dump_ui`.
- **`clipboard`:**
  - copy → paste into the same and another document; id remap (hypothesis over clashing ids);
  - variable reuse versus rename; rebasing; A4–A6;
  - `src="#"` refusal; the windows mode.
- **`files`:**
  - `FileStamp`; `rebase_paths` (relative, other drive, absolute under base; property test on random trees);
  - recent-list merge/dedupe (`normcase(realpath)`).
- **`recovery`:**
  - lock semantics with two `RecoverySession`s in one process plus one in a subprocess (the orphan is detected after the subprocess exits);
  - a corrupt snapshot (A7); the 20/30-day caps.
- **`settings`:** A9 fuzz (hypothesis on JSON values); per-key fallback; unknown keys preserved; precedence matrix.
- **Core:** `CommandStack(dirty=True)`.
- **Include resolver:** cycles, missing files and limits → placeholder; embed versus `load_ui` parity for an external include.
- **`PURE_MODULES`** gains the five new modules.

**Tk tests (`@pytest.mark.gui`, shared root):**
- **Editors:** every editor kind commits, refuses (danger style + message), resets, and Esc reverts. Spinbox arrows → one undo step. Flush before Save. Ctrl+Z local versus stack (§3.3).
- **Panels:** multi-edit Macro; the events tab `SetEvents`; variables panel add/rename/delete-with-unbind.
- **Menus and windows:** insert menu/action/separator/submenu; window add/rename/delete and Ctrl+PageDown.
- **Clipboard and tree:** Ctrl+C in an inspector `Entry` does **not** copy widgets; tree DnD before/after/into + denied.
- **Files:** the full UAT loop with `dialogs/files` faked (open → edit → save → close → reopen → `dump_ui` identical); guard paths (Save/Don't save/Cancel × quit/open/new/close); a read-only path → Save As; the conflict dialog.
- **Recovery:** a SIGINT subprocess test leaves a snapshot, and the next start lists it.
- **Settings:** geometry and sash restore and clamping.
- **Rules C1/C2:** after open, the warning message is still visible; after an inspector commit, an older refusal is cleared.

**Budgets:**
| Operation | Budget |
|---|---|
| inspector form rebuild (selection change, 40 fields) | ≤ 60 ms |
| value refresh after a stack event | ≤ 20 ms |
| multi-edit commit on 50 widgets | ≤ 150 ms (one guard run) |
| paste of 500 widgets | ≤ 1.5 s |
| autosave snapshot (2,000 widgets) | ≤ 150 ms, on the Tk thread, so it never runs during a drag |
| settings load/save | ≤ 10 ms |
| added designer Tk tests | ≤ 8 s |

## 18. Risks
| # | Risk | Mitigation |
|---|---|---|
| R1 | Editors re-entering the stack from a listener (`_Busy`) | Listeners only schedule `after_idle` refreshes; commits come from user events only |
| R2 | Lost edit: pending editor text not committed before save/quit | `flush()` is mandatory in Save/guard/Copy/undo; a test for each caller |
| R3 | Clipboard shortcuts stealing text-entry copy/paste | Scoped chords (§8.2); a Tk test |
| R4 | X11 clipboard is emptied when the owning process exits | Documented; the cross-process paste works while the source runs (the Tk limitation) |
| R5 | OS lock semantics differ (Windows `msvcrt` byte-range vs POSIX `flock`; NFS homes) | Lock + pid in `info.json`; a lock error → treat the folder as live (never delete); test on Windows + Linux CI |
| R6 | Path rebasing surprises the user | Undoable macro with a clear label; validator warnings remain; trim item 4 |
| R7 | Native file/colour dialogs block the Tk heartbeat (Ctrl+C delayed) | Accepted; noted in UAT; dialogs routed via `dialogs/files.py` (fakeable) |
| R8 | Inspector rebuild cost on large multi-selections | Rebuild only on a selection change; intersection computed once per class |
| R9 | The designer's include resolver drifts from the runtime's `_expand` | Mirror its logic; a parity test on an external-include example; runtime untouched (ADR-007 boundary) |
| R10 | Budget overshoot (Steps 13a/13b both overshot) | Per-area allocation (§0), the trim order, halves with separate UATs |
| R11 | Font missing from M3 | D8 makes the scope change explicit for the user |

## 19. UAT (for the user)
**14a.1:**
1. Select a Label: change its text and width in the inspector; change a placement field (e.g. sticky) and a Canvas `background` colour; Reset restores the default; Ctrl+Z/Ctrl+Y undo and redo each edit.
2. Select three Buttons: change `width` once, then undo it in one step. Mixed values show "(mixed)".
3. Events tab: set `command` → `on_ok`. Variables tab: add `user_name`, bind an Entry, rename the variable (the binding follows), delete it (confirm → unbound).
4. Ctrl+S → Save As → `C:\temp\uat.ui`; close (Ctrl+W); reopen via **Open recent**: identical (compare in a text editor).
5. Edit, then quit with Ctrl+Q → Save / Don't save / Cancel each behave as labelled.
6. Edit, wait 60 s, kill the process (Task Manager) → restart → Restore brings the edit back (title shows `*`).
7. Change the language, theme, sashes and window size → restart → all restored. Corrupt `settings.json` by hand → the designer starts with defaults and says so.
8. Everything again with `--lang en_XA`: no truncated labels.

**14a.2:**
_B1 = (b), 2026-10-08: §13 trimmed — items 4 and 5 below are withdrawn; reordering uses Alt+Up/Down._
1. Insert a menu bar, a File menu with Open/Quit actions, a separator and a submenu; set a shortcut and a handler; reorder with Alt+Up/Down.
2. Add a dialog and a component; rename them; Ctrl+PageDown switches tabs; deleting the last window is refused.
3. Copy two widgets, paste them into another Frame and into a second designer instance; the ids are renamed on a clash; Ctrl+D duplicates.
4. ~~Drag rows in the object tree to reorder and reparent; an invalid drop shows the reason.~~ (trimmed, B1)
5. ~~A file with an external `<include>` shows the component's widgets on the canvas.~~ (trimmed, B1)

## 20. Decisions (recommended default in bold) — **all defaults accepted by the user, 2026-10-08**
- **D1 — Split Step 14a?**
  - A: one session, one UAT. This is too large for one context window.
  - **B (recommended): two halves, 14a.1 "Files and properties" and 14a.2 "Structure", each with a UAT, under one plan row.** The file safety net (save, recovery) is approved before the structural edits land.
  - C: two plan rows (14a/14b).
- **D2 — Budget.**
  - **A (recommended): ≤ 3,600 lines with the §0 per-area allocation and trim order.**
  - B: ≤ 3,200 (apply trim items 1–3 up front).
  - C: no cap.
- **D3 — Clipboard format.**
  - **A (recommended): a complete `.ui` text with a foreign-namespace marker (§8.1) on the system clipboard.** It reuses the hardened reader and validator, works across processes and files, and can be read by humans.
  - B: a bare `<widget>` fragment. That needs a second parser path.
  - C: a private in-process clipboard. That fails M11 "between `.ui` files" across instances.
- **D4 — Id clashes on paste.**
  - **A (recommended): rename with a numeric suffix, remap internal references, and reuse a variable or image when the id and type/path match.**
  - B: refuse the paste.
  - C: always fresh ids.
- **D5 — Autosave interval and location.**
  - **A (recommended): every 60 s while dirty, in the per-OS state dir (§11.1), never next to the user's file.**
  - B: a `.~name.ui` file next to the file (pollutes repos, fails on read-only folders).
  - C: 5 minutes.
- **D6 — Recovery UX.**
  - **A (recommended): a start-up dialog with Restore / Discard / Later, plus File ▸ Recover….**
  - B: silent auto-restore.
  - C: only File ▸ Recover….
- **D7 — Settings location and format.**
  - **A (recommended): JSON in the per-OS config dir computed with the stdlib, with a `PYGUIBUD_CONFIG_DIR` override.** No new dependency.
  - B: add `platformdirs`.
  - C: INI via `configparser`.
- **D8 — Property editors in v1 (scope).**
  - **A (recommended): the §3.2 table (string with translatable/context/comment, int, float, bool, enum, colour + chooser, image, variable, handler/shortcut, layout, placement, window); font deferred after v1.** No `font` PropertyType exists, and adding one touches the schema, validator, runtime, codegen and 3 backends. **This is a scope change to FEATURES M3 and needs the user's approval.**
  - B: add `font` now (a new PropertyType, a minor schema bump, about +400 lines across core, runtime and codegen).
  - C: a minimal set (text/int/bool/enum) now, the rest in 14p.
- **D9 — Menu editor depth.**
  - **A (recommended): in place (tree + inspector + Edit ▸ Insert), with submenus, separators, shortcuts, handlers, icons, reorder by Alt+arrows and drag-and-drop.**
  - B: a dedicated menu-editor dialog (+≈300 lines, a second editing surface).
  - C: flat menus only.
- **D10 — Where the new panels live.**
  - **A (recommended): Events as a tab of the inspector; Variables as a tab beside the object tree.** No new F6 stops; 14p can restyle them.
  - B: separate panes in the right PanedWindow (more sashes and F6 stops).
  - C: modal dialogs.
- **D11 — Read-only paths and saving invalid files.**
  - **A (recommended): a write-protected file stays editable, and Save becomes Save As. Saving a document that has validation errors is allowed after a confirmation; newer-MINOR files stay fully read-only.**
  - B: block editing of write-protected files.
  - C: refuse to save invalid documents (users could lose work-in-progress on files they opened broken).
- **D12 — Several instances and the same file.**
  - **A (recommended): each `pyguibud FILE` is its own process; per-session recovery locks; conflict check at save (§9.3).**
  - B: single-instance IPC that forwards files to the running designer (sockets, platform risk, about +300 lines).
  - C: no detection.
