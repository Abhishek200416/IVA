---
name: qa_terminal_bench_reconciler
description: "Terminal-Bench 2.0 Harbor Reconciler (Testing, QA & Verification) — Capabilities: harbor_result_json_validation, verifier_reward_verification, mock_vs_container_classification"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Terminal-Bench 2.0 Harbor Reconciler (`qa_terminal_bench_reconciler`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: harbor_result_json_validation, verifier_reward_verification, mock_vs_container_classification
- **Required Tools**: benchmark_auditor, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
