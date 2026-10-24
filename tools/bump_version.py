"""Set the PyGUIbud version everywhere it is written (dev tool, spec packaging D6).

Usage::

    uv run python tools/bump_version.py 0.1.0rc2 [--no-lock]

Rewrites the single literal in ``runtime/src/pyguibud/__about__.py`` and the two exact
``pyguibud-runtime`` pins of the root ``pyproject.toml``, regenerates ``examples/hello_ui.py``
(its header names the version; the codegen goldens are version-normalised) and runs
``uv lock``. ``tests/test_version_sync.py`` fails when any of these disagree.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABOUT = ROOT / "runtime" / "src" / "pyguibud" / "__about__.py"
PYPROJECT = ROOT / "pyproject.toml"
HELLO = ROOT / "examples" / "hello.ui"

#: Public PEP 440 versions only (no local part, no epoch): what TestPyPI/PyPI accept from us.
VERSION = re.compile(r"\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?(?:\.post\d+)?(?:\.dev\d+)?")
_LITERAL = re.compile(r'^(__version__ = ")[^"]*(")$', re.MULTILINE)
_PIN = re.compile(r'("pyguibud-runtime(?:\[pyside\])?==)[^"]*(")')


def _rewrite(path: Path, pattern: re.Pattern[str], version: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    new, count = pattern.subn(lambda m: f"{m.group(1)}{version}{m.group(2)}", text)
    if count != expected:
        raise SystemExit(f"{path}: expected {expected} version site(s), found {count}")
    path.write_bytes(new.encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version", help="the new version, e.g. 0.1.0rc2")
    parser.add_argument("--no-lock", action="store_true", help="skip `uv lock`")
    args = parser.parse_args(argv)
    if not VERSION.fullmatch(args.version):
        parser.error(f"not a public PEP 440 version: {args.version!r}")
    _rewrite(ABOUT, _LITERAL, args.version, 1)
    _rewrite(PYPROJECT, _PIN, args.version, 2)
    # A fresh interpreter, so the generator reads the new literal (editable install).
    code = "from pyguibud.uic import main; raise SystemExit(main([__import__('sys').argv[1]]))"
    subprocess.run([sys.executable, "-c", code, str(HELLO)], check=True, cwd=ROOT)
    if not args.no_lock:
        subprocess.run(["uv", "lock"], check=True, cwd=ROOT)
    print(f"version set to {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
