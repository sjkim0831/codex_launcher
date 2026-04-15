#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import mimetypes
import ast
from zoneinfo import ZoneInfo


KST = ZoneInfo("Asia/Seoul")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone(KST).isoformat(timespec="seconds")


def iso_from_unix_timestamp(value: Any) -> str:
    try:
        timestamp = int(value)
    except (TypeError, ValueError):
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).astimezone(KST).isoformat(timespec="seconds")


def is_past_iso(value: str) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) <= datetime.now(timezone.utc).astimezone(KST)
    except ValueError:
        return False


def is_future_iso(value: str) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(value) > datetime.now(timezone.utc).astimezone(KST)
    except ValueError:
        return False


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def read_json_or_default(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        return read_json(path)
    except Exception:
        return dict(default)


def safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = safe_text(value).strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def prompt_signal_score(text: str) -> int:
    raw = safe_text(text)
    tokens = re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}|/[A-Za-z0-9._/-]{2,}", raw)
    return sum(max(1, len(token) // 4) for token in tokens)


def prompt_looks_actionable(text: str) -> bool:
    raw = safe_text(text).strip()
    if not raw:
        return False
    if prompt_signal_score(raw) <= 0:
        return False
    lowered = raw.lower()
    if len(raw) >= 6:
        return True
    if "/" in raw or ":" in raw:
        return True
    if re.search(r"[가-힣]{2,}", raw):
        return True
    if re.search(r"\s", raw):
        return True
    if any(keyword in lowered for keyword in ("fix", "build", "debug", "review", "check", "verify", "error", "issue")):
        return True
    return False


def prompt_is_low_signal(text: str) -> bool:
    raw = safe_text(text).strip()
    if not raw:
        return True
    if prompt_looks_actionable(raw):
        return False
    score = prompt_signal_score(raw)
    if len(raw) <= 24 and score <= 2:
        return True
    if len(raw) <= 12 and score <= 3:
        return True
    return False


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_iso_datetime(value: Any) -> str:
    text = safe_text(value).strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=KST)
    return parsed.astimezone(KST).isoformat(timespec="seconds")


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def collapse_duplicate_codex_stdout(text: str) -> str:
    raw = safe_text(text)
    if not raw:
        return raw
    pattern = re.compile(
        r"(?P<first>\n(?:codex\n)?(?P<msg>[^\n].*?))\n"
        r"tokens used\n\d[\d,]*\n"
        r"(?P=msg)\n?$",
        re.DOTALL,
    )
    match = pattern.search(raw)
    if not match:
        return raw
    start = match.start("first")
    end = match.end()
    message = match.group("msg").rstrip()
    token_line_match = re.search(r"\ntokens used\n\d[\d,]*\n", raw[start:end], re.DOTALL)
    if not token_line_match:
        return raw
    token_block = token_line_match.group(0)
    rebuilt = raw[:start] + "\n" + message + token_block
    return rebuilt if end >= len(raw) else rebuilt + raw[end:]


def ansi_to_html(text: str) -> str:
    """Converts ANSI color codes to HTML span tags for web UI visibility."""
    if not text:
        return ""
    # Standard ANSI colors to CSS
    colors = {
        "31": "color: #ff5555; font-weight: bold;",  # Red
        "32": "color: #50fa7b; font-weight: bold;",  # Green
        "33": "color: #f1fa8c;",                     # Yellow
        "34": "color: #8be9fd;",                     # Blue
        "35": "color: #ff79c6;",                     # Magenta
        "36": "color: #8be9fd;",                     # Cyan
        "90": "color: #6272a4;",                     # Gray
        "1": "font-weight: bold;",                   # Bold
    }
    def replace_ansi(match: re.Match) -> str:
        code = match.group(1)
        if not code or code == "0":
            return "</span>"
        style = colors.get(code, "")
        if style:
            return f'<span style="{style}">'
        return ""

    escaped = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    html = re.sub(r"\x1b\[([0-9;]*)m", replace_ansi, escaped)
    # Basic closing of spans if left open
    open_count = html.count("<span")
    close_count = html.count("</span>")
    if open_count > close_count:
        html += "</span>" * (open_count - close_count)
    return html


def read_key_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def rewrite_js_module_imports(source: str, base_url: str) -> str:
    def proxify(specifier: str) -> str:
        if not specifier or specifier.startswith(("data:", "http://", "https://", "node:", "javascript:")):
            return specifier
        resolved = urljoin(base_url, specifier)
        return f"/api/browser/fetch?url={quote(resolved, safe='')}"

    source = re.sub(
        r"""(\bfrom\s*)(['"])([^'"]+)(['"])""",
        lambda m: f"{m.group(1)}{m.group(2)}{proxify(m.group(3))}{m.group(4)}",
        source,
    )
    source = re.sub(
        r"""(\bimport\s*)(['"])([^'"]+)(['"])""",
        lambda m: f"{m.group(1)}{m.group(2)}{proxify(m.group(3))}{m.group(4)}",
        source,
    )
    source = re.sub(
        r"""(\bimport\s*\(\s*)(['"])([^'"]+)(['"])(\s*\))""",
        lambda m: f"{m.group(1)}{m.group(2)}{proxify(m.group(3))}{m.group(4)}{m.group(5)}",
        source,
    )
    return source


@dataclass
class JobRecord:
    job_id: str
    title: str
    kind: str
    instance_id: str
    session_id: str
    session_title: str
    plan_step: str
    workspace_id: str
    workspace_label: str
    cwd: str
    command_preview: str
    status: str = "running"
    started_at: str = field(default_factory=now_iso)
    ended_at: str = ""
    exit_code: int | None = None
    output: str = ""
    final_message: str = ""
    error: str = ""
    process: subprocess.Popen[str] | None = None
    output_file: str = ""
    failover_history: list[dict[str, Any]] = field(default_factory=list)
    local_model_inspection: list[dict[str, Any]] = field(default_factory=list)
    account_chain: list[str] = field(default_factory=list)
    execution_account_id: str = ""
    execution_account_label: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "title": self.title,
            "kind": self.kind,
            "instanceId": self.instance_id,
            "sessionId": self.session_id,
            "sessionTitle": self.session_title,
            "planStep": self.plan_step,
            "workspaceId": self.workspace_id,
            "workspaceLabel": self.workspace_label,
            "cwd": self.cwd,
            "commandPreview": self.command_preview,
            "status": self.status,
            "startedAt": self.started_at,
            "endedAt": self.ended_at,
            "exitCode": self.exit_code,
            "output": self.output,
            "finalMessage": self.final_message,
            "error": self.error,
            "outputFile": self.output_file,
            "failoverHistory": self.failover_history,
            "localModelInspection": self.local_model_inspection,
            "accountChain": self.account_chain,
            "executionAccountId": self.execution_account_id,
            "executionAccountLabel": self.execution_account_label,
        }


class LauncherApp:
    def __init__(self, app_root: Path):
        self.app_root = app_root
        self.config_root = app_root / "config"
        self.static_root = app_root / "static"
        self.extension_root = app_root / "extension"
        self.data_root = app_root / "data"
        self.jobs_root = self.data_root / "jobs"
        self.accounts_root = self.data_root / "accounts"
        self.sessions_root = self.data_root / "sessions"
        self.history_file = self.data_root / "job-history.jsonl"
        self.source_roots_file = self.data_root / "source-roots.json"
        self.current_session_file = self.data_root / "current-session.txt"
        self.instances_root = self.data_root / "instances"
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.accounts_root.mkdir(parents=True, exist_ok=True)
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.instances_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.request_context = threading.local()
        self.workspaces_doc = read_json(self.config_root / "workspaces.json")
        self.actions_doc = read_json(self.config_root / "actions.json")
        self.model_routing_doc = read_json_or_default(self.config_root / "model-routing.json", {"enabled": False, "routes": {}})
        self.project_runtime_doc = read_json_or_default(self.config_root / "project-runtime.json", {"projects": []})
        self.project_assemblies_file = self.config_root / "project-assemblies.json"
        self.project_assemblies_doc = read_json_or_default(self.project_assemblies_file, {"defaultProjectId": "", "projects": []})
        self.legacy_account_overrides_file = self.config_root / "account-overrides.json"
        self.workspaces = {
            item["id"]: item
            for item in self.workspaces_doc.get("workspaces", [])
        }
        self.actions = {
            item["id"]: item
            for item in self.actions_doc.get("actions", [])
        }
        self.jobs_by_instance: dict[str, dict[str, JobRecord]] = {}
        self.login_flows: dict[str, dict[str, Any]] = {}
        self.browser_state: dict[str, Any] = {
            "currentUrl": "",
            "currentTitle": "",
            "lastSeenAt": "",
            "lastCapture": None,
            "menuSnapshot": {},
        }
        self.source_roots_by_instance: dict[str, dict[str, Any]] = {}
        self.source_roots_by_instance["default"] = self.load_source_roots("default")
        self.migrate_legacy_account_overrides()
        self.ensure_default_session()
        self.load_persisted_jobs("default")

    def current_local_model_file_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        return self.data_root / "current-local-model.json" if resolved == "default" else self.instance_root(resolved) / "current-local-model.json"

    def current_local_model_state(self, instance_id: str | None = None) -> dict[str, Any]:
        return read_json_or_default(self.current_local_model_file_path(instance_id), {})

    def save_current_local_model_state(self, doc: dict[str, Any], instance_id: str | None = None) -> None:
        path = self.current_local_model_file_path(instance_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, indent=2)

    def model_routing_settings(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        payload_doc = payload.get("modelRouting") if isinstance(payload, dict) else {}
        payload_doc = payload_doc if isinstance(payload_doc, dict) else {}
        routes = self.model_routing_doc.get("routes", {})
        if not isinstance(routes, dict):
            routes = {}
        settings = {
            "enabled": safe_bool(payload_doc.get("enabled"), safe_bool(self.model_routing_doc.get("enabled"), True)),
            "memorySafeSingleLocalModel": safe_bool(
                payload_doc.get("memorySafeSingleLocalModel"),
                safe_bool(self.model_routing_doc.get("memorySafeSingleLocalModel"), True),
            ),
            "escalateHardTasksToCodex": safe_bool(
                payload_doc.get("escalateHardTasksToCodex"),
                safe_bool(self.model_routing_doc.get("escalateHardTasksToCodex"), True),
            ),
            "allowParallelLocalWorkers": safe_bool(
                payload_doc.get("allowParallelLocalWorkers"),
                safe_bool(self.model_routing_doc.get("allowParallelLocalWorkers"), False),
            ),
            "parallelLocalWorkers": max(
                1,
                safe_int(payload_doc.get("parallelLocalWorkers"), safe_int(self.model_routing_doc.get("parallelLocalWorkers"), 1)),
            ),
            "parallelLocalSelectedModels": (
                [
                    safe_text(item).strip()
                    for item in (
                        payload_doc.get("parallelLocalSelectedModels")
                        if isinstance(payload_doc.get("parallelLocalSelectedModels"), list)
                        else self.model_routing_doc.get("parallelLocalSelectedModels", [])
                    )
                    if safe_text(item).strip()
                ]
                or ["qwen2.5-coder:1.5b", "qwen2.5-coder:3b", "qwen2.5-coder:7b"]
            ),
            "parallelLocalKeepLoaded": safe_bool(
                payload_doc.get("parallelLocalKeepLoaded"),
                safe_bool(self.model_routing_doc.get("parallelLocalKeepLoaded"), False),
            ),
            "parallelLocalAllLoadedRequired": safe_bool(
                payload_doc.get("parallelLocalAllLoadedRequired"),
                safe_bool(self.model_routing_doc.get("parallelLocalAllLoadedRequired"), False),
            ),
            "parallelLocalFinalSynthesizer": self.normalize_parallel_local_synthesizer_mode(
                payload_doc.get("parallelLocalFinalSynthesizer", self.model_routing_doc.get("parallelLocalFinalSynthesizer", "ready-first"))
            ),
            "parallelLocalFinalSynthesizerModel": safe_text(
                payload_doc.get(
                    "parallelLocalFinalSynthesizerModel",
                    self.model_routing_doc.get("parallelLocalFinalSynthesizerModel", "qwen2.5-coder:7b"),
                )
            ).strip() or "qwen2.5-coder:7b",
            "simpleTaskLocalParallel": safe_bool(
                payload_doc.get("simpleTaskLocalParallel"),
                safe_bool(self.model_routing_doc.get("simpleTaskLocalParallel"), True),
            ),
            "simpleTaskLocalPresets": [
                safe_text(item).strip().lower()
                for item in self.model_routing_doc.get("simpleTaskLocalPresets", ["saver", "question", "summary", "lite"])
                if safe_text(item).strip()
            ],
            "parallelAccountMax": max(
                1,
                safe_int(
                    payload_doc.get("parallelAccountMax"),
                    safe_int(
                        self.model_routing_doc.get("parallelAccountMax"),
                        safe_int(os.environ.get("CARBONET_CODEX_PARALLEL_ACCOUNTS_MAX"), 14),
                    ),
                ),
            ),
            "parallelAccountPresetLimits": self.model_routing_doc.get("parallelAccountPresetLimits", {}),
            "routes": routes,
            "hardTaskPresets": [
                safe_text(item).strip().lower()
                for item in self.model_routing_doc.get("hardTaskPresets", [])
                if safe_text(item).strip()
            ],
            "scoutModels": self.model_routing_doc.get("scoutModels", {}),
        }
        return settings

    def normalize_parallel_local_synthesizer_mode(self, value: Any) -> str:
        mode = safe_text(value).strip().lower()
        return mode if mode in {"off", "ready-first", "local-7b", "codex"} else "ready-first"

    def local_scout_models(self, settings: dict[str, Any], preset: str, primary_model: str) -> list[str]:
        selected_models = settings.get("parallelLocalSelectedModels")
        if isinstance(selected_models, list) and selected_models:
            candidates = [safe_text(item).strip() for item in selected_models if safe_text(item).strip()]
        else:
            scout_doc = settings.get("scoutModels", {})
            scout_items = scout_doc.get(preset, []) if isinstance(scout_doc, dict) else []
            candidates = [safe_text(primary_model).strip()]
            if isinstance(scout_items, list):
                candidates.extend(safe_text(item).strip() for item in scout_items if safe_text(item).strip())
        unique: list[str] = []
        for item in candidates:
            if item and item not in unique:
                unique.append(item)
        limit = max(1, safe_int(settings.get("parallelLocalWorkers"), 1))
        return unique[:limit]

    def parallel_account_allocation_limit(self, settings: dict[str, Any], preset: str) -> int:
        max_accounts = max(1, safe_int(settings.get("parallelAccountMax"), 14))
        default_limits = {
            "saver": 0,
            "question": 0,
            "summary": 0,
            "lite": 0,
            "migration": 6,
            "implementation": 6,
            "balanced": 6,
            "review": 10,
            "debug": 10,
            "full": max_accounts,
            "custom": 6,
        }
        configured = settings.get("parallelAccountPresetLimits", {})
        raw_limit = default_limits.get(safe_text(preset).strip().lower(), 6)
        if isinstance(configured, dict) and safe_text(preset).strip().lower() in configured:
            raw_limit = safe_int(configured.get(safe_text(preset).strip().lower()), raw_limit)
        return max(0, min(max_accounts, safe_int(raw_limit, raw_limit)))

    def project_runtime_projects(self) -> list[dict[str, Any]]:
        items = self.project_runtime_doc.get("projects", [])
        return items if isinstance(items, list) else []

    def save_project_assemblies(self) -> None:
        self.project_assemblies_file.write_text(
            json.dumps(self.project_assemblies_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def project_assemblies(self) -> dict[str, Any]:
        projects = self.project_assemblies_doc.get("projects", [])
        if not isinstance(projects, list):
            projects = []
        normalized: list[dict[str, Any]] = []
        for item in projects:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["id"] = safe_text(row.get("id")).strip()
            row["label"] = safe_text(row.get("label")).strip() or row["id"]
            row["path"] = safe_text(row.get("path")).strip()
            row["exists"] = Path(row["path"]).exists() if row["path"] else False
            row["commonModules"] = row.get("commonModules") if isinstance(row.get("commonModules"), list) else []
            row["projectModules"] = row.get("projectModules") if isinstance(row.get("projectModules"), list) else []
            row["commands"] = row.get("commands") if isinstance(row.get("commands"), dict) else {}
            if row["id"]:
                normalized.append(row)
        return {
            "defaultProjectId": safe_text(self.project_assemblies_doc.get("defaultProjectId")),
            "projects": normalized,
        }

    def find_project_assembly(self, project_path: str = "", project_id: str = "") -> dict[str, Any] | None:
        normalized_path = safe_text(project_path).strip()
        resolved_path = ""
        if normalized_path:
            try:
                resolved_path = str(Path(normalized_path).resolve())
            except OSError:
                resolved_path = normalized_path
        project_id = safe_text(project_id).strip()
        for item in self.project_assemblies().get("projects", []):
            if project_id and safe_text(item.get("id")) == project_id:
                return item
            item_path = safe_text(item.get("path")).strip()
            try:
                item_path = str(Path(item_path).resolve())
            except OSError:
                pass
            if resolved_path and item_path == resolved_path:
                return item
        return None

    def upsert_project_assembly(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", safe_text(payload.get("id")).strip()).strip("-").lower()
        project_path = safe_text(payload.get("path")).strip()
        if not project_path:
            raise ValueError("project path is required")
        resolved_path = str(self.resolve_project_path(project_path))
        if not project_id:
            project_id = Path(resolved_path).name.lower()
        label = safe_text(payload.get("label")).strip() or project_id
        projects = self.project_assemblies_doc.setdefault("projects", [])
        if not isinstance(projects, list):
            projects = []
            self.project_assemblies_doc["projects"] = projects
        existing = next((item for item in projects if isinstance(item, dict) and safe_text(item.get("id")) == project_id), None)
        if existing is None:
            existing = {
                "id": project_id,
                "commands": {},
            }
            projects.append(existing)
        existing.update(
            {
                "id": project_id,
                "label": label,
                "path": resolved_path,
                "adapterType": safe_text(payload.get("adapterType")).strip() or safe_text(existing.get("adapterType")),
                "commonAdapter": safe_text(payload.get("commonAdapter")).strip() or safe_text(existing.get("commonAdapter")),
                "appModule": safe_text(payload.get("appModule")).strip() or safe_text(existing.get("appModule")),
                "runtimePort": safe_int(payload.get("runtimePort"), safe_int(existing.get("runtimePort"), 0)),
                "healthUrl": safe_text(payload.get("healthUrl")).strip() or safe_text(existing.get("healthUrl")),
            }
        )
        if not safe_text(self.project_assemblies_doc.get("defaultProjectId")):
            self.project_assemblies_doc["defaultProjectId"] = project_id
        self.save_project_assemblies()
        return {
            "saved": True,
            "item": existing,
            "projectAssemblies": self.project_assemblies(),
        }

    def project_assembly_status(self, project_path: str = "", project_id: str = "") -> dict[str, Any]:
        assembly = self.find_project_assembly(project_path=project_path, project_id=project_id)
        if assembly is None:
            return {
                "matched": False,
                "projectPath": project_path,
                "message": "No project assembly profile matched this project.",
            }
        runtime = self.project_runtime_status(safe_text(assembly.get("path")))
        return {
            "matched": True,
            "assembly": assembly,
            "runtime": runtime,
            "commonJarCount": len(assembly.get("commonModules") or []),
            "projectModuleCount": len(assembly.get("projectModules") or []),
            "adapterType": safe_text(assembly.get("adapterType")),
            "commonAdapter": safe_text(assembly.get("commonAdapter")),
        }

    def run_project_assembly_action(self, payload: dict[str, Any], action_name: str) -> dict[str, Any]:
        project_path = safe_text(payload.get("projectPath")).strip()
        project_id = safe_text(payload.get("projectId")).strip()
        assembly = self.find_project_assembly(project_path=project_path, project_id=project_id)
        if assembly is None:
            raise ValueError("No project assembly profile matched this project.")
        commands = assembly.get("commands") if isinstance(assembly.get("commands"), dict) else {}
        shell_command = safe_text(commands.get(action_name)).strip()
        if not shell_command:
            raise ValueError(f"Project assembly action is not configured: {action_name}")
        workspace = self.resolve_workspace({"projectPath": safe_text(assembly.get("path"))})
        session = self.resolve_session(payload, workspace)
        title = f"{safe_text(assembly.get('label') or assembly.get('id'))} {action_name}"
        return self.enqueue_job_spec(
            title=title,
            kind="shell",
            cwd=safe_text(assembly.get("path")),
            command=["bash", "-lc", shell_command.replace("{projectPath}", shlex.quote(safe_text(assembly.get("path"))))],
            command_preview=shell_command,
            workspace=workspace,
            session=session,
            plan_step=safe_text(payload.get("planStep")).strip(),
        )

    def resolve_project_runtime_target(self, project_path: str) -> dict[str, Any] | None:
        normalized = safe_text(project_path).strip()
        if not normalized:
            return None
        for item in self.project_runtime_projects():
            needle = safe_text(item.get("pathContains")).strip()
            if needle and needle in normalized:
                return item
        return None

    def project_runtime_status(self, project_path: str) -> dict[str, Any]:
        target = self.resolve_project_runtime_target(project_path)
        if target is None:
            return {
                "matched": False,
                "projectPath": project_path,
                "message": "No runtime control profile matched this project path.",
            }
        health_url = safe_text(target.get("healthUrl")).strip()
        health_ok = False
        health_body = ""
        if health_url:
            try:
                with urlopen(health_url, timeout=3) as response:
                    health_body = response.read().decode("utf-8", errors="ignore").strip()
                    health_ok = response.status == 200 and ("UP" in health_body or "ok" in health_body.lower())
            except Exception as exc:
                health_body = safe_text(exc)
        return {
            "matched": True,
            "projectId": safe_text(target.get("id")),
            "label": safe_text(target.get("label")),
            "projectPath": project_path,
            "healthUrl": health_url,
            "healthOk": health_ok,
            "healthBody": health_body,
            "commands": target.get("commands", {}),
        }

    def determine_model_route(
        self,
        payload: dict[str, Any],
        action: dict[str, Any] | None,
        cli_id: str,
        requested_model: str,
    ) -> dict[str, Any]:
        settings = self.model_routing_settings(payload)
        preset = self.runtime_preset_for_payload(payload, action)
        explicit_cli = safe_text(payload.get("cli")).strip().lower()
        result = {
            "cli": cli_id,
            "model": requested_model,
            "preset": preset,
            "note": "",
            "settings": settings,
        }
        if (
            safe_text(payload.get("mode")).strip() == "assistant_custom"
            and explicit_cli in {"codex", "minimax-codex", "freeagent", "minimax"}
        ):
            result["cli"] = explicit_cli
            result["note"] = f"manual cli={explicit_cli}"
            if explicit_cli in {"freeagent", "minimax"} and self.prompt_requests_file_change(payload):
                result["freeagentMode"] = "apply"
                result["note"] += " apply"
            return result
        if not settings.get("enabled"):
            return result
        hard_presets = set(settings.get("hardTaskPresets", []))
        if settings.get("escalateHardTasksToCodex") and preset in hard_presets:
            result["cli"] = "codex"
            result["model"] = ""
            result["note"] = f"preset={preset} escalated to codex"
            return result
        route_model = safe_text(settings.get("routes", {}).get(preset)).strip()
        if cli_id in {"codex", "minimax-codex"}:
            if route_model.lower() == "codex":
                result["cli"] = "codex"
                result["model"] = ""
                result["note"] = f"preset={preset} routed to codex"
                return result
            if route_model:
                result["cli"] = "freeagent"
                result["model"] = route_model
                result["note"] = f"preset={preset} routed from codex to local {route_model}"
                if self.prompt_requests_file_change(payload):
                    result["freeagentMode"] = "apply"
                    result["note"] += " apply"
                return result
            result["note"] = "model routing skipped for codex-compatible cli"
            return result
        if route_model.lower() == "codex":
            result["cli"] = "codex"
            result["model"] = ""
            result["note"] = f"preset={preset} routed to codex"
            return result
        if route_model:
            result["cli"] = "freeagent"
            result["model"] = route_model
            result["note"] = f"preset={preset} routed to {route_model}"
            if self.prompt_requests_file_change(payload):
                result["freeagentMode"] = "apply"
                result["note"] += " apply"
            return result
        return result

    def ollama_stop_model(self, model: str) -> tuple[bool, str]:
        target = safe_text(model).strip()
        if not target:
            return False, "model is empty"
        if shutil.which("ollama") is None:
            return False, "ollama is not installed"
        completed = subprocess.run(
            ["ollama", "stop", target],
            text=True,
            capture_output=True,
            check=False,
        )
        output = "\n".join(
            part for part in [safe_text(completed.stdout).strip(), safe_text(completed.stderr).strip()] if part
        ).strip()
        return completed.returncode == 0, output or ("stopped" if completed.returncode == 0 else "stop failed")

    def enforce_single_local_model(self, instance_id: str, job_id: str, env_overrides: dict[str, str] | None) -> None:
        env_doc = env_overrides or {}
        if safe_text(env_doc.get("FREEAGENT_PROVIDER")).strip() == "minimax":
            return
        if not safe_bool(env_doc.get("CARBONET_SINGLE_LOCAL_MODEL"), False):
            return
        next_model = safe_text(env_doc.get("FREEAGENT_MODEL")).strip()
        if not next_model:
            return
        state = self.current_local_model_state(instance_id)
        previous_model = safe_text(state.get("model")).strip()
        previous_provider = safe_text(state.get("provider")).strip()
        if previous_model and previous_model != next_model and previous_provider == "ollama":
            ok, message = self.ollama_stop_model(previous_model)
            self.append_job_runtime_event(
                job_id,
                f"single-local-model: unload {previous_model} -> {'ok' if ok else 'skip'} ({message})",
            )
        self.save_current_local_model_state(
            {
                "provider": "ollama",
                "model": next_model,
                "updatedAt": now_iso(),
            },
            instance_id,
        )

    def save_actions_doc(self) -> None:
        with (self.config_root / "actions.json").open("w", encoding="utf-8") as handle:
            json.dump(self.actions_doc, handle, ensure_ascii=False, indent=2)

    def refresh_actions_index(self) -> None:
        self.actions = {
            item["id"]: item
            for item in self.actions_doc.get("actions", [])
            if item.get("id")
        }

    def migrate_legacy_account_overrides(self) -> None:
        if not self.legacy_account_overrides_file.exists():
            return
        legacy = read_json_or_default(self.legacy_account_overrides_file, {"accounts": []})
        items = legacy.get("accounts", [])
        if not isinstance(items, list) or not items:
            return
        slots = self.list_account_slots()
        changed = False
        for item in items:
            if not isinstance(item, dict):
                continue
            slot = next(
                (
                    candidate
                    for candidate in slots
                    if safe_text(candidate.get("id")).strip() == safe_text(item.get("id")).strip()
                    or safe_text(candidate.get("email")).strip().lower() == safe_text(item.get("email")).strip().lower()
                    or safe_text(candidate.get("accountId")).strip() == safe_text(item.get("accountId")).strip()
                ),
                None,
            )
            if not slot:
                continue
            slot_id = safe_text(slot.get("id")).strip()
            if not slot_id:
                continue
            metadata_path = self.accounts_root_path() / slot_id / "metadata.json"
            if not metadata_path.exists():
                continue
            metadata = read_json(metadata_path)
            merged = dict(metadata)
            for key in (
                "accountType",
                "planType",
                "nextAvailableAt",
                "paidPlanExpiresAt",
                "manualStatus",
                "manualBlockedUntil",
                "manualNote",
                "notes",
            ):
                if key in item:
                    merged[key] = item.get(key)
            if merged != metadata:
                merged["updatedAt"] = now_iso()
                with metadata_path.open("w", encoding="utf-8") as handle:
                    json.dump(merged, handle, ensure_ascii=False, indent=2)
                changed = True
        if changed:
            print(f"Migrated legacy account overrides from {self.legacy_account_overrides_file} into account metadata.")

    def normalize_instance_id(self, value: str) -> str:
        raw = safe_text(value).strip().lower()
        if not raw or raw == "default":
            return "default"
        cleaned = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-")
        return cleaned or "default"

    def set_request_instance(self, instance_id: str) -> None:
        self.request_context.instance_id = self.normalize_instance_id(instance_id)

    def clear_request_instance(self) -> None:
        if hasattr(self.request_context, "instance_id"):
            delattr(self.request_context, "instance_id")

    def current_instance_id(self) -> str:
        return self.normalize_instance_id(getattr(self.request_context, "instance_id", "default"))

    def instance_root(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        if resolved == "default":
            return self.data_root
        root = self.instances_root / resolved
        root.mkdir(parents=True, exist_ok=True)
        return root

    def jobs_root_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        root = self.jobs_root if resolved == "default" else self.instance_root(resolved) / "jobs"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def accounts_root_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        root = self.accounts_root if resolved == "default" else self.instance_root(resolved) / "accounts"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def sessions_root_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        root = self.sessions_root if resolved == "default" else self.instance_root(resolved) / "sessions"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def history_file_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        return self.history_file if resolved == "default" else self.instance_root(resolved) / "job-history.jsonl"

    def source_roots_file_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        return self.source_roots_file if resolved == "default" else self.instance_root(resolved) / "source-roots.json"

    def jobs_store(self, instance_id: str | None = None) -> dict[str, JobRecord]:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        store = self.jobs_by_instance.get(resolved)
        if store is None:
            store = {}
            self.jobs_by_instance[resolved] = store
        return store

    def source_roots_doc(self, instance_id: str | None = None) -> dict[str, Any]:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        doc = self.source_roots_by_instance.get(resolved)
        if doc is None:
            doc = self.load_source_roots(resolved)
            self.source_roots_by_instance[resolved] = doc
        return doc

    def current_session_file_path(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        if resolved == "default":
            return self.current_session_file
        return self.instance_root(resolved) / "current-session.txt"

    def instance_process_env(self, instance_id: str | None = None) -> dict[str, str]:
        return {
            "CARBONET_CODEX_HOME": str(self.codex_home(instance_id)),
        }

    def login_flow_state(self, instance_id: str | None = None) -> dict[str, Any]:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        flow = self.login_flows.get(resolved)
        if flow is None:
            flow = {}
            self.login_flows[resolved] = flow
        return flow

    def bootstrap(self) -> dict[str, Any]:
        login = self.login_status()
        current_session = self.current_session()
        return {
            "instanceId": self.current_instance_id(),
            "defaultWorkspaceId": self.workspaces_doc.get("defaultWorkspaceId", ""),
            "workspaces": self.workspaces_doc.get("workspaces", []),
            "actions": self.actions_doc.get("actions", []),
            "codexVersion": self.codex_version(),
            "loginReady": login.get("loggedIn", False),
            "accounts": self.list_accounts(),
            "currentAccountId": self.current_account_id(),
            "currentAccount": login.get("currentAccount", {}),
            "runtimeRoot": str(Path.cwd()),
            "codexHome": str(self.codex_home()),
            "cliOptions": [
                {"id": "codex", "label": "Codex", "description": "OpenAI Codex CLI"},
                {"id": "freeagent", "label": "FreeAgent", "description": "Vendored FreeAgent Ultra"},
                {"id": "minimax", "label": "MiniMax 2.7", "description": "FreeAgent runtime with MiniMax provider"},
                {"id": "minimax-codex", "label": "MiniMax Codex Compat", "description": "Codex-like exec wrapper backed by MiniMax"},
            ],
            "freeagent": self.freeagent_config(),
            "modelRouting": self.model_routing_settings(),
            "currentLocalModel": self.current_local_model_state(),
            "projectRuntime": {
                "projects": self.project_runtime_projects(),
            },
            "projectAssemblies": self.project_assemblies(),
            "browser": self.browser_status(),
            "browserExtension": self.browser_extension_info(),
            "reference": self.reference_status(),
            "projectRoots": self.list_roots("project"),
            "referenceRoots": self.list_roots("reference"),
            "sessions": self.list_sessions(),
            "currentSessionId": current_session.get("id", ""),
            "currentSession": current_session,
        }

    def session_path(self, session_id: str) -> Path:
        return self.sessions_root_path() / session_id / "session.json"

    def job_record_path(self, job_id: str, instance_id: str | None = None) -> Path:
        return self.jobs_root_path(instance_id) / f"{job_id}.json"

    def legacy_output_file(self, job_id: str, instance_id: str | None = None) -> Path:
        return self.jobs_root_path(instance_id) / f"{job_id}-final.txt"

    def recover_legacy_job_output(self, job_id: str, command_preview: str, instance_id: str | None = None) -> tuple[str, str]:
        output_file = self.legacy_output_file(job_id, instance_id)
        if output_file.exists():
            text = output_file.read_text(encoding="utf-8").strip()
            return text, str(output_file)
        preview = self.summarize_text(command_preview, 400)
        return preview, ""

    def create_session_doc(
        self,
        title: str,
        workspace_id: str = "",
        project_path: str = "",
    ) -> dict[str, Any]:
        session_id = uuid.uuid4().hex[:12]
        now = now_iso()
        return {
            "id": session_id,
            "title": title.strip() or f"Session {now}",
            "parentSessionId": "",
            "workspaceId": workspace_id,
            "projectPath": project_path,
            "createdAt": now,
            "updatedAt": now,
            "lastJobId": "",
            "summary": "",
            "notes": "",
            "plan": [],
            "recentJobs": [],
        }

    def load_session(self, session_id: str) -> dict[str, Any]:
        path = self.session_path(session_id)
        if not path.exists():
            raise ValueError(f"Unknown session: {session_id}")
        return read_json(path)

    def save_session(self, session_doc: dict[str, Any]) -> dict[str, Any]:
        session_doc["updatedAt"] = now_iso()
        path = self.session_path(safe_text(session_doc.get("id")))
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            json.dump(session_doc, handle, ensure_ascii=False, indent=2)
        return session_doc

    def current_session_id(self) -> str:
        current_session_file = self.current_session_file_path()
        if current_session_file.exists():
            session_id = current_session_file.read_text(encoding="utf-8").strip()
            if session_id and self.session_path(session_id).exists():
                return session_id
        sessions = self.list_sessions()
        if sessions:
            session_id = safe_text(sessions[0].get("id"))
            if session_id:
                current_session_file.write_text(session_id, encoding="utf-8")
                return session_id
        session = self.save_session(self.create_session_doc("Default Session"))
        current_session_file.write_text(session["id"], encoding="utf-8")
        return session["id"]

    def current_session(self) -> dict[str, Any]:
        return self.load_session(self.current_session_id())

    def ensure_legacy_session(self) -> dict[str, Any]:
        session_id = "legacy-history"
        path = self.session_path(session_id)
        if path.exists():
            return read_json(path)
        now = now_iso()
        session = {
            "id": session_id,
            "title": "Legacy History",
            "parentSessionId": "",
            "workspaceId": "",
            "projectPath": "",
            "createdAt": now,
            "updatedAt": now,
            "lastJobId": "",
            "summary": "Pre-session historical jobs restored from job-history.jsonl",
            "notes": "Pre-session historical jobs restored from job-history.jsonl",
            "plan": [],
            "recentJobs": [],
        }
        return self.save_session(session)

    def load_persisted_jobs(self, instance_id: str | None = None) -> None:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        store = self.jobs_store(resolved)
        store.clear()
        loaded_ids: set[str] = set()
        for path in sorted(self.jobs_root_path(resolved).glob("*.json")):
            try:
                doc = read_json(path)
            except Exception:
                continue
            status = safe_text(doc.get("status")) or "failed"
            ended_at = safe_text(doc.get("endedAt"))
            error = safe_text(doc.get("error"))
            if status == "running":
                status = "failed"
                ended_at = ended_at or now_iso()
                error = error or "Launcher restarted before the job finished."
            job = JobRecord(
                job_id=safe_text(doc.get("jobId")),
                title=safe_text(doc.get("title")),
                kind=safe_text(doc.get("kind")),
                instance_id=safe_text(doc.get("instanceId")) or resolved,
                session_id=safe_text(doc.get("sessionId")),
                session_title=safe_text(doc.get("sessionTitle")),
                plan_step=safe_text(doc.get("planStep")),
                workspace_id=safe_text(doc.get("workspaceId")),
                workspace_label=safe_text(doc.get("workspaceLabel")),
                cwd=safe_text(doc.get("cwd")),
                command_preview=safe_text(doc.get("commandPreview")),
                status=status,
                started_at=safe_text(doc.get("startedAt")) or now_iso(),
                ended_at=ended_at,
                exit_code=doc.get("exitCode"),
                output=safe_text(doc.get("output")),
                final_message=safe_text(doc.get("finalMessage")),
                error=error,
                output_file=safe_text(doc.get("outputFile")),
                failover_history=doc.get("failoverHistory") if isinstance(doc.get("failoverHistory"), list) else [],
                local_model_inspection=doc.get("localModelInspection") if isinstance(doc.get("localModelInspection"), list) else [],
                account_chain=doc.get("accountChain") if isinstance(doc.get("accountChain"), list) else [],
                execution_account_id=safe_text(doc.get("executionAccountId")),
                execution_account_label=safe_text(doc.get("executionAccountLabel")),
            )
            if job.job_id:
                store[job.job_id] = job
                loaded_ids.add(job.job_id)
        history_file = self.history_file_path(resolved)
        if not history_file.exists():
            return
        legacy_session = self.ensure_legacy_session()
        for raw in history_file.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                doc = json.loads(raw)
            except Exception:
                continue
            job_id = safe_text(doc.get("jobId"))
            if not job_id or job_id in loaded_ids:
                continue
            session_id = safe_text(doc.get("sessionId")) or safe_text(legacy_session.get("id"))
            session_title = safe_text(doc.get("sessionTitle")) or (
                safe_text(legacy_session.get("title")) if session_id == legacy_session.get("id") else ""
            )
            job = JobRecord(
                job_id=job_id,
                title=safe_text(doc.get("title")),
                kind=safe_text(doc.get("kind")),
                instance_id=safe_text(doc.get("instanceId")) or resolved,
                session_id=session_id,
                session_title=session_title,
                plan_step=safe_text(doc.get("planStep")),
                workspace_id=safe_text(doc.get("workspaceId")),
                workspace_label=safe_text(doc.get("workspaceLabel")),
                cwd="",
                command_preview=safe_text(doc.get("commandPreview")),
                status=safe_text(doc.get("status")) or "failed",
                started_at=safe_text(doc.get("startedAt")) or now_iso(),
                ended_at=safe_text(doc.get("endedAt")),
                exit_code=doc.get("exitCode"),
                output="",
                final_message="",
                error="",
                output_file="",
                execution_account_id="",
                execution_account_label="",
            )
            recovered_output, recovered_file = self.recover_legacy_job_output(job_id, job.command_preview, resolved)
            job.final_message = recovered_output
            job.output = recovered_output
            job.output_file = recovered_file
            store[job.job_id] = job
            loaded_ids.add(job.job_id)

    def recover_jobs(self) -> dict[str, Any]:
        selected_job_id = safe_text(self.current_session().get("lastJobId"))
        self.load_persisted_jobs()
        store = self.jobs_store()
        recovered = len(store)
        current_job = None
        if selected_job_id and selected_job_id in store:
            current_job = store[selected_job_id].as_dict()
        elif store:
            latest = sorted(
                store.values(),
                key=lambda item: (
                    safe_text(item.started_at),
                    safe_text(item.job_id),
                ),
                reverse=True,
            )[0]
            current_job = latest.as_dict()
        return {
            "recovered": recovered,
            "currentJob": current_job,
            "items": self.list_jobs(),
            "sessions": self.list_sessions(),
            "currentSessionId": self.current_session_id(),
            "currentSession": self.current_session(),
            "message": f"Recovered {recovered} jobs from disk history.",
        }

    def ensure_default_session(self) -> None:
        self.current_session_id()

    def list_sessions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        active_id = ""
        current_session_file = self.current_session_file_path()
        if current_session_file.exists():
            active_id = current_session_file.read_text(encoding="utf-8").strip()
        for session_path in sorted(self.sessions_root_path().glob("*/session.json")):
            try:
                item = read_json(session_path)
            except Exception:
                continue
            item["isActive"] = safe_text(item.get("id")) == active_id
            items.append(item)
        items.sort(key=lambda item: safe_text(item.get("updatedAt")), reverse=True)
        return items

    def create_session(
        self,
        title: str,
        workspace_id: str = "",
        project_path: str = "",
    ) -> dict[str, Any]:
        session = self.save_session(self.create_session_doc(title, workspace_id, project_path))
        self.current_session_file_path().write_text(session["id"], encoding="utf-8")
        return {
            "session": session,
            "items": self.list_sessions(),
            "currentSessionId": session["id"],
        }

    def create_branch_session(self, session_id: str, title: str = "") -> dict[str, Any]:
        source = self.load_session(session_id)
        branch_title = title.strip() or f"{safe_text(source.get('title'))} / branch"
        session = self.create_session_doc(
            branch_title,
            safe_text(source.get("workspaceId")),
            safe_text(source.get("projectPath")),
        )
        session["parentSessionId"] = safe_text(source.get("id"))
        session["notes"] = safe_text(source.get("notes"))
        session["plan"] = list(source.get("plan", []))
        session["recentJobs"] = list(source.get("recentJobs", []))
        session["lastJobId"] = safe_text(source.get("lastJobId"))
        session["summary"] = safe_text(source.get("summary"))
        self.save_session(session)
        self.current_session_file_path().write_text(session["id"], encoding="utf-8")
        return {
            "session": session,
            "items": self.list_sessions(),
            "currentSessionId": session["id"],
        }

    def update_session(
        self,
        session_id: str,
        title: str | None = None,
        notes: str | None = None,
        plan: list[dict[str, Any]] | None = None,
        workspace_id: str | None = None,
        project_path: str | None = None,
    ) -> dict[str, Any]:
        session = self.load_session(session_id)
        if title is not None:
            clean_title = safe_text(title).strip()
            if clean_title:
                session["title"] = clean_title
        if notes is not None:
            session["notes"] = safe_text(notes).strip()
        if plan is not None:
            normalized_plan: list[dict[str, str]] = []
            for item in plan:
                step = safe_text(item.get("step")).strip()
                if not step:
                    continue
                status = safe_text(item.get("status")).strip() or "pending"
                if status not in {"pending", "in_progress", "completed"}:
                    status = "pending"
                normalized_plan.append({"step": step, "status": status})
            session["plan"] = normalized_plan
        if workspace_id is not None:
            session["workspaceId"] = safe_text(workspace_id).strip()
        if project_path is not None:
            session["projectPath"] = safe_text(project_path).strip()
        self.refresh_session_summary(session)
        self.save_session(session)
        return {
            "session": session,
            "items": self.list_sessions(),
            "currentSessionId": self.current_session_id(),
        }

    def activate_session(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        self.current_session_file_path().write_text(session["id"], encoding="utf-8")
        return {
            "session": session,
            "items": self.list_sessions(),
            "currentSessionId": session["id"],
        }

    def delete_session(self, session_id: str) -> dict[str, Any]:
        target_id = safe_text(session_id).strip()
        if not target_id:
            raise ValueError("Session id is required.")
        if target_id == "legacy-history":
            raise ValueError("Legacy History session cannot be deleted.")
        session = self.load_session(target_id)
        child_sessions = [
            item for item in self.list_sessions()
            if safe_text(item.get("parentSessionId")).strip() == target_id
        ]
        if child_sessions:
            raise ValueError("Delete child branch sessions first.")
        running_jobs = [
            job for job in self.jobs_store().values()
            if job.session_id == target_id and job.status == "running"
        ]
        if running_jobs:
            raise ValueError("Cannot delete a session with running jobs.")
        session_dir = self.session_path(target_id).parent
        if session_dir.exists():
            shutil.rmtree(session_dir)
        next_current_id = self.current_session_id()
        if next_current_id == target_id:
            remaining = self.list_sessions()
            if remaining:
                next_current_id = safe_text(remaining[0].get("id")).strip()
                if next_current_id:
                    self.current_session_file_path().write_text(next_current_id, encoding="utf-8")
            else:
                created = self.save_session(self.create_session_doc("Default Session"))
                next_current_id = safe_text(created.get("id")).strip()
                self.current_session_file_path().write_text(next_current_id, encoding="utf-8")
        current_session = self.current_session()
        return {
            "deleted": True,
            "deletedSessionId": target_id,
            "items": self.list_sessions(),
            "currentSessionId": safe_text(current_session.get("id")),
            "currentSession": current_session,
            "message": f"Deleted session: {safe_text(session.get('title')) or target_id}",
        }

    def delete_account(self, account_id: str) -> dict[str, Any]:
        target_id = safe_text(account_id).strip()
        if not target_id:
            raise ValueError("Account id is required.")
        slot_dir = self.account_slot_dir(target_id)
        if not slot_dir.exists():
            raise ValueError(f"Account slot not found: {target_id}")
        running_jobs = [
            job for job in self.jobs_store().values()
            if safe_text(job.execution_account_id).strip() == target_id and job.status == "running"
        ]
        if running_jobs:
            raise ValueError("Cannot delete an account with running jobs.")
        if slot_dir.exists():
            shutil.rmtree(slot_dir)
        return {
            "deleted": True,
            "deletedAccountId": target_id,
            "items": self.list_accounts(),
            "currentAccountId": self.current_account_id(),
            "currentAccount": self.current_account_summary(),
            "message": f"Deleted account slot: {target_id}",
        }

    def rewrite_job_history(self, instance_id: str | None = None) -> None:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        rows: list[str] = []
        for job in sorted(self.jobs_store(resolved).values(), key=lambda item: (safe_text(item.started_at), safe_text(item.job_id))):
            row = {
                "jobId": job.job_id,
                "title": job.title,
                "kind": job.kind,
                "instanceId": job.instance_id,
                "sessionId": job.session_id,
                "sessionTitle": job.session_title,
                "planStep": job.plan_step,
                "workspaceId": job.workspace_id,
                "workspaceLabel": job.workspace_label,
                "status": job.status,
                "startedAt": job.started_at,
                "endedAt": job.ended_at,
                "exitCode": job.exit_code,
                "commandPreview": job.command_preview,
            }
            rows.append(json.dumps(row, ensure_ascii=False))
        history_path = self.history_file_path(resolved)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history_path.write_text(("\n".join(rows) + ("\n" if rows else "")), encoding="utf-8")

    def delete_job(self, job_id: str) -> dict[str, Any]:
        target_id = safe_text(job_id).strip()
        if not target_id:
            raise KeyError(job_id)
        with self.lock:
            job = self.jobs_store().get(target_id)
            if job is None:
                raise KeyError(job_id)
            if job.process and job.status == "running":
                raise ValueError("Cannot delete a running job.")
            instance_id = job.instance_id
            del self.jobs_store(instance_id)[target_id]
        try:
            self.job_record_path(target_id, instance_id).unlink(missing_ok=True)
        except OSError:
            pass
        self.rewrite_job_history(instance_id)
        return {
            "deleted": True,
            "deletedJobId": target_id,
            "items": self.list_jobs(instance_id),
            "message": f"Deleted job: {target_id}",
        }

    def clear_jobs(self, instance_id: str | None = None) -> dict[str, Any]:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        with self.lock:
            running = [job.job_id for job in self.jobs_store(resolved).values() if job.process and job.status == "running"]
            if running:
                raise ValueError("Cannot clear jobs while jobs are running.")
            job_ids = list(self.jobs_store(resolved).keys())
            self.jobs_store(resolved).clear()
        for job_id in job_ids:
            try:
                self.job_record_path(job_id, resolved).unlink(missing_ok=True)
            except OSError:
                pass
        self.rewrite_job_history(resolved)
        return {
            "cleared": True,
            "items": self.list_jobs(resolved),
            "message": f"Cleared {len(job_ids)} jobs.",
        }

    def compare_session(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        parent_id = safe_text(session.get("parentSessionId")).strip()
        if not parent_id:
            return {
                "sessionId": session_id,
                "hasParent": False,
                "message": "No parent session.",
            }
        parent = self.load_session(parent_id)
        session_plan = session.get("plan", [])
        parent_plan = parent.get("plan", [])
        session_plan_map = {safe_text(item.get("step")): safe_text(item.get("status")) for item in session_plan}
        parent_plan_map = {safe_text(item.get("step")): safe_text(item.get("status")) for item in parent_plan}
        changed_steps: list[dict[str, str]] = []
        for step in sorted(set(parent_plan_map) | set(session_plan_map)):
            parent_status = parent_plan_map.get(step, "")
            session_status = session_plan_map.get(step, "")
            if parent_status != session_status:
                changed_steps.append(
                    {
                        "step": step,
                        "parentStatus": parent_status,
                        "sessionStatus": session_status,
                    }
                )
        parent_jobs = {safe_text(item.get("jobId")) for item in parent.get("recentJobs", [])}
        new_jobs = [
            item
            for item in session.get("recentJobs", [])
            if safe_text(item.get("jobId")) not in parent_jobs
        ]
        parent_notes_lines = [
            line.strip()
            for line in safe_text(parent.get("notes")).splitlines()
            if line.strip()
        ]
        session_notes_lines = [
            line.strip()
            for line in safe_text(session.get("notes")).splitlines()
            if line.strip()
        ]
        notes_added = [line for line in session_notes_lines if line not in parent_notes_lines]
        notes_removed = [line for line in parent_notes_lines if line not in session_notes_lines]
        return {
            "sessionId": session_id,
            "hasParent": True,
            "parentSessionId": parent_id,
            "parentTitle": safe_text(parent.get("title")),
            "sessionTitle": safe_text(session.get("title")),
            "notesChanged": safe_text(parent.get("notes")).strip() != safe_text(session.get("notes")).strip(),
            "parentNotes": safe_text(parent.get("notes")),
            "sessionNotes": safe_text(session.get("notes")),
            "notesAdded": notes_added,
            "notesRemoved": notes_removed,
            "changedSteps": changed_steps,
            "newJobs": new_jobs,
        }

    def session_family(self, session_id: str) -> dict[str, Any]:
        session = self.load_session(session_id)
        parent_id = safe_text(session.get("parentSessionId")).strip()
        if parent_id:
            root = self.load_session(parent_id)
        else:
            root = session
            parent_id = safe_text(root.get("id"))
        siblings = []
        for item in self.list_sessions():
            if safe_text(item.get("id")) == safe_text(root.get("id")):
                continue
            if safe_text(item.get("parentSessionId")) == safe_text(root.get("id")):
                siblings.append(
                    {
                        "id": safe_text(item.get("id")),
                        "title": safe_text(item.get("title")),
                        "isCurrent": safe_text(item.get("id")) == safe_text(session.get("id")),
                    }
                )
        return {
            "sessionId": safe_text(session.get("id")),
            "currentTitle": safe_text(session.get("title")),
            "parent": {
                "id": safe_text(root.get("id")),
                "title": safe_text(root.get("title")),
                "isCurrent": safe_text(root.get("id")) == safe_text(session.get("id")),
            },
            "siblings": siblings,
        }

    def resolve_session(self, payload: dict[str, Any], workspace: dict[str, Any]) -> dict[str, Any]:
        session_id = safe_text(payload.get("sessionId")).strip()
        if session_id:
            session = self.load_session(session_id)
        else:
            session = self.current_session()
        session["workspaceId"] = safe_text(workspace.get("id")) or safe_text(session.get("workspaceId"))
        project_path = safe_text(payload.get("projectPath")).strip()
        if project_path:
            session["projectPath"] = project_path
        self.save_session(session)
        self.current_session_file_path().write_text(session["id"], encoding="utf-8")
        return session

    def summarize_text(self, text: str, limit: int = 1200) -> str:
        """Preserves line breaks and summarizes by taking the head/tail of the content."""
        raw = safe_text(text).strip()
        if not raw:
            return ""
        if len(raw) <= limit:
            return raw
        
        # Take first 40% and last 50% to preserve context and final results
        head_len = int(limit * 0.4)
        tail_len = int(limit * 0.5)
        return raw[:head_len] + "\n\n... [중략] ...\n\n" + raw[-tail_len:]

    def build_codex_resume_prompt(self, prompt: str, partial_output: str, attempt: int) -> str:
        base_prompt = safe_text(prompt).strip()
        partial = safe_text(partial_output).strip()
        if not base_prompt:
            return partial
        if not partial:
            return base_prompt
        summary = self.summarize_text(partial, 2400)
        guidance = [
            "[Resume Context]",
            f"Previous attempt #{attempt} stopped before completion.",
            "Continue from the partial work below instead of restarting from scratch.",
            "Preserve completed work, avoid repeating already-finished steps, and continue with the remaining work only.",
            "If the partial output already includes a final answer draft, refine and finish it instead of duplicating it.",
            "",
            "Partial final output from the interrupted attempt:",
            summary,
            "",
            "[Original Request]",
            base_prompt,
        ]
        return "\n".join(guidance)

    def extract_freeagent_answer(self, text: str) -> str:
        """Extract the answer from FreeAgent rich Panel output.

        Supports two formats:
        1. New format: FINAL OUTPUT panel with plain text + RAW OUTPUT panel
        2. Old format: single PROMPT/ASK panel with JSON containing 'answer' key
        """
        import re
        clean = strip_ansi(safe_text(text))

        # --- Format 1: FINAL OUTPUT panel (new cli.py format) ---
        final_output_lines: list[str] = []
        in_final = False
        for line in clean.splitlines():
            stripped = line.strip()
            if "FINAL OUTPUT" in stripped and "╭" in stripped:
                in_final = True
                continue
            if in_final and stripped.startswith("╰"):
                break  # end of FINAL OUTPUT panel
            if in_final and stripped.startswith("│"):
                inner = stripped[1:].rstrip("│").strip()
                if inner:
                    final_output_lines.append(inner)
        if final_output_lines:
            return "\n".join(final_output_lines)

        # --- Format 2: old JSON with "answer" key inside a single panel ---
        json_lines: list[str] = []
        capture = False
        for line in clean.splitlines():
            stripped = line.strip()
            if stripped.startswith("╭") or stripped.startswith("╰"):
                if capture:
                    break
                continue
            if stripped.startswith("│"):
                inner = stripped[1:].rstrip("│").strip()
                json_lines.append(inner)
                capture = True
            elif capture:
                break
        if json_lines:
            raw_json = " ".join(json_lines)
            try:
                data = json.loads(raw_json)
                answer = safe_text(data.get("answer", "")).strip()
                if answer:
                    return answer
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            # Regex fallback
            m = re.search(r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_json)
            if m:
                return m.group(1).replace("\\n", "\n").replace('\\"', '"').strip()
        return ""

    def summarize_log_for_ui(self, text: str, include_color: bool = True) -> str:
        """Intelligently filters logs to show key execution results and diffs."""
        if not text:
            return ""

        # FreeAgent panel output: extract the answer field directly
        clean_check = strip_ansi(safe_text(text))
        if "╭" in clean_check and ('"answer"' in clean_check or "FINAL OUTPUT" in clean_check):
            answer = self.extract_freeagent_answer(text)
            if answer:
                return ansi_to_html(answer) if include_color else answer

        # Keep interesting sections (diff blocks, errors, success markers)
        lines = text.splitlines()
        filtered = []
        in_diff = False
        
        for line in lines:
            stripped = strip_ansi(line).strip()
            # Heuristics for high-signal lines
            is_high_signal = any(marker in stripped for marker in ["+++", "---", "@@ ", "Error:", "ERROR:", "SUCCESS", "FAILED", "Apply complete", "Warning:"])
            
            if is_high_signal:
                filtered.append(line)
                in_diff = True
            elif in_diff and (line.startswith("+") or line.startswith("-") or line.startswith(" ")):
                # Keep lines within a diff block or slightly after
                filtered.append(line)
            elif "Task:" in stripped or "Action:" in stripped:
                filtered.append(line)
            elif len(filtered) < 15: # Always keep the start of execution
                filtered.append(line)
        
        # If too many lines, take tails
        if len(filtered) > 100:
            filtered = filtered[:30] + ["... [생략] ..."] + filtered[-70:]
            
        result = "\n".join(filtered)
        return ansi_to_html(result) if include_color else result

    def extract_quota_message_lines(self, text: str) -> list[str]:
        lines: list[str] = []
        for raw_line in safe_text(text).splitlines():
            stripped = strip_ansi(raw_line).strip()
            lowered = stripped.lower()
            if any(marker in lowered for marker in ("quota exceeded", "429 too many requests", "rate limit reached", "usage limit", "try again at")):
                lines.append(stripped or raw_line.strip())
        deduped: list[str] = []
        for line in lines:
            if line and line not in deduped:
                deduped.append(line)
        return deduped[-3:]

    def summarize_job_message(self, text: str, limit: int = 400) -> str:
        collapsed = self.summarize_text(text, limit * 2)
        lowered = collapsed.lower()
        if "no such command 'prompt'" in lowered:
            return "freeagent prompt command was unavailable in that run"
        if "usage: python -m freeagent.cli" in lowered:
            return "freeagent cli usage error"
        if any(marker in collapsed for marker in ("╭", "│")):
            # Try to extract FreeAgent answer from panel output
            answer = self.extract_freeagent_answer(text)
            if answer:
                return self.summarize_text(answer, limit)
            # Non-FreeAgent verbose output
            if any(marker in collapsed for marker in ("children:[", "md:grid-cols", "export{")):
                return "verbose tool output omitted"
        return self.summarize_text(collapsed, limit)

    def normalize_session_notes(self, text: str, limit: int = 400) -> str:
        lines = [line.strip() for line in safe_text(text).splitlines() if line.strip()]
        if not lines:
            return ""
        recent = "\n".join(lines[-8:])
        return self.summarize_text(recent, limit)

    def refresh_session_summary(self, session_doc: dict[str, Any]) -> None:
        recent_jobs = session_doc.get("recentJobs", [])
        lines: list[str] = []
        notes = self.normalize_session_notes(safe_text(session_doc.get("notes")), 180)
        if notes:
            lines.append(f"Notes: {notes}")
        plan_items = session_doc.get("plan", [])
        if plan_items:
            compact = ", ".join(
                f"{safe_text(item.get('step'))} [{safe_text(item.get('status')) or 'pending'}]"
                for item in plan_items[:4]
                if safe_text(item.get("step")).strip()
            )
            if compact:
                lines.append(f"Plan: {self.summarize_text(compact, 180)}")
        for item in recent_jobs[-4:]:
            summary = self.summarize_job_message(safe_text(item.get("finalMessage")) or safe_text(item.get("commandPreview")), 140)
            status = safe_text(item.get("status")) or "unknown"
            title = safe_text(item.get("title")) or safe_text(item.get("jobId"))
            lines.append(f"- {title} [{status}]: {summary}")
        session_doc["summary"] = self.summarize_text("\n".join(lines), 700)

    def append_session_note(self, session: dict[str, Any], note: str) -> None:
        text = safe_text(note).strip()
        if not text:
            return
        existing = safe_text(session.get("notes")).strip()
        if text in existing:
            return
        if existing:
            session["notes"] = self.normalize_session_notes(f"{existing}\n{text}", 500)
        else:
            session["notes"] = self.normalize_session_notes(text, 500)

    def auto_update_session_plan(self, session: dict[str, Any], job: JobRecord) -> None:
        plan_items = list(session.get("plan", []))
        if not plan_items:
            return
        if job.status != "succeeded":
            self.append_session_note(
                session,
                f"Job failed: {job.title} ({job.ended_at or now_iso()})",
            )
            return
        target_step = safe_text(job.plan_step).strip()
        in_progress_index = None
        if target_step:
            in_progress_index = next(
                (index for index, item in enumerate(plan_items) if safe_text(item.get("step")).strip() == target_step),
                None,
            )
        if in_progress_index is None:
            in_progress_index = next(
                (index for index, item in enumerate(plan_items) if safe_text(item.get("status")) == "in_progress"),
                None,
            )
        if in_progress_index is None:
            pending_index = next(
                (index for index, item in enumerate(plan_items) if safe_text(item.get("status")) == "pending"),
                None,
            )
            if pending_index is not None:
                plan_items[pending_index]["status"] = "in_progress"
                self.append_session_note(
                    session,
                    f"Auto-started plan item after job: {safe_text(plan_items[pending_index].get('step'))}",
                )
            session["plan"] = plan_items
            return
        completed_step = safe_text(plan_items[in_progress_index].get("step"))
        plan_items[in_progress_index]["status"] = "completed"
        if target_step:
            for index, item in enumerate(plan_items):
                if index == in_progress_index:
                    continue
                if safe_text(item.get("status")) == "in_progress":
                    item["status"] = "pending"
        pending_index = next(
            (index for index, item in enumerate(plan_items) if safe_text(item.get("status")) == "pending"),
            None,
        )
        if pending_index is not None:
            plan_items[pending_index]["status"] = "in_progress"
            next_step = safe_text(plan_items[pending_index].get("step"))
            self.append_session_note(
                session,
                f"Auto-progressed plan after '{job.title}': completed '{completed_step}', now working on '{next_step}'.",
            )
        else:
            self.append_session_note(
                session,
                f"Auto-progressed plan after '{job.title}': completed '{completed_step}'.",
            )
        session["plan"] = plan_items

    def update_session_after_job(self, job: JobRecord) -> None:
        session = self.load_session(job.session_id)
        recent_jobs = list(session.get("recentJobs", []))
        recent_jobs.append(
            {
                "jobId": job.job_id,
                "title": job.title,
                "kind": job.kind,
                "status": job.status,
                "planStep": job.plan_step,
                "workspaceLabel": job.workspace_label,
                "cwd": job.cwd,
                "commandPreview": job.command_preview,
                "endedAt": job.ended_at,
                "finalMessage": self.summarize_job_message(job.final_message or job.output, 180),
            }
        )
        session["recentJobs"] = recent_jobs[-5:]
        session["lastJobId"] = job.job_id
        self.auto_update_session_plan(session, job)
        self.refresh_session_summary(session)
        self.save_session(session)

    def append_job_runtime_event(self, job_id: str, message: str, *, session_note: str = "") -> None:
        text = safe_text(message).strip()
        if not text:
            return
        line = f"[Launcher] {text}"
        job = None
        with self.lock:
            job = self.jobs_store().get(job_id)
            if job is not None:
                current = safe_text(job.output)
                job.output = (current + ("\n" if current and not current.endswith("\n") else "") + line + "\n")[-120000:]
        if session_note:
            session = self.load_session(job.session_id) if job is not None else None
            if session:
                self.append_session_note(session, session_note)
                self.refresh_session_summary(session)
                self.save_session(session)

    def compact_text(self, text: str, limit: int = 240) -> str:
        collapsed = " ".join(safe_text(text).split())
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3].rstrip() + "..."

    def summarize_worker_outcome(self, text: str, limit: int = 180) -> str:
        raw = safe_text(text)
        if not raw.strip():
            return "(no result)"
        for line in raw.splitlines():
            stripped = " ".join(line.split())
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith("[launcher]") or lowered.startswith("model:") or lowered.startswith("lens:"):
                continue
            return self.compact_text(stripped, limit)
        return self.compact_text(raw, limit)

    def extract_reported_file_paths(self, text: str, cwd: str = "", limit: int = 6) -> list[str]:
        raw = safe_text(text)
        if not raw.strip():
            return []
        normalized_cwd = safe_text(cwd).strip()
        found: list[str] = []
        patterns = [
            re.compile(r"\[[^\]]+\]\((/[^)\s:]+(?:\.[A-Za-z0-9_-]+)?)\)"),
            re.compile(r"`(/[^`\s]+)`"),
            re.compile(r"(?<![A-Za-z0-9._-])(/[^ \t\n\r'\"<>()]+(?:\.[A-Za-z0-9_-]+))(?![A-Za-z0-9._-])"),
        ]
        for pattern in patterns:
            for match in pattern.findall(raw):
                path = safe_text(match).strip()
                if not path or path in found:
                    continue
                if normalized_cwd and not path.startswith(normalized_cwd) and not path.startswith("/opt/projects/"):
                    continue
                found.append(path)
                if len(found) >= limit:
                    return found
        return found

    def format_worker_result_detail(
        self,
        summary: str,
        *,
        status: str,
        actor: str,
        writes_files: bool = False,
        file_paths: list[str] | None = None,
    ) -> str:
        bits = [f"status={status}", f"actor={safe_text(actor).strip() or 'unknown'}", f"writes={'yes' if writes_files else 'no'}"]
        if file_paths:
            bits.append(f"files={', '.join(file_paths[:6])}")
        bits.append(f"result={self.summarize_worker_outcome(summary or '(no result)', 220)}")
        return " | ".join(bits)

    def log_parallel_worker_result(
        self,
        job_id: str,
        worker_type: str,
        worker_name: str,
        role: str,
        summary: str,
        *,
        exit_code: int = 0,
        timed_out: bool = False,
        extra: str = "",
        actor: str = "",
        writes_files: bool = False,
        file_paths: list[str] | None = None,
    ) -> None:
        name = safe_text(worker_name).strip() or "unknown"
        role_text = safe_text(role).strip() or "-"
        status = "timeout" if timed_out else ("ok" if safe_int(exit_code, 1) == 0 else f"exit={safe_int(exit_code, 1)}")
        detail = self.format_worker_result_detail(
            summary or "(no result)",
            status=status,
            actor=actor or worker_type,
            writes_files=writes_files,
            file_paths=file_paths,
        )
        suffix = f" | {safe_text(extra).strip()}" if safe_text(extra).strip() else ""
        self.append_job_runtime_event(
            job_id,
            f"{worker_type} result | {name} | role={role_text} | {detail}{suffix}",
        )

    def capture_workspace_file_state(self, cwd: str, max_files: int = 20000) -> dict[str, str]:
        root = Path(cwd)
        if not root.exists() or not root.is_dir():
            return {}
        ignored = {".git", "node_modules", ".next", ".turbo", "dist", "build", "coverage", ".gradle"}
        state: dict[str, str] = {}
        count = 0
        try:
            for current_root, dirnames, filenames in os.walk(root):
                dirnames[:] = [name for name in dirnames if name not in ignored]
                base = Path(current_root)
                for filename in filenames:
                    path = base / filename
                    try:
                        stat = path.stat()
                    except OSError:
                        continue
                    if not path.is_file():
                        continue
                    relative = path.relative_to(root).as_posix()
                    state[relative] = f"{stat.st_mtime_ns}:{stat.st_size}"
                    count += 1
                    if count >= max_files:
                        return state
        except OSError:
            return state
        return state

    def diff_workspace_file_state(self, before: dict[str, str], after: dict[str, str]) -> dict[str, list[str]]:
        before_keys = set(before)
        after_keys = set(after)
        created = sorted(path for path in (after_keys - before_keys))
        deleted = sorted(path for path in (before_keys - after_keys))
        modified = sorted(path for path in (before_keys & after_keys) if before.get(path) != after.get(path))
        return {
            "created": created,
            "modified": modified,
            "deleted": deleted,
            "changed": created + modified + deleted,
        }

    def relevant_plan_items(self, session: dict[str, Any], active_step: str = "") -> list[dict[str, Any]]:
        plan_items = [item for item in session.get("plan", []) if safe_text(item.get("step")).strip()]
        if not plan_items:
            return []
        target_step = safe_text(active_step).strip()
        if target_step:
            target_index = next(
                (index for index, item in enumerate(plan_items) if safe_text(item.get("step")).strip() == target_step),
                None,
            )
            if target_index is not None:
                start = max(0, target_index - 1)
                end = min(len(plan_items), target_index + 2)
                return plan_items[start:end]
        in_progress_index = next(
            (index for index, item in enumerate(plan_items) if safe_text(item.get("status")).strip() == "in_progress"),
            None,
        )
        if in_progress_index is not None:
            start = max(0, in_progress_index - 1)
            end = min(len(plan_items), in_progress_index + 2)
            return plan_items[start:end]
        return plan_items[:3]

    def build_session_context(self, session: dict[str, Any], active_step: str = "", limit: int = 0) -> str:
        lines = [
            "[Session Context]",
            f"Session: {safe_text(session.get('title'))}",
        ]
        if session.get("workspaceId"):
            lines.append(f"Workspace: {safe_text(session.get('workspaceId'))}")
        if session.get("projectPath"):
            lines.append(f"Project Path: {safe_text(session.get('projectPath'))}")
        target_step = safe_text(active_step).strip()
        if target_step:
            lines.append(f"Active Step: {target_step}")
        notes = safe_text(session.get("notes")).strip()
        if notes:
            lines.append("Session Notes:")
            lines.append(self.compact_text(notes, 320 if limit <= 0 else min(320, max(120, limit // 3))))
        plan_items = self.relevant_plan_items(session, target_step)
        if plan_items:
            lines.append("Session Plan:")
            for item in plan_items:
                step = safe_text(item.get("step")).strip()
                if not step:
                    continue
                status = safe_text(item.get("status")).strip() or "pending"
                lines.append(f"- [{status}] {step}")
        summary = safe_text(session.get("summary")).strip()
        if summary:
            lines.append("Recent Decisions:")
            lines.append(self.compact_text(summary, 260 if limit <= 0 else min(260, max(100, limit // 4))))
        recent_jobs = session.get("recentJobs", [])
        if recent_jobs:
            lines.append("Recent Outputs:")
            relevant_jobs = recent_jobs[-1:]
            if target_step:
                matched_jobs = [item for item in recent_jobs if safe_text(item.get("planStep")).strip() == target_step]
                if matched_jobs:
                    relevant_jobs = matched_jobs[-1:]
            for item in relevant_jobs:
                job_limit = 120 if limit <= 0 else min(120, max(80, limit // 5))
                lines.append(f"- {safe_text(item.get('title'))}: {self.summarize_job_message(safe_text(item.get('finalMessage')), job_limit)}")
        lines.extend(
            [
                "",
                "[CRITICAL GUARDRAIL - PRECONDITION GATING]",
                "절대 규칙: 할당된 작업(Plan)의 전제조건이나 설계 내역이 명확하지 않거나 누락된 경우, 임의로 코드를 작성하거나 변경하지 말고 즉시 실행을 중단하세요. 대신, 반드시 응답(JSON의 'answer' 필드 등)에 '설계 보강이 필요하다'고 사용자에게 명시적으로 안내하세요.",
                "Use this session context as prior work. Continue from it unless the new request clearly overrides it.",
                "",
            ]
        )
        text = "\n".join(lines)
        return self.summarize_text(text, limit) if limit > 0 else text

    def build_apply_context(self, session: dict[str, Any], active_step: str = "", limit: int = 0) -> str:
        lines = [
            "[Session Context]",
            f"Session: {safe_text(session.get('title'))}",
        ]
        if session.get("workspaceId"):
            lines.append(f"Workspace: {safe_text(session.get('workspaceId'))}")
        target_step = safe_text(active_step).strip()
        if target_step:
            lines.append(f"Active Step: {target_step}")
        summary = safe_text(session.get("summary")).strip()
        if summary:
            lines.append("Recent Decisions:")
            lines.append(self.compact_text(summary, 180 if limit <= 0 else min(180, max(100, limit // 3))))
        plan_items = self.relevant_plan_items(session, target_step)
        if plan_items:
            lines.append("Relevant Plan:")
            for item in plan_items:
                lines.append(f"- [{safe_text(item.get('status')) or 'pending'}] {safe_text(item.get('step'))}")
        recent_jobs = session.get("recentJobs", [])
        if recent_jobs:
            lines.append("Recent Outputs:")
            relevant_jobs = recent_jobs[-1:]
            if target_step:
                matched_jobs = [item for item in recent_jobs if safe_text(item.get("planStep")).strip() == target_step]
                if matched_jobs:
                    relevant_jobs = matched_jobs[-1:]
            for item in relevant_jobs:
                title = safe_text(item.get("title")).strip()
                final_message = self.summarize_text(safe_text(item.get("finalMessage")), 120 if limit <= 0 else min(120, max(80, limit // 4)))
                if title or final_message:
                    lines.append(f"- {title}: {final_message}")
        lines.extend(
            [
                "",
                "[CRITICAL GUARDRAIL - PRECONDITION GATING]",
                "절대 규칙: 명시된 Relevant Plan(작업 계획)을 가장 먼저 확인하세요. 만약 선행 설계나 명확한 변경 지침(Precondition)이 존재하지 않거나 부족하다면, 절대 임의로 파일 쓰기나 코드 수정을 진행하지 마세요. 대신, 반드시 응답(JSON의 'answer' 필드 등) 내용에 '구체적인 설계/기획 보강이 필요합니다'라고 명시적으로 적어서 사용자에게 안내하세요.",
                "Use only the relevant prior context. Ignore prior logs that do not directly help with the current edit request.",
                "",
            ]
        )
        text = "\n".join(lines)
        return self.summarize_text(text, limit) if limit > 0 else text

    def normalize_runtime_options(self, payload: Any) -> dict[str, bool]:
        raw = payload if isinstance(payload, dict) else {}
        return {
            "includeBrowserContext": safe_bool(raw.get("includeBrowserContext"), True),
            "includeReferenceContext": safe_bool(raw.get("includeReferenceContext"), True),
            "includeMenuContext": safe_bool(raw.get("includeMenuContext"), True),
            "autoSaverForQuestions": safe_bool(raw.get("autoSaverForQuestions"), True),
            "compactPreferencePreamble": safe_bool(raw.get("compactPreferencePreamble"), False),
            "omitPreferencePreamble": safe_bool(raw.get("omitPreferencePreamble"), False),
            "compactPromptWhitespace": safe_bool(raw.get("compactPromptWhitespace"), True),
            "dedupeConsecutivePromptLines": safe_bool(raw.get("dedupeConsecutivePromptLines"), True),
            "stripMarkdownFences": safe_bool(raw.get("stripMarkdownFences"), False),
            "includeSessionContext": safe_bool(raw.get("includeSessionContext"), True),
            "allowSourceAnalysis": safe_bool(raw.get("allowSourceAnalysis"), True),
            "allowDocsRead": safe_bool(raw.get("allowDocsRead"), True),
            "allowSkillsRead": safe_bool(raw.get("allowSkillsRead"), True),
            "preferMinimalScan": safe_bool(raw.get("preferMinimalScan"), True),
            "preferBriefOutput": safe_bool(raw.get("preferBriefOutput"), True),
            "focusScope": safe_text(raw.get("focusScope")).strip(),
            "sessionContextLimit": max(0, safe_int(raw.get("sessionContextLimit"), 0)),
            "promptCharsLimit": max(0, safe_int(raw.get("promptCharsLimit"), 0)),
        }

    def classic_runtime_options(self) -> dict[str, Any]:
        return self.normalize_runtime_options({
            "includeBrowserContext": False,
            "includeReferenceContext": False,
            "includeMenuContext": False,
            "autoSaverForQuestions": False,
            "compactPreferencePreamble": False,
            "omitPreferencePreamble": True,
            "compactPromptWhitespace": False,
            "dedupeConsecutivePromptLines": False,
            "stripMarkdownFences": False,
            "includeSessionContext": False,
            "allowSourceAnalysis": False,
            "allowDocsRead": False,
            "allowSkillsRead": False,
            "preferMinimalScan": False,
            "preferBriefOutput": False,
            "focusScope": "",
            "sessionContextLimit": 0,
            "promptCharsLimit": 0,
        })

    def enforce_prompt_chars_limit(self, prompt: str, runtime_options: dict[str, Any]) -> str:
        raw = safe_text(prompt).strip()
        limit = max(0, safe_int(runtime_options.get("promptCharsLimit"), 0))
        if limit <= 0 or len(raw) <= limit:
            return raw
        marker = "\n...[prompt truncated]"
        if limit <= len(marker):
            return raw[:limit]
        return raw[: limit - len(marker)].rstrip() + marker

    def compact_prompt_whitespace(self, prompt: str, runtime_options: dict[str, Any]) -> str:
        raw = safe_text(prompt).strip()
        if not safe_bool(runtime_options.get("compactPromptWhitespace"), True):
            return raw
        lines = [line.rstrip() for line in raw.splitlines()]
        compacted = "\n".join(lines)
        compacted = re.sub(r"\n{3,}", "\n\n", compacted)
        return compacted.strip()

    def dedupe_consecutive_prompt_lines(self, prompt: str, runtime_options: dict[str, Any]) -> str:
        raw = safe_text(prompt).strip()
        if not safe_bool(runtime_options.get("dedupeConsecutivePromptLines"), True):
            return raw
        deduped: list[str] = []
        last_line = None
        for line in raw.splitlines():
            current = line.rstrip()
            if last_line is not None and current == last_line:
                continue
            deduped.append(current)
            last_line = current
        return "\n".join(deduped).strip()

    def strip_markdown_fences(self, prompt: str, runtime_options: dict[str, Any]) -> str:
        raw = safe_text(prompt).strip()
        if not safe_bool(runtime_options.get("stripMarkdownFences"), False):
            return raw
        lines = [line for line in raw.splitlines() if not re.match(r"^\s*```", line)]
        return "\n".join(lines).strip()

    def apply_question_saver_runtime_options(self, runtime_options: dict[str, Any]) -> dict[str, Any]:
        options = dict(runtime_options or {})
        options["focusScope"] = ""
        options["includeBrowserContext"] = False
        options["includeReferenceContext"] = False
        options["includeSessionContext"] = False
        options["compactPreferencePreamble"] = True
        options["omitPreferencePreamble"] = True
        options["compactPromptWhitespace"] = True
        options["dedupeConsecutivePromptLines"] = True
        options["stripMarkdownFences"] = False
        options["allowSourceAnalysis"] = False
        options["allowDocsRead"] = False
        options["allowSkillsRead"] = False
        options["preferMinimalScan"] = True
        options["preferBriefOutput"] = True
        current_context_limit = max(0, safe_int(options.get("sessionContextLimit"), 0))
        options["sessionContextLimit"] = 120 if current_context_limit <= 0 else min(current_context_limit, 120)
        current_prompt_limit = max(0, safe_int(options.get("promptCharsLimit"), 0))
        if current_prompt_limit <= 0:
            options["promptCharsLimit"] = 800
        else:
            options["promptCharsLimit"] = min(current_prompt_limit, 800)
        return options

    def build_runtime_prompt_preamble(
        self,
        runtime_options: dict[str, bool],
        *,
        include_session_context: bool = True,
        session: dict[str, Any] | None = None,
        plan_step: str = "",
        apply_mode: bool = False,
        question_like_prompt: bool = False,
    ) -> str:
        parts: list[str] = []
        if (
            include_session_context
            and runtime_options.get("includeSessionContext", True)
            and session is not None
            and not question_like_prompt
        ):
            context_limit = int(runtime_options.get("sessionContextLimit", 0) or 0)
            context = (
                self.build_apply_context(session, plan_step, context_limit)
                if apply_mode
                else self.build_session_context(session, plan_step, context_limit)
            )
            if context.strip():
                parts.append(context.strip())

        if safe_bool(runtime_options.get("omitPreferencePreamble"), False):
            return "\n\n".join(part for part in parts if part).strip()

        compact_preamble = safe_bool(runtime_options.get("compactPreferencePreamble"), False)
        guidance: list[str] = ["[Execution Preferences]"]
        focus_scope = safe_text(runtime_options.get("focusScope")).strip()
        if compact_preamble:
            compact_bits: list[str] = []
            if focus_scope:
                compact_bits.append(f"scope={focus_scope}")
            if not runtime_options.get("allowSourceAnalysis", True):
                compact_bits.append("no broad repo scan")
            if not runtime_options.get("allowDocsRead", True):
                compact_bits.append("no docs")
            if not runtime_options.get("allowSkillsRead", True):
                compact_bits.append("no skills")
            if runtime_options.get("preferMinimalScan", True):
                compact_bits.append("minimal reads")
            if runtime_options.get("preferBriefOutput", True):
                compact_bits.append("brief output")
            if compact_bits:
                guidance.append("- " + ", ".join(compact_bits))
        else:
            if focus_scope:
                guidance.append(f"- Focus only on this scope unless the task clearly requires adjacent files: {focus_scope}")
            if runtime_options.get("allowSourceAnalysis", True):
                guidance.append("- Source analysis is allowed when it directly helps the task.")
            else:
                guidance.append("- Do not proactively scan the repository or analyze overall source structure unless the user explicitly asks.")
            if runtime_options.get("allowDocsRead", True):
                guidance.append("- README/docs/config reference reading is allowed when needed.")
            else:
                guidance.append("- Do not open README, docs, design notes, or config reference files unless they are strictly required.")
            if runtime_options.get("allowSkillsRead", True):
                guidance.append("- Skills or auxiliary instruction files may be used if clearly relevant.")
            else:
                guidance.append("- Do not read SKILL.md, skills, or auxiliary agent guide files unless the user explicitly requests them.")
            if runtime_options.get("preferMinimalScan", True):
                guidance.append("- Prefer a minimal-read path: inspect only the smallest set of files needed and avoid broad searches.")
            if runtime_options.get("preferBriefOutput", True):
                guidance.append("- Keep the final response concise and avoid long summaries unless they are necessary.")
        context_limit = int(runtime_options.get("sessionContextLimit", 0) or 0)
        if context_limit > 0:
            guidance.append(f"- Keep launcher-added session context within about {context_limit} characters.")
        prompt_limit = int(runtime_options.get("promptCharsLimit", 0) or 0)
        if prompt_limit > 0:
            guidance.append(f"- User prompt content is capped at about {prompt_limit} characters.")
        if apply_mode:
            guidance.append("- Prioritize making the requested change over producing repo-wide analysis.")
        parts.append("\n".join(guidance))
        return "\n\n".join(part for part in parts if part).strip()

    def compose_prompt(
        self,
        prompt: str,
        runtime_options: dict[str, bool],
        *,
        session: dict[str, Any] | None = None,
        plan_step: str = "",
        include_session_context: bool = True,
        apply_mode: bool = False,
    ) -> str:
        question_like_prompt = self.is_question_like_prompt(prompt)
        low_signal_prompt = prompt_is_low_signal(prompt)
        effective_runtime_options = dict(runtime_options or {})
        if (question_like_prompt or low_signal_prompt) and safe_bool(effective_runtime_options.get("autoSaverForQuestions"), True):
            effective_runtime_options = self.apply_question_saver_runtime_options(effective_runtime_options)
        prompt = self.strip_markdown_fences(prompt, effective_runtime_options)
        prompt = self.compact_prompt_whitespace(prompt, effective_runtime_options)
        prompt = self.dedupe_consecutive_prompt_lines(prompt, effective_runtime_options)
        prompt = self.enforce_prompt_chars_limit(prompt, effective_runtime_options)
        question_like_prompt = self.is_question_like_prompt(prompt)
        low_signal_prompt = prompt_is_low_signal(prompt)
        preamble = self.build_runtime_prompt_preamble(
            effective_runtime_options,
            include_session_context=include_session_context,
            session=session,
            plan_step=plan_step,
            apply_mode=apply_mode,
            question_like_prompt=(question_like_prompt or low_signal_prompt),
        )
        if not preamble:
            return prompt
        return f"{preamble}\n\n{prompt}"

    def is_question_like_prompt(self, prompt: str) -> bool:
        text = safe_text(prompt).strip().lower()
        if not text:
            return True
        if "?" in text:
            return True
        question_markers = (
            "what",
            "how",
            "why",
            "can i",
            "can we",
            "could",
            "should",
            "is it",
            "are there",
            "뭐",
            "무엇",
            "뭘",
            "어떻게",
            "왜",
            "가능",
            "할 수 있",
            "되나",
            "되나요",
            "있나",
            "있나요",
        )
        action_markers = (
            "fix",
            "change",
            "update",
            "implement",
            "add",
            "remove",
            "refactor",
            "replace",
            "return",
            "show",
            "rename",
            "수정",
            "변경",
            "추가",
            "삭제",
            "개선",
            "리팩토링",
            "교체",
            "반환",
            "표시",
        )
        if any(marker in text for marker in question_markers) and not any(marker in text for marker in action_markers):
            return True
        return False

    def codex_home(self, instance_id: str | None = None) -> Path:
        resolved = self.normalize_instance_id(instance_id or self.current_instance_id())
        if resolved == "default":
            return Path(os.environ.get("CARBONET_CODEX_HOME", str(Path.home() / ".codex")))
        return self.instance_root(resolved) / "codex-home"

    def auth_file(self, instance_id: str | None = None) -> Path:
        return self.codex_home(instance_id) / "auth.json"

    def config_file(self, instance_id: str | None = None) -> Path:
        return self.codex_home(instance_id) / "config.toml"

    def clear_codex_runtime_state(self, home: Path, preserve_names: set[str] | None = None) -> None:
        if not home.exists():
            return
        preserved = {safe_text(name).strip() for name in (preserve_names or set()) if safe_text(name).strip()}
        for child in home.iterdir():
            if child.name in preserved:
                continue
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError:
                continue

    def codex_bin(self) -> str:
        return os.environ.get("CARBONET_CODEX_BIN", "codex")

    def freeagent_home(self) -> Path:
        return self.app_root / "vendors" / "freeagent_ultra"

    def freeagent_env_file(self) -> Path:
        return self.app_root / ".env.freeagent"

    def freeagent_legacy_env_file(self) -> Path:
        return self.freeagent_home() / ".env.freeagent"

    def freeagent_bin(self) -> str:
        return str(self.app_root / "bin" / "carbonet-freeagent")

    def freeagent_venv_dir(self) -> Path:
        return self.app_root / "runtime" / "freeagent-venv"

    def freeagent_python(self) -> Path:
        return self.freeagent_venv_dir() / "bin" / "python"

    def freeagent_write_env(self, model: str = "qwen3.5:cloud") -> None:
        self.freeagent_home().mkdir(parents=True, exist_ok=True)
        current = read_key_values(self.freeagent_env_file())
        if not current and self.freeagent_legacy_env_file().exists():
            current = read_key_values(self.freeagent_legacy_env_file())
        merged = {
            "FREEAGENT_PROVIDER": current.get("FREEAGENT_PROVIDER", "ollama"),
            "FREEAGENT_MODEL": current.get("FREEAGENT_MODEL", model),
            "OLLAMA_HOST": current.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "OLLAMA_TIMEOUT_SEC": current.get("OLLAMA_TIMEOUT_SEC", "90"),
            "OLLAMA_NUM_PREDICT": current.get("OLLAMA_NUM_PREDICT", "64"),
            "OPENAI_BASE_URL": current.get("OPENAI_BASE_URL", ""),
            "OPENAI_API_KEY": current.get("OPENAI_API_KEY", ""),
            "FREEAGENT_MINIMAX_MODEL": current.get("FREEAGENT_MINIMAX_MODEL", "minimax2.7"),
            "MINIMAX_BASE_URL": current.get("MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1"),
            "MINIMAX_API_KEY": current.get("MINIMAX_API_KEY", ""),
        }
        body = "\n".join(f"{key}={value}" for key, value in merged.items()) + "\n"
        self.freeagent_env_file().write_text(body, encoding="utf-8")

    def freeagent_provider(self) -> str:
        provider = read_key_values(self.freeagent_env_file()).get("FREEAGENT_PROVIDER", "ollama").strip()
        if provider == "minimax2.7":
            return "minimax"
        return provider or "ollama"

    def run_sudo(self, args: list[str], sudo_password: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        if not sudo_password:
            raise ValueError("sudo password is required for system installation")
        return subprocess.run(
            ["sudo", "-S", *args],
            input=f"{sudo_password}\n",
            text=True,
            capture_output=True,
            cwd=cwd,
            check=True,
        )

    def ensure_ollama_installed(self, sudo_password: str) -> list[str]:
        messages: list[str] = []
        if shutil.which("zstd") is None:
            self.run_sudo(["apt-get", "update"], sudo_password)
            self.run_sudo(["apt-get", "install", "-y", "zstd"], sudo_password)
            messages.append("installed zstd")
        if shutil.which("ollama") is None:
            self.run_sudo(["bash", "-lc", "curl -fsSL https://ollama.com/install.sh | sh"], sudo_password)
            messages.append("installed ollama")
        return messages

    def ollama_running(self, host: str = "http://127.0.0.1:11434") -> bool:
        try:
            with urlopen(f"{host}/api/version", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    def ollama_tags(self, host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
        try:
            with urlopen(f"{host}/api/tags", timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return {"models": []}

    def available_ollama_model_names(self, host: str = "http://127.0.0.1:11434") -> set[str]:
        tags = self.ollama_tags(host) if self.ollama_running(host) else {"models": []}
        names: set[str] = set()
        for item in tags.get("models", []):
            name = safe_text(item.get("name")).strip()
            if name:
                names.add(name)
        return names

    def available_ollama_models(self, host: str = "http://127.0.0.1:11434") -> dict[str, dict[str, Any]]:
        models: dict[str, dict[str, Any]] = {}
        for item in self.ollama_tags(host).get("models", []):
            name = safe_text(item.get("name")).strip()
            if name:
                models[name] = item
        return models

    def ollama_ps(self, host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
        try:
            with urlopen(f"{host}/api/ps", timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception:
            return {"models": []}

    def loaded_ollama_models(self, host: str = "http://127.0.0.1:11434") -> dict[str, dict[str, Any]]:
        loaded: dict[str, dict[str, Any]] = {}
        for item in self.ollama_ps(host).get("models", []):
            name = safe_text(item.get("name")).strip()
            if name:
                loaded[name] = item
        return loaded

    def system_memory_summary(self) -> dict[str, int]:
        summary = {
            "totalBytes": 0,
            "availableBytes": 0,
            "swapTotalBytes": 0,
            "swapFreeBytes": 0,
        }
        try:
            fields: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                parts = raw_value.strip().split()
                if not parts:
                    continue
                try:
                    value_kib = int(parts[0])
                except ValueError:
                    continue
                fields[key.strip()] = value_kib * 1024
            summary["totalBytes"] = int(fields.get("MemTotal", 0))
            summary["availableBytes"] = int(fields.get("MemAvailable", 0))
            summary["swapTotalBytes"] = int(fields.get("SwapTotal", 0))
            summary["swapFreeBytes"] = int(fields.get("SwapFree", 0))
        except Exception:
            pass
        return summary

    def inspect_local_models_payload(self, models: list[str]) -> dict[str, Any]:
        items = self.inspect_local_models(models)
        memory = self.system_memory_summary()
        selected_total = sum(max(int(item.get("sizeBytes") or 0), 0) for item in items)
        loaded_total = sum(max(int(item.get("loadedSizeBytes") or item.get("sizeBytes") or 0), 0) for item in items if item.get("loaded"))
        total_bytes = max(int(memory.get("totalBytes", 0)), 0)
        available_bytes = max(int(memory.get("availableBytes", 0)), 0)
        safe_budget = int(total_bytes * 0.8) if total_bytes > 0 else 0
        swap_total = max(int(memory.get("swapTotalBytes", 0)), 0)
        swap_free = max(int(memory.get("swapFreeBytes", 0)), 0)
        swap_used = max(swap_total - swap_free, 0)
        sorted_items = sorted(
            items,
            key=lambda item: max(int(item.get("sizeBytes") or 0), 0),
        )
        recommended: list[str] = []
        used = 0
        for item in sorted_items:
            size = max(int(item.get("sizeBytes") or 0), 0)
            if size <= 0:
                continue
            if safe_budget > 0 and used + size > safe_budget:
                continue
            recommended.append(safe_text(item.get("name")).strip())
            used += size
        recommendation = ", ".join(item for item in recommended if item)
        warning = ""
        if safe_budget > 0 and selected_total > safe_budget:
            warning = "선택한 로컬 모델 총량이 이 머신의 안전 RAM 예산을 넘습니다"
        elif available_bytes > 0 and selected_total > available_bytes and swap_used > 0:
            warning = "현재 가용 RAM보다 선택 모델 총량이 커서 일부 모델이 축출될 수 있습니다"
        return {
            "items": items,
            "summary": {
                "selectedCount": len(items),
                "loadedCount": sum(1 for item in items if item.get("loaded")),
                "selectedTotalBytes": selected_total,
                "loadedTotalBytes": loaded_total,
                "memory": memory,
                "safeBudgetBytes": safe_budget,
                "warning": warning,
                "recommendation": recommendation,
            },
        }

    def inspect_local_models(self, models: list[str]) -> list[dict[str, Any]]:
        config = self.freeagent_config()
        provider = safe_text(config.get("provider")).strip() or "ollama"
        if provider != "ollama":
            return [
                {
                    "name": safe_text(model).strip(),
                    "ready": False,
                    "reason": f"provider={provider} does not support local model inspection",
                }
                for model in models
                if safe_text(model).strip()
            ]
        host = safe_text(config.get("ollamaHost")).strip() or "http://127.0.0.1:11434"
        running = self.ollama_running(host)
        available_rows = self.available_ollama_models(host) if running else {}
        available = set(available_rows.keys())
        loaded = self.loaded_ollama_models(host) if running else {}
        rows: list[dict[str, Any]] = []
        for model in models:
            name = safe_text(model).strip()
            if not name:
                continue
            ready = running and name in available
            available_row = available_rows.get(name) or {}
            loaded_row = loaded.get(name) or {}
            loaded_now = bool(loaded_row)
            rows.append(
                {
                    "name": name,
                    "ready": ready,
                    "loaded": loaded_now,
                    "expiresAt": safe_text(loaded_row.get("expires_at")),
                    "sizeBytes": available_row.get("size") or loaded_row.get("size") or 0,
                    "loadedSizeBytes": loaded_row.get("size") or 0,
                    "sizeVram": loaded_row.get("size_vram"),
                    "reason": "ok" if ready else ("ollama not running" if not running else "model missing"),
                }
            )
        return rows

    def keep_local_model_loaded(self, model: str, keep_alive: str = "24h") -> tuple[bool, str]:
        config = self.freeagent_config()
        provider = safe_text(config.get("provider")).strip() or "ollama"
        if provider != "ollama":
            return False, f"provider={provider}"
        host = safe_text(config.get("ollamaHost")).strip() or "http://127.0.0.1:11434"
        if not self.ollama_running(host):
            return False, "ollama not running"
        name = safe_text(model).strip()
        if not name:
            return False, "model missing"
        payload = json.dumps({
            "model": name,
            "prompt": "",
            "stream": False,
            "keep_alive": keep_alive,
        }).encode("utf-8")
        request = Request(
            f"{host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status != 200:
                    return False, f"http {response.status}"
                response.read()
            return True, f"keep_alive={keep_alive}"
        except Exception as exc:
            return False, str(exc)

    def unload_local_model(self, model: str) -> tuple[bool, str]:
        config = self.freeagent_config()
        provider = safe_text(config.get("provider")).strip() or "ollama"
        if provider != "ollama":
            return False, f"provider={provider}"
        host = safe_text(config.get("ollamaHost")).strip() or "http://127.0.0.1:11434"
        if not self.ollama_running(host):
            return False, "ollama not running"
        name = safe_text(model).strip()
        if not name:
            return False, "model missing"
        payload = json.dumps({
            "model": name,
            "keep_alive": 0,
        }).encode("utf-8")
        request = Request(
            f"{host}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                if response.status != 200:
                    return False, f"http {response.status}"
                response.read()
            return True, "keep_alive=0"
        except Exception as exc:
            return False, str(exc)

    def preload_local_models(self, models: list[str], keep_alive: str = "24h") -> dict[str, Any]:
        unique: list[str] = []
        for model in models:
            name = safe_text(model).strip()
            if name and name not in unique:
                unique.append(name)
        results: list[dict[str, Any]] = []
        for model in unique:
            ok, message = self.keep_local_model_loaded(model, keep_alive=keep_alive)
            verify = next((item for item in self.inspect_local_models([model]) if safe_text(item.get("name")) == model), {})
            reason = self.classify_local_model_result_reason(ok, message, verify)
            results.append({
                "name": model,
                "ok": ok,
                "message": message,
                "reasonLabel": reason,
                "loaded": bool(verify.get("loaded")),
                "ready": bool(verify.get("ready")),
                "expiresAt": safe_text(verify.get("expiresAt")),
            })
        return {"items": results}

    def unload_local_models(self, models: list[str]) -> dict[str, Any]:
        unique: list[str] = []
        for model in models:
            name = safe_text(model).strip()
            if name and name not in unique:
                unique.append(name)
        results: list[dict[str, Any]] = []
        for model in unique:
            ok, message = self.unload_local_model(model)
            verify = next((item for item in self.inspect_local_models([model]) if safe_text(item.get("name")) == model), {})
            reason = self.classify_local_model_result_reason(ok, message, verify)
            results.append({
                "name": model,
                "ok": ok,
                "message": message,
                "reasonLabel": reason,
                "loaded": bool(verify.get("loaded")),
                "ready": bool(verify.get("ready")),
                "expiresAt": safe_text(verify.get("expiresAt")),
            })
        return {"items": results}

    def classify_local_model_result_reason(self, ok: bool, message: str, verify: dict[str, Any]) -> str:
        raw = safe_text(message).strip().lower()
        if ok and bool(verify.get("loaded")):
            return "loaded"
        if "ollama not running" in raw:
            return "ollama not running"
        if "model missing" in raw or (bool(verify) and not bool(verify.get("ready"))):
            return "model missing"
        if raw.startswith("http "):
            return "http error"
        if ok and not bool(verify.get("loaded")):
            return "evicted or not retained"
        if "timed out" in raw or "timeout" in raw:
            return "request timeout"
        return raw or "unknown"

    def prepare_parallel_local_models(self, job_id: str, models: list[str], keep_loaded: bool = False) -> None:
        unique: list[str] = []
        for model in models:
            name = safe_text(model).strip()
            if name and name not in unique:
                unique.append(name)
        if not unique:
            return
        if not keep_loaded:
            self.append_job_runtime_event(job_id, f"parallel local models: {', '.join(unique)}")
            return
        inspection = self.inspect_local_models(unique)
        for item in inspection:
            self.append_job_runtime_event(
                job_id,
                f"parallel local preload status: {safe_text(item.get('name'))} | installed={'yes' if item.get('ready') else 'no'} | loaded={'yes' if item.get('loaded') else 'no'}",
            )
        for model in unique:
            ok, message = self.keep_local_model_loaded(model)
            verify = next((item for item in self.inspect_local_models([model]) if safe_text(item.get("name")) == model), {})
            loaded = bool(verify.get("loaded"))
            expires_at = safe_text(verify.get("expiresAt")).strip()
            self.append_job_runtime_event(
                job_id,
                f"parallel local preload: {model} -> {'ok' if ok else 'skip'} ({message}) | loaded={'yes' if loaded else 'no'}{f' | expires={expires_at}' if expires_at else ''}",
            )

    def freeagent_setup_runtime(self, model: str = "qwen3.5:cloud", sudo_password: str = "") -> list[str]:
        messages: list[str] = []
        home = self.freeagent_home()
        if not (home / "freeagent").exists():
            raise ValueError(f"FreeAgent source not found: {home}")
        provider = self.freeagent_provider()
        if provider == "ollama" and shutil.which("ollama") is None:
            if not sudo_password:
                raise ValueError("ollama is missing. Enter sudo password and run Setup FreeAgent again.")
            messages.extend(self.ensure_ollama_installed(sudo_password))
        python = self.freeagent_python()
        if not python.exists():
            self.freeagent_venv_dir().mkdir(parents=True, exist_ok=True)
            subprocess.run(["python3", "-m", "venv", str(self.freeagent_venv_dir())], check=True)
            messages.append("created freeagent venv")
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip", "wheel", "setuptools"], cwd=str(home), check=True)
        subprocess.run([str(python), "-m", "pip", "install", "-e", ".[dev]"], cwd=str(home), check=True)
        self.freeagent_write_env(model=model)
        messages.append("installed freeagent runtime")
        messages.append("wrote .env.freeagent")
        return messages

    def start_ollama_service(self, host: str = "http://127.0.0.1:11434") -> dict[str, Any]:
        if self.ollama_running(host):
            return {"ok": True, "message": "ollama already running"}
        if shutil.which("ollama") is None:
            return {"ok": False, "message": "ollama not installed on system"}
        subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(2)
        return {
            "ok": self.ollama_running(host),
            "message": "ollama started" if self.ollama_running(host) else "ollama start attempted",
        }

    def freeagent_config(self) -> dict[str, Any]:
        env_doc = read_key_values(self.freeagent_env_file())
        provider = env_doc.get("FREEAGENT_PROVIDER", "ollama")
        if provider == "minimax2.7":
            provider = "minimax"
        host = env_doc.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        ollama_model = env_doc.get("FREEAGENT_MODEL", "qwen3.5:cloud")
        minimax_model = env_doc.get("FREEAGENT_MINIMAX_MODEL", "minimax2.7")
        ollama_running = self.ollama_running(host)
        tags = self.ollama_tags(host) if ollama_running else {"models": []}
        ollama_installed = shutil.which("ollama") is not None
        minimax_key_ready = bool(env_doc.get("MINIMAX_API_KEY", "") or env_doc.get("OPENAI_API_KEY", ""))
        runtime_ready = self.freeagent_python().exists()
        available_models = []
        if ollama_running:
            for m in tags.get("models", []):
                name = safe_text(m.get("name"))
                size_bytes = m.get("size", 0)
                size_label = f"{size_bytes / (1024**3):.1f} GB" if size_bytes > 0 else ""
                available_models.append({
                    "name": name,
                    "size": size_label,
                    "active": name == ollama_model,
                })
        shared = {
            "installed": self.freeagent_home().exists(),
            "home": str(self.freeagent_home()),
            "venvReady": runtime_ready,
            "cliReady": Path(self.freeagent_bin()).exists(),
            "envReady": self.freeagent_env_file().exists(),
        }
        ollama_status = {
            **shared,
            "provider": "ollama",
            "model": ollama_model,
            "host": host,
            "installedOnSystem": ollama_installed,
            "running": ollama_running,
            "modelReady": any(item.get("name") == ollama_model for item in tags.get("models", [])),
        }
        minimax_status = {
            **shared,
            "provider": "minimax",
            "model": minimax_model,
            "baseUrl": env_doc.get("MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1"),
            "keyReady": minimax_key_ready,
            "modelReady": minimax_key_ready and bool(minimax_model),
        }
        active = minimax_status if provider == "minimax" else ollama_status
        return {
            **shared,
            "provider": provider,
            "model": active["model"],
            "ollamaHost": host,
            "openaiBaseUrl": env_doc.get("OPENAI_BASE_URL", ""),
            "minimaxBaseUrl": env_doc.get("MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1"),
            "minimaxKeyReady": minimax_key_ready,
            "ollamaInstalled": ollama_installed,
            "ollamaRunning": ollama_running,
            "modelReady": active["modelReady"],
            "ollama": ollama_status,
            "minimax": minimax_status,
            "availableModels": available_models,
        }

    def codex_version(self) -> str:
        try:
            completed = subprocess.run(
                [self.codex_bin(), "--version"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return f"missing: {exc}"
        return (completed.stdout or completed.stderr or "unknown").strip()

    def login_status(self, instance_id: str | None = None) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [self.codex_bin(), "login", "status"],
                capture_output=True,
                text=True,
                check=False,
                env={**os.environ, **self.instance_process_env(instance_id)},
            )
        except OSError as exc:
            return {"loggedIn": False, "message": str(exc)}
        text = (completed.stdout or completed.stderr or "").strip()
        current_account = self.current_account_summary(instance_id)
        logged_in = completed.returncode == 0 and "Logged in" in text
        self.sync_account_metadata(current_account, login_ready=logged_in, login_message=text)
        return {
            "loggedIn": logged_in,
            "message": text,
            "currentAccount": current_account,
        }

    def current_account_summary(self, instance_id: str | None = None) -> dict[str, Any]:
        auth_path = self.auth_file(instance_id)
        if not auth_path.exists():
            return {}
        try:
            auth_doc = read_json(auth_path)
        except Exception:
            return {}
        tokens = auth_doc.get("tokens", {}) if isinstance(auth_doc, dict) else {}
        account_id = safe_text(tokens.get("account_id"))
        payload = self.decode_jwt_payload(safe_text(tokens.get("id_token")))
        name = safe_text(payload.get("name"))
        email = safe_text(payload.get("email"))
        auth_token_expires_at = iso_from_unix_timestamp(payload.get("exp"))
        fingerprint = self.auth_fingerprint(auth_doc)
        return {
            "accountId": account_id,
            "name": name,
            "email": email,
            "authMode": safe_text(auth_doc.get("auth_mode")),
            "fingerprint": fingerprint,
            "authTokenExpiresAt": auth_token_expires_at,
            "authTokenExpired": is_past_iso(auth_token_expires_at),
        }

    def decode_jwt_payload(self, token: str) -> dict[str, Any]:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        try:
            encoded = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(base64.urlsafe_b64decode(encoded.encode("utf-8")))
        except Exception:
            return {}

    def auth_fingerprint(self, auth_doc: dict[str, Any]) -> str:
        raw = json.dumps(auth_doc, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def auth_status_label(self, login_ready: bool, message: str, token_expired: bool) -> str:
        if login_ready:
            return "ready"
        lowered = message.lower()
        if token_expired or ("token" in lowered and "expire" in lowered) or "expired" in lowered:
            return "expired"
        if "unauthorized" in lowered or "401" in lowered:
            return "unauthorized"
        return "not_ready"

    def sync_account_metadata(
        self,
        current_account: dict[str, Any] | None = None,
        login_ready: bool | None = None,
        login_message: str = "",
    ) -> None:
        account = current_account or {}
        fingerprint = safe_text(account.get("fingerprint"))
        if not fingerprint:
            return
        metadata_path: Path | None = None
        metadata: dict[str, Any] | None = None
        for candidate in self.accounts_root_path().glob("*/metadata.json"):
            try:
                current_metadata = read_json(candidate)
            except Exception:
                continue
            if safe_text(current_metadata.get("fingerprint")) == fingerprint:
                metadata_path = candidate
                metadata = current_metadata
                break
        if metadata_path is None or metadata is None:
            return
        auth_token_expires_at = safe_text(account.get("authTokenExpiresAt"))
        auth_token_expired = bool(account.get("authTokenExpired"))
        if auth_token_expires_at:
            metadata["authTokenExpiresAt"] = auth_token_expires_at
        metadata["authTokenExpired"] = auth_token_expired
        if login_ready is not None:
            metadata["lastAuthStatus"] = self.auth_status_label(login_ready, login_message, not login_ready)
            metadata["lastAuthCheckedAt"] = now_iso()
        if login_message:
            metadata["lastAuthMessage"] = login_message
        metadata["updatedAt"] = now_iso()
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)

    def list_accounts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        current_id = self.current_account_id()
        for metadata_path in sorted(self.accounts_root_path().glob("*/metadata.json")):
            try:
                metadata = self.decorate_account_metadata(read_json(metadata_path))
            except Exception:
                continue
            metadata["isActive"] = metadata.get("id") == current_id
            items.append(metadata)
        items.sort(key=lambda item: safe_text(item.get("updatedAt")), reverse=True)
        return items

    def current_account_id(self, instance_id: str | None = None) -> str:
        current = self.current_account_summary(instance_id)
        fingerprint = safe_text(current.get("fingerprint"))
        if not fingerprint:
            return ""
        for metadata_path in self.accounts_root_path(instance_id).glob("*/metadata.json"):
            try:
                metadata = read_json(metadata_path)
            except Exception:
                continue
            if safe_text(metadata.get("fingerprint")) == fingerprint:
                return safe_text(metadata.get("id"))
        return ""

    def save_current_account(self, label: str) -> dict[str, Any]:
        login = self.login_status()
        if not login.get("loggedIn"):
            raise ValueError("Current Codex login is not ready.")
        account = login.get("currentAccount", {})
        account_id = safe_text(account.get("accountId")) or uuid.uuid4().hex[:12]
        slot_id = f"{self.slugify(label)}-{account_id[-6:]}"
        slot_dir = self.accounts_root_path() / slot_id
        slot_dir.mkdir(parents=True, exist_ok=True)
        auth_path = self.auth_file()
        if not auth_path.exists():
            raise ValueError("auth.json not found.")
        (slot_dir / "auth.json").write_text(auth_path.read_text(encoding="utf-8"), encoding="utf-8")
        if self.config_file().exists():
            (slot_dir / "config.toml").write_text(self.config_file().read_text(encoding="utf-8"), encoding="utf-8")
        metadata = {
            "id": slot_id,
            "label": label,
            "accountId": safe_text(account.get("accountId")),
            "name": safe_text(account.get("name")),
            "email": safe_text(account.get("email")),
            "authMode": safe_text(account.get("authMode")),
            "fingerprint": safe_text(account.get("fingerprint")),
            "tokenExpiresAt": "",
            "tokenExpired": False,
            "authTokenExpiresAt": safe_text(account.get("authTokenExpiresAt")),
            "authTokenExpired": bool(account.get("authTokenExpired")),
            "lastAuthStatus": self.auth_status_label(True, "", False),
            "lastAuthCheckedAt": now_iso(),
            "createdAt": now_iso(),
            "updatedAt": now_iso(),
        }
        with (slot_dir / "metadata.json").open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        return {
            "saved": True,
            "account": metadata,
            "loginReady": True,
        }

    def activate_account(self, account_id: str) -> dict[str, Any]:
        slot_dir = self.accounts_root_path() / account_id
        auth_path = slot_dir / "auth.json"
        if not auth_path.exists():
            raise ValueError(f"Account slot not found: {account_id}")
        self.codex_home().mkdir(parents=True, exist_ok=True)
        self.auth_file().write_text(auth_path.read_text(encoding="utf-8"), encoding="utf-8")
        config_path = slot_dir / "config.toml"
        if config_path.exists():
            self.config_file().write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        metadata_path = slot_dir / "metadata.json"
        metadata = read_json(metadata_path) if metadata_path.exists() else {"id": account_id}
        metadata["updatedAt"] = now_iso()
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        login = self.login_status()
        return {
            "activated": True,
            "account": metadata,
            "loginReady": login.get("loggedIn", False),
        }

    def account_slot_dir(self, account_id: str, instance_id: str | None = None) -> Path:
        return self.accounts_root_path(instance_id) / safe_text(account_id).strip()

    def account_slot_summary(self, account_id: str, instance_id: str | None = None) -> dict[str, Any]:
        slot_dir = self.account_slot_dir(account_id, instance_id)
        metadata = read_json_or_default(slot_dir / "metadata.json", {"id": account_id})
        auth_path = slot_dir / "auth.json"
        if auth_path.exists():
            try:
                auth_doc = read_json(auth_path)
            except Exception:
                auth_doc = {}
            tokens = auth_doc.get("tokens", {}) if isinstance(auth_doc, dict) else {}
            payload = self.decode_jwt_payload(safe_text(tokens.get("id_token")))
            auth_token_expires_at = iso_from_unix_timestamp(payload.get("exp"))
            metadata.update(
                {
                    "accountId": safe_text(tokens.get("account_id")) or safe_text(metadata.get("accountId")),
                    "name": safe_text(payload.get("name")) or safe_text(metadata.get("name")),
                    "email": safe_text(payload.get("email")) or safe_text(metadata.get("email")),
                    "authMode": safe_text(auth_doc.get("auth_mode")) or safe_text(metadata.get("authMode")),
                    "fingerprint": self.auth_fingerprint(auth_doc) if auth_doc else safe_text(metadata.get("fingerprint")),
                    "authTokenExpiresAt": auth_token_expires_at or safe_text(metadata.get("authTokenExpiresAt")),
                    "authTokenExpired": is_past_iso(auth_token_expires_at) if auth_token_expires_at else bool(metadata.get("authTokenExpired")),
                }
            )
        metadata["id"] = safe_text(metadata.get("id")) or safe_text(account_id)
        return self.decorate_account_metadata(metadata)

    def list_account_slots(self) -> list[dict[str, Any]]:
        accounts_root = self.accounts_root_path()
        if not accounts_root.exists():
            return []
        slots = []
        for item in sorted(accounts_root.iterdir()):
            if not item.is_dir():
                continue
            metadata_path = item / "metadata.json"
            if metadata_path.exists():
                slots.append(read_json(metadata_path))
            else:
                slots.append({"id": item.name, "label": item.name})
        return slots

    def update_account_status(self, account_id: str, **kwargs: Any) -> dict[str, Any]:
        slot_dir = self.accounts_root_path() / account_id
        metadata_path = slot_dir / "metadata.json"
        if not metadata_path.exists():
            raise ValueError(f"Account metadata not found: {account_id}")
        metadata = read_json(metadata_path)
        metadata.update(kwargs)
        metadata["updatedAt"] = now_iso()
        with metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)
        return metadata

    def update_account_settings(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        manual_status = safe_text(payload.get("manualStatus")).strip().lower()
        if manual_status not in {"", "auto", "ready", "quota_wait", "open_pending", "unauthorized", "login_expired"}:
            raise ValueError(f"Unsupported manualStatus: {manual_status}")
        next_available_at = normalize_iso_datetime(payload.get("nextAvailableAt"))
        update_doc = {
            "manualStatus": "" if manual_status in {"", "auto"} else manual_status,
            "nextAvailableAt": next_available_at,
            "manualNote": safe_text(payload.get("manualNote")).strip(),
            "nextAvailableAtSource": "manual" if next_available_at else "",
        }
        if "exhausted" in payload:
            update_doc["exhausted"] = safe_bool(payload.get("exhausted"), False)
        elif not next_available_at:
            update_doc["exhausted"] = False
        updated = self.update_account_status(account_id, **update_doc)
        return self.decorate_account_metadata(updated)

    def update_action_routing(self, action_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        items = self.actions_doc.get("actions", [])
        if not isinstance(items, list):
            raise ValueError("actions config is malformed")
        target: dict[str, Any] | None = None
        for item in items:
            if isinstance(item, dict) and safe_text(item.get("id")) == action_id:
                target = item
                break
        if target is None:
            raise ValueError(f"Unknown action: {action_id}")
        preferred_account_id = safe_text(payload.get("preferredAccountId")).strip()
        preferred_account_ids = [
            safe_text(item).strip()
            for item in (payload.get("preferredAccountIds") or [])
            if safe_text(item).strip()
        ]
        if not preferred_account_ids:
            preferred_account_ids = [
                item.strip()
                for item in safe_text(payload.get("preferredAccountChain")).split(",")
                if item.strip()
            ]
        preferred_account_type = safe_text(payload.get("preferredAccountType")).strip().lower()
        runtime_preset = safe_text(payload.get("runtimePreset")).strip().lower()
        if preferred_account_type not in {"", "auto", "free", "paid"}:
            raise ValueError(f"Unsupported preferredAccountType: {preferred_account_type}")
        if runtime_preset not in {"", "auto", "saver", "question", "summary", "migration", "implementation", "review", "debug", "lite", "balanced", "full"}:
            raise ValueError(f"Unsupported runtimePreset: {runtime_preset}")
        target["preferredAccountId"] = preferred_account_id
        target["preferredAccountIds"] = preferred_account_ids
        target["preferredAccountType"] = "" if preferred_account_type in {"", "auto"} else preferred_account_type
        target["runtimePreset"] = "" if runtime_preset in {"", "auto"} else runtime_preset
        self.save_actions_doc()
        self.refresh_actions_index()
        return {
            "saved": True,
            "action": self.actions.get(action_id, target),
            "actions": self.actions_doc.get("actions", []),
        }

    def extract_retry_available_at(self, text: str) -> str:
        raw = strip_ansi(safe_text(text))
        if not raw:
            return ""
        natural_patterns = [
            r"([A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?\,\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))",
            r"([A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?\s+\d{4}\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))",
            r"([A-Z][a-z]{2,8}\s+\d{1,2}(?:st|nd|rd|th)?\,\s+\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM)\s+\d{4})",
        ]
        for natural_pattern in natural_patterns:
            natural_match = re.search(natural_pattern, raw)
            if not natural_match:
                continue
            candidate_raw = natural_match.group(1).strip().rstrip(".")
            candidate_raw = re.sub(r"(\d)(st|nd|rd|th)", r"\1", candidate_raw)
            candidate_raw = re.sub(r"\s+", " ", candidate_raw)
            for fmt in (
                "%b %d, %Y %I:%M %p",
                "%B %d, %Y %I:%M %p",
                "%b %d %Y %I:%M %p",
                "%B %d %Y %I:%M %p",
                "%b %d, %I:%M %p %Y",
                "%B %d, %I:%M %p %Y",
                "%b %d, %Y %I:%M:%S %p",
                "%B %d, %Y %I:%M:%S %p",
            ):
                try:
                    parsed = datetime.strptime(candidate_raw, fmt)
                    return parsed.replace(tzinfo=KST).isoformat(timespec="seconds")
                except ValueError:
                    continue
        patterns = [
            r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})",
            r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?",
        ]
        for pattern in patterns:
            match = re.search(pattern, raw)
            if match:
                candidate = normalize_iso_datetime(match.group(0))
                if candidate:
                    return candidate
        time_only_match = re.search(r"try again at\s+(\d{1,2}:\d{2}(?::\d{2})?\s*(?:AM|PM))", raw, re.IGNORECASE)
        if time_only_match:
            candidate_raw = re.sub(r"\s+", " ", time_only_match.group(1).strip().upper())
            for fmt in ("%I:%M %p", "%I:%M:%S %p"):
                try:
                    parsed_time = datetime.strptime(candidate_raw, fmt)
                    now_kst = datetime.now(timezone.utc).astimezone(KST)
                    candidate = now_kst.replace(
                        hour=parsed_time.hour,
                        minute=parsed_time.minute,
                        second=getattr(parsed_time, "second", 0),
                        microsecond=0,
                    )
                    if candidate <= now_kst:
                        candidate = candidate + timedelta(days=1)
                    return candidate.isoformat(timespec="seconds")
                except ValueError:
                    continue
        lowered = raw.lower()
        hours = 0
        minutes = 0
        hour_match = re.search(r"(?:in\s+)?(\d+)\s*(?:hours?|hrs?|h|시간)", lowered)
        minute_match = re.search(r"(?:in\s+)?(\d+)\s*(?:minutes?|mins?|m|분)", lowered)
        if hour_match:
            hours = safe_int(hour_match.group(1), 0)
        if minute_match:
            minutes = safe_int(minute_match.group(1), 0)
        if hours > 0 or minutes > 0:
            future = datetime.now(timezone.utc).astimezone(KST) + timedelta(hours=hours, minutes=minutes)
            return future.isoformat(timespec="seconds")
        return ""

    def detect_external_auth_status(self, text: str) -> str:
        lowered = safe_text(text).lower()
        if any(marker in lowered for marker in ("quota exceeded", "429 too many requests", "rate limit reached", "usage limit", "try again at")):
            return "quota_wait"
        if any(marker in lowered for marker in (
            "refresh_token_reused",
            "token_expired",
            "failed to refresh token",
            "provided authentication token is expired",
            "your access token could not be refreshed",
            "please log out and sign in again",
            "please try signing in again",
            "responses_websocket: failed to connect to websocket: http error: 401 unauthorized",
            "unexpectedcontenttype",
        )):
            return "unauthorized"
        if "unauthorized" in lowered or "401" in lowered:
            return "unauthorized"
        if "expired" in lowered or ("token" in lowered and "expire" in lowered):
            return "login_expired"
        return ""

    def ingest_codex_output(
        self,
        output_text: str,
        exit_code: int = 0,
        instance_id: str | None = None,
        account_id: str = "",
    ) -> dict[str, Any]:
        current_account = self.current_account_summary(instance_id)
        slot_id = safe_text(account_id).strip() or self.current_account_id(instance_id)
        if not slot_id:
            return {"updated": False, "message": "No active account slot matched current auth state."}
        output = safe_text(output_text)
        status_code = self.detect_external_auth_status(output)
        update_doc: dict[str, Any] = {
            "lastSeenAt": now_iso(),
        }
        if status_code == "quota_wait":
            update_doc["exhausted"] = True
            update_doc["lastQuotaMessage"] = self.summarize_text(output, 2000)
            update_doc["lastQuotaDetectedAt"] = now_iso()
            derived_next_available_at = self.extract_retry_available_at(output)
            if derived_next_available_at:
                update_doc["nextAvailableAt"] = derived_next_available_at
                update_doc["nextAvailableAtSource"] = "quota-output"
            else:
                update_doc["nextAvailableAt"] = ""
                update_doc["nextAvailableAtSource"] = ""
        elif status_code in {"unauthorized", "login_expired"}:
            update_doc["lastAuthStatus"] = "unauthorized" if status_code == "unauthorized" else "expired"
            update_doc["lastAuthMessage"] = self.summarize_text(output, 2000)
            update_doc["lastAuthCheckedAt"] = now_iso()
        elif exit_code == 0:
            update_doc["exhausted"] = False
            update_doc["nextAvailableAt"] = ""
            update_doc["nextAvailableAtSource"] = ""
            update_doc["lastQuotaMessage"] = ""
            update_doc["lastQuotaDetectedAt"] = ""
            update_doc["lastAuthStatus"] = "ready"
            update_doc["lastAuthMessage"] = ""
            update_doc["lastAuthCheckedAt"] = now_iso()
        if current_account:
            update_doc["authTokenExpiresAt"] = safe_text(current_account.get("authTokenExpiresAt"))
            update_doc["authTokenExpired"] = bool(current_account.get("authTokenExpired"))
        updated = self.update_account_status(slot_id, **update_doc)
        return {
            "updated": True,
            "accountId": slot_id,
            "statusCode": self.account_status_code(updated),
            "nextAvailableAt": safe_text(updated.get("nextAvailableAt")),
            "message": "Account metadata updated from external codex output.",
        }

    def run_account_healthcheck_prompt(self, account_id: str, instance_id: str | None = None) -> dict[str, Any]:
        env = os.environ.copy()
        env.update({key: value for key, value in self.build_account_env(account_id, instance_id).items() if value})
        command = [
            self.codex_bin(),
            "exec",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-C",
            str(self.app_root),
            "--sandbox",
            "read-only",
            "Reply with exactly READY.",
        ]
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            env=env,
            timeout=45,
            check=False,
        )
        output_text = "\n".join(
            part for part in [safe_text(completed.stdout).strip(), safe_text(completed.stderr).strip()] if part
        ).strip()
        update = self.ingest_codex_output(
            output_text,
            exit_code=completed.returncode,
            instance_id=instance_id,
            account_id=account_id,
        )
        return {
            "ok": completed.returncode == 0,
            "exitCode": completed.returncode,
            "output": output_text,
            "accountUpdate": update,
        }

    def account_plan_expired(self, slot: dict[str, Any]) -> bool:
        return False

    def account_quota_wait(self, slot: dict[str, Any]) -> bool:
        next_available_at = safe_text(slot.get("nextAvailableAt")).strip()
        return is_future_iso(next_available_at)

    def account_manual_status(self, slot: dict[str, Any]) -> str:
        return safe_text(slot.get("manualStatus")).strip().lower()

    def account_status_code(self, slot: dict[str, Any]) -> str:
        manual_status = self.account_manual_status(slot)
        if manual_status in {"open_pending", "quota_wait", "unauthorized", "login_expired", "ready"}:
            return manual_status
        if self.account_plan_expired(slot):
            return "plan_expired"
        if self.account_quota_wait(slot) or bool(slot.get("exhausted")):
            return "quota_wait"
        auth_status = safe_text(slot.get("lastAuthStatus")).strip().lower()
        if auth_status == "ready":
            return "ready"
        if auth_status == "unauthorized":
            return "unauthorized"
        if auth_status in {"expired", "not_ready"} or bool(slot.get("tokenExpired")) or bool(slot.get("authTokenExpired")):
            return "login_expired"
        return "unknown"

    def decorate_account_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        item = dict(metadata or {})
        status_code = self.account_status_code(item)
        item["manualStatus"] = self.account_manual_status(item)
        item["planExpired"] = status_code == "plan_expired"
        item["quotaWaiting"] = status_code == "quota_wait"
        item["openPending"] = status_code == "open_pending"
        item["loginReady"] = status_code in {"ready", "unknown", "open_pending", "quota_wait"}
        item["statusCode"] = status_code
        suggested_next_available_at = ""
        suggested_source = ""
        if not safe_text(item.get("nextAvailableAt")).strip():
            for source_name, source_value in (
                ("quota-message", item.get("lastQuotaMessage")),
                ("auth-message", item.get("lastAuthMessage")),
            ):
                candidate = self.extract_retry_available_at(source_value)
                if candidate:
                    suggested_next_available_at = candidate
                    suggested_source = source_name
                    break
        item["suggestedNextAvailableAt"] = suggested_next_available_at
        item["suggestedNextAvailableSource"] = suggested_source
        return item

    def account_rotation_key(self, slot: dict[str, Any]) -> tuple[str, str]:
        return (
            safe_text(slot.get("updatedAt"))
            or safe_text(slot.get("lastAuthCheckedAt"))
            or safe_text(slot.get("createdAt"))
            or "",
            safe_text(slot.get("id")),
        )

    def account_type_code(self, slot: dict[str, Any]) -> str:
        return safe_text(slot.get("accountType") or slot.get("planType")).strip().lower()

    def account_is_reusable(self, slot: dict[str, Any]) -> bool:
        return safe_text(slot.get("statusCode")) in {"ready", "unknown"}

    def account_is_activation_candidate(self, slot: dict[str, Any]) -> bool:
        manual_status = self.account_manual_status(slot)
        if manual_status in {"open_pending"}:
            return False
        status_code = safe_text(slot.get("statusCode")).strip().lower()
        if status_code in {"ready", "unknown", "unauthorized", "login_expired"}:
            return True
        if status_code == "quota_wait":
            # API/account metadata can miss the actual reusable date. Only hard-skip when
            # a future retry timestamp exists; otherwise probe by activate -> loginReady.
            next_available_at = safe_text(slot.get("nextAvailableAt")).strip()
            return not is_future_iso(next_available_at)
        return False

    def account_matches_preference(self, slot: dict[str, Any], preferred_types: list[str]) -> bool:
        if not preferred_types:
            return True
        return self.account_type_code(slot) == preferred_types[0]

    def account_capacity_score(self, slot: dict[str, Any]) -> int:
        status_code = safe_text(slot.get("statusCode")).strip().lower()
        if status_code == "ready":
            score = 100
        elif status_code == "unknown":
            score = 70
        elif status_code == "open_pending":
            score = 35
        else:
            return -1000
        if self.account_type_code(slot) in {"paid", "pro"}:
            score += 20
        expires_at = safe_text(slot.get("authTokenExpiresAt")).strip()
        if expires_at:
            try:
                remaining = datetime.fromisoformat(expires_at) - datetime.now(timezone.utc).astimezone(KST)
                if remaining <= timedelta(minutes=15):
                    score -= 60
                elif remaining <= timedelta(hours=2):
                    score -= 30
                elif remaining <= timedelta(hours=12):
                    score -= 10
            except ValueError:
                pass
        if safe_bool(slot.get("exhausted"), False):
            score -= 80
        return score

    def explain_account_capacity(self, slot: dict[str, Any]) -> str:
        status_code = safe_text(slot.get("statusCode")) or "unknown"
        account_type = self.account_type_code(slot) or "unknown"
        expires_at = safe_text(slot.get("authTokenExpiresAt")).strip()
        bits = [status_code, account_type]
        if expires_at:
            bits.append(f"auth={expires_at}")
        return ", ".join(bits)

    def reusable_parallel_accounts(
        self,
        preferred_account_types: list[str] | None = None,
        current_account_id: str = "",
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        ready_only: bool = True,
    ) -> list[dict[str, Any]]:
        preferred_types = [safe_text(item).strip().lower() for item in (preferred_account_types or []) if safe_text(item).strip()]
        preferred_ids = [safe_text(item).strip() for item in (preferred_account_ids or []) if safe_text(item).strip()]
        slots = [self.account_slot_summary(safe_text(item.get("id"))) for item in self.list_account_slots()]
        reusable = [
            slot for slot in slots
            if self.account_is_activation_candidate(slot)
            and (not ready_only or safe_text(slot.get("statusCode")).strip().lower() == "ready")
        ]

        def sort_key(slot: dict[str, Any]) -> tuple[int, int, int, str]:
            slot_id = safe_text(slot.get("id"))
            preferred_rank = 0
            if preferred_ids and slot_id in preferred_ids:
                preferred_rank = 3
            elif preferred_account_id and slot_id == preferred_account_id:
                preferred_rank = 2
            elif current_account_id and slot_id == current_account_id:
                preferred_rank = 1
            type_rank = 1 if self.account_matches_preference(slot, preferred_types) else 0
            return (-preferred_rank, -type_rank, -self.account_capacity_score(slot), slot_id)

        reusable.sort(key=sort_key)
        return reusable

    def probe_parallel_account_candidates(
        self,
        job_id: str = "",
        preferred_account_types: list[str] | None = None,
        current_account_id: str = "",
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        max_accounts: int = 4,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        ranked = self.reusable_parallel_accounts(
            preferred_account_types=preferred_account_types,
            current_account_id=current_account_id,
            preferred_account_id=preferred_account_id,
            preferred_account_ids=preferred_account_ids,
            ready_only=False,
        )
        ready_accounts: list[dict[str, Any]] = []
        probe_rows: list[dict[str, Any]] = []
        for slot in ranked:
            slot_id = safe_text(slot.get("id")).strip()
            if not slot_id:
                continue
            row = {
                "at": now_iso(),
                "accountId": slot_id,
                "accountLabel": safe_text(slot.get("label") or slot.get("email") or slot_id),
                "beforeStatus": safe_text(slot.get("statusCode")) or "unknown",
                "decision": "probe",
            }
            try:
                result = self.activate_account(slot_id)
                ready = safe_bool(result.get("loginReady"), False)
                row["loginReady"] = ready
                row["decision"] = "ready" if ready else "not_ready"
                probed = self.account_slot_summary(slot_id)
                if ready:
                    ready_accounts.append(probed)
                    if len(ready_accounts) >= max(1, max_accounts):
                        probe_rows.append(row)
                        break
                else:
                    self.update_account_status(
                        slot_id,
                        lastAuthStatus="not_ready",
                        lastAuthMessage="Parallel preflight activate/loginReady probe failed.",
                        lastAuthCheckedAt=now_iso(),
                    )
            except Exception as exc:
                row["decision"] = "activation_failed"
                row["message"] = safe_text(exc)
            probe_rows.append(row)
        if job_id:
            lines = [
                f"- {safe_text(row.get('accountLabel') or row.get('accountId'))}: "
                f"{safe_text(row.get('beforeStatus'))} -> {safe_text(row.get('decision'))}"
                for row in probe_rows
            ]
            self.append_job_runtime_event(job_id, "parallel login probe:\n" + ("\n".join(lines) if lines else "(no candidates)"))
        return ready_accounts, probe_rows

    def build_account_env(self, account_id: str, instance_id: str | None = None) -> dict[str, str]:
        slot_dir = self.account_slot_dir(account_id, instance_id)
        env = dict(self.instance_process_env(instance_id))
        env["CARBONET_CODEX_HOME"] = str(slot_dir)
        return env

    def select_best_account(
        self,
        exclude_account_ids: set[str] | None = None,
        preferred_account_types: list[str] | None = None,
        current_account_id: str = "",
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        reusable_only: bool = False,
    ) -> dict[str, Any] | None:
        slots = [self.decorate_account_metadata(slot) for slot in self.list_account_slots()]
        excluded = {safe_text(item) for item in (exclude_account_ids or set()) if safe_text(item)}
        preferred_types = [safe_text(item).strip().lower() for item in (preferred_account_types or []) if safe_text(item).strip()]
        preferred_ids = [safe_text(item).strip() for item in (preferred_account_ids or []) if safe_text(item).strip()]
        current_slot = next((slot for slot in slots if safe_text(slot.get("id")) == current_account_id), None)
        preferred_slot = next((slot for slot in slots if safe_text(slot.get("id")) == preferred_account_id), None)

        for preferred_id in preferred_ids:
            slot = next((item for item in slots if safe_text(item.get("id")) == preferred_id), None)
            if slot and safe_text(slot.get("id")) not in excluded and self.account_is_activation_candidate(slot):
                if self.account_matches_preference(slot, preferred_types):
                    return slot

        if preferred_slot and safe_text(preferred_slot.get("id")) not in excluded and self.account_is_activation_candidate(preferred_slot):
            if self.account_matches_preference(preferred_slot, preferred_types):
                return preferred_slot

        if current_slot and safe_text(current_slot.get("id")) not in excluded and self.account_is_activation_candidate(current_slot):
            current_status = safe_text(current_slot.get("statusCode")).strip().lower()
            if current_status in {"ready", "unknown"}:
                return current_slot
            if self.account_matches_preference(current_slot, preferred_types):
                return current_slot
            if not any(
                self.account_is_activation_candidate(slot) and self.account_matches_preference(slot, preferred_types)
                for slot in slots
                if safe_text(slot.get("id")) != current_account_id
            ):
                return current_slot

        def pick(pool: list[dict[str, Any]]) -> dict[str, Any] | None:
            filtered = [slot for slot in pool if safe_text(slot.get("id")) not in excluded]
            if filtered:
                return min(filtered, key=self.account_rotation_key)
            return None

        healthy = [slot for slot in slots if safe_text(slot.get("statusCode")) == "ready"]
        reusable = [slot for slot in slots if self.account_is_activation_candidate(slot)]
        delayed = [slot for slot in slots if safe_text(slot.get("statusCode")) in {"open_pending", "quota_wait"}]
        any_slot = list(slots)

        def pick_with_type_priority(pool: list[dict[str, Any]]) -> dict[str, Any] | None:
            if not preferred_types:
                return pick(pool)
            for preferred_type in preferred_types:
                typed_pool = [
                    slot for slot in pool
                    if safe_text(slot.get("accountType") or slot.get("planType")).strip().lower() == preferred_type
                ]
                chosen = pick(typed_pool)
                if chosen:
                    return chosen
            return pick(pool)

        if reusable_only:
            return pick_with_type_priority(healthy) or pick_with_type_priority(reusable)

        return (
            pick_with_type_priority(healthy)
            or pick_with_type_priority(reusable)
            or pick_with_type_priority(delayed)
            or pick_with_type_priority(any_slot)
        )

    def activate_first_reusable_account(
        self,
        excluded_ids: set[str] | None = None,
        preferred_account_types: list[str] | None = None,
        current_account_id: str = "",
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        probe_history: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        excluded = {safe_text(item).strip() for item in (excluded_ids or set()) if safe_text(item).strip()}
        while True:
            best = self.select_best_account(
                exclude_account_ids=excluded,
                preferred_account_types=preferred_account_types,
                current_account_id=current_account_id,
                preferred_account_id=preferred_account_id,
                preferred_account_ids=preferred_account_ids,
                reusable_only=False,
            )
            if not best:
                return None
            slot_id = safe_text(best.get("id")).strip()
            probe_doc = {
                "at": now_iso(),
                "accountId": slot_id,
                "accountLabel": safe_text(best.get("label") or best.get("email") or best.get("accountId") or slot_id),
                "beforeStatus": safe_text(best.get("statusCode")) or "unknown",
                "nextAvailableAt": safe_text(best.get("nextAvailableAt")),
                "decision": "activate_probe",
            }
            try:
                result = self.activate_account(slot_id)
            except Exception as exc:
                probe_doc["decision"] = "activation_failed"
                probe_doc["message"] = safe_text(exc)
                if probe_history is not None:
                    probe_history.append(probe_doc)
                excluded.add(slot_id)
                continue
            if safe_bool(result.get("loginReady"), False):
                probe_doc["decision"] = "selected"
                probe_doc["loginReady"] = True
                if probe_history is not None:
                    probe_history.append(probe_doc)
                return best
            probe_doc["decision"] = "login_not_ready"
            probe_doc["loginReady"] = False
            probe_doc["message"] = "Activation completed but codex login status was not ready."
            if probe_history is not None:
                probe_history.append(probe_doc)
            self.update_account_status(
                slot_id,
                lastAuthStatus="unauthorized",
                lastAuthMessage="Activation completed but codex login status was not ready.",
                lastAuthCheckedAt=now_iso(),
            )
            excluded.add(slot_id)

    def runtime_preset_options(self, preset: str) -> dict[str, Any]:
        if preset == "saver":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": True,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": True,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": False,
                "allowSourceAnalysis": False,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": True,
                "focusScope": "",
                "sessionContextLimit": 120,
                "promptCharsLimit": 800,
            }
        if preset == "question":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": True,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": True,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": False,
                "allowSourceAnalysis": False,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": True,
                "focusScope": "",
                "sessionContextLimit": 80,
                "promptCharsLimit": 600,
            }
        if preset == "summary":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": True,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": False,
                "allowSourceAnalysis": True,
                "allowDocsRead": True,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": True,
                "focusScope": "",
                "sessionContextLimit": 180,
                "promptCharsLimit": 1200,
            }
        if preset == "migration":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": True,
                "includeMenuContext": False,
                "autoSaverForQuestions": False,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": True,
                "allowSourceAnalysis": True,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": False,
                "focusScope": "",
                "sessionContextLimit": 240,
                "promptCharsLimit": 2200,
            }
        if preset == "implementation":
            return {
                "includeBrowserContext": True,
                "includeReferenceContext": False,
                "includeMenuContext": True,
                "autoSaverForQuestions": False,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": True,
                "allowSourceAnalysis": True,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": False,
                "focusScope": "",
                "sessionContextLimit": 320,
                "promptCharsLimit": 2400,
            }
        if preset == "review":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": False,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": True,
                "allowSourceAnalysis": True,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": True,
                "focusScope": "",
                "sessionContextLimit": 320,
                "promptCharsLimit": 1800,
            }
        if preset == "debug":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": False,
                "compactPreferencePreamble": False,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": True,
                "allowSourceAnalysis": True,
                "allowDocsRead": True,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": False,
                "focusScope": "",
                "sessionContextLimit": 480,
                "promptCharsLimit": 2200,
            }
        if preset == "lite":
            return {
                "includeBrowserContext": False,
                "includeReferenceContext": False,
                "includeMenuContext": False,
                "autoSaverForQuestions": True,
                "compactPreferencePreamble": True,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": True,
                "dedupeConsecutivePromptLines": True,
                "stripMarkdownFences": False,
                "includeSessionContext": False,
                "allowSourceAnalysis": False,
                "allowDocsRead": False,
                "allowSkillsRead": False,
                "preferMinimalScan": True,
                "preferBriefOutput": True,
                "focusScope": "",
                "sessionContextLimit": 240,
                "promptCharsLimit": 1600,
            }
        if preset == "full":
            return {
                "includeBrowserContext": True,
                "includeReferenceContext": True,
                "includeMenuContext": True,
                "autoSaverForQuestions": False,
                "compactPreferencePreamble": False,
                "omitPreferencePreamble": False,
                "compactPromptWhitespace": False,
                "dedupeConsecutivePromptLines": False,
                "stripMarkdownFences": False,
                "includeSessionContext": True,
                "allowSourceAnalysis": True,
                "allowDocsRead": True,
                "allowSkillsRead": True,
                "preferMinimalScan": False,
                "preferBriefOutput": False,
                "focusScope": "",
                "sessionContextLimit": 0,
                "promptCharsLimit": 0,
            }
        return {
            "includeBrowserContext": True,
            "includeReferenceContext": True,
            "includeMenuContext": True,
            "autoSaverForQuestions": True,
            "compactPreferencePreamble": False,
            "omitPreferencePreamble": False,
            "compactPromptWhitespace": True,
            "dedupeConsecutivePromptLines": True,
            "stripMarkdownFences": False,
            "includeSessionContext": True,
            "allowSourceAnalysis": True,
            "allowDocsRead": True,
            "allowSkillsRead": True,
            "preferMinimalScan": True,
            "preferBriefOutput": True,
            "focusScope": "",
            "sessionContextLimit": 480,
            "promptCharsLimit": 0,
        }

    def preferred_account_types_for_payload(self, payload: dict[str, Any], action: dict[str, Any] | None = None) -> list[str]:
        if action:
            configured = safe_text(action.get("preferredAccountType")).strip().lower()
            if configured in {"free", "paid"}:
                return [configured, "paid" if configured == "free" else "free"]
        mode = safe_text(payload.get("mode")).strip()
        if mode in {"assistant_custom", "codex_custom"}:
            return ["paid", "free"]
        cli_id = safe_text(payload.get("cli")).strip()
        if cli_id in {"codex", "minimax-codex"}:
            return ["paid", "free"]
        if action:
            kind = safe_text(action.get("kind")).strip()
            group = safe_text(action.get("group")).strip()
            if kind == "codex" or group in {"build", "codex"}:
                return ["paid", "free"]
        return ["free", "paid"]

    def inferred_runtime_preset_for_payload(self, payload: dict[str, Any], action: dict[str, Any] | None = None) -> str:
        mode = safe_text(payload.get("mode")).strip()
        cli_id = safe_text(payload.get("cli")).strip()
        prompt = safe_text(payload.get("prompt")).strip()
        prompt_lower = prompt.lower()
        prompt_length = len(prompt)
        if mode == "shell_custom":
            return "saver"
        if action:
            kind = safe_text(action.get("kind")).strip()
            group = safe_text(action.get("group")).strip()
            action_id = safe_text(action.get("id")).strip()
            if kind == "shell" or group in {"repo", "ops"}:
                return "saver"
            if action_id == "codex-structure-summary":
                return "summary"
            if action_id == "codex-change-review":
                return "review"
            if action_id == "codex-build-debug":
                return "debug"
            if kind == "codex" or group in {"codex", "build"}:
                return "lite"
        if prompt_is_low_signal(prompt):
            return "question"
        if any(token in prompt_lower for token in ["선택한 reference 화면", "reference 화면", "reference html:", "reference path:", "migration"]):
            return "migration"
        if any(token in prompt_lower for token in ["리뷰", "review", "검토", "회귀 위험", "테스트 누락"]):
            return "review"
        if any(token in prompt_lower for token in ["빌드 실패", "build failed", "debug", "에러", "오류", "stack trace", "원인"]):
            return "debug"
        if any(token in prompt_lower for token in ["구조", "진입점", "요약", "정리해줘", "설명해줘", "summary"]):
            return "summary"
        if any(token in prompt_lower for token in ["만들어줘", "구현", "추가해줘", "수정해줘", "교체", "변환", "마이그레이션해줘"]):
            return "implementation"
        if self.is_question_like_prompt(prompt) and prompt_length <= 600:
            return "question"
        if re.search(r"\b(review|inspect|summari[sz]e|explain|why|what|status|analy[sz]e|compare)\b", prompt_lower):
            return "lite"
        if re.search(r"\b(full|thorough|deep|exhaustive|across repo|whole repo|entire repo|architecture|migration plan)\b", prompt_lower):
            return "full"
        if prompt_length >= 2500:
            return "full"
        if mode in {"assistant_custom", "codex_custom"}:
            return "balanced"
        if cli_id in {"freeagent", "minimax", "minimax-codex"}:
            return "lite"
        return "balanced"

    def prompt_requests_file_change(self, payload: dict[str, Any]) -> bool:
        prompt = safe_text(payload.get("prompt")).strip().lower()
        if not prompt:
            return False
        write_markers = [
            "파일 만들어",
            "파일 생성",
            "html 파일",
            "만들어줘",
            "작성해줘",
            "추가해줘",
            "수정해줘",
            "고쳐줘",
            "삭제해줘",
            "저장해줘",
            "create file",
            "write file",
            "add file",
            "modify",
            "update",
            "fix",
        ]
        if any(marker in prompt for marker in write_markers):
            return True
        return bool(re.search(r"\b(create|write|add|update|modify|fix)\b.*\b(file|html|css|js|java|py|md|json)\b", prompt))

    def writable_windows_desktop(self) -> Path | None:
        candidates = sorted(Path("/mnt/c/Users").glob("*/Desktop")) if Path("/mnt/c/Users").exists() else []
        preferred = [
            path for path in candidates
            if path.name == "Desktop" and path.parent.name.lower() not in {"default", "default user", "public", "all users"}
        ]
        for path in preferred + candidates:
            try:
                if path.is_dir() and os.access(path, os.W_OK | os.X_OK):
                    return path
            except OSError:
                continue
        return None

    def build_direct_file_creation_spec(
        self,
        payload: dict[str, Any],
        workspace: dict[str, Any],
        session: dict[str, Any],
        plan_step: str = "",
    ) -> dict[str, Any] | None:
        prompt = safe_text(payload.get("prompt")).strip()
        lowered = prompt.lower()
        if not ("html" in lowered and any(marker in lowered for marker in ("바탕화면", "desktop", "윈도우 마운트", "/mnt/c"))):
            return None
        desktop = self.writable_windows_desktop()
        if desktop is None:
            return None
        name_match = re.search(r"([A-Za-z0-9_.-]+)\s*파일\s*$", prompt) or re.search(r"([A-Za-z0-9_.-]+)\s*파일", prompt)
        stem = name_match.group(1) if name_match else "test"
        stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-") or "test"
        filename = stem if stem.lower().endswith(".html") else f"{stem}.html"
        target = desktop / filename
        html = "\n".join([
            "<!doctype html>",
            '<html lang="ko">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            f"  <title>{stem}</title>",
            "</head>",
            "<body>",
            f"  <h1>{stem}</h1>",
            "  <p>Codex Launcher generated this test HTML file.</p>",
            "</body>",
            "</html>",
            "",
        ])
        command = [
            "bash",
            "-lc",
            "python3 - <<'PY'\n"
            "from pathlib import Path\n"
            f"target = Path({str(target)!r})\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            f"target.write_text({html!r}, encoding='utf-8')\n"
            "print(f'created {target}')\n"
            "PY",
        ]
        return {
            "title": "Create Windows Desktop HTML",
            "kind": "shell",
            "cwd": safe_text(workspace["path"]),
            "command": command,
            "command_preview": f"create {target}",
            "effective_prompt": prompt,
            "route_note": f"direct file creation: {target}",
        }

    def runtime_preset_for_payload(self, payload: dict[str, Any], action: dict[str, Any] | None = None) -> str:
        requested = safe_text(payload.get("runtimePreset")).strip().lower()
        if requested in {"saver", "question", "summary", "migration", "implementation", "review", "debug", "lite", "balanced", "full", "custom"}:
            return requested
        if action:
            configured = safe_text(action.get("runtimePreset")).strip().lower()
            if configured in {"saver", "question", "summary", "migration", "implementation", "review", "debug", "lite", "balanced", "full"}:
                return configured
        return self.inferred_runtime_preset_for_payload(payload, action)

    def runtime_preset_label(self, preset: str) -> str:
        labels = {
            "saver": "Saver",
            "question": "Question",
            "summary": "Summary",
            "migration": "Migration",
            "implementation": "Implementation",
            "review": "Review",
            "debug": "Debug",
            "lite": "Lite",
            "balanced": "Balanced",
            "full": "Full",
            "custom": "Custom",
        }
        return labels.get(preset, preset or "unknown")

    def auto_runtime_options(self, payload: dict[str, Any], action: dict[str, Any] | None = None) -> dict[str, Any]:
        user_options = self.normalize_runtime_options(payload.get("runtimeOptions"))
        preset = self.runtime_preset_for_payload(payload, action)
        if preset == "custom":
            return user_options
        auto_options = self.runtime_preset_options(preset)
        focus_scope = safe_text(user_options.get("focusScope")).strip()
        if focus_scope:
            auto_options["focusScope"] = focus_scope
        session_limit = max(0, safe_int(user_options.get("sessionContextLimit"), 0))
        if session_limit > 0:
            current = max(0, safe_int(auto_options.get("sessionContextLimit"), 0))
            auto_options["sessionContextLimit"] = session_limit if current <= 0 else min(current, session_limit)
        prompt_limit = max(0, safe_int(user_options.get("promptCharsLimit"), 0))
        if prompt_limit > 0:
            current = max(0, safe_int(auto_options.get("promptCharsLimit"), 0))
            auto_options["promptCharsLimit"] = prompt_limit if current <= 0 else min(current, prompt_limit)
        return self.normalize_runtime_options(auto_options)

    def scan_all_accounts(self) -> dict[str, Any]:
        """Scans all account slots to synchronize their real login status and metadata."""
        original_auth_text = self.auth_file().read_text(encoding="utf-8") if self.auth_file().exists() else ""
        original_config_text = self.config_file().read_text(encoding="utf-8") if self.config_file().exists() else ""
        slots = self.list_account_slots()

        results = []
        switch_delay_seconds = max(1.0, float(os.environ.get("CARBONET_ACCOUNT_SCAN_SWITCH_DELAY_SEC", "2.0") or 2.0))
        for slot in slots:
            slot_id = slot["id"]
            slot_snapshot = self.account_slot_summary(slot_id)
            try:
                self.clear_codex_runtime_state(self.codex_home(), {"auth.json", "config.toml"})
                self.clear_codex_runtime_state(self.account_slot_dir(slot_id), {"auth.json", "config.toml", "metadata.json"})
                self.activate_account(slot_id)
                status = self.login_status()
                login_ready = safe_bool(status.get("loggedIn"), False)
                curr_acc = status.get("currentAccount", {})
                expected_fingerprint = safe_text(slot_snapshot.get("fingerprint")).strip()
                current_fingerprint = safe_text(curr_acc.get("fingerprint")).strip()
                login_matches_slot = bool(login_ready and expected_fingerprint and current_fingerprint and expected_fingerprint == current_fingerprint)
                status_message = safe_text(status.get("message"))
                if login_ready and not login_matches_slot:
                    status_message = (status_message + "\n[Launcher] active auth changed before scan result was persisted; treating this slot as not ready.").strip()
                updated = self.update_account_status(
                    slot_id,
                    tokenExpired=not login_matches_slot,
                    loginReady=login_matches_slot,
                    email=safe_text(slot_snapshot.get("email")),
                    name=safe_text(slot_snapshot.get("name")),
                    accountId=safe_text(slot_snapshot.get("accountId")),
                    lastAuthStatus=self.auth_status_label(login_matches_slot, status_message, not login_matches_slot),
                    lastAuthMessage=status_message,
                    lastAuthCheckedAt=now_iso()
                )
                probe_result = None
                if login_matches_slot:
                    try:
                        probe_result = self.run_account_healthcheck_prompt(slot_id, self.current_instance_id())
                    except subprocess.TimeoutExpired:
                        probe_output = "[Launcher] account healthcheck timed out after 45s"
                        probe_update = self.ingest_codex_output(
                            probe_output,
                            exit_code=124,
                            instance_id=self.current_instance_id(),
                            account_id=slot_id,
                        )
                        probe_result = {
                            "ok": False,
                            "exitCode": 124,
                            "output": probe_output,
                            "accountUpdate": probe_update,
                        }
                latest = self.account_slot_summary(slot_id)
                latest_status = safe_text(latest.get("statusCode")) or ("Ready" if login_matches_slot else "Expired")
                results.append({
                    "id": slot_id,
                    "email": updated.get("email"),
                    "status": latest_status,
                    "probeExitCode": probe_result.get("exitCode") if isinstance(probe_result, dict) else None,
                    "probeMessage": self.summarize_text(safe_text(probe_result.get("output")) if isinstance(probe_result, dict) else "", 240),
                    "nextAvailableAt": safe_text(latest.get("nextAvailableAt")),
                })
                if safe_text(latest_status).strip().lower() in {"quota_wait", "unauthorized", "login_expired"}:
                    time.sleep(switch_delay_seconds)
            except Exception as exc:
                results.append({"id": slot_id, "error": str(exc)})
                time.sleep(switch_delay_seconds)
            finally:
                self.clear_codex_runtime_state(self.codex_home(), {"auth.json", "config.toml"})
                self.clear_codex_runtime_state(self.account_slot_dir(slot_id), {"auth.json", "config.toml", "metadata.json"})

        try:
            self.codex_home().mkdir(parents=True, exist_ok=True)
            if original_auth_text:
                self.auth_file().write_text(original_auth_text, encoding="utf-8")
            elif self.auth_file().exists():
                self.auth_file().unlink()
            if original_config_text:
                self.config_file().write_text(original_config_text, encoding="utf-8")
            elif self.config_file().exists():
                self.config_file().unlink()
        except Exception:
            pass
        
        return {
            "scannedCount": len(slots),
            "results": results,
            "message": f"Successfully scanned and synchronized status for {len(slots)} accounts."
        }

    def start_device_login(self) -> dict[str, Any]:
        flow = self.login_flow_state()
        process = flow.get("process")
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            return self.login_flow_payload()

        process = subprocess.Popen(
            [self.codex_bin(), "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, **self.instance_process_env()},
        )
        flow.clear()
        flow.update({
            "process": process,
            "startedAt": now_iso(),
            "verificationUri": "",
            "userCode": "",
            "output": "",
        })
        if process.stdout is not None:
            os.set_blocking(process.stdout.fileno(), False)

        deadline = time.time() + 10
        while time.time() < deadline:
            self.capture_device_login_output()
            if flow.get("verificationUri") and flow.get("userCode"):
                break
            if process.poll() is not None:
                break
            time.sleep(0.1)
        return self.login_flow_payload()

    def capture_device_login_output(self) -> None:
        flow = self.login_flow_state()
        process = flow.get("process")
        if not isinstance(process, subprocess.Popen) or process.stdout is None:
            return
        try:
            chunk = os.read(process.stdout.fileno(), 4096).decode("utf-8", errors="replace")
        except BlockingIOError:
            return
        if not chunk:
            return
        flow["output"] = safe_text(flow.get("output")) + chunk
        output = strip_ansi(safe_text(flow.get("output")))
        if not flow.get("verificationUri"):
            match = re.search(r"https://auth\.openai\.com/\S+", output)
            if match:
                flow["verificationUri"] = match.group(0)
        if not flow.get("userCode"):
            match = re.search(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b", output)
            if match:
                flow["userCode"] = match.group(0)

    def login_flow_payload(self) -> dict[str, Any]:
        self.capture_device_login_output()
        flow = self.login_flow_state()
        process = flow.get("process")
        return {
            "started": bool(process),
            "running": isinstance(process, subprocess.Popen) and process.poll() is None,
            "verificationUri": safe_text(flow.get("verificationUri")) or "https://auth.openai.com/codex/device",
            "userCode": safe_text(flow.get("userCode")),
            "startedAt": safe_text(flow.get("startedAt")),
            "output": safe_text(flow.get("output")),
        }

    def logout(self) -> dict[str, Any]:
        flow = self.login_flow_state()
        process = flow.get("process")
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            process.terminate()
        flow.clear()
        completed = subprocess.run(
            [self.codex_bin(), "logout"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **self.instance_process_env()},
        )
        login = self.login_status()
        return {
            "loggedOut": completed.returncode == 0,
            "message": (completed.stdout or completed.stderr or "").strip(),
            "loginReady": login.get("loggedIn", False),
            "currentAccount": login.get("currentAccount", {}),
        }

    def browser_status(self) -> dict[str, Any]:
        with self.lock:
            payload = dict(self.browser_state)
        return payload

    def update_browser_menu_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        snapshot = {
            "capturedAt": now_iso(),
            "home": payload.get("home"),
            "admin": payload.get("admin"),
        }
        with self.lock:
            self.browser_state["menuSnapshot"] = snapshot
            self.browser_state["lastSeenAt"] = now_iso()
            return dict(self.browser_state)

    def browser_extension_info(self) -> dict[str, Any]:
        distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
        unc_path = f"\\\\wsl.localhost\\{distro}\\opt\\util\\codex\\extension"
        return {
            "installedFiles": self.extension_root.exists(),
            "installPath": unc_path,
            "manifestUrl": "/extension/manifest.json",
            "launcherBase": "http://localhost:43110",
        }

    def load_source_roots(self, instance_id: str | None = None) -> dict[str, Any]:
        defaults = {
            "reference": [],
            "project": [],
        }
        source_roots_file = self.source_roots_file_path(instance_id)
        if not source_roots_file.exists():
            source_roots_file.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
            return defaults
        try:
            doc = read_json(source_roots_file)
        except Exception:
            source_roots_file.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
            return defaults
        for kind in ("reference", "project"):
            items = doc.get(kind)
            if not isinstance(items, list):
                doc[kind] = list(defaults[kind])
                continue
            doc[kind] = [
                item
                for item in items
                if safe_text(item.get("id")) not in {"reference-default", "project-default"}
            ]
        source_roots_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    def save_source_roots(self, instance_id: str | None = None) -> None:
        self.source_roots_file_path(instance_id).write_text(
            json.dumps(self.source_roots_doc(instance_id), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_roots(self, kind: str) -> list[dict[str, Any]]:
        items = []
        for item in self.source_roots_doc().get(kind, []):
            path = Path(safe_text(item.get("path")))
            items.append(
                {
                    "id": safe_text(item.get("id")),
                    "label": safe_text(item.get("label")) or path.name,
                    "path": str(path),
                    "exists": path.exists() and path.is_dir(),
                }
            )
        return items

    def windows_path_to_linux(self, raw_path: str) -> str:
        path = safe_text(raw_path).strip()
        if not path:
            return ""
        distro = os.environ.get("WSL_DISTRO_NAME", "Ubuntu")
        unc_prefix = f"\\\\wsl.localhost\\{distro}\\"
        if path.lower().startswith(unc_prefix.lower()):
            suffix = path[len(unc_prefix):].replace("\\", "/")
            return f"/{suffix.lstrip('/')}"
        match = re.match(r"^([A-Za-z]):\\(.*)$", path)
        if match:
            drive = match.group(1).lower()
            suffix = match.group(2).replace("\\", "/")
            return f"/mnt/{drive}/{suffix}"
        return path.replace("\\", "/")

    def pick_directory(self, title: str = "Select folder") -> dict[str, Any]:
        escaped_title = title.replace("'", "''")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{escaped_title}'; "
            "$dialog.ShowNewFolderButton = $false; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "Write-Output $dialog.SelectedPath }"
        )
        completed = subprocess.run(
            [
                "cmd.exe",
                "/c",
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        selected = (completed.stdout or "").strip()
        if completed.returncode != 0:
            raise ValueError((completed.stderr or "Directory picker failed").strip())
        return {
            "selectedPath": self.windows_path_to_linux(selected),
            "rawPath": selected,
        }

    def get_root(self, kind: str, root_id: str | None = None) -> dict[str, Any]:
        roots = self.list_roots(kind)
        if not roots:
            raise ValueError(f"No {kind} roots registered.")
        if root_id:
            for item in roots:
                if item["id"] == root_id:
                    return item
            raise ValueError(f"Unknown {kind} root: {root_id}")
        return roots[0]

    def add_root(self, kind: str, label: str, path_value: str) -> dict[str, Any]:
        path = Path(safe_text(path_value).strip()).resolve()
        if not label.strip():
            raise ValueError("label is required")
        if not path.exists() or not path.is_dir():
            raise ValueError(f"Directory not found: {path}")
        roots_doc = self.source_roots_doc()
        for item in roots_doc.get(kind, []):
            if str(Path(safe_text(item.get("path"))).resolve()) == str(path):
                raise ValueError(f"Already registered: {path}")
        entry = {
            "id": uuid.uuid4().hex[:12],
            "label": label.strip(),
            "path": str(path),
        }
        roots_doc.setdefault(kind, []).append(entry)
        self.save_source_roots()
        return {
            "saved": True,
            "item": entry,
            "items": self.list_roots(kind),
        }

    def delete_root(self, kind: str, root_id: str) -> dict[str, Any]:
        roots_doc = self.source_roots_doc()
        items = roots_doc.get(kind, [])
        if len(items) <= 1:
            raise ValueError(f"At least one {kind} root must remain.")
        next_items = [item for item in items if safe_text(item.get("id")) != root_id]
        if len(next_items) == len(items):
            raise ValueError(f"Unknown {kind} root: {root_id}")
        roots_doc[kind] = next_items
        self.save_source_roots()
        return {
            "deleted": True,
            "items": self.list_roots(kind),
        }

    def reference_status(self) -> dict[str, Any]:
        roots = self.list_roots("reference")
        active = roots[0] if roots else None
        return {
            "enabled": bool(active and active.get("exists")),
            "root": safe_text(active.get("path")) if active else "",
        }

    def resolve_rooted_path(self, kind: str, raw_path: str, root_id: str | None = None) -> tuple[dict[str, Any], Path]:
        root_info = self.get_root(kind, root_id)
        root = Path(root_info["path"]).resolve()
        if not root.exists():
            raise ValueError(f"{kind.capitalize()} root not found: {root}")
        requested = safe_text(raw_path).strip().lstrip("/")
        target = (root / requested) if requested else root
        target_abs = Path(os.path.abspath(target))
        if os.path.commonpath([str(root), str(target_abs)]) != str(root):
            raise ValueError(f"{kind.capitalize()} path is outside the allowed root.")
        if not target_abs.exists():
            raise ValueError(f"{kind.capitalize()} path not found: {target_abs}")
        return root_info, target_abs

    def build_reference_tree_node(self, target: Path, root: Path) -> dict[str, Any]:
        relative = "" if target == root else str(target.relative_to(root)).replace(os.sep, "/")
        is_dir = target.is_dir()
        node = {
            "name": target.name if relative else root.name,
            "path": relative,
            "type": "directory" if is_dir else "file",
        }
        if is_dir:
            children: list[dict[str, Any]] = []
            entries = sorted(
                target.iterdir(),
                key=lambda item: (not item.is_dir(), item.name.lower()),
            )
            for entry in entries:
                if entry.name.startswith("."):
                    continue
                if entry.is_file() and entry.suffix.lower() not in {".html", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt"}:
                    continue
                children.append(self.build_reference_tree_node(entry, root))
            node["children"] = children
        else:
            node["size"] = target.stat().st_size
        return node

    def reference_tree(self, root_id: str | None = None) -> dict[str, Any]:
        root_info, target = self.resolve_rooted_path("reference", "", root_id)
        root = Path(root_info["path"]).resolve()
        return {
            "root": str(target),
            "rootId": root_info["id"],
            "tree": self.build_reference_tree_node(target, root),
        }

    def reference_subtree(self, raw_path: str, root_id: str | None = None) -> dict[str, Any]:
        root_info, target = self.resolve_rooted_path("reference", raw_path, root_id)
        root = Path(root_info["path"]).resolve()
        return {
            "root": str(root),
            "rootId": root_info["id"],
            "scopePath": safe_text(raw_path).strip().strip("/"),
            "tree": self.build_reference_tree_node(target, root),
        }

    def list_reference_projects(self, root_id: str | None = None) -> dict[str, Any]:
        root_info, target = self.resolve_rooted_path("reference", "", root_id)
        items: list[dict[str, Any]] = []
        for entry in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            items.append(
                {
                    "name": entry.name,
                    "path": entry.name,
                }
            )
        return {
            "root": str(target),
            "rootId": root_info["id"],
            "items": items,
        }

    def reference_file_info(self, raw_path: str, root_id: str | None = None) -> dict[str, Any]:
        root_info, target = self.resolve_rooted_path("reference", raw_path, root_id)
        if target.is_dir():
            raise ValueError("Reference file path must be a file.")
        root = Path(root_info["path"]).resolve()
        relative = str(target.relative_to(root)).replace(os.sep, "/")
        content_type, _ = mimetypes.guess_type(str(target))
        if target.suffix.lower() in {".html", ".txt"}:
            return {
                "path": relative,
                "name": target.name,
                "contentType": content_type or "text/plain; charset=utf-8",
                "text": target.read_text(encoding="utf-8"),
                "downloadUrl": f"/api/reference/file?rootId={quote(root_info['id'], safe='')}&path={quote(relative, safe='')}",
            }
        return {
            "path": relative,
            "name": target.name,
            "contentType": content_type or "application/octet-stream",
            "downloadUrl": f"/api/reference/file?rootId={quote(root_info['id'], safe='')}&path={quote(relative, safe='')}",
        }

    def reference_file_bytes(self, raw_path: str, root_id: str | None = None) -> tuple[str, bytes]:
        _, target = self.resolve_rooted_path("reference", raw_path, root_id)
        if target.is_dir():
            raise ValueError("Reference file path must be a file.")
        content_type, _ = mimetypes.guess_type(str(target))
        return content_type or "application/octet-stream", target.read_bytes()

    def build_project_tree_node(self, target: Path, root: Path, max_depth: int = 4, depth: int = 0) -> dict[str, Any]:
        relative = "" if target == root else str(target.relative_to(root)).replace(os.sep, "/")
        node = {
            "name": target.name if relative else root.name,
            "path": relative,
            "type": "directory",
        }
        if depth >= max_depth:
            node["children"] = []
            return node
        children: list[dict[str, Any]] = []
        for entry in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            children.append(self.build_project_tree_node(entry, root, max_depth=max_depth, depth=depth + 1))
        node["children"] = children
        return node

    def list_project_directories(self, root_id: str | None = None) -> dict[str, Any]:
        root_info, target = self.resolve_rooted_path("project", "", root_id)
        root = Path(root_info["path"]).resolve()
        items: list[dict[str, Any]] = []
        for entry in sorted(root.iterdir(), key=lambda item: item.name.lower()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            items.append(
                {
                    "name": entry.name,
                    "path": str(entry.resolve()),
                    "hasPom": (entry / "pom.xml").exists(),
                    "hasPackageJson": (entry / "package.json").exists(),
                    "hasFrontendPackage": (entry / "frontend" / "package.json").exists(),
                    "hasRestart18000": (entry / "ops" / "scripts" / "restart-18000.sh").exists(),
                }
            )
        return {
            "root": str(root),
            "rootId": root_info["id"],
            "items": items,
        }

    def resolve_project_path(self, raw_path: str) -> Path:
        requested = safe_text(raw_path).strip()
        if not requested:
            raise ValueError("projectPath is required.")
        target = Path(requested).resolve()
        allowed_roots = [Path(item["path"]).resolve() for item in self.list_roots("project")]
        if not any(target == root or root in target.parents for root in allowed_roots):
            raise ValueError("Project path is outside the allowed roots.")
        if not target.exists() or not target.is_dir():
            raise ValueError(f"Project path not found: {target}")
        return target

    def scan_project_menus(self, raw_project_path: str) -> dict[str, Any]:
        project_root = self.resolve_project_path(raw_project_path)
        definitions_path = project_root / "frontend" / "src" / "app" / "routes" / "definitions.ts"
        if not definitions_path.exists():
            raise ValueError(f"Route definitions not found: {definitions_path}")
        source = definitions_path.read_text(encoding="utf-8")
        pattern = re.compile(
            r'\{\s*id:\s*"(?P<id>[^"]+)",\s*label:\s*"(?P<label>[^"]+)",\s*group:\s*"(?P<group>[^"]+)",\s*koPath:\s*"(?P<ko>[^"]+)",\s*enPath:\s*"(?P<en>[^"]+)"\s*\}'
        )
        home_items: list[dict[str, Any]] = []
        admin_items: list[dict[str, Any]] = []
        for match in pattern.finditer(source):
            item = {
                "id": match.group("id"),
                "label": match.group("label"),
                "group": match.group("group"),
                "koPath": match.group("ko"),
                "enPath": match.group("en"),
            }
            if item["group"] == "admin":
                admin_items.append(item)
            else:
                home_items.append(item)
        live_home = self.fetch_local_menu_tree("http://127.0.0.1:18000/api/sitemap", mode="home")
        live_admin = self.fetch_local_menu_tree("http://127.0.0.1:18000/admin/api/admin/content/sitemap", mode="admin")
        browser_snapshot = self.browser_status().get("menuSnapshot", {})
        browser_home = self.build_browser_menu_tree(browser_snapshot.get("home"), "home", "browser-home-sitemap")
        browser_admin = self.build_browser_menu_tree(browser_snapshot.get("admin"), "admin", "browser-admin-sitemap")
        return {
            "projectPath": str(project_root),
            "source": str(definitions_path),
            "homeSource": browser_home.get("source") or live_home.get("source") or str(definitions_path),
            "adminSource": browser_admin.get("source") or live_admin.get("source") or str(definitions_path),
            "home": browser_home.get("tree") or live_home.get("tree") or self.build_menu_tree("home", home_items),
            "admin": browser_admin.get("tree") or live_admin.get("tree") or self.build_menu_tree("admin", admin_items),
        }

    def fetch_local_menu_tree(self, url: str, mode: str) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [
                    "curl",
                    "-fsS",
                    "-H",
                    "Accept: application/json",
                    "-A",
                    "CarbonetCodexLauncher/0.1",
                    url,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
        except Exception:
            return {}
        if completed.returncode != 0:
            return {}
        try:
            payload = json.loads(completed.stdout)
        except Exception:
            return {}
        if mode == "home":
            nodes = payload.get("homeMenu") or payload.get("siteMapSections") or []
            return {
                "source": url,
                "tree": self.build_menu_tree_from_live_nodes("home", nodes, mode="home"),
            }
        nodes = payload.get("siteMapSections") or []
        return {
            "source": url,
            "tree": self.build_menu_tree_from_live_nodes("admin", nodes, mode="admin"),
        }

    def build_menu_tree_from_live_nodes(self, root_name: str, nodes: list[Any], mode: str) -> dict[str, Any]:
        root = {"name": root_name, "path": root_name, "type": "group", "children": []}
        for node in nodes:
            converted = self.convert_live_menu_node(node, root_name, mode, root_name)
            if converted is not None:
                root["children"].append(converted)
        return root

    def build_browser_menu_tree(self, payload: Any, root_name: str, source_name: str) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        nodes = payload.get("homeMenu") or payload.get("siteMapSections") or []
        if not isinstance(nodes, list) or not nodes:
            return {}
        return {
            "source": source_name,
            "tree": self.build_menu_tree_from_live_nodes(root_name, nodes, mode=root_name),
        }

    def convert_live_menu_node(self, node: Any, parent_path: str, mode: str, group_name: str) -> dict[str, Any] | None:
        if not isinstance(node, dict):
            return None
        code = safe_text(node.get("code")) or uuid.uuid4().hex[:8]
        label = safe_text(node.get("label")) or code
        url = safe_text(node.get("url"))
        path = f"{parent_path}/{code}"
        raw_children = []
        if mode == "home":
            raw_children = list(node.get("sections") or []) + list(node.get("items") or []) + list(node.get("children") or [])
        else:
            raw_children = list(node.get("children") or [])
        converted_children = [
            child
            for child in (self.convert_live_menu_node(child, path, mode, group_name) for child in raw_children)
            if child is not None
        ]
        if converted_children:
            return {
                "name": label,
                "path": path,
                "type": "branch",
                "menu": {
                    "id": code,
                    "label": label,
                    "group": group_name,
                    "koPath": url,
                    "enPath": url,
                },
                "children": converted_children,
            }
        return {
            "name": label,
            "path": f"{path}#{code}",
            "type": "item",
            "menu": {
                "id": code,
                "label": label,
                "group": group_name,
                "koPath": url,
                "enPath": url,
            },
        }

    def build_menu_tree(self, root_name: str, items: list[dict[str, Any]]) -> dict[str, Any]:
        tree = {"name": root_name, "path": root_name, "type": "group", "children": []}
        index: dict[str, dict[str, Any]] = {root_name: tree}
        for item in items:
            ko_path = safe_text(item.get("koPath")).strip() or "/"
            parts = [part for part in ko_path.strip("/").split("/") if part]
            current_key = root_name
            current_node = tree
            for part in parts:
                next_key = f"{current_key}/{part}"
                child = index.get(next_key)
                if child is None:
                    child = {"name": part, "path": next_key, "type": "branch", "children": []}
                    current_node["children"].append(child)
                    index[next_key] = child
                current_node = child
                current_key = next_key
            leaf = {
                "name": safe_text(item.get("label")),
                "path": f"{current_key}#{safe_text(item.get('id'))}",
                "type": "item",
                "menu": item,
            }
            current_node["children"].append(leaf)
        return tree

    def update_browser_state(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if payload.get("currentUrl"):
                self.browser_state["currentUrl"] = safe_text(payload.get("currentUrl"))
            if payload.get("currentTitle") is not None:
                self.browser_state["currentTitle"] = safe_text(payload.get("currentTitle"))
            self.browser_state["lastSeenAt"] = now_iso()
            return dict(self.browser_state)

    def record_browser_capture(self, payload: dict[str, Any]) -> dict[str, Any]:
        capture = {
            "id": uuid.uuid4().hex[:12],
            "capturedAt": now_iso(),
            "url": safe_text(payload.get("url")),
            "title": safe_text(payload.get("title")),
            "selector": safe_text(payload.get("selector")),
            "text": safe_text(payload.get("text"))[:4000],
            "html": safe_text(payload.get("html"))[:12000],
            "tagName": safe_text(payload.get("tagName")),
        }
        with self.lock:
            self.browser_state["lastCapture"] = capture
            if capture["url"]:
                self.browser_state["currentUrl"] = capture["url"]
            if capture["title"]:
                self.browser_state["currentTitle"] = capture["title"]
            self.browser_state["lastSeenAt"] = now_iso()
        return capture

    def fetch_browser_page(self, target_url: str) -> tuple[str, str]:
        normalized = safe_text(target_url).strip()
        if not normalized:
            raise ValueError("url is required")
        if not re.match(r"^https?://", normalized):
            normalized = f"http://{normalized}"
        request = Request(
            normalized,
            headers={
                "User-Agent": "Mozilla/5.0 CarbonetCodexLauncher/0.1",
                "Accept-Language": "ko,en-US;q=0.9,en;q=0.8",
            },
        )
        with urlopen(request, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "text/html; charset=utf-8")
            body = response.read()
            final_url = response.geturl()
        charset = "utf-8"
        match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if match:
            charset = match.group(1).strip("\"'")
        html = body.decode(charset, errors="replace")
        if "text/html" not in content_type.lower():
            escaped = (
                html.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
            )
            html = f"<html><body><pre>{escaped}</pre></body></html>"
        return final_url, self.inject_browser_bridge(html, final_url)

    def proxy_browser_request(
        self,
        target_url: str,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str, bytes]:
        normalized = safe_text(target_url).strip()
        if not normalized:
            raise ValueError("url is required")
        if not re.match(r"^https?://", normalized):
            normalized = f"http://{normalized}"
        request_headers = {
            "User-Agent": "Mozilla/5.0 CarbonetCodexLauncher/0.1",
            "Accept-Language": "ko,en-US;q=0.9,en;q=0.8",
        }
        for key, value in (headers or {}).items():
            lowered = key.lower()
            if lowered in {"host", "content-length", "origin", "referer"}:
                continue
            request_headers[key] = value
        request = Request(
            normalized,
            data=body,
            headers=request_headers,
            method=method.upper(),
        )
        try:
            with urlopen(request, timeout=20) as response:
                content_type = response.headers.get("Content-Type", "application/octet-stream")
                body = response.read()
                if "javascript" in content_type.lower() or normalized.endswith(".js"):
                    body = rewrite_js_module_imports(
                        body.decode("utf-8", errors="replace"),
                        normalized,
                    ).encode("utf-8")
                return (
                    response.status,
                    content_type,
                    body,
                )
        except HTTPError as exc:
            content_type = exc.headers.get("Content-Type", "application/octet-stream")
            body = exc.read()
            if "javascript" in content_type.lower() or normalized.endswith(".js"):
                body = rewrite_js_module_imports(
                    body.decode("utf-8", errors="replace"),
                    normalized,
                ).encode("utf-8")
            return (
                exc.code,
                content_type,
                body,
            )

    def inject_browser_bridge(self, html: str, target_url: str) -> str:
        bridge = f"""
<base href="{target_url}">
<style>
#codex-browser-menu {{
  position: fixed; z-index: 2147483647; display: none; min-width: 220px;
  background: #fffaf1; color: #24190f; border: 1px solid #c8b79a; border-radius: 12px;
  box-shadow: 0 16px 36px rgba(30, 20, 10, 0.18); overflow: hidden; font: 13px/1.4 sans-serif;
}}
#codex-browser-menu button {{
  width: 100%; border: 0; background: transparent; text-align: left; padding: 10px 12px; cursor: pointer;
}}
#codex-browser-menu button:hover {{ background: #f1e1c8; }}
#codex-browser-badge {{
  position: fixed; right: 12px; bottom: 12px; z-index: 2147483647; padding: 8px 10px;
  border-radius: 999px; background: rgba(36,25,15,0.9); color: #fff; font: 12px/1 sans-serif;
}}
</style>
<script>
(function () {{
  const sourceUrl = {json.dumps(target_url)};
  const launcherOrigin = window.location.origin;
  const sourceOrigin = new URL(sourceUrl).origin;
  const sourceLocation = new URL(sourceUrl);
  let selectedElement = null;
  let menu = null;
  let badge = null;

  try {{
    window.history.replaceState(
      {{}},
      '',
      launcherOrigin + sourceLocation.pathname + sourceLocation.search + sourceLocation.hash
    );
  }} catch (error) {{
    console.warn('history.replaceState failed', error);
  }}

  function launcherApi(path) {{
    return launcherOrigin + path;
  }}

  function shouldProxy(url) {{
    try {{
      const target = new URL(url, sourceUrl);
      return target.origin === sourceOrigin;
    }} catch (error) {{
      return false;
    }}
  }}

  function proxiedUrl(url) {{
    const resolved = new URL(url, sourceUrl).toString();
    return launcherApi('/api/browser/fetch?url=' + encodeURIComponent(resolved));
  }}

  function sanitizeHeaders(inputHeaders) {{
    const cleaned = new Headers();
    if (!inputHeaders) {{
      return cleaned;
    }}
    const headerNamePattern = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;
    const appendPair = (name, value) => {{
      const normalizedName = String(name || '').trim();
      if (!normalizedName || !headerNamePattern.test(normalizedName)) {{
        return;
      }}
      cleaned.set(normalizedName, String(value ?? ''));
    }};
    if (inputHeaders instanceof Headers) {{
      for (const [name, value] of inputHeaders.entries()) {{
        appendPair(name, value);
      }}
      return cleaned;
    }}
    if (Array.isArray(inputHeaders)) {{
      for (const entry of inputHeaders) {{
        if (Array.isArray(entry) && entry.length >= 2) {{
          appendPair(entry[0], entry[1]);
        }}
      }}
      return cleaned;
    }}
    if (typeof inputHeaders === 'object') {{
      for (const [name, value] of Object.entries(inputHeaders)) {{
        appendPair(name, value);
      }}
      return cleaned;
    }}
    return cleaned;
  }}

  function rewriteValue(value) {{
    if (Array.isArray(value)) {{
      return value.map(rewriteValue);
    }}
    if (value && typeof value === 'object') {{
      return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, rewriteValue(item)]));
    }}
    if (typeof value !== 'string' || !value) {{
      return value;
    }}
    if (value.startsWith('data:') || value.startsWith('javascript:') || value.startsWith('#')) {{
      return value;
    }}
    try {{
      const resolved = new URL(value, sourceUrl);
      if (resolved.origin === sourceOrigin) {{
        return proxiedUrl(resolved.toString());
      }}
    }} catch (error) {{
      return value;
    }}
    return value;
  }}

  const originalFetch = window.fetch.bind(window);
  window.fetch = function(input, init) {{
    const url = typeof input === 'string' ? input : (input && input.url) || '';
    if (url && shouldProxy(url)) {{
      const nextInput = proxiedUrl(url);
      const nextInit = Object.assign({{}}, init || {{}});
      nextInit.headers = sanitizeHeaders(nextInit.headers);
      if (input instanceof Request) {{
        nextInit.method = nextInit.method || input.method;
        if (!init || !init.headers) {{
          nextInit.headers = sanitizeHeaders(input.headers);
        }}
        if (!nextInit.body && input.method && input.method.toUpperCase() !== 'GET' && input.method.toUpperCase() !== 'HEAD') {{
          return input.clone().text().then((text) => {{
            nextInit.body = text;
            return originalFetch(nextInput, nextInit);
          }});
        }}
      }}
      return originalFetch(nextInput, nextInit).then((response) => {{
        const originalJson = response.json.bind(response);
        response.json = () => originalJson().then(rewriteValue);
        return response;
      }});
    }}
    return originalFetch(input, init);
  }};

  const originalXhrOpen = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(method, url) {{
    if (url && shouldProxy(url)) {{
      arguments[1] = proxiedUrl(url);
    }}
    return originalXhrOpen.apply(this, arguments);
  }};

  function ensureUi() {{
    if (menu) return;
    menu = document.createElement('div');
    menu.id = 'codex-browser-menu';
    menu.innerHTML = `
      <button data-kind="html">Codex Prompt에 element HTML 넣기</button>
      <button data-kind="text">Codex Prompt에 element text 넣기</button>
      <button data-kind="selector">Codex Prompt에 selector만 넣기</button>
    `;
    document.documentElement.appendChild(menu);
    badge = document.createElement('div');
    badge.id = 'codex-browser-badge';
    badge.textContent = 'Codex Browser Capture';
    document.documentElement.appendChild(badge);
    menu.addEventListener('click', async (event) => {{
      const button = event.target.closest('button[data-kind]');
      if (!button || !selectedElement) return;
      const selector = buildSelector(selectedElement);
      const payload = {{
        url: sourceUrl,
        title: document.title || '',
        selector,
        tagName: selectedElement.tagName || '',
        text: (selectedElement.innerText || selectedElement.textContent || '').trim().slice(0, 4000),
        html: (selectedElement.outerHTML || '').slice(0, 12000)
      }};
      if (button.dataset.kind === 'selector') {{
        payload.html = '';
        payload.text = '';
      }} else if (button.dataset.kind === 'text') {{
        payload.html = '';
      }}
      await fetch(launcherApi('/api/browser/capture'), {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }});
      hideMenu();
    }});
    document.addEventListener('click', hideMenu, true);
  }}

  function hideMenu() {{
    if (menu) menu.style.display = 'none';
  }}

  function buildSelector(node) {{
    if (!(node instanceof Element)) return '';
    const parts = [];
    let current = node;
    while (current && current.nodeType === 1 && parts.length < 6) {{
      let part = current.tagName.toLowerCase();
      if (current.id) {{
        part += '#' + current.id;
        parts.unshift(part);
        break;
      }}
      const className = (current.className || '').toString().trim().split(/\\s+/).filter(Boolean).slice(0, 2).join('.');
      if (className) part += '.' + className;
      const parent = current.parentElement;
      if (parent) {{
        const siblings = Array.from(parent.children).filter((child) => child.tagName === current.tagName);
        if (siblings.length > 1) {{
          part += `:nth-of-type(${{siblings.indexOf(current) + 1}})`;
        }}
      }}
      parts.unshift(part);
      current = current.parentElement;
    }}
    return parts.join(' > ');
  }}

  async function sendState() {{
    await fetch(launcherApi('/api/browser/state'), {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ currentUrl: sourceUrl, currentTitle: document.title || '' }})
    }});
  }}

  document.addEventListener('contextmenu', (event) => {{
    ensureUi();
    selectedElement = event.target instanceof Element ? event.target : null;
    if (!selectedElement) return;
    event.preventDefault();
    menu.style.left = `${{event.clientX}}px`;
    menu.style.top = `${{event.clientY}}px`;
    menu.style.display = 'block';
  }});

  document.addEventListener('click', (event) => {{
    const anchor = event.target.closest('a[href]');
    if (!anchor) return;
    const href = anchor.getAttribute('href') || '';
    if (!href || href.startsWith('javascript:') || href.startsWith('#')) return;
    if (anchor.target === '_blank' || event.metaKey || event.ctrlKey || event.shiftKey) return;
    event.preventDefault();
    const nextUrl = new URL(anchor.href, sourceUrl).toString();
    window.location.href = launcherApi('/api/browser/page?url=' + encodeURIComponent(nextUrl));
  }});

  window.addEventListener('load', sendState);
  document.addEventListener('DOMContentLoaded', sendState);
}})();
</script>
"""
        if "<head" in html.lower():
            return re.sub(r"(<head[^>]*>)", lambda match: match.group(1) + bridge, html, count=1, flags=re.I)
        return f"<html><head>{bridge}</head><body>{html}</body></html>"

    def slugify(self, text: str) -> str:
        normalized = "".join(ch.lower() if ch.isalnum() else "-" for ch in text.strip())
        collapsed = "-".join(token for token in normalized.split("-") if token)
        return collapsed or "account"

    def list_jobs(self, session_id: str | None = None) -> list[dict[str, Any]]:
        with self.lock:
            items = list(self.jobs_store().values())
            if session_id:
                items = [item for item in items if item.session_id == session_id]
            items = sorted(items, key=lambda item: item.started_at, reverse=True)
            return [item.as_dict() for item in items]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs_store().get(job_id)
            if job is None:
                raise KeyError(job_id)
            return job.as_dict()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs_store().get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.process and job.status == "running":
                job.process.terminate()
        return self.get_job(job_id)

    def setup_freeagent(self, model: str = "qwen3.5:cloud", sudo_password: str = "") -> dict[str, Any]:
        messages = self.freeagent_setup_runtime(model=model, sudo_password=sudo_password)
        return {
            "ok": True,
            "message": "; ".join(messages),
            "freeagent": self.freeagent_config(),
        }

    def change_freeagent_model(self, model: str) -> dict[str, Any]:
        """Change the default FreeAgent model by updating .env.freeagent."""
        model = safe_text(model).strip()
        if not model:
            raise ValueError("model is required")
        env_file = self.freeagent_env_file()
        env_doc = read_key_values(env_file)
        env_doc["FREEAGENT_MODEL"] = model
        lines = []
        for key, value in env_doc.items():
            lines.append(f"{key}={value}")
        env_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return {
            "ok": True,
            "model": model,
            "message": f"Default model changed to {model}",
            "freeagent": self.freeagent_config(),
        }

    def start_freeagent_agent(self) -> dict[str, Any]:
        if self.freeagent_provider() != "ollama":
            return {
                "ok": True,
                "message": "external provider configured; no local agent start needed",
                "freeagent": self.freeagent_config(),
            }
        status = self.start_ollama_service()
        status["freeagent"] = self.freeagent_config()
        return status

    def pull_freeagent_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        model = safe_text(payload.get("model")).strip() or self.freeagent_config().get("model", "qwen3.5:cloud")
        if self.freeagent_provider() != "ollama":
            raise ValueError("Model pull is only available for Ollama-backed FreeAgent.")
        workspace = self.resolve_workspace(payload)
        session = self.resolve_session(payload, workspace)
        return self.enqueue_job_spec(
            title=f"FreeAgent Pull Model [{model}]",
            kind="freeagent",
            cwd=safe_text(workspace["path"]),
            command=["ollama", "pull", model],
            command_preview=f"ollama pull {model}",
            workspace=workspace,
            session=session,
            plan_step=safe_text(payload.get("planStep")).strip(),
            env_overrides=self.instance_process_env(),
        )

    def build_parallel_scout_prompt(
        self,
        original_prompt: str,
        role_name: str,
        role_instruction: str,
        workspace_path: str,
        account_summary: dict[str, Any],
    ) -> str:
        return "\n".join(
            [
                "[Parallel Scout]",
                f"Workspace: {workspace_path}",
                f"Assigned lens: {role_name}",
                f"Account capacity hint: {self.explain_account_capacity(account_summary)}",
                "Do not edit files. Do not run destructive commands.",
                "Read only what is needed for this lens and return concise, actionable findings.",
                "Use concrete file paths when relevant.",
                "",
                "[Task Lens]",
                role_instruction,
                "",
                "[Original Request]",
                original_prompt,
            ]
        )

    def build_parallel_final_prompt(
        self,
        original_prompt: str,
        scout_reports: list[dict[str, str]],
        workspace_path: str,
        local_reports: list[dict[str, Any]] | None = None,
    ) -> str:
        lines = [
            "[Parallel Account Execution]",
            f"Workspace: {workspace_path}",
            "Multiple isolated account scouts and local model scouts already analyzed this task.",
            "Use their findings as input, resolve conflicts explicitly, and finish the requested work end-to-end.",
            "",
            "[Scout Reports]",
        ]
        if scout_reports:
            for index, report in enumerate(scout_reports, start=1):
                lines.extend(
                    [
                        f"Scout {index}: {safe_text(report.get('accountLabel')) or safe_text(report.get('accountId'))}",
                        f"Lens: {safe_text(report.get('role'))}",
                        f"Assigned Task: {safe_text(report.get('assignedTask')) or self.describe_local_model_task(safe_text(report.get('role')), '')}",
                        safe_text(report.get("summary")).strip() or "(no summary)",
                        "",
                    ]
                )
        else:
            lines.extend(["(No scout reports)", ""])
        lines.append("[Local Model Reports]")
        if local_reports:
            for index, report in enumerate(local_reports, start=1):
                lines.extend(
                    [
                        f"Local Scout {index}: {safe_text(report.get('model'))}",
                        f"Lens: {safe_text(report.get('role'))}",
                        f"Assigned Task: {safe_text(report.get('assignedTask')) or self.describe_local_model_task(safe_text(report.get('role')), '')}",
                        safe_text(report.get("answer") or report.get("summary")).strip() or "(no answer)",
                        "",
                    ]
                )
        else:
            lines.extend(["(No local model reports)", ""])
        lines.extend(["[Original Request]", original_prompt])
        return "\n".join(lines)

    def describe_local_model_task(self, role_name: str, role_instruction: str) -> str:
        normalized = safe_text(role_name).strip().lower()
        mapping = {
            "fast-pass": "Interpret the request and decide the immediate next action.",
            "quality-pass": "Propose the safest implementation shape and call out weak assumptions.",
            "verification-pass": "List the validation steps, regression risk, and missing checks.",
            "edge-pass": "Find edge cases, compatibility issues, and failure paths.",
            "repo-scan": "Find the smallest relevant files and entry points for the request.",
            "docs-scan": "Extract rules, docs, and conventions that constrain the change.",
            "risk-scan": "Identify regression risk and missing tests before implementation.",
            "plan-scan": "Draft the safest implementation order and blockers.",
            "qa-scan": "Define acceptance criteria and verification steps.",
        }
        return mapping.get(normalized) or safe_text(role_instruction).strip()

    def build_local_model_scout_prompt(
        self,
        original_prompt: str,
        role_name: str,
        role_instruction: str,
        model_name: str,
    ) -> str:
        return "\n".join(
            [
                "[Multi Model Local Scout]",
                f"Assigned model: {model_name}",
                f"Assigned lens: {role_name}",
                f"Assigned task: {self.describe_local_model_task(role_name, role_instruction)}",
                "Do not claim certainty when unsure.",
                "Keep the answer concise and practical.",
                "",
                "[Task Lens]",
                role_instruction,
                "",
                "[Original Request]",
                original_prompt,
            ]
        )

    def build_local_model_synthesis_prompt(
        self,
        original_prompt: str,
        reports: list[dict[str, Any]],
    ) -> str:
        lines = [
            "[Multi Model Local Final Synthesizer]",
            "Multiple local model scouts already answered the request.",
            "Merge the useful parts, resolve conflicts conservatively, and return one final practical answer.",
            "Call out missing model coverage only when it changes confidence.",
            "",
            "[Scout Reports]",
        ]
        if reports:
            for index, report in enumerate(reports, start=1):
                lines.extend(
                    [
                        f"Scout {index}: {safe_text(report.get('model'))}",
                        f"Lens: {safe_text(report.get('role'))}",
                        f"Assigned Task: {safe_text(report.get('assignedTask')) or self.describe_local_model_task(safe_text(report.get('role')), '')}",
                        safe_text(report.get("answer") or report.get("summary")).strip() or "(no answer)",
                        "",
                    ]
                )
        else:
            lines.extend(["(No successful scout reports)", ""])
        lines.extend(["[Original Request]", original_prompt])
        return "\n".join(lines)

    def apply_freeagent_model_override(self, command: list[str], model_name: str) -> list[str]:
        result: list[str] = []
        skip_next = False
        for index, token in enumerate(command):
            if skip_next:
                skip_next = False
                continue
            if token == "--model" and index + 1 < len(command):
                skip_next = True
                continue
            result.append(token)
        if model_name:
            result.extend(["--model", model_name])
        return result

    def execute_isolated_freeagent_command(
        self,
        job: JobRecord,
        command: list[str],
        cwd: str,
        model_name: str,
        log_prefix: str,
        timeout_seconds: int = 180,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        env.update({key: value for key, value in self.instance_process_env(job.instance_id).items() if value})
        env["FREEAGENT_MODEL"] = model_name
        process = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        self.append_job_runtime_event(job.job_id, f"{log_prefix}: {model_name}")
        timed_out = False
        try:
            stdout_text, _ = process.communicate(timeout=max(30, timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                stdout_text, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout_text, _ = process.communicate(timeout=5)
        exit_code = process.returncode
        stdout_text = safe_text(stdout_text)
        if timed_out:
            stdout_text = stdout_text.rstrip() + f"\n[Launcher] {log_prefix} timed out after {max(30, timeout_seconds)}s\n"
            self.append_job_runtime_event(job.job_id, f"{log_prefix}: {model_name} timed out after {max(30, timeout_seconds)}s")
        combined = stdout_text.strip()
        answer = self.extract_freeagent_answer(stdout_text)
        effective_answer = "" if timed_out else answer
        summary_source = combined if timed_out else (effective_answer or combined)
        return {
            "model": model_name,
            "exitCode": exit_code,
            "stdout": stdout_text,
            "answer": effective_answer,
            "timedOut": timed_out,
            "summary": self.summarize_job_message(summary_source, 800),
            "outcome": self.summarize_worker_outcome(summary_source),
            "actor": "local-scout",
            "writesFiles": False,
            "filePaths": [],
        }

    def execute_isolated_codex_synthesis_command(
        self,
        job: JobRecord,
        prompt: str,
    ) -> dict[str, Any]:
        command = [
            self.codex_bin(),
            "exec",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-C",
            job.cwd,
            "--sandbox",
            "read-only",
            prompt,
        ]
        env = os.environ.copy()
        env.update({key: value for key, value in self.instance_process_env(job.instance_id).items() if value})
        self.append_job_runtime_event(job.job_id, "local final synthesizer: Codex")
        process = subprocess.Popen(
            command,
            cwd=job.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        chunks: list[str] = []
        if process.stdout is not None:
            for line in process.stdout:
                chunks.append(line)
        exit_code = process.wait()
        stdout_text = collapse_duplicate_codex_stdout("".join(chunks))
        return {
            "model": "codex",
            "exitCode": exit_code,
            "stdout": stdout_text,
            "answer": stdout_text.strip(),
            "summary": self.summarize_job_message(stdout_text, 800),
            "timedOut": False,
            "actor": "final-synthesizer",
            "writesFiles": False,
            "filePaths": [],
        }

    def execute_parallel_local_model_job(
        self,
        instance_id: str,
        job_id: str,
        base_command: list[str],
        original_prompt: str,
        scout_models: list[str],
        model_inspection: list[dict[str, Any]] | None = None,
        final_synthesizer: str = "ready-first",
        final_synthesizer_model: str = "qwen2.5-coder:7b",
        keep_loaded_local_models: bool = False,
    ) -> None:
        self.set_request_instance(instance_id)
        try:
            with self.lock:
                job = self.jobs_store(instance_id)[job_id]
                job.status = "in_progress"
                job.local_model_inspection = list(model_inspection or [])
            if prompt_is_low_signal(original_prompt):
                reason = "input too ambiguous for parallel local scouting; skipped local models"
                self.append_job_runtime_event(job_id, reason)
                lines = ["[Multi Model Results]", "", "[Skip Reason]", reason, "", "[Original Request]", original_prompt or "(empty)"]
                combined = "\n".join(lines).strip()
                with self.lock:
                    job.command_preview = "parallel-local-models: skipped-low-signal"
                    job.output = combined[-120000:]
                    job.exit_code = 0
                    job.status = "succeeded"
                    job.final_message = self.summarize_log_for_ui(combined)
                    job.ended_at = now_iso()
                return
            role_instructions = [
                ("fast-pass", "Provide the shortest practical interpretation and immediate next action."),
                ("quality-pass", "Focus on safer implementation shape, hidden assumptions, and likely mistakes."),
                ("verification-pass", "Focus on validation, rollback risk, and missing checks."),
                ("edge-pass", "Focus on edge cases, compatibility issues, and failure paths."),
            ]
            reports: list[dict[str, Any]] = []
            report_lock = threading.Lock()
            threads: list[threading.Thread] = []
            scout_timeout_seconds = 180
            overall_deadline = time.time() + max(120, scout_timeout_seconds + 30)
            self.prepare_parallel_local_models(job_id, list(scout_models), keep_loaded_local_models)
            refreshed_inspection = self.inspect_local_models(list(scout_models))
            with self.lock:
                job.local_model_inspection = refreshed_inspection

            def run_scout(index: int, model_name: str) -> None:
                role_name, role_instruction = role_instructions[index % len(role_instructions)]
                scout_prompt = self.build_local_model_scout_prompt(original_prompt, role_name, role_instruction, model_name)
                command = list(base_command)
                if len(command) >= 3:
                    command[2] = scout_prompt
                command = self.apply_freeagent_model_override(command, model_name)
                result = self.execute_isolated_freeagent_command(
                    job,
                    command,
                    job.cwd,
                    model_name,
                    f"local scout {index + 1}/{len(scout_models)}",
                    timeout_seconds=scout_timeout_seconds,
                )
                result["role"] = role_name
                result["assignedTask"] = self.describe_local_model_task(role_name, role_instruction)
                with report_lock:
                    reports.append(result)

            for index, model_name in enumerate(scout_models):
                thread = threading.Thread(target=run_scout, args=(index, model_name), daemon=True)
                thread.start()
                threads.append(thread)
            for thread in threads:
                remaining = max(0.0, overall_deadline - time.time())
                thread.join(timeout=remaining)

            missing_models = {
                safe_text(model).strip()
                for model in scout_models
                if safe_text(model).strip()
            } - {
                safe_text(report.get("model")).strip()
                for report in reports
                if safe_text(report.get("model")).strip()
            }
            if missing_models:
                for index, model_name in enumerate(scout_models):
                    normalized = safe_text(model_name).strip()
                    if normalized not in missing_models:
                        continue
                    role_name, _ = role_instructions[index % len(role_instructions)]
                    reports.append({
                        "model": normalized,
                        "role": role_name,
                        "exitCode": 124,
                        "stdout": f"[Launcher] local scout watchdog expired before completion for {normalized}",
                        "answer": "",
                        "timedOut": True,
                        "summary": f"[Launcher] local scout watchdog expired before completion for {normalized}",
                        "outcome": f"watchdog expired before completion for {normalized}",
                        "assignedTask": self.describe_local_model_task(role_name, role_instructions[index % len(role_instructions)][1]),
                        "actor": "local-scout",
                        "writesFiles": False,
                        "filePaths": [],
                    })
                    self.append_job_runtime_event(job.job_id, f"local scout watchdog expired: {normalized}")
                    self.log_parallel_worker_result(
                        job.job_id,
                        "parallel local scout",
                        normalized,
                        role_name,
                        safe_text(reports[-1].get("summary")),
                        exit_code=124,
                        timed_out=True,
                        actor="local-scout",
                        writes_files=False,
                        extra=f"task={safe_text(reports[-1].get('assignedTask'))}",
                    )

            reports.sort(key=lambda item: safe_text(item.get("model")))
            successful_reports = [
                report for report in reports
                if safe_int(report.get("exitCode"), 1) == 0 and not bool(report.get("timedOut"))
            ]
            synthesis_result: dict[str, Any] = {}
            synthesis_mode = self.normalize_parallel_local_synthesizer_mode(final_synthesizer)
            synthesis_prompt = self.build_local_model_synthesis_prompt(original_prompt, successful_reports)
            if successful_reports and synthesis_mode == "codex":
                synthesis_result = self.execute_isolated_codex_synthesis_command(job, synthesis_prompt)
                synthesis_result["role"] = "final-synthesizer"
                self.log_parallel_worker_result(
                    job.job_id,
                    "parallel final synth",
                    "codex",
                    "final-synthesizer",
                    safe_text(synthesis_result.get("summary") or synthesis_result.get("answer") or synthesis_result.get("stdout")),
                    exit_code=safe_int(synthesis_result.get("exitCode"), 1),
                    timed_out=bool(synthesis_result.get("timedOut")),
                    actor="final-synthesizer",
                    writes_files=False,
                    extra="task=Merge the local scout conclusions into one conservative final answer.",
                )
            elif successful_reports and synthesis_mode != "off":
                requested_model = safe_text(final_synthesizer_model).strip() or "qwen2.5-coder:7b"
                synthesis_model = scout_models[0] if synthesis_mode == "ready-first" else requested_model
                if synthesis_model in scout_models:
                    synthesis_ready = True
                else:
                    synthesis_ready = any(
                        safe_text(item.get("name")).strip() == synthesis_model and bool(item.get("ready"))
                        for item in refreshed_inspection
                    )
                if synthesis_ready:
                    synthesis_command = list(base_command)
                    if len(synthesis_command) >= 3:
                        synthesis_command[2] = synthesis_prompt
                    synthesis_command = self.apply_freeagent_model_override(synthesis_command, synthesis_model)
                    synthesis_result = self.execute_isolated_freeagent_command(
                        job,
                        synthesis_command,
                        job.cwd,
                        synthesis_model,
                        "local final synthesizer",
                        timeout_seconds=240,
                    )
                    synthesis_result["role"] = "final-synthesizer"
                    synthesis_result["assignedTask"] = "Merge the local scout conclusions into one conservative final answer."
                    self.log_parallel_worker_result(
                        job.job_id,
                        "parallel final synth",
                        synthesis_model,
                        "final-synthesizer",
                        safe_text(synthesis_result.get("summary") or synthesis_result.get("answer") or synthesis_result.get("stdout")),
                        exit_code=safe_int(synthesis_result.get("exitCode"), 1),
                        timed_out=bool(synthesis_result.get("timedOut")),
                        actor="final-synthesizer",
                        writes_files=False,
                        extra=f"task={safe_text(synthesis_result.get('assignedTask'))}",
                    )
                else:
                    synthesis_result = {
                        "model": synthesis_model,
                        "exitCode": 0,
                        "answer": f"Final synthesizer skipped: {synthesis_model} is not ready.",
                        "summary": f"Final synthesizer skipped: {synthesis_model} is not ready.",
                        "role": "final-synthesizer",
                        "skipped": True,
                        "assignedTask": "Merge the local scout conclusions into one conservative final answer.",
                    }
                    self.log_parallel_worker_result(
                        job.job_id,
                        "parallel final synth",
                        synthesis_model,
                        "final-synthesizer",
                        safe_text(synthesis_result.get("summary")),
                        exit_code=0,
                        extra="skipped=not-ready",
                        actor="final-synthesizer",
                        writes_files=False,
                    )

            if not successful_reports:
                primary_model = safe_text(scout_models[0] if scout_models else final_synthesizer_model).strip() or "qwen2.5-coder:7b"
                fallback_command = self.apply_freeagent_model_override(list(base_command), primary_model)
                fallback_result = self.execute_isolated_freeagent_command(
                    job,
                    fallback_command,
                    job.cwd,
                    primary_model,
                    "single-model fallback",
                    timeout_seconds=180,
                )
                fallback_result["role"] = "single-model-fallback"
                fallback_result["assignedTask"] = "Run a single local executor because no parallel scout completed successfully."
                self.log_parallel_worker_result(
                    job.job_id,
                    "parallel fallback",
                    primary_model,
                    "single-model-fallback",
                    safe_text(fallback_result.get("summary") or fallback_result.get("answer") or fallback_result.get("stdout")),
                    exit_code=safe_int(fallback_result.get("exitCode"), 1),
                    timed_out=bool(fallback_result.get("timedOut")),
                    actor="fallback-executor",
                    writes_files=False,
                    extra=f"task={safe_text(fallback_result.get('assignedTask'))}",
                )
                reports.append(fallback_result)
                reports.sort(key=lambda item: safe_text(item.get("model")))
                successful_reports = [
                    report for report in reports
                    if safe_int(report.get("exitCode"), 1) == 0 and not bool(report.get("timedOut"))
                ]

            lines = ["[Multi Model Results]", ""]
            if refreshed_inspection:
                lines.extend(["[Local Model Inspection]"])
                for item in refreshed_inspection:
                    expires_at = safe_text(item.get("expiresAt")).strip()
                    lines.append(
                        f"- {safe_text(item.get('name'))}: "
                        f"{'ready' if item.get('ready') else safe_text(item.get('reason')) or 'not ready'}"
                        f" · {'loaded' if item.get('loaded') else 'not-loaded'}"
                        f"{f' · expires={expires_at}' if expires_at else ''}"
                    )
                lines.append("")
            for report in reports:
                outcome = self.summarize_worker_outcome(
                    safe_text(report.get("answer") or report.get("summary") or report.get("stdout"))
                )
                lines.extend(
                    [
                        f"Model: {safe_text(report.get('model'))}",
                        f"Lens: {safe_text(report.get('role'))}",
                        f"Assigned Task: {safe_text(report.get('assignedTask')) or self.describe_local_model_task(safe_text(report.get('role')), '')}",
                        f"Actor: {safe_text(report.get('actor') or 'local-scout')}",
                        f"Writes Files: {'yes' if report.get('writesFiles') else 'no'}",
                        f"Outcome: {outcome}",
                        safe_text(report.get("answer") or report.get("summary") or "(no answer)").strip(),
                        "",
                    ]
                )
            if synthesis_result:
                synthesis_outcome = self.summarize_worker_outcome(
                    safe_text(synthesis_result.get("answer") or synthesis_result.get("summary") or synthesis_result.get("stdout"))
                )
                lines.extend(
                    [
                        "[Final Synthesizer]",
                        f"Model: {safe_text(synthesis_result.get('model'))}",
                        f"Assigned Task: {safe_text(synthesis_result.get('assignedTask')) or 'Merge the local scout conclusions into one conservative final answer.'}",
                        f"Actor: {safe_text(synthesis_result.get('actor') or 'final-synthesizer')}",
                        f"Writes Files: {'yes' if synthesis_result.get('writesFiles') else 'no'}",
                        f"Outcome: {synthesis_outcome}",
                        safe_text(synthesis_result.get("answer") or synthesis_result.get("summary") or "(no answer)").strip(),
                        "",
                    ]
                )
            combined = "\n".join(lines).strip()
            with self.lock:
                job.command_preview = (
                    "parallel-local-models: "
                    + ", ".join(scout_models)
                    + f" | final-synthesizer={synthesis_mode}"
                )
                job.output = combined[-120000:]
                all_exit_codes = [safe_int(item.get("exitCode"), 1) for item in reports]
                if synthesis_result:
                    all_exit_codes.append(safe_int(synthesis_result.get("exitCode"), 1))
                job.exit_code = 0 if all_exit_codes and all(exit_code == 0 for exit_code in all_exit_codes) else 1
                job.status = "succeeded" if job.exit_code == 0 else "failed"
                job.final_message = self.summarize_log_for_ui(combined)
                if job.status == "failed":
                    job.error = "one or more local model scouts failed"
                job.ended_at = now_iso()
        except Exception as exc:
            with self.lock:
                job = self.jobs_store(instance_id)[job_id]
                job.status = "failed"
                job.error = str(exc)
                job.ended_at = now_iso()
        finally:
            self.persist_job(job_id)
            self.clear_request_instance()

    def execute_isolated_codex_command(
        self,
        instance_id: str,
        job: JobRecord,
        account: dict[str, Any],
        command: list[str],
        cwd: str,
        output_file: Path,
        log_prefix: str,
        timeout_seconds: int = 240,
    ) -> dict[str, Any]:
        env = os.environ.copy()
        env.update({key: value for key, value in self.build_account_env(safe_text(account.get("id")), instance_id).items() if value})
        effective_command = list(command) + ["-o", str(output_file)]
        self.append_job_runtime_event(
            job.job_id,
            f"{log_prefix}: {safe_text(account.get('label') or account.get('email') or account.get('id'))} [{self.explain_account_capacity(account)}]",
        )
        try:
            output_file.unlink(missing_ok=True)
        except OSError:
            pass
        process = subprocess.Popen(
            effective_command,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=env,
        )
        timed_out = False
        try:
            stdout_text, _ = process.communicate(timeout=max(30, timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.terminate()
            try:
                stdout_text, _ = process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout_text, _ = process.communicate(timeout=5)
        exit_code = process.returncode
        stdout_text = safe_text(stdout_text)
        if timed_out:
            stdout_text = stdout_text.rstrip() + f"\n[Launcher] {log_prefix} timed out after {max(30, timeout_seconds)}s\n"
        final_text = ""
        if output_file.exists():
            try:
                final_text = output_file.read_text(encoding="utf-8")
            except OSError:
                final_text = ""
        combined = final_text.strip() or stdout_text.strip()
        return {
            "accountId": safe_text(account.get("id")),
            "accountLabel": safe_text(account.get("label") or account.get("email") or account.get("id")),
            "exitCode": exit_code,
            "stdout": stdout_text,
            "finalText": final_text,
            "timedOut": timed_out,
            "summary": self.summarize_job_message(combined, 800),
            "actor": "account-executor",
            "writesFiles": bool(final_text.strip()),
            "filePaths": self.extract_reported_file_paths(combined, cwd),
        }

    def isolated_codex_retry_status(self, result: dict[str, Any]) -> str:
        output_text = safe_text(result.get("stdout")) + "\n" + safe_text(result.get("finalText"))
        return self.detect_external_auth_status(output_text)

    def record_isolated_account_failure(
        self,
        job_id: str,
        account: dict[str, Any],
        result: dict[str, Any],
        status_code: str,
    ) -> str:
        account_id = safe_text(account.get("id"))
        account_label = safe_text(account.get("label") or account.get("email") or account_id)
        output_text = safe_text(result.get("stdout")) + "\n" + safe_text(result.get("finalText"))
        if status_code == "quota_wait":
            next_available_at = self.extract_retry_available_at(output_text)
            update_doc: dict[str, Any] = {
                "exhausted": True,
                "lastQuotaMessage": self.summarize_text(output_text, 2000),
                "lastQuotaDetectedAt": now_iso(),
            }
            if next_available_at:
                update_doc["nextAvailableAt"] = next_available_at
                update_doc["nextAvailableAtSource"] = "quota-output"
            else:
                update_doc["nextAvailableAt"] = ""
                update_doc["nextAvailableAtSource"] = ""
            if account_id:
                self.update_account_status(account_id, **update_doc)
            self.append_job_runtime_event(
                job_id,
                f"quota detected on {account_label}; switching parallel final account"
                + (f"; retry after {next_available_at}" if next_available_at else ""),
            )
            return next_available_at
        if status_code in {"unauthorized", "login_expired"}:
            if account_id:
                self.update_account_status(
                    account_id,
                    exhausted=False,
                    nextAvailableAt="",
                    nextAvailableAtSource="",
                    lastAuthStatus="unauthorized" if status_code == "unauthorized" else "expired",
                    lastAuthMessage=self.summarize_text(output_text, 2000),
                    lastAuthCheckedAt=now_iso(),
                )
            self.append_job_runtime_event(job_id, f"auth failure on {account_label}; switching parallel final account")
        return ""

    def execute_parallel_account_job(
        self,
        instance_id: str,
        job_id: str,
        base_command: list[str],
        output_file: Path,
        preferred_account_types: list[str] | None = None,
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        parallel_account_limit: int = 14,
        local_scout_models: list[str] | None = None,
        local_model_inspection: list[dict[str, Any]] | None = None,
        keep_loaded_local_models: bool = False,
    ) -> None:
        self.set_request_instance(instance_id)
        try:
            with self.lock:
                job = self.jobs_store(instance_id)[job_id]
                job.status = "in_progress"
            current_account_id = self.current_account_id()
            checked_slots = [self.account_slot_summary(safe_text(item.get("id"))) for item in self.list_account_slots()]
            precheck_lines = [
                f"- {safe_text(slot.get('label') or slot.get('email') or slot.get('id'))}: {self.explain_account_capacity(slot)}"
                for slot in checked_slots
            ]
            self.append_job_runtime_event(job_id, "parallel precheck:\n" + "\n".join(precheck_lines))
            max_parallel_accounts = max(1, safe_int(parallel_account_limit, 14))
            self.append_job_runtime_event(job_id, f"parallel account allocation: requested up to {max_parallel_accounts} accounts")
            ranked_slots, probe_rows = self.probe_parallel_account_candidates(
                job_id=job_id,
                preferred_account_types=preferred_account_types,
                current_account_id=current_account_id,
                preferred_account_id=preferred_account_id,
                preferred_account_ids=preferred_account_ids,
                max_accounts=max_parallel_accounts,
            )
            if not ranked_slots:
                raise RuntimeError("사용 가능한 계정이 없습니다. 계정 상태 스캔 후 다시 시도하세요.")

            command_prefix = list(base_command[:-1])
            original_prompt = safe_text(base_command[-1]).strip()
            scout_roles = [
                ("repo-scan", "Find the smallest set of files, modules, and entry points directly relevant to the request."),
                ("docs-scan", "Read docs, skills, and conventions relevant to the request. Summarize required rules and constraints."),
                ("risk-scan", "Identify implementation risks, regression points, and missing tests. Focus on verification strategy."),
                ("plan-scan", "Draft the safest implementation order and note blocking assumptions."),
                ("edge-scan", "Look for edge cases, hidden coupling, migration concerns, and rollback risk."),
                ("qa-scan", "Focus on acceptance criteria and validation steps for the requested change."),
            ]
            local_roles = [
                ("fast-pass", "Provide the shortest practical interpretation and immediate next action."),
                ("quality-pass", "Focus on safer implementation shape, hidden assumptions, and likely mistakes."),
                ("verification-pass", "Focus on validation, rollback risk, and missing checks."),
                ("edge-pass", "Focus on edge cases, compatibility issues, and failure paths."),
            ]
            if prompt_is_low_signal(original_prompt):
                local_scout_models = []
                self.append_job_runtime_event(job_id, "parallel local scouts skipped: input too ambiguous for local model work")
            final_account = ranked_slots[0]
            scout_accounts = ranked_slots[1:]
            job.failover_history.append({
                "at": now_iso(),
                "reason": "parallel_preflight",
                "fromAccountId": current_account_id,
                "toAccountId": safe_text(final_account.get("id")),
                "nextAvailableAt": "",
                "probes": probe_rows,
            })
            scout_reports: list[dict[str, str]] = []
            local_reports: list[dict[str, Any]] = []
            scout_lock = threading.Lock()
            local_lock = threading.Lock()
            scout_threads: list[threading.Thread] = []
            local_threads: list[threading.Thread] = []
            self.prepare_parallel_local_models(job_id, list(local_scout_models or []), keep_loaded_local_models)
            if local_scout_models:
                with self.lock:
                    job.local_model_inspection = self.inspect_local_models(list(local_scout_models))

            def run_scout(index: int, account: dict[str, Any]) -> None:
                role_name, role_instruction = scout_roles[index % len(scout_roles)]
                scout_prompt = self.build_parallel_scout_prompt(original_prompt, role_name, role_instruction, job.cwd, account)
                scout_command = list(command_prefix) + [scout_prompt]
                scout_output_file = self.jobs_root_path(instance_id) / f"{job.job_id}-scout-{index + 1}.txt"
                result = self.execute_isolated_codex_command(
                    instance_id,
                    job,
                    account,
                    scout_command,
                    job.cwd,
                    scout_output_file,
                    f"parallel scout {index + 1}/{len(scout_accounts)}",
                    timeout_seconds=180,
                )
                result["role"] = role_name
                result["assignedTask"] = self.describe_local_model_task(role_name, role_instruction)
                self.log_parallel_worker_result(
                    job_id,
                    "parallel account scout",
                    safe_text(account.get("label") or account.get("email") or account.get("id")),
                    role_name,
                    safe_text(result.get("summary") or result.get("finalText") or result.get("stdout")),
                    exit_code=safe_int(result.get("exitCode"), 1),
                    timed_out=bool(result.get("timedOut")),
                    extra=f"account={safe_text(account.get('id'))} | task={safe_text(result.get('assignedTask'))}",
                    actor="account-scout",
                    writes_files=False,
                )
                retry_status = self.isolated_codex_retry_status(result)
                if retry_status in {"quota_wait", "unauthorized", "login_expired"}:
                    next_available_at = self.record_isolated_account_failure(job_id, account, result, retry_status)
                    with self.lock:
                        job.failover_history.append({
                            "at": now_iso(),
                            "reason": f"parallel_scout_{retry_status}",
                            "fromAccountId": safe_text(account.get("id")),
                            "toAccountId": "",
                            "nextAvailableAt": next_available_at,
                            "probes": [],
                        })
                with scout_lock:
                    scout_reports.append(result)

            for index, account in enumerate(scout_accounts):
                thread = threading.Thread(target=run_scout, args=(index, account), daemon=True)
                thread.start()
                scout_threads.append(thread)

            def run_local_scout(index: int, model_name: str) -> None:
                role_name, role_instruction = local_roles[index % len(local_roles)]
                scout_prompt = self.build_local_model_scout_prompt(original_prompt, role_name, role_instruction, model_name)
                local_command = [
                    self.freeagent_bin(),
                    "prompt",
                    scout_prompt,
                    "--model",
                    model_name,
                ]
                result = self.execute_isolated_freeagent_command(
                    job,
                    local_command,
                    job.cwd,
                    model_name,
                    f"parallel local scout {index + 1}/{len(local_scout_models or [])}",
                    timeout_seconds=180,
                )
                result["role"] = role_name
                result["assignedTask"] = self.describe_local_model_task(role_name, role_instruction)
                self.log_parallel_worker_result(
                    job_id,
                    "parallel local scout",
                    model_name,
                    role_name,
                    safe_text(result.get("summary") or result.get("answer") or result.get("stdout")),
                    exit_code=safe_int(result.get("exitCode"), 1),
                    timed_out=bool(result.get("timedOut")),
                    actor="local-scout",
                    writes_files=False,
                    extra=f"task={safe_text(result.get('assignedTask'))}",
                )
                with local_lock:
                    local_reports.append(result)

            for index, model_name in enumerate(local_scout_models or []):
                normalized = safe_text(model_name).strip()
                if not normalized:
                    continue
                thread = threading.Thread(target=run_local_scout, args=(index, normalized), daemon=True)
                thread.start()
                local_threads.append(thread)

            for thread in scout_threads:
                thread.join(timeout=210)
            for thread in local_threads:
                thread.join(timeout=210)
            if any(thread.is_alive() for thread in scout_threads):
                self.append_job_runtime_event(
                    job_id,
                    "one or more parallel scouts exceeded the launcher wait window; continuing with completed scout reports",
                )
            if any(thread.is_alive() for thread in local_threads):
                self.append_job_runtime_event(
                    job_id,
                    "one or more parallel local scouts exceeded the launcher wait window; continuing with completed local reports",
                )

            local_reports.sort(key=lambda item: safe_text(item.get("model")))
            final_prompt = self.build_parallel_final_prompt(original_prompt, scout_reports, job.cwd, local_reports)
            final_command = list(command_prefix) + [final_prompt]
            final_candidates = [final_account] + [account for account in scout_accounts if safe_text(account.get("id")) != safe_text(final_account.get("id"))]
            result: dict[str, Any] = {}
            final_used_account = final_account
            attempted_final_accounts: set[str] = set()
            final_workspace_before = self.capture_workspace_file_state(job.cwd)
            for attempt_index, candidate in enumerate(final_candidates, start=1):
                candidate_id = safe_text(candidate.get("id"))
                if candidate_id in attempted_final_accounts:
                    continue
                attempted_final_accounts.add(candidate_id)
                final_used_account = candidate
                result = self.execute_isolated_codex_command(
                    instance_id,
                    job,
                    candidate,
                    final_command,
                    job.cwd,
                    output_file,
                    f"parallel final {attempt_index}/{len(final_candidates)}",
                    timeout_seconds=300,
                )
                retry_status = self.isolated_codex_retry_status(result)
                if safe_int(result.get("exitCode"), 1) == 0 or retry_status not in {"quota_wait", "unauthorized", "login_expired"}:
                    break
                next_available_at = self.record_isolated_account_failure(job_id, candidate, result, retry_status)
                job.failover_history.append({
                    "at": now_iso(),
                    "reason": retry_status,
                    "fromAccountId": candidate_id,
                    "toAccountId": safe_text(next_item.get("id")) if (next_item := next((item for item in final_candidates if safe_text(item.get("id")) not in attempted_final_accounts), None)) else "",
                    "nextAvailableAt": next_available_at,
                    "probes": [],
                })
            final_output = safe_text(result.get("finalText") or result.get("stdout"))
            final_workspace_after = self.capture_workspace_file_state(job.cwd)
            final_workspace_diff = self.diff_workspace_file_state(final_workspace_before, final_workspace_after)
            final_paths = list(final_workspace_diff.get("changed") or result.get("filePaths") or self.extract_reported_file_paths(final_output, job.cwd))
            final_task = "Execute the requested work end-to-end using scout findings and write the actual changes."
            if final_paths:
                change_bits = []
                if final_workspace_diff.get("created"):
                    change_bits.append(f"created={', '.join(final_workspace_diff['created'][:8])}")
                if final_workspace_diff.get("modified"):
                    change_bits.append(f"modified={', '.join(final_workspace_diff['modified'][:8])}")
                if final_workspace_diff.get("deleted"):
                    change_bits.append(f"deleted={', '.join(final_workspace_diff['deleted'][:8])}")
                self.append_job_runtime_event(job_id, "parallel final workspace changes | " + " | ".join(change_bits))
            self.log_parallel_worker_result(
                job_id,
                "parallel final executor",
                safe_text(final_used_account.get("label") or final_used_account.get("email") or final_used_account.get("id")),
                "final-executor",
                final_output,
                exit_code=safe_int(result.get("exitCode"), 1),
                timed_out=bool(result.get("timedOut")),
                actor="final-executor",
                writes_files=bool(final_paths),
                file_paths=final_paths,
                extra=f"task={final_task}",
            )
            with self.lock:
                job.execution_account_id = safe_text(final_used_account.get("id"))
                job.execution_account_label = safe_text(final_used_account.get("label") or final_used_account.get("email") or final_used_account.get("id"))
                job.command_preview = shlex.join(final_command + ["-o", str(output_file)])
                job.output = final_output[-120000:]
                job.exit_code = safe_int(result.get("exitCode"), 1)
                job.status = "succeeded" if job.exit_code == 0 else "failed"
                job.final_message = self.summarize_log_for_ui(final_output)
                if job.status == "failed":
                    job.error = self.summarize_job_message(final_output, 800)
                job.ended_at = now_iso()
        except Exception as exc:
            with self.lock:
                job = self.jobs_store(instance_id)[job_id]
                job.status = "failed"
                job.error = str(exc)
                job.ended_at = now_iso()
        finally:
            self.persist_job(job_id)
            self.clear_request_instance()

    def run_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        action_id = safe_text(payload.get("actionId"))
        
        # System Actions
        if action_id == "account-scan":
            job_id = uuid.uuid4().hex[:8]
            job = JobRecord(
                job_id=job_id,
                title="계정 상태 전체 정밀 스캔",
                kind="system",
                instance_id=self.current_instance_id(),
                session_id=safe_text(payload.get("sessionId")),
                session_title="",
                plan_step="",
                workspace_id=safe_text(payload.get("workspaceId")),
                workspace_label="System",
                cwd="",
                command_preview="LauncherApp.scan_all_accounts()",
            )
            with self.lock:
                self.jobs_store(job.instance_id)[job_id] = job
            
            # Run scan in a separate thread like other jobs
            def runner():
                self.set_request_instance(job.instance_id)
                try:
                    res = self.scan_all_accounts()
                    with self.lock:
                        job.status = "succeeded"
                        job.output = res.get("message", "Scan complete")
                        # Format the results as a pretty table/list in colors
                        rows = ["\x1b[1;36m[ 계정 스캔 리포트 ]\x1b[0m\n"]
                        for r in res.get("results", []):
                            status_color = "\x1b[32m[Ready]\x1b[0m" if r.get("status") == "Ready" else "\x1b[31m[Expired]\x1b[0m"
                            rows.append(f"{status_color} {r.get('email', 'N/A')} ({r.get('id')})")
                        
                        job.final_message = self.summarize_log_for_ui("\n".join(rows))
                        job.ended_at = now_iso()
                except Exception as exc:
                    with self.lock:
                        job.status = "failed"
                        job.error = str(exc)
                        job.ended_at = now_iso()
                finally:
                    self.persist_job(job_id)
                    self.clear_request_instance()

            threading.Thread(target=runner, daemon=True).start()

            return job.as_dict()

        workspace = self.resolve_workspace(payload)
        session = self.resolve_session(payload, workspace)
        action = self.actions.get(action_id) if action_id else None
        spec = self.build_spec(payload, workspace, session)
        classic_mode = safe_bool(payload.get("classicMode"), False)
        parallel_accounts = safe_bool(payload.get("parallelAccounts"), False)
        routing_settings = self.model_routing_settings(payload)
        runtime_preset = self.runtime_preset_for_payload(payload, action)
        simple_presets = set(routing_settings.get("simpleTaskLocalPresets", []))
        explicit_cli = safe_text(payload.get("cli")).strip().lower()
        if (
            not classic_mode
            and parallel_accounts
            and safe_text(spec.get("kind")) == "freeagent"
            and safe_text(spec.get("effective_cli")) == "freeagent"
            and safe_text(spec.get("effective_mode")) != "apply"
            and explicit_cli not in {"freeagent", "minimax"}
            and safe_bool(routing_settings.get("enabled"), True)
            and safe_bool(routing_settings.get("allowParallelLocalWorkers"), False)
            and safe_bool(routing_settings.get("simpleTaskLocalParallel"), True)
            and safe_int(routing_settings.get("parallelLocalWorkers"), 1) > 1
            and runtime_preset in simple_presets
        ):
            requested_scout_models = self.local_scout_models(
                routing_settings,
                runtime_preset,
                safe_text(spec.get("effective_model")).strip(),
            )
            final_synthesizer = self.normalize_parallel_local_synthesizer_mode(routing_settings.get("parallelLocalFinalSynthesizer"))
            final_synthesizer_model = safe_text(routing_settings.get("parallelLocalFinalSynthesizerModel")).strip() or "qwen2.5-coder:7b"
            inspection_models = list(requested_scout_models)
            if final_synthesizer == "local-7b" and final_synthesizer_model not in inspection_models:
                inspection_models.append(final_synthesizer_model)
            inspected_models = self.inspect_local_models(inspection_models)
            ready_scout_models = [safe_text(item.get("name")).strip() for item in inspected_models if item.get("ready")]
            ready_scout_models = [model for model in ready_scout_models if model in requested_scout_models]
            all_loaded_required = safe_bool(routing_settings.get("parallelLocalAllLoadedRequired"), False)
            loaded_requested_models = [
                safe_text(item.get("name")).strip()
                for item in inspected_models
                if item.get("ready") and item.get("loaded") and safe_text(item.get("name")).strip() in requested_scout_models
            ]
            local_parallel_models = loaded_requested_models if all_loaded_required else ready_scout_models
            if len(local_parallel_models) > 1:
                response = self.enqueue_parallel_local_model_job(
                    title=f"{safe_text(spec.get('title'))} [parallel-local]",
                    cwd=spec["cwd"],
                    command=spec["command"],
                    workspace=workspace,
                    session=session,
                    scout_models=local_parallel_models,
                    original_prompt=safe_text(spec.get("effective_prompt")).strip(),
                    plan_step=safe_text(payload.get("planStep")).strip(),
                    model_inspection=inspected_models,
                    final_synthesizer=final_synthesizer,
                    final_synthesizer_model=final_synthesizer_model,
                    keep_loaded_local_models=safe_bool(routing_settings.get("parallelLocalKeepLoaded"), False),
                )
                response["autoRuntimePreset"] = runtime_preset
                response["parallelLocalModels"] = local_parallel_models
                response["localModelInspection"] = inspected_models
                response["parallelLocalFinalSynthesizer"] = final_synthesizer
                response["effectiveCli"] = "freeagent-multi"
                response["effectiveModel"] = ", ".join(local_parallel_models)
                return response
        current_slot_id = self.current_account_id()
        current_summary = self.current_account_summary()
        preferred_account_ids = payload.get("preferredAccountIds")
        if not isinstance(preferred_account_ids, list):
            preferred_account_ids = action.get("preferredAccountIds", []) if action else []
        best_account = None
        if classic_mode:
            if current_slot_id or current_summary:
                best_account = {
                    "id": current_slot_id,
                    "label": safe_text(current_summary.get("email")) or safe_text(current_summary.get("name")) or current_slot_id,
                    "email": safe_text(current_summary.get("email")),
                    "accountId": safe_text(current_summary.get("accountId")),
                }
        elif not parallel_accounts:
            preferred_account_id = safe_text(payload.get("preferredAccountId")).strip() or safe_text(action.get("preferredAccountId") if action else "").strip()
            best_account = self.activate_first_reusable_account(
                excluded_ids=None,
                preferred_account_types=self.preferred_account_types_for_payload(payload, action),
                current_account_id=current_slot_id,
                preferred_account_id=preferred_account_id,
                preferred_account_ids=preferred_account_ids,
            )
            if best_account:
                print(f"Auto-selected account: {best_account.get('email')} ({best_account.get('id')})")
            elif current_slot_id or current_summary:
                best_account = {
                    "id": current_slot_id,
                    "label": safe_text(current_summary.get("email")) or safe_text(current_summary.get("name")) or current_slot_id,
                    "email": safe_text(current_summary.get("email")),
                    "accountId": safe_text(current_summary.get("accountId")),
                }

        account_chain = []
        if not classic_mode and isinstance(preferred_account_ids, list):
            account_chain = [safe_text(item).strip() for item in preferred_account_ids if safe_text(item).strip()]
        preferred_account_id = safe_text(payload.get("preferredAccountId")).strip() or safe_text(action.get("preferredAccountId") if action else "").strip()
        if not classic_mode and preferred_account_id and preferred_account_id not in account_chain:
            account_chain.insert(0, preferred_account_id)

        if parallel_accounts and safe_text(spec.get("kind")) == "codex" and not classic_mode and spec.get("command", [None])[0] == self.codex_bin():
            parallel_account_limit = self.parallel_account_allocation_limit(routing_settings, runtime_preset)
            if parallel_account_limit <= 0:
                parallel_account_limit = 1
            local_requested_models = self.local_scout_models(
                routing_settings,
                runtime_preset if runtime_preset in {"question", "summary", "migration", "implementation", "lite", "balanced"} else "question",
                "qwen2.5-coder:1.5b",
            )
            local_inspection = self.inspect_local_models(local_requested_models)
            ready_local_models = [safe_text(item.get("name")).strip() for item in local_inspection if item.get("ready")]
            if safe_bool(routing_settings.get("parallelLocalAllLoadedRequired"), False):
                ready_local_models = [
                    safe_text(item.get("name")).strip()
                    for item in local_inspection
                    if item.get("ready") and item.get("loaded")
                ]
            response = self.enqueue_parallel_account_job(
                title=f"{spec['title']} [parallel]",
                cwd=spec["cwd"],
                command=spec["command"],
                command_preview=spec["command_preview"],
                workspace=workspace,
                session=session,
                plan_step=safe_text(payload.get("planStep")).strip(),
                preferred_account_types=self.preferred_account_types_for_payload(payload, action),
                preferred_account_id=preferred_account_id,
                preferred_account_ids=account_chain,
                parallel_account_limit=parallel_account_limit,
                local_scout_models=ready_local_models,
                local_model_inspection=local_inspection,
                keep_loaded_local_models=safe_bool(routing_settings.get("parallelLocalKeepLoaded"), False),
            )
            response["autoRuntimePreset"] = runtime_preset
            response["parallelAccountAllocation"] = parallel_account_limit
            response["parallelAccounts"] = True
            response["parallelLocalModels"] = ready_local_models
            response["localModelInspection"] = local_inspection
            response["effectiveCli"] = "codex-hybrid"
            return response

        response = self.enqueue_job_spec(
            title=spec["title"],
            kind=spec["kind"],
            cwd=spec["cwd"],
            command=spec["command"],
            command_preview=spec["command_preview"],
            workspace=workspace,
            session=session,
            plan_step=safe_text(payload.get("planStep")).strip(),
            env_overrides=spec.get("env_overrides"),
            account_chain=account_chain,
            execution_account_id=safe_text(best_account.get("id")) if best_account else "",
            execution_account_label=safe_text(best_account.get("label") or best_account.get("email") or best_account.get("accountId")) if best_account else "",
        )
        if best_account:
            response["autoAccountId"] = safe_text(best_account.get("id"))
            response["autoAccountLabel"] = safe_text(best_account.get("label") or best_account.get("email") or best_account.get("accountId"))
        response["autoRuntimePreset"] = "classic" if classic_mode else runtime_preset
        if safe_text(spec.get("route_note")).strip():
            response["routeNote"] = safe_text(spec.get("route_note")).strip()
        if safe_text(spec.get("effective_model")).strip():
            response["effectiveModel"] = safe_text(spec.get("effective_model")).strip()
        if safe_text(spec.get("effective_cli")).strip():
            response["effectiveCli"] = safe_text(spec.get("effective_cli")).strip()
        return response

    def enqueue_parallel_account_job(
        self,
        title: str,
        cwd: str,
        command: list[str],
        command_preview: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        plan_step: str = "",
        preferred_account_types: list[str] | None = None,
        preferred_account_id: str = "",
        preferred_account_ids: list[str] | None = None,
        parallel_account_limit: int = 14,
        local_scout_models: list[str] | None = None,
        local_model_inspection: list[dict[str, Any]] | None = None,
        keep_loaded_local_models: bool = False,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        output_file = self.jobs_root_path() / f"{job_id}-final.txt"
        job = JobRecord(
            job_id=job_id,
            title=title,
            kind="codex",
            instance_id=self.current_instance_id(),
            session_id=safe_text(session.get("id")),
            session_title=safe_text(session.get("title")),
            plan_step=plan_step,
            workspace_id=workspace["id"],
            workspace_label=workspace["label"],
            cwd=cwd,
            command_preview=command_preview,
            output_file=str(output_file),
            account_chain=list(preferred_account_ids or []),
            local_model_inspection=list(local_model_inspection or []),
        )
        with self.lock:
            self.jobs_store(job.instance_id)[job_id] = job
        thread = threading.Thread(
            target=self.execute_parallel_account_job,
            args=(
                job.instance_id,
                job_id,
                command,
                output_file,
                preferred_account_types,
                preferred_account_id,
                list(preferred_account_ids or []),
                max(1, safe_int(parallel_account_limit, 14)),
                list(local_scout_models or []),
                list(local_model_inspection or []),
                bool(keep_loaded_local_models),
            ),
            daemon=True,
        )
        thread.start()
        return job.as_dict()

    def enqueue_parallel_local_model_job(
        self,
        title: str,
        cwd: str,
        command: list[str],
        workspace: dict[str, Any],
        session: dict[str, Any],
        scout_models: list[str],
        original_prompt: str,
        plan_step: str = "",
        model_inspection: list[dict[str, Any]] | None = None,
        final_synthesizer: str = "ready-first",
        final_synthesizer_model: str = "qwen2.5-coder:7b",
        keep_loaded_local_models: bool = False,
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        output_file = self.jobs_root_path() / f"{job_id}-final.txt"
        job = JobRecord(
            job_id=job_id,
            title=title,
            kind="freeagent",
            instance_id=self.current_instance_id(),
            session_id=safe_text(session.get("id")),
            session_title=safe_text(session.get("title")),
            plan_step=plan_step,
            workspace_id=workspace["id"],
            workspace_label=workspace["label"],
            cwd=cwd,
            command_preview="parallel-local-models: " + ", ".join(scout_models) + f" | final-synthesizer={final_synthesizer}",
            output_file=str(output_file),
            local_model_inspection=list(model_inspection or []),
        )
        with self.lock:
            self.jobs_store(job.instance_id)[job_id] = job
        thread = threading.Thread(
            target=self.execute_parallel_local_model_job,
            args=(
                job.instance_id,
                job_id,
                command,
                original_prompt,
                list(scout_models),
                list(model_inspection or []),
                final_synthesizer,
                final_synthesizer_model,
                bool(keep_loaded_local_models),
            ),
            daemon=True,
        )
        thread.start()
        return job.as_dict()

    def enqueue_job_spec(
        self,
        title: str,
        kind: str,
        cwd: str,
        command: list[str],
        command_preview: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        plan_step: str = "",
        env_overrides: dict[str, str] | None = None,
        account_chain: list[str] | None = None,
        execution_account_id: str = "",
        execution_account_label: str = "",
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        output_file = self.jobs_root_path() / f"{job_id}-final.txt"
        job = JobRecord(
            job_id=job_id,
            title=title,
            kind=kind,
            instance_id=self.current_instance_id(),
            session_id=safe_text(session.get("id")),
            session_title=safe_text(session.get("title")),
            plan_step=plan_step,
            workspace_id=workspace["id"],
            workspace_label=workspace["label"],
            cwd=cwd,
            command_preview=command_preview,
            output_file=str(output_file),
            account_chain=list(account_chain or []),
            execution_account_id=execution_account_id,
            execution_account_label=execution_account_label,
        )
        with self.lock:
            self.jobs_store(job.instance_id)[job_id] = job
        thread = threading.Thread(
            target=self._execute_job,
            args=(job.instance_id, job_id, command, output_file, env_overrides),
            daemon=True,
        )
        thread.start()
        return job.as_dict()

    def run_project_runtime_action(self, payload: dict[str, Any], action_name: str) -> dict[str, Any]:
        project_path = safe_text(payload.get("projectPath")).strip()
        if not project_path:
            raise ValueError("projectPath is required")
        target = self.resolve_project_runtime_target(project_path)
        if target is None:
            raise ValueError("No runtime control profile matched this project path.")
        commands = target.get("commands", {})
        shell_command = safe_text(commands.get(action_name)).strip()
        if not shell_command:
            raise ValueError(f"Runtime action is not configured: {action_name}")
        workspace = self.resolve_workspace(payload)
        session = self.resolve_session(payload, workspace)
        title = f"{safe_text(target.get('label') or target.get('id') or 'project')} {action_name}"
        return self.enqueue_job_spec(
            title=title,
            kind="shell",
            cwd=safe_text(workspace["path"]),
            command=["bash", "-lc", shell_command],
            command_preview=shell_command,
            workspace=workspace,
            session=session,
            plan_step=safe_text(payload.get("planStep")).strip(),
        )

    def resolve_workspace(self, payload: dict[str, Any]) -> dict[str, Any]:
        project_path = safe_text(payload.get("projectPath")).strip()
        if project_path:
            path = self.resolve_project_path(project_path)
            return {
                "id": f"project:{path.name}",
                "label": f"Project {path.name}",
                "path": str(path),
                "defaultSandbox": "workspace-write",
            }
        workspace_id = safe_text(payload.get("workspaceId")) or safe_text(self.workspaces_doc.get("defaultWorkspaceId"))
        workspace = self.workspaces.get(workspace_id)
        if workspace is None:
            raise ValueError(f"Unknown workspace: {workspace_id}")
        path = Path(safe_text(workspace.get("path")))
        if not path.exists():
            raise ValueError(f"Workspace path not found: {path}")
        return workspace

    def build_spec(self, payload: dict[str, Any], workspace: dict[str, Any], session: dict[str, Any]) -> dict[str, Any]:
        mode = safe_text(payload.get("mode"))
        plan_step = safe_text(payload.get("planStep")).strip()
        action_id = safe_text(payload.get("actionId"))
        action = self.actions.get(action_id) if action_id else None
        classic_mode = safe_bool(payload.get("classicMode"), False)
        runtime_options = self.classic_runtime_options() if classic_mode else self.auto_runtime_options(payload, action)
        if mode == "assistant_custom":
            prompt = safe_text(payload.get("prompt")).strip()
            if not prompt:
                raise ValueError("Prompt is required.")
            cli_id = safe_text(payload.get("cli")).strip().lower() or "codex"
            route = self.determine_model_route(
                payload,
                None,
                cli_id,
                safe_text(payload.get("freeagentModel")).strip(),
            )
            cli_id = safe_text(route.get("cli")).strip().lower() or cli_id
            routed_model = safe_text(route.get("model")).strip()
            if cli_id == "minimax-codex":
                spec = self.build_minimax_codex_spec(
                    title="Custom MiniMax Codex Prompt",
                    workspace=workspace,
                    session=session,
                    prompt=prompt,
                    full_auto=True,
                    plan_step=plan_step,
                    runtime_options=runtime_options,
                )
                spec["route_note"] = safe_text(route.get("note"))
                return spec
            if cli_id in {"freeagent", "minimax"}:
                spec = self.build_freeagent_spec(
                    title="Custom MiniMax Prompt" if cli_id == "minimax" else "Custom FreeAgent Prompt",
                    workspace=workspace,
                    session=session,
                    prompt=prompt,
                    freeagent_mode=safe_text(route.get("freeagentMode")) or safe_text(payload.get("freeagentMode")) or "prompt",
                    freeagent_targets=safe_text(payload.get("freeagentTargets")).strip(),
                    freeagent_test_command=safe_text(payload.get("freeagentTestCommand")).strip(),
                    provider_override="minimax" if cli_id == "minimax" else "",
                    plan_step=plan_step,
                    runtime_options=runtime_options,
                    freeagent_model=routed_model or safe_text(payload.get("freeagentModel")).strip(),
                    model_routing=route.get("settings") if isinstance(route.get("settings"), dict) else None,
                )
                spec["route_note"] = safe_text(route.get("note"))
                return spec
            spec = self.build_codex_spec(
                title="Custom Codex Prompt",
                workspace=workspace,
                session=session,
                prompt=prompt,
                full_auto=True,
                plan_step=plan_step,
                runtime_options=runtime_options,
            )
            spec["route_note"] = safe_text(route.get("note"))
            return spec
        if mode == "codex_custom":
            prompt = safe_text(payload.get("prompt")).strip()
            if not prompt:
                raise ValueError("Prompt is required.")
            return self.build_codex_spec(
                title="Custom Codex Prompt",
                workspace=workspace,
                session=session,
                prompt=prompt,
                full_auto=True,
                plan_step=plan_step,
                runtime_options=runtime_options,
            )
        if mode == "shell_custom":
            command = safe_text(payload.get("shellCommand")).strip()
            if not command:
                raise ValueError("Shell command is required.")
            return {
                "title": "Custom Shell Command",
                "kind": "shell",
                "cwd": safe_text(workspace["path"]),
                "command": ["bash", "-lc", command],
                "command_preview": command,
            }

        action = self.actions.get(action_id)
        if action is None:
            raise ValueError("Action is required.")

        if safe_text(action.get("kind")) == "codex":
            extra_input = safe_text(payload.get("extraInput")).strip()
            prompt = safe_text(payload.get("prompt")).strip() or safe_text(action.get("promptTemplate")).strip()
            if extra_input:
                prompt = f"{prompt}\n\n추가 입력:\n{extra_input}"
            return self.build_codex_spec(
                title=safe_text(action.get("label")) or action_id,
                workspace=self.resolve_action_workspace(action, workspace),
                session=session,
                prompt=prompt,
                full_auto=bool(action.get("fullAuto", True)),
                plan_step=plan_step,
                runtime_options=runtime_options,
            )

        command_workspace = self.resolve_action_workspace(action, workspace)
        cwd = safe_text(command_workspace["path"])
        if action.get("script"):
            script_path = (self.app_root / safe_text(action["script"])).resolve()
            if not script_path.exists():
                raise ValueError(f"Script not found: {script_path}")
            command = ["bash", str(script_path)]
            preview = str(script_path)
        elif action.get("command"):
            command = [safe_text(item) for item in action.get("command", [])]
            preview = shlex.join(command)
        else:
            shell = safe_text(action.get("shell")).strip()
            if not shell:
                raise ValueError(f"Unsupported action: {action_id}")
            command = ["bash", "-lc", shell]
            preview = shell
        return {
            "title": safe_text(action.get("label")) or action_id,
            "kind": "shell",
            "cwd": cwd,
            "command": command,
            "command_preview": preview,
        }

    def estimate_prompt_tokens(self, text: str) -> int:
        raw = safe_text(text)
        if not raw:
            return 0
        # Rough estimate for mixed Korean/English prompts.
        return max(1, int((len(raw) + 3) / 4))

    def prompt_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = self.resolve_workspace(payload)
        session_id = safe_text(payload.get("sessionId")).strip()
        session = self.load_session(session_id) if session_id else self.current_session()
        action_id = safe_text(payload.get("actionId")).strip()
        action = self.actions.get(action_id) if action_id else None
        spec = self.build_spec(payload, workspace, session)
        effective_prompt = safe_text(spec.get("effective_prompt"))
        preview_note = "실행 직전 서버 기준 preview입니다."
        if safe_text(spec.get("kind")) == "shell":
            preview_note = "Shell action은 prompt preview 대신 실행 명령만 표시합니다."
        classic_mode = safe_bool(payload.get("classicMode"), False)
        parallel_accounts = safe_bool(payload.get("parallelAccounts"), False)
        current_slot_id = self.current_account_id()
        current_summary = self.current_account_summary()
        recommended_account = {}
        runtime_preset = "classic" if classic_mode else self.runtime_preset_for_payload(payload, action)
        explicit_cli = safe_text(payload.get("cli")).strip().lower()
        note_bits = [preview_note]
        if classic_mode:
            note_bits.append("Classic Mode: 자동 계정/자동 토큰 절약/세션 문맥 우회")
            if current_slot_id or current_summary:
                recommended_account = {
                    "id": current_slot_id,
                    "label": safe_text(current_summary.get("email")) or safe_text(current_summary.get("name")) or current_slot_id,
                    "email": safe_text(current_summary.get("email")),
                    "accountId": safe_text(current_summary.get("accountId")),
                    "statusCode": "active",
                }
        else:
            preferred_account_id = safe_text(payload.get("preferredAccountId")).strip() or safe_text(action.get("preferredAccountId") if action else "").strip()
            preferred_account_ids = payload.get("preferredAccountIds")
            if not isinstance(preferred_account_ids, list):
                preferred_account_ids = action.get("preferredAccountIds", []) if action else []
            recommended_account = self.select_best_account(
                preferred_account_types=self.preferred_account_types_for_payload(payload, action),
                current_account_id=current_slot_id,
                preferred_account_id=preferred_account_id,
                preferred_account_ids=preferred_account_ids,
            ) or {}
            note_bits.append(f"자동 토큰 프리셋: {self.runtime_preset_label(runtime_preset)}")
        if parallel_accounts and not classic_mode and safe_text(spec.get("kind")) == "codex" and spec.get("command", [None])[0] == self.codex_bin():
            routing_settings = self.model_routing_settings(payload)
            allocation_limit = self.parallel_account_allocation_limit(routing_settings, runtime_preset)
            if allocation_limit <= 0:
                allocation_limit = 1
            parallel_candidates = self.reusable_parallel_accounts(
                preferred_account_types=self.preferred_account_types_for_payload(payload, action),
                current_account_id=current_slot_id,
                preferred_account_id=safe_text(payload.get("preferredAccountId")).strip() or safe_text(action.get("preferredAccountId") if action else "").strip(),
                preferred_account_ids=preferred_account_ids if isinstance(preferred_account_ids, list) else [],
                ready_only=False,
            )
            metadata_ready_count = len([item for item in parallel_candidates if safe_text(item.get("statusCode")).strip().lower() == "ready"])
            max_accounts = safe_int(routing_settings.get("parallelAccountMax"), 14)
            note_bits.append(
                f"계정 병렬 실행: preset={runtime_preset} · allocation {allocation_limit}/{max_accounts} · 실행 직전 전체 로그인 probe · metadata ready {metadata_ready_count}/{len(parallel_candidates)}"
            )
            local_requested_models = self.local_scout_models(
                routing_settings,
                runtime_preset if runtime_preset in {"question", "summary", "migration", "implementation", "lite", "balanced"} else "question",
                "qwen2.5-coder:1.5b",
            )
            inspected_models = self.inspect_local_models(local_requested_models)
            ready_models = [safe_text(item.get("name")).strip() for item in inspected_models if item.get("ready")]
            missing_models = [safe_text(item.get("name")).strip() for item in inspected_models if not item.get("ready")]
            if ready_models:
                note_bits.append("하이브리드 로컬 스카우트: " + ", ".join(ready_models))
            if missing_models:
                note_bits.append("준비 안 된 로컬 모델: " + ", ".join(missing_models))
        elif parallel_accounts and not classic_mode and safe_text(spec.get("kind")) == "freeagent":
            routing_settings = self.model_routing_settings(payload)
            simple_presets = set(routing_settings.get("simpleTaskLocalPresets", []))
            if runtime_preset in simple_presets and safe_bool(routing_settings.get("allowParallelLocalWorkers"), False):
                note_bits.append(f"단순 작업 로컬 병렬 우선: preset={runtime_preset}")
        if recommended_account:
            account_label = safe_text(recommended_account.get("label") or recommended_account.get("email") or recommended_account.get("accountId") or recommended_account.get("id"))
            account_type = self.account_type_code(recommended_account) or "unknown"
            status_code = safe_text(recommended_account.get("statusCode")) or "unknown"
            note_bits.append(f"{'현재 계정' if classic_mode else '자동 계정'}: {account_label} ({account_type}, {status_code})")
        if (
            parallel_accounts
            and
            not classic_mode
            and safe_text(spec.get("kind")) == "freeagent"
            and safe_text(spec.get("effective_cli")) == "freeagent"
            and safe_text(spec.get("effective_mode")) != "apply"
            and explicit_cli not in {"freeagent", "minimax"}
        ):
            routing_settings = self.model_routing_settings(payload)
            if safe_bool(routing_settings.get("allowParallelLocalWorkers"), False) and safe_int(routing_settings.get("parallelLocalWorkers"), 1) > 1:
                requested_scout_models = self.local_scout_models(
                    routing_settings,
                    runtime_preset,
                    safe_text(spec.get("effective_model")).strip(),
                )
                final_synthesizer = self.normalize_parallel_local_synthesizer_mode(routing_settings.get("parallelLocalFinalSynthesizer"))
                final_synthesizer_model = safe_text(routing_settings.get("parallelLocalFinalSynthesizerModel")).strip() or "qwen2.5-coder:7b"
                inspection_models = list(requested_scout_models)
                if final_synthesizer == "local-7b" and final_synthesizer_model not in inspection_models:
                    inspection_models.append(final_synthesizer_model)
                inspected_models = self.inspect_local_models(inspection_models)
                ready_models = [safe_text(item.get("name")).strip() for item in inspected_models if item.get("ready")]
                ready_models = [model for model in ready_models if model in requested_scout_models]
                missing_models = [safe_text(item.get("name")).strip() for item in inspected_models if not item.get("ready")]
                if len(ready_models) > 1:
                    note_bits.append("병렬 로컬 모델: " + ", ".join(ready_models))
                    note_bits.append(f"최종 합성: {final_synthesizer}")
                if missing_models:
                    note_bits.append("준비 안 된 모델: " + ", ".join(missing_models))
        return {
            "title": safe_text(spec.get("title")),
            "kind": safe_text(spec.get("kind")),
            "cwd": safe_text(spec.get("cwd")),
            "commandPreview": safe_text(spec.get("command_preview")),
            "effectivePrompt": effective_prompt,
            "promptChars": len(effective_prompt),
            "promptLines": effective_prompt.count("\n") + (1 if effective_prompt else 0),
            "estimatedTokens": self.estimate_prompt_tokens(effective_prompt),
            "note": " · ".join(note_bits),
            "message": "Preview ready" if effective_prompt else "No prompt content",
            "autoRuntimePreset": runtime_preset,
            "autoRuntimePresetLabel": "Classic" if classic_mode else self.runtime_preset_label(runtime_preset),
            "recommendedAccount": recommended_account or {},
            "routeNote": safe_text(spec.get("route_note")),
            "effectiveModel": safe_text(spec.get("effective_model")),
            "effectiveCli": safe_text(spec.get("effective_cli")),
            "localModelInspection": inspected_models if 'inspected_models' in locals() else [],
        }

    def resolve_action_workspace(self, action: dict[str, Any], default_workspace: dict[str, Any]) -> dict[str, Any]:
        override_id = safe_text(action.get("workspaceId"))
        if not override_id:
            return default_workspace
        workspace = self.workspaces.get(override_id)
        if workspace is None:
            raise ValueError(f"Unknown action workspace: {override_id}")
        return workspace

    def build_codex_spec(
        self,
        title: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        prompt: str,
        full_auto: bool,
        plan_step: str = "",
        runtime_options: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        cwd = safe_text(workspace["path"])
        sandbox = safe_text(workspace.get("defaultSandbox")) or "workspace-write"
        options = runtime_options or self.normalize_runtime_options({})
        effective_prompt = self.compose_prompt(
            prompt,
            options,
            session=session,
            plan_step=plan_step,
            include_session_context=True,
        )
        command = [
            self.codex_bin(),
            "exec",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-C",
            cwd,
            "--sandbox",
            sandbox,
        ]
        if full_auto:
            command.append("--full-auto")
        command.append(effective_prompt)
        return {
            "title": title,
            "kind": "codex",
            "cwd": cwd,
            "command": command,
            "command_preview": shlex.join(command),
            "effective_prompt": effective_prompt,
            "env_overrides": self.instance_process_env(),
            "effective_cli": "codex",
            "effective_model": "",
        }

    def build_minimax_codex_spec(
        self,
        title: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        prompt: str,
        full_auto: bool,
        plan_step: str = "",
        runtime_options: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        cwd = safe_text(workspace["path"])
        sandbox = safe_text(workspace.get("defaultSandbox")) or "workspace-write"
        options = runtime_options or self.normalize_runtime_options({})
        effective_prompt = self.compose_prompt(
            prompt,
            options,
            session=session,
            plan_step=plan_step,
            include_session_context=True,
        )
        wrapper = self.app_root / "bin" / "carbonet-minimax-codex"
        command = [
            str(wrapper),
            "exec",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-C",
            cwd,
            "--sandbox",
            sandbox,
        ]
        if full_auto:
            command.append("--full-auto")
        command.append(effective_prompt)
        return {
            "title": title,
            "kind": "codex",
            "cwd": cwd,
            "command": command,
            "command_preview": shlex.join(command),
            "effective_prompt": effective_prompt,
            "env_overrides": self.instance_process_env(),
            "effective_cli": "minimax-codex",
            "effective_model": "minimax2.7",
        }

    def build_freeagent_spec(
        self,
        title: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        prompt: str,
        freeagent_mode: str = "prompt",
        freeagent_targets: str = "",
        freeagent_test_command: str = "",
        provider_override: str = "",
        plan_step: str = "",
        runtime_options: dict[str, bool] | None = None,
        freeagent_model: str = "",
        model_routing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        freeagent_home = self.freeagent_home()
        if not freeagent_home.exists():
            raise ValueError(f"FreeAgent source not found: {freeagent_home}")
        wrapper = Path(self.freeagent_bin())
        if not wrapper.exists():
            raise ValueError(f"FreeAgent launcher not found: {wrapper}")
        mode = freeagent_mode if freeagent_mode in {"prompt", "plan", "ask", "explain", "graph", "apply"} else "prompt"
        options = runtime_options or self.normalize_runtime_options({})
        if mode == "apply" and self.is_question_like_prompt(prompt):
            raise ValueError("FreeAgent apply requires a concrete edit request. Use prompt or plan for questions.")
        if mode == "apply":
            effective_prompt = self.compose_prompt(
                prompt,
                options,
                session=session,
                plan_step=plan_step,
                include_session_context=True,
                apply_mode=True,
            )
        elif mode in {"prompt", "plan", "ask", "explain"}:
            effective_prompt = prompt if mode == "explain" else self.compose_prompt(
                prompt,
                options,
                session=session,
                plan_step=plan_step,
                include_session_context=False,
            )
        elif mode == "graph":
            effective_prompt = self.compose_prompt(
                prompt,
                options,
                session=session,
                plan_step=plan_step,
                include_session_context=True,
            )
        else:
            effective_prompt = self.compose_prompt(
                prompt,
                options,
                session=session,
                plan_step=plan_step,
                include_session_context=True,
            )
        command = [str(wrapper), mode]
        if mode == "explain":
            if freeagent_targets:
                command.extend(["--targets", freeagent_targets])
            else:
                command.extend(["--symbol", prompt])
        else:
            command.append(effective_prompt)
            if freeagent_targets:
                command.extend(["--targets", freeagent_targets])
            if mode == "apply":
                command.append("--yes")
                if freeagent_test_command:
                    command.extend(["--test-command", freeagent_test_command])
        # Model override via --model flag
        model_override = safe_text(freeagent_model).strip()
        if model_override:
            command.extend(["--model", model_override])
        env_overrides: dict[str, str] = dict(self.instance_process_env())
        if model_override:
            env_overrides["FREEAGENT_MODEL"] = model_override
        routing_settings = model_routing or self.model_routing_settings()
        if safe_bool(routing_settings.get("memorySafeSingleLocalModel"), True):
            env_overrides["CARBONET_SINGLE_LOCAL_MODEL"] = "1"
        if provider_override == "minimax":
            env_doc = read_key_values(self.freeagent_env_file())
            env_overrides.update({
                "FREEAGENT_PROVIDER": "minimax",
                "FREEAGENT_MODEL": env_doc.get("FREEAGENT_MINIMAX_MODEL", "minimax2.7"),
                "MINIMAX_BASE_URL": env_doc.get("MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1"),
                "MINIMAX_API_KEY": env_doc.get("MINIMAX_API_KEY", ""),
            })
        return {
            "title": f"{title} [{mode}]" + (f" ({model_override})" if model_override else ""),
            "kind": "freeagent",
            "cwd": safe_text(workspace["path"]),
            "command": command,
            "command_preview": shlex.join(command),
            "effective_prompt": effective_prompt,
            "env_overrides": env_overrides,
            "effective_cli": "minimax" if provider_override == "minimax" else "freeagent",
            "effective_model": env_overrides.get("FREEAGENT_MODEL", ""),
            "effective_mode": mode,
        }

    def _execute_job(self, instance_id: str, job_id: str, command: list[str], output_file: Path, env_overrides: dict[str, str] | None = None) -> None:
        self.set_request_instance(instance_id)
        with self.lock:
            job = self.jobs_store(instance_id)[job_id]
        if safe_text(job.execution_account_label):
            self.append_job_runtime_event(
                job_id,
                f"execution account: {safe_text(job.execution_account_label)} ({safe_text(job.execution_account_id) or 'active'})",
            )
        quota_markers = [
            "Quota exceeded",
            "429 Too Many Requests",
            "Rate limit reached",
            "You've hit your usage limit",
            "try again at",
        ]
        workspace_before = self.capture_workspace_file_state(job.cwd)
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                effective_command = list(command)
                if job.kind == "codex":
                    resumed_output = ""
                    if attempt > 0 and output_file.exists():
                        try:
                            resumed_output = output_file.read_text(encoding="utf-8")
                        except OSError:
                            resumed_output = ""
                    if resumed_output and effective_command:
                        effective_command[-1] = self.build_codex_resume_prompt(
                            effective_command[-1],
                            resumed_output,
                            attempt,
                        )
                        self.append_job_runtime_event(
                            job_id,
                            f"retry {attempt + 1}/{max_retries}: resuming from partial final output",
                        )
                    effective_command.extend(["-o", str(output_file)])
                    try:
                        output_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                env = os.environ.copy()
                if env_overrides:
                    env.update({key: value for key, value in env_overrides.items() if value})
                if job.kind == "freeagent":
                    self.enforce_single_local_model(instance_id, job_id, env_overrides)
                
                process = subprocess.Popen(
                    effective_command,
                    cwd=job.cwd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                    env=env,
                )
                with self.lock:
                    job.command_preview = shlex.join(effective_command)
                    job.process = process
                    job.status = "in_progress"

                with self.lock:
                    prior_output = safe_text(job.output)

                chunks: list[str] = []
                final_output_parts: list[str] = []
                final_output_lock = threading.Lock()
                tail_stop = threading.Event()

                def refresh_live_output() -> None:
                    current_attempt_output = collapse_duplicate_codex_stdout("".join(chunks))
                    combined = f"{prior_output.rstrip()}\n{current_attempt_output}".strip() if prior_output.strip() and current_attempt_output.strip() else (prior_output or current_attempt_output)
                    with final_output_lock:
                        final_stream = "".join(final_output_parts).strip()
                    live = combined
                    combined_tail = combined[-max(2000, len(final_stream) * 2 if final_stream else 0):]
                    if final_stream and final_stream not in combined_tail:
                        divider = "\n[Final Output Stream]\n"
                        live = f"{combined.rstrip()}{divider}{final_stream}\n" if combined.strip() else f"[Final Output Stream]\n{final_stream}\n"
                    with self.lock:
                        job.output = live[-120000:]

                def tail_final_output() -> None:
                    last_text = ""
                    while not tail_stop.is_set():
                        try:
                            if output_file.exists():
                                current = output_file.read_text(encoding="utf-8")
                                if current != last_text:
                                    with final_output_lock:
                                        final_output_parts.clear()
                                        final_output_parts.append(current)
                                    last_text = current
                                    refresh_live_output()
                        except OSError:
                            pass
                        tail_stop.wait(0.4)

                tail_thread: threading.Thread | None = None
                if job.kind == "codex":
                    tail_thread = threading.Thread(target=tail_final_output, daemon=True)
                    tail_thread.start()
                assert process.stdout is not None
                is_quota_error = False
                for line in process.stdout:
                    chunks.append(line)
                    # Detect quota exhaustion
                    if any(msg in line for msg in quota_markers):
                        is_quota_error = True
                    refresh_live_output()
                
                exit_code = process.wait()
                tail_stop.set()
                if tail_thread is not None:
                    tail_thread.join(timeout=1)
                refresh_live_output()
                
                # If quota/auth error detected or exit code suggests failure, try failover
                if is_quota_error or exit_code != 0:
                    output_text = "".join(chunks)
                    if any(msg in output_text for msg in quota_markers):
                        print(f"Quota error detected in job {job_id} (attempt {attempt+1}/{max_retries}). Switching account...")
                        login = self.login_status()
                        curr_acc = login.get("currentAccount", {})
                        current_slot_id = self.current_account_id()
                        
                        slots = self.list_account_slots()
                        current_slot = next(
                            (slot for slot in slots if safe_text(slot.get("id")) == current_slot_id),
                            None,
                        )
                        if current_slot is None:
                            curr_id = safe_text(curr_acc.get("accountId"))
                            current_slot = next(
                                (slot for slot in slots if safe_text(slot.get("accountId")) == curr_id),
                                None,
                            )
                            current_slot_id = safe_text(current_slot.get("id")) if current_slot else ""
                        derived_next_available_at = self.extract_retry_available_at(output_text)
                        quota_lines = self.extract_quota_message_lines(output_text)
                        if current_slot is not None:
                            update_doc: dict[str, Any] = {
                                "exhausted": True,
                                "lastQuotaMessage": self.summarize_text(output_text, 2000),
                                "lastQuotaDetectedAt": now_iso(),
                                "nextAvailableAt": derived_next_available_at or "",
                                "nextAvailableAtSource": "quota-output" if derived_next_available_at else "",
                            }
                            self.update_account_status(current_slot["id"], **update_doc)
                            self.append_job_runtime_event(
                                job_id,
                                f"quota detected on {safe_text(current_slot.get('label') or current_slot.get('email') or current_slot.get('id'))}"
                                + (f"; retry after {derived_next_available_at}" if derived_next_available_at else ""),
                                session_note=(
                                    f"Quota wait on {safe_text(current_slot.get('label') or current_slot.get('email') or current_slot.get('id'))}"
                                    + (f", retry after {derived_next_available_at}" if derived_next_available_at else "")
                                ),
                            )
                            for quota_line in quota_lines:
                                self.append_job_runtime_event(job_id, quota_line)
                        else:
                            self.append_job_runtime_event(
                                job_id,
                                "quota detected but the current slot could not be matched to saved account metadata",
                                session_note=f"Quota was detected during '{job.title}', but the active slot metadata could not be matched",
                            )
                            for quota_line in quota_lines:
                                self.append_job_runtime_event(job_id, quota_line)

                        probe_history: list[dict[str, Any]] = []
                        best_acc = self.activate_first_reusable_account(
                            excluded_ids={current_slot_id} if current_slot_id else None,
                            probe_history=probe_history,
                        )
                        if best_acc:
                            self.append_job_runtime_event(
                                job_id,
                                f"switching account {current_slot_id or '?'} -> {safe_text(best_acc.get('id'))} and retrying",
                                session_note=f"Auto-switched account {current_slot_id or '?'} -> {safe_text(best_acc.get('id'))} for '{job.title}'",
                            )
                            job.failover_history.append({
                                "at": now_iso(),
                                "reason": "quota_wait",
                                "fromAccountId": current_slot_id,
                                "toAccountId": safe_text(best_acc.get("id")),
                                "nextAvailableAt": derived_next_available_at,
                                "probes": probe_history,
                            })
                            with self.lock:
                                job.execution_account_id = safe_text(best_acc.get("id"))
                                job.execution_account_label = safe_text(best_acc.get("label") or best_acc.get("email") or best_acc.get("accountId"))
                            self.persist_job(job_id)
                            continue # Retry the loop
                        self.append_job_runtime_event(
                            job_id,
                            "quota detected but no reusable fallback account was available",
                            session_note=f"No reusable fallback account was available after quota wait during '{job.title}'",
                        )
                    else:
                        auth_status = self.detect_external_auth_status(output_text)
                        if auth_status in {"unauthorized", "login_expired"}:
                            login = self.login_status()
                            curr_acc = login.get("currentAccount", {})
                            current_slot_id = self.current_account_id()
                            slots = self.list_account_slots()
                            current_slot = next(
                                (slot for slot in slots if safe_text(slot.get("id")) == current_slot_id),
                                None,
                            )
                            if current_slot is None:
                                curr_id = safe_text(curr_acc.get("accountId"))
                                current_slot = next(
                                    (slot for slot in slots if safe_text(slot.get("accountId")) == curr_id),
                                    None,
                                )
                                current_slot_id = safe_text(current_slot.get("id")) if current_slot else ""
                            auth_label = safe_text(current_slot.get("label") or current_slot.get("email") or current_slot.get("id")) if current_slot else (current_slot_id or "?")
                            if current_slot is not None:
                                self.update_account_status(
                                    current_slot["id"],
                                    exhausted=False,
                                    nextAvailableAt="",
                                    nextAvailableAtSource="",
                                    lastAuthStatus="unauthorized" if auth_status == "unauthorized" else "expired",
                                    lastAuthMessage=self.summarize_text(output_text, 2000),
                                    lastAuthCheckedAt=now_iso(),
                                )
                            self.append_job_runtime_event(
                                job_id,
                                f"auth refresh failed on {auth_label}; re-login required",
                                session_note=f"Re-login required on {auth_label} during '{job.title}'",
                            )
                            probe_history = []
                            best_acc = self.activate_first_reusable_account(
                                excluded_ids={current_slot_id} if current_slot_id else None,
                                probe_history=probe_history,
                            )
                            if best_acc:
                                self.append_job_runtime_event(
                                    job_id,
                                    f"switching account {current_slot_id or '?'} -> {safe_text(best_acc.get('id'))} after auth failure",
                                    session_note=f"Auto-switched account {current_slot_id or '?'} -> {safe_text(best_acc.get('id'))} after auth failure for '{job.title}'",
                                )
                                job.failover_history.append({
                                    "at": now_iso(),
                                    "reason": auth_status,
                                    "fromAccountId": current_slot_id,
                                    "toAccountId": safe_text(best_acc.get("id")),
                                    "nextAvailableAt": "",
                                    "probes": probe_history,
                                })
                                with self.lock:
                                    job.execution_account_id = safe_text(best_acc.get("id"))
                                    job.execution_account_label = safe_text(best_acc.get("label") or best_acc.get("email") or best_acc.get("accountId"))
                                self.persist_job(job_id)
                                continue
                            self.append_job_runtime_event(
                                job_id,
                                "auth refresh failed and no reusable fallback account was available",
                                session_note=f"No reusable fallback account was available after auth failure during '{job.title}'",
                            )
                
                final_message = ""
                persisted_output = ""
                if output_file.exists():
                    persisted_output = output_file.read_text(encoding="utf-8").strip()
                    if persisted_output:
                        final_message = self.summarize_log_for_ui(persisted_output)
                elif job.kind != "codex" and chunks:
                    final_message = self.summarize_log_for_ui("".join(chunks))

                combined_output = collapse_duplicate_codex_stdout("".join(chunks))
                combined_tail = combined_output[-max(2000, len(persisted_output) * 2 if persisted_output else 0):]
                if job.kind == "codex" and persisted_output and persisted_output not in combined_tail:
                    divider = "\n[Final Output Stream]\n"
                    if "[Final Output Stream]" not in combined_output:
                        combined_output = f"{combined_output.rstrip()}{divider}{persisted_output}\n" if combined_output.strip() else f"[Final Output Stream]\n{persisted_output}\n"
                workspace_after = self.capture_workspace_file_state(job.cwd)
                workspace_diff = self.diff_workspace_file_state(workspace_before, workspace_after)
                changed_files = workspace_diff.get("changed", [])
                if changed_files:
                    change_bits = []
                    if workspace_diff.get("created"):
                        change_bits.append(f"created={', '.join(workspace_diff['created'][:8])}")
                    if workspace_diff.get("modified"):
                        change_bits.append(f"modified={', '.join(workspace_diff['modified'][:8])}")
                    if workspace_diff.get("deleted"):
                        change_bits.append(f"deleted={', '.join(workspace_diff['deleted'][:8])}")
                    self.append_job_runtime_event(job_id, "workspace changes | " + " | ".join(change_bits))
                
                with self.lock:
                    job.exit_code = exit_code
                    if combined_output:
                        job.output = combined_output[-120000:]
                    job.final_message = final_message # Now contains HTML colors and filtered high-signal lines
                    job.status = "succeeded" if exit_code == 0 else "failed"
                    job.ended_at = now_iso()
                break # Success or non-quota failure, exit retry loop
                
            except Exception as exc:
                if attempt < max_retries - 1:
                    print(f"Exception in job execution (attempt {attempt+1}): {exc}. Retrying...")
                    time.sleep(1)
                    continue
                with self.lock:
                    job.status = "failed"
                    job.error = str(exc)
                    job.ended_at = now_iso()
                    if not job.output:
                        job.output = str(exc)
                break
        
        try:
            self.persist_job(job_id)
            self.update_session_after_job(job)
        finally:
            self.clear_request_instance()

    def persist_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs_store().get(job_id)
            if job is None:
                for store in self.jobs_by_instance.values():
                    if job_id in store:
                        job = store[job_id]
                        break
            if job is None:
                raise KeyError(job_id)
            row = {
                "jobId": job.job_id,
                "title": job.title,
                "kind": job.kind,
                "instanceId": job.instance_id,
                "sessionId": job.session_id,
                "sessionTitle": job.session_title,
                "planStep": job.plan_step,
                "workspaceId": job.workspace_id,
                "workspaceLabel": job.workspace_label,
                "status": job.status,
                "startedAt": job.started_at,
                "endedAt": job.ended_at,
                "exitCode": job.exit_code,
                "commandPreview": job.command_preview,
            }
            snapshot = job.as_dict()
        with self.history_file_path(job.instance_id).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        with self.job_record_path(job.job_id, job.instance_id).open("w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "CarbonetCodexLauncher/0.1"

    @property
    def app(self) -> LauncherApp:
        return self.server.app  # type: ignore[attr-defined]

    def request_instance_id(self) -> str:
        parsed = urlparse(self.path)
        value = parse_qs(parsed.query).get("instance", [""])[0]
        return self.app.normalize_instance_id(value)

    def do_GET(self) -> None:
        self.app.set_request_instance(self.request_instance_id())
        try:
            parsed = urlparse(self.path)
            normalized_path = parsed.path.rstrip("/") or "/"
            if normalized_path in {"/", "/mypage/password"}:
                self.serve_static("index.html", "text/html; charset=utf-8")
                return
            if parsed.path.startswith("/static/"):
                self.serve_static(parsed.path.removeprefix("/static/"))
                return
            if parsed.path.startswith("/extension/"):
                self.serve_extension(parsed.path.removeprefix("/extension/"))
                return
            if parsed.path == "/api/bootstrap":
                self.write_json(HTTPStatus.OK, self.app.bootstrap())
                return
            if parsed.path == "/api/sessions":
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "items": self.app.list_sessions(),
                        "currentSessionId": self.app.current_session_id(),
                        "currentSession": self.app.current_session(),
                    },
                )
                return
            if parsed.path == "/api/jobs":
                session_id = parse_qs(parsed.query).get("sessionId", [""])[0] or None
                self.write_json(HTTPStatus.OK, {"items": self.app.list_jobs(session_id)})
                return
            if parsed.path == "/api/accounts":
                self.write_json(
                    HTTPStatus.OK,
                    {
                        "items": self.app.list_accounts(),
                        "currentAccountId": self.app.current_account_id(),
                        "currentAccount": self.app.current_account_summary(),
                    },
                )
                return
            if parsed.path == "/api/freeagent/models":
                config = self.app.freeagent_config()
                self.write_json(HTTPStatus.OK, {
                    "model": config.get("model", ""),
                    "provider": config.get("provider", ""),
                    "availableModels": config.get("availableModels", []),
                    "ollamaRunning": config.get("ollamaRunning", False),
                })
                return
            if parsed.path == "/api/freeagent/model-status":
                models = parse_qs(parsed.query).get("models", [""])[0]
                requested = [item.strip() for item in models.split(",") if item.strip()]
                self.write_json(HTTPStatus.OK, self.app.inspect_local_models_payload(requested))
                return
            if parsed.path == "/api/freeagent/loaded-models":
                models = parse_qs(parsed.query).get("models", [""])[0]
                requested = [item.strip() for item in models.split(",") if item.strip()]
                self.write_json(HTTPStatus.OK, self.app.inspect_local_models_payload(requested))
                return
            if parsed.path == "/api/browser/state":
                self.write_json(HTTPStatus.OK, self.app.browser_status())
                return
            if parsed.path == "/api/reference/roots":
                self.write_json(HTTPStatus.OK, {"items": self.app.list_roots("reference")})
                return
            if parsed.path == "/api/reference/projects":
                root_id = parse_qs(parsed.query).get("rootId", [""])[0] or None
                try:
                    self.write_json(HTTPStatus.OK, self.app.list_reference_projects(root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/system/pick-directory":
                title = parse_qs(parsed.query).get("title", ["Select folder"])[0]
                try:
                    self.write_json(HTTPStatus.OK, self.app.pick_directory(title))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/reference/tree":
                root_id = parse_qs(parsed.query).get("rootId", [""])[0] or None
                scope_path = parse_qs(parsed.query).get("path", [""])[0]
                try:
                    if scope_path:
                        self.write_json(HTTPStatus.OK, self.app.reference_subtree(scope_path, root_id))
                    else:
                        self.write_json(HTTPStatus.OK, self.app.reference_tree(root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/projects/tree":
                root_id = parse_qs(parsed.query).get("rootId", [""])[0] or None
                try:
                    self.write_json(HTTPStatus.OK, self.app.list_project_directories(root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/project/roots":
                self.write_json(HTTPStatus.OK, {"items": self.app.list_roots("project")})
                return
            if parsed.path == "/api/project/menus":
                project_path = parse_qs(parsed.query).get("projectPath", [""])[0]
                try:
                    self.write_json(HTTPStatus.OK, self.app.scan_project_menus(project_path))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/project-runtime/status":
                project_path = parse_qs(parsed.query).get("projectPath", [""])[0]
                try:
                    self.write_json(HTTPStatus.OK, self.app.project_runtime_status(project_path))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/project-assemblies":
                self.write_json(HTTPStatus.OK, self.app.project_assemblies())
                return
            if parsed.path == "/api/project-assembly/status":
                query = parse_qs(parsed.query)
                project_path = query.get("projectPath", [""])[0]
                project_id = query.get("projectId", [""])[0]
                self.write_json(HTTPStatus.OK, self.app.project_assembly_status(project_path=project_path, project_id=project_id))
                return
            if parsed.path == "/api/reference/meta":
                target_path = parse_qs(parsed.query).get("path", [""])[0]
                root_id = parse_qs(parsed.query).get("rootId", [""])[0] or None
                try:
                    self.write_json(HTTPStatus.OK, self.app.reference_file_info(target_path, root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/reference/file":
                target_path = parse_qs(parsed.query).get("path", [""])[0]
                root_id = parse_qs(parsed.query).get("rootId", [""])[0] or None
                try:
                    content_type, body = self.app.reference_file_bytes(target_path, root_id)
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/browser/page":
                target_url = parse_qs(parsed.query).get("url", [""])[0]
                try:
                    final_url, html = self.app.fetch_browser_page(target_url)
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                    return
                except Exception as exc:
                    self.write_json(HTTPStatus.BAD_GATEWAY, {"message": str(exc)})
                    return
                self.app.update_browser_state({"currentUrl": final_url})
                body = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/browser/fetch":
                target_url = parse_qs(parsed.query).get("url", [""])[0]
                try:
                    status, content_type, body = self.app.proxy_browser_request(target_url, method="GET")
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                    return
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.split("/")[-1]
                try:
                    self.write_json(HTTPStatus.OK, self.app.get_job(job_id))
                except KeyError:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": "Job not found"})
                return
            if parsed.path.endswith("/compare") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.compare_session(session_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": str(exc)})
                return
            if parsed.path.endswith("/family") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.session_family(session_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": str(exc)})
                return
            if parsed.path.startswith("/api/sessions/"):
                session_id = parsed.path.split("/")[-1]
                try:
                    self.write_json(HTTPStatus.OK, self.app.load_session(unquote(session_id)))
                except ValueError as exc:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": str(exc)})
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"message": "Not found"})
        finally:
            self.app.clear_request_instance()

    def do_HEAD(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/browser/fetch":
            target_url = parse_qs(parsed.query).get("url", [""])[0]
            try:
                status, content_type, body = self.app.proxy_browser_request(target_url, method="HEAD")
            except ValueError as exc:
                self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        self.app.set_request_instance(self.request_instance_id())
        try:
            parsed = urlparse(self.path)
            payload = self.read_body_json()
            if parsed.path == "/api/run":
                try:
                    self.write_json(HTTPStatus.OK, self.app.run_job(payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/prompt-preview":
                try:
                    self.write_json(HTTPStatus.OK, self.app.prompt_preview(payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/sessions":
                title = safe_text(payload.get("title")).strip() or "New Session"
                self.write_json(
                    HTTPStatus.OK,
                    self.app.create_session(
                        title,
                        safe_text(payload.get("workspaceId")).strip(),
                        safe_text(payload.get("projectPath")).strip(),
                    ),
                )
                return
            if parsed.path.endswith("/branch") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                title = safe_text(payload.get("title")).strip()
                try:
                    self.write_json(HTTPStatus.OK, self.app.create_branch_session(session_id, title))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/login-status":
                self.write_json(HTTPStatus.OK, self.app.login_status())
                return
            if parsed.path == "/api/freeagent/setup":
                try:
                    model = safe_text(payload.get("model")).strip() or "qwen3.5:cloud"
                    sudo_password = safe_text(payload.get("sudoPassword"))
                    self.write_json(HTTPStatus.OK, self.app.setup_freeagent(model, sudo_password=sudo_password))
                except (ValueError, subprocess.CalledProcessError) as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/freeagent/start":
                self.write_json(HTTPStatus.OK, self.app.start_freeagent_agent())
                return
            if parsed.path == "/api/freeagent/pull-model":
                try:
                    self.write_json(HTTPStatus.OK, self.app.pull_freeagent_model(payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/freeagent/model":
                model = safe_text(payload.get("model")).strip()
                try:
                    self.write_json(HTTPStatus.OK, self.app.change_freeagent_model(model))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/freeagent/preload-models":
                models = payload.get("models")
                if not isinstance(models, list):
                    models = []
                keep_alive = safe_text(payload.get("keepAlive")).strip() or "24h"
                self.write_json(HTTPStatus.OK, self.app.preload_local_models(models, keep_alive=keep_alive))
                return
            if parsed.path == "/api/freeagent/unload-models":
                models = payload.get("models")
                if not isinstance(models, list):
                    models = []
                self.write_json(HTTPStatus.OK, self.app.unload_local_models(models))
                return
            if parsed.path in {
                "/api/project-runtime/start",
                "/api/project-runtime/stop",
                "/api/project-runtime/restart",
                "/api/project-runtime/verify",
            }:
                action_name = parsed.path.rsplit("/", 1)[-1]
                try:
                    self.write_json(HTTPStatus.OK, self.app.run_project_runtime_action(payload, action_name))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/project-assemblies/upsert":
                try:
                    self.write_json(HTTPStatus.OK, self.app.upsert_project_assembly(payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.startswith("/api/project-assembly/"):
                action_name = parsed.path.rsplit("/", 1)[-1]
                if action_name in {
                    "buildCommon",
                    "installCommon",
                    "buildProject",
                    "buildAll",
                    "restart",
                    "verify",
                    "sqlBackup",
                    "physicalBackup",
                    "backupStatus",
                    "trafficStatus",
                    "trafficTail",
                }:
                    try:
                        self.write_json(HTTPStatus.OK, self.app.run_project_assembly_action(payload, action_name))
                    except ValueError as exc:
                        self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                    return
            if parsed.path == "/api/login/start":
                self.write_json(HTTPStatus.OK, self.app.start_device_login())
                return
            if parsed.path == "/api/logout":
                self.write_json(HTTPStatus.OK, self.app.logout())
                return
            if parsed.path == "/api/jobs/recover":
                self.write_json(HTTPStatus.OK, self.app.recover_jobs())
                return
            if parsed.path == "/api/browser/state":
                self.write_json(HTTPStatus.OK, self.app.update_browser_state(payload))
                return
            if parsed.path == "/api/browser/capture":
                self.write_json(HTTPStatus.OK, self.app.record_browser_capture(payload))
                return
            if parsed.path == "/api/browser/menu-snapshot":
                self.write_json(HTTPStatus.OK, self.app.update_browser_menu_snapshot(payload))
                return
            if parsed.path == "/api/browser/fetch":
                target_url = parse_qs(parsed.query).get("url", [""])[0]
                try:
                    status, content_type, body = self.app.proxy_browser_request(
                        target_url,
                        method=self.command,
                        body=self.read_body_bytes(),
                        headers={key: value for key, value in self.headers.items()},
                    )
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                    return
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/reference/roots":
                try:
                    self.write_json(
                        HTTPStatus.OK,
                        self.app.add_root(
                            "reference",
                            safe_text(payload.get("label")),
                            safe_text(payload.get("path")),
                        ),
                    )
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/project/roots":
                try:
                    self.write_json(
                        HTTPStatus.OK,
                        self.app.add_root(
                            "project",
                            safe_text(payload.get("label")),
                            safe_text(payload.get("path")),
                        ),
                    )
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/delete") and parsed.path.startswith("/api/reference/roots/"):
                root_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.delete_root("reference", root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/delete") and parsed.path.startswith("/api/project/roots/"):
                root_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.delete_root("project", root_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/accounts/save-current":
                label = safe_text(payload.get("label")).strip()
                if not label:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": "label is required"})
                    return
                try:
                    self.write_json(HTTPStatus.OK, self.app.save_current_account(label))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/update") and parsed.path.startswith("/api/accounts/"):
                account_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.update_account_settings(account_id, payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/activate") and parsed.path.startswith("/api/accounts/"):
                account_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.activate_account(account_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/routing") and parsed.path.startswith("/api/actions/"):
                action_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.update_action_routing(action_id, payload))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/activate") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.activate_session(session_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/update") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(
                        HTTPStatus.OK,
                        self.app.update_session(
                            session_id,
                            title=payload.get("title"),
                            notes=payload.get("notes"),
                            plan=payload.get("plan") if isinstance(payload.get("plan"), list) else None,
                            workspace_id=payload.get("workspaceId"),
                            project_path=payload.get("projectPath"),
                        ),
                    )
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/delete") and parsed.path.startswith("/api/sessions/"):
                session_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.delete_session(session_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/delete") and parsed.path.startswith("/api/accounts/"):
                account_id = unquote(parsed.path.split("/")[-2])
                try:
                    self.write_json(HTTPStatus.OK, self.app.delete_account(account_id))
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/delete") and parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.split("/")[-2]
                try:
                    self.write_json(HTTPStatus.OK, self.app.delete_job(job_id))
                except KeyError:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": "Job not found"})
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path == "/api/jobs/clear":
                try:
                    self.write_json(HTTPStatus.OK, self.app.clear_jobs())
                except ValueError as exc:
                    self.write_json(HTTPStatus.BAD_REQUEST, {"message": str(exc)})
                return
            if parsed.path.endswith("/cancel") and parsed.path.startswith("/api/jobs/"):
                job_id = parsed.path.split("/")[-2]
                try:
                    self.write_json(HTTPStatus.OK, self.app.cancel_job(job_id))
                except KeyError:
                    self.write_json(HTTPStatus.NOT_FOUND, {"message": "Job not found"})
                return
            self.write_json(HTTPStatus.NOT_FOUND, {"message": "Not found"})
        finally:
            self.app.clear_request_instance()

    def read_body_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def read_body_bytes(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def serve_static(self, relative_path: str, content_type: str | None = None) -> None:
        target = (self.app.static_root / relative_path).resolve()
        if not str(target).startswith(str(self.app.static_root.resolve())) or not target.exists():
            self.write_json(HTTPStatus.NOT_FOUND, {"message": "Asset not found"})
            return
        if content_type is None:
            if target.suffix == ".css":
                content_type = "text/css; charset=utf-8"
            elif target.suffix == ".js":
                content_type = "application/javascript; charset=utf-8"
            else:
                content_type = "text/plain; charset=utf-8"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def serve_extension(self, relative_path: str) -> None:
        target = (self.app.extension_root / relative_path).resolve()
        if not str(target).startswith(str(self.app.extension_root.resolve())) or not target.exists():
            self.write_json(HTTPStatus.NOT_FOUND, {"message": "Extension asset not found"})
            return
        if target.suffix == ".json":
            content_type = "application/json; charset=utf-8"
        elif target.suffix == ".js":
            content_type = "application/javascript; charset=utf-8"
        elif target.suffix == ".html":
            content_type = "text/html; charset=utf-8"
        else:
            content_type = "text/plain; charset=utf-8"
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", required=True)
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve")
    serve_parser.add_argument("--host", default="localhost")
    serve_parser.add_argument("--port", type=int, default=43110)

    scan_parser = subparsers.add_parser("scan-accounts")
    scan_parser.add_argument("--instance", default="default")

    ingest_parser = subparsers.add_parser("ingest-codex-output")
    ingest_parser.add_argument("--instance", default="default")
    ingest_parser.add_argument("--exit-code", type=int, default=0)
    ingest_parser.add_argument("--output-file", default="")

    args = parser.parse_args()
    app = LauncherApp(Path(args.app_root).resolve())

    if args.command in {None, "serve"}:
        host = getattr(args, "host", "localhost")
        port = getattr(args, "port", 43110)
        server = ThreadingHTTPServer((host, port), LauncherHandler)
        server.app = app  # type: ignore[attr-defined]
        print(f"Carbonet Codex Launcher listening on http://{host}:{port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return

    if args.command == "scan-accounts":
        app.set_request_instance(app.normalize_instance_id(args.instance))
        try:
            print(json.dumps(app.scan_all_accounts(), ensure_ascii=False))
        finally:
            app.clear_request_instance()
        return

    if args.command == "ingest-codex-output":
        text = ""
        if args.output_file:
            text = Path(args.output_file).read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()
        print(json.dumps(app.ingest_codex_output(text, exit_code=args.exit_code, instance_id=args.instance), ensure_ascii=False))
        return


if __name__ == "__main__":
    main()
