from __future__ import annotations

from free_agent.memory.store import SessionStore
from free_agent.models import Plan
from free_agent.repo.indexer import RepositoryIndexer


class Planner:
    def __init__(self) -> None:
        self.indexer = RepositoryIndexer()

    def make_plan(self, goal: str, targets: list[str], workspace: str) -> Plan:
        indexed_files = self.indexer.list_files(workspace)
        symbol_map = self.indexer.collect_symbols(workspace=workspace, files=indexed_files)
        matched_symbols = self.indexer.infer_goal_symbols(goal=goal, symbols=symbol_map)
        candidate_files = self.indexer.rank_candidates(goal=goal, files=indexed_files)
        if matched_symbols:
            boosted = [
                path for path, file_symbols in symbol_map.items() if any(symbol.name in matched_symbols for symbol in file_symbols)
            ]
            candidate_files = list(dict.fromkeys(boosted + candidate_files))
        verify_commands = self._default_verify_commands(indexed_files)
        recent_sessions = SessionStore(workspace).recent_summaries()
        notes = [
            "Start with read-only context collection.",
            "Apply minimal patches before running verification.",
            "Escalate risky commands through the policy layer.",
        ]
        if matched_symbols:
            notes.append(f"Matched goal symbols: {', '.join(matched_symbols)}.")
        if recent_sessions:
            notes.append("Use recent session context to avoid repeating failed attempts.")
        return Plan(
            goal=goal,
            targets=targets,
            candidate_files=candidate_files,
            verify_commands=verify_commands,
            notes=notes,
            recent_sessions=recent_sessions,
        )

    def _default_verify_commands(self, indexed_files: list[str]) -> list[str]:
        if "tests" in {path.split("/", 1)[0] for path in indexed_files} and any(
            path.endswith("pyproject.toml") for path in indexed_files
        ):
            return ["python3 -m pytest -q"]
        if any(path.endswith("package.json") for path in indexed_files):
            return ["npm test -- --runInBand"]
        return ["echo 'no verifier configured yet'"]
