from __future__ import annotations

import re


def inspect_errors(text: str, max_items: int = 5) -> dict[str, object]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    error_lines = [
        line
        for line in lines
        if any(token in line.lower() for token in ("error", "exception", "failed", "traceback", "assertionerror"))
    ]
    top = error_lines[:max_items]
    hints: list[str] = []
    joined = "\n".join(lines).lower()
    if "permissionerror" in joined or "access is denied" in joined:
        hints.append("Check file/folder permissions and temp directory access.")
    if "modulenotfounderror" in joined:
        hints.append("Install missing dependencies or fix PYTHONPATH/module imports.")
    if "assert" in joined and "failed" in joined:
        hints.append("A test assertion failed. Review expected/actual values in failing test.")
    m = re.search(r"(tests?/[^:\s]+|[A-Za-z0-9_./\\-]+\.py)", "\n".join(top))
    if m:
        hints.append(f"Focus on related file first: {m.group(1)}")
    if not hints:
        hints.append("Inspect first failing stack frame and narrow patch scope.")
    return {
        "summary": top[0] if top else "No explicit error line found.",
        "errors": top,
        "hints": hints[:max_items],
    }

