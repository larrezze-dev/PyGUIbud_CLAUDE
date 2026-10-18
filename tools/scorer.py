"""PyGUIbud SCORER: builds SCOREBOARD.md and scoreboard.html from the plan, tests and coverage.

Read-only with respect to the plan and the code. Writes only SCOREBOARD.md, scoreboard.html
and the ``.scorer/`` working directory. Standard library only.

Usage: ``uv run python tools/scorer.py [--no-tests]``
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / "DEVELOPMENT_PLAN.md"
SCORER_DIR = ROOT / ".scorer"
JUNIT = SCORER_DIR / "junit.xml"
COVERAGE = SCORER_DIR / "coverage.json"
GATE = SCORER_DIR / "gate.json"

STATUS_ORDER = ("✅", "🧪", "🔄", "⏳")
STATUS_LABEL = {"✅": "done", "🧪": "awaiting UAT", "🔄": "in progress", "⏳": "pending"}
STATUS_CLASS = {"✅": "done", "🧪": "uat", "🔄": "wip", "⏳": "todo"}
NA_ITEMS = (("Lint (ruff)", "lint"), ("Types (mypy)", "types"), ("i18n coverage", "i18n"))
NA_TEXT = "n/a (later step)"
ROW_RE = re.compile(r"^\|\s*(\d{1,3}[a-z]?)\s*\|")


@dataclass
class Step:
    """One row of the development plan table."""

    number: str
    name: str
    lead: str
    status: str


@dataclass
class TestResult:
    """Aggregated pytest outcome."""

    tests: int
    passed: int
    failed: int
    errors: int
    skipped: int
    seconds: float


@dataclass
class TestRun:
    """Outcome of a test run (or reuse of earlier artefacts)."""

    result: TestResult | None
    coverage: float | None
    note: str
    ok: bool


def clean(text: str) -> str:
    """Strip markdown emphasis and backticks for display."""
    return re.sub(r"[`*]", "", text).strip()


def split_row(line: str) -> list[str]:
    """Split a markdown table row on pipes that are not inside backticks."""
    cells: list[str] = []
    buf: list[str] = []
    in_code = False
    for ch in line.strip().strip("|"):
        if ch == "`":
            in_code = not in_code
        if ch == "|" and not in_code:
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def find_status(cell: str) -> str | None:
    """Return the status emoji contained in a cell, tolerating U+FE0F.

    A cell with several emojis (e.g. "🔄 14a.1 ✅ · 14a.2 ⏳") takes the leading one. A partial
    status ("🔶 ... ✅ ...") is in progress: only a leading ✅ counts as done (H06).
    """
    if cell.lstrip().startswith("🔶"):
        return "🔄"
    stripped = cell.lstrip()
    markers = {emoji for emoji in STATUS_ORDER if emoji in cell}
    if stripped.startswith("✅") and markers - {"✅"}:
        return "🔄"  # a leading ✅ with unfinished parts ("✅ 19a · 🧪 19c") is in progress
    for emoji in STATUS_ORDER:
        if stripped.startswith(emoji):
            return emoji
    for emoji in reversed(STATUS_ORDER):  # the least finished one wins: ✅ only on its own
        if emoji in cell:
            return emoji
    return None


def parse_plan(path: Path) -> list[Step]:
    """Parse the step table of the development plan."""
    steps: list[Step] = []
    text = path.read_text(encoding="utf-8")
    for raw in text.replace("\r", "").split("\n"):
        if not ROW_RE.match(raw):
            continue
        cells = split_row(raw)
        non_empty = [c for c in cells if c]
        if len(cells) < 4 or not non_empty:
            continue
        status = find_status(non_empty[-1])
        if status is None:
            continue
        steps.append(Step(clean(cells[0]), clean(cells[1]), clean(cells[2]), status))
    return steps


def run_tests() -> TestRun:
    """Run pytest with junit and coverage output; never raises on test failure."""
    SCORER_DIR.mkdir(exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        f"--junitxml={JUNIT.relative_to(ROOT).as_posix()}",
        "--cov",
        f"--cov-report=json:{COVERAGE.relative_to(ROOT).as_posix()}",
    ]
    try:
        proc = subprocess.run(
            cmd, encoding="utf-8", errors="replace", cwd=ROOT, capture_output=True, check=False
        )
    except OSError as exc:
        return TestRun(None, None, f"pytest could not start: {exc}", ok=False)
    run = load_artefacts()
    run.ok = proc.returncode == 0
    if proc.returncode != 0:
        run.note = f"pytest exited with code {proc.returncode}"
    else:
        run.note = "tests run now"
    return run


def load_artefacts() -> TestRun:
    """Parse existing junit and coverage files, reporting honestly if they are missing."""
    result: TestResult | None = None
    coverage: float | None = None
    if JUNIT.exists():
        try:
            result = parse_junit(JUNIT)
        except (ET.ParseError, ValueError):
            result = None
    if COVERAGE.exists():
        try:
            data = json.loads(COVERAGE.read_text(encoding="utf-8"))
            coverage = float(data["totals"]["percent_covered"])
        except (OSError, ValueError, KeyError, TypeError):
            coverage = None
    if result is None and coverage is None:
        return TestRun(None, None, "tests not run", ok=False)
    ok = result is not None and result.failed == 0 and result.errors == 0
    return TestRun(result, coverage, "reused earlier .scorer/ files (--no-tests)", ok=ok)


def parse_junit(path: Path) -> TestResult:
    """Aggregate all testsuite elements of a junit XML file."""
    root = ET.parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = failed = errors = skipped = 0
    seconds = 0.0
    for suite in suites:
        tests += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        seconds += float(suite.get("time", 0.0))
    passed = tests - failed - errors - skipped
    return TestResult(tests, passed, failed, errors, skipped, seconds)


def load_gate() -> dict[str, object] | None:
    """Read orchestrator-supplied gate figures from .scorer/gate.json, if present."""
    if not GATE.is_file():
        return None
    try:
        data = json.loads(GATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def gate_run(gate: dict[str, object]) -> TestRun:
    """Build the test outcome from gate figures; pytest is not executed by the scorer.

    Coverage is taken only from an explicit ``coverage`` number in the gate file; an older
    ``.scorer/coverage.json`` is never shown as if it belonged to the current gate.
    """
    raw_cov = gate.get("coverage")
    coverage = float(raw_cov) if isinstance(raw_cov, (int, float)) else None
    block = gate.get("tests")
    if not isinstance(block, dict):
        return TestRun(None, coverage, "gate file has no tests block", ok=False)
    passed = int(block.get("passed", 0))
    failed = int(block.get("failed", 0))
    skipped = int(block.get("skipped", 0))
    xfailed = int(block.get("xfailed", 0))
    total = passed + failed + skipped + xfailed
    result = TestResult(total, passed, failed, 0, skipped + xfailed, 0.0)
    note = f"gate figures {gate.get('date', 'undated')}, pytest not run by scorer"
    return TestRun(result, coverage, note, ok=failed == 0)


def gate_quality(gate: dict[str, object] | None) -> dict[str, str]:
    """Quality-gate texts from the gate file, keyed like NA_ITEMS."""
    raw = gate.get("quality") if gate is not None else None
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def recent_commits() -> list[str]:
    """Return the last few commits via read-only git; empty if git is unavailable."""
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            encoding="utf-8",
            errors="replace",
            cwd=ROOT,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def current_step(steps: list[Step]) -> Step | None:
    """First in-progress or UAT step, otherwise the first pending one."""
    for step in steps:
        if step.status in ("🔄", "🧪"):
            return step
    for step in steps:
        if step.status == "⏳":
            return step
    return None


def fmt_tests(run: TestRun) -> str:
    """Short test summary text."""
    if run.result is None:
        return "tests not run"
    r = run.result
    return f"{r.passed}/{r.tests} passed" + (
        f", {r.failed + r.errors} failing" if not run.ok else ""
    )


def fmt_cov(run: TestRun) -> str:
    """Coverage text."""
    return "not available" if run.coverage is None else f"{run.coverage:.1f} %"


def build_markdown(
    steps: list[Step],
    run: TestRun,
    commits: list[str],
    stamp: str,
    quality: dict[str, str] | None = None,
) -> str:
    """Render SCOREBOARD.md."""
    done = sum(1 for s in steps if s.status == "✅")
    cur = current_step(steps)
    cur_text = f"{cur.number} {cur.name} ({cur.status})" if cur else "none"
    lines = [
        "# PyGUIbud scoreboard",
        "",
        f"_Last updated: {stamp}_",
        "",
        f"- **Steps done:** {done}/{len(steps)}",
        f"- **Current step:** {cur_text}",
        f"- **Tests:** {fmt_tests(run)} ({run.note})",
        f"- **Coverage:** {fmt_cov(run)}",
    ]
    if run.result is not None:
        r = run.result
        lines.append(
            f"- **Test detail:** {r.tests} collected, {r.failed} failed, {r.errors} errors, "
            f"{r.skipped} skipped, {r.seconds:.2f} s"
        )
    lines += ["", "## Quality gates", "", "| Check | Result |", "| --- | --- |"]
    quality = quality or {}
    lines += [f"| {label} | {quality.get(key, NA_TEXT)} |" for label, key in NA_ITEMS]
    lines += ["", "## Steps", "", "| # | Step | Lead | Status |", "| --- | --- | --- | --- |"]
    for s in steps:
        name = s.name.replace("|", "\\|")
        lead = s.lead.replace("|", "\\|")
        lines.append(f"| {s.number} | {name} | {lead} | {s.status} {STATUS_LABEL[s.status]} |")
    if commits:
        lines += ["", "## Recent commits", ""]
        lines += [f"- `{c}`" for c in commits]
    return "\n".join(lines) + "\n"


CSS = """
:root{--primary:#1C3FF0;--surface:#FFFFFF;--page:#F4F6FA;--selected:#EEF3FF;--text:#212832;
--muted:#5C636B;--border:#D9DEE6;--success:#147A50;--success-bg:#EAF8F1;--warning:#9A5A00;
--warning-bg:#FFF4D8;--error:#AD2A31;--error-bg:#FDEBEC}
@media (prefers-color-scheme:dark){:root{--primary:#3F6DFF;--surface:#212832;--page:#15181D;
--selected:#071044;--text:#F2F4F6;--muted:#CFD3D8;--border:#3A4350;--success:#8FD8B7;
--success-bg:#12332A;--warning:#F0C36A;--warning-bg:#3A2D10;--error:#F0A6AA;--error-bg:#3F1A1D}}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);
font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.45}
main{max-width:1000px;margin:0 auto;padding:16px}
h1{margin:0 0 4px;font-size:1.6rem}h2{font-size:1.1rem;margin:24px 0 8px}
.sub{color:var(--muted);font-size:.9rem;margin:0 0 16px}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px}
.bar{height:16px;border-radius:8px;background:var(--border);overflow:hidden;margin:8px 0}
.bar>span{display:block;height:100%;background:var(--primary)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}
.tile .k{color:var(--muted);font-size:.8rem;text-transform:uppercase;letter-spacing:.04em}
.tile .v{font-size:1.4rem;font-weight:700;margin-top:4px;overflow-wrap:anywhere}
.tile .n{color:var(--muted);font-size:.8rem;margin-top:2px}
.tile.na .v{color:var(--muted);font-size:1.05rem}
.tile.bad .v{color:var(--error)}.tile.good .v{color:var(--success)}
.filters{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.filters button{background:var(--surface);color:var(--text);border:1px solid var(--border);
border-radius:16px;padding:4px 12px;cursor:pointer;font:inherit}
.filters button[aria-pressed=true]{background:var(--primary);color:#fff;border-color:var(--primary)}
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.92rem}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--border);vertical-align:top}
th{color:var(--muted);font-weight:600}
tr.current{background:var(--selected)}
.badge{display:inline-block;border-radius:12px;padding:2px 10px;font-size:.8rem;
font-weight:600;white-space:nowrap;border:1px solid transparent}
.badge.done{background:var(--success-bg);color:var(--success)}
.badge.wip,.badge.uat{background:var(--warning-bg);color:var(--warning)}
.badge.todo{background:transparent;color:var(--muted);border-color:var(--border)}
ul.commits{margin:0;padding-left:18px;font-family:ui-monospace,Consolas,monospace;font-size:.85rem}
@media (max-width:560px){main{padding:10px}h1{font-size:1.3rem}th,td{padding:6px}}
"""

JS = """
(function(){
var btns=document.querySelectorAll('.filters button');
var rows=document.querySelectorAll('tbody tr[data-status]');
btns.forEach(function(b){b.addEventListener('click',function(){
btns.forEach(function(o){o.setAttribute('aria-pressed',o===b?'true':'false');});
var f=b.getAttribute('data-filter');
rows.forEach(function(r){r.hidden=!(f==='all'||r.getAttribute('data-status')===f);});
});});
})();
"""


def esc(value: object) -> str:
    """HTML-escape any value."""
    return html.escape(str(value), quote=True)


def tile(label: str, value: str, note: str = "", cls: str = "") -> str:
    """Render one summary tile."""
    note_html = f'<div class="n">{esc(note)}</div>' if note else ""
    return (
        f'<div class="card tile {cls}"><div class="k">{esc(label)}</div>'
        f'<div class="v">{esc(value)}</div>{note_html}</div>'
    )


def _favicon() -> str:
    """The brand application icon as an inline favicon (nothing when a fork removed it)."""
    icon = ROOT / "assets" / "brand" / "logo" / "pyguibud.png"
    if not icon.is_file():
        return ""
    data = base64.b64encode(icon.read_bytes()).decode("ascii")
    return f'\n<link rel="icon" type="image/png" href="data:image/png;base64,{data}">'


def build_html(
    steps: list[Step],
    run: TestRun,
    commits: list[str],
    stamp: str,
    quality: dict[str, str] | None = None,
) -> str:
    """Render the self-contained scoreboard.html."""
    total = len(steps)
    done = sum(1 for s in steps if s.status == "✅")
    pct = round(100 * done / total) if total else 0
    cur = current_step(steps)
    cur_cls = "bad" if run.result and not run.ok else ("good" if run.ok else "na")
    tiles = [
        tile("Tests", fmt_tests(run), run.note, cur_cls),
        tile("Coverage", fmt_cov(run), "line + branch" if run.coverage is not None else ""),
        tile(
            "Current step",
            f"{cur.number} {cur.name}" if cur else "none",
            f"{cur.status} {STATUS_LABEL[cur.status]}" if cur else "",
        ),
    ]
    quality = quality or {}
    tiles += [
        tile(label, quality[key], "", "good") if key in quality else tile(label, NA_TEXT, "", "na")
        for label, key in NA_ITEMS
    ]
    rows = []
    for s in steps:
        is_cur = cur is not None and s.number == cur.number
        rows.append(
            f'<tr data-status="{STATUS_CLASS[s.status]}"{" class=current" if is_cur else ""}>'
            f"<td>{esc(s.number)}</td><td>{esc(s.name)}</td><td>{esc(s.lead)}</td>"
            f'<td><span class="badge {STATUS_CLASS[s.status]}">{s.status} '
            f"{esc(STATUS_LABEL[s.status])}</span></td></tr>"
        )
    filters = "".join(
        f'<button type="button" data-filter="{key}" '
        f'aria-pressed="{"true" if key == "all" else "false"}">'
        f"{label}</button>"
        for key, label in (
            ("all", "All"),
            ("done", "Done"),
            ("wip", "In progress"),
            ("uat", "Awaiting UAT"),
            ("todo", "Pending"),
        )
    )
    commit_html = ""
    if commits:
        items = "".join(f"<li>{esc(c)}</li>" for c in commits)
        commit_html = (
            f'<h2>Recent commits</h2><div class="card"><ul class="commits">{items}</ul></div>'
        )
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>PyGUIbud scoreboard</title>{_favicon()}
<style>{CSS}</style>
</head>
<body>
<main>
<h1>PyGUIbud scoreboard</h1>
<p class="sub">Last updated: {esc(stamp)}</p>
<div class="card">
<strong>{done} of {total} steps done ({pct} %)</strong>
<div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="{total}" \
aria-valuenow="{done}" aria-label="Steps done"><span style="width:{pct}%"></span></div>
</div>
<h2>Metrics</h2>
<div class="tiles">{"".join(tiles)}</div>
<h2>Steps</h2>
<div class="filters">{filters}</div>
<div class="card table-wrap">
<table>
<thead><tr><th>#</th><th>Step</th><th>Lead</th><th>Status</th></tr></thead>
<tbody>{"".join(rows)}</tbody>
</table>
</div>
{commit_html}
</main>
<script>{JS}</script>
</body>
</html>
"""


def main() -> int:
    """Entry point."""
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Generate SCOREBOARD.md and scoreboard.html")
    parser.add_argument("--no-tests", action="store_true", help="reuse existing .scorer/ files")
    args = parser.parse_args()

    steps = parse_plan(PLAN)
    gate = load_gate()
    # Gate figures supplied by the orchestrator take precedence; pytest is never run then.
    if gate is not None:
        run = gate_run(gate)
    elif args.no_tests:
        run = load_artefacts()
    else:
        run = run_tests()
    quality = gate_quality(gate)
    commits = recent_commits()
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S UTC%z")

    (ROOT / "SCOREBOARD.md").write_text(
        build_markdown(steps, run, commits, stamp, quality), encoding="utf-8", newline="\n"
    )
    (ROOT / "scoreboard.html").write_text(
        build_html(steps, run, commits, stamp, quality), encoding="utf-8", newline="\n"
    )

    done = sum(1 for s in steps if s.status == "✅")
    cur = current_step(steps)
    cur_text = f"{cur.number} {cur.name} ({cur.status})" if cur else "none"
    tests = (
        "tests not run" if run.result is None else f"tests {run.result.passed}/{run.result.tests}"
    )
    print(
        f"Steps {done}/{len(steps)} done · current: {cur_text} · {tests} · coverage {fmt_cov(run)}"
    )
    if not run.ok and run.result is not None:
        print(f"WARNING: {run.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
