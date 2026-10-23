---
name: ops_process_tree_warden
description: "Process Tree & Orphan Reaper Warden (Terminal, Shell & OS Operations) — Capabilities: win32_process_enumeration, orphan_pid_reconciliation, protected_pid_preservation"
family: "Terminal, Shell & OS Operations"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Process Tree & Orphan Reaper Warden (`ops_process_tree_warden`)

- **Family**: Terminal, Shell & OS Operations
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: win32_process_enumeration, orphan_pid_reconciliation, protected_pid_preservation
- **Required Tools**: process_supervisor, resource_snapshot
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
