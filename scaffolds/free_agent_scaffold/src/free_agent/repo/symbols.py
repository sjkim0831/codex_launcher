from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import re

from free_agent.models import SymbolReference


@dataclass(slots=True)
class _MatchRule:
    pattern: re.Pattern[str]
    kind: str


class _PythonSymbolBackend:
    def extract(self, relative_path: str, path: Path) -> list[SymbolReference]:
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return []

        symbols: list[SymbolReference] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    SymbolReference(
                        name=node.name,
                        kind="function",
                        path=relative_path,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                    )
                )
            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    SymbolReference(
                        name=node.name,
                        kind="class",
                        path=relative_path,
                        start_line=node.lineno,
                        end_line=getattr(node, "end_lineno", node.lineno),
                    )
                )
        symbols.sort(key=lambda item: (item.start_line, item.name))
        return symbols


class _RegexJavascriptSymbolBackend:
    def __init__(self) -> None:
        self._rules = [
            _MatchRule(
                re.compile(r"^\s*(?:export\s+default\s+|export\s+)?function\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*\("),
                "function",
            ),
            _MatchRule(
                re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][A-Za-z0-9_$]*)\b"),
                "class",
            ),
            _MatchRule(
                re.compile(
                    r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?\([^)]*\)\s*=>"
                ),
                "function",
            ),
            _MatchRule(
                re.compile(
                    r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?[A-Za-z_$][A-Za-z0-9_$]*\s*=>"
                ),
                "function",
            ),
            _MatchRule(
                re.compile(
                    r"^\s*(?:export\s+)?const\s+([A-Za-z_$][A-Za-z0-9_$]*)\s*(?::[^=]+)?=\s*(?:async\s*)?function\b"
                ),
                "function",
            ),
            _MatchRule(
                re.compile(r"^\s*(?:async\s+)?([A-Za-z_$][A-Za-z0-9_$]*)\s*\([^)]*\)\s*\{"),
                "method",
            ),
            _MatchRule(
                re.compile(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(?:async\s*)?function\s*\([^)]*\)\s*\{"),
                "method",
            ),
            _MatchRule(
                re.compile(r"^\s*([A-Za-z_$][A-Za-z0-9_$]*)\s*:\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{"),
                "method",
            ),
        ]

    def extract(self, relative_path: str, path: Path) -> list[SymbolReference]:
        source = path.read_text(encoding="utf-8", errors="ignore")
        lines = source.splitlines()
        symbols: list[SymbolReference] = []

        for index, line in enumerate(lines, start=1):
            for rule in self._rules:
                match = rule.pattern.search(line)
                if not match:
                    continue
                if rule.kind == "method" and line.lstrip().startswith(("if ", "for ", "while ", "switch ", "catch ")):
                    continue
                name = match.group(1)
                end_line = self._estimate_block_end(lines=lines, start_line=index)
                symbols.append(
                    SymbolReference(
                        name=name,
                        kind=self._classify_symbol(name=name, default_kind=rule.kind),
                        path=relative_path,
                        start_line=index,
                        end_line=end_line,
                    )
                )
                break

        symbols.sort(key=lambda item: (item.start_line, item.name))
        return symbols

    def _classify_symbol(self, name: str, default_kind: str) -> str:
        if name.startswith("use") and len(name) > 3 and name[3:4].isupper():
            return "hook"
        if name[:1].isupper():
            return "component" if default_kind in {"function", "method"} else default_kind
        return default_kind

    def _estimate_block_end(self, lines: list[str], start_line: int) -> int:
        brace_depth = 0
        opened = False
        for index in range(start_line - 1, len(lines)):
            line = lines[index]
            brace_depth += line.count("{")
            if "{" in line:
                opened = True
            brace_depth -= line.count("}")
            if opened and brace_depth <= 0:
                return index + 1
        return start_line


class _TreeSitterJavascriptSymbolBackend:
    def __init__(self) -> None:
        self._backend = self._load_backend()

    def available(self) -> bool:
        return self._backend is not None

    def extract(self, relative_path: str, path: Path) -> list[SymbolReference]:
        if self._backend is None:
            return []
        return self._backend(relative_path, path)

    def _load_backend(self):
        try:
            import tree_sitter_languages  # type: ignore
        except Exception:
            return None

        def _extract(relative_path: str, path: Path) -> list[SymbolReference]:
            language_name = "tsx" if path.suffix == ".tsx" else "typescript" if path.suffix == ".ts" else "javascript"
            parser = tree_sitter_languages.get_parser(language_name)
            source = path.read_bytes()
            tree = parser.parse(source)
            lines = source.decode("utf-8", errors="ignore").splitlines()
            symbols: list[SymbolReference] = []

            def add_symbol(name: str, kind: str, start_row: int, end_row: int) -> None:
                symbols.append(
                    SymbolReference(
                        name=name,
                        kind=self._classify_symbol(name=name, default_kind=kind),
                        path=relative_path,
                        start_line=start_row + 1,
                        end_line=end_row + 1,
                    )
                )

            def text(node) -> str:
                return source[node.start_byte:node.end_byte].decode("utf-8", errors="ignore")

            def identifier_from(node):
                if node is None:
                    return None
                if getattr(node, "type", "") == "identifier":
                    return text(node)
                for child in getattr(node, "children", []):
                    found = identifier_from(child)
                    if found:
                        return found
                return None

            def walk(node) -> None:
                node_type = getattr(node, "type", "")
                if node_type in {"function_declaration", "class_declaration", "method_definition"}:
                    name = identifier_from(node.child_by_field_name("name"))
                    if name:
                        kind = "class" if node_type == "class_declaration" else "method" if node_type == "method_definition" else "function"
                        add_symbol(name, kind, node.start_point[0], node.end_point[0])
                elif node_type in {"lexical_declaration", "variable_declaration"}:
                    for child in getattr(node, "children", []):
                        if getattr(child, "type", "") != "variable_declarator":
                            continue
                        name = identifier_from(child.child_by_field_name("name"))
                        value = child.child_by_field_name("value")
                        if name and value is not None and getattr(value, "type", "") in {
                            "arrow_function",
                            "function_expression",
                        }:
                            add_symbol(name, "function", child.start_point[0], child.end_point[0])
                for child in getattr(node, "children", []):
                    walk(child)

            walk(tree.root_node)
            symbols.sort(key=lambda item: (item.start_line, item.name))
            return symbols

        return _extract

    def _classify_symbol(self, name: str, default_kind: str) -> str:
        if name.startswith("use") and len(name) > 3 and name[3:4].isupper():
            return "hook"
        if name[:1].isupper():
            return "component" if default_kind in {"function", "method"} else default_kind
        return default_kind


class SymbolIndexer:
    def __init__(self) -> None:
        self._python_backend = _PythonSymbolBackend()
        self._tree_sitter_js_backend = _TreeSitterJavascriptSymbolBackend()
        self._regex_js_backend = _RegexJavascriptSymbolBackend()

    def extract(self, workspace: str, relative_path: str) -> list[SymbolReference]:
        path = Path(workspace) / relative_path
        if not path.exists():
            return []
        if path.suffix == ".py":
            return self._python_backend.extract(relative_path=relative_path, path=path)
        if path.suffix in {".js", ".jsx", ".ts", ".tsx"}:
            if self._tree_sitter_js_backend.available():
                symbols = self._tree_sitter_js_backend.extract(relative_path=relative_path, path=path)
                if symbols:
                    return symbols
            return self._regex_js_backend.extract(relative_path=relative_path, path=path)
        return []
