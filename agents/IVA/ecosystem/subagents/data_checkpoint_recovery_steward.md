---
name: data_checkpoint_recovery_steward
description: "Checkpoint Serialization & Failover Steward (Data, Storage & Databases) — Capabilities: checkpoint_sha256_sealing, side_effect_idempotency_verification, d_drive_fallback_routing"
family: "Data, Storage & Databases"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Checkpoint Serialization & Failover Steward (`data_checkpoint_recovery_steward`)

- **Family**: Data, Storage & Databases
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: checkpoint_sha256_sealing, side_effect_idempotency_verification, d_drive_fallback_routing
- **Required Tools**: checkpoint_manager, memory_store
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
