# Codex Launcher Project Assembly Upgrade

## Direction

The launcher owns project operation orchestration:

- common jar build/install
- project app build
- combined common + project build
- runtime restart/verify
- backup and traffic checks
- multi-project profile selection
- **AI Agentic Graph (LAG) Integration**

Carbonet project code should connect to common behavior through stable adapters, not copied common source.

## AI Agentic Graph (LAG) Architecture

For AI-enhanced projects, the launcher supports LangGraph-based orchestration.

### Layered Structure

1.  **Client Layer**: Web UI / CLI
2.  **API Gateway**: FastAPI / Server.py
3.  **LangGraph Runtime Layer**: State machine execution
4.  **Agent Tool Layer**: Filesystem, Shell, Git, Search tools
5.  **Data / Model Layer**: Local LLM (Ollama), Vector DB (Qdrant), Postgres

### Core Agents

- **Router**: Classifies intent (research, coding, automation).
- **Planner**: Decomposes high-level goals into task lists.
- **Researcher**: Gathers context via project scanning and web search.
- **Coder**: Generates and applies patches.
- **Memory**: Manages short-term state and long-term vector storage.
- **Executor**: Orchestrates the loop between agents.

## Ownership Lanes
... (rest of the file)

- `COMMON_ONLY`: reusable jars under `modules/platform-*`, `modules/carbonet-*`, `modules/screenbuilder-core`, and common runtime adapters.
- `COMMON_DEF_PROJECT_BIND`: menus, page definitions, route manifests, authority bindings, theme bindings, install units.
- `PROJECT_ONLY`: project app module, project business services, project DB mappings, project-specific screen bindings.
- `MIXED_TRANSITION`: root `src/main/**` and legacy admin build/runtime screens until the launcher has feature parity.

## Launcher Registry

Project profiles live in:

- `config/project-assemblies.json`

Each profile declares:

- project id, label, path
- `commonAdapter`
- `adapterType`
- `appModule`
- `runtimePort`
- `healthUrl`
- `commonModules`
- `projectModules`
- command map for build, backup, traffic, restart, verify

## Migration Rule

Do not delete Carbonet admin build/runtime management screens first.

Use this order:

1. Make the launcher perform the same build/runtime/backup/traffic operations.
2. Verify launcher jobs, logs, artifact output, health, and route checks.
3. Hide or disable duplicate Carbonet admin menu entries.
4. Remove old Carbonet admin screens only after launcher parity is proven.

## Build Model

Common line:

```bash
mvn -q -DskipTests -pl <common-modules> -am install
```

Project line:

```bash
mvn -q -DskipTests -pl <project-app-module> -am package
```

Combined line:

```bash
cd frontend && npm run build
mvn -q -DskipTests package
```

## Adapter Rule

Project modules should depend on common adapters and stable contracts:

- common core internals can evolve
- project adapters stay thin
- breaking project-facing adapter changes require a new versioned contract line

