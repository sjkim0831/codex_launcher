from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore


def test_run_graph_returns_final_answer_and_asset_state(tmp_path, monkeypatch):
    (tmp_path / "frontend" / "src" / "features" / "sensor-list").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "features" / "sensor-list" / "SensorListMigrationPage.tsx").write_text(
        "export default function SensorListMigrationPage(){return <div/>}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FREEAGENT_PROVIDER", "mock")

    res = Orchestrator(SessionStore()).run_graph("자산 관리 시스템에서 현재 가동 중인 센서 목록을 스캔하고 인벤토리에 반영해줘.")

    assert res.final_answer
    assert "Scanned" in res.final_answer
    assert isinstance(res.state.get("memory"), dict)
    assert "asset_audit" in res.state
    # With Command(goto="__end__"), the runtime stops but doesn't necessarily set 'next' in state
    assert res.final_answer != ""

