from __future__ import annotations
import subprocess
from freeagent.models import CommandResult

def _run_git(args: list[str], cwd: str = ".") -> CommandResult:
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return CommandResult(ok=proc.returncode == 0, code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)

def git_status(cwd: str = ".") -> CommandResult:
    return _run_git(["status", "--short"], cwd)

def git_diff(cwd: str = ".") -> CommandResult:
    return _run_git(["diff"], cwd)

def git_available(cwd: str = ".") -> bool:
    return _run_git(["rev-parse", "--is-inside-work-tree"], cwd).ok
