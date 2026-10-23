---
name: data_memory_supersession_curator
description: "Semantic Memory Supersession Curator (Data, Storage & Databases) — Capabilities: fact_conflict_supersession, historical_chain_preservation, expired_ttl_pruning"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Semantic Memory Supersession Curator (`data_memory_supersession_curator`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: fact_conflict_supersession, historical_chain_preservation, expired_ttl_pruning
- **Required Tools**: memory_store, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
