from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.utils.project_scan import summarize_project, choose_files
from freeagent.tools.file_tools import read_file
from freeagent.graph.state import AgentState
import os

def researcher_node(state: AgentState) -> Command:
    providers = ProviderManager()
    current_task = state.get("current_task", "")
    
    project_root = "/opt/projects/carbonet"
    target_path = project_root if os.path.exists(project_root) else "."
    
    # 1. Project Scan & File Selection
    summary = summarize_project(target_path)
    candidates = choose_files(current_task, root=target_path, limit=5)
    selected_paths = [c.path for c in candidates]
    
    # 2. Deep Content Analysis
    file_contents = []
    for path in selected_paths[:5]: 
        try:
            full_path = os.path.join(target_path, path) if not os.path.isabs(path) else path
            content = read_file(full_path)
            file_contents.append(f"--- File: {path} ---\n{content[:2500]}") 
        except Exception as e:
            file_contents.append(f"--- File: {path} (Error reading: {e}) ---")

    context = f"Project root: {target_path}\nStack: {summary.stack}\n\n" + "\n".join(file_contents)
    
    prompt = f"""
    You are a professional researcher for the Carbonet asset management system.
    Task: {current_task}
    
    [Source Code Context]
    {context}

    [Instruction]
    Analyze the provided source code to fulfill the task. 
    Identify which parts of the code define the asset and what might be causing inconsistency.
    Provide a detailed technical finding report with specific file references.
    """
    
    resp, provider = providers.generate(prompt)
    
    new_research = f"--- Research for: {current_task} ---\n{resp}"
    
    return Command(
        update={"research_data": new_research},
        goto="executor"
    )
