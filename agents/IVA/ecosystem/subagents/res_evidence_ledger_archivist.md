---
name: res_evidence_ledger_archivist
description: "Research Register Archivist (Research & Evidence Synthesis) — Capabilities: research_register_compilation, limitation_cataloging, requirement_traceability_linking"
family: "Research & Evidence Synthesis"
resource_class: "LIGHT"
max_token_budget: 10000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Research Register Archivist (`res_evidence_ledger_archivist`)

- **Family**: Research & Evidence Synthesis
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: research_register_compilation, limitation_cataloging, requirement_traceability_linking
- **Required Tools**: memory_store, file_writer
- **Max Token Budget**: `10000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
