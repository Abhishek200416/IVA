---
name: data_acon_context_compressor
description: "ACON Episodic Context Compressor (Data, Storage & Databases) — Capabilities: observation_anchor_extraction, token_compression_ratio_auditing, lossless_hash_error_preservation"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# ACON Episodic Context Compressor (`data_acon_context_compressor`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: observation_anchor_extraction, token_compression_ratio_auditing, lossless_hash_error_preservation
- **Required Tools**: memory_store, token_economy
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
