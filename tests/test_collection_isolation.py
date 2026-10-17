"""The suite's own collection: a package conftest reaches its tests in every argument order.

pytest 9.1 binds a conftest's fixtures to the first Directory node of its folder; a later file
argument in the parent folder used to build a second node, and the qa tests after it then ran
without ``clean_i18n`` (a pseudo-locale leaked into ``test_m24_*``, Step 19b). ``tests/conftest.py``
reuses the first node; this test runs pytest on the order that broke.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_a_package_conftest_survives_a_detour_through_the_parent_folder() -> None:
    later = "tests/qa/test_step10_abuse.py"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--setup-plan", "-p", "no:cacheprovider",
         "tests/qa/test_step15b_fixes.py", "tests/test_scorer_status.py", later],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120, check=False,
    )  # fmt: skip
    plans = [line for line in done.stdout.splitlines() if line.strip().startswith(later + "::")]
    assert done.returncode == 0 and plans, done.stdout[-2000:] + done.stderr[-2000:]
    assert all("clean_i18n" in line for line in plans), [p for p in plans if "clean_i18n" not in p]
