from langgraph.types import Command
from freeagent.graph.state import AgentState

def executor_node(state: AgentState) -> Command:
    if not state.get("task_plan"):
        return Command(goto="memory")

    task_plan = state["task_plan"].copy()
    current_task = task_plan.pop(0)

    # Determine next node based on task type
    next_node = "memory"
    if "RESEARCH" in current_task.upper():
        next_node = "researcher"
    elif "CODING" in current_task.upper():
        next_node = "coder"
    elif "ASSET" in current_task.upper():
        next_node = "asset_manager"

    return Command(
        update={
            "current_task": current_task,
            "task_plan": task_plan
        },
        goto=next_node
    )
