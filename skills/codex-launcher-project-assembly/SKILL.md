---
name: codex-launcher-project-assembly
description: Upgrade /opt/util/codex so it can manage multiple projects through common adapters, common jar builds, project app builds, runtime operations, backups, and traffic checks.
---

# Codex Launcher Project Assembly

Use this skill when changing the launcher project management flow or implementing AI Agentic Graph (LAG) features.

## Required Reading

- `/opt/util/codex/docs/project-assembly-upgrade.md`
- `/opt/util/codex/config/project-assemblies.json`
- `langgraph` and `langchain` documentation

## Ownership Rules

- Keep common behavior in reusable modules and common adapters.
- Keep project behavior in project app modules or thin project adapters.
- Do not copy common source into project folders as the normal reuse path.
- Do not delete existing Carbonet admin management screens until launcher parity is proven.

## Implementation Rules

### AI Agentic Graph (LAG) Patterns

When building or modifying agents:

1.  **State Definition**: Define the `AgentState` in `graph/state.py` or similar.
2.  **Node Isolation**: Each agent (Router, Planner, Coder, etc.) should be a pure function or a tool-calling node.
3.  **Edge Routing**: Use conditional edges for routing between agents.
4.  **Memory Integration**: Persist state to Postgres or Redis via LangGraph Checkpointers.
5.  **Tool Safety**: Any tool that modifies the filesystem (Coder) or runs shell commands (Executor) must follow the `safety.py` protocols.

### Project Operations

When adding a project operation:
... (rest of the file)

1. Add it to `config/project-assemblies.json` as a command or profile field.
2. Expose it through `/opt/util/codex/app/server.py`.
3. Wire the UI in `/opt/util/codex/static/index.html` and `/opt/util/codex/static/app.js`.
4. Keep execution output in the normal launcher Job flow.
5. Verify with:
   - `python3 -m py_compile /opt/util/codex/app/server.py`
   - `node --check /opt/util/codex/static/app.js`
   - JSON parsing for changed config files

## Project Profile Contract

A profile should include:

- `id`
- `label`
- `path`
- `commonAdapter`
- `adapterType`
- `appModule`
- `runtimePort`
- `healthUrl`
- `commonModules`
- `projectModules`
- `commands`

## Preferred Commands

- `buildCommon`
- `installCommon`
- `buildProject`
- `buildAll`
- `restart`
- `verify`
- `sqlBackup`
- `physicalBackup`
- `backupStatus`
- `trafficStatus`
- `trafficTail`

