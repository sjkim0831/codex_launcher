import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR_ROOT = ROOT / "vendors" / "freeagent_ultra"
VENV_SITE_PACKAGES = VENDOR_ROOT / ".venv313" / "lib" / "python3.12" / "site-packages"

# Add repo-local package paths so the smoke test can run without shell activation.
sys.path.insert(0, str(VENDOR_ROOT))
if VENV_SITE_PACKAGES.exists():
    sys.path.insert(0, str(VENV_SITE_PACKAGES))

from freeagent.graph.builder import build_graph
from freeagent.bootstrap import load_env_file

def test_run():
    load_env_file()
    graph = build_graph()
    initial_state = {
        "user_input": "자산 관리 시스템에서 현재 가동 중인 센서 목록을 스캔하고 인벤토리에 반영해줘.",
        "task_plan": [],
        "current_task": None,
        "research_data": None,
        "code_result": None,
        "final_answer": None,
        "memory": {},
        "next": None,
        "history": [],
        "assets": [],
        "asset_audit": None,
        "inventory_result": None,
    }
    
    # Run the graph
    config = {"configurable": {"thread_id": "test-thread"}}
    for output in graph.stream(initial_state, config=config):
        for key, value in output.items():
            print(f"--- Node: {key} ---")
            print(value)
            print("-" * 20)

if __name__ == "__main__":
    test_run()
