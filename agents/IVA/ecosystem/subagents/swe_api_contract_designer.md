---
name: swe_api_contract_designer
description: "REST & RPC Schema Contract Designer (Software Engineering) — Capabilities: json_schema_specification, backward_compatibility_validation, idempotency_key_design"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# REST & RPC Schema Contract Designer (`swe_api_contract_designer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: json_schema_specification, backward_compatibility_validation, idempotency_key_design
- **Required Tools**: file_reader, schema_validator
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
