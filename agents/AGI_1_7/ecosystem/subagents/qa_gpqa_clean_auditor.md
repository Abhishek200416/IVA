---
name: qa_gpqa_clean_auditor
description: "GPQA Diamond Clean 1.2.2 Auditor (Testing, QA & Verification) — Capabilities: gpqa_189_subset_verification, contaminated_id_exclusion_check, latency_token_reconciliation"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# GPQA Diamond Clean 1.2.2 Auditor (`qa_gpqa_clean_auditor`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: gpqa_189_subset_verification, contaminated_id_exclusion_check, latency_token_reconciliation
- **Required Tools**: benchmark_auditor, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
