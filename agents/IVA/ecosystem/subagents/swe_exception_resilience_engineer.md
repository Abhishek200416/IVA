---
name: swe_exception_resilience_engineer
description: "Fault Tolerance & Recovery Path Engineer (Software Engineering) — Capabilities: exception_hierarchy_design, exponential_backoff_implementation, graceful_degradation_guards"
family: "Software Engineering"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Fault Tolerance & Recovery Path Engineer (`swe_exception_resilience_engineer`)

- **Family**: Software Engineering
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: exception_hierarchy_design, exponential_backoff_implementation, graceful_degradation_guards
- **Required Tools**: file_reader, file_writer
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
