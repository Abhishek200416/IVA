---
name: qa_integration_scenario_verifier
description: "End-to-End Integration Scenario Verifier (Testing, QA & Verification) — Capabilities: multi_subsystem_workflow_testing, mid_run_command_injection_testing, crash_recovery_verification"
family: "Testing, QA & Verification"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# End-to-End Integration Scenario Verifier (`qa_integration_scenario_verifier`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: multi_subsystem_workflow_testing, mid_run_command_injection_testing, crash_recovery_verification
- **Required Tools**: task_store, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
