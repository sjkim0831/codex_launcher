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
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import mimetypes
import ast


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def safe_text(value: Any) -> str:
    return "" if value is None else str(value)


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "jobId": self.job_id,
            "title": self.title,
            "kind": self.kind,
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
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.accounts_root.mkdir(parents=True, exist_ok=True)
        self.sessions_root.mkdir(parents=True, exist_ok=True)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.workspaces_doc = read_json(self.config_root / "workspaces.json")
        self.actions_doc = read_json(self.config_root / "actions.json")
        self.workspaces = {
            item["id"]: item
            for item in self.workspaces_doc.get("workspaces", [])
        }
        self.actions = {
            item["id"]: item
            for item in self.actions_doc.get("actions", [])
        }
        self.jobs: dict[str, JobRecord] = {}
        self.login_flow: dict[str, Any] = {}
        self.browser_state: dict[str, Any] = {
            "currentUrl": "",
            "currentTitle": "",
            "lastSeenAt": "",
            "lastCapture": None,
            "menuSnapshot": {},
        }
        self.source_roots = self.load_source_roots()
        self.ensure_default_session()
        self.load_persisted_jobs()

    def bootstrap(self) -> dict[str, Any]:
        login = self.login_status()
        current_session = self.current_session()
        return {
            "defaultWorkspaceId": self.workspaces_doc.get("defaultWorkspaceId", ""),
            "workspaces": self.workspaces_doc.get("workspaces", []),
            "actions": self.actions_doc.get("actions", []),
            "codexVersion": self.codex_version(),
            "loginReady": login.get("loggedIn", False),
            "accounts": self.list_accounts(),
            "currentAccountId": self.current_account_id(),
            "runtimeRoot": str(Path.cwd()),
            "codexHome": str(self.codex_home()),
            "cliOptions": [
                {"id": "codex", "label": "Codex", "description": "OpenAI Codex CLI"},
                {"id": "freeagent", "label": "FreeAgent", "description": "Vendored FreeAgent Ultra"},
                {"id": "minimax", "label": "MiniMax 2.7", "description": "FreeAgent runtime with MiniMax provider"},
                {"id": "minimax-codex", "label": "MiniMax Codex Compat", "description": "Codex-like exec wrapper backed by MiniMax"},
            ],
            "freeagent": self.freeagent_config(),
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
        return self.sessions_root / session_id / "session.json"

    def job_record_path(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}.json"

    def legacy_output_file(self, job_id: str) -> Path:
        return self.jobs_root / f"{job_id}-final.txt"

    def recover_legacy_job_output(self, job_id: str, command_preview: str) -> tuple[str, str]:
        output_file = self.legacy_output_file(job_id)
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
        if self.current_session_file.exists():
            session_id = self.current_session_file.read_text(encoding="utf-8").strip()
            if session_id and self.session_path(session_id).exists():
                return session_id
        sessions = self.list_sessions()
        if sessions:
            session_id = safe_text(sessions[0].get("id"))
            if session_id:
                self.current_session_file.write_text(session_id, encoding="utf-8")
                return session_id
        session = self.save_session(self.create_session_doc("Default Session"))
        self.current_session_file.write_text(session["id"], encoding="utf-8")
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

    def load_persisted_jobs(self) -> None:
        loaded_ids: set[str] = set()
        for path in sorted(self.jobs_root.glob("*.json")):
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
            )
            if job.job_id:
                self.jobs[job.job_id] = job
                loaded_ids.add(job.job_id)
        if not self.history_file.exists():
            return
        legacy_session = self.ensure_legacy_session()
        for raw in self.history_file.read_text(encoding="utf-8").splitlines():
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
            )
            recovered_output, recovered_file = self.recover_legacy_job_output(job_id, job.command_preview)
            job.final_message = recovered_output
            job.output = recovered_output
            job.output_file = recovered_file
            self.jobs[job.job_id] = job
            loaded_ids.add(job.job_id)

    def ensure_default_session(self) -> None:
        self.current_session_id()

    def list_sessions(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        active_id = ""
        if self.current_session_file.exists():
            active_id = self.current_session_file.read_text(encoding="utf-8").strip()
        for session_path in sorted(self.sessions_root.glob("*/session.json")):
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
        self.current_session_file.write_text(session["id"], encoding="utf-8")
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
        self.current_session_file.write_text(session["id"], encoding="utf-8")
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
        self.current_session_file.write_text(session["id"], encoding="utf-8")
        return {
            "session": session,
            "items": self.list_sessions(),
            "currentSessionId": session["id"],
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
        self.current_session_file.write_text(session["id"], encoding="utf-8")
        return session

    def summarize_text(self, text: str, limit: int = 280) -> str:
        collapsed = re.sub(r"\s+", " ", safe_text(text)).strip()
        if len(collapsed) <= limit:
            return collapsed
        return collapsed[: limit - 3].rstrip() + "..."

    def summarize_job_message(self, text: str, limit: int = 220) -> str:
        collapsed = self.summarize_text(text, limit * 3)
        lowered = collapsed.lower()
        if "no such command 'prompt'" in lowered:
            return "freeagent prompt command was unavailable in that run"
        if "usage: python -m freeagent.cli" in lowered:
            return "freeagent cli usage error"
        if any(marker in collapsed for marker in ("╭", "│", "children:[", "md:grid-cols", "export{")):
            return "verbose tool output omitted"
        return self.summarize_text(collapsed, limit)

    def refresh_session_summary(self, session_doc: dict[str, Any]) -> None:
        recent_jobs = session_doc.get("recentJobs", [])
        lines: list[str] = []
        notes = self.summarize_text(safe_text(session_doc.get("notes")), 220)
        if notes:
            lines.append(f"Notes: {notes}")
        plan_items = session_doc.get("plan", [])
        if plan_items:
            compact = ", ".join(
                f"{safe_text(item.get('step'))} [{safe_text(item.get('status')) or 'pending'}]"
                for item in plan_items[:5]
                if safe_text(item.get("step")).strip()
            )
            if compact:
                lines.append(f"Plan: {self.summarize_text(compact, 240)}")
        for item in recent_jobs[-6:]:
            summary = self.summarize_job_message(safe_text(item.get("finalMessage")) or safe_text(item.get("commandPreview")), 220)
            status = safe_text(item.get("status")) or "unknown"
            title = safe_text(item.get("title")) or safe_text(item.get("jobId"))
            lines.append(f"- {title} [{status}]: {summary}")
        session_doc["summary"] = "\n".join(lines)

    def append_session_note(self, session: dict[str, Any], note: str) -> None:
        text = safe_text(note).strip()
        if not text:
            return
        existing = safe_text(session.get("notes")).strip()
        if text in existing:
            return
        if existing:
            session["notes"] = f"{existing}\n{text}"
        else:
            session["notes"] = text

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
                "finalMessage": self.summarize_job_message(job.final_message or job.output, 320),
            }
        )
        session["recentJobs"] = recent_jobs[-8:]
        session["lastJobId"] = job.job_id
        self.auto_update_session_plan(session, job)
        self.refresh_session_summary(session)
        self.save_session(session)

    def build_session_context(self, session: dict[str, Any]) -> str:
        lines = [
            "[Session Context]",
            f"Session: {safe_text(session.get('title'))}",
        ]
        if session.get("workspaceId"):
            lines.append(f"Workspace: {safe_text(session.get('workspaceId'))}")
        if session.get("projectPath"):
            lines.append(f"Project Path: {safe_text(session.get('projectPath'))}")
        notes = safe_text(session.get("notes")).strip()
        if notes:
            lines.append("Session Notes:")
            lines.append(notes)
        plan_items = session.get("plan", [])
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
            lines.append(summary)
        recent_jobs = session.get("recentJobs", [])
        if recent_jobs:
            lines.append("Recent Outputs:")
            for item in recent_jobs[-3:]:
                lines.append(
                    f"- {safe_text(item.get('title'))}: {self.summarize_job_message(safe_text(item.get('finalMessage')), 160)}"
                )
        lines.extend(
            [
                "",
                "Use this session context as prior work. Continue from it unless the new request clearly overrides it.",
                "",
            ]
        )
        return "\n".join(lines)

    def build_apply_context(self, session: dict[str, Any]) -> str:
        lines = [
            "[Session Context]",
            f"Session: {safe_text(session.get('title'))}",
        ]
        if session.get("workspaceId"):
            lines.append(f"Workspace: {safe_text(session.get('workspaceId'))}")
        summary = safe_text(session.get("summary")).strip()
        if summary:
            lines.append("Recent Decisions:")
            lines.append(self.summarize_text(summary, 240))
        recent_jobs = session.get("recentJobs", [])
        if recent_jobs:
            lines.append("Recent Outputs:")
            for item in recent_jobs[-1:]:
                title = safe_text(item.get("title")).strip()
                final_message = self.summarize_text(safe_text(item.get("finalMessage")), 160)
                if title or final_message:
                    lines.append(f"- {title}: {final_message}")
        lines.extend(
            [
                "",
                "Use only the relevant prior context. Ignore prior logs that do not directly help with the current edit request.",
                "",
            ]
        )
        return "\n".join(lines)

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

    def codex_home(self) -> Path:
        return Path(os.environ.get("CARBONET_CODEX_HOME", str(Path.home() / ".codex")))

    def auth_file(self) -> Path:
        return self.codex_home() / "auth.json"

    def config_file(self) -> Path:
        return self.codex_home() / "config.toml"

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

    def freeagent_write_env(self, model: str = "qwen2.5-coder:7b") -> None:
        self.freeagent_home().mkdir(parents=True, exist_ok=True)
        current = read_key_values(self.freeagent_env_file())
        if not current and self.freeagent_legacy_env_file().exists():
            current = read_key_values(self.freeagent_legacy_env_file())
        merged = {
            "FREEAGENT_PROVIDER": current.get("FREEAGENT_PROVIDER", "ollama"),
            "FREEAGENT_MODEL": current.get("FREEAGENT_MODEL", model),
            "OLLAMA_HOST": current.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            "OLLAMA_TIMEOUT_SEC": current.get("OLLAMA_TIMEOUT_SEC", "90"),
            "OLLAMA_NUM_PREDICT": current.get("OLLAMA_NUM_PREDICT", "256"),
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

    def freeagent_setup_runtime(self, model: str = "qwen2.5-coder:7b", sudo_password: str = "") -> list[str]:
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
        ollama_model = env_doc.get("FREEAGENT_MODEL", "qwen2.5-coder:7b")
        minimax_model = env_doc.get("FREEAGENT_MINIMAX_MODEL", "minimax2.7")
        ollama_running = self.ollama_running(host)
        tags = self.ollama_tags(host) if ollama_running else {"models": []}
        ollama_installed = shutil.which("ollama") is not None
        minimax_key_ready = bool(env_doc.get("MINIMAX_API_KEY", "") or env_doc.get("OPENAI_API_KEY", ""))
        runtime_ready = self.freeagent_python().exists()
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

    def login_status(self) -> dict[str, Any]:
        try:
            completed = subprocess.run(
                [self.codex_bin(), "login", "status"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as exc:
            return {"loggedIn": False, "message": str(exc)}
        text = (completed.stdout or completed.stderr or "").strip()
        return {
            "loggedIn": completed.returncode == 0 and "Logged in" in text,
            "message": text,
            "currentAccount": self.current_account_summary(),
        }

    def current_account_summary(self) -> dict[str, Any]:
        auth_path = self.auth_file()
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
        fingerprint = self.auth_fingerprint(auth_doc)
        return {
            "accountId": account_id,
            "name": name,
            "email": email,
            "authMode": safe_text(auth_doc.get("auth_mode")),
            "fingerprint": fingerprint,
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

    def list_accounts(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        current_id = self.current_account_id()
        for metadata_path in sorted(self.accounts_root.glob("*/metadata.json")):
            try:
                metadata = read_json(metadata_path)
            except Exception:
                continue
            metadata["isActive"] = metadata.get("id") == current_id
            items.append(metadata)
        items.sort(key=lambda item: safe_text(item.get("updatedAt")), reverse=True)
        return items

    def current_account_id(self) -> str:
        current = self.current_account_summary()
        fingerprint = safe_text(current.get("fingerprint"))
        if not fingerprint:
            return ""
        for metadata_path in self.accounts_root.glob("*/metadata.json"):
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
        slot_dir = self.accounts_root / slot_id
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
        slot_dir = self.accounts_root / account_id
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

    def start_device_login(self) -> dict[str, Any]:
        process = self.login_flow.get("process")
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            return self.login_flow_payload()

        process = subprocess.Popen(
            [self.codex_bin(), "login", "--device-auth"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.login_flow = {
            "process": process,
            "startedAt": now_iso(),
            "verificationUri": "",
            "userCode": "",
            "output": "",
        }
        if process.stdout is not None:
            os.set_blocking(process.stdout.fileno(), False)

        deadline = time.time() + 10
        while time.time() < deadline:
            self.capture_device_login_output()
            if self.login_flow.get("verificationUri") and self.login_flow.get("userCode"):
                break
            if process.poll() is not None:
                break
            time.sleep(0.1)
        return self.login_flow_payload()

    def capture_device_login_output(self) -> None:
        process = self.login_flow.get("process")
        if not isinstance(process, subprocess.Popen) or process.stdout is None:
            return
        try:
            chunk = os.read(process.stdout.fileno(), 4096).decode("utf-8", errors="replace")
        except BlockingIOError:
            return
        if not chunk:
            return
        self.login_flow["output"] = safe_text(self.login_flow.get("output")) + chunk
        output = strip_ansi(safe_text(self.login_flow.get("output")))
        if not self.login_flow.get("verificationUri"):
            match = re.search(r"https://auth\.openai\.com/\S+", output)
            if match:
                self.login_flow["verificationUri"] = match.group(0)
        if not self.login_flow.get("userCode"):
            match = re.search(r"\b[A-Z0-9]{4,5}-[A-Z0-9]{4,5}\b", output)
            if match:
                self.login_flow["userCode"] = match.group(0)

    def login_flow_payload(self) -> dict[str, Any]:
        self.capture_device_login_output()
        process = self.login_flow.get("process")
        return {
            "started": bool(process),
            "running": isinstance(process, subprocess.Popen) and process.poll() is None,
            "verificationUri": safe_text(self.login_flow.get("verificationUri")) or "https://auth.openai.com/codex/device",
            "userCode": safe_text(self.login_flow.get("userCode")),
            "startedAt": safe_text(self.login_flow.get("startedAt")),
            "output": safe_text(self.login_flow.get("output")),
        }

    def logout(self) -> dict[str, Any]:
        process = self.login_flow.get("process")
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            process.terminate()
        self.login_flow = {}
        completed = subprocess.run(
            [self.codex_bin(), "logout"],
            capture_output=True,
            text=True,
            check=False,
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

    def load_source_roots(self) -> dict[str, Any]:
        defaults = {
            "reference": [],
            "project": [],
        }
        if not self.source_roots_file.exists():
            self.source_roots_file.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
            return defaults
        try:
            doc = read_json(self.source_roots_file)
        except Exception:
            self.source_roots_file.write_text(json.dumps(defaults, ensure_ascii=False, indent=2), encoding="utf-8")
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
        self.source_roots_file.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
        return doc

    def save_source_roots(self) -> None:
        self.source_roots_file.write_text(
            json.dumps(self.source_roots, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_roots(self, kind: str) -> list[dict[str, Any]]:
        items = []
        for item in self.source_roots.get(kind, []):
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
        for item in self.source_roots.get(kind, []):
            if str(Path(safe_text(item.get("path"))).resolve()) == str(path):
                raise ValueError(f"Already registered: {path}")
        entry = {
            "id": uuid.uuid4().hex[:12],
            "label": label.strip(),
            "path": str(path),
        }
        self.source_roots.setdefault(kind, []).append(entry)
        self.save_source_roots()
        return {
            "saved": True,
            "item": entry,
            "items": self.list_roots(kind),
        }

    def delete_root(self, kind: str, root_id: str) -> dict[str, Any]:
        items = self.source_roots.get(kind, [])
        if len(items) <= 1:
            raise ValueError(f"At least one {kind} root must remain.")
        next_items = [item for item in items if safe_text(item.get("id")) != root_id]
        if len(next_items) == len(items):
            raise ValueError(f"Unknown {kind} root: {root_id}")
        self.source_roots[kind] = next_items
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
            items = list(self.jobs.values())
            if session_id:
                items = [item for item in items if item.session_id == session_id]
            items = sorted(items, key=lambda item: item.started_at, reverse=True)
            return [item.as_dict() for item in items]

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return job.as_dict()

    def cancel_job(self, job_id: str) -> dict[str, Any]:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            if job.process and job.status == "running":
                job.process.terminate()
        return self.get_job(job_id)

    def setup_freeagent(self, model: str = "qwen2.5-coder:7b", sudo_password: str = "") -> dict[str, Any]:
        messages = self.freeagent_setup_runtime(model=model, sudo_password=sudo_password)
        return {
            "ok": True,
            "message": "; ".join(messages),
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
        model = safe_text(payload.get("model")).strip() or self.freeagent_config().get("model", "qwen2.5-coder:7b")
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
        )

    def run_job(self, payload: dict[str, Any]) -> dict[str, Any]:
        workspace = self.resolve_workspace(payload)
        session = self.resolve_session(payload, workspace)
        spec = self.build_spec(payload, workspace, session)
        return self.enqueue_job_spec(
            title=spec["title"],
            kind=spec["kind"],
            cwd=spec["cwd"],
            command=spec["command"],
            command_preview=spec["command_preview"],
            workspace=workspace,
            session=session,
            plan_step=safe_text(payload.get("planStep")).strip(),
            env_overrides=spec.get("env_overrides"),
        )

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
    ) -> dict[str, Any]:
        job_id = uuid.uuid4().hex[:12]
        output_file = self.jobs_root / f"{job_id}-final.txt"
        job = JobRecord(
            job_id=job_id,
            title=title,
            kind=kind,
            session_id=safe_text(session.get("id")),
            session_title=safe_text(session.get("title")),
            plan_step=plan_step,
            workspace_id=workspace["id"],
            workspace_label=workspace["label"],
            cwd=cwd,
            command_preview=command_preview,
            output_file=str(output_file),
        )
        with self.lock:
            self.jobs[job_id] = job
        thread = threading.Thread(
            target=self._execute_job,
            args=(job_id, command, output_file, env_overrides),
            daemon=True,
        )
        thread.start()
        return job.as_dict()

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
        if mode == "assistant_custom":
            prompt = safe_text(payload.get("prompt")).strip()
            if not prompt:
                raise ValueError("Prompt is required.")
            cli_id = safe_text(payload.get("cli")) or "codex"
            if cli_id == "minimax-codex":
                return self.build_minimax_codex_spec(
                    title="Custom MiniMax Codex Prompt",
                    workspace=workspace,
                    session=session,
                    prompt=prompt,
                    full_auto=True,
                )
            if cli_id in {"freeagent", "minimax"}:
                return self.build_freeagent_spec(
                    title="Custom MiniMax Prompt" if cli_id == "minimax" else "Custom FreeAgent Prompt",
                    workspace=workspace,
                    session=session,
                    prompt=prompt,
                    freeagent_mode=safe_text(payload.get("freeagentMode")) or "prompt",
                    freeagent_targets=safe_text(payload.get("freeagentTargets")).strip(),
                    freeagent_test_command=safe_text(payload.get("freeagentTestCommand")).strip(),
                    provider_override="minimax" if cli_id == "minimax" else "",
                )
            return self.build_codex_spec(
                title="Custom Codex Prompt",
                workspace=workspace,
                session=session,
                prompt=prompt,
                full_auto=True,
            )
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

        action_id = safe_text(payload.get("actionId"))
        action = self.actions.get(action_id)
        if action is None:
            raise ValueError("Action is required.")

        if safe_text(action.get("kind")) == "codex":
            extra_input = safe_text(payload.get("extraInput")).strip()
            prompt = safe_text(action.get("promptTemplate")).strip()
            if extra_input:
                prompt = f"{prompt}\n\n추가 입력:\n{extra_input}"
            return self.build_codex_spec(
                title=safe_text(action.get("label")) or action_id,
                workspace=self.resolve_action_workspace(action, workspace),
                session=session,
                prompt=prompt,
                full_auto=bool(action.get("fullAuto", True)),
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
    ) -> dict[str, Any]:
        cwd = safe_text(workspace["path"])
        sandbox = safe_text(workspace.get("defaultSandbox")) or "workspace-write"
        effective_prompt = f"{self.build_session_context(session)}{prompt}"
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
        }

    def build_minimax_codex_spec(
        self,
        title: str,
        workspace: dict[str, Any],
        session: dict[str, Any],
        prompt: str,
        full_auto: bool,
    ) -> dict[str, Any]:
        cwd = safe_text(workspace["path"])
        sandbox = safe_text(workspace.get("defaultSandbox")) or "workspace-write"
        effective_prompt = f"{self.build_session_context(session)}{prompt}"
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
    ) -> dict[str, Any]:
        freeagent_home = self.freeagent_home()
        if not freeagent_home.exists():
            raise ValueError(f"FreeAgent source not found: {freeagent_home}")
        wrapper = Path(self.freeagent_bin())
        if not wrapper.exists():
            raise ValueError(f"FreeAgent launcher not found: {wrapper}")
        mode = freeagent_mode if freeagent_mode in {"prompt", "plan", "ask", "explain", "apply"} else "prompt"
        if mode == "apply" and self.is_question_like_prompt(prompt):
            raise ValueError("FreeAgent apply requires a concrete edit request. Use prompt or plan for questions.")
        if mode == "apply":
            effective_prompt = f"{self.build_apply_context(session)}{prompt}"
        elif mode in {"prompt", "plan", "ask", "explain"}:
            effective_prompt = prompt
        else:
            effective_prompt = f"{self.build_session_context(session)}{prompt}"
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
        env_overrides: dict[str, str] = {}
        if provider_override == "minimax":
            env_doc = read_key_values(self.freeagent_env_file())
            env_overrides = {
                "FREEAGENT_PROVIDER": "minimax",
                "FREEAGENT_MODEL": env_doc.get("FREEAGENT_MINIMAX_MODEL", "minimax2.7"),
                "MINIMAX_BASE_URL": env_doc.get("MINIMAX_BASE_URL", "https://api.minimaxi.chat/v1"),
                "MINIMAX_API_KEY": env_doc.get("MINIMAX_API_KEY", ""),
            }
        return {
            "title": f"{title} [{mode}]",
            "kind": "freeagent",
            "cwd": safe_text(workspace["path"]),
            "command": command,
            "command_preview": shlex.join(command),
            "env_overrides": env_overrides,
        }

    def _execute_job(self, job_id: str, command: list[str], output_file: Path, env_overrides: dict[str, str] | None = None) -> None:
        with self.lock:
            job = self.jobs[job_id]
        try:
            effective_command = list(command)
            if job.kind == "codex":
                effective_command.extend(["-o", str(output_file)])
            env = os.environ.copy()
            if env_overrides:
                env.update({key: value for key, value in env_overrides.items() if value})
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
            chunks: list[str] = []
            assert process.stdout is not None
            for line in process.stdout:
                chunks.append(line)
                with self.lock:
                    job.output = "".join(chunks)[-120000:]
            exit_code = process.wait()
            final_message = ""
            if output_file.exists():
                final_message = output_file.read_text(encoding="utf-8").strip()
            elif chunks:
                final_message = "".join(chunks)[-8000:]
            with self.lock:
                job.exit_code = exit_code
                job.final_message = final_message
                job.status = "succeeded" if exit_code == 0 else "failed"
                job.ended_at = now_iso()
        except Exception as exc:
            with self.lock:
                job.status = "failed"
                job.error = str(exc)
                job.ended_at = now_iso()
                if not job.output:
                    job.output = str(exc)
        finally:
            self.persist_job(job_id)
            self.update_session_after_job(job)

    def persist_job(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs[job_id]
            row = {
                "jobId": job.job_id,
                "title": job.title,
                "kind": job.kind,
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
        with self.history_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        with self.job_record_path(job.job_id).open("w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)


class LauncherHandler(BaseHTTPRequestHandler):
    server_version = "CarbonetCodexLauncher/0.1"

    @property
    def app(self) -> LauncherApp:
        return self.server.app  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
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
        parsed = urlparse(self.path)
        payload = self.read_body_json()
        if parsed.path == "/api/run":
            try:
                self.write_json(HTTPStatus.OK, self.app.run_job(payload))
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
                model = safe_text(payload.get("model")).strip() or "qwen2.5-coder:7b"
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
        if parsed.path == "/api/login/start":
            self.write_json(HTTPStatus.OK, self.app.start_device_login())
            return
        if parsed.path == "/api/logout":
            self.write_json(HTTPStatus.OK, self.app.logout())
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
        if parsed.path.endswith("/activate") and parsed.path.startswith("/api/accounts/"):
            account_id = unquote(parsed.path.split("/")[-2])
            try:
                self.write_json(HTTPStatus.OK, self.app.activate_account(account_id))
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
        if parsed.path.endswith("/cancel") and parsed.path.startswith("/api/jobs/"):
            job_id = parsed.path.split("/")[-2]
            try:
                self.write_json(HTTPStatus.OK, self.app.cancel_job(job_id))
            except KeyError:
                self.write_json(HTTPStatus.NOT_FOUND, {"message": "Job not found"})
            return
        self.write_json(HTTPStatus.NOT_FOUND, {"message": "Not found"})

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
        self.end_headers()
        self.wfile.write(body)

    def write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-root", required=True)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=43110)
    args = parser.parse_args()

    app = LauncherApp(Path(args.app_root).resolve())
    server = ThreadingHTTPServer((args.host, args.port), LauncherHandler)
    server.app = app  # type: ignore[attr-defined]
    print(f"Carbonet Codex Launcher listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
