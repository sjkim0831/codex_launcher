from __future__ import annotations

from pathlib import Path

from free_agent.context.builder import build_context
from free_agent.editing.patcher import build_patch_preview, propose_edit
from free_agent.memory.store import SessionStore
from free_agent.models import ContextBundle, ExecutionResult, Plan, RunResult, TaskState
from free_agent.orchestrator.state_machine import StateMachine
from free_agent.planning.planner import Planner
from free_agent.policy.approvals import ApprovalFlow
from free_agent.policy.guard import PolicyGuard
from free_agent.repo.symbols import SymbolIndexer
from free_agent.reporting.final_report import compose_final_report
from free_agent.tools.filesystem import ensure_parent, read_text, write_text
from free_agent.verify.verifier import Verifier


class AgentEngine:
    def __init__(self, workspace: str | None = None, auto_approve: bool = False) -> None:
        self.workspace = workspace or str(Path.cwd())
        self.planner = Planner()
        self.policy = PolicyGuard()
        self.verifier = Verifier()
        self.approvals = ApprovalFlow(auto_approve=auto_approve)
        self.sessions = SessionStore(self.workspace)
        self.symbols = SymbolIndexer()

    def build_plan(self, goal: str, targets: list[str] | None = None) -> Plan:
        return self.planner.make_plan(goal=goal, targets=targets or [], workspace=self.workspace)

    def run(self, goal: str, targets: list[str] | None = None, verify_commands: list[str] | None = None) -> RunResult:
        machine = StateMachine()
        machine.transition(TaskState.ANALYZE)

        machine.transition(TaskState.PLAN)
        plan = self.build_plan(goal=goal, targets=targets or [])
        if verify_commands:
            plan.verify_commands = verify_commands

        session = self.sessions.create(goal=goal, workspace=self.workspace, targets=plan.targets or plan.candidate_files[:3])
        self.sessions.append(session, "plan_created", {"candidate_files": plan.candidate_files, "verify_commands": plan.verify_commands})

        machine.transition(TaskState.GATHER_CONTEXT)
        context = build_context(workspace=self.workspace, candidates=plan.targets or plan.candidate_files[:3])
        self.sessions.append(session, "context_built", {"candidates": context.candidates, "git_branch": context.git_branch})

        machine.transition(TaskState.EXECUTE)
        execution = self._execute(plan, context)
        self.sessions.append(
            session,
            "execution_completed",
            {
                "applied": execution.applied,
                "changed_files": execution.changed_files,
                "summary": execution.summary,
                "approvals": execution.approvals,
            },
        )

        machine.transition(TaskState.VERIFY)
        verification = self.verifier.run(
            workspace=self.workspace,
            commands=plan.verify_commands,
            approvals=self.approvals,
            policy=self.policy,
        )
        self.sessions.append(session, "verification_completed", {"ok": verification.ok, "commands": verification.ran_commands})

        machine.transition(TaskState.REVIEW)
        machine.transition(TaskState.REPORT)

        final_report = compose_final_report(
            goal=goal,
            plan=plan,
            context=context,
            execution=execution,
            verification=verification,
            state_history=machine.history,
            session_id=session.session_id,
        )
        machine.transition(TaskState.DONE)
        self.sessions.append(session, "run_completed", {"state_history": [state.value for state in machine.history]})

        return RunResult(
            goal=goal,
            state_history=machine.history,
            plan=plan,
            context=context,
            execution=execution,
            verification=verification,
            final_report=final_report,
        )

    def _execute(self, plan: Plan, context: ContextBundle) -> ExecutionResult:
        changed_files: list[str] = []
        approvals: list[str] = []
        summaries: list[str] = []
        patch_preview = build_patch_preview(
            goal=plan.goal,
            candidates=plan.targets or plan.candidate_files[:1],
            previews=context.previews,
            symbols=context.symbols,
        )

        for relative_path in plan.targets or plan.candidate_files[:1]:
            absolute_path = str(Path(self.workspace) / relative_path)
            try:
                original_text = read_text(absolute_path)
            except OSError:
                continue

            proposal = propose_edit(
                goal=plan.goal,
                path=relative_path,
                original_text=original_text,
                available_symbols=self.symbols.extract(workspace=self.workspace, relative_path=relative_path),
            )
            if proposal is None:
                continue

            if self.policy.requires_write_approval(relative_path):
                approved = self.approvals.request(f"Apply edit to {relative_path}: {proposal.summary}?")
                approvals.append(f"{relative_path}={'approved' if approved else 'declined'}")
                if not approved:
                    continue

            ensure_parent(absolute_path)
            write_text(absolute_path, proposal.updated_text)
            changed_files.append(relative_path)
            summaries.append(f"{relative_path}: {proposal.summary}")
            patch_preview = proposal.diff

        return ExecutionResult(
            applied=bool(changed_files),
            summary="; ".join(summaries) if summaries else "no deterministic edit applied",
            changed_files=changed_files,
            patch_preview=patch_preview,
            approvals=approvals,
        )
