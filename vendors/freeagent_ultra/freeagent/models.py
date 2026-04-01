from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional, Any

@dataclass
class FileCandidate:
    path: str
    score: float
    reasons: list[str] = field(default_factory=list)
    kind: str = "generic"

@dataclass
class PlanStep:
    title: str
    detail: str
    risk: str = "medium"

@dataclass
class Plan:
    goal: str
    stack: str
    candidate_files: list[FileCandidate]
    target_files: list[str]
    steps: list[PlanStep]
    risk: str
    verify_plan: list[str] = field(default_factory=list)

@dataclass
class CommandResult:
    ok: bool
    code: int
    stdout: str
    stderr: str

@dataclass
class FilePatch:
    path: str
    before: str
    after: str
    diff: str

@dataclass
class ApplyResult:
    ok: bool
    summary: str
    patches: list[FilePatch] = field(default_factory=list)
    test_result: Optional[CommandResult] = None
    session_id: Optional[str] = None

@dataclass
class ExplainResult:
    path: Optional[str]
    symbol: Optional[str]
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class AskResult:
    answer: str
    provider: str
    details: dict[str, Any] = field(default_factory=dict)

@dataclass
class ProjectSummary:
    stack: str
    root_files: list[str]
    directories: list[str]
    suggested_tests: list[str]
    summaries: dict[str, str] = field(default_factory=dict)
