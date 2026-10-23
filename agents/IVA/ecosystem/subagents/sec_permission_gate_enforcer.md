---
name: sec_permission_gate_enforcer
description: "Execution Permission Gate Enforcer (Security, Permissions & Safety) — Capabilities: destructive_command_interception, github_push_prevention, host_config_modification_blocking"
family: "Security, Permissions & Safety"
resource_class: "LIGHT"
max_token_budget: 8000
mainAgent: false
subagent: true
hidden: true
embedded_in: "AGI 1.7"
---

# Execution Permission Gate Enforcer (`sec_permission_gate_enforcer`)

- **Family**: Security, Permissions & Safety
- **Execution Mode**: `IN_PROCESS_TOOL_WORKER`
- **Primary Capabilities**: destructive_command_interception, github_push_prevention, host_config_modification_blocking
- **Required Tools**: evidence_verifier, capability_profiler
- **Max Token Budget**: `8000`
- **Max Wall-Clock Seconds**: `180s`

Embedded inside **AGI 1.7 — OMEGA COMMAND** (`agents/AGI_1_7/ecosystem/agent_registry/registry.json`). Automatically routed by `CapabilityRouter` and instantiated by `SpecialistFactory`.
