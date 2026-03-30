#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_CANDIDATES = [ROOT / ".venv313", ROOT / ".venv"]

def selected_venv() -> Path:
    for candidate in VENV_CANDIDATES:
        if candidate.exists():
            return candidate
    return VENV_CANDIDATES[0]

def venv_python() -> Path:
    venv = selected_venv()
    if os.name == "nt":
        return venv / "Scripts" / "python.exe"
    return venv / "bin" / "python"

def ensure_venv() -> None:
    if not venv_python().exists():
        print("[bootstrap] creating virtual environment")
        subprocess.check_call([sys.executable, "-m", "venv", str(selected_venv())])

def run_py(args: list[str]) -> int:
    py = str(venv_python())
    return subprocess.call([py, *args])

def pip_install() -> None:
    py = str(venv_python())
    subprocess.check_call([py, "-m", "pip", "install", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "-e", ".[dev]"], cwd=str(ROOT))

def bootstrap() -> None:
    ensure_venv()
    pip_install()
    run_py(["-m", "freeagent.cli", "bootstrap", "--yes"])

def main() -> int:
    ensure_venv()
    if len(sys.argv) == 1:
        bootstrap()
        return run_py(["-m", "freeagent.cli", "inspect"])
    py = str(venv_python())
    if not selected_venv().exists():
        bootstrap()
    return subprocess.call([py, "-m", "freeagent.cli", *sys.argv[1:]], cwd=str(ROOT))

if __name__ == "__main__":
    raise SystemExit(main())
