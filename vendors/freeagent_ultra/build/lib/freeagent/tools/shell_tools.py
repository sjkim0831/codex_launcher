from __future__ import annotations
import subprocess
from freeagent.models import CommandResult
from freeagent.safety import command_allowed

def run_shell(command: str, cwd: str = ".", timeout_sec: int = 180) -> CommandResult:
    allowed, reason = command_allowed(command)
    if not allowed:
        return CommandResult(ok=False, code=-1, stdout="", stderr=reason)
    try:
        proc = subprocess.run(command, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout_sec)
        return CommandResult(ok=proc.returncode == 0, code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)
    except subprocess.TimeoutExpired as exc:
        return CommandResult(ok=False, code=-2, stdout=exc.stdout or "", stderr=f"timeout after {timeout_sec}s")


def run_tests(command: str, cwd: str = ".", timeout_sec: int = 300) -> CommandResult:
    return run_shell(command=command, cwd=cwd, timeout_sec=timeout_sec)
