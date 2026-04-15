from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore

def test_explain_target(tmp_path, monkeypatch):
    monkeypatch.setenv("FREEAGENT_PROVIDER", "mock")
    f = tmp_path / "src.py"
    f.write_text("def login_user():\n    return 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    res = Orchestrator(SessionStore()).explain(["src.py"], None)
    assert res.path == "src.py"
    assert res.summary
