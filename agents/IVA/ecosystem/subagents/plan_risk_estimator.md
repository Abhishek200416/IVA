---
name: plan_risk_estimator
description: "Execution Risk & Fallback Planner (Planning & Architecture) — Capabilities: failure_mode_analysis, rollback_checkpoint_planning, blast_radius_estimation"
family: "Planning & Architecture"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Execution Risk & Fallback Planner (`plan_risk_estimator`)

- **Family**: Planning & Architecture
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: failure_mode_analysis, rollback_checkpoint_planning, blast_radius_estimation
- **Required Tools**: checkpoint_manager, resource_snapshot
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
