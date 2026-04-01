from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore


def test_ask_returns_answer_and_provider(tmp_path, monkeypatch):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "SensorListPage.tsx").write_text(
        "export default function SensorListPage(){return <div>sensor</div>}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    res = Orchestrator(SessionStore()).ask("센서 목록 화면을 설계해줘")
    assert res.answer
    assert res.provider


def test_ask_guards_low_signal_question(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = Orchestrator(SessionStore()).ask("됨?")
    assert res.provider
    assert res.answer


def test_ask_allows_short_but_meaningful_question(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = Orchestrator(SessionStore()).ask("이거 지금 사용 가능해?")
    assert res.provider
    assert res.answer
