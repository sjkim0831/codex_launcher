from __future__ import annotations

import json
import re
from pathlib import Path

from freeagent.models import FileCandidate, ProjectSummary
from freeagent.tools.file_tools import list_files, read_file, summarize_file

STACK_HINTS = {
    "react": ["package.json", "src/App.tsx", ".tsx", "react", "vite.config", "next.config"],
    "python-backend": ["requirements.txt", "pyproject.toml", ".py", "FastAPI", "flask", "django"],
    "node-backend": ["package.json", "express", "nest", "router."],
    "java-backend": ["pom.xml", ".java", "spring", "controller", "service", "repository"],
}

IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    ".venv313",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "site-packages",
    "dist",
    "build",
}

ACTION_WORDS = {
    "fix",
    "bug",
    "update",
    "change",
    "implement",
    "add",
    "remove",
    "refactor",
    "test",
    "수정",
    "변경",
    "추가",
    "삭제",
    "개선",
    "리팩토링",
    "테스트",
    "버그",
}


def _is_ignored_path(path: str) -> bool:
    parts = [part.lower() for part in Path(path).parts]
    return any(part in IGNORED_DIR_NAMES for part in parts)


def _project_files(root: str = ".") -> list[str]:
    return [f for f in list_files(root) if not _is_ignored_path(f)]


def detect_stack(root: str = ".") -> str:
    files = _project_files(root)
    joined = " ".join(files)
    scores = {"react": 0, "python-backend": 0, "node-backend": 0, "java-backend": 0}
    for stack, hints in STACK_HINTS.items():
        for hint in hints:
            if hint in joined:
                scores[stack] += 1
    if scores["react"] and scores["python-backend"]:
        return "react + python-backend"
    if scores["react"] and scores["node-backend"]:
        return "react + node-backend"
    if scores["react"] and scores["java-backend"]:
        return "react + java-backend"
    return max(scores, key=scores.get) if any(scores.values()) else "generic"


def suggest_test_commands(root: str = ".") -> list[str]:
    p = Path(root)
    cmds = []
    if (p / "pytest.ini").exists() or any(Path(f).suffix == ".py" for f in _project_files(root)):
        cmds.append("pytest -q")
    if (p / "package.json").exists():
        try:
            data = json.loads((p / "package.json").read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            if "test" in scripts:
                if (p / "pnpm-lock.yaml").exists():
                    cmds.append("pnpm test")
                else:
                    cmds.append("npm test")
        except Exception:
            pass
    return cmds or ["pytest -q"]


def summarize_project(root: str = ".") -> ProjectSummary:
    files = _project_files(root)
    summaries = {}
    for f in files[:30]:
        try:
            content = read_file(f)
        except Exception:
            continue
        summaries[f] = summarize_file(f, content)
    dirs = sorted({str(Path(f).parent) for f in files if Path(f).parent != Path(".")})[:30]
    root_files = [str(Path(f).name) for f in files[:30]]
    return ProjectSummary(
        stack=detect_stack(root),
        root_files=root_files,
        directories=dirs,
        suggested_tests=suggest_test_commands(root),
        summaries=summaries,
    )


def _extract_goal_keywords(goal: str) -> set[str]:
    goal_l = goal.lower()
    tokens = {t for t in re.findall(r"[0-9A-Za-z가-힣_]+", goal_l) if len(t) >= 2}
    if "401" in goal_l:
        tokens.add("401")
    if "500" in goal_l:
        tokens.add("500")
    if any(k in goal_l for k in ("로그인", "auth", "login")):
        tokens.update({"login", "auth"})
    if any(k in goal_l for k in ("인증", "unauthorized", "forbidden", "권한")):
        tokens.update({"auth", "unauthorized", "forbidden"})
    if any(k in goal_l for k in ("에러", "오류", "error")):
        tokens.add("error")
    if any(k in goal_l for k in ("route", "라우트", "api")):
        tokens.update({"route", "api"})
    if any(k in goal_l for k in ("frontend", "프론트", "ui", "화면")):
        tokens.update({"frontend", "ui", "component", "page"})
    if any(k in goal_l for k in ("backend", "백엔드", "서버")):
        tokens.update({"backend", "controller", "service", "repository"})
    if any(k in goal_l for k in ("menu-management", "menu", "admin", "system")):
        tokens.update({"menu", "admin", "system", "management"})
    # URL path tokens like /admin/system/menu-management
    for seg in re.findall(r"/([a-zA-Z0-9_-]+)", goal_l):
        if len(seg) >= 2:
            tokens.add(seg)
            for part in seg.split("-"):
                if len(part) >= 2:
                    tokens.add(part)
    return tokens


def _goal_has_action_intent(goal: str, tokens: set[str]) -> bool:
    if any(word in goal.lower() for word in ACTION_WORDS):
        return True
    return any(token in ACTION_WORDS for token in tokens)


def _goal_is_docs_intent(goal: str) -> bool:
    gl = goal.lower()
    return any(k in gl for k in ("readme", "docs", "documentation", "문서", "가이드", "설명"))


def _goal_is_test_intent(goal: str) -> bool:
    gl = goal.lower()
    return any(k in gl for k in ("test", "pytest", "spec", "테스트"))


def _goal_is_low_signal(goal: str, tokens: set[str]) -> bool:
    # e.g. "되나?", "가능?" 같은 짧은 확인성 문장
    compact = goal.strip().replace(" ", "")
    if len(tokens) <= 1 and len(compact) <= 5:
        return True
    return False


def _content_hint_score(path: str, tokens: set[str]) -> tuple[float, list[str]]:
    suffix = Path(path).suffix.lower()
    if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx", ".java"}:
        return 0.0, []
    try:
        if Path(path).stat().st_size > 300_000:
            return 0.0, []
        content = read_file(path).lower()[:8000]
    except Exception:
        return 0.0, []

    score = 0.0
    reasons: list[str] = []
    for token in tokens:
        if token in content:
            score += 1.5
            reasons.append(f"content:{token}")
    if {"login", "auth"} & tokens and any(k in content for k in ("status_code=500", "status(500)", "http 500", "internal server error", "httpstatus.internal_server_error")):
        score += 3.0
        reasons.append("content:status500")
    if {"menu", "admin", "system"} & tokens and any(k in content for k in ("menu", "admin", "system")):
        score += 2.0
        reasons.append("content:menu-admin-system")
    return score, reasons


def score_file(path: str, goal: str, stack: str) -> FileCandidate:
    p = path.lower().replace("\\", "/")
    goal_l = goal.lower()
    tokens = _extract_goal_keywords(goal_l)
    has_action = _goal_has_action_intent(goal, tokens)
    docs_intent = _goal_is_docs_intent(goal)
    test_intent = _goal_is_test_intent(goal)

    score = 0.0
    reasons: list[str] = []
    kind = "generic"

    for kw in tokens:
        if kw in p:
            score += 3
            reasons.append(f"path:{kw}")

    if "frontend/" in p and any(k in tokens for k in ("frontend", "ui", "component", "page", "menu", "admin", "system")):
        score += 5
        reasons.append("frontend-area")
        kind = "frontend"

    if any(seg in p for seg in ("src/main", "controller", "service", "repository")) and any(
        k in tokens for k in ("backend", "controller", "service", "repository", "menu", "admin", "system", "401", "500")
    ):
        score += 5
        reasons.append("backend-area")
        kind = "backend"

    if docs_intent and (p.endswith("readme.md") or "/docs/" in p or p.endswith(".md")):
        score += 7
        reasons.append("docs-intent")
        kind = "docs"

    if test_intent and ("/tests/" in p or p.endswith("_test.py") or p.endswith(".spec.ts") or p.endswith(".test.tsx")):
        score += 5
        reasons.append("test-intent")
        kind = "test"

    if any(seg in p for seg in ("auth", "login", "security", "account")) and any(k in tokens for k in ("auth", "login", "401", "500")):
        score += 5
        reasons.append("auth-area")
        kind = "backend"

    if "/tests/" in p or p.endswith("_test.py") or p.endswith(".test.tsx") or p.endswith(".spec.ts"):
        score += 2
        reasons.append("test-file")
        kind = "test"

    if any(seg in p for seg in ("component", "page", "src/", "frontend/")) and any(
        k in goal_l for k in ("react", "button", "toast", "ui", "화면")
    ):
        score += 5
        reasons.append("frontend")
        kind = "frontend"

    if any(seg in p for seg in ("api", "route", "controller", "service")) and any(k in tokens for k in ("api", "401", "500", "login", "auth", "route", "error")):
        score += 5
        reasons.append("backend")
        kind = "backend"

    if p.endswith(".py") and any(k in tokens for k in ("401", "500", "auth", "login")):
        score += 2
        reasons.append("python-auth-likely")

    if p.endswith(".tsx"):
        score += 2
    if p.endswith(".py") and "python" in stack and has_action and score > 0:
        score += 2
    if p.endswith((".js", ".ts")) and "node" in stack and has_action and score > 0:
        score += 2
    if p.endswith(".java") and "java" in stack and has_action and score > 0:
        score += 2

    c_score, c_reasons = _content_hint_score(path, tokens)
    score += c_score
    reasons.extend(c_reasons[:5])

    return FileCandidate(path=path, score=score, reasons=reasons, kind=kind)


def choose_files(goal: str, explicit_targets: list[str] | None = None, root: str = ".", limit: int = 6) -> list[FileCandidate]:
    if explicit_targets:
        return [FileCandidate(path=t, score=999.0, reasons=["explicit-target"]) for t in explicit_targets]

    stack = detect_stack(root)
    tokens = _extract_goal_keywords(goal)
    files = _project_files(root)
    if _goal_is_low_signal(goal, tokens):
        return sorted(
            [FileCandidate(path=f, score=1.0, reasons=["low-signal-default"]) for f in files if f.lower().endswith("readme.md")],
            key=lambda c: c.path,
        )[:1]

    candidates = [score_file(f, goal, stack) for f in files]
    filtered = [c for c in candidates if c.score > 0]
    if not filtered:
        # No meaningful match: return empty to avoid random, unsafe edits.
        return []
    filtered.sort(key=lambda c: c.score, reverse=True)
    return filtered[:limit]
# agent note: updated by FreeAgent Ultra
