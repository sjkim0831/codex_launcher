from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.graph.state import AgentState

def planner_node(state: AgentState) -> Command:
    providers = ProviderManager()
    prompt = f"""
    You are a planner for an AI agent system.
    Break down the user's request into a step-by-step task list.
    Each task should be concise and start with its type (RESEARCH, CODING, or ASSET).

    User Input: {state["user_input"]}

    Respond with ONLY the task list, one task per line.
    Example:
    RESEARCH: Find the current implementation of the authentication logic.
    ASSET: Scan for existing sensors in the carbonet-builder-observability module.
    CODING: Update the auth check to handle session timeouts.
    """

    resp, provider = providers.generate(prompt)
    tasks = [t.strip() for t in resp.split("\n") if t.strip()]

    return Command(
        update={"task_plan": tasks},
        goto="executor"
    )
