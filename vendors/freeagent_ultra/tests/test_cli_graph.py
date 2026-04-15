from typer.testing import CliRunner

from freeagent.cli import app


runner = CliRunner()


def test_graph_command_renders_runtime_result(tmp_path, monkeypatch):
    (tmp_path / "frontend" / "src" / "features" / "sensor-list").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "features" / "sensor-list" / "SensorListMigrationPage.tsx").write_text(
        "export default function SensorListMigrationPage(){return <div/>}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FREEAGENT_PROVIDER", "mock")

    result = runner.invoke(app, ["graph", "자산 관리 시스템에서 현재 가동 중인 센서 목록을 스캔하고 인벤토리에 반영해줘."])

    assert result.exit_code == 0
    assert "GRAPH" in result.stdout
    assert '"final_answer":' in result.stdout
    assert '"state":' in result.stdout
