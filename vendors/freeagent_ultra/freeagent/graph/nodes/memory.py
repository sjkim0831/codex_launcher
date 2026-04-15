from langgraph.types import Command
from freeagent.graph.state import AgentState

def memory_node(state: AgentState) -> Command:
    # Store the results into the memory dictionary
    memory = state.get("memory", {}).copy()
        
    memory["last_execution_summary"] = {
        "research": state.get("research_data"),
        "code": state.get("code_result"),
        "user_input": state["user_input"],
        "asset_audit": state.get("asset_audit"),
        "inventory_result": state.get("inventory_result"),
    }

    asset_audit = state.get("asset_audit")
    inventory_result = state.get("inventory_result")
    code_result = state.get("code_result")
    
    if asset_audit or inventory_result:
        audit_dict = asset_audit or {}
        issues = audit_dict.get("issues") or []
        inv_res = inventory_result or "Inventory was not saved."
        final_answer = (
            f"Task completed. Scanned {audit_dict.get('total', 0)} assets. "
            f"Issues: {len(issues)}. {inv_res}"
        )
    elif code_result:
        final_answer = f"Coding task completed.\n\n{code_result}"
    else:
        final_answer = "Task completed successfully."

    return Command(
        update={
            "memory": memory,
            "final_answer": final_answer
        },
        goto="__end__"
    )
