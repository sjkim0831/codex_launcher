from __future__ import annotations

import shlex

from free_agent.models import VerificationResult
from free_agent.policy.approvals import ApprovalFlow
from free_agent.policy.guard import PolicyGuard
from free_agent.tools.shell import run_shell


class Verifier:
    def run(self, workspace: str, commands: list[str], approvals: ApprovalFlow, policy: PolicyGuard) -> VerificationResult:
        outputs: list[str] = []
        ran: list[str] = []
        for command in commands:
            policy.assert_command_allowed(command)
            if policy.requires_command_approval(command) and not approvals.request(f"Run verifier command `{command}`?"):
                outputs.append(f"$ {command}\nskipped: approval declined")
                return VerificationResult(ok=False, ran_commands=ran, output="\n\n".join(outputs))
            ran.append(command)
            result = run_shell(workspace=workspace, command=shlex.split(command))
            outputs.append(f"$ {command}\n{result.stdout}{result.stderr}".rstrip())
            if not result.ok:
                return VerificationResult(ok=False, ran_commands=ran, output="\n\n".join(outputs))
        return VerificationResult(ok=True, ran_commands=ran, output="\n\n".join(outputs))
