from __future__ import annotations

import sys

from free_agent.cli.app import run_cli


def main() -> int:
    return run_cli(sys.argv[1:])
