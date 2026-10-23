---
name: qa_state_transition_fuzzer
description: "Task State Machine Transition Tester (Testing, QA & Verification) — Capabilities: illegal_transition_rejection_testing, terminal_state_immutability_check, cancel_preemption_verification"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Task State Machine Transition Tester (`qa_state_transition_fuzzer`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: illegal_transition_rejection_testing, terminal_state_immutability_check, cancel_preemption_verification
- **Required Tools**: task_store, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
