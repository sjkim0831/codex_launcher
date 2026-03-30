from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore

def test_doctor_has_python(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    data = Orchestrator(SessionStore()).doctor()
    assert "python" in data
    assert "stack" in data
