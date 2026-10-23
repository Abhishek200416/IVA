---
name: qa_unit_suite_runner
description: "Deterministic Unit Test Runner (Testing, QA & Verification) — Capabilities: unittest_assertion_execution, boundary_condition_probing, fixture_isolation_verification"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Deterministic Unit Test Runner (`qa_unit_suite_runner`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: unittest_assertion_execution, boundary_condition_probing, fixture_isolation_verification
- **Required Tools**: evidence_verifier, process_supervisor
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
