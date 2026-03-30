from __future__ import annotations
import json, time, uuid
from dataclasses import dataclass, field, asdict
import os
from pathlib import Path
from typing import Any

ROOT = Path(os.getenv("FREEAGENT_STATE_ROOT", ".freeagent"))
SESSION_DIR = ROOT / "sessions"
BACKUP_DIR = ROOT / "backups"
STATE_FILE = ROOT / "state.json"
CACHE_DIR = ROOT / "cache"

@dataclass
class Session:
    id: str
    goal: str
    created_at: float
    targets: list[str] = field(default_factory=list)
    logs: list[dict[str, Any]] = field(default_factory=list)

class SessionStore:
    def __init__(self) -> None:
        for p in (SESSION_DIR, BACKUP_DIR, CACHE_DIR):
            p.mkdir(parents=True, exist_ok=True)

    def create(self, goal: str, targets: list[str] | None = None) -> Session:
        s = Session(id=str(uuid.uuid4()), goal=goal, created_at=time.time(), targets=targets or [])
        self.save_session(s)
        self.save_state({"last_session_id": s.id})
        return s

    def save_session(self, session: Session) -> None:
        (SESSION_DIR / f"{session.id}.json").write_text(json.dumps(asdict(session), ensure_ascii=False, indent=2), encoding="utf-8")

    def load_session(self, session_id: str) -> Session:
        data = json.loads((SESSION_DIR / f"{session_id}.json").read_text(encoding="utf-8"))
        return Session(**data)

    def append_log(self, session: Session, event: str, payload: dict[str, Any]) -> None:
        session.logs.append({"ts": time.time(), "event": event, "payload": payload})
        self.save_session(session)

    def save_backup(self, path: str, content: str) -> str:
        backup_id = f"{uuid.uuid4()}.json"
        (BACKUP_DIR / backup_id).write_text(json.dumps({"path": path, "content": content}, ensure_ascii=False, indent=2), encoding="utf-8")
        return backup_id

    def load_backup(self, backup_id: str) -> dict[str, Any]:
        return json.loads((BACKUP_DIR / backup_id).read_text(encoding="utf-8"))

    def save_state(self, state: dict[str, Any]) -> None:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def load_state(self) -> dict[str, Any]:
        if not STATE_FILE.exists():
            return {}
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))

    def cache_path(self, name: str) -> Path:
        return CACHE_DIR / name
