from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.graph.state import AgentState

from freeagent.patch_engine import patch_file
from freeagent.safety import protected_path
import os

def coder_node(state: AgentState) -> Command:
    providers = ProviderManager()
    current_task = state.get("current_task", "")
    research_data = state.get("research_data", "No research data available.")

    prompt = f"""
    You are an expert software engineer at Carbonet.
    Task: {current_task}
    
    [Research Data]
    {research_data}

    [Instruction]
    Based on the research findings, propose the necessary code changes.
    Output your response in the following format:
    ACTION: <brief_action_name>
    FILE: <relative_path_to_file>
    PATCH_HINT: <describe_what_to_change>
    """

    resp, provider = providers.generate(prompt)
    
    # Simple parser for the structured response
    file_to_patch = None
    for line in resp.split("\n"):
        if line.startswith("FILE:"):
            file_to_patch = line.split(":", 1)[1].strip()
            break
            
    code_result = resp
    if file_to_patch:
        if protected_path(file_to_patch):
            code_result = f"{resp}\n\n[ERROR] Path is protected: {file_to_patch}"
        else:
            # Actually apply the patch if the file exists
            full_path = f"/opt/projects/carbonet/{file_to_patch}"
            if os.path.exists(full_path):
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()
                    new_content = patch_file(file_to_patch, content, current_task, resp)
                    with open(full_path, "w", encoding="utf-8") as f:
                        f.write(new_content)
                    code_result = f"{resp}\n\n[SUCCESS] Applied patch to {file_to_patch}"
                except Exception as e:
                    code_result = f"{resp}\n\n[ERROR] Failed to patch {file_to_patch}: {e}"
            else:
                code_result = f"{resp}\n\n[ERROR] File not found: {file_to_patch}"
    
    return Command(
        update={"code_result": code_result},
        goto="verifier"
    )
