from freeagent.models import CommandResult, FilePatch, Plan, PlanStep
from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore


def test_retry_keeps_previous_patches_and_reports_verify_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")

    orch = Orchestrator(SessionStore())

    def fake_plan(goal, targets):
        return Plan(
            goal=goal,
            stack="python-backend",
            candidate_files=[],
            target_files=["app.py"],
            steps=[PlanStep("s", "d")],
            risk="medium",
            verify_plan=["pytest -q"],
        )

    calls = {"n": 0}

    def fake_patch_file(path, before, goal, resp):
        calls["n"] += 1
        if calls["n"] == 1:
            return before + "# change\n"
        return before

    def fake_build_patch(path, before, after):
        return FilePatch(path=path, before=before, after=after, diff="" if before == after else "diff")

    def fake_generate(prompt):
        return "patched", "mock"

    def fake_verify(session, commands, yes=False):
        return CommandResult(ok=False, code=1, stdout="", stderr="AssertionError: boom")

    monkeypatch.setattr(orch, "make_plan", fake_plan)
    monkeypatch.setattr("freeagent.orchestrator.patch_file", fake_patch_file)
    monkeypatch.setattr("freeagent.orchestrator.build_patch", fake_build_patch)
    monkeypatch.setattr(orch.providers, "generate", fake_generate)
    monkeypatch.setattr(orch, "_run_verify", fake_verify)

    res = orch.apply("fix it", targets=None, yes=True, auto_rollback=False, max_retries=1)
    assert not res.ok
    assert "verify failed after 2 attempt(s)" in res.summary
    assert len(res.patches) == 1
    assert "no patches applied" not in res.summary
