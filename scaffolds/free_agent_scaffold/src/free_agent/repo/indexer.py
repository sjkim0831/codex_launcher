from __future__ import annotations

from pathlib import Path

from free_agent.models import SymbolReference
from free_agent.repo.symbols import SymbolIndexer


class RepositoryIndexer:
    def __init__(self) -> None:
        self.symbols = SymbolIndexer()

    def list_files(self, workspace: str) -> list[str]:
        root = Path(workspace)
        files: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part.startswith(".git") for part in path.parts):
                continue
            if any(part in {"node_modules", "__pycache__", "build", "dist"} for part in path.parts):
                continue
            files.append(str(path.relative_to(root)))
        return sorted(files)

    def rank_candidates(self, goal: str, files: list[str], limit: int = 8) -> list[str]:
        tokens = [token.lower() for token in goal.replace("/", " ").replace("_", " ").split() if token]
        scored: list[tuple[int, str]] = []
        for path in files:
            lower = path.lower()
            score = sum(1 for token in tokens if token in lower)
            if score:
                scored.append((score, path))
        scored.sort(key=lambda item: (-item[0], item[1]))
        if scored:
            return [path for _, path in scored[:limit]]
        return files[:limit]

    def collect_symbols(self, workspace: str, files: list[str]) -> dict[str, list[SymbolReference]]:
        collected: dict[str, list[SymbolReference]] = {}
        for path in files:
            symbols = self.symbols.extract(workspace=workspace, relative_path=path)
            if symbols:
                collected[path] = symbols
        return collected

    def infer_goal_symbols(self, goal: str, symbols: dict[str, list[SymbolReference]]) -> list[str]:
        lower_goal = goal.lower()
        matches: list[str] = []
        for file_symbols in symbols.values():
            for symbol in file_symbols:
                if symbol.name.lower() in lower_goal:
                    matches.append(symbol.name)
        return sorted(set(matches))
