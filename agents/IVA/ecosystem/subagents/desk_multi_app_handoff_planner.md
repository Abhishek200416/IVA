---
name: desk_multi_app_handoff_planner
description: "Cross-Application Workflow Planner (Desktop & Computer Use) — Capabilities: libreoffice_gimp_chrome_handoff, file_bridge_verification, post_action_evaluator_check"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Cross-Application Workflow Planner (`desk_multi_app_handoff_planner`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: libreoffice_gimp_chrome_handoff, file_bridge_verification, post_action_evaluator_check
- **Required Tools**: task_store, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
