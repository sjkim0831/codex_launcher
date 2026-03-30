from __future__ import annotations
import difflib, json, re
from pathlib import Path
from typing import Iterable

TEXT_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".json", ".md", ".txt", ".yml", ".yaml", ".sh"}

def is_text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES

def read_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")

def write_file(path: str, content: str) -> None:
    Path(path).write_text(content, encoding="utf-8")

def list_files(root: str = ".") -> list[str]:
    base = Path(root)
    out = []
    for p in base.rglob("*"):
        if p.is_file() and ".git" not in p.parts and ".venv" not in p.parts and ".freeagent" not in p.parts and is_text_file(p):
            out.append(str(p))
    return sorted(out)

def diff_text(old: str, new: str, path: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(keepends=True), new.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}"))

def replace_function_block(text: str, symbol: str, new_block: str) -> str:
    py_pat = re.compile(rf"(^def\s+{re.escape(symbol)}\s*\([^)]*\):[\s\S]*?)(?=^\S|\Z)", re.M)
    js_pat = re.compile(rf"((?:export\s+)?function\s+{re.escape(symbol)}\s*\([^)]*\)\s*\{{[\s\S]*?\n\}})", re.M)
    text2, n = py_pat.subn(new_block.rstrip() + "\n\n", text, count=1)
    if n:
        return text2
    text2, n = js_pat.subn(new_block.rstrip() + "\n", text, count=1)
    if n:
        return text2
    return text

def ensure_import(text: str, statement: str) -> str:
    if statement in text:
        return text
    lines = text.splitlines()
    idx = 0
    for i, line in enumerate(lines):
        if line.startswith("import ") or line.startswith("from "):
            idx = i + 1
    lines.insert(idx, statement)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")

def append_before_export_default_tsx(text: str, snippet: str) -> str:
    if snippet in text:
        return text
    m = re.search(r"export\s+default", text)
    if not m:
        return text.rstrip() + "\n\n" + snippet.rstrip() + "\n"
    return text[:m.start()].rstrip() + "\n\n" + snippet.rstrip() + "\n\n" + text[m.start():]

def summarize_file(path: str, content: str) -> str:
    head = "\n".join(content.splitlines()[:40])
    signals = []
    if "React" in content or ".tsx" in path:
        signals.append("react")
    if "FastAPI" in content or "APIRouter" in content:
        signals.append("fastapi")
    if "express" in content or "router." in content:
        signals.append("express")
    if "def " in content:
        signals.append("python-functions")
    if "export default" in content:
        signals.append("component")
    return f"{Path(path).name}: signals={','.join(signals) or 'generic'} preview={head[:240].replace(chr(10), ' ')}"
