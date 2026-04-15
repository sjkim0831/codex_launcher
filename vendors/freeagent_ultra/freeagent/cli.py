from __future__ import annotations
import json
import os
from pathlib import Path
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from freeagent.bootstrap import bootstrap_all, ensure_env_file, load_env_file
from freeagent.orchestrator import Orchestrator
from freeagent.session import SessionStore
from freeagent.tools.git_tools import git_diff, git_status
from freeagent.tools.shell_tools import run_shell
from freeagent.utils.project_scan import choose_files, summarize_project

app = typer.Typer(help="FreeAgent Ultra CLI")
console = Console()


def _apply_model_override(model: str | None) -> None:
    """Override the FREEAGENT_MODEL env var if --model is given."""
    if model:
        os.environ["FREEAGENT_MODEL"] = model

def parse_targets(targets: str | None) -> list[str] | None:
    if not targets:
        return None
    return [x.strip() for x in targets.split(",") if x.strip()]


@app.callback()
def _load_env():
    ensure_env_file()
    load_env_file()

@app.command()
def bootstrap(yes: bool = typer.Option(False, "--yes"), model: str = typer.Option("qwen3.5:cloud", "--model")):
    status = bootstrap_all(model=model, yes=yes)
    console.print(Panel(json.dumps(status, ensure_ascii=False, indent=2), title="BOOTSTRAP"))

@app.command()
def inspect(model: str = typer.Option(None, "--model", help="Override model (e.g. qwen3:8b, gemma3:27b)")):
    _apply_model_override(model)
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
def scan(goal: str, targets: str | None = typer.Option(None, "--targets"), model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
    summary, candidates = Orchestrator(SessionStore()).scan(goal, parse_targets(targets))
    body = {
        "stack": summary.stack,
        "candidates": [{"path": c.path, "score": c.score, "reasons": c.reasons} for c in candidates]
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="SCAN"))

@app.command()
def plan(goal: str, targets: str | None = typer.Option(None, "--targets"), model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
    orch = Orchestrator(SessionStore())
    p = orch.make_plan(goal, parse_targets(targets))
    orch.render_plan(p)


@app.command()
def graph(goal: str, model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
    res = Orchestrator(SessionStore()).run_graph(goal)
    body = {
        "final_answer": res.final_answer,
        "details": res.details,
        "state": res.state,
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="GRAPH", border_style="green"))


@app.command()
def prompt(goal: str, targets: str | None = typer.Option(None, "--targets"), model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
    res = Orchestrator(SessionStore()).prompt(goal, parse_targets(targets))
    body = {
        "answer": res.answer or "",
        "provider": res.provider,
        "details": res.details,
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="PROMPT", border_style="green"))


@app.command()
def ask(goal: str, targets: str | None = typer.Option(None, "--targets"), model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
    res = Orchestrator(SessionStore()).ask(goal, parse_targets(targets))
    body = {
        "answer": res.answer or "",
        "provider": res.provider,
        "details": res.details,
    }
    console.print(Panel(json.dumps(body, ensure_ascii=False, indent=2), title="ASK", border_style="green"))

@app.command()
def apply(
    goal: str,
    targets: str | None = typer.Option(None, "--targets"),
    yes: bool = typer.Option(False, "--yes"),
    test_command: str | None = typer.Option(None, "--test-command"),
    max_retries: int = typer.Option(1, "--max-retries"),
    time_budget_sec: int = typer.Option(240, "--time-budget-sec"),
    model: str = typer.Option(None, "--model", help="Override model"),
):
    _apply_model_override(model)
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
def explain(targets: str | None = typer.Option(None, "--targets"), symbol: str | None = typer.Option(None, "--symbol"), model: str = typer.Option(None, "--model", help="Override model")):
    _apply_model_override(model)
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

@app.command()
def models():
    """List available models and show the active model."""
    import requests as _requests
    provider = os.getenv("FREEAGENT_PROVIDER", "ollama")
    current_model = os.getenv("FREEAGENT_MODEL", "qwen3.5:cloud")
    table = Table(title=f"FreeAgent Models (provider: {provider})")
    table.add_column("Model", style="cyan", no_wrap=True)
    table.add_column("Size", justify="right", style="green")
    table.add_column("Active", justify="center", style="bold yellow")
    if provider == "ollama":
        host = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
        try:
            r = _requests.get(f"{host}/api/tags", timeout=5)
            r.raise_for_status()
            available = r.json().get("models", [])
        except Exception as exc:
            console.print(f"[red]Failed to list Ollama models: {exc}[/red]")
            console.print(f"Current model (from env): [cyan]{current_model}[/cyan]")
            raise typer.Exit(1)
        if not available:
            console.print("[yellow]No models found in Ollama. Pull one with: ollama pull <model>[/yellow]")
            raise typer.Exit(0)
        for m in sorted(available, key=lambda x: x.get("name", "")):
            name = m.get("name", "")
            size_bytes = m.get("size", 0)
            size_label = f"{size_bytes / (1024**3):.1f} GB" if size_bytes > 0 else "-"
            is_active = "✓" if name == current_model else ""
            table.add_row(name, size_label, is_active)
    elif provider == "minimax":
        minimax_model = os.getenv("FREEAGENT_MINIMAX_MODEL", "minimax2.7")
        table.add_row(minimax_model, "-", "✓")
    else:
        table.add_row(current_model, "-", "✓")
    console.print(table)
    console.print(f"\nActive model: [bold cyan]{current_model}[/bold cyan]")
    console.print("[dim]Use --model <name> on any command to switch, or edit .env.freeagent to change default.[/dim]")

if __name__ == "__main__":
    app()
