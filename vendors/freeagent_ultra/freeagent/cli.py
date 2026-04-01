from __future__ import annotations
import json
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel

from freeagent.bootstrap import bootstrap_all, ensure_env_file, load_env_file
from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore
from freeagent.tools.git_tools import git_diff, git_status
from freeagent.tools.shell_tools import run_shell
from freeagent.utils.project_scan import choose_files, summarize_project

app = typer.Typer(help="FreeAgent Ultra CLI")
console = Console()

def parse_targets(targets: str | None) -> list[str] | None:
    if not targets:
        return None
    return [x.strip() for x in targets.split(",") if x.strip()]


def build_prompt_payload(goal: str, targets: list[str] | None = None) -> dict:
    orch = Orchestrator(SessionStore())
    plan = orch.make_plan(goal, targets)
    selected_targets = targets or plan.target_files
    low_signal = not selected_targets and not plan.candidate_files
    instructions = [
        "Apply only the files that are directly relevant to the goal.",
        "Avoid generated, bundled, compiled, or deployment output files.",
        "Keep the patch minimal and explain assumptions before risky changes.",
    ]
    if low_signal:
        instructions.insert(0, "The request is too short or ambiguous to map to files safely. Clarify the desired change first.")
    prompt_lines = [
        f"Goal: {goal}",
        f"Stack: {plan.stack}",
        f"Risk: {plan.risk}",
        "Targets:",
        *([f"- {path}" for path in selected_targets] or ["- none"]),
        "Candidates:",
        *(
            [
                f"- {c.path} score={c.score} reasons={','.join(c.reasons)}"
                for c in plan.candidate_files[:6]
            ]
            or ["- none"]
        ),
        "Verify:",
        *([f"- {item}" for item in plan.verify_plan] or ["- none"]),
        "Constraints:",
        *[f"- {item}" for item in instructions],
    ]
    return {
        "goal": goal,
        "stack": plan.stack,
        "risk": plan.risk,
        "targets": selected_targets,
        "candidate_files": [{"path": c.path, "score": c.score, "reasons": c.reasons} for c in plan.candidate_files[:6]],
        "verify": plan.verify_plan,
        "instructions": instructions,
        "prompt": "\n".join(prompt_lines),
    }

@app.callback()
def _load_env():
    ensure_env_file()
    load_env_file()

@app.command()
def bootstrap(yes: bool = typer.Option(False, "--yes"), model: str = typer.Option("qwen2.5-coder:7b", "--model")):
    status = bootstrap_all(model=model, yes=yes)
    console.print(Panel(json.dumps(status, ensure_ascii=False, indent=2), title="BOOTSTRAP"))

@app.command()
def inspect():
    orch = Orchestrator(SessionStore())
    summary = orch.inspect()
    body = {
        "stack": summary.stack,
        "directories": summary.directories,
        "suggested_tests": summary.suggested_tests,
        "sample_files": list(summary.summaries)[:10],
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="INSPECT"))

@app.command()
def scan(goal: str, targets: str | None = typer.Option(None, "--targets")):
    summary, candidates = Orchestrator(SessionStore()).scan(goal, parse_targets(targets))
    body = {
        "stack": summary.stack,
        "candidates": [{"path": c.path, "score": c.score, "reasons": c.reasons} for c in candidates]
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="SCAN"))

@app.command()
def plan(goal: str, targets: str | None = typer.Option(None, "--targets")):
    orch = Orchestrator(SessionStore())
    p = orch.make_plan(goal, parse_targets(targets))
    orch.render_plan(p)


@app.command()
def prompt(goal: str, targets: str | None = typer.Option(None, "--targets")):
    payload = build_prompt_payload(goal, parse_targets(targets))
    console.print(Panel(json.dumps(payload, ensure_ascii=False, indent=2), title="PROMPT"))


@app.command()
def ask(goal: str, targets: str | None = typer.Option(None, "--targets")):
    res = Orchestrator(SessionStore()).ask(goal, parse_targets(targets))
    console.print(
        Panel(
            json.dumps(
                {
                    "answer": res.answer,
                    "provider": res.provider,
                    "details": res.details,
                },
                ensure_ascii=False,
                indent=2,
            ),
            title="ASK",
        )
    )

@app.command()
def apply(
    goal: str,
    targets: str | None = typer.Option(None, "--targets"),
    yes: bool = typer.Option(False, "--yes"),
    test_command: str | None = typer.Option(None, "--test-command"),
    max_retries: int = typer.Option(1, "--max-retries"),
    time_budget_sec: int = typer.Option(240, "--time-budget-sec"),
):
    orch = Orchestrator(SessionStore())
    res = orch.apply(
        goal,
        parse_targets(targets),
        yes=yes,
        test_command=test_command,
        max_retries=max_retries,
        time_budget_sec=time_budget_sec,
    )
    console.print(Panel(json.dumps({
        "ok": res.ok,
        "summary": res.summary,
        "session_id": res.session_id,
        "patches": [p.path for p in res.patches],
        "verify_ok": None if not res.test_result else res.test_result.ok,
    }, ensure_ascii=False, indent=2), title="APPLY"))

@app.command()
def explain(targets: str | None = typer.Option(None, "--targets"), symbol: str | None = typer.Option(None, "--symbol")):
    res = Orchestrator(SessionStore()).explain(parse_targets(targets), symbol)
    console.print(Panel(json.dumps({"path": res.path, "symbol": res.symbol, "summary": res.summary, "details": res.details}, ensure_ascii=False, indent=2), title="EXPLAIN"))

@app.command()
def diff():
    res = git_diff(".")
    console.print(Panel(res.stdout or "(no diff)", title="GIT DIFF"))
    if res.stderr:
        console.print(Panel(res.stderr, title="STDERR"))

@app.command()
def status():
    res = git_status(".")
    console.print(Panel(res.stdout or "(clean)", title="GIT STATUS"))
    if res.stderr:
        console.print(Panel(res.stderr, title="STDERR"))

@app.command()
def rollback(session_id: str):
    store = SessionStore()
    session = store.load_session(session_id)
    Orchestrator(store).rollback_session(session)
    console.print(Panel(f"rolled back session {session_id}", title="ROLLBACK"))

@app.command()
def sessions():
    root = Path(".freeagent/sessions")
    if not root.exists():
        console.print("no sessions")
        raise typer.Exit()
    names = [p.name for p in sorted(root.glob("*.json"))]
    console.print(Panel("\n".join(names) if names else "no sessions", title="SESSIONS"))

@app.command()
def doctor():
    data = Orchestrator(SessionStore()).doctor()
    console.print(Panel(json.dumps(data, ensure_ascii=False, indent=2), title="DOCTOR"))

@app.command()
def run(command: str):
    res = run_shell(command)
    console.print(Panel(res.stdout or "(no stdout)", title="STDOUT"))
    if res.stderr:
        console.print(Panel(res.stderr, title="STDERR"))
    raise typer.Exit(0 if res.ok else 1)

if __name__ == "__main__":
    app()
