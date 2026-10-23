---
name: desk_vm_snapshot_coordinator
description: "Sandbox VM Snapshot & Reset Coordinator (Desktop & Computer Use) — Capabilities: vm_clean_state_verification, snapshot_restore_planning, environment_readiness_reporting"
family: "Desktop & Computer Use"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Sandbox VM Snapshot & Reset Coordinator (`desk_vm_snapshot_coordinator`)

- **Family**: Desktop & Computer Use
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: vm_clean_state_verification, snapshot_restore_planning, environment_readiness_reporting
- **Required Tools**: capability_profiler, checkpoint_manager
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
