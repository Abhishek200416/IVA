---
name: res_citation_auditor
description: "Multi-Tier Citation Auditor (Research & Evidence Synthesis) — Capabilities: claim_to_source_verification, hallucination_filtering, quote_integrity_check"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Multi-Tier Citation Auditor (`res_citation_auditor`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: claim_to_source_verification, hallucination_filtering, quote_integrity_check
- **Required Tools**: grounded_research, evidence_verifier
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
