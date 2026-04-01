from __future__ import annotations


class ApprovalFlow:
    def __init__(self, auto_approve: bool = False) -> None:
        self.auto_approve = auto_approve

    def request(self, message: str) -> bool:
        if self.auto_approve:
            return True
        try:
            answer = input(f"{message} [y/N]: ").strip().lower()
        except EOFError:
            return False
        return answer in {"y", "yes"}
