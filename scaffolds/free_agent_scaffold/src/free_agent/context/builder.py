from __future__ import annotations

from pathlib import Path

from free_agent.models import ContextBundle
from free_agent.repo.git_state import collect_git_state
from free_agent.repo.symbols import SymbolIndexer


def build_context(workspace: str, candidates: list[str]) -> ContextBundle:
    previews: dict[str, str] = {}
    symbols: dict[str, list[str]] = {}
    root = Path(workspace)
    indexer = SymbolIndexer()
    for item in candidates:
        path = root / item
        if path.exists() and path.is_file():
            previews[item] = path.read_text(encoding="utf-8", errors="ignore")[:400]
            file_symbols = indexer.extract(workspace=workspace, relative_path=item)
            if file_symbols:
                symbols[item] = [symbol.name for symbol in file_symbols]

    git_branch, git_status = collect_git_state(workspace)
    return ContextBundle(
        cwd=workspace,
        git_branch=git_branch,
        git_status=git_status,
        candidates=candidates,
        previews=previews,
        symbols=symbols,
    )
