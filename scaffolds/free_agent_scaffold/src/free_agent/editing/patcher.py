from __future__ import annotations

from dataclasses import dataclass, field
from difflib import unified_diff
import re

from free_agent.config.presets import load_ui_preset_catalog
from free_agent.models import ProposedEdit, SymbolReference


@dataclass(slots=True)
class ReplacementRule:
    before: str
    after: str


@dataclass(slots=True)
class InsertRule:
    text: str
    anchor: str | None = None
    position: str = "after"
    location: str = "anchor"
    apply_all: bool = False


@dataclass(slots=True)
class DeleteRule:
    text: str


@dataclass(slots=True)
class AttributeRule:
    tag: str
    attribute: str


@dataclass(slots=True)
class DeclarationRule:
    text: str
    kind: str


@dataclass(slots=True)
class SignatureRule:
    component: str
    type_name: str
    props_pattern: str | None = None


@dataclass(slots=True)
class PropUsageRule:
    tag: str
    prop_name: str
    source_name: str | None = None
    apply_all: bool = False


@dataclass(slots=True)
class PropSetRule:
    tag: str
    prop_name: str
    value: str
    apply_all: bool = False


@dataclass(slots=True)
class ConditionalRule:
    expression: str
    anchor: str | None = None
    apply_all: bool = False


@dataclass(slots=True)
class UiPresetRule:
    tag: str
    variant: str | None = None
    class_name: str | None = None
    prop_sets: list[tuple[str, str]] = field(default_factory=list)
    prop_bindings: list[tuple[str, str]] = field(default_factory=list)
    apply_all: bool = False


@dataclass(slots=True)
class RuleSet:
    replacements: list[ReplacementRule] = field(default_factory=list)
    inserts: list[InsertRule] = field(default_factory=list)
    deletes: list[DeleteRule] = field(default_factory=list)
    attributes: list[AttributeRule] = field(default_factory=list)
    declarations: list[DeclarationRule] = field(default_factory=list)
    signatures: list[SignatureRule] = field(default_factory=list)
    prop_usages: list[PropUsageRule] = field(default_factory=list)
    prop_sets: list[PropSetRule] = field(default_factory=list)
    conditionals: list[ConditionalRule] = field(default_factory=list)
    ui_presets: list[UiPresetRule] = field(default_factory=list)


def _extract_quoted(goal: str) -> list[str]:
    return [item for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal) for item in [left or right] if item]


def _split_goal_clauses(goal: str) -> list[str]:
    clauses = [part.strip(" .,") for part in re.split(r"(?:\s+그리고\s+|하고\s+|\s+and\s+)", goal) if part.strip(" .,")]
    return clauses or [goal]


def _append_unique(items: list[object], item: object | None) -> None:
    if item is None:
        return
    if item not in items:
        items.append(item)


def infer_replacement(goal: str) -> ReplacementRule | None:
    marker = " 대신 "
    if marker not in goal:
        return None
    before, after = goal.split(marker, 1)
    before = before.strip(" .,:;\"'")
    after = after.strip(" .,:;\"'")
    before_match = re.search(r"([A-Za-z_][A-Za-z0-9_]*|\d+|[^\s]+)$", before)
    after_match = re.search(r"^([A-Za-z_][A-Za-z0-9_]*|\d+|[^\s]+)", after)
    if before_match:
        before = before_match.group(1)
    if after_match:
        after = after_match.group(1)
    if not before or not after:
        return None
    return ReplacementRule(before=before, after=after)


def infer_insert(goal: str) -> InsertRule | None:
    if "추가" not in goal:
        return None
    lower_goal = goal.lower()
    if any(
        marker in lower_goal
        for marker in (
            "속성 추가",
            "props 사용 연결",
            "type 추가",
            "interface 추가",
            "조건부 렌더링 추가",
        )
    ):
        return None
    matches = re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)
    quoted = [left or right for left, right in matches]
    if not quoted:
        return None
    text = quoted[-1]
    anchor = None
    position = "after"
    location = "anchor"
    apply_all = "모든" in goal or "all " in lower_goal
    if "import로 추가" in lower_goal or "import 추가" in lower_goal:
        return InsertRule(text=text, anchor=None, position="before", location="import", apply_all=apply_all)
    if "return 앞에" in lower_goal:
        return InsertRule(text=text, anchor="return", position="before", location="before_return", apply_all=apply_all)
    if "함수 맨 앞" in lower_goal:
        return InsertRule(text=text, anchor=None, position="after", location="function_start", apply_all=apply_all)
    if "함수 맨 끝" in lower_goal:
        return InsertRule(text=text, anchor=None, position="before", location="function_end", apply_all=apply_all)
    if "다음 줄에" in goal:
        position = "after"
        if len(quoted) >= 2:
            anchor = quoted[0]
    elif "위에" in goal:
        position = "before"
        if len(quoted) >= 2:
            anchor = quoted[0]
    return InsertRule(text=text, anchor=anchor, position=position, location=location, apply_all=apply_all)


def infer_delete(goal: str) -> DeleteRule | None:
    if "삭제" not in goal:
        return None
    match = re.search(r"'([^']+)'", goal)
    if not match:
        match = re.search(r'"([^"]+)"', goal)
    if not match:
        return None
    return DeleteRule(text=match.group(1))


def infer_attribute_insert(goal: str) -> AttributeRule | None:
    if "속성 추가" not in goal:
        return None
    direct = re.search(r'["\']([^"\']+)["\']에\s+(.+?)\s+속성 추가', goal)
    if direct is not None:
        attribute = direct.group(2).strip()
        if attribute[:1] in {"'", '"'} and attribute[-1:] == attribute[:1]:
            attribute = attribute[1:-1]
        attribute = attribute.replace('\\"', '"').replace("\\'", "'")
        return AttributeRule(tag=direct.group(1), attribute=attribute)
    quoted = [left or right for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)]
    quoted = [item for item in quoted if item]
    if len(quoted) >= 2:
        attribute = quoted[1].replace('\\"', '"').replace("\\'", "'")
        return AttributeRule(tag=quoted[0], attribute=attribute)
    return None


def infer_declaration_insert(goal: str) -> DeclarationRule | None:
    lower_goal = goal.lower()
    if "type 추가" not in lower_goal and "interface 추가" not in lower_goal:
        return None
    quoted = [left or right for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)]
    quoted = [item for item in quoted if item]
    if not quoted:
        return None
    kind = "interface" if "interface 추가" in lower_goal else "type"
    return DeclarationRule(text=quoted[-1], kind=kind)


def infer_signature_update(goal: str) -> SignatureRule | None:
    lower_goal = goal.lower()
    if "props 연결" not in lower_goal and "props 타입 연결" not in lower_goal:
        return None
    quoted = [left or right for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)]
    quoted = [item for item in quoted if item]
    if len(quoted) < 2:
        return None
    if "구조분해" in lower_goal or "destructured" in lower_goal:
        if len(quoted) < 3:
            return None
        return SignatureRule(component=quoted[0], props_pattern=quoted[1], type_name=quoted[2])
    return SignatureRule(component=quoted[0], type_name=quoted[1])


def infer_prop_usage_insert(goal: str) -> PropUsageRule | None:
    lower_goal = goal.lower()
    if "props 사용 연결" not in lower_goal:
        return None
    quoted = [left or right for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)]
    quoted = [item for item in quoted if item]
    if len(quoted) < 2:
        return None
    apply_all = "모든" in goal or "all " in lower_goal
    if len(quoted) >= 3:
        return PropUsageRule(tag=quoted[0], prop_name=quoted[1], source_name=quoted[2], apply_all=apply_all)
    return PropUsageRule(tag=quoted[0], prop_name=quoted[1], source_name=quoted[1], apply_all=apply_all)


def infer_prop_set(goal: str) -> PropSetRule | None:
    lower_goal = goal.lower()
    if "변경" not in lower_goal and "설정" not in lower_goal:
        return None
    quoted = [left or right for left, right in re.findall(r"'([^']+)'|\"([^\"]+)\"", goal)]
    quoted = [item for item in quoted if item]
    if len(quoted) < 3:
        return None
    apply_all = "모든" in goal or "all " in lower_goal
    return PropSetRule(tag=quoted[0], prop_name=quoted[1], value=quoted[2], apply_all=apply_all)


def infer_conditional_insert(goal: str) -> ConditionalRule | None:
    if "조건부 렌더링 추가" not in goal:
        return None
    quoted = _extract_quoted(goal)
    if not quoted:
        return None
    apply_all = "모든" in goal or "all " in goal.lower()
    if len(quoted) >= 2:
        return ConditionalRule(expression=quoted[-1], anchor=quoted[0], apply_all=apply_all)
    return ConditionalRule(expression=quoted[0], anchor=None, apply_all=apply_all)


def infer_ui_preset(goal: str) -> UiPresetRule | None:
    lower_goal = goal.lower()
    if "preset" not in lower_goal or "적용" not in goal:
        return None
    quoted = _extract_quoted(goal)
    if not quoted:
        return None
    tag = quoted[0]
    apply_all = "모든" in goal or "all " in lower_goal
    rule = UiPresetRule(tag=tag, apply_all=apply_all)

    matched_named_preset = False
    for preset_name, preset_values in load_ui_preset_catalog().items():
        if preset_name.lower() not in lower_goal:
            continue
        matched_named_preset = True
        if "variant" in preset_values:
            rule.variant = str(preset_values["variant"])
        if "class_name" in preset_values:
            rule.class_name = str(preset_values["class_name"])
        for prop_name, source_name in preset_values.get("prop_bindings", []):
            if (prop_name, source_name) not in rule.prop_bindings:
                rule.prop_bindings.append((str(prop_name), str(source_name)))

    for token in quoted[1:]:
        if "=" not in token:
            continue
        name, raw_value = token.split("=", 1)
        name = name.strip()
        value = raw_value.strip().replace('\\"', '"').replace("\\'", "'")
        if not name or not value:
            continue
        if name == "variant":
            rule.variant = value
            continue
        if name == "className":
            rule.class_name = value.strip('"\'')
            continue
        if (
            name == value
            or name.startswith("on")
            or name.startswith(("aria-", "data-"))
        ):
            rule.prop_bindings.append((name, value))
            continue
        if value.startswith(("{", "props.", "state.")):
            rule.prop_bindings.append((name, value.strip("{}")))
            continue
        rule.prop_sets.append((name, value))
    if not matched_named_preset and len(quoted) < 2:
        return None
    if rule.variant is None and rule.class_name is None and not rule.prop_sets and not rule.prop_bindings:
        return None
    return rule


def infer_rule_set(goal: str) -> RuleSet:
    rules = RuleSet()
    for clause in _split_goal_clauses(goal):
        _append_unique(rules.replacements, infer_replacement(clause))
        _append_unique(rules.inserts, infer_insert(clause))
        _append_unique(rules.deletes, infer_delete(clause))
        _append_unique(rules.attributes, infer_attribute_insert(clause))
        _append_unique(rules.declarations, infer_declaration_insert(clause))
        _append_unique(rules.signatures, infer_signature_update(clause))
        _append_unique(rules.prop_usages, infer_prop_usage_insert(clause))
        _append_unique(rules.prop_sets, infer_prop_set(clause))
        _append_unique(rules.conditionals, infer_conditional_insert(clause))
        _append_unique(rules.ui_presets, infer_ui_preset(clause))
    return rules


def _replace_with_boundaries(source: str, before: str, after: str) -> tuple[str, int]:
    escaped = re.escape(before)
    if re.fullmatch(r"[A-Za-z0-9_]+", before):
        pattern = rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])"
    elif before.isdigit():
        pattern = rf"(?<!\d){escaped}(?!\d)"
    else:
        pattern = escaped
    return re.subn(pattern, after, source)


def infer_target_symbol(goal: str, available_symbols: list[SymbolReference]) -> SymbolReference | None:
    lower_goal = goal.lower()
    scored: list[tuple[int, SymbolReference]] = []
    for symbol in available_symbols:
        score = 0
        if symbol.name.lower() in lower_goal:
            score += 2
        if f"{symbol.name.lower()} 함수" in lower_goal:
            score += 2
        if f"{symbol.name.lower()}에서" in lower_goal:
            score += 2
        if score:
            scored.append((score, symbol))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1].start_line, item[1].name))
    return scored[0][1]


def _replace_in_symbol_scope(
    original_text: str,
    before: str,
    after: str,
    symbol: SymbolReference,
) -> tuple[str, int]:
    lines = original_text.splitlines(keepends=True)
    start = max(symbol.start_line - 1, 0)
    end = min(symbol.end_line, len(lines))
    target_block = "".join(lines[start:end])
    updated_block, replacements = _replace_with_boundaries(target_block, before, after)
    if replacements == 0:
        return original_text, 0
    updated_lines = lines[:start] + [updated_block] + lines[end:]
    return "".join(updated_lines), replacements


def _normalize_insert_line(text: str, indent: str = "") -> str:
    line = text if text.endswith("\n") else f"{text}\n"
    return line if line.startswith(indent) else f"{indent}{line.lstrip()}"


def _detect_semicolon_style(lines: list[str]) -> bool:
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith(";"):
            return True
        if stripped.startswith(("import ", "const ", "let ", "var ", "return ", "throw ")) and not stripped.endswith("{"):
            return False
    return False


def _match_statement_style(text: str, lines: list[str]) -> str:
    stripped = text.rstrip()
    if not stripped:
        return text
    if stripped.startswith("<") or stripped.startswith("{") or stripped.endswith("/>") or "</" in stripped:
        return stripped
    if _detect_semicolon_style(lines) and not stripped.endswith((";", "{", "}", ":")):
        return f"{stripped};"
    return stripped


def _line_exists(lines: list[str], text: str) -> bool:
    needle = text.strip()
    return any(line.strip() == needle for line in lines)


def _attribute_name(attribute: str) -> str:
    return attribute.split("=", 1)[0].strip()


def _replace_existing_attribute(block: str, attribute: str) -> str:
    name = re.escape(_attribute_name(attribute))
    pattern = rf'\b{name}(?:=(?:"[^"]*"|\'[^\']*\'|\{{[^}}]*\}}))?'
    return re.sub(pattern, attribute, block, count=1)


def _has_adjacent_insert(lines: list[str], index: int, text: str, position: str) -> bool:
    needle = text.strip()
    adjacent_index = index if position == "before" else index + 1
    if adjacent_index < 0 or adjacent_index >= len(lines):
        return False
    return lines[adjacent_index].strip() == needle


def _apply_insert(source: str, rule: InsertRule) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    styled_text = rule.text if rule.location == "import" else _match_statement_style(rule.text, lines)
    insert_line = _normalize_insert_line(styled_text)
    if rule.location == "import":
        if _line_exists(lines, styled_text):
            return source, 0
        insert_at = 0
        for index, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("import ") or stripped.startswith("from "):
                insert_at = index + 1
                continue
            break
        updated = lines[:insert_at] + [insert_line] + lines[insert_at:]
        return "".join(updated), 1
    if rule.location == "before_return":
        for index, line in enumerate(lines):
            if re.search(r"\breturn\b", line):
                indent = re.match(r"^\s*", line).group(0)
                normalized_insert = _normalize_insert_line(styled_text, indent)
                if _line_exists(lines, normalized_insert):
                    return source, 0
                updated = lines[:index] + [normalized_insert] + lines[index:]
                return "".join(updated), 1
        return source, 0
    if rule.location == "function_start":
        if len(lines) <= 1:
            return source, 0
        body_index = 1
        indent = re.match(r"^\s*", lines[body_index]).group(0) if body_index < len(lines) else "    "
        normalized_insert = _normalize_insert_line(styled_text, indent)
        if _line_exists(lines, normalized_insert):
            return source, 0
        updated = lines[:body_index] + [normalized_insert] + lines[body_index:]
        return "".join(updated), 1
    if rule.location == "function_end":
        if not lines:
            return source, 0
        insert_at = len(lines)
        trailing_blank = 0
        for index in range(len(lines) - 1, -1, -1):
            if lines[index].strip() == "":
                trailing_blank += 1
                continue
            break
        insert_at = len(lines) - trailing_blank
        closing_index = insert_at - 1
        if closing_index >= 0 and lines[closing_index].strip() in {"}", "};", ")", ");"}:
            insert_at = closing_index
        indent = "    "
        for index in range(insert_at - 1, -1, -1):
            if lines[index].strip():
                indent = re.match(r"^\s*", lines[index]).group(0)
                break
        normalized_insert = _normalize_insert_line(styled_text, indent)
        if _line_exists(lines, normalized_insert):
            return source, 0
        updated = lines[:insert_at] + [normalized_insert] + lines[insert_at:]
        return "".join(updated), 1
    if rule.anchor is None:
        if rule.position == "before":
            if _line_exists(lines, styled_text):
                return source, 0
            return insert_line + source, 1
        if _line_exists(lines, styled_text):
            return source, 0
        return source + ("" if source.endswith("\n") or not source else "\n") + insert_line.rstrip("\n") + ("\n" if source else ""), 1

    index = 0
    applied = 0
    while index < len(lines):
        line = lines[index]
        if rule.anchor in line:
            indent = re.match(r"^\s*", line).group(0)
            if line.lstrip().startswith(("if ", "for ", "while ", "try", "except", "with ")) and line.rstrip().endswith(":"):
                indent = f"{indent}    "
            elif (
                line.lstrip().startswith("<")
                and not line.lstrip().startswith("</")
                and line.rstrip().endswith(">")
                and "</" not in line
            ):
                indent = f"{indent}  "
            normalized_insert = _normalize_insert_line(styled_text, indent)
            if _has_adjacent_insert(lines, index, normalized_insert, rule.position):
                index += 1
                continue
            insert_at = index if rule.position == "before" else index + 1
            lines[insert_at:insert_at] = [normalized_insert]
            applied += 1
            if not rule.apply_all:
                return "".join(lines), applied
            index = insert_at + 1
            continue
        index += 1
    return "".join(lines), applied


def _apply_delete(source: str, rule: DeleteRule) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    removed = 0
    kept: list[str] = []
    for line in lines:
        if rule.text in line and removed == 0:
            removed += 1
            continue
        kept.append(line)
    return "".join(kept), removed


def _format_jsx_value(value: str) -> str:
    if value.startswith(("{", '"', "'")):
        return value
    if value in {"true", "false"}:
        return f"{{{value}}}"
    return f'"{value}"'


def _apply_attribute_insert(source: str, rule: AttributeRule, apply_all: bool = False) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    index = 0
    applied = 0
    while index < len(lines):
        line = lines[index]
        if f"<{rule.tag}" not in line:
            index += 1
            continue
        tag_start = index
        tag_lines = [line]
        while index + 1 < len(lines) and ">" not in tag_lines[-1]:
            index += 1
            tag_lines.append(lines[index])
        block = "".join(tag_lines)
        if rule.attribute in block:
            index += 1
            continue
        if rule.attribute.startswith("className="):
            merged = _merge_classname_attribute(block, rule.attribute)
            if merged != block:
                replacement_lines = merged.splitlines(keepends=True) or [merged]
                lines[tag_start:index + 1] = replacement_lines
                applied += 1
                if not apply_all:
                    return "".join(lines), applied
                index = tag_start + len(replacement_lines)
                continue
        if re.search(rf'\b{re.escape(_attribute_name(rule.attribute))}\b', block):
            updated = _replace_existing_attribute(block, rule.attribute)
            if updated != block:
                replacement_lines = updated.splitlines(keepends=True) or [updated]
                lines[tag_start:index + 1] = replacement_lines
                applied += 1
                if not apply_all:
                    return "".join(lines), applied
                index = tag_start + len(replacement_lines)
                continue
        if len(tag_lines) > 1:
            indent_match = re.match(r"^(\s*)", tag_lines[-1])
            attr_indent = f"{indent_match.group(1)}  " if indent_match else "  "
            insertion = f"{attr_indent}{rule.attribute}\n"
            tag_lines.insert(len(tag_lines) - 1, insertion)
            lines[tag_start:index + 1] = tag_lines
            applied += 1
            if not apply_all:
                return "".join(lines), applied
            index = tag_start + len(tag_lines)
            continue
        updated = re.sub(
            rf"(<{re.escape(rule.tag)}\b)([^>]*)(/?>)",
            lambda match: f"{match.group(1)}{match.group(2).replace('/', '').rstrip()} {rule.attribute}{' /' if '/' in match.group(2) or match.group(3).startswith('/>') else ''}{'>' if match.group(3).endswith('>') else match.group(3)}",
            block,
            count=1,
        )
        if updated != block:
            lines[tag_start:index + 1] = [updated]
            applied += 1
            if not apply_all:
                return "".join(lines), applied
            index = tag_start + 1
            continue
        index += 1
    return "".join(lines), applied


def _apply_declaration_insert(source: str, rule: DeclarationRule) -> tuple[str, int]:
    lines = source.splitlines(keepends=True)
    declaration = rule.text if rule.text.endswith("\n") else f"{rule.text}\n"
    if any(line.strip() == rule.text.strip() for line in lines):
        return source, 0
    insert_at = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            insert_at = index + 1
            continue
        break
    prefix = "\n" if insert_at > 0 else ""
    suffix = "" if insert_at < len(lines) and lines[insert_at].strip() == "" else "\n"
    declaration = f"{prefix}{declaration}{suffix}"
    updated = lines[:insert_at] + [declaration] + lines[insert_at:]
    return "".join(updated), 1


def _apply_signature_update(source: str, rule: SignatureRule) -> tuple[str, int]:
    param_expr = f"{rule.props_pattern}: {rule.type_name}" if rule.props_pattern is not None else f"props: {rule.type_name}"
    patterns = [
        (
            re.compile(
                rf"(export\s+function\s+{re.escape(rule.component)}\s*)\(([^)]*)\)",
                re.MULTILINE,
            ),
            lambda match: f"{match.group(1)}({param_expr})",
        ),
        (
            re.compile(
                rf"(function\s+{re.escape(rule.component)}\s*)\(([^)]*)\)",
                re.MULTILINE,
            ),
            lambda match: f"{match.group(1)}({param_expr})",
        ),
        (
            re.compile(
                rf"(const\s+{re.escape(rule.component)}\s*=\s*\()([^)]*)(\)\s*=>)",
                re.MULTILINE,
            ),
            lambda match: f"{match.group(1)}{param_expr}{match.group(3)}",
        ),
        (
            re.compile(
                rf"(const\s+{re.escape(rule.component)}\s*=\s*)([^=]+?)(=>)",
                re.MULTILINE,
            ),
            lambda match: (
                match.group(0)
                if f": {rule.type_name}" in match.group(0)
                else f"{match.group(1)}({param_expr}) {match.group(3)}"
            ),
        ),
    ]
    for pattern, replacer in patterns:
        updated, count = pattern.subn(replacer, source, count=1)
        if count and updated != source:
            return updated, 1
    return source, 0


def _merge_classname_attribute(block: str, attribute: str) -> str:
    new_match = re.search(r'className=(["\'])([^"\']+)\1', attribute)
    if new_match is None:
        return block
    incoming = new_match.group(2).split()

    old_match = re.search(r'className=(["\'])([^"\']*)\1', block)
    if old_match is not None:
        existing = old_match.group(2).split()
        merged = _merge_tailwind_tokens(existing, incoming)
        replacement = f'className={old_match.group(1)}{" ".join(merged)}{old_match.group(1)}'
        return block[: old_match.start()] + replacement + block[old_match.end() :]

    template_match = re.search(r'className=\{`([^`]*)`\}', block)
    if template_match is not None:
        existing = template_match.group(1).split()
        merged = _merge_tailwind_tokens(existing, incoming)
        replacement = f'className={{`{" ".join(merged)}`}}'
        return block[: template_match.start()] + replacement + block[template_match.end() :]

    clsx_match = re.search(r'className=\{clsx\(([^)]*)\)\}', block)
    if clsx_match is not None:
        args = clsx_match.group(1)
        for token in incoming:
            quoted = f'"{token}"'
            squoted = f"'{token}'"
            if quoted in args or squoted in args:
                continue
            args = f'{args}, "{token}"' if args.strip() else f'"{token}"'
        replacement = f'className={{clsx({args})}}'
        return block[: clsx_match.start()] + replacement + block[clsx_match.end() :]

    return block


def _tailwind_group(token: str) -> str | None:
    prefixes = (
        "p-",
        "px-",
        "py-",
        "pt-",
        "pr-",
        "pb-",
        "pl-",
        "m-",
        "mx-",
        "my-",
        "text-",
        "bg-",
        "font-",
        "rounded",
    )
    for prefix in prefixes:
        if token.startswith(prefix):
            return prefix
    return None


def _merge_tailwind_tokens(existing: list[str], incoming: list[str]) -> list[str]:
    merged = existing[:]
    for token in incoming:
        group = _tailwind_group(token)
        if group is not None:
            merged = [item for item in merged if _tailwind_group(item) != group]
        if token not in merged:
            merged.append(token)
    return merged


def _apply_prop_usage_insert(source: str, rule: PropUsageRule) -> tuple[str, int]:
    value = rule.source_name or rule.prop_name
    attribute = f"{rule.prop_name}={{{value}}}"
    return _apply_attribute_insert(source, AttributeRule(tag=rule.tag, attribute=attribute), apply_all=rule.apply_all)


def _apply_prop_set(source: str, rule: PropSetRule) -> tuple[str, int]:
    attribute = f"{rule.prop_name}={_format_jsx_value(rule.value)}"
    return _apply_attribute_insert(source, AttributeRule(tag=rule.tag, attribute=attribute), apply_all=rule.apply_all)


def _apply_conditional_insert(source: str, rule: ConditionalRule) -> tuple[str, int]:
    insert_rule = InsertRule(
        text=rule.expression,
        anchor=rule.anchor,
        position="after",
        location="anchor",
        apply_all=rule.apply_all,
    )
    return _apply_insert(source, insert_rule)


def _apply_ui_preset(source: str, rule: UiPresetRule) -> tuple[str, int, list[str]]:
    updated = source
    applied = 0
    summaries: list[str] = []

    if rule.variant is not None:
        next_text, count = _apply_prop_set(
            updated,
            PropSetRule(tag=rule.tag, prop_name="variant", value=rule.variant, apply_all=rule.apply_all),
        )
        if count:
            updated = next_text
            applied += count
            summaries.append(f"set preset variant {rule.variant!r} on <{rule.tag}>")

    if rule.class_name is not None:
        next_text, count = _apply_attribute_insert(
            updated,
            AttributeRule(tag=rule.tag, attribute=f'className="{rule.class_name}"'),
            apply_all=rule.apply_all,
        )
        if count:
            updated = next_text
            applied += count
            summaries.append(f"merged preset className {rule.class_name!r} into <{rule.tag}>")

    for prop_name, value in rule.prop_sets:
        next_text, count = _apply_prop_set(
            updated,
            PropSetRule(tag=rule.tag, prop_name=prop_name, value=value, apply_all=rule.apply_all),
        )
        if count:
            updated = next_text
            applied += count
            summaries.append(f"set preset prop {prop_name!r} on <{rule.tag}>")

    for prop_name, source_name in rule.prop_bindings:
        next_text, count = _apply_prop_usage_insert(
            updated,
            PropUsageRule(tag=rule.tag, prop_name=prop_name, source_name=source_name, apply_all=rule.apply_all),
        )
        if count:
            updated = next_text
            applied += count
            summaries.append(f"connected preset prop {prop_name!r} usage to <{rule.tag}>")

    return updated, applied, summaries


def _apply_rule_to_text(
    original_text: str,
    rules: RuleSet,
) -> tuple[str, int, str]:
    updated_text = original_text
    total = 0
    summaries: list[str] = []

    for replacement_rule in rules.replacements:
        updated_text, count = _replace_with_boundaries(updated_text, replacement_rule.before, replacement_rule.after)
        if count:
            total += count
            summaries.append(f"replaced {replacement_rule.before!r} with {replacement_rule.after!r}")
    for signature_rule in rules.signatures:
        updated_text, count = _apply_signature_update(updated_text, signature_rule)
        if count:
            total += count
            summaries.append(f"connected props type {signature_rule.type_name!r} to {signature_rule.component}")
    for ui_preset_rule in rules.ui_presets:
        updated_text, count, preset_summaries = _apply_ui_preset(updated_text, ui_preset_rule)
        if count:
            total += count
            summaries.extend(preset_summaries)
    for prop_usage_rule in rules.prop_usages:
        updated_text, count = _apply_prop_usage_insert(updated_text, prop_usage_rule)
        if count:
            total += count
            summaries.append(f"connected prop {prop_usage_rule.prop_name!r} usage to <{prop_usage_rule.tag}>")
    for prop_set_rule in rules.prop_sets:
        updated_text, count = _apply_prop_set(updated_text, prop_set_rule)
        if count:
            total += count
            summaries.append(f"set prop {prop_set_rule.prop_name!r} on <{prop_set_rule.tag}>")
    for declaration_rule in rules.declarations:
        updated_text, count = _apply_declaration_insert(updated_text, declaration_rule)
        if count:
            total += count
            summaries.append(f"inserted {declaration_rule.kind} declaration")
    for attribute_rule in rules.attributes:
        updated_text, count = _apply_attribute_insert(updated_text, attribute_rule)
        if count:
            total += count
            summaries.append(f"inserted attribute {attribute_rule.attribute!r} into <{attribute_rule.tag}>")
    for conditional_rule in rules.conditionals:
        updated_text, count = _apply_conditional_insert(updated_text, conditional_rule)
        if count:
            total += count
            summaries.append("inserted conditional rendering block")
    for insert_rule in rules.inserts:
        updated_text, count = _apply_insert(updated_text, insert_rule)
        if count:
            total += count
            summaries.append(f"inserted line {insert_rule.text!r}")
    for delete_rule in rules.deletes:
        updated_text, count = _apply_delete(updated_text, delete_rule)
        if count:
            total += count
            summaries.append(f"deleted line containing {delete_rule.text!r}")

    return updated_text, total, "; ".join(summaries) if summaries else "no-op"


def propose_edit(
    goal: str,
    path: str,
    original_text: str,
    available_symbols: list[SymbolReference] | None = None,
) -> ProposedEdit | None:
    rules = infer_rule_set(goal)
    if (
        not rules.replacements
        and not rules.inserts
        and not rules.deletes
        and not rules.attributes
        and not rules.declarations
        and not rules.signatures
        and not rules.prop_usages
        and not rules.prop_sets
        and not rules.conditionals
        and not rules.ui_presets
    ):
        return None
    target_symbol = infer_target_symbol(goal, available_symbols or [])
    if target_symbol is not None:
        lines = original_text.splitlines(keepends=True)
        start = max(target_symbol.start_line - 1, 0)
        end = min(target_symbol.end_line, len(lines))
        target_block = "".join(lines[start:end])
        updated_block, replacements, action_summary = _apply_rule_to_text(
            original_text=target_block,
            rules=rules,
        )
        updated_text = "".join(lines[:start] + [updated_block] + lines[end:]) if replacements else original_text
    else:
        updated_text, replacements, action_summary = _apply_rule_to_text(
            original_text=original_text,
            rules=rules,
        )
    if replacements == 0:
        return None
    diff = "".join(
        unified_diff(
            original_text.splitlines(keepends=True),
            updated_text.splitlines(keepends=True),
            fromfile=path,
            tofile=path,
        )
    )
    return ProposedEdit(
        path=path,
        original_text=original_text,
        updated_text=updated_text,
        summary=(
            f"{action_summary} ({replacements} occurrence(s))"
            + (f" in symbol {target_symbol.name}" if target_symbol is not None else "")
        ),
        diff=diff,
        target_symbol=target_symbol.name if target_symbol is not None else None,
    )


def build_patch_preview(goal: str, candidates: list[str], previews: dict[str, str], symbols: dict[str, list[str]] | None = None) -> str:
    lines = [
        f"Goal: {goal}",
        "Candidate files:",
    ]
    lines.extend(f"- {path}" for path in candidates or ["none"])
    if previews:
        lines.append("Preview snippets:")
        for path, preview in previews.items():
            compact = " ".join(preview.split())
            lines.append(f"- {path}: {compact[:120]}")
    if symbols:
        lines.append("Detected symbols:")
        for path, names in symbols.items():
            lines.append(f"- {path}: {', '.join(names[:8])}")
    rules = infer_rule_set(goal)
    replacement_rule = rules.replacements[0] if rules.replacements else None
    insert_rule = rules.inserts[0] if rules.inserts else None
    delete_rule = rules.deletes[0] if rules.deletes else None
    attribute_rule = rules.attributes[0] if rules.attributes else None
    declaration_rule = rules.declarations[0] if rules.declarations else None
    signature_rule = rules.signatures[0] if rules.signatures else None
    prop_usage_rule = rules.prop_usages[0] if rules.prop_usages else None
    prop_set_rule = rules.prop_sets[0] if rules.prop_sets else None
    conditional_rule = rules.conditionals[0] if rules.conditionals else None
    ui_preset_rule = rules.ui_presets[0] if rules.ui_presets else None
    if replacement_rule is not None:
        lines.append(f"Deterministic replacement: {replacement_rule.before!r} -> {replacement_rule.after!r}")
    elif ui_preset_rule is not None:
        lines.append(f"Deterministic UI preset: <{ui_preset_rule.tag}>")
    elif signature_rule is not None:
        lines.append(f"Deterministic signature update: {signature_rule.component} -> {signature_rule.type_name}")
    elif prop_usage_rule is not None:
        lines.append(f"Deterministic prop usage insert: <{prop_usage_rule.tag}> {prop_usage_rule.prop_name}")
    elif prop_set_rule is not None:
        lines.append(f"Deterministic prop set: <{prop_set_rule.tag}> {prop_set_rule.prop_name}={prop_set_rule.value}")
    elif conditional_rule is not None:
        lines.append("Deterministic conditional rendering insert")
    elif declaration_rule is not None:
        lines.append(f"Deterministic declaration insert: {declaration_rule.kind}")
    elif attribute_rule is not None:
        lines.append(f"Deterministic attribute insert: <{attribute_rule.tag}> {attribute_rule.attribute}")
    elif insert_rule is not None:
        lines.append(f"Deterministic insert: {insert_rule.text!r}, anchor={insert_rule.anchor!r}, position={insert_rule.position}")
    elif delete_rule is not None:
        lines.append(f"Deterministic delete: line containing {delete_rule.text!r}")
    else:
        lines.append("No deterministic edit rule inferred from the goal.")
    return "\n".join(lines)
