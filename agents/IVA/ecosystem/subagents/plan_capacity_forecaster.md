---
name: plan_capacity_forecaster
description: "Workload Capacity Forecaster (Planning & Architecture) — Capabilities: ram_cpu_budget_estimation, concurrency_envelope_modeling, queue_sizing"
family: "Planning & Architecture"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Workload Capacity Forecaster (`plan_capacity_forecaster`)

- **Family**: Planning & Architecture
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: ram_cpu_budget_estimation, concurrency_envelope_modeling, queue_sizing
- **Required Tools**: capability_profiler, resource_snapshot
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
