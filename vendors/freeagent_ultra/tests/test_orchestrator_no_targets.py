from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore


def test_apply_fails_when_no_targets_found(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    orch = Orchestrator(SessionStore())
    res = orch.apply("nonsense request", targets=None, yes=True)
    assert not res.ok
    assert "no target files detected" in res.summary

