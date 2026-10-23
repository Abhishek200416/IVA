---
name: qa_registry_smoke_harness
description: "100-Specialist Smoke Test Harness (Testing, QA & Verification) — Capabilities: contract_instantiation_testing, verification_hook_execution, family_coverage_assertion"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# 100-Specialist Smoke Test Harness (`qa_registry_smoke_harness`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: contract_instantiation_testing, verification_hook_execution, family_coverage_assertion
- **Required Tools**: registry_validator, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
