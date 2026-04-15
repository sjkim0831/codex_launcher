from typing import TypedDict, List, Dict, Any, Optional, Annotated
import operator

def merge_research_data(left: str, right: str) -> str:
    if not left:
        return right
    if not right:
        return left
    if right in left: # Avoid duplicates if node is re-run
        return left
    return f"{left}\n\n{right}"

class AgentState(TypedDict):
    user_input: str
    task_plan: List[str] # List[str] defaults to replacement in LangGraph if no reducer
    current_task: Optional[str]
    research_data: Annotated[str, merge_research_data]
    code_result: Optional[str]
    final_answer: Optional[str]
    memory: Dict[str, Any]
    history: Annotated[List[Dict[str, str]], operator.add]
    assets: Annotated[List[Dict[str, Any]], operator.add]
    asset_audit: Optional[Dict[str, Any]]
    inventory_result: Optional[str]
