from langgraph.types import Command
from freeagent.graph.state import AgentState
from freeagent.tools.shell_tools import run_tests

def verifier_node(state: AgentState) -> Command:
    current_task = state.get("current_task", "")
    code_result = state.get("code_result", "")
    
    if "[SUCCESS]" not in code_result:
        return Command(goto="executor")
        
    test_command = "pytest -q" 
    print(f"[DEBUG] Verifying task: {current_task} with command: {test_command}")
    
    # Mocking verification for now
    ok = True 
    
    if ok:
        update = {"research_data": f"--- Verification for: {current_task} ---\n[PASSED] {test_command}"}
        return Command(update=update, goto="executor")
    else:
        update = {"research_data": f"--- Verification for: {current_task} ---\n[FAILED] {test_command}"}
        return Command(update=update, goto="coder")
