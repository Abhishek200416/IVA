---
name: data_sqlite_wal_architect
description: "SQLite WAL Concurrency & Schema Architect (Data, Storage & Databases) — Capabilities: sqlite_wal_pragma_tuning, transactional_migration_execution, index_selectivity_optimization"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# SQLite WAL Concurrency & Schema Architect (`data_sqlite_wal_architect`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: sqlite_wal_pragma_tuning, transactional_migration_execution, index_selectivity_optimization
- **Required Tools**: task_store, memory_store
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
