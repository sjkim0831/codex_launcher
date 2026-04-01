from __future__ import annotations

import argparse
import json
from dataclasses import asdict

from free_agent.orchestrator.engine import AgentEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="free-agent-scaffold")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="run the full scaffold loop")
    run_parser.add_argument("goal")
    run_parser.add_argument("--targets", nargs="*", default=[])
    run_parser.add_argument("--verify", nargs="*", default=[])
    run_parser.add_argument("--yes", action="store_true")

    plan_parser = subparsers.add_parser("plan", help="print the generated plan")
    plan_parser.add_argument("goal")
    plan_parser.add_argument("--targets", nargs="*", default=[])
    return parser


def run_cli(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    if argv and argv[0] not in {"run", "plan", "-h", "--help"}:
        argv = ["run", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "plan":
        engine = AgentEngine()
        plan = engine.build_plan(goal=args.goal, targets=args.targets)
        print(json.dumps(asdict(plan), ensure_ascii=False, indent=2))
        return 0

    if args.command == "run":
        engine = AgentEngine(auto_approve=args.yes)
        result = engine.run(goal=args.goal, targets=args.targets, verify_commands=args.verify)
        print(result.final_report)
        return 0 if result.verification.ok else 1

    parser.print_help()
    return 1
