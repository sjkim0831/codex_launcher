from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from free_agent.models import SessionRecord


class SessionStore:
    def __init__(self, workspace: str) -> None:
        self.root = Path(workspace) / ".free_agent" / "sessions"
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self, goal: str, workspace: str, targets: list[str]) -> SessionRecord:
        return SessionRecord(
            session_id=uuid4().hex[:12],
            goal=goal,
            workspace=workspace,
            targets=targets,
        )

    def append(self, session: SessionRecord, event: str, payload: dict[str, object]) -> None:
        path = self.root / f"{session.session_id}.jsonl"
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "session": asdict(session),
            "payload": payload,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent_summaries(self, limit: int = 3) -> list[str]:
        files = sorted(self.root.glob("*.jsonl"), key=lambda item: item.stat().st_mtime, reverse=True)
        summaries: list[str] = []
        for path in files[:limit]:
            lines = path.read_text(encoding="utf-8").splitlines()
            if not lines:
                continue
            try:
                first = json.loads(lines[0])
                last = json.loads(lines[-1])
            except json.JSONDecodeError:
                continue
            goal = first.get("session", {}).get("goal", "unknown goal")
            session_id = first.get("session", {}).get("session_id", path.stem)
            final_state = ",".join(last.get("payload", {}).get("state_history", [])) or "incomplete"
            summaries.append(f"{session_id}: {goal} [{final_state}]")
        return summaries
