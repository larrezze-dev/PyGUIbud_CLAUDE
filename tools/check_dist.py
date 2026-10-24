"""Check the built PyGUIbud distributions before an upload (spec packaging §4 20b, ADR-016).

Usage::

    uv build --all-packages && uv run python tools/check_dist.py dist

``dist`` must hold exactly the two wheels and the two sdists of one version. The script checks the
wheel trees against the two source roots (no file in both wheels, no namespace ``__init__.py``,
no designer code in the runtime), the shipped catalogues, schema and ``py.typed`` markers, the
licence files, the README in the metadata, the exact runtime pin and where the entry points live.
Prints "OK" and exits 0, or lists every problem and exits 1. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from email.message import Message
from email.parser import Parser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
#: Source root of each distribution (ADR-016) and the top-level entries of its wheel.
SOURCES = {"pyguibud": ROOT / "src", "pyguibud_runtime": ROOT / "runtime" / "src"}
TOP_LEVEL = {
    "pyguibud": {"pyguibud"},
    "pyguibud_runtime": {"pyguibud", "pyguibud_runtime"},
}
DESIGNER_ONLY = re.compile(r"^pyguibud/(designer|codegen|preview|cli\.py|uic\.py|__main__\.py)")
TYPED = {
    "pyguibud": ["codegen", "designer", "preview"],
    "pyguibud_runtime": ["core", "backends"],
}
LOCALES = ("de_DE", "en_GB", "es_ES", "fr_FR", "it_IT", "nl_NL", "pt_BR", "pt_PT")
SCHEMA = "pyguibud/core/schema/pyguibud-ui-1.0.xsd"
CREDIT = "Created by Luciano Arrezze and programmed with the support of Claude Code."
PLUGIN_GROUPS = ("pyguibud.widgets", "pyguibud.backends")


def _version() -> str:
    text = (SOURCES["pyguibud_runtime"] / "pyguibud" / "__about__.py").read_text(encoding="utf-8")
    found = re.search(r'^__version__ = "([^"]+)"$', text, re.MULTILINE)
    if found is None:
        raise SystemExit("no __version__ literal in runtime/src/pyguibud/__about__.py")
    return found.group(1)


def _source_files(name: str) -> set[str]:
    """The files the wheel should hold: the source tree minus caches and the .po/.pot sources."""
    root = SOURCES[name]
    return {
        path.relative_to(root).as_posix()
        for top in TOP_LEVEL[name]
        for path in (root / top).rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".po", ".pot", ".pyc"}
    }


def _sections(text: str) -> dict[str, set[str]]:
    """Group name -> entry names of an ``entry_points.txt``."""
    groups: dict[str, set[str]] = {}
    current: set[str] | None = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            current = groups.setdefault(line[1:-1], set())
        elif "=" in line and current is not None:
            current.add(line.split("=", 1)[0].strip())
    return groups


def check_wheel(name: str, wheel: Path, version: str, problems: list[str]) -> set[str]:
    """Check one wheel; returns its package files (without the .dist-info folder)."""
    with zipfile.ZipFile(wheel) as archive:
        names = [n for n in archive.namelist() if not n.endswith("/")]
        info = f"{name}-{version}.dist-info/"
        metadata: Message = Parser().parsestr(archive.read(info + "METADATA").decode("utf-8"))
        entry_points = (
            _sections(archive.read(info + "entry_points.txt").decode("utf-8"))
            if info + "entry_points.txt" in names
            else {}
        )
    files = {n for n in names if not n.startswith(info)}
    label = wheel.name

    tops = {n.split("/", 1)[0] for n in files}
    if tops != TOP_LEVEL[name]:
        problems.append(
            f"{label}: top-level entries {sorted(tops)}, expected {sorted(TOP_LEVEL[name])}"
        )
    for forbidden in ("pyguibud/__init__.py", "pyguibud/py.typed"):
        if forbidden in files:
            problems.append(f"{label}: ships {forbidden} (pyguibud is a PEP 420 namespace)")
    missing = _source_files(name) - files
    extra = files - _source_files(name)
    if missing:
        problems.append(
            f"{label}: missing {len(missing)} source file(s), e.g. {sorted(missing)[:3]}"
        )
    if extra:
        problems.append(f"{label}: {len(extra)} unexpected file(s), e.g. {sorted(extra)[:3]}")
    if any(n.endswith((".po", ".pot")) for n in files):
        problems.append(f"{label}: ships .po/.pot sources (wheels carry .mo only)")
    for package in TYPED[name]:
        if f"pyguibud/{package}/py.typed" not in files:
            problems.append(f"{label}: no pyguibud/{package}/py.typed")
    for member in ("licenses/LICENSE", "licenses/NOTICE.md"):
        if info + member not in names:
            problems.append(f"{label}: no {member} in the .dist-info folder")

    if metadata.get("Version") != version:
        problems.append(
            f"{label}: METADATA version {metadata.get('Version')!r}, expected {version}"
        )
    if metadata.get("Description-Content-Type") != "text/markdown" or CREDIT not in str(
        metadata.get_payload()
    ):
        problems.append(f"{label}: METADATA has no Markdown README with the credit line")

    plugin_groups = {group for group in entry_points if group.startswith("pyguibud.")}
    if name == "pyguibud_runtime":
        if any(DESIGNER_ONLY.match(n) for n in files):
            problems.append(f"{label}: ships designer code")
        mo = {n for n in files if n.endswith("/pyguibud.mo")}
        expected_mo = {f"pyguibud/locale/{code}/LC_MESSAGES/pyguibud.mo" for code in LOCALES}
        if mo != expected_mo:
            problems.append(f"{label}: catalogues {sorted(mo)}, expected the 8 locales")
        if SCHEMA not in files:
            problems.append(f"{label}: no {SCHEMA}")
        if "pyguibud_runtime/py.typed" not in files:
            problems.append(f"{label}: no pyguibud_runtime/py.typed")
        if plugin_groups != set(PLUGIN_GROUPS):
            problems.append(
                f"{label}: entry-point groups {sorted(plugin_groups)}, "
                f"expected {list(PLUGIN_GROUPS)}"
            )
        if "console_scripts" in entry_points:
            problems.append(f"{label}: declares console scripts (they belong to pyguibud)")
    else:
        if plugin_groups:
            problems.append(
                f"{label}: declares {sorted(plugin_groups)} (only pyguibud-runtime may)"
            )
        if entry_points.get("console_scripts") != {"pyguibud", "pyguibud-uic"}:
            problems.append(f"{label}: console scripts {entry_points.get('console_scripts')}")
        requires = metadata.get_all("Requires-Dist") or []
        pins = sorted(r for r in requires if r.replace(" ", "").startswith("pyguibud-runtime"))
        expected_pins = [
            f"pyguibud-runtime=={version}",
            f"pyguibud-runtime[pyside]=={version}; extra == 'pyside'",
        ]
        if [p.replace('"', "'") for p in pins] != expected_pins:
            problems.append(f"{label}: runtime pins {pins}, expected {expected_pins}")
    return files


def check_sdist(name: str, sdist: Path, version: str, problems: list[str]) -> None:
    prefix = f"{name}-{version}/"
    with tarfile.open(sdist) as archive:
        names = {m.name.removeprefix(prefix) for m in archive.getmembers() if m.isfile()}
    for needed in ("pyproject.toml", "PKG-INFO", "README.md", "LICENSE", "NOTICE.md"):
        if needed not in names:
            problems.append(f"{sdist.name}: no {needed}")
    has_tests = any(n.startswith("tests/") for n in names)
    if name == "pyguibud_runtime":
        if has_tests:
            problems.append(f"{sdist.name}: ships tests (spec packaging D7)")
        if not any(n.endswith("/pyguibud.po") for n in names):
            problems.append(f"{sdist.name}: no .po sources")
    else:
        if not has_tests:
            problems.append(f"{sdist.name}: no tests (spec packaging D7)")
        if not any(n.startswith("runtime/src/pyguibud/locale/") for n in names):
            problems.append(f"{sdist.name}: no runtime catalogues for the tests")
        if any(n.startswith("runtime/src/pyguibud/core/") for n in names):
            problems.append(f"{sdist.name}: ships runtime code (it belongs to pyguibud-runtime)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the built PyGUIbud distributions.")
    parser.add_argument("dist", type=Path, help="the folder `uv build --all-packages` wrote")
    args = parser.parse_args(argv)
    version = _version()
    problems: list[str] = []

    found = sorted(p.name for p in args.dist.iterdir() if p.suffix in {".whl", ".gz"})
    expected = sorted(
        [f"{n}-{version}-py3-none-any.whl" for n in SOURCES]
        + [f"{n}-{version}.tar.gz" for n in SOURCES]
    )
    if found != expected:
        print(f"{args.dist}: found {found}\nexpected {expected}", file=sys.stderr)
        return 1

    wheel_files = {
        name: check_wheel(name, args.dist / f"{name}-{version}-py3-none-any.whl", version, problems)
        for name in SOURCES
    }
    overlap = wheel_files["pyguibud"] & wheel_files["pyguibud_runtime"]
    if overlap:
        problems.append(f"{len(overlap)} file(s) in both wheels, e.g. {sorted(overlap)[:3]}")
    for name in SOURCES:
        check_sdist(name, args.dist / f"{name}-{version}.tar.gz", version, problems)

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"OK: {', '.join(expected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
