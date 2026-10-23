---
name: perf_adaptive_concurrency_governor
description: "Live Headroom Concurrency Governor (Performance, Token & Resource Optimization) — Capabilities: ram_commit_admission_control, hysteresis_scaling_enforcement, worker_slot_throttling"
family: "Performance, Token & Resource Optimization"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Live Headroom Concurrency Governor (`perf_adaptive_concurrency_governor`)

- **Family**: Performance, Token & Resource Optimization
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: ram_commit_admission_control, hysteresis_scaling_enforcement, worker_slot_throttling
- **Required Tools**: resource_snapshot, capability_profiler
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
