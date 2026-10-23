---
name: res_freshness_assessor
description: "Temporal Freshness & TTL Assessor (Research & Evidence Synthesis) — Capabilities: publication_date_verification, cache_ttl_validation, staleness_detection"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 6000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Temporal Freshness & TTL Assessor (`res_freshness_assessor`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: publication_date_verification, cache_ttl_validation, staleness_detection
- **Required Tools**: memory_store, grounded_research
- **Max Token Budget**: `6000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
