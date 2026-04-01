from __future__ import annotations

import subprocess


def _run_git(workspace: str, args: list[str]) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or completed.stderr.strip()


def collect_git_state(workspace: str) -> tuple[str | None, str]:
    branch = _run_git(workspace, ["rev-parse", "--abbrev-ref", "HEAD"])
    status = _run_git(workspace, ["status", "--short"])
    if "not a git repository" in branch.lower():
        return None, status
    return branch or None, status
