---
name: plan_mission_decomposer
description: "Mission DAG Decomposer (Planning & Architecture) — Capabilities: hierarchical_task_decomposition, wbs_generation, milestone_slicing"
family: "Planning & Architecture"
resource_class: "LIGHT"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Mission DAG Decomposer (`plan_mission_decomposer`)

- **Family**: Planning & Architecture
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: hierarchical_task_decomposition, wbs_generation, milestone_slicing
- **Required Tools**: task_store, dependency_manager
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
