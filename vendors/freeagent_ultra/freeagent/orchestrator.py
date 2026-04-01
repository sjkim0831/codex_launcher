from __future__ import annotations

import time
from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from freeagent.models import ApplyResult, AskResult, ExplainResult, Plan, PlanStep
from freeagent.patch_engine import build_patch, patch_file
from freeagent.provider_manager import ProviderManager
from freeagent.safety import classify_risk_for_command, protected_path
from freeagent.session import Session, SessionStore
from freeagent.tools.approval import ask_second_approval, ask_user_approval
from freeagent.tools.file_tools import read_file, write_file
from freeagent.tools.inspect_tools import inspect_errors
from freeagent.tools.shell_tools import run_tests
from freeagent.utils.project_scan import _goal_is_low_signal, _extract_goal_keywords, choose_files, summarize_project

console = Console()


class Orchestrator:
    def __init__(self, store: SessionStore):
        self.store = store
        self.providers = ProviderManager()

    def inspect(self):
        return summarize_project(".")

    def explain(self, targets: list[str] | None = None, symbol: str | None = None) -> ExplainResult:
        if targets:
            p = targets[0]
            text = read_file(p)
            clean_text = text.lstrip("\ufeff")
            prompt = f"Explain file briefly: {p}\\n\\n{clean_text[:1800]}"
            resp, provider = self.providers.generate(prompt)
            return ExplainResult(
                path=p,
                symbol=symbol,
                summary=resp,
                details={"provider": provider, "preview": clean_text[:500]},
            )
        if symbol:
            for f in summarize_project(".").summaries:
                try:
                    text = read_file(f)
                except Exception:
                    continue
                if symbol in text:
                    prompt = f"Explain symbol {symbol} in file {f}\\n\\n{text[:1800]}"
                    resp, provider = self.providers.generate(prompt)
                    return ExplainResult(path=f, symbol=symbol, summary=resp, details={"provider": provider})
        return ExplainResult(path=None, symbol=symbol, summary="No matching target or symbol found.")

    def ask(self, goal: str, targets: list[str] | None = None) -> AskResult:
        summary, candidates = self.scan(goal, targets)
        tokens = _extract_goal_keywords(goal)
        low_signal = _goal_is_low_signal(goal, tokens)
        selected = targets or [c.path for c in candidates[:2]]
        prompt_lines = [
            "You are helping with a software project.",
            "Answer directly and keep it concise.",
            "Do not edit files.",
            "Prefer practical guidance on UI structure, state flow, API flow, and UX.",
            "Limit the answer to 8 short bullets or fewer.",
            f"Request: {goal}",
            f"Detected stack: {summary.stack}",
        ]
        if low_signal:
            prompt_lines.extend(
                [
                    "The request is underspecified.",
                    "Do not refuse.",
                    "First state the most likely interpretation in one short sentence.",
                    "Then ask up to 3 short clarifying questions or provide the smallest safe next step.",
                ]
            )
        if selected:
            prompt_lines.append("Relevant targets:")
            prompt_lines.extend(f"- {path}" for path in selected)
        if candidates:
            prompt_lines.append("Candidate files:")
            prompt_lines.extend(
                f"- {item.path}"
                for item in candidates[:3]
            )
        sample_summaries = []
        for path in selected[:2]:
            preview = summary.summaries.get(path)
            if preview:
                compact_preview = " ".join(str(preview).split())[:240]
                sample_summaries.append(f"- {compact_preview}")
        if sample_summaries:
            prompt_lines.append("Context:")
            prompt_lines.extend(sample_summaries)
        prompt_lines.append("Do not propose file edits unless explicitly asked.")
        resp, provider = self.providers.generate("\n".join(prompt_lines))
        return AskResult(
            answer=resp,
            provider=provider,
            details={
                "stack": summary.stack,
                "targets": selected,
                "candidate_files": [c.path for c in candidates[:3]],
            },
        )

    def prompt(self, goal: str, targets: list[str] | None = None) -> AskResult:
        summary, candidates = self.scan(goal, targets)
        selected = targets or [c.path for c in candidates[:4]]
        prompt_lines = [
            "You are helping with a software project.",
            "Answer naturally and directly.",
            "You may discuss likely code changes, edit points, tradeoffs, and next steps.",
            "Do not claim files were edited unless an apply/edit command was explicitly requested and completed.",
            f"User request: {goal}",
            f"Detected stack: {summary.stack}",
        ]
        if selected:
            prompt_lines.append("Likely relevant files:")
            prompt_lines.extend(f"- {path}" for path in selected)
        if candidates:
            prompt_lines.append("Top candidates:")
            prompt_lines.extend(f"- {item.path} score={item.score}" for item in candidates[:6])
        sample_summaries = []
        for path in selected[:3]:
            preview = summary.summaries.get(path)
            if preview:
                sample_summaries.append(f"- {' '.join(str(preview).split())[:240]}")
        if sample_summaries:
            prompt_lines.append("Context:")
            prompt_lines.extend(sample_summaries)
        resp, provider = self.providers.generate("\n".join(prompt_lines))
        return AskResult(
            answer=resp,
            provider=provider,
            details={
                "stack": summary.stack,
                "targets": selected,
                "candidate_files": [c.path for c in candidates[:6]],
            },
        )

    def scan(self, goal: str, targets: list[str] | None = None):
        summary = summarize_project(".")
        candidates = choose_files(goal, explicit_targets=targets)
        return summary, candidates

    def make_plan(self, goal: str, targets: list[str] | None = None) -> Plan:
        summary, candidates = self.scan(goal, targets)
        target_files: list[str] = []
        if candidates:
            top = candidates[0].score
            cutoff = max(1.0, top * 0.75)
            selected = [c for c in candidates if c.score >= cutoff][:4]
            if not selected:
                selected = candidates[:1]
            target_files = [c.path for c in selected]

        verify = summary.suggested_tests[:2]
        if any("test" in t for t in target_files) and not verify:
            verify = ["pytest -q"]

        return Plan(
            goal=goal,
            stack=summary.stack,
            candidate_files=candidates,
            target_files=target_files,
            steps=[
                PlanStep("Inspect Context", "Detect stack, target files, and verification commands.", "low"),
                PlanStep("Draft Patches", "Build minimal diffs for selected files.", "medium"),
                PlanStep("Approval Gate", "Require approval for multi-file edits and command execution.", "high"),
                PlanStep("Apply Changes", "Apply backups and write patches.", "medium"),
                PlanStep("Verify and Recover", "Run tests, retry once, and rollback on persistent failure.", "high"),
            ],
            risk="high" if len(target_files) > 1 else "medium",
            verify_plan=verify,
        )

    def render_plan(self, plan: Plan):
        lines = [f"Goal: {plan.goal}", f"Stack: {plan.stack}", f"Risk: {plan.risk}", "Candidates:"]
        for c in plan.candidate_files[:6]:
            lines.append(f"- {c.path} score={c.score} reasons={','.join(c.reasons)}")
        lines.append("Targets:")
        for t in plan.target_files:
            lines.append(f"- {t}")
        lines.append("Verify:")
        for v in plan.verify_plan:
            lines.append(f"- {v}")
        console.print(Panel("\\n".join(lines), title="PLAN"))

    def _run_verify(self, session: Session, commands: list[str], yes: bool = False):
        for cmd in commands:
            if not cmd:
                continue
            risk = classify_risk_for_command(cmd)
            if risk == "critical" and not ask_second_approval(f"Run critical verify command {cmd}", yes=yes):
                continue
            if ask_user_approval(f"Run verify command: {cmd}?", risk, yes=yes):
                test_res = run_tests(cmd)
                self.store.append_log(
                    session,
                    "verify",
                    {
                        "command": cmd,
                        "ok": test_res.ok,
                        "code": test_res.code,
                        "stderr": test_res.stderr,
                        "stdout": test_res.stdout,
                    },
                )
                return test_res
        return None

    def apply(
        self,
        goal: str,
        targets: list[str] | None,
        yes: bool = False,
        test_command: str | None = None,
        auto_rollback: bool = True,
        max_retries: int = 1,
        time_budget_sec: int = 240,
    ) -> ApplyResult:
        started = time.time()
        plan = self.make_plan(goal, targets)
        self.render_plan(plan)

        if not plan.target_files:
            return ApplyResult(ok=False, summary="no target files detected; specify --targets or refine goal")

        if len(plan.target_files) > 1 and not ask_user_approval(
            f"Apply changes to {len(plan.target_files)} files?", "high", yes=yes
        ):
            return ApplyResult(ok=False, summary="multi-file apply declined")

        session = self.store.create(goal, plan.target_files)
        commands = [test_command] if test_command else plan.verify_plan[:1]
        current_goal = goal
        accumulated_patches = []
        last_test_res = None

        attempt = 0
        while attempt <= max_retries:
            attempt += 1
            if time.time() - started > time_budget_sec:
                return ApplyResult(
                    ok=False,
                    summary="time budget exceeded",
                    patches=accumulated_patches,
                    test_result=last_test_res,
                    session_id=session.id,
                )

            self.store.append_log(session, "attempt_start", {"attempt": attempt, "goal": current_goal})
            attempt_patches = []

            for path in plan.target_files:
                if protected_path(path):
                    self.store.append_log(session, "protected_skipped", {"path": path})
                    continue

                try:
                    before = read_file(path)
                except Exception as e:
                    self.store.append_log(session, "read_failed", {"path": path, "error": str(e)})
                    continue

                prompt = f"Goal: {current_goal}\\nFile: {path}\\nPreview:\\n{before[:1800]}"
                resp, provider = self.providers.generate(prompt)
                after = patch_file(path, before, current_goal, resp)
                patch = build_patch(path, before, after)

                if not patch.diff.strip():
                    continue

                console.print(Panel(patch.diff, title=f"DIFF {path}"))
                if not ask_user_approval(f"Apply patch to {path}?", "medium", yes=yes):
                    self.store.append_log(session, "patch_declined", {"path": path, "attempt": attempt})
                    continue

                backup_id = self.store.save_backup(path, before)
                write_file(path, after)
                self.store.append_log(
                    session,
                    "patch_applied",
                    {"path": path, "backup_id": backup_id, "provider": provider, "attempt": attempt},
                )
                attempt_patches.append(patch)
                accumulated_patches.append(patch)

            if not attempt_patches and not accumulated_patches:
                return ApplyResult(ok=False, summary="no patches applied", session_id=session.id)

            test_res = self._run_verify(session=session, commands=commands, yes=yes)
            last_test_res = test_res
            if not test_res or test_res.ok:
                return ApplyResult(
                    ok=True,
                    summary=f"applied {len(accumulated_patches)} patch(es) in {attempt} attempt(s)",
                    patches=accumulated_patches,
                    test_result=test_res,
                    session_id=session.id,
                )

            analysis = inspect_errors((test_res.stderr or "") + "\\n" + (test_res.stdout or ""))
            self.store.append_log(session, "verify_failed_analysis", {"attempt": attempt, "analysis": analysis})

            if attempt > max_retries:
                if auto_rollback and ask_user_approval("Verify failed after retries. Roll back applied patches?", "high", yes=yes):
                    self.rollback_session(session)
                    return ApplyResult(
                        ok=False,
                        summary=f"verify failed and rolled back after {attempt} attempt(s)",
                        patches=accumulated_patches,
                        test_result=test_res,
                        session_id=session.id,
                    )
                return ApplyResult(
                    ok=False,
                    summary=f"verify failed after {attempt} attempt(s): {analysis.get('summary')}",
                    patches=accumulated_patches,
                    test_result=test_res,
                    session_id=session.id,
                )

            current_goal = (
                f"{goal}\\nRetry Fix Context:\\n{analysis.get('summary')}\\n"
                f"Hints: {', '.join(analysis.get('hints', []))}"
            )
            self.store.append_log(session, "retry_goal_refined", {"attempt": attempt + 1, "goal": current_goal})

        return ApplyResult(ok=False, summary="unexpected apply loop exit", session_id=session.id)

    def rollback_session(self, session: Session):
        for entry in reversed(session.logs):
            if entry["event"] == "patch_applied":
                backup = self.store.load_backup(entry["payload"]["backup_id"])
                write_file(backup["path"], backup["content"])
                self.store.append_log(
                    session,
                    "rollback_applied",
                    {"path": backup["path"], "backup_id": entry["payload"]["backup_id"]},
                )

    def doctor(self) -> dict:
        import shutil
        import sys

        summary = summarize_project(".")
        git_ok = shutil.which("git") is not None
        return {
            "python": sys.version.split()[0],
            "git": git_ok,
            "git_repo": (Path(".") / ".git").exists(),
            "ollama": shutil.which("ollama") is not None,
            "venv": Path(".venv").exists() or Path(".venv313").exists(),
            "stack": summary.stack,
            "suggested_tests": summary.suggested_tests,
            "target_count": len(summary.summaries),
        }
