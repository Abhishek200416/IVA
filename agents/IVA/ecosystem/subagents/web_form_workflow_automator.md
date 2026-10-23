---
name: web_form_workflow_automator
description: "Deterministic Web Form & Action Automator (Browser & Web Automation) — Capabilities: input_validation_handling, navigation_wait_condition_verification, idempotent_submission_guard"
family: "Browser & Web Automation"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Deterministic Web Form & Action Automator (`web_form_workflow_automator`)

- **Family**: Browser & Web Automation
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: input_validation_handling, navigation_wait_condition_verification, idempotent_submission_guard
- **Required Tools**: evidence_verifier, checkpoint_manager
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
