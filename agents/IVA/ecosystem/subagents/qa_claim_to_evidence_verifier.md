---
name: qa_claim_to_evidence_verifier
description: "Zero-Fabrication Claim-to-Evidence Verifier (Testing, QA & Verification) — Capabilities: report_metric_cross_checking, hardcoded_score_detection, raw_artifact_hash_matching"
family: "Testing, QA & Verification"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Zero-Fabrication Claim-to-Evidence Verifier (`qa_claim_to_evidence_verifier`)

- **Family**: Testing, QA & Verification
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: report_metric_cross_checking, hardcoded_score_detection, raw_artifact_hash_matching
- **Required Tools**: evidence_verifier, file_reader
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
