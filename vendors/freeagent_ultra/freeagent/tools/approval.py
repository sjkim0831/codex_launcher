from __future__ import annotations

def ask_user_approval(reason: str, risk: str = "medium", yes: bool = False) -> bool:
    if yes:
        return True
    answer = input(f"[{risk.upper()}] {reason} (y/N): ").strip().lower()
    return answer == "y"

def ask_second_approval(reason: str, yes: bool = False) -> bool:
    if yes:
        return True
    answer = input(f"[CRITICAL] {reason}. Type 'approve' to continue: ").strip().lower()
    return answer == "approve"
