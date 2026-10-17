"""Shared fakes of the designer tests (H05: test modules never import each other's helpers)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


class FakeStdin:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ValueError("closed")
        self.lines.append(data.decode().rstrip("\n"))

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    """A child that never runs: the test decides when it is ready and when it ends."""

    def __init__(self, argv: list[str], cwd: Path, hangs: bool = False) -> None:
        self.argv, self.cwd, self.hangs = argv, cwd, hangs
        self.stdin = FakeStdin()
        self.code: int | None = None
        self.signals: list[str] = []

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.signals.append("terminate")

    def kill(self) -> None:
        self.signals.append("kill")

    def wait(self, timeout: float | None = None) -> int:
        if self.code is None and (self.hangs or not self.stdin.closed):
            raise subprocess.TimeoutExpired("child", timeout or 0)
        self.code = 0 if self.code is None else self.code
        return self.code

    # what the real child would write
    def ready(self, themes: tuple[str, ...] = ("flatly", "darkly")) -> None:
        (self.cwd / "ready.json").write_text(json.dumps({"themes": list(themes)}), "utf-8")

    def end(self, code: int = 0, result: dict[str, str] | None = None, stderr: str = "") -> None:
        if result is not None:
            (self.cwd / "result.json").write_text(json.dumps(result), "utf-8")
        (self.cwd / "stderr.txt").write_text(stderr, "utf-8")
        self.code = code
