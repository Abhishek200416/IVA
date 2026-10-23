---
name: plan_systems_architect
description: "Systems Topology Architect (Planning & Architecture) — Capabilities: architecture_specification, component_boundary_design, interface_contract_design"
family: "Planning & Architecture"
resource_class: "MEDIUM"
max_token_budget: 16000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Systems Topology Architect (`plan_systems_architect`)

- **Family**: Planning & Architecture
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: architecture_specification, component_boundary_design, interface_contract_design
- **Required Tools**: file_reader, schema_validator
- **Max Token Budget**: `16000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
