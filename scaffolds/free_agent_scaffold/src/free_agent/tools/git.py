from __future__ import annotations

from free_agent.repo.git_state import collect_git_state


def current_git_snapshot(workspace: str) -> dict[str, str | None]:
    branch, status = collect_git_state(workspace)
    return {
        "branch": branch,
        "status": status,
    }
