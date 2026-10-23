---
name: gov_phase_gate_reviewer
description: "Phase Gate & Acceptance Criteria Reviewer (Release, Governance & Reporting) — Capabilities: unit_integration_test_tallying, deliverable_completeness_verification, defect_remediation_signoff"
family: "Release, Governance & Reporting"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Phase Gate & Acceptance Criteria Reviewer (`gov_phase_gate_reviewer`)

- **Family**: Release, Governance & Reporting
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: unit_integration_test_tallying, deliverable_completeness_verification, defect_remediation_signoff
- **Required Tools**: evidence_verifier, task_store
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
