from langgraph.graph import StateGraph
from langgraph.checkpoint.memory import MemorySaver
from freeagent.graph.state import AgentState

from freeagent.graph.nodes.router import router_node
from freeagent.graph.nodes.planner import planner_node
from freeagent.graph.nodes.executor import executor_node
from freeagent.graph.nodes.researcher import researcher_node
from freeagent.graph.nodes.coder import coder_node
from freeagent.graph.nodes.memory import memory_node
from freeagent.graph.nodes.asset_manager import asset_manager_node
from freeagent.graph.nodes.verifier import verifier_node
from freeagent.graph.nodes.chat import chat_node

def build_graph():
    builder = StateGraph(AgentState)

    # 1. Add Nodes
    builder.add_node("router", router_node)
    builder.add_node("planner", planner_node)
    builder.add_node("executor", executor_node)
    builder.add_node("researcher", researcher_node)
    builder.add_node("coder", coder_node)
    builder.add_node("memory", memory_node)
    builder.add_node("asset_manager", asset_manager_node)
    builder.add_node("verifier", verifier_node)
    builder.add_node("chat", chat_node)

    # 2. Set Entry Point
    builder.set_entry_point("router")

    # 3. Add Memory Checkpointer
    memory = MemorySaver()

    return builder.compile(checkpointer=memory)
