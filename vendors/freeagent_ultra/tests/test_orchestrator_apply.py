from pathlib import Path
from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore

def test_apply_and_rollback(tmp_path, monkeypatch):
    p = tmp_path / "auth.py"
    p.write_text("def login_user():\n    raise Exception('bad')\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    orch = Orchestrator(SessionStore())
    res = orch.apply("login should return 401 instead of 500", ["auth.py"], yes=True, test_command="python -c \"print('ok')\"")
    assert res.ok
    assert "401" in p.read_text(encoding="utf-8") or "HTTPException" in p.read_text(encoding="utf-8")
    sess = SessionStore().load_session(res.session_id)
    orch.rollback_session(sess)
    assert "raise Exception" in p.read_text(encoding="utf-8")
