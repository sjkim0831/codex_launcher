from pathlib import Path

from free_agent.memory.store import SessionStore
from free_agent.orchestrator.engine import AgentEngine


def test_recent_session_summary_is_available_to_planner(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text("return 500\n", encoding="utf-8")

    engine = AgentEngine(workspace=str(tmp_path), auto_approve=True)
    first = engine.run(goal="500 대신 401", targets=["service.py"], verify_commands=["echo ok"])

    planner = AgentEngine(workspace=str(tmp_path), auto_approve=True)
    plan = planner.build_plan(goal="401 대신 403", targets=["service.py"])

    assert first.execution.applied is True
    assert any("500 대신 401" in item for item in plan.recent_sessions)
    assert any("recent session context" in item.lower() for item in plan.notes)


def test_session_store_lists_recent_summaries(tmp_path: Path) -> None:
    store = SessionStore(str(tmp_path))
    session = store.create(goal="demo goal", workspace=str(tmp_path), targets=["a.py"])
    store.append(session, "plan_created", {"candidate_files": ["a.py"]})
    store.append(session, "run_completed", {"state_history": ["idle", "done"]})

    summaries = store.recent_summaries()

    assert len(summaries) == 1
    assert "demo goal" in summaries[0]


def test_engine_prefers_symbol_scoped_edit(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text(
        "def login():\n"
        "    return 500\n\n"
        "def logout():\n"
        "    return 500\n",
        encoding="utf-8",
    )

    engine = AgentEngine(workspace=str(tmp_path), auto_approve=True)
    result = engine.run(goal="login 함수에서 500 대신 401", targets=["service.py"], verify_commands=["echo ok"])

    assert result.execution.applied is True
    assert "symbol login" in result.execution.summary
    assert target.read_text(encoding="utf-8") == (
        "def login():\n"
        "    return 401\n\n"
        "def logout():\n"
        "    return 500\n"
    )


def test_engine_can_insert_line_inside_symbol_scope(tmp_path: Path) -> None:
    target = tmp_path / "service.py"
    target.write_text(
        "def login():\n"
        "    return 500\n\n"
        "def logout():\n"
        "    return 500\n",
        encoding="utf-8",
    )

    engine = AgentEngine(workspace=str(tmp_path), auto_approve=True)
    result = engine.run(
        goal="login 함수에서 \"return 500\" 다음 줄에 \"audit()\" 추가",
        targets=["service.py"],
        verify_commands=["echo ok"],
    )

    assert result.execution.applied is True
    assert "in symbol login" in result.execution.summary
    assert target.read_text(encoding="utf-8") == (
        "def login():\n"
        "    return 500\n"
        "    audit()\n\n"
        "def logout():\n"
        "    return 500\n"
    )
