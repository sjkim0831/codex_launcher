from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.graph.state import AgentState

def chat_node(state: AgentState) -> Command:
    providers = ProviderManager()
    prompt = f"""
    You are a helpful AI assistant. Answer the user's input naturally.

    User Input: {state["user_input"]}
    """

    resp, provider = providers.generate(prompt)
    
    return Command(
        update={"final_answer": resp},
        goto="__end__"
    )
