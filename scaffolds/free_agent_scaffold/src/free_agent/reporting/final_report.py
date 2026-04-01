from __future__ import annotations

from free_agent.models import ContextBundle, ExecutionResult, Plan, TaskState, VerificationResult


def compose_final_report(
    goal: str,
    plan: Plan,
    context: ContextBundle,
    execution: ExecutionResult,
    verification: VerificationResult,
    state_history: list[TaskState],
    session_id: str,
) -> str:
    state_line = " -> ".join(state.value for state in state_history)
    targets = ", ".join(plan.targets or plan.candidate_files[:3] or ["none"])
    verify_line = ", ".join(verification.ran_commands or ["none"])
    branch = context.git_branch or "unknown"
    return "\n".join(
        [
            f"Goal: {goal}",
            f"State path: {state_line}",
            f"Targets: {targets}",
            f"Session: {session_id}",
            f"Git branch: {branch}",
            f"Execution: {execution.summary}",
            f"Approvals: {', '.join(execution.approvals or ['none'])}",
            f"Verify commands: {verify_line}",
            f"Verification ok: {verification.ok}",
            f"Recent sessions: {', '.join(plan.recent_sessions or ['none'])}",
            "",
            "Patch preview:",
            execution.patch_preview or "(none)",
        ]
    )
