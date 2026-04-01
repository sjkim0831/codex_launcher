from pathlib import Path

from free_agent.orchestrator.engine import AgentEngine


def test_engine_applies_deterministic_edit(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("return 500\n", encoding="utf-8")

    engine = AgentEngine(workspace=str(tmp_path), auto_approve=True)
    result = engine.run(goal="500 대신 401", targets=["service.py"], verify_commands=["echo ok"])

    assert result.execution.applied is True
    assert target.read_text(encoding="utf-8") == "return 401\n"
    assert result.verification.ok is True
