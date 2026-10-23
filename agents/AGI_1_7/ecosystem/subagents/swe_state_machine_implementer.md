---
name: swe_state_machine_implementer
description: "Finite State Machine & Transition Guard Engineer (Software Engineering) — Capabilities: state_transition_table_enforcement, invariant_assertion_generation, idempotent_event_replay"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Finite State Machine & Transition Guard Engineer (`swe_state_machine_implementer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: state_transition_table_enforcement, invariant_assertion_generation, idempotent_event_replay
- **Required Tools**: task_store, ast_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
