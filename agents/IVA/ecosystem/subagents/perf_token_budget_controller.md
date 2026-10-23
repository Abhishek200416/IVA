---
name: perf_token_budget_controller
description: "Token Budget & Effort Tier Controller (Performance, Token & Resource Optimization) — Capabilities: call_task_campaign_budget_gating, isolated_cwd_leak_prevention, effort_tier_adaptation"
family: "Performance, Token & Resource Optimization"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Token Budget & Effort Tier Controller (`perf_token_budget_controller`)

- **Family**: Performance, Token & Resource Optimization
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: call_task_campaign_budget_gating, isolated_cwd_leak_prevention, effort_tier_adaptation
- **Required Tools**: token_economy, memory_store
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
