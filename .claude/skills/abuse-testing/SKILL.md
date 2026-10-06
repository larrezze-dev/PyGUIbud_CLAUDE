---
name: abuse-testing
description: PyGUIbud "idiot-proof" QA checklist - abuse scenarios for files, editing, plugins, locales and accessibility that must be blocked gracefully. Use for QA passes, hardening and writing the user's break-it checklist.
---

# Abuse testing ("idiot-proof")

Goal: every stupid or malicious action is **blocked with a clear translated reason**, the app never crashes, and user data is never lost. The UI does not need to explain everything; it only needs to refuse harm.

## Files (M24)
- Open: empty file, binary file, a 2 GB file, truncated XML, a billion-laughs/entity bomb, external DTD, wrong root, newer MAJOR/MINOR schema, wrong encoding, path with non-ASCII or emoji, a UNC/network path, a file deleted while open.
- Save: read-only file/folder, disk full (simulate), file locked by another process, overwrite a non-`.ui` file, save while the file is changed externally. Verify the atomic write and the `.bak`.
- Kill the process mid-edit → restart → crash recovery offers the autosave.
- Close with unsaved changes (window X, Alt+F4, menu quit, OS logout signal where possible).

## Editing (M23)
- Drop into a non-container; drop a window into itself; reparent a container into its own descendant (cycle).
- Ids: duplicate, `class`, `None`, `_private`, `1abc`, `a-b`, 10 000 characters, Unicode lookalikes.
- Grid collisions, negative/huge row/span/padding, mixed grid+pack, two main windows, cyclic `<include>`.
- Handler/variable names that are not identifiers; binding an int var to a text entry; deleting a variable that is still bound.
- Undo/redo storms (1 000 rapid Ctrl+Z/Ctrl+Y), paste of garbage XML or huge text from the clipboard, multi-select delete + undo.
- Rapid double-clicks on every button; resizing the window to 1×1 px and to 8K.

## Plugins (M25)
A plugin that raises on import, on render or in a property setter; one that hangs; incompatible `api_version`; a missing plugin referenced by a `.ui`. Expected: placeholder + diagnostics, and the designer keeps running.

## Locales and accessibility
Every one of the 8 locales + `en_XA`: no truncated labels, no untranslated strings, mnemonics unique per menu. Keyboard-only walk-through of the main flows. High-contrast theme meets `assets/brand/docs/ACCESSIBILITY.md`.

## Report format
Table: `# | scenario | expected | actual | severity (blocker/major/minor) | repro steps`. Blockers go to the debugger. Also produce a short human checklist the user can run for UAT.
