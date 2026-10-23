---
name: desk_osworld_task_inspector
description: "OSWorld-V2.1 Task Manifest Inspector (Desktop & Computer Use) — Capabilities: osworld_json_schema_parsing, evaluator_func_classification, domain_task_inventory_counting"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# OSWorld-V2.1 Task Manifest Inspector (`desk_osworld_task_inspector`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: osworld_json_schema_parsing, evaluator_func_classification, domain_task_inventory_counting
- **Required Tools**: file_reader, benchmark_auditor
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
