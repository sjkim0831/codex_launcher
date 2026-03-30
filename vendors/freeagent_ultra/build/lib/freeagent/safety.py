from __future__ import annotations
from pathlib import Path

DENY_COMMAND_TOKENS = [
    "rm -rf /", "mkfs", "shutdown", "reboot", "curl | sh", "wget | sh", "dd if=",
    "scp ", "rsync ", "powershell -enc", "format c:"
]
PROTECTED_NAMES = {".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "known_hosts", ".npmrc"}

def protected_path(path: str) -> bool:
    p = Path(path)
    parts = {part.lower() for part in p.parts}
    return p.name in PROTECTED_NAMES or ".ssh" in parts or "secrets" in parts or "credential" in p.name.lower() or "token" in p.name.lower()

def classify_risk_for_command(command: str) -> str:
    lowered = command.strip().lower()
    if any(token in lowered for token in DENY_COMMAND_TOKENS):
        return "critical"
    if lowered.startswith(("git clean", "pip install", "npm install", "pnpm add", "apt ", "brew install")):
        return "high"
    if lowered.startswith(("pytest", "python ", "python3 ", "node ", "npm test", "pnpm test", "uv run", "echo ", "ls", "dir", "git status", "git diff")):
        return "medium"
    return "high"

def command_allowed(command: str) -> tuple[bool, str]:
    risk = classify_risk_for_command(command)
    return (risk != "critical", "allowed" if risk != "critical" else "dangerous command token detected")

def second_approval_required(command: str) -> bool:
    return classify_risk_for_command(command) == "critical"
