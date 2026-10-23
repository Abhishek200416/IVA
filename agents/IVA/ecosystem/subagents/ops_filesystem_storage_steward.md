---
name: ops_filesystem_storage_steward
description: "Volume Space & Filesystem Integrity Steward (Terminal, Shell & OS Operations) — Capabilities: drive_free_space_monitoring, d_drive_routing_enforcement, atomic_file_rename"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Volume Space & Filesystem Integrity Steward (`ops_filesystem_storage_steward`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: drive_free_space_monitoring, d_drive_routing_enforcement, atomic_file_rename
- **Required Tools**: capability_profiler, evidence_verifier
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
