---
name: res_primary_source_hunter
description: "Primary Literature Retriever (Research & Evidence Synthesis) — Capabilities: arxiv_doi_lookup, primary_source_identification, bibliographic_extraction"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Primary Literature Retriever (`res_primary_source_hunter`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: arxiv_doi_lookup, primary_source_identification, bibliographic_extraction
- **Required Tools**: grounded_research, memory_store
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
