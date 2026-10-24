"""Dump, fill and check PyGUIbud ``.po`` catalogues through JSON (dev tool).

Usage::

    uv run python tools/po_roundtrip.py dump <locale> <out.json> [--all]
    uv run python tools/po_roundtrip.py load <locale> <in.json>
    uv run python tools/po_roundtrip.py check <locale>

``dump`` lists untranslated or fuzzy entries (every entry with ``--all``). ``load`` writes the
translations back with the same options as ``pybabel update`` (width 76), so a later update
produces no diff. Placeholders (``{name}``, ``%(name)s``) and the mnemonic underscore must match
the source; otherwise nothing is written and the exit status is 1.
"""

from __future__ import annotations

import argparse
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

from babel.messages.catalog import Catalog, Message
from babel.messages.pofile import read_po, write_po

from pyguibud.core.keys import split_mnemonic

ROOT = Path(__file__).resolve().parents[1]
LOCALE_DIR = ROOT / "runtime" / "src" / "pyguibud" / "locale"  # owned by pyguibud-runtime
DOMAIN = "pyguibud"
WIDTH = 76
SEP = "\x04"

_BRACE = re.compile(r"\{([A-Za-z_]\w*)[^{}]*\}")
_PERCENT = re.compile(r"%\((\w+)\)")


def po_path(locale: str) -> Path:
    """Return the catalogue path of ``locale``."""
    return LOCALE_DIR / locale / "LC_MESSAGES" / f"{DOMAIN}.po"


def read_catalogue(locale: str) -> Catalog:
    """Read the catalogue of ``locale`` the way ``pybabel update`` does."""
    with po_path(locale).open("rb") as handle:
        return read_po(handle, locale=locale, domain=DOMAIN)


def write_catalogue(locale: str, catalogue: Catalog) -> None:
    """Write ``catalogue`` with the options ``pybabel update`` uses."""
    buffer = io.BytesIO()
    write_po(buffer, catalogue, width=WIDTH)
    po_path(locale).write_bytes(buffer.getvalue())


def forms(value: str | tuple[str, ...] | list[str] | None) -> list[str]:
    """Return the message id or string as a list of forms."""
    if value is None:
        return [""]
    return [value] if isinstance(value, str) else list(value)


def key_of(message: Message) -> str:
    """Return the stable key ``msgctxt + \\x04 + msgid``."""
    return f"{message.context or ''}{SEP}{forms(message.id)[0]}"


def placeholders(text: str) -> frozenset[str]:
    """Return the ``{name}`` and ``%(name)s`` placeholder names of ``text``."""
    plain = text.replace("{{", "").replace("}}", "")
    return frozenset(_BRACE.findall(plain)) | frozenset(_PERCENT.findall(plain))


def has_mnemonic(text: str) -> bool:
    """Return whether ``text`` marks an access key (placeholders ignored)."""
    stripped = _BRACE.sub("", text.replace("{{", "").replace("}}", ""))
    return split_mnemonic(stripped)[1] >= 0


def is_pending(message: Message) -> bool:
    """Return whether ``message`` is untranslated (any empty form) or fuzzy."""
    return message.fuzzy or any(not form for form in forms(message.string))


def problems_of(message: Message, strings: list[str]) -> list[str]:
    """Return placeholder and mnemonic problems of ``strings`` against the source."""
    ids = forms(message.id)
    found: list[str] = []
    for index, text in enumerate(strings):
        if not text:
            continue
        if len(ids) == 1:
            wanted = {placeholders(ids[0])}
        else:
            full = placeholders(ids[1])
            wanted = {full}
            if index == 0 and "count" not in placeholders(ids[0]):
                wanted.add(full - {"count"})
        if placeholders(text) not in wanted:
            expected = " or ".join(str(sorted(w)) for w in wanted)
            found.append(
                f"placeholders {sorted(placeholders(text))} differ from {expected} (form {index})"
            )
        if has_mnemonic(ids[0]) and not has_mnemonic(text):
            found.append(f"mnemonic underscore missing (form {index})")
    return found


def entries(catalogue: Catalog) -> list[Message]:
    """Return the real messages (without the header)."""
    return [message for message in catalogue if message.id]


def dump(locale: str, out: Path, everything: bool) -> int:
    """Write the pending (or all) entries of ``locale`` to ``out`` as JSON."""
    catalogue = read_catalogue(locale)
    nplurals = catalogue.num_plurals
    rows: list[dict[str, Any]] = []
    for message in entries(catalogue):
        if not everything and not is_pending(message):
            continue
        ids = forms(message.id)
        plural = len(ids) > 1
        rows.append(
            {
                "key": key_of(message),
                "msgctxt": message.context,
                "msgid": ids[0],
                "msgid_plural": ids[1] if plural else None,
                "auto_comments": list(message.auto_comments),
                "locations": [f"{path}:{line}" for path, line in message.locations[:2]],
                "msgstr": forms(message.string) if plural else message.string or "",
                "nplurals": nplurals,
            }
        )
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(rows)} entries to {out}")
    return 0


def load(locale: str, source: Path) -> int:
    """Apply the translations of ``source`` to the catalogue of ``locale``."""
    catalogue = read_catalogue(locale)
    nplurals = catalogue.num_plurals
    by_key = {key_of(message): message for message in entries(catalogue)}
    rows = json.loads(source.read_text(encoding="utf-8"))
    errors: list[str] = []
    updates: list[tuple[Message, str | tuple[str, ...]]] = []
    for row in rows:
        key = row["key"]
        message = by_key.get(key)
        if message is None:
            errors.append(f"unknown key {key!r}")
            continue
        value = row["msgstr"]
        is_plural = len(forms(message.id)) > 1
        strings = forms(value) if isinstance(value, (list, tuple)) else [value]
        if all(not text for text in strings):
            continue
        if is_plural:
            if len(strings) != nplurals or not all(strings):
                errors.append(f"{key!r}: needs exactly {nplurals} non-empty plural forms")
                continue
        elif len(strings) != 1:
            errors.append(f"{key!r}: expected a single string")
            continue
        errors.extend(f"{key!r}: {problem}" for problem in problems_of(message, strings))
        updates.append((message, tuple(strings) if is_plural else strings[0]))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        print(f"refused: {len(errors)} problem(s); nothing written", file=sys.stderr)
        return 1
    for message, string in updates:
        message.string = string
        message.flags.discard("fuzzy")
    write_catalogue(locale, catalogue)
    print(f"applied {len(updates)} translation(s) to {po_path(locale)}")
    return 0


def check(locale: str) -> int:
    """Print statistics and problems of ``locale``; return 1 if anything is wrong."""
    messages = entries(read_catalogue(locale))
    untranslated = [m for m in messages if any(not f for f in forms(m.string))]
    fuzzy = [m for m in messages if m.fuzzy]
    found = [
        f"{key_of(m)!r}: {problem}"
        for m in messages
        if (strings := forms(m.string)) and any(strings)
        for problem in problems_of(m, strings)
    ]
    print(
        f"{locale}: total {len(messages)}, untranslated {len(untranslated)}, "
        f"fuzzy {len(fuzzy)}, problems {len(found)}"
    )
    for line in found:
        print(f"  {line}")
    return 1 if (found or untranslated or fuzzy) else 0


def main(argv: list[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p_dump = sub.add_parser("dump", help="write pending entries as JSON")
    p_dump.add_argument("locale")
    p_dump.add_argument("out", type=Path)
    p_dump.add_argument("--all", action="store_true", help="include translated entries")
    p_load = sub.add_parser("load", help="apply translations from JSON")
    p_load.add_argument("locale")
    p_load.add_argument("source", type=Path)
    p_check = sub.add_parser("check", help="report statistics and problems")
    p_check.add_argument("locale")
    args = parser.parse_args(argv)
    if args.command == "dump":
        return dump(args.locale, args.out, args.all)
    if args.command == "load":
        return load(args.locale, args.source)
    return check(args.locale)


if __name__ == "__main__":
    sys.exit(main())
