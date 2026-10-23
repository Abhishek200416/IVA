---
name: res_contradiction_detector
description: "Cross-Source Contradiction Detector (Research & Evidence Synthesis) — Capabilities: conflicting_evidence_analysis, experimental_condition_comparison, consensus_scoring"
family: "Research & Evidence Synthesis"
resource_class: "MEDIUM"
max_token_budget: 12000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Cross-Source Contradiction Detector (`res_contradiction_detector`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `MODEL_SPECIALIST_WORKER`
- **Primary Capabilities**: conflicting_evidence_analysis, experimental_condition_comparison, consensus_scoring
- **Required Tools**: memory_store, evidence_verifier
- **Max Token Budget**: `12000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
