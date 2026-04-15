from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.graph.state import AgentState

def router_node(state: AgentState) -> Command:
    providers = ProviderManager()
    prompt = f"""
    You are a router for an AI agent system.
    Classify the user request into one of the following categories:
    - research: The user wants to understand the codebase, find information, or analyze something.
    - coding: The user wants to modify files, write code, or fix bugs.
    - asset: The user wants to manage, scan, or audit system assets.
    - chat: The user just wants to talk or ask a general question.

    User Input: {state["user_input"]}

    Respond with ONLY the category name (research, coding, asset, or chat).
    """

    resp, provider = providers.generate(prompt)
    route = resp.strip().lower()
    print(f"[DEBUG] Router provider response: '{route}' from {provider}")

    if any(k in route for k in ["research", "coding", "asset"]):
        return Command(goto="planner")

    return Command(goto="chat")
