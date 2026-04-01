from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class ShellResult:
    ok: bool
    code: int
    stdout: str
    stderr: str


def run_shell(workspace: str, command: list[str]) -> ShellResult:
    completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=False)
    return ShellResult(
        ok=completed.returncode == 0,
        code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
