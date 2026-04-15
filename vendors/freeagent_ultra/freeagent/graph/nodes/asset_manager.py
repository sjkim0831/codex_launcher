from langgraph.types import Command
from freeagent.provider_manager import ProviderManager
from freeagent.graph.state import AgentState
from freeagent.tools.asset_tools import (
    scan_carbonet_assets,
    audit_asset_consistency,
    save_carbonet_inventory,
    format_asset_summary,
)

def asset_manager_node(state: AgentState) -> Command:
    providers = ProviderManager()
    current_task = state.get("current_task", "")
    
    # 1. Perform actual scan of the carbonet project
    found_assets = scan_carbonet_assets()
    
    # 2. Perform audit/consistency check
    audit_report = audit_asset_consistency(found_assets)
    inventory_result = save_carbonet_inventory(found_assets)
    
    # 3. Use LLM to analyze the findings and propose next steps
    prompt = f"""
    You are an expert asset manager for the Carbonet project.
    
    Current Task: {current_task}
    
    Asset Scan Findings:
    - Total Assets: {audit_report['total']}
    - Types: {audit_report['types']}
    - Critical Issues: {', '.join(audit_report['issues']) if audit_report['issues'] else 'None detected'}
    - Inventory Save Result: {inventory_result}
    
    Propose a concrete management plan (RESEARCH, ASSET, or CODING tasks) to resolve issues or optimize the asset inventory.
    Respond with a concise analysis and proposed sub-tasks.
    """
    
    resp, provider = providers.generate(prompt)
    asset_summary = format_asset_summary(audit_report, inventory_result)
    
    # Extract sub-tasks from response if any (e.g., RESEARCH: ..., CODING: ...)
    new_tasks = []
    for line in resp.split("\n"):
        line = line.strip()
        if any(keyword in line.upper() for keyword in ["RESEARCH:", "CODING:", "ASSET:"]):
            new_tasks.append(line)
            
    return Command(
        update={
            "assets": found_assets,
            "asset_audit": audit_report,
            "inventory_result": inventory_result,
            "research_data": f"--- Asset Audit Report ---\n{asset_summary}\n{resp}",
            "task_plan": new_tasks + state.get("task_plan", [])
        },
        goto="executor"
    )
