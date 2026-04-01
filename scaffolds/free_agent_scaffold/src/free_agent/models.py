from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    IDLE = "idle"
    ANALYZE = "analyze"
    PLAN = "plan"
    GATHER_CONTEXT = "gather_context"
    EXECUTE = "execute"
    VERIFY = "verify"
    REVIEW = "review"
    REPORT = "report"
    DONE = "done"
    RECOVER = "recover"


@dataclass(slots=True)
class Plan:
    goal: str
    targets: list[str] = field(default_factory=list)
    candidate_files: list[str] = field(default_factory=list)
    verify_commands: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    recent_sessions: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ContextBundle:
    cwd: str
    git_branch: str | None
    git_status: str
    candidates: list[str]
    previews: dict[str, str]
    symbols: dict[str, list[str]]


@dataclass(slots=True)
class ExecutionResult:
    applied: bool
    summary: str
    changed_files: list[str] = field(default_factory=list)
    patch_preview: str | None = None
    approvals: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VerificationResult:
    ok: bool
    ran_commands: list[str] = field(default_factory=list)
    output: str = ""


@dataclass(slots=True)
class RunResult:
    goal: str
    state_history: list[TaskState]
    plan: Plan
    context: ContextBundle
    execution: ExecutionResult
    verification: VerificationResult
    final_report: str


@dataclass(slots=True)
class ProposedEdit:
    path: str
    original_text: str
    updated_text: str
    summary: str
    diff: str
    target_symbol: str | None = None


@dataclass(slots=True)
class SymbolReference:
    name: str
    kind: str
    path: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    goal: str
    workspace: str
    targets: list[str]
    notes: list[str] = field(default_factory=list)
