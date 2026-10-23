---
name: perf_tail_latency_mitigator
description: "Subprocess Tail-Latency & Straggler Mitigator (Performance, Token & Resource Optimization) — Capabilities: p95_latency_tracking, idle_timeout_preemption, staggered_worker_admission"
family: "Performance, Token & Resource Optimization"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Subprocess Tail-Latency & Straggler Mitigator (`perf_tail_latency_mitigator`)

- **Family**: Performance, Token & Resource Optimization
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: p95_latency_tracking, idle_timeout_preemption, staggered_worker_admission
- **Required Tools**: process_supervisor, resource_snapshot
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
